"""SAVE checkpoint service for PatchDIFF targets."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.storage.models import CloudTargetFiles, EditingCycles, TargetSnapshots
from app.storage.repositories import select_target_for_update


@dataclass(frozen=True, slots=True)
class SaveResult:
    status: str
    target_file_id: uuid.UUID | str
    snapshot_id: uuid.UUID | None
    closed_editing_cycle_id: uuid.UUID | None
    new_editing_cycle_id: uuid.UUID | None
    current_hash: str | None
    version: int | None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None


def save_target(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    expected_current_hash: str | None = None,
    _after_snapshot=None,
) -> SaveResult:
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return SaveResult(
            status="rejected",
            target_file_id=str(target_file_id),
            snapshot_id=None,
            closed_editing_cycle_id=None,
            new_editing_cycle_id=None,
            current_hash=None,
            version=None,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="target_file_id is not a valid UUID.",
        )

    with _transaction(session):
        target = session.execute(select_target_for_update(target_uuid)).scalar_one_or_none()
        if target is None:
            return SaveResult(
                status="rejected",
                target_file_id=target_uuid,
                snapshot_id=None,
                closed_editing_cycle_id=None,
                new_editing_cycle_id=None,
                current_hash=None,
                version=None,
                failure_reason=FailureReason.TARGET_NOT_FOUND,
                failure_detail="Target file was not found.",
            )

        if expected_current_hash is not None and target.current_hash != expected_current_hash:
            return SaveResult(
                status="rejected",
                target_file_id=target.target_file_id,
                snapshot_id=None,
                closed_editing_cycle_id=None,
                new_editing_cycle_id=None,
                current_hash=target.current_hash,
                version=target.version,
                failure_reason=FailureReason.TARGET_HASH_MISMATCH,
                failure_detail="expected_current_hash does not match the current target hash.",
            )

        old_cycle = session.get(EditingCycles, target.active_editing_cycle_id)
        if old_cycle is None:
            return SaveResult(
                status="rejected",
                target_file_id=target.target_file_id,
                snapshot_id=None,
                closed_editing_cycle_id=None,
                new_editing_cycle_id=None,
                current_hash=target.current_hash,
                version=target.version,
                failure_reason=FailureReason.CONTEXT_INVALID,
                failure_detail="Target active editing cycle was not found.",
            )

        snapshot = TargetSnapshots(
            target_file_id=target.target_file_id,
            editing_cycle_id=old_cycle.editing_cycle_id,
            content=target.current_content,
            content_hash=target.current_hash,
            version=target.version,
            snapshot_reason="save_checkpoint",
            base_pdcp_log_id=target.latest_accepted_pdcp_log_id,
        )
        session.add(snapshot)
        session.flush()

        if _after_snapshot is not None:
            _after_snapshot()

        next_cycle_index = (
            session.scalar(
                select(func.coalesce(func.max(EditingCycles.cycle_index), -1)).where(
                    EditingCycles.target_file_id == target.target_file_id
                )
            )
            + 1
        )
        new_cycle = EditingCycles(
            target_file_id=target.target_file_id,
            cycle_index=next_cycle_index,
            status="active",
        )
        old_cycle.status = "closed"
        old_cycle.closed_at = func.now()
        old_cycle.save_snapshot_id = snapshot.snapshot_id
        session.flush()
        session.add(new_cycle)
        session.flush()
        target.active_editing_cycle_id = new_cycle.editing_cycle_id

        return SaveResult(
            status="saved",
            target_file_id=target.target_file_id,
            snapshot_id=snapshot.snapshot_id,
            closed_editing_cycle_id=old_cycle.editing_cycle_id,
            new_editing_cycle_id=new_cycle.editing_cycle_id,
            current_hash=target.current_hash,
            version=target.version,
        )


def _try_coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class _transaction:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._context = None

    def __enter__(self):
        if self._session.in_transaction():
            return None
        self._context = self._session.begin()
        return self._context.__enter__()

    def __exit__(self, exc_type, exc, traceback) -> bool | None:
        if self._context is None:
            return None
        return self._context.__exit__(exc_type, exc, traceback)
