"""Pure-runtime regressions for the PR #11 friction follow-up (FR-1..FR-20)."""

import json
import random

import pytest

from app.core.advisories import MAX_WARNING_DETAILS, bounded_warnings, splits_grapheme, warning_strings
from app.core.diagnostics import exact_candidates
from app.core.failures import RETRYABLE_FAILURE_REASONS, FailureReason
from app.core.line_endings import EXPORT_FORMATS, apply_eol, export_eol, source_line_endings
from app.core.result import AcceptedCoreResult, FailureBufferContext, RejectedCoreResult
from app.core.versions import (OPERATIONS_RUNTIME_VERSION, SPAN_CONTEXT_RUNTIME_VERSION, SUPPORTED_RUNTIME_PROFILES,
                               RuntimeProfile, resolve_runtime_profile)
from app.mcp.external_adapter import ExternalMCPAdapter, _argument_error, _dumps
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.matcher import find_exact_occurrences
from app.pdcp.operations import (build_operations_record, decode_operations_record, operations_runtime_version,
                                 parse_operations_record, to_parsed_operations)
from app.pdcp.protocol_validator import ProtocolValidationError
from app.pdcp.replacement import MAX_REPLACEMENT_CHARS, replacement_size_error, replacement_size_evidence
from app.pdcp.typed import build_record, canonical_record_json, parse_typed_record, to_parsed_transaction
from app.services.near_miss_service import near_misses
from app.services.pdcp_service import _core_rejection
from app.services.read_service import line_slice
from app.services.rejection_context import available_context, response_current_context, unavailable_context
from app.core.diagnostics import near_miss_query

README = ("# Calcly\n\nCalcly is a tiny calculator.\n\nInstall Calcly from a checkout.\n\n"
          "Calcly keeps no globals. Calcly is pure. Calcly has tests.\n")


def typed(text, edits, **options):
    record = build_record(target_file_id="t", intent="Test", edits=edits, expected_target_version=0,
                          expected_current_hash=None)
    parsed = to_parsed_transaction(parse_typed_record(record), target_type="text/plain")
    return apply_pdcp_transaction(text, parsed, **options)


def span(start, end, expected_text, replace, **extra):
    return {"op": "span", "start": start, "end": end, "expected_text": expected_text, "replace": replace, **extra}


def operations(text, ops, *, context=True, **options):
    record = build_operations_record(target_file_id="t", intent="Test", operations=ops, expected_target_version=0,
                                     expected_current_hash=None)
    parsed = to_parsed_operations(parse_operations_record(record, allow_span_context=context), target_type="text/plain")
    return apply_pdcp_transaction(text, parsed, allow_span_operations=True, allow_span_context=context, **options)


def codes(result):
    return [item["code"] for item in result.warnings]


# FR-1: sequential occurrence_index basis -------------------------------------------------


def test_copied_find_occurrences_indexes_are_flagged_with_their_transaction_start_index():
    starts = [span.start for span in find_exact_occurrences(README, "Calcly")]
    assert len(starts) == 6
    result = typed(README, [{"match": "Calcly", "replace": "Numerix", "occurrence_index": index} for index in (1, 2, 3)])
    assert isinstance(result, AcceptedCoreResult)
    shifts = [item for item in result.warnings if item["code"] == "occurrence_index_basis_shift"]
    assert [(item["change_id"], item["occurrence_index"], item["transaction_start_occurrence_index"]) for item in shifts] == [
        ("chg_002", 2, 3), ("chg_003", 3, 5)]
    assert "index 3 at transaction start" in shifts[0]["detail"]


def test_sequential_indexes_that_mean_the_first_three_are_still_reported_and_single_edits_are_silent():
    renumbered = typed(README, [{"match": "Calcly", "replace": "Numerix", "occurrence_index": 1} for _ in range(3)])
    assert [item["transaction_start_occurrence_index"] for item in renumbered.warnings] == [2, 3]
    single = typed(README, [{"match": "Calcly", "replace": "Numerix", "occurrence_index": 2}])
    assert single.warnings == ()
    # Text created by an earlier edit has no transaction-start index.
    created = typed("a b", [{"match": "a", "replace": "a a"}, {"match": "a", "replace": "x", "occurrence_index": 2}])
    assert created.warnings[0]["transaction_start_occurrence_index"] is None
    assert "produced by earlier changes" in created.warnings[0]["detail"]


