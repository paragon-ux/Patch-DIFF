"""Small reproducible one-shot/resident comparison, with real MCP/Postgres and gold oracles."""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO))
from evaluation.structural_batch.benchmark import (
    Client, append, benchmark_database, digest, dump, expected, original_plan, source_hashes, workflow,
)
from evaluation.structural_batch.verify import complete_primary


@contextmanager
def clients(mode, url):
    old = os.environ.get("PATCHDIFF_WAYMARK_MODE")
    try:
        os.environ["PATCHDIFF_WAYMARK_MODE"] = mode
        with Client("full", url) as operator, Client("observed", url) as editor:
            yield operator, editor
    finally:
        if old is None:
            os.environ.pop("PATCHDIFF_WAYMARK_MODE", None)
        else:
            os.environ["PATCHDIFF_WAYMARK_MODE"] = old


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = REPO / "evaluation/structural_batch/performance" / f"{stamp}-worker-comparison-{uuid.uuid4()}"
    destination.mkdir()
    pins = source_hashes()
    script_hash = digest(Path(__file__).read_bytes())
    dump(destination / "protocol.json", {"pairs": 5, "warmups_per_mode": 1, "instrumentation": False,
        "comparison_script_sha256": script_hash, "order": "alternating", "numerical_claim": "descriptive sample only", "worktree_source_hashes": pins})
    measured = {"oneshot": [], "resident": []}
    plan, gold = original_plan(), expected()
    with benchmark_database(destination) as (url, info), ExitStack() as stack:
        peers = {mode: stack.enter_context(clients(mode, url)) for mode in measured}
        for mode in measured:
            row, _ = workflow(*peers[mode], plan, gold)
            append(destination / "samples.jsonl", {"kind": "warmup", "mode": mode, **row})
        for pair in range(5):
            order = ("oneshot", "resident") if pair % 2 == 0 else ("resident", "oneshot")
            for mode in order:
                row, outputs = workflow(*peers[mode], plan, gold)
                row["editing_seconds"] = sum(call["seconds"] for call in row["calls"] if call["tool"] in (
                    "patchdiff_observe_scope", "patchdiff_submit_observed_operations", "patchdiff_save", "patchdiff_replay"))
                measured[mode].append(row)
                append(destination / "samples.jsonl", {"kind": "sample", "mode": mode, "pair": pair, **row})
                exports = destination / "exports" / mode
                exports.mkdir(parents=True, exist_ok=True)
                for name, raw in outputs.items():
                    (exports / name).write_bytes(raw)
                assert complete_primary(exports)["complete_correct"]
            print(json.dumps({"pairs_complete": pair + 1, "pairs_total": 5}), flush=True)
        assert source_hashes() == pins and digest(Path(__file__).read_bytes()) == script_hash, "Source changed during comparison"
        summary = {"database": info, "pairs": 5, "all_gold_bytes": True, "behavioral_checks_per_mode": 20,
            "calls_per_workflow": 40, "editing_calls": 20, "catalog_bytes": {
                mode: {"full": peers[mode][0].catalog_bytes, "observed": peers[mode][1].catalog_bytes} for mode in peers},
            "medians": {mode: {metric: statistics.median(row[metric] for row in rows)
                for metric in ("seconds", "editing_seconds")} for mode, rows in measured.items()}}
        summary["editing_ratio_resident_over_oneshot"] = summary["medians"]["resident"]["editing_seconds"] / summary["medians"]["oneshot"]["editing_seconds"]
        dump(destination / "summary.json", summary)
    dump(destination / "files.json", {p.relative_to(destination).as_posix(): digest(p.read_bytes())
        for p in destination.rglob("*") if p.is_file() and p.name != "files.json"})
    print(json.dumps({"output": str(destination), **summary}), flush=True)


if __name__ == "__main__":
    main()
