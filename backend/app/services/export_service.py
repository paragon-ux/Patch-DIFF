"""Read-only target retrieval and export services."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.storage.models import CloudTargetFiles


def get_target(session: Session, *, target_file_id: uuid.UUID | str) -> dict[str, Any]:
    target = session.get(CloudTargetFiles, _coerce_uuid(target_file_id))
    if target is None:
        return {"status": "not_found", "target_file_id": str(target_file_id)}
    return {
        "target_file_id": str(target.target_file_id),
        "filename": target.filename,
        "target_type": target.target_type,
        "current_content": target.current_content,
        "current_hash": target.current_hash,
        "version": target.version,
        "active_editing_cycle_id": str(target.active_editing_cycle_id),
    }


def export_target(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    format: str = "original_text",
) -> dict[str, Any]:
    target = session.get(CloudTargetFiles, _coerce_uuid(target_file_id))
    if target is None:
        return {"status": "not_found", "target_file_id": str(target_file_id)}
    return {
        "filename": target.filename,
        "content_type": target.target_type,
        "target_type": target.target_type,
        "content": target.current_content,
        "version": target.version,
        "hash": target.current_hash,
        "current_hash": target.current_hash,
        "format": format,
    }


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
