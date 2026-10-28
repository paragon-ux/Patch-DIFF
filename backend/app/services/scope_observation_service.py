"""Server-issued structural scope observation service backed by Waymark and PostgreSQL.

Waymark discovers structural candidates (`waymark-engine@4.1.0`); Patch-DIFF
converts Waymark's 1-based line and 0-based UTF-16 column coordinates into
canonical LF Unicode code-point offsets (`patchdiff-tx/2`), persists an opaque
server-issued `observation_id` in `target_scope_observations`, and validates
that observation under the PostgreSQL target lock before admitting scoped edits.
"""

from __future__ import annotations

import uuid
from bisect import bisect_left
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.input_text import invalid_text_paths, safe_input_text
from app.core.validity import ValidationStage
from app.pdcp.observed_batch import (
    MAX_BATCH_SCOPES, MAX_BATCH_TOTAL_SCOPE_CHARS, MAX_BATCH_INITIAL_TEXT_CHARS,
    BATCH_UNSET, BatchScope, BatchValidationError, validate_scope_set,
)
from app.services.read_service import DEFAULT_READ_CHARS, MAX_READ_CHARS
from app.services.waymark_adapter import (
    DEFAULT_WAYMARK_TIMEOUT_SECONDS,
    EXPECTED_WAYMARK_ENGINE_VERSION,
    WaymarkPosition,
    WaymarkSymbol,
    discover_symbols_from_content,
)
from app.storage.models import CloudTargetFiles, TargetScopeObservations
from app.services.performance_events import timed

MAX_OBSERVE_CANDIDATES = 200


class ScopeCoordinateConversionError(ValueError):
    """Raised when Waymark line/UTF-16 column coordinates cannot map to canonical LF code points."""


@dataclass(frozen=True, slots=True)
class ObservationValidationFailure:
    failure_reason: FailureReason
    failure_detail: str
    code: str
    stage: ValidationStage
    diagnostic: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ValidatedScopeObservation:
    observation: TargetScopeObservations
    scope_start: int
    scope_end: int
    observed_scope_hash: str


def utf16_column_to_code_point_offset(line_text: str, utf16_column: int) -> int:
    """Convert a 0-based UTF-16 code-unit column within one LF line to a Unicode code-point offset."""
    if isinstance(utf16_column, bool) or not isinstance(utf16_column, int) or utf16_column < 0:
        raise ScopeCoordinateConversionError(f"UTF-16 column must be a non-negative integer, got {utf16_column!r}.")
    utf16_bytes = line_text.encode("utf-16-le")
    byte_offset = utf16_column * 2
    if byte_offset > len(utf16_bytes):
        raise ScopeCoordinateConversionError(
            f"UTF-16 column {utf16_column} exceeds line UTF-16 length {len(utf16_bytes) // 2}."
        )
    try:
        prefix = utf16_bytes[:byte_offset].decode("utf-16-le")
    except UnicodeDecodeError as exc:
        raise ScopeCoordinateConversionError(
            f"UTF-16 column {utf16_column} splits a UTF-16 surrogate pair."
        ) from exc
    return len(prefix)


@timed("coordinate_conversion")
def waymark_span_to_code_point_offsets(
    content: str,
    start: WaymarkPosition,
    end: WaymarkPosition,
) -> tuple[int, int]:
    """Convert Waymark 1-based line / 0-based UTF-16 column coordinates to canonical code-point offsets."""
    if not isinstance(content, str):
        raise ScopeCoordinateConversionError("Target content must be a string.")
    if "\r" in content:
        raise ScopeCoordinateConversionError("Target content must be canonical LF text without CR.")

    lines = content.split("\n")
    total_lines = len(lines)
    if (
        isinstance(start.line, bool)
        or isinstance(end.line, bool)
        or not isinstance(start.line, int)
        or not isinstance(end.line, int)
    ):
        raise ScopeCoordinateConversionError("Start and end lines must be integers.")
    if start.line < 1 or end.line < start.line or end.line > total_lines:
        raise ScopeCoordinateConversionError(
            f"Line range [{start.line}, {end.line}] is outside target total_lines={total_lines}."
        )

    line_starts = [0] + [idx + 1 for idx, ch in enumerate(content) if ch == "\n"]
    start_line_text = lines[start.line - 1]
    end_line_text = lines[end.line - 1]

    start_col_cp = utf16_column_to_code_point_offset(start_line_text, start.column)
    if start.column == 0 and end.column == 0 and len(end_line_text) > 0:
        # Line-only outline fallback (e.g. codedb): inclusive of end_line content.
        end_col_cp = len(end_line_text)
    else:
        end_col_cp = utf16_column_to_code_point_offset(end_line_text, end.column)

    scope_start = line_starts[start.line - 1] + start_col_cp
    scope_end = line_starts[end.line - 1] + end_col_cp
    if not (0 <= scope_start <= scope_end <= len(content)):
        raise ScopeCoordinateConversionError(
            f"Converted code-point span [{scope_start}, {scope_end}) is invalid for content length {len(content)}."
        )
    return scope_start, scope_end


