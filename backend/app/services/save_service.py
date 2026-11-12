"""SAVE checkpoint service for PatchDIFF targets."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_workspace_root, is_workspace_sync_on_save_enabled
from app.core.failures import FailureReason
from app.storage.models import CloudTargetFiles, EditingCycles, TargetSnapshots
from app.storage.repositories import select_target_for_update
from app.services.performance_events import timed
from app.services.workspace_binding_service import (
    active_binding_evidence, bind_workspace_target, lock_workspace_destination, lock_workspace_path, workspace_write_fence,
)
from app.services.workspace_sync_service import WorkspaceSyncError, sync_target_file_to_workspace


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
    code: str | None = None
    workspace_sync: dict[str, Any] | None = None
    workspace_evidence: dict[str, Any] | None = None


@timed("task")
def save_target(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    expected_current_hash: str | None = None,
    expected_target_version: int | None = None,
    sync_workspace: bool | None = None,
    workspace_eol_format: str = "original_eol",
    workspace_root: str | os.PathLike[str] | None = None,
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

    if expected_target_version is not None and (
        isinstance(expected_target_version, bool) or not isinstance(expected_target_version, int)
        or not 0 <= expected_target_version <= 2**63 - 1
    ):
        return SaveResult(
            status="rejected",
            target_file_id=target_uuid,
            snapshot_id=None,
            closed_editing_cycle_id=None,
            new_editing_cycle_id=None,
            current_hash=None,
            version=None,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="expected_target_version must be a non-negative integer.",
        )

    if sync_workspace is not None and not isinstance(sync_workspace, bool):
        return SaveResult("rejected", target_uuid, None, None, None, None, None,
                          FailureReason.CONTEXT_INVALID, "sync_workspace must be a boolean.", "invalid_sync_workspace")
    should_sync = sync_workspace if sync_workspace is not None else (workspace_root is not None or is_workspace_sync_on_save_enabled())
    # Publishing from an outer transaction would let a caller roll back the
    # checkpoint after receiving a successful file receipt. Fail before IO.
    if should_sync and session.in_transaction():
        return SaveResult("rejected", target_uuid, None, None, None, None, None,
                          FailureReason.CONTEXT_INVALID,
                          "Workspace SAVE requires a service-owned transaction; commit/rollback the outer transaction first.",
                          "workspace_requires_owned_transaction")
    sync_payload = None
    observed_hash = observed_version = None
    try:
        with _transaction(session):
            key = session.identity_key(CloudTargetFiles, target_uuid)
            existing = session.identity_map.get(key)
            if existing is not None and (existing in session.dirty or session.is_modified(existing)):
                return SaveResult(
                    status="rejected",
                    target_file_id=target_uuid,
                    snapshot_id=None,
                    closed_editing_cycle_id=None,
                    new_editing_cycle_id=None,
                    current_hash=getattr(existing, "current_hash", None),
                    version=getattr(existing, "version", None),
                    failure_reason=FailureReason.CONTEXT_INVALID,
                    failure_detail="Pending local direct modifications on target are not permitted.",
                )

            with session.no_autoflush:
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

            fence = workspace_write_fence(session, target)
            if fence is not None:
                return SaveResult(
                    "rejected", target.target_file_id, None, None, None, target.current_hash, target.version,
                    fence.reason, fence.detail, fence.code, workspace_evidence=fence.evidence,
                )

            if expected_target_version is not None and target.version != expected_target_version:
                return SaveResult(
                    status="rejected",
                    target_file_id=target.target_file_id,
                    snapshot_id=None,
                    closed_editing_cycle_id=None,
                    new_editing_cycle_id=None,
                    current_hash=target.current_hash,
                    version=target.version,
                    failure_reason=FailureReason.TARGET_VERSION_MISMATCH,
                    failure_detail="expected_target_version does not match the current target version.",
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

            observed_hash, observed_version = target.current_hash, target.version
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

            if should_sync:
                eff_root = workspace_root if workspace_root is not None else get_workspace_root()
                binding = None
                destination = None
                physical = None

                def lock_path(identity, relative):
                    nonlocal binding
                    binding = lock_workspace_path(session, identity, relative)
                    if binding is not None and binding.active_target_file_id != target.target_file_id:
                        raise WorkspaceSyncError(
                            FailureReason.CONTEXT_INVALID, "workspace_binding_mismatch",
                            "This target does not own the workspace destination.",
                            evidence=active_binding_evidence(binding),
                        )

                def lock_destination(opened):
                    nonlocal destination, physical
                    destination = opened
                    physical = lock_workspace_destination(session, destination, binding)

                try:
                    sync_payload = sync_target_file_to_workspace(
                        target,
                        workspace_root=eff_root,
                        eol_format=workspace_eol_format,
                        before_traverse=lock_path,
                        before_publish=lock_destination,
                    ).as_dict()
                    if binding is None:
                        bind_workspace_target(session, destination, physical, target.target_file_id)
                    else:
                        binding.physical_destination = physical
                except WorkspaceSyncError as err:
                    if err.receipt is not None:
                        sync_payload = err.receipt
                        raise
                    evidence = err.evidence
                    metadata = target.source_line_endings
                    if (err.code == "workspace_binding_mismatch" and not evidence
                            and isinstance(metadata, dict) and metadata.get("workspace_tracked") is True):
                        evidence = {"active_target_file_id": str(target.target_file_id)}
                    return SaveResult(
                        status="rejected",
                        target_file_id=target.target_file_id,
                        snapshot_id=None,
                        closed_editing_cycle_id=None,
                        new_editing_cycle_id=None,
                        current_hash=target.current_hash,
                        version=target.version,
                        failure_reason=err.reason,
                        failure_detail=err.detail,
                        code=err.code,
                        workspace_evidence=evidence,
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
                workspace_sync=sync_payload,
            )
    except Exception as exc:
        if sync_payload is None:
            raise
        # A published file cannot be rolled back with PostgreSQL. Do not mask it
        # as an ordinary rejection or attempt an automatic filesystem rollback.
        return SaveResult(
            status="partial", target_file_id=target_uuid,
            snapshot_id=None, closed_editing_cycle_id=None, new_editing_cycle_id=None,
            current_hash=observed_hash, version=observed_version,
            failure_reason=FailureReason.TRANSACTION_INTERNAL_ERROR,
            failure_detail="File installed; checkpoint outcome is uncertain. Reconcile disk and database explicitly before continuing; do not retry SAVE automatically.",
            code=exc.code if isinstance(exc, WorkspaceSyncError) else "workspace_checkpoint_uncertain",
            workspace_sync=sync_payload,
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
