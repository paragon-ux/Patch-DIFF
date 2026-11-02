"""Unit tests for the atomic finalize_target service."""

import hashlib
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.failures import FailureReason
from app.services.finalize_service import FinalizeResult, finalize_target
from app.services.save_service import SaveResult
from app.services.replay_service import ReplayResult


def test_finalize_target_invalid_uuid():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()

    result = finalize_target(session, target_file_id="not-a-uuid", client_request_id="req-1", expected_target_version=1)
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "target_file_id is not a valid UUID" in result.failure_detail


def test_finalize_target_missing_client_request_id():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, client_request_id="", expected_target_version=1)
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "client_request_id is required" in result.failure_detail


def test_finalize_target_missing_both_guards():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=None, expected_current_hash=None)
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "At least one of expected_target_version or expected_current_hash must be provided" in result.failure_detail


def test_finalize_target_dirty_session_rejected():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = {"some_dirty_object"}
    session.new = set()
    session.deleted = set()

    tid = str(uuid.uuid4())
    with pytest.raises(ValueError, match="clean Session"):
        finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=1)


def test_finalize_target_active_transaction_rejected():
    session = MagicMock()
    session.in_transaction.return_value = True
    session.dirty = set()
    session.new = set()
    session.deleted = set()

    tid = str(uuid.uuid4())
    with pytest.raises(ValueError, match="clean Session"):
        finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=1)


def test_finalize_target_invalid_format():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=1, format="invalid_format")
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "format must be one of" in result.failure_detail


def test_finalize_target_invalid_expected_version():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=-1)
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "expected_target_version must be a non-negative integer" in result.failure_detail


def test_finalize_target_nul_character():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_current_hash="abc\x00def")
    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    assert "valid UTF-8 without NUL bytes" in result.failure_detail


def test_finalize_target_not_found():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    tx = MagicMock()
    session.begin.return_value = tx
    session.execute.return_value.scalar_one_or_none.return_value = None

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=1)

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.TARGET_NOT_FOUND
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


def test_finalize_target_version_mismatch():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 3
    target.current_hash = "hash3"
    target.filename = "doc.txt"
    target.source_line_endings = None
    # First query is select_target_for_update, second is existing_finalization
    session.execute.return_value.scalar_one_or_none.side_effect = [target, None]

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=2)

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.TARGET_VERSION_MISMATCH
    assert result.version == 3
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


def test_finalize_target_hash_mismatch():
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "actual_hash"
    target.filename = "doc.txt"
    target.source_line_endings = None
    session.execute.return_value.scalar_one_or_none.side_effect = [target, None]

    tid = str(uuid.uuid4())
    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_current_hash="different_hash")

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.TARGET_HASH_MISMATCH
    assert result.current_hash == "actual_hash"
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


@patch("app.services.finalize_service.save_target")
def test_finalize_target_save_rejection_rolls_back(mock_save):
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "hash2"
    target.filename = "doc.txt"
    target.source_line_endings = None
    session.execute.return_value.scalar_one_or_none.side_effect = [target, None]

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

    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=2)

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.CONTEXT_INVALID
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


@patch("app.services.finalize_service.save_target")
@patch("app.services.finalize_service.replay_target")
def test_finalize_target_replay_failure_rolls_back_save(mock_replay, mock_save):
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "hash2"
    target.filename = "doc.txt"
    target.source_line_endings = None
    session.execute.return_value.scalar_one_or_none.side_effect = [target, None]

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

    result = finalize_target(session, target_file_id=tid, client_request_id="req-1", expected_target_version=2)

    assert result.status == "rejected"
    assert result.failure_reason == FailureReason.REPLAY_HASH_MISMATCH
    assert "rolled back atomically" in result.failure_detail
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


