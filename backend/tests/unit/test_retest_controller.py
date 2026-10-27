"""Deterministic non-model orchestration faults; real MCP is tested separately."""
import asyncio
import copy
import hashlib
import json
import uuid

import pytest

from evaluation.structural_retest import controller
from evaluation.structural_retest.host_adapter import TOOLS
from evaluation.structural_retest.mcp_session import MCPSession, eol_facts
from evaluation.structural_retest.native import NativeTools
from evaluation.structural_retest.synthetic import SyntheticHost, description
from evaluation.structural_retest.telemetry import verify_events


class FakeSession(MCPSession):
    """Synthetic transport, never passed off as real MCP evidence."""
    fault = None
    created = []

    def __init__(self, url, arm):
        self.arm, self.targets, self.documents = arm, {}, {}
        self.process = None
        self.schemas = {"tools": [{"name": name} for name in TOOLS[arm]]}
        self.calls = []
        self.created.append(self)

    async def start(self):
        pass

    async def close(self):
        pass

    async def call(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if name == self.fault:
            return {"status": "error"}
        if name == "patchdiff_initialize_target":
            target = str(uuid.uuid4())
            self.documents[target] = args
            return {"status": "ok", "target_file_id": target, "version": 0,
                    "current_hash": hashlib.sha256(args["content"].encode()).hexdigest()}
        if name == "patchdiff_get_target":
            doc = self.documents[args["target_file_id"]]
            return {"status": "ok", "current_content": doc["content"], "version": 0,
                    "current_hash": hashlib.sha256(doc["content"].encode()).hexdigest(), "source_line_endings": eol_facts(doc["content"].encode())}
        if name == "patchdiff_save":
            return {"status": "saved"}
        if name == "patchdiff_export_target":
            content = self.documents[args["target_file_id"]]["content"]
            return {"status": "ok", "content": content, "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "source_line_endings": eol_facts(content.encode())}
        if name == "patchdiff_replay":
            return {"status": "success", "materialized_state_matches": True,
                    "materialized_state_checks": {key: True for key in ("content_matches", "stored_hash_matches", "recomputed_hash_matches", "version_matches")}}
        if name in {"patchdiff_get_pdcp_log", "patchdiff_get_manifest_ledger"}:
            return {"entries": [], "has_more": False, "next_sequence": None}
        if name == "patchdiff_read_target":
            return {"status": "ok", "content": "synthetic"}
        if name in controller.EDIT_TOOLS:
            return {"status": "accepted"}
        raise AssertionError(name)


async def fake_database(url, evidence):
    return "synthetic-isolated-" + str(uuid.uuid4())


@pytest.fixture
def manifest():
    return json.loads((controller.ROOT / "manifest.json").read_text())


def run_one(tmp_path, manifest, host, arm="B", session=FakeSession, clock=None):
    async def go():
        info = await host.describe()
        kwargs = {"clock": clock} if clock else {}
        run = controller.Run(tmp_path / "run", arm, 1, manifest, host, info,
                             database_factory=fake_database, session_factory=session, **kwargs)
        return await run.execute({"admin_database_url": "synthetic"}, set())
    return asyncio.run(go())


def test_balanced_order_fresh_contexts_hidden_inputs_and_failure_denominator(tmp_path, manifest):
    host = SyntheticHost()
    summary = asyncio.run(controller.run_study(tmp_path / "study", manifest, host, {"admin_database_url": "synthetic"},
                                              database_factory=fake_database, session_factory=FakeSession))
    assert [(r["replicate"], r["arm"]) for r in summary["results"]] == [(i, a) for i, order in enumerate(("ABC", "BCA", "CAB"), 1) for a in order]
    assert summary["scheduled"] == summary["archived"] == len(summary["results"]) == len(host.contexts) == 9
    assert summary["measured_model_invocations"] == 0 and summary["comparative_results"] is False
    assert all(r["outcome"] == "failed" and r["last_stage"] == "HIDDEN_ORACLE_EVALUATION" for r in summary["results"])
    assert len((tmp_path / "study/runs.jsonl").read_text().splitlines()) == 9
    for spec in host.contexts.values():
        assert "reference" not in json.dumps(spec) and "expected_files" not in json.dumps(spec)
        visible = tmp_path / "study" / f"r{spec['replicate']}-{spec['arm']}" / "agent-files"
        assert len(list(visible.iterdir())) == (5 if spec["arm"] == "A" else 0)
        assert spec["task"] == (controller.ROOT / "primary/prompts/TASK.md").read_text()
        assert spec["permissions"]["evaluator_access"] is False
    for item in summary["results"]:
        records = verify_events(tmp_path / "study" / item["run_id"] / "events.jsonl")
        assert [r["stage"] for r in records if r["event"] == "stage"] == list(controller.STAGES[1:])


@pytest.mark.parametrize("tool", ["edit_file", "patchdiff_submit_observed_operations", "run_command"])
def test_arm_b_rejects_unauthorized_before_dispatch(tmp_path, manifest, tool):
    host = SyntheticHost({"B": [{"finished": True, "tool_calls": [{"id": "bad", "name": tool, "arguments": {}}]}]})
    result = run_one(tmp_path, manifest, host)
    assert any(f["classification"] == "PermissionError" for f in result["failures"])
    assert all(name != tool for name, args in FakeSession.created[-1].calls)
    assert "unauthorized_rejected" in (tmp_path / "run/events.jsonl").read_text()


def test_cross_arm_target_rejected(tmp_path, manifest):
    host = SyntheticHost({"B": [{"finished": True, "tool_calls": [{"id": "bad", "name": "patchdiff_read_target", "arguments": {"target_file_id": str(uuid.uuid4())}}]}]})
    result = run_one(tmp_path, manifest, host)
    assert any("does not belong" in f["detail"] for f in result["failures"])
    assert all(name != "patchdiff_read_target" for name, args in FakeSession.created[-1].calls)


@pytest.mark.parametrize("arm,tool", [("A", "patchdiff_read_target"), ("C", "patchdiff_submit_edits"), ("C", "edit_file")])
def test_other_arm_tool_routes_cannot_bypass_permissions(tmp_path, manifest, arm, tool):
    result = run_one(tmp_path, manifest, SyntheticHost({arm: [{"finished": True, "tool_calls": [{"id": "forbidden", "name": tool, "arguments": {}}]}]}), arm=arm)
    assert any(f["classification"] == "PermissionError" for f in result["failures"])
    assert "unauthorized_rejected" in (tmp_path / "run/events.jsonl").read_text()


def test_reused_host_context_is_preserved_as_failed_run(tmp_path, manifest):
    class Reused(SyntheticHost):
        async def open_context(self, specification):
            context = await super().open_context(specification)
            self.contexts["reused"] = self.contexts[context]
            self.turns["reused"] = self.turns[context]
            return "reused"
    host = Reused()
    summary = asyncio.run(controller.run_study(tmp_path / "study", manifest, host, {"admin_database_url": "synthetic"},
                                              database_factory=fake_database, session_factory=FakeSession))
    assert summary["archived"] == 9
    assert sum(any("reused a context" in f["detail"] for f in r["failures"]) for r in summary["results"]) == 8


@pytest.mark.parametrize("fault,stage", [("patchdiff_save", "SAVE_AND_EXPORT"), ("patchdiff_export_target", "SAVE_AND_EXPORT"), ("patchdiff_replay", "REPLAY_VALIDATION")])
def test_save_export_replay_failure_archived_without_repair(tmp_path, manifest, fault, stage):
    class Broken(FakeSession):
        pass
    Broken.fault = fault
    result = run_one(tmp_path, manifest, SyntheticHost(), session=Broken)
    assert result["last_stage"] == stage and result["outcome"] == "failed"
    assert any(f["stage"] == stage for f in result["failures"])
    assert verify_events(tmp_path / "run/events.jsonl")[-1]["result"]["archived"]


def test_missing_usage_and_response_model_mismatch_preserved(tmp_path, manifest):
    for index, response in enumerate(({"usage": {}}, {"model_id": "wrong"})):
        result = run_one(tmp_path / str(index), manifest, SyntheticHost({"B": [{"finished": True, **response}]}))
        assert result["agent_outcome"] == "failed" and result["failures"]
        assert result["last_stage"] == "HIDDEN_ORACLE_EVALUATION"


def test_call_budget_stops_dispatch_at_96(tmp_path, manifest):
    def calls(spec, results):
        target_id = next(iter(spec["targets"].values()))
        return {"finished": True, "tool_calls": [{"id": str(i), "name": "patchdiff_read_target", "arguments": {"target_file_id": target_id}} for i in range(97)]}
    result = run_one(tmp_path, manifest, SyntheticHost({"B": [calls]}))
    assert result["agent_outcome"] == "budget_exhausted"
    assert len([n for n, a in FakeSession.created[-1].calls if n == "patchdiff_read_target"]) == 96


def test_wall_clock_enforced_after_provider_response(tmp_path, manifest):
    clock = [0]
    def consume_time(spec, results):
        clock[0] = 601
        return {"finished": True}
    result = run_one(tmp_path, manifest, SyntheticHost({"B": [consume_time]}), clock=lambda: clock[0])
    assert result["agent_outcome"] == "budget_exhausted"
    assert any("wall_clock" in f["detail"] for f in result["failures"])


def test_tool_timeout_cancels_without_automatic_retry(tmp_path, manifest):
    manifest["conditions"]["tool_timeout_seconds"] = .01  # Synthetic test clock only.
    class Slow(FakeSession):
        async def call(self, name, args):
            if name == "patchdiff_read_target":
                self.calls.append((name, args))
                await asyncio.sleep(.1)
            return await super().call(name, args)
    def call(spec, results):
        return {"finished": True, "tool_calls": [{"id": "read", "name": "patchdiff_read_target", "arguments": {"target_file_id": next(iter(spec["targets"].values()))}}]}
    result = run_one(tmp_path, manifest, SyntheticHost({"B": [call]}), session=Slow)
    assert any(f["classification"] == "TimeoutError" for f in result["failures"])
    assert len([n for n, a in Slow.created[-1].calls if n == "patchdiff_read_target"]) == 1


@pytest.mark.parametrize("arm", ["B", "C"])
def test_explicit_lost_response_retry_keeps_identical_request_key(tmp_path, manifest, arm):
    class LostOnce(FakeSession):
        async def call(self, name, args):
            if name in controller.EDIT_TOOLS:
                self.calls.append((name, copy.deepcopy(args)))
                if len([n for n, a in self.calls if n in controller.EDIT_TOOLS]) == 1:
                    raise ConnectionError("synthetic lost response AFTER commit")
                return {"status": "accepted", "pdcp_log_id": "same-idempotent-log", "version": 1}
            return await super().call(name, args)
    args = {}
    def first(spec, results):
        args.update({"target_file_id": next(iter(spec["targets"].values())), "client_request_id": "stable-key", "intent": "synthetic", "attempt": 1})
        if arm == "C":
            args["observation_id"] = "synthetic-observation"
        return {"tool_calls": [{"id": "first", "name": "patchdiff_submit_edits" if arm == "B" else "patchdiff_submit_observed_operations", "arguments": copy.deepcopy(args)}]}
    def second(spec, results):
        assert results[0]["result"]["status"] == "lost_response"
        return {"finished": True, "tool_calls": [{"id": "retry", "name": "patchdiff_submit_edits" if arm == "B" else "patchdiff_submit_observed_operations", "arguments": copy.deepcopy(args)}]}
    async def go():
        host = SyntheticHost({arm: [first, second]})
        run = controller.Run(tmp_path / "run", arm, 1, manifest, host, await host.describe(), database_factory=fake_database, session_factory=LostOnce)
        if arm == "C":
            run.observations.add("synthetic-observation")
        result = await run.execute({"admin_database_url": "synthetic"}, set())
        assert run.budget.retries == 1
        edits = [a for n, a in LostOnce.created[-1].calls if n in controller.EDIT_TOOLS]
        assert len(edits) == 2 and edits[0] == edits[1]
        assert result["failures"] and result["archived"]
    asyncio.run(go())


def test_live_run_api_refuses_before_model_or_staging(tmp_path, manifest):
    class Unverified(SyntheticHost):
        synthetic = False
    with pytest.raises(ValueError, match="disabled/unverified"):
        asyncio.run(controller.run_study(tmp_path / "forbidden", manifest, Unverified(), {"gate_2": "approved"}))
    assert not (tmp_path / "forbidden").exists()


def test_native_replace_all_and_confined_read_semantics(tmp_path):
    (tmp_path / "x.py").write_bytes(b"same same\n")
    tools = NativeTools(tmp_path, {"x.py"}, "unused")
    result = asyncio.run(tools.call("edit_file", {"Path": "x.py", "Target": "same", "Replacement": "new"}))
    assert result["occurrences_replaced"] == 2 and (tmp_path / "x.py").read_bytes() == b"new new\n"
    for args in ({"Path": "../gold.py", "Target": "x", "Replacement": "y"}, {"Path": "TASK.md", "Target": "x", "Replacement": "y"}):
        with pytest.raises(PermissionError):
            asyncio.run(tools.call("edit_file", args))
    with pytest.raises(PermissionError):
        asyncio.run(tools.call("run_command", {"command": "rtk read x.py; python evil.py"}))


def test_all_arm_binding_preflight_rejects_schema_mismatch_before_context(tmp_path, monkeypatch):
    async def native_ok(binding, configured):
        return []
    monkeypatch.setattr(controller, "verify_binding", native_ok)
    info = description()
    info["arms"]["B"]["mcp_schema_sha256"] = "matching"
    info["arms"]["C"]["mcp_schema_sha256"] = "stale"
    errors = asyncio.run(controller.tool_binding_errors(info, {}, "matching"))
    assert errors == ["C: actual MCP schema differs from reviewed binding"]


def test_source_pin_tamper_fails_before_context_or_mcp(tmp_path, manifest):
    manifest["controller"]["source_sha256"]["controller.py"] = "0" * 64
    host = SyntheticHost()
    result = run_one(tmp_path, manifest, host)
    assert not host.contexts and result["last_stage"] == "PREPARED"
    assert any("source pin mismatch" in f["detail"] for f in result["failures"])
