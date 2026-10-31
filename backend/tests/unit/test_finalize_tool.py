"""Unit tests for the patchdiff_finalize_target MCP tool and profile access control."""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.external_adapter import ExternalMCPAdapter, MCP_PROFILES
from app.mcp.server import registry
from app.services.finalize_service import FinalizeResult


def test_finalize_tool_registered_in_registry():
    assert "patchdiff_finalize_target" in registry.names()
    assert "patchdiff_finalize_target" in MCP_PROFILES["full"]
    # Finalize tool is host-owned and must NOT be in observed_v2 agent profile
    assert "patchdiff_finalize_target" not in MCP_PROFILES["observed_v2"]


def test_finalize_tool_denied_in_observed_v2_profile():
    adapter = ExternalMCPAdapter(profile="observed_v2")
    tid = str(uuid.uuid4())
    res = adapter.call_tool("patchdiff_finalize_target", {"target_file_id": tid})
    assert res["isError"]
    assert "Unknown PatchDIFF MCP tool: patchdiff_finalize_target" in res["content"][0]["text"]


@patch("app.mcp.tools.finalize_target")
def test_finalize_tool_dispatches_in_full_profile(mock_finalize):
    tid = str(uuid.uuid4())
    mock_finalize.return_value = FinalizeResult(
        status="ok",
        target_file_id=tid,
        client_request_id="req-123",
        filename="test.py",
        version=1,
        current_hash="hash1",
        snapshot_id=uuid.uuid4(),
        closed_editing_cycle_id=uuid.uuid4(),
        new_editing_cycle_id=uuid.uuid4(),
        materialized_state_matches=True,
        materialized_state_checks={"content_matches": True},
        exported_content="print('hello')\n",
        content_sha256="sha256_print",
        format="original_eol",
        source_line_endings="lf",
    )

    adapter = ExternalMCPAdapter(profile="full")
    res = adapter.call_tool(
        "patchdiff_finalize_target",
        {
            "target_file_id": tid,
            "expected_target_version": 1,
            "format": "original_eol",
            "client_request_id": "req-123",
        },
    )

    assert not res["isError"]
    payload = json.loads(res["content"][0]["text"])
    assert payload["status"] == "ok"
    assert payload["filename"] == "test.py"
    assert payload["version"] == 1
    assert payload["exported_content"] == "print('hello')\n"
    assert payload["client_request_id"] == "req-123"


def test_finalize_tool_schema_requires_client_request_id():
    adapter = ExternalMCPAdapter(profile="full")
    tid = str(uuid.uuid4())
    res = adapter.call_tool(
        "patchdiff_finalize_target",
        {
            "target_file_id": tid,
            "expected_target_version": 1,
        },
    )
    assert res["isError"]
    payload = json.loads(res["content"][0]["text"])
    assert payload["code"] == "missing_argument"
    assert "client_request_id" in payload["missing_arguments"]


def test_finalize_tool_schema_declarations():
    adapter = ExternalMCPAdapter(profile="full")
    tools = {t["name"]: t for t in adapter.list_tools()}
    schema = tools["patchdiff_finalize_target"]["inputSchema"]
    assert "client_request_id" in schema["required"]
    assert "target_file_id" in schema["required"]
    assert "anyOf" in schema
    guard_props = [set(branch["required"]) for branch in schema["anyOf"]]
    assert {"expected_target_version"} in guard_props
    assert {"expected_current_hash"} in guard_props


@patch("app.mcp.tools.finalize_target")
def test_finalize_tool_requires_guard(mock_finalize):
    tid = str(uuid.uuid4())
    mock_finalize.return_value = FinalizeResult(
        status="invalid_argument",
        target_file_id=tid,
        failure_code="missing_guard",
        failure_detail="At least one of expected_target_version or expected_current_hash must be provided.",
    )
    adapter = ExternalMCPAdapter(profile="full")
    res = adapter.call_tool(
        "patchdiff_finalize_target",
        {
            "target_file_id": tid,
            "client_request_id": "req-123",
        },
    )
    assert not res["isError"]
    payload = json.loads(res["content"][0]["text"])
    assert payload["status"] == "invalid_argument"
    assert payload["failure_code"] == "missing_guard"


