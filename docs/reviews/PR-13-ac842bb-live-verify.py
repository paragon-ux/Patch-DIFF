"""Independent PR #13 live run: real stdio MCP subprocess + independent SQL via psql.

Adapted copy of docs/reviews/PR-11-0f83855-live-verify.py (left unchanged). Two PR #11 checks
are adapted to intended behaviour (FR-6 near-miss scope, FR-8 duplicate current_context elision) and
an FR-1..FR-20 section re-tests every PR #11 friction finding.

Derived from PR-13-0420dac-live-verify.py (left unchanged) after the friction re-test at de6e7c2:
the FR-14 wire check follows the amended D14 (pure-ASCII JSON-RPC lines, literal tool text), and
NF-2, NF-3 and NF-6 checks are added.

Usage: python PR-13-ac842bb-live-verify.py <worktree> <db_url> <out_json>
Every check is recorded (pass/fail) rather than aborting, so the full picture is captured.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import hashlib
from pathlib import Path

import jsonschema

WT = Path(sys.argv[1])
DB_URL = sys.argv[2]
OUT = Path(sys.argv[3])
DB_NAME = DB_URL.rsplit("/", 1)[-1]

checks: list[dict] = []
transcript: list[dict] = []


def check(name: str, ok: bool, detail=None):
    checks.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" :: {json.dumps(detail, default=str)[:600]}"), flush=True)


def sql(query: str) -> list[list[str]]:
    out = subprocess.run(["docker", "exec", "patchdiff-postgres", "psql", "-U", "patchdiff", "-d", DB_NAME,
                          "-At", "-F", "\t", "-c", query], capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise RuntimeError(out.stderr)
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Stdio:
    def __init__(self):
        env = {**os.environ, "PYTHONPATH": str(WT / "backend"), "PATCHDIFF_DATABASE_URL": DB_URL,
               "PYTHONIOENCODING": "cp1252"}  # adapter must not depend on inherited encoding
        self.proc = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], cwd=str(WT),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.n = 0

    def raw(self, payload: bytes) -> dict:
        self.proc.stdin.write(payload + b"\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        self.last_line = line
        return json.loads(line.decode("utf-8"))

    def rpc(self, method: str, params=None) -> dict:
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": method}
        if params is not None:
            msg["params"] = params
        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        resp = self.raw(body)
        return resp

    def call(self, name: str, args: dict, *, label: str | None = None) -> dict:
        resp = self.rpc("tools/call", {"name": name, "arguments": args})
        entry = {"label": label or name, "tool": name, "args": _trim(args), "response": None}
        if "error" in resp:
            entry["response"] = resp
            transcript.append(entry)
            return {"__rpc_error__": resp["error"]}
        result = resp["result"]
        payload = json.loads(result["content"][0]["text"])
        payload["__isError__"] = result.get("isError")
        entry["response"] = _trim(payload)
        transcript.append(entry)
        return payload

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=20)
        return self.proc.stderr.read().decode("utf-8", "replace")


def _trim(value, limit=400):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"...<{len(value)} chars>"
    if isinstance(value, list):
        return [_trim(v, limit) for v in value[:40]]
    if isinstance(value, dict):
        return {k: _trim(v, limit) for k, v in value.items()}
    return value


def logs(target):
    return sql(f"select log_sequence,status,protocol_version,runtime_version,failure_reason,change_count,"
               f"coalesce(client_request_id,''),length(pdcp_content) from append_only_pdcp_logs "
               f"where target_file_id='{target}' order by log_sequence")


def ledger(target):
    return sql(f"select change_index,change_id,origin,derived_json::text from append_only_manifest_ledger "
               f"where target_file_id='{target}' order by ledger_sequence")


def target_row(target):
    rows = sql(f"select version,current_hash,length(current_content) from cloud_target_files where target_file_id='{target}'")
    return rows[0] if rows else None


s = Stdio()

# ---------------------------------------------------------------- discovery
init = s.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "pr13-review", "version": "0"}})
check("initialize returns serverInfo", "result" in init and "serverInfo" in init["result"], init)
tools = s.rpc("tools/list")["result"]["tools"]
names = sorted(t["name"] for t in tools)
check("tools/list advertises 20 tools", len(tools) == 20, names)
for expected in ("patchdiff_submit_operations", "patchdiff_submit_replacement", "patchdiff_read_lines", "patchdiff_preview"):
    check(f"tools/list includes {expected}", expected in names)
by_name = {t["name"]: t for t in tools}
examples = {t["name"]: t["inputSchema"].get("examples", []) for t in tools if t["inputSchema"].get("examples")}
check("13 examples across 9 tools", sum(map(len, examples.values())) == 13 and len(examples) == 9,
      {k: len(v) for k, v in examples.items()})
list_bytes = len(json.dumps({"tools": tools}, ensure_ascii=True, separators=(",", ":")).encode())
ex_bytes = len(json.dumps(examples, ensure_ascii=True, separators=(",", ":")).encode())
check("tools/list <= 65536 compact bytes", list_bytes <= 65536, list_bytes)
check("examples map <= 8192 compact bytes", ex_bytes <= 8192, ex_bytes)
for tname, exs in examples.items():
    for i, ex in enumerate(exs):
        try:
            jsonschema.Draft202012Validator(by_name[tname]["inputSchema"]).validate(ex)
            check(f"example {tname}[{i}] conforms to its inputSchema", True)
        except jsonschema.ValidationError as exc:
            check(f"example {tname}[{i}] conforms to its inputSchema", False, exc.message)
for tname, t in by_name.items():
    try:
        jsonschema.Draft202012Validator.check_schema(t["inputSchema"])
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = False
    check(f"inputSchema of {tname} is a valid JSON Schema", ok)
desc_ops = by_name["patchdiff_submit_operations"]["description"]
check("submit_operations description spacing ('runtime0.3.0')", "runtime0.3.0" not in desc_ops, desc_ops)
check("preview schema enumerates 4 formats",
      by_name["patchdiff_preview"]["inputSchema"]["properties"]["format"].get("enum") == ["0.2.3", "patchdiff-tx/1", "patchdiff-tx/2", "patchdiff-tx/3"])

# ---------------------------------------------------------------- 1-2 upload/initialize, 3 get_target
up = s.call("patchdiff_handle_upload", {"filename": "upload.md", "content": "Upload body\r\nline2\r\n", "content_type": "text/markdown"})
check("handle_upload initializes LF-normalized target", up.get("target_file_id") and target_row(up["target_file_id"])[2] == str(len("Upload body\nline2\n")), up)

DOC = "alpha alpha\n🌟 中\nThe quick brown fox jumps over the lazy dog.\n"
init_t = s.call("patchdiff_initialize_target", {"filename": "doc.txt", "content": DOC, "content_type": "text/plain"})
T = init_t["target_file_id"]
check("initialize_target returns version 0 and canonical hash", init_t.get("version", init_t.get("current_version")) in (0, None) and
      (init_t.get("current_hash") == sha(DOC) or init_t.get("initial_hash") == sha(DOC)), init_t)
g = s.call("patchdiff_get_target", {"target_file_id": T})
check("get_target matches DB", str(g.get("version")) == target_row(T)[0] and g.get("current_hash") == target_row(T)[1], g)

# ---------------------------------------------------------------- 4 read_target, 5 read_lines, 6 find
rt = s.call("patchdiff_read_target", {"target_file_id": T, "start": 12, "length": 4})
check("read_target code-point slicing over astral char", rt.get("text") == "🌟 中\n", rt)
rl = s.call("patchdiff_read_lines", {"target_file_id": T})
check("read_lines default = whole doc, 4 lines (trailing LF -> final empty line)",
      rl.get("status") == "ok" and rl.get("total_lines") == 4 and rl.get("text") == DOC and rl.get("truncated") is False, rl)
rl2 = s.call("patchdiff_read_lines", {"target_file_id": T, "start_line": 2, "end_line": 2})
check("read_lines line 2 inclusive of LF with absolute range offsets",
      rl2.get("text") == "🌟 中\n" and rl2.get("range_start") == 12 and rl2.get("range_end") == 16, rl2)
rl3 = s.call("patchdiff_read_lines", {"target_file_id": T, "start_line": 4, "end_line": 4})
check("read_lines final empty line is addressable", rl3.get("status") == "ok" and rl3.get("text") == "", rl3)
pages, off = [], 0
while True:
    p = s.call("patchdiff_read_lines", {"target_file_id": T, "start_line": 3, "end_line": 3, "offset": off, "max_chars": 10})
    pages.append(p["text"])
    if p.get("next_offset") is None:
        break
    off = p["next_offset"]
check("read_lines paging reassembles line 3 exactly", "".join(pages) == DOC.split("\n")[2] + "\n", pages)
for bad, label in (({"start_line": 0}, "start_line 0"), ({"start_line": 5}, "start_line > total"), ({"start_line": 3, "end_line": 2}, "reversed"),
                   ({"max_chars": 0}, "max_chars 0"), ({"start_line": True}, "bool start_line"), ({"offset": 10**6, "start_line": 1, "end_line": 1}, "offset beyond range")):
    r = s.call("patchdiff_read_lines", {"target_file_id": T, **bad}, label=f"read_lines invalid {label}")
    check(f"read_lines rejects {label}", r.get("status") == "invalid_argument" or "__rpc_error__" in r, r)
big = s.call("patchdiff_read_lines", {"target_file_id": T, "max_chars": 10**9})
check("read_lines caps max_chars at 8000 (no error)", big.get("status") == "ok", big)
nf = s.call("patchdiff_read_lines", {"target_file_id": "00000000-0000-4000-8000-000000000000"})
check("read_lines unknown target -> not_found", nf.get("status") == "not_found", nf)
fo = s.call("patchdiff_find_occurrences", {"target_file_id": T, "text": "alpha", "context_chars": 5})
check("find_occurrences lists 2 alpha occurrences", fo.get("total_occurrences", fo.get("occurrence_count")) == 2 or len(fo.get("occurrences", [])) == 2, fo)

# ---------------------------------------------------------------- 7 submit_edits (tx/1) accept/reject/ambiguous/dedup/conflict/correlation
v0 = 0
acc = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "second alpha", "expected_target_version": v0,
                                         "client_request_id": "k-accept", "include_correlation_id": True,
                                         "edits": [{"match": "alpha", "replace": "beta", "occurrence_index": 2}]})
check("tx/1 accept with selector", acc.get("status") == "accepted" and acc.get("version") == 1 and acc["evidence"]["changes"][0]["span_start"] == 6, acc)
check("correlation_id is a UUID4 on accept", isinstance(acc.get("correlation_id"), str) and len(acc["correlation_id"]) == 36 and acc["correlation_id"][14] == "4", acc.get("correlation_id"))
dup = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "second alpha", "expected_target_version": v0,
                                         "client_request_id": "k-accept", "include_correlation_id": True,
                                         "edits": [{"match": "alpha", "replace": "beta", "occurrence_index": 2}]})
check("exact key replay deduplicates to original accept", dup.get("deduplicated") is True and dup.get("pdcp_log_id") == acc.get("pdcp_log_id"), dup)
check("fresh correlation_id on dedup", dup.get("correlation_id") not in (None, acc.get("correlation_id")), dup.get("correlation_id"))
check("correlation never persisted", not sql(f"select 1 from append_only_pdcp_logs where target_file_id='{T}' and (pdcp_content like '%correlation%' or diagnostic_json::text like '%correlation%')"))
badcorr = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "x", "expected_target_version": 1,
                                             "include_correlation_id": "yes", "edits": [{"match": "beta", "replace": "b"}]})
check("non-bool include_correlation_id -> invalid_argument/schema error, no attempt", badcorr.get("status") == "invalid_argument" or "__rpc_error__" in badcorr, badcorr)
n_logs = len(logs(T))
check("no log written for invalid correlation flag", n_logs == 1, logs(T))

absent = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "missing", "expected_target_version": 1,
                                            "edits": [{"match": "quick brwn fox", "replace": "slow fox"}]})
check("tx/1 absent match rejected", absent.get("status") == "rejected" and absent.get("failure_reason") == "match_absent", absent)
fc = (absent.get("diagnostic") or {}).get("failure_context") or {}
check("failure_context available prefix, canonical_target", fc.get("available") is True and fc.get("selection") == "prefix" and fc.get("buffer_stage") == "canonical_target" and fc.get("observed_target_version") == 1, fc)
# Adapted (FR-8 / D8): a canonical-stage current_context identical to failure_context is elided.
check("current_context elided as same_as_failure_context on canonical-stage rejection",
      (absent.get("current_context") or {}).get("unavailable_reason") == "same_as_failure_context", absent.get("current_context"))
nm = absent.get("near_misses") or {}
check("near_misses computed and finds 'quick brown fox'", nm.get("status") == "computed" and any("quick brown fox" in c["text"] for c in nm.get("candidates", [])), nm)
check("near_misses not persisted", not sql(f"select 1 from append_only_pdcp_logs where pdcp_log_id='{absent['pdcp_log_id']}' and diagnostic_json ? 'near_misses'"))
retry = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "fixed", "expected_target_version": 1,
                                           "parent_pdcp_log_id": absent["pdcp_log_id"], "attempt": 1,
                                           "edits": [{"match": "quick brown fox", "replace": "quick red fox"}]})
check("retry with parent lineage accepted", retry.get("status") == "accepted" and
      sql(f"select parent_pdcp_log_id from append_only_pdcp_logs where pdcp_log_id='{retry['pdcp_log_id']}'")[0][0] == absent["pdcp_log_id"], retry)
AMBT = s.call("patchdiff_initialize_target", {"filename": "amb.txt", "content": "o " * 9 + "\n", "content_type": "text/plain"})["target_file_id"]
amb = s.call("patchdiff_submit_edits", {"target_file_id": AMBT, "intent": "ambiguous", "expected_target_version": 0,
                                         "edits": [{"match": "o", "replace": "0"}]})
ec = (amb.get("diagnostic") or {}).get("exact_candidates") or {}
check("ambiguous -> exact_candidates bounded to 5 with truncation", amb.get("failure_reason") == "match_ambiguous" and ec.get("returned_count") == 5 and ec.get("truncated") is True and ec.get("occurrence_count", 0) > 5, ec)
conflict = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "other", "expected_target_version": 2,
                                              "client_request_id": "k-accept", "edits": [{"match": "lazy", "replace": "busy"}]})
check("key reuse with different proposal -> audited conflict, target unchanged",
      conflict.get("status") == "rejected" and "already used" in (conflict.get("failure_detail") or "") and target_row(T)[0] == "2", conflict)
stale = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "stale", "expected_target_version": 0,
                                           "edits": [{"match": "lazy", "replace": "busy"}]})
check("stale version -> target_version_mismatch at precondition_guard", stale.get("failure_reason") == "target_version_mismatch" and
      (stale.get("diagnostic") or {}).get("validation_stage") == "precondition_guard", stale)
noguard = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "noguard", "edits": [{"match": "lazy", "replace": "busy"}]})
check("tx/1 without guard rejected (schema or context_missing)", "__rpc_error__" in noguard or noguard.get("failure_reason") == "context_missing", noguard)

# ---------------------------------------------------------------- 8 submit_pdcp (legacy)
cur = s.call("patchdiff_get_target", {"target_file_id": T})
pdcp = f"""PDCP 0.2.3
target_file_id: {T}
target_type: text/plain

