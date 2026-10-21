"""Read-only target retrieval and export services."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.input_text import invalid_text_paths, safe_input_text
from app.storage.models import CloudTargetFiles


def get_target(session: Session, *, target_file_id: uuid.UUID | str) -> dict[str, Any]:
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "target_file_id is not a valid UUID.",
        }
    target = session.get(CloudTargetFiles, target_uuid)
    if target is None:
        return {"status": "not_found", "target_file_id": safe_input_text(target_file_id)}
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
    if invalid_text_paths(format):
        return {"status": "invalid_argument", "target_file_id": safe_input_text(target_file_id),
                "failure_detail": "format must be UTF-8 without NUL."}
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "target_file_id is not a valid UUID.",
        }
    target = session.get(CloudTargetFiles, target_uuid)
    if target is None:
        return {"status": "not_found", "target_file_id": safe_input_text(target_file_id)}
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


def _try_coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