def _symbol_matches_selection(
    symbol: WaymarkSymbol,
    *,
    symbol_name: str,
    kind: str | None = None,
) -> bool:
    if kind is not None and symbol.kind != kind:
        if not (kind == "object" and symbol.kind in {"config_item", "config_block", "property"}):
            return False
    qualified = f"{symbol.parent}.{symbol.name}" if symbol.parent else None
    return symbol.name == symbol_name or qualified == symbol_name


def _candidate_dict(content: str, symbol: WaymarkSymbol) -> dict[str, Any]:
    scope_start, scope_end = waymark_span_to_code_point_offsets(content, symbol.start, symbol.end)
    return {
        "name": symbol.name,
        "kind": symbol.kind,
        "parent": symbol.parent,
        "signature": symbol.signature,
        "start_line": symbol.start.line,
        "start_column": symbol.start.column,
        "end_line": symbol.end.line,
        "end_column": symbol.end.column,
        "scope_start": scope_start,
        "scope_end": scope_end,
        "scope_chars": scope_end - scope_start,
    }


def _scope_page(
    content: str,
    *,
    scope_start: int,
    scope_end: int,
    start_line: int,
    end_line: int,
    offset: int = 0,
    max_chars: int | None = None,
    include_line_starts: bool = False,
) -> dict[str, Any]:
    scope_len = scope_end - scope_start
    if offset > scope_len:
        raise ValueError("offset exceeds the observed scope length.")
    size = DEFAULT_READ_CHARS if max_chars is None else min(max_chars, MAX_READ_CHARS)
    page_start = scope_start + offset
    page_end = min(scope_end, page_start + size)
    truncated = page_end < scope_end
    page: dict[str, Any] = {
        "scope_start": scope_start,
        "scope_end": scope_end,
        "scope_chars": scope_len,
        "start_line": start_line,
        "end_line": end_line,
        "offset": offset,
        "max_chars": size,
        "start": page_start,
        "end": page_end,
        "text": content[page_start:page_end],
        "truncated": truncated,
        "next_offset": (offset + (page_end - page_start)) if truncated else None,
        "next_start": page_end if truncated else None,
    }
    if include_line_starts:
        starts = [0] + [index + 1 for index, char in enumerate(content) if char == "\n"]
        total_lines = len(starts)
        last = min(end_line, total_lines)
        first = bisect_left(starts, page_start, lo=max(0, start_line - 1), hi=last)
        page["line_starts"] = [
            {"line": index + 1, "start": starts[index]}
            for index in range(first, last)
            if starts[index] < page_end or (starts[index] == page_start == page_end)
        ]
    return page


