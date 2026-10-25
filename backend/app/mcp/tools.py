"""PatchDIFF MCP tool wrappers backed by service-layer operations."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import defer

from app.core.input_text import invalid_text_paths, safe_input_text
from app.core.validity import validity_levels
from app.mcp.server import registry
from app.services.export_service import export_target, get_target
from app.services.pdcp_service import SubmitPDCPResult, submit_edits, submit_pdcp, submit_operations, submit_replacement, preview
from app.services.rejection_context import response_current_context
from app.services.prompt_context_service import build_prompt_context
from app.services.regeneration_service import (
    build_regeneration_context,
    build_regeneration_prompt,
    request_regeneration,
)
from app.services.read_service import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    clamp_limit,
    find_occurrences,
    read_target,
    read_lines,
)
from app.services.replay_service import replay_target
from app.services.save_service import save_target
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
)

_UNSET = object()
# include_content pages: later entries stop carrying pdcp_content past this many UTF-8 bytes.
MAX_CONTENT_PAGE_BYTES = 1_048_576
MAX_ATTEMPT_INTENT_CHARS = 256
_TYPED_PROTOCOLS = ("patchdiff-tx/1", "patchdiff-tx/2", "patchdiff-tx/3")


@registry.register("patchdiff_handle_upload")
def patchdiff_handle_upload(
    *,
    filename: str,
    content: str,
    content_type: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    return patchdiff_initialize_target(
        filename=filename,
        content=content,
        content_type=content_type,
        project_id=project_id,
    )


@registry.register("patchdiff_initialize_target")
def patchdiff_initialize_target(
    *,
    filename: str,
    content: str,
    content_type: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    project_uuid: uuid.UUID | None = None
    if project_id is not None:
        project_uuid = _try_coerce_uuid(project_id)
        if project_uuid is None:
            return {
                "status": "invalid_argument",
                "project_id": str(project_id),
                "failure_detail": "project_id is not a valid UUID.",
            }
    with SessionLocal() as session:
        result = initialize_target(
            session,
            filename=filename,
            content=content,
            target_type=content_type,
            project_id=project_uuid,
        )
    return {
        "status": "ok",
        "target_file_id": str(result.target_file_id),
        "filename": result.filename,
        "target_type": result.target_type,
        "version": result.version,
        "current_hash": result.current_hash,
        "active_editing_cycle_id": str(result.active_editing_cycle_id),
        "source_line_endings": result.source_line_endings,
    }


@registry.register("patchdiff_submit_pdcp")
def patchdiff_submit_pdcp(
    *,
    target_file_id: str,
    pdcp_content: str,
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    source: str = "model_response",
    parent_pdcp_log_id: str | None = None,
    regeneration_attempt: int | None = None,
    regeneration_source: str | None = None,
    client_request_id: str | None = None,
    include_correlation_id: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_file_id,
            pdcp_content=pdcp_content,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
            submission_source=source,
            parent_pdcp_log_id=parent_pdcp_log_id,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
            client_request_id=client_request_id,
            include_correlation_id=include_correlation_id,
        )
    return _submit_result_to_payload(result)


@registry.register("patchdiff_submit_edits")
def patchdiff_submit_edits(
    *,
    target_file_id: str,
    intent: str,
    edits: list[dict],
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    source: str = "model_response",
    parent_pdcp_log_id: str | None = None,
    attempt: int | None = None,
    client_request_id: str | None = None,
    include_correlation_id: bool = False,
) -> dict[str, Any]:
    """Typed transaction submit. At least one of expected_target_version / expected_current_hash is required."""

    with SessionLocal() as session:
        result = submit_edits(
            session,
            target_file_id=target_file_id,
            intent=intent,
            edits=edits,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
            submission_source=source,
            parent_pdcp_log_id=parent_pdcp_log_id,
            attempt=attempt,
            client_request_id=client_request_id,
            include_correlation_id=include_correlation_id,
        )
    return _submit_result_to_payload(result)


@registry.register("patchdiff_submit_operations")
def patchdiff_submit_operations(
    *, target_file_id: str, intent: str, operations: list[dict],
    expected_target_version: int | None = None, expected_current_hash: str | None = None,
    source: str = "model_response", parent_pdcp_log_id: str | None = None,
    attempt: int | None = None, client_request_id: str | None = None, include_correlation_id: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as session:
        result = submit_operations(session, target_file_id=target_file_id, intent=intent, operations=operations,
                                   expected_target_version=expected_target_version, expected_current_hash=expected_current_hash,
                                   submission_source=source, parent_pdcp_log_id=parent_pdcp_log_id, attempt=attempt,
                                   client_request_id=client_request_id, include_correlation_id=include_correlation_id)
    return _submit_result_to_payload(result)


@registry.register("patchdiff_read_target")
def patchdiff_read_target(*, target_file_id: str, start: int = 0, length: int | None = None) -> dict[str, Any]:
    with SessionLocal() as session:
        return read_target(session, target_file_id=target_file_id, start=start, length=length)


@registry.register("patchdiff_submit_replacement")
def patchdiff_submit_replacement(
    *, target_file_id: str, intent: str, replacement: str,
    expected_target_version: int | None = None, expected_current_hash: str | None = None,
    source: str = "model_response", parent_pdcp_log_id: str | None = None,
    attempt: int | None = None, client_request_id: str | None = None, include_correlation_id: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as session:
        result = submit_replacement(session, target_file_id=target_file_id, intent=intent, replacement=replacement,
                                    expected_target_version=expected_target_version, expected_current_hash=expected_current_hash,
                                    submission_source=source, parent_pdcp_log_id=parent_pdcp_log_id, attempt=attempt,
                                    client_request_id=client_request_id, include_correlation_id=include_correlation_id)
    return _submit_result_to_payload(result)


@registry.register("patchdiff_read_lines")
def patchdiff_read_lines(*, target_file_id: str, start_line: int = 1, end_line: int | None = None,
                        offset: int = 0, max_chars: int | None = None, include_line_starts: bool = False) -> dict[str, Any]:
    with SessionLocal() as session:
        return read_lines(session, target_file_id=target_file_id, start_line=start_line,
                          end_line=end_line, offset=offset, max_chars=max_chars,
                          include_line_starts=include_line_starts)


@registry.register("patchdiff_preview")
def patchdiff_preview(
    *, target_file_id: str, format: str, intent: str | None = _UNSET, edits: list[dict] | None = _UNSET,
    operations: list[dict] | None = _UNSET, replacement: str | None = _UNSET, pdcp_content: str | None = _UNSET,
    expected_target_version: int | None = None, expected_current_hash: str | None = None,
) -> dict[str, Any]:
    proposal = {key: value for key, value in {"intent": intent, "edits": edits, "operations": operations,
                "replacement": replacement, "pdcp_content": pdcp_content}.items() if value is not _UNSET}
    with SessionLocal() as session:
        return preview(session, target_file_id=target_file_id, format=format, **proposal,
                       expected_target_version=expected_target_version, expected_current_hash=expected_current_hash)


@registry.register("patchdiff_find_occurrences")
def patchdiff_find_occurrences(
    *,
    target_file_id: str,
    text: str,
    context_chars: int = 40,
    start_occurrence: int = 1,
    max_results: int = 200,
) -> dict[str, Any]:
    with SessionLocal() as session:
        return find_occurrences(
            session,
            target_file_id=target_file_id,
            text=text,
            context_chars=context_chars,
            start_occurrence=start_occurrence,
            max_results=max_results,
        )


@registry.register("patchdiff_get_target")
def patchdiff_get_target(*, target_file_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        return get_target(session, target_file_id=target_file_id)


@registry.register("patchdiff_export_target")
def patchdiff_export_target(*, target_file_id: str, format: str = "original_text") -> dict[str, Any]:
    with SessionLocal() as session:
        return export_target(session, target_file_id=target_file_id, format=format)


@registry.register("patchdiff_save")
def patchdiff_save(
    *,
    target_file_id: str,
    expected_current_hash: str | None = None,
    expected_target_version: int | None = None,
    export_after_save: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as session:
        result = save_target(
            session,
            target_file_id=target_file_id,
            expected_current_hash=expected_current_hash,
            expected_target_version=expected_target_version,
        )
    payload = {
        "status": result.status,
        "target_file_id": str(result.target_file_id),
        "snapshot_id": str(result.snapshot_id) if result.snapshot_id else None,
        "closed_editing_cycle_id": str(result.closed_editing_cycle_id) if result.closed_editing_cycle_id else None,
        "new_editing_cycle_id": str(result.new_editing_cycle_id) if result.new_editing_cycle_id else None,
        "current_hash": result.current_hash,
        "version": result.version,
        "failure_reason": result.failure_reason.value if result.failure_reason else None,
        "failure_detail": result.failure_detail,
    }
    if export_after_save and result.status == "saved":
        payload["export"] = patchdiff_export_target(target_file_id=target_file_id)
    return payload


@registry.register("patchdiff_replay")
def patchdiff_replay(*, target_file_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        result = replay_target(session, target_file_id=target_file_id)
    return {
        "status": result.status,
        "target_file_id": str(result.target_file_id),
        "reconstructed_hash": result.reconstructed_hash,
        "current_hash": result.current_hash,
        "reconstructed_version": result.reconstructed_version,
        "current_version": result.current_version,
        "materialized_state_matches": result.materialized_state_matches,
        "materialized_state_checks": result.materialized_state_checks,
        "accepted_transactions_replayed": result.accepted_transactions_replayed,
        "failure_reason": result.failure_reason.value if result.failure_reason else None,
        "failure_detail": result.failure_detail,
        "pdcp_log_id": str(result.pdcp_log_id) if result.pdcp_log_id else None,
    }


@registry.register("patchdiff_get_pdcp_log")
def patchdiff_get_pdcp_log(
    *,
    target_file_id: str,
    limit: int | None = None,
    before_sequence: int | None = None,
    status: str | None = None,
    content_hash: str | None = None,
    client_request_id: str | None = None,
    include_content: bool = False,
) -> dict[str, Any]:
    """Newest-first bounded attempts; continue with the smallest returned sequence."""

    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return _history_error(target_file_id, "target_file_id is not a valid UUID.")
    if invalid_text_paths({"limit": limit, "before_sequence": before_sequence, "status": status,
                           "content_hash": content_hash, "client_request_id": client_request_id,
                           "include_content": include_content}):
        return _history_error(target_file_id, "History inputs must be UTF-8 without NUL.")
    if before_sequence is not None and (
        isinstance(before_sequence, bool) or not isinstance(before_sequence, int) or before_sequence < 1
    ):
        return _history_error(target_file_id, "before_sequence must be a positive integer.")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        return _history_error(target_file_id, "limit must be a positive integer.")
    if status is not None and (not isinstance(status, str) or status not in ("accepted", "rejected")):
        return _history_error(target_file_id, "status must be accepted, rejected, or null.")
    for field, value in (("content_hash", content_hash), ("client_request_id", client_request_id)):
        if value is not None and not isinstance(value, str):
            return _history_error(target_file_id, f"{field} must be a string or null.")
    if not isinstance(include_content, bool):
        return _history_error(target_file_id, "include_content must be a boolean.")

    effective_limit = clamp_limit(limit, default=DEFAULT_HISTORY_LIMIT, maximum=MAX_HISTORY_LIMIT)
    query = (
        select(AppendOnlyPdcpLogs)
        .options(defer(AppendOnlyPdcpLogs.pdcp_content))
        .where(AppendOnlyPdcpLogs.target_file_id == target_uuid)
    )
    if before_sequence is not None:
        query = query.where(AppendOnlyPdcpLogs.log_sequence < before_sequence)
    if status is not None:
        query = query.where(AppendOnlyPdcpLogs.status == status)
    if content_hash is not None:
        query = query.where(AppendOnlyPdcpLogs.pdcp_content_hash == content_hash)
    if client_request_id is not None:
        query = query.where(AppendOnlyPdcpLogs.client_request_id == client_request_id)
    with SessionLocal() as session:
        if session.get(CloudTargetFiles, target_uuid) is None:
            return _history_error(target_file_id, status="not_found")
        rows = session.scalars(
            query.order_by(AppendOnlyPdcpLogs.log_sequence.desc()).limit(effective_limit + 1)
        ).all()
        has_more = len(rows) > effective_limit
        page_rows = rows[:effective_limit]
        meta_by_id: dict[uuid.UUID, Any] = {}
        contents_by_id: dict[uuid.UUID, str] = {}
        if page_rows:
            meta_cols = [
                AppendOnlyPdcpLogs.pdcp_log_id,
                _sql_bounded_intent().label("intent"),
                _sql_intent_truncated().label("intent_truncated"),
            ]
            if include_content:
                meta_cols.append(func.octet_length(AppendOnlyPdcpLogs.pdcp_content).label("content_bytes"))
            page_ids = [row.pdcp_log_id for row in page_rows]
            meta_by_id = {
                meta.pdcp_log_id: meta
                for meta in session.execute(
                    select(*meta_cols).where(AppendOnlyPdcpLogs.pdcp_log_id.in_(page_ids))
                ).all()
            }
            if include_content:
                included_ids: list[uuid.UUID] = []
                budget_used = 0
                for row in page_rows:
                    meta = meta_by_id.get(row.pdcp_log_id)
                    size = (
                        (meta.content_bytes or 0)
                        if (meta is not None and hasattr(meta, "content_bytes"))
                        else len(row.pdcp_content.encode("utf-8"))
                    )
                    if not budget_used or budget_used + size <= MAX_CONTENT_PAGE_BYTES:
                        included_ids.append(row.pdcp_log_id)
                        budget_used += size
                for item in session.execute(
                    select(AppendOnlyPdcpLogs.pdcp_log_id, AppendOnlyPdcpLogs.pdcp_content).where(
                        AppendOnlyPdcpLogs.pdcp_log_id.in_(included_ids)
                    )
                ).all():
                    contents_by_id[item.pdcp_log_id] = item.pdcp_content
    next_sequence = page_rows[-1].log_sequence if has_more and page_rows else None
    entries = []
    for row in page_rows:
        meta = meta_by_id.get(row.pdcp_log_id)
        if meta is not None and hasattr(meta, "intent_truncated"):
            intent_val = meta.intent
            intent_trunc = bool(meta.intent_truncated)
        else:
            raw_intent = _record_field(row.protocol_version, row.pdcp_content, "intent")
            intent_val = raw_intent[:MAX_ATTEMPT_INTENT_CHARS] if isinstance(raw_intent, str) else None
            intent_trunc = isinstance(raw_intent, str) and len(raw_intent) > MAX_ATTEMPT_INTENT_CHARS
        entry = {
            "pdcp_log_id": str(row.pdcp_log_id),
            "log_sequence": row.log_sequence,
            "status": row.status,
            "failure_reason": row.failure_reason,
            "failure_detail": row.failure_detail,
            "failed_change_id": row.failed_change_id,
            "before_hash": row.before_hash,
            "after_hash": row.after_hash,
            "before_version": row.before_version,
            "after_version": row.after_version,
            "pdcp_content_hash": row.pdcp_content_hash,
            "protocol_version": row.protocol_version,
            "runtime_version": row.runtime_version,
            "submission_source": row.submission_source,
            "parent_pdcp_log_id": str(row.parent_pdcp_log_id) if row.parent_pdcp_log_id else None,
            "regeneration_attempt": row.regeneration_attempt,
            "attempt": row.regeneration_attempt,
            "regeneration_source": row.regeneration_source,
            "client_request_id": row.client_request_id,
            "request_fingerprint": row.request_fingerprint,
            "diagnostic": row.diagnostic_json,
            "created_at": row.created_at.isoformat(),
            "intent": intent_val,
            "intent_truncated": intent_trunc,
        }
        if include_content:
            if row.pdcp_log_id in contents_by_id:
                # The first entry with content is always whole, so limit=1 can fetch any row.
                entry["pdcp_content"] = contents_by_id[row.pdcp_log_id]
            else:
                entry["pdcp_content"] = None
                entry["pdcp_content_omitted"] = "page_byte_budget"
        entries.append(entry)
    return {"entries": entries, "has_more": has_more, "next_sequence": next_sequence}


@registry.register("patchdiff_get_manifest_ledger")
def patchdiff_get_manifest_ledger(
    *,
    target_file_id: str,
    include_previous_cycles: bool = False,
    limit: int | None = None,
    before_sequence: int | None = None,
) -> dict[str, Any]:
    """Bounded, oldest-first page of accepted manifest ledger entries within the newest page.

    Page backward by passing the smallest returned `ledger_sequence` as `before_sequence`.
    """

    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "target_file_id is not a valid UUID.",
            "entries": [],
            "has_more": False,
            "next_sequence": None,
        }
    if invalid_text_paths({"include_previous_cycles": include_previous_cycles,
                           "limit": limit, "before_sequence": before_sequence}):
        return {"status": "invalid_argument", "target_file_id": str(target_uuid),
                "failure_detail": "History inputs must be UTF-8 without NUL.", "entries": [],
                "has_more": False, "next_sequence": None}
    if not isinstance(include_previous_cycles, bool):
        return _history_error(target_file_id, "include_previous_cycles must be a boolean.")
    if before_sequence is not None and (
        isinstance(before_sequence, bool) or not isinstance(before_sequence, int) or before_sequence < 1
    ):
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "before_sequence must be >= 1.",
            "entries": [],
            "has_more": False,
            "next_sequence": None,
        }
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "limit must be a positive integer.",
            "entries": [],
            "has_more": False,
            "next_sequence": None,
        }

    effective_limit = clamp_limit(limit, default=DEFAULT_HISTORY_LIMIT, maximum=MAX_HISTORY_LIMIT)

    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_uuid)
        if target is None:
            return {
                "status": "not_found",
                "target_file_id": safe_input_text(target_file_id),
                "entries": [],
                "has_more": False,
                "next_sequence": None,
            }
        query = select(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target.target_file_id
        )
        if not include_previous_cycles:
            query = query.where(AppendOnlyManifestLedger.editing_cycle_id == target.active_editing_cycle_id)
        if before_sequence is not None:
            query = query.where(AppendOnlyManifestLedger.ledger_sequence < before_sequence)

        # Fetch effective_limit + 1 rows ordered desc to determine has_more
        rows = session.scalars(
            query.order_by(AppendOnlyManifestLedger.ledger_sequence.desc()).limit(effective_limit + 1)
        ).all()
        page_rows = rows[:effective_limit]
        log_ids = {row.pdcp_log_id for row in page_rows}
        needs_json = any(
            row.origin == "typed" and (row.derived_json or {}).get("operation") != "replace_all"
            for row in page_rows
        )
        log_cols = [
            AppendOnlyPdcpLogs.pdcp_log_id,
            AppendOnlyPdcpLogs.log_sequence,
            AppendOnlyPdcpLogs.before_version,
            AppendOnlyPdcpLogs.after_version,
            AppendOnlyPdcpLogs.protocol_version,
        ]
        if needs_json:
            log_cols.extend((
                _sql_transaction_intent().label("transaction_intent"),
                _sql_rationales().label("rationales"),
            ))
        logs = {
            log.pdcp_log_id: log
            for log in (
                session.execute(select(*log_cols).where(AppendOnlyPdcpLogs.pdcp_log_id.in_(log_ids))).all()
                if log_ids else ()
            )
        }

    has_more = len(rows) > effective_limit
    next_sequence = page_rows[-1].ledger_sequence if has_more and page_rows else None
    ordered_rows = list(reversed(page_rows))

    entries = []
    for row in ordered_rows:
        log = logs.get(row.pdcp_log_id)
        if not needs_json:
            tx_intent = row.intent if (row.origin == "typed" and log and log.protocol_version in _TYPED_PROTOCOLS) else None
            rationale = None
        else:
            if log is not None and hasattr(log, "transaction_intent"):
                tx_intent = (
                    row.intent
                    if (row.origin == "typed" and log.protocol_version == "patchdiff-tx/3")
                    else log.transaction_intent
                )
                rats = log.rationales
                rationale = rats[row.change_index - 1] if isinstance(rats, list) and 0 < row.change_index <= len(rats) else None
            else:
                record = _decoded_record(log.protocol_version, getattr(log, "pdcp_content", None)) if log else None
                items = (record.get("edits") if "edits" in record else record.get("operations")) if record else None
                item = items[row.change_index - 1] if isinstance(items, list) and 0 < row.change_index <= len(items) else None
                tx_intent = record.get("intent") if record else None
                rationale = item.get("rationale") if isinstance(item, dict) else None
        entries.append({
            "ledger_sequence": row.ledger_sequence,
            "pdcp_log_id": str(row.pdcp_log_id),
            "log_sequence": log.log_sequence if log else None,
            "before_version": log.before_version if log else None,
            "after_version": log.after_version if log else None,
            "editing_cycle_id": str(row.editing_cycle_id),
            "change_index": row.change_index,
            "change_id": row.change_id,
            "intent": row.intent,
            "transaction_intent": tx_intent,
            "rationale": rationale,
            "input_state": row.input_state,
            "output_state": row.output_state,
            "affected_region": row.affected_region,
            "user_visible_change": row.user_visible_change,
            "risk": row.risk,
            "origin": row.origin,
            "derived": row.derived_json,
            "created_at": row.created_at.isoformat(),
        })
    return {
        "entries": entries,
        "has_more": has_more,
        "next_sequence": next_sequence,
    }


@registry.register("patchdiff_build_prompt_context")
def patchdiff_build_prompt_context(
    *,
    target_file_id: str,
    user_request: str,
    context_policy: str = "relevant_spans",
) -> dict[str, Any]:
    with SessionLocal() as session:
        return build_prompt_context(
            session,
            target_file_id=target_file_id,
            user_request=user_request,
            context_policy=context_policy,
        )


@registry.register("patchdiff_get_regeneration_context")
def patchdiff_get_regeneration_context(
    *,
    pdcp_log_id: str,
    user_request: str | None = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        return build_regeneration_context(session, pdcp_log_id=pdcp_log_id, user_request=user_request)


@registry.register("patchdiff_build_regeneration_prompt")
def patchdiff_build_regeneration_prompt(
    *,
    pdcp_log_id: str,
    user_request: str | None = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        context = build_regeneration_context(session, pdcp_log_id=pdcp_log_id, user_request=user_request)
        return build_regeneration_prompt(context)


@registry.register("patchdiff_request_regeneration")
def patchdiff_request_regeneration(
    *,
    pdcp_log_id: str,
    user_request: str | None = None,
    regenerated_pdcp_content: str | None = None,
    regeneration_attempt: int = 1,
    regeneration_source: str = "mcp_host",
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        result = request_regeneration(
            session,
            pdcp_log_id=pdcp_log_id,
            user_request=user_request,
            regenerated_pdcp_content=regenerated_pdcp_content,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
        )
    if "result" in result and isinstance(result["result"], SubmitPDCPResult):
        result["result"] = _submit_result_to_payload(result["result"])
    return result


def _submit_result_to_payload(result: SubmitPDCPResult) -> dict[str, Any]:
    invocation = {"correlation_id": result.correlation_id} if result.correlation_id is not None else {}
    if result.status == "invalid_argument":
        return {"status": "invalid_argument", "target_file_id": str(result.target_file_id),
                "failure_detail": result.failure_detail, **invocation,
                **({"code": result.code} if result.code is not None else {}),
                **({"pdcp_log_id": None, "diagnostic": result.diagnostic} if result.diagnostic is not None else {})}
    if result.status == "accepted":
        return {
            "status": "accepted",
            **invocation,
            "target_file_id": str(result.target_file_id),
            "before_hash": result.before_hash,
            "after_hash": result.after_hash,
            "version": result.after_version,
            "current_version": result.current_version,
            "current_hash": result.current_hash,
            "pdcp_log_id": str(result.pdcp_log_id) if result.pdcp_log_id else None,
            "manifest_entries_added": result.manifest_entries_added,
            "warnings": list(result.warnings),
            "warning_details": [dict(item) for item in result.warning_details],
            "warning_count": result.warning_count,
            "warnings_truncated": result.warnings_truncated,
            "validity": validity_levels("accepted", None, stage=result.validation_stage),
            "evidence": {"changes": list(result.change_facts)},
            "deduplicated": result.deduplicated,
            "client_request_id": result.client_request_id,
        }
    return {
        "status": "rejected",
        **invocation,
        **({"near_misses": result.near_misses} if result.near_misses is not None else {}),
        "target_file_id": str(result.target_file_id),
        "failure_reason": result.failure_reason.value if result.failure_reason else None,
        "failure_detail": result.failure_detail,
        "failed_change_id": result.failed_change_id,
        "before_hash": result.before_hash,
        "after_hash": None,
        "current_version": result.current_version,
        "current_hash": result.current_hash,
        "pdcp_log_id": str(result.pdcp_log_id) if result.pdcp_log_id else None,
        "diagnostic": result.diagnostic,
        "current_context": response_current_context(
            result.current_context, (result.diagnostic or {}).get("failure_context")),
        "validity": validity_levels("rejected", result.failure_reason, stage=result.validation_stage),
        "deduplicated": result.deduplicated,
        "client_request_id": result.client_request_id,
    }


_PREFIX_SLICE = 'split_part(left(append_only_pdcp_logs.pdcp_content, 4096), \',"operations":[\', 1) || \'}\''
_SAFE_DOC_SQL = f"""(
    CASE
      WHEN append_only_pdcp_logs.protocol_version IN ('patchdiff-tx/1', 'patchdiff-tx/2', 'patchdiff-tx/3') THEN
        CASE
          WHEN octet_length(append_only_pdcp_logs.pdcp_content) > 65536
               AND strpos(left(append_only_pdcp_logs.pdcp_content, 4096), ',"operations":[') > 0
               AND pg_input_is_valid({_PREFIX_SLICE}, 'jsonb')
          THEN
            CASE
              WHEN jsonb_typeof(({_PREFIX_SLICE})::jsonb) = 'object'
                   AND NOT ((({_PREFIX_SLICE})::jsonb) ? 'evidence_format')
              THEN ({_PREFIX_SLICE})::jsonb
            END
          WHEN pg_input_is_valid(append_only_pdcp_logs.pdcp_content, 'jsonb') THEN
            CASE
              WHEN jsonb_typeof(append_only_pdcp_logs.pdcp_content::jsonb) = 'object'
                   AND NOT ((append_only_pdcp_logs.pdcp_content::jsonb) ? 'evidence_format')
              THEN append_only_pdcp_logs.pdcp_content::jsonb
            END
        END
    END
)"""
_SAFE_TX12_DOC_SQL = """(
    CASE
      WHEN append_only_pdcp_logs.protocol_version IN ('patchdiff-tx/1', 'patchdiff-tx/2') THEN
        CASE
          WHEN pg_input_is_valid(append_only_pdcp_logs.pdcp_content, 'jsonb') THEN
            CASE
              WHEN jsonb_typeof(append_only_pdcp_logs.pdcp_content::jsonb) = 'object'
                   AND NOT ((append_only_pdcp_logs.pdcp_content::jsonb) ? 'evidence_format')
              THEN append_only_pdcp_logs.pdcp_content::jsonb
            END
        END
    END
)"""
_ITEMS_SQL = f"""(
    CASE
      WHEN {_SAFE_TX12_DOC_SQL} IS NOT NULL THEN
        CASE
          WHEN {_SAFE_TX12_DOC_SQL} ? 'edits' THEN {_SAFE_TX12_DOC_SQL} -> 'edits'
          ELSE {_SAFE_TX12_DOC_SQL} -> 'operations'
        END
    END
)"""


def _sql_bounded_intent():
    return literal_column(
        f"(CASE WHEN jsonb_typeof({_SAFE_DOC_SQL} -> 'intent') = 'string' "
        f"THEN left({_SAFE_DOC_SQL} ->> 'intent', {MAX_ATTEMPT_INTENT_CHARS}) END)"
    )


def _sql_intent_truncated():
    return literal_column(
        f"coalesce(jsonb_typeof({_SAFE_DOC_SQL} -> 'intent') = 'string' "
        f"AND char_length({_SAFE_DOC_SQL} ->> 'intent') > {MAX_ATTEMPT_INTENT_CHARS}, false)"
    )


def _sql_transaction_intent():
    return literal_column(f"({_SAFE_DOC_SQL} -> 'intent')")


def _sql_rationales():
    return literal_column(
        f"(CASE WHEN jsonb_typeof({_ITEMS_SQL}) = 'array' THEN "
        f"(SELECT coalesce(jsonb_agg(coalesce(CASE WHEN jsonb_typeof(elem) = 'object' "
        f"THEN elem -> 'rationale' END, 'null'::jsonb)), '[]'::jsonb) "
        f"FROM jsonb_array_elements({_ITEMS_SQL}) AS elem) END)"
    )


def _decoded_record(protocol_version: str | None, content: str | None) -> dict | None:
    """Stored typed record as an object; legacy PDCP and evidence envelopes give None."""
    if protocol_version not in _TYPED_PROTOCOLS or not isinstance(content, str):
        return None
    try:
        record = json.loads(content)
    except ValueError:
        return None
    return record if isinstance(record, dict) and "evidence_format" not in record else None


def _record_field(protocol_version: str | None, content: str | None, field: str) -> Any:
    record = _decoded_record(protocol_version, content)
    return record.get(field) if record else None


def _history_error(
    target_file_id: uuid.UUID | str, failure_detail: str | None = None, *, status: str = "invalid_argument",
) -> dict[str, Any]:
    payload = {"status": status, "target_file_id": safe_input_text(target_file_id),
               "entries": [], "has_more": False, "next_sequence": None}
    if failure_detail is not None:
        payload["failure_detail"] = failure_detail
    return payload


def _try_coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
