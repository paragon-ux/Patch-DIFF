"""Outside-pytest F01 exercise through raw UTF-8 stdio, checked independently with SQL."""
import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
DB = "patchdiff_goal_f_f01_manual_20261021"
URL = f"postgresql://patchdiff:patchdiff@127.0.0.1:5432/{DB}"
ENV = os.environ.copy()
ENV.pop("PYTHONIOENCODING", None)
ENV.pop("PYTHONUTF8", None)
ENV.update(PYTHONPATH=str(ROOT / "backend"), PATCHDIFF_DATABASE_URL=URL.replace("postgresql://", "postgresql+psycopg://", 1))
RUNS = []
CHECKS = []


def call(name, args):
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    wire = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    result = subprocess.run([sys.executable, "-m", "app.mcp.external_adapter"], input=wire, capture_output=True, cwd=ROOT, env=ENV, timeout=30)
    RUNS.append({"tool": name, "stdin_base64": base64.b64encode(wire).decode(), "stdout_base64": base64.b64encode(result.stdout).decode(), "stderr_base64": base64.b64encode(result.stderr).decode(), "exit_code": result.returncode})
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="backslashreplace")
    responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert len(responses) == 1, responses
    envelope = responses[0]["result"]
    assert envelope.get("isError") is False, envelope
    return json.loads(envelope["content"][0]["text"])


def state(target):
    with psycopg.connect(URL, options="-c default_transaction_read_only=on") as conn:
        content, version, digest = conn.execute("SELECT current_content,version,current_hash FROM cloud_target_files WHERE target_file_id=%s", (target,)).fetchone()
        logs = dict(conn.execute("SELECT status,count(*) FROM append_only_pdcp_logs WHERE target_file_id=%s GROUP BY status", (target,)))
        ledger = conn.execute("SELECT count(*) FROM append_only_manifest_ledger WHERE target_file_id=%s", (target,)).fetchone()[0]
    return {"content": content, "version": version, "hash": digest, "logs": logs, "ledger": ledger}


def compact_size(value):
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))


def rejection_contexts(payload):
    assert payload["status"] == "rejected", payload
    failure = payload["diagnostic"]["failure_context"]
    current = payload["current_context"]
    assert compact_size(failure) <= 4096
    assert compact_size(current) <= 4096
    assert compact_size({"failure_context": failure, "current_context": current}) <= 8192
    return failure, current


def available(context, text, version, digest, stage, prior):
    assert context["available"] is True, context
    assert context["selection"] == "prefix"
    assert context["buffer_stage"] == stage
    assert context["prior_changes"] == prior
    assert context["start"] == 0 and context["end"] == len(context["text"])
    assert context["text"] == text[:context["end"]]
    assert context["end"] <= 256
    assert context["total_chars"] == len(text)
    assert context["truncated"] is (len(context["text"]) < len(text))
    assert context["observed_target_version"] == version
    assert context["observed_target_hash"] == digest


def totals():
    with psycopg.connect(URL, options="-c default_transaction_read_only=on") as conn:
        return {table: conn.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in ("cloud_target_files", "append_only_pdcp_logs", "append_only_manifest_ledger", "current_pdcp_files", "editing_cycles", "target_snapshots")}


initial = "🌟 café 世界\n" + "🚀" * 300 + "\nalpha beta\n"
target = call("patchdiff_initialize_target", {"filename": "f01-manual.txt", "content_type": "text/plain", "content": initial})["target_file_id"]
original = state(target)
assert original["content"] == initial and original["version"] == 0
assert original["hash"] == hashlib.sha256(initial.encode("utf-8")).hexdigest()
stale = call("patchdiff_submit_edits", {"target_file_id": target, "expected_target_version": 1, "intent": "Observe stale guard failure context.", "edits": [{"match": "alpha", "replace": "ALPHA"}], "client_request_id": "manual-f01-stale"})
failure, current = rejection_contexts(stale)
for context in (failure, current):
    available(context, initial, 0, original["hash"], "canonical_target", 0)
assert stale["failure_reason"] == "target_version_mismatch"
assert state(target) == {**original, "logs": {"rejected": 1}}
CHECKS.append("stale guard: fresh bounded Unicode context; no target/ledger mutation")

proposal = {"target_file_id": target, "expected_target_version": 0, "intent": "Fail after a simulated first edit.", "edits": [{"match": "🌟", "replace": "🚀"}, {"match": "manual missing", "replace": "never"}], "client_request_id": "manual-f01-sequential"}
sequential = call("patchdiff_submit_edits", proposal)
failure, current = rejection_contexts(sequential)
available(failure, initial.replace("🌟", "🚀"), 0, original["hash"], "intermediate_buffer", 1)
available(current, initial, 0, original["hash"], "canonical_target", 0)
assert sequential["failure_reason"] == "match_absent"
assert state(target) == {**original, "logs": {"rejected": 2}}
with psycopg.connect(URL, options="-c default_transaction_read_only=on") as conn:
    stored = conn.execute("SELECT diagnostic_json FROM append_only_pdcp_logs WHERE pdcp_log_id=%s", (sequential["pdcp_log_id"],)).fetchone()[0]
