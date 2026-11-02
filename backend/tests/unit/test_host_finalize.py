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


def _make_auth_root(tmp_path, name="project"):
    os.chmod(tmp_path, 0o700)
    root = tmp_path / name
    root.mkdir(mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def test_safe_write_back_file_success(tmp_path):
    auth_root = _make_auth_root(tmp_path)
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
    # Permanent lock marker exists and was not unlinked
    lock_marker = target_path.parent / ".lock-app.py"
    assert lock_marker.exists()
    lock_st = os.lstat(lock_marker)
    assert lock_st.st_nlink == 1
    assert (lock_st.st_mode & 0o777) <= 0o600

    # Second write with matched preimage reuses the same lock marker inode
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
    assert os.lstat(lock_marker).st_ino == lock_st.st_ino


def test_safe_write_back_preimage_mismatch_fails_without_overwrite(tmp_path):
    auth_root = _make_auth_root(tmp_path)
    target_path = auth_root / "config.yaml"
    initial_bytes = b"mode: prod\n"
    target_path.write_bytes(initial_bytes)
    os.chmod(target_path, 0o600)
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
    auth_root = _make_auth_root(tmp_path)
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
    auth_root = _make_auth_root(tmp_path)
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

    dest_file = auth_root / "test.py"
    res = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        expected_target_version=1,
        client_request_id="req-single",
        destination_path=dest_file,
        authorized_root=auth_root,
    )
    assert res["status"] == "ok"
    assert res["db_status"] == "ok"
    assert res["disk_status"] == "written"
    assert res["written_destination"] == str(dest_file)
    assert dest_file.read_text(encoding="utf-8") == content


# --- Comprehensive Security & Regression Tests (SCRIPT-001..005) ---


def test_safe_write_back_pre_write_digest_mismatch(tmp_path):
    """PR23-R3-SCRIPT-002: Pre-write digest verification rejects mismatched data before touching disk."""
    auth_root = _make_auth_root(tmp_path)
    target_path = auth_root / "app.py"
    original_bytes = b"def original():\n    return 42\n"
    target_path.write_bytes(original_bytes)
    os.chmod(target_path, 0o600)
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
    auth_root = _make_auth_root(tmp_path)
    target_path = auth_root / "file.txt"
    with pytest.raises(finalizer.HostWriteBackError):
        finalizer.safe_write_back_file(
            target_path, "not bytes", expected_sha256="a" * 64, authorized_root=auth_root
        )  # type: ignore

    with pytest.raises(finalizer.HostWriteBackError):
        finalizer.safe_write_back_file(
            target_path, b"bytes", expected_sha256="short_hash", authorized_root=auth_root
        )

    with pytest.raises(finalizer.HostWriteBackError):
        finalizer.safe_write_back_file(
            target_path, b"bytes", expected_sha256="g" * 64, authorized_root=auth_root
        )


def test_safe_write_back_preimage_mandatory_enforcement(tmp_path):
    """PR23-R3-SCRIPT-005: Preimage is mandatory for existing files unless allow_unconditional_overwrite=True."""
    auth_root = _make_auth_root(tmp_path)
    target_path = auth_root / "locked.py"
    initial_bytes = b"version = 1\n"
    target_path.write_bytes(initial_bytes)
    os.chmod(target_path, 0o600)
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
    auth_root = _make_auth_root(tmp_path)
    target_path = auth_root / "nonexistent.txt"
    data = b"payload\n"
    data_hash = hashlib.sha256(data).hexdigest()
    with pytest.raises(finalizer.PreimageMismatchError):
        finalizer.safe_write_back_file(
            target_path,
            data,
            expected_sha256=data_hash,
            preimage_sha256="b" * 64,
            authorized_root=auth_root,
        )
    assert not target_path.exists()


