"""Postgres-backed PDCP and typed transaction submission service."""

from __future__ import annotations

import json
import re
import uuid
from functools import wraps
from collections.abc import Callable
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.advisories import bounded_warnings, warning_strings
from app.core.failures import RETRYABLE_FAILURE_REASONS, FailureReason
from app.core.hashing import canonical_sha256
from app.core.canonicalization import canonicalize_text
from app.core.input_text import invalid_text_paths, is_persistable_text, safe_input_text
from app.core.result import AcceptedCoreResult, FailureBufferContext, RejectedCoreResult
from app.core.validity import ValidationStage, validity_levels
from app.core.versions import OPERATIONS_RUNTIME_VERSION, REPLACEMENT_RUNTIME_VERSION, RUNTIME_VERSION, resolve_runtime_profile
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.observed_batch import (
    BATCH_PROTOCOL_VERSION, BATCH_RUNTIME_VERSION, BATCH_UNSET, BatchValidationError,
    validate_batch_envelope, parse_batch_request, flatten_batch, apply_observed_batch,
)
from app.pdcp.operations import (OPERATIONS_PROTOCOL_VERSION, build_operations_record, operations_runtime_version,
                                 parse_operations_record, to_parsed_operations)
from app.pdcp.replacement import (REPLACEMENT_PROTOCOL_VERSION, build_replacement_record, parse_replacement_record,
                                 to_parsed_replacement, replacement_size_evidence)
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
from app.services.rejection_context import (available_context, unavailable_context, bound_candidates, context_identity,
                                            response_current_context)
from app.services.near_miss_service import near_misses
from app.core.config import is_strict_observation_mode_enabled
from app.services.preview_evidence import bound_preview
from app.services.scope_observation_service import (
    ObservationValidationFailure,
    ValidatedScopeObservation,
    validate_observation_for_locked_target,
    validate_bundle_for_locked_target, batch_scope_evidence,
)
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    CurrentPdcpFiles,
)
from app.storage.repositories import select_target_for_update

_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class TargetHashApplicabilityError(ProtocolValidationError):
    """Raised when a valid PDCP header target_hash does not match the target's current hash."""
    pass


def sanitize_expected_target_version(val: Any) -> tuple[int | None, bool]:
    if val is None:
        return None, True
    if isinstance(val, bool):
        return None, False
    if isinstance(val, int) and 0 <= val <= (2**63 - 1):
        return val, True
    return None, False


def sanitize_expected_current_hash(val: Any) -> tuple[str | None, bool]:
    if val is None:
        return None, True
    if isinstance(val, str) and bool(_HEX_64_RE.fullmatch(val)):
        return val, True
    return None, False


def sanitize_regeneration_attempt(val: Any) -> tuple[int | None, bool]:
    if val is None:
        return None, True
    if isinstance(val, bool):
        return None, False
    if isinstance(val, int) and 1 <= val <= (2**31 - 1):
        return val, True
    return None, False


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
    current_context: dict | None = None
    near_misses: dict | None = None
    correlation_id: str | None = None
    warning_details: tuple[dict, ...] = ()
    warning_count: int = 0
    warnings_truncated: bool = False
    code: str | None = None
    # Bounded, response-only failing-buffer copy for fresh near-miss scans; never stored.
    near_miss_buffer: str | None = None
    batch_metadata: dict | None = None



def _submission_response(submit):
    @wraps(submit)
    def call(session: Session, *, include_correlation_id=False, **kwargs):
        if not isinstance(include_correlation_id, bool):
            return replace(_invalid_target_uuid_result(kwargs.get("target_file_id")), status="invalid_argument",
                           failure_detail="include_correlation_id must be a boolean.", diagnostic=None, current_context=None,
                           code="invalid_include_correlation_id")
        result = submit(session, **kwargs)
        # _submit's owned transaction has successfully exited (committed) before comparison.
        if result.status == "rejected" and result.failure_reason in {
            FailureReason.MATCH_ABSENT, FailureReason.SEQUENTIAL_MATCH_INVALID,
        }:
            result = replace(result, near_misses=near_misses(
                result.diagnostic or {}, caller_owned=session.in_transaction(), buffer=result.near_miss_buffer,
                failure_reason=result.failure_reason.value))
        if include_correlation_id:
            result = replace(result, correlation_id=str(uuid.uuid4()))
        return result
    return call


