"""Unit tests for Waymark bridge resolution and dynamic configuration."""

import os
from pathlib import Path
import pytest

from app.services.waymark_adapter import (
    get_waymark_bridge_dir,
    WaymarkBridgeError,
    REQUIRED_BRIDGE_FILES,
)
from app.waymark_bridge.bootstrap import (
    verify_installed_bridge,
    get_default_bridge_cache_dir,
    get_packaged_bridge_dir,
)


def test_bridge_packaged_files_exist():
    pkg_dir = get_packaged_bridge_dir()
    assert pkg_dir.is_dir()
    for fname in REQUIRED_BRIDGE_FILES:
        assert (pkg_dir / fname).is_file(), f"Missing packaged bridge file: {fname}"


def test_bridge_resolution_default_finds_checkout_or_package():
    # In developer workspace, should find valid bridge directory
    bridge_dir = get_waymark_bridge_dir()
    assert bridge_dir.is_dir()
    for fname in REQUIRED_BRIDGE_FILES:
        assert (bridge_dir / fname).is_file()


def test_bridge_resolution_runtime_override_dynamically(monkeypatch, tmp_path):
    # Create valid dummy bridge in tmp_path
    custom_bridge = tmp_path / "custom_bridge"
    custom_bridge.mkdir()
    for fname in REQUIRED_BRIDGE_FILES:
        (custom_bridge / fname).write_text("// dummy", encoding="utf-8")

    # Override env var at runtime
    monkeypatch.setenv("PATCHDIFF_WAYMARK_BRIDGE_DIR", str(custom_bridge))
    resolved = get_waymark_bridge_dir()
    assert resolved == custom_bridge.resolve()

    # Pass explicit argument override
    custom_bridge_2 = tmp_path / "custom_bridge_2"
    custom_bridge_2.mkdir()
    for fname in REQUIRED_BRIDGE_FILES:
        (custom_bridge_2 / fname).write_text("// dummy 2", encoding="utf-8")

    resolved_arg = get_waymark_bridge_dir(custom_bridge_2)
    assert resolved_arg == custom_bridge_2.resolve()


def test_bridge_resolution_invalid_override_fails_closed(monkeypatch, tmp_path):
    # Non-existent path fails closed
    non_existent = tmp_path / "does_not_exist"
    monkeypatch.setenv("PATCHDIFF_WAYMARK_BRIDGE_DIR", str(non_existent))
    with pytest.raises(WaymarkBridgeError) as exc_info:
        get_waymark_bridge_dir()
    assert "does not exist or is not a directory" in str(exc_info.value)

    # Incomplete directory fails closed (missing required files)
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "discover.mjs").write_text("// incomplete", encoding="utf-8")
    monkeypatch.setenv("PATCHDIFF_WAYMARK_BRIDGE_DIR", str(incomplete))
    with pytest.raises(WaymarkBridgeError) as exc_info:
        get_waymark_bridge_dir()
    assert "missing required files" in str(exc_info.value)


def test_bridge_resolution_relative_override_canonicalized(monkeypatch, tmp_path):
    custom_bridge = tmp_path / "relative_bridge"
    custom_bridge.mkdir()
    for fname in REQUIRED_BRIDGE_FILES:
        (custom_bridge / fname).write_text("// dummy", encoding="utf-8")

    # Set relative path from current directory
    rel_path = os.path.relpath(custom_bridge, os.getcwd())
    monkeypatch.setenv("PATCHDIFF_WAYMARK_BRIDGE_DIR", rel_path)
    resolved = get_waymark_bridge_dir()
    assert resolved == custom_bridge.resolve()
    assert resolved.is_absolute()
