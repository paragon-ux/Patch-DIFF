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

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
import pytest

from app.core.config import settings


from backend.tests.integration.test_installed_wheel_smoke import isolated_wheel_installation


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
assert str(app.__file__).startswith("/tmp/test-pd-wheel-venv"), f"app leaked: {app.__file__}"

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
assert str(bridge_dir).startswith("/tmp/test-pd-wheel-venv"), f"Bridge not in venv: {bridge_dir}"

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


def test_adversarial_wheel_package_completeness():
    """Challenge 4: Verify built wheel contains all runtime assets and zero repository/test artifacts."""
    repo_root = Path(__file__).resolve().parents[3]
    runtime_python = Path(sys.executable)

    with tempfile.TemporaryDirectory() as td:
        dist_dir = Path(td)
        subprocess.run(
            [str(runtime_python), "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist_dir)],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
        wheels = list(dist_dir.glob("*.whl"))
        assert wheels, "No wheel built"
        wheel = wheels[0]

        with zipfile.ZipFile(wheel, "r") as z:
            names = z.namelist()

            # Entry points verification
            entry_points_files = [n for n in names if n.endswith("entry_points.txt")]
            assert entry_points_files, "entry_points.txt missing from wheel"
            ep_content = z.read(entry_points_files[0]).decode("utf-8")
            assert "patchdiff = app.mcp.external_adapter:main" in ep_content

            # Required waymark_bridge files
            expected_bridge_files = [
                "app/waymark_bridge/__init__.py",
                "app/waymark_bridge/bootstrap.py",
                "app/waymark_bridge/discover.mjs",
                "app/waymark_bridge/discovery_core.mjs",
                "app/waymark_bridge/package.json",
                "app/waymark_bridge/package-lock.json",
                "app/waymark_bridge/worker.mjs",
            ]
            for ebf in expected_bridge_files:
                assert ebf in names, f"Required bridge asset {ebf} missing from wheel"

            # Migrations check
            migration_files = [n for n in names if "migrations/versions" in n and n.endswith(".py")]
            assert len(migration_files) >= 7, f"Expected at least 7 migrations, got {len(migration_files)}"
            assert any("0007" in n for n in migration_files), "Migration 0007 missing from wheel"

            # Zero test files or repo leaks
            forbidden = [n for n in names if n.startswith("backend/tests") or n.startswith("tests/") or "conftest" in n]
            assert not forbidden, f"Forbidden test artifacts packaged into wheel: {forbidden}"


def test_adversarial_profile_privilege_separation(isolated_env):
    """Challenge 5: Verify strict profile boundary enforcement outside repository checkout."""
    patchdiff_bin = isolated_env["patchdiff_bin"]
    db_url = settings.database_url
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    # 1. Test observed_v2 profile (5 tools allowed, lifecycle denied)
    env_v2 = {
        **clean_env,
        "PATH": f"{isolated_env['venv_dir'] / 'bin'}:{clean_env.get('PATH', '')}",
        "PATCHDIFF_MCP_PROFILE": "observed_v2",
        "PATCHDIFF_DATABASE_URL": db_url,
    }
    proc_v2 = subprocess.Popen(
        [str(patchdiff_bin)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/tmp",
        env=env_v2,
    )
    try:
        # Check tools/list
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        proc_v2.stdin.write(json.dumps(req) + "\n")
        proc_v2.stdin.flush()
        res = json.loads(proc_v2.stdout.readline())
        tool_names = [t["name"] for t in res["result"]["tools"]]
        assert len(tool_names) == 5, f"observed_v2 must expose exactly 5 tools, got {len(tool_names)}"
        assert "patchdiff_commit_bundle" in tool_names
        assert "patchdiff_read_target" in tool_names
        assert "patchdiff_finalize_target" not in tool_names
        assert "patchdiff_initialize_target" not in tool_names

        # Check calling denied lifecycle tools returns isError: true
        for denied_tool in ["patchdiff_initialize_target", "patchdiff_finalize_target", "patchdiff_read_finalized_export"]:
            req_call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": denied_tool, "arguments": {}}}
            proc_v2.stdin.write(json.dumps(req_call) + "\n")
            proc_v2.stdin.flush()
            res_call = json.loads(proc_v2.stdout.readline())
            assert res_call["result"]["isError"] is True
            assert "Unknown PatchDIFF MCP tool" in res_call["result"]["content"][0]["text"]
    finally:
        proc_v2.stdin.close()
        proc_v2.terminate()

    # 2. Test full profile (24 tools allowed)
    env_full = {
        **clean_env,
        "PATH": f"{isolated_env['venv_dir'] / 'bin'}:{clean_env.get('PATH', '')}",
        "PATCHDIFF_MCP_PROFILE": "full",
        "PATCHDIFF_DATABASE_URL": db_url,
    }
    proc_full = subprocess.Popen(
        [str(patchdiff_bin)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/tmp",
        env=env_full,
    )
    try:
        req = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "patchdiff_initialize_target", "arguments": {}}}
        proc_full.stdin.write(json.dumps(req) + "\n")
        proc_full.stdin.flush()
        res_full = json.loads(proc_full.stdout.readline())
        # Should be an invalid_argument error, NOT tool not found
        assert res_full["result"]["isError"] is True
        assert "missing_argument" in res_full["result"]["content"][0]["text"]
    finally:
        proc_full.stdin.close()
        proc_full.terminate()


def test_adversarial_two_process_lifecycle_and_timing(isolated_env):
    """Challenge 6: Verify full lifecycle, Node discovery, and timing decoupling outside repository checkout."""
    patchdiff_bin = isolated_env["patchdiff_bin"]
    db_url = settings.database_url
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    node_bin_dir = str(Path(isolated_env["node_path"]).parent)

    env_host = {
        **clean_env,
        "PATH": f"{isolated_env['venv_dir'] / 'bin'}:{node_bin_dir}:{clean_env.get('PATH', '')}",
        "PATCHDIFF_MCP_PROFILE": "full",
        "PATCHDIFF_DATABASE_URL": db_url,
        "PATCHDIFF_NODE_BINARY": str(isolated_env["node_path"]),
        "PATCHDIFF_WAYMARK_MODE": os.getenv("PATCHDIFF_WAYMARK_MODE", "resident"),
    }
    env_editor = {
        **clean_env,
        "PATH": f"{isolated_env['venv_dir'] / 'bin'}:{node_bin_dir}:{clean_env.get('PATH', '')}",
        "PATCHDIFF_MCP_PROFILE": "observed_v2",
        "PATCHDIFF_DATABASE_URL": db_url,
        "PATCHDIFF_NODE_BINARY": str(isolated_env["node_path"]),
        "PATCHDIFF_WAYMARK_MODE": os.getenv("PATCHDIFF_WAYMARK_MODE", "resident"),
    }

    host_proc = subprocess.Popen(
        [str(patchdiff_bin)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/tmp",
        env=env_host,
    )
    editor_proc = subprocess.Popen(
        [str(patchdiff_bin)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/tmp",
        env=env_editor,
    )

    def call_tool(p, req_id, name, args):
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
        p.stdin.write(json.dumps(req) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()
        assert line, f"Process closed stdout unexpectedly (stderr: {p.stderr.read() if p.poll() else ''})"
        return json.loads(line)

    try:
        # 1. Host initializes multi-function target
        init_resp = call_tool(
            host_proc,
            1,
            "patchdiff_initialize_target",
            {
                "filename": "adversarial_math.py",
                "content": "def alpha(x):\n    return x + 1\n\ndef beta(x):\n    return x * 2\n",
                "content_type": "text/x-python",
            },
        )
        assert not init_resp["result"]["isError"]
        init_payload = json.loads(init_resp["result"]["content"][0]["text"])
        target_id = init_payload["target_file_id"]
        assert init_payload["version"] == 0

        # 2. Editor discovers scopes via authentic Node bridge
        list_resp = call_tool(editor_proc, 2, "patchdiff_list_scopes", {"target_file_id": target_id})
        if list_resp["result"]["isError"]:
            editor_proc.stdin.close()
            editor_proc.terminate()
            err = editor_proc.stderr.read()
            assert not list_resp["result"]["isError"], f"list_resp: {list_resp} | stderr: {err}"
        list_payload = json.loads(list_resp["result"]["content"][0]["text"])
        assert list_payload["status"] == "candidates"
        names = {c["name"] for c in list_payload["candidates"]}
        assert "alpha" in names and "beta" in names

        # 3. Editor observes scope beta
        obs_resp = call_tool(
            editor_proc,
            3,
            "patchdiff_observe_scopes",
            {"target_file_id": target_id, "selections": [{"symbol_name": "beta"}]},
        )
        assert not obs_resp["result"]["isError"]
        obs_payload = json.loads(obs_resp["result"]["content"][0]["text"])
        obs_id = obs_payload["scopes"][0]["observation_id"]

        # 4. Editor commits guarded bundle
        commit_resp = call_tool(
            editor_proc,
            4,
            "patchdiff_commit_bundle",
            {
                "snapshot": obs_payload["snapshot"],
                "intent": "Update beta return value",
                "client_request_id": f"adv-commit-{uuid.uuid4()}",
                "groups": [
                    {
                        "observation_id": obs_id,
                        "operations": [
                            {
                                "op": "match",
                                "match": "def beta(x):\n    return x * 2",
                                "replace": "def beta(x):\n    return x * 3",
                            }
                        ],
                    }
                ],
            },
        )
        assert not commit_resp["result"]["isError"]
        commit_payload = json.loads(commit_resp["result"]["content"][0]["text"])
        assert commit_payload["status"] == "accepted"
        assert commit_payload["transaction"]["after"]["version"] == 1

        # 5. Host finalizes target and verifies decoupled timing instrumentation
        fin_resp = call_tool(
            host_proc,
            5,
            "patchdiff_finalize_target",
            {
                "target_file_id": target_id,
                "expected_target_version": 1,
                "client_request_id": f"adv-fin-{uuid.uuid4()}",
            },
        )
        assert not fin_resp["result"]["isError"]
        fin_payload = json.loads(fin_resp["result"]["content"][0]["text"])
        assert fin_payload["status"] == "ok"
        assert fin_payload["version"] == 1
        assert "return x * 3" in fin_payload["exported_content"]
        # Timing decoupling verification
        assert fin_payload.get("lock_wait_ms") is not None
        assert fin_payload.get("lock_hold_ms") is not None
        assert fin_payload["lock_wait_ms"] >= 0.0
        assert fin_payload["lock_hold_ms"] >= 0.0

        # 6. Host retrieves export chunk
        read_resp = call_tool(
            host_proc,
            6,
            "patchdiff_read_finalized_export",
            {
                "finalization_id": fin_payload["finalization_id"],
                "target_file_id": target_id,
                "offset": 0,
                "limit": 65536,
            },
        )
        assert not read_resp["result"]["isError"]
        read_payload = json.loads(read_resp["result"]["content"][0]["text"])
        assert read_payload["status"] == "ok"
        assert read_payload["content_sha256"] == fin_payload["content_sha256"]

    finally:
        host_proc.stdin.close()
        host_proc.terminate()
        editor_proc.stdin.close()
        editor_proc.terminate()
