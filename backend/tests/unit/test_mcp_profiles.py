import copy
import json
import uuid
from dataclasses import FrozenInstanceError

import pytest
from jsonschema import Draft202012Validator

from app.mcp.external_adapter import ExternalMCPAdapter, MCP_PROFILES
from app.mcp.server import registry


@pytest.mark.parametrize("profile,count", [("editor", 7), ("unobserved", 5), ("unobserved_editor", 3), ("hybrid_editor", 1), ("observed", 6), ("observed_editor", 4), ("observed_v2", 5), ("full", 23)])
def test_profiles_filter_advertisement_and_dispatch(profile, count, monkeypatch):
    adapter = ExternalMCPAdapter(profile=profile)
    assert len(adapter.list_tools()) == count
    assert {tool["name"] for tool in adapter.list_tools()} == MCP_PROFILES[profile]
    assert len(registry.names()) == 23
    invoked = []
    monkeypatch.setattr(type(registry), "call", lambda self, name, **kw: invoked.append(name) or {"status": "ok"})
    for name in registry.names():
        result = adapter.call_tool(name, {})
        if name not in MCP_PROFILES[profile]:
            assert result["isError"] and name not in invoked
    # Explicit legacy and administrative calls succeed under full through the actual dispatch path.
    result = adapter.call_tool("patchdiff_get_target", {"target_file_id": str(uuid.uuid4())})
    assert bool(result.get("isError")) == (profile != "full")


def test_default_startup_environment_and_session_immutability(monkeypatch):
    monkeypatch.delenv("PATCHDIFF_MCP_PROFILE", raising=False)
    adapter = ExternalMCPAdapter()
    assert adapter.profile == "observed_v2" and len(adapter.list_tools()) == 5
    monkeypatch.setenv("PATCHDIFF_MCP_PROFILE", "full")
    assert len(adapter.list_tools()) == 5 and ExternalMCPAdapter().profile == "full"
    with pytest.raises(FrozenInstanceError): adapter.profile = "full"
    with pytest.raises(ValueError): ExternalMCPAdapter(profile="bad")
    monkeypatch.setenv("PATCHDIFF_MCP_PROFILE", "bad")
    with pytest.raises(ValueError): ExternalMCPAdapter()
    assert ExternalMCPAdapter(profile="observed").profile == "observed"


def test_batch_schemas_are_typed_bounded_and_mutually_exclusive():
    schemas = {item["name"]: item["inputSchema"] for item in ExternalMCPAdapter(profile="editor").list_tools()}
    observe = Draft202012Validator(schemas["patchdiff_observe_scope"])
    tid, bid, oid = (str(uuid.uuid4()) for _ in range(3))
    selector = {"target_file_id": tid, "selections": [{"symbol_name": "f", "kind": "function"}]}
    assert observe.is_valid(selector)
    for extra in ({"query": "f"}, {"symbol_name": "f"}, {"observation_id": oid}, {"kind": "function"}):
        assert not observe.is_valid({**selector, **extra})
    assert not observe.is_valid({**selector, "selections": [{}]})
    assert not observe.is_valid({**selector, "selections": [{"symbol_name": "f", "parent": "x"}]})
    assert not observe.is_valid({**selector, "selections": [{"symbol_name": f"f{i}"} for i in range(33)]})
    submit = Draft202012Validator(schemas["patchdiff_submit_observed_operations"])
    args = {"target_file_id": tid, "intent": "Update functions", "observation_bundle_id": bid,
            "expected_target_version": 0, "expected_current_hash": "0" * 64, "client_request_id": "test",
            "groups": [{"observation_id": oid, "operations": [{"op": "match", "match": "a", "replace": "b"}]}]}
    assert submit.is_valid(args)
    for field in ("observation_bundle_id", "groups", "client_request_id", "expected_current_hash", "expected_target_version"):
        missing = copy.deepcopy(args)
        missing.pop(field)
        assert not submit.is_valid(missing), field
    assert not submit.is_valid({**args, "operations": []})
    assert not submit.is_valid({**args, "observation_id": oid})
    single = {k: v for k, v in args.items() if k not in {"observation_bundle_id", "groups"}}
    single.update(observation_id=oid, operations=args["groups"][0]["operations"])
    assert submit.is_valid(single)
    insertion = copy.deepcopy(args)
    insertion["groups"][0]["operations"] = [{"op": "span", "start": 1, "end": 1, "expected_text": "", "replace": "!"}]
    assert not submit.is_valid(insertion)
    insertion["groups"][0]["operations"][0].update(expected_before="a", expected_after="b")
    assert submit.is_valid(insertion)


def test_profile_schema_sizes_are_actual_serialized_tools_list_bytes():
    sizes = {profile: len(json.dumps({"tools": ExternalMCPAdapter(profile=profile).list_tools()},
                                   ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
             for profile in MCP_PROFILES}
    assert sizes["unobserved"] < sizes["observed"] < sizes["editor"] < sizes["full"]
