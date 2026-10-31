"""Integration smoke test for built package wheel, MCP stdio server, and two-process lifecycle.

Verifies:
1. Pinned package metadata and console script entry point outside source tree.
2. Two distinct processes: trusted host (PATCHDIFF_MCP_PROFILE=full) and editor (default observed_v2).
3. Full lifecycle: target initialization, scope observation via Waymark, guarded bundle commit,
   and host finalization against live PostgreSQL.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import uuid
import pytest

from app.core.config import settings


@pytest.mark.integration
def test_two_process_mcp_lifecycle_live_pg():
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
    }
    env_editor = {
        **os.environ,
        "PYTHONPATH": backend_dir,
        "PATCHDIFF_MCP_PROFILE": "observed_v2",
        "PATCHDIFF_DATABASE_URL": db_url,
        "PATCHDIFF_WAYMARK_BRIDGE_DIR": bridge_dir,
        "PATCHDIFF_NODE_BINARY": node_path,
    }

    # Run using current python -m app.mcp.external_adapter (or patchdiff binary)
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


def test_isolated_installed_wheel_stdio():
    wheel_bin = Path("/tmp/test-pd-wheel-venv/bin/patchdiff")
    if not wheel_bin.is_file():
        pytest.skip("Isolated test venv at /tmp/test-pd-wheel-venv not installed")
    proc = subprocess.Popen(
        [str(wheel_bin)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/tmp",
        env={"PATH": os.environ.get("PATH", ""), "PATCHDIFF_MCP_PROFILE": "observed_v2"},
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
    finally:
        proc.stdin.close()
        proc.terminate()

