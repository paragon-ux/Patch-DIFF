"""One combined outside-pytest Pass A exercise: raw stdio plus independent SQL."""
import base64
import datetime
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
DB = "patchdiff_goal_f_pass_a_manual_20261021"
URL = f"postgresql://patchdiff:patchdiff@127.0.0.1:5432/{DB}"
ENV = os.environ.copy()
ENV.pop("PYTHONIOENCODING", None)
ENV.pop("PYTHONUTF8", None)
ENV.update(PYTHONPATH=str(ROOT / "backend"), PATCHDIFF_DATABASE_URL=URL.replace("postgresql://", "postgresql+psycopg://", 1))
CHECKS = []
EVENTS = []


class Client:
    def __init__(self):
        self.process = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, env=ENV)
        self.responses = queue.Queue()
        self.stderr = []
        self.index = 0
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._errors, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            self.responses.put(line)
        self.responses.put(None)

    def _errors(self):
        self.stderr.extend(self.process.stderr.readlines())

    def rpc(self, method, params):
        self.index += 1
        request = {"jsonrpc": "2.0", "id": self.index, "method": method, "params": params}
        wire = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        self.process.stdin.write(wire)
        self.process.stdin.flush()
        raw = self.responses.get(timeout=30)
        assert raw is not None, "MCP process ended before its response"
        EVENTS.append({"stdin_base64": base64.b64encode(wire).decode(), "stdout_base64": base64.b64encode(raw).decode()})
        response = json.loads(raw)
        assert response["id"] == self.index and "error" not in response, response
        return response["result"]

    def call(self, name, args):
        result = self.rpc("tools/call", {"name": name, "arguments": args})
        assert result.get("isError") is False, result
        return json.loads(result["content"][0]["text"])

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
        assert self.process.returncode == 0, b"".join(self.stderr).decode("utf-8", errors="backslashreplace")


def sql_state(target):
    with psycopg.connect(URL, options="-c default_transaction_read_only=on") as conn:
        content, version, digest = conn.execute("SELECT current_content,version,current_hash FROM cloud_target_files WHERE target_file_id=%s", (target,)).fetchone()
        rows = conn.execute("SELECT pdcp_log_id::text,status,protocol_version,runtime_version,client_request_id,diagnostic_json FROM append_only_pdcp_logs WHERE target_file_id=%s ORDER BY log_sequence", (target,)).fetchall()
        ledger = conn.execute("SELECT derived_json FROM append_only_manifest_ledger WHERE target_file_id=%s ORDER BY ledger_sequence", (target,)).fetchall()
    assert digest == hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {"content": content, "version": version, "hash": digest, "logs": rows, "ledger": [row[0] for row in ledger]}


def size(value):
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def check_enrichment(payload):
    diagnostic = payload.get("diagnostic") or {}
    fields = {key: diagnostic[key] for key in ("failure_context", "exact_candidates", "near_miss_query") if key in diagnostic}
    fields.update({key: payload[key] for key in ("current_context", "near_misses", "correlation_id") if key in payload})
    assert size(fields) <= 18432
    for key in ("exact_candidates", "near_misses"):
        if key in fields:
            assert size({key: fields[key]}) <= 8192


def correlation(payload):
    value = uuid.UUID(payload["correlation_id"])
    assert value.version == 4
    return str(value)


client = Client()
try:
    client.rpc("initialize", {})
    tools = client.rpc("tools/list", {})["tools"]
    assert any(tool["name"] == "patchdiff_submit_operations" for tool in tools)
    initial = "alpha alpha\nworld\n"
    target = client.call("patchdiff_initialize_target", {"filename": "pass-a.txt", "content_type": "text/plain", "content": initial})["target_file_id"]
    ambiguous = client.call("patchdiff_submit_edits", {"target_file_id": target, "intent": "Expose bounded exact candidates.", "expected_target_version": 0, "edits": [{"match": "alpha", "replace": "ALPHA"}], "include_correlation_id": True})
    assert ambiguous["failure_reason"] == "match_ambiguous"
    first_correlation = correlation(ambiguous)
    exact = ambiguous["diagnostic"]["exact_candidates"]
    assert exact["kind"] == "exact_occurrences" and exact["occurrence_count"] == 2
    assert [(item["occurrence_index"], item["start"], item["end"]) for item in exact["candidates"]] == [(1, 0, 5), (2, 6, 11)]
    check_enrichment(ambiguous)
    assert sql_state(target)["content"] == initial
    assert sql_state(target)["logs"][0][4] is None, "Correlation silently generated a retry key"
    CHECKS.append("F03/F06: fresh opt-in UUID; no generated retry key; bounded exact ambiguity candidates; no target mutation")

    old = client.call("patchdiff_submit_edits", {"target_file_id": target, "intent": "Keep a tx/1 accepted history entry.", "expected_target_version": 0, "edits": [{"match": "world", "replace": "world!"}]})
    assert old["status"] == "accepted" and "correlation_id" not in old
    missing_args = {"target_file_id": target, "intent": "Diagnose a whitespace mismatch.", "expected_target_version": 1, "edits": [{"match": "world! ", "replace": "earth"}], "client_request_id": "pass-a-original-missing", "include_correlation_id": True}
    missing = client.call("patchdiff_submit_edits", missing_args)
    assert missing["failure_reason"] == "match_absent"
    second_correlation = correlation(missing)
    assert second_correlation != first_correlation
    near = missing["near_misses"]
    assert near["kind"] == "near_miss" and near["status"] == "computed"
    assert any("world!" in item["text"] for item in near["candidates"]), near
    assert "near_misses" not in missing["diagnostic"]
    check_enrichment(missing)
    original_diagnostic = missing["diagnostic"]
    CHECKS.append("F05: actual whitespace mismatch yields bounded labeled supplemental candidates from original failure evidence")

    operations_args = {"target_file_id": target, "intent": "Apply mixed sequential code-point operations.", "expected_target_version": 1, "client_request_id": "pass-a-operations", "include_correlation_id": True, "operations": [{"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": "🚀\n"}, {"op": "match", "match": "world!", "replace": "earth"}, {"op": "span", "start": 2, "end": 7, "expected_text": "alpha", "replace": "ALPHA"}]}
    operations = client.call("patchdiff_submit_operations", operations_args)
    assert operations["status"] == "accepted" and operations["version"] == 2
    third_correlation = correlation(operations)
    assert third_correlation not in (first_correlation, second_correlation)
    expected = "🚀\nALPHA alpha\nearth\n"
    final_state = sql_state(target)
    assert final_state["content"] == expected and final_state["version"] == 2
    assert len(final_state["ledger"]) == 4
    assert [(fact["span_start"], fact["span_end"]) for fact in final_state["ledger"]] == [(12, 17), (0, 0), (14, 20), (2, 7)]
    assert final_state["ledger"][1]["matched_chars"] == 0
    assert final_state["ledger"][1]["matched_sha256"] == hashlib.sha256(b"").hexdigest()
    assert final_state["ledger"][1]["operation"] == final_state["ledger"][3]["operation"] == "span"
    CHECKS.append("F07: guarded insertion and mixed match/span operations use sequential Unicode code-point coordinates and typed ledger facts")

    recovered = client.call("patchdiff_submit_edits", missing_args)
    assert recovered["deduplicated"] is True and recovered["pdcp_log_id"] == missing["pdcp_log_id"]
    assert correlation(recovered) not in (first_correlation, second_correlation, third_correlation)
    assert recovered["diagnostic"] == original_diagnostic
    assert recovered["current_context"]["observed_target_version"] == 2
    assert recovered["near_misses"] == near
    assert sql_state(target) == final_state
    no_id = client.call("patchdiff_submit_operations", {**operations_args, "include_correlation_id": False})
    assert no_id["deduplicated"] is True and no_id["pdcp_log_id"] == operations["pdcp_log_id"]
    assert "correlation_id" not in no_id and sql_state(target) == final_state
    CHECKS.append("F01/F03/F05/F07 recovery: immutable original diagnostics/near inputs; fresh state/UUID; response flags outside request identity; zero extra rows")

    for operation, reason in (({"op": "span", "start": 2, "end": 7, "expected_text": "WRONG", "replace": "x"}, "span_expected_text_mismatch"), ({"op": "span", "start": 999, "end": 1000, "expected_text": "x", "replace": "y"}, "span_out_of_bounds")):
        rejected = client.call("patchdiff_submit_operations", {"target_file_id": target, "intent": "Reject an invalid guarded span atomically.", "expected_target_version": 2, "operations": [operation]})
        assert rejected["status"] == "rejected" and rejected["failure_reason"] == reason
        check_enrichment(rejected)
        current = sql_state(target)
        assert current["content"] == expected and current["version"] == 2 and current["ledger"] == final_state["ledger"]
    mixed = client.call("patchdiff_submit_operations", {"target_file_id": target, "intent": "Roll back a simulated first change.", "expected_target_version": 2, "operations": [{"op": "match", "match": "earth", "replace": "planet"}, {"op": "span", "start": 2, "end": 7, "expected_text": "wrong", "replace": "bad"}]})
    assert mixed["failure_reason"] == "span_expected_text_mismatch"
    assert mixed["diagnostic"]["failure_context"]["buffer_stage"] == "intermediate_buffer"
    assert "planet" in mixed["diagnostic"]["failure_context"]["text"]
    assert sql_state(target)["content"] == expected
    before_bad_flag = sql_state(target)
    bad_flag = client.call("patchdiff_submit_edits", {"target_file_id": target, "intent": "Reject invalid response option before admission.", "expected_target_version": 2, "edits": [{"match": "earth", "replace": "planet"}], "include_correlation_id": "true"})
    assert bad_flag["status"] == "invalid_argument" and sql_state(target) == before_bad_flag
    CHECKS.append("F03/F07 rejection: expected-text/bounds/second-operation failures remain atomic; invalid correlation option creates no attempt")

    ledger_entries = []
    cursor = None
    while True:
        page = client.call("patchdiff_get_manifest_ledger", {"target_file_id": target, "limit": 2, **({"before_sequence": cursor} if cursor is not None else {})})
        ledger_entries.extend(page["entries"])
        if not page["has_more"]:
            break
        assert page["next_sequence"] != cursor
        cursor = page["next_sequence"]
        assert len(ledger_entries) <= 4
    assert len(ledger_entries) == 4
    assert client.call("patchdiff_save", {"target_file_id": target})["status"] == "saved"
    replay = client.call("patchdiff_replay", {"target_file_id": target})
    assert replay["status"] == "success" and replay["materialized_state_matches"] is True
    assert client.call("patchdiff_export_target", {"target_file_id": target})["content"] == expected
    final_state = sql_state(target)
    assert {(row[2], row[3]) for row in final_state["logs"] if row[1] == "accepted"} == {("patchdiff-tx/1", "patchdiff-mvp-0.2.2"), ("patchdiff-tx/2", "patchdiff-mvp-0.3.0")}
    assert all(row[5] == original_diagnostic for row in final_state["logs"] if row[0] == missing["pdcp_log_id"])
    CHECKS.append("Integrated history: existing exclusive paging, old/new recorded profiles, SAVE/replay/export and original audit evidence all agree with SQL")
    lock_target = client.call("patchdiff_initialize_target", {"filename": "pass-a-lock.txt", "content_type": "text/plain", "content": "world\n"})["target_file_id"]
