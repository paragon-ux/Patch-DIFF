"""Adversarial stress-test battery for examples/host_finalize.py:finalize_single_target.

Focus areas:
1. PR23-R3-SCRIPT-004: Deferred export pagination, integrity validation, and failure isolation.
2. PR23-R3-SCRIPT-005: Mandatory preimage enforcement and unconditional overwrite bypass.
3. PR23-R3-SCRIPT-004: Truthful multi-stage status separation (db_status vs disk_status).
"""
import base64
import hashlib
import os
from pathlib import Path
import pytest
import uuid

from examples import host_finalize as finalizer


# -----------------------------------------------------------------------------
# Helpers & Mock Factories
# -----------------------------------------------------------------------------

def _make_chunked_export_mocks(
    full_payload: bytes,
    *,
    chunk_size: int = 262144,
    corrupt_b64_page: int | None = None,
    corrupt_payload_page: int | None = None,
    missing_b64_page: int | None = None,
    tool_error_page: int | None = None,
    tool_exception_page: int | None = None,
    trap_pagination: str | None = None,
    custom_content_sha256: str | None = None,
    custom_content_bytes: int | None = None,
):
    """Factory creating mock call_tool functions for finalize_single_target deferred export."""
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    full_sha = hashlib.sha256(full_payload).hexdigest()
    content_sha = custom_content_sha256 if custom_content_sha256 is not None else full_sha
    content_bytes = custom_content_bytes if custom_content_bytes is not None else len(full_payload)

    # Compute chunks
    chunks: list[bytes] = []
    if len(full_payload) == 0:
        chunks = [b""]
    else:
        for i in range(0, len(full_payload), chunk_size):
            chunks.append(full_payload[i : i + chunk_size])

    calls = []
    page_counter = [0]

    def mock_call(name, **kwargs):
        calls.append((name, kwargs))
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "version": 42,
                "filename": "deferred.bin",
                "exported_content": None,  # Signals deferred delivery > 1 MiB
                "content_delivery": "deferred",
                "content_sha256": content_sha,
                "content_bytes": content_bytes,
            }
        elif name == "patchdiff_read_finalized_export":
            assert kwargs.get("finalization_id") == fid
            assert kwargs.get("target_file_id") == tid
            page_idx = page_counter[0]
            page_counter[0] += 1

            if tool_exception_page is not None and page_idx == tool_exception_page:
                raise ConnectionResetError(f"Simulated network drop on page {page_idx}")

            if tool_error_page is not None and page_idx == tool_error_page:
                return {
                    "status": "error",
                    "error": "snapshot_integrity_failure",
                    "failure_detail": f"Simulated tool error on page {page_idx}",
                }

            if missing_b64_page is not None and page_idx == missing_b64_page:
                return {
                    "status": "ok",
                    "finalization_id": fid,
                    "target_file_id": tid,
                    "offset": kwargs["offset"],
                    "bytes_read": 100,
                    "total_bytes": len(full_payload),
                    "has_more": False,
                }

            req_offset = kwargs["offset"]
            req_limit = kwargs["limit"]

            # Trap pagination anomalies
            if trap_pagination == "infinite_loop" and page_idx == 1:
                return {
                    "status": "ok",
                    "finalization_id": fid,
                    "target_file_id": tid,
                    "content_base64": base64.b64encode(b"loop").decode("ascii"),
                    "offset": req_offset,
                    "bytes_read": 4,
                    "total_bytes": len(full_payload),
                    "has_more": True,
                    "next_offset": req_offset,  # Trap: next == current!
                }
            if trap_pagination == "backward_offset" and page_idx == 1:
                return {
                    "status": "ok",
                    "finalization_id": fid,
                    "target_file_id": tid,
                    "content_base64": base64.b64encode(b"back").decode("ascii"),
                    "offset": req_offset,
                    "bytes_read": 4,
                    "total_bytes": len(full_payload),
                    "has_more": True,
                    "next_offset": max(0, req_offset - 100),  # Trap: backward!
                }
            if trap_pagination == "missing_next_offset" and page_idx == 0:
                return {
                    "status": "ok",
                    "finalization_id": fid,
                    "target_file_id": tid,
                    "content_base64": base64.b64encode(b"chunk").decode("ascii"),
                    "offset": req_offset,
                    "bytes_read": 5,
                    "total_bytes": len(full_payload),
                    "has_more": True,
                    "next_offset": None,  # Trap: has_more=True but next_offset=None
                }

            # Normal or corrupted slice
            chunk = full_payload[req_offset : req_offset + req_limit]
            if corrupt_payload_page is not None and page_idx == corrupt_payload_page:
                chunk = b"CORRUPTED_BYTES_" + chunk[16:]

            if corrupt_b64_page is not None and page_idx == corrupt_b64_page:
                b64_str = "!!!NotBase64InvalidPadding==="
            else:
                b64_str = base64.b64encode(chunk).decode("ascii")

            has_more = (req_offset + len(chunk)) < len(full_payload)
            next_offset = (req_offset + len(chunk)) if has_more else None

            return {
                "status": "ok",
                "finalization_id": fid,
                "target_file_id": tid,
                "content_base64": b64_str,
                "offset": req_offset,
                "bytes_read": len(chunk),
                "total_bytes": len(full_payload),
                "content_sha256": content_sha,
                "has_more": has_more,
                "next_offset": next_offset,
            }

        raise ValueError(f"Unexpected tool call: {name}")

    return tid, fid, full_sha, calls, mock_call