@_submission_response
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
    include_correlation_id: bool = False,
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
            raise TargetHashApplicabilityError(
                FailureReason.TARGET_HASH_MISMATCH,
                "PDCP target_hash does not match the current target hash.",
            )
        return parsed, None

    return _submit(
        session,
        target_uuid=target_uuid,
        submitted_target_id=target_file_id,
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


@_submission_response
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
    include_correlation_id: bool = False,
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
        submitted_target_id=target_file_id,
        record_content=record_content,
        raw_record=record,
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



@_submission_response
def submit_operations(
    session: Session, *, target_file_id: uuid.UUID | str, intent: Any, operations: Any,
    expected_target_version: int | None = None, expected_current_hash: str | None = None,
    submission_source: str = "model_response", parent_pdcp_log_id: uuid.UUID | str | None = None,
    attempt: int | None = None, client_request_id: str | None = None,
    include_correlation_id: bool = False, _before_final_guard=None,
) -> SubmitPDCPResult:
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return _invalid_target_uuid_result(target_file_id)
    record = build_operations_record(target_file_id=str(target_uuid), intent=intent, operations=operations,
                                     expected_target_version=expected_target_version, expected_current_hash=expected_current_hash)
    def decode(target):
        typed = parse_operations_record(record)
        return to_parsed_operations(typed, target_type=target.target_type), typed
    return _submit(session, target_uuid=target_uuid, submitted_target_id=target_file_id,
                   record_content=canonical_record_json(record), raw_record=record, decode=decode,
                   protocol_version=OPERATIONS_PROTOCOL_VERSION, runtime_version=operations_runtime_version(record),
                   guard_required=True,
                   expected_target_version=expected_target_version, expected_current_hash=expected_current_hash,
                   submission_source=submission_source, parent_pdcp_log_id=parent_pdcp_log_id,
                   regeneration_attempt=attempt, regeneration_source="host" if parent_pdcp_log_id is not None else None,
                   client_request_id=client_request_id, _before_final_guard=_before_final_guard)


@_submission_response
def submit_observed_operations(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    observation_id: uuid.UUID | str | None = BATCH_UNSET,
    intent: Any,
    operations: Any = BATCH_UNSET,
    observation_bundle_id: str | None = BATCH_UNSET,
    groups: Any = BATCH_UNSET,
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    submission_source: str = "model_response",
    parent_pdcp_log_id: uuid.UUID | str | None = None,
    attempt: int | None = None,
    client_request_id: str | None = None,
    include_correlation_id: bool = False,
    _before_final_guard=None,
) -> SubmitPDCPResult:
    """Submit a guarded patchdiff-tx/2 transaction restricted to a server-issued observed scope."""
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return _invalid_target_uuid_result(target_file_id)
    if observation_bundle_id is not BATCH_UNSET or groups is not BATCH_UNSET:
        record = {"format": BATCH_PROTOCOL_VERSION, "target_file_id": str(target_uuid),
                  "observation_bundle_id": None if observation_bundle_id is BATCH_UNSET else observation_bundle_id,
                  "intent": intent, "groups": None if groups is BATCH_UNSET else groups,
                  "expected_target_version": expected_target_version, "expected_current_hash": expected_current_hash}
        if observation_id is not BATCH_UNSET or operations is not BATCH_UNSET:
            record["conflicting_single_request"] = {
                "observation_id": None if observation_id is BATCH_UNSET else observation_id,
                "operations": None if operations is BATCH_UNSET else operations}
        return _submit(
            session, target_uuid=target_uuid, submitted_target_id=target_file_id,
            record_content=canonical_record_json(record), raw_record=record, decode=lambda target: (None, None),
            protocol_version=BATCH_PROTOCOL_VERSION, runtime_version=BATCH_RUNTIME_VERSION,
            guard_required=True, expected_target_version=expected_target_version, expected_current_hash=expected_current_hash,
            submission_source=submission_source, parent_pdcp_log_id=parent_pdcp_log_id,
            regeneration_attempt=attempt, regeneration_source="host" if parent_pdcp_log_id is not None else None,
            client_request_id=client_request_id, _before_final_guard=_before_final_guard, _batch_request=record)
    observation_id = None if observation_id is BATCH_UNSET else observation_id
    operations = None if operations is BATCH_UNSET else operations
    record = build_operations_record(
        target_file_id=str(target_uuid),
        intent=intent,
        operations=operations,
        expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash,
    )

    def decode(target):
        typed = parse_operations_record(record)
        return to_parsed_operations(typed, target_type=target.target_type), typed

    return _submit(
        session,
        target_uuid=target_uuid,
        submitted_target_id=target_file_id,
        record_content=canonical_record_json(record),
        raw_record=record,
        decode=decode,
        protocol_version=OPERATIONS_PROTOCOL_VERSION,
        runtime_version=operations_runtime_version(record),
        guard_required=True,
        expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash,
        submission_source=submission_source,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=attempt,
        regeneration_source="host" if parent_pdcp_log_id is not None else None,
        client_request_id=client_request_id,
        _before_final_guard=_before_final_guard,
        _require_observation=True,
        _observation_id=observation_id,
    )


@_submission_response
def submit_replacement(
    session: Session, *, target_file_id: uuid.UUID | str, intent: Any, replacement: Any,
    expected_target_version: int | None = None, expected_current_hash: str | None = None,
    submission_source: str = "model_response", parent_pdcp_log_id: uuid.UUID | str | None = None,
    attempt: int | None = None, client_request_id: str | None = None,
    include_correlation_id: bool = False, _before_final_guard=None,
) -> SubmitPDCPResult:
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return _invalid_target_uuid_result(target_file_id)
    record = build_replacement_record(target_file_id=str(target_uuid), intent=intent, replacement=replacement,
                                     expected_target_version=expected_target_version, expected_current_hash=expected_current_hash)
    def decode(target):
        typed = parse_replacement_record(record)
        return to_parsed_replacement(typed, target_type=target.target_type), typed
    return _submit(session, target_uuid=target_uuid, submitted_target_id=target_file_id,
                   record_content=canonical_record_json(record), raw_record=record, decode=decode,
                   protocol_version=REPLACEMENT_PROTOCOL_VERSION, guard_required=True,
                   expected_target_version=expected_target_version, expected_current_hash=expected_current_hash,
                   submission_source=submission_source, parent_pdcp_log_id=parent_pdcp_log_id,
                   regeneration_attempt=attempt, regeneration_source="host" if parent_pdcp_log_id is not None else None,
                   client_request_id=client_request_id, _before_final_guard=_before_final_guard,
                   _fresh_admission=lambda: replacement_size_evidence(replacement))


def preview(session: Session, *, target_file_id: uuid.UUID | str, format: str, **proposal) -> dict:
    """Return bounded advisory evidence without changing submit or durable facts."""
    payload = _preview(session, target_file_id=target_file_id, format=format, **proposal)
    if "current_context" in payload:
        payload["current_context"] = response_current_context(
            payload["current_context"], (payload.get("diagnostic") or {}).get("failure_context"))
    return bound_preview(payload)


def _preview(session: Session, *, target_file_id: uuid.UUID | str, format: str, **proposal) -> dict:
    """Observe and evaluate a fresh proposal without writes, locks or identity reservation."""
    from app.services.read_service import observe_target

    fields = {
        SUPPORTED_PROTOCOL_VERSION: {"pdcp_content"},
        TYPED_PROTOCOL_VERSION: {"intent", "edits"},
        OPERATIONS_PROTOCOL_VERSION: {"intent", "operations"},
        REPLACEMENT_PROTOCOL_VERSION: {"intent", "replacement"},
    }
    common = {"preview": True, "advisory": True, "target_file_id": safe_input_text(target_file_id)}
    if not isinstance(format, str) or format not in fields:
        return {**common, "status": "invalid_argument", "code": "invalid_format", "detail": "Unsupported preview format.",
                "failure_detail": "Unsupported preview format."}
    if set(proposal) - fields[format] - {"expected_target_version", "expected_current_hash"}:
        return {**common, "status": "invalid_argument", "code": "irrelevant_proposal_fields",
                "detail": "Preview fields must belong to the explicit format.",
                "failure_detail": "Preview fields must belong to the explicit format."}
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        result = _invalid_target_uuid_result(target_file_id)
        return {**common, "status": result.status, "failure_reason": result.failure_reason.value,
                "failure_detail": result.failure_detail, "failed_change_id": None,
                "validation_stage": result.validation_stage.value,
                "validity": validity_levels(result.status, result.failure_reason, stage=result.validation_stage),
                "diagnostic": result.diagnostic, "current_context": result.current_context,
                "current_hash": None, "current_version": None, "before_hash": None, "before_version": None,
                "after_hash": None}
    local = session.identity_map.get(session.identity_key(CloudTargetFiles, target_uuid))
    pending = (local is not None and (local in session.dirty or local in session.deleted or session.is_modified(local)))
    pending = pending or any(isinstance(item, CloudTargetFiles) and item.target_file_id == target_uuid for item in session.new)
    if pending:
        context = unavailable_context("unlocked_local_state")
        return {**common, "status": "rejected", "failure_reason": FailureReason.CONTEXT_INVALID.value,
                "failure_detail": "Pending local direct modifications on target are not permitted.",
                "failed_change_id": None, "validation_stage": ValidationStage.PRECONDITION_GUARD.value,
                "validity": validity_levels("rejected", stage=ValidationStage.PRECONDITION_GUARD),
                "diagnostic": {"failure_context": context}, "current_context": context,
                "current_hash": None, "current_version": None, "before_hash": None, "before_version": None,
                "after_hash": None}
    observation = observe_target(session, target_uuid)
    if observation is None:
        context = unavailable_context("target_not_found")
        return {**common, "status": "rejected", "failure_reason": FailureReason.TARGET_NOT_FOUND.value,
                "failure_detail": "Target file was not found.", "failed_change_id": None,
                "validation_stage": ValidationStage.PRECONDITION_GUARD.value,
                "validity": validity_levels("rejected", stage=ValidationStage.PRECONDITION_GUARD),
                "diagnostic": {"failure_context": context}, "current_context": context,
                "current_hash": None, "current_version": None, "before_hash": None, "before_version": None,
                "after_hash": None}
    target = SimpleNamespace(target_file_id=observation.target_file_id, target_type=observation.target_type,
                             current_content=observation.current_content, current_hash=observation.current_hash,
                             version=observation.current_version)
    version, digest = proposal.get("expected_target_version"), proposal.get("expected_current_hash")
    record_args = {"target_file_id": str(target_uuid), "intent": proposal.get("intent"),
                   "expected_target_version": version, "expected_current_hash": digest}
    if format == SUPPORTED_PROTOCOL_VERSION:
        record = proposal.get("pdcp_content")
        def decode(target):
            if not isinstance(record, str):
                raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "pdcp_content must be a string.")
            parsed = parse_pdcp(record)
            validate_pdcp(parsed)
            if parsed.header.target_file_id != str(target_uuid):
                raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "PDCP target_file_id does not match the submitted target.")
            if parsed.header.target_hash is not None and parsed.header.target_hash != target.current_hash:
                raise TargetHashApplicabilityError(FailureReason.TARGET_HASH_MISMATCH,
                                                   "PDCP target_hash does not match the current target hash.")
            return parsed, None
    elif format == TYPED_PROTOCOL_VERSION:
        record = build_record(**record_args, edits=proposal.get("edits"))
        def decode(target):
            typed = parse_typed_record(record)
            return to_parsed_transaction(typed, target_type=target.target_type), typed
    elif format == OPERATIONS_PROTOCOL_VERSION:
        record = build_operations_record(**record_args, operations=proposal.get("operations"))
        runtime_version = operations_runtime_version(record)
        def decode(target):
            typed = parse_operations_record(record)
            return to_parsed_operations(typed, target_type=target.target_type), typed
    else:
        record = build_replacement_record(**record_args, replacement=proposal.get("replacement"))
        def decode(target):
            typed = parse_replacement_record(record)
            return to_parsed_replacement(typed, target_type=target.target_type), typed
    if format != OPERATIONS_PROTOCOL_VERSION:
        runtime_version = _runtime_version(format)
    encoding_paths = invalid_text_paths({"record": record, "expected_target_version": version, "expected_current_hash": digest})
    encoding = None
    if encoding_paths:
        encoding = {"evidence_format": "patchdiff-invalid-input/1",
                    "invalid_input_paths": [path[:256] for path in encoding_paths[:20]],
                    "invalid_input_paths_truncated": len(encoding_paths) > 20 or any(len(path) > 256 for path in encoding_paths[:20])}
    if format == REPLACEMENT_PROTOCOL_VERSION and not encoding_paths:
        size_evidence = replacement_size_evidence(proposal.get("replacement"))
        if size_evidence is not None:
            return {**common, "status": "invalid_argument", "code": "replacement_too_large",
                    "failure_detail": "Replacement exceeds fresh admission limits.", "diagnostic": size_evidence}
    _, _, result, stage = _evaluate_proposal(
        target=target, decode=decode, protocol_version=format, guard_required=format != SUPPORTED_PROTOCOL_VERSION,
        expected_target_version=version, expected_current_hash=digest, encoding_diagnostic=encoding,
        runtime_version=runtime_version)
    common.update(status=result.status, current_hash=target.current_hash, current_version=target.version,
                  before_hash=target.current_hash, before_version=target.version, after_hash=result.after_hash,
                  validation_stage=(ValidationStage.ACCEPTED if result.status == "accepted" else stage).value,
                  validity=validity_levels(result.status, stage=ValidationStage.ACCEPTED if result.status == "accepted" else stage),
                  failed_change_id=None)
    if isinstance(result, AcceptedCoreResult):
        envelope = bounded_warnings(result.warnings)
        return {**common, "change_facts": list(result.change_facts), "warnings": warning_strings(envelope["warnings"]),
                "warning_details": envelope["warnings"], "warning_count": envelope["warning_count"],
                "warnings_truncated": envelope["warnings_truncated"]}
    diagnostic = dict(result.diagnostic or {})
    diagnostic["failure_context"] = available_context(
        result.failure_buffer or FailureBufferContext.capture(target.current_content),
        observed_target_version=target.version, observed_target_hash=target.current_hash)
    if "exact_candidates" in diagnostic:
        diagnostic["exact_candidates"] = bound_candidates("exact_candidates", {
            **diagnostic["exact_candidates"], **context_identity(diagnostic["failure_context"])})
    payload = {**common, "failure_reason": result.failure_reason.value, "failure_detail": result.failure_detail,
               "failed_change_id": result.failed_change_id, "diagnostic": diagnostic,
               "current_context": _target_context(target)}
    if result.failure_reason in {FailureReason.MATCH_ABSENT, FailureReason.SEQUENTIAL_MATCH_INVALID}:
        # Preview holds no lock, so near misses are computed inline under the same budget.
        payload["near_misses"] = near_misses(diagnostic, caller_owned=False, buffer=result.near_miss_buffer,
                                             failure_reason=result.failure_reason.value)
    return payload


