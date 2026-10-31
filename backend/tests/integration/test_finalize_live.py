"""Live PostgreSQL integration tests for atomic finalization, idempotency, and session hygiene."""

import hashlib
import uuid
import pytest
from sqlalchemy import func, select

from app.core.failures import FailureReason
from app.services.finalize_service import finalize_target, compute_finalization_fingerprint
from app.services.pdcp_service import submit_edits
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal
from app.storage.models import CloudTargetFiles, EditingCycles, TargetFinalizations, TargetSnapshots


def test_finalize_target_live_success_atomic():
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="atomic_finalize.txt",
            content="Hello World\nSecond Line\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        version = init.version
        current_hash = init.current_hash
        active_cycle_id = init.active_editing_cycle_id

    # Baseline counts
    with SessionLocal() as session:
        snapshots_before = session.execute(
            select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == target_id)
        ).scalar()
        cycles_before = session.execute(
            select(func.count()).select_from(EditingCycles).where(EditingCycles.target_file_id == target_id)
        ).scalar()
        assert snapshots_before == 1
        assert cycles_before == 1

    # Execute finalize in a clean dedicated session
    client_request_id = f"fin-{uuid.uuid4()}"
    with SessionLocal() as session:
        result = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=version,
            expected_current_hash=current_hash,
            format="canonical_lf",
        )

    assert result.status == "ok"
    assert result.version == version
    assert result.current_hash == current_hash
    assert result.exported_content == "Hello World\nSecond Line\n"
    assert result.content_bytes == len("Hello World\nSecond Line\n".encode("utf-8"))
    assert result.content_sha256 == hashlib.sha256(b"Hello World\nSecond Line\n").hexdigest()
    assert result.snapshot_id is not None
    assert result.closed_editing_cycle_id == active_cycle_id
    assert result.new_editing_cycle_id is not None
    assert result.new_editing_cycle_id != active_cycle_id
    assert result.materialized_state_matches is True
    assert result.is_idempotent_replay is False
    assert result.lock_hold_ms is not None and result.lock_hold_ms > 0
    assert result.replay_ms is not None and result.replay_ms > 0

    # Verify database state after commit
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target.active_editing_cycle_id == result.new_editing_cycle_id

        snapshots_after = session.execute(
            select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == target_id)
        ).scalar()
        cycles_after = session.execute(
            select(func.count()).select_from(EditingCycles).where(EditingCycles.target_file_id == target_id)
        ).scalar()
        assert snapshots_after == 2
        assert cycles_after == 2

        # Verify durable finalization identity in target_finalizations
        fin_rec = session.execute(
            select(TargetFinalizations).where(
                TargetFinalizations.target_file_id == target_id,
                TargetFinalizations.client_request_id == client_request_id,
            )
        ).scalar_one_or_none()
        assert fin_rec is not None
        assert fin_rec.status == "completed"
        assert fin_rec.snapshot_id == result.snapshot_id
        assert fin_rec.closed_editing_cycle_id == result.closed_editing_cycle_id
        assert fin_rec.new_editing_cycle_id == result.new_editing_cycle_id
        assert fin_rec.saved_target_version == version
        assert fin_rec.content_sha256 == result.content_sha256
        assert fin_rec.exported_content == "Hello World\nSecond Line\n"


def test_finalize_target_live_replay_failure_rolls_back_completely():
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="replay_fail.txt",
            content="Alpha Bravo\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        active_cycle_id = init.active_editing_cycle_id

    # Corrupt target hash in DB to simulate replay divergence
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        target.current_hash = "0" * 64
        session.commit()

    # Attempt finalization with corrupt hash as guard (guards pass, but replay will diverge!)
    client_request_id = f"fin-diverge-{uuid.uuid4()}"
    with SessionLocal() as session:
        result = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_current_hash="0" * 64,
            format="canonical_lf",
        )

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.REPLAY_HASH_MISMATCH
    assert "SAVE checkpoint and editing cycle rotation were rolled back atomically" in result.failure_detail

    # Verify rollback: 0 snapshots created, exactly 1 cycle remains, active cycle unchanged!
    with SessionLocal() as session:
        snapshots_count = session.execute(
            select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == target_id)
        ).scalar()
        cycles_count = session.execute(
            select(func.count()).select_from(EditingCycles).where(EditingCycles.target_file_id == target_id)
        ).scalar()
        assert snapshots_count == 1
        assert cycles_count == 1

        target = session.get(CloudTargetFiles, target_id)
        assert target.active_editing_cycle_id == active_cycle_id

        # Verify no completed finalization row persisted
        fin_rec = session.execute(
            select(TargetFinalizations).where(
                TargetFinalizations.target_file_id == target_id,
                TargetFinalizations.client_request_id == client_request_id,
            )
        ).scalar_one_or_none()
        assert fin_rec is None


