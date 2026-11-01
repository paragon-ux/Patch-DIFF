import base64
import copy
import hashlib
import json
import os
import threading
import uuid

import pytest

from examples import host_finalize as finalizer


def setup_targets(count=1, filename="results.json"):
    content = "changed 🌟\n"
    targets = [{"filename": filename if i == 0 else f"target{i}.txt", "target_file_id": str(uuid.uuid4()),
                "accepted_pdcp_log_id": str(uuid.uuid4()), "expected_target_version": 1,
                "expected_current_hash": hashlib.sha256(content.encode()).hexdigest()} for i in range(count)]
    calls = []
    def call(name, **args):
        calls.append((name, args))
        item = next(t for t in targets if t["target_file_id"] == args["target_file_id"])
        common = {"target_file_id": item["target_file_id"], "current_hash": item["expected_current_hash"]}
        if name == "patchdiff_save":
            return {**common, "status": "saved", "version": 1,
                    **{k: str(uuid.uuid4()) for k in ("snapshot_id", "closed_editing_cycle_id", "new_editing_cycle_id")}}
        if name == "patchdiff_replay":
            return {**common, "status": "success", "materialized_state_matches": True,
                    "reconstructed_version": 1, "current_version": 1, "reconstructed_hash": common["current_hash"],
                    "materialized_state_checks": {k: True for k in (
                        "content_matches", "stored_hash_matches", "recomputed_hash_matches", "version_matches")}}
        return {"status": "ok", "filename": item["filename"], "content": content, "version": 1,
                "current_hash": common["current_hash"], "hash": common["current_hash"],
                "content_sha256": common["current_hash"], "format": "canonical_lf"}
    return targets, calls, call


def test_success_separates_export_names_from_control_artifacts_and_refuses_rerun(tmp_path):
    targets, calls, call = setup_targets(2)
    result = finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert result["status"] == "complete" and len(calls) == 6
    assert json.loads((tmp_path / "run/results.json").read_text()) == result
    assert (tmp_path / "run/exports/results.json").read_bytes() == "changed 🌟\n".encode()
    events = [json.loads(l) for l in (tmp_path / "run/events.jsonl").read_text().splitlines()]
    assert sum(e["kind"] == "save_pending" for e in events) == 2
    with pytest.raises(FileExistsError): finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert len(calls) == 6


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "CON", "nul.txt", "COM1.py", "x.", "x ", "a:b", "x\x00"])
def test_unsafe_names_fail_before_any_call(tmp_path, name):
    targets, calls, call = setup_targets(filename=name)
    with pytest.raises(ValueError): finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert not calls and not (tmp_path / "run").exists()


@pytest.mark.parametrize("field,value", [("expected_target_version", True), ("expected_target_version", -1),
    ("expected_current_hash", "bad"), ("accepted_pdcp_log_id", "bad")])
def test_invalid_manifest_fails_before_any_call(tmp_path, field, value):
    targets, calls, call = setup_targets()
    targets[0][field] = value
    with pytest.raises(ValueError): finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert not calls


def test_case_insensitive_duplicate_names_preflight_all_targets(tmp_path):
    targets, calls, call = setup_targets(2)
    targets[1]["filename"] = "RESULTS.JSON"
    with pytest.raises(ValueError): finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert not calls


@pytest.mark.parametrize("failure", ["lost", "malformed", "rejected", "replay", "export"])
def test_failure_paths_do_not_retry_save_or_claim_success(tmp_path, failure):
    targets, calls, call = setup_targets(2)
    def faulty(name, **args):
        result = call(name, **args)
        if args["target_file_id"] == targets[0]["target_file_id"]:
            if name == "patchdiff_save":
                if failure == "lost": raise TimeoutError("response lost")
                if failure == "malformed": return {"status": "saved"}
                if failure == "rejected": return {"status": "rejected", "target_file_id": args["target_file_id"]}
            if name == "patchdiff_replay" and failure == "replay":
                result["materialized_state_checks"]["content_matches"] = False
            if name == "patchdiff_export_target" and failure == "export": result["content"] += "collateral"
        return result
    result = finalizer.finalize_targets(faulty, targets, tmp_path / "run")
    uncertain = failure in {"lost", "malformed"}
    assert result["status"] == ("uncertain" if uncertain else "failed")
    assert result["targets"][0]["status"] == ("save_uncertain" if uncertain else "failed")
    assert result["targets"][1]["status"] == ("not_attempted" if uncertain else "complete")
    assert sum(name == "patchdiff_save" and args["target_file_id"] == targets[0]["target_file_id"] for name, args in calls) == 1
    if failure in {"lost", "malformed", "rejected"}:
        assert not any(name != "patchdiff_save" and args["target_file_id"] == targets[0]["target_file_id"] for name, args in calls)


