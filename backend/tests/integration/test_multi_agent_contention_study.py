"""Empirical Multi-Agent Contention and Concurrency Study for PatchDIFF.

Evaluates high-concurrency refactoring across three critical operational regimes:
1. Disjoint Parallel Workload: Concurrent non-overlapping target edits (baseline scaling).
2. Hotspot Contention Workload: High contention on a shared file with lineage-based retries.
3. Multi-Target Circular Dependency Workload: Deadlock-free cross-file transactions.
4. Deterministic Replay Verification: Complete cryptographic audit validation after contention.
"""

from __future__ import annotations

import concurrent.futures
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import select

import app.mcp.tools
from app.core.failures import FailureReason
from app.mcp.server import registry
from app.services.read_service import observe_target
from app.services.replay_service import replay_target
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyPdcpLogs, CloudTargetFiles


@pytest.fixture
def clean_project_id():
    return uuid.uuid4()


def _create_target(name: str, content: str, target_type: str = "text/x-python") -> dict[str, Any]:
    with SessionLocal() as session:
        t = initialize_target(session, filename=name, content=content, target_type=target_type)
        session.commit()
        return {
            "id": str(t.target_file_id),
            "uuid": t.target_file_id,
            "filename": name,
            "version": t.version,
            "hash": t.current_hash,
        }


def test_concurrent_disjoint_parallel_workload():
    """Verify that 4 concurrent workers editing distinct files achieve 100% first-pass commits."""
    num_workers = 4
    rounds_per_worker = 5
    targets = [
        _create_target(f"worker_module_{i}.py", f"# Module {i}\nCOUNTER = 0\n")
        for i in range(num_workers)
    ]

    def worker_task(worker_idx: int) -> list[dict[str, Any]]:
        target_info = targets[worker_idx]
        tid = target_info["id"]
        results = []
        for r in range(rounds_per_worker):
            with SessionLocal() as session:
                obs = observe_target(session, uuid.UUID(tid))
                assert obs is not None
                version = obs.current_version
                digest = obs.current_hash

            old_text = f"COUNTER = {r}"
            new_text = f"COUNTER = {r + 1}"
            res = registry.call(
                "patchdiff_submit_edits",
                target_file_id=tid,
                expected_target_version=version,
                expected_current_hash=digest,
                intent=f"Worker {worker_idx} increment to {r + 1}",
                edits=[{"match": old_text, "replace": new_text}],
            )
            results.append(res)
        return results

    start_time = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_task, i) for i in range(num_workers)]
        all_results = [f.result(timeout=20) for f in futures]
    duration_s = time.perf_counter() - start_time

    # Verify every transaction committed on first attempt without any rejections
    for worker_results in all_results:
        assert len(worker_results) == rounds_per_worker
        for res in worker_results:
            assert res["status"] == "accepted"

    # Verify each target reached expected final version and state
    with SessionLocal() as session:
        for i, target_info in enumerate(targets):
            obs = observe_target(session, uuid.UUID(target_info["id"]))
            assert obs is not None
            assert obs.current_version == rounds_per_worker
            assert f"COUNTER = {rounds_per_worker}" in obs.current_content

            # Replay audit history
            replay = replay_target(session, target_file_id=target_info["id"])
            assert replay.status == "success"
            assert replay.materialized_state_matches is True
            assert replay.accepted_transactions_replayed == rounds_per_worker

    assert duration_s > 0


