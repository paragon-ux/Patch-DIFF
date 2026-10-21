import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.core.failures import FailureReason
from app.services.pdcp_service import submit_pdcp
from app.services.replay_service import replay_target
from app.services.save_service import save_target
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    CurrentPdcpFiles,
    TargetSnapshots,
)
from backend.tests.integration.helpers import create_target, pdcp_for


def test_replay_reconstructs_current_target_from_accepted_logs() -> None:
    target_id = create_target("alpha")
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("alpha", "beta")))
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("beta", "gamma")))
        result = replay_target(session, target_file_id=target_id)

    assert result.status == "success"
    assert result.reconstructed_content == "gamma"
    assert result.reconstructed_hash == result.current_hash
    assert result.accepted_transactions_replayed == 2


def test_replay_ignores_current_pdcp_manifest_ledger_and_save_snapshots_as_authoritative() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("old", "new")))
        save_target(session, target_file_id=target_id)
        current_pdcp = session.scalar(select(CurrentPdcpFiles).where(CurrentPdcpFiles.target_file_id == target_id))
        current_pdcp.pdcp_content = "corrupted display state"
        ledger = session.scalar(
            select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == target_id)
        )
        ledger.intent = "mutated non-authoritative ledger"
        save_snapshot = session.scalar(
            select(TargetSnapshots).where(
                TargetSnapshots.target_file_id == target_id,
                TargetSnapshots.snapshot_reason == "save_checkpoint",
            )
        )
        save_snapshot.content = "mutated save snapshot"
        result = replay_target(session, target_file_id=target_id)

    assert result.status == "success"
    assert result.reconstructed_content == "new"


def test_replay_protocol_failure_for_corrupted_accepted_pdcp_log() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("old", "new")))
        log = session.scalar(select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_id))
        log.pdcp_content = "not a pdcp"
        session.flush()
        result = replay_target(session, target_file_id=target_id)

    assert result.status == "failed"
    assert result.failure_reason is FailureReason.REPLAY_PROTOCOL_INVALID
    assert result.pdcp_log_id == log.pdcp_log_id


def test_replay_transaction_failure_for_corrupted_accepted_pdcp_applicability() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("old", "new")))
        log = session.scalar(select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_id))
        log.pdcp_content = pdcp_for(target_id, ("missing", "new"))
        session.flush()
        result = replay_target(session, target_file_id=target_id)

    assert result.status == "failed"
    assert result.failure_reason is FailureReason.REPLAY_TRANSACTION_INVALID
    assert result.pdcp_log_id == log.pdcp_log_id


def test_replay_hash_mismatch_for_corrupted_after_hash() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("old", "new")))
        log = session.scalar(select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_id))
        log.after_hash = "a" * 64
        session.flush()
        result = replay_target(session, target_file_id=target_id)

    assert result.status == "failed"
    assert result.failure_reason is FailureReason.REPLAY_HASH_MISMATCH
    assert result.pdcp_log_id == log.pdcp_log_id


def test_replay_does_not_depend_on_current_materialized_target() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("old", "new")))
        target = session.get(CloudTargetFiles, target_id)
        target.current_content = "materialized corruption"
        target.current_hash = "b" * 64
        session.flush()
        result = replay_target(session, target_file_id=target_id)

    assert result.status == "success"
    assert result.reconstructed_content == "new"
    assert result.current_hash == "b" * 64


def test_replay_coherent_cut_with_preloaded_target_after_concurrent_commit() -> None:
    target_id = create_target("v0_initial")
    session1 = SessionLocal()
    session2 = SessionLocal()
    try:
        # Session 1 pre-loads target at version 0
        t1 = session1.get(CloudTargetFiles, target_id)
        assert t1 is not None
        assert t1.version == 0

        # Session 2 commits edit (v0 -> v1)
        res2 = submit_pdcp(
            session2,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("v0_initial", "v1_committed")),
            expected_target_version=0,
        )
        assert res2.status == "accepted"
        assert res2.after_version == 1

        # Session 1 now calls replay_target
        # select_target_for_update with populate_existing=True refreshes t1 to version 1
        replay_res = replay_target(session1, target_file_id=target_id)
        assert replay_res.status == "success"
        assert replay_res.reconstructed_version == 1
        assert replay_res.current_version == 1
        assert replay_res.materialized_state_matches is True
        assert t1.version == 1
        assert t1.current_content == "v1_committed"
    finally:
        session1.close()
        session2.close()


def test_replay_target_lock_blocks_concurrent_writer() -> None:
    target_id = create_target("base")
    session1 = SessionLocal()
    session2 = SessionLocal()
    try:
        tx1 = session1.begin()
        tx1.__enter__()
        # Session 1 calls replay_target inside an active transaction, holding the target lock
        replay_res = replay_target(session1, target_file_id=target_id)
        assert replay_res.status == "success"
        assert session1.in_transaction()

        # Session 2 attempts to submit an edit while session1 holds the lock
        tx2 = session2.begin()
        tx2.__enter__()
        session2.execute(text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(OperationalError):
            submit_pdcp(
                session2,
                target_file_id=target_id,
                pdcp_content=pdcp_for(target_id, ("base", "writer_update")),
                expected_target_version=0,
            )
        tx2.__exit__(None, None, None)
        tx1.__exit__(None, None, None)
    finally:
        session1.close()
        session2.close()

