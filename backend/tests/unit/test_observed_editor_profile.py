"""Delegated editor capabilities and compatibility of the advertised contracts."""
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest
from jsonschema import Draft202012Validator

from app.mcp.editor_contracts import EDITOR_V2_TOOLS
from app.mcp.external_adapter import ExternalMCPAdapter, TOOL_EXAMPLES
from app.mcp.server import registry


EDITOR_TOOLS = {
    "patchdiff_read_target", "patchdiff_find_occurrences",
    "patchdiff_observe_scope", "patchdiff_submit_observed_operations",
}
LIFECYCLE_TOOLS = {"patchdiff_save", "patchdiff_replay"}


def test_delegated_profile_is_opt_in_and_preserves_existing_catalogs(monkeypatch):
    monkeypatch.delenv("PATCHDIFF_MCP_PROFILE", raising=False)
    default = ExternalMCPAdapter()
    assert default.profile == "observed_v2"
    expected = {
        "editor": EDITOR_TOOLS | LIFECYCLE_TOOLS | {"patchdiff_submit_edits"},
        "unobserved": {"patchdiff_read_target", "patchdiff_find_occurrences", "patchdiff_submit_edits"} | LIFECYCLE_TOOLS,
        "observed": EDITOR_TOOLS | LIFECYCLE_TOOLS,
        "observed_editor": EDITOR_TOOLS,
        "observed_v2": set(EDITOR_V2_TOOLS),
        "full": set(registry.names()),
    }
    assert len(expected["full"]) == 23
    for profile, names in expected.items():
        assert {tool["name"] for tool in ExternalMCPAdapter(profile=profile).list_tools()} == names
    monkeypatch.setenv("PATCHDIFF_MCP_PROFILE", "observed_editor")
    delegated = ExternalMCPAdapter()
    assert delegated.profile == "observed_editor"
    monkeypatch.setenv("PATCHDIFF_MCP_PROFILE", "full")
    assert {tool["name"] for tool in delegated.list_tools()} == EDITOR_TOOLS
    assert {tool["name"] for tool in default.list_tools()} == expected["observed_v2"]
    with pytest.raises(FrozenInstanceError):
        delegated.profile = "full"
    with pytest.raises(ValueError, match="observed_editor"):
        ExternalMCPAdapter(profile="unknown")


def test_delegated_profile_rejects_every_other_route_before_dispatch(monkeypatch):
    adapter = ExternalMCPAdapter(profile="observed_editor")
    invoked = []
    monkeypatch.setattr(type(registry), "call", lambda self, name, **kwargs: invoked.append(name) or {"status": "ok"})
    for name in set(registry.names()) - EDITOR_TOOLS:
        # Empty arguments would fail handler admission if the capability boundary were bypassed.
        result = adapter.call_tool(name, {})
        assert result["isError"]
        assert "Unknown PatchDIFF MCP tool" in result["content"][0]["text"]
    assert invoked == []
    args = {
        "patchdiff_read_target": {"target_file_id": "target"},
        "patchdiff_find_occurrences": {"target_file_id": "target", "text": "text"},
        "patchdiff_observe_scope": {"target_file_id": "target"},
        "patchdiff_submit_observed_operations": {"target_file_id": "target", "intent": "edit"},
    }
    for name, arguments in args.items():
        assert not adapter.call_tool(name, arguments).get("isError", False)
    assert set(invoked) == EDITOR_TOOLS
    invoked.clear()
    override = adapter.call_tool("patchdiff_read_target", {"target_file_id": "target", "profile": "full"})
    assert override["isError"] and not invoked
    denied = adapter.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "patchdiff_save", "profile": "full", "arguments": {"target_file_id": "target"}}})
    assert denied["result"]["isError"] and not invoked


def _without_descriptions(value):
    if isinstance(value, dict):
        return {key: _without_descriptions(child) for key, child in value.items() if key != "description"}
    if isinstance(value, list):
        return [_without_descriptions(child) for child in value]
    return value


@pytest.mark.parametrize("name,expected", [
    ("patchdiff_observe_scope", "ed81ef007af185df12f9c4fd3e8ea2e96c475285295c36e13fc08bf746b7e8d8"),
    ("patchdiff_submit_observed_operations", "972d51ff004b5f3272ac6fccef29ff1f0253ac0ebb88469d704200f229ea22f6"),
])
def test_description_revision_preserves_request_contract_and_examples(name, expected):
    # Baseline bc2423f: pin domains, alternatives, examples and capabilities, but allow prose changes.
    for profile in ("editor", "observed", "observed_editor", "full"):
        tool = next(tool for tool in ExternalMCPAdapter(profile=profile).list_tools() if tool["name"] == name)
        schema = tool["inputSchema"]
        canonical = json.dumps(_without_descriptions(schema), sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(canonical).hexdigest() == expected
        for example in TOOL_EXAMPLES[name]:
            Draft202012Validator(schema).validate(example)


def test_observation_paging_description_uses_scope_coordinates():
    tools = {tool["name"]: tool for tool in ExternalMCPAdapter(profile="full").list_tools()}
    observation = tools["patchdiff_observe_scope"]
    offset = observation["inputSchema"]["properties"]["offset"]["description"]
    assert "observed scope" in offset and "next_offset" in offset and "line range" not in offset
    assert "selected line range" in tools["patchdiff_read_lines"]["inputSchema"]["properties"]["offset"]["description"]
    assert "no observation receipt" in observation["description"]
    submission = tools["patchdiff_submit_observed_operations"]["description"]
    assert "scopes[].observation_id" in submission and "null placeholders" in submission
