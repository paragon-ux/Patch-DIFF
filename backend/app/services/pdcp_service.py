"""Postgres-backed PDCP submission service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.models import (
    REQUIRED_MANIFEST_FIELDS,
    SUPPORTED_MANIFEST_FIELDS,
    SUPPORTED_PROTOCOL_VERSION,
    VALID_RISK_VALUES,
    ParsedPDCP,
)
from app.pdcp.parser import PDCPParseError, parse_pdcp
from app.pdcp.protocol_validator import ProtocolValidationError, validate_pdcp
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    CurrentPdcpFiles,
)
from app.storage.repositories import select_target_for_update

RUNTIME_VERSION = "patchdiff-mvp-0.1.0"


@dataclass(frozen=True, slots=True)
class SubmitPDCPResult:
    status: str
    target_file_id: uuid.UUID
    pdcp_log_id: uuid.UUID | None
    before_hash: str | None
    after_hash: str | None
    before_version: int | None
    after_version: int | None
    current_hash: str | None
    current_version: int | None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None
    failed_change_id: str | None = None
    diagnostic: dict | None = None
    manifest_entries_added: int = 0
    warnings: tuple[str, ...] = ()


def submit_pdcp(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    pdcp_content: str,
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    submission_source: str = "model_response",
    parent_pdcp_log_id: uuid.UUID | None = None,
    regeneration_attempt: int | None = None,
    regeneration_source: str | None = None,
    _before_final_guard=None,
) -> SubmitPDCPResult:
    """Submit a PDCP transaction through deterministic runtime and Postgres commit."""

    target_uuid = _coerce_uuid(target_file_id)
    pdcp_content_hash = canonical_sha256(pdcp_content)

    with _transaction(session):
        target = session.execute(select_target_for_update(str(target_uuid))).scalar_one_or_none()
        if target is None:
            return SubmitPDCPResult(
                status="rejected",
                target_file_id=target_uuid,
                pdcp_log_id=None,
                before_hash=None,
                after_hash=None,
                before_version=None,
                after_version=None,
                current_hash=None,
                current_version=None,
                failure_reason=FailureReason.TARGET_NOT_FOUND,
                failure_detail="Target file was not found.",
            )

        current_pdcp = _upsert_current_pdcp(
            session,
            target=target,
            pdcp_content=pdcp_content,
            pdcp_content_hash=pdcp_content_hash,
            status="pending_validation",
            submission_source=submission_source,
            parent_pdcp_log_id=parent_pdcp_log_id,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
        )
        before_hash = target.current_hash
        before_version = target.version
        before_content = target.current_content

        guard_rejection = _guard_rejection(
            target=target,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
        )
        if guard_rejection is not None:
            return _persist_rejection(
                session,
                target=target,
                current_pdcp=current_pdcp,
                pdcp_content=pdcp_content,
                pdcp_content_hash=pdcp_content_hash,
                expected_target_version=expected_target_version,
                expected_current_hash=expected_current_hash,
                submission_source=submission_source,
                parent_pdcp_log_id=parent_pdcp_log_id,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
                parsed=None,
                rejection=guard_rejection,
                before_hash=before_hash,
                before_version=before_version,
            )

        parsed: ParsedPDCP | None = None
        try:
            parsed = parse_pdcp(pdcp_content)
            validate_pdcp(parsed)
            if parsed.header.target_file_id != str(target_uuid):
                raise ProtocolValidationError(
                    FailureReason.CONTEXT_INVALID,
                    "PDCP target_file_id does not match the submitted target.",
                )
            if parsed.header.target_hash is not None and parsed.header.target_hash != target.current_hash:
                raise ProtocolValidationError(
                    FailureReason.TARGET_HASH_MISMATCH,
                    "PDCP target_hash does not match the current target hash.",
                )
            core_result = apply_pdcp_transaction(target.current_content, parsed)
        except PDCPParseError as exc:
            core_result = _core_rejection(exc.failure_reason, exc.failure_detail, before_hash, exc.failed_change_id)
        except ProtocolValidationError as exc:
            core_result = _core_rejection(exc.failure_reason, exc.failure_detail, before_hash, exc.failed_change_id)

        if isinstance(core_result, RejectedCoreResult):
            return _persist_rejection(
                session,
                target=target,
                current_pdcp=current_pdcp,
                pdcp_content=pdcp_content,
                pdcp_content_hash=pdcp_content_hash,
                expected_target_version=expected_target_version,
                expected_current_hash=expected_current_hash,
                submission_source=submission_source,
                parent_pdcp_log_id=parent_pdcp_log_id,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
                parsed=parsed,
                rejection=core_result,
                before_hash=before_hash,
                before_version=before_version,
            )

        if _before_final_guard is not None:
            _before_final_guard(target)
        if target.version != before_version or target.current_hash != before_hash:
            target.version = before_version
            target.current_hash = before_hash
            target.current_content = before_content
            divergence = _core_rejection(
                FailureReason.TARGET_DIVERGED,
                "Target changed after validation before final commit guard.",
                before_hash,
            )
            return _persist_rejection(
                session,
                target=target,
                current_pdcp=current_pdcp,
                pdcp_content=pdcp_content,
                pdcp_content_hash=pdcp_content_hash,
                expected_target_version=expected_target_version,
                expected_current_hash=expected_current_hash,
                submission_source=submission_source,
                parent_pdcp_log_id=parent_pdcp_log_id,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
                parsed=parsed,
                rejection=divergence,
                before_hash=before_hash,
                before_version=before_version,
            )

        return _persist_acceptance(
            session,
            target=target,
            current_pdcp=current_pdcp,
            pdcp_content=pdcp_content,
            pdcp_content_hash=pdcp_content_hash,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
            submission_source=submission_source,
            parent_pdcp_log_id=parent_pdcp_log_id,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
            parsed=parsed,
            accepted=core_result,
            before_version=before_version,
        )


def _guard_rejection(
    *,
    target: CloudTargetFiles,
    expected_target_version: int | None,
    expected_current_hash: str | None,
) -> RejectedCoreResult | None:
    if expected_target_version is not None and target.version != expected_target_version:
        return _core_rejection(
            FailureReason.TARGET_VERSION_MISMATCH,
            "expected_target_version does not match the current target version.",
            target.current_hash,
        )
    if expected_current_hash is not None and target.current_hash != expected_current_hash:
        return _core_rejection(
            FailureReason.TARGET_HASH_MISMATCH,
            "expected_current_hash does not match the current target hash.",
            target.current_hash,
        )
    return None


def _persist_acceptance(
    session: Session,
    *,
    target: CloudTargetFiles,
    current_pdcp: CurrentPdcpFiles,
    pdcp_content: str,
    pdcp_content_hash: str,
    expected_target_version: int | None,
    expected_current_hash: str | None,
    submission_source: str,
    parent_pdcp_log_id: uuid.UUID | None,
    regeneration_attempt: int | None,
    regeneration_source: str | None,
    parsed: ParsedPDCP,
    accepted: AcceptedCoreResult,
    before_version: int,
) -> SubmitPDCPResult:
    after_version = before_version + 1
    log = AppendOnlyPdcpLogs(
        target_file_id=target.target_file_id,
        editing_cycle_id=target.active_editing_cycle_id,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=regeneration_attempt,
        regeneration_source=regeneration_source,
        submission_source=submission_source,
        protocol_version=parsed.header.protocol_version,
        runtime_version=RUNTIME_VERSION,
        pdcp_content=pdcp_content,
        pdcp_content_hash=pdcp_content_hash,
        status="accepted",
        expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash,
        before_version=before_version,
        after_version=after_version,
        before_hash=accepted.before_hash,
        after_hash=accepted.after_hash,
        change_count=accepted.change_count,
    )
    session.add(log)
    session.flush()

    for change in parsed.changes:
        fields = change.manifest.fields
        session.add(
            AppendOnlyManifestLedger(
                target_file_id=target.target_file_id,
                editing_cycle_id=target.active_editing_cycle_id,
                pdcp_log_id=log.pdcp_log_id,
                change_index=change.change_index,
                change_id=fields["change_id"],
                intent=fields["intent"],
                input_state=fields["input_state"],
                output_state=fields["output_state"],
                affected_region=fields["affected_region"],
                user_visible_change=fields["user_visible_change"],
                risk=fields["risk"],
            )
        )

    target.current_content = accepted.target_content
    target.current_hash = accepted.after_hash
    target.version = after_version
    target.latest_accepted_pdcp_log_id = log.pdcp_log_id
    current_pdcp.status = "accepted"
    current_pdcp.last_pdcp_log_id = log.pdcp_log_id

    return SubmitPDCPResult(
        status="accepted",
        target_file_id=target.target_file_id,
        pdcp_log_id=log.pdcp_log_id,
        before_hash=accepted.before_hash,
        after_hash=accepted.after_hash,
        before_version=before_version,
        after_version=after_version,
        current_hash=accepted.after_hash,
        current_version=after_version,
        manifest_entries_added=len(parsed.changes),
        warnings=(),
    )


def _persist_rejection(
    session: Session,
    *,
    target: CloudTargetFiles,
    current_pdcp: CurrentPdcpFiles,
    pdcp_content: str,
    pdcp_content_hash: str,
    expected_target_version: int | None,
    expected_current_hash: str | None,
    submission_source: str,
    parent_pdcp_log_id: uuid.UUID | None,
    regeneration_attempt: int | None,
    regeneration_source: str | None,
    parsed: ParsedPDCP | None,
    rejection: RejectedCoreResult,
    before_hash: str,
    before_version: int,
) -> SubmitPDCPResult:
    log = AppendOnlyPdcpLogs(
        target_file_id=target.target_file_id,
        editing_cycle_id=target.active_editing_cycle_id,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=regeneration_attempt,
        regeneration_source=regeneration_source,
        submission_source=submission_source,
        protocol_version=parsed.header.protocol_version if parsed else SUPPORTED_PROTOCOL_VERSION,
        runtime_version=RUNTIME_VERSION,
        pdcp_content=pdcp_content,
        pdcp_content_hash=pdcp_content_hash,
        status="rejected",
        failure_reason=rejection.failure_reason.value,
        failure_detail=rejection.failure_detail,
        failed_change_id=rejection.failed_change_id,
        diagnostic_json=rejection.diagnostic,
        expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash,
        before_version=before_version,
        after_version=None,
        before_hash=before_hash,
        after_hash=None,
        change_count=len(parsed.changes) if parsed else 0,
    )
    session.add(log)
    session.flush()

    current_pdcp.status = "rejected"
    current_pdcp.last_pdcp_log_id = log.pdcp_log_id

    return SubmitPDCPResult(
        status="rejected",
        target_file_id=target.target_file_id,
        pdcp_log_id=log.pdcp_log_id,
        before_hash=before_hash,
        after_hash=None,
        before_version=before_version,
        after_version=None,
        current_hash=target.current_hash,
        current_version=target.version,
        failure_reason=rejection.failure_reason,
        failure_detail=rejection.failure_detail,
        failed_change_id=rejection.failed_change_id,
        diagnostic=rejection.diagnostic,
    )


def _upsert_current_pdcp(
    session: Session,
    *,
    target: CloudTargetFiles,
    pdcp_content: str,
    pdcp_content_hash: str,
    status: str,
    submission_source: str,
    parent_pdcp_log_id: uuid.UUID | None,
    regeneration_attempt: int | None,
    regeneration_source: str | None,
) -> CurrentPdcpFiles:
    existing = session.execute(
        select(CurrentPdcpFiles).where(CurrentPdcpFiles.target_file_id == target.target_file_id)
    ).scalar_one_or_none()
    if existing is None:
        existing = CurrentPdcpFiles(
            target_file_id=target.target_file_id,
            editing_cycle_id=target.active_editing_cycle_id,
            protocol_version=SUPPORTED_PROTOCOL_VERSION,
            pdcp_content=pdcp_content,
            pdcp_content_hash=pdcp_content_hash,
            status=status,
            submission_source=submission_source,
            parent_pdcp_log_id=parent_pdcp_log_id,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
        )
        session.add(existing)
    else:
        existing.editing_cycle_id = target.active_editing_cycle_id
        existing.protocol_version = SUPPORTED_PROTOCOL_VERSION
        existing.pdcp_content = pdcp_content
        existing.pdcp_content_hash = pdcp_content_hash
        existing.status = status
        existing.submission_source = submission_source
        existing.parent_pdcp_log_id = parent_pdcp_log_id
        existing.regeneration_attempt = regeneration_attempt
        existing.regeneration_source = regeneration_source
        existing.last_pdcp_log_id = None
    session.flush()
    return existing


def _core_rejection(
    reason: FailureReason,
    detail: str,
    before_hash: str,
    failed_change_id: str | None = None,
) -> RejectedCoreResult:
    diagnostic = {
        "retryable": reason
        in {
            FailureReason.MATCH_ABSENT,
            FailureReason.MATCH_AMBIGUOUS,
            FailureReason.DISAMBIGUATION_INVALID,
            FailureReason.SEQUENTIAL_MATCH_INVALID,
        },
        "requires_new_pdcp": True,
    }
    if reason == FailureReason.MANIFEST_INVALID:
        diagnostic.update(
            {
                "allowed_manifest_fields": sorted(SUPPORTED_MANIFEST_FIELDS),
                "required_manifest_fields": sorted(REQUIRED_MANIFEST_FIELDS),
                "valid_risk_values": sorted(VALID_RISK_VALUES),
                "manifest_line_format": "# field_name: value",
            }
        )
    return RejectedCoreResult(
        failure_reason=reason,
        failure_detail=detail,
        before_hash=before_hash,
        failed_change_id=failed_change_id,
        diagnostic=diagnostic,
    )


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


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
