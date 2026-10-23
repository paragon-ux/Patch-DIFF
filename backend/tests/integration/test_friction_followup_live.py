"""Live PostgreSQL regressions for the PR #11 friction follow-up (FR-1..FR-20)."""
import hashlib
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.core.hashing import canonical_sha256
from app.core.versions import OPERATIONS_RUNTIME_VERSION, SPAN_CONTEXT_RUNTIME_VERSION
from app.mcp import tools
from app.mcp.tools import _submit_result_to_payload
from app.services.pdcp_service import preview, submit_edits, submit_operations
from app.services.replay_service import replay_target
from app.services.save_service import save_target
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles, TargetSnapshots
from backend.tests.integration.helpers import create_target


def edits(target_id, items, version=0, **extra):
    return dict(target_file_id=target_id, intent="Friction follow-up", edits=items, expected_target_version=version, **extra)


def ops(target_id, items, version=0, **extra):
    return dict(target_file_id=target_id, intent="Friction follow-up", operations=items,
                expected_target_version=version, **extra)


def span(start, end, expected_text, replace, **extra):
    return {"op": "span", "start": start, "end": end, "expected_text": expected_text, "replace": replace, **extra}


def log_row(log_id):
    with SessionLocal() as session:
        return session.get(AppendOnlyPdcpLogs, log_id)


def counts(target_id):
    with SessionLocal() as session:
        return tuple(session.scalar(select(func.count()).select_from(model).where(model.target_file_id == target_id))
                     for model in (AppendOnlyPdcpLogs, AppendOnlyManifestLedger))


README = ("# Calcly\n\nCalcly is a tiny calculator.\n\nInstall Calcly from a checkout.\n\n"
          "Calcly keeps no globals. Calcly is pure. Calcly has tests.\n")


def test_fr1_fr17_warnings_are_persisted_recovered_and_listed():
    target_id = create_target(README)
    arguments = edits(target_id, [{"match": "Calcly", "replace": "Numerix", "occurrence_index": index} for index in (1, 2, 3)],
                      client_request_id="fr1-warn")
    with SessionLocal() as session:
        accepted = submit_edits(session, **arguments)
    assert accepted.status == "accepted" and accepted.warning_count == 2
    assert [item["code"] for item in accepted.warning_details] == ["occurrence_index_basis_shift"] * 2
    assert accepted.warnings[0].startswith("occurrence_index_basis_shift: chg_002 occurrence_index 2 selected")
    stored = log_row(accepted.pdcp_log_id).diagnostic_json
    assert stored == {"warnings": list(accepted.warning_details), "warning_count": 2, "warnings_truncated": False}
    with SessionLocal() as session:
        recovered = submit_edits(session, **arguments)
    assert recovered.deduplicated and recovered.warning_details == accepted.warning_details
    history = tools.patchdiff_get_pdcp_log(target_file_id=str(target_id), limit=1)["entries"][0]
    assert history["diagnostic"]["warning_count"] == 2
    payload = _submit_result_to_payload(accepted)
    assert payload["warnings"] == list(accepted.warnings) and payload["warning_details"] == list(accepted.warning_details)
    # A plain acceptance keeps the historical NULL diagnostic.
    with SessionLocal() as session:
        plain = submit_edits(session, **edits(target_id, [{"match": "tiny", "replace": "small"}], version=1))
    assert plain.warnings == () and log_row(plain.pdcp_log_id).diagnostic_json is None
    with SessionLocal() as session:
        noop = submit_edits(session, **edits(target_id, [{"match": "small", "replace": "small"}], version=2))
    assert [item["code"] for item in noop.warning_details] == ["no_op_change", "no_op_transaction"]
    assert noop.before_hash == noop.after_hash and noop.after_version == 3
    with SessionLocal() as session:
        assert replay_target(session, target_file_id=target_id).materialized_state_matches is True