def test_failed_save_receipt_fsync_preserves_pending_and_stops_calls(tmp_path, monkeypatch):
    targets, calls, call = setup_targets(2)
    fsync = finalizer.os.fsync
    counter = 0
    def fail_receipt(fd):
        nonlocal counter
        counter += 1
        if counter == 3: raise OSError("disk failure after SAVE")
        fsync(fd)
    monkeypatch.setattr(finalizer.os, "fsync", fail_receipt)
    result = finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert result["status"] == "uncertain" and len(calls) == 1
    assert '"save_pending"' in (tmp_path / "run/events.jsonl").read_text()


@pytest.mark.parametrize("failed_name", ["results.json", "exports/results.json"])
def test_evidence_failure_returns_incomplete_without_false_receipt(tmp_path, monkeypatch, failed_name):
    targets, calls, call = setup_targets(2)
    write = finalizer._write_new
    def failing(path, data):
        if path.relative_to(tmp_path / "run").as_posix() == failed_name: raise OSError("disk full")
        write(path, data)
    monkeypatch.setattr(finalizer, "_write_new", failing)
    result = finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert result["status"] == "failed"
    if failed_name == "results.json":
        assert result["evidence_error"] and not (tmp_path / "run/results.json").exists()
    else:
        assert result["targets"][1]["status"] == "not_attempted" and len(calls) == 3


def test_safe_write_back_file_success(tmp_path):
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    target_path = auth_root / "src" / "app.py"
    content = b"print('hello world')\n"
    content_hash = hashlib.sha256(content).hexdigest()

    # Initial write
    written = finalizer.safe_write_back_file(
        target_path,
        content,
        expected_sha256=content_hash,
        authorized_root=auth_root,
    )
    assert written == target_path.resolve()
    assert target_path.read_bytes() == content

    # Second write with matched preimage
    new_content = b"print('hello world modified')\n"
    new_hash = hashlib.sha256(new_content).hexdigest()
    finalizer.safe_write_back_file(
        target_path,
        new_content,
        expected_sha256=new_hash,
        preimage_sha256=content_hash,
        authorized_root=auth_root,
    )
    assert target_path.read_bytes() == new_content


def test_safe_write_back_preimage_mismatch_fails_without_overwrite(tmp_path):
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    target_path = auth_root / "config.yaml"
    initial_bytes = b"mode: prod\n"
    target_path.write_bytes(initial_bytes)
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()

    # External modification occurs
    target_path.write_bytes(b"mode: external_change\n")

    # Attempt write-back expecting initial_hash as preimage
    new_bytes = b"mode: patchdiff_update\n"
    new_hash = hashlib.sha256(new_bytes).hexdigest()
    with pytest.raises(finalizer.PreimageMismatchError):
        finalizer.safe_write_back_file(
            target_path,
            new_bytes,
            expected_sha256=new_hash,
            preimage_sha256=initial_hash,
            authorized_root=auth_root,
        )
    # File on disk remains external_change (not overwritten)
    assert target_path.read_bytes() == b"mode: external_change\n"


def test_safe_write_back_path_escape_rejected(tmp_path):
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    escape_path = tmp_path / "outside.txt"

    content = b"malicious write\n"
    content_hash = hashlib.sha256(content).hexdigest()

    with pytest.raises(finalizer.PathEscapeError):
        finalizer.safe_write_back_file(
            escape_path,
            content,
            expected_sha256=content_hash,
            authorized_root=auth_root,
        )
    assert not escape_path.exists()


def test_finalize_single_target_success(tmp_path):
    content = "def test():\n    pass\n"
    content_bytes = content.encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    tid = str(uuid.uuid4())

    def mock_call(name, **args):
        assert name == "patchdiff_finalize_target"
        assert args["target_file_id"] == tid
        assert args["client_request_id"] == "req-single"
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 1,
            "filename": "test.py",
            "exported_content": content,
            "content_sha256": content_hash,
        }

    dest_file = tmp_path / "test.py"
    res = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        expected_target_version=1,
        client_request_id="req-single",
        destination_path=dest_file,
    )
    assert res["status"] == "ok"
    assert res["db_status"] == "ok"
    assert res["disk_status"] == "written"
    assert res["written_destination"] == str(dest_file)
    assert dest_file.read_text(encoding="utf-8") == content