def test_selector_failure_detail_names_the_sequential_basis_only_after_prior_changes():
    first = typed("alpha alpha", [{"match": "alpha", "replace": "x", "occurrence_index": 3}])
    assert first.failure_detail == "occurrence_index is outside the exact occurrence list."
    later = typed("alpha alpha", [{"match": "alpha", "replace": "x", "occurrence_index": 1},
                                  {"match": "alpha", "replace": "y", "occurrence_index": 2}])
    assert later.failure_reason is FailureReason.DISAMBIGUATION_INVALID
    assert later.failure_detail.startswith("occurrence_index is outside the exact occurrence list. ")
    assert "sequential buffer after 1 earlier simulated change(s)" in later.failure_detail
    ambiguous = typed("a b b", [{"match": "a", "replace": "x"}, {"match": "b", "replace": "y"}])
    assert ambiguous.failure_reason is FailureReason.MATCH_AMBIGUOUS and "after 1 earlier" in ambiguous.failure_detail


# FR-2: span context guards and grapheme warnings -----------------------------------------


@pytest.mark.parametrize("text,position,expected", [
    ("é", 1, True), ("\U0001f468‍\U0001f4bb", 1, True), ("\U0001f468‍\U0001f4bb", 2, True),
    ("\U0001f1ef\U0001f1f5", 1, True), ("\U0001f1ef\U0001f1f5\U0001f1fa\U0001f1f8", 2, False),
    ("\U0001f1ef\U0001f1f5\U0001f1fa\U0001f1f8", 3, True), ("\U0001f44d\U0001f3fd", 1, True), ("❤️", 1, True),
    ("가", 1, True), ("각", 1, True), ("ab", 1, False), ("a\nb", 2, False), ("x", 0, False),
    ("x", 1, False),
])
def test_conservative_grapheme_boundary_check(text, position, expected):
    assert splits_grapheme(text, position) is expected


def test_insertion_inside_a_flag_is_accepted_with_a_warning_and_code_point_offset():
    text = "- Flag: \U0001f1ef\U0001f1f5 Japan\n"
    result = operations(text, [span(9, 9, "", "X")])
    assert isinstance(result, AcceptedCoreResult) and result.target_content == "- Flag: \U0001f1efX\U0001f1f5 Japan\n"
    assert result.warnings[0]["code"] == "grapheme_boundary_split"
    assert result.warnings[0]["boundary"] == "insertion" and result.warnings[0]["offset"] == 9
    clean = operations(text, [span(8, 8, "", "X")])
    assert clean.warnings == ()


def test_span_context_guards_check_exact_adjacent_text_after_canonicalization():
    text = "alpha\nbeta\ngamma\n"
    accepted = operations(text, [span(6, 6, "", "inserted\n", expected_before="alpha\r\n", expected_after="beta")])
    assert isinstance(accepted, AcceptedCoreResult) and accepted.target_content == "alpha\ninserted\nbeta\ngamma\n"
    shifted = operations(text, [span(7, 7, "", "x", expected_before="alpha\n")])
    assert shifted.failure_reason is FailureReason.SPAN_EXPECTED_TEXT_MISMATCH
    assert shifted.failure_detail.startswith("Span expected_before does not match")
    assert shifted.diagnostic["span_check"] == "expected_before" and shifted.diagnostic["actual_text"] == "lpha\nb"
    after = operations(text, [span(6, 6, "", "x", expected_after="gamma")])
    assert after.diagnostic["span_check"] == "expected_after" and after.diagnostic["actual_text"] == "beta\n"
    start = operations(text, [span(0, 0, "", "x", expected_before="z")])
    assert start.diagnostic["actual_text"] == "" and start.diagnostic["actual_chars"] == 0
    assert all(result.diagnostic["retryable"] is True for result in (shifted, after, start))