def test_fr2_span_context_records_the_new_profile_and_replays_beside_0_3_0_history():
    target_id = create_target("alpha\nbeta\n")
    plain_args = ops(target_id, [span(0, 0, "", "# ")], client_request_id="fr2-plain")
    with SessionLocal() as session:
        plain = submit_operations(session, **plain_args)
    assert plain.status == "accepted"
    plain_row = log_row(plain.pdcp_log_id)
    assert plain_row.runtime_version == OPERATIONS_RUNTIME_VERSION
    assert "expected_before" not in plain_row.pdcp_content
    with SessionLocal() as session:
        rejected = submit_operations(session, **ops(target_id, [span(8, 8, "", "x\n", expected_before="beta")], version=1))
    assert rejected.failure_reason.value == "span_expected_text_mismatch"
    assert rejected.diagnostic["span_check"] == "expected_before" and rejected.diagnostic["retryable"] is True
    assert log_row(rejected.pdcp_log_id).runtime_version == SPAN_CONTEXT_RUNTIME_VERSION
    with SessionLocal() as session:
        accepted = submit_operations(session, **ops(target_id, [span(8, 8, "", "inserted\n", expected_before="alpha\n",
                                                                     expected_after="beta")], version=1,
                                                    parent_pdcp_log_id=str(rejected.pdcp_log_id), attempt=2))
    assert accepted.status == "accepted"
    row = log_row(accepted.pdcp_log_id)
    assert row.runtime_version == SPAN_CONTEXT_RUNTIME_VERSION and json.loads(row.pdcp_content)["operations"][0]["expected_after"] == "beta"
    with SessionLocal() as session:
        assert session.get(CloudTargetFiles, target_id).current_content == "# alpha\ninserted\nbeta\n"
        replay = replay_target(session, target_file_id=target_id)
    assert replay.status == "success" and replay.materialized_state_matches and replay.accepted_transactions_replayed == 2
    with SessionLocal() as session:
        again = submit_operations(session, **plain_args)
    assert again.deduplicated and again.pdcp_log_id == plain.pdcp_log_id


def test_fr2_grapheme_split_warning_on_a_utf16_derived_offset():
    target_id = create_target("- Flag: \U0001f1ef\U0001f1f5 Japan\n")
    with SessionLocal() as session:
        result = submit_operations(session, **ops(target_id, [span(9, 9, "", "X")]))
    assert result.status == "accepted" and result.warning_details[0]["code"] == "grapheme_boundary_split"


def test_fr3_line_endings_are_recorded_and_exports_honour_format():
    content = "first\r\nsecond\r\nthird"
    upload = tools.patchdiff_initialize_target(filename="crlf.md", content=content, content_type="text/markdown")
    assert upload["status"] == "ok"
    facts = upload["source_line_endings"]
    assert facts["style"] == "crlf" and facts["crlf"] == 2 and facts["normalized"] is True
    assert facts["source_sha256"] == hashlib.sha256(content.encode()).hexdigest() != upload["current_hash"]
    target_id = upload["target_file_id"]
    with SessionLocal() as session:
        stored = session.get(CloudTargetFiles, uuid.UUID(target_id))
        assert stored.current_content == "first\nsecond\nthird" and stored.source_line_endings == facts
    assert tools.patchdiff_get_target(target_file_id=target_id)["source_line_endings"] == facts
    original = tools.patchdiff_export_target(target_file_id=target_id, format="original_eol")
    assert original["status"] == "ok" and original["content"] == content and original["content_eol"] == "crlf"
    assert original["content_sha256"] == facts["source_sha256"] and original["hash"] == upload["current_hash"]
    default = tools.patchdiff_export_target(target_file_id=target_id)
    assert default["format"] == "original_text" and default["content"] == "first\nsecond\nthird"
    assert default["content_sha256"] == default["current_hash"]
    assert tools.patchdiff_export_target(target_file_id=target_id, format="crlf")["content"] == content
    unsupported = tools.patchdiff_export_target(target_file_id=target_id, format="docx")
    assert unsupported["status"] == "invalid_argument" and unsupported["code"] == "unsupported_export_format"
    mixed = tools.patchdiff_initialize_target(filename="mixed.txt", content="line1\r\nline2\nline3\rline4",
                                              content_type="text/plain")
    assert mixed["source_line_endings"]["style"] == "mixed"
    refusal = tools.patchdiff_export_target(target_file_id=mixed["target_file_id"], format="original_eol")
    assert refusal["status"] == "invalid_argument" and refusal["code"] == "original_eol_unrecoverable"
    # Edits keep LF storage; original_eol applies the recorded style to new lines too.
    with SessionLocal() as session:
        edited = submit_edits(session, **edits(target_id, [{"match": "third", "replace": "third\r\nfourth"}]))
    assert edited.status == "accepted"
    assert tools.patchdiff_export_target(target_file_id=target_id, format="original_eol")["content"] == content + "\r\nfourth"
    saved = tools.patchdiff_save(target_file_id=target_id, export_after_save=True)
    assert saved["export"]["status"] == "ok" and saved["export"]["format"] == "original_text"


