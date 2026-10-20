import pytest
from sqlalchemy import func, select

from app.core.failures import FailureReason
from app.services.pdcp_service import submit_pdcp
from app.services.save_service import save_target
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    EditingCycles,
    TargetSnapshots,
)
from backend.tests.integration.helpers import create_target, pdcp_for


def test_save_creates_snapshot_closes_old_cycle_and_opens_one_active_cycle() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        target_before = session.get(CloudTargetFiles, target_id)
        old_cycle_id = target_before.active_editing_cycle_id
        expected_hash = target_before.current_hash

    with SessionLocal() as session:
        result = save_target(session, target_file_id=target_id, expected_current_hash=expected_hash)

    assert result.status == "saved"
    assert result.closed_editing_cycle_id == old_cycle_id
    assert result.new_editing_cycle_id is not None
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target.active_editing_cycle_id == result.new_editing_cycle_id
        old_cycle = session.get(EditingCycles, old_cycle_id)
        new_cycle = session.get(EditingCycles, result.new_editing_cycle_id)
        assert old_cycle.status == "closed"
        assert old_cycle.save_snapshot_id == result.snapshot_id
        assert new_cycle.status == "active"
        active_count = session.scalar(
            select(func.count()).select_from(EditingCycles).where(
                EditingCycles.target_file_id == target_id,
                EditingCycles.status == "active",
            )
        )
        assert active_count == 1


def test_save_does_not_mutate_target_content_hash_or_version() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        target_before = session.get(CloudTargetFiles, target_id)
        before = (target_before.current_content, target_before.current_hash, target_before.version)

    with SessionLocal() as session:
        save_target(session, target_file_id=target_id)

    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert (target.current_content, target.current_hash, target.version) == before


def test_save_preserves_logs_and_ledger_history_and_shifts_active_manifest_context() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("old", "new")))

    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        old_cycle_id = target.active_editing_cycle_id

    with SessionLocal() as session:
        save_target(session, target_file_id=target_id)

    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        log_count = session.scalar(
            select(func.count()).select_from(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_id)
        )
        all_ledger_count = session.scalar(
            select(func.count()).select_from(AppendOnlyManifestLedger).where(
                AppendOnlyManifestLedger.target_file_id == target_id
            )
        )
        active_ledger_count = session.scalar(
            select(func.count()).select_from(AppendOnlyManifestLedger).where(
                AppendOnlyManifestLedger.target_file_id == target_id,
                AppendOnlyManifestLedger.editing_cycle_id == target.active_editing_cycle_id,
            )
        )
        previous_ledger_count = session.scalar(
            select(func.count()).select_from(AppendOnlyManifestLedger).where(
                AppendOnlyManifestLedger.target_file_id == target_id,
                AppendOnlyManifestLedger.editing_cycle_id == old_cycle_id,
            )
        )
        assert log_count == 1
        assert all_ledger_count == 1
        assert active_ledger_count == 0
        assert previous_ledger_count == 1


def test_save_hash_mismatch_leaves_old_cycle_active() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        target_before = session.get(CloudTargetFiles, target_id)
        old_cycle_id = target_before.active_editing_cycle_id

    with SessionLocal() as session:
        result = save_target(session, target_file_id=target_id, expected_current_hash="a" * 64)

    assert result.status == "rejected"
    assert result.failure_reason is FailureReason.TARGET_HASH_MISMATCH
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        old_cycle = session.get(EditingCycles, old_cycle_id)
        snapshot_count = session.scalar(
            select(func.count()).select_from(TargetSnapshots).where(
                TargetSnapshots.target_file_id == target_id,
                TargetSnapshots.snapshot_reason == "save_checkpoint",
            )
        )
        assert target.active_editing_cycle_id == old_cycle_id
        assert old_cycle.status == "active"
        assert snapshot_count == 0


def test_save_failure_after_snapshot_rolls_back_partial_state() -> None:
    target_id = create_target("old")
    with pytest.raises(RuntimeError):
        with SessionLocal() as session:
            target_before = session.get(CloudTargetFiles, target_id)
            old_cycle_id = target_before.active_editing_cycle_id
            save_target(
                session,
                target_file_id=target_id,
                _after_snapshot=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            )

    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        active_count = session.scalar(
            select(func.count()).select_from(EditingCycles).where(
                EditingCycles.target_file_id == target_id,
                EditingCycles.status == "active",
            )
        )
        save_snapshot_count = session.scalar(
            select(func.count()).select_from(TargetSnapshots).where(
                TargetSnapshots.target_file_id == target_id,
                TargetSnapshots.snapshot_reason == "save_checkpoint",
            )
        )
        assert target.active_editing_cycle_id == old_cycle_id
        assert active_count == 1
        assert save_snapshot_count == 0


def test_save_rejects_pending_local_direct_modifications() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target is not None
        target.current_content = "unauthorized local mutation"
        result = save_target(session, target_file_id=target_id)
        assert result.status == "rejected"
        assert result.failure_reason is FailureReason.CONTEXT_INVALID
        assert result.failure_detail == "Pending local direct modifications on target are not permitted."