# =============================================================================
# 1. Deferred Export Pagination & Integrity Challenge (PR23-R3-SCRIPT-004)
# =============================================================================

def test_deferred_export_multi_page_success(tmp_path):
    """Verify that multi-page deferred export streams cleanly, verifies digest, and writes destination."""
    # 700 KiB payload across 3 pages (256 KiB, 256 KiB, 188 KiB)
    payload = b"PATCHDIFF_DEFERRED_TEST_PAYLOAD_" * 25000  # ~800,000 bytes
    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(payload)

    dest = tmp_path / "successful_deferred.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-deferred-ok",
        destination_path=dest,
    )

    assert receipt["status"] == "ok"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert receipt["written_destination"] == str(dest)
    assert dest.is_file()
    assert dest.read_bytes() == payload
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == expected_sha


@pytest.mark.parametrize("corrupt_page", [0, 1, 3])
def test_deferred_export_corrupted_base64_in_stream(tmp_path, corrupt_page):
    """Verify corrupted base64 at any page fails closed: status='error', disk_status='error', no disk write."""
    payload = b"D" * (262144 * 4)  # 4 full pages
    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(
        payload, corrupt_b64_page=corrupt_page
    )

    dest = tmp_path / f"corrupt_b64_page_{corrupt_page}.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id=f"req-b64-corrupt-{corrupt_page}",
        destination_path=dest,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error", "Must never report status='ok' on corrupted base64"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert receipt["written_destination"] is None
    assert "Invalid base64 payload" in receipt["disk_error"]
    assert not dest.exists(), "Destination file must never be created on stream failure"


@pytest.mark.parametrize("error_page", [0, 2])
def test_deferred_export_midstream_tool_error(tmp_path, error_page):
    """Verify tool returning status='error' mid-stream immediately aborts with truthful error reporting."""
    payload = b"T" * (262144 * 3)
    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(
        payload, tool_error_page=error_page
    )

    dest = tmp_path / f"tool_error_page_{error_page}.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id=f"req-tool-err-{error_page}",
        destination_path=dest,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert receipt["written_destination"] is None
    assert "Deferred read failed" in receipt["disk_error"]
    assert not dest.exists()


def test_deferred_export_tool_exception_midstream(tmp_path):
    """Verify unexpected tool exception during deferred retrieval fails closed."""
    payload = b"E" * (262144 * 3)
    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(
        payload, tool_exception_page=1
    )

    dest = tmp_path / "exception_midstream.bin"
    # Case 1: raise_on_disk_error=False
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-exc-stream",
        destination_path=dest,
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert receipt["written_destination"] is None
    assert not dest.exists()

    # Case 2: raise_on_disk_error=True with fresh mock
    tid_2, _, _, _, mock_call_2 = _make_chunked_export_mocks(
        payload, tool_exception_page=1
    )
    with pytest.raises((finalizer.HostWriteBackError, ConnectionResetError)):
        finalizer.finalize_single_target(
            mock_call_2,
            target_file_id=tid_2,
            client_request_id="req-exc-stream-raise",
            destination_path=dest,
            raise_on_disk_error=True,
        )
    assert not dest.exists()


def test_deferred_export_assembled_sha256_mismatch(tmp_path):
    """Verify that tampering 1 byte mid-stream is caught by assembled SHA-256 validation before write."""
    payload = b"A" * (262144 * 3)
    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(
        payload, corrupt_payload_page=1  # Page 1 corrupted
    )

    dest = tmp_path / "tampered_assembled.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-tampered-sha",
        destination_path=dest,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert receipt["written_destination"] is None
    assert "Deferred assembled bytes SHA-256" in receipt["disk_error"]
    assert not dest.exists()


