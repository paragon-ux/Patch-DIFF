"""Typed `patchdiff-tx/1` transactions: validation, determinism, and equivalence with PDCP.

All pure-core: no database. The equivalence tests prove the typed path and the
legacy PDCP path reach the same verdict through the one shared applier.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.parser import PDCPParseError, parse_pdcp
from app.pdcp.protocol_validator import ProtocolValidationError, validate_pdcp
from app.pdcp.typed import (
    ALLOWED_TYPED_EDIT_FIELDS,
    REQUIRED_TYPED_EDIT_FIELDS,
    TYPED_EDIT_JSON_SCHEMA,
    TYPED_PROTOCOL_VERSION,
    build_record,
    canonical_record_json,
    decode_record,
    parse_typed_record,
    to_parsed_transaction,
    validate_client_request_id,
)

TARGET_ID = "11111111-1111-1111-1111-111111111111"


def record(edits, *, intent="Update text.", version=0, hash_=None):
    return build_record(
        target_file_id=TARGET_ID,
        intent=intent,
        edits=edits,
        expected_target_version=version,
        expected_current_hash=hash_,
    )


def pdcp_text(*changes: tuple[str, str, dict[str, str] | None]) -> str:
    sections = [f"PDCP 0.2.3\ntarget_file_id: {TARGET_ID}\ntarget_type: text/plain"]
    for index, (match, replace, extra) in enumerate(changes, start=1):
        fields = {
            "change_id": f"chg_{index:03d}",
            "intent": "Update text.",
            "input_state": "Old text exists.",
            "output_state": "New text exists.",
            "affected_region": "example",
            "user_visible_change": "Text changes.",
            "risk": "low",
        }
        fields.update(extra or {})
        manifest = "\n".join(f"# {key}: {value}" for key, value in fields.items())
        sections.append(f"# MANIFEST\n{manifest}\n\n<<<<<<< MATCH\n{match}\n=======\n{replace}\n>>>>>>> REPLACE")
    return "\n\n".join(sections)


def run_typed(target: str, edits):
    try:
        typed = parse_typed_record(record(edits))
    except ProtocolValidationError as exc:
        return exc.failure_reason, None
    result = apply_pdcp_transaction(target, to_parsed_transaction(typed, target_type="text/plain"))
    return _verdict(result)


def run_pdcp(target: str, *changes):
    try:
        parsed = parse_pdcp(pdcp_text(*changes))
        validate_pdcp(parsed)
    except (PDCPParseError, ProtocolValidationError) as exc:
        return exc.failure_reason, None
    return _verdict(apply_pdcp_transaction(target, parsed))


def _verdict(result):
    if isinstance(result, AcceptedCoreResult):
        return None, result.after_hash
    assert isinstance(result, RejectedCoreResult)
    return result.failure_reason, None


# --- validation -----------------------------------------------------------------


def test_minimal_typed_transaction_parses_with_default_change_ids() -> None:
    tx = parse_typed_record(record([{"match": "a", "replace": "b"}, {"match": "c", "replace": "d"}]))
    assert [e.change_id for e in tx.edits] == ["chg_001", "chg_002"]
    assert tx.intent == "Update text."


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda r: r.pop("intent"), FailureReason.MANIFEST_MISSING),
        (lambda r: r.update(intent="  "), FailureReason.MANIFEST_MISSING),
        (lambda r: r.update(intent=3), FailureReason.MANIFEST_INVALID),
        (lambda r: r.update(edits=[]), FailureReason.MANIFEST_MISSING),
        (lambda r: r.update(edits="x"), FailureReason.MANIFEST_INVALID),
        (lambda r: r.update(edits=["x"]), FailureReason.MANIFEST_INVALID),
        (lambda r: r.update(format="patchdiff-tx/2"), FailureReason.CONTEXT_INVALID),
        (lambda r: r.update(extra="x"), FailureReason.CONTEXT_INVALID),
        (lambda r: r.update(target_file_id=""), FailureReason.CONTEXT_MISSING),
        (lambda r: r.update(expected_target_version=-1), FailureReason.CONTEXT_INVALID),
        (lambda r: r.update(expected_target_version=True), FailureReason.CONTEXT_INVALID),
        (lambda r: r.update(expected_current_hash="ABC"), FailureReason.CONTEXT_INVALID),
    ],
)
def test_invalid_top_level_fields_use_existing_failure_labels(mutate, reason) -> None:
    rec = record([{"match": "a", "replace": "b"}])
    mutate(rec)
    with pytest.raises(ProtocolValidationError) as info:
        parse_typed_record(rec)
    assert info.value.failure_reason is reason


@pytest.mark.parametrize(
    ("edit", "reason"),
    [
        ({"match": "", "replace": "b"}, FailureReason.BLOCK_MALFORMED),
        ({"match": "a"}, FailureReason.BLOCK_MALFORMED),
        ({"match": "a", "replace": 1}, FailureReason.BLOCK_MALFORMED),
        ({"match": "a", "replace": "b", "risk": "extreme"}, FailureReason.MANIFEST_INVALID),
        ({"match": "a", "replace": "b", "rationale": " "}, FailureReason.MANIFEST_INVALID),
        ({"match": "a", "replace": "b", "occurrence_index": 0}, FailureReason.MANIFEST_INVALID),
        ({"match": "a", "replace": "b", "occurrence_index": "1"}, FailureReason.MANIFEST_INVALID),
        ({"match": "a", "replace": "b", "anchor_before": ""}, FailureReason.MANIFEST_INVALID),
        ({"match": "a", "replace": "b", "change_id": "bad id!"}, FailureReason.MANIFEST_INVALID),
        ({"match": "a", "replace": "b", "region_hint": "x"}, FailureReason.MANIFEST_INVALID),
    ],
)
def test_invalid_edit_fields_are_rejected(edit, reason) -> None:
    with pytest.raises(ProtocolValidationError) as info:
        parse_typed_record(record([edit]))
    assert info.value.failure_reason is reason


def test_duplicate_change_ids_rejected() -> None:
    edits = [
        {"match": "a", "replace": "b", "change_id": "x"},
        {"match": "c", "replace": "d", "change_id": "x"},
    ]
    with pytest.raises(ProtocolValidationError) as info:
        parse_typed_record(record(edits))
    assert info.value.failure_reason is FailureReason.MANIFEST_INVALID
    assert info.value.failed_change_id == "x"


def test_empty_replace_is_deletion_and_allowed() -> None:
    tx = parse_typed_record(record([{"match": "a", "replace": ""}]))
    assert tx.edits[0].replace == ""


# --- durable record --------------------------------------------------------------


def test_canonical_record_is_deterministic_and_round_trips() -> None:
    rec = record([{"replace": "é\nb", "match": "a"}], hash_="0" * 64)
    reordered = {key: rec[key] for key in reversed(list(rec))}
    text = canonical_record_json(rec)
    assert text == canonical_record_json(reordered)
    assert canonical_sha256(text) == canonical_sha256(canonical_record_json(reordered))
    assert json.loads(text)["format"] == TYPED_PROTOCOL_VERSION
    assert "é" in text  # ensure_ascii disabled: payload stays readable and byte-stable
    decoded = decode_record(text)
    assert decoded.edits[0].replace == "é\nb"
    assert decoded.expected_current_hash == "0" * 64


def test_decode_record_rejects_garbage_and_other_versions() -> None:
    with pytest.raises(ProtocolValidationError):
        decode_record("not json")
    with pytest.raises(ProtocolValidationError):
        decode_record(json.dumps({**record([{"match": "a", "replace": "b"}]), "format": "patchdiff-tx/9"}))


# --- equivalence with legacy PDCP through the shared applier ----------------------

CORPUS = [
    # (name, target, [(match, replace, disambiguation-or-None)])
    ("single", "old", [("old", "new", None)]),
    ("two_sequential", "a b c", [("a", "x", None), ("x b", "y", None)]),
    ("deletion", "keep drop keep2", [(" drop", "", None)]),
    ("multiline", "l1\nl2\nl3", [("l1\nl2", "m", None)]),
    ("absent", "abc", [("zzz", "q", None)]),
    ("ambiguous", "one one", [("one", "two", None)]),
    ("ambiguous_overlap", "aaa", [("aa", "b", None)]),
    ("index_ok", "one one", [("one", "two", {"occurrence_index": "2"})]),
    ("index_bad", "one one", [("one", "two", {"occurrence_index": "5"})]),
    ("anchor_ok", "x1 y x2 y", [("y", "z", {"anchor_before": "x2"})]),
    ("sequential_invalid", "ab", [("a", "", None), ("ab", "c", None)]),
    ("second_absent", "abc", [("a", "x", None), ("nope", "y", None)]),
]


@pytest.mark.parametrize(("name", "target", "changes"), CORPUS, ids=[c[0] for c in CORPUS])
def test_typed_and_pdcp_reach_identical_verdicts(name, target, changes) -> None:
    typed_edits = []
    for match, replace, extra in changes:
        edit = {"match": match, "replace": replace}
        for key, value in (extra or {}).items():
            edit[key] = int(value) if key == "occurrence_index" else value
        typed_edits.append(edit)

    assert run_typed(target, typed_edits) == run_pdcp(target, *changes), name


def test_ambiguity_diagnostic_reports_occurrence_count_including_overlaps() -> None:
    tx = parse_typed_record(record([{"match": "aa", "replace": "b"}]))
    result = apply_pdcp_transaction("aaa", to_parsed_transaction(tx, target_type="text/plain"))
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.MATCH_AMBIGUOUS
    assert result.diagnostic["occurrence_count"] == 2


# --- delimiter collision ----------------------------------------------------------

DELIMITED_TARGET = "intro\n=======\nbody\n"


def test_payload_containing_a_delimiter_line_is_accepted_when_typed() -> None:
    tx = parse_typed_record(record([{"match": "intro\n=======\nbody", "replace": "intro\n>>>>>>> REPLACE\nbody"}]))
    result = apply_pdcp_transaction(DELIMITED_TARGET, to_parsed_transaction(tx, target_type="text/plain"))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "intro\n>>>>>>> REPLACE\nbody\n"


def test_same_edit_cannot_be_expressed_as_pdcp_v023() -> None:
    with pytest.raises(PDCPParseError) as info:
        parse_pdcp(pdcp_text(("intro\n=======\nbody", "intro\nbody", None)))
    assert info.value.failure_reason is FailureReason.BLOCK_MALFORMED


# --- overlap fix + derived facts --------------------------------------------------


def test_overlap_probe_aa_in_aaa_without_selector_is_now_rejected_as_ambiguous() -> None:
    # Regression for matcher.py skipping overlapping candidates: this used to be
    # accepted and silently produced "ba".
    assert run_pdcp("aaa", ("aa", "b", None)) == (FailureReason.MATCH_AMBIGUOUS, None)


def test_overlap_probe_with_selector_picks_the_requested_span() -> None:
    parsed = parse_pdcp(pdcp_text(("aa", "b", {"occurrence_index": "2"})))
    result = apply_pdcp_transaction("aaa", parsed)
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "ab"


def test_legacy_runtime_mode_reproduces_old_accepted_history() -> None:
    parsed = parse_pdcp(pdcp_text(("aa", "b", None)))
    result = apply_pdcp_transaction("aaa", parsed, overlapping_matches=False)
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "ba"


def test_accepted_result_carries_runtime_derived_facts() -> None:
    tx = parse_typed_record(record([{"match": "b", "replace": "XY"}, {"match": "XYc", "replace": "Z"}]))
    result = apply_pdcp_transaction("abc", to_parsed_transaction(tx, target_type="text/plain"))
    assert isinstance(result, AcceptedCoreResult)
    first, second = result.change_facts
    assert (first["span_start"], first["span_end"]) == (1, 2)
    assert first["matched_sha256"] == canonical_sha256("b")
    assert first["replacement_chars"] == 2
    # Spans are against the progressively updated buffer ("aXYc").
    assert (second["span_start"], second["span_end"]) == (1, 4)
    assert result.target_content == "aZ"


def test_typed_edit_schema_conforms_to_runtime_contract() -> None:
    assert set(TYPED_EDIT_JSON_SCHEMA["properties"].keys()) == set(ALLOWED_TYPED_EDIT_FIELDS)
    assert set(TYPED_EDIT_JSON_SCHEMA["required"]) == set(REQUIRED_TYPED_EDIT_FIELDS)
    assert TYPED_EDIT_JSON_SCHEMA["additionalProperties"] is False


def test_null_change_id_defaults_to_indexed_chg_id() -> None:
    tx = parse_typed_record(record([{"match": "a", "replace": "b", "change_id": None}]))
    assert tx.edits[0].change_id == "chg_001"


def test_region_hint_accepted_in_pdcp_v023_but_rejected_in_typed() -> None:
    # PDCP v0.2.3 supports region_hint as an optional manifest field
    assert run_pdcp("hello world", ("hello", "hi", {"region_hint": "greeting"})) == (
        None,
        canonical_sha256("hi world"),
    )
    # Typed patchdiff-tx/1 explicitly rejects region_hint as an unknown edit field
    assert run_typed("hello world", [{"match": "hello", "replace": "hi", "region_hint": "greeting"}]) == (
        FailureReason.MANIFEST_INVALID,
        None,
    )


def test_validate_client_request_id() -> None:
    assert validate_client_request_id(None) is None
    assert validate_client_request_id("req-123_abc:01") == "req-123_abc:01"
    with pytest.raises(ProtocolValidationError):
        validate_client_request_id("   ")
    with pytest.raises(ProtocolValidationError):
        validate_client_request_id("has space")
    with pytest.raises(ProtocolValidationError):
        validate_client_request_id("x" * 129)
    with pytest.raises(ProtocolValidationError):
        validate_client_request_id(123)


def test_run_001_unhashable_risk_raises_protocol_validation_error() -> None:
    for unhashable_risk in (["low"], {"level": "low"}, (["nested"],)):
        with pytest.raises(ProtocolValidationError) as exc_info:
            parse_typed_record(record([{"match": "a", "replace": "b", "risk": unhashable_risk}]))
        assert exc_info.value.failure_reason is FailureReason.MANIFEST_INVALID


def test_mcp_002_colon_in_change_id_and_nullable_schema() -> None:
    # Colon is valid in change_id
    tx = parse_typed_record(record([{"match": "a", "replace": "b", "change_id": "part:01"}]))
    assert tx.edits[0].change_id == "part:01"

    # Schema allows string and null for change_id
    assert TYPED_EDIT_JSON_SCHEMA["properties"]["change_id"]["type"] == ["string", "null"]
    assert ":" in TYPED_EDIT_JSON_SCHEMA["properties"]["change_id"]["pattern"]

    # Schema enforces minLength: 1 for rationale, runtime rejects whitespace-only
    assert TYPED_EDIT_JSON_SCHEMA["properties"]["rationale"]["minLength"] == 1
    with pytest.raises(ProtocolValidationError) as exc1:
        parse_typed_record(record([{"match": "a", "replace": "b", "rationale": ""}]))
    assert exc1.value.failure_reason is FailureReason.MANIFEST_INVALID

    with pytest.raises(ProtocolValidationError) as exc2:
        parse_typed_record(record([{"match": "a", "replace": "b", "rationale": "   "}]))
    assert exc2.value.failure_reason is FailureReason.MANIFEST_INVALID


def test_mcp_001_schema_requires_non_null_guard() -> None:
    from jsonschema import Draft202012Validator
    from app.mcp.external_adapter import ExternalMCPAdapter

    schema = next(t["inputSchema"] for t in ExternalMCPAdapter().list_tools() if t["name"] == "patchdiff_submit_edits")
    validator = Draft202012Validator(schema)
    args = {"target_file_id": TARGET_ID, "intent": "Edit", "edits": [{"match": "a", "replace": "b"}]}
    assert not validator.is_valid(args)
    assert not validator.is_valid({**args, "expected_target_version": None})
    assert not validator.is_valid({**args, "expected_target_version": None, "expected_current_hash": None})
    assert validator.is_valid({**args, "expected_target_version": 0})
    assert validator.is_valid({**args, "expected_current_hash": "a" * 64})
    assert validator.is_valid({**args, "expected_target_version": 0, "expected_current_hash": "a" * 64})


@pytest.mark.parametrize("runtime_version", ["patchdiff-mvp-0.1.0", "patchdiff-mvp-0.2.0"])
def test_historical_decoding_retains_full_accepted_change_id(runtime_version):
    raw = canonical_record_json(record([{"match": "a", "replace": "b", "change_id": "legacy\n"}]))
    assert decode_record(raw, runtime_version=runtime_version).edits[0].change_id == "legacy\n"
    with pytest.raises(ProtocolValidationError):
        decode_record(raw)


def test_unknown_decoding_profile_rejects():
    from app.core.versions import UnsupportedRuntimeVersionError
    with pytest.raises(UnsupportedRuntimeVersionError):
        decode_record(canonical_record_json(record([{"match": "a", "replace": "b"}])), runtime_version="unknown")
