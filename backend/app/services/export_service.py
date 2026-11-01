"""Read-only target retrieval and export services."""

from __future__ import annotations

import base64
from collections import OrderedDict
import hashlib
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.input_text import invalid_text_paths, safe_input_text
from app.core.line_endings import EXPORT_FORMATS, apply_eol, eol_name, export_eol
from app.storage.models import CloudTargetFiles, TargetFinalizations, TargetSnapshots

DEFAULT_EXPORT_CHUNK_BYTES = 262_144  # 256 KiB
MAX_EXPORT_CHUNK_BYTES = 1_048_576    # 1 MiB
_MAX_CACHED_EXPORTS = 8
_VERIFIED_EXPORT_CACHE: OrderedDict[uuid.UUID, tuple[tuple[Any, ...], bytes, str]] = OrderedDict()


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


def read_finalized_export(
    session: Session,
    finalization_id: uuid.UUID | str,
    target_file_id: uuid.UUID | str,
    offset: int = 0,
    limit: int = DEFAULT_EXPORT_CHUNK_BYTES,
) -> dict[str, Any]:
    finalization_uuid = _try_coerce_uuid(finalization_id)
    if finalization_uuid is None:
        return {
            "status": "invalid_argument",
            "finalization_id": safe_input_text(finalization_id),
            "failure_detail": "finalization_id is not a valid UUID.",
        }
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "target_file_id is not a valid UUID.",
        }
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return {
            "status": "invalid_argument",
            "code": "invalid_offset",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": "offset must be a non-negative integer.",
        }
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        return {
            "status": "invalid_argument",
            "code": "invalid_limit",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": "limit must be a positive integer.",
        }

    effective_limit = min(limit, MAX_EXPORT_CHUNK_BYTES)

    finalization = session.get(TargetFinalizations, finalization_uuid)
    if finalization is None or finalization.target_file_id != target_uuid:
        return {
            "status": "not_found",
            "error": "finalization_not_found",
            "finalization_id": safe_input_text(finalization_id),
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "Finalization not found for target_file_id.",
        }
    if finalization.status != "completed" or finalization.snapshot_id is None:
        return {
            "status": "not_found",
            "error": "finalization_not_found",
            "finalization_id": safe_input_text(finalization_id),
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "Finalization is not in completed status.",
        }

    snapshot = session.get(TargetSnapshots, finalization.snapshot_id)
    if snapshot is None or snapshot.target_file_id != target_uuid:
        return {
            "status": "error",
            "error": "snapshot_integrity_failure",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": "Snapshot record associated with finalization is missing or invalid.",
        }

    export_format = finalization.export_format or "original_eol"
    eol, eol_error = export_eol(export_format, finalization.source_line_endings)
    if eol_error is not None:
        return {
            "status": "error",
            "error": "snapshot_integrity_failure",
            "code": eol_error,
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": f"Failed to derive export line endings: {eol_error}",
        }

    # Bounded integrity-verified export buffer cache (PR23-R4I-SVC-001):
    # Avoids repeating apply_eol + UTF-8 encode + SHA-256 across paged reads of the same immutable
    # finalized snapshot while re-verifying immediately if any DB column or snapshot content mutates.
    state_guard = (
        export_format,
        finalization.content_sha256,
        finalization.content_bytes,
        getattr(snapshot, "content_hash", None),
        len(snapshot.content),
        hash(snapshot.content),
    )
    cached_entry = _VERIFIED_EXPORT_CACHE.get(finalization_uuid)
    if cached_entry is not None and cached_entry[0] == state_guard:
        _VERIFIED_EXPORT_CACHE.move_to_end(finalization_uuid)
        _, raw_bytes, computed_sha256 = cached_entry
        computed_bytes = len(raw_bytes)
    else:
        content = apply_eol(snapshot.content, eol)
        raw_bytes = content.encode("utf-8")
        computed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        computed_bytes = len(raw_bytes)

        if (finalization.content_sha256 is not None and computed_sha256 != finalization.content_sha256) or (
            finalization.content_bytes is not None and computed_bytes != finalization.content_bytes
        ):
            _VERIFIED_EXPORT_CACHE.pop(finalization_uuid, None)
            return {
                "status": "error",
                "error": "snapshot_integrity_failure",
                "finalization_id": str(finalization_uuid),
                "target_file_id": str(target_uuid),
                "failure_detail": (
                    f"Snapshot integrity check failed: computed sha256={computed_sha256} "
                    f"(expected {finalization.content_sha256}), bytes={computed_bytes} "
                    f"(expected {finalization.content_bytes})."
                ),
            }

        _VERIFIED_EXPORT_CACHE[finalization_uuid] = (state_guard, raw_bytes, computed_sha256)
        _VERIFIED_EXPORT_CACHE.move_to_end(finalization_uuid)
        while len(_VERIFIED_EXPORT_CACHE) > _MAX_CACHED_EXPORTS:
            _VERIFIED_EXPORT_CACHE.popitem(last=False)

    total_bytes = computed_bytes
    if offset > total_bytes:
        return {
            "status": "invalid_argument",
            "code": "invalid_range",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": f"offset {offset} exceeds total bytes {total_bytes}.",
            "total_bytes": total_bytes,
        }

    chunk = raw_bytes[offset : offset + effective_limit]
    bytes_read = len(chunk)
    end_offset = offset + bytes_read
    has_more = end_offset < total_bytes
    next_offset = end_offset if has_more else None
    content_base64 = base64.b64encode(chunk).decode("ascii")

    return {
        "status": "ok",
        "finalization_id": str(finalization_uuid),
        "target_file_id": str(target_uuid),
        "content_base64": content_base64,
        "offset": offset,
        "bytes_read": bytes_read,
        "total_bytes": total_bytes,
        "content_sha256": computed_sha256,
        "has_more": has_more,
        "next_offset": next_offset,
        "format": export_format,
        "content_eol": finalization.content_eol,
    }


def _try_coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