assert stored == sequential["diagnostic"]
CHECKS.append("later sequential failure: original intermediate prefix differs from committed prefix; full atomic rollback")

accepted = call("patchdiff_submit_edits", {"target_file_id": target, "expected_target_version": 0, "intent": "Advance state before recovering the old rejection.", "edits": [{"match": "🌟", "replace": "UPDATED"}], "client_request_id": "manual-f01-advance"})
assert accepted["status"] == "accepted" and "current_context" not in accepted
changed = state(target)
assert changed["content"] == initial.replace("🌟", "UPDATED") and changed["version"] == 1
assert changed["hash"] == hashlib.sha256(changed["content"].encode("utf-8")).hexdigest()
assert changed["logs"] == {"accepted": 1, "rejected": 2} and changed["ledger"] == 1
recovered = call("patchdiff_submit_edits", proposal)
old, fresh = rejection_contexts(recovered)
assert recovered["deduplicated"] is True and recovered["pdcp_log_id"] == sequential["pdcp_log_id"]
assert recovered["diagnostic"] == stored and old == failure
available(fresh, changed["content"], 1, changed["hash"], "canonical_target", 0)
assert state(target) == changed
with psycopg.connect(URL, options="-c default_transaction_read_only=on") as conn:
    assert conn.execute("SELECT diagnostic_json FROM append_only_pdcp_logs WHERE pdcp_log_id=%s", (sequential["pdcp_log_id"],)).fetchone()[0] == stored
CHECKS.append("keyed recovery after later acceptance: immutable stored failure, separate fresh state, no new rows")

before = totals()
for identity, reason in (("invalid-uuid", "invalid_target_id"), (str(uuid.uuid4()), "target_not_found")):
    missing = call("patchdiff_submit_edits", {"target_file_id": identity, "expected_target_version": 0, "intent": "Unavailable identity context.", "edits": [{"match": "x", "replace": "y"}]})
    for context in rejection_contexts(missing):
        assert context["available"] is False and context["unavailable_reason"] == reason
        assert all(context[key] is None for key in ("text", "start", "end", "total_chars", "buffer_stage", "selection", "prior_changes", "observed_target_version", "observed_target_hash"))
assert totals() == before
CHECKS.append("malformed/missing targets: explicit unavailable contexts; all six table counts unchanged")

empty = call("patchdiff_initialize_target", {"filename": "f01-empty.txt", "content_type": "text/plain", "content": ""})["target_file_id"]
empty_state = state(empty)
empty_rejection = call("patchdiff_submit_edits", {"target_file_id": empty, "expected_target_version": 0, "intent": "Distinguish empty available context.", "edits": [{"match": "x", "replace": "y"}]})
for context in rejection_contexts(empty_rejection):
    available(context, "", 0, empty_state["hash"], "canonical_target", 0)
CHECKS.append("empty known target: available empty context, zero spans, no truncation")

assert call("patchdiff_save", {"target_file_id": target})["status"] == "saved"
replay = call("patchdiff_replay", {"target_file_id": target})
assert replay["status"] == "success" and replay["materialized_state_matches"] is True
assert call("patchdiff_export_target", {"target_file_id": target})["content"] == changed["content"]
CHECKS.append("SAVE/replay/export: canonical content and all materialized checks preserved")

files = ["backend/app/core/result.py", "backend/app/pdcp/applier.py", "backend/app/services/pdcp_service.py", "backend/app/services/rejection_context.py", "backend/app/mcp/tools.py", "docs/usability/F01-live-verify.py"]
record = {"classification": "Outside-pytest raw-byte public MCP subprocesses and independent read-only SQL; not installed-host native calls.", "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "executed_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "working_tree_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True), "python": sys.version, "database": DB, "environment_overrides": {"PYTHONIOENCODING": ENV.get("PYTHONIOENCODING"), "PYTHONUTF8": ENV.get("PYTHONUTF8")}, "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}, "passed_checks": CHECKS, "targets": {"main": target, "empty": empty}, "main_final_SQL_state": state(target), "replay_checks": replay["materialized_state_checks"], "runs": RUNS}
(ROOT / "docs/usability/F01-live-results.json").write_text(json.dumps(record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"passed": len(CHECKS), "checks": CHECKS}, ensure_ascii=True, indent=2))
