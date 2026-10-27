"""Categories C, D, and E integration tests for guarded observed submission, concurrency, replay, and strict mode."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

from app.core.config import strict_observation_mode
from app.mcp import tools  # noqa: F401
from app.mcp.server import registry
from app.services.pdcp_service import submit_observed_operations
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    TargetScopeObservations,
)
from backend.tests.integration.helpers import pdcp_for


def _init_tenants_target() -> dict:
    content = (
        json.dumps(
            {
                "tenants": [
                    {"id": "ten_006", "tier": "standard", "quota": 100},
                    {"id": "ten_013", "tier": "standard", "quota": 100},
                    {"id": "ten_018", "tier": "standard", "quota": 100},
                ]
            },
            indent=2,
        )
        + "\n"
    )
    return registry.call(
        "patchdiff_initialize_target",
        filename="tenants.json",
        content=content,
        content_type="application/json",
    )


def test_observed_submission_rejects_and_logs_invalid_cross_target_and_stale_observations() -> None:
    target_a = _init_tenants_target()
    target_b = _init_tenants_target()
    tid_a = target_a["target_file_id"]
    tid_b = target_b["target_file_id"]

    obs_a = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid_a,
        symbol_name="tenants[ten_013]",
    )
    obs_b = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid_b,
        symbol_name="tenants[ten_013]",
    )
    assert obs_a["status"] == "observed" and obs_b["status"] == "observed"

    # 1. Missing observation_id
    missing_obs = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id=None,
        intent="Missing observation",
        expected_target_version=0,
        expected_current_hash=target_a["current_hash"],
        operations=[{"op": "match", "match": '"quota": 100', "replace": '"quota": 250'}],
    )
    assert missing_obs["status"] == "rejected"
    assert missing_obs["code"] == "OBSERVATION_REQUIRED"
    assert missing_obs["pdcp_log_id"] is not None

    # 2. Malformed observation_id
    malformed_obs = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id="not-a-uuid",
        intent="Malformed observation",
        expected_target_version=0,
        expected_current_hash=target_a["current_hash"],
        operations=[{"op": "match", "match": '"quota": 100', "replace": '"quota": 250'}],
    )
    assert malformed_obs["status"] == "rejected"
    assert malformed_obs["code"] == "INVALID_OBSERVATION_ID"
    assert malformed_obs["pdcp_log_id"] is not None

    # 3. Unknown / forged observation_id
    forged_obs = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id=str(uuid.uuid4()),
        intent="Forged observation",
        expected_target_version=0,
        expected_current_hash=target_a["current_hash"],
        operations=[{"op": "match", "match": '"quota": 100', "replace": '"quota": 250'}],
    )
    assert forged_obs["status"] == "rejected"
    assert forged_obs["code"] == "UNKNOWN_OBSERVATION_ID"
    assert forged_obs["pdcp_log_id"] is not None

    # 4. Cross-target observation_id
    cross_obs = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id=obs_b["observation_id"],
        intent="Cross-target observation",
        expected_target_version=0,
        expected_current_hash=target_a["current_hash"],
        operations=[{"op": "match", "match": '"quota": 100', "replace": '"quota": 250'}],
    )
    assert cross_obs["status"] == "rejected"
    assert cross_obs["code"] == "OBSERVATION_TARGET_MISMATCH"
    assert cross_obs["pdcp_log_id"] is not None

    # 5. Stale observation after a no-op accepted edit (version 0 -> 1, hash unchanged!)
    noop_obs = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid_a,
        symbol_name="tenants[ten_006]",
    )
    noop_accept = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id=noop_obs["observation_id"],
        intent="No-op edit bumping version",
        expected_target_version=0,
        expected_current_hash=target_a["current_hash"],
        operations=[{"op": "match", "match": '"quota": 100', "replace": '"quota": 100'}],
    )
    assert noop_accept["status"] == "accepted"
    assert noop_accept["version"] == 1
    assert noop_accept["current_hash"] == target_a["current_hash"]

    # Now obs_a (issued at version 0) must be rejected even though current_hash is identical!
    stale_after_noop = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id=obs_a["observation_id"],
        intent="Attempt with version-0 observation at version 1",
        expected_target_version=1,
        expected_current_hash=noop_accept["current_hash"],
        operations=[{"op": "match", "match": '"quota": 100', "replace": '"quota": 250'}],
    )
    assert stale_after_noop["status"] == "rejected"
    assert stale_after_noop["code"] == "STALE_OBSERVATION_VERSION"
    assert stale_after_noop["pdcp_log_id"] is not None

    # 6. Stale observation after ABA edit (A -> B -> A: hash returns to v0 hash, version is 3)
    obs_v1 = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid_a,
        symbol_name="tenants[ten_018]",
    )
    obs_to_b = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid_a,
        symbol_name="tenants[ten_006]",
    )
    step_b = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id=obs_to_b["observation_id"],
        intent="Change A -> B",
        expected_target_version=1,
        expected_current_hash=noop_accept["current_hash"],
        operations=[{"op": "match", "match": '"quota": 100', "replace": '"quota": 999'}],
    )
    assert step_b["status"] == "accepted" and step_b["version"] == 2

    obs_to_a = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid_a,
        symbol_name="tenants[ten_006]",
    )
    step_a = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id=obs_to_a["observation_id"],
        intent="Change B -> A",
        expected_target_version=2,
        expected_current_hash=step_b["current_hash"],
        operations=[{"op": "match", "match": '"quota": 999', "replace": '"quota": 100'}],
    )
    assert step_a["status"] == "accepted" and step_a["version"] == 3
    assert step_a["current_hash"] == target_a["current_hash"]

    aba_rejected = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid_a,
        observation_id=obs_v1["observation_id"],
        intent="Attempt with pre-ABA observation_id",
        expected_target_version=3,
        expected_current_hash=step_a["current_hash"],
        operations=[{"op": "match", "match": '"quota": 100', "replace": '"quota": 500'}],
    )
    assert aba_rejected["status"] == "rejected"
    assert aba_rejected["code"] == "STALE_OBSERVATION_VERSION"
    assert aba_rejected["pdcp_log_id"] is not None


def test_observed_submission_enforces_scope_bounds_and_rolls_back_atomically() -> None:
    target = _init_tenants_target()
    tid = target["target_file_id"]

    with SessionLocal() as session:
        full_text = session.get(CloudTargetFiles, uuid.UUID(tid)).current_content

    obs = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid,
        symbol_name="tenants[ten_013]",
    )
    assert obs["status"] == "observed"
    obs_id = obs["observation_id"]
    s_start, s_end = obs["scope_start"], obs["scope_end"]

    # 1. Span before scope_start
    before_pos = full_text.index('"ten_006"')
    assert before_pos < s_start
    span_before = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Edit before scope",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        operations=[
            {
                "op": "span",
                "start": before_pos,
                "end": before_pos + len('"ten_006"'),
                "expected_text": '"ten_006"',
                "replace": '"ten_006_hacked"',
            }
        ],
    )
    assert span_before["status"] == "rejected"
    assert span_before["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"
    assert span_before["failure_reason"] == "span_out_of_bounds"

    # 2. Span after scope_end
    after_pos = full_text.index('"ten_018"')
    assert after_pos >= s_end
    span_after = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Edit after scope",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        operations=[
            {
                "op": "span",
                "start": after_pos,
                "end": after_pos + len('"ten_018"'),
                "expected_text": '"ten_018"',
                "replace": '"ten_018_hacked"',
            }
        ],
    )
    assert span_after["status"] == "rejected"
    assert span_after["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"

    # 3. Span crossing scope_start boundary
    crossing_span = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Span crossing scope_start",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        operations=[
            {
                "op": "span",
                "start": s_start - 2,
                "end": s_start + 5,
                "expected_text": full_text[s_start - 2 : s_start + 5],
                "replace": "X",
            }
        ],
    )
    assert crossing_span["status"] == "rejected"
    assert crossing_span["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"

    # 4. Match operation whose only occurrence lies outside [scope_start, scope_end)
    match_outside = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Match ten_006 while observing ten_013",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        operations=[{"op": "match", "match": '"id": "ten_006"', "replace": '"id": "ten_999"'}],
    )
    assert match_outside["status"] == "rejected"
    assert match_outside["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"
    assert match_outside["failure_reason"] == "span_out_of_bounds"

    # 5. Match operation crossing scope_end boundary
    boundary_str = full_text[s_end - 4 : s_end + 4]
    match_crossing = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Match crossing scope_end",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        operations=[{"op": "match", "match": boundary_str, "replace": boundary_str}],
    )
    assert match_crossing["status"] == "rejected"
    assert match_crossing["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"

    # 6. Wrong expected_text inside observed scope
    wrong_expected = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Wrong expected_text inside scope",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        operations=[
            {
                "op": "span",
                "start": s_start,
                "end": s_start + 1,
                "expected_text": "WRONG",
                "replace": "{",
            }
        ],
    )
    assert wrong_expected["status"] == "rejected"
    assert wrong_expected["failure_reason"] == "span_expected_text_mismatch"

    # 7. Multi-op atomicity: op 1 succeeds inside scope, op 2 fails outside scope -> full rollback
    multi_op = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Op 1 inside scope, Op 2 outside scope",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        operations=[
            {"op": "match", "match": '"quota": 100', "replace": '"quota": 777'},
            {"op": "match", "match": '"id": "ten_018"', "replace": '"id": "ten_888"'},
        ],
    )
    assert multi_op["status"] == "rejected"
    assert multi_op["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"

    with SessionLocal() as session:
        unchanged = session.get(CloudTargetFiles, uuid.UUID(tid))
        assert unchanged.version == 0
        assert unchanged.current_content == full_text


def test_overlapping_ambiguity_inside_observed_scope_is_rejected() -> None:
    py_init = registry.call(
        "patchdiff_initialize_target",
        filename="overlap.py",
        content='PATTERN = "ababa"\n',
        content_type="text/x-python",
    )
    tid = py_init["target_file_id"]
    obs = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid,
        symbol_name="PATTERN",
        kind="variable",
    )
    assert obs["status"] == "observed"

    overlapping = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs["observation_id"],
        intent="Ambiguous overlapping match inside scope",
        expected_target_version=0,
        expected_current_hash=py_init["current_hash"],
        operations=[{"op": "match", "match": "aba", "replace": "xyz"}],
    )
    assert overlapping["status"] == "rejected"
    assert overlapping["failure_reason"] == "match_ambiguous"


def test_scoped_disambiguation_save_export_replay_and_idempotency() -> None:
    # Notice: '"tier": "standard"' and '"quota": 100' appear 3 times in tenants.json (once per tenant),
    # so a file-wide match without occurrence_index would fail with match_ambiguous.
    # Inside tenants[ten_013]'s observed scope, they are unique!
    target = _init_tenants_target()
    tid = target["target_file_id"]

    obs = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid,
        symbol_name="tenants[ten_013]",
    )
    assert obs["status"] == "observed"
    obs_id = obs["observation_id"]

    accepted = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Upgrade ten_013 tier and quota within observed scope",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        client_request_id="req-ten-013-upgrade",
        operations=[
            {"op": "match", "match": '"tier": "standard"', "replace": '"tier": "enterprise"'},
            {"op": "match", "match": '"quota": 100', "replace": '"quota": 500'},
        ],
    )
    assert accepted["status"] == "accepted"
    assert accepted["version"] == 1
    assert accepted["manifest_entries_added"] == 2
    assert accepted["deduplicated"] is False

    # Idempotent retry with same client_request_id and same observation_id recovers accepted result
    dedup = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_id,
        intent="Upgrade ten_013 tier and quota within observed scope",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        client_request_id="req-ten-013-upgrade",
        operations=[
            {"op": "match", "match": '"tier": "standard"', "replace": '"tier": "enterprise"'},
            {"op": "match", "match": '"quota": 100', "replace": '"quota": 500'},
        ],
    )
    assert dedup["status"] == "accepted"
    assert dedup["deduplicated"] is True
    assert dedup["pdcp_log_id"] == accepted["pdcp_log_id"]

    # Reusing the same client_request_id with a different observation_id is rejected as request_key_conflict
    obs_other = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid,
        symbol_name="tenants[ten_006]",
    )
    conflict = registry.call(
        "patchdiff_submit_observed_operations",
        target_file_id=tid,
        observation_id=obs_other["observation_id"],
        intent="Upgrade ten_013 tier and quota within observed scope",
        expected_target_version=0,
        expected_current_hash=target["current_hash"],
        client_request_id="req-ten-013-upgrade",
        operations=[
            {"op": "match", "match": '"tier": "standard"', "replace": '"tier": "enterprise"'},
            {"op": "match", "match": '"quota": 100', "replace": '"quota": 500'},
        ],
    )
    assert conflict["status"] == "rejected"
    assert conflict["code"] == "request_key_conflict"

    # Verify DB linkage, SAVE, export, and deterministic replay
    with SessionLocal() as session:
        obs_row = session.get(TargetScopeObservations, uuid.UUID(obs_id))
        assert str(obs_row.accepted_pdcp_log_id) == accepted["pdcp_log_id"]
        ledger_rows = (
            session.query(AppendOnlyManifestLedger)
            .filter_by(pdcp_log_id=uuid.UUID(accepted["pdcp_log_id"]))
            .all()
        )
        assert len(ledger_rows) == 2

    saved = registry.call(
        "patchdiff_save",
        target_file_id=tid,
        expected_target_version=1,
        export_after_save=True,
    )
    assert saved["status"] == "saved"
    parsed_export = json.loads(saved["export"]["content"])
    by_id = {t["id"]: t for t in parsed_export["tenants"]}
    assert by_id["ten_006"] == {"id": "ten_006", "tier": "standard", "quota": 100}
    assert by_id["ten_013"] == {"id": "ten_013", "tier": "enterprise", "quota": 500}
    assert by_id["ten_018"] == {"id": "ten_018", "tier": "standard", "quota": 100}

    replayed = registry.call("patchdiff_replay", target_file_id=tid)
    assert replayed["status"] == "success"
    assert replayed["materialized_state_matches"] is True
    assert replayed["accepted_transactions_replayed"] == 1


def test_concurrent_workers_racing_on_observed_submission_serialize_under_for_update() -> None:
    target = _init_tenants_target()
    tid = target["target_file_id"]
    h0 = target["current_hash"]

    obs_1 = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid,
        symbol_name="tenants[ten_006]",
    )
    obs_2 = registry.call(
        "patchdiff_observe_scope",
        target_file_id=tid,
        symbol_name="tenants[ten_018]",
    )
    assert obs_1["status"] == "observed" and obs_2["status"] == "observed"

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(obs_id: str, new_quota: int) -> None:
        barrier.wait(timeout=5.0)
        with SessionLocal() as session:
            res = submit_observed_operations(
                session,
                target_file_id=tid,
                observation_id=obs_id,
                intent=f"Concurrent quota update to {new_quota}",
                expected_target_version=0,
                expected_current_hash=h0,
                operations=[
                    {"op": "match", "match": '"quota": 100', "replace": f'"quota": {new_quota}'}
                ],
            )
            with lock:
                outcomes.append(res.status)

    t1 = threading.Thread(target=worker, args=(obs_1["observation_id"], 200))
    t2 = threading.Thread(target=worker, args=(obs_2["observation_id"], 300))
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert sorted(outcomes) == ["accepted", "rejected"]
    replayed = registry.call("patchdiff_replay", target_file_id=tid)
    assert replayed["status"] == "success" and replayed["materialized_state_matches"] is True


def test_strict_observation_mode_blocks_all_unobserved_writes_and_allows_observed_writes() -> None:
    py_init = registry.call(
        "patchdiff_initialize_target",
        filename="strict_service.py",
        content='SERVICE_MODE = "legacy"\n',
        content_type="text/x-python",
    )
    tid = py_init["target_file_id"]
    h0 = py_init["current_hash"]

    # Seed one rejected attempt before strict mode so we have a valid parent log for request_regeneration
    seed_rej = registry.call(
        "patchdiff_submit_edits",
        target_file_id=tid,
        intent="Seed rejected attempt",
        expected_target_version=0,
        edits=[{"match": "nonexistent", "replace": "x"}],
    )
    assert seed_rej["status"] == "rejected"
    rejected_log_id = seed_rej["pdcp_log_id"]

    with strict_observation_mode(True):
        # 1. patchdiff_submit_edits rejected with OBSERVATION_REQUIRED
        r_edits = registry.call(
            "patchdiff_submit_edits",
            target_file_id=tid,
            intent="Unobserved submit_edits",
            expected_target_version=0,
            expected_current_hash=h0,
            edits=[{"match": '"legacy"', "replace": '"modern"'}],
        )
        assert r_edits["status"] == "rejected"
        assert r_edits["code"] == "OBSERVATION_REQUIRED"
        assert r_edits["pdcp_log_id"] is not None

        # 2. patchdiff_submit_operations rejected with OBSERVATION_REQUIRED
        r_ops = registry.call(
            "patchdiff_submit_operations",
            target_file_id=tid,
            intent="Unobserved submit_operations",
            expected_target_version=0,
            expected_current_hash=h0,
            operations=[{"op": "match", "match": '"legacy"', "replace": '"modern"'}],
        )
        assert r_ops["status"] == "rejected"
        assert r_ops["code"] == "OBSERVATION_REQUIRED"
        assert r_ops["pdcp_log_id"] is not None

        # 3. patchdiff_submit_replacement rejected with OBSERVATION_REQUIRED
        r_rep = registry.call(
            "patchdiff_submit_replacement",
            target_file_id=tid,
            intent="Unobserved submit_replacement",
            expected_target_version=0,
            expected_current_hash=h0,
            replacement='SERVICE_MODE = "modern"\n',
        )
        assert r_rep["status"] == "rejected"
        assert r_rep["code"] == "OBSERVATION_REQUIRED"
        assert r_rep["pdcp_log_id"] is not None

        # 4. patchdiff_submit_pdcp rejected with OBSERVATION_REQUIRED
        r_pdcp = registry.call(
            "patchdiff_submit_pdcp",
            target_file_id=tid,
            pdcp_content=pdcp_for(tid, ('"legacy"', '"modern"')),
            expected_target_version=0,
            expected_current_hash=h0,
        )
        assert r_pdcp["status"] == "rejected"
        assert r_pdcp["code"] == "OBSERVATION_REQUIRED"
        assert r_pdcp["pdcp_log_id"] is not None

        # 5. patchdiff_request_regeneration with regenerated_pdcp_content rejected with OBSERVATION_REQUIRED
        r_regen = registry.call(
            "patchdiff_request_regeneration",
            pdcp_log_id=rejected_log_id,
            regenerated_pdcp_content=pdcp_for(tid, ('"legacy"', '"modern"')),
            expected_target_version=0,
            expected_current_hash=h0,
        )
        assert r_regen["status"] == "rejected"
        assert r_regen["result"]["code"] == "OBSERVATION_REQUIRED"

        # 6. Observe + submit_observed_operations succeeds in strict mode!
        obs = registry.call(
            "patchdiff_observe_scope",
            target_file_id=tid,
            symbol_name="SERVICE_MODE",
            kind="variable",
        )
        assert obs["status"] == "observed"
        accepted = registry.call(
            "patchdiff_submit_observed_operations",
            target_file_id=tid,
            observation_id=obs["observation_id"],
            intent="Observed update in strict mode",
            expected_target_version=0,
            expected_current_hash=h0,
            operations=[{"op": "match", "match": '"legacy"', "replace": '"strict_ok"'}],
        )
        assert accepted["status"] == "accepted"
        assert accepted["version"] == 1

    # Outside strict mode, normal submit_edits works again
    normal_ok = registry.call(
        "patchdiff_submit_edits",
        target_file_id=tid,
        intent="Unobserved edit when strict mode is disabled",
        expected_target_version=1,
        expected_current_hash=accepted["current_hash"],
        edits=[{"match": '"strict_ok"', "replace": '"relaxed_ok"'}],
    )
    assert normal_ok["status"] == "accepted"
    assert normal_ok["version"] == 2


def test_stdio_mcp_subprocess_end_to_end_observe_and_strict_submit() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "backend")
    env["PATCHDIFF_STRICT_OBSERVATION_MODE"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-m", "app.mcp.external_adapter"],
        cwd=str(repo_root),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None

    def rpc(req_id: int, method: str, params: dict) -> dict:
        line = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()
        resp_line = proc.stdout.readline()
        assert resp_line, f"Subprocess exited early: {proc.stderr.read() if proc.stderr else ''}"
        return json.loads(resp_line)

    try:
        listed = rpc(1, "tools/list", {})
        tool_names = {t["name"] for t in listed["result"]["tools"]}
        assert "patchdiff_observe_scope" in tool_names
        assert "patchdiff_submit_observed_operations" in tool_names

        init_resp = rpc(
            2,
            "tools/call",
            {
                "name": "patchdiff_initialize_target",
                "arguments": {
                    "filename": "stdio_target.py",
                    "content": 'FRAME_SYNC_STREAM = "v1"\nOTHER = "v1"\n',
                    "content_type": "text/x-python",
                },
            },
        )
        init_payload = json.loads(init_resp["result"]["content"][0]["text"])
        tid = init_payload["target_file_id"]
        h0 = init_payload["current_hash"]

        # Unobserved submit_operations over stdio in strict mode -> OBSERVATION_REQUIRED
        unobs_resp = rpc(
            3,
            "tools/call",
            {
                "name": "patchdiff_submit_operations",
                "arguments": {
                    "target_file_id": tid,
                    "intent": "Unobserved over stdio",
                    "expected_target_version": 0,
                    "expected_current_hash": h0,
                    "operations": [{"op": "match", "match": '"v1"', "replace": '"v2"'}],
                },
            },
        )
        unobs_payload = json.loads(unobs_resp["result"]["content"][0]["text"])
        assert unobs_payload["status"] == "rejected"
        assert unobs_payload["code"] == "OBSERVATION_REQUIRED"

        # Observe FRAME_SYNC_STREAM over stdio
        obs_resp = rpc(
            4,
            "tools/call",
            {
                "name": "patchdiff_observe_scope",
                "arguments": {
                    "target_file_id": tid,
                    "symbol_name": "FRAME_SYNC_STREAM",
                    "kind": "variable",
                },
            },
        )
        obs_payload = json.loads(obs_resp["result"]["content"][0]["text"])
        assert obs_payload["status"] == "observed"
        obs_id = obs_payload["observation_id"]

        # E-2: exercise advertised insertion constraints through real stdio.
        observed_tool = next(t for t in listed["result"]["tools"] if t["name"] == "patchdiff_submit_observed_operations")
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(observed_tool["inputSchema"])
        at = obs_payload["scope_start"] + 1
        for position, guards, code in [
            (obs_payload["scope_start"], {"expected_before": "X", "expected_after": "F"}, "OPERATION_OUTSIDE_OBSERVED_SCOPE"),
            (obs_payload["scope_end"], {"expected_before": '"', "expected_after": "\n"}, "OPERATION_OUTSIDE_OBSERVED_SCOPE"),
            (at, {}, "OBSERVED_INSERTION_GUARDS_REQUIRED"),
            (at, {"expected_before": "X", "expected_after": "R"}, None),
            (at, {"expected_before": "XF", "expected_after": "R"}, "OPERATION_OUTSIDE_OBSERVED_SCOPE"),
        ]:
            arguments = {"target_file_id": tid, "observation_id": obs_id, "intent": "Negative insertion",
                         "expected_target_version": 0, "expected_current_hash": h0,
                         "operations": [{"op": "span", "start": position, "end": position,
                                         "expected_text": "", "replace": "!", **guards}]}
            assert validator.is_valid(arguments) is bool(guards)
            negative = rpc(40, "tools/call", {"name": "patchdiff_submit_observed_operations", "arguments": arguments})
            payload = json.loads(negative["result"]["content"][0]["text"])
            assert payload["status"] == "rejected" and payload["pdcp_log_id"]
            if code is not None:
                assert payload["code"] == code
            else:
                assert payload["failure_reason"] == "span_expected_text_mismatch"

        # Submit observed operation over stdio (disambiguating '"v1"' within FRAME_SYNC_STREAM!)
        sub_resp = rpc(
            5,
            "tools/call",
            {
                "name": "patchdiff_submit_observed_operations",
                "arguments": {
                    "target_file_id": tid,
                    "observation_id": obs_id,
                    "intent": "Update FRAME_SYNC_STREAM over stdio",
                    "expected_target_version": 0,
                    "expected_current_hash": h0,
                    "operations": [{"op": "match", "match": '"v1"', "replace": '"v2"'}],
                },
            },
        )
        sub_payload = json.loads(sub_resp["result"]["content"][0]["text"])
        assert sub_payload["status"] == "accepted"
        assert sub_payload["version"] == 1

        fresh = rpc(50, "tools/call", {"name": "patchdiff_observe_scope",
                                      "arguments": {"target_file_id": tid, "symbol_name": "FRAME_SYNC_STREAM"}})
        fresh_obs = json.loads(fresh["result"]["content"][0]["text"])
        positive_args = {"target_file_id": tid, "observation_id": fresh_obs["observation_id"],
                         "intent": "Guarded interior insertion", "expected_target_version": 1,
                         "expected_current_hash": fresh_obs["target_current_hash"],
                         "operations": [{"op": "span", "start": at, "end": at, "expected_text": "",
                                         "replace": "X", "expected_before": "F", "expected_after": "R"}]}
        validator.validate(positive_args)
        positive = rpc(51, "tools/call", {"name": "patchdiff_submit_observed_operations", "arguments": positive_args})
        assert json.loads(positive["result"]["content"][0]["text"])["status"] == "accepted"
        exported = rpc(52, "tools/call", {"name": "patchdiff_export_target", "arguments": {"target_file_id": tid}})
        assert json.loads(exported["result"]["content"][0]["text"])["content"] == 'FXRAME_SYNC_STREAM = "v2"\nOTHER = "v1"\n'
        with SessionLocal() as session:
            assert session.query(AppendOnlyPdcpLogs).filter_by(target_file_id=uuid.UUID(tid), status="rejected").count() == 6
            assert session.query(AppendOnlyManifestLedger).filter_by(target_file_id=uuid.UUID(tid)).count() == 2

        # Replay over stdio
        rep_resp = rpc(
            6,
            "tools/call",
            {"name": "patchdiff_replay", "arguments": {"target_file_id": tid}},
        )
        rep_payload = json.loads(rep_resp["result"]["content"][0]["text"])
        assert rep_payload["status"] == "success"
        assert rep_payload["materialized_state_matches"] is True
    finally:
        proc.stdin.close()
        proc.wait(timeout=5.0)