def test_safe_write_back_descriptor_containment_and_symlinks(tmp_path):
    """PR23-R3-SCRIPT-001: Pinned directory traversal rejects symlinks and escapes."""
    auth_root = _make_auth_root(tmp_path)
    outside_dir = tmp_path / "outside_jail"
    outside_dir.mkdir(mode=0o700)
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
    auth_root = _make_auth_root(tmp_path)
    nested = auth_root / "sub"
    nested.mkdir(mode=0o700)
    os.chmod(nested, 0o700)

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
    auth_root = _make_auth_root(tmp_path)
    sub_dir = auth_root / "somedir"
    sub_dir.mkdir(mode=0o700)
    os.chmod(sub_dir, 0o700)

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
    auth_root = _make_auth_root(tmp_path)
    target_file = auth_root / "concurrent.txt"
    v1_bytes = b"v1: initial content\n"
    target_file.write_bytes(v1_bytes)
    os.chmod(target_file, 0o600)
    v1_hash = hashlib.sha256(v1_bytes).hexdigest()

    # Process A acquires cooperative lock
    lock_path = target_file.parent / f".lock-{target_file.name}"
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(lock_fd, 0o600)
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
            authorized_root=auth_root,
        )
    # Process A's write (v2) is preserved; Process B did not overwrite it
    assert target_file.read_bytes() == v2_bytes


def test_cooperative_writers_serialize_and_prevent_lost_update(tmp_path):
    """PR23-R3-SCRIPT-003: Multi-threaded cooperative writers serialize and fail closed on preimage."""
    auth_root = _make_auth_root(tmp_path)
    target = auth_root / "shared_concurrency.txt"
    target.write_bytes(b"version 1\n")
    os.chmod(target, 0o600)
    h1 = hashlib.sha256(b"version 1\n").hexdigest()
    h2 = hashlib.sha256(b"version 2 (A)\n").hexdigest()
    h3 = hashlib.sha256(b"version 3 (B)\n").hexdigest()
    barrier = threading.Barrier(2)
    errors = []

    def writer_a():
        barrier.wait()
        try:
            finalizer.safe_write_back_file(
                target, b"version 2 (A)\n", expected_sha256=h2, preimage_sha256=h1, authorized_root=auth_root
            )
        except Exception as exc:
            errors.append(exc)

    def writer_b():
        barrier.wait()
        try:
            finalizer.safe_write_back_file(
                target, b"version 3 (B)\n", expected_sha256=h3, preimage_sha256=h1, authorized_root=auth_root
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
    auth_root = _make_auth_root(tmp_path)
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

    dest_file = auth_root / "app.py"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        expected_target_version=1,
        client_request_id="inline-req-1",
        destination_path=dest_file,
        authorized_root=auth_root,
    )
    assert receipt["status"] == "ok"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "written"
    assert receipt["written_destination"] == str(dest_file)
    assert dest_file.read_bytes() == content_bytes


def test_finalize_single_target_deferred_chunked_success(tmp_path):
    """PR23-R3-SCRIPT-004: Truthful deferred write-back retrieves chunks, verifies full SHA, and writes disk."""
    auth_root = _make_auth_root(tmp_path)
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

    dest_file = auth_root / "large.bin"
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        expected_target_version=2,
        client_request_id="deferred-req-1",
        destination_path=dest_file,
        authorized_root=auth_root,
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
    """PR23-R3-SCRIPT-004: Deferred export read failure marks disk_status='rejected' and never returns status='ok'."""
    auth_root = _make_auth_root(tmp_path)
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    dest_file = auth_root / "deferred_fail.bin"

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

    # 1. With raise_on_disk_error=False: returns receipt with disk_status='rejected'
    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="def-fail-1",
        destination_path=dest_file,
        authorized_root=auth_root,
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "rejected"
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
            authorized_root=auth_root,
            raise_on_disk_error=True,
        )
    assert not dest_file.exists()


def test_finalize_single_target_deferred_integrity_mismatch_fails(tmp_path):
    """PR23-R3-SCRIPT-004: Assembled byte digest mismatch fails before write-back."""
    auth_root = _make_auth_root(tmp_path)
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    dest_file = auth_root / "tampered.bin"
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
        authorized_root=auth_root,
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "rejected"
    assert receipt["written_destination"] is None
    assert "Deferred assembled bytes SHA-256" in receipt["disk_error"]
    assert not dest_file.exists()


def test_finalize_single_target_status_truthfulness_no_dest_and_db_failure(tmp_path):
    """PR23-R3-SCRIPT-004: Status truthfulness when no destination is requested or DB finalization fails."""
    auth_root = _make_auth_root(tmp_path)
    tid = str(uuid.uuid4())

    # Case 1: destination_path is None -> disk_status='not_requested'
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
    assert res_no_dest["disk_status"] == "not_requested"
    assert res_no_dest["written_destination"] is None

    # Case 2: DB finalization rejected -> disk_status='rejected', status='rejected'
    def mock_rejected(name, **args):
        return {"status": "rejected", "target_file_id": tid, "failure_reason": "version_mismatch"}

    res_rejected = finalizer.finalize_single_target(
        mock_rejected,
        target_file_id=tid,
        client_request_id="db-rejected",
        destination_path=auth_root / "never_written.txt",
        authorized_root=auth_root,
    )
    assert res_rejected["status"] == "rejected"
    assert res_rejected["db_status"] == "rejected"
    assert res_rejected["disk_status"] == "rejected"
    assert res_rejected["written_destination"] is None
    assert not (auth_root / "never_written.txt").exists()