def _submit(
    session: Session,
    *,
    target_uuid: uuid.UUID,
    submitted_target_id: Any = None,
    record_content: str,
    raw_record: Any = None,
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
    runtime_version: str | None = None,
    _before_final_guard=None,
    _fresh_admission: Callable[[], dict | None] | None = None,
    _require_observation: bool = False,
    _observation_id: Any = None,
    _batch_request: dict | None = None,
) -> SubmitPDCPResult:
    """Shared locked validate/apply/commit path for every submission format."""

    runtime_version = runtime_version or _runtime_version(protocol_version)

    original_inputs = {
        "target_file_id": submitted_target_id,
        "record": raw_record if raw_record is not None else record_content,
        "expected_target_version": expected_target_version,
        "expected_current_hash": expected_current_hash,
        "submission_source": submission_source,
        "parent_pdcp_log_id": parent_pdcp_log_id,
        "regeneration_attempt": regeneration_attempt,
        "regeneration_source": regeneration_source,
        "client_request_id": client_request_id,
        **({"observation_id": _observation_id} if (_require_observation or _observation_id is not None) else {}),
    }
    encoding_paths = invalid_text_paths(original_inputs)
    encoding_diagnostic = {}
    pdcp_content = record_content
    if encoding_paths:
        pdcp_content = json.dumps(
            {"evidence_format": "patchdiff-invalid-input/1", "inputs": original_inputs},
            ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str,
        )
        encoding_diagnostic = {
            "evidence_format": "patchdiff-invalid-input/1",
            "invalid_input_paths": [path[:256] for path in encoding_paths[:20]],
            "invalid_input_paths_truncated": len(encoding_paths) > 20 or any(
                len(path) > 256 for path in encoding_paths[:20]
            ),
        }
        # Original values remain reversible in TEXT evidence, never unsafe JSONB/columns.
        if invalid_text_paths(expected_target_version):
            expected_target_version = None
        if invalid_text_paths(expected_current_hash):
            expected_current_hash = None
        if invalid_text_paths(regeneration_attempt):
            regeneration_attempt = None
        if invalid_text_paths(parent_pdcp_log_id):
            parent_pdcp_log_id = None
        if invalid_text_paths(regeneration_source):
            regeneration_source = None
        if invalid_text_paths(submission_source):
            submission_source = "invalid_input"
        if invalid_text_paths(client_request_id):
            client_request_id = None
        if invalid_text_paths(_observation_id):
            _observation_id = None
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
                diagnostic={"failure_context": unavailable_context("unlocked_local_state")},
                current_context=unavailable_context("unlocked_local_state"),
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
                diagnostic={"failure_context": unavailable_context("target_not_found")},
                current_context=unavailable_context("target_not_found"),
                validation_stage=ValidationStage.PRECONDITION_GUARD,
            )

        before_hash = target.current_hash
        before_version = target.version
        before_content = target.current_content

        # Existing keys keep exact outcome recovery across stricter validation versions.
        # Only already-persisted keys bypass new-key syntax checks, under the target lock.
        with session.no_autoflush:
            existing_log = (
                session.scalar(
                    select(AppendOnlyPdcpLogs).where(
                        AppendOnlyPdcpLogs.target_file_id == target.target_file_id,
                        AppendOnlyPdcpLogs.client_request_id == client_request_id,
                    )
                )
                if isinstance(client_request_id, str) and is_persistable_text(client_request_id)
                else None
            )
        try:
            validated_req_id = (
                existing_log.client_request_id
                if existing_log is not None
                else validate_client_request_id(client_request_id)
            )
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
                FailureReason.TARGET_ENCODING_INVALID if encoding_paths else exc.failure_reason,
                "Input strings must be UTF-8 without NUL." if encoding_paths else exc.failure_detail,
                before_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
                diagnostic_extra=encoding_diagnostic or {"code": "invalid_client_request_id"},
            )
            return _persist_rejection(
                session,
                runtime_version=runtime_version,
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
                identity_domain=(
                    "patchdiff-invalid-input/1"
                    if encoding_paths
                    else (f"observed:{safe_input_text(_observation_id)}" if _require_observation else None)
                ),
            )
            if validated_req_id is not None
            else None
        )

        # C4: Idempotency / outcome-recovery check precedes stale-guard checks so a
        # retried request whose first response was lost recovers its recorded terminal
        # outcome instead of failing on a now-advanced target version/hash.
        if validated_req_id is not None:
            if existing_log is not None:
                matches_recorded = existing_log.request_fingerprint == fingerprint
                if (
                    encoding_paths
                    and not (existing_log.diagnostic_json or {}).get("evidence_format")
                    and is_persistable_text(record_content)
                ):
                    # Existing rows may include escaped NUL or an invalid parent UUID.
                    historical_parent = original_inputs["parent_pdcp_log_id"]
                    historical_parent_uuid, _ = _resolve_parent_log(
                        session, target.target_file_id, historical_parent
                    )
                    historical_fingerprint = _compute_request_fingerprint(
                        protocol_version=protocol_version,
                        target_file_id=str(target.target_file_id),
                        pdcp_content_hash=canonical_sha256(record_content),
                        expected_target_version=original_inputs["expected_target_version"],
                        expected_current_hash=original_inputs["expected_current_hash"],
                        parent_pdcp_log_id=str(historical_parent_uuid) if historical_parent_uuid else (
                            str(historical_parent) if historical_parent else None
                        ),
                    )
                    matches_recorded = matches_recorded or (
                        existing_log.request_fingerprint == historical_fingerprint
                    )
                if matches_recorded:
                    return _reconstruct_deduplicated_result(session, target, existing_log)
                # Audit this attempt separately; the original keyed outcome stays authoritative.
                conflict = _core_rejection(
                    FailureReason.CONTEXT_INVALID,
                    "client_request_id was already used for a different proposal on this target.",
                    before_hash,
                    protocol_version=protocol_version,
                    stage=ValidationStage.PRECONDITION_GUARD,
                    diagnostic_extra={
                        **encoding_diagnostic,
                        "code": "request_key_conflict",
                        "existing_pdcp_log_id": str(existing_log.pdcp_log_id),
                        "submitted_client_request_id": validated_req_id[:256],
                        "submitted_client_request_id_truncated": len(validated_req_id) > 256,
                        **_conflict_evidence(
                            existing_log, protocol_version=protocol_version, pdcp_content_hash=pdcp_content_hash,
                            expected_target_version=expected_target_version,
                            expected_current_hash=expected_current_hash,
                            parent=parent_uuid if parent_uuid else parent_pdcp_log_id,
                            record_content=None if encoding_paths else record_content),
                    },
                )
                current_pdcp = _upsert_current_pdcp(
                    session, target=target,
                    pdcp_content=pdcp_content, pdcp_content_hash=pdcp_content_hash,
                    status="pending_validation", protocol_version=protocol_version,
                    submission_source=submission_source, parent_pdcp_log_id=parent_uuid,
                    regeneration_attempt=regeneration_attempt, regeneration_source=regeneration_source,
                )
                result = _persist_rejection(
                    session, runtime_version=runtime_version, target=target, current_pdcp=current_pdcp,
                    pdcp_content=pdcp_content, pdcp_content_hash=pdcp_content_hash,
                    expected_target_version=expected_target_version,
                    expected_current_hash=expected_current_hash,
                    submission_source=submission_source, parent_pdcp_log_id=parent_uuid,
                    regeneration_attempt=regeneration_attempt, regeneration_source=regeneration_source,
                    protocol_version=protocol_version, parsed=None, rejection=conflict,
                    before_hash=before_hash, before_version=before_version,
                    stage=ValidationStage.PRECONDITION_GUARD,
                    client_request_id=None, request_fingerprint=fingerprint,
                )
                # Response echoes the submitted key, while the new audit row has a NULL key.
                return replace(result, client_request_id=validated_req_id)


        if not encoding_paths and _fresh_admission is not None:
            size_evidence = _fresh_admission()
            if size_evidence is not None:
                return SubmitPDCPResult(
                    status="invalid_argument", target_file_id=target_uuid, pdcp_log_id=None,
                    before_hash=before_hash, after_hash=None, before_version=before_version, after_version=None,
                    current_hash=before_hash, current_version=before_version,
                    failure_detail="Replacement exceeds fresh admission limits.",
                    diagnostic=size_evidence, code=size_evidence["code"],
                    client_request_id=validated_req_id)

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

        if encoding_paths:
            _, _, rejection, _ = _evaluate_proposal(
                target=target, decode=decode, protocol_version=protocol_version, guard_required=guard_required,
                expected_target_version=expected_target_version, expected_current_hash=expected_current_hash,
                encoding_diagnostic=encoding_diagnostic, runtime_version=runtime_version)
            return _persist_rejection(
                session, runtime_version=runtime_version, target=target, current_pdcp=current_pdcp,
                pdcp_content=pdcp_content, pdcp_content_hash=pdcp_content_hash,
                expected_target_version=expected_target_version,
                expected_current_hash=expected_current_hash,
                submission_source=submission_source, parent_pdcp_log_id=parent_uuid,
                regeneration_attempt=regeneration_attempt, regeneration_source=regeneration_source,
                protocol_version=protocol_version, parsed=None, rejection=rejection,
                before_hash=before_hash, before_version=before_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
                client_request_id=validated_req_id, request_fingerprint=fingerprint,
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
                runtime_version=runtime_version,
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

        sanitized_attempt, attempt_valid = sanitize_regeneration_attempt(regeneration_attempt)
        if not attempt_valid:
            rejection = _core_rejection(
                FailureReason.CONTEXT_INVALID,
                "attempt must be an integer between 1 and 2147483647.",
                before_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
                diagnostic_extra={"raw_attempt": regeneration_attempt},
            )
            return _persist_rejection(
                session,
                runtime_version=runtime_version,
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
                rejection=rejection,
                before_hash=before_hash,
                before_version=before_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
                client_request_id=validated_req_id,
                request_fingerprint=fingerprint,
            )

        if is_strict_observation_mode_enabled() and not _require_observation and _batch_request is None:
            rejection = _core_rejection(
                FailureReason.CONTEXT_MISSING,
                "Strict observation mode requires a server-issued scope observation via patchdiff_submit_observed_operations.",
                before_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PRECONDITION_GUARD,
                diagnostic_extra={"code": "OBSERVATION_REQUIRED"},
            )
            return _persist_rejection(
                session,
                runtime_version=runtime_version,
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
                rejection=rejection,
                before_hash=before_hash,
                before_version=before_version,
                stage=ValidationStage.PRECONDITION_GUARD,
                client_request_id=validated_req_id,
                request_fingerprint=fingerprint,
            )

        validated_obs: ValidatedScopeObservation | None = None
        scope_bounds: tuple[int, int] | None = None
        if _require_observation:
            _, version_valid = sanitize_expected_target_version(expected_target_version)
            _, hash_valid = sanitize_expected_current_hash(expected_current_hash)
            if not version_valid or not hash_valid:
                guard_rej, guard_stg = _guard_rejection(
                    target=target,
                    expected_target_version=expected_target_version,
                    expected_current_hash=expected_current_hash,
                    guard_required=True,
                    protocol_version=protocol_version,
                )
                assert guard_rej is not None and guard_stg is not None
                return _persist_rejection(
                    session,
                    runtime_version=runtime_version,
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
                    rejection=guard_rej,
                    before_hash=before_hash,
                    before_version=before_version,
                    stage=guard_stg,
                    client_request_id=validated_req_id,
                    request_fingerprint=fingerprint,
                )

            obs_check = validate_observation_for_locked_target(
                session,
                target=target,
                observation_id=_observation_id,
                expected_target_version=expected_target_version,
                expected_current_hash=expected_current_hash,
            )
            if isinstance(obs_check, ObservationValidationFailure):
                rejection = _core_rejection(
                    obs_check.failure_reason,
                    obs_check.failure_detail,
                    before_hash,
                    protocol_version=protocol_version,
                    stage=obs_check.stage,
                    diagnostic_extra=obs_check.diagnostic,
                )
                return _persist_rejection(
                    session,
                    runtime_version=runtime_version,
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
                    rejection=rejection,
                    before_hash=before_hash,
                    before_version=before_version,
                    stage=obs_check.stage,
                    client_request_id=validated_req_id,
                    request_fingerprint=fingerprint,
                )
            validated_obs = obs_check
            scope_bounds = (validated_obs.scope_start, validated_obs.scope_end)

        batch_observations, batch_metadata = (), None
        if _batch_request is not None:
            parsed, typed, core_result, stage, batch_observations, durable_record, batch_metadata = _evaluate_locked_batch(
                session, target=target, record=_batch_request, client_request_id=validated_req_id)
            if isinstance(core_result, AcceptedCoreResult):
                # Fingerprint identifies the original request; the durable content also records server authority.
                pdcp_content = canonical_record_json(durable_record)
                pdcp_content_hash = canonical_sha256(pdcp_content)
                current_pdcp.pdcp_content = pdcp_content
                current_pdcp.pdcp_content_hash = pdcp_content_hash
        else:
            parsed, typed, core_result, stage = _evaluate_proposal(
                target=target, decode=decode, protocol_version=protocol_version, guard_required=guard_required,
                expected_target_version=expected_target_version, expected_current_hash=expected_current_hash,
                runtime_version=runtime_version, scope_bounds=scope_bounds)

        if isinstance(core_result, RejectedCoreResult):
            if validated_obs is not None:
                obs_diag = dict(core_result.diagnostic or {})
                obs_diag.setdefault("observation_id", str(validated_obs.observation.observation_id))
                obs_diag.setdefault("observed_symbol", validated_obs.observation.symbol_name)
                obs_diag.setdefault("observed_scope", [validated_obs.scope_start, validated_obs.scope_end])
                core_result = replace(core_result, diagnostic=obs_diag)
            return _persist_rejection(
                session,
                runtime_version=runtime_version,
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
                runtime_version=runtime_version,
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
            runtime_version=runtime_version,
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
            validated_observation=validated_obs,
            validated_observations=batch_observations,
            batch_metadata=batch_metadata,
        )


def _evaluate_locked_batch(session, *, target, record, client_request_id):
    parsed, typed = None, None
    stage = ValidationStage.PROTOCOL_VALIDATION
    try:
        if client_request_id is None:
            raise BatchValidationError("INVALID_BATCH_REQUEST", "Batch submissions require client_request_id.")
        observation_ids = validate_batch_envelope(record)
        rejection, guard_stage = _guard_rejection(target=target,
            expected_target_version=record["expected_target_version"], expected_current_hash=record["expected_current_hash"],
            guard_required=True, protocol_version=BATCH_PROTOCOL_VERSION)
        if rejection is not None:
            code = "BUNDLE_VERSION_MISMATCH" if rejection.failure_reason == FailureReason.TARGET_VERSION_MISMATCH else "BUNDLE_HASH_MISMATCH"
            rejection = replace(rejection, diagnostic={**rejection.diagnostic, "code": code},
                                failure_buffer=FailureBufferContext.capture(""))
            return parsed, typed, rejection, guard_stage, (), None, None
        stage = ValidationStage.PRECONDITION_GUARD
        if canonicalize_text(target.current_content) != target.current_content or canonical_sha256(target.current_content) != target.current_hash:
            raise BatchValidationError("BUNDLE_HASH_MISMATCH", "Locked target content differs from its canonical preimage hash.")
        observations, scopes = validate_bundle_for_locked_target(session, target=target, record=record, observation_ids=observation_ids)
        stage = ValidationStage.PROTOCOL_VALIDATION
        groups = parse_batch_request(record)
        parsed, typed = flatten_batch(groups, target_type=target.target_type)
        stage = ValidationStage.TRANSACTION_APPLICABILITY
        result = apply_observed_batch(target.current_content, groups, scopes, target_type=target.target_type)
        if isinstance(result, RejectedCoreResult):
            result = _enrich_diagnostic(result, protocol_version=BATCH_PROTOCOL_VERSION, stage=stage)
            return parsed, typed, result, stage, (), None, None
        evidence = [batch_scope_evidence(obs, index, len(group.transaction.edits))
                    for index, (obs, group) in enumerate(zip(observations, groups))]
        bundle_id = str(uuid.UUID(record["observation_bundle_id"]))
        durable = {**record, "observation_bundle_id": bundle_id,
                   "groups": [{**raw, "observation_id": group.observation_id} for raw, group in zip(record["groups"], groups)],
                   "editing_cycle_id": str(target.active_editing_cycle_id), "scope_evidence": evidence}
        metadata = {"observation_bundle_id": bundle_id, "group_count": len(groups),
                    "change_count": result.change_count,
                    "groups": [{"group_index": index, "observation_id": group.observation_id,
                                "change_count": len(group.transaction.edits)} for index, group in enumerate(groups)]}
        return parsed, typed, result, stage, observations, durable, metadata
    except BatchValidationError as exc:
        rejection = _core_rejection(FailureReason.CONTEXT_INVALID, str(exc), target.current_hash,
                                    protocol_version=BATCH_PROTOCOL_VERSION, stage=stage, diagnostic_extra=exc.diagnostic)
        return parsed, typed, replace(rejection, failure_buffer=FailureBufferContext.capture("")), stage, (), None, None


def _evaluate_proposal(
    *, target, decode, protocol_version: str, guard_required: bool,
    expected_target_version, expected_current_hash, encoding_diagnostic: dict | None = None,
    runtime_version: str | None = None, scope_bounds: tuple[int, int] | None = None,
) -> tuple[ParsedPDCP | None, TypedTransaction | None, AcceptedCoreResult | RejectedCoreResult, ValidationStage]:
    """Read-only fresh-proposal evaluator shared by locked submit and advisory preview."""
    if encoding_diagnostic is not None:
        return None, None, _core_rejection(
            FailureReason.TARGET_ENCODING_INVALID, "Input strings must be UTF-8 without NUL.", target.current_hash,
            protocol_version=protocol_version, stage=ValidationStage.PROTOCOL_VALIDATION,
            diagnostic_extra=encoding_diagnostic), ValidationStage.PROTOCOL_VALIDATION
    guard_rejection, guard_stage = _guard_rejection(
        target=target, expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash, guard_required=guard_required, protocol_version=protocol_version)
    if guard_rejection is not None:
        return None, None, guard_rejection, guard_stage
    parsed: ParsedPDCP | None = None
    typed: TypedTransaction | None = None
    stage = ValidationStage.TRANSACTION_APPLICABILITY
    try:
        parsed, typed = decode(target)
        profile = resolve_runtime_profile(runtime_version or _runtime_version(protocol_version))
        core_result = apply_pdcp_transaction(
            target.current_content,
            parsed,
            overlapping_matches=profile.overlapping_matches,
            enforce_singleton_selectors=profile.enforce_singleton_selectors,
            allow_span_operations=profile.span_operations,
            allow_replace_all_operations=profile.replace_all_operations,
            allow_span_context=profile.span_context,
            scope_bounds=scope_bounds,
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
            target.current_hash,
            exc.failed_change_id,
            protocol_version=protocol_version,
            stage=stage,
        )
    except TargetHashApplicabilityError as exc:
        stage = ValidationStage.TRANSACTION_APPLICABILITY
        core_result = _core_rejection(
            exc.failure_reason,
            exc.failure_detail,
            target.current_hash,
            exc.failed_change_id,
            protocol_version=protocol_version,
            stage=stage,
        )
    except ProtocolValidationError as exc:
        stage = ValidationStage.PROTOCOL_VALIDATION
        core_result = _core_rejection(
            exc.failure_reason,
            exc.failure_detail,
            target.current_hash,
            exc.failed_change_id,
            protocol_version=protocol_version,
            stage=stage,
        )
    return parsed, typed, core_result, stage


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
    sanitized_version, version_valid = sanitize_expected_target_version(expected_target_version)
    if not version_valid:
        diag = {}
        if expected_target_version is not None:
            diag["raw_expected_target_version"] = expected_target_version
        return (
            _core_rejection(
                FailureReason.CONTEXT_INVALID,
                "expected_target_version must be a non-negative integer.",
                target.current_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
                diagnostic_extra=diag,
            ),
            ValidationStage.PROTOCOL_VALIDATION,
        )
    sanitized_hash, hash_valid = sanitize_expected_current_hash(expected_current_hash)
    if not hash_valid:
        diag = {}
        if expected_current_hash is not None:
            diag["raw_expected_current_hash"] = expected_current_hash
        return (
            _core_rejection(
                FailureReason.CONTEXT_INVALID,
                "expected_current_hash must be a 64-character lowercase SHA-256 hex digest.",
                target.current_hash,
                protocol_version=protocol_version,
                stage=ValidationStage.PROTOCOL_VALIDATION,
                diagnostic_extra=diag,
            ),
            ValidationStage.PROTOCOL_VALIDATION,
        )
    if sanitized_version is not None and target.version != sanitized_version:
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
    if sanitized_hash is not None and target.current_hash != sanitized_hash:
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
    runtime_version: str | None = None,
    validated_observation: ValidatedScopeObservation | None = None,
    validated_observations: tuple = (),
    batch_metadata: dict | None = None,
) -> SubmitPDCPResult:
    after_version = before_version + 1
    envelope = bounded_warnings(accepted.warnings)
    accepted_diag: dict[str, Any] | None = None
    if accepted.warnings:
        accepted_diag = dict(envelope)
    if validated_observation is not None:
        obs_meta = {
            "observation_id": str(validated_observation.observation.observation_id),
            "symbol_name": validated_observation.observation.symbol_name,
            "symbol_kind": validated_observation.observation.symbol_kind,
            "scope_start": validated_observation.scope_start,
            "scope_end": validated_observation.scope_end,
            "observed_scope_hash": validated_observation.observed_scope_hash,
        }
        accepted_diag = {**(accepted_diag or {}), **obs_meta}
    if batch_metadata is not None:
        accepted_diag = {**(accepted_diag or {}), "batch_metadata": batch_metadata}
    log = AppendOnlyPdcpLogs(
        target_file_id=target.target_file_id,
        editing_cycle_id=target.active_editing_cycle_id,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=regeneration_attempt,
        regeneration_source=regeneration_source,
        submission_source=submission_source,
        protocol_version=protocol_version,
        runtime_version=runtime_version or _runtime_version(protocol_version),
        pdcp_content=pdcp_content,
        pdcp_content_hash=pdcp_content_hash,
        status="accepted",
        # Accepted rows without warnings leave diagnostic_json unset: SQL NULL as before, never JSON null.
        **({"diagnostic_json": accepted_diag} if accepted_diag is not None else {}),
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
    if validated_observation is not None:
        validated_observation.observation.accepted_pdcp_log_id = log.pdcp_log_id
    for observation in validated_observations:
        observation.accepted_pdcp_log_id = log.pdcp_log_id

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
        batch_metadata=batch_metadata,
        **_warning_fields(envelope),
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
    runtime_version: str | None = None,
) -> SubmitPDCPResult:
    sanitized_version, version_valid = sanitize_expected_target_version(expected_target_version)
    sanitized_hash, hash_valid = sanitize_expected_current_hash(expected_current_hash)
    sanitized_attempt, attempt_valid = sanitize_regeneration_attempt(regeneration_attempt)

    diagnostic = dict(rejection.diagnostic) if rejection.diagnostic else {}
    diagnostic["failure_context"] = available_context(
        rejection.failure_buffer or FailureBufferContext.capture("" if protocol_version == BATCH_PROTOCOL_VERSION else target.current_content),
        observed_target_version=before_version,
        observed_target_hash=before_hash,
    )
    if protocol_version == BATCH_PROTOCOL_VERSION:
        if "group_index" in diagnostic and rejection.failure_buffer is not None:
            diagnostic["failure_context"]["buffer_stage"] = (
                "scope_local_intermediate_buffer" if rejection.failure_buffer.prior_changes else "scope_local_original")
        else:
            diagnostic["failure_context"] = unavailable_context("batch_scope_not_evaluated")
    if "exact_candidates" in diagnostic:
        candidates = {**diagnostic["exact_candidates"], **context_identity(diagnostic["failure_context"])}
        diagnostic["exact_candidates"] = bound_candidates("exact_candidates", candidates)
    if not version_valid and expected_target_version is not None:
        diagnostic["raw_expected_target_version"] = expected_target_version
    if not hash_valid and expected_current_hash is not None:
        diagnostic["raw_expected_current_hash"] = expected_current_hash
    if not attempt_valid and regeneration_attempt is not None:
        diagnostic["raw_attempt"] = regeneration_attempt
        diagnostic["raw_regeneration_attempt"] = regeneration_attempt

    log = AppendOnlyPdcpLogs(
        target_file_id=target.target_file_id,
        editing_cycle_id=target.active_editing_cycle_id,
        parent_pdcp_log_id=parent_pdcp_log_id,
        regeneration_attempt=sanitized_attempt,
        regeneration_source=regeneration_source,
        submission_source=submission_source,
        protocol_version=protocol_version,
        runtime_version=runtime_version or _runtime_version(protocol_version),
        pdcp_content=pdcp_content,
        pdcp_content_hash=pdcp_content_hash,
        status="rejected",
        failure_reason=rejection.failure_reason.value,
        failure_detail=rejection.failure_detail,
        failed_change_id=rejection.failed_change_id,
        diagnostic_json=diagnostic,
        expected_target_version=sanitized_version,
        expected_current_hash=sanitized_hash,
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
        diagnostic=diagnostic,
        validation_stage=stage,
        current_context=None if protocol_version == BATCH_PROTOCOL_VERSION else _target_context(target),
        client_request_id=client_request_id,
        near_miss_buffer=rejection.near_miss_buffer,
        code=diagnostic.get("code") if isinstance(diagnostic.get("code"), str) else None,
    )


