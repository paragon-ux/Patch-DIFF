"""G2-2/G3-2 non-model controller through real stdio, isolated PostgreSQL, Waymark.

These scripted probes deliberately leave the primary task unsolved. They are
infrastructure tests with zero model calls, never comparative study outcomes.
"""
import asyncio
import copy
import hashlib
import json

import pytest

from app.core.config import settings
from evaluation.structural_retest import controller
from evaluation.structural_retest.mcp_session import MCPSession
from evaluation.structural_retest.synthetic import SyntheticHost
from evaluation.structural_retest.telemetry import verify_events


@pytest.mark.parametrize("arm", ["B", "C"])
def test_controller_real_stdio_fresh_database_rejection_idempotent_recovery_save_export_replay(tmp_path, arm):
    manifest = json.loads((controller.ROOT / "manifest.json").read_text())
    state = {}
    tool = "patchdiff_submit_edits" if arm == "B" else "patchdiff_submit_observed_operations"

    def observe(spec, results):
        return {"tool_calls": [{"id": "observe", "name": "patchdiff_observe_scope",
                                 "arguments": {"target_file_id": spec["targets"]["matrix_kernel.py"], "symbol_name": "execute_tile_kernel_07"}}]}

    def reject(spec, results):
        if arm == "C":
            state["observation_id"] = results[0]["result"]["observation_id"]
            state["current_hash"] = results[0]["result"]["target_current_hash"]
        args = {"target_file_id": spec["targets"]["matrix_kernel.py"], "intent": "Non-model rejection probe",
                "client_request_id": "probe-rejected", "expected_target_version": 0, "attempt": 1}
        if arm == "C":
            args.update(observation_id=state["observation_id"], expected_current_hash=state["current_hash"], operations=[{"op": "match", "match": "absent-probe-string", "replace": "ignored"}])
        else:
            args["edits"] = [{"match": "absent-probe-string", "replace": "ignored"}]
        return {"tool_calls": [{"id": "reject", "name": tool, "arguments": args}]}

    def accept(spec, results):
        rejected = results[0]["result"]
        assert rejected["status"] == "rejected"
        args = {"target_file_id": spec["targets"]["matrix_kernel.py"], "intent": "Non-model no-op/idempotency probe",
                "client_request_id": "probe-accepted", "expected_target_version": 0, "attempt": 2,
                "parent_pdcp_log_id": rejected["pdcp_log_id"]}
        if arm == "C":
            args.update(observation_id=state["observation_id"], expected_current_hash=state["current_hash"], operations=[{"op": "match", "match": "stride_offset = (block_id << 4) + lane_id", "replace": "stride_offset = (block_id << 4) + lane_id"}])
        else:
            args["edits"] = [{"match": 'FRAME_SYNC_STREAM = "HEADER::SYNC::SYNC::SYNC::SYNC::SYNC::TRAILER"',
                              "replace": 'FRAME_SYNC_STREAM = "HEADER::SYNC::SYNC::SYNC::SYNC::SYNC::TRAILER"'}]
        state["accepted_args"] = copy.deepcopy(args)
        return {"tool_calls": [{"id": "accept-lost", "name": tool, "arguments": args}]}

    def retry(spec, results):
        assert results[0]["result"]["status"] == "lost_response"
        return {"finished": True, "tool_calls": [{"id": "explicit-idempotent-retry", "name": tool, "arguments": copy.deepcopy(state["accepted_args"])}]}

    class LoseOneRealResponse(MCPSession):
        """Inject response loss AFTER the real PostgreSQL transaction commits."""
        async def call(self, name, args):
            result = await super().call(name, args)
            if name == tool and result.get("status") == "accepted" and not state.get("lost"):
                state["lost"] = result
                raise ConnectionError("synthetic lost response after real commit")
            return result

    async def go():
        scripts = ([observe] if arm == "C" else []) + [reject, accept, retry]
        host = SyntheticHost({arm: scripts})
        run = controller.Run(tmp_path / arm, arm, 1, manifest, host, await host.describe(), session_factory=LoseOneRealResponse)
        result = await run.execute({"admin_database_url": settings.database_url}, set())
        assert result["last_stage"] == "HIDDEN_ORACLE_EVALUATION", result
        assert result["measured_model_invocations"] == host.live_model_invocations == 0
        assert result["outcome"] == "failed" and not result["oracle"]["complete_correct"]
        assert run.budget.retries == 2
        assert len(run.targets) == len(set(run.targets.values())) == 5
        records = verify_events(tmp_path / arm / "events.jsonl")
        assert len([r for r in records if r["event"] == "disposable_database_created"]) == 1
        assert any(r["event"] == "jsonrpc_request" for r in records)
        audits = [r for r in records if r["event"] == "audit_integrity"]
        assert len(audits) == 5
        audit = next(r for r in audits if r["target_file_id"] == run.targets["matrix_kernel.py"])
        attempts = audit["history"]["patchdiff_get_pdcp_log"]
        assert len(attempts) == 2 and {a["status"] for a in attempts} == {"accepted", "rejected"}
        accepted = next(a for a in attempts if a["status"] == "accepted")
        assert accepted["pdcp_log_id"] == state["lost"]["pdcp_log_id"]
        assert accepted["after_version"] == 1
        if arm == "C":
            assert accepted["diagnostic"]["observation_id"] == state["observation_id"]
        for name, data in run.sources.items():
            assert (run.exports / name).read_bytes() == data  # No-op only; original EOL preserved.
        replayed = [r for r in records if r["event"] == "tool_end" and r["tool_name"] == "patchdiff_replay"]
        assert len(replayed) == 5 and all(r["result"]["materialized_state_matches"] for r in replayed)
        assert not list(run.visible.iterdir())
    asyncio.run(go())


def test_real_mcp_canonicalization_eol_and_server_strict_mode(tmp_path):
    async def go():
        evidence = controller.Evidence(tmp_path / "events.jsonl", {"synthetic": True})
        url = await controller.disposable_database(settings.database_url, evidence)
        session = MCPSession(url, "C")
        try:
            await session.start()
            sources = {"crlf.py": b'def sample():\r\n    return 1\r\n'}
            targets = await session.initialize(sources, session.call)
            target_id = targets["crlf.py"]
            rejected = await session.call("patchdiff_submit_edits", {"target_file_id": target_id, "intent": "strict bypass probe",
                        "expected_target_version": 0, "client_request_id": "strict-probe", "edits": [{"match": "return 1", "replace": "return 2"}]})
            assert rejected["status"] == "rejected" and rejected["code"] == "OBSERVATION_REQUIRED"
            exported = await session.call("patchdiff_export_target", {"target_file_id": target_id, "format": "original_eol"})
            assert exported["content"].encode() == sources["crlf.py"]
            assert exported["content_sha256"] == hashlib.sha256(sources["crlf.py"]).hexdigest()
        finally:
            await session.close()
            evidence.emit("archive_complete")
            evidence.close()
    asyncio.run(go())
