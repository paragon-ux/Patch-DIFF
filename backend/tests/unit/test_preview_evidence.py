"""Actual JSON budgets, whole-prefix facts and unchanged preview verdicts."""
import copy
import uuid

import pytest

from app.services.preview_evidence import (
    MAX_DIAGNOSTIC_BYTES, MAX_FACT_BYTES, MAX_FACTS_BYTES, MAX_PREVIEW_BYTES, bound_preview, json_bytes,
)

TARGET = "11111111-1111-1111-1111-111111111111"


def payload(status="accepted", **extra):
    return {"preview": True, "advisory": True, "status": status, "target_file_id": TARGET,
            "validation_stage": "accepted" if status == "accepted" else "protocol_validation",
            "validity": {"protocol_valid": status == "accepted", "transaction_valid": status == "accepted",
                         "task_correct": "not_evaluated", "semantic": "not_evaluated"},
            "current_hash": "a" * 64, "before_hash": "a" * 64, "current_version": 7, "before_version": 7,
            "after_hash": "b" * 64 if status == "accepted" else None, **extra}


def fact(index=1, change_id=None):
    return {"change_id": change_id or f"chg_{index:03d}", "change_index": index,
            "span_start": 0, "span_end": 1, "matched_chars": 1, "replacement_chars": 1,
            "matched_sha256": "a" * 64, "replacement_sha256": "b" * 64}


def test_small_facts_keep_exact_values_and_original_payload_unmodified():
    original = payload(change_facts=[fact(1), fact(2)])
    saved = copy.deepcopy(original)
    result = bound_preview(original)
    assert original == saved and result["change_facts"] == original["change_facts"]
    assert result["total_change_count"] == result["returned_fact_count"] == 2
    assert result["change_facts_truncated"] is False and result["change_facts_omission_reason"] is None
    assert "evidence_omissions" not in result and json_bytes(result) <= MAX_PREVIEW_BYTES


def test_many_facts_return_first_32_complete_facts_and_explicit_total():
    facts = [fact(index) for index in range(1, 101)]
    result = bound_preview(payload(change_facts=facts))
    assert result["change_facts"] == facts[:32]
    assert result["total_change_count"] == 100 and result["returned_fact_count"] == 32
    assert result["change_facts_truncated"] and result["change_facts_omission_reason"] == "fact_count_limit"
    assert json_bytes({"change_facts": result["change_facts"]}) <= MAX_FACTS_BYTES
    assert json_bytes(result) <= MAX_PREVIEW_BYTES


def test_first_oversized_fact_stops_prefix_without_truncating_id_or_skipping_to_later_facts():
    facts = [fact(1), fact(2, "\U0001f31f" * 300), fact(3)]
    result = bound_preview(payload(change_facts=facts))
    assert json_bytes(facts[1]) > MAX_FACT_BYTES
    assert result["change_facts"] == facts[:1] and result["returned_fact_count"] == 1
    assert result["total_change_count"] == 3 and result["change_facts_omission_reason"] == "fact_byte_limit"
    assert facts[1]["change_id"] == "\U0001f31f" * 300


def test_fact_and_facts_wrapper_byte_boundaries_are_inclusive():
    at_limit = fact(change_id="x")
    at_limit["change_id"] += "x" * (MAX_FACT_BYTES - json_bytes(at_limit))
    assert json_bytes(at_limit) == MAX_FACT_BYTES
    assert bound_preview(payload(change_facts=[at_limit]))["returned_fact_count"] == 1
    too_large = {**at_limit, "change_id": at_limit["change_id"] + "x"}
    rejected_fact = bound_preview(payload(change_facts=[too_large]))
    assert rejected_fact["returned_fact_count"] == 0 and rejected_fact["change_facts_omission_reason"] == "fact_byte_limit"
    result = bound_preview(payload(change_facts=[at_limit] * 8))
    assert result["returned_fact_count"] == 7 and result["change_facts_omission_reason"] == "facts_byte_limit"
    assert json_bytes({"change_facts": result["change_facts"]}) <= MAX_FACTS_BYTES


