"""Offline payload accounting for PDCP v0.2.3, tx/1 and guarded tx/3 proposals.

Deterministic; no model, no network, no database. It answers ONLY:
  * how many UTF-8 bytes does an equivalent proposal take in each serialization,
    separating input-format framing overhead from reduced-manifest prose savings?
  * how many UTF-8 bytes does the MCP tool-call request payload take vs the
    persisted canonical record stored in append_only_pdcp_logs.pdcp_content?
  * does each serialization reach the exact same verdict and after_hash through
    the shared deterministic applier?
  * can each serialization express the edit at all (delimiter collision)?

Three proposal variants are compared per scenario:
  1. PDCP v0.2.3 (required 7 manifest fields per change block)
  2. Typed patchdiff-tx/1 with matched advisory prose (intent + per-edit change_id,
     rationale carrying the equivalent prose description, and risk="low")
  3. Minimal typed patchdiff-tx/1 (intent + {match, replace} only)

A separate tx/3 section measures the same admitted, guarded whole-target replacement
as its persisted canonical record and complete tools/call request line. The latter
uses fixed JSON-RPC id=1, compact UTF-8 JSON and one LF; it is a deterministic
serialization measurement, not a captured network/database run. Its accepted result
and hash are checked against explicit content oracles through the frozen 0.4.0
applier. It makes no cross-format verdict-equivalence claim for replacement.

It does NOT measure tokens, model validity rates, task success, latency, or recovery
turns. Those require a live-model study (see docs/MODERNIZATION_CHANGE_DOC.md),
which has NOT been run. Bytes are a deterministic measure of wire/storage size, not
model inference cost.

Run from the repo root:  PYTHONPATH=backend python backend/tests/verification/offline_eval.py
"""

from __future__ import annotations

import json
import sys
from typing import Any

from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult
from app.core.versions import REPLACEMENT_RUNTIME_VERSION, resolve_runtime_profile
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.parser import PDCPParseError, parse_pdcp
from app.pdcp.protocol_validator import ProtocolValidationError, validate_pdcp
from app.pdcp.replacement import (
    build_replacement_record, decode_replacement_record, replacement_size_error, to_parsed_replacement,
)
from app.pdcp.typed import build_record, canonical_record_json, parse_typed_record, to_parsed_transaction

TARGET_ID = "11111111-1111-1111-1111-111111111111"
LONG_BODY = "\n".join(f"line {i}: the quick brown fox jumps over the lazy dog" for i in range(40))

MATCHED_RATIONALE = (
    "input_state: Old text exists. | output_state: New text exists. | "
    "affected_region: example | user_visible_change: Text changes."
)

SCENARIOS = [
    (
        "1 tiny edit",
        "old",
        [("old", "new")],
        "accepted",
        canonical_sha256("new"),
        "accepted",
        canonical_sha256("new"),
    ),
    (
        "5 small edits",
        "a b c d e",
        [("a", "1"), ("b", "2"), ("c", "3"), ("d", "4"), ("e", "5")],
        "accepted",
        canonical_sha256("1 2 3 4 5"),
        "accepted",
        canonical_sha256("1 2 3 4 5"),
    ),
    (
        "1 edit, 2 KB span",
        LONG_BODY,
        [(LONG_BODY, LONG_BODY.replace("fox", "cat"))],
        "accepted",
        canonical_sha256(LONG_BODY.replace("fox", "cat")),
        "accepted",
        canonical_sha256(LONG_BODY.replace("fox", "cat")),
    ),
    (
        "quotes+backslashes+unicode",
        'say "hi" \\ \u00e9\u4e2d',
        [('"hi" \\ \u00e9', '"yo" \\\\ \u4e2d')],
        "accepted",
        canonical_sha256('say "yo" \\\\ \u4e2d\u4e2d'),
        "accepted",
        canonical_sha256('say "yo" \\\\ \u4e2d\u4e2d'),
    ),
    (
        "payload has a delimiter line",
        "a\n=======\nb",
        [("a\n=======\nb", "a\nb")],
        "rejected:block_malformed",
        None,
        "accepted",
        canonical_sha256("a\nb"),
    ),
]

REPLACEMENT_SCENARIOS = [
    ("guarded whole-target rewrite", "old", "new", "new"),
    ("empty target", "", "new", "new"),
    ("empty replacement", "old", "", ""),
    ("unicode, quotes, CRLF", "\u00e9 \u4e2d \U0001f31f", 'say "hi" \\\r\n\U0001f31f', 'say "hi" \\\n\U0001f31f'),
    ("whole-target 2 KB rewrite", LONG_BODY, LONG_BODY.replace("fox", "cat"), LONG_BODY.replace("fox", "cat")),
]


