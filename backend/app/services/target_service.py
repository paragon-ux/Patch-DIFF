"""Target initialization services backed by Postgres."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.canonicalization import canonicalize_text
from app.core.hashing import canonical_sha256
from app.core.line_endings import source_line_endings
from app.storage.models import CloudTargetFiles, EditingCycles, Projects, TargetSnapshots


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


def initialize_target(
    session: Session,
    *,
    filename: str,
    content: str | bytes,
    target_type: str,
    project_id: uuid.UUID | None = None,
) -> InitializedTarget:
    """Create canonical target state, active editing cycle, and initial snapshot."""

    line_endings = source_line_endings(content)
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