def test_span_context_is_refused_by_the_0_3_0_profile_and_runtime_selection_keeps_old_records_on_0_3_0():
    with pytest.raises(ProtocolValidationError, match="Unknown span fields"):
        parse_operations_record(build_operations_record(
            target_file_id="t", intent="x", operations=[span(0, 0, "", "x", expected_after="a")],
            expected_target_version=0, expected_current_hash=None), allow_span_context=False)
    plain = build_operations_record(target_file_id="t", intent="x", operations=[span(0, 0, "", "x")],
                                    expected_target_version=0, expected_current_hash=None)
    with_context = build_operations_record(target_file_id="t", intent="x",
                                           operations=[span(0, 0, "", "x", expected_after=None)],
                                           expected_target_version=0, expected_current_hash=None)
    assert operations_runtime_version(plain) == OPERATIONS_RUNTIME_VERSION
    assert operations_runtime_version(with_context) == SPAN_CONTEXT_RUNTIME_VERSION
    with pytest.raises(ProtocolValidationError):
        decode_operations_record(canonical_record_json(with_context), runtime_version=OPERATIONS_RUNTIME_VERSION)
    assert decode_operations_record(canonical_record_json(with_context), runtime_version=SPAN_CONTEXT_RUNTIME_VERSION)
    record = build_operations_record(target_file_id="t", intent="x", operations=[span(0, 0, "", "x", expected_after="a")],
                                     expected_target_version=0, expected_current_hash=None)
    parsed = to_parsed_operations(parse_operations_record(record), target_type="text/plain")
    refused = apply_pdcp_transaction("a", parsed, allow_span_operations=True, allow_span_context=False)
    assert refused.failure_reason is FailureReason.BLOCK_MALFORMED


def test_profiles_are_immutable_and_only_0_5_0_enables_span_context():
    assert SUPPORTED_RUNTIME_PROFILES[OPERATIONS_RUNTIME_VERSION] == RuntimeProfile(True, True, True, False, False)
    assert resolve_runtime_profile(SPAN_CONTEXT_RUNTIME_VERSION) == RuntimeProfile(True, True, True, False, True)
    assert [name for name, profile in SUPPORTED_RUNTIME_PROFILES.items() if profile.span_context] == [SPAN_CONTEXT_RUNTIME_VERSION]


@pytest.mark.parametrize("value", ["", 3, True, ["a"]])
def test_span_context_values_must_be_non_empty_strings(value):
    with pytest.raises(ProtocolValidationError, match="expected_before must be a non-empty string"):
        parse_operations_record(build_operations_record(
            target_file_id="t", intent="x", operations=[span(0, 0, "", "x", expected_before=value)],
            expected_target_version=0, expected_current_hash=None))


# FR-3: line endings ----------------------------------------------------------------------


@pytest.mark.parametrize("raw,style,counts", [
    ("a\nb\n", "lf", (2, 0, 0)), ("a\r\nb\r\n", "crlf", (0, 2, 0)), ("a\rb", "cr", (0, 0, 1)),
    ("line1\r\nline2\nline3\rline4", "mixed", (1, 1, 1)), ("no newline", "none", (0, 0, 0)), ("", "none", (0, 0, 0)),
])
def test_source_line_endings_count_before_canonicalization(raw, style, counts):
    facts = source_line_endings(raw)
    assert (facts["style"], (facts["lf"], facts["crlf"], facts["cr"])) == (style, counts)
    assert facts["normalized"] is (counts[1] + counts[2] > 0)
    assert facts["source_code_points"] == len(raw) and facts["source_utf8_bytes"] == len(raw.encode())
    assert facts == source_line_endings(raw.encode("utf-8"))


def test_export_formats_restore_uniform_styles_and_refuse_unknown_or_mixed():
    assert EXPORT_FORMATS == ("original_text", "canonical_lf", "crlf", "original_eol")
    canonical = "a\nb\n"
    for style, restored in (("crlf", "a\r\nb\r\n"), ("cr", "a\rb\r"), ("lf", canonical), ("none", canonical)):
        eol, error = export_eol("original_eol", {"style": style})
        assert error is None and apply_eol(canonical, eol) == restored
    assert export_eol("original_text", None) == ("\n", None)
    assert export_eol("crlf", None) == ("\r\n", None)
    assert export_eol("original_eol", None) == (None, "source_line_endings_unknown")
    assert export_eol("original_eol", {"style": "mixed"}) == (None, "original_eol_unrecoverable")
    assert export_eol("docx", {"style": "lf"}) == (None, "unsupported_export_format")


# FR-4/FR-5: retryable and span evidence ------------------------------------------------


