import hashlib
import os

import pytest

from examples import host_finalize as finalizer


@pytest.mark.parametrize("failure", ["temp_write", "temp_fsync", "replace"])
def test_pre_rename_failure_preserves_destination_and_reports_db_commit(tmp_path, monkeypatch, failure):
    tmp_path.chmod(0o700)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    destination = root / "document.txt"
    original = b"original bytes\n"
    destination.write_bytes(original)
    destination.chmod(0o600)
    original_inode = destination.stat().st_ino
    exported = b"committed export bytes\n"
    calls = []
    injected = False
    real_write = os.write

    def call_tool(name, **args):
        calls.append(name)
        return {"status": "ok", "finalization_id": "pinned-receipt",
                "exported_content": exported.decode(),
                "content_sha256": hashlib.sha256(exported).hexdigest()}

    if failure == "temp_write":
        def fail_partial_write(fd, data):
            nonlocal injected
            if not injected:
                injected = True
                return real_write(fd, data[:3])
            raise OSError("injected temp write failure")
        monkeypatch.setattr(finalizer.os, "write", fail_partial_write)
    elif failure == "temp_fsync":
        def fail_temp_fsync(fd):
            nonlocal injected
            injected = True
            raise OSError("injected temp fsync failure")
        monkeypatch.setattr(finalizer.os, "fsync", fail_temp_fsync)
    else:
        def fail_replace(*args, **kwargs):
            nonlocal injected
            injected = True
            raise OSError("injected replace failure")
        monkeypatch.setattr(finalizer.os, "replace", fail_replace)

    receipt = finalizer.finalize_single_target(
        call_tool, target_file_id="target", client_request_id="request",
        destination_path=destination, authorized_root=root,
        preimage_sha256=hashlib.sha256(original).hexdigest(),
    )

    assert injected, receipt
    assert calls == ["patchdiff_finalize_target"]
    assert receipt["finalization_id"] == "pinned-receipt"
    assert receipt["db_status"] == "ok"
    assert receipt["status"] == "error"
    assert receipt["disk_status"] == "rejected"
    assert receipt["installed"] is False
    assert receipt["reconciliation_required"] is False
    assert receipt["written_destination"] is None
    assert "injected" in receipt["disk_error"]
    assert destination.read_bytes() == original
    assert destination.stat().st_ino == original_inode
    assert not list(root.glob(".tmp-*"))
    assert (root / ".lock-document.txt").is_file()