def test_finalize_single_target_deferred_missing_finalization_id(tmp_path):
    """PR23-R3-SCRIPT-004: Missing finalization_id on deferred delivery reports error."""
    auth_root = _make_auth_root(tmp_path)
    tid = str(uuid.uuid4())
    dest_file = auth_root / "no_fid.bin"

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
        authorized_root=auth_root,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "rejected"
    assert "missing finalization_id" in receipt["disk_error"]
    assert not dest_file.exists()


def test_lock_marker_symlink_and_fifo_rejected(tmp_path):
    """PR23-R4I-SCRIPT-003: Lock marker must reject symlinks and non-regular files (FIFOs)."""
    auth_root = _make_auth_root(tmp_path, "workspace")
    dest = auth_root / "target.txt"
    payload = b"safe content\n"
    expected_sha = hashlib.sha256(payload).hexdigest()

    # 1. Symlink lock marker
    outside_target = tmp_path / "outside_victim.txt"
    outside_target.write_bytes(b"victim")
    lock_file = auth_root / ".lock-target.txt"
    lock_file.symlink_to(outside_target)

    with pytest.raises(finalizer.PathEscapeError, match="symlink"):
        finalizer.safe_write_back_file(
            dest,
            payload,
            expected_sha256=expected_sha,
            authorized_root=auth_root,
        )
    assert outside_target.read_bytes() == b"victim"
    lock_file.unlink()

    # 2. FIFO lock marker
    if hasattr(os, "mkfifo"):
        os.mkfifo(lock_file)
        try:
            with pytest.raises(finalizer.HostWriteBackError, match="not a regular file"):
                finalizer.safe_write_back_file(
                    dest,
                    payload,
                    expected_sha256=expected_sha,
                    authorized_root=auth_root,
                )
        finally:
            lock_file.unlink(missing_ok=True)


def test_lock_marker_inode_replacement_before_replace_rejected(tmp_path):
    """PR23-R4I-SCRIPT-003: Replacing lock marker inode mid-operation fails closed before replace."""
    auth_root = _make_auth_root(tmp_path, "workspace")
    dest = auth_root / "target.txt"
    dest.write_bytes(b"original\n")
    os.chmod(dest, 0o600)
    preimage_sha = hashlib.sha256(b"original\n").hexdigest()
    payload = b"updated\n"
    expected_sha = hashlib.sha256(payload).hexdigest()

    def replace_lock_inode():
        lock_path = auth_root / ".lock-target.txt"
        lock_path.unlink()
        lock_path.write_bytes(b"forged lock inode")
        os.chmod(lock_path, 0o600)

    with pytest.raises(finalizer.HostWriteBackError, match="Lock marker .* identity changed"):
        finalizer.safe_write_back_file(
            dest,
            payload,
            expected_sha256=expected_sha,
            preimage_sha256=preimage_sha,
            authorized_root=auth_root,
            _after_preimage_hook=replace_lock_inode,
        )
    assert dest.read_bytes() == b"original\n"


def test_world_writable_authorized_root_and_subdir_rejected(tmp_path):
    """PR23-R3-SCRIPT-001: World-writable authorized_root or intermediate directory fails closed."""
    os.chmod(tmp_path, 0o700)
    auth_root = tmp_path / "world_writable_root"
    auth_root.mkdir()
    os.chmod(auth_root, 0o777)
    payload = b"hello\n"
    expected_sha = hashlib.sha256(payload).hexdigest()

    try:
        with pytest.raises(finalizer.PathEscapeError, match="world-writable|mode"):
            finalizer.safe_write_back_file(
                auth_root / "file.txt",
                payload,
                expected_sha256=expected_sha,
                authorized_root=auth_root,
            )
    finally:
        os.chmod(auth_root, 0o700)

    subdir = auth_root / "sub"
    subdir.mkdir()
    os.chmod(subdir, 0o777)
    try:
        with pytest.raises(finalizer.PathEscapeError, match="world-writable|group"):
            finalizer.safe_write_back_file(
                subdir / "file.txt",
                payload,
                expected_sha256=expected_sha,
                authorized_root=auth_root,
            )
    finally:
        os.chmod(subdir, 0o700)


