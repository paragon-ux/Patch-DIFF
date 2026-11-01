"""Live PostgreSQL integration tests for atomic finalization, idempotency, and session hygiene."""

import base64
import hashlib
import uuid
import pytest
from sqlalchemy import func, select

from app.core.failures import FailureReason
from app.services.export_service import read_finalized_export
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
    assert result.materialized_state_checks is not None
    assert result.materialized_state_checks["content_matches"] is True
    assert result.materialized_state_checks["stored_hash_matches"] is True
    assert result.materialized_state_checks["recomputed_hash_matches"] is True
    assert result.materialized_state_checks["version_matches"] is True
    assert result.is_idempotent_replay is False
    assert result.lock_wait_ms is not None and result.lock_wait_ms >= 0
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
        assert fin_rec.materialized_state_checks == result.materialized_state_checks


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
    assert res1.lock_wait_ms is not None and res1.lock_wait_ms >= 0
    assert res1.materialized_state_checks is not None
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
    assert res2.materialized_state_checks == res1.materialized_state_checks
    assert res2.lock_wait_ms is not None and res2.lock_wait_ms >= 0
    assert res2.lock_hold_ms is not None and res2.lock_hold_ms >= 0

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


def test_finalize_target_live_session_hygiene_across_repeated_retries():
    """Verify PR23-R3-SVC-002: session.in_transaction() remains False across retries and conflicts."""
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="hygiene_multi.txt",
            content="Hygiene Verification\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        version = init.version
        current_hash = init.current_hash

    client_request_id = f"fin-hygiene-{uuid.uuid4()}"

    # Use a SINGLE session across initial finalize, idempotent retry, and conflict
    with SessionLocal() as session:
        # 1. Initial finalize
        res1 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=version,
            expected_current_hash=current_hash,
            format="canonical_lf",
        )
        assert res1.status == "ok"
        assert res1.lock_wait_ms is not None and res1.lock_wait_ms >= 0
        assert res1.lock_hold_ms is not None and res1.lock_hold_ms >= 0
        assert session.in_transaction() is False

        # 2. Idempotent retry on the same session
        res2 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=version,
            expected_current_hash=current_hash,
            format="canonical_lf",
        )
        assert res2.status == "ok"
        assert res2.is_idempotent_replay is True
        assert res2.lock_wait_ms is not None and res2.lock_wait_ms >= 0
        assert res2.lock_hold_ms is not None and res2.lock_hold_ms >= 0
        assert session.in_transaction() is False

        # 3. Third call (conflict) on the same session
        res3 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=version,
            expected_current_hash=current_hash,
            format="crlf",
        )
        assert res3.status == "rejected"
        assert res3.failure_code == "request_key_conflict"
        assert session.in_transaction() is False


def test_finalize_target_live_idempotent_materialized_state_checks_parity():
    """Verify PR23-R3-SVC-003: idempotent recovery returns original immutable checks field-for-field."""
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="checks_parity.txt",
            content="Line 1\nLine 2\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        init_version = init.version
        init_hash = init.current_hash

    client_request_id = f"fin-parity-{uuid.uuid4()}"

    # First attempt: finalizes and persists replay checks
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
    assert res1.materialized_state_checks is not None
    assert res1.materialized_state_checks["content_matches"] is True
    assert res1.materialized_state_checks["stored_hash_matches"] is True
    assert res1.materialized_state_checks["recomputed_hash_matches"] is True
    assert res1.materialized_state_checks["version_matches"] is True

    # Advance target version by editing
    with SessionLocal() as session:
        edit_res = submit_edits(
            session,
            target_file_id=target_id,
            expected_target_version=init_version,
            expected_current_hash=init_hash,
            intent="Advance version after finalization",
            edits=[{"match": "Line 1", "replace": "Line One"}],
        )
        assert edit_res.status == "accepted"

    # Idempotent retry with original arguments
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

    # Immutable verification proof preserved exactly
    assert res2.materialized_state_checks is not None
    assert res2.materialized_state_checks == res1.materialized_state_checks
    assert res2.materialized_state_matches is True

    # Complete field-for-field parity excluding documented request-local fields
    assert res2.finalization_id == res1.finalization_id
    assert res2.target_file_id == res1.target_file_id
    assert res2.version == res1.version
    assert res2.current_hash == res1.current_hash
    assert res2.snapshot_id == res1.snapshot_id
    assert res2.closed_editing_cycle_id == res1.closed_editing_cycle_id
    assert res2.new_editing_cycle_id == res1.new_editing_cycle_id
    assert res2.exported_content == res1.exported_content
    assert res2.content_sha256 == res1.content_sha256
    assert res2.content_bytes == res1.content_bytes
    assert res2.format == res1.format


