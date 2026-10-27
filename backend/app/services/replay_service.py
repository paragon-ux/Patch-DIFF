"""Deterministic replay over initial canonical upload state plus accepted logs."""

from __future__ import annotations

import uuid
import json
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.canonicalization import canonicalize_text
from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.input_text import safe_input_text
from app.core.result import AcceptedCoreResult
from app.core.versions import UnsupportedRuntimeVersionError, resolve_runtime_profile
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.observed_batch import (
    BATCH_PROTOCOL_VERSION, BATCH_RUNTIME_VERSION, BatchValidationError, BatchScope,
    parse_batch_request, apply_observed_batch,
)
from app.pdcp.typed import canonical_record_json
from app.services.scope_observation_service import batch_scope_evidence
from app.pdcp.operations import OPERATIONS_PROTOCOL_VERSION, decode_operations_record, to_parsed_operations
from app.pdcp.replacement import REPLACEMENT_PROTOCOL_VERSION, decode_replacement_record, to_parsed_replacement
from app.pdcp.models import SUPPORTED_PROTOCOL_VERSION, ParsedPDCP
from app.pdcp.parser import PDCPParseError, parse_pdcp
from app.pdcp.protocol_validator import ProtocolValidationError, validate_pdcp
from app.pdcp.typed import TYPED_PROTOCOL_VERSION, decode_record, to_parsed_transaction
from app.storage.models import AppendOnlyPdcpLogs, CloudTargetFiles, TargetScopeObservations, TargetSnapshots
from app.storage.repositories import select_target_for_update


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
    code: str | None = None


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
            target_file_id=safe_input_text(target_file_id),
            reconstructed_content=None,
            reconstructed_hash=None,
            current_hash=None,
            accepted_transactions_replayed=0,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="target_file_id must be a valid UUID.",
        )

    with _transaction(session):
        target = session.execute(select_target_for_update(target_uuid)).scalar_one_or_none()
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

        accepted_logs = session.execute(
            select(AppendOnlyPdcpLogs)
            .where(
                AppendOnlyPdcpLogs.target_file_id == target.target_file_id,
                AppendOnlyPdcpLogs.status == "accepted",
            )
            .order_by(AppendOnlyPdcpLogs.log_sequence)
            .execution_options(populate_existing=True)
        ).scalars().all()

        obs_by_log_id: dict[uuid.UUID, list[TargetScopeObservations]] = {}
        if accepted_logs:
            observations = session.execute(
                select(TargetScopeObservations)
                .join(
                    AppendOnlyPdcpLogs,
                    TargetScopeObservations.accepted_pdcp_log_id == AppendOnlyPdcpLogs.pdcp_log_id,
                )
                .where(
                    AppendOnlyPdcpLogs.target_file_id == target.target_file_id,
                    AppendOnlyPdcpLogs.status == "accepted",
                )
                .execution_options(populate_existing=True)
            ).scalars().all()
            for obs in observations:
                obs_by_log_id.setdefault(obs.accepted_pdcp_log_id, []).append(obs)

        expected_version = initial_snapshot.version
        for replayed_count, log in enumerate(accepted_logs, start=1):
            batch_code = "BATCH_REPLAY_INTEGRITY_FAILURE" if log.protocol_version == BATCH_PROTOCOL_VERSION else None
            if log.target_file_id != target.target_file_id:
                return _failed(
                    target,
                    FailureReason.REPLAY_PROTOCOL_INVALID,
                    "Logged target_file_id does not match the replayed target.",
                    code=batch_code,
                    replayed=replayed_count - 1,
                    pdcp_log_id=log.pdcp_log_id,
                )

            try:
                profile = resolve_runtime_profile(log.runtime_version)
            except UnsupportedRuntimeVersionError as exc:
                return _failed(
                    target,
                    FailureReason.REPLAY_PROTOCOL_INVALID,
                    str(exc),
                    code=batch_code,
                    replayed=replayed_count - 1,
                    pdcp_log_id=log.pdcp_log_id,
                )

            try:
                parsed = None if log.protocol_version == BATCH_PROTOCOL_VERSION else _decode_logged_transaction(log, target)
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
                    code=batch_code,
                    replayed=replayed_count - 1,
                    pdcp_log_id=log.pdcp_log_id,
                )
            buffer_hash = canonical_sha256(buffer)
            if log.before_hash != buffer_hash:
                return _failed(
                    target,
                    FailureReason.REPLAY_HASH_MISMATCH,
                    "Logged before_hash does not match the replay buffer before this transaction.",
                    code=batch_code,
                    replayed=replayed_count - 1,
                    pdcp_log_id=log.pdcp_log_id,
                    reconstructed_hash=buffer_hash,
                )

            if log.protocol_version == BATCH_PROTOCOL_VERSION:
                try:
                    result = _replay_observed_batch(log, target, buffer, obs_by_log_id.get(log.pdcp_log_id, []))
                except (BatchValidationError, ValueError, TypeError, KeyError) as exc:
                    return replace(_failed(target, FailureReason.REPLAY_PROTOCOL_INVALID,
                        f"Batch replay integrity failure: {exc}", replayed=replayed_count - 1, pdcp_log_id=log.pdcp_log_id),
                        code="BATCH_REPLAY_INTEGRITY_FAILURE")
                buffer = result.target_content
                expected_version = log.after_version
                continue

            scope_bounds: tuple[int, int] | None = None
            linked_observations = obs_by_log_id.get(log.pdcp_log_id, [])
            diagnostic = log.diagnostic_json if isinstance(log.diagnostic_json, dict) else {}
            if "observation_id" in diagnostic or linked_observations:
                observation_uuid = _try_coerce_uuid(diagnostic.get("observation_id"))
                if observation_uuid is None or len(linked_observations) != 1:
                    return _failed(
                        target, FailureReason.REPLAY_PROTOCOL_INVALID,
                        "Observed transaction requires exactly one authoritative observation linkage and recorded observation_id.",
                        replayed=replayed_count - 1, pdcp_log_id=log.pdcp_log_id,
                    )
                obs = linked_observations[0]
                if (
                    obs.observation_id != observation_uuid
                    or obs.accepted_pdcp_log_id != log.pdcp_log_id
                    or obs.target_file_id != target.target_file_id
                    or obs.editing_cycle_id != log.editing_cycle_id
                    or obs.target_version != log.before_version
                    or obs.target_current_hash != log.before_hash
                    or not 0 <= obs.scope_start <= obs.scope_end <= len(buffer)
                    or any(type(diagnostic.get(key)) is not int for key in ("scope_start", "scope_end"))
                    or diagnostic["scope_start"] != obs.scope_start
                    or diagnostic["scope_end"] != obs.scope_end
                    or diagnostic.get("observed_scope_hash") != obs.observed_scope_hash
                    or canonical_sha256(buffer[obs.scope_start:obs.scope_end]) != obs.observed_scope_hash
                ):
                    return _failed(
                        target,
                        FailureReason.REPLAY_PROTOCOL_INVALID,
                        "Authoritative observation identity, target, cycle, preimage or scope integrity does not match the replayed transaction.",
                        replayed=replayed_count - 1,
                        pdcp_log_id=log.pdcp_log_id,
                    )
                scope_bounds = (obs.scope_start, obs.scope_end)

            result = apply_pdcp_transaction(
                buffer,
                parsed,
                overlapping_matches=profile.overlapping_matches,
                enforce_singleton_selectors=profile.enforce_singleton_selectors,
                allow_span_operations=profile.span_operations,
                allow_replace_all_operations=profile.replace_all_operations,
                allow_span_context=profile.span_context,
                collect_warnings=False,
                scope_bounds=scope_bounds,
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
            "content_matches": target.current_content == buffer,
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


def _replay_observed_batch(log, target, buffer, linked):
    def fail(detail):
        raise BatchValidationError("BATCH_REPLAY_INTEGRITY_FAILURE", detail)

    if log.runtime_version != BATCH_RUNTIME_VERSION or canonical_sha256(log.pdcp_content) != log.pdcp_content_hash:
        fail("Unknown batch runtime or altered record hash.")
    record = json.loads(log.pdcp_content)
    if not isinstance(record, dict) or canonical_record_json(record) != log.pdcp_content:
        fail("Batch record must be canonical JSON.")
    request = {key: value for key, value in record.items() if key not in {"scope_evidence", "editing_cycle_id"}}
    groups = parse_batch_request(request)
    if (request["target_file_id"] != str(target.target_file_id)
            or record.get("editing_cycle_id") != str(log.editing_cycle_id)
            or request["expected_target_version"] != log.before_version
            or request["expected_current_hash"] != log.before_hash
            or log.expected_target_version != log.before_version or log.expected_current_hash != log.before_hash):
        fail("Batch target, cycle or global preimage guard differs.")
    if len(linked) != len(groups) or {str(row.observation_id) for row in linked} != {g.observation_id for g in groups}:
        fail("Missing, additional or duplicated authoritative observation linkage.")
    by_id = {str(row.observation_id): row for row in linked}
    expected_evidence, scopes = [], []
    for index, group in enumerate(groups):
        row = by_id[group.observation_id]
        if (str(row.observation_bundle_id) != request["observation_bundle_id"]
                or row.accepted_pdcp_log_id != log.pdcp_log_id or row.target_file_id != target.target_file_id
                or row.editing_cycle_id != log.editing_cycle_id or row.target_version != log.before_version
                or row.target_current_hash != log.before_hash):
            fail("Authoritative observation bundle, linkage or preimage differs.")
        expected_evidence.append(batch_scope_evidence(row, index, len(group.transaction.edits)))
        scopes.append(BatchScope(group.observation_id, row.bundle_ordinal, row.scope_start, row.scope_end, row.observed_scope_hash))
    # Canonical serialization distinguishes booleans from integer coordinates and indices.
    if canonical_record_json({"evidence": record.get("scope_evidence")}) != canonical_record_json({"evidence": expected_evidence}):
        fail("Authoritative scope evidence or group ordering differs.")
    metadata = {"observation_bundle_id": request["observation_bundle_id"], "group_count": len(groups),
                "change_count": sum(len(group.transaction.edits) for group in groups),
                "groups": [{"group_index": index, "observation_id": group.observation_id,
                            "change_count": len(group.transaction.edits)} for index, group in enumerate(groups)]}
    if canonical_record_json((log.diagnostic_json or {}).get("batch_metadata", {})) != canonical_record_json(metadata):
        fail("Recorded group mapping differs from authoritative batch order.")
    result = apply_observed_batch(buffer, groups, tuple(scopes), target_type=target.target_type, collect_warnings=False)
    if (not isinstance(result, AcceptedCoreResult) or result.after_hash != log.after_hash
            or result.change_count != log.change_count):
        fail("Batch operations, count or resulting hash differ.")
    return result


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
    if log.protocol_version == REPLACEMENT_PROTOCOL_VERSION:
        typed = decode_replacement_record(log.pdcp_content, runtime_version=log.runtime_version)
        if typed.target_file_id != str(target.target_file_id):
            raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "Logged replacement target does not match replay target.")
        return to_parsed_replacement(typed, target_type=target.target_type)
    if log.protocol_version == OPERATIONS_PROTOCOL_VERSION:
        typed = decode_operations_record(log.pdcp_content, runtime_version=log.runtime_version)
        if typed.target_file_id != str(target.target_file_id):
            raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "Logged operations target does not match replay target.")
        return to_parsed_operations(typed, target_type=target.target_type)
    if log.protocol_version == TYPED_PROTOCOL_VERSION:
        typed = decode_record(log.pdcp_content, runtime_version=log.runtime_version)
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
    code: str | None = None,
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
        code=code,
    )


def _load_initial_snapshot(session: Session, target: CloudTargetFiles) -> TargetSnapshots | None:
    if target.initial_snapshot_id is not None:
        snapshot = session.execute(
            select(TargetSnapshots)
            .where(TargetSnapshots.snapshot_id == target.initial_snapshot_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if snapshot is not None:
            return snapshot
    return session.execute(
        select(TargetSnapshots)
        .where(
            TargetSnapshots.target_file_id == target.target_file_id,
            TargetSnapshots.snapshot_reason == "initial_upload",
        )
        .order_by(TargetSnapshots.created_at, TargetSnapshots.snapshot_id)
        .limit(1)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


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


def _try_coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