def test_hotspot_contention_and_lineage_retry_recovery():
    """Verify that concurrent workers competing on a single hotspot file resolve via lineage retries.

    Four workers concurrently append distinct configuration keys to a shared settings file.
    When a worker experiences a version mismatch (due to an interleaved commit), it re-observes
    and retries with parent_pdcp_log_id and an incremented attempt counter until accepted.
    """
    initial_content = "# System Settings Hub\nSETTINGS = {}\n"
    target = _create_target("system_settings.py", initial_content)
    tid = target["id"]
    target_uuid = uuid.UUID(tid)

    num_workers = 4
    keys_per_worker = 3
    total_expected_commits = num_workers * keys_per_worker

    stats = {
        "initial_attempts": 0,
        "conflict_rejections": 0,
        "successful_commits": 0,
        "max_retry_depth": 0,
    }

    def agent_worker(worker_idx: int) -> list[dict[str, Any]]:
        local_results = []
        for k in range(keys_per_worker):
            key_name = f"WORKER_{worker_idx}_KEY_{k}"
            key_val = f"val_{worker_idx}_{k}"
            committed = False
            attempt = 1
            parent_log_id = None

            while not committed and attempt <= 10:
                with SessionLocal() as session:
                    obs = observe_target(session, target_uuid)
                    assert obs is not None
                    cur_ver = obs.current_version
                    cur_hash = obs.current_hash
                    cur_content = obs.current_content

                edit_proposal = {
                    "target_file_id": tid,
                    "expected_target_version": cur_ver,
                    "expected_current_hash": cur_hash,
                    "intent": f"Add {key_name} on attempt {attempt}",
                    "attempt": attempt,
                    "parent_pdcp_log_id": str(parent_log_id) if parent_log_id else None,
                    "edits": [
                        {
                            "match": "SETTINGS = {",
                            "replace": f"SETTINGS = {{\n    '{key_name}': '{key_val}',",
                        }
                    ],
                }

                stats["initial_attempts"] += 1
                res = registry.call("patchdiff_submit_edits", **edit_proposal)
                if res["status"] == "accepted":
                    committed = True
                    stats["successful_commits"] += 1
                    local_results.append({"key": key_name, "status": "accepted", "attempts": attempt})
                else:
                    assert res["failure_reason"] in (
                        FailureReason.TARGET_VERSION_MISMATCH.value,
                        FailureReason.TARGET_HASH_MISMATCH.value,
                        FailureReason.MATCH_AMBIGUOUS.value,
                    )
                    stats["conflict_rejections"] += 1
                    parent_log_id = res.get("pdcp_log_id")
                    attempt += 1
                    stats["max_retry_depth"] = max(stats["max_retry_depth"], attempt)
                    # Short backoff to stagger concurrent retries
                    time.sleep(0.01 * worker_idx)

            assert committed, f"Worker {worker_idx} failed to commit key {key_name} after {attempt} attempts"
        return local_results

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(agent_worker, i) for i in range(num_workers)]
        worker_outcomes = [f.result(timeout=30) for f in futures]

    assert stats["successful_commits"] == total_expected_commits
    # Verify that under concurrency, at least some conflict rejections occurred
    assert stats["conflict_rejections"] > 0, "Expected concurrency conflicts on shared hotspot target"

    # Verify database state and deterministic replay integrity
    with SessionLocal() as session:
        final_obs = observe_target(session, target_uuid)
        assert final_obs is not None
        assert final_obs.current_version == total_expected_commits

        # Check all keys present in final content
        for w in range(num_workers):
            for k in range(keys_per_worker):
                expected_key = f"WORKER_{w}_KEY_{k}"
                assert expected_key in final_obs.current_content

        # Full cryptographic replay from version 0 to final version
        replay = replay_target(session, target_file_id=tid)
        assert replay.status == "success"
        assert replay.materialized_state_matches is True
        assert replay.accepted_transactions_replayed == total_expected_commits

        # Verify audit ledger recorded both accepted and rejected logs
        logs = session.execute(
            select(AppendOnlyPdcpLogs)
            .where(AppendOnlyPdcpLogs.target_file_id == target_uuid)
            .order_by(AppendOnlyPdcpLogs.created_at.asc())
        ).scalars().all()

        accepted_logs = [log for log in logs if log.status == "accepted"]
        rejected_logs = [log for log in logs if log.status == "rejected"]
        assert len(accepted_logs) == total_expected_commits
        assert len(rejected_logs) == stats["conflict_rejections"]

        # Verify retry lineage links on rejected logs
        retried_logs = [log for log in logs if log.parent_pdcp_log_id is not None]
        assert len(retried_logs) > 0


def test_deadlock_free_circular_multi_target_contention():
    """Verify that concurrent multi-target refactorings with circular dependencies never deadlock.

    Four targets form a circular dependency graph:
      Agent 0: [Target 0, Target 1]
      Agent 1: [Target 1, Target 2]
      Agent 2: [Target 2, Target 3]
      Agent 3: [Target 3, Target 0]

    Because PatchDIFF acquires locks via canonical UUID sort order:
      SELECT ... FOR UPDATE ORDER BY target_file_id ASC
    deadlocks are mathematically precluded regardless of caller parameter order.
    """
    targets = [
        _create_target(f"service_node_{i}.py", f"# Node {i}\nVALUE = 100\n")
        for i in range(4)
    ]

    deadlock_occurrences = 0
    version_mismatch_occurrences = 0
    accepted_occurrences = 0

    def run_circular_tx(worker_id: int):
        nonlocal deadlock_occurrences, version_mismatch_occurrences, accepted_occurrences
        t_a = targets[worker_id]
        t_b = targets[(worker_id + 1) % 4]

        # Submit in randomized / caller-specified order
        first_t = t_a if worker_id % 2 == 0 else t_b
        second_t = t_b if worker_id % 2 == 0 else t_a

        with SessionLocal() as session:
            obs_1 = observe_target(session, uuid.UUID(first_t["id"]))
            obs_2 = observe_target(session, uuid.UUID(second_t["id"]))
            assert obs_1 is not None and obs_2 is not None

        try:
            res = registry.call(
                "patchdiff_commit_multi_target",
                intent=f"Worker {worker_id} circular refactoring",
                targets=[
                    {
                        "target_file_id": first_t["id"],
                        "expected_target_version": obs_1.current_version,
                        "expected_current_hash": obs_1.current_hash,
                        "operations": [
                            {"op": "match", "match": "VALUE = 100", "replace": f"VALUE = {200 + worker_id}"}
                        ],
                    },
                    {
                        "target_file_id": second_t["id"],
                        "expected_target_version": obs_2.current_version,
                        "expected_current_hash": obs_2.current_hash,
                        "operations": [
                            {"op": "match", "match": "VALUE = 100", "replace": f"VALUE = {200 + worker_id}"}
                        ],
                    },
                ],
            )
            if res["status"] == "accepted":
                accepted_occurrences += 1
            else:
                version_mismatch_occurrences += 1
            return res
        except Exception as exc:
            if "deadlock detected" in str(exc).lower():
                deadlock_occurrences += 1
            raise

    # Launch all 4 circular workers simultaneously
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_circular_tx, i) for i in range(4)]
        results = [f.result(timeout=15) for f in futures]

    assert len(results) == 4
    # Zero deadlocks must occur
    assert deadlock_occurrences == 0
    # At least one transaction commits cleanly
    assert accepted_occurrences >= 1
    # Conflicted transactions report clean serialization rejection, not deadlock aborts
    assert version_mismatch_occurrences + accepted_occurrences == 4

    # Replay all 4 targets to confirm ledger consistency
    with SessionLocal() as session:
        for t in targets:
            replay = replay_target(session, target_file_id=t["id"])
            assert replay.status == "success"
            assert replay.materialized_state_matches is True
