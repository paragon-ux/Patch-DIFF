"""Deterministic replay from persisted accepted PDCP logs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.parser import PDCPParseError, parse_pdcp
from app.pdcp.protocol_validator import ProtocolValidationError, validate_pdcp
from app.storage.models import AppendOnlyPdcpLogs, CloudTargetFiles, TargetSnapshots


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: str
    target_file_id: uuid.UUID
    reconstructed_content: str | None
    reconstructed_hash: str | None
    current_hash: str | None
    accepted_transactions_replayed: int
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None
    pdcp_log_id: uuid.UUID | None = None


def replay_target(session: Session, *, target_file_id: uuid.UUID | str) -> ReplayResult:
    target_uuid = _coerce_uuid(target_file_id)
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
            accepted_transactions_replayed=0,
            failure_reason=FailureReason.REPLAY_PROTOCOL_INVALID,
            failure_detail="Initial target snapshot was not found.",
        )

    buffer = initial_snapshot.content
    accepted_logs = session.scalars(
        select(AppendOnlyPdcpLogs)
        .where(
            AppendOnlyPdcpLogs.target_file_id == target.target_file_id,
            AppendOnlyPdcpLogs.status == "accepted",
        )
        .order_by(AppendOnlyPdcpLogs.log_sequence)
    ).all()

    for replayed_count, log in enumerate(accepted_logs, start=1):
        try:
            parsed = parse_pdcp(log.pdcp_content)
            validate_pdcp(parsed)
        except (PDCPParseError, ProtocolValidationError) as exc:
            return ReplayResult(
                status="failed",
                target_file_id=target.target_file_id,
                reconstructed_content=None,
                reconstructed_hash=None,
                current_hash=target.current_hash,
                accepted_transactions_replayed=replayed_count - 1,
                failure_reason=FailureReason.REPLAY_PROTOCOL_INVALID,
                failure_detail=getattr(exc, "failure_detail", "Replay protocol validation failed."),
                pdcp_log_id=log.pdcp_log_id,
            )

        result = apply_pdcp_transaction(buffer, parsed)
        if not isinstance(result, AcceptedCoreResult):
            return ReplayResult(
                status="failed",
                target_file_id=target.target_file_id,
                reconstructed_content=None,
                reconstructed_hash=None,
                current_hash=target.current_hash,
                accepted_transactions_replayed=replayed_count - 1,
                failure_reason=FailureReason.REPLAY_TRANSACTION_INVALID,
                failure_detail=result.failure_detail,
                pdcp_log_id=log.pdcp_log_id,
            )

        buffer = result.target_content
        if log.after_hash != result.after_hash:
            return ReplayResult(
                status="failed",
                target_file_id=target.target_file_id,
                reconstructed_content=None,
                reconstructed_hash=result.after_hash,
                current_hash=target.current_hash,
                accepted_transactions_replayed=replayed_count,
                failure_reason=FailureReason.REPLAY_HASH_MISMATCH,
                failure_detail="Computed replay hash does not match logged after_hash.",
                pdcp_log_id=log.pdcp_log_id,
            )

    reconstructed_hash = canonical_sha256(buffer)
    return ReplayResult(
        status="success",
        target_file_id=target.target_file_id,
        reconstructed_content=buffer,
        reconstructed_hash=reconstructed_hash,
        current_hash=target.current_hash,
        accepted_transactions_replayed=len(accepted_logs),
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


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