def test_read_finalized_export_large_multibyte_paging_post_edit():
    """Verify PR23-R3-SVC-001: immutable retrieval of >1MiB export across subsequent edits with chunk pagination."""
    # 1. Initialize large >1MiB target with multibyte UTF-8 and CRLF line endings
    base_text = "Line with UTF-8 chars: €, ✓, 世界\r\n"
    target_content = base_text * 35000  # ~1.2 MiB
    assert len(target_content.encode("utf-8")) > 1_048_576

    with SessionLocal() as session:
        init = initialize_target(session, filename="large_doc.txt", content=target_content, target_type="text/plain")
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash

    # 2. Finalize target with format original_eol
    with SessionLocal() as session:
        fin_res = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-{uuid.uuid4()}",
            expected_target_version=v0,
            expected_current_hash=h0,
            format="original_eol",
        )
    assert fin_res.status == "ok"
    assert fin_res.content_delivery == "deferred"
    assert fin_res.exported_content is None
    assert fin_res.finalization_id is not None
    original_sha256 = fin_res.content_sha256
    original_bytes = fin_res.content_bytes

    # 3. Mutate target state by applying edits on the new cycle
    with SessionLocal() as session:
        edit_res = submit_edits(
            session,
            target_file_id=target_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            intent="Mutate document after finalization",
            edits=[{"match": "Line with UTF-8 chars: €", "replace": "MODIFIED_HEADER", "occurrence_index": 1}],
        )
        assert edit_res.status == "accepted"

    # 4. Page through read_finalized_export and reassemble
    chunks = []
    offset = 0
    has_more = True
    page_size = 262144

    with SessionLocal() as session:
        while has_more:
            page = read_finalized_export(
                session,
                finalization_id=fin_res.finalization_id,
                target_file_id=target_id,
                offset=offset,
                limit=page_size,
            )
            assert page["status"] == "ok"
            assert page["finalization_id"] == str(fin_res.finalization_id)
            assert page["target_file_id"] == str(target_id)
            assert page["total_bytes"] == original_bytes
            assert page["content_sha256"] == original_sha256

            chunk_data = base64.b64decode(page["content_base64"])
            assert len(chunk_data) == page["bytes_read"]
            chunks.append(chunk_data)

            has_more = page["has_more"]
            offset = page["next_offset"]

    # 5. Verify byte fidelity against original finalized state (NOT current target state)
    reassembled = b"".join(chunks)
    assert len(reassembled) == original_bytes
    assert hashlib.sha256(reassembled).hexdigest() == original_sha256
    assert b"MODIFIED_HEADER" not in reassembled  # Proves historical immutability!

    # 6. Negative paths
    with SessionLocal() as session:
        # Wrong target ID
        wrong_tid = uuid.uuid4()
        res_wrong = read_finalized_export(session, finalization_id=fin_res.finalization_id, target_file_id=wrong_tid)
        assert res_wrong["status"] == "not_found"
        assert res_wrong["error"] == "finalization_not_found"

        # Out-of-bounds offset
        res_oob = read_finalized_export(session, finalization_id=fin_res.finalization_id, target_file_id=target_id, offset=original_bytes + 10)
        assert res_oob["status"] == "invalid_argument"
        assert res_oob["code"] == "invalid_range"

        # Exact end offset returns 0 bytes and has_more=False
        res_end = read_finalized_export(session, finalization_id=fin_res.finalization_id, target_file_id=target_id, offset=original_bytes)
        assert res_end["status"] == "ok"
        assert res_end["bytes_read"] == 0
        assert res_end["has_more"] is False
        assert res_end["next_offset"] is None