# --- Comprehensive Security & Regression Tests (SCRIPT-001..005) ---


def test_safe_write_back_pre_write_digest_mismatch(tmp_path):
    """PR23-R3-SCRIPT-002: Pre-write digest verification rejects mismatched data before touching disk."""
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    target_path = auth_root / "app.py"
    original_bytes = b"def original():\n    return 42\n"
    target_path.write_bytes(original_bytes)
    orig_hash = hashlib.sha256(original_bytes).hexdigest()

    corrupt_data = b"def corrupted():\n    return 0\n"
    fake_expected_hash = "a" * 64

    # Must raise HostWriteBackError before touching disk or creating temp files
    with pytest.raises(finalizer.HostWriteBackError) as exc_info:
        finalizer.safe_write_back_file(
            target_path,
            corrupt_data,
            expected_sha256=fake_expected_hash,
            preimage_sha256=orig_hash,
            authorized_root=auth_root,
        )
    assert "Pre-write digest verification failed" in str(exc_info.value)
    # Target file is untouched
    assert target_path.read_bytes() == original_bytes
    # No temporary files created
    temp_files = list(target_path.parent.glob(".tmp-*"))
    assert len(temp_files) == 0


def test_safe_write_back_invalid_data_and_expected_sha_formats(tmp_path):
    """PR23-R3-SCRIPT-002: Rejects non-bytes data and invalid hash formats."""
    target_path = tmp_path / "file.txt"
    with pytest.raises(finalizer.HostWriteBackError):
        finalizer.safe_write_back_file(target_path, "not bytes", expected_sha256="a" * 64)  # type: ignore

    with pytest.raises(finalizer.HostWriteBackError):
        finalizer.safe_write_back_file(target_path, b"bytes", expected_sha256="short_hash")

    with pytest.raises(finalizer.HostWriteBackError):
        finalizer.safe_write_back_file(target_path, b"bytes", expected_sha256="g" * 64)


def test_safe_write_back_preimage_mandatory_enforcement(tmp_path):
    """PR23-R3-SCRIPT-005: Preimage is mandatory for existing files unless allow_unconditional_overwrite=True."""
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    target_path = auth_root / "locked.py"
    initial_bytes = b"version = 1\n"
    target_path.write_bytes(initial_bytes)
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()

    new_data = b"version = 2\n"
    new_hash = hashlib.sha256(new_data).hexdigest()

    # 1. Attempt overwrite without preimage and without unconditional authorization -> Rejected!
    with pytest.raises(finalizer.PreimageMismatchError) as exc_info:
        finalizer.safe_write_back_file(
            target_path,
            new_data,
            expected_sha256=new_hash,
            preimage_sha256=None,
            authorized_root=auth_root,
            allow_unconditional_overwrite=False,
        )
    assert "preimage_sha256 is required" in str(exc_info.value)
    assert target_path.read_bytes() == initial_bytes

    # 2. Overwrite with valid preimage -> Allowed
    finalizer.safe_write_back_file(
        target_path,
        new_data,
        expected_sha256=new_hash,
        preimage_sha256=initial_hash,
        authorized_root=auth_root,
        allow_unconditional_overwrite=False,
    )
    assert target_path.read_bytes() == new_data

    # 3. Overwrite with allow_unconditional_overwrite=True -> Allowed without preimage
    unconditional_data = b"version = 3\n"
    unconditional_hash = hashlib.sha256(unconditional_data).hexdigest()
    finalizer.safe_write_back_file(
        target_path,
        unconditional_data,
        expected_sha256=unconditional_hash,
        preimage_sha256=None,
        authorized_root=auth_root,
        allow_unconditional_overwrite=True,
    )
    assert target_path.read_bytes() == unconditional_data


def test_safe_write_back_preimage_on_nonexistent_destination_raises(tmp_path):
    """PR23-R3-SCRIPT-005: Preimage provided when destination does not exist raises PreimageMismatchError."""
    target_path = tmp_path / "nonexistent.txt"
    data = b"payload\n"
    data_hash = hashlib.sha256(data).hexdigest()
    with pytest.raises(finalizer.PreimageMismatchError):
        finalizer.safe_write_back_file(
            target_path,
            data,
            expected_sha256=data_hash,
            preimage_sha256="b" * 64,
        )
    assert not target_path.exists()


