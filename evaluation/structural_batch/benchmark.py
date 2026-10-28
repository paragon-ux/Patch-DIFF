"""Preregistered, progressive P0 instrumentation comparison; never runs a model.

Every sample is the unchanged five-file workflow over real stdio and a dedicated
PostgreSQL database. Qualification is held out from diagnostic/screening data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import random
import statistics
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))
from evaluation.structural_batch.verify import PRIMARY, original_plan
from evaluation.structural_retest.evaluate import complete_primary
from evaluation.structural_retest.primary.evaluator.full_byte_oracle import expected, SOURCE_HASHES

SEED = 20261027
TIERS = (("diagnostic", 20, 0), ("screening", 60, 0), ("qualification", 200, 10))
PROTOCOL = {
    "schema": "patchdiff-performance-experiment/1", "comparison": "instrumentation_on_vs_off",
    "seed": SEED, "tiers": TIERS, "block_pairs": 10, "bootstrap_resamples": 10000,
    "median_upper_gate": 1.03, "p95_upper_gate": 1.05,
    "screening_median_rejection": 1.10, "screening_p95_rejection": 1.20,
    "cold_pairs": 40, "outliers_removed": False, "model_invocations": 0,
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="ascii")


def append(path, value):
    with path.open("a", encoding="ascii", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes():
    paths = list((REPO / "backend/app").rglob("*.py"))
    paths += [p for p in (REPO / "integrations/waymark").glob("*.mjs")]
    paths += [Path(__file__), REPO / "requirements.lock", REPO / "integrations/waymark/package-lock.json"]
    return {p.relative_to(REPO).as_posix(): digest(p.read_bytes()) for p in sorted(paths)}


def percentile95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def paired_intervals(blocks, *, resamples=10000):
    """Resample whole paired blocks, keeping their A/B observations together."""
    if not blocks or any(not block for block in blocks):
        raise ValueError("Nonempty paired blocks are required.")
    def ratios(sample):
        baseline = [pair[0] for block in sample for pair in block]
        candidate = [pair[1] for block in sample for pair in block]
        if any(not math.isfinite(v) or v <= 0 for v in baseline + candidate):
            raise ValueError("Timing observations must be positive and finite.")
        return statistics.median(candidate) / statistics.median(baseline), percentile95(candidate) / percentile95(baseline)
    point = ratios(blocks)
    all_pairs = [pair for block in blocks for pair in block]
    baseline = [pair[0] for pair in all_pairs]
    candidate = [pair[1] for pair in all_pairs]
    differences = [pair[1] - pair[0] for pair in all_pairs]
    rng = random.Random(SEED)
    medians, tails = [], []
    for _ in range(resamples):
        selected = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        median, tail = ratios(selected)
        medians.append(median)
        tails.append(tail)
    def interval(values):
        values.sort()
        return [values[math.floor(0.025 * (len(values) - 1))], values[math.ceil(0.975 * (len(values) - 1))]]
    return {"median_ratio": point[0], "p95_ratio": point[1],
            "baseline_seconds": {"median": statistics.median(baseline), "p95": percentile95(baseline)},
            "candidate_seconds": {"median": statistics.median(candidate), "p95": percentile95(candidate)},
            "paired_difference_seconds": {"median": statistics.median(differences), "p95": percentile95(differences)},
            "median_ci95": interval(medians), "p95_ci95": interval(tails), "blocks": len(blocks),
            "pairs": sum(map(len, blocks)), "resamples": resamples}


class Client:
    def __init__(self, profile, database_url, event_path=None):
        self.sequence, self.samples = 0, []
        env = {**os.environ, "PYTHONPATH": str(REPO / "backend"), "PATCHDIFF_DATABASE_URL": database_url,
               "PATCHDIFF_MCP_PROFILE": profile, "PATCHDIFF_STRICT_OBSERVATION_MODE": "1" if profile == "observed" else "0"}
        env.pop("PATCHDIFF_PERF_EVENTS", None)
        if event_path:
            env["PATCHDIFF_PERF_EVENTS"] = str(event_path.resolve())
        self.process = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], cwd=REPO,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.responses = queue.Queue(maxsize=2)
        self.stderr = bytearray()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.error_reader = threading.Thread(target=self._read_errors, daemon=True)
        self.reader.start()
        self.error_reader.start()

    def _read(self):
        while raw := self.process.stdout.readline(16 * 1024 * 1024 + 1):
            if len(raw) > 16 * 1024 * 1024:
                self.process.kill()
                break
            try:
                self.responses.put(raw, timeout=0.5)
            except queue.Full:
                self.process.kill()
                return
        try:
            self.responses.put_nowait(None)
        except queue.Full:
            pass

    def _read_errors(self):
        while raw := self.process.stderr.read(4096):
            if len(self.stderr) < 65536:
                self.stderr.extend(raw[:65536 - len(self.stderr)])

    def __enter__(self):
        try:
            self.rpc("initialize", {})
            self.catalog, sizes = self.rpc("tools/list", {})
            self.catalog_bytes = sizes[1]
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.error_reader.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()

    def rpc(self, method, params):
        self.sequence += 1
        raw = (json.dumps({"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params}, separators=(",", ":")) + "\n").encode("utf-8")
        self.process.stdin.write(raw)
        self.process.stdin.flush()
        try:
            answer = self.responses.get(timeout=30)
        except queue.Empty:
            self.process.kill()
            raise RuntimeError("MCP_TOOL_TIMEOUT") from None
        if answer is None:
            raise RuntimeError("MCP_PROCESS_EXITED")
        reply = json.loads(answer)
        if reply.get("id") != self.sequence or "result" not in reply:
            raise RuntimeError("MCP_PROTOCOL_FAILURE")
        return reply["result"], (len(raw), len(answer))

    def call(self, name, **arguments):
        start = time.perf_counter_ns()
        result, sizes = self.rpc("tools/call", {"name": name, "arguments": arguments})
        elapsed = time.perf_counter_ns() - start
        if result.get("isError"):
            raise RuntimeError("MCP_TOOL_FAILURE")
        payload = json.loads(result["content"][0]["text"])
        self.samples.append({"tool": name, "seconds": elapsed / 1e9, "request_bytes": sizes[0], "result_bytes": sizes[1]})
        return payload


@contextmanager
def benchmark_database(destination):
    """Only create/drop a new database owned by this exact run, never the canonical DB."""
    from sqlalchemy import create_engine, text
    from app.core.config import settings
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    name = "patchdiff_perf_" + uuid.uuid4().hex
    created = False
    success = False
    try:
        with admin.connect() as connection:
            version = connection.execute(text("SHOW server_version")).scalar_one()
            assert int(version.split('.')[0]) >= 16
            database_settings = {key: connection.exec_driver_sql("SHOW " + key).scalar_one()
                                 for key in ("shared_buffers", "max_connections", "synchronous_commit", "fsync", "jit")}
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        url = admin.url.set(database=name).render_as_string(hide_password=False)
        env = {**os.environ, "PYTHONPATH": str(REPO / "backend"), "PATCHDIFF_DATABASE_URL": url}
        env.pop("PATCHDIFF_PERF_EVENTS", None)
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", "backend/app/migrations/alembic.ini", "upgrade", "head"],
                                cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (destination / "migration.txt").write_bytes(result.stdout)
        if result.returncode:
            raise RuntimeError("BENCHMARK_MIGRATION_FAILED")
        yield url, {"database": name, "postgres_version": version, "database_settings": database_settings}
        success = True
    finally:
        if created:
            if success:
                assert name.startswith("patchdiff_perf_") and len(name) == len("patchdiff_perf_") + 32
                with admin.connect() as connection:
                    connection.exec_driver_sql(f'DROP DATABASE "{name}"')
            else:
                dump(destination / "retained-database.json", {"database": name, "reason": "failed run retained for inspection"})
        admin.dispose()


def workflow(operator, editor, plan, gold):
    start = time.perf_counter_ns()
    positions = len(operator.samples), len(editor.samples)
    outputs, receipts = {}, []
    for name, groups in plan.items():
        content = (PRIMARY / "fixtures" / name).read_bytes()
        assert digest(content) == SOURCE_HASHES[name]
        target = operator.call("patchdiff_initialize_target", filename=name, content=content.decode("utf-8"),
                               content_type={".py": "text/x-python", ".md": "text/markdown", ".json": "application/json"}[Path(name).suffix])
        tid = target["target_file_id"]
        observed = editor.call("patchdiff_observe_scope", target_file_id=tid, selections=[g["selection"] for g in groups])
        assert observed["status"] == "observed_batch"
        accepted = editor.call("patchdiff_submit_observed_operations", target_file_id=tid,
                               observation_bundle_id=observed["observation_bundle_id"], expected_target_version=0,
                               expected_current_hash=target["current_hash"], client_request_id="performance-fixture",
                               intent="Apply the original primary task to selected structures",
                               groups=[{"observation_id": scope["observation_id"], "operations": g["operations"]}
                                       for scope, g in zip(observed["scopes"], groups)])
        assert accepted["status"] == "accepted" and accepted["after_version"] == 1
        saved = editor.call("patchdiff_save", target_file_id=tid, expected_target_version=1, expected_current_hash=accepted["after_hash"])
        replay = editor.call("patchdiff_replay", target_file_id=tid)
        exported = operator.call("patchdiff_export_target", target_file_id=tid)
        history = operator.call("patchdiff_get_pdcp_log", target_file_id=tid)
        ledger = operator.call("patchdiff_get_manifest_ledger", target_file_id=tid, include_previous_cycles=True, limit=200)
        assert saved["status"] == "saved" and replay["materialized_state_matches"]
        assert len(history["entries"]) == 1 and len(ledger["entries"]) == sum(len(g["operations"]) for g in groups)
        outputs[name] = exported["content"].encode("utf-8")
        assert outputs[name] == gold[name]
        receipts.append({"target_file_id": tid, "pdcp_log_id": accepted["pdcp_log_id"], "snapshot_id": saved["snapshot_id"],
                         "sha256": digest(outputs[name]), "version": accepted["after_version"], "replay_checks": replay["materialized_state_checks"]})
    elapsed = (time.perf_counter_ns() - start) / 1e9
    calls = operator.samples[positions[0]:] + editor.samples[positions[1]:]
    operator.samples.clear()
    editor.samples.clear()
    return {"seconds": elapsed, "rpc_seconds": sum(r["seconds"] for r in calls), "calls": calls,
            "editing_calls": 20, "lifecycle_calls": 20, "receipts": receipts, "all_gold_bytes": True}, outputs


def machine_information():
    data = {"os": platform.platform(), "cpu": platform.processor(), "cpu_count": os.cpu_count()}
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in ("total_ram", "available_ram", "total_pagefile",
                 "available_pagefile", "total_virtual", "available_virtual", "extended_virtual")]
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            data["ram_bytes"] = memory.total_ram
        result = subprocess.run(["powercfg.exe", "/getactivescheme"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        data["power_configuration"] = result.stdout.decode("utf-8", errors="replace").strip() if result.returncode == 0 else "unavailable"
    else:
        data["ram_bytes"] = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        governor = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        data["power_configuration"] = governor.read_text().strip() if governor.exists() else "unavailable"
    return data


def run(destination, until):
    destination.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter_ns()
    try:
        return _run_created_directory(destination, until)
    except BaseException as error:
        dump(destination / "failure.json", {"qualified": False, "fatal_errors": 1,
             "error_type": type(error).__name__, "elapsed_seconds": (time.perf_counter_ns() - start) / 1e9,
             "samples_preserved": True})
        raise


def _run_created_directory(destination, until):
    dump(destination / "preregister.json", PROTOCOL)
    pins = source_hashes()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    manifest = {"run_uuid": str(uuid.uuid4()), "pid": os.getpid(), "head": head, "worktree_source_hashes": pins,
                "python": sys.version, "node": subprocess.check_output(["node", "--version"], text=True).strip(),
                **machine_information(),
                "qualified": False, "model_invocations": 0, "gate2": "closed", "tiers": {}}
    dump(destination / "manifest.json", manifest)
    plan, gold = original_plan(), expected()
    event_path = destination / "events.jsonl"
    correctness = {"gold_workflows": 0, "behavioral": None}
    with benchmark_database(destination) as (database_url, database_info):
        manifest.update(database_info)
        dump(destination / "manifest.json", manifest)
        for tier, pairs, warmups in TIERS:
            blocks = []
            for block in range(pairs // 10):
                with Client("full", database_url) as off_operator, Client("observed", database_url) as off_editor, \
                     Client("full", database_url, event_path) as on_operator, Client("observed", database_url, event_path) as on_editor:
                    sides = {"A": (off_operator, off_editor), "B": (on_operator, on_editor)}
                    for warmup in range(warmups):
                        for side in ("A", "B"):
                            result, _ = workflow(*sides[side], plan, gold)
                            correctness["gold_workflows"] += 1
                            append(destination / "samples.jsonl", {"tier": tier, "kind": "warmup", "block": block, "side": side, **result})
                    paired = []
                    for pair in range(10):
                        observed = {}
                        order = ("A", "B") if (block * 10 + pair) % 2 == 0 else ("B", "A")
                        for side in order:
                            result, outputs = workflow(*sides[side], plan, gold)
                            observed[side] = result["seconds"]
                            correctness["gold_workflows"] += 1
                            append(destination / "samples.jsonl", {"tier": tier, "kind": "sample", "block": block, "pair": pair, "side": side, **result})
                            if correctness["behavioral"] is None:
                                output_dir = destination / "exports"
                                output_dir.mkdir()
                                for name, raw in outputs.items():
                                    (output_dir / name).write_bytes(raw)
                                correctness["behavioral"] = complete_primary(output_dir)
                                assert correctness["behavioral"]["complete_correct"]
                        paired.append((observed["A"], observed["B"]))
                        print(json.dumps({"tier": tier, "pairs_complete": block * 10 + pair + 1, "pairs_total": pairs}), flush=True)
                    blocks.append(paired)
                    dump(destination / "sizes.json", {"full_catalog_bytes": off_operator.catalog_bytes,
                                                        "observed_catalog_bytes": off_editor.catalog_bytes})
                assert source_hashes() == pins, "Source changed during the experiment"
            statistics_result = paired_intervals(blocks)
            manifest["tiers"][tier] = statistics_result
            statuses = [json.loads(p.read_text()) for p in destination.glob("events.jsonl.status-*.json")]
            assert statuses and all(status["valid"] for status in statuses), "Invalid timing evidence"
            event_rows = [json.loads(line) for line in event_path.read_text(encoding="ascii").splitlines()]
            assert sum(row["written"] for row in statuses) == len(event_rows), "Missing recorder status or events"
            completed_on = sum(1 for line in (destination / "samples.jsonl").read_text(encoding="ascii").splitlines()
                               if json.loads(line)["side"] == "B")
            assert sum(row["event"] == "rpc" for row in event_rows) == completed_on * 40, "Incomplete RPC telemetry"
            assert source_hashes() == pins, "Source changed during the experiment"
            dump(destination / "correctness.json", correctness)
            if tier == "qualification":
                manifest["warm_qualification_passed"] = statistics_result["median_ci95"][1] <= 1.03 and statistics_result["p95_ci95"][1] <= 1.05
            dump(destination / "summary.json", manifest)
            if tier != "qualification" and (statistics_result["median_ratio"] > PROTOCOL["screening_median_rejection"]
                                           or statistics_result["p95_ratio"] > PROTOCOL["screening_p95_rejection"]):
                manifest["stop_reason"] = "instrumentation_screening_failed"
                break
            if tier == until:
                break
        if manifest.get("warm_qualification_passed"):
            cold_blocks = []
            for block in range(PROTOCOL["cold_pairs"] // 10):
                paired = []
                for pair in range(10):
                    values = {}
                    order = ("A", "B") if pair % 2 == 0 else ("B", "A")
                    for side in order:
                        start = time.perf_counter_ns()
                        events = event_path if side == "B" else None
                        with Client("full", database_url, events) as operator, Client("observed", database_url, events) as editor:
                            measured, _ = workflow(operator, editor, plan, gold)
                        values[side] = (time.perf_counter_ns() - start) / 1e9
                        correctness["gold_workflows"] += 1
                        append(destination / "samples.jsonl", {"tier": "cold", "kind": "sample", "block": block,
                               "pair": pair, "side": side, "process_wall_seconds": values[side], **measured})
                    paired.append((values["A"], values["B"]))
                    print(json.dumps({"tier": "cold", "pairs_complete": block * 10 + pair + 1, "pairs_total": PROTOCOL["cold_pairs"]}), flush=True)
                cold_blocks.append(paired)
            manifest["cold"] = paired_intervals(cold_blocks)
            dump(destination / "correctness.json", correctness)
            statuses = [json.loads(p.read_text()) for p in destination.glob("events.jsonl.status-*.json")]
            assert all(status["valid"] for status in statuses) and source_hashes() == pins
            manifest["qualified"] = True
    dump(destination / "summary.json", manifest)
    manifest["files"] = {p.relative_to(destination).as_posix(): digest(p.read_bytes())
                         for p in sorted(destination.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    dump(destination / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--until", choices=[t[0] for t in TIERS], default="diagnostic")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    head = subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], cwd=REPO, text=True).strip()
    destination = args.output or REPO / "evaluation/structural_batch/performance" / f"{stamp}-{head}-{uuid.uuid4()}"
    result = run(destination.resolve(), args.until)
    print(json.dumps({"output": str(destination), "qualified": result["qualified"], "tiers": result["tiers"]}), flush=True)
    if args.until == "qualification" and not result["qualified"]:
        raise SystemExit(1)
