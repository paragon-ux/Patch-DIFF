"""Adversarial stress and verification suite for Milestone M4 (PR23-R3-TEST-001).

Adversarial Challenges:
1. Strict environment isolation: sys.path hygiene, no repo leaks, no backend import.
2. Waymark bridge candidate resolution and zero-fallback verification.
3. Node binary verification and minimum version enforcement (Node >= 22).
4. Wheel packaging completeness: required assets present, test/repo leaks absent.
5. Profile privilege separation outside repository checkout.
6. End-to-end two-process lifecycle and timing metric validation outside repo.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import zipfile
import pytest


from backend.tests.integration.test_installed_wheel_smoke import isolated_wheel_installation, wheel_linux_fixture


@pytest.fixture(scope="module")
def isolated_env(isolated_wheel_installation):
    """PR23-R3-TEST-001: Authentic isolated wheel environment provided by isolated_wheel_installation."""
    return isolated_wheel_installation


def test_adversarial_venv_strict_isolation(isolated_env):
    """Challenge 1: Verify strict isolation from outside repo with zero repository source on sys.path."""
    repo_root = Path(__file__).resolve().parents[3]
    python_bin = isolated_env["python_bin"]

    code = """
import sys, os
from pathlib import Path

# Verify cwd is outside repository
assert os.getcwd() == "/tmp", f"Unexpected cwd: {os.getcwd()}"

# Verify app module is imported strictly from venv
import app
assert str(app.__file__).startswith(sys.prefix), f"app leaked: {app.__file__}"

# Verify backend cannot be imported
try:
    import backend
    print("LEAK_BACKEND")
except ImportError:
    print("BACKEND_ISOLATED")

# Verify sys.path does not contain repo root
repo_leak = [p for p in sys.path if str(Path(p).resolve()).startswith(sys.argv[1])]
if repo_leak:
    print(f"REPO_LEAK: {repo_leak}")
else:
    print("SYS_PATH_CLEAN")
"""
    proc = subprocess.run(
        [str(python_bin), "-c", code, str(repo_root)],
        cwd="/tmp",
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "BACKEND_ISOLATED" in proc.stdout, f"backend package leaked:\n{proc.stdout}"
    assert "SYS_PATH_CLEAN" in proc.stdout, f"Repository root leaked into sys.path:\n{proc.stdout}"
    assert "REPO_LEAK" not in proc.stdout


def test_adversarial_bridge_resolution_failsafe(isolated_env):
    """Challenge 2: Verify Waymark bridge candidate resolution resolves to package resources without repo fallback."""
    python_bin = isolated_env["python_bin"]

    code = """
import os
from pathlib import Path
import app.services.waymark_adapter as wa
from app.services.waymark_adapter import get_waymark_bridge_dir, WaymarkBridgeError

file_path = Path(wa.__file__).resolve()
pkg_candidate = file_path.parent.parent / "waymark_bridge"
repo_candidate = file_path.parents[3] / "integrations" / "waymark"

# Verify Candidate 2 (repo candidate) does not exist in isolated venv
assert not repo_candidate.exists(), f"repo candidate should not exist in venv: {repo_candidate}"

# Verify get_waymark_bridge_dir resolves strictly to pkg_candidate
bridge_dir = get_waymark_bridge_dir()
assert bridge_dir == pkg_candidate, f"Expected {pkg_candidate}, got {bridge_dir}"
assert str(bridge_dir).startswith(__import__("sys").prefix), f"Bridge not in venv: {bridge_dir}"

# Verify explicit non-existent override fails closed with WaymarkBridgeError
try:
    get_waymark_bridge_dir("/nonexistent/custom/bridge")
    print("OVERRIDE_FAILED_TO_RAISE")
except WaymarkBridgeError:
    print("OVERRIDE_RAISED_OK")
"""
    proc = subprocess.run(
        [str(python_bin), "-c", code],
        cwd="/tmp",
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "OVERRIDE_RAISED_OK" in proc.stdout, f"Override check failed:\n{proc.stdout}"


def test_adversarial_node_binary_and_version_enforcement(isolated_env):
    """Challenge 3: Adversarially challenge Node binary verification, version bounds, and error handling."""
    python_bin = isolated_env["python_bin"]

    code = """
import tempfile
from pathlib import Path
from app.waymark_bridge.bootstrap import verify_node_binary, verify_installed_bridge, BRIDGE_FILES

# 1. Test Node version check rejects Node < 22 (e.g. Node 18, Node 20)
for bad_ver in ["v18.19.0", "v20.11.0", "20.0.0"]:
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(f"#!/bin/sh\\necho '{bad_ver}'\\n")
        bad_node = Path(f.name)
    bad_node.chmod(0o755)
    try:
        verify_node_binary(str(bad_node))
        print(f"FAILED_TO_REJECT_{bad_ver}")
    except RuntimeError as exc:
        assert "below minimum requirement" in str(exc)
        print(f"REJECTED_{bad_ver}")
    finally:
        bad_node.unlink()

