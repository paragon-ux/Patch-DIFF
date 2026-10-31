import copy
import json
from dataclasses import FrozenInstanceError

import pytest
from jsonschema import Draft202012Validator

from app.mcp import tools
from app.mcp.editor_contracts import EDITOR_V2_TOOLS, EDITOR_V2_ROUTES, MAX_RECEIPT_BYTES
from app.mcp.external_adapter import ExternalMCPAdapter, MCP_PROFILES, SUPPORTED_PROTOCOL_VERSIONS
from app.mcp.server import registry


def initialize(adapter, revision):
    return adapter.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": revision}})


@pytest.mark.parametrize("revision", SUPPORTED_PROTOCOL_VERSIONS)
def test_negotiated_contract_and_error_channels(revision):
    adapter = ExternalMCPAdapter(profile="observed_v2")
    assert initialize(adapter, revision)["result"]["protocolVersion"] == revision
    modern = revision != "2024-11-05"
    declarations = adapter.list_tools()
    assert {t["name"] for t in declarations} == EDITOR_V2_TOOLS
    assert len(declarations) == 5 and len(registry.names()) == 22
    for declaration in declarations:
        assert ("outputSchema" in declaration) == modern
        assert ("annotations" in declaration) == modern
        Draft202012Validator.check_schema(declaration["inputSchema"])
    result = adapter.call_tool("patchdiff_commit_bundle", {"snapshot": {}})
    assert result["isError"]
    assert ("structuredContent" in result) == modern
    if modern:
        assert result["structuredContent"] == json.loads(result["content"][0]["text"])
        schema = next(t["outputSchema"] for t in declarations if t["name"] == "patchdiff_commit_bundle")
        Draft202012Validator(schema).validate(result["structuredContent"])
    assert adapter.call_tool("patchdiff_save", {"target_file_id": "x"})["isError"]
    with pytest.raises(FrozenInstanceError):
        adapter.profile = "full"


def test_negotiation_fallback_invalid_reinitialize_and_legacy_payloads(monkeypatch):
    adapter = ExternalMCPAdapter(profile="observed_v2")
    assert initialize(adapter, None)["error"]["code"] == -32602
    assert initialize(adapter, "unimplemented")["result"]["protocolVersion"] == "2025-11-25"
    assert initialize(adapter, "2024-11-05")["error"]["code"] == -32602
    assert initialize(adapter, "2025-11-25")["result"]["protocolVersion"] == "2025-11-25"
    legacy = ExternalMCPAdapter(profile="observed_editor")
    declarations = copy.deepcopy(legacy.list_tools())
    initialize(legacy, "2025-11-25")
    assert legacy.list_tools() == declarations
    payload = {"status": "rejected", "diagnostic": {"code": "unchanged"}}
    monkeypatch.setattr(type(registry), "call", lambda *a, **kw: payload)
    response = legacy.call_tool("patchdiff_observe_scope", {"target_file_id": "x"})
    assert response == {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, sort_keys=True)}], "isError": False}


def test_alias_routes_and_profile_denials_are_exact(monkeypatch):
    seen = []
    monkeypatch.setattr(type(registry), "call", lambda self, name, **kw: seen.append((name, kw)) or {"status": "invalid_argument"})
    monkeypatch.setattr(tools, "submit_editor_operations", lambda **kw: seen.append(("commit", kw)) or {"status": "rejected"})
    adapter = ExternalMCPAdapter(profile="observed_v2")
    examples = {
        "patchdiff_read_target": {"target_file_id": "raw"},
        "patchdiff_find_occurrences": {"target_file_id": "raw", "text": "a"},
        "patchdiff_list_scopes": {"target_file_id": "raw"},
        "patchdiff_observe_scopes": {"target_file_id": "raw", "selections": None},
        "patchdiff_commit_bundle": {"snapshot": {"target_file_id": "RAW", "observation_bundle_id": "BID"}},
    }
    for name, arguments in examples.items():
        adapter.call_tool(name, arguments)
        assert seen[-1][0] == ("commit" if name.startswith("patchdiff_commit") else EDITOR_V2_ROUTES[name])
    assert seen[-1][1] == {"target_file_id": "RAW", "observation_bundle_id": "BID", "groups": None, "intent": None}
    count = len(seen)
    for name in registry.names():
        if name not in EDITOR_V2_TOOLS:
            assert adapter.call_tool(name, {})["isError"]
    for name in ("patchdiff_read_observation", "patchdiff_observe_one", "patchdiff_commit_observation"):
        assert adapter.call_tool(name, {"target_file_id": "raw"})["isError"]
    assert len(seen) == count
    for profile in MCP_PROFILES.keys() - {"observed_v2"}:
        assert ExternalMCPAdapter(profile=profile).call_tool("patchdiff_commit_bundle", examples["patchdiff_commit_bundle"])["isError"]


def test_wire_receipt_is_bounded_and_infrastructure_failure_is_unknown(monkeypatch):
    adapter = ExternalMCPAdapter(profile="observed_v2")
    initialize(adapter, "2025-11-25")
    args = {"snapshot": {"target_file_id": "x", "observation_bundle_id": "y"}, "intent": "edit", "groups": []}
    monkeypatch.setattr(tools, "submit_editor_operations", lambda **kw: {"status": "rejected", "failure_detail": "🌟" * 10000})
    response = adapter.call_tool("patchdiff_commit_bundle", args)
    assert len(response["content"][0]["text"].encode("utf-8")) <= MAX_RECEIPT_BYTES
    assert response["structuredContent"]["presentation"]["truncated"]
    def fail(**kwargs):
        raise RuntimeError("private infrastructure detail")
    monkeypatch.setattr(tools, "submit_editor_operations", fail)
    response = adapter.call_tool("patchdiff_commit_bundle", args)
    assert response["isError"] and response["structuredContent"]["status"] == "outcome_unknown"
    assert "private infrastructure" not in response["content"][0]["text"]