def test_deferred_export_assembled_length_mismatch(tmp_path):
    """Verify that byte count discrepancy between receipt metadata and assembled stream is rejected."""
    payload = b"L" * (262144 * 2)
    # Advertise content_bytes 100 bytes larger than actual
    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(
        payload, custom_content_bytes=len(payload) + 100
    )

    dest = tmp_path / "length_mismatch.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-length-mismatch",
        destination_path=dest,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert "Deferred assembled bytes length" in receipt["disk_error"]
    assert not dest.exists()


@pytest.mark.parametrize("trap", ["infinite_loop", "backward_offset", "missing_next_offset"])
def test_deferred_export_pagination_anomalies_fail_closed(tmp_path, trap):
    """Verify pagination loop traps (infinite offset loop, backward offset, missing offset) abort immediately."""
    payload = b"P" * (262144 * 3)
    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(
        payload, trap_pagination=trap
    )

    dest = tmp_path / f"trap_{trap}.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id=f"req-trap-{trap}",
        destination_path=dest,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert receipt["written_destination"] is None
    assert "Invalid pagination response" in receipt["disk_error"]
    assert not dest.exists()


def test_deferred_export_multibyte_utf8_split_across_chunks(tmp_path):
    """Verify multibyte UTF-8 characters split exactly across 256KiB chunk boundary assemble with 100% fidelity."""
    # Construct payload where a 4-byte emoji (🚀: F0 9F 99 80) straddles byte 262142 (2 bytes in chunk 1, 2 in chunk 2)
    prefix = b"A" * (262144 - 2)
    rocket = "🚀".encode("utf-8")  # 4 bytes
    assert len(rocket) == 4
    suffix = b"B" * 1000
    full_payload = prefix + rocket + suffix

    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(full_payload)
    dest = tmp_path / "utf8_split.txt"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-utf8-split",
        destination_path=dest,
    )

    assert receipt["status"] == "ok"
    assert receipt["disk_status"] == "written"
    written_data = dest.read_bytes()
    assert written_data == full_payload
    assert written_data[262144 - 2 : 262144 + 2] == rocket
    assert written_data.decode("utf-8").endswith("🚀" + ("B" * 1000))


def test_deferred_export_zero_length_file(tmp_path):
    """Verify 0-byte deferred export is handled cleanly and creates empty file."""
    full_payload = b""
    tid, fid, expected_sha, calls, mock_call = _make_chunked_export_mocks(full_payload)
    dest = tmp_path / "empty_deferred.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-empty-deferred",
        destination_path=dest,
    )

    assert receipt["status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert dest.exists()
    assert dest.stat().st_size == 0


# =============================================================================
# 2. Mandatory Preimage Challenge (PR23-R3-SCRIPT-005)
# =============================================================================

def test_preimage_overwrite_existing_without_preimage_rejected(tmp_path):
    """Verify attempting to overwrite an existing file when preimage_sha256 is None fails closed."""
    dest = tmp_path / "target.txt"
    original_data = b"Original baseline data v1\n"
    dest.write_bytes(original_data)

    new_content = "New incoming data v2\n"
    new_bytes = new_content.encode("utf-8")
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    tid = str(uuid.uuid4())

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 2,
            "exported_content": new_content,
            "content_sha256": new_sha,
            "content_delivery": "inline",
            "content_bytes": len(new_bytes),
        }

    # 1. With raise_on_disk_error=False
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-preimage-missing",
        destination_path=dest,
        preimage_sha256=None,  # Missing!
        allow_unconditional_overwrite=False,
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert receipt["written_destination"] is None
    assert "preimage_sha256 is required unless allow_unconditional_overwrite=True" in receipt["disk_error"]
    # Existing disk content MUST be unmodified
    assert dest.read_bytes() == original_data

    # 2. With raise_on_disk_error=True: must raise PreimageMismatchError
    with pytest.raises(finalizer.PreimageMismatchError):
        finalizer.finalize_single_target(
            mock_call,
            target_file_id=tid,
            client_request_id="req-preimage-missing-raise",
            destination_path=dest,
            preimage_sha256=None,
            allow_unconditional_overwrite=False,
            raise_on_disk_error=True,
        )
    assert dest.read_bytes() == original_data


