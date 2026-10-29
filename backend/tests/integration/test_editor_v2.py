"""Live external v2 facade: audit/recovery, scope authority, paging and legacy parity."""
import copy
import json
import uuid

import pytest
from jsonschema import Draft202012Validator

from app.core.config import strict_observation_mode
from app.mcp.external_adapter import ExternalMCPAdapter
from app.mcp.server import registry
from backend.tests.integration.test_observed_batch import initialized, state
from backend.tests.verification.structural_batch.verify import MCP


def editor():
    adapter = ExternalMCPAdapter(profile="observed_v2")
    adapter.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
    return adapter


def call(adapter, name, args, *, ok=True):
    response = adapter.call_tool(name, args)
    payload = json.loads(response["content"][0]["text"])
    assert response["isError"] is (not ok), payload
    assert response["structuredContent"] == payload
    declaration = next(t for t in adapter.list_tools() if t["name"] == name)
    Draft202012Validator(declaration["outputSchema"]).validate(payload)
    return payload


def bundle_request(adapter, target, selectors):
    bundle = call(adapter, "patchdiff_observe_scopes", {"target_file_id": target["target_file_id"], "selections": selectors})
    return bundle, {"snapshot": bundle["snapshot"], "intent": "Update selected functions", "client_request_id": str(uuid.uuid4()),
                    "groups": [{"observation_id": scope["observation_id"], "operations": [
                        {"op": "match", "match": "abcd", "replace": "ABCDE"},
                        {"op": "match", "match": "BCD", "replace": "🌟"}]} for scope in bundle["scopes"]]}


@pytest.mark.parametrize("single", [False, True])
def test_recovery_after_later_commit_keeps_transaction_distinct_from_current(single):
    adapter = editor()
    target, selectors = initialized(1)
    tid = target["target_file_id"]
    if single:
        observed = call(adapter, "patchdiff_observe_one", {"target_file_id": tid, "symbol_name": "f0"})
        args = {"snapshot": observed["snapshot"], "intent": "first", "client_request_id": "first",
                "operations": [{"op": "match", "match": "abcd", "replace": "ABCDE"}]}
        name = "patchdiff_commit_observation"
    else:
        _, args = bundle_request(adapter, target, selectors)
        name = "patchdiff_commit_bundle"
    first = call(adapter, name, args)
    assert first["transaction"]["before"]["version"] == 0
    assert first["transaction"]["after"]["version"] == first["current"]["version"] == 1
    second = call(adapter, "patchdiff_observe_one", {"target_file_id": tid, "symbol_name": "f0"})
    call(adapter, "patchdiff_commit_observation", {"snapshot": second["snapshot"], "intent": "advance",
          "operations": [{"op": "match", "match": "return", "replace": "return "}]})
    before_recovery = state(target)
    with strict_observation_mode():
        recovered = call(adapter, name, args)
    assert recovered["transaction"] == {**first["transaction"], "deduplicated": True}
    assert recovered["changes"] == first["changes"]
    assert recovered["current"]["version"] == 2 and recovered["transaction"]["after"]["version"] == 1
    assert len(state(target)[2]) == len(before_recovery[2]) == 2
    assert len(state(target)[3]) == len(before_recovery[3])
    changed = copy.deepcopy(args)
    changed["intent"] += " different"
    conflict = call(adapter, name, changed, ok=False)
    assert conflict["diagnostic"]["existing_pdcp_log_id"] == first["transaction"]["pdcp_log_id"]
    assert state(target)[1] == 2 and len(state(target)[2]) == 3


@pytest.mark.parametrize("fault", ["missing_version", "missing_hash", "missing_key", "bad_text", "bad_operations", "missing_intent", "stale", "foreign_scope"])
def test_known_target_malformed_and_stale_requests_remain_audited_and_atomic(fault):
    adapter = editor()
    target, selectors = initialized()
    _, args = bundle_request(adapter, target, selectors)
    if fault == "missing_version": del args["snapshot"]["expected_target_version"]
    if fault == "missing_hash": del args["snapshot"]["expected_current_hash"]
    if fault == "missing_key": del args["client_request_id"]
    if fault == "bad_text": args["groups"][1]["operations"][0]["replace"] = "\ud800"
    if fault == "bad_operations": args["groups"][1]["operations"] = "invalid"
    if fault == "missing_intent": del args["intent"]
    if fault == "stale": args["snapshot"]["expected_target_version"] = 9
    if fault == "foreign_scope":
        other, other_selectors = initialized(1)
        other_bundle, _ = bundle_request(adapter, other, other_selectors)
        args["groups"][1]["observation_id"] = other_bundle["scopes"][0]["observation_id"]
    before = state(target)
    rejected = call(adapter, "patchdiff_commit_bundle", args, ok=False)
    after = state(target)
    assert rejected["status"] == "rejected", rejected
    assert rejected["transaction"]["pdcp_log_id"]
    assert after[:2] == before[:2] and len(after[2]) == 1 and not after[3]
    assert all(scope.accepted_pdcp_log_id is None for scope in after[4])