def _warning_fields(envelope: dict) -> dict:
    return {"warnings": tuple(warning_strings(envelope["warnings"])), "warning_details": tuple(envelope["warnings"]),
            "warning_count": envelope["warning_count"], "warnings_truncated": envelope["warnings_truncated"]}


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
            batch_metadata=(log.diagnostic_json or {}).get("batch_metadata"),
            **_warning_fields(_stored_warnings(log.diagnostic_json)),
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
        current_context=None if log.protocol_version == BATCH_PROTOCOL_VERSION else _target_context(target),
        deduplicated=True,
        client_request_id=log.client_request_id,
        code=diag.get("code") if isinstance(diag.get("code"), str) else None,
    )


def _stored_warnings(diagnostic: Any) -> dict:
    """Recorded accepted-row warnings; older rows have none."""
    if isinstance(diagnostic, dict) and isinstance(diagnostic.get("warnings"), list):
        return {"warnings": diagnostic["warnings"],
                "warning_count": diagnostic.get("warning_count", len(diagnostic["warnings"])),
                "warnings_truncated": bool(diagnostic.get("warnings_truncated", False))}
    return bounded_warnings(())


def _runtime_version(protocol_version: str) -> str:
    if protocol_version == REPLACEMENT_PROTOCOL_VERSION:
        return REPLACEMENT_RUNTIME_VERSION
    return OPERATIONS_RUNTIME_VERSION if protocol_version == OPERATIONS_PROTOCOL_VERSION else RUNTIME_VERSION