def pdcp_text(edits: list[tuple[str, str]]) -> str:
    parts = [f"PDCP 0.2.3\ntarget_file_id: {TARGET_ID}\ntarget_type: text/plain"]
    for i, (match, replace) in enumerate(edits, start=1):
        parts.append(
            f"# MANIFEST\n# change_id: chg_{i:03d}\n# intent: Update text.\n# input_state: Old text exists.\n"
            f"# output_state: New text exists.\n# affected_region: example\n# user_visible_change: Text changes.\n"
            f"# risk: low\n\n<<<<<<< MATCH\n{match}\n=======\n{replace}\n>>>>>>> REPLACE"
        )
    return "\n\n".join(parts)


def pdcp_mcp_request_json(edits: list[tuple[str, str]]) -> str:
    payload = {
        "target_file_id": TARGET_ID,
        "pdcp_content": pdcp_text(edits),
        "expected_target_version": 0,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def typed_matched_edits(edits: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "change_id": f"chg_{i:03d}",
            "match": m,
            "replace": r,
            "rationale": MATCHED_RATIONALE,
            "risk": "low",
        }
        for i, (m, r) in enumerate(edits, start=1)
    ]


def typed_minimal_edits(edits: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return [{"match": m, "replace": r} for m, r in edits]


def typed_mcp_request_json(edit_items: list[dict[str, Any]]) -> str:
    payload = {
        "target_file_id": TARGET_ID,
        "intent": "Update text.",
        "edits": edit_items,
        "expected_target_version": 0,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def typed_persisted_record_json(edit_items: list[dict[str, Any]]) -> str:
    record = build_record(
        target_file_id=TARGET_ID,
        intent="Update text.",
        edits=edit_items,
        expected_target_version=0,
        expected_current_hash=None,
    )
    return canonical_record_json(record)


def run_pdcp(target: str, edits: list[tuple[str, str]]) -> tuple[str, str | None]:
    try:
        parsed = parse_pdcp(pdcp_text(edits))
        validate_pdcp(parsed)
    except (PDCPParseError, ProtocolValidationError) as exc:
        return f"rejected:{exc.failure_reason.value}", None
    result = apply_pdcp_transaction(target, parsed)
    return _verdict(result)


def run_typed(target: str, persisted_json: str) -> tuple[str, str | None]:
    typed = parse_typed_record(json.loads(persisted_json))
    return _verdict(apply_pdcp_transaction(target, to_parsed_transaction(typed, target_type="text/plain")))


def replacement_payloads(target: str, replacement: str) -> tuple[str, str]:
    """Serialize one guarded proposal in storage and complete stdio request forms."""
    arguments = {
        "target_file_id": TARGET_ID, "intent": "Replace complete target.", "replacement": replacement,
        "expected_target_version": 0, "expected_current_hash": canonical_sha256(target),
    }
    persisted = canonical_record_json(build_replacement_record(
        target_file_id=TARGET_ID, intent=arguments["intent"], replacement=replacement,
        expected_target_version=arguments["expected_target_version"],
        expected_current_hash=arguments["expected_current_hash"],
    ))
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "patchdiff_submit_replacement", "arguments": arguments}}
    wire_line = json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    return persisted, wire_line


def replacement_matches_oracle(target: str, persisted_json: str, expected: str) -> bool:
    """Check fresh admission and accepted replacement execution, without persistence."""
    record = json.loads(persisted_json)
    replacement = record["operations"][0]["replace"]
    if replacement_size_error(replacement) is not None:
        return False
    # This section models the known initial version=0 and both matching guards.
    if record["expected_target_version"] != 0 or record["expected_current_hash"] != canonical_sha256(target):
        return False
    transaction = decode_replacement_record(persisted_json, runtime_version=REPLACEMENT_RUNTIME_VERSION)
    profile = resolve_runtime_profile(REPLACEMENT_RUNTIME_VERSION)
    result = apply_pdcp_transaction(
        target, to_parsed_replacement(transaction, target_type="text/plain"),
        overlapping_matches=profile.overlapping_matches,
        enforce_singleton_selectors=profile.enforce_singleton_selectors,
        allow_span_operations=profile.span_operations,
        allow_replace_all_operations=profile.replace_all_operations,
    )
    return (isinstance(result, AcceptedCoreResult) and result.target_content == expected
            and result.after_hash == canonical_sha256(expected) and result.change_count == 1
            and result.change_facts[0]["operation"] == "replace_all")


def _verdict(result: Any) -> tuple[str, str | None]:
    if isinstance(result, AcceptedCoreResult):
        return "accepted", result.after_hash
    return f"rejected:{result.failure_reason.value}", None


