"""PatchDIFF MCP tool wrappers backed by service-layer operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.mcp.server import registry
from app.services.export_service import export_target, get_target
from app.services.pdcp_service import SubmitPDCPResult, submit_pdcp
from app.services.prompt_context_service import build_prompt_context
from app.services.regeneration_service import (
    build_regeneration_context,
    build_regeneration_prompt,
    request_regeneration,
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
    with SessionLocal() as session:
        result = initialize_target(
            session,
            filename=filename,
            content=content,
            target_type=content_type,
            project_id=uuid.UUID(project_id) if project_id else None,
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
) -> dict[str, Any]:
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_file_id,
            pdcp_content=pdcp_content,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
            submission_source=source,
            parent_pdcp_log_id=uuid.UUID(parent_pdcp_log_id) if parent_pdcp_log_id else None,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
        )
    return _submit_result_to_payload(result)


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
        "accepted_transactions_replayed": result.accepted_transactions_replayed,
        "failure_reason": result.failure_reason.value if result.failure_reason else None,
        "failure_detail": result.failure_detail,
        "pdcp_log_id": str(result.pdcp_log_id) if result.pdcp_log_id else None,
    }


@registry.register("patchdiff_get_pdcp_log")
def patchdiff_get_pdcp_log(*, target_file_id: str, limit: int = 50) -> dict[str, Any]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(AppendOnlyPdcpLogs)
            .where(AppendOnlyPdcpLogs.target_file_id == uuid.UUID(target_file_id))
            .order_by(AppendOnlyPdcpLogs.log_sequence.desc())
            .limit(limit)
        ).all()
    return {
        "entries": [
            {
                "pdcp_log_id": str(row.pdcp_log_id),
                "status": row.status,
                "failure_reason": row.failure_reason,
                "before_hash": row.before_hash,
                "after_hash": row.after_hash,
                "parent_pdcp_log_id": str(row.parent_pdcp_log_id) if row.parent_pdcp_log_id else None,
                "regeneration_attempt": row.regeneration_attempt,
                "regeneration_source": row.regeneration_source,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@registry.register("patchdiff_get_manifest_ledger")
def patchdiff_get_manifest_ledger(
    *,
    target_file_id: str,
    include_previous_cycles: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, uuid.UUID(target_file_id))
        if target is None:
            return {"entries": []}
        query = select(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target.target_file_id
        )
        if not include_previous_cycles:
            query = query.where(AppendOnlyManifestLedger.editing_cycle_id == target.active_editing_cycle_id)
        rows = session.scalars(query.order_by(AppendOnlyManifestLedger.ledger_sequence)).all()
    return {
        "entries": [
            {
                "change_id": row.change_id,
                "intent": row.intent,
                "input_state": row.input_state,
                "output_state": row.output_state,
                "affected_region": row.affected_region,
                "user_visible_change": row.user_visible_change,
                "risk": row.risk,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
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
) -> dict[str, Any]:
    with SessionLocal() as session:
        result = request_regeneration(
            session,
            pdcp_log_id=pdcp_log_id,
            user_request=user_request,
            regenerated_pdcp_content=regenerated_pdcp_content,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
        )
    if "result" in result and isinstance(result["result"], SubmitPDCPResult):
        result["result"] = _submit_result_to_payload(result["result"])
    return result


def _submit_result_to_payload(result: SubmitPDCPResult) -> dict[str, Any]:
    if result.status == "accepted":
        return {
            "status": "accepted",
            "target_file_id": str(result.target_file_id),
            "before_hash": result.before_hash,
            "after_hash": result.after_hash,
            "version": result.after_version,
            "pdcp_log_id": str(result.pdcp_log_id) if result.pdcp_log_id else None,
            "manifest_entries_added": result.manifest_entries_added,
            "warnings": list(result.warnings),
        }
    return {
        "status": "rejected",
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
    }
