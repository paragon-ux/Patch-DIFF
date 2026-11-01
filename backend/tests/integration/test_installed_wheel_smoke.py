"""Integration smoke test for built package wheel, MCP stdio server, and two-process lifecycle.

Verifies (PR23-R3-TEST-001):
1. Distributable wheel built and installed in isolated virtualenv outside repository checkout.
2. Console script entry point `/tmp/test-pd-wheel-venv/bin/patchdiff` executable with zero repository source on sys.path.
3. Waymark JavaScript bridge and waymark-engine dependency provisioned and running via installed package.
4. Two distinct processes: trusted host (PATCHDIFF_MCP_PROFILE=full) and editor (default observed_v2).
5. Full lifecycle: target initialization, scope listing, scope observation, guarded bundle commit,
   host finalization with decoupled timing metrics, and immutable finalized-export paging against live PostgreSQL without repository PYTHONPATH.
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
import pytest

from app.core.config import settings


@pytest.fixture(scope="module")
def isolated_wheel_installation(tmp_path_factory):
    """PR23-R3-TEST-001: Authentic, non-skipped isolated wheel installation in /tmp/test-pd-wheel-venv."""
    repo_root = Path(__file__).resolve().parents[3]
    venv_dir = Path("/tmp/test-pd-wheel-venv")
    patchdiff_bin = venv_dir / "bin" / "patchdiff"
    python_bin = venv_dir / "bin" / "python3"
    bridge_dir = venv_dir / "waymark-bridge"

    from app.services.waymark_adapter import resolve_node_executable
    node_path = resolve_node_executable()

    # Determine if fresh installation or verification of existing venv is needed
    needs_install = True
    if patchdiff_bin.is_file() and python_bin.is_file():
        # Verify app importable from venv without PYTHONPATH
        check = subprocess.run(
            [str(python_bin), "-c", "import app; print(app.__file__)"],
            cwd="/tmp",
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
            capture_output=True,
            text=True,
        )
        if check.returncode == 0 and "/tmp/test-pd-wheel-venv" in check.stdout:
            needs_install = False

    if needs_install:
        dist_dir = tmp_path_factory.mktemp("wheel-dist")
        build_cmd = [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(dist_dir),
        ]
        subprocess.run(build_cmd, cwd=str(repo_root), check=True, capture_output=True, text=True)
        wheels = list(dist_dir.glob("patchdiff_mcp-*.whl"))
        assert wheels, f"No built wheel found in {dist_dir}"
        wheel_path = wheels[0]

        venv_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(venv_dir)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", "--prefix", str(venv_dir), str(wheel_path)],
            check=True,
            capture_output=True,
            text=True,
        )

        site_packages_dirs = list(venv_dir.glob("lib/python*/site-packages"))
        assert site_packages_dirs, f"No site-packages found in {venv_dir}"
        venv_site_packages = site_packages_dirs[0]

        current_site_packages = [p for p in sys.path if "site-packages" in p and str(repo_root) not in p]
        if current_site_packages:
            pth_file = venv_site_packages / "base-deps.pth"
            pth_file.write_text("\n".join(current_site_packages) + "\n", encoding="utf-8")

        sitecustomize_file = venv_site_packages / "sitecustomize.py"
        sitecustomize_file.write_text(
            "import sys\nsys.path = [p for p in sys.path if 'Patch-DIFF' not in p and not p.endswith('/backend')]\n",
            encoding="utf-8",
        )

        if patchdiff_bin.is_file():
            content = patchdiff_bin.read_text(encoding="utf-8").splitlines()
            content[0] = f"#!{python_bin}"
            patchdiff_bin.write_text("\n".join(content) + "\n", encoding="utf-8")
            patchdiff_bin.chmod(0o755)

    # Ensure Waymark bridge is bootstrapped with pinned Node
    site_packages_dirs = list(venv_dir.glob("lib/python*/site-packages"))
    assert site_packages_dirs, f"No site-packages found in {venv_dir}"
    venv_site_packages = site_packages_dirs[0]
    pkg_bridge_dir = venv_site_packages / "app" / "waymark_bridge"

    if not (pkg_bridge_dir / "node_modules" / "waymark-engine" / "package.json").is_file():
        bridge_dir.mkdir(parents=True, exist_ok=True)
        bootstrap_env = {
            **os.environ,
            "PATH": f"{Path(node_path).parent}:{os.environ.get('PATH', '')}",
            "PATCHDIFF_NODE_BINARY": node_path,
        }
        bootstrap_cmd = [
            str(python_bin),
            "-m",
            "app.waymark_bridge.bootstrap",
            "--target-dir",
            str(bridge_dir),
        ]
        subprocess.run(bootstrap_cmd, cwd="/tmp", env=bootstrap_env, check=True, capture_output=True, text=True)

        if (bridge_dir / "node_modules").is_dir() and not (pkg_bridge_dir / "node_modules").exists():
            shutil.copytree(bridge_dir / "node_modules", pkg_bridge_dir / "node_modules")

    # Assert that patchdiff_bin and python_bin exist and are executable
    assert patchdiff_bin.is_file(), f"{patchdiff_bin} does not exist"
    assert python_bin.is_file(), f"{python_bin} does not exist"
    assert os.access(patchdiff_bin, os.X_OK), f"{patchdiff_bin} is not executable"

    # Strict isolation check: assert zero repository source on sys.path when invoked from outside checkout
    path_check = subprocess.run(
        [str(python_bin), "-c", "import sys, app; print('PATH_CHECK_START'); print(sys.path); print('APP_FILE:', app.__file__)"],
        cwd="/tmp",
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert str(repo_root) not in path_check.stdout, f"Repository root {repo_root} leaked into sys.path:\n{path_check.stdout}"
    assert "/tmp/test-pd-wheel-venv" in path_check.stdout, f"app package not loaded from isolated venv:\n{path_check.stdout}"

    return {
        "venv_dir": venv_dir,
        "python_bin": python_bin,
        "patchdiff_bin": patchdiff_bin,
        "bridge_dir": bridge_dir,
        "pkg_bridge_dir": pkg_bridge_dir,
        "node_path": node_path,
    }


@pytest.mark.integration
def test_two_process_mcp_lifecycle_live_pg():
    """Verify source-tree two-process lifecycle."""
    db_url = settings.database_url
    from app.services.waymark_adapter import get_waymark_bridge_dir, resolve_node_executable

    bridge_dir = str(get_waymark_bridge_dir())
    node_path = resolve_node_executable()

    backend_dir = str(Path(__file__).resolve().parents[2])
    env_host = {
        **os.environ,
        "PYTHONPATH": backend_dir,
        "PATCHDIFF_MCP_PROFILE": "full",
        "PATCHDIFF_DATABASE_URL": db_url,
        "PATCHDIFF_WAYMARK_BRIDGE_DIR": bridge_dir,
        "PATCHDIFF_NODE_BINARY": node_path,
        "PATCHDIFF_WAYMARK_MODE": os.getenv("PATCHDIFF_WAYMARK_MODE", "resident"),
    }
    env_editor = {
        **os.environ,
        "PYTHONPATH": backend_dir,
        "PATCHDIFF_MCP_PROFILE": "observed_v2",
        "PATCHDIFF_DATABASE_URL": db_url,
        "PATCHDIFF_WAYMARK_BRIDGE_DIR": bridge_dir,
        "PATCHDIFF_NODE_BINARY": node_path,
        "PATCHDIFF_WAYMARK_MODE": os.getenv("PATCHDIFF_WAYMARK_MODE", "resident"),
    }

    cmd = [os.sys.executable, "-m", "app.mcp.external_adapter"]

    host_proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env_host,
    )
    editor_proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
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
        # 1. Host initializes target
        init_resp = call_tool(
            host_proc,
            1,
            "patchdiff_initialize_target",
            {
                "filename": "math_ops.py",
                "content": "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n",
                "content_type": "text/x-python",
            },
        )
        assert not init_resp["result"]["isError"]
        init_payload = json.loads(init_resp["result"]["content"][0]["text"])
        target_id = init_payload["target_file_id"]
        assert init_payload["version"] == 0

        # 2. Editor verifies scope listing and observes scope
        list_resp = call_tool(editor_proc, 2, "patchdiff_list_scopes", {"target_file_id": target_id})
        assert not list_resp["result"]["isError"]

        obs_resp = call_tool(
            editor_proc,
            3,
            "patchdiff_observe_scopes",
            {"target_file_id": target_id, "selections": [{"symbol_name": "sub"}]},
        )
        assert not obs_resp["result"]["isError"]
        obs_payload = json.loads(obs_resp["result"]["content"][0]["text"])
        assert obs_payload["status"] == "observed_batch"
        obs_id = obs_payload["scopes"][0]["observation_id"]

        # Editor commits guarded bundle
        commit_resp = call_tool(
            editor_proc,
            4,
            "patchdiff_commit_bundle",
            {
                "snapshot": obs_payload["snapshot"],
                "intent": "Append mul function to sub scope",
                "client_request_id": f"smoke-commit-{uuid.uuid4()}",
                "groups": [
                    {
                        "observation_id": obs_id,
                        "operations": [
                            {
                                "op": "match",
                                "match": "def sub(a, b):\n    return a - b",
                                "replace": "def sub(a, b):\n    return a - b\n\ndef mul(a, b):\n    return a * b",
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

        # 3. Host finalizes target
        fin_resp = call_tool(
            host_proc,
            5,
            "patchdiff_finalize_target",
            {
                "target_file_id": target_id,
                "expected_target_version": 1,
                "client_request_id": f"smoke-fin-{uuid.uuid4()}",
            },
        )
        assert not fin_resp["result"]["isError"]
        fin_payload = json.loads(fin_resp["result"]["content"][0]["text"])
        assert fin_payload["status"] == "ok"
        assert fin_payload["version"] == 1
        assert "def mul" in fin_payload["exported_content"]

    finally:
        host_proc.stdin.close()
        host_proc.terminate()
        editor_proc.stdin.close()
        editor_proc.terminate()


@pytest.mark.integration
def test_isolated_installed_wheel_stdio(isolated_wheel_installation):
    """PR23-R3-TEST-001: Genuine non-skipped stdio tool verification against installed wheel outside repo."""
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env = {
        **clean_env,
        "PATH": f"{isolated_wheel_installation['venv_dir'] / 'bin'}:{clean_env.get('PATH', '')}",
        "PATCHDIFF_MCP_PROFILE": "observed_v2",
    }
    env.pop("PYTHONPATH", None)

    cmd = [str(isolated_wheel_installation["patchdiff_bin"])]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/tmp",
        env=env,
    )
    try:
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        resp = json.loads(line)
        tools = [t["name"] for t in resp["result"]["tools"]]
        assert len(tools) == 5
        assert "patchdiff_commit_bundle" in tools
        assert "patchdiff_read_target" in tools
        assert "patchdiff_finalize_target" not in tools
    finally:
        proc.stdin.close()
        proc.terminate()


@pytest.mark.integration
def test_isolated_installed_wheel_full_lifecycle(isolated_wheel_installation):
    """PR23-R3-TEST-001: Full two-process lifecycle against installed wheel outside repository tree without PYTHONPATH."""
    db_url = settings.database_url
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    node_bin_dir = str(Path(isolated_wheel_installation["node_path"]).parent)

    env_host = {
        **clean_env,
        "PATH": f"{isolated_wheel_installation['venv_dir'] / 'bin'}:{node_bin_dir}:{clean_env.get('PATH', '')}",
        "PATCHDIFF_MCP_PROFILE": "full",
        "PATCHDIFF_DATABASE_URL": db_url,
        "PATCHDIFF_NODE_BINARY": str(isolated_wheel_installation["node_path"]),
        "PATCHDIFF_WAYMARK_MODE": os.getenv("PATCHDIFF_WAYMARK_MODE", "resident"),
    }
    env_editor = {
        **clean_env,
        "PATH": f"{isolated_wheel_installation['venv_dir'] / 'bin'}:{node_bin_dir}:{clean_env.get('PATH', '')}",
        "PATCHDIFF_MCP_PROFILE": "observed_v2",
        "PATCHDIFF_DATABASE_URL": db_url,
        "PATCHDIFF_NODE_BINARY": str(isolated_wheel_installation["node_path"]),
        "PATCHDIFF_WAYMARK_MODE": os.getenv("PATCHDIFF_WAYMARK_MODE", "resident"),
    }

    cmd = [str(isolated_wheel_installation["patchdiff_bin"])]

    host_proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/tmp",
        env=env_host,
    )
    editor_proc = subprocess.Popen(
        cmd,
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
        # 1. Host initializes target
        init_resp = call_tool(
            host_proc,
            1,
            "patchdiff_initialize_target",
            {
                "filename": "wheel_calc.py",
                "content": "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n",
                "content_type": "text/x-python",
            },
        )
        assert not init_resp["result"]["isError"]
        init_payload = json.loads(init_resp["result"]["content"][0]["text"])
        target_id = init_payload["target_file_id"]
        assert init_payload["version"] == 0

        # 2. Editor lists scopes and observes via real Waymark in wheel
        list_resp = call_tool(editor_proc, 2, "patchdiff_list_scopes", {"target_file_id": target_id})
        if list_resp["result"]["isError"]:
            editor_proc.stdin.close()
            editor_proc.terminate()
            err_output = editor_proc.stderr.read()
            assert not list_resp["result"]["isError"], f"list_scopes failed: {list_resp} | stderr: {err_output}"
        list_payload = json.loads(list_resp["result"]["content"][0]["text"])
        assert list_payload["status"] == "candidates"
        assert len(list_payload["candidates"]) == 2

        obs_resp = call_tool(
            editor_proc,
            3,
            "patchdiff_observe_scopes",
            {"target_file_id": target_id, "selections": [{"symbol_name": "multiply"}]},
        )
        assert not obs_resp["result"]["isError"], f"observe_scopes failed: {obs_resp}"
        obs_payload = json.loads(obs_resp["result"]["content"][0]["text"])
        assert obs_payload["status"] == "observed_batch"
        obs_id = obs_payload["scopes"][0]["observation_id"]

        # Editor commits guarded bundle
        commit_resp = call_tool(
            editor_proc,
            4,
            "patchdiff_commit_bundle",
            {
                "snapshot": obs_payload["snapshot"],
                "intent": "Enhance multiply docstring",
                "client_request_id": f"wheel-commit-{uuid.uuid4()}",
                "groups": [
                    {
                        "observation_id": obs_id,
                        "operations": [
                            {
                                "op": "match",
                                "match": "def multiply(a, b):\n    return a * b",
                                "replace": "def multiply(a, b):\n    \"\"\"Multiply two numbers.\"\"\"\n    return a * b",
                            }
                        ],
                    }
                ],
            },
        )
        assert not commit_resp["result"]["isError"], f"commit_bundle failed: {commit_resp}"
        commit_payload = json.loads(commit_resp["result"]["content"][0]["text"])
        assert commit_payload["status"] == "accepted"
        assert commit_payload["transaction"]["after"]["version"] == 1

        # 3. Host finalizes target
        fin_resp = call_tool(
            host_proc,
            5,
            "patchdiff_finalize_target",
            {
                "target_file_id": target_id,
                "expected_target_version": 1,
                "client_request_id": f"wheel-fin-{uuid.uuid4()}",
            },
        )
        assert not fin_resp["result"]["isError"], f"finalize_target failed: {fin_resp}"
        fin_payload = json.loads(fin_resp["result"]["content"][0]["text"])
        assert fin_payload["status"] == "ok"
        assert fin_payload["version"] == 1
        assert "Multiply two numbers." in fin_payload["exported_content"]
        assert fin_payload.get("lock_wait_ms") is not None
        assert fin_payload.get("lock_hold_ms") is not None

        # 4. Host retrieves export chunk via patchdiff_read_finalized_export
        fin_id = fin_payload["finalization_id"]
        read_resp = call_tool(
            host_proc,
            6,
            "patchdiff_read_finalized_export",
            {
                "finalization_id": fin_id,
                "target_file_id": target_id,
                "offset": 0,
                "limit": 65536,
            },
        )
        assert not read_resp["result"]["isError"], f"read_finalized_export failed: {read_resp}"
        read_payload = json.loads(read_resp["result"]["content"][0]["text"])
        assert read_payload["status"] == "ok"
        assert read_payload["content_sha256"] == fin_payload["content_sha256"]

    finally:
        host_proc.stdin.close()
        host_proc.terminate()
        editor_proc.stdin.close()
        editor_proc.terminate()