def test_safe_write_back_descriptor_containment_and_symlinks(tmp_path):
    """PR23-R3-SCRIPT-001: Pinned directory traversal rejects symlinks and escapes."""
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    outside_dir = tmp_path / "outside_jail"
    outside_dir.mkdir()
    outside_secret = outside_dir / "secret.txt"
    outside_secret.write_bytes(b"untouchable\n")

    # Symlink directory escape
    symlink_dir = auth_root / "link_to_jail"
    symlink_dir.symlink_to(outside_dir)

    payload = b"escaped content\n"
    payload_hash = hashlib.sha256(payload).hexdigest()

    with pytest.raises(finalizer.PathEscapeError):
        finalizer.safe_write_back_file(
            symlink_dir / "secret.txt",
            payload,
            expected_sha256=payload_hash,
            authorized_root=auth_root,
        )
    # Outside secret was NOT overwritten
    assert outside_secret.read_bytes() == b"untouchable\n"

    # Symlink file escape: target is symlink pointing outside
    symlink_file = auth_root / "symlink_file.txt"
    symlink_file.symlink_to(outside_secret)

    with pytest.raises(finalizer.PathEscapeError):
        finalizer.safe_write_back_file(
            symlink_file,
            payload,
            expected_sha256=payload_hash,
            authorized_root=auth_root,
        )
    assert outside_secret.read_bytes() == b"untouchable\n"


def test_safe_write_back_dotdot_parent_traversal_rejected(tmp_path):
    """PR23-R3-SCRIPT-001: Paths attempting '..' escape must be rejected."""
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    nested = auth_root / "sub"
    nested.mkdir()

    data = b"payload\n"
    h = hashlib.sha256(data).hexdigest()
    with pytest.raises(finalizer.PathEscapeError):
        finalizer.safe_write_back_file(
            nested / ".." / "outside.txt",
            data,
            expected_sha256=h,
            authorized_root=auth_root,
        )


def test_safe_write_back_destination_directory_or_invalid_names(tmp_path):
    """PR23-R3-SCRIPT-001: Destination being an existing directory or invalid leaf raises error."""
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    sub_dir = auth_root / "somedir"
    sub_dir.mkdir()

    data = b"payload\n"
    h = hashlib.sha256(data).hexdigest()

    with pytest.raises(finalizer.HostWriteBackError):
        finalizer.safe_write_back_file(
            sub_dir,
            data,
            expected_sha256=h,
            authorized_root=auth_root,
        )

    with pytest.raises(finalizer.PathEscapeError):
        finalizer.safe_write_back_file(
            auth_root,
            data,
            expected_sha256=h,
            authorized_root=auth_root,
        )


def test_safe_write_back_cooperative_locking_lost_update(tmp_path):
    """PR23-R3-SCRIPT-003: Cooperative per-file locking prevents lost update races."""
    import fcntl
    target_file = tmp_path / "concurrent.txt"
    v1_bytes = b"v1: initial content\n"
    target_file.write_bytes(v1_bytes)
    v1_hash = hashlib.sha256(v1_bytes).hexdigest()

    # Process A acquires cooperative lock
    lock_path = target_file.parent / f".lock-{target_file.name}"
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)

    try:
        # Process A modifies the file while holding lock
        v2_bytes = b"v2: modified by Process A\n"
        target_file.write_bytes(v2_bytes)
        v2_hash = hashlib.sha256(v2_bytes).hexdigest()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    # Process B tries to write back expecting preimage v1
    v3_bytes = b"v3: proposed by Process B\n"
    v3_hash = hashlib.sha256(v3_bytes).hexdigest()

    with pytest.raises(finalizer.PreimageMismatchError):
        finalizer.safe_write_back_file(
            target_file,
            v3_bytes,
            expected_sha256=v3_hash,
            preimage_sha256=v1_hash,
        )
    # Process A's write (v2) is preserved; Process B did not overwrite it
    assert target_file.read_bytes() == v2_bytes


