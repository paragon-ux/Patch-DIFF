"""Subprocess tests for the stdio MCP adapter and malformed-JSON-RPC resilience."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from app.mcp.external_adapter import ExternalMCPAdapter, _portable_schema_patterns
from app.pdcp.typed import ALLOWED_TYPED_EDIT_FIELDS, REQUIRED_TYPED_EDIT_FIELDS, TYPED_EDIT_JSON_SCHEMA

BACKEND = Path(__file__).resolve().parents[2]


def _rpc(*messages: str) -> list[dict]:
    completed = subprocess.run(
        [sys.executable, "-m", "app.mcp.external_adapter"],
        input="\n".join(messages) + "\n",
        capture_output=True,
        text=True,
        cwd=BACKEND,
        env={**os.environ, "PATCHDIFF_MCP_PROFILE": "full", "PYTHONPATH": str(BACKEND), "SYSTEMROOT": _systemroot()},
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def _systemroot() -> str:
    return os.environ.get("SYSTEMROOT", "")


def test_subprocess_initialize_and_list_new_tools_with_complete_schema() -> None:
    init, listed = _rpc(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    )
    assert init["result"]["serverInfo"]["name"] == "patchdiff-mvp"
    tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
    assert {"patchdiff_submit_edits", "patchdiff_read_target", "patchdiff_find_occurrences"} <= set(tools)

    submit_edits_schema = tools["patchdiff_submit_edits"]["inputSchema"]
    edits = submit_edits_schema["properties"]["edits"]
    assert edits["type"] == "array"
    assert edits["minItems"] == 1
    advertised = copy.deepcopy(edits["items"])
    runtime = copy.deepcopy(TYPED_EDIT_JSON_SCHEMA)
    _portable_schema_patterns(runtime)
    wire_id = Draft202012Validator(advertised["properties"].pop("change_id"))
    runtime_id = Draft202012Validator(runtime["properties"].pop("change_id"))
    assert advertised == runtime
    # The wire regex is portable; its identifier domain must remain identical.
    for value in (None, "chg_001", "a" * 64, "a" * 65, "", "chg_001\n", "two words", "é", 1):
        assert wire_id.is_valid(value) == runtime_id.is_valid(value)
    assert set(edits["items"]["properties"].keys()) == set(ALLOWED_TYPED_EDIT_FIELDS)
    assert set(edits["items"]["required"]) == set(REQUIRED_TYPED_EDIT_FIELDS)
    assert edits["items"]["additionalProperties"] is False
    assert "client_request_id" in submit_edits_schema["properties"]
    assert "edits" in submit_edits_schema["required"]

    find_occ_props = tools["patchdiff_find_occurrences"]["inputSchema"]["properties"]
    assert {"start_occurrence", "max_results", "context_chars"} <= set(find_occ_props)

    log_props = tools["patchdiff_get_pdcp_log"]["inputSchema"]["properties"]
    assert {"before_sequence", "status", "content_hash", "client_request_id"} <= set(log_props)

    assert "DEPRECATED" in tools["patchdiff_request_regeneration"]["description"]


def test_subprocess_survives_malformed_params_of_every_json_type() -> None:
    bad = [1, [1, 2], "x", True]
    messages = [
        json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": value})
        for i, value in enumerate(bad, start=1)
    ]
    messages.append(json.dumps({"jsonrpc": "2.0", "id": 99, "method": "tools/list"}))
    responses = _rpc(*messages)
    assert [r["error"]["code"] for r in responses[:-1]] == [-32602] * len(bad)
    assert "tools" in responses[-1]["result"]  # server kept running after every bad request


def test_non_object_arguments_and_unknown_tool_are_errors_not_crashes() -> None:
    adapter = ExternalMCPAdapter()
    response = adapter.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "patchdiff_save", "arguments": [1]}}
    )
    assert response["error"]["code"] == -32602
    unknown = adapter.call_tool("patchdiff_nope", {})
    assert unknown["isError"] is True


def test_in_process_params_validation_matches_subprocess() -> None:
    adapter = ExternalMCPAdapter()
    for params in (5, [1], "s"):
        response = adapter.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
        assert response["error"]["code"] == -32602


def test_malformed_typed_submit_reports_invalid_arguments_without_database() -> None:
    adapter = ExternalMCPAdapter()
    result = adapter.call_tool("patchdiff_submit_edits", {"target_file_id": "t"})  # missing required args
    assert result["isError"] is True
