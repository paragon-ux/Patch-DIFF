"""Separate public-stdio/SQL probe for preview's actual whole-payload budgets."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("pass_b_live", ROOT / "docs/usability/PASS-B-live-verify.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


def pdcp(target, change_id, match="absent"):
    return f"""PDCP 0.2.3
target_file_id: {target}
target_type: text/plain

# MANIFEST
# change_id: {change_id}
# intent: Bound preview evidence.
# input_state: Original.
# output_state: Proposed.
# affected_region: target
# user_visible_change: proposed
# risk: low

<<<<<<< MATCH
{match}
=======
x
>>>>>>> REPLACE
"""


client = live.Client()
checks = []
try:
    client.rpc("initialize", {})
    target = client.call("patchdiff_initialize_target", {
        "filename": "budget-🌟.txt", "content_type": "text/plain", "content": "x"})["target_file_id"]
    before = live.all_tables()
    many = client.call("patchdiff_preview", {
        "target_file_id": target, "format": "patchdiff-tx/2", "intent": "Bound whole facts.",
        "expected_target_version": 0,
        "operations": [{"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": ""}] * 40})
    assert many["status"] == "accepted" and many["total_change_count"] == 40
    assert many["returned_fact_count"] == 32 and len(many["change_facts"]) == 32 and many["change_facts_truncated"]
    assert many["change_facts_omission_reason"] == "fact_count_limit"
    assert many["after_hash"] == hashlib.sha256(b"x").hexdigest()
    assert live.size({"change_facts": many["change_facts"]}) <= 16384
    assert all(live.size(fact) <= 2048 for fact in many["change_facts"])
    checks.append("many_accepted_facts_prefix_counts_whole_fact_byte_budgets")

    guard = client.call("patchdiff_preview", {
        "target_file_id": target, "format": "patchdiff-tx/3", "intent": "Bound raw guard evidence.",
        "replacement": "y", "expected_target_version": {"untrusted": "🌟" * 10000}})
    assert guard["status"] == "rejected" and guard["failure_reason"] == "context_invalid"
    assert guard["current_version"] == 0 and guard["evidence_omissions"]
    giant_id = "c" * 10000
    legacy = client.call("patchdiff_preview", {"target_file_id": target, "format": "0.2.3",
                         "pdcp_content": pdcp(target, giant_id)})
    assert legacy["status"] == "rejected" and legacy["failure_reason"] == "match_absent"
    assert legacy.get("failed_change_id") is None and "failed_change_id" in legacy["evidence_omissions"]
    assert "change_facts" not in legacy
    invalid = client.call("patchdiff_preview", {"target_file_id": "z" * 10000, "format": "patchdiff-tx/3",
                          "intent": "Bound invalid identity echo.", "replacement": "y", "expected_target_version": 0})
    assert invalid["status"] == "rejected" and invalid.get("target_file_id") is None
    assert "target_file_id" in invalid["evidence_omissions"]
    checks.append("huge_raw_guard_legacy_failed_identity_invalid_target_echo_explicit_omission")
    for payload in (many, guard, legacy, invalid):
        assert live.size(payload) <= 32768
    assert live.all_tables() == before
    state = live.state(target)
    assert state["version"] == 0 and state["content"] == "x" and not state["logs"] and not state["ledger"]
    checks.append("all_payloads_actual_ascii_json_budget_all_managed_table_content_nonmutation")
finally:
    client.close()

result = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
          "target_file_id": target, "checks": checks, "final_sql": state,
          "response_bytes": {name: live.size(payload) for name, payload in (
              ("many_facts", many), ("raw_guard", guard), ("legacy_id", legacy), ("invalid_target", invalid))},
          "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted((ROOT / "backend/app").rglob("*.py"))},
          "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "shared_helper_sha256": hashlib.sha256((ROOT / "docs/usability/PASS-B-live-verify.py").read_bytes()).hexdigest(),
          "events": live.EVENTS}
output = ROOT / "docs/usability/PASS-B-budget-live-results.json"
output.write_text(json.dumps(result, ensure_ascii=True, indent=2, default=str) + "\n", encoding="utf-8")
print(f"PASS: {len(checks)} budget groups; target={target}; output={output}")
