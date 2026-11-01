"""Benchmark lock wait time, lock hold duration, and deterministic replay scaling in patchdiff_finalize_target.

Measures:
- Initial target (0 edits history)
- Moderate target (25 sequential edits history)
- Extended target (100 sequential edits history)

Records (PR23-R3-DOC-002 decoupled instrumentation):
- lock_wait_ms: Duration spent waiting to acquire PostgreSQL SELECT ... FOR UPDATE row lock.
- lock_hold_ms: Duration the exclusive row lock is held while validating, snapshotting, replaying, and committing.
- replay_ms: Duration of in-memory deterministic replay verification (replay_target).
- Total finalization roundtrip time: End-to-end Python roundtrip duration of finalize_target.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from typing import Any

from app.core.config import settings
from app.services.finalize_service import finalize_target
from app.services.pdcp_service import submit_edits
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal


def run_benchmark(trials_per_tier: int = 5, edit_counts: tuple[int, ...] = (0, 25, 100)) -> dict[int, dict[str, Any]]:
    print("=== PatchDIFF Finalize & Replay Scaling Benchmark (PR23-R3-DOC-002 Aligned) ===")
    results = {}

    for edit_count in edit_counts:
        wait_times: list[float] = []
        hold_times: list[float] = []
        replay_times: list[float] = []
        total_times: list[float] = []

        # Run configured trials per edit count tier
        for trial in range(trials_per_tier):
            # 1. Initialize target with 120 lines
            lines = [f"line_{i:04d} = {i * 10}" for i in range(120)]
            content = "\n".join(lines) + "\n"

            with SessionLocal() as session:
                init_res = initialize_target(
                    session,
                    filename=f"bench_{edit_count}_{trial}.py",
                    content=content,
                    target_type="python",
                )
                tid = init_res.target_file_id
                current_ver = init_res.version

            # 2. Apply sequential edits
            for e in range(edit_count):
                target_line = f"line_{e:04d} = {e * 10}"
                replacement_line = f"line_{e:04d} = {e * 10 + 1}"
                with SessionLocal() as session:
                    sub_res = submit_edits(
                        session,
                        target_file_id=tid,
                        intent=f"Edit {e}",
                        edits=[{"match": target_line, "replace": replacement_line}],
                        expected_target_version=current_ver,
                    )
                    assert sub_res.status == "accepted", sub_res
                    current_ver = sub_res.after_version

            # 3. Benchmark finalize_target
            t0 = time.monotonic()
            with SessionLocal() as session:
                fin_res = finalize_target(
                    session,
                    target_file_id=tid,
                    client_request_id=f"bench-fin-{edit_count}-{trial}-{uuid.uuid4()}",
                    expected_target_version=current_ver,
                )
            t_total = (time.monotonic() - t0) * 1000.0

            assert fin_res.status == "ok", fin_res
            assert fin_res.lock_wait_ms is not None, "lock_wait_ms must be populated"
            assert fin_res.lock_hold_ms is not None, "lock_hold_ms must be populated"
            assert fin_res.replay_ms is not None, "replay_ms must be populated"

            wait_times.append(fin_res.lock_wait_ms)
            hold_times.append(fin_res.lock_hold_ms)
            replay_times.append(fin_res.replay_ms)
            total_times.append(t_total)

        mean_wait = statistics.mean(wait_times)
        mean_hold = statistics.mean(hold_times)
        mean_replay = statistics.mean(replay_times)
        mean_total = statistics.mean(total_times)

        results[edit_count] = {
            "mean_lock_wait_ms": round(mean_wait, 2),
            "range_lock_wait_ms": [round(min(wait_times), 2), round(max(wait_times), 2)],
            "mean_lock_hold_ms": round(mean_hold, 2),
            "range_lock_hold_ms": [round(min(hold_times), 2), round(max(hold_times), 2)],
            "mean_replay_ms": round(mean_replay, 2),
            "range_replay_ms": [round(min(replay_times), 2), round(max(replay_times), 2)],
            "mean_total_ms": round(mean_total, 2),
            "range_total_ms": [round(min(total_times), 2), round(max(total_times), 2)],
            "trials": len(hold_times),
        }
        print(
            f"Edits: {edit_count:3d} (n={trials_per_tier}) | "
            f"Lock Wait: {mean_wait:5.2f} ms [{min(wait_times):5.2f}..{max(wait_times):5.2f}] | "
            f"Lock Hold: {mean_hold:5.2f} ms [{min(hold_times):5.2f}..{max(hold_times):5.2f}] | "
            f"Replay: {mean_replay:5.2f} ms [{min(replay_times):5.2f}..{max(replay_times):5.2f}] | "
            f"Total: {mean_total:5.2f} ms [{min(total_times):5.2f}..{max(total_times):5.2f}]"
        )

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark finalize lock and replay scaling.")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials per edit tier (default: 5)")
    args = parser.parse_args()
    run_benchmark(trials_per_tier=args.trials)
