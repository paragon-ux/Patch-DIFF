from sqlalchemy import select

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
        result = replay_target(session, target_file_id=target_id)

    assert result.status == "success"
    assert result.reconstructed_content == "new"
    assert result.current_hash == "b" * 64
