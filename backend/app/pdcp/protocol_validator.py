"""Shared validation error for typed transaction formats."""

from dataclasses import dataclass

from app.core.failures import FailureReason


@dataclass(frozen=True, slots=True)
class ProtocolValidationError(Exception):
    failure_reason: FailureReason
    failure_detail: str
    failed_change_id: str | None = None