def test_fr4_fr5_persisted_retryable_and_span_evidence():
    target_id = create_target("x" * 300)
    with SessionLocal() as session:
        mismatch = submit_operations(session, **ops(target_id, [span(280, 290, "y" * 10, "z")]))
        bounds = submit_operations(session, **ops(target_id, [span(299, 400, "", "z")]))
        stale = submit_operations(session, **ops(target_id, [span(0, 0, "", "z")], version=9))
    stored = log_row(mismatch.pdcp_log_id).diagnostic_json
    assert stored["retryable"] is True and stored["span_check"] == "expected_text"
    assert stored["actual_text"] == "x" * 10 and stored["buffer_length"] == 300
    # The failure context is a window around the span, not the document prefix.
    assert stored["failure_context"]["selection"] == "failure_window"
    assert stored["failure_context"]["start"] <= 280 < stored["failure_context"]["end"]
    assert log_row(bounds.pdcp_log_id).diagnostic_json["buffer_length"] == 300
    assert log_row(bounds.pdcp_log_id).diagnostic_json["retryable"] is True
    assert log_row(stale.pdcp_log_id).diagnostic_json["retryable"] is True


def test_fr6_fresh_near_misses_reach_beyond_256_and_recovery_reports_scope():
    content = "intro text. " * 40 + "the quick brwn fox\n"
    target_id = create_target(content)
    arguments = edits(target_id, [{"match": "quick brown", "replace": "slow"}], client_request_id="fr6")
    with SessionLocal() as session:
        first = submit_edits(session, **arguments)
    near = first.near_misses
    assert near["scan_source"] == "failing_buffer" and near["candidates"][0]["text"] == "quick brwn"
    assert near["candidates"][0]["start"] == content.index("quick") and near["scope_truncated"] is False
    with SessionLocal() as session:
        recovered = submit_edits(session, **arguments)
    assert recovered.deduplicated and recovered.near_misses["scan_source"] == "stored_failure_context"
    assert recovered.near_misses["candidates"] == [] and recovered.near_misses["scope_truncated"] is True
    assert "patchdiff_find_occurrences" in recovered.near_misses["hint"]


def test_fr7_sequential_consumption_is_explained_and_near_misses_are_suppressed():
    target_id = create_target("# Calcly\nInstall Calcly\n")
    with SessionLocal() as session:
        result = submit_edits(session, **edits(target_id, [{"match": "# Calcly", "replace": "# Numerix"},
                                                           {"match": "# Calcly", "replace": "# X"}]))
    assert result.failure_reason.value == "sequential_match_invalid"
    assert result.failure_detail == "MATCH text was consumed by earlier change chg_001 in this transaction."
    stored = log_row(result.pdcp_log_id).diagnostic_json
    assert stored["original_occurrences"][0]["consumed_by_change_id"] == "chg_001" and "near_miss_query" not in stored
    assert result.near_misses["omission_reason"] == "sequential_match_consumed"


def test_fr8_duplicate_current_context_is_elided_on_mcp_responses():
    target_id = create_target("alpha")
    with SessionLocal() as session:
        result = submit_edits(session, **edits(target_id, [{"match": "absent", "replace": "x"}]))
    assert result.current_context == result.diagnostic["failure_context"]
    payload = _submit_result_to_payload(result)
    assert payload["current_context"]["available"] is False
    assert payload["current_context"]["unavailable_reason"] == "same_as_failure_context"
    assert payload["diagnostic"]["failure_context"]["text"] == "alpha"
    # After another write the current context differs and is returned in full.
    arguments = edits(target_id, [{"match": "absent", "replace": "x"}], client_request_id="fr8")
    with SessionLocal() as session:
        keyed = submit_edits(session, **arguments)
        assert submit_edits(session, **edits(target_id, [{"match": "alpha", "replace": "beta"}])).status == "accepted"
        recovered = submit_edits(session, **arguments)
    assert keyed.status == "rejected"
    assert _submit_result_to_payload(recovered)["current_context"]["text"] == "beta"


def test_fr9_accepted_and_deduplicated_responses_name_current_state():
    target_id = create_target("alpha")
    arguments = edits(target_id, [{"match": "alpha", "replace": "beta"}], client_request_id="fr9")
    with SessionLocal() as session:
        first = _submit_result_to_payload(submit_edits(session, **arguments))
        later = submit_edits(session, **edits(target_id, [{"match": "beta", "replace": "gamma"}], version=1))
        again = _submit_result_to_payload(submit_edits(session, **arguments))
    assert (first["version"], first["current_version"], first["current_hash"]) == (1, 1, first["after_hash"])
    assert again["deduplicated"] is True and again["version"] == 1
    assert (again["current_version"], again["current_hash"]) == (2, later.after_hash)


