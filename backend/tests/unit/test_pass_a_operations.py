"""Pure operation grammar/profile and sequential exact span semantics."""
import json
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.core.versions import OPERATIONS_RUNTIME_VERSION, RUNTIME_VERSION, UnsupportedRuntimeVersionError, resolve_runtime_profile
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.operations import (OPERATION_JSON_SCHEMA, SpanEdit, build_operations_record, decode_operations_record,
                                 parse_operations_record, to_parsed_operations)
from app.pdcp.protocol_validator import ProtocolValidationError
from app.pdcp.typed import canonical_record_json, parse_typed_record


def span(start=0, end=1, expected_text="a", replace="A", **extra):
    return {"op": "span", "start": start, "end": end, "expected_text": expected_text, "replace": replace, **extra}


def record(operations):
    return build_operations_record(target_file_id="target", intent="Operation test", operations=operations,
                                   expected_target_version=0, expected_current_hash=None)


def apply(text, operations, **options):
    parsed = to_parsed_operations(parse_operations_record(record(operations)), target_type="text/plain")
    return apply_pdcp_transaction(text, parsed, allow_span_operations=True, **options)


@pytest.mark.parametrize("text,operation,expected", [
    ("a\U0001f642b", span(1, 2, "\U0001f642", "\U0001f30e"), "a\U0001f30eb"),
    ("", span(0, 0, "", "\U0001f642"), "\U0001f642"),
    ("a", span(1, 1, "", "b"), "ab"),
    ("abc", span(0, 3, "abc", ""), ""),
    ("a\nb", span(1, 2, "\r\n", "\r\nx"), "a\nxb"),
])
def test_span_unicode_insert_delete_and_canonical_expected_text(text, operation, expected):
    result = apply(text, [operation])
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == expected
    assert result.change_facts[0]["span_start"] == operation["start"]
    assert result.change_facts[0]["span_end"] == operation["end"]
    assert result.change_facts[0]["operation"] == "span"


def test_mixed_operations_use_sequential_buffer_coordinates_and_shared_facts():
    result = apply("alpha beta", [span(0, 5, "alpha", "A"), {"op": "match", "match": "beta", "replace": "B"},
                                  span(2, 3, "B", "\U0001f642")])
    assert result.target_content == "A \U0001f642"
    assert [fact["change_index"] for fact in result.change_facts] == [1, 2, 3]
    assert "operation" not in result.change_facts[1]
    overlap = apply("abcd", [span(0, 2, "ab", "X"), span(0, 2, "Xc", "Y")])
    assert overlap.target_content == "Yd"


@pytest.mark.parametrize("operation,reason", [
    (span(0, 2, "a", "x"), "span_out_of_bounds"),
    (span(0, 1, "wrong", "x"), "span_expected_text_mismatch"),
    (span(0, 0, "a", "x"), "span_expected_text_mismatch"),
])
def test_span_applicability_rejects_atomically(operation, reason):
    result = apply("a", [operation])
    assert isinstance(result, RejectedCoreResult) and result.failure_reason.value == reason
    assert result.failure_buffer.text == "a" and not hasattr(result, "change_facts")


def test_later_span_failure_captures_intermediate_buffer_without_partial_facts():
    result = apply("alpha", [span(0, 5, "alpha", "new"), span(0, 3, "old", "x")])
    assert result.failure_buffer.text == "new" and result.failure_buffer.prior_changes == 1
    assert result.failure_reason.value == "span_expected_text_mismatch"
    assert not hasattr(result, "change_facts")


@pytest.mark.parametrize("changes", [
    {"start": True}, {"start": -1}, {"start": 1.5}, {"start": None}, {"start": 2**63},
    {"end": False}, {"end": -1}, {"end": "1"}, {"end": 2**63}, {"start": 2, "end": 1},
    {"expected_text": None}, {"replace": None}, {"occurrence_index": 1}, {"anchor_before": ""},
    {"anchor_after": None}, {"match": "a"}, {"unknown": "x"}, {"op": "replace_all"}, {"op": {}},
])
def test_span_structural_and_selector_failures(changes):
    with pytest.raises(ProtocolValidationError):
        parse_operations_record(record([span(**changes)]))


@pytest.mark.parametrize("missing", ["op", "start", "end", "expected_text", "replace"])
def test_span_required_fields(missing):
    operation = span()
    del operation[missing]
    with pytest.raises(ProtocolValidationError):
        parse_operations_record(record([operation]))


def test_operations_ids_metadata_and_schema_share_existing_validation():
    for operation in (span(), {"op": "match", "match": "a", "replace": "b", "occurrence_index": 1}):
        assert Draft202012Validator(OPERATION_JSON_SCHEMA).is_valid(operation)
    assert not Draft202012Validator(OPERATION_JSON_SCHEMA).is_valid(span(start=True))
    assert not Draft202012Validator(OPERATION_JSON_SCHEMA).is_valid(span(anchor_before="a"))
    parsed = parse_operations_record(record([span(rationale="Why", risk="low"), span(0, 0, "", "x")]))
    assert isinstance(parsed.edits[0], SpanEdit) and parsed.edits[0].rationale == "Why"
    for operations in ([span(change_id="same"), span(change_id="same")],
                       [{"op": "match", "match": "", "replace": "x"}], [span(change_id="bad\n")]):
        with pytest.raises(ProtocolValidationError):
            parse_operations_record(record(operations))


def test_frozen_profile_gate_and_format_identity():
    text = canonical_record_json(record([span()]))
    assert decode_operations_record(text).edits[0].start == 0
    assert resolve_runtime_profile(OPERATIONS_RUNTIME_VERSION).span_operations is True
    assert resolve_runtime_profile(RUNTIME_VERSION).span_operations is False
    for version in ("patchdiff-mvp-0.1.0", "patchdiff-mvp-0.2.0", "patchdiff-mvp-0.2.1", RUNTIME_VERSION):
        with pytest.raises(ProtocolValidationError):
            decode_operations_record(text, runtime_version=version)
    with pytest.raises(UnsupportedRuntimeVersionError):
        decode_operations_record(text, runtime_version="future")
    with pytest.raises(ProtocolValidationError):
        parse_typed_record(json.loads(text))
    parsed = to_parsed_operations(decode_operations_record(text), target_type="text/plain")
    assert apply_pdcp_transaction("a", parsed).failure_reason.value == "block_malformed"


@pytest.mark.parametrize("selector", [{"occurrence_index": 2}, {"anchor_before": "missing"}, {"anchor_after": "missing"}])
def test_failed_singleton_selectors_expose_exact_occurrences_without_certifying_selectors(selector):
    result = apply("alpha", [{"op": "match", "match": "alpha", "replace": "x", **selector}])
    assert result.failure_reason.value == "disambiguation_invalid"
    exact = result.diagnostic["exact_candidates"]
    assert exact["occurrence_count"] == exact["returned_count"] == 1
    assert exact["candidates"][0]["start"] == 0 and exact["candidates"][0]["end"] == 5


def test_long_exact_match_preview_is_bounded_without_truncating_span():
    needle = "\U0001f642" * 65
    result = apply(needle + " " + needle, [{"op": "match", "match": needle, "replace": "x"}])
    assert result.failure_reason.value == "match_ambiguous"
    first = result.diagnostic["exact_candidates"]["candidates"][0]
    assert first["match_preview"] == needle[:64] and first["match_truncated"] is True
    assert first["end"] == 65
