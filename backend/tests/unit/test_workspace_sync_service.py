"""Unit and adversarial tests for Goal A native workspace registration and SAVE write-back."""

from __future__ import annotations

import hashlib
import os
import subprocess
import copy
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from jsonschema import Draft202012Validator

from app.core.canonicalization import canonicalize_text
from app.core.config import workspace_root_context
from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.line_endings import source_line_endings
from app.mcp import tools
from app.mcp.external_adapter import ExternalMCPAdapter
from app.services.save_service import save_target
from app.services.target_service import initialize_target_from_workspace
from app.services import workspace_sync_service as workspace_io
from app.services.workspace_sync_service import (
    WorkspaceSyncError,
    read_workspace_source,
    resolve_workspace_file,
    sync_target_file_to_workspace,
)


def _fake_target(filename: str, raw_bytes: bytes, *, version: int = 1, edited_canonical: str | None = None):
    le = source_line_endings(raw_bytes)
    canonical = edited_canonical if edited_canonical is not None else canonicalize_text(raw_bytes)
    return SimpleNamespace(
        target_file_id=uuid.uuid4(),
        filename=filename,
        target_type="text/x-python",
        current_content=canonical,
        current_hash=canonical_sha256(canonical),
        version=version,
        active_editing_cycle_id=uuid.uuid4(),
        latest_accepted_pdcp_log_id=uuid.uuid4(),
        source_line_endings=le,
    )


def _mock_save_session(target):
    old_cycle = SimpleNamespace(
        editing_cycle_id=target.active_editing_cycle_id,
        target_file_id=target.target_file_id,
        cycle_index=0,
        status="active",
        closed_at=None,
        save_snapshot_id=None,
    )
    added = []
    session = MagicMock()
    session.in_transaction.return_value = False
    session.identity_key.return_value = ("CloudTargetFiles", target.target_file_id)
    session.identity_map = {}
    session.no_autoflush.__enter__.return_value = None
    session.no_autoflush.__exit__.return_value = None
    session.execute.return_value.scalar_one_or_none.return_value = target
    session.get.return_value = old_cycle
    session.scalar.return_value = 0

    def _add(obj):
        if getattr(obj, "snapshot_id", None) is None and hasattr(obj, "snapshot_reason"):
            obj.snapshot_id = uuid.uuid4()
        if getattr(obj, "editing_cycle_id", None) is None and hasattr(obj, "cycle_index"):
            obj.editing_cycle_id = uuid.uuid4()
        added.append(obj)

    session.add.side_effect = _add
    return session, old_cycle, added


def test_crlf_and_lf_roundtrip_preserve_exact_line_endings_across_sequential_saves(tmp_path) -> None:
    src = tmp_path / "pkg" / "worker.py"
    src.parent.mkdir(parents=True)
    initial_crlf = b"def run():\r\n    return 1\r\n"
    src.write_bytes(initial_crlf)

    raw, norm_rel = read_workspace_source(tmp_path, r"pkg\worker.py")
    assert raw == initial_crlf
    assert norm_rel == "pkg/worker.py"

    target = _fake_target(
        norm_rel,
        raw,
        version=1,
        edited_canonical="def run():\n    return 2\n",
    )
    receipt1 = sync_target_file_to_workspace(target, workspace_root=tmp_path)
    expected_v1 = b"def run():\r\n    return 2\r\n"
    assert src.read_bytes() == expected_v1
    assert receipt1.content_eol == "crlf"
    assert receipt1.synced_path == "pkg/worker.py"
    assert receipt1.disk_sha256 == hashlib.sha256(expected_v1).hexdigest()

    # Repeating publication preserves bytes; SAVE itself remains non-idempotent
    retry = sync_target_file_to_workspace(target, workspace_root=tmp_path)
    assert retry == receipt1

    # Second edit (v2) tracks updated disk_sha256 smoothly
    target.version = 2
    target.current_content = "def run():\n    return 3\n"
    target.current_hash = canonical_sha256(target.current_content)
    receipt2 = sync_target_file_to_workspace(target, workspace_root=tmp_path)
    expected_v2 = b"def run():\r\n    return 3\r\n"
    assert src.read_bytes() == expected_v2
    assert receipt2.disk_sha256 == hashlib.sha256(expected_v2).hexdigest()


