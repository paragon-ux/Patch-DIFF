import json
import pytest

from app.core.versions import (
    OPERATIONS_RUNTIME_VERSION,
    REPLACEMENT_RUNTIME_VERSION,
    RUNTIME_VERSION,
)
from app.mcp.external_adapter import (
    ExternalMCPAdapter,
    SUPPORTED_FEATURES,
    SUPPORTED_TRANSACTION_FORMATS,
)
from app.mcp.server import registry


def test_default_initialize_without_patchdiff_capabilities_preserves_legacy_response():
    adapter = ExternalMCPAdapter(profile="full")
    response = adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25"},
    })
    assert response["result"]["protocolVersion"] == "2025-11-25"
    assert response["result"]["capabilities"] == {"tools": {}}
    assert response["result"]["serverInfo"]["name"] == "patchdiff-mvp"
    assert adapter.negotiated_capabilities is None


def test_capability_negotiation_handshake_intersection():
    adapter = ExternalMCPAdapter(profile="full")
    response = adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {
                "patchdiff": {
                    "supported_formats": ["patchdiff-tx/1", "patchdiff-tx/2", "unknown-tx/99"],
                    "features": ["multi_target", "span_context", "unknown_future_flag"],
                }
            },
        },
    })
    pd = response["result"]["capabilities"]["patchdiff"]
    assert pd["supported_formats"] == ["patchdiff-tx/1", "patchdiff-tx/2"]
    assert pd["runtime_versions"]["patchdiff-tx/1"] == RUNTIME_VERSION
    assert pd["runtime_versions"]["patchdiff-tx/2"] == OPERATIONS_RUNTIME_VERSION
    assert "patchdiff-tx/3" not in pd["runtime_versions"]
    assert pd["features"] == {"multi_target": True, "span_context": True}
    assert adapter.negotiated_capabilities == pd


def test_unnegotiated_format_enforcement(monkeypatch):
    invoked = []
    monkeypatch.setattr(type(registry), "call", lambda self, name, **kw: invoked.append(name) or {"status": "ok"})

    adapter = ExternalMCPAdapter(profile="full")
    adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {
                "patchdiff": {
                    "supported_formats": ["patchdiff-tx/1"],
                    "features": ["multi_target"],
                }
            },
        },
    })

    # Allowed format patchdiff-tx/1
    res1 = adapter.call_tool("patchdiff_submit_edits", {"target_file_id": "t", "intent": "i", "edits": []})
    # Tool execution proceeds past capability check (may fail on argument validation or succeed)
    assert not (res1.get("isError") and "unnegotiated_transaction_format" in res1["content"][0]["text"])

    # Disallowed format patchdiff-tx/2
    res2 = adapter.call_tool("patchdiff_submit_operations", {"target_file_id": "t", "intent": "i", "operations": []})
    assert res2["isError"] is True
    err2 = json.loads(res2["content"][0]["text"])
    assert err2["code"] == "unnegotiated_transaction_format"
    assert "patchdiff-tx/2" in err2["failure_detail"]

    # Disallowed format patchdiff-tx/3
    res3 = adapter.call_tool("patchdiff_submit_replacement", {"target_file_id": "t", "intent": "i", "replacement": "x"})
    assert res3["isError"] is True
    err3 = json.loads(res3["content"][0]["text"])
    assert err3["code"] == "unnegotiated_transaction_format"
    assert "patchdiff-tx/3" in err3["failure_detail"]

    # Preview with disallowed format
    res4 = adapter.call_tool("patchdiff_preview", {"target_file_id": "t", "format": "patchdiff-tx/2", "intent": "i"})
    assert res4["isError"] is True
    err4 = json.loads(res4["content"][0]["text"])
    assert err4["code"] == "unnegotiated_transaction_format"


def test_unnegotiated_feature_enforcement():
    adapter = ExternalMCPAdapter(profile="full")
    adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {
                "patchdiff": {
                    "supported_formats": ["patchdiff-tx/1"],
                    "features": {"multi_target": False, "workspace_sync": False},
                }
            },
        },
    })

    # Multi-target feature not negotiated
    res1 = adapter.call_tool("patchdiff_commit_multi_target", {"intent": "i", "targets": []})
    assert res1["isError"] is True
    err1 = json.loads(res1["content"][0]["text"])
    assert err1["code"] == "unnegotiated_feature"
    assert "multi_target" in err1["failure_detail"]

    # Workspace sync feature not negotiated
    res2 = adapter.call_tool("patchdiff_save", {"target_file_id": "t", "sync_workspace": True})
    assert res2["isError"] is True
    err2 = json.loads(res2["content"][0]["text"])
    assert err2["code"] == "unnegotiated_feature"
    assert "workspace_sync" in err2["failure_detail"]


def test_idempotent_reinitialize_succeeds():
    adapter = ExternalMCPAdapter(profile="full")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {
                "patchdiff": {
                    "supported_formats": ["patchdiff-tx/1"],
                    "features": ["multi_target"],
                }
            },
        },
    }
    first = adapter.handle_request(payload)
    second = adapter.handle_request(payload)
    assert first == second
    assert first["result"]["capabilities"]["patchdiff"]["supported_formats"] == ["patchdiff-tx/1"]


def test_renegotiate_revision_or_capabilities_rejected():
    adapter = ExternalMCPAdapter(profile="full")
    adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {
                "patchdiff": {"supported_formats": ["patchdiff-tx/1"]},
            },
        },
    })

    # Changing protocol revision
    res1 = adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    })
    assert res1["error"]["code"] == -32602
    assert "protocol revision" in res1["error"]["message"]

    # Changing capabilities
    res2 = adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {
                "patchdiff": {"supported_formats": ["patchdiff-tx/1", "patchdiff-tx/2"]},
            },
        },
    })
    assert res2["error"]["code"] == -32602
    assert "protocol capabilities" in res2["error"]["message"]


def test_invalid_capabilities_structure_rejected():
    adapter = ExternalMCPAdapter(profile="full")
    res1 = adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"capabilities": "not_an_object"},
    })
    assert res1["error"]["code"] == -32602

    res2 = adapter.handle_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "initialize",
        "params": {"capabilities": {"patchdiff": "not_an_object"}},
    })
    assert res2["error"]["code"] == -32602
