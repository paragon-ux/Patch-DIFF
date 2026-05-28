"""Deterministic core result types shared by runtime and service layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.failures import FailureReason


@dataclass(frozen=True, slots=True)
class AcceptedCoreResult:
    before_hash: str
    after_hash: str
    target_content: str
    change_count: int
    status: Literal["accepted"] = "accepted"
    manifest_entries: tuple[Any, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RejectedCoreResult:
    failure_reason: FailureReason
    failure_detail: str
    before_hash: str
    failed_change_id: str | None = None
    diagnostic: dict[str, Any] | None = None
    status: Literal["rejected"] = "rejected"
    after_hash: None = None
