import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.services.pdcp_service import submit_pdcp
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    CurrentPdcpFiles,
    TargetSnapshots,
)
from app.storage.repositories import select_target_for_update


def pdcp_for(
    target_file_id: uuid.UUID,
    *changes: tuple[str, str],
    header_hash: str | None = None,
) -> str:
    header = f"PDCP 0.2.3\ntarget_file_id: {target_file_id}\ntarget_type: text/plain"
    if header_hash is not None:
        header += f"\ntarget_hash: {header_hash}"

    sections = [header]
    for index, (match, replace) in enumerate(changes, start=1):
        sections.append(
            f"""# MANIFEST
# change_id: chg_{index:03d}
# intent: Update text.
# input_state: Old text exists.
# output_state: New text exists.
# affected_region: example
# user_visible_change: Text changes.
# risk: low

<<<<<<< MATCH
{match}
=======
{replace}
>>>>>>> REPLACE"""
        )
    return "\n\n".join(sections)


def create_target(content: str = "old") -> uuid.UUID:
    with SessionLocal() as session:
        initialized = initialize_target(
            session,
            filename=f"{uuid.uuid4()}.txt",
            content=content,
            target_type="text/plain",
        )
        return initialized.target_file_id


def test_initialize_target_creates_target_snapshot_and_active_cycle() -> None:
    target_id = create_target("alpha\r\n")
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target is not None
        assert target.current_content == "alpha\n"
        assert target.version == 0
        assert target.current_hash == canonical_sha256("alpha\n")
        assert target.active_editing_cycle_id is not None
        snapshot_count = session.scalar(
            select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == target_id)
        )
        assert snapshot_count == 1


def test_accepted_pdcp_updates_target_log_and_manifest_ledger() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("old", "new")),
            expected_target_version=0,
        )

    assert result.status == "accepted"
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target.current_content == "new"
        assert target.version == 1
        assert target.latest_accepted_pdcp_log_id == result.pdcp_log_id
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log.status == "accepted"
        assert log.after_hash == canonical_sha256("new")
        ledger_count = session.scalar(
            select(func.count()).select_from(AppendOnlyManifestLedger).where(
                AppendOnlyManifestLedger.pdcp_log_id == result.pdcp_log_id
            )
        )
        assert ledger_count == 1


def test_rejected_pdcp_logs_rejection_and_does_not_mutate_target() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("missing", "new")),
            expected_target_version=0,
        )

    assert result.status == "rejected"
    assert result.failure_reason is FailureReason.MATCH_ABSENT
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target.current_content == "old"
        assert target.version == 0
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log.status == "rejected"
        assert log.after_hash is None
        assert log.diagnostic_json is not None
        ledger_count = session.scalar(
            select(func.count()).select_from(AppendOnlyManifestLedger).where(
                AppendOnlyManifestLedger.target_file_id == target_id
            )
        )
        assert ledger_count == 0


def test_failed_multi_change_transaction_does_not_partially_mutate() -> None:
    target_id = create_target("alpha beta")
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("alpha", "gamma"), ("alpha beta", "done")),
            expected_target_version=0,
        )

    assert result.status == "rejected"
    assert result.failure_reason is FailureReason.SEQUENTIAL_MATCH_INVALID
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target.current_content == "alpha beta"
        assert target.version == 0


def test_stale_expected_target_version_rejects() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("old", "new")),
            expected_target_version=99,
        )
    assert result.status == "rejected"
    assert result.failure_reason is FailureReason.TARGET_VERSION_MISMATCH


def test_stale_expected_current_hash_rejects() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("old", "new")),
            expected_current_hash="a" * 64,
        )
    assert result.status == "rejected"
    assert result.failure_reason is FailureReason.TARGET_HASH_MISMATCH


def test_pdcp_target_hash_mismatch_rejects() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("old", "new"), header_hash="b" * 64),
            expected_target_version=0,
        )
    assert result.status == "rejected"
    assert result.failure_reason is FailureReason.TARGET_HASH_MISMATCH


def test_current_pdcp_file_is_mutable_not_authoritative_history() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("old", "new")))
    with SessionLocal() as session:
        submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("new", "latest")))

    with SessionLocal() as session:
        current_count = session.scalar(
            select(func.count()).select_from(CurrentPdcpFiles).where(CurrentPdcpFiles.target_file_id == target_id)
        )
        log_count = session.scalar(
            select(func.count()).select_from(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_id)
        )
        current_pdcp = session.scalar(select(CurrentPdcpFiles).where(CurrentPdcpFiles.target_file_id == target_id))
        assert current_count == 1
        assert log_count == 2
        assert current_pdcp.status == "accepted"


def test_target_diverged_rejects_and_does_not_mutate_target() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        result = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("old", "new")),
            expected_target_version=0,
            _before_final_guard=lambda target: setattr(target, "version", target.version + 1),
        )
    assert result.status == "rejected"
    assert result.failure_reason is FailureReason.TARGET_DIVERGED
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target.current_content == "old"
        assert target.version == 0


def test_same_target_row_lock_blocks_concurrent_submit() -> None:
    target_id = create_target("old")
    session1 = SessionLocal()
    session2 = SessionLocal()
    try:
        tx1 = session1.begin()
        tx1.__enter__()
        session1.execute(select_target_for_update(target_id)).scalar_one()

        tx2 = session2.begin()
        tx2.__enter__()
        session2.execute(text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(OperationalError):
            submit_pdcp(
                session2,
                target_file_id=target_id,
                pdcp_content=pdcp_for(target_id, ("old", "new")),
                expected_target_version=0,
            )
        tx2.__exit__(None, None, None)
        tx1.__exit__(None, None, None)
    finally:
        session1.close()
        session2.close()


def test_different_targets_are_independent_under_row_lock() -> None:
    locked_target_id = create_target("locked")
    free_target_id = create_target("free")
    session1 = SessionLocal()
    session2 = SessionLocal()
    try:
        tx1 = session1.begin()
        tx1.__enter__()
        session1.execute(select_target_for_update(locked_target_id)).scalar_one()

        tx2 = session2.begin()
        tx2.__enter__()
        session2.execute(text("SET LOCAL lock_timeout = '250ms'"))
        result = submit_pdcp(
            session2,
            target_file_id=free_target_id,
            pdcp_content=pdcp_for(free_target_id, ("free", "updated")),
            expected_target_version=0,
        )
        assert result.status == "accepted"
        tx2.__exit__(None, None, None)
        tx1.__exit__(None, None, None)
    finally:
        session1.close()
        session2.close()
