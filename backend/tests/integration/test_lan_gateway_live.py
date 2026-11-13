"""Two independently authenticated network MCP clients sharing live PostgreSQL."""

import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import httpx
import pytest
from sqlalchemy import text

from app.storage.db import engine


VERSION = "2025-11-25"
ACCEPT = "application/json, text/event-stream"


class Peer:
    def __init__(self, client, token):
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT}
        self.request_id = 0
        response = self.rpc("initialize", {
            "protocolVersion": VERSION,
            "capabilities": {},
            "clientInfo": {"name": "patchdiff-network-test", "version": "1"},
        })
        assert response.status_code == 200, response.text
        assert response.json()["result"]["protocolVersion"] == VERSION
        self.headers["MCP-Session-Id"] = response.headers["MCP-Session-Id"]
        self.headers["MCP-Protocol-Version"] = VERSION
        assert self.rpc("notifications/initialized", notification=True).status_code == 202

    def rpc(self, method, params=None, *, notification=False):
        request = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params
        if not notification:
            self.request_id += 1
            request["id"] = self.request_id
        return self.client.post("/mcp", json=request, headers=self.headers)

    def tool(self, name, **arguments):
        response = self.rpc("tools/call", {"name": name, "arguments": arguments})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        if "structuredContent" in result:
            return result["structuredContent"]
        return json.loads(result["content"][0]["text"])


@pytest.mark.skipif(sys.platform != "linux", reason="Managed workspace gateway requires POSIX I/O")
def test_real_http_workers_share_pending_state_and_contend(tmp_path):
    assert os.getenv("PATCHDIFF_DATABASE_URL"), "A migrated live PostgreSQL database is required."
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "fixture.py"
    initial = b"def answer():\n    return 1\n"
    path.write_bytes(initial)

    tokens = [secrets.token_hex(32) for _ in range(3)]
    digests = [hashlib.sha256(token.encode()).hexdigest() for token in tokens]
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({
        "workers": dict(zip(("first", "second"), digests)),
        "trusted": {},
        "operator": digests[2],
    }), encoding="utf-8")
    credentials.chmod(0o600)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log = tmp_path / "gateway.log"
    env = {
        **os.environ,
        "PATCHDIFF_WORKSPACE_ROOT": str(workspace),
        "PATCHDIFF_STRICT_OBSERVATION_MODE": "1",
    }
    with log.open("wb") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.mcp.lan_gateway", "--run-id", "live-test",
             "--credentials-file", str(credentials), "--port", str(port)],
            env=env, stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            with ExitStack() as stack:
                clients = [stack.enter_context(httpx.Client(
                    base_url=url, timeout=15, trust_env=False)) for _ in tokens]
                operator = {"Authorization": f"Bearer {tokens[2]}"}
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        if clients[2].get("/operator/drain", headers=operator).status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(.05)
                else:
                    pytest.fail(f"Gateway failed to start: {log.read_text(errors='replace')}")

                first, second = [Peer(client, token) for client, token in zip(clients[:2], tokens[:2], strict=True)]
                assert first.headers["MCP-Session-Id"] != second.headers["MCP-Session-Id"]
                tools = first.rpc("tools/list").json()["result"]["tools"]
                assert len(tools) == 7 and "patchdiff_replay" not in {tool["name"] for tool in tools}
                probe = {"jsonrpc": "2.0", "id": 50, "method": "tools/list"}
                assert clients[1].post("/mcp", json=probe).status_code == 401
                wrong_session = {**first.headers, "Authorization": second.headers["Authorization"]}
                assert clients[1].post("/mcp", json=probe, headers=wrong_session).status_code == 404

                target = first.tool("patchdiff_initialize_target", filename=path.name,
                                    from_workspace=True)["target_file_id"]
                assert second.tool("patchdiff_initialize_target", filename=path.name,
                                   from_workspace=True)["target_file_id"] == target
                requests = []
                for peer, number in ((first, 2), (second, 3)):
                    bundle = peer.tool("patchdiff_observe_scopes", target_file_id=target,
                                       selections=[{"kind": "function", "symbol_name": "answer"}])
                    requests.append({
                        "snapshot": bundle["snapshot"],
                        "intent": "Update the answer",
                        "client_request_id": f"network-test-{number}",
                        "groups": [{"observation_id": bundle["scopes"][0]["observation_id"],
                                    "operations": [{"op": "match", "match": "return 1",
                                                    "replace": f"return {number}"}]}],
                    })
                barrier = threading.Barrier(2)

                def commit(peer, request):
                    barrier.wait(timeout=5)
                    return peer.tool("patchdiff_commit_bundle", **request)

                with engine.connect() as lock, ThreadPoolExecutor(2) as pool:
                    pid = lock.execute(text("SELECT pg_backend_pid()")).scalar_one()
                    lock.execute(text("SELECT target_file_id FROM cloud_target_files "
                                      "WHERE target_file_id = :target FOR UPDATE"), {"target": target})
                    futures = [pool.submit(commit, peer, request)
                               for peer, request in zip((first, second), requests)]
                    try:
                        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                            deadline = time.monotonic() + 5
                            while time.monotonic() < deadline:
                                waiting = observer.execute(text(
                                    "SELECT count(*) FROM pg_stat_activity "
                                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                                    "AND query LIKE '%cloud_target_files%'"
                                )).scalar_one()
                                if waiting >= 2:
                                    assert observer.execute(text(
                                        "SELECT count(*) FROM pg_stat_activity "
                                        "WHERE :pid = ANY(pg_blocking_pids(pid))"
                                    ), {"pid": pid}).scalar_one() >= 1
                                    break
                                time.sleep(.03)
                            else:
                                pytest.fail("Both network submissions did not reach PostgreSQL lock waits.")
                        assert clients[2].post("/operator/drain", headers=operator).json()["inflight"] == 2
                        assert first.rpc("tools/list").status_code == 503
                    finally:
                        lock.rollback()
                    results = [future.result() for future in futures]
                assert sorted(result["status"] for result in results) == ["accepted", "rejected"]
                winner = next(i for i, result in enumerate(results, 2) if result["status"] == "accepted")
                assert path.read_bytes() == initial
                with engine.connect() as db:
                    row = db.execute(text("SELECT current_content, version FROM cloud_target_files "
                                          "WHERE target_file_id = :target"), {"target": target}).one()
                assert tuple(row) == (f"def answer():\n    return {winner}\n", 1)
                traces = re.findall(r"tool=patchdiff_commit_bundle start_ns=(\d+) end_ns=(\d+)",
                                    log.read_text(encoding="utf-8"))
                assert len(traces) == 2
                starts, ends = zip(*(map(int, interval) for interval in traces))
                assert max(starts) < min(ends)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)