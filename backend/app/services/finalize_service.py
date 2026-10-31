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
from app.services.export_service import export_target
from app.services.performance_events import timed
from app.services.replay_service import replay_target
from app.services.save_service import save_target
from app.storage.models import CloudTargetFiles, TargetFinalizations
from app.storage.repositories import select_target_for_update

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
    materialized_state_checks: dict[str, bool] | None = None
    exported_content: str | None = None
    content_sha256: str | None = None
    content_bytes: int | None = None
    content_delivery: str = "inline"
    format: str | None = None
    source_line_endings: str | None = None
    failure_reason: FailureReason | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    is_idempotent_replay: bool = False
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

    t0_lock = time.perf_counter()
    tx = session.begin()
    try:
        # 2. Lock target row
        with session.no_autoflush:
            target = session.execute(select_target_for_update(target_uuid)).scalar_one_or_none()

        if target is None:
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                failure_reason=FailureReason.TARGET_NOT_FOUND,
                failure_detail="Target file was not found.",
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
            tx.rollback()
            if existing_finalization.request_fingerprint == fingerprint:
                # Exact identical retry returns original cached receipt
                return FinalizeResult(
                    status="ok" if existing_finalization.status == "completed" else existing_finalization.status,
                    target_file_id=target_uuid,
                    client_request_id=client_request_id,
                    finalization_id=existing_finalization.finalization_id,
                    filename=existing_finalization.filename,
                    version=existing_finalization.saved_target_version,
                    current_hash=existing_finalization.canonical_current_hash,
                    snapshot_id=existing_finalization.snapshot_id,
                    closed_editing_cycle_id=existing_finalization.closed_editing_cycle_id,
                    new_editing_cycle_id=existing_finalization.new_editing_cycle_id,
                    materialized_state_matches=True if existing_finalization.status == "completed" else None,
                    exported_content=existing_finalization.exported_content,
                    content_sha256=existing_finalization.content_sha256,
                    content_bytes=existing_finalization.content_bytes,
                    content_delivery="inline" if existing_finalization.exported_content is not None else "deferred",
                    format=existing_finalization.export_format,
                    source_line_endings=existing_finalization.source_line_endings,
                    failure_code=existing_finalization.failure_code,
                    failure_detail=existing_finalization.failure_detail,
                    is_idempotent_replay=True,
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
                )

        # 4. Check fresh guards before mutating state
        if expected_target_version is not None and target_version != expected_target_version:
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.TARGET_VERSION_MISMATCH,
                failure_detail="expected_target_version does not match the current target version.",
            )

        if expected_current_hash is not None and target_hash != expected_current_hash:
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.TARGET_HASH_MISMATCH,
                failure_detail="expected_current_hash does not match the current target hash.",
            )

        # 5. SAVE: checkpoint snapshot and rotate cycle
        save_res = save_target(
            session,
            target_file_id=target_uuid,
            expected_target_version=expected_target_version,
            expected_current_hash=expected_current_hash,
        )
        if save_res.status != "saved":
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=save_res.failure_reason or FailureReason.CONTEXT_INVALID,
                failure_detail=save_res.failure_detail or "SAVE checkpoint failed during finalization.",
            )

        # 6. REPLAY: verify full history in memory under lock
        t0_replay = time.perf_counter()
        replay_res = replay_target(session, target_file_id=target_uuid)
        t_replay_ms = (time.perf_counter() - t0_replay) * 1000.0

        if not replay_res.materialized_state_matches:
            # Replay failed: rollback transaction completely!
            tx.rollback()
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
                replay_ms=t_replay_ms,
            )

        # 7. EXPORT: format target content
        export_res = export_target(session, target_file_id=target_uuid, format=format)
        if export_res.get("status") != "ok":
            tx.rollback()
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
            )

        # 8. Content extraction and byte validation (fix PR23-IMPL-SVC-001)
        content = export_res.get("content")
        if not isinstance(content, str):
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.CONTEXT_INVALID,
                failure_detail="Export did not return valid string content.",
            )

        content_bytes = len(content.encode("utf-8"))
        content_sha256 = export_res.get("content_sha256")
        expected_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if content_sha256 != expected_sha256:
            tx.rollback()
            return FinalizeResult(
                status="rejected",
                target_file_id=target_uuid,
                client_request_id=client_request_id,
                version=target_version,
                current_hash=target_hash,
                failure_reason=FailureReason.CONTEXT_INVALID,
                failure_detail="Exported content SHA-256 does not match computed bytes digest.",
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
        )
        session.add(record)
        tx.commit()

    except Exception:
        tx.rollback()
        raise

    t_lock_hold_ms = (time.perf_counter() - t0_lock) * 1000.0

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
        lock_hold_ms=t_lock_hold_ms,
        replay_ms=t_replay_ms,
    )
