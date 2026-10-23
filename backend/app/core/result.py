"""Deterministic core result types shared by runtime and service layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.failures import FailureReason


CONTEXT_CHARS = 256
# A known failure location is shown in place when at least this much of it is
# visible in the prefix; otherwise the context becomes a window around it.
FOCUS_MARGIN_CHARS = 64


@dataclass(frozen=True, slots=True)
class FailureBufferContext:
    text: str
    total_chars: int
    prior_changes: int
    start: int = 0
    selection: str = "prefix"
    focus: int | None = None

    @classmethod
    def capture(cls, buffer: str, prior_changes: int = 0, focus: int | None = None) -> FailureBufferContext:
        if focus is None or len(buffer) <= CONTEXT_CHARS or focus + FOCUS_MARGIN_CHARS <= CONTEXT_CHARS:
            return cls(buffer[:CONTEXT_CHARS], len(buffer), prior_changes)
        start = max(0, min(focus - CONTEXT_CHARS // 2, len(buffer) - CONTEXT_CHARS))
        return cls(buffer[start:start + CONTEXT_CHARS], len(buffer), prior_changes,
                   start=start, selection="failure_window", focus=focus)


@dataclass(frozen=True, slots=True)
class AcceptedCoreResult:
    before_hash: str
    after_hash: str
    target_content: str
    change_count: int
    status: Literal["accepted"] = "accepted"
    manifest_entries: tuple[Any, ...] = field(default_factory=tuple)
    # Runtime-derived facts, one per applied change (spans, payload lengths/hashes).
    # These are computed by the runtime, never asserted by the proposer.
    change_facts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    # Advisory warnings; they never change the verdict and replay ignores them.
    warnings: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RejectedCoreResult:
    failure_reason: FailureReason
    failure_detail: str
    before_hash: str
    failed_change_id: str | None = None
    diagnostic: dict[str, Any] | None = None
    status: Literal["rejected"] = "rejected"
    after_hash: None = None
    failure_buffer: FailureBufferContext | None = None
    # Bounded, response-only copy of the failing buffer for near-miss scanning.
    near_miss_buffer: str | None = None
