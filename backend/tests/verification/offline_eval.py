"""Check typed proposal verdicts, hashes and UTF-8 serialization sizes offline."""

from __future__ import annotations

import json
import sys
from typing import Any

from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult
from app.core.versions import REPLACEMENT_RUNTIME_VERSION, resolve_runtime_profile
from app.pdcp.applier import apply_pdcp_transaction
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
        canonical_sha256("new"),
    ),
    (
        "5 small edits",
        "a b c d e",
        [("a", "1"), ("b", "2"), ("c", "3"), ("d", "4"), ("e", "5")],
        canonical_sha256("1 2 3 4 5"),
    ),
    (
        "1 edit, 2 KB span",
        LONG_BODY,
        [(LONG_BODY, LONG_BODY.replace("fox", "cat"))],
        canonical_sha256(LONG_BODY.replace("fox", "cat")),
    ),
    (
        "quotes+backslashes+unicode",
        'say "hi" \\ \u00e9\u4e2d',
        [('"hi" \\ \u00e9', '"yo" \\\\ \u4e2d')],
        canonical_sha256('say "yo" \\\\ \u4e2d\u4e2d'),
    ),
    (
        "payload has a delimiter line",
        "a\n=======\nb",
        [("a\n=======\nb", "a\nb")],
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
    print("=== Typed tx/1 UTF-8 Bytes and Accepted Hash Oracle ===")
    print(f"{'scenario':30} {'record B':>13} {'arguments B':>13}  variant")
    all_equivalent = True
    for name, target, edits, expected_hash in SCENARIOS:
        for label, edit_items in (("with metadata", typed_matched_edits(edits)),
                                  ("minimal", typed_minimal_edits(edits))):
            persisted = typed_persisted_record_json(edit_items)
            arguments = typed_mcp_request_json(edit_items)
            all_equivalent &= run_typed(target, persisted) == ("accepted", expected_hash)
            print(f"{name:30} {len(persisted.encode('utf-8')):13d} "
                  f"{len(arguments.encode('utf-8')):13d}  {label}")

    print()
    print("=== Guarded tx/3 Replacement UTF-8 Bytes (same proposal, storage vs complete request) ===")
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
    print("Typed tx/1 accepted verdict and hash oracles:", "OK" if all_equivalent else "MISMATCH")
    print("Accepted guarded replacement content/hash oracles:", "OK" if all_replacements else "MISMATCH")
    return 0 if all_equivalent and all_replacements else 1


if __name__ == "__main__":
    sys.exit(main())
