"""Read-only review of supplied Gemini reports and their accessible live evidence."""
import datetime
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
ORIGINAL = Path(r"C:\Users\USER\Desktop\Frameworks\Patch-DIFF")
PLAYGROUND = Path(r"C:\Users\USER\Desktop\Frameworks\Antigravity-playground\patch-diff\Patch-DIFF")
reports = sorted((ORIGINAL / "docs/reviews/gemini/v1").glob("*.md")) + sorted((ORIGINAL / "docs/reviews/gemini/v2").glob("*.md"))
output = {"checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "python": sys.version, "classification": "Independent artifact inspection and read-only SQL; no Gemini workflow rerun or product mutation.", "report_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in reports}}
output["playground_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PLAYGROUND, text=True).strip()
output["playground_status"] = subprocess.check_output(["git", "status", "--short"], cwd=PLAYGROUND, text=True)
results_path = PLAYGROUND / "live_test_results.json"
steps = json.loads(results_path.read_text(encoding="utf-8"))
output["harness"] = {"file": str(results_path), "sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(), "status_counts": dict(Counter(s["status"] for s in steps)), "concurrency": [{k: s[k] for k in ("step_id", "observed", "status")} for s in steps if s["step_id"].startswith("CONCURRENCY")]}
g02_path = PLAYGROUND / "docs/gemini-remediation/G02-live-results.json"
g02 = json.loads(g02_path.read_text(encoding="utf-8"))
output["g02"] = {"file": str(g02_path), "sha256": hashlib.sha256(g02_path.read_bytes()).hexdigest(), "top_level_keys": list(g02) if isinstance(g02, dict) else None}
if isinstance(g02, dict):
    for key in ("source_head", "executed_head", "database", "summaries", "profiles", "source_sha"):
        if key in g02:
            output["g02"][key] = g02[key]
    output["g02"]["source_hashes_match_current_files"] = {name: hashlib.sha256((PLAYGROUND / name).read_bytes()).hexdigest() == digest for name, digest in g02["source_sha256"].items()}
    with psycopg.connect("postgresql://patchdiff:patchdiff@127.0.0.1:5432/" + g02["database"], options="-c default_transaction_read_only=on") as conn:
        checks = []
        for summary in g02["summaries"]:
            target = summary["target_file_id"]
            row = conn.execute("SELECT current_content,version FROM cloud_target_files WHERE target_file_id=%s", (target,)).fetchone()
            counts = dict(conn.execute("SELECT status,count(*) FROM append_only_pdcp_logs WHERE target_file_id=%s GROUP BY status", (target,)))
            ledger = conn.execute("SELECT count(*) FROM append_only_manifest_ledger WHERE target_file_id=%s", (target,)).fetchone()[0]
            actual = None if row is None else {"content": row[0], "version": row[1], "logs": counts, "ledger": ledger}
            checks.append({"target": target, "SQL_matches_recorded_summary": actual == summary["exact_SQL_state"]})
        output["g02"]["independent_live_read_only_SQL"] = checks

catalogs = {}
for host in ("127.0.0.1", "localhost"):
    with psycopg.connect(f"postgresql://patchdiff:patchdiff@{host}:5432/postgres", options="-c default_transaction_read_only=on") as conn:
        catalogs[host] = {"server_version": conn.execute("SELECT version()").fetchone()[0], "databases": [row[0] for row in conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'patchdiff%' ORDER BY datname")], "read_only": conn.execute("SHOW transaction_read_only").fetchone()[0]}
output["database_catalogs"] = catalogs
if "patchdiff_subagent_v2_eval" not in catalogs["127.0.0.1"]["databases"]:
    output["database_verification"] = "Unavailable: reported v2 database does not currently exist; no conclusion about historical run validity. No database was created or modified."
else:
    output["database_verification"] = "Database exists. This checker does not rerun W1-W12 or authenticate historical timing/SQL claims."

(HERE / "GEMINI-v2-evidence-check.json").write_text(json.dumps(output, ensure_ascii=True, indent=2), encoding="utf-8")
print(json.dumps(output, ensure_ascii=True, indent=2))