def test_preimage_overwrite_existing_with_matching_preimage_succeeds(tmp_path):
    """Verify providing correct preimage_sha256 allows atomic destination overwrite."""
    dest = tmp_path / "target.txt"
    original_data = b"Original baseline data v1\n"
    dest.write_bytes(original_data)
    original_sha = hashlib.sha256(original_data).hexdigest()

    new_content = "New incoming data v2\n"
    new_bytes = new_content.encode("utf-8")
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    tid = str(uuid.uuid4())

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 2,
            "exported_content": new_content,
            "content_sha256": new_sha,
            "content_delivery": "inline",
            "content_bytes": len(new_bytes),
        }

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-preimage-match",
        destination_path=dest,
        preimage_sha256=original_sha,  # Matching!
        allow_unconditional_overwrite=False,
    )

    assert receipt["status"] == "ok"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert receipt["written_destination"] == str(dest)
    assert dest.read_bytes() == new_bytes


def test_preimage_overwrite_existing_with_mismatched_preimage_fails(tmp_path):
    """Verify providing mismatched preimage_sha256 fails closed without overwriting disk."""
    dest = tmp_path / "target.txt"
    original_data = b"Original baseline data v1\n"
    dest.write_bytes(original_data)

    new_content = "New incoming data v2\n"
    new_bytes = new_content.encode("utf-8")
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    tid = str(uuid.uuid4())

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 2,
            "exported_content": new_content,
            "content_sha256": new_sha,
            "content_delivery": "inline",
            "content_bytes": len(new_bytes),
        }

    bogus_sha = "0" * 64
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-preimage-mismatch",
        destination_path=dest,
        preimage_sha256=bogus_sha,  # Mismatch!
        allow_unconditional_overwrite=False,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert "has hash" in receipt["disk_error"] and "expected" in receipt["disk_error"]
    assert dest.read_bytes() == original_data


def test_preimage_allow_unconditional_overwrite(tmp_path):
    """Verify allow_unconditional_overwrite=True permits overwrite when preimage_sha256 is None."""
    dest = tmp_path / "target.txt"
    original_data = b"Original baseline data v1\n"
    dest.write_bytes(original_data)

    new_content = "New incoming data v2 (unconditional)\n"
    new_bytes = new_content.encode("utf-8")
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    tid = str(uuid.uuid4())

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 2,
            "exported_content": new_content,
            "content_sha256": new_sha,
            "content_delivery": "inline",
            "content_bytes": len(new_bytes),
        }

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-unconditional-ok",
        destination_path=dest,
        preimage_sha256=None,
        allow_unconditional_overwrite=True,  # Explicit override!
    )

    assert receipt["status"] == "ok"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert dest.read_bytes() == new_bytes


def test_preimage_unconditional_flag_with_mismatched_preimage_still_fails(tmp_path):
    """Verify that allow_unconditional_overwrite=True DOES NOT bypass an explicitly specified mismatched preimage."""
    dest = tmp_path / "target.txt"
    original_data = b"Original data\n"
    dest.write_bytes(original_data)

    new_content = "New data\n"
    new_bytes = new_content.encode("utf-8")
    tid = str(uuid.uuid4())

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 2,
            "exported_content": new_content,
            "content_sha256": hashlib.sha256(new_bytes).hexdigest(),
        }

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-unconditional-bad-preimage",
        destination_path=dest,
        preimage_sha256="bad" * 21 + "0",  # Provided but wrong!
        allow_unconditional_overwrite=True,
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["disk_status"] == "error"
    assert dest.read_bytes() == original_data


def test_preimage_new_file_with_preimage_fails(tmp_path):
    """Verify that specifying preimage_sha256 when target file DOES NOT EXIST fails closed with PreimageMismatchError."""
    dest = tmp_path / "nonexistent.txt"
    assert not dest.exists()

    new_content = "Fresh file content\n"
    new_bytes = new_content.encode("utf-8")
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    tid = str(uuid.uuid4())

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 1,
            "exported_content": new_content,
            "content_sha256": new_sha,
        }

    # 1. With raise_on_disk_error=False
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-new-file-bad-preimage",
        destination_path=dest,
        preimage_sha256="f" * 64,  # Expected nonexistent file to have a hash!
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert "does not exist, but preimage_sha256 was expected" in receipt["disk_error"]
    assert not dest.exists()

    # 2. With raise_on_disk_error=True
    with pytest.raises(finalizer.PreimageMismatchError):
        finalizer.finalize_single_target(
            mock_call,
            target_file_id=tid,
            client_request_id="req-new-file-bad-preimage-raise",
            destination_path=dest,
            preimage_sha256="f" * 64,
            raise_on_disk_error=True,
        )
    assert not dest.exists()