def test_one_retryable_definition_covers_span_and_state_failures():
    assert RETRYABLE_FAILURE_REASONS == {
        FailureReason.MATCH_ABSENT, FailureReason.MATCH_AMBIGUOUS, FailureReason.DISAMBIGUATION_INVALID,
        FailureReason.SEQUENTIAL_MATCH_INVALID, FailureReason.SPAN_OUT_OF_BOUNDS,
        FailureReason.SPAN_EXPECTED_TEXT_MISMATCH, FailureReason.TARGET_HASH_MISMATCH,
        FailureReason.TARGET_VERSION_MISMATCH, FailureReason.TARGET_DIVERGED}
    for reason in FailureReason:
        if reason.value.startswith("replay_"):
            continue
        core = _core_rejection(reason, "x", "0" * 64, protocol_version="patchdiff-tx/2")
        assert core.diagnostic["retryable"] is (reason in RETRYABLE_FAILURE_REASONS)


def test_span_failures_report_what_is_at_the_span_in_failing_buffer_coordinates():
    text = "x" * 100
    mismatch = operations(text, [span(10, 90, "y" * 80, "z")], context=False)
    diagnostic = mismatch.diagnostic
    assert diagnostic["retryable"] is True and diagnostic["span_check"] == "expected_text"
    assert diagnostic["actual_text"] == "x" * 64 and diagnostic["actual_text_truncated"] is True
    assert (diagnostic["expected_chars"], diagnostic["actual_chars"], diagnostic["buffer_length"]) == (80, 80, 100)
    bounds = operations(text, [span(1, 2, "x", "yy"), span(150, 160, "", "x")], context=False)
    assert bounds.failure_reason is FailureReason.SPAN_OUT_OF_BOUNDS
    assert bounds.diagnostic == {**bounds.diagnostic, "retryable": True, "span_check": "bounds", "buffer_length": 101}


# FR-6/FR-7: near misses ---------------------------------------------------------------


def stored(buffer, query):
    return {"failure_context": available_context(FailureBufferContext.capture(buffer), observed_target_version=0,
                                                 observed_target_hash="f" * 64),
            "near_miss_query": near_miss_query(query)}


def test_fresh_scan_finds_typos_beyond_the_stored_prefix_and_reports_its_scope():
    buffer = "intro " * 70 + "the quick brwn fox"
    fresh = near_misses(stored(buffer, "quick brown"), caller_owned=False, buffer=buffer)
    assert fresh["scan_source"] == "failing_buffer" and fresh["candidates"][0]["text"] == "quick brwn"
    assert fresh["candidates"][0]["start"] == buffer.index("quick")
    assert fresh["scope_truncated"] is False and fresh["scanned_end"] == len(buffer) - 9
    recovered = near_misses(stored(buffer, "quick brown"), caller_owned=False)
    assert recovered["scan_source"] == "stored_failure_context" and recovered["candidates"] == []
    assert recovered["scope_truncated"] is True and recovered["truncated"] is True
    assert recovered["scanned_end"] <= 256 and "patchdiff_find_occurrences" in recovered["hint"]