def _target_context(target: CloudTargetFiles) -> dict:
    return available_context(
        FailureBufferContext.capture(target.current_content),
        observed_target_version=target.version,
        observed_target_hash=target.current_hash,
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
    sanitized_attempt, _ = sanitize_regeneration_attempt(regeneration_attempt)
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
            regeneration_attempt=sanitized_attempt,
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
        existing.regeneration_attempt = sanitized_attempt
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
    diagnostic_extra: dict[str, Any] | None = None,
) -> RejectedCoreResult:
    is_typed = protocol_version in (TYPED_PROTOCOL_VERSION, OPERATIONS_PROTOCOL_VERSION, REPLACEMENT_PROTOCOL_VERSION, BATCH_PROTOCOL_VERSION)
    diagnostic: dict[str, Any] = {
        "format": protocol_version,
        "retryable": reason in RETRYABLE_FAILURE_REASONS,
        "requires_new_submission": True,
        "validation_stage": stage.value,
    }
    if not is_typed:
        diagnostic["requires_new_pdcp"] = True

    if reason in {FailureReason.MANIFEST_INVALID, FailureReason.MANIFEST_MISSING}:
        if protocol_version == REPLACEMENT_PROTOCOL_VERSION:
            diagnostic.update({"allowed_operations": ["replace_all"], "sole_operation": True,
                               "required_operation_fields": ["op", "replace"]})
        elif protocol_version == OPERATIONS_PROTOCOL_VERSION:
            diagnostic.update({"allowed_operations": ["match", "span"],
                               "required_span_fields": ["op", "start", "end", "expected_text", "replace"],
                               "required_match_fields": ["op", "match", "replace"],
                               "valid_risk_values": sorted(VALID_RISK_VALUES)})
        elif is_typed:
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
    if diagnostic_extra:
        diagnostic.update(diagnostic_extra)
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
    if protocol_version in (TYPED_PROTOCOL_VERSION, OPERATIONS_PROTOCOL_VERSION, REPLACEMENT_PROTOCOL_VERSION, BATCH_PROTOCOL_VERSION):
        diag.pop("requires_new_pdcp", None)
    else:
        diag["requires_new_pdcp"] = True
    return replace(rejection, diagnostic=diag)


