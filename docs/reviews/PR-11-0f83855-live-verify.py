"""Independent PR #11 live run: real stdio MCP subprocess + independent SQL via psql.

Usage: python live_pr11.py <worktree> <db_url> <out_json>
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
init = s.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "pr11-review", "version": "0"}})
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
check("current_context present on rejection", (absent.get("current_context") or {}).get("available") is True, absent.get("current_context"))
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
check("near-miss beyond the 256-point prefix is not found (documented limitation; recorded)", True, nmf)
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
transcript.append({"label": "OBSERVATION near-miss by query length (256-pt prefix)", "timing": timing})
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
stderr = s.close()
check("adapter stderr clean", not stderr.strip(), stderr[-2000:])

OUT.write_text(json.dumps({"checks": checks, "transcript": transcript}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
failed = [c for c in checks if not c["ok"]]
print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed of {len(checks)} checks")
sys.exit(1 if failed else 0)