def test_fr10_key_conflicts_and_invalid_keys_carry_codes_and_differences():
    target_id = create_target("alpha")
    arguments = edits(target_id, [{"match": "absent", "replace": "x"}], client_request_id="fr10")
    with SessionLocal() as session:
        original = submit_edits(session, **arguments)
        nulled = submit_edits(session, **{**arguments, "edits": [{"match": "absent", "replace": "x", "rationale": None}]})
        guards = submit_edits(session, **{**arguments, "expected_target_version": None,
                                          "expected_current_hash": canonical_sha256("alpha")})
        spaced = submit_edits(session, **{**arguments, "client_request_id": "has space"})
    assert nulled.failure_reason.value == "context_invalid"
    assert nulled.diagnostic["code"] == "request_key_conflict"
    assert nulled.diagnostic["existing_pdcp_log_id"] == str(original.pdcp_log_id)
    assert nulled.diagnostic["differing_components"] == ["pdcp_content_hash"]
    assert nulled.diagnostic["differing_fields"] == ["edits[0].rationale"]
    assert log_row(nulled.pdcp_log_id).diagnostic_json["differing_fields"] == ["edits[0].rationale"]
    assert set(guards.diagnostic["differing_components"]) == {"pdcp_content_hash", "expected_target_version",
                                                              "expected_current_hash"}
    assert set(guards.diagnostic["differing_fields"]) == {"expected_current_hash", "expected_target_version"}
    assert spaced.failure_reason.value == "context_invalid" and spaced.diagnostic["code"] == "invalid_client_request_id"


def test_fr11_ledger_and_attempt_rows_join_through_mcp():
    target_id = create_target("alpha beta")
    with SessionLocal() as session:
        rejected = submit_edits(session, **edits(target_id, [{"match": "absent", "replace": "x"}]))
        accepted = submit_edits(session, **edits(target_id, [
            {"match": "alpha", "replace": "ALPHA", "rationale": "Shout the first word."},
            {"match": "beta", "replace": "BETA"}], parent_pdcp_log_id=str(rejected.pdcp_log_id), attempt=2))
        save_target(session, target_file_id=target_id)
    active = tools.patchdiff_get_manifest_ledger(target_file_id=str(target_id))
    assert active["entries"] == []
    ledger = tools.patchdiff_get_manifest_ledger(target_file_id=str(target_id), include_previous_cycles=True)["entries"]
    accepted_row = log_row(accepted.pdcp_log_id)
    assert [entry["change_index"] for entry in ledger] == [1, 2]
    for entry in ledger:
        assert entry["pdcp_log_id"] == str(accepted.pdcp_log_id) and entry["log_sequence"] == accepted_row.log_sequence
        assert (entry["before_version"], entry["after_version"]) == (0, 1)
        assert entry["transaction_intent"] == "Friction follow-up"
        assert entry["editing_cycle_id"] == str(accepted_row.editing_cycle_id)
    assert ledger[0]["intent"] == ledger[0]["rationale"] == "Shout the first word."
    assert ledger[1]["intent"] == "Friction follow-up" and ledger[1]["rationale"] is None
    attempts = tools.patchdiff_get_pdcp_log(target_file_id=str(target_id))["entries"]
    assert attempts[0]["attempt"] == attempts[0]["regeneration_attempt"] == 2
    assert all(entry["intent"] == "Friction follow-up" and entry["intent_truncated"] is False for entry in attempts)


def test_fr12_include_content_pages_have_a_byte_budget_and_rows_stay_fetchable():
    target_id = create_target("seed")
    big = "x" * 700_000
    with SessionLocal() as session:
        for version, value in enumerate((big, big + "y")):
            arguments = {**ops(target_id, [span(0, 0, "", value[:10])], version=version), "intent": value}
            assert submit_operations(session, **arguments).status == "accepted"
    page = tools.patchdiff_get_pdcp_log(target_file_id=str(target_id), include_content=True)["entries"]
    assert page[0]["pdcp_content"] is not None and page[1]["pdcp_content"] is None
    assert page[1]["pdcp_content_omitted"] == "page_byte_budget"
    assert page[0]["intent_truncated"] is True and len(page[0]["intent"]) == 256
    single = tools.patchdiff_get_pdcp_log(target_file_id=str(target_id), include_content=True, limit=1,
                                          before_sequence=page[0]["log_sequence"])["entries"][0]
    assert single["pdcp_log_id"] == page[1]["pdcp_log_id"] and json.loads(single["pdcp_content"])["intent"] == big


