"""Atomic finalization service combining SAVE, replay verification, and export in a single transaction."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.core.input_text import invalid_text_paths, safe_input_text
from app.core.line_endings import EXPORT_FORMATS
from app.core.hashing import canonicalize_text
from app.services.export_service import export_target
from app.services.performance_events import timed
from app.services.replay_service import replay_target
from app.services.save_service import save_target, save_target_locked
from app.storage.models import CloudTargetFiles, TargetFinalizations
from app.storage.repositories import select_target_for_update

_DEFAULT_SAVE_TARGET = save_target
_DEFAULT_REPLAY_TARGET = replay_target

_CLIENT_REQUEST_ID_RE = re.compile(r"^[\x21-\x7e]{1,128}$")
MAX_INLINE_EXPORT_BYTES = 1_048_576  # 1 MiB UTF-8 byte cap for inline wire delivery


def _try_coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def compute_finalization_fingerprint(
    *,
    target_file_id: uuid.UUID | str,
    expected_target_version: int | None,
    expected_current_hash: str | None,
    format: str,
) -> tuple[int, str]:
    """Compute (fingerprint_version, sha256_hex) over canonical finalization arguments."""
    payload = {
        "expected_current_hash": expected_current_hash,
        "expected_target_version": expected_target_version,
        "format": format,
        "target_file_id": str(target_file_id),
        "version": 1,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return 1, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class _DetachedFinalizationRecord:
    """Detached snapshot of TargetFinalizations to avoid SQLAlchemy autobegin post-rollback."""
    finalization_id: uuid.UUID
    target_file_id: uuid.UUID
    client_request_id: str
    fingerprint_version: int
    request_fingerprint: str
    status: str
    snapshot_id: uuid.UUID | None
    closed_editing_cycle_id: uuid.UUID | None
    new_editing_cycle_id: uuid.UUID | None
    saved_target_version: int | None
    canonical_current_hash: str | None
    filename: str | None
    export_format: str | None
    content_eol: str | None
    source_line_endings: dict | None
    content_sha256: str | None
    content_bytes: int | None
    exported_content: str | None
    failure_code: str | None
    failure_detail: str | None
    materialized_state_checks: dict[str, Any] | None = None


def _materialize_finalization(record: TargetFinalizations) -> _DetachedFinalizationRecord:
    sle = record.source_line_endings
    if isinstance(sle, dict):
        sle = dict(sle)
    msc = getattr(record, "materialized_state_checks", None)
    if isinstance(msc, dict):
        msc = dict(msc)

    return _DetachedFinalizationRecord(
        finalization_id=record.finalization_id,
        target_file_id=record.target_file_id,
        client_request_id=record.client_request_id,
        fingerprint_version=record.fingerprint_version,
        request_fingerprint=record.request_fingerprint,
        status=record.status,
        snapshot_id=record.snapshot_id,
        closed_editing_cycle_id=record.closed_editing_cycle_id,
        new_editing_cycle_id=record.new_editing_cycle_id,
        saved_target_version=record.saved_target_version,
        canonical_current_hash=record.canonical_current_hash,
        filename=record.filename,
        export_format=record.export_format,
        content_eol=record.content_eol,
        source_line_endings=sle,
        content_sha256=record.content_sha256,
        content_bytes=record.content_bytes,
        exported_content=record.exported_content,
        failure_code=record.failure_code,
        failure_detail=record.failure_detail,
        materialized_state_checks=msc,
    )


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    status: str
    target_file_id: uuid.UUID | str
    client_request_id: str | None = None
    finalization_id: uuid.UUID | None = None
    filename: str | None = None
    version: int | None = None
    current_hash: str | None = None
    snapshot_id: uuid.UUID | None = None
    closed_editing_cycle_id: uuid.UUID | None = None
    new_editing_cycle_id: uuid.UUID | None = None
    materialized_state_matches: bool | None = None
    materialized_state_checks: dict[str, Any] | None = None
    exported_content: str | None = None
    content_sha256: str | None = None
    content_bytes: int | None = None
    content_delivery: str = "inline"
    format: str | None = None
    source_line_endings: Any = None
    failure_reason: FailureReason | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    is_idempotent_replay: bool = False
    lock_wait_ms: float | None = None
    lock_hold_ms: float | None = None
    replay_ms: float | None = None


@timed("finalize_target")
def finalize_target(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    client_request_id: str,
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    format: str = "original_eol",
) -> FinalizeResult:
    """Atomically checkpoint, replay-verify, and export a canonical target in a single database transaction.

    Database Atomicity Guarantees:
    - Dedicated clean Session ownership: rejects any pre-existing transaction or dirty ORM state.
    - Validates target existence, mandatory client_request_id, and at least one guard.
    - Locks the target row under SELECT ... FOR UPDATE.
    - Keyed recovery: returns cached receipt on identical retry before running stale guard checks.
    - Checkpoints via save_target (creates snapshot and rotates editing cycle).
    - Verifies authoritative history via replay_target.
    - Exports target content in requested format and validates SHA-256 against export metadata.
    - If any phase fails, rolls back completely: 0 snapshots created, 0 editing cycles rotated.
    - Persists durable target_finalizations record and commits atomically.
    """
    # 0. Session cleanliness check (AD-1: reject pre-existing transaction or pending ORM modifications)
    if session.in_transaction() or session.dirty or session.new or session.deleted:
        raise ValueError("finalize_target requires an unattached clean Session without an active or dirty transaction.")

    # 1. Argument preflight checks
    if invalid_text_paths({"format": format, "expected_current_hash": expected_current_hash, "client_request_id": client_request_id}):
        return FinalizeResult(
            status="rejected",
            target_file_id=safe_input_text(target_file_id),
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="Finalization arguments must be valid UTF-8 without NUL bytes.",
        )

    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return FinalizeResult(
            status="rejected",
            target_file_id=str(target_file_id),
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="target_file_id is not a valid UUID.",
        )

    if not isinstance(client_request_id, str) or not _CLIENT_REQUEST_ID_RE.match(client_request_id):
        return FinalizeResult(
            status="rejected",
            target_file_id=target_uuid,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="client_request_id is required and must be 1-128 printable ASCII characters without whitespace.",
        )

    if expected_target_version is None and expected_current_hash is None:
        return FinalizeResult(
            status="rejected",
            target_file_id=target_uuid,
            client_request_id=client_request_id,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="At least one of expected_target_version or expected_current_hash must be provided.",
        )

    if format not in EXPORT_FORMATS:
        return FinalizeResult(
            status="rejected",
            target_file_id=target_uuid,
            client_request_id=client_request_id,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail=f"format must be one of {sorted(EXPORT_FORMATS)}; got {format!r}.",
        )

    if expected_target_version is not None and (
        isinstance(expected_target_version, bool)
        or not isinstance(expected_target_version, int)
        or not 0 <= expected_target_version <= 2**63 - 1
    ):
        return FinalizeResult(
            status="rejected",
            target_file_id=target_uuid,
            client_request_id=client_request_id,
            failure_reason=FailureReason.CONTEXT_INVALID,
            failure_detail="expected_target_version must be a non-negative integer.",
        )

    fp_version, fingerprint = compute_finalization_fingerprint(
        target_file_id=target_uuid,
        expected_target_version=expected_target_version,
        expected_current_hash=expected_current_hash,
        format=format,
    )

    t_lock_wait_ms: float | None = None
    t_lock_hold_ms: float | None = None
    pre_replay_res = None
    t_pre_replay_ms: float = 0.0

    # Two-phase replay optimization (PR23-IMPL-ARCH-001):
    # Pre-compute O(history) replay outside the FOR UPDATE row lock when operating on a live Session,
    # then verify freshness in O(1) under the lock (falling back to under-lock replay on concurrent mutation).
    if isinstance(session, Session) and save_target is _DEFAULT_SAVE_TARGET and replay_target is _DEFAULT_REPLAY_TARGET:
        pre_tx = session.begin()
        try:
            with session.no_autoflush:
                pre_existing = session.execute(
                    select(TargetFinalizations.finalization_id).where(
                        TargetFinalizations.target_file_id == target_uuid,
                        TargetFinalizations.client_request_id == client_request_id,
                    )
                ).scalar_one_or_none()
                if pre_existing is None:
                    pre_target = session.get(CloudTargetFiles, target_uuid)
                    if (
                        pre_target is not None
                        and (expected_target_version is None or pre_target.version == expected_target_version)
                        and (expected_current_hash is None or pre_target.current_hash == expected_current_hash)
                    ):
                        t0_pre = time.perf_counter()
                        pre_replay_res = replay_target(session, target_file_id=target_uuid, for_update=False)
                        t_pre_replay_ms = (time.perf_counter() - t0_pre) * 1000.0
        finally:
            pre_tx.rollback()

    tx = session.begin()
    try:
        # 2. Lock target row under SELECT ... FOR UPDATE
        # PR23-R3-DOC-002: measure lock acquisition wait time exclusively
        t0_wait = time.perf_counter()
        with session.no_autoflush:
            target = session.execute(select_target_for_update(target_uuid)).scalar_one_or_none()
        t_lock_wait_ms = (time.perf_counter() - t0_wait) * 1000.0

        # Start exclusive row lock-hold timer immediately after lock acquisition
        t0_hold = time.perf_counter()

        def _rollback() -> float:
            tx.rollback()
            return (time.perf_counter() - t0_hold) * 1000.0

        if target is None:
            t_lock_hold_ms = _rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                failure_reason=FailureReason.TARGET_NOT_FOUND,
                failure_detail="Target file was not found.",
                lock_wait_ms=t_lock_wait_ms,
                lock_hold_ms=t_lock_hold_ms,
            )

        target_version = target.version
        target_hash = target.current_hash
        target_filename = target.filename
        target_source_line_endings = target.source_line_endings

        # 3. Durable keyed recovery check (BEFORE stale guard checks)
        existing_finalization = session.execute(
            select(TargetFinalizations).where(
                TargetFinalizations.target_file_id == target_uuid,
                TargetFinalizations.client_request_id == client_request_id,
            )
        ).scalar_one_or_none()

        if existing_finalization is not None:
            # PR23-R3-SVC-002: Materialize all columns into a detached structure
            # BEFORE calling tx.rollback() to prevent SQLAlchemy 2.0 autobegin.
            cached = _materialize_finalization(existing_finalization)
            t_lock_hold_ms = _rollback()

            if cached.request_fingerprint == fingerprint:
                # Exact identical retry returns original cached receipt with persisted checks (PR23-R3-SVC-003)
                return FinalizeResult(
                    status="ok" if cached.status == "completed" else cached.status,
                    target_file_id=target_uuid,
                    client_request_id=client_request_id,
                    finalization_id=cached.finalization_id,
                    filename=cached.filename,
                    version=cached.saved_target_version,
                    current_hash=cached.canonical_current_hash,
                    snapshot_id=cached.snapshot_id,
                    closed_editing_cycle_id=cached.closed_editing_cycle_id,
                    new_editing_cycle_id=cached.new_editing_cycle_id,
                    materialized_state_matches=True if cached.status == "completed" else None,
                    materialized_state_checks=cached.materialized_state_checks,
                    exported_content=cached.exported_content,
                    content_sha256=cached.content_sha256,
                    content_bytes=cached.content_bytes,
                    content_delivery="inline" if cached.exported_content is not None else "deferred",
                    format=cached.export_format,
                    source_line_endings=cached.source_line_endings,
                    failure_code=cached.failure_code,
                    failure_detail=cached.failure_detail,
                    is_idempotent_replay=True,
                    lock_wait_ms=t_lock_wait_ms,
                    lock_hold_ms=t_lock_hold_ms,
                )
            else:
                # Key reused with differing parameters: conflict rejection
                return FinalizeResult(
                    status="rejected",
                    target_file_id=target_uuid,
                    client_request_id=client_request_id,
                    version=target_version,
                    current_hash=target_hash,
                    failure_reason=FailureReason.CONTEXT_INVALID,
                    failure_code="request_key_conflict",
                    failure_detail=f"client_request_id '{client_request_id}' has already been used with different finalization parameters.",
                    lock_wait_ms=t_lock_wait_ms,
                    lock_hold_ms=t_lock_hold_ms,
                )

        # 4. Check fresh guards before mutating state
        if expected_target_version is not None and target_version != expected_target_version:
            t_lock_hold_ms = _rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.TARGET_VERSION_MISMATCH,
                failure_detail="expected_target_version does not match the current target version.",
                lock_wait_ms=t_lock_wait_ms,
                lock_hold_ms=t_lock_hold_ms,
            )

        if expected_current_hash is not None and target_hash != expected_current_hash:
            t_lock_hold_ms = _rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.TARGET_HASH_MISMATCH,
                failure_detail="expected_current_hash does not match the current target hash.",
                lock_wait_ms=t_lock_wait_ms,
                lock_hold_ms=t_lock_hold_ms,
            )

        # 5. SAVE: checkpoint snapshot and rotate cycle using already-locked target (PR23-R4I-SVC-002)
        if save_target is _DEFAULT_SAVE_TARGET and isinstance(session, Session):
            save_res = save_target_locked(session, target=target)
        else:
            save_res = save_target(
                session,
                target_file_id=target_uuid,
                expected_target_version=expected_target_version,
                expected_current_hash=expected_current_hash,
            )
        if save_res.status != "saved":
            t_lock_hold_ms = _rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=save_res.failure_reason or FailureReason.CONTEXT_INVALID,
                failure_detail=save_res.failure_detail or "SAVE checkpoint failed during finalization.",
                lock_wait_ms=t_lock_wait_ms,
                lock_hold_ms=t_lock_hold_ms,
            )

        # 6. REPLAY: verify freshness of pre-lock replay in O(1) under lock, or run fallback replay (PR23-IMPL-ARCH-001)
        t0_replay = time.perf_counter()
        if (
            pre_replay_res is not None
            and pre_replay_res.current_version == target_version
            and pre_replay_res.current_hash == target_hash
            and (
                not pre_replay_res.materialized_state_matches
                or canonicalize_text(target.current_content) == pre_replay_res.reconstructed_content
            )
        ):
            replay_res = pre_replay_res
            t_replay_ms = t_pre_replay_ms + (time.perf_counter() - t0_replay) * 1000.0
        else:
            if replay_target is _DEFAULT_REPLAY_TARGET:
                replay_res = replay_target(session, target_file_id=target_uuid, for_update=False)
            else:
                replay_res = replay_target(session, target_file_id=target_uuid)
            t_replay_ms = (time.perf_counter() - t0_replay) * 1000.0

        if not replay_res.materialized_state_matches:
            # Replay failed: rollback transaction completely!
            t_lock_hold_ms = _rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                materialized_state_matches=replay_res.materialized_state_matches,
                materialized_state_checks=replay_res.materialized_state_checks,
                failure_reason=replay_res.failure_reason or FailureReason.REPLAY_HASH_MISMATCH,
                failure_detail=(
                    f"Replay verification failed during finalization: {replay_res.failure_detail or 'materialized state mismatch'}. "
                    "SAVE checkpoint and editing cycle rotation were rolled back atomically."
                ),
                lock_wait_ms=t_lock_wait_ms,
                lock_hold_ms=t_lock_hold_ms,
                replay_ms=t_replay_ms,
            )

        # 7. EXPORT: format target content
        export_res = export_target(session, target_file_id=target_uuid, format=format)
        if export_res.get("status") != "ok":
            t_lock_hold_ms = _rollback()
            return FinalizeResult(
                status=export_res.get("status", "rejected"),
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.CONTEXT_INVALID,
                failure_code=export_res.get("code"),
                failure_detail=f"Export failed during finalization: {export_res.get('failure_detail')}",
                source_line_endings=export_res.get("source_line_endings") or target_source_line_endings,
                lock_wait_ms=t_lock_wait_ms,
                lock_hold_ms=t_lock_hold_ms,
            )

        # 8. Content extraction and byte validation (fix PR23-IMPL-SVC-001)
        content = export_res.get("content")
        if not isinstance(content, str):
            t_lock_hold_ms = _rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.CONTEXT_INVALID,
                failure_detail="Export did not return valid string content.",
                lock_wait_ms=t_lock_wait_ms,
                lock_hold_ms=t_lock_hold_ms,
            )

        content_bytes = len(content.encode("utf-8"))
        content_sha256 = export_res.get("content_sha256")
        expected_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if content_sha256 != expected_sha256:
            t_lock_hold_ms = _rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.CONTEXT_INVALID,
                failure_detail="Exported content SHA-256 does not match computed bytes digest.",
                lock_wait_ms=t_lock_wait_ms,
                lock_hold_ms=t_lock_hold_ms,
            )

        # Determine delivery mode (inline vs deferred for large files > 1 MiB)
        inline_content = content if content_bytes <= MAX_INLINE_EXPORT_BYTES else None
        delivery_mode = "inline" if content_bytes <= MAX_INLINE_EXPORT_BYTES else "deferred"

        # 9. Persist durable finalization identity
        finalization_id = uuid.uuid4()
        record = TargetFinalizations(
            finalization_id=finalization_id,
            target_file_id=target_uuid,
            client_request_id=client_request_id,
            fingerprint_version=fp_version,
            request_fingerprint=fingerprint,
            status="completed",
            snapshot_id=save_res.snapshot_id,
            closed_editing_cycle_id=save_res.closed_editing_cycle_id,
            new_editing_cycle_id=save_res.new_editing_cycle_id,
            saved_target_version=target_version,
            canonical_current_hash=target_hash,
            filename=target_filename,
            export_format=export_res.get("format"),
            content_eol=export_res.get("content_eol"),
            source_line_endings=target_source_line_endings,
            content_sha256=content_sha256,
            content_bytes=content_bytes,
            exported_content=inline_content,
            materialized_state_checks=replay_res.materialized_state_checks,
        )
        session.add(record)
        tx.commit()
        t_lock_hold_ms = (time.perf_counter() - t0_hold) * 1000.0

    except Exception:
        tx.rollback()
        raise
    finally:
        if session.in_transaction():
            session.rollback()

    return FinalizeResult(
        status="ok",
        target_file_id=target_uuid,
        client_request_id=client_request_id,
        finalization_id=finalization_id,
        filename=target_filename,
        version=target_version,
        current_hash=target_hash,
        snapshot_id=save_res.snapshot_id,
        closed_editing_cycle_id=save_res.closed_editing_cycle_id,
        new_editing_cycle_id=save_res.new_editing_cycle_id,
        materialized_state_matches=replay_res.materialized_state_matches,
        materialized_state_checks=replay_res.materialized_state_checks,
        exported_content=inline_content,
        content_sha256=content_sha256,
        content_bytes=content_bytes,
        content_delivery=delivery_mode,
        format=export_res.get("format"),
        source_line_endings=target_source_line_endings,
        lock_wait_ms=t_lock_wait_ms,
        lock_hold_ms=t_lock_hold_ms,
        replay_ms=t_replay_ms,
    )