def test_preimage_new_file_without_preimage_succeeds(tmp_path):
    """Verify creating a brand-new file with preimage_sha256=None succeeds cleanly."""
    dest = tmp_path / "brand_new.txt"
    assert not dest.exists()

    new_content = "Brand new file content\n"
    new_bytes = new_content.encode("utf-8")
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    tid = str(uuid.uuid4())

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 1,
            "exported_content": new_content,
            "content_sha256": new_sha,
        }

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-brand-new",
        destination_path=dest,
        preimage_sha256=None,
    )
    assert receipt["status"] == "ok"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert dest.read_bytes() == new_bytes


def test_preimage_case_insensitivity(tmp_path):
    """Verify preimage hash comparison is hex case-insensitive (e.g. uppercase vs lowercase)."""
    dest = tmp_path / "case_test.txt"
    original_data = b"some data\n"
    dest.write_bytes(original_data)
    upper_sha = hashlib.sha256(original_data).hexdigest().upper()

    new_content = "updated data\n"
    new_bytes = new_content.encode("utf-8")
    tid = str(uuid.uuid4())

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 2,
            "exported_content": new_content,
            "content_sha256": hashlib.sha256(new_bytes).hexdigest(),
        }

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-case-insens",
        destination_path=dest,
        preimage_sha256=upper_sha,
    )
    assert receipt["status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert dest.read_bytes() == new_bytes


# =============================================================================
# 3. Multi-Stage Status Separation (PR23-R3-SCRIPT-004)
# =============================================================================

def test_status_separation_destination_path_none(tmp_path):
    """Verify that when destination_path is None, db_status='ok', disk_status='skipped', status='ok'."""
    tid = str(uuid.uuid4())
    called = []

    def mock_call(name, **kwargs):
        called.append(name)
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "version": 3,
                "exported_content": None,  # Deferred!
                "content_delivery": "deferred",
                "content_sha256": "a" * 64,
                "finalization_id": str(uuid.uuid4()),
            }
        raise AssertionError(f"Unexpected call to {name} when destination_path is None")

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-no-dest",
        destination_path=None,
    )

    assert receipt["status"] == "ok"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "skipped"
    assert receipt["written_destination"] is None
    assert called == ["patchdiff_finalize_target"]


@pytest.mark.parametrize("rejection_status", ["rejected", "invalid_argument", "not_found", "error"])
def test_status_separation_db_failure_skips_disk(tmp_path, rejection_status):
    """Verify that when DB finalization returns non-ok status, disk_status='skipped' and disk is untouched."""
    tid = str(uuid.uuid4())
    dest = tmp_path / "never_written.bin"

    def mock_call(name, **kwargs):
        return {
            "status": rejection_status,
            "target_file_id": tid,
            "failure_reason": "version_guard_mismatch",
        }

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id=f"req-db-fail-{rejection_status}",
        destination_path=dest,
    )

    assert receipt["status"] == rejection_status
    assert receipt["db_status"] == rejection_status
    assert receipt["disk_status"] == "skipped"
    assert receipt["written_destination"] is None
    assert not dest.exists(), "Write-back must never be attempted if DB finalization was not 'ok'"


def test_status_separation_disk_error_preserves_db_status_ok(tmp_path):
    """Verify that when DB finalization succeeds but disk write fails, db_status remains 'ok' while overall status is 'error'."""
    tid = str(uuid.uuid4())
    dest = tmp_path / "existing.txt"
    dest.write_bytes(b"initial\n")

    new_content = "replacement\n"
    new_bytes = new_content.encode("utf-8")

    def mock_call(name, **kwargs):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 2,
            "exported_content": new_content,
            "content_sha256": hashlib.sha256(new_bytes).hexdigest(),
        }

    # Trigger disk error via missing preimage on existing file
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="req-partial-status",
        destination_path=dest,
        preimage_sha256=None,
        allow_unconditional_overwrite=False,
        raise_on_disk_error=False,
    )

    assert receipt["db_status"] == "ok", "Database state succeeded and must be reported as 'ok'"
    assert receipt["disk_status"] == "error", "Disk write failed and must be reported as 'error'"
    assert receipt["status"] == "error", "Overall lifecycle status must be 'error' to prevent false host success"
    assert receipt["written_destination"] is None
    assert "preimage_sha256 is required" in receipt["disk_error"]