def test_finalize_target_live_export_eol_failure_rolls_back_and_propagates_code():
    # Target uploaded with mixed line endings
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="mixed_eol.txt",
            content="Line 1\r\nLine 2\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        active_cycle_id = init.active_editing_cycle_id

    # Request original_eol: unrecoverable for mixed uploads!
    client_request_id = f"fin-eol-{uuid.uuid4()}"
    with SessionLocal() as session:
        result = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=0,
            format="original_eol",
        )

    assert result.status == "invalid_argument"
    assert result.failure_code == "original_eol_unrecoverable"
    assert "mixed line-ending styles" in result.failure_detail

    # Verify rollback: 0 snapshots, 1 cycle, active cycle unchanged
    with SessionLocal() as session:
        snapshots_count = session.execute(
            select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == target_id)
        ).scalar()
        cycles_count = session.execute(
            select(func.count()).select_from(EditingCycles).where(EditingCycles.target_file_id == target_id)
        ).scalar()
        assert snapshots_count == 1
        assert cycles_count == 1

        target = session.get(CloudTargetFiles, target_id)
        assert target.active_editing_cycle_id == active_cycle_id


def test_finalize_target_live_caller_session_hygiene_enforced():
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="hygiene.txt",
            content="Clean test\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id

    # Session already in transaction: must be rejected!
    with SessionLocal() as session:
        session.begin()
        with pytest.raises(ValueError, match="clean Session"):
            finalize_target(
                session,
                target_file_id=target_id,
                client_request_id="req-dirty-1",
                expected_target_version=0,
            )

    # Session with dirty/uncommitted modifications: must be rejected!
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        target.filename = "modified_dirty.txt"
        assert session.is_modified(target)
        with pytest.raises(ValueError, match="clean Session"):
            finalize_target(
                session,
                target_file_id=target_id,
                client_request_id="req-dirty-2",
                expected_target_version=0,
            )


def test_finalize_target_live_missing_guards_rejected():
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="guards.txt",
            content="Guard test\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id

    with SessionLocal() as session:
        result = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id="req-no-guard",
            expected_target_version=None,
            expected_current_hash=None,
        )
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "At least one of expected_target_version or expected_current_hash must be provided" in result.failure_detail


def test_finalize_target_live_idempotency_recovery_and_conflict():
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="idempotent.txt",
            content="Initial Content\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        init_version = init.version
        init_hash = init.current_hash

    client_request_id = f"idem-key-{uuid.uuid4()}"

    # First attempt: succeeds and commits
    with SessionLocal() as session:
        res1 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=init_version,
            expected_current_hash=init_hash,
            format="canonical_lf",
        )
    assert res1.status == "ok"
    assert res1.is_idempotent_replay is False
    first_snapshot_id = res1.snapshot_id
    first_new_cycle = res1.new_editing_cycle_id
    first_content = res1.exported_content

    # Target advances: submit an edit on the new cycle (version becomes 1)
    with SessionLocal() as session:
        edit_res = submit_edits(
            session,
            target_file_id=target_id,
            expected_target_version=init_version,
            expected_current_hash=init_hash,
            intent="Advance version after finalization",
            edits=[{"match": "Initial", "replace": "Updated"}],
        )
        assert edit_res.status == "accepted"

    # Retry with identical original arguments and identical client_request_id:
    # Must succeed via keyed recovery despite target having advanced and version 0 being stale!
    with SessionLocal() as session:
        res2 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=init_version,
            expected_current_hash=init_hash,
            format="canonical_lf",
        )
    assert res2.status == "ok"
    assert res2.is_idempotent_replay is True
    assert res2.snapshot_id == first_snapshot_id
    assert res2.new_editing_cycle_id == first_new_cycle
    assert res2.exported_content == first_content
    assert res2.version == init_version

    # Ensure NO duplicate snapshots or cycles were created on retry
    with SessionLocal() as session:
        snapshots_count = session.execute(
            select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == target_id)
        ).scalar()
        cycles_count = session.execute(
            select(func.count()).select_from(EditingCycles).where(EditingCycles.target_file_id == target_id)
        ).scalar()
        assert snapshots_count == 2
        assert cycles_count == 2

    # Same client_request_id with DIFFERENT arguments: conflict!
    with SessionLocal() as session:
        res_conflict = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=init_version,
            expected_current_hash=init_hash,
            format="crlf",  # differing format!
        )
    assert res_conflict.status == "rejected"
    assert res_conflict.failure_code == "request_key_conflict"
    assert "has already been used with different finalization parameters" in res_conflict.failure_detail