def test_parent_directory_swap_after_preflight_rejected(tmp_path):
    """PR23-R3-SCRIPT-001: Swapping or relocating a parent directory after preflight and before replace fails closed."""
    auth_root = _make_auth_root(tmp_path, "auth")
    subdir = auth_root / "nested"
    subdir.mkdir(mode=0o700)
    os.chmod(subdir, 0o700)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(mode=0o700)
    os.chmod(outside_dir, 0o700)

    dest = subdir / "doc.txt"
    payload = b"new content\n"
    expected_sha = hashlib.sha256(payload).hexdigest()

    def swap_parent_with_symlink():
        relocated = tmp_path / "relocated_nested"
        subdir.rename(relocated)
        subdir.symlink_to(outside_dir)

    with pytest.raises(finalizer.PathEscapeError, match="swapped|replaced|parent linkage|symlink"):
        finalizer.safe_write_back_file(
            dest,
            payload,
            expected_sha256=expected_sha,
            authorized_root=auth_root,
            _after_preimage_hook=swap_parent_with_symlink,
        )
    assert not (outside_dir / "doc.txt").exists()


def test_concurrent_external_writer_after_preimage_check_not_overwritten(tmp_path):
    """PR23-R3-SCRIPT-003: External write interleaved after preimage check and before replace is detected and preserved."""
    auth_root = _make_auth_root(tmp_path, "workspace")
    dest = auth_root / "doc.txt"
    initial_bytes = b"version A\n"
    external_bytes = b"version B from concurrent external writer\n"
    finalizer_bytes = b"version C from finalizer\n"

    dest.write_bytes(initial_bytes)
    os.chmod(dest, 0o600)
    preimage_sha = hashlib.sha256(initial_bytes).hexdigest()
    expected_sha = hashlib.sha256(finalizer_bytes).hexdigest()

    def interleave_external_write():
        dest.write_bytes(external_bytes)

    with pytest.raises(finalizer.PreimageMismatchError, match="modified concurrently|content changed"):
        finalizer.safe_write_back_file(
            dest,
            finalizer_bytes,
            expected_sha256=expected_sha,
            preimage_sha256=preimage_sha,
            authorized_root=auth_root,
            _after_preimage_hook=interleave_external_write,
        )
    # External writer's bytes must remain intact!
    assert dest.read_bytes() == external_bytes