MAX_DIFFERING_FIELDS = 10
_TYPED_PROTOCOLS = (TYPED_PROTOCOL_VERSION, OPERATIONS_PROTOCOL_VERSION, REPLACEMENT_PROTOCOL_VERSION, BATCH_PROTOCOL_VERSION)


def _conflict_evidence(existing_log, *, protocol_version, pdcp_content_hash, expected_target_version,
                       expected_current_hash, parent, record_content) -> dict:
    """Advisory comparison of a conflicting proposal with the stored keyed row."""
    stored = {name: getattr(existing_log, name, None) for name in (
        "protocol_version", "pdcp_content_hash", "expected_target_version", "expected_current_hash",
        "parent_pdcp_log_id", "pdcp_content")}
    stored_parent = str(stored["parent_pdcp_log_id"]) if stored["parent_pdcp_log_id"] else None
    submitted_parent = str(_try_coerce_uuid(parent) or parent) if parent is not None else None
    components = [name for name, old, new in (
        ("protocol_version", stored["protocol_version"], protocol_version),
        ("pdcp_content_hash", stored["pdcp_content_hash"], pdcp_content_hash),
        ("expected_target_version", stored["expected_target_version"],
         sanitize_expected_target_version(expected_target_version)[0]),
        ("expected_current_hash", stored["expected_current_hash"],
         sanitize_expected_current_hash(expected_current_hash)[0]),
        ("parent_pdcp_log_id", stored_parent, submitted_parent),
    ) if old != new]
    fields: list[str] | None = None
    if ("pdcp_content_hash" in components and record_content is not None
            and protocol_version in _TYPED_PROTOCOLS and stored["protocol_version"] == protocol_version):
        try:
            old_record, new_record = json.loads(stored["pdcp_content"]), json.loads(record_content)
        except (TypeError, ValueError):
            old_record = new_record = None
        if isinstance(old_record, dict) and isinstance(new_record, dict) and "evidence_format" not in old_record:
            if protocol_version == BATCH_PROTOCOL_VERSION:
                old_record = {key: value for key, value in old_record.items() if key not in {"scope_evidence", "editing_cycle_id"}}
            fields = []
            _diff_paths(old_record, new_record, "", fields, depth=0)
    elif "pdcp_content_hash" in components:
        fields = ["pdcp_content"]
    evidence: dict[str, Any] = {"differing_components": components}
    if fields is not None:
        evidence.update(differing_fields=fields[:MAX_DIFFERING_FIELDS],
                        differing_fields_truncated=len(fields) > MAX_DIFFERING_FIELDS)
    return evidence


