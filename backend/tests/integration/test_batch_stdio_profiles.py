"""Real JSON-RPC subprocess profile enforcement and committed-response-loss recovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.mcp.external_adapter import MCP_PROFILES
from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyPdcpLogs
from backend.tests.integration.test_observed_batch import initialized, request, state

ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def peer(profile):
    process = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(ROOT / "backend"), "PATCHDIFF_DATABASE_URL": settings.database_url,
             "PATCHDIFF_MCP_PROFILE": profile})
    sequence = 0
    def send(method, params=None, *, read=True):
        nonlocal sequence
        sequence += 1
        message = {"jsonrpc": "2.0", "id": sequence, "method": method, "params": params or {}}
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        process.stdin.flush()
        if not read: return
        raw = process.stdout.readline()
        assert raw, process.stderr.read().decode("utf-8")
        response = json.loads(raw)
        assert response["id"] == sequence and "result" in response, response
        return response["result"]
    try:
        send("initialize")
        yield process, send
    finally:
        process.stdin.close()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()


@pytest.mark.parametrize("profile,count", [("editor", 7), ("unobserved", 5), ("unobserved_editor", 3), ("hybrid_editor", 1), ("observed", 6), ("observed_editor", 4), ("full", 22)])
def test_real_stdio_profiles_advertise_and_enforce_same_tools(profile, count):
    with peer(profile) as (_, rpc):
        listed = rpc("tools/list")["tools"]
        assert len(listed) == count and {item["name"] for item in listed} == MCP_PROFILES[profile]
        for name in ("patchdiff_initialize_target", "patchdiff_submit_pdcp", "patchdiff_get_pdcp_log"):
            args = {"target_file_id": str(uuid.uuid4())}
            if name == "patchdiff_initialize_target": args = {"filename": "profile.txt", "content": "alpha", "content_type": "text/plain"}
            if name == "patchdiff_submit_pdcp": args["pdcp_content"] = "PDCP invalid"
            result = rpc("tools/call", {"name": name, "arguments": args})
            assert bool(result.get("isError")) == (profile != "full")
        override = rpc("tools/call", {"name": "patchdiff_read_target", "arguments": {"target_file_id": "x", "profile": "full"}})
        assert override["isError"]



def test_delegated_editor_stdio_denies_lifecycle_and_every_unadvertised_route():
    allowed = {"patchdiff_read_target", "patchdiff_find_occurrences",
               "patchdiff_observe_scope", "patchdiff_submit_observed_operations"}
    with peer("observed_editor") as (_, rpc):
        assert {tool["name"] for tool in rpc("tools/list")["tools"]} == allowed
        for name in set(registry.names()) - allowed:
            result = rpc("tools/call", {"name": name, "arguments": {}, "profile": "full"})
            assert result["isError"]
            assert "Unknown PatchDIFF MCP tool" in result["content"][0]["text"]
        override = rpc("tools/call", {"name": "patchdiff_observe_scope",
            "arguments": {"target_file_id": "target", "profile": "full"}})
        assert override["isError"]
        assert json.loads(override["content"][0]["text"])["code"] == "unknown_argument"
        assert {tool["name"] for tool in rpc("tools/list")["tools"]} == allowed

def test_unknown_profile_fails_startup_without_advertisement():
    completed = subprocess.run([sys.executable, "-m", "app.mcp.external_adapter"], cwd=ROOT,
        input=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n', capture_output=True, timeout=30,
        env={**os.environ, "PYTHONPATH": str(ROOT / "backend"), "PATCHDIFF_MCP_PROFILE": "unknown"})
    assert completed.returncode != 0 and completed.stdout == b"" and b"Unknown PATCHDIFF_MCP_PROFILE" in completed.stderr


def test_real_postgres_stdio_response_lost_after_commit_recovers_once():
    target, selectors = initialized()
    with peer("observed") as (process, rpc):
        observed = rpc("tools/call", {"name": "patchdiff_observe_scope", "arguments": {
            "target_file_id": target["target_file_id"], "selections": selectors}})
        bundle = json.loads(observed["content"][0]["text"])
        args = request(target, bundle)
        # The client intentionally never receives this tools/call response. Observe the actual
        # committed database row, then drop this transport and recover through a new process.
        rpc("tools/call", {"name": "patchdiff_submit_observed_operations", "arguments": args}, read=False)
        log_id = None
        for _ in range(200):
            with SessionLocal() as session:
                log = session.scalar(select(AppendOnlyPdcpLogs).where(
                    AppendOnlyPdcpLogs.target_file_id == uuid.UUID(target["target_file_id"]),
                    AppendOnlyPdcpLogs.client_request_id == args["client_request_id"]))
                if log is not None:
                    assert log.status == "accepted"
                    log_id = str(log.pdcp_log_id)
                    break
            time.sleep(.025)
        assert log_id is not None
        process.terminate()
        process.wait(timeout=10)
    with peer("observed") as (_, rpc):
        reply = rpc("tools/call", {"name": "patchdiff_submit_observed_operations", "arguments": args})
        recovered = json.loads(reply["content"][0]["text"])
        assert recovered["status"] == "accepted" and recovered["deduplicated"] and recovered["pdcp_log_id"] == log_id
        assert recovered["before_version"] == 0 and recovered["after_version"] == 1 and recovered["group_count"] == 2
        for name in ("patchdiff_save", "patchdiff_replay"):
            result = json.loads(rpc("tools/call", {"name": name, "arguments": {"target_file_id": target["target_file_id"]}})["content"][0]["text"])
            assert result["status"] in {"saved", "success"}
    assert state(target)[1] == 1 and len(state(target)[2]) == 1 and len(state(target)[3]) == 4


def test_observed_selector_admission_contract_over_real_stdio():
    from jsonschema import Draft202012Validator

    target = registry.call("patchdiff_initialize_target", filename="stdio-selector.py",
                           content="def example():\n    return 1\n", content_type="text/x-python")
    with peer("observed") as (_, rpc):
        schema = next(tool["inputSchema"] for tool in rpc("tools/list")["tools"]
                      if tool["name"] == "patchdiff_observe_scope")
        validator = Draft202012Validator(schema)
        base = {"target_file_id": target["target_file_id"]}
        for field in ("query", "symbol_name", "kind"):
            assert not validator.is_valid({**base, field: ""})
            assert validator.is_valid({**base, field: None})
            result = rpc("tools/call", {"name": "patchdiff_observe_scope", "arguments": {**base, field: "\u3000"}})
            assert json.loads(result["content"][0]["text"])["status"] == "invalid_argument"
        valid = rpc("tools/call", {"name": "patchdiff_observe_scope", "arguments": {**base, "query": "example"}})
        assert json.loads(valid["content"][0]["text"])["status"] == "candidates"
