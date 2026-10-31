"""Bounded, JSON-safe original and current rejection context representations."""

from __future__ import annotations

import json
from typing import Literal

from app.core.result import FailureBufferContext


def _json_bytes(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii"))


# Reserve wrapper bytes even when both independently captured contexts fill their budget.
_WRAPPER_BYTES = _json_bytes({"failure_context": None, "current_context": None}) - 8
_CONTEXT_BYTES = min(4096, (8192 - _WRAPPER_BYTES) // 2)


def unavailable_context(
    reason: Literal["invalid_target_id", "target_not_found", "unlocked_local_state", "same_as_failure_context", "batch_scope_not_evaluated"],
) -> dict:
    return {
        "available": False,
        "unavailable_reason": reason,
        "selection": None,
        "buffer_stage": None,
        "prior_changes": None,
        "start": None,
        "end": None,
        "total_chars": None,
        "text": None,
        "truncated": None,
        "observed_target_version": None,
        "observed_target_hash": None,
    }


def available_context(
    buffer: FailureBufferContext, *, observed_target_version: int, observed_target_hash: str,
) -> dict:
    context = {
        "available": True,
        "unavailable_reason": None,
        "selection": buffer.selection,
        "buffer_stage": "intermediate_buffer" if buffer.prior_changes else "canonical_target",
        "prior_changes": buffer.prior_changes,
        "start": buffer.start,
        "end": buffer.start + len(buffer.text),
        "total_chars": buffer.total_chars,
        "text": buffer.text,
        "truncated": len(buffer.text) < buffer.total_chars,
        "observed_target_version": observed_target_version,
        "observed_target_hash": observed_target_hash,
    }

    def fit(length: int) -> None:
        # A prefix shrinks from its end; a failure window keeps its focus inside.
        local = 0
        if buffer.focus is not None:
            local = max(0, min(buffer.focus - buffer.start - length // 2, len(buffer.text) - length))
        context.update(text=buffer.text[local:local + length], start=buffer.start + local,
                       end=buffer.start + local + length, truncated=length < buffer.total_chars)

    if _json_bytes(context) > _CONTEXT_BYTES:
        # A corrupted non-ASCII stored hash can consume more JSON bytes than a valid SHA-256.
        low, high = 0, len(buffer.text)
        while low < high:
            length = (low + high + 1) // 2
            fit(length)
            if _json_bytes(context) <= _CONTEXT_BYTES:
                low = length
            else:
                high = length - 1
        fit(low)
    return context


def response_current_context(current: dict | None, failure: dict | None) -> dict | None:
    """MCP responses elide a current context identical to the stored failure context."""
    if current is not None and current.get("available") and current == failure:
        return unavailable_context("same_as_failure_context")
    return current


def context_identity(context: dict) -> dict:
    return {key: context.get(key) for key in ("buffer_stage", "prior_changes", "observed_target_version", "observed_target_hash")}


def bound_candidates(key: str, value: dict) -> dict:
    while _json_bytes({key: value}) > 8192 and value["candidates"]:
        value["candidates"].pop()
        value["truncated"] = True
    value["returned_count"] = len(value["candidates"])
    if "next_occurrence_index" in value:
        value["next_occurrence_index"] = value["returned_count"] + 1 if value["truncated"] else None
    return value
