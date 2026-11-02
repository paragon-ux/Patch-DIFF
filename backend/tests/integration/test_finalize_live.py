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


from contextlib import contextmanager


@contextmanager
def _replay_query_phases():
    from sqlalchemy import event
    from app.storage.db import get_engine
    phases = []
    locked = False
    def trace(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal locked
        if "cloud_target_files" in statement and "FOR UPDATE" in statement:
            locked = True
            phases.append("row_lock")
        if "append_only_pdcp_logs.pdcp_content" in statement:
            phases.append("locked_replay" if locked else "pre_replay")
    engine = get_engine()
    event.listen(engine, "before_cursor_execute", trace)
    try:
        yield phases
    finally:
        event.remove(engine, "before_cursor_execute", trace)


@pytest.mark.parametrize("corrupt_log_hash", [False, True])
def test_stage_c_live_history_revision_race_and_raw_content_check(corrupt_log_hash):
    """Verify Stage C (PR23-IMPL-ARCH-001, PR23-R5-DB-001): pre-lock REPEATABLE READ READ ONLY replay + history_revision & raw content check under lock."""
    import threading
    from sqlalchemy import text as sa_text
    import app.services.finalize_service as fin_mod
    from app.storage.db import create_bootstrap_engine
    from app.storage.models import AppendOnlyPdcpLogs
    from app.pdcp.typed import build_record, canonical_record_json

    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="stage_c_race.txt",
            content="Alpha\nBeta\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash
        cycle_id = init.active_editing_cycle_id

    # 1. Deterministic barrier: between pre-lock replay and SELECT ... FOR UPDATE,
    # a concurrent transaction inserts an accepted log row (which triggers DB history_revision + 1)
    # without changing version or current_hash. Under lock, finalize_target must detect the
    # history_revision mismatch and fall back to under-lock replay (which detects the extra accepted log!).
    hook_fired = []
    revisions = []

    def _race_hook(*_args):
        hook_fired.append(target_id)
        record = canonical_record_json(build_record(
            target_file_id=str(target_id), intent="race",
            edits=[{"match": "Alpha", "replace": "Gamma"}],
            expected_target_version=v0, expected_current_hash=h0,
        ))
        with SessionLocal() as race_session:
            with race_session.begin():
                race_session.add(
                    AppendOnlyPdcpLogs(
                        pdcp_log_id=uuid.uuid4(),
                        target_file_id=target_id,
                        editing_cycle_id=cycle_id,
                        submission_source="race_test",
                        pdcp_content=record,
                        pdcp_content_hash=hashlib.sha256(b"race" if corrupt_log_hash else record.encode()).hexdigest(),
                        protocol_version="patchdiff-tx/1",
                        runtime_version="patchdiff-mvp-0.2.2",
                        status="accepted",
                        change_count=1,
                        before_hash=h0,
                        after_hash=hashlib.sha256(b"Gamma\nBeta\n").hexdigest(),
                        before_version=0,
                        after_version=1,
                    )
                )

                race_session.flush()
                revisions.append(race_session.get(CloudTargetFiles, target_id).history_revision)

    orig_hook = fin_mod._AFTER_PRE_REPLAY_HOOK
    fin_mod._AFTER_PRE_REPLAY_HOOK = _race_hook
    try:
        with _replay_query_phases() as phases, SessionLocal() as session:
            res_race = finalize_target(
                session,
                target_file_id=target_id,
                client_request_id=f"fin-race-{uuid.uuid4()}",
                expected_target_version=v0,
                expected_current_hash=h0,
                format="canonical_lf",
            )
    finally:
        fin_mod._AFTER_PRE_REPLAY_HOOK = orig_hook

    assert len(hook_fired) == 1
    assert revisions == [1]
    assert phases.count("row_lock") == 1
    assert "pre_replay" in phases and "locked_replay" in phases, phases
    with SessionLocal() as session:
        assert session.get(CloudTargetFiles, target_id).history_revision == 1
        assert session.scalar(select(func.count()).select_from(TargetSnapshots).where(
            TargetSnapshots.target_file_id == target_id)) == 1
        assert session.scalar(select(func.count()).select_from(TargetFinalizations).where(
            TargetFinalizations.target_file_id == target_id)) == 0
    assert res_race.status == "rejected"
    assert res_race.failure_reason == FailureReason.REPLAY_HASH_MISMATCH

    # 2. Under-lock raw content check: if current_content is corrupted while (version, current_hash, history_revision) match
    with SessionLocal() as session:
        init2 = initialize_target(
            session,
            filename="stage_c_raw_corrupt.txt",
            content="Clean line\n",
            target_type="text/plain",
        )
        tid2 = init2.target_file_id
        v2 = init2.version
        h2 = init2.current_hash

    def _corrupt_raw_content_hook(*_args):
        boot_engine = create_bootstrap_engine()
        try:
            with boot_engine.begin() as conn:
                conn.execute(
                    sa_text("UPDATE cloud_target_files SET current_content = 'Corrupted line\n' WHERE target_file_id = :tid"),
                    {"tid": tid2},
                )
        finally:
            boot_engine.dispose()

    fin_mod._AFTER_PRE_REPLAY_HOOK = _corrupt_raw_content_hook
    try:
        with SessionLocal() as session:
            res_corrupt = finalize_target(
                session,
                target_file_id=tid2,
                client_request_id=f"fin-raw-{uuid.uuid4()}",
                expected_target_version=v2,
                expected_current_hash=h2,
                format="canonical_lf",
            )
    finally:
        fin_mod._AFTER_PRE_REPLAY_HOOK = orig_hook

    assert res_corrupt.status == "rejected"
    assert res_corrupt.failure_reason == FailureReason.REPLAY_HASH_MISMATCH


def test_stage_c_legal_observation_link_retries_failed_pre_replay(monkeypatch):
    """A legal link changes history identity without changing target version/hash."""
    import app.services.finalize_service as module
    from app.mcp import tools  # noqa: F401
    from app.mcp.server import registry
    from app.pdcp.typed import build_record, canonical_record_json
    from app.storage.models import AppendOnlyPdcpLogs, TargetScopeObservations

    before = "def work():\n    return 1\n"
    after = before.replace("return 1", "return 2")
    with SessionLocal() as session:
        initial = initialize_target(session, filename="link_race.py", content=before,
                                    target_type="text/x-python")
    observation = registry.call("patchdiff_observe_scope", target_file_id=str(initial.target_file_id),
                                symbol_name="work")
    assert observation["status"] == "observed"
    log_id = uuid.uuid4()
    record = canonical_record_json(build_record(
        target_file_id=str(initial.target_file_id), intent="Link race",
        edits=[{"match": "return 1", "replace": "return 2"}],
        expected_target_version=0, expected_current_hash=initial.current_hash))
    after_hash = hashlib.sha256(after.encode()).hexdigest()
    with SessionLocal.begin() as session:
        session.add(AppendOnlyPdcpLogs(
            pdcp_log_id=log_id, target_file_id=initial.target_file_id,
            editing_cycle_id=initial.active_editing_cycle_id, submission_source="race_test",
            pdcp_content=record, pdcp_content_hash=hashlib.sha256(record.encode()).hexdigest(),
            protocol_version="patchdiff-tx/1", runtime_version="patchdiff-mvp-0.2.2",
            status="accepted", change_count=1, before_hash=initial.current_hash,
            after_hash=after_hash, before_version=0, after_version=1,
            diagnostic_json={key: observation[key] for key in (
                "observation_id", "scope_start", "scope_end", "observed_scope_hash")}))
        session.flush()
        target = session.get(CloudTargetFiles, initial.target_file_id)
        target.current_content, target.current_hash, target.version = after, after_hash, 1
        target.latest_accepted_pdcp_log_id = log_id
    revisions = []
    def link_after_pre_replay():
        with SessionLocal.begin() as session:
            target = session.get(CloudTargetFiles, initial.target_file_id)
            revisions.append(target.history_revision)
            obs = session.get(TargetScopeObservations, uuid.UUID(observation["observation_id"]))
            obs.accepted_pdcp_log_id = log_id
            session.flush()
            session.refresh(target)
            revisions.append(target.history_revision)
            assert (target.version, target.current_hash, target.current_content) == (1, after_hash, after)
    monkeypatch.setattr(module, "_AFTER_PRE_REPLAY_HOOK", link_after_pre_replay)
    with _replay_query_phases() as phases, SessionLocal() as session:
        final = finalize_target(session, target_file_id=initial.target_file_id,
                                client_request_id=str(uuid.uuid4()), expected_target_version=1,
                                expected_current_hash=after_hash, format="canonical_lf")
    assert revisions == [1, 2]
    assert phases.count("row_lock") == 1
    assert "pre_replay" in phases and "locked_replay" in phases, phases
    assert final.status == "ok" and final.materialized_state_matches is True
    assert all(final.materialized_state_checks.values())
    assert final.exported_content == after
    with SessionLocal() as session:
        assert session.get(CloudTargetFiles, initial.target_file_id).history_revision == 2
        assert session.scalar(select(func.count()).select_from(TargetSnapshots).where(
            TargetSnapshots.target_file_id == initial.target_file_id)) == 2
        assert session.scalar(select(func.count()).select_from(TargetFinalizations).where(
            TargetFinalizations.target_file_id == initial.target_file_id)) == 1


def test_stage_f_live_chunked_export_boundaries_and_concurrent_historical_backfill():
    """Verify Stage F (PR23-R4I-SVC-001): 256-KiB export chunks, boundary sizes, concurrent backfill, and 10-MiB bounded paging."""
    import threading
    from sqlalchemy import text as sa_text
    import app.services.export_service as exp_mod
    from app.storage.db import create_bootstrap_engine
    from app.storage.models import TargetFinalizationExportChunks

    # 1. Confirm unbounded _VERIFIED_EXPORT_CACHE is completely removed
    assert not hasattr(exp_mod, "_VERIFIED_EXPORT_CACHE")
    assert exp_mod.DEFAULT_EXPORT_CHUNK_BYTES == 262_144
    assert exp_mod.MAX_EXPORT_CHUNK_BYTES == 1_048_576

    # 2. Boundary sizes: 0 bytes, 262,144 bytes (1 chunk), 262,145 bytes (2 chunks)
    for size, expected_chunks in ((0, 0), (262_144, 1), (262_145, 2)):
        content = ("A" * (size - 1) + "\n") if size > 0 else ""
        with SessionLocal() as session:
            init = initialize_target(session, filename=f"boundary_{size}.txt", content=content, target_type="text/plain")
            fin = finalize_target(
                session,
                target_file_id=init.target_file_id,
                client_request_id=f"fin-b-{size}-{uuid.uuid4()}",
                expected_target_version=init.version,
                expected_current_hash=init.current_hash,
                format="canonical_lf",
            )
            assert fin.status == "ok"
            chunk_count = session.execute(
                select(func.count())
                .select_from(TargetFinalizationExportChunks)
                .where(TargetFinalizationExportChunks.finalization_id == fin.finalization_id)
            ).scalar()
            assert chunk_count == expected_chunks

            # Read with non-aligned offset/limit if size > 100
            if size == 0:
                page = read_finalized_export(session, fin.finalization_id, init.target_file_id, offset=0, limit=1024)
                assert page["status"] == "ok" and page["bytes_read"] == 0 and page["has_more"] is False
            elif size == 262_145:
                # Span across chunk 0 and chunk 1 boundary
                page = read_finalized_export(session, fin.finalization_id, init.target_file_id, offset=262_140, limit=5)
                assert page["status"] == "ok"
                assert page["bytes_read"] == 5
                assert base64.b64decode(page["content_base64"]) == b"AAAA\n"
                assert page["has_more"] is False

                # Concurrent historical backfill test: clear chunk rows via bootstrap with trigger disabled,
                # then run two threads calling read_finalized_export concurrently!
                fid = fin.finalization_id
                tid = init.target_file_id

    boot_engine = create_bootstrap_engine()
    try:
        with boot_engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE target_finalization_export_chunks DISABLE TRIGGER USER"))
            conn.execute(
                sa_text("DELETE FROM target_finalization_export_chunks WHERE finalization_id = :fid"),
                {"fid": fid},
            )
            conn.execute(sa_text("ALTER TABLE target_finalization_export_chunks ENABLE TRIGGER USER"))
    finally:
        boot_engine.dispose()

    barrier = threading.Barrier(2)
    results = [None, None]

    def _concurrent_reader(idx: int):
        with SessionLocal() as s:
            barrier.wait(timeout=5.0)
            results[idx] = read_finalized_export(s, fid, tid, offset=0, limit=300_000)

    t1 = threading.Thread(target=_concurrent_reader, args=(0,))
    t2 = threading.Thread(target=_concurrent_reader, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert results[0] is not None and results[0]["status"] == "ok"
    assert results[1] is not None and results[1]["status"] == "ok"
    assert results[0]["bytes_read"] == 262_145
    assert results[1]["bytes_read"] == 262_145
    with SessionLocal() as persisted:
        assert persisted.scalar(select(func.count()).select_from(TargetFinalizationExportChunks).where(
            TargetFinalizationExportChunks.finalization_id == fid)) == 2

    # 3. 10-MiB chunked export pagination test verifying <= 5 chunks read per 1-MiB page
    line_1k = ("0123456789abcdef" * 63) + "0123456789abcde\n"  # 1024 bytes
    ten_mib_text = line_1k * (10 * 1024)  # 10 MiB = 10,485,760 bytes (40 chunks of 256 KiB)
    with SessionLocal() as session:
        init10 = initialize_target(session, filename="ten_mib.txt", content=ten_mib_text, target_type="text/plain")
        fin10 = finalize_target(
            session,
            target_file_id=init10.target_file_id,
            client_request_id=f"fin-10m-{uuid.uuid4()}",
            expected_target_version=init10.version,
            expected_current_hash=init10.current_hash,
            format="canonical_lf",
        )
        assert fin10.status == "ok"
        assert fin10.content_delivery == "deferred"
        assert fin10.content_bytes == 10 * 1024 * 1024

        total_chunks_10m = session.execute(
            select(func.count())
            .select_from(TargetFinalizationExportChunks)
            .where(TargetFinalizationExportChunks.finalization_id == fin10.finalization_id)
        ).scalar()
        assert total_chunks_10m == 40

        # Non-aligned 1-MiB page starting at offset 100 (spans chunks 0..4 = 5 chunks)
        p_unaligned = read_finalized_export(
            session,
            fin10.finalization_id,
            init10.target_file_id,
            offset=100,
            limit=1_048_576,
        )
        assert p_unaligned["status"] == "ok"
        assert p_unaligned["bytes_read"] == 1_048_576
        assert p_unaligned["has_more"] is True
        assert p_unaligned["next_offset"] == 1_048_676


def test_chunk_insert_failure_rolls_back_snapshot_cycle_receipt_and_chunks():
    from sqlalchemy import event
    from app.storage.db import get_engine
    from app.storage.models import TargetFinalizationExportChunks
    with SessionLocal() as session:
        initial = initialize_target(session, filename="chunk_failure.txt", content="pinned bytes",
                                    target_type="text/plain")
    engine = get_engine()
    def fail_chunk(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO target_finalization_export_chunks"):
            raise RuntimeError("injected chunk insert failure")
    event.listen(engine, "before_cursor_execute", fail_chunk)
    try:
        with SessionLocal() as session, pytest.raises(RuntimeError, match="injected chunk insert"):
            finalize_target(session, target_file_id=initial.target_file_id,
                            client_request_id=str(uuid.uuid4()), expected_target_version=0,
                            format="canonical_lf")
        assert not session.in_transaction()
    finally:
        event.remove(engine, "before_cursor_execute", fail_chunk)
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, initial.target_file_id)
        assert target.active_editing_cycle_id == initial.active_editing_cycle_id
        for model, expected in ((TargetSnapshots, 1), (EditingCycles, 1), (TargetFinalizations, 0)):
            assert session.scalar(select(func.count()).select_from(model).where(
                model.target_file_id == initial.target_file_id)) == expected
        assert session.scalar(select(func.count()).select_from(TargetFinalizationExportChunks).join(
            TargetFinalizations).where(TargetFinalizations.target_file_id == initial.target_file_id)) == 0
