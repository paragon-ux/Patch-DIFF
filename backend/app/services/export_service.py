"""Read-only target retrieval and export services."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.input_text import invalid_text_paths, safe_input_text
from app.core.line_endings import EXPORT_FORMATS, apply_eol, eol_name, export_eol
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
        "status": "ok",
        "target_file_id": str(target.target_file_id),
        "filename": target.filename,
        "target_type": target.target_type,
        "current_content": target.current_content,
        "current_hash": target.current_hash,
        "version": target.version,
        "active_editing_cycle_id": str(target.active_editing_cycle_id),
        "source_line_endings": target.source_line_endings,
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
    if not isinstance(format, str) or format not in EXPORT_FORMATS:
        return {"status": "invalid_argument", "target_file_id": safe_input_text(target_file_id),
                "code": "unsupported_export_format", "allowed_formats": list(EXPORT_FORMATS),
                "failure_detail": "format must be one of: " + ", ".join(EXPORT_FORMATS) + "."}
    target = session.get(CloudTargetFiles, target_uuid)
    if target is None:
        return {"status": "not_found", "target_file_id": safe_input_text(target_file_id)}
    eol, error = export_eol(format, target.source_line_endings)
    if error is not None:
        detail = {"source_line_endings_unknown": "This target predates recorded line endings; choose canonical_lf or crlf.",
                  "original_eol_unrecoverable": "The upload mixed line-ending styles, which cannot be restored per line; choose canonical_lf or crlf."}[error]
        return {"status": "invalid_argument", "target_file_id": str(target.target_file_id), "code": error,
                "failure_detail": detail, "source_line_endings": target.source_line_endings}
    content = apply_eol(target.current_content, eol)
    return {
        "status": "ok",
        "filename": target.filename,
        "content_type": target.target_type,
        "target_type": target.target_type,
        "content": content,
        "version": target.version,
        "hash": target.current_hash,
        "current_hash": target.current_hash,
        "format": format,
        "content_eol": eol_name(eol),
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "source_line_endings": target.source_line_endings,
    }


def _try_coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
