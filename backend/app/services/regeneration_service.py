"""Regeneration context and prompt orchestration services."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services.pdcp_service import submit_pdcp
from app.services.prompt_context_service import build_prompt_context, pdcp_rules_text
from app.storage.models import AppendOnlyPdcpLogs, CloudTargetFiles


def build_regeneration_context(
    session: Session,
    *,
    pdcp_log_id: uuid.UUID | str,
    user_request: str | None = None,
) -> dict[str, Any]:
    log = session.get(AppendOnlyPdcpLogs, _coerce_uuid(pdcp_log_id))
    if log is None:
        return {"status": "not_found", "pdcp_log_id": str(pdcp_log_id)}
    target = session.get(CloudTargetFiles, log.target_file_id)
    if target is None:
        return {"status": "not_found", "target_file_id": str(log.target_file_id)}

    prompt_context = build_prompt_context(
        session,
        target_file_id=target.target_file_id,
        user_request=user_request or "",
        context_policy="relevant_spans",
    )
    return {
        "status": "ready",
        "pdcp_log_id": str(log.pdcp_log_id),
        "target_file_id": str(target.target_file_id),
        "failure_reason": log.failure_reason,
        "failure_detail": log.failure_detail,
        "failed_change_id": log.failed_change_id,
        "diagnostic": log.diagnostic_json,
        "current_version": target.version,
        "current_hash": target.current_hash,
        "manifest_summary": prompt_context["manifest_summary"],
        "fresh_target_context": prompt_context["target_context"],
        "rejected_pdcp_content": log.pdcp_content,
        "pdcp_rules": prompt_context["pdcp_rules"],
        "user_request": user_request,
        "instruction": "Regenerate a fresh declarative .pdcp transaction from scratch and submit it for validation.",
    }


def build_regeneration_prompt(context: dict[str, Any]) -> dict[str, Any]:
    prompt = "\n".join(
        [
            "PatchDIFF regeneration request.",
            f"Original user request: {context.get('user_request') or ''}",
            f"Rejected PDCP log: {context.get('pdcp_log_id')}",
            f"Failure reason: {context.get('failure_reason')}",
            f"Failure detail: {context.get('failure_detail')}",
            f"Failed change id: {context.get('failed_change_id')}",
            f"Current target version: {context.get('current_version')}",
            f"Current target hash: {context.get('current_hash')}",
            "Fresh target context:",
            context.get("fresh_target_context") or "",
            "PDCP rules:",
            context.get("pdcp_rules") or pdcp_rules_text(),
            "Generate a fresh declarative .pdcp transaction. Do not generate executable apply functions or tool calls.",
        ]
    )
    return {
        "status": "ready",
        "target_file_id": context.get("target_file_id"),
        "pdcp_log_id": context.get("pdcp_log_id"),
        "prompt": prompt,
        "context": context,
    }


def request_regeneration(
    session: Session,
    *,
    pdcp_log_id: uuid.UUID | str,
    user_request: str | None = None,
    regenerated_pdcp_content: str | None = None,
    regeneration_attempt: int = 1,
    regeneration_source: str = "mcp_host",
) -> dict[str, Any]:
    context = build_regeneration_context(session, pdcp_log_id=pdcp_log_id, user_request=user_request)
    prompt = build_regeneration_prompt(context)
    if regenerated_pdcp_content is None:
        return {"status": "context_ready", "regeneration_context": context, "regeneration_prompt": prompt}

    log = session.get(AppendOnlyPdcpLogs, _coerce_uuid(pdcp_log_id))
    parent_log_id = log.pdcp_log_id
    target_file_id = log.target_file_id
    if session.in_transaction():
        session.commit()
    result = submit_pdcp(
        session,
        target_file_id=target_file_id,
        pdcp_content=regenerated_pdcp_content,
        submission_source="regeneration",
        parent_pdcp_log_id=parent_log_id,
        regeneration_attempt=regeneration_attempt,
        regeneration_source=regeneration_source,
    )
    return {
        "status": result.status,
        "new_pdcp_log_id": str(result.pdcp_log_id) if result.pdcp_log_id else None,
        "parent_pdcp_log_id": str(parent_log_id),
        "result": result,
    }


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
