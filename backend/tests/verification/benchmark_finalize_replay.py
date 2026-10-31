"""Benchmark lock hold duration and deterministic replay scaling in patchdiff_finalize_target.

Measures:
- Initial target (0 edits history)
- Moderate target (25 sequential edits history)
- Extended target (100 sequential edits history)
Records:
- lock_hold_ms
- replay_ms
- Total finalization roundtrip time
"""

from __future__ import annotations

import json
import statistics
import time
import uuid

from app.core.config import settings
from app.services.finalize_service import finalize_target
from app.services.pdcp_service import submit_edits
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal


def run_benchmark():
    print("=== PatchDIFF Finalize & Replay Scaling Benchmark ===")
    results = {}

    for edit_count in (0, 25, 100):
        lock_times = []
        replay_times = []
        total_times = []

        # Run 3 trials per edit count
        for trial in range(3):
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
            lock_times.append(fin_res.lock_hold_ms)
            replay_times.append(fin_res.replay_ms)
            total_times.append(t_total)

        mean_lock = statistics.mean(lock_times)
        mean_replay = statistics.mean(replay_times)
        mean_total = statistics.mean(total_times)
        results[edit_count] = {
            "mean_lock_ms": round(mean_lock, 2),
            "mean_replay_ms": round(mean_replay, 2),
            "mean_total_ms": round(mean_total, 2),
            "trials": len(lock_times),
        }
        print(f"Edits: {edit_count:3d} | Lock Hold: {mean_lock:6.2f} ms | Replay: {mean_replay:6.2f} ms | Total: {mean_total:6.2f} ms")

    return results


if __name__ == "__main__":
    run_benchmark()