def test_mixed_eol_and_legacy_original_text_format_fail_closed_unless_overridden(tmp_path) -> None:
    mixed_raw = b"a = 1\r\nb = 2\nc = 3\r"
    src = tmp_path / "mixed.py"
    src.write_bytes(mixed_raw)

    target = _fake_target("mixed.py", mixed_raw, version=1, edited_canonical="a = 10\nb = 2\nc = 3\n")
    with pytest.raises(WorkspaceSyncError) as exc_info:
        sync_target_file_to_workspace(target, workspace_root=tmp_path, eol_format="original_eol")
    assert exc_info.value.code == "original_eol_unrecoverable"
    assert src.read_bytes() == mixed_raw

    with pytest.raises(WorkspaceSyncError) as bad_fmt:
        sync_target_file_to_workspace(target, workspace_root=tmp_path, eol_format="original_text")
    assert bad_fmt.value.code == "unsupported_workspace_eol_format"

    # Explicit override to crlf succeeds cleanly
    receipt = sync_target_file_to_workspace(target, workspace_root=tmp_path, eol_format="crlf")
    assert receipt.content_eol == "crlf"
    assert src.read_bytes() == b"a = 10\r\nb = 2\r\nc = 3\r\n"


def test_external_disk_drift_and_deletion_reject_before_db_checkpoint_mutation(tmp_path) -> None:
    src = tmp_path / "service.py"
    initial = b"VALUE = 1\r\n"
    src.write_bytes(initial)
    target = _fake_target("service.py", initial, version=1, edited_canonical="VALUE = 2\n")
    target.source_line_endings["workspace_tracked"] = True

    # Simulate external editor modifying disk outside PatchDIFF
    external_bytes = b"VALUE = 999\r\n"
    src.write_bytes(external_bytes)

    session, old_cycle, added = _mock_save_session(target)
    res = save_target(
        session,
        target_file_id=target.target_file_id,
        expected_target_version=1,
        sync_workspace=True,
        workspace_root=tmp_path,
    )
    assert res.status == "rejected"
    assert res.failure_reason == FailureReason.TARGET_DIVERGED
    assert res.code == "external_disk_drift"
    # Neither disk nor DB snapshot/cycle was mutated
    assert src.read_bytes() == external_bytes
    assert added == []
    assert old_cycle.status == "active"

    # External deletion of tracked file also fails closed
    src.unlink()
    res_del = save_target(
        session,
        target_file_id=target.target_file_id,
        expected_target_version=1,
        sync_workspace=True,
        workspace_root=tmp_path,
    )
    assert res_del.status == "rejected"
    assert res_del.code == "external_disk_drift"
    assert not src.exists()


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "",
        "../outside.py",
        "sub/../../outside.py",
        "/etc/passwd",
        r"\Windows\win.ini",
        "C:relative.py",
        r"C:\abs\file.py",
        r"\\server\share\file.py",
        "file.py:ads_stream",
        "CON",
        "nul.py",
        "COM1.txt",
        "com\u00b9.txt",
        "dir/trailing.",
        "dir/trailing ",
        "nul\x00byte.py",
    ],
)
def test_unsafe_paths_ads_and_reserved_names_fail_closed(tmp_path, unsafe_path: str) -> None:
    with pytest.raises(WorkspaceSyncError) as exc_info:
        resolve_workspace_file(tmp_path, unsafe_path)
    assert exc_info.value.reason == FailureReason.CONTEXT_INVALID


