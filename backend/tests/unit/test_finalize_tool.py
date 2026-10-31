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