finally:
    client.close()

os.environ["PATCHDIFF_DATABASE_URL"] = ENV["PATCHDIFF_DATABASE_URL"]
sys.path.insert(0, str(ROOT / "backend"))
from app.services import pdcp_service as service
from app.storage.db import SessionLocal

# Observe the actual expensive-function entry against a second PostgreSQL connection.
# This scoped probe retains the production algorithm and never changes product files.
original_comparison = service.near_misses
lock_observations = []
def observed_comparison(diagnostic, *, caller_owned):
    assert caller_owned is False
    with psycopg.connect(URL) as observer:
        observer.execute("SELECT target_file_id FROM cloud_target_files WHERE target_file_id=%s FOR UPDATE NOWAIT", (lock_target,)).fetchone()
        count = observer.execute("SELECT count(*) FROM append_only_pdcp_logs WHERE target_file_id=%s", (lock_target,)).fetchone()[0]
        assert count == 1, "Comparison began before its rejection committed"
        observer.rollback()
    lock_observations.append("service lock released and committed rejection visible at comparison entry")
    return original_comparison(diagnostic, caller_owned=caller_owned)

service.near_misses = observed_comparison
try:
    with SessionLocal() as owned:
        owned_result = service.submit_edits(owned, target_file_id=lock_target, intent="Observe actual comparison lock boundary.", expected_target_version=0, edits=[{"match": "world ", "replace": "earth"}])
        assert owned_result.status == "rejected" and owned_result.near_misses["status"] == "computed"
finally:
    service.near_misses = original_comparison
assert len(lock_observations) == 1
before_caller = sql_state(lock_target)
with SessionLocal() as caller:
    caller.begin()
    caller_result = service.submit_edits(caller, target_file_id=lock_target, intent="Keep caller-owned rejection provisional.", expected_target_version=0, edits=[{"match": "world ", "replace": "earth"}])
    assert caller.in_transaction()
    assert caller_result.near_misses["status"] == "omitted" and caller_result.near_misses["omission_reason"] == "caller_transaction"
    try:
        with psycopg.connect(URL) as observer:
            observer.execute("SELECT target_file_id FROM cloud_target_files WHERE target_file_id=%s FOR UPDATE NOWAIT", (lock_target,)).fetchone()
    except psycopg.errors.LockNotAvailable:
        lock_observations.append("caller-owned lock retained; comparison explicitly omitted")
    else:
        raise AssertionError("Service released the caller-owned lock")
    assert sql_state(lock_target) == before_caller, "Provisional caller rejection became externally visible"
    caller.rollback()
assert sql_state(lock_target) == before_caller
CHECKS.append("F05 live lock probe: committed service rejection visible and lock free at comparison entry; caller lock retained with explicit omission and rollback ownership")

files = [path.relative_to(ROOT).as_posix() for folder in (ROOT / "backend/app",) for path in folder.rglob("*.py")]
files.append("docs/usability/PASS-A-live-verify.py")
record = {"classification": "Combined outside-pytest raw UTF-8 public MCP subprocess, independent SQL and scoped service diagnostic-entry lock probe; no installed-host claim.", "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "executed_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "working_tree_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True), "python": sys.version, "database": DB, "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(files)}, "checks": CHECKS, "target": target, "final_SQL_state": final_state, "replay_checks": replay["materialized_state_checks"], "lock_probe_target": lock_target, "lock_observations": lock_observations, "events": EVENTS, "stderr_base64": base64.b64encode(b"".join(client.stderr)).decode()}
(ROOT / "docs/usability/PASS-A-live-results.json").write_text(json.dumps(record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"passed": len(CHECKS), "checks": CHECKS}, indent=2))
