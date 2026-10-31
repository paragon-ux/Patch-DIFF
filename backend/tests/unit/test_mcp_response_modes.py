import copy
from dataclasses import FrozenInstanceError
import json

import pytest

from app.mcp.external_adapter import ExternalMCPAdapter, MCP_PROFILES, _compact_payload
from app.mcp.server import registry


def test_startup_mode_is_opt_in_validated_and_frozen(monkeypatch):
    monkeypatch.delenv("PATCHDIFF_MCP_RESPONSE_MODE", raising=False)
    original = ExternalMCPAdapter()
    assert original.response_mode == "detailed"
    monkeypatch.setenv("PATCHDIFF_MCP_RESPONSE_MODE", "compact")
    assert original.response_mode == "detailed" and ExternalMCPAdapter().response_mode == "compact"
    with pytest.raises(FrozenInstanceError):
        original.response_mode = "compact"
    monkeypatch.setenv("PATCHDIFF_MCP_RESPONSE_MODE", "bad")
    with pytest.raises(ValueError):
        ExternalMCPAdapter()
    assert ExternalMCPAdapter(response_mode="detailed").response_mode == "detailed"
    with pytest.raises(ValueError):
        ExternalMCPAdapter(response_mode="bad")


@pytest.mark.parametrize("profile", MCP_PROFILES)
def test_mode_keeps_schema_profile_and_discovery_budget(profile):
    detailed = ExternalMCPAdapter(profile=profile, response_mode="detailed").list_tools()
    compact = ExternalMCPAdapter(profile=profile, response_mode="compact").list_tools()
    assert [t["name"] for t in detailed] == [t["name"] for t in compact]
    assert [t["inputSchema"] for t in detailed] == [t["inputSchema"] for t in compact]
    assert len(json.dumps({"tools": compact}, separators=(",", ":")).encode()) <= 65536


def test_success_projection_preserves_all_other_fields_and_never_mutates():
    payload = {"status": "accepted", "evidence": {"changes": [{"span_start": 1}]}, "groups": [{}],
               "future_field": [1], "warnings": ["grapheme_boundary_split"], "warning_details": [{"x": 1}],
               "warning_count": 1, "warnings_truncated": False, "deduplicated": True,
               "validity": {"task_correct": "not_evaluated"}, "after_hash": "f" * 64, "client_request_id": "key"}
    before = copy.deepcopy(payload)
    compact = _compact_payload("patchdiff_submit_observed_operations", payload)
    assert payload == before
    assert compact == {**{k: v for k, v in payload.items() if k not in {"evidence", "groups"}},
                       "presentation": {"mode": "compact", "omitted": ["evidence", "groups"]}}
    assert _compact_payload("patchdiff_submit_observed_operations", {"status": "accepted"})["presentation"]["omitted"] == []


def test_candidate_and_bundle_projections_keep_order_text_guards_and_continuations():
    candidate = {"name": "🌟", "kind": "function", "parent": None, "start_line": 2, "end_line": 4, "signature": "f()", "scope_start": 9}
    original = {"status": "candidates", "target_current_hash": "a" * 64, "candidates": [candidate, candidate],
                "total_candidates": 3, "candidates_truncated": True, "future_field": 1}
    compact = _compact_payload("patchdiff_observe_scope", original)
    assert len(compact["candidates"]) == 2 and compact["total_candidates"] == 3 and compact["candidates_truncated"]
    assert compact["candidates"][0] == {k: v for k, v in candidate.items() if k not in {"signature", "scope_start"}}
    scope = {"observation_id": "id", "scope_start": 9, "scope_end": 30, "scope_chars": 21, "offset": 2,
             "text": "a🌟\n", "truncated": True, "next_offset": 5, "line_starts": [{"line": 2, "start": 9}],
             "start": 11, "end": 14, "max_chars": 3, "next_start": 14, "start_line": 2, "end_line": 4}
    full = {"status": "observed_batch", "scopes": [scope], "target_version": 0}
    snapshot = copy.deepcopy(full)
    projected = _compact_payload("patchdiff_observe_scope", full)
    assert full == snapshot
    for key in ("observation_id", "scope_start", "scope_end", "scope_chars", "offset", "text", "truncated", "next_offset", "line_starts"):
        assert projected["scopes"][0][key] == scope[key]


@pytest.mark.parametrize("status", ["rejected", "ambiguous", "not_found", "discovery_error", "invalid_argument", "observed"])
def test_nonprojected_results_keep_object_and_serialization(status, monkeypatch):
    payload = {"status": status, "diagnostic": {"text": "🌟"}}
    monkeypatch.setattr(type(registry), "call", lambda *args, **kw: payload)
    detailed = ExternalMCPAdapter(response_mode="detailed").call_tool("patchdiff_observe_scope", {"target_file_id": "x"})
    compact = ExternalMCPAdapter(response_mode="compact").call_tool("patchdiff_observe_scope", {"target_file_id": "x"})
    assert compact == detailed and _compact_payload("patchdiff_observe_scope", payload) is payload
    assert _compact_payload("patchdiff_read_target", payload) is payload


def test_compact_serialization_keeps_unicode_and_surrogate_fallback(monkeypatch):
    for text in ("🌟\u2028\n", "\ud800"):
        payload = {"status": "accepted", "warnings": [text], "evidence": {"changes": []}}
        monkeypatch.setattr(type(registry), "call", lambda *a, **kw: payload)
        result = ExternalMCPAdapter(response_mode="compact").call_tool("patchdiff_submit_observed_operations",
                                                                    {"target_file_id": "x", "intent": "update"})
        wire = result["content"][0]["text"]
        wire.encode("utf-8")
        assert json.loads(wire)["warnings"] == [text] and '": "' not in wire


@pytest.mark.parametrize("stalled", [True, False])
def test_operator_peer_timeout_and_failed_initialization_reap_child(monkeypatch, stalled):
    import subprocess
    import sys
    from backend.tests.verification.structural_batch import verify
    popen = subprocess.Popen
    code = "import time; time.sleep(30)" if stalled else "import sys,time; sys.stdin.readline(); print('bad',flush=True); time.sleep(30)"
    monkeypatch.setattr(verify.subprocess, "Popen", lambda *args, **kw: popen([sys.executable, "-u", "-c", code], **kw))
    peer = verify.MCP("full", rpc_timeout_seconds=0.2 if stalled else 5)
    with pytest.raises(TimeoutError if stalled else json.JSONDecodeError):
        peer.__enter__()
    assert peer.closed and peer.process.poll() is not None and peer.stderr.closed
    with pytest.raises(RuntimeError, match="closed"):
        peer.rpc("tools/list", {})
