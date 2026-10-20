"""Layered validity reporting for PatchDIFF transaction responses.

Separates four orthogonal questions so callers cannot conflate "the edit applied"
with "the edit solved the user's task":

* ``protocol_valid``: input parsed and satisfied the structural contract of its
  submitted format (PDCP v0.2.3 or ``patchdiff-tx/1``).
* ``transaction_valid``: every ``MATCH`` resolved unambiguously in sequential
  in-memory simulation and all target guards held.
* ``task_correct``: did the edit satisfy the user's request? PatchDIFF does not
  evaluate this; reported as ``"not_evaluated"``.
* ``semantic``: did the target remain well-formed in its language (tests, syntax,
  types)? PatchDIFF does not evaluate this; reported as ``"not_evaluated"``.

When a rejection happens *before* a given stage runs (for example, a pre-parse
version/hash guard failure or missing target), the unreached stage is reported as
``None``. When a stage runs and succeeds before a later stage fails (for example,
protocol validation succeeds and transaction applicability fails, or both succeed
and a post-simulation ``TARGET_DIVERGED`` commit guard fails), the completed stages
report ``True``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.core.failures import FailureReason

NOT_EVALUATED = "not_evaluated"


class ValidationStage(StrEnum):
    """Actual validation stage reached by a submission path."""

    PRECONDITION_GUARD = "precondition_guard"
    PROTOCOL_VALIDATION = "protocol_validation"
    TRANSACTION_APPLICABILITY = "transaction_applicability"
    COMMIT_GUARD = "commit_guard"
    ACCEPTED = "accepted"


PROTOCOL_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        FailureReason.MANIFEST_MISSING.value,
        FailureReason.MANIFEST_INVALID.value,
        FailureReason.BLOCK_MALFORMED.value,
        FailureReason.CONTEXT_MISSING.value,
        FailureReason.CONTEXT_INVALID.value,
        FailureReason.DISAMBIGUATION_INVALID.value,
        FailureReason.EXECUTABLE_LOGIC_DETECTED.value,
    }
)

TRANSACTION_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        FailureReason.MATCH_ABSENT.value,
        FailureReason.MATCH_AMBIGUOUS.value,
        FailureReason.SEQUENTIAL_MATCH_INVALID.value,
        FailureReason.TARGET_HASH_MISMATCH.value,
    }
)

PRECONDITION_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        FailureReason.TARGET_VERSION_MISMATCH.value,
        FailureReason.TARGET_NOT_FOUND.value,
    }
)


def validity_levels(
    status: str,
    failure_reason: FailureReason | str | None = None,
    *,
    stage: ValidationStage | str | None = None,
) -> dict[str, Any]:
    """Return the four-level validity dictionary for an accept or reject outcome.

    When ``stage`` is supplied by the submit pipeline, ``protocol_valid`` and
    ``transaction_valid`` are determined from the actual stage reached rather than
    inferred solely from ``failure_reason`` (which is needed because reasons such as
    ``TARGET_HASH_MISMATCH`` and ``CONTEXT_INVALID`` can occur either at pre-parse
    guard check or inside core validation).
    """

    stage_val = stage.value if isinstance(stage, ValidationStage) else stage

    if status == "accepted" or stage_val == ValidationStage.ACCEPTED.value:
        return {
            "protocol_valid": True,
            "transaction_valid": True,
            "task_correct": NOT_EVALUATED,
            "semantic": NOT_EVALUATED,
        }

    if stage_val == ValidationStage.PRECONDITION_GUARD.value:
        protocol_valid: bool | None = None
        transaction_valid: bool | None = None
    elif stage_val == ValidationStage.PROTOCOL_VALIDATION.value:
        protocol_valid = False
        transaction_valid = None
    elif stage_val == ValidationStage.TRANSACTION_APPLICABILITY.value:
        protocol_valid = True
        transaction_valid = False
    elif stage_val == ValidationStage.COMMIT_GUARD.value:
        protocol_valid = True
        transaction_valid = True
    else:
        reason = failure_reason.value if isinstance(failure_reason, FailureReason) else failure_reason
        if reason in PROTOCOL_FAILURE_REASONS:
            protocol_valid = False
            transaction_valid = None
        elif reason in TRANSACTION_FAILURE_REASONS:
            protocol_valid = True
            transaction_valid = False
        elif reason == FailureReason.TARGET_DIVERGED.value:
            protocol_valid = True
            transaction_valid = True
        elif reason in PRECONDITION_FAILURE_REASONS:
            protocol_valid = None
            transaction_valid = None
        else:
            protocol_valid = None
            transaction_valid = None

    return {
        "protocol_valid": protocol_valid,
        "transaction_valid": transaction_valid,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }
