"""Recount this fixed exploratory intake and verify archived output bytes.

No model, database, transcript command, or transcript Python is executed. The
existing trusted primary evaluator imports outputs only after exact gold equality.
Default mode checks the committed receipts; --write explicitly refreshes them.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
from evaluation.structural_retest.evaluate import complete_primary
from evaluation.structural_retest.primary.evaluator.full_byte_oracle import SOURCE_HASHES


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def decoded(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def result_json(row: dict) -> dict:
    text = row["content"]
    start = re.search(r"(?m)^\{", text)
    if start is None:
        raise ValueError("Critical MCP result missing inline JSON")
    return json.loads(text[start.start():])


def analyze(arm: str) -> dict:
    full = rows(ROOT / f"sources/transcript-ARM-{arm}-full.jsonl")
    compact = rows(ROOT / f"sources/transcript-ARM-{arm}.jsonl")
    if len(full) != len(compact):
        raise ValueError(f"Compact/full row count mismatch: {arm}")
    calls, mcp, operation_types = Counter(), Counter(), Counter()
    critical, commands = [], []
    native_edit_results = []
    discovery = 0
    for index, row in enumerate(full):
        if row.get("truncated_fields"):
            raise ValueError(f"Full transcript has truncation marker: {arm}:{index + 1}")
        for call in row.get("tool_calls", []) or []:
            name = call["name"]
            calls[name] += 1
            args = {key: decoded(value) for key, value in call["args"].items()}
            if name == "run_command":
                commands.append({"line": index + 1, "command": args.get("CommandLine")})
            if name == "edit_file":
                native_edit_results.append({"response_line": index + 2,
                                           "content": full[index + 1]["content"]})
            if name != "call_mcp_tool":
                continue
            tool, arguments = args["ToolName"], decoded(args["Arguments"])
            if not isinstance(arguments, dict):
                raise ValueError("MCP arguments are not a complete object")
            mcp[tool] += 1
            if tool == "patchdiff_observe_scope" and not arguments.get("symbol_name"):
                discovery += 1
            if "submit" not in tool and tool not in {"patchdiff_save", "patchdiff_replay"}:
                continue
            response = result_json(full[index + 1])
            operations = arguments.get("operations", [])
            operation_types.update(item["op"] for item in operations)
            critical.append({
                "tool": tool, "request_line": index + 1, "response_line": index + 2,
                "target_file_id": arguments["target_file_id"],
                "expected_target_version": arguments.get("expected_target_version"),
                "expected_current_hash": arguments.get("expected_current_hash"),
                "client_request_id": arguments.get("client_request_id"),
                "observation_id": arguments.get("observation_id"),
                "operation_count": len(operations),
                "status": response["status"], "current_hash": response.get("current_hash"),
                "version": response.get("current_version", response.get("version")),
                "pdcp_log_id": response.get("pdcp_log_id"),
                "snapshot_id": response.get("snapshot_id"),
                "materialized_state_matches": response.get("materialized_state_matches"),
                "materialized_state_checks": response.get("materialized_state_checks"),
            })
    start, end = full[0]["created_at"], full[-1]["created_at"]
    task = full[0]["content"].split("### EXACT MULTI-FILE EDIT SPECIFICATION", 1)[1]
    task = ("### EXACT MULTI-FILE EDIT SPECIFICATION" + task.split("Complete all 21 edits", 1)[0]).strip()
    truncated = [{"line": i + 1, "fields": row["truncated_fields"]}
                 for i, row in enumerate(compact) if row.get("truncated_fields")]
    usage = {key: {"sum": sum(row.get(key, 0) or 0 for row in full),
                   "rows_with_field": sum(key in row for row in full)}
             for key in ["input_tokens", "output_tokens", "cache_read_tokens"]}
    return {
        "rows": len(full), "first_created_at": start, "last_created_at": end,
        "interval_seconds": (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(),
        "host_tool_calls": dict(sorted(calls.items())), "total_host_tool_calls": sum(calls.values()),
        "mcp_tool_calls": dict(sorted(mcp.items())),
        "observe_discovery_calls_without_symbol_name": discovery, "operation_types": dict(operation_types),
        "common_embedded_task_block_sha256": sha(task.encode("utf-8")),
        "compact_truncated_rows": truncated, "full_truncated_rows": 0,
        "usage_host_reported_unverified": usage,
        "reasoning_tokens": None, "provider_model_id_verified": False,
        "effective_reasoning_verified": False, "hard_token_cap_verified": False,
        "commands": commands, "native_edit_results": native_edit_results,
        "critical_mcp_calls": critical,
    }


def receipts() -> tuple[dict, dict]:
    manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    seen = set()
    for entry in manifest["files"]:
        path = (ROOT / entry["path"]).resolve()
        if not path.is_relative_to(ROOT) or entry["path"] in seen:
            raise ValueError("Duplicate or escaped manifest path")
        seen.add(entry["path"])
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or sha(raw) != entry["sha256"]:
            raise ValueError(f"Source byte mismatch: {entry['path']}")
    actual = {p.relative_to(ROOT).as_posix() for directory in ["sources", "exports", "target_mappings"]
              for p in (ROOT / directory).rglob("*") if p.is_file()}
    if seen != actual:
        raise ValueError("Source inventory differs from manifest")
    mappings = {}
    for arm in "BC":
        mapping = json.loads((ROOT / f"target_mappings/arm_{arm.lower()}_targets.json").read_text())
        if set(mapping) != set(SOURCE_HASHES):
            raise ValueError("Mapping file inventory differs from original fixtures")
        for name, entry in mapping.items():
            if (entry["version"] != 0 or entry["current_hash"] != SOURCE_HASHES[name]
                    or entry["source_line_endings"]["source_sha256"] != SOURCE_HASHES[name]):
                raise ValueError(f"Mapping not at authenticated initial state: {arm}:{name}")
        mappings[arm] = {name: entry["target_file_id"] for name, entry in mapping.items()}
    analysis = {"schema": "patchdiff-exploratory-analysis/1", "source_files_verified": len(seen),
                "usage_caveat": "Host log field sums; semantics and provider totals unverified; missing reasoning is unavailable, not zero.",
                "arms": {arm: analyze(arm) for arm in "ABC"}, "initial_target_ids": mappings}
    oracle = {arm: complete_primary(ROOT / "exports" / arm) for arm in "ABC"}
    if not all(result["complete_correct"] for result in oracle.values()):
        raise ValueError("An archived output failed the trusted primary oracle")
    return analysis, oracle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Explicitly write derived receipts")
    args = parser.parse_args()
    analysis, oracle = receipts()
    for name, value in [("analysis.json", analysis), ("oracle_results.json", oracle)]:
        path = ROOT / name
        if args.write:
            path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
        elif json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError(f"Derived receipt mismatch: {name}")
    print("PASS: 24 archived source files; complete JSONL recount; A/B/C exact bytes and 20/20 behavioral checks each.")


if __name__ == "__main__":
    main()
