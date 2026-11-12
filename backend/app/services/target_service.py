"""Target initialization services backed by Postgres."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.canonicalization import canonicalize_text
from app.core.config import get_workspace_root
from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.input_text import is_persistable_text
from app.core.line_endings import source_line_endings
from app.pdcp.protocol_validator import ProtocolValidationError
from app.pdcp.typed import validate_client_request_id
from app.services.workspace_binding_service import bind_workspace_target, lock_workspace_destination, lock_workspace_path
from app.services.workspace_sync_service import (
    WorkspaceDestination, WorkspaceSyncError, pinned_workspace_path, read_workspace_bytes,
    valid_workspace_metadata, validate_workspace_source, workspace_baseline, workspace_destination,
)
from app.storage.models import (
    CloudTargetFiles, EditingCycles, Projects, TargetSnapshots, WorkspaceBinding, WorkspaceBindingMember,
    WorkspaceRecoveryReceipt,
)
from app.storage.repositories import select_targets_for_update_ordered


@dataclass(frozen=True, slots=True)
class InitializedTarget:
    target_file_id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    target_type: str
    version: int
    current_hash: str
    active_editing_cycle_id: uuid.UUID
    initial_snapshot_id: uuid.UUID
    source_line_endings: dict | None = None
    created: bool | None = None
    disk_sha256: str | None = None
    active_target_file_id: uuid.UUID | None = None
    recovery_action: str | None = None
    deduplicated: bool = False


def initialize_target(
    session: Session,
    *,
    filename: str,
    content: str | bytes,
    target_type: str,
    project_id: uuid.UUID | None = None,
    workspace_tracked: bool = False,
    workspace_root_identity: str | None = None,
) -> InitializedTarget:
    """Create canonical target state, active editing cycle, and initial snapshot."""

    line_endings = source_line_endings(content)
    if workspace_tracked:
        line_endings = {**line_endings, "workspace_tracked": True, "workspace_root_identity": workspace_root_identity}
    canonical_content = canonicalize_text(content)
    current_hash = canonical_sha256(canonical_content)
    target_file_id = uuid.uuid4()
    editing_cycle_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()

    with _transaction(session):
        if project_id is None:
            project = Projects(name=f"Project for {filename}")
            session.add(project)
            session.flush()
            project_id = project.project_id

        target = CloudTargetFiles(
            target_file_id=target_file_id,
            project_id=project_id,
            filename=filename,
            target_type=target_type,
            current_content=canonical_content,
            current_hash=current_hash,
            version=0,
            active_editing_cycle_id=editing_cycle_id,
            source_line_endings=line_endings,
        )
        cycle = EditingCycles(
            editing_cycle_id=editing_cycle_id,
            target_file_id=target_file_id,
            cycle_index=0,
            status="active",
        )
        session.add_all([target, cycle])
        session.flush()

        snapshot = TargetSnapshots(
            snapshot_id=snapshot_id,
            target_file_id=target_file_id,
            editing_cycle_id=editing_cycle_id,
            content=canonical_content,
            content_hash=current_hash,
            version=0,
            snapshot_reason="initial_upload",
        )
        session.add(snapshot)
        session.flush()
        target.initial_snapshot_id = snapshot_id

    return InitializedTarget(
        target_file_id=target_file_id,
        project_id=project_id,
        filename=filename,
        target_type=target_type,
        version=0,
        current_hash=current_hash,
        active_editing_cycle_id=editing_cycle_id,
        initial_snapshot_id=snapshot_id,
        source_line_endings=line_endings,
    )


_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_CANDIDATES = 20


@dataclass(frozen=True, slots=True)
class WorkspaceRecovery:
    action: str
    target_file_id: uuid.UUID
    expected_target_version: int
    expected_current_hash: str
    expected_disk_sha256: str
    client_request_id: str

    @classmethod
    def parse(cls, raw: dict) -> WorkspaceRecovery:
        if not isinstance(raw, dict) or raw.keys() != cls.__dataclass_fields__.keys():
            raise ValueError("workspace_recovery requires exactly the action, target ID, three guards and request ID.")
        if raw["action"] not in ("select_existing", "reimport"):
            raise ValueError("workspace_recovery action must be select_existing or reimport.")
        target_id = raw["target_file_id"]
        if not isinstance(target_id, str):
            raise ValueError("workspace_recovery target_file_id must be a UUID string.")
        try:
            target_uuid = uuid.UUID(target_id)
        except ValueError as exc:
            raise ValueError("workspace_recovery target_file_id must be a UUID string.") from exc
        version = raw["expected_target_version"]
        if type(version) is not int or not 0 <= version <= 2**63 - 1:
            raise ValueError("workspace_recovery expected_target_version must be a non-negative 64-bit integer.")
        for field in ("expected_current_hash", "expected_disk_sha256"):
            if not isinstance(raw[field], str) or not _DIGEST.fullmatch(raw[field]):
                raise ValueError(f"workspace_recovery {field} must be a lowercase SHA-256 digest.")
        try:
            request_id = validate_client_request_id(raw["client_request_id"])
        except ProtocolValidationError as exc:
            raise ValueError(exc.failure_detail) from exc
        if request_id is None:
            raise ValueError("workspace_recovery client_request_id is required.")
        return cls(raw["action"], target_uuid, version, raw["expected_current_hash"],
                   raw["expected_disk_sha256"], request_id)

    def fingerprint(self, project_id: uuid.UUID | None, target_type: str | None) -> str:
        record = {**asdict(self), "project_id": project_id, "content_type": target_type}
        del record["client_request_id"]
        canonical = json.dumps(record, default=str, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def initialize_target_from_workspace(
    session: Session,
    *,
    filename: str,
    target_type: str | None = None,
    project_id: uuid.UUID | None = None,
    workspace_root: str | os.PathLike[str] | None = None,
    recovery: WorkspaceRecovery | None = None,
) -> InitializedTarget:
    """Open the active workspace target or apply a guarded recovery transition."""
    if target_type is not None and (not isinstance(target_type, str) or not is_persistable_text(target_type)):
        raise ValueError("content_type must be valid UTF-8 text without NUL.")
    root = workspace_root if workspace_root is not None else get_workspace_root()
    with _transaction(session), session.no_autoflush:
        with pinned_workspace_path(root, filename) as path:
            binding = lock_workspace_path(session, path.root_identity, path.relative_path)
            result = None
            if recovery is not None:
                if binding is None:
                    raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_binding_not_found",
                                             "Open the workspace path before requesting recovery.")
                fingerprint = recovery.fingerprint(project_id, target_type)
                result = _recorded_workspace_recovery(session, binding, recovery.client_request_id, fingerprint)
            if result is None:
                with _destination_or_missing(path) as destination:
                    physical = lock_workspace_destination(session, destination, binding) if destination else None
                    claim_legacy = binding is not None and binding.physical_destination is None and physical is not None
                    try:
                        if recovery is None:
                            result = _open_workspace_target(session, destination, binding, physical, project_id, target_type)
                        else:
                            result = _recover_workspace_target(
                                session, destination, binding, project_id, target_type, recovery, fingerprint,
                            )
                    except WorkspaceSyncError as err:
                        if not claim_legacy or err.code == "workspace_pending_target_changes":
                            raise
                        result = err
                    if claim_legacy:
                        binding.physical_destination = physical
                session.flush()
    if isinstance(result, WorkspaceSyncError):
        raise result
    return result


@contextmanager
def _destination_or_missing(path):
    # Failure to open a missing parent is equivalent to an absent leaf for
    # drift reporting. Descriptor teardown still precedes any database commit.
    with ExitStack() as stack:
        try:
            destination = stack.enter_context(workspace_destination(path))
        except WorkspaceSyncError as err:
            if err.code != "workspace_parent_not_found":
                raise
            destination = None
        yield destination


def _locked_workspace_targets(session, target_ids):
    for target_id in target_ids:
        existing = session.identity_map.get(session.identity_key(CloudTargetFiles, target_id))
        if existing is not None and (existing in session.dirty or session.is_modified(existing)):
            raise WorkspaceSyncError(
                FailureReason.CONTEXT_INVALID, "workspace_pending_target_changes",
                "Pending local direct modifications on workspace targets are not permitted.",
            )
    return session.scalars(select_targets_for_update_ordered(target_ids)).all()


def _open_workspace_target(session, destination, binding, physical, project_id, target_type) -> InitializedTarget:
    if binding is None:
        if project_id is not None and session.get(Projects, project_id) is None:
            raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_project_conflict",
                                     "The supplied project_id does not exist.")
        raw = validate_workspace_source(read_workspace_bytes(destination) if destination else None)
        target = _import_workspace_target(session, destination, raw, project_id,
                                          "text/plain" if target_type is None else target_type)
        bind_workspace_target(session, destination, physical, target.target_file_id)
        return _workspace_result(target, created=True, disk_sha256=hashlib.sha256(raw).hexdigest())

    if binding.active_target_file_id is None:
        members = select(WorkspaceBindingMember.target_file_id).where(
            WorkspaceBindingMember.binding_id == binding.binding_id)
        candidate_ids = session.scalars(members.order_by(WorkspaceBindingMember.target_file_id).limit(_MAX_CANDIDATES)).all()
        total = session.scalar(select(func.count()).select_from(members.subquery()))
        raw = read_workspace_bytes(destination) if destination else None
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID, "workspace_binding_ambiguous",
            "Select a legacy target explicitly before opening this workspace path.",
            evidence={"candidate_target_file_ids": [str(value) for value in candidate_ids],
                      "candidate_count": total, "candidates_truncated": total > len(candidate_ids),
                      "disk_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None},
        )

    target, = _locked_workspace_targets(session, [binding.active_target_file_id])
    _check_workspace_metadata(target, project_id, target_type)
    raw = read_workspace_bytes(destination) if destination else None
    disk_sha256 = hashlib.sha256(raw).hexdigest() if raw is not None else None
    _check_workspace_baseline(target, disk_sha256)
    return _workspace_result(_initialized_target(target), created=False, disk_sha256=disk_sha256)


def _recorded_workspace_recovery(session, binding, request_id, fingerprint):
    prior = session.get(WorkspaceRecoveryReceipt, (binding.binding_id, request_id))
    if prior is None:
        return None
    if prior.request_fingerprint != fingerprint:
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "request_key_conflict",
                                 "This recovery request ID was already used with different arguments.")
    outcome = prior.outcome
    if outcome["status"] == "rejected":
        return WorkspaceSyncError(
            FailureReason(outcome["reason"]), outcome["code"], outcome["detail"],
            evidence={**outcome["evidence"], "deduplicated": True,
                      "active_target_file_id": str(binding.active_target_file_id) if binding.active_target_file_id else None},
        )
    fields = dict(outcome["target"])
    for field in ("target_file_id", "project_id", "initial_snapshot_id", "active_editing_cycle_id"):
        fields[field] = uuid.UUID(fields[field])
    fields.update(deduplicated=True, active_target_file_id=binding.active_target_file_id)
    return InitializedTarget(**fields)


def _recover_workspace_target(session, destination, binding, project_id, target_type, recovery, fingerprint):
    try:
        result = _apply_workspace_recovery(session, destination, binding, project_id, target_type, recovery)
    except WorkspaceSyncError as err:
        if err.code == "workspace_pending_target_changes":
            raise
        result = err
        result.evidence = {**err.evidence, "deduplicated": False, "recovery_action": recovery.action,
                           "active_target_file_id": str(binding.active_target_file_id) if binding.active_target_file_id else None}
        outcome = {"status": "rejected", "reason": err.reason.value, "code": err.code,
                   "detail": err.detail, "evidence": result.evidence}
    else:
        outcome = {"status": "ok", "target": json.loads(json.dumps(asdict(result), default=str))}
    session.add(WorkspaceRecoveryReceipt(binding_id=binding.binding_id, client_request_id=recovery.client_request_id,
                                         request_fingerprint=fingerprint, outcome=outcome))
    return result


def _apply_workspace_recovery(session, destination, binding, project_id, target_type, recovery):
    active = binding.active_target_file_id
    selecting = recovery.action == "select_existing"
    if active is not None and (selecting or active != recovery.target_file_id):
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID, "workspace_recovery_target_conflict",
            "Select an unresolved legacy member, or reimport an unresolved member or the current active target.",
        )
    members = session.scalars(
        select(WorkspaceBindingMember)
        .where(WorkspaceBindingMember.binding_id == binding.binding_id,
               WorkspaceBindingMember.superseded_by_target_file_id.is_(None))
        .execution_options(populate_existing=True)
    ).all()
    member_ids = [member.target_file_id for member in members]
    if recovery.target_file_id not in member_ids:
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_recovery_target_conflict",
                                 "The selected target is not a member of this workspace binding.")
    locked = _locked_workspace_targets(session, member_ids)
    target = next(row for row in locked if row.target_file_id == recovery.target_file_id)
    _check_workspace_metadata(target, project_id, target_type)
    if target.version != recovery.expected_target_version:
        raise WorkspaceSyncError(FailureReason.TARGET_VERSION_MISMATCH, "target_version_mismatch",
                                 "The recovery version guard does not match.", evidence=_target_evidence(target))
    if target.current_hash != recovery.expected_current_hash:
        raise WorkspaceSyncError(FailureReason.TARGET_HASH_MISMATCH, "target_hash_mismatch",
                                 "The recovery canonical hash guard does not match.", evidence=_target_evidence(target))
    raw = read_workspace_bytes(destination) if destination else None
    disk_sha256 = hashlib.sha256(raw).hexdigest() if raw is not None else None
    if disk_sha256 != recovery.expected_disk_sha256:
        raise WorkspaceSyncError(
            FailureReason.TARGET_DIVERGED, "workspace_disk_hash_mismatch", "The recovery disk hash guard does not match.",
            evidence={**_target_evidence(target), "disk_sha256": disk_sha256},
        )
    if selecting:
        _check_workspace_baseline(target, disk_sha256)
        result = _initialized_target(target)
    else:
        result = _import_workspace_target(session, destination, validate_workspace_source(raw),
                                          target.project_id, target.target_type)
        session.add(WorkspaceBindingMember(target_file_id=result.target_file_id, binding_id=binding.binding_id))
    for member in members:
        if member.target_file_id != result.target_file_id:
            member.superseded_by_target_file_id = result.target_file_id
    binding.active_target_file_id = result.target_file_id
    return _workspace_result(result, created=not selecting, disk_sha256=disk_sha256, recovery_action=recovery.action)


def _import_workspace_target(session, destination: WorkspaceDestination, raw, project_id, target_type):
    return initialize_target(session, filename=destination.relative_path, content=raw, target_type=target_type,
                             project_id=project_id, workspace_tracked=True,
                             workspace_root_identity=destination.root_identity)


def _initialized_target(target: CloudTargetFiles) -> InitializedTarget:
    return InitializedTarget(target.target_file_id, target.project_id, target.filename, target.target_type, target.version,
                             target.current_hash, target.active_editing_cycle_id, target.initial_snapshot_id,
                             target.source_line_endings)


def _workspace_result(target, *, created, disk_sha256, recovery_action=None):
    return replace(target, created=created, disk_sha256=disk_sha256,
                   active_target_file_id=target.target_file_id, recovery_action=recovery_action)


def _target_evidence(target):
    return {"target_file_id": str(target.target_file_id), "version": target.version, "current_hash": target.current_hash}


def _check_workspace_metadata(target, project_id, target_type):
    if project_id is not None and project_id != target.project_id:
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_project_conflict",
                                 "The supplied project_id differs from the bound target.",
                                 evidence=_target_evidence(target))
    if target_type is not None and target_type != target.target_type:
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_content_type_conflict",
                                 "The supplied content_type differs from the bound target.",
                                 evidence=_target_evidence(target))


def _check_workspace_baseline(target, disk_sha256):
    metadata = target.source_line_endings
    if not valid_workspace_metadata(target.filename, metadata):
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID, "workspace_binding_metadata_invalid",
            "The bound target's workspace tracking metadata is invalid.",
            evidence={**_target_evidence(target), "disk_sha256": disk_sha256},
        )
    if disk_sha256 is None or disk_sha256 != workspace_baseline(metadata):
        raise WorkspaceSyncError(
            FailureReason.TARGET_DIVERGED, "external_disk_drift",
            "Workspace bytes differ from the target's recorded disk baseline. Use guarded recovery to reimport.",
            evidence={**_target_evidence(target), "disk_sha256": disk_sha256},
        )


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
