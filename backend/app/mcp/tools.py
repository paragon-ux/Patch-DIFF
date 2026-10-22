"""PatchDIFF MCP tool wrappers backed by service-layer operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.input_text import invalid_text_paths, safe_input_text
from app.core.validity import validity_levels
from app.mcp.server import registry
from app.services.export_service import export_target, get_target
from app.services.pdcp_service import SubmitPDCPResult, submit_edits, submit_pdcp, submit_operations, submit_replacement, preview
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
        "target_file_id": str(result.target_file_id),
        "filename": result.filename,
        "target_type": result.target_type,
        "version": result.version,
        "current_hash": result.current_hash,
        "active_editing_cycle_id": str(result.active_editing_cycle_id),
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
                        offset: int = 0, max_chars: int | None = None) -> dict[str, Any]:
    with SessionLocal() as session:
        return read_lines(session, target_file_id=target_file_id, start_line=start_line,
                          end_line=end_line, offset=offset, max_chars=max_chars)


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
    export_after_save: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as session:
        result = save_target(
            session,
            target_file_id=target_file_id,
            expected_current_hash=expected_current_hash,
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
    query = select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_uuid)
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
    next_sequence = page_rows[-1].log_sequence if has_more and page_rows else None
    entries = []
    for row in page_rows:
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
            "regeneration_source": row.regeneration_source,
            "client_request_id": row.client_request_id,
            "request_fingerprint": row.request_fingerprint,
            "diagnostic": row.diagnostic_json,
            "created_at": row.created_at.isoformat(),
        }
        if include_content:
            entry["pdcp_content"] = row.pdcp_content
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

    has_more = len(rows) > effective_limit
    page_rows = rows[:effective_limit]
    next_sequence = page_rows[-1].ledger_sequence if has_more and page_rows else None
    ordered_rows = list(reversed(page_rows))

    return {
        "entries": [
            {
                "ledger_sequence": row.ledger_sequence,
                "change_id": row.change_id,
                "intent": row.intent,
                "input_state": row.input_state,
                "output_state": row.output_state,
                "affected_region": row.affected_region,
                "user_visible_change": row.user_visible_change,
                "risk": row.risk,
                "origin": row.origin,
                "derived": row.derived_json,
                "created_at": row.created_at.isoformat(),
            }
            for row in ordered_rows
        ],
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
                "failure_detail": result.failure_detail}
    if result.status == "accepted":
        return {
            "status": "accepted",
            **invocation,
            "target_file_id": str(result.target_file_id),
            "before_hash": result.before_hash,
            "after_hash": result.after_hash,
            "version": result.after_version,
            "pdcp_log_id": str(result.pdcp_log_id) if result.pdcp_log_id else None,
            "manifest_entries_added": result.manifest_entries_added,
            "warnings": list(result.warnings),
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
        "current_context": result.current_context,
        "validity": validity_levels("rejected", result.failure_reason, stage=result.validation_stage),
        "deduplicated": result.deduplicated,
        "client_request_id": result.client_request_id,
    }


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