# 2. Test verify_installed_bridge detects empty directory
with tempfile.TemporaryDirectory() as td:
    try:
        verify_installed_bridge(Path(td))
        print("EMPTY_DIR_FAILED_TO_RAISE")
    except RuntimeError as exc:
        assert "missing required files" in str(exc)
        print("EMPTY_DIR_RAISED_OK")

# 3. Test verify_installed_bridge detects missing waymark-engine
with tempfile.TemporaryDirectory() as td:
    tpath = Path(td)
    for bf in BRIDGE_FILES:
        (tpath / bf).write_text("// dummy")
    try:
        verify_installed_bridge(tpath)
        print("MISSING_MODULE_FAILED_TO_RAISE")
    except RuntimeError as exc:
        assert "waymark-engine is not installed" in str(exc)
        print("MISSING_MODULE_RAISED_OK")

# 4. Test verify_installed_bridge detects unpatched web-tree-sitter
with tempfile.TemporaryDirectory() as td:
    tpath = Path(td)
    for bf in BRIDGE_FILES:
        (tpath / bf).write_text("// dummy")
    (tpath / "node_modules" / "waymark-engine").mkdir(parents=True)
    (tpath / "node_modules" / "waymark-engine" / "package.json").write_text('{"version": "4.1.0"}')
    (tpath / "node_modules" / "web-tree-sitter").mkdir(parents=True)
    (tpath / "node_modules" / "web-tree-sitter" / "tree-sitter.js").write_text('// unpatched code')
    try:
        verify_installed_bridge(tpath)
        print("UNPATCHED_TS_FAILED_TO_RAISE")
    except RuntimeError as exc:
        assert "missing C++ scanner patch" in str(exc)
        print("UNPATCHED_TS_RAISED_OK")
"""
    proc = subprocess.run(
        [str(python_bin), "-c", code],
        cwd="/tmp",
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "REJECTED_v18.19.0" in proc.stdout
    assert "REJECTED_v20.11.0" in proc.stdout
    assert "EMPTY_DIR_RAISED_OK" in proc.stdout
    assert "MISSING_MODULE_RAISED_OK" in proc.stdout
    assert "UNPATCHED_TS_RAISED_OK" in proc.stdout


def test_adversarial_wheel_package_completeness(isolated_env):
    """Challenge 4: Verify built wheel contains all runtime assets and zero repository/test artifacts."""
    with zipfile.ZipFile(isolated_env["wheel_path"], "r") as z:
        names = z.namelist()

        # Entry points verification
        entry_points_files = [n for n in names if n.endswith("entry_points.txt")]
        assert entry_points_files, "entry_points.txt missing from wheel"
        ep_content = z.read(entry_points_files[0]).decode("utf-8")
        assert "patchdiff-mcp = app.mcp.external_adapter:main" in ep_content
        assert "patchdiff = app.mcp.external_adapter:main" in ep_content

        # Required waymark_bridge and mcp/resources files (PR23-R4I-DEP-001)
        expected_bridge_files = [
            "app/mcp/resources/__init__.py",
            "app/mcp/resources/docker-compose.yml",
            "app/waymark_bridge/__init__.py",
            "app/waymark_bridge/bootstrap.py",
            "app/waymark_bridge/discover.mjs",
            "app/waymark_bridge/discovery_core.mjs",
            "app/waymark_bridge/package.json",
            "app/waymark_bridge/package-lock.json",
            "app/waymark_bridge/worker.mjs",
        ]
        for ebf in expected_bridge_files:
            assert ebf in names, f"Required package asset {ebf} missing from wheel"

        # Migrations check
        migration_files = [n for n in names if "migrations/versions" in n and n.endswith(".py")]
        assert len(migration_files) >= 8, f"Expected at least 8 migrations, got {len(migration_files)}"
        assert any("0008" in n for n in migration_files), "Migration 0008 missing from wheel"

        metadata = z.read(next(name for name in names if name.endswith(".dist-info/METADATA"))).decode()
        assert "Name: patchdiff-mcp\n" in metadata and "Version: 0.1.0\n" in metadata

        # Zero test files or repo leaks
        forbidden = [n for n in names if n.startswith("backend/tests") or n.startswith("tests/") or "conftest" in n]
        assert not forbidden, f"Forbidden test artifacts packaged into wheel: {forbidden}"


def test_adversarial_profile_privilege_separation(wheel_linux_fixture):
    assert len({wheel_linux_fixture[k] for k in ("operator_uid","editor_uid","model_uid")}) == 3


def test_adversarial_two_process_lifecycle_and_timing(wheel_linux_fixture):
    assert wheel_linux_fixture["status"] == "PASS"