def observe_scope(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    symbol_name: str | None = None,
    kind: str | None = None,
    query: str | None = None,
    observation_id: uuid.UUID | str | None = None,
    selections: list[dict] | None = BATCH_UNSET,
    offset: int = 0,
    max_chars: int | None = None,
    include_line_starts: bool = False,
    timeout_seconds: float = DEFAULT_WAYMARK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Discover structural candidates or select a unique Waymark scope and issue a persistent observation."""
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "code": "INVALID_TARGET_ID",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "target_file_id must be a valid UUID.",
        }

    if invalid_text_paths(
        {
            "symbol_name": symbol_name,
            "kind": kind,
            "query": query,
            "observation_id": observation_id,
            "offset": offset,
            "max_chars": max_chars,
            "selections": None if selections is BATCH_UNSET else selections,
        }
    ):
        return {
            "status": "invalid_argument",
            "code": "INVALID_INPUT_ENCODING",
            "target_file_id": str(target_uuid),
            "failure_detail": "Observation inputs must be valid UTF-8 without NUL.",
        }

    if not isinstance(include_line_starts, bool):
        return {
            "status": "invalid_argument",
            "code": "INVALID_ARGUMENT",
            "target_file_id": str(target_uuid),
            "failure_detail": "include_line_starts must be a boolean.",
        }
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return {
            "status": "invalid_argument",
            "code": "INVALID_ARGUMENT",
            "target_file_id": str(target_uuid),
            "failure_detail": "offset must be a non-negative integer.",
        }
    if max_chars is not None and (isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1):
        return {
            "status": "invalid_argument",
            "code": "INVALID_ARGUMENT",
            "target_file_id": str(target_uuid),
            "failure_detail": "max_chars must be a positive integer.",
        }
    for field_name, field_val in (("symbol_name", symbol_name), ("kind", kind), ("query", query)):
        if field_val is not None and (not isinstance(field_val, str) or not field_val.strip()):
            return {
                "status": "invalid_argument",
                "code": "INVALID_ARGUMENT",
                "target_file_id": str(target_uuid),
                "failure_detail": f"{field_name} must be a non-empty string when provided.",
            }

    with _transaction(session):
        target = session.get(CloudTargetFiles, target_uuid)
        if target is None:
            return {
                "status": "not_found",
                "code": "TARGET_NOT_FOUND",
                "target_file_id": str(target_uuid),
                "failure_detail": "Target file was not found.",
            }

        if selections is not BATCH_UNSET:
            if any(value is not None for value in (symbol_name, query, observation_id, kind)) or offset != 0:
                return {"status": "invalid_argument", "code": "INVALID_BATCH_REQUEST",
                        "failure_detail": "selections cannot be combined with single selectors, paging or kind."}
            if target in session.dirty or session.is_modified(target):
                return {"status": "invalid_argument", "code": "INVALID_BATCH_REQUEST",
                        "failure_detail": "Cannot issue a bundle over pending caller-local target changes."}
            # Refresh the entire row together, so a caller's identity map cannot mix snapshots.
            with session.no_autoflush:
                target = session.execute(select(CloudTargetFiles).where(
                    CloudTargetFiles.target_file_id == target_uuid).execution_options(populate_existing=True)).scalar_one()
            return _issue_bundle(session, target, selections, max_chars=max_chars,
                                 include_line_starts=include_line_starts, timeout_seconds=timeout_seconds)

        # Mode 1: Paginated read of an already-issued observation_id
        if observation_id is not None:
            if symbol_name is not None or query is not None:
                return {
                    "status": "invalid_argument",
                    "code": "CONFLICTING_OBSERVATION_ARGUMENTS",
                    "target_file_id": str(target.target_file_id),
                    "failure_detail": "observation_id cannot be combined with symbol_name or query.",
                }
            obs_uuid = _try_coerce_uuid(observation_id)
            if obs_uuid is None:
                return {
                    "status": "invalid_argument",
                    "code": "INVALID_OBSERVATION_ID",
                    "target_file_id": str(target.target_file_id),
                    "failure_detail": "observation_id must be a valid UUID.",
                }
            obs = session.get(TargetScopeObservations, obs_uuid)
            if obs is None or obs.target_file_id != target.target_file_id:
                return {
                    "status": "rejected",
                    "code": "UNKNOWN_OBSERVATION_ID",
                    "target_file_id": str(target.target_file_id),
                    "target_version": target.version,
                    "target_current_hash": target.current_hash,
                    "failure_detail": "observation_id was not found for this target.",
                }
            if obs.editing_cycle_id != target.active_editing_cycle_id:
                return {
                    "status": "rejected",
                    "code": "OBSERVATION_CYCLE_MISMATCH",
                    "target_file_id": str(target.target_file_id),
                    "target_version": target.version,
                    "target_current_hash": target.current_hash,
                    "failure_detail": "observation_id belongs to a closed editing cycle.",
                }
            if obs.accepted_pdcp_log_id is not None:
                return {
                    "status": "rejected",
                    "code": "OBSERVATION_ALREADY_CONSUMED",
                    "target_file_id": str(target.target_file_id),
                    "target_version": target.version,
                    "target_current_hash": target.current_hash,
                    "failure_detail": "observation_id was already consumed by an accepted transaction.",
                }
            if obs.target_version != target.version:
                return {
                    "status": "rejected",
                    "code": "STALE_OBSERVATION_VERSION",
                    "target_file_id": str(target.target_file_id),
                    "target_version": target.version,
                    "target_current_hash": target.current_hash,
                    "observed_target_version": obs.target_version,
                    "failure_detail": "Target version has advanced since this observation was issued.",
                }
            if obs.target_current_hash != target.current_hash:
                return {
                    "status": "rejected",
                    "code": "STALE_OBSERVATION_HASH",
                    "target_file_id": str(target.target_file_id),
                    "target_version": target.version,
                    "target_current_hash": target.current_hash,
                    "observed_target_hash": obs.target_current_hash,
                    "failure_detail": "Target content hash does not match the recorded observation.",
                }
            try:
                page = _scope_page(
                    target.current_content,
                    scope_start=obs.scope_start,
                    scope_end=obs.scope_end,
                    start_line=obs.start_line,
                    end_line=obs.end_line,
                    offset=offset,
                    max_chars=max_chars,
                    include_line_starts=include_line_starts,
                )
            except ValueError as exc:
                return {
                    "status": "invalid_argument",
                    "code": "INVALID_SCOPE_PAGE_OFFSET",
                    "target_file_id": str(target.target_file_id),
                    "failure_detail": str(exc),
                }
            return {
                "status": "observed",
                "mode": "scope_page",
                "observation_id": str(obs.observation_id),
                "target_file_id": str(target.target_file_id),
                "target_version": target.version,
                "target_current_hash": target.current_hash,
                "waymark_engine_version": obs.waymark_engine_version,
                "language": obs.language,
                "symbol": {
                    "name": obs.symbol_name,
                    "kind": obs.symbol_kind,
                    "parent": obs.symbol_parent,
                    "start_line": obs.start_line,
                    "start_column": obs.start_column,
                    "end_line": obs.end_line,
                    "end_column": obs.end_column,
                },
                "observed_scope_hash": obs.observed_scope_hash,
                "created_at": obs.created_at.isoformat() if obs.created_at else None,
                **page,
            }

        # Run Waymark discovery on authoritative PostgreSQL target content
        discovery = discover_symbols_from_content(
            filename=target.filename,
            content=target.current_content,
            query=query if symbol_name is None else None,
            kind=kind,
            timeout_seconds=timeout_seconds,
        )
        if not discovery.ok:
            err = discovery.error
            return {
                "status": "discovery_error",
                "code": err.code if err else "WAYMARK_DISCOVERY_ERROR",
                "failure_detail": err.message if err else "Waymark discovery failed.",
                "target_file_id": str(target.target_file_id),
                "target_version": target.version,
                "target_current_hash": target.current_hash,
                "waymark_engine_version": discovery.waymark_engine_version,
                "error": err.to_dict() if err else None,
            }

        try:
            all_candidates = [
                (sym, _candidate_dict(target.current_content, sym))
                for sym in discovery.symbols
            ]
        except ScopeCoordinateConversionError as exc:
            return {
                "status": "discovery_error",
                "code": "COORDINATE_CONVERSION_ERROR",
                "failure_detail": str(exc),
                "target_file_id": str(target.target_file_id),
                "target_version": target.version,
                "target_current_hash": target.current_hash,
                "waymark_engine_version": discovery.waymark_engine_version,
            }

        # Mode 2: Candidate discovery (no symbol_name specified)
        if symbol_name is None:
            bounded = [cand for _, cand in all_candidates[:MAX_OBSERVE_CANDIDATES]]
            return {
                "status": "candidates",
                "mode": "candidate_discovery",
                "observation_id": None,
                "target_file_id": str(target.target_file_id),
                "target_version": target.version,
                "target_current_hash": target.current_hash,
                "waymark_engine_version": discovery.waymark_engine_version,
                "language": discovery.language,
                "query": query,
                "kind": kind,
                "total_candidates": len(all_candidates),
                "candidates_truncated": len(all_candidates) > MAX_OBSERVE_CANDIDATES,
                "candidates": bounded,
            }

        # Mode 3: Exact scope selection (symbol_name specified)
        matching = [
            (sym, cand)
            for sym, cand in all_candidates
            if _symbol_matches_selection(sym, symbol_name=symbol_name, kind=kind)
        ]
        if not matching:
            return {
                "status": "not_found",
                "code": "SCOPE_NOT_FOUND",
                "failure_detail": (
                    f"No structural symbol matching symbol_name={symbol_name!r}"
                    + (f" and kind={kind!r}" if kind is not None else "")
                    + f" was found in {target.filename!r}."
                ),
                "observation_id": None,
                "target_file_id": str(target.target_file_id),
                "target_version": target.version,
                "target_current_hash": target.current_hash,
                "waymark_engine_version": discovery.waymark_engine_version,
                "language": discovery.language,
                "candidates": [cand for _, cand in all_candidates[:MAX_OBSERVE_CANDIDATES]],
            }

        if len(matching) > 1:
            return {
                "status": "ambiguous",
                "code": "AMBIGUOUS_SCOPE_SELECTION",
                "failure_detail": (
                    f"Symbol selection symbol_name={symbol_name!r}"
                    + (f" and kind={kind!r}" if kind is not None else "")
                    + f" matched {len(matching)} symbols; specify a unique symbol_name and kind."
                ),
                "observation_id": None,
                "target_file_id": str(target.target_file_id),
                "target_version": target.version,
                "target_current_hash": target.current_hash,
                "waymark_engine_version": discovery.waymark_engine_version,
                "language": discovery.language,
                "total_candidates": len(matching),
                "candidates_truncated": len(matching) > MAX_OBSERVE_CANDIDATES,
                "candidates": [cand for _, cand in matching[:MAX_OBSERVE_CANDIDATES]],
            }

        selected_sym, selected_cand = matching[0]
        scope_start = selected_cand["scope_start"]
        scope_end = selected_cand["scope_end"]
        scope_slice = target.current_content[scope_start:scope_end]
        observed_scope_hash = canonical_sha256(scope_slice)

        try:
            page = _scope_page(
                target.current_content,
                scope_start=scope_start,
                scope_end=scope_end,
                start_line=selected_sym.start.line,
                end_line=selected_sym.end.line,
                offset=offset,
                max_chars=max_chars,
                include_line_starts=include_line_starts,
            )
        except ValueError as exc:
            return {
                "status": "invalid_argument",
                "code": "INVALID_SCOPE_PAGE_OFFSET",
                "target_file_id": str(target.target_file_id),
                "failure_detail": str(exc),
            }

        obs_id = uuid.uuid4()
        obs_row = TargetScopeObservations(
            observation_id=obs_id,
            target_file_id=target.target_file_id,
            editing_cycle_id=target.active_editing_cycle_id,
            target_version=target.version,
            target_current_hash=target.current_hash,
            waymark_engine_version=discovery.waymark_engine_version or EXPECTED_WAYMARK_ENGINE_VERSION,
            language=discovery.language or "unknown",
            symbol_name=selected_sym.name,
            symbol_kind=selected_sym.kind,
            symbol_parent=selected_sym.parent,
            start_line=selected_sym.start.line,
            start_column=selected_sym.start.column,
            end_line=selected_sym.end.line,
            end_column=selected_sym.end.column,
            scope_start=scope_start,
            scope_end=scope_end,
            observed_scope_hash=observed_scope_hash,
        )
        session.add(obs_row)
        session.flush()

        return {
            "status": "observed",
            "mode": "exact_selection",
            "observation_id": str(obs_row.observation_id),
            "target_file_id": str(target.target_file_id),
            "target_version": target.version,
            "target_current_hash": target.current_hash,
            "waymark_engine_version": obs_row.waymark_engine_version,
            "language": obs_row.language,
            "symbol": {
                "name": selected_sym.name,
                "kind": selected_sym.kind,
                "parent": selected_sym.parent,
                "signature": selected_sym.signature,
                "start_line": selected_sym.start.line,
                "start_column": selected_sym.start.column,
                "end_line": selected_sym.end.line,
                "end_column": selected_sym.end.column,
            },
            "observed_scope_hash": observed_scope_hash,
            "created_at": obs_row.created_at.isoformat() if obs_row.created_at else None,
            **page,
        }


@timed("observation_validation")
def validate_observation_for_locked_target(
    session: Session,
    *,
    target: CloudTargetFiles,
    observation_id: Any,
    expected_target_version: int | None,
    expected_current_hash: str | None,
    _discovery=None,
) -> ValidatedScopeObservation | ObservationValidationFailure:
    """Validate a server-issued `observation_id` against a `SELECT ... FOR UPDATE` locked target row."""
    if observation_id is None or (isinstance(observation_id, str) and not observation_id.strip()):
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_MISSING,
            failure_detail="observation_id is required for observed scope submission.",
            code="OBSERVATION_REQUIRED",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={"code": "OBSERVATION_REQUIRED"},
        )

    obs_uuid = _try_coerce_uuid(observation_id)
    if obs_uuid is None:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="observation_id must be a valid UUID.",
            code="INVALID_OBSERVATION_ID",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={"code": "INVALID_OBSERVATION_ID", "raw_observation_id": safe_input_text(observation_id)},
        )

    if expected_target_version is None or expected_current_hash is None:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_MISSING,
            failure_detail="Both expected_target_version and expected_current_hash are required for observed scope submission.",
            code="OBSERVATION_GUARDS_REQUIRED",
            stage=ValidationStage.PROTOCOL_VALIDATION,
            diagnostic={"code": "OBSERVATION_GUARDS_REQUIRED", "observation_id": str(obs_uuid)},
        )

    with session.no_autoflush:
        obs = session.execute(
            select(TargetScopeObservations)
            .where(TargetScopeObservations.observation_id == obs_uuid)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    if obs is None:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="observation_id was not issued by this server or does not exist.",
            code="UNKNOWN_OBSERVATION_ID",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={"code": "UNKNOWN_OBSERVATION_ID", "observation_id": str(obs_uuid)},
        )

    if obs.target_file_id != target.target_file_id:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="observation_id belongs to a different target_file_id.",
            code="OBSERVATION_TARGET_MISMATCH",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVATION_TARGET_MISMATCH",
                "observation_id": str(obs.observation_id),
                "observation_target_file_id": str(obs.target_file_id),
                "submitted_target_file_id": str(target.target_file_id),
            },
        )

    if obs.editing_cycle_id != target.active_editing_cycle_id:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="observation_id belongs to a closed editing cycle.",
            code="OBSERVATION_CYCLE_MISMATCH",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVATION_CYCLE_MISMATCH",
                "observation_id": str(obs.observation_id),
                "observation_editing_cycle_id": str(obs.editing_cycle_id),
                "active_editing_cycle_id": str(target.active_editing_cycle_id),
            },
        )

    if obs.accepted_pdcp_log_id is not None:
        return ObservationValidationFailure(
            failure_reason=FailureReason.TARGET_VERSION_MISMATCH,
            failure_detail="observation_id has already been consumed by a prior accepted transaction.",
            code="OBSERVATION_ALREADY_CONSUMED",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVATION_ALREADY_CONSUMED",
                "observation_id": str(obs.observation_id),
                "accepted_pdcp_log_id": str(obs.accepted_pdcp_log_id),
            },
        )

    if target.version != obs.target_version:
        return ObservationValidationFailure(
            failure_reason=FailureReason.TARGET_VERSION_MISMATCH,
            failure_detail=(
                f"Observation target_version ({obs.target_version}) does not match "
                f"current locked target version ({target.version})."
            ),
            code="STALE_OBSERVATION_VERSION",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "STALE_OBSERVATION_VERSION",
                "observation_id": str(obs.observation_id),
                "observation_target_version": obs.target_version,
                "current_target_version": target.version,
            },
        )

    if expected_target_version != obs.target_version:
        return ObservationValidationFailure(
            failure_reason=FailureReason.TARGET_VERSION_MISMATCH,
            failure_detail=(
                f"expected_target_version ({expected_target_version}) does not match "
                f"observation target_version ({obs.target_version})."
            ),
            code="OBSERVATION_VERSION_MISMATCH",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVATION_VERSION_MISMATCH",
                "observation_id": str(obs.observation_id),
                "observation_target_version": obs.target_version,
                "expected_target_version": expected_target_version,
            },
        )

    if target.current_hash != obs.target_current_hash:
        return ObservationValidationFailure(
            failure_reason=FailureReason.TARGET_HASH_MISMATCH,
            failure_detail="Observation target_current_hash does not match current locked target hash.",
            code="STALE_OBSERVATION_HASH",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "STALE_OBSERVATION_HASH",
                "observation_id": str(obs.observation_id),
                "observation_target_hash": obs.target_current_hash,
                "current_target_hash": target.current_hash,
            },
        )

    if expected_current_hash != obs.target_current_hash:
        return ObservationValidationFailure(
            failure_reason=FailureReason.TARGET_HASH_MISMATCH,
            failure_detail="expected_current_hash does not match observation target_current_hash.",
            code="OBSERVATION_HASH_MISMATCH",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVATION_HASH_MISMATCH",
                "observation_id": str(obs.observation_id),
                "observation_target_hash": obs.target_current_hash,
                "expected_current_hash": expected_current_hash,
            },
        )

    if obs.waymark_engine_version != EXPECTED_WAYMARK_ENGINE_VERSION:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail=(
                f"Observation waymark_engine_version ({obs.waymark_engine_version!r}) "
                f"does not match pinned {EXPECTED_WAYMARK_ENGINE_VERSION!r}."
            ),
            code="OBSERVATION_ENGINE_VERSION_MISMATCH",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVATION_ENGINE_VERSION_MISMATCH",
                "observation_id": str(obs.observation_id),
                "observation_waymark_version": obs.waymark_engine_version,
                "expected_waymark_version": EXPECTED_WAYMARK_ENGINE_VERSION,
            },
        )

    if not (0 <= obs.scope_start <= obs.scope_end <= len(target.current_content)):
        return ObservationValidationFailure(
            failure_reason=FailureReason.SPAN_OUT_OF_BOUNDS,
            failure_detail="Observed scope boundaries fall outside locked target content.",
            code="OBSERVED_SCOPE_OUT_OF_BOUNDS",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVED_SCOPE_OUT_OF_BOUNDS",
                "observation_id": str(obs.observation_id),
                "scope_start": obs.scope_start,
                "scope_end": obs.scope_end,
            },
        )

    current_scope_slice = target.current_content[obs.scope_start : obs.scope_end]
    current_scope_hash = canonical_sha256(current_scope_slice)
    if current_scope_hash != obs.observed_scope_hash:
        return ObservationValidationFailure(
            failure_reason=FailureReason.TARGET_HASH_MISMATCH,
            failure_detail="Locked target scope slice hash does not match observed_scope_hash.",
            code="OBSERVED_SCOPE_HASH_MISMATCH",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVED_SCOPE_HASH_MISMATCH",
                "observation_id": str(obs.observation_id),
                "observed_scope_hash": obs.observed_scope_hash,
                "current_scope_hash": current_scope_hash,
            },
        )

    # Re-verify Waymark symbol identity and boundaries against the locked target state
    discovery = _discovery if _discovery is not None else discover_symbols_from_content(
        filename=target.filename,
        content=target.current_content,
        kind=obs.symbol_kind,
        _locked_submission=True,
    )
    if not discovery.ok:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail=(
                f"Waymark re-verification failed on locked target: "
                f"{discovery.error.message if discovery.error else 'unknown error'}"
            ),
            code=discovery.error.code if discovery.error else "WAYMARK_DISCOVERY_ERROR",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": discovery.error.code if discovery.error else "WAYMARK_DISCOVERY_ERROR",
                "observation_id": str(obs.observation_id),
            },
        )

    matching_symbols = [
        sym
        for sym in discovery.symbols
        if sym.name == obs.symbol_name
        and sym.kind == obs.symbol_kind
        and sym.parent == obs.symbol_parent
    ]
    if len(matching_symbols) != 1:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail=(
                f"Observed symbol {obs.symbol_name!r} ({obs.symbol_kind}) no longer resolves "
                f"uniquely on the locked target (matched {len(matching_symbols)})."
            ),
            code="OBSERVED_SCOPE_DRIFT",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVED_SCOPE_DRIFT",
                "observation_id": str(obs.observation_id),
                "symbol_name": obs.symbol_name,
                "symbol_kind": obs.symbol_kind,
                "matches_found": len(matching_symbols),
            },
        )

    try:
        recomputed_start, recomputed_end = waymark_span_to_code_point_offsets(
            target.current_content,
            matching_symbols[0].start,
            matching_symbols[0].end,
        )
    except ScopeCoordinateConversionError as exc:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail=f"Failed to convert recomputed symbol coordinates: {exc}",
            code="OBSERVED_SCOPE_DRIFT",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={"code": "OBSERVED_SCOPE_DRIFT", "observation_id": str(obs.observation_id)},
        )

    if recomputed_start != obs.scope_start or recomputed_end != obs.scope_end:
        return ObservationValidationFailure(
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="Recomputed Waymark scope boundaries do not match recorded observation boundaries.",
            code="OBSERVED_SCOPE_DRIFT",
            stage=ValidationStage.PRECONDITION_GUARD,
            diagnostic={
                "code": "OBSERVED_SCOPE_DRIFT",
                "observation_id": str(obs.observation_id),
                "recorded_scope": [obs.scope_start, obs.scope_end],
                "recomputed_scope": [recomputed_start, recomputed_end],
            },
        )

    return ValidatedScopeObservation(
        observation=obs,
        scope_start=obs.scope_start,
        scope_end=obs.scope_end,
        observed_scope_hash=obs.observed_scope_hash,
    )


def _issue_bundle(session, target, selections, *, max_chars, include_line_starts, timeout_seconds):
    def fail(code, detail, index=None):
        return {"status": "rejected", "code": code, "failure_detail": detail,
                "target_file_id": str(target.target_file_id),
                **({"selection_index": index} if index is not None else {})}

    if not isinstance(selections, list) or not selections:
        return fail("INVALID_BATCH_REQUEST", "selections must contain 1..32 exact selectors.")
    if len(selections) > MAX_BATCH_SCOPES:
        return fail("BATCH_LIMIT_EXCEEDED", "At most 32 selections are allowed.")
    seen = set()
    for index, selector in enumerate(selections):
        if (not isinstance(selector, dict) or set(selector) - {"symbol_name", "kind"}
                or "symbol_name" not in selector or any(not isinstance(v, str) or not v.strip() for v in selector.values())):
            return fail("INVALID_BATCH_REQUEST", "Each selector needs symbol_name and optional kind.", index)
        key = (selector["symbol_name"], selector.get("kind"))
        if key in seen:
            return fail("BUNDLE_SCOPE_DUPLICATE", "Duplicate selector.", index)
        seen.add(key)
    discovery = discover_symbols_from_content(filename=target.filename, content=target.current_content,
                                               timeout_seconds=timeout_seconds)
    if not discovery.ok:
        return fail(discovery.error.code if discovery.error else "WAYMARK_DISCOVERY_ERROR",
                    discovery.error.message if discovery.error else "Discovery failed.")
    resolved, pages, scopes = [], [], []
    for index, selector in enumerate(selections):
        matching = [sym for sym in discovery.symbols if _symbol_matches_selection(sym, **selector)]
        if len(matching) != 1:
            return fail("BUNDLE_SELECTION_NOT_FOUND" if not matching else "BUNDLE_SELECTION_AMBIGUOUS",
                        "Exact selector must resolve uniquely.", index)
        sym = matching[0]
        try:
            start, end = waymark_span_to_code_point_offsets(target.current_content, sym.start, sym.end)
        except ScopeCoordinateConversionError as exc:
            return fail("INVALID_BATCH_REQUEST", str(exc), index)
        if start == end:
            return fail("INVALID_BATCH_REQUEST", "Selected scope must be nonempty.", index)
        if any((start, end) == (s.scope_start, s.scope_end) for s in scopes):
            return fail("BUNDLE_SCOPE_DUPLICATE", "Selectors refer to the same scope.", index)
        if any(start < s.scope_end and s.scope_start < end for s in scopes):
            return fail("BUNDLE_SCOPE_OVERLAP", "Nested and overlapping scopes are forbidden.", index)
        scope = BatchScope(str(uuid.uuid4()), index, start, end, canonical_sha256(target.current_content[start:end]))
        scopes.append(scope)
        if sum(s.scope_end - s.scope_start for s in scopes) > MAX_BATCH_TOTAL_SCOPE_CHARS:
            return fail("BATCH_LIMIT_EXCEEDED", "Selected contents exceed 65,536 code points.", index)
        page = _scope_page(target.current_content, scope_start=start, scope_end=end,
                           start_line=sym.start.line, end_line=sym.end.line, max_chars=max_chars,
                           include_line_starts=include_line_starts)
        pages.append(page)
        if sum(len(p["text"]) for p in pages) > MAX_BATCH_INITIAL_TEXT_CHARS:
            return fail("BUNDLE_RESPONSE_TOO_LARGE", "Initial pages exceed 32,768 code points.", index)
        resolved.append(sym)
    bundle_id = uuid.uuid4()
    entries = []
    # Nothing is persisted until every selection and both aggregate limits pass.
    for scope, sym, page in zip(scopes, resolved, pages):
        session.add(TargetScopeObservations(
            observation_id=uuid.UUID(scope.observation_id), observation_bundle_id=bundle_id, bundle_ordinal=scope.bundle_ordinal,
            target_file_id=target.target_file_id, editing_cycle_id=target.active_editing_cycle_id,
            target_version=target.version, target_current_hash=target.current_hash,
            waymark_engine_version=discovery.waymark_engine_version or EXPECTED_WAYMARK_ENGINE_VERSION,
            language=discovery.language or "unknown", symbol_name=sym.name, symbol_kind=sym.kind,
            symbol_parent=sym.parent, start_line=sym.start.line, start_column=sym.start.column,
            end_line=sym.end.line, end_column=sym.end.column, scope_start=scope.scope_start, scope_end=scope.scope_end,
            observed_scope_hash=scope.observed_scope_hash))
        entries.append({"observation_id": scope.observation_id, "ordinal": scope.bundle_ordinal,
                        "symbol": {"name": sym.name, "kind": sym.kind, "parent": sym.parent},
                        "observed_scope_hash": scope.observed_scope_hash, **page})
    session.flush()
    return {"status": "observed_batch", "observation_bundle_id": str(bundle_id),
            "target_file_id": str(target.target_file_id), "target_version": target.version,
            "target_current_hash": target.current_hash, "waymark_engine_version": discovery.waymark_engine_version,
            "language": discovery.language, "scopes": entries}


def batch_scope_evidence(obs, group_index, operation_count):
    fields = ("bundle_ordinal", "scope_start", "scope_end", "observed_scope_hash", "symbol_name", "symbol_kind",
              "symbol_parent", "start_line", "start_column", "end_line", "end_column", "waymark_engine_version", "language")
    return {"observation_id": str(obs.observation_id), "group_index": group_index,
            "operation_indices": list(range(operation_count)), **{field: getattr(obs, field) for field in fields}}


def validate_bundle_for_locked_target(session, *, target, record, observation_ids):
    bundle_id = uuid.UUID(record["observation_bundle_id"])
    with session.no_autoflush:
        rows = session.scalars(select(TargetScopeObservations).where(
            TargetScopeObservations.observation_bundle_id == bundle_id).order_by(
            TargetScopeObservations.bundle_ordinal).with_for_update().execution_options(populate_existing=True)).all()
    if not rows:
        raise BatchValidationError("BUNDLE_NOT_FOUND", "Bundle was not issued by this server.")
    # All members were issued together; even unused members retain their original snapshot identity.
    by_id = {str(row.observation_id): row for row in rows}
    chosen = []
    for index, observation_id in enumerate(observation_ids):
        obs = by_id.get(observation_id)
        if obs is None:
            raise BatchValidationError("BATCH_GROUP_INVALID", "Observation does not belong to this bundle.",
                                       group_index=index, observation_id=observation_id)
        for condition, code, detail in (
            (obs.target_file_id != target.target_file_id, "BUNDLE_TARGET_MISMATCH", "Bundle belongs to another target."),
            (obs.editing_cycle_id != target.active_editing_cycle_id, "BUNDLE_CYCLE_MISMATCH", "Bundle belongs to a closed cycle."),
            (obs.accepted_pdcp_log_id is not None, "BUNDLE_ALREADY_CONSUMED", "Observation was already consumed."),
            (obs.target_version != target.version or obs.target_version != record["expected_target_version"],
             "BUNDLE_VERSION_MISMATCH", "Bundle version differs from the locked snapshot."),
            (obs.target_current_hash != target.current_hash or obs.target_current_hash != record["expected_current_hash"],
             "BUNDLE_HASH_MISMATCH", "Bundle preimage hash differs from the locked snapshot."),
        ):
            if condition:
                raise BatchValidationError(code, detail, group_index=index, observation_id=observation_id)
        chosen.append(obs)
    discovery = discover_symbols_from_content(filename=target.filename, content=target.current_content,
                                              _locked_submission=True)
    for index, obs in enumerate(chosen):
        checked = validate_observation_for_locked_target(
            session, target=target, observation_id=obs.observation_id,
            expected_target_version=record["expected_target_version"], expected_current_hash=record["expected_current_hash"],
            _discovery=discovery)
        if isinstance(checked, ObservationValidationFailure):
            raise BatchValidationError("BATCH_GROUP_INVALID", checked.failure_detail, group_index=index,
                                       observation_id=str(obs.observation_id), underlying_code=checked.code)
    scopes = tuple(BatchScope(str(obs.observation_id), obs.bundle_ordinal, obs.scope_start, obs.scope_end,
                              obs.observed_scope_hash) for obs in chosen)
    validate_scope_set(target.current_content, scopes)
    return chosen, scopes


def _try_coerce_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
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
