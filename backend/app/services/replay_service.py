"""Deterministic replay over initial canonical upload state plus accepted logs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.canonicalization import canonicalize_text
from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult
from app.core.versions import UnsupportedRuntimeVersionError, resolve_overlapping_matches
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.models import SUPPORTED_PROTOCOL_VERSION, ParsedPDCP
from app.pdcp.parser import PDCPParseError, parse_pdcp
from app.pdcp.protocol_validator import ProtocolValidationError, validate_pdcp
from app.pdcp.typed import TYPED_PROTOCOL_VERSION, decode_record, to_parsed_transaction
from app.storage.models import AppendOnlyPdcpLogs, CloudTargetFiles, TargetSnapshots


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: str
    target_file_id: uuid.UUID | str
    reconstructed_content: str | None
    reconstructed_hash: str | None
    current_hash: str | None
    accepted_transactions_replayed: int
    materialized_state_matches: bool | None = None
    materialized_state_checks: dict[str, bool] | None = None
    reconstructed_version: int | None = None
    current_version: int | None = None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None
    pdcp_log_id: uuid.UUID | None = None


def replay_target(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
) -> ReplayResult:
    """Reconstruct target content strictly from initial snapshot + accepted logs."""

    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return ReplayResult(
            status="failed",
            target_file_id=str(target_file_id),
            reconstructed_content=None,
            reconstructed_hash=None,
            current_hash=None,
            accepted_transactions_replayed=0,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="target_file_id must be a valid UUID.",
        )

    target = session.get(CloudTargetFiles, target_uuid)
    if target is None:
        return ReplayResult(
            status="failed",
            target_file_id=target_uuid,
            reconstructed_content=None,
            reconstructed_hash=None,
            current_hash=None,
            accepted_transactions_replayed=0,
            failure_reason=FailureReason.TARGET_NOT_FOUND,
            failure_detail="Target file was not found.",
        )

    initial_snapshot = _load_initial_snapshot(session, target)
    if initial_snapshot is None:
        return ReplayResult(
            status="failed",
            target_file_id=target.target_file_id,
            reconstructed_content=None,
            reconstructed_hash=None,
            current_hash=target.current_hash,
            current_version=target.version,
            accepted_transactions_replayed=0,
            failure_reason=FailureReason.REPLAY_PROTOCOL_INVALID,
            failure_detail="Initial upload snapshot is missing.",
        )

    if initial_snapshot.target_file_id != target.target_file_id:
        return ReplayResult(
            status="failed",
            target_file_id=target.target_file_id,
            reconstructed_content=None,
            reconstructed_hash=None,
            current_hash=target.current_hash,
            current_version=target.version,
            accepted_transactions_replayed=0,
            failure_reason=FailureReason.REPLAY_PROTOCOL_INVALID,
            failure_detail="Initial snapshot target_file_id does not match the replayed target.",
        )

    buffer = canonicalize_text(initial_snapshot.content)
    if canonical_sha256(buffer) != initial_snapshot.content_hash:
        return ReplayResult(
            status="failed",
            target_file_id=target.target_file_id,
            reconstructed_content=None,
            reconstructed_hash=canonical_sha256(buffer),
            current_hash=target.current_hash,
            current_version=target.version,
            accepted_transactions_replayed=0,
            failure_reason=FailureReason.REPLAY_HASH_MISMATCH,
            failure_detail="Initial upload snapshot content does not match its content_hash.",
        )

    accepted_logs = session.scalars(
        select(AppendOnlyPdcpLogs)
        .where(
            AppendOnlyPdcpLogs.target_file_id == target.target_file_id,
            AppendOnlyPdcpLogs.status == "accepted",
        )
        .order_by(AppendOnlyPdcpLogs.log_sequence)
    ).all()

    expected_version = initial_snapshot.version
    for replayed_count, log in enumerate(accepted_logs, start=1):
        if log.target_file_id != target.target_file_id:
            return _failed(
                target,
                FailureReason.REPLAY_PROTOCOL_INVALID,
                "Logged target_file_id does not match the replayed target.",
                replayed=replayed_count - 1,
                pdcp_log_id=log.pdcp_log_id,
            )

        try:
            overlapping_matches = resolve_overlapping_matches(log.runtime_version)
        except UnsupportedRuntimeVersionError as exc:
            return _failed(
                target,
                FailureReason.REPLAY_PROTOCOL_INVALID,
                str(exc),
                replayed=replayed_count - 1,
                pdcp_log_id=log.pdcp_log_id,
            )

        try:
            parsed = _decode_logged_transaction(log, target)
        except (PDCPParseError, ProtocolValidationError, _UnsupportedLoggedProtocol) as exc:
            return _failed(
                target,
                FailureReason.REPLAY_PROTOCOL_INVALID,
                str(exc),
                replayed=replayed_count - 1,
                pdcp_log_id=log.pdcp_log_id,
            )

        if log.before_version != expected_version or log.after_version != expected_version + 1:
            return _failed(
                target,
                FailureReason.REPLAY_PROTOCOL_INVALID,
                "Logged version chain is not contiguous with the replay buffer.",
                replayed=replayed_count - 1,
                pdcp_log_id=log.pdcp_log_id,
            )
        buffer_hash = canonical_sha256(buffer)
        if log.before_hash != buffer_hash:
            return _failed(
                target,
                FailureReason.REPLAY_HASH_MISMATCH,
                "Logged before_hash does not match the replay buffer before this transaction.",
                replayed=replayed_count - 1,
                pdcp_log_id=log.pdcp_log_id,
                reconstructed_hash=buffer_hash,
            )

        result = apply_pdcp_transaction(
            buffer,
            parsed,
            overlapping_matches=overlapping_matches,
        )
        if not isinstance(result, AcceptedCoreResult):
            return _failed(
                target,
                FailureReason.REPLAY_TRANSACTION_INVALID,
                result.failure_detail,
                replayed=replayed_count - 1,
                pdcp_log_id=log.pdcp_log_id,
            )

        if canonical_sha256(log.pdcp_content) != log.pdcp_content_hash:
            return _failed(
                target,
                FailureReason.REPLAY_HASH_MISMATCH,
                "Logged pdcp_content does not match logged pdcp_content_hash.",
                replayed=replayed_count - 1,
                pdcp_log_id=log.pdcp_log_id,
            )

        buffer = result.target_content
        expected_version = log.after_version
        if log.after_hash != result.after_hash:
            return _failed(
                target,
                FailureReason.REPLAY_HASH_MISMATCH,
                "Computed replay hash does not match logged after_hash.",
                replayed=replayed_count,
                pdcp_log_id=log.pdcp_log_id,
                reconstructed_hash=result.after_hash,
            )

    reconstructed_hash = canonical_sha256(buffer)
    current_canonical = canonicalize_text(target.current_content)
    current_recomputed_hash = canonical_sha256(current_canonical)
    checks = {
        "content_matches": current_canonical == buffer,
        "stored_hash_matches": target.current_hash == reconstructed_hash,
        "recomputed_hash_matches": current_recomputed_hash == reconstructed_hash,
        "version_matches": target.version == expected_version,
    }
    return ReplayResult(
        status="success",
        target_file_id=target.target_file_id,
        reconstructed_content=buffer,
        reconstructed_hash=reconstructed_hash,
        current_hash=target.current_hash,
        reconstructed_version=expected_version,
        current_version=target.version,
        accepted_transactions_replayed=len(accepted_logs),
        materialized_state_matches=all(checks.values()),
        materialized_state_checks=checks,
    )


class _UnsupportedLoggedProtocol(Exception):
    pass


def _decode_logged_transaction(log: AppendOnlyPdcpLogs, target: CloudTargetFiles) -> ParsedPDCP:
    """Dispatch on the recorded protocol version. Old rows are never reinterpreted."""

    if log.protocol_version == SUPPORTED_PROTOCOL_VERSION:
        parsed = parse_pdcp(log.pdcp_content)
        validate_pdcp(parsed)
        if parsed.header.target_file_id != str(target.target_file_id):
            raise ProtocolValidationError(
                FailureReason.CONTEXT_INVALID,
                "Logged PDCP target_file_id does not match the replayed target.",
            )
        return parsed
    if log.protocol_version == TYPED_PROTOCOL_VERSION:
        typed = decode_record(log.pdcp_content)
        if typed.target_file_id != str(target.target_file_id):
            raise ProtocolValidationError(
                FailureReason.CONTEXT_INVALID,
                "Logged typed transaction target_file_id does not match the replayed target.",
            )
        return to_parsed_transaction(typed, target_type=target.target_type)
    raise _UnsupportedLoggedProtocol(f"Unsupported logged protocol_version: {log.protocol_version!r}.")


def _failed(
    target: CloudTargetFiles,
    reason: FailureReason,
    detail: str,
    *,
    replayed: int,
    pdcp_log_id: uuid.UUID | None = None,
    reconstructed_hash: str | None = None,
) -> ReplayResult:
    return ReplayResult(
        status="failed",
        target_file_id=target.target_file_id,
        reconstructed_content=None,
        reconstructed_hash=reconstructed_hash,
        current_hash=target.current_hash,
        current_version=target.version,
        accepted_transactions_replayed=replayed,
        failure_reason=reason,
        failure_detail=detail,
        pdcp_log_id=pdcp_log_id,
    )


def _load_initial_snapshot(session: Session, target: CloudTargetFiles) -> TargetSnapshots | None:
    if target.initial_snapshot_id is not None:
        snapshot = session.get(TargetSnapshots, target.initial_snapshot_id)
        if snapshot is not None:
            return snapshot
    return session.scalar(
        select(TargetSnapshots)
        .where(
            TargetSnapshots.target_file_id == target.target_file_id,
            TargetSnapshots.snapshot_reason == "initial_upload",
        )
        .order_by(TargetSnapshots.created_at, TargetSnapshots.snapshot_id)
        .limit(1)
    )


def _try_coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
