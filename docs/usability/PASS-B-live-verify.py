"""Executable discovery workflow over raw UTF-8 stdio, verified with independent SQL.

Run after migrations, with PATCHDIFF_DATABASE_URL selecting a disposable database.
The same public workflow is included once in the integration suite and can be run
outside pytest; the latter is recorded as a separate execution, not a new scenario.
"""
import base64
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import psycopg
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
URL = os.environ["PATCHDIFF_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
ENV = os.environ.copy()
ENV.update(PYTHONPATH=str(ROOT / "backend"))
ENV.pop("PYTHONIOENCODING", None)
ENV.pop("PYTHONUTF8", None)
EVENTS = []
CHECKS = []


class Client:
    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], cwd=ROOT, env=ENV,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.responses = queue.Queue()
        self.errors = []
        self.index = 0
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=lambda: self.errors.extend(self.proc.stderr.readlines()), daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            self.responses.put(line)
        self.responses.put(None)

    def rpc(self, method, params):
        self.index += 1
        wire = (json.dumps({"jsonrpc": "2.0", "id": self.index, "method": method, "params": params},
                           ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        # Regular multilingual proposals use literal UTF-8; escaped invalid text is intentional.
        if b"\\ud800" not in wire:
            wire = (json.dumps(json.loads(wire), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        self.proc.stdin.write(wire)
        self.proc.stdin.flush()
        raw = self.responses.get(timeout=45)
        assert raw is not None, b"".join(self.errors)
        event = {"request_bytes": len(wire), "request_sha256": hashlib.sha256(wire).hexdigest(),
                 "stdout_base64": base64.b64encode(raw).decode()}
        if len(wire) <= 65536:
            event["stdin_base64"] = base64.b64encode(wire).decode()
        EVENTS.append(event)
        response = json.loads(raw)
        assert response["id"] == self.index and "error" not in response, response
        return response["result"]

    def call(self, name, arguments):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        assert result["isError"] is False, result
        return json.loads(result["content"][0]["text"])

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        finally:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait(timeout=5)
        assert self.proc.returncode == 0, b"".join(self.errors)


def state(target):
    with psycopg.connect(URL, options="-c default_transaction_read_only=on") as conn:
        content, version, digest = conn.execute(
            "SELECT current_content,version,current_hash FROM cloud_target_files WHERE target_file_id=%s", (target,)).fetchone()
        logs = conn.execute("SELECT pdcp_log_id::text,status,protocol_version,runtime_version,parent_pdcp_log_id::text,"
                            "diagnostic_json,log_sequence FROM append_only_pdcp_logs WHERE target_file_id=%s ORDER BY log_sequence",
                            (target,)).fetchall()
        ledger = conn.execute("SELECT ledger_sequence,derived_json FROM append_only_manifest_ledger "
                              "WHERE target_file_id=%s ORDER BY ledger_sequence", (target,)).fetchall()
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == digest
    return {"content": content, "version": version, "hash": digest, "logs": logs, "ledger": ledger}


def all_tables():
    # Only server-owned application tables, not PostgreSQL catalogs or sequences.
    from app.storage.models import Base
    with psycopg.connect(URL, options="-c default_transaction_read_only=on") as conn:
        tables = {}
        for name in sorted(Base.metadata.tables):
            rows = sorted(row[0] for row in conn.execute(
                psycopg.sql.SQL("SELECT row_to_json(t)::text FROM {} t").format(psycopg.sql.Identifier(name))).fetchall())
            tables[name] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()}
    return tables


def size(value):
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def run():
    client = Client()
    executed = set()
    try:
        client.rpc("initialize", {})
        tools = client.rpc("tools/list", {})["tools"]
        schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
        examples = {name: schema["examples"] for name, schema in schemas.items() if "examples" in schema}
        expected = {(name, index) for name, values in examples.items() for index in range(len(values))}
        assert len(expected) == 13 and len(examples) == 9
        assert size({"tools": tools}) <= 65536 and size(examples) <= 8192
        target = client.call("patchdiff_initialize_target", {
            "filename": "pass-b-🌟.txt", "content_type": "text/plain", "content": "alpha alpha\r\n🌟 中\n"})["target_file_id"]

        def bound(name, index=0, **overrides):
            args = copy.deepcopy(examples[name][index])
            args.update(target_file_id=target, **overrides)
            Draft202012Validator(schemas[name]).validate(args)
            executed.add((name, index))
            return args

        read = client.call("patchdiff_read_target", bound("patchdiff_read_target"))
        assert read["text"] == "alpha alpha\n🌟 中\n" and read["version"] == 0
        found = client.call("patchdiff_find_occurrences", bound("patchdiff_find_occurrences"))
        assert [(row["start"], row["end"]) for row in found["occurrences"]] == [(0, 5), (6, 11)]
        first_args = bound("patchdiff_submit_edits", 0, expected_target_version=read["version"])
        first = client.call("patchdiff_submit_edits", first_args)
        assert first["status"] == "accepted" and first["version"] == 1
        dedup = client.call("patchdiff_submit_edits", first_args)
        assert dedup["deduplicated"] and dedup["pdcp_log_id"] == first["pdcp_log_id"]
        rejected = client.call("patchdiff_submit_edits", bound("patchdiff_submit_edits", 1, expected_target_version=1))
        assert rejected["failure_reason"] == "match_absent"
        retry = client.call("patchdiff_submit_edits", bound("patchdiff_submit_edits", 2,
                            expected_target_version=1, parent_pdcp_log_id=rejected["pdcp_log_id"]))
        assert retry["status"] == "accepted" and retry["version"] == 2
        inserted = client.call("patchdiff_submit_operations", bound("patchdiff_submit_operations", expected_target_version=2))
        assert inserted["status"] == "accepted" and inserted["version"] == 3
        replaced = client.call("patchdiff_submit_replacement", bound("patchdiff_submit_replacement", expected_target_version=3))
        assert replaced["status"] == "accepted" and replaced["version"] == 4
        lines = client.call("patchdiff_read_lines", bound("patchdiff_read_lines"))
        assert lines["text"] == "Final text\n" and lines["total_lines"] == 2 and lines["version"] == 4
        before_preview = all_tables()
        advisory = client.call("patchdiff_preview", bound("patchdiff_preview", expected_target_version=4))
        assert advisory["preview"] and advisory["advisory"] and advisory["status"] == "accepted"
        assert advisory["after_hash"] == hashlib.sha256(b"Reviewed text\n").hexdigest()
        assert "pdcp_log_id" not in advisory and "correlation_id" not in advisory
        assert all_tables() == before_preview
        CHECKS.append("all13publishedexamples_bound_and_executed;preview_all_table_contents_unchanged")

        pages = {}
        for name, sequence, ascending in (("patchdiff_get_pdcp_log", "log_sequence", False),
                                           ("patchdiff_get_manifest_ledger", "ledger_sequence", True)):
            rows = []
            page = client.call(name, bound(name, 0))
            assert page["has_more"] and len(page["entries"]) == 2
            first_page = page
            while True:
                seqs = [row[sequence] for row in page["entries"]]
                assert seqs == sorted(seqs, reverse=not ascending)
                rows.extend(page["entries"])
                if not page["has_more"]:
                    assert page["next_sequence"] is None
                    break
                cursor = page["next_sequence"]
                assert cursor == min(seqs)
                page = client.call(name, bound(name, 1, before_sequence=cursor))
                assert all(row[sequence] < cursor for row in page["entries"])
            pages[name] = rows
            assert first_page["next_sequence"] is not None
            assert len({row[sequence] for row in rows}) == len(rows)
        assert executed == expected
        sql = state(target)
        assert sql["content"] == "Final text\n" and sql["version"] == 4
        assert len(sql["logs"]) == 5 and len(sql["ledger"]) == 4
        assert {row[6] for row in sql["logs"]} == {row["log_sequence"] for row in pages["patchdiff_get_pdcp_log"]}
        assert {row[0] for row in sql["ledger"]} == {row["ledger_sequence"] for row in pages["patchdiff_get_manifest_ledger"]}
        reject_row = next(row for row in sql["logs"] if row[0] == rejected["pdcp_log_id"])
        assert reject_row[5] == rejected["diagnostic"]
        assert next(row for row in sql["logs"] if row[0] == retry["pdcp_log_id"])[4] == rejected["pdcp_log_id"]
        replacement_log = next(row for row in sql["logs"] if row[0] == replaced["pdcp_log_id"])
        assert replacement_log[2:4] == ("patchdiff-tx/3", "patchdiff-mvp-0.4.0")
        assert sql["ledger"][-1][1]["operation"] == "replace_all"
        CHECKS.append("exclusive_history_traversal_order_lineage_immutable_diagnostics_and_SQL_5attempts_4facts")

        # Read boundaries and rejected/advisory proposals stay outside the attempt log.
        final_empty = client.call("patchdiff_read_lines", {"target_file_id": target, "start_line": 2})
        assert final_empty["text"] == "" and final_empty["range_start"] == 11
        invalid = client.call("patchdiff_read_lines", {"target_file_id": target, "start_line": True})
        assert invalid["status"] == "invalid_argument"
        oversized = client.call("patchdiff_submit_replacement", {"target_file_id": target, "intent": "too large",
                                "expected_target_version": 4, "replacement": "x" * 1_000_001})
        assert oversized["status"] == "invalid_argument" and oversized["pdcp_log_id"] is None
        assert oversized["diagnostic"]["code"] == "replacement_too_large"
        bad_preview = client.call("patchdiff_preview", {"target_file_id": target, "format": "patchdiff-tx/2",
                                  "intent": "wrong span", "expected_target_version": 4,
                                  "operations": [{"op": "span", "start": 0, "end": 5, "expected_text": "wrong", "replace": "x"}]})
        assert bad_preview["failure_reason"] == "span_expected_text_mismatch" and "change_facts" not in bad_preview
        assert state(target) == sql
        CHECKS.append("line_EOF_invalid_types_oversize_no_attempt_rejected_preview_atomic_nonmutation")

        # Monotonic versions detect a no-op transition even though the content hash is unchanged.
        no_op = client.call("patchdiff_submit_replacement", {"target_file_id": target, "intent": "version transition",
                            "expected_target_version": 4, "replacement": "Final text\n"})
        assert no_op["status"] == "accepted" and no_op["version"] == 5
        stale_preview = client.call("patchdiff_preview", bound("patchdiff_preview", expected_target_version=4))
        assert stale_preview["failure_reason"] == "target_version_mismatch" and stale_preview["current_hash"] == sql["hash"]
        assert client.call("patchdiff_save", {"target_file_id": target})["status"] == "saved"
        replay = client.call("patchdiff_replay", {"target_file_id": target})
        assert replay["status"] == "success" and replay["materialized_state_matches"]
        assert all(replay["materialized_state_checks"].values())
        assert client.call("patchdiff_export_target", {"target_file_id": target})["content"] == "Final text\n"
        CHECKS.append("version_ABA_guard_SAVE_replay_export_mixed_frozen_profiles")
        return {"target_file_id": target, "executed_pairs": sorted(executed), "discovery_bytes": size({"tools": tools}),
                "examples_bytes": size(examples), "checks": CHECKS, "final_sql": state(target), "replay": replay,
                "preview_table_evidence": before_preview}
    finally:
        client.close()


if __name__ == "__main__":
    result = run()
    result.update(timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  status=subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
                  source_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in sorted((ROOT / "backend/app").rglob("*.py"))},
                  helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), events=EVENTS)
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/usability/PASS-B-live-results.json"
    output.write_text(json.dumps(result, ensure_ascii=True, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"PASS: {len(result['checks'])} groups; all13publishedexamples; target={result['target_file_id']}; output={output}")
