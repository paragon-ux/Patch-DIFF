import inspect
import json
import uuid

from app.mcp import external_adapter
from app.mcp.external_adapter import ExternalMCPAdapter
from app.storage.db import SessionLocal
from app.storage.models import CloudTargetFiles
from backend.tests.integration.helpers import pdcp_for


def _tool_payload(result: dict) -> dict:
    assert result["isError"] is False
    return json.loads(result["content"][0]["text"])


def test_external_mcp_tool_discovery_exposes_expected_patchdiff_tools() -> None:
    adapter = ExternalMCPAdapter()

    tools = adapter.list_tools()
    names = {tool["name"] for tool in tools}

    assert names == set(external_adapter.EXPECTED_TOOL_NAMES)
    assert {
        "patchdiff_handle_upload",
        "patchdiff_build_prompt_context",
        "patchdiff_submit_pdcp",
        "patchdiff_get_regeneration_context",
        "patchdiff_save",
        "patchdiff_replay",
        "patchdiff_export_target",
        "patchdiff_get_pdcp_log",
        "patchdiff_get_manifest_ledger",
    }.issubset(names)
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert "properties" in tool["inputSchema"]


def test_external_mcp_json_rpc_initialize_and_tool_list() -> None:
    adapter = ExternalMCPAdapter()

    initialized = adapter.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    listed = adapter.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    assert initialized["result"]["serverInfo"]["name"] == "patchdiff-mvp"
    assert initialized["result"]["capabilities"] == {"tools": {}}
    assert {tool["name"] for tool in listed["result"]["tools"]} == set(external_adapter.EXPECTED_TOOL_NAMES)


def test_external_mcp_tools_call_routes_to_existing_internal_registry(monkeypatch) -> None:
    calls = []

    def fake_call(self, name: str, **kwargs):
        calls.append((name, kwargs))
        return {"status": "ok", "tool": name, "arguments": kwargs}

    monkeypatch.setattr(type(external_adapter.registry), "call", fake_call)
    adapter = ExternalMCPAdapter()

    response = adapter.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "patchdiff_export_target",
                "arguments": {"target_file_id": "target-1"},
            },
        }
    )

    payload = _tool_payload(response["result"])
    assert calls == [("patchdiff_export_target", {"target_file_id": "target-1"})]
    assert payload["tool"] == "patchdiff_export_target"


def test_external_upload_and_submit_use_existing_behavior_without_direct_mutation() -> None:
    adapter = ExternalMCPAdapter()

    upload = _tool_payload(
        adapter.call_tool(
            "patchdiff_handle_upload",
            {"filename": "external.txt", "content": "old", "content_type": "text/plain"},
        )
    )
    target_id = upload["target_file_id"]

    accepted = _tool_payload(
        adapter.call_tool(
            "patchdiff_submit_pdcp",
            {
                "target_file_id": target_id,
                "pdcp_content": pdcp_for(target_id, ("old", "new")),
                "expected_target_version": 0,
            },
        )
    )

    assert accepted["status"] == "accepted"
    assert accepted["version"] == 1
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, uuid.UUID(target_id))
        assert target.current_content == "new"
        assert target.version == 1


def test_external_mcp_adapter_does_not_mutate_storage_or_call_runtime_directly() -> None:
    source = inspect.getsource(external_adapter)

    assert ".current_content =" not in source
    assert "CloudTargetFiles" not in source
    assert "SessionLocal" not in source
    assert "submit_pdcp(" not in source
    assert "save_target(" not in source
    assert "replay_target(" not in source
    assert "export_target(" not in source
    assert "apply_pdcp_transaction" not in source