@patch("app.services.finalize_service.save_target")
@patch("app.services.finalize_service.replay_target")
@patch("app.services.finalize_service.export_target")
def test_finalize_target_success_commits(mock_export, mock_replay, mock_save):
    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "hash2"
    target.filename = "main.py"
    target.source_line_endings = {"style": "crlf"}
    session.execute.return_value.scalar_one_or_none.side_effect = [target, None]

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

    content = "export_text\r\n"
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Real export_target contract returns "content", NOT "exported_content"
    mock_export.return_value = {
        "status": "ok",
        "target_file_id": tid,
        "filename": "main.py",
        "content": content,
        "content_sha256": content_sha256,
        "format": "original_eol",
    }

    result = finalize_target(
        session,
        target_file_id=tid,
        client_request_id="req-1",
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
    assert result.content_sha256 == content_sha256
    assert result.format == "original_eol"
    assert result.source_line_endings == {"style": "crlf"}
    assert result.lock_wait_ms is not None and result.lock_wait_ms >= 0
    assert result.lock_hold_ms is not None and result.lock_hold_ms >= 0
    tx.commit.assert_called_once()
    tx.rollback.assert_not_called()


def test_materialize_finalization_helper():
    from app.services.finalize_service import _materialize_finalization
    from app.storage.models import TargetFinalizations

    record = MagicMock(spec=TargetFinalizations)
    record.finalization_id = uuid.uuid4()
    record.target_file_id = uuid.uuid4()
    record.client_request_id = "req-1"
    record.fingerprint_version = 1
    record.request_fingerprint = "fp-1"
    record.status = "completed"
    record.snapshot_id = uuid.uuid4()
    record.closed_editing_cycle_id = uuid.uuid4()
    record.new_editing_cycle_id = uuid.uuid4()
    record.saved_target_version = 5
    record.canonical_current_hash = "h5"
    record.filename = "file.txt"
    record.export_format = "original_eol"
    record.content_eol = "lf"
    record.source_line_endings = {"style": "lf"}
    record.content_sha256 = "sha256"
    record.content_bytes = 100
    record.exported_content = "content"
    record.failure_code = None
    record.failure_detail = None
    record.materialized_state_checks = {"content_matches": True, "stored_hash_matches": True}

    detached = _materialize_finalization(record)
    assert detached.finalization_id == record.finalization_id
    assert detached.saved_target_version == 5
    assert detached.materialized_state_checks == {"content_matches": True, "stored_hash_matches": True}
    assert detached.source_line_endings == {"style": "lf"}
    # Verify dict copies are distinct instances
    assert detached.materialized_state_checks is not record.materialized_state_checks
    assert detached.source_line_endings is not record.source_line_endings


def test_finalize_target_idempotent_retry_returns_materialized_checks():
    from app.services.finalize_service import compute_finalization_fingerprint

    session = MagicMock()
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    tx = MagicMock()
    session.begin.return_value = tx

    target = MagicMock()
    target.version = 2
    target.current_hash = "hash2"
    target.filename = "main.py"
    target.source_line_endings = None

    tid = uuid.uuid4()
    client_req_id = "retry-req-1"
    _, fp = compute_finalization_fingerprint(
        target_file_id=tid,
        expected_target_version=2,
        expected_current_hash="hash2",
        format="original_eol",
    )

    existing = MagicMock()
    existing.finalization_id = uuid.uuid4()
    existing.target_file_id = tid
    existing.client_request_id = client_req_id
    existing.fingerprint_version = 1
    existing.request_fingerprint = fp
    existing.status = "completed"
    existing.snapshot_id = uuid.uuid4()
    existing.closed_editing_cycle_id = uuid.uuid4()
    existing.new_editing_cycle_id = uuid.uuid4()
    existing.saved_target_version = 2
    existing.canonical_current_hash = "hash2"
    existing.filename = "main.py"
    existing.export_format = "original_eol"
    existing.content_eol = "lf"
    existing.source_line_endings = None
    existing.content_sha256 = "hash2"
    existing.content_bytes = 12
    existing.exported_content = "text"
    existing.failure_code = None
    existing.failure_detail = None
    existing.materialized_state_checks = {
        "content_matches": True,
        "stored_hash_matches": True,
        "recomputed_hash_matches": True,
        "version_matches": True,
    }

    session.execute.return_value.scalar_one_or_none.side_effect = [target, existing]

    result = finalize_target(
        session,
        target_file_id=tid,
        client_request_id=client_req_id,
        expected_target_version=2,
        expected_current_hash="hash2",
        format="original_eol",
    )

    assert result.status == "ok"
    assert result.is_idempotent_replay is True
    assert result.materialized_state_checks == {
        "content_matches": True,
        "stored_hash_matches": True,
        "recomputed_hash_matches": True,
        "version_matches": True,
    }
    assert result.lock_wait_ms is not None and result.lock_wait_ms >= 0
    assert result.lock_hold_ms is not None and result.lock_hold_ms >= 0
    tx.rollback.assert_called_once()
    tx.commit.assert_not_called()


def test_read_finalized_export_validation_errors():
    import base64
    from app.services.export_service import read_finalized_export

    session = MagicMock()

    # Invalid UUIDs
    res1 = read_finalized_export(session, "invalid-uuid", str(uuid.uuid4()))
    assert res1["status"] == "invalid_argument"

    res2 = read_finalized_export(session, str(uuid.uuid4()), "invalid-uuid")
    assert res2["status"] == "invalid_argument"

    # Invalid offset
    res3 = read_finalized_export(session, str(uuid.uuid4()), str(uuid.uuid4()), offset=-1)
    assert res3["status"] == "invalid_argument"
    assert res3["code"] == "invalid_offset"

    res3_bool = read_finalized_export(session, str(uuid.uuid4()), str(uuid.uuid4()), offset=True)
    assert res3_bool["status"] == "invalid_argument"

    # Invalid limit
    res4 = read_finalized_export(session, str(uuid.uuid4()), str(uuid.uuid4()), limit=0)
    assert res4["status"] == "invalid_argument"
    assert res4["code"] == "invalid_limit"


def test_read_finalized_export_not_found_and_integrity_errors():
    from app.services.export_service import read_finalized_export
    from app.storage.models import TargetFinalizations, TargetSnapshots

    session = MagicMock()
    fin_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Finalization not found
    session.get.return_value = None
    res1 = read_finalized_export(session, fin_id, target_id)
    assert res1["status"] == "not_found"
    assert res1["error"] == "finalization_not_found"

    # Finalization belongs to another target
    fin = MagicMock(spec=TargetFinalizations)
    fin.finalization_id = fin_id
    fin.target_file_id = uuid.uuid4()  # different target
    fin.status = "completed"
    fin.snapshot_id = uuid.uuid4()
    session.get.return_value = fin
    res2 = read_finalized_export(session, fin_id, target_id)
    assert res2["status"] == "not_found"

    # Historical backfill when no chunks exist yet: snapshot not found
    fin.target_file_id = target_id
    fin.export_format = "canonical_lf"
    fin.source_line_endings = {"style": "lf"}
    fin.content_sha256 = "0" * 64
    fin.content_bytes = 100
    # 1st execute: _query_chunk_aggregate -> (0, 0, None, None)
    # 2nd execute: host-only receipt lock capability
    # 3rd execute: SELECT locked TargetFinalizations -> fin
    # 3rd execute: _query_chunk_aggregate under lock -> (0, 0, None, None)
    # 4th execute: SELECT TargetSnapshots -> None
    res_agg_zero = MagicMock()
    res_agg_zero.one.return_value = (0, 0, None, None)
    res_locked_fin = MagicMock()
    res_locked_fin.scalar_one_or_none.return_value = fin
    res_snap_none = MagicMock()
    res_snap_none.scalar_one_or_none.return_value = None

    session.execute.side_effect = [res_agg_zero, MagicMock(), res_locked_fin, res_agg_zero, res_snap_none]
    session.get.return_value = fin
    res3 = read_finalized_export(session, fin_id, target_id)
    assert res3["status"] == "error"
    assert res3["error"] == "snapshot_integrity_failure"

    # EOL derivation error (caught before chunk query)
    snap = MagicMock(spec=TargetSnapshots)
    snap.target_file_id = target_id
    snap.content = "corrupted text\n"
    snap.content_hash = hashlib.sha256(b"corrupted text\n").hexdigest()
    fin.export_format = "original_eol"
    fin.source_line_endings = None
    fin.content_sha256 = "0" * 64
    fin.content_bytes = 100
    fin.canonical_current_hash = snap.content_hash
    session.get.return_value = fin
    res4 = read_finalized_export(session, fin_id, target_id)
    assert res4["status"] == "error"
    assert res4["error"] == "snapshot_integrity_failure"
    assert "Failed to derive export line endings" in res4["failure_detail"]

    # Snapshot digest mismatch during historical backfill
    fin.export_format = "canonical_lf"
    res_snap = MagicMock()
    res_snap.scalar_one_or_none.return_value = snap
    session.execute.side_effect = [res_agg_zero, MagicMock(), res_locked_fin, res_agg_zero, res_snap]
    session.get.return_value = fin
    res5 = read_finalized_export(session, fin_id, target_id)
    assert res5["status"] == "error"
    assert res5["error"] == "snapshot_integrity_failure"
    assert "Snapshot integrity check failed" in res5["failure_detail"]


def test_read_finalized_export_chunked_storage_no_cache_and_tamper_detection():
    """Verify multi-page read_finalized_export reads immutable 256-KiB chunks without _VERIFIED_EXPORT_CACHE or TargetSnapshots.content (PR23-R4I-SVC-001)."""
    import base64
    from app.services import export_service
    from app.storage.models import TargetFinalizationExportChunks, TargetFinalizations

    assert not hasattr(export_service, "_VERIFIED_EXPORT_CACHE")
    session = MagicMock()
    fin_id = uuid.uuid4()
    target_id = uuid.uuid4()
    snap_id = uuid.uuid4()

    payload_text = "line-alpha\nline-beta\n" * 500
    payload_crlf = payload_text.replace("\n", "\r\n")
    raw_bytes = payload_crlf.encode("utf-8")
    expected_sha = hashlib.sha256(raw_bytes).hexdigest()

    fin = MagicMock(spec=TargetFinalizations)
    fin.finalization_id = fin_id
    fin.target_file_id = target_id
    fin.status = "completed"
    fin.snapshot_id = snap_id
    fin.export_format = "crlf"
    fin.content_eol = "crlf"
    fin.source_line_endings = {"style": "crlf"}
    fin.content_sha256 = expected_sha
    fin.content_bytes = len(raw_bytes)

    chunk_row = MagicMock(spec=TargetFinalizationExportChunks)
    chunk_row.finalization_id = fin_id
    chunk_row.chunk_index = 0
    chunk_row.payload = raw_bytes
    chunk_row.payload_sha256 = expected_sha
    chunk_row.byte_length = len(raw_bytes)

    session.get.return_value = fin
    exec_result = MagicMock()
    exec_result.one.return_value = (1, len(raw_bytes), 0, 0)
    exec_result.scalars.return_value.all.return_value = [chunk_row]
    session.execute.return_value = exec_result

    with patch("app.services.export_service.apply_eol", wraps=export_service.apply_eol) as spy_eol:
        assembled = bytearray()
        offset = 0
        pages = 0
        while True:
            page = export_service.read_finalized_export(session, fin_id, target_id, offset=offset, limit=1024)
            assert page["status"] == "ok"
            assembled.extend(base64.b64decode(page["content_base64"]))
            pages += 1
            if not page["has_more"]:
                break
            offset = page["next_offset"]

        assert pages > 5
        assert bytes(assembled) == raw_bytes
        # apply_eol is NEVER invoked when reading persisted chunks
        assert spy_eol.call_count == 0

    # Tampering with chunk payload immediately fails chunk SHA-256 verification
    chunk_row.payload = raw_bytes[:-1] + b"X"
    tampered = export_service.read_finalized_export(session, fin_id, target_id, offset=0, limit=1024)
    assert tampered["status"] == "error"
    assert tampered["error"] == "snapshot_integrity_failure"


def test_finalize_target_single_lock_and_two_phase_replay_freshness():
    """Verify real-Session finalize_target uses REPEATABLE READ READ ONLY pre-replay and verifies (version, current_hash, history_revision) + raw content under lock (PR23-IMPL-ARCH-001, PR23-R5-DB-001)."""
    from sqlalchemy.orm import Session
    from app.services import finalize_service

    session = MagicMock(spec=Session)
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    pre_tx = MagicMock()
    lock_tx = MagicMock()
    session.begin.side_effect = [pre_tx, lock_tx]

    tid = uuid.uuid4()
    target = MagicMock()
    target.target_file_id = tid
    target.version = 4
    target.history_revision = 9
    target.current_content = "alpha\nbeta\n"
    target.current_hash = hashlib.sha256(b"alpha\nbeta\n").hexdigest()
    target.filename = "notes.txt"
    target.source_line_endings = {"style": "lf"}
    target.active_editing_cycle_id = uuid.uuid4()

    session.get.return_value = target
    # 1st execute: SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY
    # 2nd execute: pre_existing in pre_tx -> None
    # 3rd execute: pre_target in pre_tx -> target
    # 4th execute: select_target_for_update in lock_tx -> target
    # 5th execute: existing_finalization in lock_tx -> None
    res_none = MagicMock()
    res_none.scalar_one_or_none.return_value = None
    res_target = MagicMock()
    res_target.scalar_one_or_none.return_value = target
    session.execute.side_effect = [MagicMock(), res_none, res_target, res_target, res_none]

    pre_replay = ReplayResult(
        status="replayed",
        target_file_id=tid,
        reconstructed_content="alpha\nbeta\n",
        reconstructed_hash=target.current_hash,
        current_hash=target.current_hash,
        accepted_transactions_replayed=4,
        materialized_state_matches=True,
        current_version=4,
        reconstructed_version=4,
        current_history_revision=9,
        materialized_state_checks={
            "content_matches": True,
            "stored_hash_matches": True,
            "recomputed_hash_matches": True,
            "version_matches": True,
        },
    )
    saved = SaveResult(
        status="saved",
        target_file_id=tid,
        snapshot_id=uuid.uuid4(),
        closed_editing_cycle_id=uuid.uuid4(),
        new_editing_cycle_id=uuid.uuid4(),
        current_hash=target.current_hash,
        version=4,
    )

    with (
        patch.object(finalize_service, "save_target_locked", return_value=saved) as mock_save_locked,
        patch.object(finalize_service, "replay_target", return_value=pre_replay) as mock_replay,
        patch.object(finalize_service, "_DEFAULT_REPLAY_TARGET", mock_replay),
        patch.object(
            finalize_service,
            "export_target",
            return_value={
                "status": "ok",
                "content": "alpha\nbeta\n",
                "content_sha256": target.current_hash,
                "format": "original_eol",
                "content_eol": "lf",
            },
        ),
    ):
        res = finalize_target(
            session,
            target_file_id=tid,
            client_request_id="req-2phase-1",
            expected_target_version=4,
            expected_current_hash=target.current_hash,
        )

    assert res.status == "ok"
    mock_save_locked.assert_called_once_with(session, target=target)
    mock_replay.assert_called_once_with(session, target_file_id=tid, for_update=False)
    pre_tx.rollback.assert_called_once()
    lock_tx.commit.assert_called_once()


def test_finalize_target_history_revision_drift_triggers_locked_replay_fallback():
    """Verify that if history_revision changes between pre-lock replay and FOR UPDATE lock, finalize_target re-runs replay_target under lock even if version and current_hash are unchanged."""
    from sqlalchemy.orm import Session
    from app.services import finalize_service

    session = MagicMock(spec=Session)
    session.in_transaction.return_value = False
    session.dirty = set()
    session.new = set()
    session.deleted = set()
    pre_tx = MagicMock()
    lock_tx = MagicMock()
    session.begin.side_effect = [pre_tx, lock_tx]

    tid = uuid.uuid4()
    target = MagicMock()
    target.target_file_id = tid
    target.version = 4
    target.history_revision = 10  # Bumped from 9 to 10 before lock acquisition!
    target.current_content = "alpha\nbeta\n"
    target.current_hash = hashlib.sha256(b"alpha\nbeta\n").hexdigest()
    target.filename = "notes.txt"
    target.source_line_endings = {"style": "lf"}
    target.active_editing_cycle_id = uuid.uuid4()

    session.get.return_value = target
    res_none = MagicMock()
    res_none.scalar_one_or_none.return_value = None
    res_target = MagicMock()
    res_target.scalar_one_or_none.return_value = target
    session.execute.side_effect = [MagicMock(), res_none, res_target, res_target, res_none]

    pre_replay = ReplayResult(
        status="replayed",
        target_file_id=tid,
        reconstructed_content="alpha\nbeta\n",
        reconstructed_hash=target.current_hash,
        current_hash=target.current_hash,
        accepted_transactions_replayed=4,
        materialized_state_matches=True,
        current_version=4,
        reconstructed_version=4,
        current_history_revision=9,  # Observed revision 9 pre-lock
        materialized_state_checks={
            "content_matches": True,
            "stored_hash_matches": True,
            "recomputed_hash_matches": True,
            "version_matches": True,
        },
    )
    locked_replay = ReplayResult(
        status="replayed",
        target_file_id=tid,
        reconstructed_content="alpha\nbeta\n",
        reconstructed_hash=target.current_hash,
        current_hash=target.current_hash,
        accepted_transactions_replayed=4,
        materialized_state_matches=True,
        current_version=4,
        reconstructed_version=4,
        current_history_revision=10,
        materialized_state_checks={
            "content_matches": True,
            "stored_hash_matches": True,
            "recomputed_hash_matches": True,
            "version_matches": True,
        },
    )
    saved = SaveResult(
        status="saved",
        target_file_id=tid,
        snapshot_id=uuid.uuid4(),
        closed_editing_cycle_id=uuid.uuid4(),
        new_editing_cycle_id=uuid.uuid4(),
        current_hash=target.current_hash,
        version=4,
    )

    with (
        patch.object(finalize_service, "save_target_locked", return_value=saved),
        patch.object(finalize_service, "replay_target", side_effect=[pre_replay, locked_replay]) as mock_replay,
        patch.object(finalize_service, "_DEFAULT_REPLAY_TARGET", mock_replay),
        patch.object(
            finalize_service,
            "export_target",
            return_value={
                "status": "ok",
                "content": "alpha\nbeta\n",
                "content_sha256": target.current_hash,
                "format": "original_eol",
                "content_eol": "lf",
            },
        ),
    ):
        res = finalize_target(
            session,
            target_file_id=tid,
            client_request_id="req-2phase-drift",
            expected_target_version=4,
            expected_current_hash=target.current_hash,
        )

    assert res.status == "ok"
    assert mock_replay.call_count == 2
