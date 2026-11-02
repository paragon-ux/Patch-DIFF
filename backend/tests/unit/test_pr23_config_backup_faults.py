import json
import os

import pytest

from app.mcp import runtime_cli


def test_foreign_owned_backup_is_rejected_before_replacement(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    target = tmp_path / "mcp.json"
    backup = tmp_path / "mcp.json.bak"
    original = b'{"keep": "original"}\n'
    old_backup = b'{"keep": "older"}\n'
    target.write_bytes(original)
    backup.write_bytes(old_backup)
    target.chmod(0o600)
    backup.chmod(0o600)
    real_stat = os.stat
    checked_foreign_owner = False

    def foreign_backup_stat(path, *args, **kwargs):
        nonlocal checked_foreign_owner
        result = real_stat(path, *args, **kwargs)
        if path == backup.name and kwargs.get("dir_fd") is not None:
            fields = list(result)
            fields[4] = os.getuid() + 1
            checked_foreign_owner = True
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(runtime_cli.os, "stat", foreign_backup_stat)
    with pytest.raises(PermissionError, match="owned by uid"):
        runtime_cli._atomic_write_json_0600(target, {"keep": "updated"}, make_backup=True)

    assert checked_foreign_owner
    assert target.read_bytes() == original
    assert backup.read_bytes() == old_backup
    assert set(p.name for p in tmp_path.iterdir()) == {target.name, backup.name}


@pytest.mark.parametrize("failed_destination", ["mcp.json.bak", "mcp.json"])
def test_backup_or_main_rename_failure_preserves_original_config(tmp_path, monkeypatch, failed_destination):
    tmp_path.chmod(0o700)
    target = tmp_path / "mcp.json"
    backup = tmp_path / "mcp.json.bak"
    original = b'{"keep": "original"}\n'
    old_backup = b'{"keep": "older"}\n'
    target.write_bytes(original)
    backup.write_bytes(old_backup)
    target.chmod(0o600)
    backup.chmod(0o600)
    real_replace = os.replace
    destinations = []

    def fail_selected_rename(source, destination, **kwargs):
        destinations.append(destination)
        if destination == failed_destination:
            raise OSError("injected rename failure")
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(runtime_cli.os, "replace", fail_selected_rename)
    with pytest.raises(OSError, match="injected rename failure"):
        runtime_cli._atomic_write_json_0600(target, {"keep": "updated"}, make_backup=True)

    assert destinations == ([backup.name] if failed_destination == backup.name else [backup.name, target.name])
    assert target.read_bytes() == original
    assert backup.read_bytes() == (old_backup if failed_destination == backup.name else original)
    assert json.loads(target.read_bytes()) == {"keep": "original"}
    assert set(p.name for p in tmp_path.iterdir()) == {target.name, backup.name}