def _reference(buffer, needle):
    threshold = min(4, max(1, len(needle)//4))
    ranked = []
    for width in (len(needle)-1, len(needle), len(needle)+1):
        for start in range(len(buffer)-width+1) if width > 0 else ():
            text = buffer[start:start+width]
            previous = list(range(width+1))
            for index, char in enumerate(needle, 1):
                current = [index]
                for offset, other in enumerate(text, 1):
                    current.append(min(current[-1]+1, previous[offset]+1, previous[offset-1]+(char != other)))
                previous = current
            if 0 < previous[-1] <= threshold:
                ranked.append((previous[-1], start, start+width))
    chosen = []
    for item in sorted(ranked):
        if all(item[2] <= other[1] or item[1] >= other[2] for other in chosen):
            chosen.append(item)
    return chosen


def test_bag_pruned_full_buffer_scan_equals_unpruned_reference():
    rng = random.Random(20261022)
    for _ in range(150):
        buffer = "".join(rng.choice("abcde \n") for _ in range(rng.randint(0, 400)))
        needle = "".join(rng.choice("abcde ") for _ in range(rng.randint(1, 24)))
        result = near_misses(stored(buffer, needle), caller_owned=False, buffer=buffer)
        expected = _reference(buffer, needle)
        assert [(c["distance"], c["start"], c["end"]) for c in result["candidates"]] == expected[:3]
        assert result["candidates_truncated"] is (len(expected) > 3) and result["scope_truncated"] is False


def test_budget_stop_keeps_the_exact_ranking_of_the_scanned_range(monkeypatch):
    from app.services import near_miss_service
    buffer = "abab" * 200
    monkeypatch.setattr(near_miss_service, "MAX_COMPARISON_CELLS", 400)
    result = near_misses(stored(buffer, "abac"), caller_owned=False, buffer=buffer)
    assert result["status"] == "computed" and result["scope_truncated"] is True
    assert 0 < result["scanned_end"] < len(buffer) and result["comparison_cells"] <= 400
    assert all(c["start"] < result["scanned_end"] for c in result["candidates"])
    reference = _reference(buffer[:result["scanned_end"] + 4], "abac")
    in_range = [item for item in reference if item[1] < result["scanned_end"]]
    assert [(c["distance"], c["start"], c["end"]) for c in result["candidates"]] == in_range[:3]


def test_abandoned_starts_keep_the_exact_ranking_and_cut_work():
    rng = random.Random(11)
    buffer = "".join(rng.choice("abcdefgh ") for _ in range(800))
    needle = buffer[500:520][:9] + "#" + buffer[500:520][10:]
    result = near_misses(stored(buffer, needle), caller_owned=False, buffer=buffer)
    assert [(c["distance"], c["start"], c["end"]) for c in result["candidates"]] == _reference(buffer, needle)[:3]
    assert result["candidates"][0]["start"] == 500 and result["scope_truncated"] is False
    # Without abandoning, every start evaluates about len(needle) banded rows.
    assert result["comparison_cells"] < (len(buffer) - len(needle)) * len(needle) * 9 // 3


def test_sequential_failures_name_the_consuming_change_and_suppress_near_misses():
    result = typed("# Calcly\nInstall Calcly", [{"match": "# Calcly", "replace": "# Numerix"},
                                                 {"match": "# Calcly", "replace": "# X"}])
    assert result.failure_reason is FailureReason.SEQUENTIAL_MATCH_INVALID
    assert result.failure_detail == "MATCH text was consumed by earlier change chg_001 in this transaction."
    assert result.diagnostic["original_occurrence_count"] == 1
    assert result.diagnostic["original_occurrences"] == [{"occurrence_index": 1, "start": 0, "end": 8,
                                                          "consumed_by_change_id": "chg_001",
                                                          "consumed_by_change_index": 1}]
    assert "near_miss_query" not in result.diagnostic and result.near_miss_buffer is None
    omitted = near_misses({**result.diagnostic, "near_miss_query": near_miss_query("# Calcly")}, caller_owned=False,
                          failure_reason="sequential_match_invalid")
    assert omitted["status"] == "omitted" and omitted["omission_reason"] == "sequential_match_consumed"


def test_consumed_occurrences_follow_shifts_and_insertions():
    result = typed("aa XY bb XY", [{"match": "aa", "replace": "aaaa"}, {"match": "bb XY", "replace": "c"},
                                   {"match": "XY", "replace": "z"}, {"match": "XY", "replace": "q"}])
    # chg_003 renames the first XY; chg_002 consumed the second one before that.
    assert [item["consumed_by_change_id"] for item in result.diagnostic["original_occurrences"]] == ["chg_003", "chg_002"]
    inserted = operations("abcd", [span(2, 2, "", "-"), {"op": "match", "match": "abcd", "replace": "x"}])
    assert inserted.diagnostic["original_occurrences"][0]["consumed_by_change_id"] == "chg_001"


def test_absent_rejections_keep_a_bounded_scan_buffer_only():
    big = "z" * 70000
    result = typed(big, [{"match": "missing", "replace": "x"}])
    assert len(result.near_miss_buffer) == 65536 and result.failure_buffer.text == big[:256]


# FR-8: focused failure context and elision ------------------------------------------------


def test_known_failure_locations_beyond_the_prefix_get_a_window():
    buffer = "".join(chr(97 + index % 26) for index in range(1000))
    assert FailureBufferContext.capture(buffer, 0, 100) == FailureBufferContext(buffer[:256], 1000, 0)
    window = FailureBufferContext.capture(buffer, 0, 500)
    assert (window.start, window.selection, window.text) == (372, "failure_window", buffer[372:628])
    end = FailureBufferContext.capture(buffer, 0, 1000)
    assert (end.start, len(end.text)) == (744, 256)
    context = available_context(window, observed_target_version=0, observed_target_hash="\U0001f642" * 64)
    assert context["selection"] == "failure_window" and context["start"] <= 500 < context["end"]
    assert context["text"] == buffer[context["start"]:context["end"]] and context["truncated"] is True
    assert len(json.dumps(context, ensure_ascii=True, separators=(",", ":"))) <= 4096


def test_span_and_ambiguity_failures_focus_their_location():
    text = "x" * 600 + "needle" + "y" * 100 + "needle"
    ambiguous = typed(text, [{"match": "needle", "replace": "z"}])
    assert ambiguous.failure_buffer.selection == "failure_window" and "needle" in ambiguous.failure_buffer.text
    mismatch = operations(text, [span(650, 651, "q", "z")], context=False)
    assert mismatch.failure_buffer.start <= 650 < mismatch.failure_buffer.start + 256
    assert typed(text, [{"match": "absent", "replace": "z"}]).failure_buffer.selection == "prefix"


def test_identical_current_context_is_elided_in_responses():
    context = available_context(FailureBufferContext.capture("alpha"), observed_target_version=0, observed_target_hash="f" * 64)
    elided = response_current_context(dict(context), context)
    assert elided == unavailable_context("same_as_failure_context")
    other = {**context, "observed_target_version": 1}
    assert response_current_context(other, context) == other
    missing = unavailable_context("target_not_found")
    assert response_current_context(missing, missing) == missing


# FR-17: no-op warnings and bounded envelope -----------------------------------------------


def test_no_op_changes_and_transactions_are_flagged_but_replay_collects_nothing():
    result = typed("alpha", [{"match": "alpha", "replace": "alpha"}])
    assert codes(result) == ["no_op_change", "no_op_transaction"]
    round_trip = typed("alpha", [{"match": "alpha", "replace": "beta"}, {"match": "beta", "replace": "alpha"}])
    assert codes(round_trip) == ["no_op_transaction"]
    quiet = typed("alpha", [{"match": "alpha", "replace": "alpha"}], collect_warnings=False)
    assert quiet.warnings == () and quiet.after_hash == result.after_hash


def test_warning_envelope_is_bounded_and_strings_lead_with_codes():
    details = [{"code": "no_op_change", "detail": f"chg_{index}"} for index in range(40)]
    envelope = bounded_warnings(details)
    assert len(envelope["warnings"]) == MAX_WARNING_DETAILS and envelope["warning_count"] == 40
    assert envelope["warnings_truncated"] is True
    assert warning_strings(envelope["warnings"])[0] == "no_op_change: chg_0"


# FR-18: missing numbers -----------------------------------------------------------------


def test_exact_candidates_and_replacement_limits_carry_their_numbers():
    spans = find_exact_occurrences("a " * 7, "a")
    value = exact_candidates("a " * 7, spans)
    assert value["returned_count"] == 5 and value["next_occurrence_index"] == 6
    assert exact_candidates("a", find_exact_occurrences("a", "a"))["next_occurrence_index"] is None
    crlf = "x\r\n" * 340000
    evidence = replacement_size_evidence(crlf)
    assert evidence["limit_exceeded"] == "raw_code_points" and evidence["actual"] == 1020000
    assert evidence["limit"] == MAX_REPLACEMENT_CHARS and evidence["canonical_code_points"] == 680000
    assert evidence["canonical_would_fit"] is True and replacement_size_error(crlf) == "raw_code_points"
    assert replacement_size_evidence("x" * MAX_REPLACEMENT_CHARS) is None
    wide = replacement_size_evidence("\U0001f642" * 300000)
    assert wide["limit_exceeded"] == "raw_utf8_bytes" and wide["canonical_would_fit"] is False


# FR-13: line coordinates ----------------------------------------------------------------


def test_read_lines_returns_absolute_continuation_and_optional_line_starts():
    content = "".join(f"line {index}\n" for index in range(1, 31))
    page = line_slice(content, start_line=20, end_line=24, max_chars=12, include_line_starts=True)
    range_start = content.index("line 20")
    assert page["start"] == range_start and page["next_offset"] == 12 and page["next_start"] == range_start + 12
    assert page["line_starts"] == [{"line": 20, "start": range_start}, {"line": 21, "start": range_start + 8}]
    nxt = line_slice(content, start_line=20, end_line=24, offset=page["next_offset"], max_chars=12)
    assert nxt["start"] == page["next_start"] and "line_starts" not in nxt
    final = line_slice("a\n", start_line=2, include_line_starts=True)
    assert final["line_starts"] == [{"line": 2, "start": 2}] and final["next_start"] is None
    with pytest.raises(ValueError, match="include_line_starts"):
        line_slice(content, include_line_starts="yes")


# FR-14/FR-15: wire encoding, argument errors and schemas -----------------------------


def test_tool_text_is_literal_utf8_with_safe_ascii_fallback():
    assert _dumps({"text": "\U0001f30d 中"}) == '{"text": "\U0001f30d 中"}'
    assert _dumps({"text": "\ud800"}) == '{"text": "\\ud800"}'


def test_unknown_and_missing_arguments_are_structured():
    unknown = _argument_error("patchdiff_preview", {"target_file_id": "x", "format": "patchdiff-tx/1",
                                                    "include_correlation_id": True})
    assert unknown["code"] == "unknown_argument" and unknown["unknown_arguments"] == ["include_correlation_id"]
    missing = _argument_error("patchdiff_submit_edits", {"target_file_id": "t"})
    assert missing["code"] == "missing_argument" and missing["missing_arguments"] == ["edits", "intent"]
    assert _argument_error("patchdiff_get_target", {"target_file_id": "x"}) is None
    result = ExternalMCPAdapter().call_tool("patchdiff_preview", {"target_file_id": "x", "format": "patchdiff-tx/1",
                                                                  "include_correlation_id": True})
    assert result["isError"] is True and json.loads(result["content"][0]["text"])["status"] == "invalid_argument"


def test_every_tool_parameter_is_described_and_new_schema_domains_are_advertised():
    tools = {tool["name"]: tool for tool in ExternalMCPAdapter().list_tools()}
    assert not [(name, field) for name, tool in tools.items()
                for field, schema in tool["inputSchema"]["properties"].items() if not schema.get("description")]
    assert tools["patchdiff_export_target"]["inputSchema"]["properties"]["format"]["enum"] == list(EXPORT_FORMATS)
    assert tools["patchdiff_read_lines"]["inputSchema"]["properties"]["include_line_starts"]["default"] is False
    assert tools["patchdiff_save"]["inputSchema"]["properties"]["expected_target_version"]["minimum"] == 0
    span_schema = tools["patchdiff_submit_operations"]["inputSchema"]["properties"]["operations"]["items"]["oneOf"][1]
    assert {"expected_before", "expected_after"} <= set(span_schema["properties"])
    capability = tools["patchdiff_submit_operations"]["inputSchema"]["x-patchdiff-capabilities"]["span_context"]
    assert capability == {"fields": ["expected_before", "expected_after"], "runtime_version": SPAN_CONTEXT_RUNTIME_VERSION}
    for name in ("patchdiff_submit_edits", "patchdiff_submit_operations", "patchdiff_submit_replacement"):
        assert "Requires expected_target_version and/or expected_current_hash" in tools[name]["description"]
    for name in ("patchdiff_read_target", "patchdiff_read_lines", "patchdiff_find_occurrences", "patchdiff_submit_operations"):
        assert "UTF-16" in tools[name]["description"]
    assert "not transaction start" in tools["patchdiff_submit_edits"]["inputSchema"]["properties"]["edits"]["items"][
        "properties"]["occurrence_index"]["description"]
    assert len(json.dumps({"tools": list(tools.values())}, ensure_ascii=True, separators=(",", ":"))) <= 65536


def test_rejected_core_results_keep_their_old_defaults():
    rejected = RejectedCoreResult(FailureReason.MATCH_ABSENT, "x", "0" * 64)
    assert rejected.near_miss_buffer is None and rejected.failure_buffer is None