def _diff_paths(old: Any, new: Any, path: str, out: list[str], *, depth: int) -> None:
    """Collect JSON paths where two decoded records differ (bounded, deterministic)."""
    if len(out) > MAX_DIFFERING_FIELDS:
        return
    label = (path or "$")[:256]
    if type(old) is not type(new) or depth >= 8:
        if type(old) is not type(new) or old != new:
            out.append(label)
        return
    if isinstance(old, dict):
        for key in sorted(set(old) | set(new), key=str):
            child = f"{path}.{key}" if path else str(key)
            if key not in old or key not in new:
                out.append(child[:256])
            else:
                _diff_paths(old[key], new[key], child, out, depth=depth + 1)
    elif isinstance(old, list):
        for index in range(max(len(old), len(new))):
            child = f"{path}[{index}]"
            if index >= len(old) or index >= len(new):
                out.append(child[:256])
            else:
                _diff_paths(old[index], new[index], child, out, depth=depth + 1)
    elif old != new:
        out.append(label)


def _compute_request_fingerprint(
    *,
    protocol_version: str,
    target_file_id: str,
    pdcp_content_hash: str,
    expected_target_version: int | None,
    expected_current_hash: str | None,
    parent_pdcp_log_id: str | None,
    identity_domain: str | None = None,
) -> str:
    envelope = {
        "protocol_version": protocol_version,
        "target_file_id": target_file_id,
        "pdcp_content_hash": pdcp_content_hash,
        "expected_target_version": expected_target_version,
        "expected_current_hash": expected_current_hash,
        "parent_pdcp_log_id": parent_pdcp_log_id,
    }
    if identity_domain is not None:
        envelope["identity_domain"] = identity_domain
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
    with session.no_autoflush:
        parent = session.get(AppendOnlyPdcpLogs, parent_uuid)
    if parent is None:
        return None, "parent_pdcp_log_id does not exist."
    if parent.target_file_id != target_uuid:
        return None, "parent_pdcp_log_id belongs to a different target_file_id."
    if parent.status != "rejected":
        return None, "parent_pdcp_log_id must reference a rejected attempt."
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
        target_file_id=safe_input_text(target_file_id),
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
            "failure_context": unavailable_context("invalid_target_id"),
        },
        current_context=unavailable_context("invalid_target_id"),
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