def test_cooperative_writers_serialize_and_prevent_lost_update(tmp_path):
    """PR23-R3-SCRIPT-003: Multi-threaded cooperative writers serialize and fail closed on preimage."""
    target = tmp_path / "shared_concurrency.txt"
    target.write_bytes(b"version 1\n")
    h1 = hashlib.sha256(b"version 1\n").hexdigest()
    h2 = hashlib.sha256(b"version 2 (A)\n").hexdigest()
    h3 = hashlib.sha256(b"version 3 (B)\n").hexdigest()
    barrier = threading.Barrier(2)
    errors = []

    def writer_a():
        barrier.wait()
        try:
            finalizer.safe_write_back_file(
                target, b"version 2 (A)\n", expected_sha256=h2, preimage_sha256=h1
            )
        except Exception as exc:
            errors.append(exc)

    def writer_b():
        barrier.wait()
        try:
            finalizer.safe_write_back_file(
                target, b"version 3 (B)\n", expected_sha256=h3, preimage_sha256=h1
            )
        except Exception as exc:
            errors.append(exc)

    t_a = threading.Thread(target=writer_a)
    t_b = threading.Thread(target=writer_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    # Exactly one writer succeeded and the other encountered PreimageMismatchError
    assert len(errors) == 1
    assert isinstance(errors[0], finalizer.PreimageMismatchError)
    assert target.read_bytes() in [b"version 2 (A)\n", b"version 3 (B)\n"]


def test_finalize_single_target_inline_success(tmp_path):
    """PR23-R3-SCRIPT-004: Inline content write-back sets db_status='ok' and disk_status='written'."""
    content = "def test_inline():\n    return 'success'\n"
    content_bytes = content.encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    tid = str(uuid.uuid4())

    def mock_call(name, **args):
        assert name == "patchdiff_finalize_target"
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 1,
            "filename": "app.py",
            "exported_content": content,
            "content_sha256": content_hash,
            "content_delivery": "inline",
            "content_bytes": len(content_bytes),
        }

    dest_file = tmp_path / "app.py"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        expected_target_version=1,
        client_request_id="inline-req-1",
        destination_path=dest_file,
    )
    assert receipt["status"] == "ok"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert receipt["written_destination"] == str(dest_file)
    assert dest_file.read_bytes() == content_bytes


def test_finalize_single_target_deferred_chunked_success(tmp_path):
    """PR23-R3-SCRIPT-004: Truthful deferred write-back retrieves chunks, verifies full SHA, and writes disk."""
    # Create large byte payload spanning 3 pages (e.g. 600 KiB)
    chunk_size = 262144
    full_bytes = b"X" * 600000
    full_hash = hashlib.sha256(full_bytes).hexdigest()
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())

    calls = []

    def mock_call(name, **args):
        calls.append((name, args))
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "version": 2,
                "filename": "large.bin",
                "exported_content": None,  # Deferred!
                "content_delivery": "deferred",
                "content_sha256": full_hash,
                "content_bytes": len(full_bytes),
            }
        if name == "patchdiff_read_finalized_export":
            assert args["finalization_id"] == fid
            assert args["target_file_id"] == tid
            offset = args["offset"]
            limit = args["limit"]
            chunk = full_bytes[offset : offset + limit]
            has_more = (offset + len(chunk)) < len(full_bytes)
            next_offset = (offset + len(chunk)) if has_more else None
            return {
                "status": "ok",
                "finalization_id": fid,
                "target_file_id": tid,
                "content_base64": base64.b64encode(chunk).decode("ascii"),
                "offset": offset,
                "bytes_read": len(chunk),
                "total_bytes": len(full_bytes),
                "content_sha256": full_hash,
                "has_more": has_more,
                "next_offset": next_offset,
            }
        raise ValueError(f"Unexpected tool call: {name}")

    dest_file = tmp_path / "large.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        expected_target_version=2,
        client_request_id="deferred-req-1",
        destination_path=dest_file,
    )

    # Truthful status separation
    assert receipt["status"] == "ok"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert receipt["written_destination"] == str(dest_file)
    assert dest_file.read_bytes() == full_bytes

    # Assert pagination took 3 calls for 600 KiB with 256 KiB limit
    read_calls = [c for c in calls if c[0] == "patchdiff_read_finalized_export"]
    assert len(read_calls) == 3
    assert read_calls[0][1]["offset"] == 0
    assert read_calls[1][1]["offset"] == chunk_size
    assert read_calls[2][1]["offset"] == chunk_size * 2