def test_two_host_processes_serialize_on_lock_marker(tmp_path):
    """PR23-R4I-SCRIPT-003: Two separate Python processes writing to the same destination serialize via flock."""
    from pathlib import Path
    import subprocess
    import sys

    auth_root = _make_auth_root(tmp_path, "multiproc")
    dest = auth_root / "shared.txt"
    b0 = b"state-0\n"
    b1 = b"state-1\n"
    b2 = b"state-2\n"
    dest.write_bytes(b0)
    os.chmod(dest, 0o600)

    script = (
        "import hashlib, sys; from pathlib import Path; "
        "import examples.host_finalize as hf; "
        "root = Path(sys.argv[1]); dest = root / 'shared.txt'; "
        "pre = sys.argv[2]; data = sys.argv[3].encode('utf-8'); "
        "hf.safe_write_back_file(dest, data, expected_sha256=hashlib.sha256(data).hexdigest(), "
        "preimage_sha256=pre, authorized_root=root)"
    )
    repo_root = str(Path(__file__).resolve().parents[3])
    p1 = subprocess.run(
        [sys.executable, "-c", script, str(auth_root), hashlib.sha256(b0).hexdigest(), b1.decode("utf-8")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert p1.returncode == 0
    assert dest.read_bytes() == b1

    # Second process with stale preimage (b0) must fail with PreimageMismatchError
    p2_stale = subprocess.run(
        [sys.executable, "-c", script, str(auth_root), hashlib.sha256(b0).hexdigest(), b2.decode("utf-8")],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert p2_stale.returncode != 0
    assert "PreimageMismatchError" in p2_stale.stderr
    assert dest.read_bytes() == b1


def test_safe_write_back_requires_explicit_authorized_root_and_rejects_bad_modes(tmp_path):
    """Stage D (PR23-PLAN-ARCH-002, PR23-R3-SCRIPT-001): authorized_root is mandatory and must be 0700 or 0750."""
    auth_root = _make_auth_root(tmp_path, "auth")
    dest = auth_root / "file.txt"
    data = b"hello\n"
    expected_sha = hashlib.sha256(data).hexdigest()

    # Missing authorized_root -> rejected
    with pytest.raises(finalizer.PathEscapeError, match="requires an explicit authorized_root"):
        finalizer.safe_write_back_file(dest, data, expected_sha256=expected_sha, authorized_root=None)

    # 0755 mode on authorized_root -> rejected
    os.chmod(auth_root, 0o755)
    try:
        with pytest.raises(finalizer.PathEscapeError, match="0700 or 0750"):
            finalizer.safe_write_back_file(dest, data, expected_sha256=expected_sha, authorized_root=auth_root)
    finally:
        os.chmod(auth_root, 0o700)

    # 0770 (group-writable) mode on authorized_root -> rejected
    os.chmod(auth_root, 0o770)
    try:
        with pytest.raises(finalizer.PathEscapeError, match="group/world write bits|0700 or 0750"):
            finalizer.safe_write_back_file(dest, data, expected_sha256=expected_sha, authorized_root=auth_root)
    finally:
        os.chmod(auth_root, 0o700)


def test_post_rename_dir_fsync_failure_reports_durability_uncertain_and_reconciles(tmp_path, monkeypatch):
    """Stage D (PR23-R5-SCRIPT-002): Post-rename parent directory fsync failure never claims 'written' and supports reconciliation."""
    auth_root = _make_auth_root(tmp_path, "workspace")
    dest = auth_root / "critical.py"
    content = "def critical():\n    return True\n"
    content_bytes = content.encode("utf-8")
    expected_sha = hashlib.sha256(content_bytes).hexdigest()
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())

    real_fsync = os.fsync
    fail_dir_fsync = True

    def SelectiveFsync(fd):
        st = os.fstat(fd)
        import stat
        if fail_dir_fsync and stat.S_ISDIR(st.st_mode) and dest.exists():
            raise OSError("Simulated directory fsync I/O error after os.replace")
        return real_fsync(fd)

    monkeypatch.setattr(finalizer.os, "fsync", SelectiveFsync)

    calls = []

    def mock_call(name, **args):
        calls.append((name, args))
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "version": 1,
                "filename": "critical.py",
                "exported_content": content,
                "content_sha256": expected_sha,
                "content_bytes": len(content_bytes),
                "content_delivery": "inline",
            }
        if name == "patchdiff_read_finalized_export":
            return {
                "status": "ok",
                "finalization_id": fid,
                "target_file_id": tid,
                "content_base64": base64.b64encode(content_bytes).decode("ascii"),
                "offset": 0,
                "bytes_read": len(content_bytes),
                "total_bytes": len(content_bytes),
                "content_sha256": expected_sha,
                "has_more": False,
                "next_offset": None,
            }
        raise ValueError(name)

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        expected_target_version=1,
        client_request_id="req-uncertain-1",
        destination_path=dest,
        authorized_root=auth_root,
        raise_on_disk_error=False,
    )
    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "durability_uncertain"
    assert receipt["reconciliation_required"] is True
    assert receipt["installed"] is True
    assert receipt["finalization_id"] == fid
    assert receipt["pinned_content_sha256"] == expected_sha
    assert receipt["written_destination"] is None
    assert dest.read_bytes() == content_bytes

    # Now restore directory fsync and reconcile using the same immutable finalization (no extra SAVE!)
    fail_dir_fsync = False
    reconciled = finalizer.reconcile_finalized_write_back(
        mock_call,
        target_file_id=tid,
        finalization_id=fid,
        expected_sha256=expected_sha,
        destination_path=dest,
        authorized_root=auth_root,
    )
    assert reconciled["status"] == "ok"
    assert reconciled["db_status"] == "ok"
    assert reconciled["disk_status"] == "written"
    assert reconciled["reconciliation_required"] is False
    assert reconciled["installed"] is True
    assert reconciled["written_destination"] == str(dest.resolve())
    # No extra patchdiff_finalize_target or patchdiff_save was called during reconciliation
    assert sum(1 for n, _ in calls if n == "patchdiff_finalize_target") == 1