# MANIFEST
# change_id: chg_001
# intent: Update text.
# input_state: Old text exists.
# output_state: New text exists.
# affected_region: example
# user_visible_change: Text changes.
# risk: low

<<<<<<< MATCH
lazy dog
=======
sleepy dog
>>>>>>> REPLACE"""
lp = s.call("patchdiff_submit_pdcp", {"target_file_id": T, "pdcp_content": pdcp, "expected_target_version": cur["version"], "include_correlation_id": True})
check("legacy PDCP accepted on runtime 0.2.2", lp.get("status") == "accepted" and logs(T)[-1][3] == "patchdiff-mvp-0.2.2", lp)

# ---------------------------------------------------------------- 9 submit_operations (tx/2)
cur = s.call("patchdiff_get_target", {"target_file_id": T}); V = cur["version"]
content = s.call("patchdiff_export_target", {"target_file_id": T}).get("content")
ins = s.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "Insert at beginning", "expected_target_version": V,
                                              "operations": [{"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": "Note: "}]})
check("tx/2 zero-length insertion accepted", ins.get("status") == "accepted" and ins["evidence"]["changes"][0].get("operation") == "span", ins)
check("tx/2 log on immutable runtime 0.3.0", logs(T)[-1][2:4] == ["patchdiff-tx/2", "patchdiff-mvp-0.3.0"], logs(T)[-1])
after = "Note: " + content
star = after.index("🌟")
seq = s.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "sequential coordinates", "expected_current_hash": sha(after),
    "operations": [
        {"op": "span", "start": 0, "end": 6, "expected_text": "Note: ", "replace": ""},           # buffer shrinks by 6
        {"op": "span", "start": star - 6, "end": star - 5, "expected_text": "🌟", "replace": "*"},  # coordinates in sequential buffer
        {"op": "match", "match": "中", "replace": "zh"}]})
check("tx/2 mixed span/match with sequential code-point coordinates accepted", seq.get("status") == "accepted", seq)
content = s.call("patchdiff_export_target", {"target_file_id": T}).get("content")
check("tx/2 result text exact", content.startswith("alpha beta\n* zh\n"), content[:30])
cur = s.call("patchdiff_get_target", {"target_file_id": T}); V = cur["version"]
n_before = len(logs(T)); led_before = len(ledger(T))
atomic = s.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "second op fails", "expected_target_version": V,
    "operations": [{"op": "match", "match": "alpha", "replace": "ALPHA"},
                   {"op": "span", "start": 0, "end": 5, "expected_text": "alpha", "replace": "x"}]})
check("tx/2 span expected_text mismatch on intermediate buffer rejects whole tx",
      atomic.get("failure_reason") == "span_expected_text_mismatch" and target_row(T)[0] == str(V) and len(ledger(T)) == led_before, atomic)
afc = (atomic.get("diagnostic") or {}).get("failure_context") or {}
check("failure_context names intermediate_buffer with prior_changes=1", afc.get("buffer_stage") == "intermediate_buffer" and afc.get("prior_changes") == 1 and afc.get("text", "").startswith("ALPHA"), afc)
check("current_context names canonical state", (atomic.get("current_context") or {}).get("buffer_stage") == "canonical_target" and (atomic.get("current_context") or {}).get("text", "").startswith("alpha"), atomic.get("current_context"))
oob = s.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "oob", "expected_target_version": V,
    "operations": [{"op": "span", "start": 0, "end": 10**6, "expected_text": "x", "replace": "y"}]})
check("tx/2 span out of bounds -> span_out_of_bounds (transaction stage)", oob.get("failure_reason") == "span_out_of_bounds" and
      (oob.get("validity") or {}).get("protocol_valid") is True and (oob.get("validity") or {}).get("transaction_valid") is False, oob)
sel = s.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "selector on span", "expected_target_version": V,
    "operations": [{"op": "span", "start": 0, "end": 5, "expected_text": "alpha", "replace": "x", "occurrence_index": 1}]})
check("tx/2 selector on span rejected", sel.get("status") == "rejected" or "__rpc_error__" in sel, sel)
rev = s.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "reversed", "expected_target_version": V,
    "operations": [{"op": "span", "start": 5, "end": 1, "expected_text": "", "replace": "x"}]})
check("tx/2 end<start rejected", rev.get("status") == "rejected" or "__rpc_error__" in rev, rev)
boolspan = s.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "bool", "expected_target_version": V,
    "operations": [{"op": "span", "start": False, "end": True, "expected_text": "a", "replace": "x"}]})
check("tx/2 boolean coordinates rejected", boolspan.get("status") == "rejected" or "__rpc_error__" in boolspan, boolspan)
crlf_target = s.call("patchdiff_initialize_target", {"filename": "crlf.txt", "content": "a\nb\nc\n", "content_type": "text/plain"})["target_file_id"]
crlf = s.call("patchdiff_submit_operations", {"target_file_id": crlf_target, "intent": "crlf expected", "expected_target_version": 0,
    "operations": [{"op": "span", "start": 0, "end": 4, "expected_text": "a\r\nb\r\n", "replace": "X\r\n"}]})
check("tx/2 CRLF expected_text canonicalizes before compare", crlf.get("status") == "accepted" and
      s.call("patchdiff_export_target", {"target_file_id": crlf_target}).get("content") == "X\nc\n", crlf)
surr = s.proc and s.raw(json.dumps({"jsonrpc": "2.0", "id": "surr", "method": "tools/call", "params": {"name": "patchdiff_submit_operations",
    "arguments": {"target_file_id": T, "intent": "bad", "expected_target_version": V,
                  "operations": [{"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": "\ud800"}]}}}).encode())
surr_payload = json.loads(surr["result"]["content"][0]["text"]) if "result" in surr else surr
check("lone surrogate in tx/2 -> durable target_encoding_invalid, unchanged target",
      surr_payload.get("failure_reason") == "target_encoding_invalid" and surr_payload.get("pdcp_log_id") and target_row(T)[0] == str(V), surr_payload)

# ---------------------------------------------------------------- 10 submit_replacement (tx/3)
cur = s.call("patchdiff_get_target", {"target_file_id": T}); V = cur["version"]
rp = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "Replace whole", "expected_target_version": V,
                                              "replacement": "Final text\r\n", "client_request_id": "k-repl"})
check("tx/3 replacement accepted with canonical LF", rp.get("status") == "accepted" and
      s.call("patchdiff_export_target", {"target_file_id": T}).get("content") == "Final text\n", rp)
check("tx/3 on immutable runtime 0.4.0", logs(T)[-1][2:4] == ["patchdiff-tx/3", "patchdiff-mvp-0.4.0"], logs(T)[-1])
led = ledger(T)[-1]
check("tx/3 single typed ledger row with operation=replace_all", led[2] == "typed" and json.loads(led[3]).get("operation") == "replace_all", led)
n_before = len(logs(T))
over_cp = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "too big", "expected_target_version": V + 1,
                                                   "replacement": "a" * 1_000_001})
check("tx/3 > 1,000,000 code points -> invalid_argument, no writes", over_cp.get("status") == "invalid_argument" and
      (over_cp.get("diagnostic") or {}).get("limit_exceeded") == "raw_code_points" and len(logs(T)) == n_before, over_cp)
over_b = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "too many bytes", "expected_target_version": V + 1,
                                                  "replacement": "中" * 400_000})
check("tx/3 > 1,048,576 UTF-8 bytes -> raw_utf8_bytes", (over_b.get("diagnostic") or {}).get("limit_exceeded") == "raw_utf8_bytes" and len(logs(T)) == n_before, over_b)
edge = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "exact limit", "expected_target_version": V + 1,
                                                "replacement": "a" * 1_000_000})
check("tx/3 exactly 1,000,000 code points accepted (inclusive)", edge.get("status") == "accepted", {k: edge.get(k) for k in ("status", "failure_reason", "diagnostic")})
rdup = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "Replace whole", "expected_target_version": V,
                                                "replacement": "Final text\r\n", "client_request_id": "k-repl"})
check("tx/3 exact-key recovery after later edit", rdup.get("deduplicated") is True and rdup.get("pdcp_log_id") == rp.get("pdcp_log_id"), rdup)
n_before = len(logs(T))
rconf_big = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "Replace whole", "expected_target_version": V,
                                                     "replacement": "b" * 1_200_000, "client_request_id": "k-repl"})
big_row = logs(T)[-1]
check("existing-key conflict precedes admission (documented)", rconf_big.get("status") == "rejected" and "already used" in (rconf_big.get("failure_detail") or ""), rconf_big)
transcript.append({"label": "OBSERVATION oversize replacement persisted via key-conflict path", "log_row": big_row, "logs_added": len(logs(T)) - n_before})
cur = s.call("patchdiff_get_target", {"target_file_id": T}); V = cur["version"]
empty = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "Empty", "expected_target_version": V, "replacement": ""})
check("tx/3 empty replacement accepted", empty.get("status") == "accepted" and target_row(T)[2] == "0", empty)
rp2 = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "restore", "expected_target_version": V + 1,
                                               "replacement": "alpha alpha\nThe quick brown fox jumps over the lazy dog.\n" + ("filler line\n" * 40) + "tail marker zebra crossing\n"})
check("tx/3 restore accepted", rp2.get("status") == "accepted", rp2)
noguard3 = s.call("patchdiff_submit_replacement", {"target_file_id": T, "intent": "noguard", "replacement": "x"})
check("tx/3 without guard rejected", "__rpc_error__" in noguard3 or noguard3.get("failure_reason") == "context_missing", noguard3)

# near-miss reach: only first 256 code points are searched
cur = s.call("patchdiff_get_target", {"target_file_id": T}); V = cur["version"]
far = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "typo late in doc", "expected_target_version": V,
                                         "edits": [{"match": "zebra crosing", "replace": "x"}]})
nmf = far.get("near_misses") or {}
transcript.append({"label": "OBSERVATION near-miss beyond 256-char prefix", "near_misses": nmf})
# Adapted (FR-6 / D6): fresh rejections scan the failing buffer, not the 256-point stored prefix.
check("near-miss beyond the 256-point prefix is found (FR-6)", any("zebra crossing" in c["text"] for c in nmf.get("candidates", [])), nmf)
longq = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "long typo", "expected_target_version": V,
                                           "edits": [{"match": "The quick brown fox jumps over the lazzy dog.", "replace": "x"}]})
transcript.append({"label": "OBSERVATION 45-char near-miss query", "near_misses": longq.get("near_misses")})
check("45-char typo within prefix: near-miss status recorded", True, (longq.get("near_misses") or {}).get("status"))

# ---------------------------------------------------------------- 11 preview (all 4 formats) + no-write proof
cur = s.call("patchdiff_get_target", {"target_file_id": T}); V = cur["version"]; H = cur["current_hash"]
snap = (len(logs(T)), len(ledger(T)), target_row(T), sql(f"select status, pdcp_content_hash from current_pdcp_files where target_file_id='{T}'"))
pv1 = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/1", "intent": "p", "expected_target_version": V,
                                    "edits": [{"match": "lazy", "replace": "busy"}]})
check("preview tx/1 accepted, advisory, has after_hash", pv1.get("status") == "accepted" and pv1.get("preview") is True and pv1.get("advisory") is True and pv1.get("after_hash"), pv1)
pv2 = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/2", "intent": "p", "expected_current_hash": H,
                                    "operations": [{"op": "span", "start": 0, "end": 5, "expected_text": "alpha", "replace": "A"}]})
check("preview tx/2 accepted", pv2.get("status") == "accepted", pv2)
pv3 = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/3", "intent": "p", "expected_target_version": V, "replacement": "z"})
check("preview tx/3 accepted with after_hash == sha('z')", pv3.get("after_hash") == sha("z"), pv3)
pv0 = s.call("patchdiff_preview", {"target_file_id": T, "format": "0.2.3", "pdcp_content": pdcp.replace("lazy dog", "lazy dog.").replace("sleepy dog", "dog.")})
check("preview legacy 0.2.3 evaluated", pv0.get("status") in ("accepted", "rejected") and pv0.get("preview") is True, pv0)
pvr = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/1", "intent": "p", "expected_target_version": V,
                                    "edits": [{"match": "nope nope", "replace": "x"}]})
check("preview rejection carries failure_context and no partial facts", pvr.get("status") == "rejected" and "change_facts" not in pvr and (pvr.get("diagnostic") or {}).get("failure_context"), pvr)
pvi = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/3", "intent": "p", "expected_target_version": V,
                                    "replacement": "z", "edits": [{"match": "a", "replace": "b"}]})
check("preview rejects irrelevant proposal fields", pvi.get("status") == "invalid_argument" or "__rpc_error__" in pvi, pvi)
pvf = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/9", "intent": "p", "expected_target_version": V, "edits": []})
check("preview rejects unknown format", pvf.get("status") == "invalid_argument" or "__rpc_error__" in pvf, pvf)
pvs = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/1", "intent": "p", "expected_target_version": V - 1,
                                    "edits": [{"match": "lazy", "replace": "busy"}]})
check("preview stale guard -> target_version_mismatch", pvs.get("failure_reason") == "target_version_mismatch", pvs)
many = [{"match": f"filler line\n", "replace": f"filler line\n", "occurrence_index": i} for i in range(1, 41)]
pvb = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/1", "intent": "many", "expected_target_version": V, "edits": many})
pvb_bytes = len(json.dumps({k: v for k, v in pvb.items() if k != "__isError__"}, ensure_ascii=True, separators=(",", ":")).encode())
check("preview with 40 facts bounded to 32 with explicit truncation, <= 32768 bytes",
      pvb.get("status") == "accepted" and pvb.get("returned_fact_count") == 32 and pvb.get("total_change_count") == 40 and pvb.get("change_facts_truncated") is True and pvb_bytes <= 32768,
      {k: pvb.get(k) for k in ("status", "failure_reason", "returned_fact_count", "total_change_count", "change_facts_truncated", "change_facts_omission_reason")} | {"bytes": pvb_bytes})
snap_after = (len(logs(T)), len(ledger(T)), target_row(T), sql(f"select status, pdcp_content_hash from current_pdcp_files where target_file_id='{T}'"))
check("preview wrote nothing (logs/ledger/target/current_pdcp unchanged)", snap == snap_after, {"before": snap, "after": snap_after})

# ---------------------------------------------------------------- concurrency: preview does not block on a locked row; submit does
locker = subprocess.Popen(["docker", "exec", "-i", "patchdiff-postgres", "psql", "-U", "patchdiff", "-d", DB_NAME, "-v", "ON_ERROR_STOP=1"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
locker.stdin.write(f"BEGIN; SELECT version FROM cloud_target_files WHERE target_file_id='{T}' FOR UPDATE; UPDATE cloud_target_files SET version=version WHERE target_file_id='{T}';\n")
locker.stdin.flush()
time.sleep(1.5)
t0 = time.time()
pvl = s.call("patchdiff_preview", {"target_file_id": T, "format": "patchdiff-tx/1", "intent": "p", "expected_target_version": V,
                                    "edits": [{"match": "lazy", "replace": "busy"}]}, label="preview while row locked")
dt = time.time() - t0
check("preview completes while another session holds FOR UPDATE (no lock)", pvl.get("status") == "accepted" and dt < 1.5, {"seconds": round(dt, 3)})
result_box = {}
ready = threading.Event()
def bg_submit():
    s2 = Stdio()
    s2.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "pr11-b", "version": "0"}})
    s2.rpc("tools/list")
    ready.set()
    t1 = time.time()
    result_box["r"] = s2.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "blocked", "expected_target_version": V,
                               "operations": [{"op": "match", "match": "lazy", "replace": "busy"}]}, label="submit while row locked")
    result_box["dt"] = time.time() - t1
    s2.close()
th = threading.Thread(target=bg_submit); th.start()
ready.wait(60); time.sleep(3.0)
locker.stdin.write(f"UPDATE cloud_target_files SET version=version+1 WHERE target_file_id='{T}'; COMMIT;\n")
locker.stdin.close(); locker.wait(timeout=20)
th.join(timeout=30)
r = result_box.get("r", {})
check("submit blocks on the row lock, then rejects on advanced version (no lost update)",
      result_box.get("dt", 0) >= 2.0 and r.get("failure_reason") == "target_version_mismatch", {"dt": result_box.get("dt"), "r": r})
# restore consistency (externally bumped version, content unchanged)
cur = s.call("patchdiff_get_target", {"target_file_id": T}); V = cur["version"]

# ---------------------------------------------------------------- 12 save, 13 replay, 14 export
sv = s.call("patchdiff_save", {"target_file_id": T, "expected_current_hash": cur["current_hash"], "export_after_save": True})
check("save succeeds", sv.get("status") in ("saved", "ok", "accepted") or sv.get("snapshot_id") or sv.get("new_editing_cycle_id"), sv)
post = s.call("patchdiff_submit_operations", {"target_file_id": T, "intent": "after save", "expected_target_version": V,
                                               "operations": [{"op": "match", "match": "lazy", "replace": "busy"},
                                                              {"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": ">"}]})
check("tx/2 accepted in new cycle", post.get("status") == "accepted", post)
rpl = s.call("patchdiff_replay", {"target_file_id": T})
check("replay detects the out-of-band SQL version bump made by this harness (tamper detection)", rpl.get("status") == "failed" and "not contiguous" in (rpl.get("failure_detail") or ""), _trim(rpl, 200))
ex = s.call("patchdiff_export_target", {"target_file_id": T})
check("export returns canonical current content", sha(ex.get("content", "")) == target_row(T)[1], {k: ex.get(k) for k in ex if k != "content"})
rpl_crlf = s.call("patchdiff_replay", {"target_file_id": crlf_target})
check("replay of tx/2 CRLF target verifies", rpl_crlf.get("status") == "success" and rpl_crlf.get("materialized_state_matches") is True, _trim(rpl_crlf, 200))
upd = sql(f"select count(*) from append_only_pdcp_logs where target_file_id='{T}'")[0][0]


# ---------------------------------------------------------------- extra: clean mixed-format replay across SAVE
M = s.call("patchdiff_initialize_target", {"filename": "mixed.txt", "content": "one two three\nfour five six\n", "content_type": "text/plain"})["target_file_id"]
a1 = s.call("patchdiff_submit_edits", {"target_file_id": M, "intent": "tx1", "expected_target_version": 0, "edits": [{"match": "two", "replace": "2"}]})
leg = pdcp.replace(T, M).replace("lazy dog", "three").replace("sleepy dog", "3")
a2 = s.call("patchdiff_submit_pdcp", {"target_file_id": M, "pdcp_content": leg, "expected_target_version": 1})
mrej = s.call("patchdiff_submit_operations", {"target_file_id": M, "intent": "bad span", "expected_target_version": 2,
              "operations": [{"op": "span", "start": 0, "end": 3, "expected_text": "ONE", "replace": "1"}]})
mh = s.call("patchdiff_get_target", {"target_file_id": M})
msv = s.call("patchdiff_save", {"target_file_id": M, "expected_current_hash": mh["current_hash"]})
a3 = s.call("patchdiff_submit_operations", {"target_file_id": M, "intent": "tx2", "expected_target_version": 2, "parent_pdcp_log_id": mrej["pdcp_log_id"],
              "operations": [{"op": "span", "start": 0, "end": 3, "expected_text": "one", "replace": "1"}, {"op": "match", "match": "five", "replace": "5"}]})
a4 = s.call("patchdiff_submit_replacement", {"target_file_id": M, "intent": "tx3", "expected_target_version": 3, "replacement": "rewritten\r\nall\r\n"})
a5 = s.call("patchdiff_submit_edits", {"target_file_id": M, "intent": "tx1 after tx3", "expected_target_version": 4, "edits": [{"match": "all", "replace": "ALL"}]})
check("mixed target: tx/1, 0.2.3, tx/2 (after rejected parent across SAVE), tx/3, tx/1 all accepted",
      [x.get("status") for x in (a1, a2, a3, a4, a5)] == ["accepted"] * 5 and msv.get("status") == "saved",
      [(x.get("status"), x.get("failure_reason"), x.get("failure_detail")) for x in (a1, a2, a3, a4, a5)])
mr = s.call("patchdiff_replay", {"target_file_id": M})
check("replay success over mixed protocols/runtimes across SAVE with component checks",
      mr.get("status") == "success" and mr.get("materialized_state_matches") is True and all((mr.get("materialized_state_checks") or {}).values()), mr)
check("mixed target runtime pairing in DB",
      [r[2:4] for r in logs(M) if r[1] == "accepted"] == [["patchdiff-tx/1", "patchdiff-mvp-0.2.2"], ["0.2.3", "patchdiff-mvp-0.2.2"],
                                                         ["patchdiff-tx/2", "patchdiff-mvp-0.3.0"], ["patchdiff-tx/3", "patchdiff-mvp-0.4.0"],
                                                         ["patchdiff-tx/1", "patchdiff-mvp-0.2.2"]], logs(M))

# ---------------------------------------------------------------- extra: rejected exact-key recovery
K = s.call("patchdiff_initialize_target", {"filename": "k.txt", "content": "hello world\n", "content_type": "text/plain"})["target_file_id"]
r1 = s.call("patchdiff_submit_edits", {"target_file_id": K, "intent": "typo", "expected_target_version": 0, "client_request_id": "k-rej",
                                        "edits": [{"match": "helo world", "replace": "x"}]})
s.call("patchdiff_submit_edits", {"target_file_id": K, "intent": "move on", "expected_target_version": 0, "edits": [{"match": "hello", "replace": "HELLO"}]})
r2 = s.call("patchdiff_submit_edits", {"target_file_id": K, "intent": "typo", "expected_target_version": 0, "client_request_id": "k-rej",
                                        "edits": [{"match": "helo world", "replace": "x"}]})
check("rejected exact-key recovery: original failure_context unchanged, current_context fresh, near-miss recomputed",
      r2.get("deduplicated") is True and r2["diagnostic"]["failure_context"] == r1["diagnostic"]["failure_context"]
      and r2["current_context"]["text"].startswith("HELLO") and (r2.get("near_misses") or {}).get("status") == "computed",
      {"r1": r1.get("diagnostic"), "r2cc": r2.get("current_context"), "nm": r2.get("near_misses")})

# ---------------------------------------------------------------- extra: preview oversize replacement / near-miss latency
pvo = s.call("patchdiff_preview", {"target_file_id": K, "format": "patchdiff-tx/3", "intent": "big", "expected_target_version": 1, "replacement": "a" * 1_000_001})
check("preview oversize replacement -> invalid_argument replacement_too_large", pvo.get("status") == "invalid_argument" and pvo.get("code") == "replacement_too_large", pvo)
NM = s.call("patchdiff_initialize_target", {"filename": "nm.txt", "content": ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6), "content_type": "text/plain"})["target_file_id"]
timing = {}
for n in (20, 30, 38, 40, 48, 64):
    needle = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 2)[1:n + 1].replace("o", "0", 1)
    t0 = time.time()
    rr_ = s.call("patchdiff_submit_edits", {"target_file_id": NM, "intent": "nm", "expected_target_version": 0, "edits": [{"match": needle, "replace": "x"}]}, label=f"near-miss len {n}")
    timing[n] = {"seconds": round(time.time() - t0, 3), "status": (rr_.get("near_misses") or {}).get("status"),
                 "reason": (rr_.get("near_misses") or {}).get("omission_reason"), "found": len((rr_.get("near_misses") or {}).get("candidates", []))}
transcript.append({"label": "OBSERVATION near-miss by query length (failing-buffer scan)", "timing": timing})
check("near-miss timing recorded", True, timing)
print("NEAR-MISS TIMING", json.dumps(timing), flush=True)
tx2bad = s.call("patchdiff_submit_operations", {"target_file_id": K, "intent": "replace_all via tx2", "expected_target_version": 1, "operations": [{"op": "replace_all", "replace": "x"}]})
check("tx/2 rejects replace_all operation", tx2bad.get("status") == "rejected" or "__rpc_error__" in tx2bad, tx2bad)

# ---------------------------------------------------------------- 15/16 history paging
seen, before = [], None
while True:
    args = {"target_file_id": T, "limit": 3, **({"before_sequence": before} if before else {})}
    page = s.call("patchdiff_get_pdcp_log", args, label="get_pdcp_log page")
    seen += [a.get("log_sequence") for a in page.get("entries", [])]
    if not page.get("has_more"):
        break
    before = page.get("next_sequence")
check("pdcp_log paging traverses every attempt exactly once", len(seen) == int(upd) and len(set(seen)) == len(seen), {"seen": len(seen), "db": upd})
lseen, before = [], None
while True:
    args = {"target_file_id": T, "limit": 2, "include_previous_cycles": True, **({"before_sequence": before} if before else {})}
    page = s.call("patchdiff_get_manifest_ledger", args, label="ledger page")
    lseen += [e.get("ledger_sequence") for e in page.get("entries", [])]
    if not page.get("has_more"):
        break
    before = page.get("next_sequence")
check("ledger paging traverses every row exactly once", len(lseen) == len(ledger(T)) and len(set(lseen)) == len(lseen), {"seen": len(lseen), "db": len(ledger(T))})

# ---------------------------------------------------------------- 17-20 convenience + deprecated wrappers
pc = s.call("patchdiff_build_prompt_context", {"target_file_id": T, "user_request": "fix typo"})
check("build_prompt_context responds", "__rpc_error__" not in pc and not pc.get("__isError__"), _trim(pc, 120))
rej = s.call("patchdiff_submit_edits", {"target_file_id": T, "intent": "for regen", "expected_target_version": target_row_int if (target_row_int := int(target_row(T)[0])) else 0,
                                         "edits": [{"match": "does-not-exist", "replace": "x"}]})
rc = s.call("patchdiff_get_regeneration_context", {"pdcp_log_id": rej["pdcp_log_id"]})
check("deprecated get_regeneration_context still works for new rejection rows", "__rpc_error__" not in rc and not rc.get("__isError__"), _trim(rc, 120))
rpm = s.call("patchdiff_build_regeneration_prompt", {"pdcp_log_id": rej["pdcp_log_id"]})
check("deprecated build_regeneration_prompt still works", "__rpc_error__" not in rpm and not rpm.get("__isError__"), _trim(rpm, 120))
rr = s.call("patchdiff_request_regeneration", {"pdcp_log_id": rej["pdcp_log_id"]})
check("deprecated request_regeneration still responds", "__rpc_error__" not in rr and not rr.get("__isError__"), _trim(rr, 120))
# ================================================================ PR #11 friction follow-up: FR-1..FR-20
print("--- FR-1..FR-20 friction follow-up checks", flush=True)


def init(filename, content):
    return s.call("patchdiff_initialize_target", {"filename": filename, "content": content, "content_type": "text/plain"})


def codes(response):
    return [d.get("code") for d in response.get("warning_details") or []]


def diag(response):
    return response.get("diagnostic") or {}


def stored_diag(log_id):
    rows = sql(f"select coalesce(diagnostic_json::text,'null') from append_only_pdcp_logs where pdcp_log_id='{log_id}'")
    return json.loads(rows[0][0]) if rows else None


# FR-15/FR-16: parameter descriptions, mirrored guard rule, capabilities; FR-2/FR-3 schema surface
undescribed = sorted(f"{t['name']}.{p}" for t in tools for p, v in t["inputSchema"].get("properties", {}).items()
                     if not v.get("description"))
check("FR-15 every top-level tool parameter has a description", not undescribed, undescribed)
guarded = ("patchdiff_submit_edits", "patchdiff_submit_operations", "patchdiff_submit_replacement")
check("FR-15 submission descriptions mirror the guard rule",
      all("expected_target_version and/or expected_current_hash" in by_name[n]["description"] for n in guarded),
      {n: by_name[n]["description"][-200:] for n in guarded})
check("FR-2 read/search/submit descriptions say offsets are code points",
      all("Unicode code points" in by_name[n]["description"] for n in
          ("patchdiff_read_target", "patchdiff_find_occurrences", "patchdiff_submit_operations")),
      {n: by_name[n]["description"][-160:] for n in ("patchdiff_read_target", "patchdiff_find_occurrences")})
check("FR-2 tx/2 capabilities advertise span_context on runtime 0.5.0",
      by_name["patchdiff_submit_operations"]["inputSchema"].get("x-patchdiff-capabilities", {}).get("span_context") ==
      {"fields": ["expected_before", "expected_after"], "runtime_version": "patchdiff-mvp-0.5.0"},
      by_name["patchdiff_submit_operations"]["inputSchema"].get("x-patchdiff-capabilities"))
check("FR-3 export format is an enum of 4 values",
      by_name["patchdiff_export_target"]["inputSchema"]["properties"]["format"].get("enum") ==
      ["original_text", "canonical_lf", "crlf", "original_eol"], by_name["patchdiff_export_target"]["inputSchema"]["properties"]["format"])
check("FR-20 save schema exposes expected_target_version",
      "expected_target_version" in by_name["patchdiff_save"]["inputSchema"]["properties"])
check("FR-13 read_lines schema exposes include_line_starts",
      by_name["patchdiff_read_lines"]["inputSchema"]["properties"].get("include_line_starts", {}).get("type") == "boolean")

# FR-14: literal UTF-8 on the wire, status ok, structured argument errors
E = init("emoji.txt", "star 🌟 here\n")
check("FR-14 initialize_target returns status ok", E.get("status") == "ok", E)
s.call("patchdiff_read_target", {"target_file_id": E["target_file_id"]})
wire_line = s.last_line
tool_text = json.loads(wire_line.decode("utf-8"))["result"]["content"][0]["text"]
check("FR-14 tool text carries literal characters, not \\u escapes", "🌟" in tool_text and "\\ud83c" not in tool_text, tool_text[:200])
check("NF-2 JSON-RPC line is pure ASCII", wire_line.isascii(), wire_line[:200])
check("NF-2 a host decoding stdout as cp1252 reads identical text",
      json.loads(wire_line.decode("cp1252"))["result"]["content"][0]["text"] == tool_text)
SEP = init("seps.txt", "a\u2028b\u2029c\x85d\n")["target_file_id"]
sep_read = s.call("patchdiff_read_target", {"target_file_id": SEP})
check("NF-6 U+2028/U+2029/U+0085 round-trip without splitting the JSON-RPC line",
      sep_read.get("text") == "a\u2028b\u2029c\x85d\n" and s.last_line.isascii()
      and len(s.last_line.decode("utf-8").splitlines()) == 1, s.last_line[:200])
check("FR-14 handle_upload returns status ok and source_line_endings",
      up.get("status") == "ok" and (up.get("source_line_endings") or {}).get("style") == "crlf", up)
check("FR-14 get_target returns status ok", g.get("status") == "ok", g)
unk = s.call("patchdiff_get_target", {"target_file_id": T, "bogus": 1}, label="unknown argument")
check("FR-14 unknown argument -> structured invalid_argument JSON with isError",
      unk.get("__isError__") is True and unk.get("status") == "invalid_argument" and unk.get("code") == "unknown_argument"
      and unk.get("unknown_arguments") == ["bogus"], unk)
mis = s.call("patchdiff_get_target", {}, label="missing argument")
check("FR-14 missing argument -> structured invalid_argument JSON with isError",
      mis.get("__isError__") is True and mis.get("code") == "missing_argument" and mis.get("missing_arguments") == ["target_file_id"], mis)
check("FR-14 submission invalid_argument carries a top-level code", over_cp.get("code") == "replacement_too_large", over_cp)
check("FR-14 preview invalid_argument carries failure_detail", isinstance(pvi.get("failure_detail"), str) and pvi.get("code"), pvi)

# FR-1 / FR-17 / FR-9 / FR-10 / FR-11: sequential selector basis, warnings, current state, key diagnostics, joinable audit
F1 = init("fr1.txt", "cat dog cat dog cat\n")["target_file_id"]
w = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "rename two cats", "expected_target_version": 0,
                                       "client_request_id": "fr1-warn",
                                       "edits": [{"match": "cat", "replace": "CAT", "occurrence_index": 1, "change_id": "first",
                                                  "rationale": "first cat"},
                                                 {"match": "cat", "replace": "KITTEN", "occurrence_index": 2, "change_id": "second"}]})
shift = [d for d in w.get("warning_details") or [] if d.get("code") == "occurrence_index_basis_shift"]
check("FR-1 sequential index accepted with occurrence_index_basis_shift (transaction-start index 3)",
      w.get("status") == "accepted" and shift and shift[0].get("transaction_start_occurrence_index") == 3
      and shift[0].get("change_id") == "second", w)
check("FR-1 the sequential basis is what was applied",
      s.call("patchdiff_export_target", {"target_file_id": F1}).get("content") == "CAT dog cat dog KITTEN\n")
check("FR-17 warnings strings start with their code; count and truncation flags",
      all(x.startswith(c) for x, c in zip(w.get("warnings", []), codes(w))) and w.get("warning_count") == len(w.get("warning_details", []))
      and w.get("warnings_truncated") is False, {k: w.get(k) for k in ("warnings", "warning_count", "warnings_truncated")})
sd = stored_diag(w["pdcp_log_id"])
check("FR-17 accepted row with warnings persists the bounded envelope",
      isinstance(sd, dict) and sd.get("warning_count") == len(shift) and sd["warnings"][0]["code"] == "occurrence_index_basis_shift", sd)
check("FR-9 accepted response names current_version/current_hash",
      w.get("current_version") == w.get("version") == 1 and w.get("current_hash") == w.get("after_hash") == target_row(F1)[1], w)
plain = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "plain", "expected_target_version": 1,
                                           "edits": [{"match": "KITTEN", "replace": "kitten"}]})
check("FR-17 accepted row without warnings keeps diagnostic_json NULL",
      plain.get("status") == "accepted" and stored_diag(plain["pdcp_log_id"]) is None and plain.get("warnings") == [], plain)
check("NF-3 that NULL is SQL NULL, not a JSON null value",
      sql(f"select diagnostic_json is null, coalesce(jsonb_typeof(diagnostic_json), '') from append_only_pdcp_logs "
          f"where pdcp_log_id='{plain['pdcp_log_id']}'") == [["t", ""]])
rec = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "rename two cats", "expected_target_version": 0,
                                         "client_request_id": "fr1-warn",
                                         "edits": [{"match": "cat", "replace": "CAT", "occurrence_index": 1, "change_id": "first",
                                                    "rationale": "first cat"},
                                                   {"match": "cat", "replace": "KITTEN", "occurrence_index": 2, "change_id": "second"}]})
check("FR-9 keyed recovery after a later edit names the current state",
      rec.get("deduplicated") is True and rec.get("version") == 1 and rec.get("current_version") == 2
      and rec.get("current_hash") == target_row(F1)[1], rec)
check("FR-17 keyed recovery returns the stored warnings", rec.get("warning_details") == w.get("warning_details"), rec.get("warning_details"))
ambp = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "ambiguous after a prior change", "expected_target_version": 2,
                                          "edits": [{"match": "CAT", "replace": "C"}, {"match": "dog", "replace": "x"}]})
check("FR-1 ambiguity after prior changes names the sequential basis",
      ambp.get("failure_reason") == "match_ambiguous" and "after 1 earlier simulated change(s), not at transaction start" in (ambp.get("failure_detail") or ""),
      ambp.get("failure_detail"))
check("FR-1 ambiguity at transaction start keeps the historical detail",
      "not at transaction start" not in (amb.get("failure_detail") or ""), amb.get("failure_detail"))
disp = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "bad index after a prior change", "expected_target_version": 2,
                                          "edits": [{"match": "CAT", "replace": "C"}, {"match": "dog", "replace": "x", "occurrence_index": 3}]})
check("FR-1 disambiguation_invalid after prior changes names the sequential basis",
      disp.get("failure_reason") == "disambiguation_invalid" and "not at transaction start" in (disp.get("failure_detail") or ""), disp.get("failure_detail"))
conf = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "rename two cats", "expected_target_version": 0,
                                          "client_request_id": "fr1-warn",
                                          "edits": [{"match": "cat", "replace": "CAT", "occurrence_index": 1, "change_id": "first",
                                                     "rationale": "first cat"},
                                                    {"match": "cat", "replace": "LION", "occurrence_index": 2, "change_id": "second"}]})
check("FR-10 key conflict -> request_key_conflict naming the differing component and field",
      conf.get("failure_reason") == "context_invalid" and diag(conf).get("code") == "request_key_conflict"
      and diag(conf).get("differing_components") == ["pdcp_content_hash"] and diag(conf).get("differing_fields") == ["edits[1].replace"],
      diag(conf))
check("FR-10 conflict keeps the historical failure_detail", "already used" in (conf.get("failure_detail") or ""), conf.get("failure_detail"))
conf2 = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "rename two cats", "expected_target_version": 1,
                                           "client_request_id": "fr1-warn",
                                           "edits": [{"match": "cat", "replace": "CAT", "occurrence_index": 1, "change_id": "first",
                                                      "rationale": "first cat"},
                                                     {"match": "cat", "replace": "KITTEN", "occurrence_index": 2, "change_id": "second"}]})
check("FR-10 guard-only conflict names expected_target_version (a typed-record member, so the content hash differs too)",
      diag(conf2).get("differing_components") == ["pdcp_content_hash", "expected_target_version"]
      and diag(conf2).get("differing_fields") == ["expected_target_version"], diag(conf2))
badkey = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "bad key", "expected_target_version": 2,
                                            "client_request_id": "has space", "edits": [{"match": "CAT", "replace": "C"}]})
check("FR-10 invalid key syntax -> context_invalid with code invalid_client_request_id",
      badkey.get("failure_reason") == "context_invalid" and diag(badkey).get("code") == "invalid_client_request_id", badkey)
led1 = s.call("patchdiff_get_manifest_ledger", {"target_file_id": F1})["entries"]
first = [e for e in led1 if e.get("pdcp_log_id") == w["pdcp_log_id"]]
check("FR-11 ledger rows join to their attempt (log id, sequence, versions, cycle, change index, intent, rationale)",
      len(first) == 2 and all(e.get("log_sequence") and e.get("before_version") == 0 and e.get("after_version") == 1
                              and e.get("editing_cycle_id") and e.get("transaction_intent") == "rename two cats" for e in first)
      and [e.get("change_index") for e in first] == [1, 2] and first[0].get("rationale") == "first cat" and first[1].get("rationale") is None,
      first)
lg = s.call("patchdiff_get_pdcp_log", {"target_file_id": F1, "limit": 20})["entries"]
wl = [e for e in lg if e.get("pdcp_log_id") == w["pdcp_log_id"]][0]
check("FR-11 attempt entries carry attempt alias and bounded intent",
      "attempt" in wl and wl.get("attempt") == wl.get("regeneration_attempt") and wl.get("intent") == "rename two cats"
      and wl.get("intent_truncated") is False, wl)
longi = s.call("patchdiff_submit_edits", {"target_file_id": F1, "intent": "i" * 300, "expected_target_version": 2,
                                           "edits": [{"match": "nothing-here", "replace": "x"}]})
li = [e for e in s.call("patchdiff_get_pdcp_log", {"target_file_id": F1, "limit": 1})["entries"]][0]
check("FR-11 long intents are bounded to 256 code points", li.get("pdcp_log_id") == longi.get("pdcp_log_id")
      and len(li.get("intent") or "") == 256 and li.get("intent_truncated") is True, {k: li.get(k) for k in ("intent_truncated", "pdcp_log_id")})
legacy_rows = [e for e in s.call("patchdiff_get_manifest_ledger", {"target_file_id": M, "include_previous_cycles": True})["entries"]
               if e.get("pdcp_log_id") == a2.get("pdcp_log_id")]
check("FR-11 legacy PDCP ledger rows join with null typed intent/rationale",
      legacy_rows and legacy_rows[0].get("transaction_intent") is None and legacy_rows[0].get("log_sequence"), legacy_rows)

# FR-2: span context guards on immutable runtime 0.5.0; grapheme warning
F2 = init("fr2.md", "alpha\nbeta\n")["target_file_id"]
st2 = s.call("patchdiff_submit_operations", {"target_file_id": F2, "intent": "insert gamma", "expected_target_version": 0,
                                              "operations": [{"op": "span", "start": 6, "end": 6, "expected_text": "", "replace": "gamma\n",
                                                              "expected_before": "beta\n"}]})
check("FR-2 stale insertion offset caught by expected_before (span_expected_text_mismatch, span_check)",
      st2.get("failure_reason") == "span_expected_text_mismatch" and diag(st2).get("span_check") == "expected_before"
      and diag(st2).get("actual_text") == "lpha\n" and target_row(F2)[0] == "0", st2)
ea = s.call("patchdiff_submit_operations", {"target_file_id": F2, "intent": "after guard", "expected_target_version": 0,
                                             "operations": [{"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": "> ",
                                                             "expected_after": "zzz"}]})
check("FR-2 expected_after mismatch -> span_check expected_after",
      ea.get("failure_reason") == "span_expected_text_mismatch" and diag(ea).get("span_check") == "expected_after" and diag(ea).get("actual_text") == "alp", diag(ea))
ok2 = s.call("patchdiff_submit_operations", {"target_file_id": F2, "intent": "insert gamma", "expected_target_version": 0,
                                              "parent_pdcp_log_id": st2["pdcp_log_id"], "attempt": 2,
                                              "operations": [{"op": "span", "start": 11, "end": 11, "expected_text": "", "replace": "gamma\n",
                                                              "expected_before": "beta\r\n"},
                                                             {"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": "# ",
                                                              "expected_after": "alpha\n"}]})
check("FR-2 context-guarded spans accepted (CRLF guard canonicalized) on runtime 0.5.0",
      ok2.get("status") == "accepted" and logs(F2)[-1][2:4] == ["patchdiff-tx/2", "patchdiff-mvp-0.5.0"]
      and s.call("patchdiff_export_target", {"target_file_id": F2}).get("content") == "# alpha\nbeta\ngamma\n", (ok2, logs(F2)[-1]))
plain2 = s.call("patchdiff_submit_operations", {"target_file_id": F2, "intent": "no context", "expected_target_version": 1,
                                                 "operations": [{"op": "match", "match": "gamma", "replace": "GAMMA"}]})
check("FR-2 tx/2 without context keys stays on immutable runtime 0.3.0",
      plain2.get("status") == "accepted" and logs(F2)[-1][3] == "patchdiff-mvp-0.3.0", logs(F2)[-1])
emptyctx = s.call("patchdiff_submit_operations", {"target_file_id": F2, "intent": "empty context", "expected_target_version": 2,
                                                   "operations": [{"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": "x",
                                                                   "expected_before": ""}]})
check("FR-2 empty-string context is not accepted", emptyctx.get("status") != "accepted", emptyctx)
G = init("graph.txt", "café ok\n")["target_file_id"]
gw = s.call("patchdiff_submit_operations", {"target_file_id": G, "intent": "split", "expected_target_version": 0,
                                             "operations": [{"op": "span", "start": 4, "end": 4, "expected_text": "", "replace": "X"}]})
check("FR-2 span boundary before a combining mark -> grapheme_boundary_split warning (still accepted)",
      gw.get("status") == "accepted" and "grapheme_boundary_split" in codes(gw), gw)
n_f2_logs = len(logs(F2))
r2 = s.call("patchdiff_replay", {"target_file_id": F2})
check("FR-2 replay over 0.5.0 and 0.3.0 tx/2 rows succeeds",
      r2.get("status") == "success" and r2.get("materialized_state_matches") is True, _trim(r2, 200))
check("FR-2 replay re-derives without persisting new warnings",
      len(logs(F2)) == n_f2_logs and stored_diag(ok2["pdcp_log_id"]) is None, logs(F2))

# FR-3: recorded source line endings and honoured export formats
raw3 = "a\r\nb\r\n"
F3r = init("crlf3.md", raw3)
F3 = F3r["target_file_id"]
sle = F3r.get("source_line_endings") or {}
check("FR-3 initialize records CRLF source facts",
      sle.get("style") == "crlf" and sle.get("crlf") == 2 and sle.get("lf") == 0 and sle.get("cr") == 0 and sle.get("normalized") is True
      and sle.get("source_sha256") == sha(raw3) and sle.get("source_code_points") == len(raw3), sle)
check("FR-3 DB column records the style", sql(f"select source_line_endings->>'style' from cloud_target_files where target_file_id='{F3}'") == [["crlf"]])
check("FR-3 get_target returns source_line_endings", s.call("patchdiff_get_target", {"target_file_id": F3}).get("source_line_endings") == sle)
ex_def = s.call("patchdiff_export_target", {"target_file_id": F3})
check("FR-3 default export keeps canonical LF (original_text alias) with content_eol/content_sha256",
      ex_def.get("status") == "ok" and ex_def.get("content") == "a\nb\n" and ex_def.get("content_eol") == "lf"
      and ex_def.get("content_sha256") == sha("a\nb\n") and ex_def.get("format") == "original_text", {k: ex_def.get(k) for k in ex_def if k != "__isError__"})
ex_crlf = s.call("patchdiff_export_target", {"target_file_id": F3, "format": "crlf"})
check("FR-3 crlf export", ex_crlf.get("content") == raw3 and ex_crlf.get("content_eol") == "crlf" and ex_crlf.get("content_sha256") == sha(raw3), ex_crlf)
ex_orig = s.call("patchdiff_export_target", {"target_file_id": F3, "format": "original_eol"})
check("FR-3 original_eol restores CRLF byte-identically (content_sha256 == source_sha256)",
      ex_orig.get("content") == raw3 and ex_orig.get("content_sha256") == sle.get("source_sha256"), ex_orig)
check("FR-3 canonical hash unchanged by export format",
      ex_orig.get("current_hash", ex_orig.get("hash")) == ex_def.get("current_hash", ex_def.get("hash")) == target_row(F3)[1], (ex_orig, ex_def))
check("FR-3 canonical_lf export", s.call("patchdiff_export_target", {"target_file_id": F3, "format": "canonical_lf"}).get("content") == "a\nb\n")
CR = init("cr.txt", "a\rb\r")["target_file_id"]
check("FR-3 original_eol restores CR-only sources", s.call("patchdiff_export_target", {"target_file_id": CR, "format": "original_eol"}).get("content") == "a\rb\r")
MX = init("mixed-eol.txt", "a\r\nb\nc\r")
check("FR-3 mixed source recorded as mixed", (MX.get("source_line_endings") or {}).get("style") == "mixed", MX.get("source_line_endings"))
mxe = s.call("patchdiff_export_target", {"target_file_id": MX["target_file_id"], "format": "original_eol"})
check("FR-3 mixed original_eol -> invalid_argument original_eol_unrecoverable",
      mxe.get("status") == "invalid_argument" and mxe.get("code") == "original_eol_unrecoverable", mxe)
bad_fmt = s.call("patchdiff_export_target", {"target_file_id": F3, "format": "docx"})
check("FR-3 unknown format -> unsupported_export_format with allowed_formats (no silent echo)",
      bad_fmt.get("status") == "invalid_argument" and bad_fmt.get("code") == "unsupported_export_format"
      and bad_fmt.get("allowed_formats") == ["original_text", "canonical_lf", "crlf", "original_eol"], bad_fmt)
LEG = init("legacy-eol.txt", "x\r\ny\r\n")["target_file_id"]
sql(f"update cloud_target_files set source_line_endings=null where target_file_id='{LEG}'")  # simulate a pre-0003 target
check("FR-3 pre-0003 target reports unknown source line endings", s.call("patchdiff_get_target", {"target_file_id": LEG}).get("source_line_endings") is None)
lege = s.call("patchdiff_export_target", {"target_file_id": LEG, "format": "original_eol"})
check("FR-3 pre-0003 original_eol -> source_line_endings_unknown", lege.get("code") == "source_line_endings_unknown", lege)
check("FR-3 pre-0003 explicit crlf export still works", s.call("patchdiff_export_target", {"target_file_id": LEG, "format": "crlf"}).get("content") == "x\r\ny\r\n")

# FR-4 / FR-5: retryable flag and span evidence
check("FR-4 match_absent marked retryable (response and stored row)",
      diag(absent).get("retryable") is True and stored_diag(absent["pdcp_log_id"]).get("retryable") is True, diag(absent).get("retryable"))
check("FR-4 target_version_mismatch marked retryable", diag(stale).get("retryable") is True, diag(stale))
check("FR-4 span_expected_text_mismatch marked retryable", diag(atomic).get("retryable") is True, diag(atomic).get("retryable"))
badp = s.call("patchdiff_submit_pdcp", {"target_file_id": F3, "pdcp_content": "PDCP 0.2.3\ngarbage", "expected_target_version": 0})
check("FR-4 protocol failure not retryable", badp.get("status") == "rejected" and diag(badp).get("retryable") is False, badp)
check("FR-5 span text mismatch shows what is at the span",
      diag(atomic).get("span_check") == "expected_text" and diag(atomic).get("actual_text") == "ALPHA" and diag(atomic).get("expected_chars") == 5
      and diag(atomic).get("actual_chars") == 5 and isinstance(diag(atomic).get("buffer_length"), int) and diag(atomic).get("actual_text_truncated") is False,
      diag(atomic))
check("FR-5 out-of-bounds names the buffer length",
      diag(oob).get("span_check") == "bounds" and isinstance(diag(oob).get("buffer_length"), int), diag(oob))

# FR-6 / FR-7: near-miss scope and distinct locations; consumed sequential matches
check("FR-6 near-miss beyond the 256-point prefix is found in the failing buffer",
      nmf.get("status") == "computed" and nmf.get("scan_source") == "failing_buffer" and (nmf.get("scanned_end") or 0) > 256
      and any("zebra crossing" in c["text"] for c in nmf.get("candidates", [])), nmf)
check("FR-6 scan metadata present", all(k in nmf for k in ("scanned_start", "scanned_end", "scope_truncated", "candidates_truncated")), nmf)
nohit = s.call("patchdiff_submit_edits", {"target_file_id": NM, "intent": "far off", "expected_target_version": 0,
                                           "edits": [{"match": "QQQQQQQQQQQQ", "replace": "x"}]})
check("FR-6 empty near-miss result carries a find_occurrences hint",
      (nohit.get("near_misses") or {}).get("candidates") == [] and "patchdiff_find_occurrences" in ((nohit.get("near_misses") or {}).get("hint") or ""),
      nohit.get("near_misses"))
lor = s.call("patchdiff_submit_edits", {"target_file_id": NM, "intent": "typo", "expected_target_version": 0,
                                         "edits": [{"match": "Lorem ipsum d0lor", "replace": "x"}]})
cands = (lor.get("near_misses") or {}).get("candidates", [])
disjoint = all(a["end"] <= b["start"] or b["end"] <= a["start"] for i, a in enumerate(cands) for b in cands[i + 1:])
check("FR-7 near-miss candidates name distinct, non-overlapping locations", len(cands) >= 2 and disjoint, cands)
SQ = init("seq.txt", "quick brown fox\n")["target_file_id"]
sq = s.call("patchdiff_submit_edits", {"target_file_id": SQ, "intent": "overlap", "expected_target_version": 0,
                                        "edits": [{"match": "quick brown", "replace": "slow", "change_id": "c1"},
                                                  {"match": "brown fox", "replace": "x", "change_id": "c2"}]})
oo = diag(sq).get("original_occurrences") or [{}]
check("FR-7 consumed match -> sequential_match_invalid naming the consuming change",
      sq.get("failure_reason") == "sequential_match_invalid" and sq.get("failure_detail") == "MATCH text was consumed by earlier change c1 in this transaction."
      and diag(sq).get("original_occurrence_count") == 1 and oo[0].get("consumed_by_change_id") == "c1" and oo[0].get("start") == 6, sq)
check("FR-7 consumed match near misses omitted (sequential_match_consumed), no stored near_miss_query",
      (sq.get("near_misses") or {}).get("omission_reason") == "sequential_match_consumed" and "near_miss_query" not in stored_diag(sq["pdcp_log_id"]),
      sq.get("near_misses"))

# FR-8: focused window and deduplicated current context
F8 = init("long8.txt", "filler\n" * 100 + "zone a\nzone b\n")["target_file_id"]
z = s.call("patchdiff_submit_edits", {"target_file_id": F8, "intent": "late ambiguity", "expected_target_version": 0,
                                       "edits": [{"match": "zone", "replace": "Z"}]})
zfc = diag(z).get("failure_context") or {}
check("FR-8 late failure -> failure_window around the first candidate",
      zfc.get("selection") == "failure_window" and zfc.get("start", 10**9) <= 700 < zfc.get("end", 0) and "zone a" in (zfc.get("text") or ""), zfc)
check("FR-8 a focused window differs from the prefix, so current_context stays available (elided only when identical)",
      (z.get("current_context") or {}).get("available") is True and z["current_context"].get("selection") == "prefix", z.get("current_context"))
check("FR-8 (adapted PR #11 check) canonical-stage rejection elides current_context",
      (absent.get("current_context") or {}).get("unavailable_reason") == "same_as_failure_context" and fc.get("available") is True, absent.get("current_context"))
z2 = s.call("patchdiff_submit_edits", {"target_file_id": F8, "intent": "late ambiguity after prior", "expected_target_version": 0,
                                        "edits": [{"match": "filler\n", "replace": "F\n", "occurrence_index": 1}, {"match": "zone", "replace": "Z"}]})
check("FR-8 intermediate-buffer failure keeps a distinct current_context",
      diag(z2).get("failure_context", {}).get("buffer_stage") == "intermediate_buffer" and (z2.get("current_context") or {}).get("available") is True,
      z2.get("current_context"))

# FR-12: page byte budget over returned pdcp_content
F12 = init("big.txt", "seed\n")["target_file_id"]
b1 = s.call("patchdiff_submit_replacement", {"target_file_id": F12, "intent": "big one", "expected_target_version": 0, "replacement": "a" * 700_000})
b2 = s.call("patchdiff_submit_replacement", {"target_file_id": F12, "intent": "big two", "expected_target_version": 1, "replacement": "b" * 700_000})
pg = s.call("patchdiff_get_pdcp_log", {"target_file_id": F12, "limit": 2, "include_content": True})
ents = pg.get("entries", [])
check("FR-12 content page budget: first entry whole, later over-budget entry omitted",
      b1.get("status") == b2.get("status") == "accepted" and len(ents) == 2 and len(ents[0].get("pdcp_content") or "") > 700_000
      and ents[1].get("pdcp_content") is None and ents[1].get("pdcp_content_omitted") == "page_byte_budget",
      [{k: (v if k != "pdcp_content" else (len(v) if v else v)) for k, v in e.items()} for e in ents])
one = s.call("patchdiff_get_pdcp_log", {"target_file_id": F12, "limit": 1, "include_content": True, "before_sequence": ents[0]["log_sequence"]})
check("FR-12 omitted row is fetchable with limit 1", len((one.get("entries") or [{}])[0].get("pdcp_content") or "") > 700_000)

# FR-13: line-read coordinates
rl4 = s.call("patchdiff_read_lines", {"target_file_id": F3, "start_line": 1, "end_line": 2, "include_line_starts": True, "max_chars": 3})
check("FR-13 read_lines returns absolute next_start and line_starts",
      rl4.get("text") == "a\nb" and rl4.get("next_start") == 3 and rl4.get("next_offset") == 3
      and rl4.get("line_starts") == [{"line": 1, "start": 0}, {"line": 2, "start": 2}], rl4)
check("FR-13 next_start null when not truncated and line_starts opt-in only",
      rl.get("next_start") is None and "line_starts" not in rl, {k: rl.get(k) for k in ("next_start", "line_starts")})

# FR-17: no-op warnings
nop = s.call("patchdiff_submit_edits", {"target_file_id": F3, "intent": "no-op", "expected_target_version": 0,
                                         "edits": [{"match": "b", "replace": "b"}]})
check("FR-17 no-op change and transaction flagged but accepted",
      nop.get("status") == "accepted" and {"no_op_change", "no_op_transaction"} <= set(codes(nop)), nop)

# FR-18: missing numbers
check("FR-18 truncated exact_candidates names next_occurrence_index", ec.get("next_occurrence_index") == 6, ec)
od = diag(over_cp)
check("FR-18 replacement_too_large names actual/limit/canonical size",
      od.get("actual") == 1_000_001 and od.get("limit") == 1_000_000 and od.get("canonical_code_points") == 1_000_001
      and od.get("canonical_would_fit") is False, od)
cfit = s.call("patchdiff_submit_replacement", {"target_file_id": F12, "intent": "crlf at limit", "expected_target_version": 2,
                                                "replacement": "a" * 999_999 + "\r\n"})
check("FR-18 raw-over/canonical-fit case reports canonical_would_fit (admission rule unchanged)",
      cfit.get("status") == "invalid_argument" and diag(cfit).get("limit_exceeded") == "raw_code_points"
      and diag(cfit).get("canonical_code_points") == 1_000_000 and diag(cfit).get("canonical_would_fit") is True, diag(cfit))

# FR-19: preview recovery parity
pnm = s.call("patchdiff_preview", {"target_file_id": SQ, "format": "patchdiff-tx/1", "intent": "p", "expected_target_version": 0,
                                    "edits": [{"match": "quick brwn fox", "replace": "x"}]})
check("FR-19 preview computes near_misses inline",
      pnm.get("failure_reason") == "match_absent" and (pnm.get("near_misses") or {}).get("status") == "computed"
      and any("quick brown fox" in c.get("text", "") for c in (pnm.get("near_misses") or {}).get("candidates", [])), pnm.get("near_misses"))
pcor = s.call("patchdiff_preview", {"target_file_id": SQ, "format": "patchdiff-tx/1", "intent": "p", "expected_target_version": 0,
                                     "edits": [{"match": "quick", "replace": "x"}], "include_correlation_id": True})
check("FR-19 preview include_correlation_id -> structured unknown_argument",
      pcor.get("__isError__") is True and pcor.get("code") == "unknown_argument" and pcor.get("unknown_arguments") == ["include_correlation_id"], pcor)

# FR-20: version-guarded SAVE
snaps = lambda t: int(sql(f"select count(*) from target_snapshots where target_file_id='{t}'")[0][0])
n_snap = snaps(SQ)
sv_stale = s.call("patchdiff_save", {"target_file_id": SQ, "expected_target_version": 5})
check("FR-20 stale expected_target_version -> rejected target_version_mismatch, no snapshot",
      sv_stale.get("status") == "rejected" and sv_stale.get("failure_reason") == "target_version_mismatch" and snaps(SQ) == n_snap, sv_stale)
sv_bad = s.call("patchdiff_save", {"target_file_id": SQ, "expected_target_version": -1})
check("FR-20 invalid expected_target_version -> context_invalid", sv_bad.get("failure_reason") == "context_invalid" and snaps(SQ) == n_snap, sv_bad)
sq_hash = target_row(SQ)[1]
sv_both = s.call("patchdiff_save", {"target_file_id": SQ, "expected_target_version": 0, "expected_current_hash": "0" * 64})
check("FR-20 both guards checked when supplied", sv_both.get("status") == "rejected" and snaps(SQ) == n_snap, sv_both)
sv_ok = s.call("patchdiff_save", {"target_file_id": SQ, "expected_target_version": 0, "expected_current_hash": sq_hash})
check("FR-20 matching guards save", sv_ok.get("status") == "saved" and snaps(SQ) == n_snap + 1, sv_ok)

# global: clean replays for every FR target
for label, tid in (("F1", F1), ("F3", F3), ("G", G), ("SQ", SQ), ("F8", F8), ("F12", F12), ("CR", CR)):
    rp_ = s.call("patchdiff_replay", {"target_file_id": tid}, label=f"replay {label}")
    check(f"FR replay {label} succeeds", rp_.get("status") == "success" and rp_.get("materialized_state_matches") is True, _trim(rp_, 200))

check("NF-3 no accepted row anywhere stores a JSON null diagnostic",
      sql("select count(*) from append_only_pdcp_logs where status='accepted' and jsonb_typeof(diagnostic_json)='null'") == [["0"]])
stderr = s.close()
check("adapter stderr clean", not stderr.strip(), stderr[-2000:])

OUT.write_text(json.dumps({"checks": checks, "transcript": transcript}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
failed = [c for c in checks if not c["ok"]]
print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed of {len(checks)} checks")
sys.exit(1 if failed else 0)
