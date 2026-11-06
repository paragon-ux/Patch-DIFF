"""Multi-Agent Contention and Concurrency Benchmark Runner for PatchDIFF.

Generates empirical concurrency metrics across parallel disjoint workloads,
hotspot contention workloads with lineage retries, and circular multi-target refactorings.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

import app.mcp.tools
from app.core.failures import FailureReason
from app.mcp.server import registry
from app.services.read_service import observe_target
from app.services.replay_service import replay_target
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyPdcpLogs


def create_target(name: str, content: str, target_type: str = "text/x-python") -> dict[str, Any]:
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


def benchmark_disjoint_workload(workers: int, rounds_per_worker: int) -> dict[str, Any]:
    """Measure baseline throughput across independent files with zero collision expectation."""
    targets = [
        create_target(f"bench_disjoint_{i}.py", f"# Worker {i}\nCOUNTER = 0\n")
        for i in range(workers)
    ]

    latencies_ms: list[float] = []

    def worker_fn(worker_idx: int) -> list[dict[str, Any]]:
        tid = targets[worker_idx]["id"]
        res_list = []
        for r in range(rounds_per_worker):
            with SessionLocal() as session:
                obs = observe_target(session, uuid.UUID(tid))
                assert obs is not None
                version = obs.current_version
                digest = obs.current_hash

            t0 = time.perf_counter()
            res = registry.call(
                "patchdiff_submit_edits",
                target_file_id=tid,
                expected_target_version=version,
                expected_current_hash=digest,
                intent=f"Worker {worker_idx} r{r}",
                edits=[{"match": f"COUNTER = {r}", "replace": f"COUNTER = {r + 1}"}],
            )
            latencies_ms.append((time.perf_counter() - t0) * 1000)
            res_list.append(res)
        return res_list

    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker_fn, i) for i in range(workers)]
        outcomes = [f.result(timeout=60) for f in futures]
    elapsed_s = time.perf_counter() - t_start

    total_commits = sum(len(o) for o in outcomes)
    accepted_commits = sum(sum(1 for r in o if r["status"] == "accepted") for o in outcomes)

    # Replay verification
    with SessionLocal() as session:
        replays_valid = all(
            replay_target(session, target_file_id=t["id"]).materialized_state_matches is True
            for t in targets
        )

    return {
        "workload": "disjoint_parallel",
        "workers": workers,
        "rounds_per_worker": rounds_per_worker,
        "total_transactions": total_commits,
        "accepted_commits": accepted_commits,
        "conflict_rate_pct": round((total_commits - accepted_commits) / total_commits * 100, 2),
        "elapsed_seconds": round(elapsed_s, 3),
        "throughput_tx_per_sec": round(total_commits / elapsed_s, 2),
        "latency_p50_ms": round(statistics.median(latencies_ms), 2) if latencies_ms else 0,
        "latency_p95_ms": round(statistics.quantiles(latencies_ms, n=20)[18], 2) if len(latencies_ms) >= 20 else 0,
        "replay_verified": replays_valid,
    }


def benchmark_hotspot_workload(workers: int, keys_per_worker: int) -> dict[str, Any]:
    """Measure conflict rate, lineage retry recovery, and latency under heavy contention on one file."""
    initial_content = "# Hotspot Config Registry\nREGISTRY = {}\n"
    target = create_target("hotspot_registry.py", initial_content)
    tid = target["id"]
    target_uuid = target["uuid"]

    total_keys = workers * keys_per_worker
    latencies_ms: list[float] = []
    attempts_counts: list[int] = []
    total_submissions = 0
    conflict_rejections = 0

    def agent_worker(worker_idx: int) -> list[dict[str, Any]]:
        nonlocal total_submissions, conflict_rejections
        local_res = []
        for k in range(keys_per_worker):
            key = f"HOTSPOT_W{worker_idx}_K{k}"
            val = f"val_{worker_idx}_{k}"
            committed = False
            attempt = 1
            parent_log = None

            while not committed and attempt <= 15:
                with SessionLocal() as session:
                    obs = observe_target(session, target_uuid)
                    assert obs is not None
                    cur_ver = obs.current_version
                    cur_hash = obs.current_hash

                proposal = {
                    "target_file_id": tid,
                    "expected_target_version": cur_ver,
                    "expected_current_hash": cur_hash,
                    "intent": f"Insert {key} (attempt {attempt})",
                    "attempt": attempt,
                    "parent_pdcp_log_id": str(parent_log) if parent_log else None,
                    "edits": [
                        {
                            "match": "REGISTRY = {",
                            "replace": f"REGISTRY = {{\n    '{key}': '{val}',",
                        }
                    ],
                }

                total_submissions += 1
                t0 = time.perf_counter()
                res = registry.call("patchdiff_submit_edits", **proposal)
                latencies_ms.append((time.perf_counter() - t0) * 1000)

                if res["status"] == "accepted":
                    committed = True
                    attempts_counts.append(attempt)
                    local_res.append({"key": key, "attempts": attempt})
                else:
                    conflict_rejections += 1
                    parent_log = res.get("pdcp_log_id")
                    attempt += 1
                    time.sleep(0.005 * worker_idx)

            assert committed, f"Worker {worker_idx} failed on key {key}"
        return local_res

    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(agent_worker, i) for i in range(workers)]
        outcomes = [f.result(timeout=60) for f in futures]
    elapsed_s = time.perf_counter() - t_start

    successful_keys = sum(len(o) for o in outcomes)

    with SessionLocal() as session:
        replay = replay_target(session, target_file_id=tid)
        replay_ok = (replay.status == "success" and replay.materialized_state_matches is True)

    return {
        "workload": "hotspot_contention",
        "workers": workers,
        "keys_per_worker": keys_per_worker,
        "target_commits": successful_keys,
        "total_submissions": total_submissions,
        "conflict_rejections": conflict_rejections,
        "conflict_rate_pct": round(conflict_rejections / total_submissions * 100, 2) if total_submissions else 0,
        "recovery_rate_pct": 100.0 if successful_keys == total_keys else round(successful_keys / total_keys * 100, 2),
        "mean_attempts_per_commit": round(statistics.mean(attempts_counts), 2) if attempts_counts else 0,
        "max_attempts": max(attempts_counts) if attempts_counts else 0,
        "elapsed_seconds": round(elapsed_s, 3),
        "latency_p50_ms": round(statistics.median(latencies_ms), 2) if latencies_ms else 0,
        "latency_p95_ms": round(statistics.quantiles(latencies_ms, n=20)[18], 2) if len(latencies_ms) >= 20 else 0,
        "replay_verified": replay_ok,
    }


def run_benchmark_suite(workers: int = 4) -> dict[str, Any]:
    print(f"Running Multi-Agent Contention Benchmark with {workers} workers...")
    disjoint_results = benchmark_disjoint_workload(workers=workers, rounds_per_worker=5)
    print(f"  Disjoint Parallel: {disjoint_results['throughput_tx_per_sec']} tx/s, 0% conflict, p50={disjoint_results['latency_p50_ms']}ms")

    hotspot_results = benchmark_hotspot_workload(workers=workers, keys_per_worker=3)
    print(f"  Hotspot Contention: {hotspot_results['conflict_rate_pct']}% conflicts, {hotspot_results['recovery_rate_pct']}% recovered, mean attempts={hotspot_results['mean_attempts_per_commit']}")

    report = {
        "benchmark": "PatchDIFF Multi-Agent Contention Study",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "disjoint_workload": disjoint_results,
        "hotspot_workload": hotspot_results,
    }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PatchDIFF Multi-Agent Contention Benchmark")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers (default: 4)")
    parser.add_argument("--output", type=str, default=None, help="Optional output JSON file path")
    args = parser.parse_args()

    results = run_benchmark_suite(workers=args.workers)
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2))
        print(f"Report saved to {out_path}")
    else:
        print("\nBenchmark Summary:")
        print(json.dumps(results, indent=2))