def main() -> int:
    print("=== 1. Persisted Record UTF-8 Bytes (append_only_pdcp_logs.pdcp_content) ===")
    header = (
        f"{'scenario':30} {'pdcp B':>8} {'typed_match B':>14} {'typed_min B':>12} "
        f"{'match/pdcp':>11} {'min/pdcp':>9}  verdict (pdcp / matched / minimal)"
    )
    print(header)
    print("-" * len(header))
    all_equivalent = True
    for name, target, edits, exp_pdcp_v, exp_pdcp_h, exp_typed_v, exp_typed_h in SCENARIOS:
        p_raw = pdcp_text(edits)
        t_matched_persisted = typed_persisted_record_json(typed_matched_edits(edits))
        t_min_persisted = typed_persisted_record_json(typed_minimal_edits(edits))

        p_bytes = len(p_raw.encode("utf-8"))
        tm_bytes = len(t_matched_persisted.encode("utf-8"))
        tn_bytes = len(t_min_persisted.encode("utf-8"))

        pv, ph = run_pdcp(target, edits)
        tmv, tmh = run_typed(target, t_matched_persisted)
        tnv, tnh = run_typed(target, t_min_persisted)

        # Oracle checks: actual verdicts/hashes must match independent expectations
        pdcp_matches_oracle = (pv == exp_pdcp_v) and (ph == exp_pdcp_h)
        typed_matches_oracle = (
            (tmv == exp_typed_v and tmh == exp_typed_h)
            and (tnv == exp_typed_v and tnh == exp_typed_h)
        )

        # SCRIPT-001: The delimiter scenario is the sole recognized expressibility gap
        is_delimiter_scenario = (name == "payload has a delimiter line")
        expressible_gap = (
            is_delimiter_scenario
            and pv.startswith("rejected:block_malformed")
            and tmv == "accepted"
            and tnv == "accepted"
        )
        typed_agree = (tmv, tmh) == (tnv, tnh)
        same = (
            pdcp_matches_oracle
            and typed_matches_oracle
            and typed_agree
            and ((pv, ph) == (tmv, tmh) or expressible_gap)
        )
        all_equivalent &= same
        note = " [PDCP delimiter collision]" if expressible_gap else ""
        print(
            f"{name:30} {p_bytes:8d} {tm_bytes:14d} {tn_bytes:12d} "
            f"{tm_bytes / p_bytes:11.2f} {tn_bytes / p_bytes:9.2f}  "
            f"{pv} / {tmv} / {tnv}{note}"
        )

    print()
    print("=== 2. MCP Tool Request Payload UTF-8 Bytes (wire arguments JSON) ===")
    req_header = (
        f"{'scenario':30} {'submit_pdcp B':>14} {'edits_match B':>14} {'edits_min B':>12} "
        f"{'match/pdcp':>11} {'min/pdcp':>9}"
    )
    print(req_header)
    print("-" * len(req_header))
    for name, _target, edits, *rest in SCENARIOS:
        p_req_bytes = len(pdcp_mcp_request_json(edits).encode("utf-8"))
        tm_req_bytes = len(typed_mcp_request_json(typed_matched_edits(edits)).encode("utf-8"))
        tn_req_bytes = len(typed_mcp_request_json(typed_minimal_edits(edits)).encode("utf-8"))
        print(
            f"{name:30} {p_req_bytes:14d} {tm_req_bytes:14d} {tn_req_bytes:12d} "
            f"{tm_req_bytes / p_req_bytes:11.2f} {tn_req_bytes / p_req_bytes:9.2f}"
        )

    print()
    print("=== 3. Guarded tx/3 Replacement UTF-8 Bytes (same proposal, storage vs complete request) ===")
    print(f"{'scenario':30} {'tx/3 record B':>14} {'tools/call line B':>18}  accepted content/hash oracle")
    all_replacements = True
    for name, target, replacement, expected in REPLACEMENT_SCENARIOS:
        persisted, wire_line = replacement_payloads(target, replacement)
        matches = replacement_matches_oracle(target, persisted, expected)
        all_replacements &= matches
        print(f"{name:30} {len(persisted.encode('utf-8')):14d} {len(wire_line.encode('utf-8')):18d}  "
              f"{'OK' if matches else 'MISMATCH'}")
    print("  tx/3 request = compact UTF-8 JSON-RPC tools/call, fixed id=1, including one terminal LF.")
    print("  Counts are serialized bytes; no live transport, persistence, timing or representative workload is measured.")

    print()
    print("Accounting separation:")
    print("  - pdcp vs typed_match isolates serialization/framing difference with matched advisory prose.")
    print("  - typed_match vs typed_min isolates byte savings from dropping mandatory prose manifest fields.")
    print("  - tx/1 persisted bytes include format='patchdiff-tx/1' and nullable guard fields; omitted edit defaults stay omitted.")
    print("  - MCP request payload bytes measure the JSON arguments sent over tools/call.")
    print("Bytes only. Not tokens, not model validity, not task success. Live-model study: NOT RUN.")
    print("Verdict equivalence on the shared applier:", "OK" if all_equivalent else "MISMATCH")
    print("  Historical equivalence permits only the named PDCP delimiter-collision expressibility exception.")
    print("Accepted guarded replacement content/hash oracles:", "OK" if all_replacements else "MISMATCH")
    return 0 if all_equivalent and all_replacements else 1


if __name__ == "__main__":
    sys.exit(main())