def test_fr13_read_lines_tool_absolute_continuation():
    content = "".join(f"line {index}\n" for index in range(1, 31))
    target_id = create_target(content)
    page = tools.patchdiff_read_lines(target_file_id=str(target_id), start_line=25, end_line=25, include_line_starts=True)
    assert page["line_starts"] == [{"line": 25, "start": content.index("line 25")}] and page["next_start"] is None
    paged = tools.patchdiff_read_lines(target_file_id=str(target_id), start_line=20, end_line=24, max_chars=12)
    assert paged["next_offset"] == 12 and paged["next_start"] == paged["end"]
    resumed = tools.patchdiff_read_target(target_file_id=str(target_id), start=paged["next_start"], length=5)
    assert resumed["text"] == content[paged["end"]:paged["end"] + 5]
    invalid = tools.patchdiff_read_lines(target_file_id=str(target_id), include_line_starts="yes")
    assert invalid["status"] == "invalid_argument"


def test_fr14_status_ok_and_shared_invalid_argument_envelope():
    target_id = create_target("alpha")
    assert tools.patchdiff_get_target(target_file_id=str(target_id))["status"] == "ok"
    assert tools.patchdiff_export_target(target_file_id=str(target_id))["status"] == "ok"
    bad_preview = tools.patchdiff_preview(target_file_id=str(target_id), format="nope", intent="x")
    assert bad_preview["code"] == "invalid_format" and bad_preview["failure_detail"] == bad_preview["detail"]
    bad_flag = tools.patchdiff_submit_edits(**edits(str(target_id), [{"match": "alpha", "replace": "b"}]),
                                            include_correlation_id="true")
    assert bad_flag["status"] == "invalid_argument" and bad_flag["code"] == "invalid_include_correlation_id"
    assert counts(target_id) == (0, 0)


def test_fr18_replacement_and_candidate_numbers_through_tools():
    target_id = create_target("a " * 7)
    too_large = tools.patchdiff_submit_replacement(target_file_id=str(target_id), intent="Replace",
                                                   replacement="x\r\n" * 340000, expected_target_version=0)
    assert too_large["status"] == "invalid_argument" and too_large["code"] == "replacement_too_large"
    assert too_large["diagnostic"]["actual"] == 1020000 and too_large["diagnostic"]["canonical_would_fit"] is True
    ambiguous = tools.patchdiff_submit_edits(**edits(str(target_id), [{"match": "a", "replace": "b"}]))
    candidates = ambiguous["diagnostic"]["exact_candidates"]
    assert candidates["returned_count"] == 5 and candidates["next_occurrence_index"] == 6
    found = tools.patchdiff_find_occurrences(target_file_id=str(target_id), text="a",
                                             start_occurrence=candidates["next_occurrence_index"])
    assert [item["occurrence_index"] for item in found["occurrences"]] == [6, 7]
    assert counts(target_id) == (1, 0)


def test_fr19_preview_returns_near_misses_and_warnings_without_writes():
    target_id = create_target("the quick brwn fox")
    with SessionLocal() as session:
        absent = preview(session, target_file_id=target_id, format="patchdiff-tx/1", intent="x",
                         edits=[{"match": "quick brown", "replace": "slow"}], expected_target_version=0)
        noop = preview(session, target_file_id=target_id, format="patchdiff-tx/1", intent="x",
                       edits=[{"match": "fox", "replace": "fox"}], expected_target_version=0)
    assert absent["near_misses"]["candidates"][0]["text"] == "quick brwn"
    assert absent["current_context"]["unavailable_reason"] == "same_as_failure_context"
    assert noop["warnings"][0].startswith("no_op_change") and noop["warning_count"] == 2
    assert counts(target_id) == (0, 0)


def test_fr20_save_accepts_a_version_guard():
    target_id = create_target("alpha")
    with SessionLocal() as session:
        assert submit_edits(session, **edits(target_id, [{"match": "alpha", "replace": "beta"}])).status == "accepted"
    stale = tools.patchdiff_save(target_file_id=str(target_id), expected_target_version=0)
    assert stale["status"] == "rejected" and stale["failure_reason"] == "target_version_mismatch"
    invalid = tools.patchdiff_save(target_file_id=str(target_id), expected_target_version=True)
    assert invalid["status"] == "rejected" and invalid["failure_reason"] == "context_invalid"
    mismatched_hash = tools.patchdiff_save(target_file_id=str(target_id), expected_target_version=1,
                                           expected_current_hash="0" * 64)
    assert mismatched_hash["failure_reason"] == "target_hash_mismatch"
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(TargetSnapshots).where(
            TargetSnapshots.target_file_id == target_id)) == 1
    saved = tools.patchdiff_save(target_file_id=str(target_id), expected_target_version=1,
                                 expected_current_hash=canonical_sha256("beta"))
    assert saved["status"] == "saved" and saved["version"] == 1
