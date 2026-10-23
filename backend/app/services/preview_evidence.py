"""Bound only advisory preview evidence; submit and durable facts remain complete."""
from __future__ import annotations

import json
import uuid

MAX_PREVIEW_BYTES = 32_768
MAX_FACTS = 32
MAX_FACT_BYTES = 2_048
MAX_FACTS_BYTES = 16_384
MAX_TEXT_CHARS = 1_024
MAX_TEXT_BYTES = 8_192
MAX_DIAGNOSTIC_BYTES = 16_384
MAX_CONTEXT_BYTES = 4_096


def json_bytes(value) -> int:
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def bound_preview(payload: dict) -> dict:
    """Return a bounded projection with explicit omissions and unchanged verdict."""
    result = dict(payload)
    omissions = {}

    def omit(field: str, reason: str) -> None:
        result[field] = None
        omissions[field] = reason
        result["evidence_omissions"] = omissions

    # A valid UUID stays an identity, even if the caller used a long accepted UUID
    # spelling (UUID accepts repeated urn: prefixes). Invalid input is only an echo.
    try:
        target_uuid = uuid.UUID(str(result.get("target_file_id")))
    except (ValueError, TypeError, AttributeError):
        target_uuid = None
    if target_uuid is not None:
        result["target_file_id"] = str(target_uuid)

    for field in ("failure_detail", "failed_change_id", "target_file_id"):
        if field == "target_file_id" and target_uuid is not None:
            continue
        value = result.get(field)
        if isinstance(value, str):
            if len(value) > MAX_TEXT_CHARS:
                omit(field, "code_points_limit")
            elif json_bytes({field: value}) > MAX_TEXT_BYTES:
                omit(field, "field_byte_limit")

    if result.get("status") == "accepted":
        all_facts = result.get("change_facts", ())
        facts = []
        reason = None
        for fact in all_facts:
            if len(facts) == MAX_FACTS:
                reason = "fact_count_limit"
                break
            if json_bytes(fact) > MAX_FACT_BYTES:
                reason = "fact_byte_limit"
                break
            if json_bytes({"change_facts": [*facts, fact]}) > MAX_FACTS_BYTES:
                reason = "facts_byte_limit"
                break
            facts.append(fact)
        result.update(change_facts=facts, total_change_count=len(all_facts), returned_fact_count=len(facts),
                      change_facts_truncated=len(facts) < len(all_facts), change_facts_omission_reason=reason)

    diagnostic = result.get("diagnostic")
    if diagnostic is not None and json_bytes({"diagnostic": diagnostic}) > MAX_DIAGNOSTIC_BYTES:
        context = diagnostic.get("failure_context") if isinstance(diagnostic, dict) else None
        if context is not None and json_bytes(context) <= MAX_CONTEXT_BYTES:
            result["diagnostic"] = {"failure_context": context}
            omissions["diagnostic"] = "diagnostic_byte_limit"
            result["evidence_omissions"] = omissions
        else:
            omit("diagnostic", "diagnostic_byte_limit")

    current_context = result.get("current_context")
    if current_context is not None and json_bytes(current_context) > MAX_CONTEXT_BYTES:
        omit("current_context", "field_byte_limit")

    # Combined evidence can exceed the whole-payload budget even when individual
    # fields fit. Preserve core verdict/observed identity and omit optional evidence.
    for field in ("near_misses", "warning_details", "warnings", "diagnostic", "failure_detail", "failed_change_id",
                  "target_file_id", "current_context"):
        if json_bytes(result) <= MAX_PREVIEW_BYTES:
            break
        if field == "target_file_id" and target_uuid is not None:
            continue
        if result.get(field) is not None:
            omit(field, "total_output_limit")
    while json_bytes(result) > MAX_PREVIEW_BYTES and result.get("change_facts"):
        result["change_facts"].pop()
        result.update(returned_fact_count=len(result["change_facts"]), change_facts_truncated=True,
                      change_facts_omission_reason="total_output_limit")
    return result
