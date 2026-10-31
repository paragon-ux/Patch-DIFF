"""Atomic finalization service combining SAVE, replay verification, and export in a single transaction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.core.input_text import invalid_text_paths, safe_input_text
from app.core.line_endings import EXPORT_FORMATS
from app.services.export_service import export_target
from app.services.performance_events import timed
from app.services.replay_service import replay_target
from app.services.save_service import save_target
from app.storage.models import CloudTargetFiles
from app.storage.repositories import select_target_for_update


def _try_coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    status: str
    target_file_id: uuid.UUID | str
    filename: str | None = None
    version: int | None = None
    current_hash: str | None = None
    snapshot_id: uuid.UUID | None = None
    closed_editing_cycle_id: uuid.UUID | None = None
    new_editing_cycle_id: uuid.UUID | None = None
    materialized_state_matches: bool | None = None
    materialized_state_checks: dict[str, bool] | None = None
    exported_content: str | None = None
    content_sha256: str | None = None
    format: str | None = None
    source_line_endings: str | None = None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None


class _FinalizeRollbackError(Exception):
    """Internal exception raised to trigger transaction rollback when replay or export fails."""
    def __init__(self, failure_reason: FailureReason, failure_detail: str) -> None:
        super().__init__(failure_detail)
        self.failure_reason = failure_reason
        self.failure_detail = failure_detail


@timed("finalize_target")
def finalize_target(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    format: str = "original_eol",
) -> FinalizeResult:
    """Atomically checkpoint, replay-verify, and export a canonical target in a single database transaction.

    Database Atomicity Guarantees:
    - Runs in a single PostgreSQL session and transaction under SELECT ... FOR UPDATE row locking.
    - Validates target existence and version/hash guards.
    - Checkpoints via save_target (creates snapshot and rotates editing cycle).
    - Verifies authoritative history via replay_target (reconstructs state from upload and logs).
    - If replay verification fails (materialized_state_matches is not True), the entire transaction
      is rolled back, leaving zero snapshots created and zero editing cycle mutations.
    - Exports target content in the requested format (original_eol, canonical_lf, crlf, original_text).
    - Only commits when all three phases succeed.
    """
    if invalid_text_paths({"format": format, "expected_current_hash": expected_current_hash}):
        return FinalizeResult(
            status="rejected",
            target_file_id=safe_input_text(target_file_id),
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="Finalization arguments must be valid UTF-8 without NUL bytes.",
        )

    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return FinalizeResult(
            status="rejected",
            target_file_id=str(target_file_id),
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="target_file_id is not a valid UUID.",
        )

    if format not in EXPORT_FORMATS:
        return FinalizeResult(
            status="rejected",
            target_file_id=target_uuid,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail=f"format must be one of {sorted(EXPORT_FORMATS)}; got {format!r}.",
        )

    if expected_target_version is not None and (
        isinstance(expected_target_version, bool)
        or not isinstance(expected_target_version, int)
        or not 0 <= expected_target_version <= 2**63 - 1
    ):
        return FinalizeResult(
            status="rejected",
            target_file_id=target_uuid,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="expected_target_version must be a non-negative integer.",
        )

    # Use an outer transaction or nested savepoint if session already in transaction
    is_outer = not session.in_transaction()
    tx = session.begin() if is_outer else session.begin_nested()

    try:
        # 1. Lock target row
        with session.no_autoflush:
            target = session.execute(select_target_for_update(target_uuid)).scalar_one_or_none()

        if target is None:
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                failure_reason=FailureReason.TARGET_NOT_FOUND,
                failure_detail="Target file was not found.",
            )

        # 2. Check guards before modifying any state
        if expected_target_version is not None and target.version != expected_target_version:
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                version=target.version,
                current_hash=target.current_hash,
                failure_reason=FailureReason.TARGET_VERSION_MISMATCH,
                failure_detail="expected_target_version does not match the current target version.",
            )

        if expected_current_hash is not None and target.current_hash != expected_current_hash:
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                version=target.version,
                current_hash=target.current_hash,
                failure_reason=FailureReason.TARGET_HASH_MISMATCH,
                failure_detail="expected_current_hash does not match the current target hash.",
            )

        # 3. SAVE: create snapshot and rotate editing cycle
        save_res = save_target(
            session,
            target_file_id=target_uuid,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
        )

        if save_res.status != "saved":
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                version=save_res.version,
                current_hash=save_res.current_hash,
                failure_reason=save_res.failure_reason,
                failure_detail=save_res.failure_detail,
            )

        # 4. REPLAY: verify authoritative deterministic history
        replay_res = replay_target(session, target_file_id=target_uuid)
        if replay_res.status != "success" or not replay_res.materialized_state_matches:
            # Replay failed! Roll back the transaction completely so save_target is undone!
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                version=target.version,
                current_hash=target.current_hash,
                materialized_state_matches=replay_res.materialized_state_matches,
                materialized_state_checks=replay_res.materialized_state_checks,
                failure_reason=replay_res.failure_reason or FailureReason.REPLAY_HASH_MISMATCH,
                failure_detail=(
                    f"Replay verification failed during finalization: {replay_res.failure_detail or 'materialized state mismatch'}. "
                    "SAVE checkpoint and editing cycle rotation were rolled back atomically."
                ),
            )

        # 5. EXPORT: format target content
        export_res = export_target(session, target_file_id=target_uuid, format=format)
        if export_res.get("status") != "ok":
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                version=target.version,
                current_hash=target.current_hash,
                failure_reason=FailureReason.CONTEXT_INVALID,
                failure_detail=f"Export failed during finalization: {export_res.get('failure_detail')}",
            )

        # 6. All three phases verified: commit transaction
        tx.commit()

        return FinalizeResult(
            status="ok",
            target_file_id=target_uuid,
            filename=target.filename,
            version=target.version,
            current_hash=target.current_hash,
            snapshot_id=save_res.snapshot_id,
            closed_editing_cycle_id=save_res.closed_editing_cycle_id,
            new_editing_cycle_id=save_res.new_editing_cycle_id,
            materialized_state_matches=replay_res.materialized_state_matches,
            materialized_state_checks=replay_res.materialized_state_checks,
            exported_content=export_res.get("exported_content"),
            content_sha256=export_res.get("content_sha256"),
            format=export_res.get("format"),
            source_line_endings=target.source_line_endings,
        )

    except Exception:
        tx.rollback()
        raise
