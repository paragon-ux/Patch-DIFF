"""Authoritative read services over the managed target.

Offsets are Unicode code-point offsets into canonical (LF) content, the same
coordinate system ``find_exact_occurrences`` and the applier use. These are reads
only: they never mutate state and never replace guards on submit.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.canonicalization import canonicalize_text
from app.pdcp.matcher import find_exact_occurrences
from app.storage.models import CloudTargetFiles

DEFAULT_READ_CHARS = 4_000
MAX_READ_CHARS = 8_000
MAX_OCCURRENCES = 200
MAX_CONTEXT_CHARS = 400
MAX_HISTORY_LIMIT = 200
DEFAULT_HISTORY_LIMIT = 50


def clamp_limit(limit: int | None, *, default: int = DEFAULT_HISTORY_LIMIT, maximum: int = MAX_HISTORY_LIMIT) -> int:
    """Bound a caller-supplied page size to ``1..maximum``."""

    if limit is None:
        return default
    return max(1, min(int(limit), maximum))


def slice_content(
    content: str,
    start: int = 0,
    length: int | None = None,
    *,
    default_length: int = DEFAULT_READ_CHARS,
    max_length: int = MAX_READ_CHARS,
) -> dict[str, Any]:
    """Return a bounded slice of canonical content with explicit truncation and continuation info."""

    text = canonicalize_text(content)
    total = len(text)
    begin = max(0, min(int(start), total))
    effective_max = max(1, int(max_length))
    effective_default = min(max(1, int(default_length)), effective_max)
    wanted = effective_default if length is None else max(0, min(int(length), effective_max))
    end = min(total, begin + wanted)
    truncated = end < total
    return {
        "start": begin,
        "end": end,
        "total_chars": total,
        "text": text[begin:end],
        "truncated": truncated,
        "next_start": end if truncated else None,
    }


def occurrence_report(
    content: str,
    text: str,
    *,
    context_chars: int = 40,
    start_occurrence: int = 1,
    max_results: int = MAX_OCCURRENCES,
) -> dict[str, Any]:
    """List exact occurrences (overlapping counted) with bounded context and pagination.

    ``occurrence_index`` is 1-based over the same global list the disambiguator uses,
    so a host can pass it straight back as ``occurrence_index`` on an edit.
    """

    canonical = canonicalize_text(content)
    spans = find_exact_occurrences(canonical, text)
    context = max(0, min(int(context_chars), MAX_CONTEXT_CHARS))
    first_idx = max(1, int(start_occurrence))
    page_size = max(1, min(int(max_results), MAX_OCCURRENCES))
    slice_start = first_idx - 1
    slice_end = slice_start + page_size
    shown = spans[slice_start:slice_end]
    has_more = slice_end < len(spans)
    return {
        "occurrence_count": len(spans),
        "returned_count": len(shown),
        "start_occurrence": first_idx,
        "occurrences": [
            {
                "occurrence_index": index,
                "start": span.start,
                "end": span.end,
                "before": canonical[max(0, span.start - context) : span.start],
                "after": canonical[span.end : span.end + context],
            }
            for index, span in enumerate(shown, start=first_idx)
        ],
        "truncated": has_more,
        "next_occurrence_index": slice_end + 1 if has_more else None,
    }


def read_target(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    start: int = 0,
    length: int | None = None,
) -> dict[str, Any]:
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "target_file_id": str(target_file_id),
            "failure_detail": "target_file_id must be a valid UUID.",
        }
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        return {
            "status": "invalid_argument",
            "target_file_id": str(target_uuid),
            "failure_detail": "start must be a non-negative integer.",
        }
    if length is not None and (isinstance(length, bool) or not isinstance(length, int) or length <= 0):
        return {
            "status": "invalid_argument",
            "target_file_id": str(target_uuid),
            "failure_detail": "length must be a positive integer when provided.",
        }
    target = session.get(CloudTargetFiles, target_uuid)
    if target is None:
        return {"status": "not_found", "target_file_id": str(target_uuid)}
    return {
        "status": "ok",
        "target_file_id": str(target.target_file_id),
        "version": target.version,
        "current_hash": target.current_hash,
        **slice_content(target.current_content, start, length),
    }


def find_occurrences(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    text: str,
    context_chars: int = 40,
    start_occurrence: int = 1,
    max_results: int = MAX_OCCURRENCES,
) -> dict[str, Any]:
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "target_file_id": str(target_file_id),
            "failure_detail": "target_file_id must be a valid UUID.",
        }
    if not isinstance(text, str) or text == "":
        return {
            "status": "invalid_argument",
            "target_file_id": str(target_uuid),
            "failure_detail": "text must be a non-empty string.",
        }
    if isinstance(start_occurrence, bool) or not isinstance(start_occurrence, int) or start_occurrence < 1:
        return {
            "status": "invalid_argument",
            "target_file_id": str(target_uuid),
            "failure_detail": "start_occurrence must be a positive integer.",
        }
    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
        return {
            "status": "invalid_argument",
            "target_file_id": str(target_uuid),
            "failure_detail": "max_results must be a positive integer.",
        }
    target = session.get(CloudTargetFiles, target_uuid)
    if target is None:
        return {"status": "not_found", "target_file_id": str(target_uuid)}
    return {
        "status": "ok",
        "target_file_id": str(target.target_file_id),
        "version": target.version,
        "current_hash": target.current_hash,
        **occurrence_report(
            target.current_content,
            text,
            context_chars=context_chars,
            start_occurrence=start_occurrence,
            max_results=max_results,
        ),
    }


def _try_coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