@pytest.mark.parametrize("field", ["failure_detail", "failed_change_id", "target_file_id"])
@pytest.mark.parametrize("value,reason", [("x" * 1024, None), ("x" * 1025, "code_points_limit"),
    ("\U0001f31f" * 600, None), ("\U0001f31f" * 700, "field_byte_limit")],
    ids=["chars-equal", "chars-over", "escaped-bytes-fit", "escaped-bytes-over"])
def test_optional_text_is_whole_or_omitted_never_shortened_identity(field, value, reason):
    result = bound_preview(payload("rejected", **{field: value}))
    if reason is None:
        assert result[field] == value and "evidence_omissions" not in result
    else:
        assert result[field] is None and result["evidence_omissions"][field] == reason
    assert json_bytes(result) <= MAX_PREVIEW_BYTES


def test_valid_uuid_identity_is_retained_canonically_even_for_long_uuid_spelling():
    spelling = "urn:" * 10_000 + "uuid:" + TARGET
    assert uuid.UUID(spelling) == uuid.UUID(TARGET)
    result = bound_preview(payload("rejected", target_file_id=spelling))
    assert result["target_file_id"] == TARGET and "evidence_omissions" not in result


def test_oversized_arbitrary_diagnostic_falls_back_to_bounded_failure_context():
    context = {"text": "\U0001f31f" * 200, "buffer_stage": "canonical_target"}
    original = payload("rejected", diagnostic={"failure_context": context, "raw_expected_target_version": ["x" * 20_000]})
    result = bound_preview(original)
    assert result["diagnostic"] == {"failure_context": context}
    assert result["evidence_omissions"]["diagnostic"] == "diagnostic_byte_limit"
    assert len(original["diagnostic"]["raw_expected_target_version"][0]) == 20_000
    assert json_bytes({"diagnostic": result["diagnostic"]}) <= MAX_DIAGNOSTIC_BYTES


def test_oversized_diagnostic_without_safe_context_is_omitted_explicitly():
    result = bound_preview(payload("rejected", diagnostic={"raw": "x" * 20_000}))
    assert result["diagnostic"] is None and result["evidence_omissions"]["diagnostic"] == "diagnostic_byte_limit"


def test_combined_budget_prunes_diagnostic_first_and_preserves_verdict_observed_identity_and_text():
    original = payload("rejected", failure_reason="context_invalid", failed_change_id="\U0001f31f" * 600,
                       failure_detail="\U0001f31f" * 600, diagnostic={"raw": "x" * 16_000},
                       current_context={"text": "x" * 3500})
    assert json_bytes(original) > MAX_PREVIEW_BYTES
    result = bound_preview(original)
    assert result["diagnostic"] is None and result["evidence_omissions"]["diagnostic"] == "total_output_limit"
    assert result["failure_detail"] == original["failure_detail"] and result["failed_change_id"] == original["failed_change_id"]
    for key in ("status", "failure_reason", "validation_stage", "validity", "target_file_id", "current_hash", "current_version"):
        assert result[key] == original[key]
    assert json_bytes(result) <= MAX_PREVIEW_BYTES and "change_facts" not in result


def test_exact_diagnostic_wrapper_limit_is_retained_and_one_more_byte_omitted():
    diagnostic = {"raw": ""}
    diagnostic["raw"] = "x" * (MAX_DIAGNOSTIC_BYTES - json_bytes({"diagnostic": diagnostic}))
    assert json_bytes({"diagnostic": diagnostic}) == MAX_DIAGNOSTIC_BYTES
    assert bound_preview(payload("rejected", diagnostic=diagnostic))["diagnostic"] == diagnostic
    result = bound_preview(payload("rejected", diagnostic={"raw": diagnostic["raw"] + "x"}))
    assert result["diagnostic"] is None