def test_finalize_single_target_deferred_read_failure_never_reports_ok(tmp_path):
    """PR23-R3-SCRIPT-004: Deferred export read failure marks disk_status='error' and never returns status='ok'."""
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    dest_file = tmp_path / "deferred_fail.bin"

    def mock_call(name, **args):
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "version": 1,
                "exported_content": None,
                "content_delivery": "deferred",
                "content_sha256": "f" * 64,
                "content_bytes": 1000,
            }
        if name == "patchdiff_read_finalized_export":
            return {
                "status": "error",
                "error": "snapshot_integrity_failure",
                "failure_detail": "Snapshot integrity check failed",
            }
        raise ValueError(name)

    # 1. With raise_on_disk_error=False: returns receipt with disk_status='error'
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="def-fail-1",
        destination_path=dest_file,
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert receipt["written_destination"] is None
    assert "Deferred read failed" in receipt["disk_error"]
    assert not dest_file.exists()

    # 2. With raise_on_disk_error=True: raises HostWriteBackError
    with pytest.raises(finalizer.HostWriteBackError):
        finalizer.finalize_single_target(
            mock_call,
            target_file_id=tid,
            client_request_id="def-fail-2",
            destination_path=dest_file,
            raise_on_disk_error=True,
        )
    assert not dest_file.exists()


def test_finalize_single_target_deferred_integrity_mismatch_fails(tmp_path):
    """PR23-R3-SCRIPT-004: Assembled byte digest mismatch fails before write-back."""
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    dest_file = tmp_path / "tampered.bin"
    corrupt_bytes = b"tampered stream"

    def mock_call(name, **args):
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "exported_content": None,
                "content_delivery": "deferred",
                "content_sha256": "e" * 64,  # Expects 'e'*64
                "content_bytes": len(corrupt_bytes),
            }
        if name == "patchdiff_read_finalized_export":
            return {
                "status": "ok",
                "finalization_id": fid,
                "target_file_id": tid,
                "content_base64": base64.b64encode(corrupt_bytes).decode("ascii"),
                "offset": 0,
                "bytes_read": len(corrupt_bytes),
                "total_bytes": len(corrupt_bytes),
                "has_more": False,
                "next_offset": None,
            }
        raise ValueError(name)

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="integrity-fail",
        destination_path=dest_file,
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert receipt["written_destination"] is None
    assert "Deferred assembled bytes SHA-256" in receipt["disk_error"]
    assert not dest_file.exists()


def test_finalize_single_target_status_truthfulness_no_dest_and_db_failure(tmp_path):
    """PR23-R3-SCRIPT-004: Status truthfulness when no destination is requested or DB finalization fails."""
    tid = str(uuid.uuid4())

    # Case 1: destination_path is None -> disk_status='skipped'
    def mock_ok(name, **args):
        return {"status": "ok", "target_file_id": tid, "version": 1}

    res_no_dest = finalizer.finalize_single_target(
        mock_ok,
        target_file_id=tid,
        client_request_id="no-dest",
        destination_path=None,
    )
    assert res_no_dest["status"] == "ok"
    assert res_no_dest["db_status"] == "ok"
    assert res_no_dest["disk_status"] == "skipped"
    assert res_no_dest["written_destination"] is None

    # Case 2: DB finalization rejected -> disk_status='skipped', status='rejected'
    def mock_rejected(name, **args):
        return {"status": "rejected", "target_file_id": tid, "failure_reason": "version_mismatch"}

    res_rejected = finalizer.finalize_single_target(
        mock_rejected,
        target_file_id=tid,
        client_request_id="db-rejected",
        destination_path=tmp_path / "never_written.txt",
    )
    assert res_rejected["status"] == "rejected"
    assert res_rejected["db_status"] == "rejected"
    assert res_rejected["disk_status"] == "skipped"
    assert res_rejected["written_destination"] is None
    assert not (tmp_path / "never_written.txt").exists()


def test_finalize_single_target_deferred_missing_finalization_id(tmp_path):
    """PR23-R3-SCRIPT-004: Missing finalization_id on deferred delivery reports error."""
    tid = str(uuid.uuid4())
    dest_file = tmp_path / "no_fid.bin"

    def mock_call(name, **args):
        return {
            "status": "ok",
            "target_file_id": tid,
            "version": 1,
            "exported_content": None,
            "content_delivery": "deferred",
            "content_sha256": "f" * 64,
        }

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="missing-fid",
        destination_path=dest_file,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert "missing finalization_id" in receipt["disk_error"]
    assert not dest_file.exists()