@pytest.mark.skipif(os.name != "posix", reason="Managed workspace IO requires POSIX handles and flock")
def test_symlinked_ancestors_and_leaves_fail_closed(tmp_path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.py").write_bytes(b"OUTSIDE\n")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (root / "leaf.py").symlink_to(outside / "secret.py")
    for filename in ("linked/secret.py", "leaf.py"):
        with pytest.raises(WorkspaceSyncError):
            read_workspace_source(root, filename)
    assert (outside / "secret.py").read_bytes() == b"OUTSIDE\n"


def test_encoding_validation_rejects_nul_and_invalid_utf8(tmp_path) -> None:
    (tmp_path / "has_nul.py").write_bytes(b"x = 1\x00\n")
    (tmp_path / "bad.py").write_bytes(b"\xff\xfe\xfd")

    with pytest.raises(WorkspaceSyncError) as nul_err:
        read_workspace_source(tmp_path, "has_nul.py")
    assert nul_err.value.reason == FailureReason.TARGET_ENCODING_INVALID

    with pytest.raises(WorkspaceSyncError) as utf_err:
        read_workspace_source(tmp_path, "bad.py")
    assert utf_err.value.reason == FailureReason.TARGET_ENCODING_INVALID


def test_mcp_from_workspace_and_sync_save_emit_compact_receipts_without_full_text(tmp_path) -> None:
    # Schema & tool-count invariants remain intact across profiles
    full_tools = {t["name"]: t for t in ExternalMCPAdapter(profile="full").list_tools()}
    assert len(full_tools) == 17
    Draft202012Validator.check_schema(full_tools["patchdiff_initialize_target"]["inputSchema"])
    Draft202012Validator.check_schema(full_tools["patchdiff_save"]["inputSchema"])

    ws_file = tmp_path / "src" / "app.py"
    ws_file.parent.mkdir(parents=True)
    ws_file.write_bytes(b"PORT = 8000\r\n")

    captured: dict = {}

    def fake_init_session():
        ctx = MagicMock()
        session = MagicMock()
        session.in_transaction.return_value = True

        def _add_all(objs):
            captured["target"] = objs[0]

        session.add_all.side_effect = _add_all
        ctx.__enter__.return_value = session
        ctx.__exit__.return_value = False
        return ctx

    with workspace_root_context(tmp_path, sync_on_save=True):
        with patch.object(tools, "SessionLocal", side_effect=fake_init_session):
            init_payload = tools.patchdiff_initialize_target(
                filename="src/app.py",
                content_type="text/x-python",
                from_workspace=True,
            )
        assert init_payload["status"] == "ok"
        assert init_payload["filename"] == "src/app.py"
        assert "content" not in init_payload
        assert "current_content" not in init_payload
        assert init_payload["source_line_endings"]["style"] == "crlf"
        assert init_payload["source_line_endings"]["workspace_tracked"] is True

        target = captured["target"]
        target.version = 1
        target.current_content = "PORT = 9090\n"
        target.current_hash = canonical_sha256(target.current_content)

        save_session, _, _ = _mock_save_session(target)
        save_ctx = MagicMock()
        save_ctx.__enter__.return_value = save_session
        save_ctx.__exit__.return_value = False

        with patch.object(tools, "SessionLocal", return_value=save_ctx):
            save_payload = tools.patchdiff_save(
                target_file_id=str(target.target_file_id),
                expected_target_version=1,
            )

    assert save_payload["status"] == "saved"
    assert "content" not in save_payload
    assert "export" not in save_payload
    assert save_payload["workspace_sync"] == {
        "synced_path": "src/app.py",
        "disk_sha256": hashlib.sha256(b"PORT = 9090\r\n").hexdigest(),
        "bytes_written": len(b"PORT = 9090\r\n"),
        "content_eol": "crlf",
        "publication": "installed",
        "durability": "confirmed",
    }
    assert ws_file.read_bytes() == b"PORT = 9090\r\n"


def _publication_fixture(tmp_path):
    source = tmp_path / "target.py"
    source.write_bytes(b"VALUE = 1\n")
    target = _fake_target("target.py", source.read_bytes(), edited_canonical="VALUE = 2\n")
    return source, target


def test_workspace_save_rejects_caller_owned_transaction_before_io(tmp_path):
    source, target = _publication_fixture(tmp_path)
    session, _, _ = _mock_save_session(target)
    session.in_transaction.return_value = True
    result = save_target(session, target_file_id=target.target_file_id, workspace_root=tmp_path)
    assert result.status == "rejected"
    assert result.code == "workspace_requires_owned_transaction"
    assert source.read_bytes() == b"VALUE = 1\n"
    session.execute.assert_not_called()


@pytest.mark.parametrize("phase", ["flush", "commit"])
def test_workspace_save_reports_publication_when_checkpoint_fails(tmp_path, phase):
    source, target = _publication_fixture(tmp_path)
    session, _, _ = _mock_save_session(target)
    if phase == "flush":
        session.flush.side_effect = RuntimeError("injected flush failure")
    else:
        session.begin.return_value.__exit__.side_effect = RuntimeError("injected commit acknowledgement failure")
    result = save_target(session, target_file_id=target.target_file_id, workspace_root=tmp_path)
    assert result.status == "partial"
    assert result.code == "workspace_checkpoint_uncertain"
    assert result.snapshot_id is None and result.new_editing_cycle_id is None
    assert result.workspace_sync["publication"] == "installed"
    assert result.workspace_sync["disk_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.workspace_sync["durability"] == "confirmed"
    assert source.read_bytes() == b"VALUE = 2\n"
    assert "do not retry" in result.failure_detail


def test_directory_fsync_failure_is_partial_with_installed_receipt(tmp_path):
    source, target = _publication_fixture(tmp_path)
    session, _, added = _mock_save_session(target)
    fsync = os.fsync
    count = 0
    def fail_directory(fd):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("directory fsync failed")
        return fsync(fd)
    with patch.object(workspace_io.os, "fsync", side_effect=fail_directory):
        result = save_target(session, target_file_id=target.target_file_id, workspace_root=tmp_path)
    assert result.status == "partial"
    assert result.code == "workspace_durability_uncertain"
    assert result.workspace_sync["publication"] == "installed"
    assert result.workspace_sync["durability"] == "uncertain"
    assert source.read_bytes() == b"VALUE = 2\n"
    assert added == []


def test_two_targets_cannot_publish_concurrently_to_one_workspace(tmp_path):
    source, first = _publication_fixture(tmp_path)
    second = copy.deepcopy(first)
    second.target_file_id = uuid.uuid4()
    second.current_content = "VALUE = 3\n"
    entered, release = threading.Event(), threading.Event()
    fsync = os.fsync
    def pause_staging(fd):
        entered.set()
        assert release.wait(5)
        return fsync(fd)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with patch.object(workspace_io.os, "fsync", side_effect=pause_staging):
            pending = executor.submit(sync_target_file_to_workspace, first, workspace_root=tmp_path)
            assert entered.wait(5)
            try:
                with pytest.raises(WorkspaceSyncError) as error:
                    sync_target_file_to_workspace(second, workspace_root=tmp_path)
                assert error.value.code == "workspace_busy"
            finally:
                release.set()
            assert pending.result(timeout=5).disk_sha256 == hashlib.sha256(b"VALUE = 2\n").hexdigest()
    with pytest.raises(WorkspaceSyncError) as stale:
        sync_target_file_to_workspace(second, workspace_root=tmp_path)
    assert stale.value.code == "external_disk_drift"
    assert source.read_bytes() == b"VALUE = 2\n"


def test_overlapping_roots_share_the_physical_destination_lease(tmp_path):
    subroot = tmp_path / "sub"
    subroot.mkdir()
    source, first = _publication_fixture(subroot)
    first.filename = "sub/target.py"
    second = copy.deepcopy(first)
    second.target_file_id = uuid.uuid4()
    second.filename = "target.py"
    second.current_content = "VALUE = 3\n"
    for target, root in ((first, tmp_path), (second, subroot)):
        st = root.stat()
        target.source_line_endings.update(workspace_tracked=True, workspace_root_identity=f"{st.st_dev}:{st.st_ino}")
    entered, release = threading.Event(), threading.Event()
    fsync = os.fsync
    def pause_staging(fd):
        entered.set()
        assert release.wait(5)
        return fsync(fd)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with patch.object(workspace_io.os, "fsync", side_effect=pause_staging):
            pending = executor.submit(sync_target_file_to_workspace, first, workspace_root=tmp_path)
            assert entered.wait(5)
            try:
                with pytest.raises(WorkspaceSyncError) as error:
                    sync_target_file_to_workspace(second, workspace_root=subroot)
                assert error.value.code == "workspace_busy"
            finally:
                release.set()
            pending.result(timeout=5)
    assert source.read_bytes() == b"VALUE = 2\n"
    with pytest.raises(WorkspaceSyncError) as stale:
        sync_target_file_to_workspace(second, workspace_root=subroot)
    assert stale.value.code == "external_disk_drift"


def test_post_install_directory_close_failure_retains_published_receipt(tmp_path):
    source, target = _publication_fixture(tmp_path)
    session, _, added = _mock_save_session(target)
    real_close = os.close
    failed = False
    def fail_after_close(fd):
        nonlocal failed
        real_close(fd)
        if not failed:
            failed = True
            raise OSError("directory close reported an error")
    with patch.object(workspace_io.os, "close", side_effect=fail_after_close):
        result = save_target(session, target_file_id=target.target_file_id, workspace_root=tmp_path)
    assert result.status == "partial"
    assert result.code == "workspace_post_install_error"
    assert result.workspace_sync["publication"] == "installed"
    assert result.workspace_sync["durability"] == "confirmed"
    assert source.read_bytes() == b"VALUE = 2\n"
    assert added == []


def test_unmanaged_drift_during_staging_preserves_external_bytes(tmp_path):
    source, target = _publication_fixture(tmp_path)
    fsync = os.fsync
    def external_edit(fd):
        source.write_bytes(b"EXTERNAL = 99\n")
        return fsync(fd)
    with patch.object(workspace_io.os, "fsync", side_effect=external_edit):
        with pytest.raises(WorkspaceSyncError) as error:
            sync_target_file_to_workspace(target, workspace_root=tmp_path)
    assert error.value.code == "external_disk_drift"
    assert source.read_bytes() == b"EXTERNAL = 99\n"
    assert list(tmp_path.glob(".patchdiff-*.tmp")) == []


def test_ancestor_replacement_cannot_redirect_opened_directory_handle(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    parent = root / "sub"
    parent.mkdir(parents=True)
    outside.mkdir()
    (parent / "file.py").write_bytes(b"INSIDE\n")
    (outside / "file.py").write_bytes(b"OUTSIDE\n")
    real_open = os.open
    replaced = False
    def swap_before_leaf(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == "file.py" and not replaced:
            replaced = True
            parent.rename(root / "held")
            parent.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)
    with patch.object(workspace_io.os, "open", side_effect=swap_before_leaf):
        raw, _ = read_workspace_source(root, "sub/file.py")
    assert raw == b"INSIDE\n"
    assert (outside / "file.py").read_bytes() == b"OUTSIDE\n"


def test_workspace_binding_rejects_another_root_even_with_identical_bytes(tmp_path):
    root, other = tmp_path / "root", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    source, target = _publication_fixture(root)
    sync_target_file_to_workspace(target, workspace_root=root)
    (other / "target.py").write_bytes(source.read_bytes())
    target.current_content = "VALUE = 3\n"
    with pytest.raises(WorkspaceSyncError) as error:
        sync_target_file_to_workspace(target, workspace_root=other)
    assert error.value.code == "workspace_binding_mismatch"
    assert source.read_bytes() == (other / "target.py").read_bytes() == b"VALUE = 2\n"


def test_unsupported_platform_rejects_before_file_io(tmp_path):
    source, target = _publication_fixture(tmp_path)
    with patch.object(workspace_io.os, "name", "nt"):
        with pytest.raises(WorkspaceSyncError) as error:
            sync_target_file_to_workspace(target, workspace_root=tmp_path)
    assert error.value.code == "workspace_platform_unsupported"
    assert source.read_bytes() == b"VALUE = 1\n"


def test_staging_failure_keeps_file_and_checkpoint_unchanged(tmp_path):
    source, target = _publication_fixture(tmp_path)
    session, _, added = _mock_save_session(target)
    with patch.object(workspace_io.os, "fsync", side_effect=OSError("staging fsync failed")):
        result = save_target(session, target_file_id=target.target_file_id, workspace_root=tmp_path)
    assert result.status == "rejected"
    assert result.workspace_sync is None
    assert source.read_bytes() == b"VALUE = 1\n"
    assert added == []
    assert list(tmp_path.glob(".patchdiff-*.tmp")) == []


def test_workspace_lease_also_excludes_another_process(tmp_path):
    source, target = _publication_fixture(tmp_path)
    script = "import os,fcntl,sys; fd=os.open(sys.argv[1],os.O_RDONLY); fcntl.flock(fd,fcntl.LOCK_EX); print('owned',flush=True); sys.stdin.read(1); os.close(fd)"
    process = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "owned"
        with pytest.raises(WorkspaceSyncError) as error:
            sync_target_file_to_workspace(target, workspace_root=tmp_path)
        assert error.value.code == "workspace_busy"
        assert source.read_bytes() == b"VALUE = 1\n"
    finally:
        process.communicate("x", timeout=5)
    assert process.returncode == 0


@pytest.mark.parametrize("arguments,valid", [
    ({"filename": "a.py", "content": "x"}, True),
    ({"filename": "a.py"}, False),
    ({"filename": "a.py", "content": None}, False),
    ({"filename": "a.py", "from_workspace": True}, True),
    ({"filename": "a.py", "from_workspace": True, "content": None}, True),
    ({"filename": "a.py", "from_workspace": True, "content": "x"}, False),
    ({"filename": "a.py", "from_workspace": None}, False),
])
def test_initialization_schema_represents_inline_and_workspace_alternatives(arguments, valid):
    tool = next(t for t in ExternalMCPAdapter(profile="full").list_tools() if t["name"] == "patchdiff_initialize_target")
    assert Draft202012Validator(tool["inputSchema"]).is_valid(arguments) is valid
