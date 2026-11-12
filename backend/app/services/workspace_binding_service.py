"""PostgreSQL ownership of workspace destinations."""

from __future__ import annotations

import hashlib
import os
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.services.workspace_sync_service import (
    WorkspaceDestination, WorkspaceSyncError, has_workspace_tracking, legacy_workspace_parent_matches,
    valid_workspace_metadata, workspace_entry_stat,
)
from app.storage.models import CloudTargetFiles, WorkspaceBinding, WorkspaceBindingMember


def _try_lock(session: Session, namespace: str, identity: str) -> None:
    digest = hashlib.sha256(f"patchdiff:workspace:{namespace}:{identity}".encode()).digest()
    key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    if not session.scalar(select(func.pg_try_advisory_xact_lock(key))):
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_busy",
                                 "Another managed operation owns this workspace destination.")


def lock_workspace_path(session: Session, root_identity: str, relative_path: str) -> WorkspaceBinding | None:
    _try_lock(session, "path", f"{root_identity}/{relative_path}")
    binding = session.scalar(
        select(WorkspaceBinding)
        .where(WorkspaceBinding.root_identity == root_identity,
               WorkspaceBinding.path_sha256 == hashlib.sha256(relative_path.encode()).hexdigest())
        .execution_options(populate_existing=True)
    )
    if binding is not None and binding.relative_path != relative_path:
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_binding_mismatch",
                                 "The workspace path conflicts with a different binding.")
    return binding


def lock_workspace_destination(
    session: Session, destination: WorkspaceDestination, binding: WorkspaceBinding | None,
) -> str:
    physical = destination.physical_identity
    _try_lock(session, "physical", physical)
    owner = session.scalar(select(WorkspaceBinding).where(WorkspaceBinding.physical_destination == physical)
                           .execution_options(populate_existing=True))
    if (owner is not None and (binding is None or owner.binding_id != binding.binding_id)) or (
        binding is not None and binding.physical_destination not in (None, physical)
    ):
        conflicting_binding = owner if owner is not None else binding
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID, "workspace_binding_mismatch",
            "The physical destination conflicts with the pinned workspace binding.",
            evidence=active_binding_evidence(conflicting_binding),
        )
    _check_workspace_entry(session, destination, physical, binding)
    return physical


def _check_workspace_entry(session, destination, physical, binding) -> None:
    entry = workspace_entry_stat(destination.parent_fd, destination.name)
    if entry is None:
        # With no entry to resolve, publication uses the existing no-clobber link.
        return
    claiming = binding is None or binding.physical_destination is None
    with os.scandir(destination.parent_fd) as entries:
        names = {item.name for item in entries} if claiming else None
        exact = destination.name in names if names is not None else any(item.name == destination.name for item in entries)
    if not exact:
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID, "workspace_binding_mismatch",
            "Use the exact filename listed in the workspace directory.",
        )
    if not claiming:
        return

    parent_prefix = physical.split("/", 1)[0] + "/"
    # Only claims need to look for a legacy spelling or a renamed pinned entry.
    candidates = select(
        WorkspaceBinding.relative_path,
        WorkspaceBinding.physical_destination,
        WorkspaceBinding.active_target_file_id,
    ).where(or_(
        WorkspaceBinding.physical_destination.startswith(parent_prefix),
        and_(WorkspaceBinding.root_identity == destination.root_identity,
             WorkspaceBinding.physical_destination.is_(None)),
    )).order_by(WorkspaceBinding.binding_id)
    if binding is not None:
        candidates = candidates.where(WorkspaceBinding.binding_id != binding.binding_id)
    with session.no_autoflush:
        recorded_paths = session.execute(candidates).all()
    for relative_path, pinned_path, active_id in recorded_paths:
        leaf = relative_path.rsplit("/", 1)[-1] if pinned_path is None else pinned_path[len(parent_prefix):]
        if leaf in names and leaf != destination.name:
            continue
        alias = workspace_entry_stat(destination.parent_fd, leaf)
        if alias is None or not os.path.samestat(entry, alias):
            continue
        if pinned_path is None and not legacy_workspace_parent_matches(destination, relative_path):
            continue
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID, "workspace_binding_mismatch",
            "The destination resolves to a different recorded workspace path.",
            evidence={"active_target_file_id": str(active_id)} if active_id else {},
        )


def bind_workspace_target(
    session: Session, destination: WorkspaceDestination, physical: str, target_file_id: uuid.UUID,
) -> WorkspaceBinding:
    binding = WorkspaceBinding(
        binding_id=uuid.uuid4(), root_identity=destination.root_identity,
        relative_path=destination.relative_path,
        path_sha256=hashlib.sha256(destination.relative_path.encode()).hexdigest(),
        physical_destination=physical, active_target_file_id=target_file_id,
    )
    session.add(binding)
    session.flush()
    session.add(WorkspaceBindingMember(target_file_id=target_file_id, binding_id=binding.binding_id))
    return binding


def active_binding_evidence(binding: WorkspaceBinding) -> dict[str, str]:
    if binding.active_target_file_id is None:
        return {}
    return {"active_target_file_id": str(binding.active_target_file_id)}


def workspace_write_fence(session: Session, target: CloudTargetFiles) -> WorkspaceSyncError | None:
    """Check write admission while the caller holds this target's row lock."""
    state = session.execute(
        select(WorkspaceBinding.active_target_file_id, WorkspaceBindingMember.superseded_by_target_file_id)
        .join(WorkspaceBindingMember, WorkspaceBindingMember.binding_id == WorkspaceBinding.binding_id)
        .where(WorkspaceBindingMember.target_file_id == target.target_file_id)
    ).one_or_none()
    metadata = target.source_line_endings
    if state is None:
        if not has_workspace_tracking(metadata):
            return None
    else:
        active, successor = state
        if active is None:
            return WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_binding_ambiguous",
                                      "Select the active target for this workspace path before writing.")
        if active != target.target_file_id:
            return WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_target_superseded",
                                      "This target has been superseded. Reopen its workspace path.",
                                      evidence={"active_target_file_id": str(active),
                                                "superseded_by_target_file_id": str(successor) if successor else None})
        if valid_workspace_metadata(target.filename, metadata):
            return None
    return WorkspaceSyncError(
        FailureReason.CONTEXT_INVALID, "workspace_binding_metadata_invalid",
        "This target's workspace tracking metadata is invalid or has no binding.",
        evidence={"active_target_file_id": str(target.target_file_id)} if state is not None else {},
    )