def test_candidate_selection_paging_and_mixed_sequential_operations():
    adapter = editor()
    target, selectors = initialized(2, body="    value = '" + "x" * 5000 + "'\n    return 'abcd abcd'")
    tid = target["target_file_id"]
    candidates = call(adapter, "patchdiff_list_scopes", {"target_file_id": tid})
    assert len(candidates["candidates"]) == 2 and not state(target)[4]
    observed = call(adapter, "patchdiff_observe_scopes", {"target_file_id": tid, "selections": selectors, "max_chars": 40})
    scope = observed["scopes"][0]
    page = call(adapter, "patchdiff_read_observation", {"target_file_id": tid, "observation_id": scope["observation_id"], "offset": scope["next_offset"], "max_chars": 100})
    assert page["offset"] == 40
    # Use an exact known offset in the authoritative text, then a match against its sequential result.
    whole = registry.call("patchdiff_get_target", target_file_id=tid)["current_content"]
    start = whole[scope["scope_start"]:scope["scope_end"]].index("abcd")
    result = call(adapter, "patchdiff_commit_bundle", {"snapshot": observed["snapshot"], "intent": "mixed", "client_request_id": "mixed",
          "groups": [{"observation_id": scope["observation_id"], "operations": [
              {"op": "span", "start": start, "end": start + 4, "expected_text": "abcd", "replace": "ABCD"},
              {"op": "match", "match": "abcd", "replace": "DONE"}]}]})
    assert "'ABCD DONE'" in state(target)[0]
    assert result["changes"]["coordinate_space"] == "scope_local_sequential_code_points"
    assert result["transaction"]["operation_count"] == 2
    call(adapter, "patchdiff_read_observation", {"target_file_id": tid, "observation_id": scope["observation_id"]}, ok=False)


def test_large_single_scope_compatibility_and_absolute_span():
    adapter = editor()
    target, selectors = initialized(1, body="    value = '" + "x" * 66000 + "'\n    return 'abcd'", prefix="# prefix\n")
    tid = target["target_file_id"]
    call(adapter, "patchdiff_observe_scopes", {"target_file_id": tid, "selections": selectors}, ok=False)
    observed = call(adapter, "patchdiff_observe_one", {"target_file_id": tid, "symbol_name": "f0", "max_chars": 50})
    assert observed["scope_end"] - observed["scope_start"] > 65536
    content = state(target)[0]
    start = content.index("abcd")
    accepted = call(adapter, "patchdiff_commit_observation", {"snapshot": observed["snapshot"], "intent": "large", "client_request_id": "large",
          "operations": [{"op": "span", "start": start, "end": start + 4, "expected_text": "abcd", "replace": "DONE"}]})
    assert accepted["changes"]["coordinate_space"] == "target_absolute_sequential_code_points"
    assert accepted["transaction"]["before"]["version"] == 0 and accepted["transaction"]["after"]["version"] == 1
    assert state(target)[0] == content.replace("abcd", "DONE")
    saved = registry.call("patchdiff_save", target_file_id=tid)
    replayed = registry.call("patchdiff_replay", target_file_id=tid)
    assert saved["status"] == "saved" and replayed["status"] == "success" and replayed["materialized_state_matches"]


def test_real_stdio_modern_profile_denies_privileged_and_old_mixed_routes():
    target, selectors = initialized(1)
    with MCP("observed_v2") as peer:
        assert len(peer.catalog["tools"]) == 8
        for name in ("patchdiff_save", "patchdiff_replay", "patchdiff_export_target", "patchdiff_submit_edits",
                     "patchdiff_observe_scope", "patchdiff_submit_observed_operations"):
            denied = peer.rpc("tools/call", {"name": name, "arguments": {"target_file_id": target["target_file_id"]}})
            assert denied["isError"]
        bundle = peer.call("patchdiff_observe_scopes", target_file_id=target["target_file_id"], selections=selectors)
        receipt = peer.call("patchdiff_commit_bundle", snapshot=bundle["snapshot"], intent="stdio", client_request_id="stdio",
                            groups=[{"observation_id": bundle["scopes"][0]["observation_id"],
                                     "operations": [{"op": "match", "match": "abcd", "replace": "DONE"}]}])
        assert receipt["transaction"]["after"]["version"] == 1 and "DONE" in state(target)[0]
