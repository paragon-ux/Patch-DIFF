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
    reason: Literal["invalid_target_id", "target_not_found", "unlocked_local_state"],
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
        "selection": "prefix",
        "buffer_stage": "intermediate_buffer" if buffer.prior_changes else "canonical_target",
        "prior_changes": buffer.prior_changes,
        "start": 0,
        "end": len(buffer.text),
        "total_chars": buffer.total_chars,
        "text": buffer.text,
        "truncated": len(buffer.text) < buffer.total_chars,
        "observed_target_version": observed_target_version,
        "observed_target_hash": observed_target_hash,
    }
    if _json_bytes(context) > _CONTEXT_BYTES:
        # A corrupted non-ASCII stored hash can consume more JSON bytes than a valid SHA-256.
        low, high = 0, len(buffer.text)
        while low < high:
            end = (low + high + 1) // 2
            context.update(text=buffer.text[:end], end=end, truncated=end < buffer.total_chars)
            if _json_bytes(context) <= _CONTEXT_BYTES:
                low = end
            else:
                high = end - 1
        context.update(text=buffer.text[:low], end=low, truncated=low < buffer.total_chars)
    return context
