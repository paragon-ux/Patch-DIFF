"""Unit tests for the atomic finalize_target service."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.failures import FailureReason
from app.services.finalize_service import FinalizeResult, finalize_target
from app.services.save_service import SaveResult
from app.services.replay_service import ReplayResult


def test_finalize_target_invalid_uuid():
    session = MagicMock()
    result = finalize_target(session, target_file_id="not-a-uuid")
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "target_file_id is not a valid UUID" in result.failure_detail


def test_finalize_target_invalid_format():
    session = MagicMock()
    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, format="invalid_format")
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "format must be one of" in result.failure_detail


def test_finalize_target_invalid_expected_version():
    session = MagicMock()
    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, expected_target_version=-1)
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "expected_target_version must be a non-negative integer" in result.failure_detail


def test_finalize_target_nul_character():
    session = MagicMock()
    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, expected_current_hash="abc\x00def")
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "valid UTF-8 without NUL bytes" in result.failure_detail


def test_finalize_target_not_found():
    session = MagicMock()
    session.in_transaction.return_value = False
    tx = MagicMock()
    session.begin.return_value = tx
    session.execute.return_value.scalar_one_or_none.return_value = None

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid)

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.TARGET_NOT_FOUND
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


def test_finalize_target_version_mismatch():
    session = MagicMock()
    session.in_transaction.return_value = False
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 3
    target.current_hash = "hash3"
    session.execute.return_value.scalar_one_or_none.return_value = target

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, expected_target_version=2)

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.TARGET_VERSION_MISMATCH
    assert result.version == 3
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


def test_finalize_target_hash_mismatch():
    session = MagicMock()
    session.in_transaction.return_value = False
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "actual_hash"
    session.execute.return_value.scalar_one_or_none.return_value = target

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, expected_current_hash="different_hash")

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.TARGET_HASH_MISMATCH
    assert result.current_hash == "actual_hash"
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


@patch("app.services.finalize_service.save_target")
def test_finalize_target_save_rejection_rolls_back(mock_save):
    session = MagicMock()
    session.in_transaction.return_value = False
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "hash2"
    session.execute.return_value.scalar_one_or_none.return_value = target

    tid = str(uuid.uuid4())
    mock_save.return_value = SaveResult(
        status="rejected",
        target_file_id=tid,
        snapshot_id=None,
        closed_editing_cycle_id=None,
        new_editing_cycle_id=None,
        current_hash="hash2",
        version=2,
        failure_reason=FailureReason.CONTEXT_INVALID,
        failure_detail="Direct pending modifications not permitted.",
    )

    result = finalize_target(session, target_file_id=tid)

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


@patch("app.services.finalize_service.save_target")
@patch("app.services.finalize_service.replay_target")
def test_finalize_target_replay_failure_rolls_back_save(mock_replay, mock_save):
    session = MagicMock()
    session.in_transaction.return_value = False
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "hash2"
    session.execute.return_value.scalar_one_or_none.return_value = target

    tid = str(uuid.uuid4())
    mock_save.return_value = SaveResult(
        status="saved",
        target_file_id=tid,
        snapshot_id=uuid.uuid4(),
        closed_editing_cycle_id=uuid.uuid4(),
        new_editing_cycle_id=uuid.uuid4(),
        current_hash="hash2",
        version=2,
    )

    # Replay detects divergence
    mock_replay.return_value = ReplayResult(
        status="rejected",
        target_file_id=tid,
        reconstructed_content=None,
        reconstructed_hash=None,
        current_hash="hash2",
        accepted_transactions_replayed=1,
        materialized_state_matches=False,
        failure_reason=FailureReason.REPLAY_HASH_MISMATCH,
        failure_detail="Materialized hash mismatch.",
    )

    result = finalize_target(session, target_file_id=tid)

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.REPLAY_HASH_MISMATCH
    assert "rolled back atomically" in result.failure_detail
    # Crucial assertion: tx.rollback MUST have been called, destroying the SAVE snapshot/cycle rotation
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


@patch("app.services.finalize_service.save_target")
@patch("app.services.finalize_service.replay_target")
@patch("app.services.finalize_service.export_target")
def test_finalize_target_success_commits(mock_export, mock_replay, mock_save):
    session = MagicMock()
    session.in_transaction.return_value = False
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "hash2"
    target.filename = "main.py"
    target.source_line_endings = "crlf"
    session.execute.return_value.scalar_one_or_none.return_value = target

    tid = str(uuid.uuid4())
    snap_id = uuid.uuid4()
    closed_id = uuid.uuid4()
    new_id = uuid.uuid4()

    mock_save.return_value = SaveResult(
        status="saved",
        target_file_id=tid,
        snapshot_id=snap_id,
        closed_editing_cycle_id=closed_id,
        new_editing_cycle_id=new_id,
        current_hash="hash2",
        version=2,
    )

    mock_replay.return_value = ReplayResult(
        status="success",
        target_file_id=tid,
        reconstructed_content="export_text\r\n",
        reconstructed_hash="hash2",
        current_hash="hash2",
        accepted_transactions_replayed=2,
        materialized_state_matches=True,
        materialized_state_checks={
            "content_matches": True,
            "stored_hash_matches": True,
            "recomputed_hash_matches": True,
            "version_matches": True,
        },
    )

    mock_export.return_value = {
        "status": "ok",
        "target_file_id": tid,
        "filename": "main.py",
        "exported_content": "export_text\r\n",
        "content_sha256": "export_sha256",
        "format": "original_eol",
    }

    result = finalize_target(
        session,
        target_file_id=tid,
        expected_target_version=2,
        expected_current_hash="hash2",
        format="original_eol",
    )

    assert result.status == "ok"
    assert result.filename == "main.py"
    assert result.version == 2
    assert result.current_hash == "hash2"
    assert result.snapshot_id == snap_id
    assert result.closed_editing_cycle_id == closed_id
    assert result.new_editing_cycle_id == new_id
    assert result.materialized_state_matches is True
    assert result.exported_content == "export_text\r\n"
    assert result.content_sha256 == "export_sha256"
    assert result.format == "original_eol"
    assert result.source_line_endings == "crlf"
    tx.commit.assert_called_once()
    tx.rollback.assert_not_called()
