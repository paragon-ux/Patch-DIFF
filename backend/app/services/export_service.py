"""Read-only target retrieval and chunked finalized export services."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import uuid
from typing import Any, Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from app.core.canonicalization import canonicalize_text
from app.core.hashing import canonical_sha256
from app.core.input_text import invalid_text_paths, safe_input_text
from app.core.line_endings import EXPORT_FORMATS, apply_eol, eol_name, export_eol
from app.storage.models import (
    CloudTargetFiles,
    TargetFinalizationExportChunks,
    TargetFinalizations,
    TargetSnapshots,
)

DEFAULT_EXPORT_CHUNK_BYTES = 262_144  # 256 KiB immutable PostgreSQL chunk slice size
MAX_EXPORT_CHUNK_BYTES = 1_048_576    # 1 MiB maximum page request size
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@contextmanager
def _finalization_backfill_tx(session: Session) -> Iterator[None]:
    if session.in_transaction():
        with session.begin_nested():
            yield
    else:
        with session.begin():
            yield


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
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "format must be UTF-8 without NUL.",
        }
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "target_file_id is not a valid UUID.",
        }
    if not isinstance(format, str) or format not in EXPORT_FORMATS:
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "code": "unsupported_export_format",
            "allowed_formats": list(EXPORT_FORMATS),
            "failure_detail": "format must be one of: " + ", ".join(EXPORT_FORMATS) + ".",
        }
    target = session.get(CloudTargetFiles, target_uuid)
    if target is None:
        return {"status": "not_found", "target_file_id": safe_input_text(target_file_id)}
    eol, error = export_eol(format, target.source_line_endings)
    if error is not None:
        detail = {
            "source_line_endings_unknown": "This target predates recorded line endings; choose canonical_lf or crlf.",
            "original_eol_unrecoverable": "The upload mixed line-ending styles, which cannot be restored per line; choose canonical_lf or crlf.",
        }[error]
        return {
            "status": "invalid_argument",
            "target_file_id": str(target.target_file_id),
            "code": error,
            "failure_detail": detail,
            "source_line_endings": target.source_line_endings,
        }
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


def _query_chunk_aggregate(
    session: Session,
    finalization_uuid: uuid.UUID,
) -> tuple[int, int, int | None, int | None]:
    row = session.execute(
        select(
            func.count(TargetFinalizationExportChunks.chunk_index),
            func.coalesce(func.sum(TargetFinalizationExportChunks.byte_length), 0),
            func.min(TargetFinalizationExportChunks.chunk_index),
            func.max(TargetFinalizationExportChunks.chunk_index),
        ).where(TargetFinalizationExportChunks.finalization_id == finalization_uuid)
    ).one()
    return (
        int(row[0] or 0),
        int(row[1] or 0),
        int(row[2]) if row[2] is not None else None,
        int(row[3]) if row[3] is not None else None,
    )


def _backfill_historical_chunks_locked(
    session: Session,
    *,
    finalization_uuid: uuid.UUID,
    target_uuid: uuid.UUID,
    eol: str,
) -> dict[str, Any] | None:
    """Backfill 256-KiB chunks for a pre-0008 finalization under per-finalization row lock from immutable TargetSnapshots."""
    try:
        with _finalization_backfill_tx(session):
            session.execute(select(func.patchdiff_lock_finalized_export(finalization_uuid)))
            locked_fin = session.execute(
                select(TargetFinalizations)
                .options(defer(TargetFinalizations.exported_content))
                .where(TargetFinalizations.finalization_id == finalization_uuid)
            ).scalar_one_or_none()
            if (
                locked_fin is None
                or locked_fin.target_file_id != target_uuid
                or locked_fin.status != "completed"
                or locked_fin.snapshot_id is None
            ):
                return {
                    "status": "not_found",
                    "error": "finalization_not_found",
                    "finalization_id": str(finalization_uuid),
                    "target_file_id": str(target_uuid),
                    "failure_detail": "Finalization not found or not completed during backfill.",
                }

            count_under_lock, _, _, _ = _query_chunk_aggregate(session, finalization_uuid)
            if count_under_lock > 0:
                # Concurrent first-page reader already completed the backfill.
                return None

            snapshot = session.execute(
                select(TargetSnapshots)
                .where(TargetSnapshots.snapshot_id == locked_fin.snapshot_id)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if snapshot is None or snapshot.target_file_id != target_uuid:
                raise ValueError("Snapshot record associated with finalization is missing or invalid.")

            snap_canonical = canonicalize_text(snapshot.content)
            if canonical_sha256(snap_canonical) != snapshot.content_hash:
                raise ValueError("Snapshot content does not match its recorded content_hash.")
            if locked_fin.canonical_current_hash and snapshot.content_hash != locked_fin.canonical_current_hash:
                raise ValueError("Snapshot content_hash does not match finalization canonical_current_hash.")

            raw_bytes = apply_eol(snapshot.content, eol).encode("utf-8")
            computed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            computed_bytes = len(raw_bytes)

            if (
                locked_fin.content_sha256 is None
                or locked_fin.content_bytes is None
                or computed_sha256 != locked_fin.content_sha256
                or computed_bytes != int(locked_fin.content_bytes)
            ):
                raise ValueError(
                    f"Snapshot integrity check failed: computed sha256={computed_sha256} "
                    f"(expected {locked_fin.content_sha256}), bytes={computed_bytes} "
                    f"(expected {locked_fin.content_bytes})."
                )

            if computed_bytes > 0:
                for chunk_idx, start_byte in enumerate(
                    range(0, computed_bytes, DEFAULT_EXPORT_CHUNK_BYTES)
                ):
                    chunk_payload = raw_bytes[start_byte : start_byte + DEFAULT_EXPORT_CHUNK_BYTES]
                    session.add(
                        TargetFinalizationExportChunks(
                            finalization_id=finalization_uuid,
                            chunk_index=chunk_idx,
                            payload=chunk_payload,
                            payload_sha256=hashlib.sha256(chunk_payload).hexdigest(),
                            byte_length=len(chunk_payload),
                        )
                    )
                session.flush()
    except ValueError as exc:
        return {
            "status": "error",
            "error": "snapshot_integrity_failure",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": str(exc),
        }
    return None


def read_finalized_export(
    session: Session,
    finalization_id: uuid.UUID | str,
    target_file_id: uuid.UUID | str,
    offset: int = 0,
    limit: int = DEFAULT_EXPORT_CHUNK_BYTES,
) -> dict[str, Any]:
    # Initial SELECTs autobegin a transaction. Own that boundary from the start
    # so a successful historical conversion survives closing a service session.
    if not session.in_transaction():
        with session.begin():
            return _read_finalized_export(session, finalization_id, target_file_id, offset, limit)
    return _read_finalized_export(session, finalization_id, target_file_id, offset, limit)


def _read_finalized_export(
    session: Session,
    finalization_id: uuid.UUID | str,
    target_file_id: uuid.UUID | str,
    offset: int,
    limit: int,
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

    if isinstance(session, Session):
        finalization = session.execute(
            select(TargetFinalizations)
            .options(defer(TargetFinalizations.exported_content))
            .where(TargetFinalizations.finalization_id == finalization_uuid)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
    else:
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

    if (
        finalization.content_bytes is None
        or int(finalization.content_bytes) < 0
        or not isinstance(finalization.content_sha256, str)
        or len(finalization.content_sha256) != 64
    ):
        return {
            "status": "error",
            "error": "snapshot_integrity_failure",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": "Finalization receipt is missing valid content_bytes or content_sha256.",
        }

    total_bytes = int(finalization.content_bytes)
    expected_sha256 = str(finalization.content_sha256)
    expected_total_chunks = (
        (total_bytes + DEFAULT_EXPORT_CHUNK_BYTES - 1) // DEFAULT_EXPORT_CHUNK_BYTES
        if total_bytes > 0
        else 0
    )

    # Scan the immutable index once at the beginning of pagination, rather than
    # scanning all chunk metadata again for every page (quadratic aggregate IO).
    if offset == 0 or total_bytes == 0:
        chunk_count, sum_byte_length, min_chunk_idx, max_chunk_idx = _query_chunk_aggregate(
            session, finalization_uuid
        )
    else:
        chunk_count, sum_byte_length = expected_total_chunks, total_bytes
        min_chunk_idx, max_chunk_idx = 0, expected_total_chunks - 1

    if total_bytes > 0 and chunk_count == 0:
        backfill_err = _backfill_historical_chunks_locked(
            session,
            finalization_uuid=finalization_uuid,
            target_uuid=target_uuid,
            eol=eol,
        )
        if backfill_err is not None:
            return backfill_err
        chunk_count, sum_byte_length, min_chunk_idx, max_chunk_idx = _query_chunk_aggregate(
            session, finalization_uuid
        )

    if total_bytes == 0:
        if chunk_count != 0 or sum_byte_length != 0 or expected_sha256 != _EMPTY_SHA256:
            return {
                "status": "error",
                "error": "snapshot_integrity_failure",
                "finalization_id": str(finalization_uuid),
                "target_file_id": str(target_uuid),
                "failure_detail": "Zero-byte finalization receipt has unexpected export chunks or invalid SHA-256.",
            }
        if offset > 0:
            return {
                "status": "invalid_argument",
                "code": "invalid_range",
                "finalization_id": str(finalization_uuid),
                "target_file_id": str(target_uuid),
                "failure_detail": f"offset {offset} exceeds total bytes 0.",
                "total_bytes": 0,
            }
        return {
            "status": "ok",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "content_base64": "",
            "offset": 0,
            "bytes_read": 0,
            "total_bytes": 0,
            "content_sha256": expected_sha256,
            "has_more": False,
            "next_offset": None,
            "format": export_format,
            "content_eol": finalization.content_eol,
        }

    # Verify aggregate chunk invariants for non-empty export
    if (
        chunk_count != expected_total_chunks
        or sum_byte_length != total_bytes
        or min_chunk_idx != 0
        or max_chunk_idx != expected_total_chunks - 1
    ):
        return {
            "status": "error",
            "error": "snapshot_integrity_failure",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": (
                f"Export chunk set integrity failure: count={chunk_count} (expected {expected_total_chunks}), "
                f"sum_bytes={sum_byte_length} (expected {total_bytes}), "
                f"index_range=[{min_chunk_idx}, {max_chunk_idx}]."
            ),
        }

    if offset > total_bytes:
        return {
            "status": "invalid_argument",
            "code": "invalid_range",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": f"offset {offset} exceeds total bytes {total_bytes}.",
            "total_bytes": total_bytes,
        }

    end_byte_exclusive = min(offset + effective_limit, total_bytes)
    if offset == total_bytes:
        # At exact EOF, still verify the final chunk so tampered single/last chunk is caught
        start_chunk_idx = expected_total_chunks - 1
        end_chunk_idx = expected_total_chunks - 1
    else:
        start_chunk_idx = offset // DEFAULT_EXPORT_CHUNK_BYTES
        end_chunk_idx = (end_byte_exclusive - 1) // DEFAULT_EXPORT_CHUNK_BYTES

    chunk_rows = (
        session.execute(
            select(TargetFinalizationExportChunks)
            .where(
                TargetFinalizationExportChunks.finalization_id == finalization_uuid,
                TargetFinalizationExportChunks.chunk_index >= start_chunk_idx,
                TargetFinalizationExportChunks.chunk_index <= end_chunk_idx,
            )
            .order_by(TargetFinalizationExportChunks.chunk_index.asc())
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )

    expected_window_count = end_chunk_idx - start_chunk_idx + 1
    if not chunk_rows and offset > 0:
        # Historical receipts may first be read at any offset. Backfill only
        # an entirely absent chunk set; a hole in populated storage is corrupt.
        count, _, _, _ = _query_chunk_aggregate(session, finalization_uuid)
        if count == 0:
            error = _backfill_historical_chunks_locked(
                session, finalization_uuid=finalization_uuid, target_uuid=target_uuid, eol=eol,
            )
            if error is not None:
                return error
            return read_finalized_export(session, finalization_uuid, target_uuid, offset, effective_limit)
    if len(chunk_rows) != expected_window_count:
        return {
            "status": "error",
            "error": "snapshot_integrity_failure",
            "finalization_id": str(finalization_uuid),
            "target_file_id": str(target_uuid),
            "failure_detail": (
                f"Missing or sparse export chunks in range [{start_chunk_idx}, {end_chunk_idx}]: "
                f"got {len(chunk_rows)} rows, expected {expected_window_count}."
            ),
        }

    assembled = bytearray()
    for rel_i, row in enumerate(chunk_rows):
        expected_idx = start_chunk_idx + rel_i
        expected_chunk_len = min(
            DEFAULT_EXPORT_CHUNK_BYTES,
            total_bytes - expected_idx * DEFAULT_EXPORT_CHUNK_BYTES,
        )
        raw_payload = bytes(row.payload) if isinstance(row.payload, (bytes, bytearray, memoryview)) else b""
        if (
            int(row.chunk_index) != expected_idx
            or int(row.byte_length) != expected_chunk_len
            or len(raw_payload) != expected_chunk_len
        ):
            return {
                "status": "error",
                "error": "snapshot_integrity_failure",
                "finalization_id": str(finalization_uuid),
                "target_file_id": str(target_uuid),
                "failure_detail": (
                    f"Export chunk {row.chunk_index} length/index mismatch (expected idx={expected_idx}, "
                    f"len={expected_chunk_len}, got byte_length={row.byte_length}, payload_len={len(raw_payload)})."
                ),
            }

        actual_chunk_sha = hashlib.sha256(raw_payload).hexdigest()
        stored_chunk_sha = str(row.payload_sha256).strip()
        if actual_chunk_sha != stored_chunk_sha:
            return {
                "status": "error",
                "error": "snapshot_integrity_failure",
                "finalization_id": str(finalization_uuid),
                "target_file_id": str(target_uuid),
                "failure_detail": (
                    f"Export chunk {expected_idx} SHA-256 mismatch: computed {actual_chunk_sha}, "
                    f"expected {stored_chunk_sha}."
                ),
            }

        if expected_total_chunks == 1 and actual_chunk_sha != expected_sha256:
            return {
                "status": "error",
                "error": "snapshot_integrity_failure",
                "finalization_id": str(finalization_uuid),
                "target_file_id": str(target_uuid),
                "failure_detail": (
                    f"Single-chunk export SHA-256 {actual_chunk_sha} does not match "
                    f"receipt content_sha256 {expected_sha256}."
                ),
            }

        if offset < total_bytes:
            chunk_abs_start = expected_idx * DEFAULT_EXPORT_CHUNK_BYTES
            slice_start = max(0, offset - chunk_abs_start)
            slice_end = min(expected_chunk_len, end_byte_exclusive - chunk_abs_start)
            if slice_end > slice_start:
                assembled.extend(raw_payload[slice_start:slice_end])

    page_bytes = bytes(assembled)
    bytes_read = len(page_bytes)
    end_offset = offset + bytes_read
    has_more = end_offset < total_bytes
    next_offset = end_offset if has_more else None
    content_base64 = base64.b64encode(page_bytes).decode("ascii")

    return {
        "status": "ok",
        "finalization_id": str(finalization_uuid),
        "target_file_id": str(target_uuid),
        "content_base64": content_base64,
        "offset": offset,
        "bytes_read": bytes_read,
        "total_bytes": total_bytes,
        "content_sha256": expected_sha256,
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
