"""G2-2-R1: actual child processes, fake provider only; no live execution approval.

The tests exercise the same per-run supervisor via explicitly synthetic BridgeHost
children. Only target MCP and native attestation are deterministic test doubles;
real MCP behavior remains covered by test_retest_controller_mcp.py.
"""
import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

from backend.tests.unit.test_retest_controller import FakeSession, fake_database
from evaluation.structural_retest import controller
from evaluation.structural_retest.host_adapter import BridgeHost
from evaluation.structural_retest.synthetic import SyntheticHost, description
from evaluation.structural_retest.telemetry import Budget, digest, verify_events

BRIDGE = Path(__file__).resolve().parents[1] / "fixtures/retest_host_bridge.py"


def trace(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def scenario(tmp_path, monkeypatch, *, first="noop", changed=None, startup_failure=False):
    info = description()
    manifest = json.loads((controller.ROOT / "manifest.json").read_text())
    conditions = copy.deepcopy(manifest["conditions"])
    bindings, budgets, hosts, factory_calls = [], [], [], []

    async def verify_bindings(actual, config, schema):
        bindings.append(digest(actual))
        return []
    monkeypatch.setattr(controller, "tool_binding_errors", verify_bindings)

    class SimulatedElapsedBudget(Budget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if not budgets and first == "timeout":
                # Simulate elapsed planning time, without changing the manifest's
                # 600-second budget or shrinking any subsequent run's allowance.
                self.started -= 599.5
            budgets.append(self)
    monkeypatch.setattr(controller, "Budget", SimulatedElapsedBudget)

    class FakeProviderBridge(BridgeHost):
        synthetic = True

    def factory():
        index = len(factory_calls)
        factory_calls.append(index)
        host_info = copy.deepcopy(info)
        if index == 1 and changed:
            changed(host_info)
        path = tmp_path / f"description-{index}.json"
        path.write_bytes((json.dumps(host_info) + "\n").encode())
        command = [sys.executable, str(BRIDGE), "--description", str(path), "--trace", str(tmp_path / f"bridge-{index}.jsonl"),
                   "--mode", first if index == 0 else "noop"]
        if index == 1 and startup_failure:
            command = [str(tmp_path / "missing-bridge-executable")]
        host = FakeProviderBridge(command)
        hosts.append(host)
        return host

    async def run():
        try:
            return await controller.run_study(tmp_path / "study", manifest, SyntheticHost(host_description=info),
                                              {"admin_database_url": "synthetic", "host_evidence": info}, host_factory=factory,
                                              database_factory=fake_database, session_factory=FakeSession)
        finally:
            # Leak assertion precedes emergency cleanup so the test cannot hide
            # a controller failure by silently reaping its children itself.
            leaked = [host for host in hosts if host.process and host.process.returncode is None]
            for host in leaked:
                await host.close()
            assert not leaked, "controller leaked a host bridge"
    summary = asyncio.run(run())
    assert manifest["conditions"] == conditions
    assert summary["synthetic"] and summary["measured_model_invocations"] == 0
    assert [(r["replicate"], r["arm"]) for r in summary["results"]] == [(i, a) for i, order in enumerate(("ABC", "BCA", "CAB"), 1) for a in order]
    assert len((tmp_path / "study/runs.jsonl").read_text().splitlines()) == 9
    return summary, hosts, budgets, bindings


def test_timeout_isolated_from_next_verified_process_context_and_budget(tmp_path, monkeypatch):
    summary, hosts, budgets, bindings = scenario(tmp_path, monkeypatch, first="timeout")
    first, second = summary["results"][:2]
    assert summary["archived"] == 9 and len(hosts) == len(bindings) == len(budgets) == 9
    assert first["agent_outcome"] == "budget_exhausted" and first["failures"][0]["classification"] == "TimeoutError"
    assert second["agent_outcome"] == "finished" and not second["failures"]
    assert not first["oracle"]["complete_correct"] and not second["oracle"]["complete_correct"]
    assert hosts[0].process.pid != hosts[1].process.pid and all(h.process.returncode is not None for h in hosts)
    left, right = trace(tmp_path / "bridge-0.jsonl"), trace(tmp_path / "bridge-1.jsonl")
    assert left[0]["provider_session"] != right[0]["provider_session"]
    opens = [next(e for e in rows if e["event"] == "open") for rows in (left, right)]
    assert opens[0]["context_id"] != opens[1]["context_id"]
    turns1, turns2 = [[e for e in rows if e["event"] == "turn"] for rows in (left, right)]
    assert turns1[-1]["tool_results"] and turns2[0]["tool_results"] == []
    assert turns1[0]["limits"]["deadline_seconds"] < 1 and turns2[0]["limits"]["deadline_seconds"] > 590
    assert turns2[0]["limits"]["remaining_total_tokens"] == 16000
    assert budgets[0].calls == 1 and budgets[1].calls == budgets[1].retries == 0
    assert len({id(b) for b in budgets}) == 9 and len(set(bindings)) == 1
    events = verify_events(tmp_path / "study/r1-A/events.jsonl")
    assert sum(e["event"] == "archive_complete" for e in events) == 1
    assert any(e["event"] == "host_turn_timeout" for e in events)
    assert any(e["event"] == "host_process_reaped" and e["pid"] == hosts[0].process.pid for e in events)


def test_unexpected_bridge_exit_is_attributed_without_task_retry(tmp_path, monkeypatch):
    summary, hosts, budgets, bindings = scenario(tmp_path, monkeypatch, first="exit")
    first, second = summary["results"][:2]
    assert summary["archived"] == len(summary["results"]) == len(hosts) == 9
    assert first["agent_outcome"] == "failed" and first["failures"][0]["classification"] == "ConnectionError"
    assert hosts[0].process.returncode == 23
    assert second["agent_outcome"] == "finished" and not second["failures"]
    assert hosts[0].process.pid != hosts[1].process.pid
    records = trace(tmp_path / "bridge-0.jsonl")
    assert sum(e["event"] == "open" for e in records) == 1
    assert sum(e["event"] == "turn" for e in records) == 2  # no retry of the failed task
    assert any(e["event"] == "host_turn_disconnected" for e in verify_events(tmp_path / "study/r1-A/events.jsonl"))


@pytest.mark.parametrize("field", ["exact_provider_model_id", "effective_reasoning_setting", "host_version", "tool_permissions", "provider_evidence"])
def test_changed_replacement_attestation_blocks_all_unstarted_runs(tmp_path, monkeypatch, field):
    def changed(info):
        info["arms"]["B"][field] = ["edit_file"] if field == "tool_permissions" else {} if field == "provider_evidence" else "changed"
    summary, hosts, budgets, bindings = scenario(tmp_path, monkeypatch, first="exit", changed=changed)
    assert summary["outcome"] == "failed" and summary["requires_operator_review"]
    assert len(hosts) == summary["archived"] == 2
    assert summary["results"][1]["outcome"] == "blocked_by_host_preflight"
    assert not summary["results"][1]["execution_started"]
    assert not any(e["event"] == "open" for e in trace(tmp_path / "bridge-1.jsonl"))
    assert len(budgets) == len(bindings) == 1
    assert all(r["outcome"] == "not_started" and not r["execution_started"] and r["reason"] and "oracle" not in r for r in summary["results"][2:])
    assert not any((tmp_path / "study" / r["run_id"]).exists() for r in summary["results"][2:])


def test_failed_replacement_start_blocks_without_opening_context(tmp_path, monkeypatch):
    summary, hosts, budgets, bindings = scenario(tmp_path, monkeypatch, startup_failure=True)
    assert summary["outcome"] == "failed" and summary["requires_operator_review"]
    assert len(hosts) == summary["archived"] == 2 and hosts[1].process is None
    assert summary["results"][1]["outcome"] == "blocked_by_host_preflight"
    assert all(r["outcome"] == "not_started" for r in summary["results"][2:])


def test_dead_bridge_context_cleanup_cannot_replace_original_timeout(tmp_path, monkeypatch):
    summary, hosts, budgets, bindings = scenario(tmp_path, monkeypatch, first="timeout")
    failed = summary["results"][0]
    assert failed["failures"][0]["classification"] == "TimeoutError"
    assert len(failed["failures"]) == 1
    assert failed["cleanup_failures"][0]["classification"] == "ConnectionError"
    assert summary["results"][1]["agent_outcome"] == "finished" and hosts[0].process.returncode is not None
    events = verify_events(tmp_path / "study/r1-A/events.jsonl")
    assert any(e["event"] == "host_context_cleanup_failed" and e["secondary"] for e in events)
    assert sum(e["event"] == "archive_complete" for e in events) == 1


def test_normal_contexts_use_separate_processes_and_terminate_cleanly(tmp_path, monkeypatch):
    summary, hosts, budgets, bindings = scenario(tmp_path, monkeypatch)
    assert summary["archived"] == 9 and not summary["requires_operator_review"]
    assert len(hosts) == len(bindings) == len(set(h.process.pid for h in hosts)) == 9
    assert all(h.process.returncode == 0 for h in hosts)
    assert all(r["agent_outcome"] == "finished" and not r["failures"] and not r["cleanup_failures"] for r in summary["results"])
    for i in (0, 1):
        rows = trace(tmp_path / f"bridge-{i}.jsonl")
        assert [e["event"] for e in rows] == ["started", "describe", "open", "turn", "close", "eof"]
        events = verify_events(tmp_path / "study" / summary["results"][i]["run_id"] / "events.jsonl")
        assert next(e for e in events if e["event"] == "host_process_started")["startup_seconds"] >= 0
        assert next(e for e in events if e["event"] == "host_attestation_verified")["host_evidence_sha256"] == bindings[i]
        assert next(e for e in events if e["event"] == "host_process_reaped")["returncode"] == 0
