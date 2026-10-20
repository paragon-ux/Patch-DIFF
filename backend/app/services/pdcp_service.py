"""Postgres-backed PDCP and typed transaction submission service."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.core.validity import ValidationStage, validity_levels
from app.core.versions import RUNTIME_VERSION
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
from app.pdcp.typed import (
    ALLOWED_TYPED_EDIT_FIELDS,
    REQUIRED_TYPED_EDIT_FIELDS,
    TYPED_PROTOCOL_VERSION,
    TypedTransaction,
    build_record,
    canonical_record_json,
    parse_typed_record,
    to_parsed_transaction,
    validate_client_request_id,
)
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    CurrentPdcpFiles,
)
from app.storage.repositories import select_target_for_update


@dataclass(frozen=True, slots=True)
class SubmitPDCPResult:
    status: str
    target_file_id: uuid.UUID | str
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
    change_facts: tuple[dict, ...] = ()
    validation_stage: ValidationStage | None = None
    deduplicated: bool = False
    client_request_id: str | None = None


def submit_pdcp(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    pdcp_content: str,
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    submission_source: str = "model_response",
    parent_pdcp_log_id: uuid.UUID | str | None = None,
    regeneration_attempt: int | None = None,
    regeneration_source: str | None = None,
    client_request_id: str | None = None,
    _before_final_guard=None,
) -> SubmitPDCPResult:
    """Submit a legacy PDCP v0.2.3 transaction through the deterministic runtime and Postgres commit."""

    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return _invalid_target_uuid_result(target_file_id)

    def decode(target: CloudTargetFiles) -> tuple[ParsedPDCP, TypedTransaction | None]:
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
        return parsed, None

    return _submit(
        session,
        target_uuid=target_uuid,
        record_content=pdcp_content,
        decode=decode,
        protocol_version=SUPPORTED_PROTOCOL_VERSION,
        guard_required=False,
        expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash,
        submission_source=submission_source,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=regeneration_attempt,
        regeneration_source=regeneration_source,
        client_request_id=client_request_id,
        _before_final_guard=_before_final_guard,
    )


def submit_edits(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    intent: Any,
    edits: Any,
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    submission_source: str = "model_response",
    parent_pdcp_log_id: uuid.UUID | str | None = None,
    attempt: int | None = None,
    client_request_id: str | None = None,
    _before_final_guard=None,
) -> SubmitPDCPResult:
    """Submit a typed ``patchdiff-tx/1`` transaction.

    Same trusted path as ``submit_pdcp``: one row lock, one applier, one atomic commit.
    At least one state guard is required. The durable record is the canonical JSON of
    the submitted transaction; no textual PDCP is synthesized.
    """

    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return _invalid_target_uuid_result(target_file_id)

    record = build_record(
        target_file_id=str(target_uuid),
        intent=intent,
        edits=edits,
        expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash,
    )
    record_content = canonical_record_json(record)

    def decode(target: CloudTargetFiles) -> tuple[ParsedPDCP, TypedTransaction | None]:
        typed = parse_typed_record(record)
        return to_parsed_transaction(typed, target_type=target.target_type), typed

    return _submit(
        session,
        target_uuid=target_uuid,
        record_content=record_content,
        decode=decode,
        protocol_version=TYPED_PROTOCOL_VERSION,
        guard_required=True,
        expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash,
        submission_source=submission_source,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=attempt,
        regeneration_source="host" if parent_pdcp_log_id is not None else None,
        client_request_id=client_request_id,
        _before_final_guard=_before_final_guard,
    )


def _submit(
    session: Session,
    *,
    target_uuid: uuid.UUID,
    record_content: str,
    decode: Callable[[CloudTargetFiles], tuple[ParsedPDCP, TypedTransaction | None]],
    protocol_version: str,
    guard_required: bool,
    expected_target_version: int | None,
    expected_current_hash: str | None,
    submission_source: str,
    parent_pdcp_log_id: uuid.UUID | str | None,
    regeneration_attempt: int | None,
    regeneration_source: str | None,
    client_request_id: str | None = None,
    _before_final_guard=None,
) -> SubmitPDCPResult:
    """Shared locked validate/apply/commit path for every submission format."""

    pdcp_content = record_content
    pdcp_content_hash = canonical_sha256(pdcp_content)

    with _transaction(session):
        key = session.identity_key(CloudTargetFiles, target_uuid)
        existing = session.identity_map.get(key)
        if existing is not None and (existing in session.dirty or session.is_modified(existing)):
            return SubmitPDCPResult(
                status="rejected",
                target_file_id=target_uuid,
                pdcp_log_id=None,
                before_hash=getattr(existing, "current_hash", None),
                after_hash=None,
                before_version=getattr(existing, "version", None),
                after_version=None,
                current_hash=getattr(existing, "current_hash", None),
                current_version=getattr(existing, "version", None),
                failure_reason=FailureReason.CONTEXT_INVALID,
                failure_detail="Pending local direct modifications on target are not permitted.",
                validation_stage=ValidationStage.PRECONDITION_GUARD,
            )

        with session.no_autoflush:
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
                validation_stage=ValidationStage.PRECONDITION_GUARD,
            )

        before_hash = target.current_hash
        before_version = target.version
        before_content = target.current_content

        # Validate client_request_id syntax before lookup.
        try:
            validated_req_id = validate_client_request_id(client_request_id)
        except ProtocolValidationError as exc:
            current_pdcp = _upsert_current_pdcp(
                session,
                target=target,
                pdcp_content=pdcp_content,
                pdcp_content_hash=pdcp_content_hash,
                status="pending_validation",
                protocol_version=protocol_version,
                submission_source=submission_source,
                parent_pdcp_log_id=None,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
            )
            rejection = _core_rejection(
                exc.failure_reason,
                exc.failure_detail,
                before_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
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
                parent_pdcp_log_id=None,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
                protocol_version=protocol_version,
                parsed=None,
                rejection=rejection,
                before_hash=before_hash,
                before_version=before_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
                client_request_id=None,
                request_fingerprint=None,
            )

        # Validate parent_pdcp_log_id syntax and target ownership before FK insert.
        parent_uuid, parent_error = _resolve_parent_log(session, target.target_file_id, parent_pdcp_log_id)
        fingerprint = (
            _compute_request_fingerprint(
                protocol_version=protocol_version,
                target_file_id=str(target.target_file_id),
                pdcp_content_hash=pdcp_content_hash,
                expected_target_version=expected_target_version,
                expected_current_hash=expected_current_hash,
                parent_pdcp_log_id=str(parent_uuid) if parent_uuid else (str(parent_pdcp_log_id) if parent_pdcp_log_id else None),
            )
            if validated_req_id is not None
            else None
        )

        # C4: Idempotency / outcome-recovery check precedes stale-guard checks so a
        # retried request whose first response was lost recovers its recorded terminal
        # outcome instead of failing on a now-advanced target version/hash.
        if validated_req_id is not None:
            existing_log = session.scalar(
                select(AppendOnlyPdcpLogs).where(
                    AppendOnlyPdcpLogs.target_file_id == target.target_file_id,
                    AppendOnlyPdcpLogs.client_request_id == validated_req_id,
                )
            )
            if existing_log is not None:
                if existing_log.request_fingerprint == fingerprint:
                    return _reconstruct_deduplicated_result(session, target, existing_log)
                # Same client_request_id reused with a different proposal on the same target:
                # reject explicitly without overwriting the original log row or mutating state.
                conflict = _core_rejection(
                    FailureReason.CONTEXT_INVALID,
                    "client_request_id was already used for a different proposal on this target.",
                    before_hash,
                    protocol_version=protocol_version,
                    stage=ValidationStage.PRECONDITION_GUARD,
                )
                conflict_diag = dict(conflict.diagnostic or {})
                conflict_diag["existing_pdcp_log_id"] = str(existing_log.pdcp_log_id)
                return SubmitPDCPResult(
                    status="rejected",
                    target_file_id=target.target_file_id,
                    pdcp_log_id=None,
                    before_hash=before_hash,
                    after_hash=None,
                    before_version=before_version,
                    after_version=None,
                    current_hash=target.current_hash,
                    current_version=target.version,
                    failure_reason=conflict.failure_reason,
                    failure_detail=conflict.failure_detail,
                    diagnostic=conflict_diag,
                    validation_stage=ValidationStage.PRECONDITION_GUARD,
                    client_request_id=validated_req_id,
                )

        current_pdcp = _upsert_current_pdcp(
            session,
            target=target,
            pdcp_content=pdcp_content,
            pdcp_content_hash=pdcp_content_hash,
            status="pending_validation",
            protocol_version=protocol_version,
            submission_source=submission_source,
            parent_pdcp_log_id=parent_uuid,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
        )

        if parent_error is not None:
            rejection = _core_rejection(
                FailureReason.CONTEXT_INVALID,
                parent_error,
                before_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
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
                parent_pdcp_log_id=None,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
                protocol_version=protocol_version,
                parsed=None,
                rejection=rejection,
                before_hash=before_hash,
                before_version=before_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
                client_request_id=validated_req_id,
                request_fingerprint=fingerprint,
            )

        guard_rejection, guard_stage = _guard_rejection(
            target=target,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
            guard_required=guard_required,
            protocol_version=protocol_version,
        )
        if guard_rejection is not None and guard_stage is not None:
            return _persist_rejection(
                session,
                target=target,
                current_pdcp=current_pdcp,
                pdcp_content=pdcp_content,
                pdcp_content_hash=pdcp_content_hash,
                expected_target_version=expected_target_version,
                expected_current_hash=expected_current_hash,
                submission_source=submission_source,
                parent_pdcp_log_id=parent_uuid,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
                protocol_version=protocol_version,
                parsed=None,
                rejection=guard_rejection,
                before_hash=before_hash,
                before_version=before_version,
                stage=guard_stage,
                client_request_id=validated_req_id,
                request_fingerprint=fingerprint,
            )

        parsed: ParsedPDCP | None = None
        typed: TypedTransaction | None = None
        stage = ValidationStage.TRANSACTION_APPLICABILITY
        try:
            parsed, typed = decode(target)
            core_result = apply_pdcp_transaction(
                target.current_content,
                parsed,
                overlapping_matches=True,
            )
            if isinstance(core_result, RejectedCoreResult):
                core_result = _enrich_diagnostic(
                    core_result,
                    protocol_version=protocol_version,
                    stage=ValidationStage.TRANSACTION_APPLICABILITY,
                )
        except PDCPParseError as exc:
            stage = ValidationStage.PROTOCOL_VALIDATION
            core_result = _core_rejection(
                exc.failure_reason,
                exc.failure_detail,
                before_hash,
                exc.failed_change_id,
                protocol_version=protocol_version,
                stage=stage,
            )
        except ProtocolValidationError as exc:
            # PDCP header `target_hash` precondition is checked after parse_pdcp + validate_pdcp
            # succeed, so it is a transaction-applicability rejection over a valid protocol envelope.
            stage = (
                ValidationStage.TRANSACTION_APPLICABILITY
                if exc.failure_reason is FailureReason.TARGET_HASH_MISMATCH
                else ValidationStage.PROTOCOL_VALIDATION
            )
            core_result = _core_rejection(
                exc.failure_reason,
                exc.failure_detail,
                before_hash,
                exc.failed_change_id,
                protocol_version=protocol_version,
                stage=stage,
            )

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
                parent_pdcp_log_id=parent_uuid,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
                protocol_version=parsed.header.protocol_version if parsed else protocol_version,
                parsed=parsed,
                rejection=core_result,
                before_hash=before_hash,
                before_version=before_version,
                stage=stage,
                client_request_id=validated_req_id,
                request_fingerprint=fingerprint,
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
                protocol_version=protocol_version,
                stage=ValidationStage.COMMIT_GUARD,
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
                parent_pdcp_log_id=parent_uuid,
                regeneration_attempt=regeneration_attempt,
                regeneration_source=regeneration_source,
                protocol_version=parsed.header.protocol_version if parsed else protocol_version,
                parsed=parsed,
                rejection=divergence,
                before_hash=before_hash,
                before_version=before_version,
                stage=ValidationStage.COMMIT_GUARD,
                client_request_id=validated_req_id,
                request_fingerprint=fingerprint,
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
            parent_pdcp_log_id=parent_uuid,
            regeneration_attempt=regeneration_attempt,
            regeneration_source=regeneration_source,
            protocol_version=parsed.header.protocol_version,
            typed=typed,
            parsed=parsed,
            accepted=core_result,
            before_version=before_version,
            client_request_id=validated_req_id,
            request_fingerprint=fingerprint,
        )


def _guard_rejection(
    *,
    target: CloudTargetFiles,
    expected_target_version: int | None,
    expected_current_hash: str | None,
    guard_required: bool = False,
    protocol_version: str = SUPPORTED_PROTOCOL_VERSION,
) -> tuple[RejectedCoreResult | None, ValidationStage | None]:
    if guard_required and expected_target_version is None and expected_current_hash is None:
        return (
            _core_rejection(
                FailureReason.CONTEXT_MISSING,
                "At least one of expected_target_version or expected_current_hash is required.",
                target.current_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
            ),
            ValidationStage.PROTOCOL_VALIDATION,
        )
    if expected_target_version is not None and (
        isinstance(expected_target_version, bool)
        or not isinstance(expected_target_version, int)
        or expected_target_version < 0
    ):
        return (
            _core_rejection(
                FailureReason.CONTEXT_INVALID,
                "expected_target_version must be a non-negative integer.",
                target.current_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
            ),
            ValidationStage.PROTOCOL_VALIDATION,
        )
    if expected_current_hash is not None and (
        not isinstance(expected_current_hash, str) or len(expected_current_hash) != 64
    ):
        return (
            _core_rejection(
                FailureReason.CONTEXT_INVALID,
                "expected_current_hash must be a 64-character lowercase SHA-256 hex digest.",
                target.current_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
            ),
            ValidationStage.PROTOCOL_VALIDATION,
        )
    if expected_target_version is not None and target.version != expected_target_version:
        return (
            _core_rejection(
                FailureReason.TARGET_VERSION_MISMATCH,
                "expected_target_version does not match the current target version.",
                target.current_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PRECONDITION_GUARD,
            ),
            ValidationStage.PRECONDITION_GUARD,
        )
    if expected_current_hash is not None and target.current_hash != expected_current_hash:
        return (
            _core_rejection(
                FailureReason.TARGET_HASH_MISMATCH,
                "expected_current_hash does not match the current target hash.",
                target.current_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PRECONDITION_GUARD,
            ),
            ValidationStage.PRECONDITION_GUARD,
        )
    return None, None


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
    protocol_version: str = SUPPORTED_PROTOCOL_VERSION,
    typed: TypedTransaction | None = None,
    client_request_id: str | None = None,
    request_fingerprint: str | None = None,
) -> SubmitPDCPResult:
    after_version = before_version + 1
    log = AppendOnlyPdcpLogs(
        target_file_id=target.target_file_id,
        editing_cycle_id=target.active_editing_cycle_id,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=regeneration_attempt,
        regeneration_source=regeneration_source,
        submission_source=submission_source,
        protocol_version=protocol_version,
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
        client_request_id=client_request_id,
        request_fingerprint=request_fingerprint,
    )
    session.add(log)
    session.flush()

    facts_by_id = {fact["change_id"]: fact for fact in accepted.change_facts}
    if typed is None:
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
                    origin="pdcp_manifest",
                    derived_json=facts_by_id.get(fields["change_id"]),
                )
            )
    else:
        # Typed path: asserted text lives only in `intent` (advisory); everything the
        # runtime knows for certain lives only in `derived_json`.
        for index, edit in enumerate(typed.edits, start=1):
            session.add(
                AppendOnlyManifestLedger(
                    target_file_id=target.target_file_id,
                    editing_cycle_id=target.active_editing_cycle_id,
                    pdcp_log_id=log.pdcp_log_id,
                    change_index=index,
                    change_id=edit.change_id,
                    intent=edit.rationale or typed.intent,
                    input_state=None,
                    output_state=None,
                    affected_region=None,
                    user_visible_change=None,
                    risk=edit.risk,
                    origin="typed",
                    derived_json=facts_by_id.get(edit.change_id),
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
        current_hash=target.current_hash,
        current_version=target.version,
        manifest_entries_added=accepted.change_count,
        change_facts=accepted.change_facts,
        validation_stage=ValidationStage.ACCEPTED,
        client_request_id=client_request_id,
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
    protocol_version: str = SUPPORTED_PROTOCOL_VERSION,
    stage: ValidationStage = ValidationStage.PROTOCOL_VALIDATION,
    client_request_id: str | None = None,
    request_fingerprint: str | None = None,
) -> SubmitPDCPResult:
    log = AppendOnlyPdcpLogs(
        target_file_id=target.target_file_id,
        editing_cycle_id=target.active_editing_cycle_id,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=regeneration_attempt,
        regeneration_source=regeneration_source,
        submission_source=submission_source,
        protocol_version=protocol_version,
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
        client_request_id=client_request_id,
        request_fingerprint=request_fingerprint,
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
        validation_stage=stage,
        client_request_id=client_request_id,
    )


def _reconstruct_deduplicated_result(
    session: Session,
    target: CloudTargetFiles,
    log: AppendOnlyPdcpLogs,
) -> SubmitPDCPResult:
    """Return the original terminal outcome for an already-recorded (target_file_id, client_request_id)."""

    if log.status == "accepted":
        ledger_rows = session.scalars(
            select(AppendOnlyManifestLedger)
            .where(AppendOnlyManifestLedger.pdcp_log_id == log.pdcp_log_id)
            .order_by(AppendOnlyManifestLedger.change_index)
        ).all()
        facts = tuple(row.derived_json for row in ledger_rows if row.derived_json is not None)
        return SubmitPDCPResult(
            status="accepted",
            target_file_id=target.target_file_id,
            pdcp_log_id=log.pdcp_log_id,
            before_hash=log.before_hash,
            after_hash=log.after_hash,
            before_version=log.before_version,
            after_version=log.after_version,
            current_hash=target.current_hash,
            current_version=target.version,
            manifest_entries_added=log.change_count,
            change_facts=facts,
            validation_stage=ValidationStage.ACCEPTED,
            deduplicated=True,
            client_request_id=log.client_request_id,
        )

    diag = dict(log.diagnostic_json or {})
    stage_str = diag.get("validation_stage")
    stage = ValidationStage(stage_str) if stage_str in ValidationStage._value2member_map_ else None
    reason = FailureReason(log.failure_reason) if log.failure_reason else None
    return SubmitPDCPResult(
        status="rejected",
        target_file_id=target.target_file_id,
        pdcp_log_id=log.pdcp_log_id,
        before_hash=log.before_hash,
        after_hash=None,
        before_version=log.before_version,
        after_version=None,
        current_hash=target.current_hash,
        current_version=target.version,
        failure_reason=reason,
        failure_detail=log.failure_detail,
        failed_change_id=log.failed_change_id,
        diagnostic=diag,
        validation_stage=stage,
        deduplicated=True,
        client_request_id=log.client_request_id,
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
    protocol_version: str = SUPPORTED_PROTOCOL_VERSION,
) -> CurrentPdcpFiles:
    existing = session.execute(
        select(CurrentPdcpFiles).where(CurrentPdcpFiles.target_file_id == target.target_file_id)
    ).scalar_one_or_none()
    if existing is None:
        existing = CurrentPdcpFiles(
            target_file_id=target.target_file_id,
            editing_cycle_id=target.active_editing_cycle_id,
            protocol_version=protocol_version,
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
        existing.protocol_version = protocol_version
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
    *,
    protocol_version: str = SUPPORTED_PROTOCOL_VERSION,
    stage: ValidationStage = ValidationStage.PROTOCOL_VALIDATION,
) -> RejectedCoreResult:
    is_typed = protocol_version == TYPED_PROTOCOL_VERSION
    diagnostic: dict[str, Any] = {
        "format": protocol_version,
        "retryable": reason
        in {
            FailureReason.MATCH_ABSENT,
            FailureReason.MATCH_AMBIGUOUS,
            FailureReason.DISAMBIGUATION_INVALID,
            FailureReason.SEQUENTIAL_MATCH_INVALID,
            FailureReason.TARGET_HASH_MISMATCH,
            FailureReason.TARGET_VERSION_MISMATCH,
        },
        "requires_new_submission": True,
        "validation_stage": stage.value,
    }
    if not is_typed:
        diagnostic["requires_new_pdcp"] = True

    if reason in {FailureReason.MANIFEST_INVALID, FailureReason.MANIFEST_MISSING}:
        if is_typed:
            diagnostic.update(
                {
                    "allowed_edit_fields": list(ALLOWED_TYPED_EDIT_FIELDS),
                    "required_edit_fields": list(REQUIRED_TYPED_EDIT_FIELDS),
                    "valid_risk_values": sorted(VALID_RISK_VALUES),
                }
            )
        else:
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


def _enrich_diagnostic(
    rejection: RejectedCoreResult,
    *,
    protocol_version: str,
    stage: ValidationStage,
) -> RejectedCoreResult:
    diag = dict(rejection.diagnostic or {})
    diag["format"] = protocol_version
    diag["validation_stage"] = stage.value
    diag["requires_new_submission"] = True
    if protocol_version == TYPED_PROTOCOL_VERSION:
        diag.pop("requires_new_pdcp", None)
    else:
        diag["requires_new_pdcp"] = True
    return RejectedCoreResult(
        failure_reason=rejection.failure_reason,
        failure_detail=rejection.failure_detail,
        before_hash=rejection.before_hash,
        failed_change_id=rejection.failed_change_id,
        diagnostic=diag,
    )


def _compute_request_fingerprint(
    *,
    protocol_version: str,
    target_file_id: str,
    pdcp_content_hash: str,
    expected_target_version: int | None,
    expected_current_hash: str | None,
    parent_pdcp_log_id: str | None,
) -> str:
    envelope = {
        "protocol_version": protocol_version,
        "target_file_id": target_file_id,
        "pdcp_content_hash": pdcp_content_hash,
        "expected_target_version": expected_target_version,
        "expected_current_hash": expected_current_hash,
        "parent_pdcp_log_id": parent_pdcp_log_id,
    }
    return canonical_sha256(json.dumps(envelope, sort_keys=True, separators=(",", ":")))


def _resolve_parent_log(
    session: Session,
    target_uuid: uuid.UUID,
    parent_pdcp_log_id: uuid.UUID | str | None,
) -> tuple[uuid.UUID | None, str | None]:
    if parent_pdcp_log_id is None:
        return None, None
    parent_uuid = _try_coerce_uuid(parent_pdcp_log_id)
    if parent_uuid is None:
        return None, "parent_pdcp_log_id must be a valid UUID."
    parent = session.get(AppendOnlyPdcpLogs, parent_uuid)
    if parent is None:
        return None, "parent_pdcp_log_id does not exist."
    if parent.target_file_id != target_uuid:
        return None, "parent_pdcp_log_id belongs to a different target_file_id."
    return parent_uuid, None


def _try_coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _invalid_target_uuid_result(target_file_id: Any) -> SubmitPDCPResult:
    return SubmitPDCPResult(
        status="rejected",
        target_file_id=str(target_file_id),
        pdcp_log_id=None,
        before_hash=None,
        after_hash=None,
        before_version=None,
        after_version=None,
        current_hash=None,
        current_version=None,
        failure_reason=FailureReason.CONTEXT_INVALID,
        failure_detail="target_file_id must be a valid UUID.",
        diagnostic={
            "retryable": False,
            "requires_new_submission": True,
            "validation_stage": ValidationStage.PRECONDITION_GUARD.value,
        },
        validation_stage=ValidationStage.PRECONDITION_GUARD,
    )


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
