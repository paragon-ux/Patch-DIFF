"""Remediated Hard-Suite Discovery & Scoped-Slice Simulation Benchmark (Workstream D).

Remediations implemented in this harness:
- BM-1 (P1): Relabeled Python string-slicing workspace checks as `scoped_slice_simulation`
  (explicitly distinguished from guarded Patch-DIFF transactional MCP execution).
- BM-2 (P1): Implemented and enforced `ObservationReceipt` admission (`mint_observation_receipt`
  and `verify_and_admit_scoped_edit`) checking line bounds, SHA-256 span freshness, and strict
  target uniqueness (`count == 1`), plus automated negative self-tests (`verify_receipt_enforcement_guard`).
- BM-3 (P1): Replaced substring matching (`q in s["name"].lower()`) and silent smallest-span
  tie-breaking (`min(...)`) with exact symbol identity matching (`==`) that fails closed on
  missing (`SCOPE_NOT_FOUND`) or colliding (`AMBIGUOUS_SCOPE_COLLISION`) symbols.
- BM-4 (P2): Removed hardcoded overlapping-occurrence index selection (`occurrence_in_scope = 1`);
  every edit target in all 45 specs must resolve to a unique match (`count == 1`) within its scope.
- BM-5 (P2): Updated `rb_conflict_fence` (`R19`) to directly target `fence:L241` (`kind: "code_block"`,
  lines 241..251) rather than falling back to the parent H2 section (`4. Literal Patch`).
- BM-6 (P2): Separated cold initialization / first-pass timings from warm 5-file query timings and
  annotated `in_process` vs `cold_cli_subprocess` execution modes.
- BM-7 (P3): Eliminated all hardcoded Windows paths (`C:\\Users\\USER\\...`), packaged the standalone
  `verify_hard_suite.py` in the benchmark directory, and recorded SHA-256 fixture provenance and
  pinned tool versions.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import ast_grep_py as sg

from verify_hard_suite import check_workspace

BENCH_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = BENCH_DIR / "fixtures"
FIXTURE_FILES = [
    ("matrix_kernel.py", "python"),
    ("schema_defs.py", "python"),
    ("validator_engine.py", "python"),
    ("routing_manifest.json", "json"),
    ("MIGRATION_RUNBOOK.md", "markdown"),
]

# 1. Compute SHA-256 fixture provenance manifest (BM-7)
fixture_provenance: dict[str, dict[str, Any]] = {}
file_texts: dict[str, str] = {}
for fname, lang in FIXTURE_FILES:
    fpath = FIXTURES_DIR / fname
    raw_bytes = fpath.read_bytes()
    txt = raw_bytes.decode("utf-8")
    file_texts[fname] = txt
    fixture_provenance[fname] = {
        "language": lang,
        "bytes": len(raw_bytes),
        "lines": len(txt.splitlines()),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }

# Load Waymark (stock baseline & production PR #4) and CodeGraph symbol tables
wm_data = json.loads((BENCH_DIR / "waymark_results.json").read_text(encoding="utf-8"))
cg_data = json.loads((BENCH_DIR / "codegraph_results.json").read_text(encoding="utf-8"))

# Resolve probe binary portably (BM-7)
local_probe = BENCH_DIR / "node_modules" / ".bin" / ("probe.cmd" if os.name == "nt" else "probe")
probe_bin = str(local_probe) if local_probe.exists() else (shutil.which("probe") or "probe")

t_probe0 = time.perf_counter()
probe_proc = subprocess.run(
    [
        probe_bin,
        "symbols",
        *[str(FIXTURES_DIR / fname) for fname, _ in FIXTURE_FILES],
        "-o",
        "json",
    ],
    capture_output=True,
    text=True,
    encoding="utf-8",
    check=True,
)
probe_ms = (time.perf_counter() - t_probe0) * 1000.0
probe_raw = json.loads(probe_proc.stdout)
probe_symbols: dict[str, list[dict[str, Any]]] = {}
for entry in probe_raw:
    fname = Path(entry["file"]).name
    probe_symbols[fname] = [
        {
            "name": s["name"],
            "kind": s["kind"],
            "startLine": s["line"],
            "endLine": s["end_line"],
        }
        for s in entry["symbols"]
        if s.get("name")
    ]

# All 45 individual edits across the 20 logical scopes in the 5 hard-suite files.
# BM-3 / BM-4 / BM-5: Each spec declares `expected_symbol` and `expected_kind` for exact identity matching,
# and every target requires a unique match (`count == 1`) within the resolved scope.
EDIT_SPECS: list[dict[str, Any]] = [
    # 1. matrix_kernel.py (8 edits across 5 scopes)
    {
        "file": "matrix_kernel.py",
        "group": "mk_sync_overlap",
        "expected_symbol": "FRAME_SYNC_STREAM",
        "expected_kind": "variable",
        "exact_symbol_aliases": ("FRAME_SYNC_STREAM",),
        "ast_grep_kind": "assignment",
        "ast_grep_rule": {"kind": "assignment", "has": {"field": "left", "regex": "^FRAME_SYNC_STREAM$"}},
        "ast_grep_pattern": "FRAME_SYNC_STREAM = $VAL",
        "match": "HEADER::SYNC::SYNC::SYNC::",
        "replace": "HEADER::SYNC::SYNC::CALIB::",
        "category": "overlapping_literal_in_constant",
    },
    *[
        {
            "file": "matrix_kernel.py",
            "group": f"mk_kernel_{k:02d}",
            "expected_symbol": f"execute_tile_kernel_{k:02d}",
            "expected_kind": "function",
            "exact_symbol_aliases": (f"execute_tile_kernel_{k:02d}",),
            "ast_grep_kind": "function_definition",
            "ast_grep_rule": {"kind": "function_definition", "has": {"field": "name", "regex": f"^execute_tile_kernel_{k:02d}$"}},
            "ast_grep_pattern": f"def execute_tile_kernel_{k:02d}($$$):\n    $$$",
            "match": m,
            "replace": r,
            "category": "repeated_python_function",
        }
        for k in (7, 14, 21)
        for m, r in [
            ("stride_offset = (block_id << 4) + lane_id", "stride_offset = (block_id << 5) + (lane_id * 3)"),
            ("scaled = cell >> scale_shift", "scaled = (cell + (1 << (scale_shift - 1))) >> scale_shift"),
        ]
    ],
    {
        "file": "matrix_kernel.py",
        "group": "mk_dispatch_triad",
        "expected_symbol": "dispatch_kernel_triad",
        "expected_kind": "function",
        "exact_symbol_aliases": ("dispatch_kernel_triad",),
        "ast_grep_kind": "function_definition",
        "ast_grep_rule": {"kind": "function_definition", "has": {"field": "name", "regex": "^dispatch_kernel_triad$"}},
        "ast_grep_pattern": "def dispatch_kernel_triad($$$):\n    $$$",
        "match": '        "total_accumulator": total_acc,',
        "replace": '        "total_accumulator": total_acc,\n        "total_saturation_clips": k07["saturation_clips"] + k14["saturation_clips"] + k21["saturation_clips"],',
        "category": "unique_python_function",
    },
    # 2. schema_defs.py (4 edits across 2 scopes)
    {
        "file": "schema_defs.py",
        "group": "sd_dataclass",
        "expected_symbol": "SettlementEnvelope",
        "expected_kind": "class",
        "exact_symbol_aliases": ("SettlementEnvelope",),
        "ast_grep_kind": "class_definition",
        "ast_grep_rule": {"kind": "class_definition", "has": {"field": "name", "regex": "^SettlementEnvelope$"}},
        "ast_grep_pattern": "class SettlementEnvelope:\n    $$$",
        "match": '    settlement_epoch_sec: int\n    schema_revision: str = "v3"',
        "replace": '    settlement_epoch_sec: int\n    schema_revision: str = "v3"\n    idempotency_scope: str = "GLOBAL"',
        "category": "python_dataclass",
    },
    *[
        {
            "file": "schema_defs.py",
            "group": "sd_serialize_v3",
            "expected_symbol": "serialize_envelope_v3",
            "expected_kind": "function",
            "exact_symbol_aliases": ("serialize_envelope_v3",),
            "ast_grep_kind": "function_definition",
            "ast_grep_rule": {"kind": "function_definition", "has": {"field": "name", "regex": "^serialize_envelope_v3$"}},
            "ast_grep_pattern": "def serialize_envelope_v3($$$):\n    $$$",
            "match": m,
            "replace": r,
            "category": "repeated_python_function",
        }
        for m, r in [
            ('"epoch_unit": "sec",', '"epoch_unit": "ns",'),
            ('"settlement_epoch": env.settlement_epoch_sec,', '"settlement_epoch": env.settlement_epoch_sec * 1_000_000_000,'),
            ('"quorum_required": 2,', '"quorum_required": 3,\n        "idempotency_scope": env.idempotency_scope,'),
        ]
    ],
    # 3. validator_engine.py (13 edits across 5 scopes)
    {
        "file": "validator_engine.py",
        "group": "ve_valid_scopes",
        "expected_symbol": "VALID_SCOPES",
        "expected_kind": "variable",
        "exact_symbol_aliases": ("VALID_SCOPES",),
        "ast_grep_kind": "assignment",
        "ast_grep_rule": {"kind": "assignment", "has": {"field": "left", "regex": "^VALID_SCOPES$"}},
        "ast_grep_pattern": "VALID_SCOPES = $VAL",
        "match": 'VALID_SCOPES = ("GLOBAL", "PARTITION")',
        "replace": 'VALID_SCOPES = ("GLOBAL", "PARTITION", "TENANT")',
        "category": "python_constant",
    },
    *[
        {
            "file": "validator_engine.py",
            "group": f"ve_rule_{r_num:02d}",
            "expected_symbol": f"evaluate_settlement_rule_{r_num:02d}",
            "expected_kind": "function",
            "exact_symbol_aliases": (f"evaluate_settlement_rule_{r_num:02d}",),
            "ast_grep_kind": "function_definition",
            "ast_grep_rule": {"kind": "function_definition", "has": {"field": "name", "regex": f"^evaluate_settlement_rule_{r_num:02d}$"}},
            "ast_grep_pattern": f"def evaluate_settlement_rule_{r_num:02d}($$$):\n    $$$",
            "match": m,
            "replace": r,
            "category": "repeated_python_function",
        }
        for r_num in (4, 11, 19, 27)
        for m, r in [
            ("max_drift = 30", "max_drift = 30_000_000_000"),
            ('if unit != "sec":', 'if unit != "ns":'),
            ("if quorum < 2:", "if quorum < 3:"),
        ]
    ],
    # 4. routing_manifest.json (16 edits across 4 scopes)
    {
        "file": "routing_manifest.json",
        "group": "rm_version",
        "expected_symbol": "manifest_version",
        "expected_kind": "config_block",
        "exact_symbol_aliases": ("manifest_version",),
        "ast_grep_kind": "pair",
        "ast_grep_rule": {"kind": "pair", "has": {"field": "key", "regex": '^"manifest_version"$'}},
        "ast_grep_pattern": '"manifest_version": "2026.10.1"',
        "match": '"manifest_version": "2026.10.1"',
        "replace": '"manifest_version": "2026.10.2-v3"',
        "category": "json_top_level_key",
    },
    *[
        {
            "file": "routing_manifest.json",
            "group": f"rm_{tid}",
            "expected_symbol": f"tenants[{tid}]",
            "expected_kind": "config_item",
            "exact_symbol_aliases": (f"tenants[{tid}]", tid),
            "ast_grep_kind": "object",
            "ast_grep_rule": {
                "kind": "object",
                "has": {
                    "kind": "pair",
                    "all": [
                        {"has": {"field": "key", "regex": '^"tenant_id"$'}},
                        {"has": {"field": "value", "regex": f'^"{tid}"$'}},
                    ],
                },
            },
            "ast_grep_pattern": f'{{"tenant_id": "{tid}", $$$}}',
            "match": m,
            "replace": r,
            "category": "json_nested_tenant_object",
        }
        for tid in ("ten_006", "ten_013", "ten_018")
        for m, r in [
            ('"wire_version": "v2"', '"wire_version": "v3"'),
            ('"epoch_unit": "sec"', '"epoch_unit": "ns"'),
            ('"max_drift": 30', '"max_drift": 30000000000'),
            ('"quorum_size": 2', '"quorum_size": 3'),
            ('"idempotency_scope": "GLOBAL"', '"idempotency_scope": "TENANT"'),
        ]
    ],
    # 5. MIGRATION_RUNBOOK.md (4 edits across 4 scopes)
    {
        "file": "MIGRATION_RUNBOOK.md",
        "group": "rb_allowed_scopes",
        "expected_symbol": "## 1. Executive Summary",
        "expected_kind": "section",
        "exact_symbol_aliases": ("## 1. Executive Summary", "1. Executive Summary"),
        "ast_grep_kind": "list_item",
        "ast_grep_rule": {"kind": "list_item", "regex": "Allowed Idempotency Scopes"},
        "ast_grep_pattern": "- **Allowed Idempotency Scopes**: `GLOBAL, PARTITION`",
        "match": "- **Allowed Idempotency Scopes**: `GLOBAL, PARTITION`",
        "replace": "- **Allowed Idempotency Scopes**: `GLOBAL, PARTITION, TENANT`",
        "category": "markdown_list_item",
    },
    {
        "file": "MIGRATION_RUNBOOK.md",
        "group": "rb_gate_14",
        "expected_symbol": "row:CHK-14-C",
        "expected_kind": "table_row",
        "exact_symbol_aliases": ("row:CHK-14-C",),
        "ast_grep_kind": "pipe_table_row",
        "ast_grep_rule": {"kind": "pipe_table_row", "regex": "CHK-14-C"},
        "ast_grep_pattern": "| `CHK-14-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |",
        "match": "| `CHK-14-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |",
        "replace": "| `CHK-14-C` | Clock skew p99 | `<= 30000000000 ns` | Trigger PTP hardware resync |",
        "category": "markdown_table_row",
    },
    {
        "file": "MIGRATION_RUNBOOK.md",
        "group": "rb_canary_row",
        "expected_symbol": "row:canary-v3",
        "expected_kind": "table_row",
        "exact_symbol_aliases": ("row:canary-v3",),
        "ast_grep_kind": "pipe_table_row",
        "ast_grep_rule": {"kind": "pipe_table_row", "regex": "canary-v3"},
        "ast_grep_pattern": "| `canary-v3` | `v2` | `sec` | `30` | `2` | `GLOBAL` |",
        "match": "| `canary-v3` | `v2` | `sec` | `30` | `2` | `GLOBAL` |",
        "replace": "| `canary-v3` | `v3` | `ns` | `30000000000` | `3` | `TENANT` |",
        "category": "markdown_table_row",
    },
    # BM-5: Directly target `fence:L241` (`kind: "code_block"`) instead of parent H2 section
    {
        "file": "MIGRATION_RUNBOOK.md",
        "group": "rb_conflict_fence",
        "expected_symbol": "fence:L241",
        "expected_kind": "code_block",
        "exact_symbol_aliases": ("fence:L241",),
        "ast_grep_kind": "fenced_code_block",
        "ast_grep_rule": {"kind": "fenced_code_block", "regex": "<<<<<<< MATCH"},
        "ast_grep_pattern": "<<<<<<< MATCH\n$$$\n>>>>>>> REPLACE",
        "match": '=======\nwire_version = "v3"\nepoch_unit = "sec"\nquorum_required = 2\n>>>>>>> REPLACE',
        "replace": '=======\nwire_version = "v3"\nepoch_unit = "ns"\nquorum_required = 3\n>>>>>>> REPLACE',
        "category": "markdown_code_fence",
    },
]


def find_occurrences_in_slice(
    text: str,
    pattern: str,
    start_char: int,
    end_char: int,
) -> list[tuple[int, int]]:
    sub = text[start_char:end_char]
    spans: list[tuple[int, int]] = []
    step = max(1, len(pattern))
    pos = 0
    while True:
        idx = sub.find(pattern, pos)
        if idx == -1:
            break
        spans.append((start_char + idx, start_char + idx + len(pattern)))
        pos = idx + step
    return spans


def line_range_to_char_range(text: str, start_line: int, end_line: int) -> tuple[int, int]:
    lines = text.splitlines(keepends=True)
    s_idx = sum(len(lines[i]) for i in range(max(0, start_line - 1)))
    e_idx = sum(len(lines[i]) for i in range(min(len(lines), end_line)))
    return s_idx, e_idx


# BM-2: Observation receipt minting and strict admission verification
def mint_observation_receipt(
    file_rel_path: str,
    full_text: str,
    symbol_name: str,
    symbol_kind: str,
    start_line: int,
    end_line: int,
) -> dict[str, Any]:
    lines = full_text.splitlines(keepends=True)
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        raise ValueError(f"Invalid receipt line bounds L{start_line}-L{end_line} (total={len(lines)})")
    s_char, e_char = line_range_to_char_range(full_text, start_line, end_line)
    span_text = full_text[s_char:e_char]
    file_sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    span_sha256 = hashlib.sha256(span_text.encode("utf-8")).hexdigest()
    return {
        "receipt_id": f"obs_{file_rel_path}:{symbol_name}:L{start_line}-L{end_line}:{span_sha256[:12]}",
        "file": file_rel_path,
        "symbol_name": symbol_name,
        "symbol_kind": symbol_kind,
        "start_line": start_line,
        "end_line": end_line,
        "file_sha256": file_sha256,
        "span_sha256": span_sha256,
    }


def verify_and_admit_scoped_edit(
    current_text: str,
    receipt: dict[str, Any],
    match_str: str,
    replace_str: str,
) -> dict[str, Any]:
    lines = current_text.splitlines(keepends=True)
    s_line = receipt["start_line"]
    e_line = receipt["end_line"]
    if s_line < 1 or e_line < s_line or e_line > len(lines):
        return {"admitted": False, "reason": "OUT_OF_BOUNDS_RECEIPT"}

    s_char, e_char = line_range_to_char_range(current_text, s_line, e_line)
    span_text = current_text[s_char:e_char]
    actual_span_sha256 = hashlib.sha256(span_text.encode("utf-8")).hexdigest()
    if actual_span_sha256 != receipt["span_sha256"]:
        return {
            "admitted": False,
            "reason": "STALE_RECEIPT_SPAN_HASH",
            "expected_span_sha256": receipt["span_sha256"],
            "actual_span_sha256": actual_span_sha256,
        }

    occ = find_occurrences_in_slice(current_text, match_str, s_char, e_char)
    if len(occ) == 0:
        return {"admitted": False, "reason": "TARGET_NOT_FOUND_IN_SCOPE", "matches_in_scope": 0}
    if len(occ) > 1:
        return {"admitted": False, "reason": "AMBIGUOUS_TARGET_IN_SCOPE", "matches_in_scope": len(occ)}

    m_start, m_end = occ[0]
    updated_text = current_text[:m_start] + replace_str + current_text[m_end:]
    line_delta = replace_str.count("\n") - match_str.count("\n")
    new_e_line = e_line + line_delta
    updated_receipt = mint_observation_receipt(
        receipt["file"],
        updated_text,
        receipt["symbol_name"],
        receipt["symbol_kind"],
        s_line,
        new_e_line,
    )
    return {
        "admitted": True,
        "reason": "OK",
        "updated_text": updated_text,
        "updated_receipt": updated_receipt,
    }


# Cache ast-grep roots and measure parse time (BM-6)
sg_roots: dict[str, Any] = {}
t_sg0 = time.perf_counter()
for fname, lang in FIXTURE_FILES:
    txt = file_texts[fname]
    sg_roots[fname] = sg.SgRoot(txt, lang).root()
sg_parse_ms = (time.perf_counter() - t_sg0) * 1000.0


# BM-3: Exact symbol identity lookup (no substring matching, no smallest-span tie-breaking)
def resolve_exact_symbol_scope(
    symbols_by_file: dict[str, list[dict[str, Any]]],
    spec: dict[str, Any],
) -> dict[str, Any]:
    fname = spec["file"]
    txt = file_texts[fname]
    syms = symbols_by_file.get(fname, [])
    allowed_exact_names = set(spec.get("exact_symbol_aliases", (spec["expected_symbol"],)))
    matched_syms = [
        s for s in syms
        if s["name"] in allowed_exact_names and s.get("kind") != "file"
    ]
    if len(matched_syms) == 0:
        return {
            "scope_resolved": False,
            "unique_in_scope": False,
            "scoped_slice_admitted": False,
            "rejection_reason": "SCOPE_NOT_FOUND",
        }
    if len(matched_syms) > 1:
        return {
            "scope_resolved": False,
            "unique_in_scope": False,
            "scoped_slice_admitted": False,
            "rejection_reason": "AMBIGUOUS_SCOPE_COLLISION",
            "collision_count": len(matched_syms),
        }

    target_sym = matched_syms[0]
    total_lines = len(txt.splitlines())
    is_tight = (target_sym["endLine"] - target_sym["startLine"]) < (total_lines * 0.8)
    if not is_tight:
        return {
            "scope_resolved": False,
            "unique_in_scope": False,
            "scoped_slice_admitted": False,
            "rejection_reason": "SCOPE_NOT_SELECTIVE",
        }

    receipt = mint_observation_receipt(
        fname,
        txt,
        target_sym["name"],
        target_sym["kind"],
        target_sym["startLine"],
        target_sym["endLine"],
    )
    admission = verify_and_admit_scoped_edit(txt, receipt, spec["match"], spec["replace"])
    admitted = bool(admission["admitted"])
    return {
        "scope_resolved": True,
        "unique_in_scope": admitted,
        "scoped_slice_admitted": admitted,
        "scope_lines": (target_sym["startLine"], target_sym["endLine"]),
        "receipt_id": receipt["receipt_id"],
        "rejection_reason": None if admitted else admission["reason"],
    }


def eval_ast_grep_pattern(spec: dict[str, Any]) -> dict[str, Any]:
    fname = spec["file"]
    txt = file_texts[fname]
    root = sg_roots[fname]
    try:
        nodes = root.find_all(pattern=spec["ast_grep_pattern"])
    except Exception as exc:
        return {"scope_resolved": False, "unique_in_scope": False, "scoped_slice_admitted": False, "error": str(exc)}
    if len(nodes) != 1:
        return {"scope_resolved": False, "unique_in_scope": False, "scoped_slice_admitted": False, "node_count": len(nodes)}
    r = nodes[0].range()
    occ = find_occurrences_in_slice(txt, spec["match"], r.start.index, r.end.index)
    ok = len(occ) == 1
    return {
        "scope_resolved": True,
        "unique_in_scope": ok,
        "scoped_slice_admitted": ok,
        "char_span": (r.start.index, r.end.index),
        "matches_in_scope": len(occ),
    }


def eval_ast_grep_rule(spec: dict[str, Any]) -> dict[str, Any]:
    fname = spec["file"]
    txt = file_texts[fname]
    root = sg_roots[fname]
    try:
        nodes = root.find_all({"rule": spec["ast_grep_rule"]})
    except Exception as exc:
        return {"scope_resolved": False, "unique_in_scope": False, "scoped_slice_admitted": False, "error": str(exc)}
    if len(nodes) != 1:
        return {"scope_resolved": False, "unique_in_scope": False, "scoped_slice_admitted": False, "node_count": len(nodes)}
    r = nodes[0].range()
    s_line = r.start.line + 1
    e_line = r.end.line + 1
    receipt = mint_observation_receipt(fname, txt, spec["expected_symbol"], spec["ast_grep_kind"], s_line, e_line)
    admission = verify_and_admit_scoped_edit(txt, receipt, spec["match"], spec["replace"])
    ok = bool(admission["admitted"])
    return {
        "scope_resolved": True,
        "unique_in_scope": ok,
        "scoped_slice_admitted": ok,
        "scope_lines": (s_line, e_line),
        "char_span": (r.start.index, r.end.index),
        "receipt_id": receipt["receipt_id"],
    }


def eval_ripgrep(spec: dict[str, Any]) -> dict[str, Any]:
    fname = spec["file"]
    txt = file_texts[fname]
    occ = find_occurrences_in_slice(txt, spec["match"], 0, len(txt))
    ok = len(occ) == 1
    return {
        "scope_resolved": ok,
        "unique_in_scope": ok,
        "scoped_slice_admitted": ok,
        "global_matches": len(occ),
    }


engines = {
    "waymark_stock_v4.0.2": lambda s: resolve_exact_symbol_scope(wm_data["stockResults"], s),
    "waymark_production_pr4": lambda s: resolve_exact_symbol_scope(wm_data["extResults"], s),
    "ast_grep_py_pattern_naive": eval_ast_grep_pattern,
    "ast_grep_py_pattern_typed": lambda s: eval_ast_grep_pattern({**s, "ast_grep_pattern": s["ast_grep_pattern"].replace("($$$):", "($$$) -> $RET:")}),
    "ast_grep_py_rule": eval_ast_grep_rule,
    "codegraph_1.6.2": lambda s: resolve_exact_symbol_scope(cg_data["results"], s),
    "probe_0.6.0": lambda s: resolve_exact_symbol_scope(probe_symbols, s),
    "ripgrep_15.2.0_literal": eval_ripgrep,
}

summary: dict[str, Any] = {}
for eng_name, fn in engines.items():
    t0 = time.perf_counter()
    results = [fn(spec) for spec in EDIT_SPECS]
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    by_cat: dict[str, dict[str, int]] = {}
    for spec, res in zip(EDIT_SPECS, results):
        cat = spec["category"]
        by_cat.setdefault(cat, {"passed": 0, "total": 0})
        by_cat[cat]["total"] += 1
        if res["scoped_slice_admitted"]:
            by_cat[cat]["passed"] += 1
    passed = sum(1 for r in results if r["scoped_slice_admitted"])
    summary[eng_name] = {
        "passed": passed,
        "total": len(EDIT_SPECS),
        "pct": round(100.0 * passed / len(EDIT_SPECS), 1),
        "eval_ms": round(elapsed_ms, 2),
        "by_category": by_cat,
    }

print("\n=== SUMMARY ACROSS ALL 45 HARD-SUITE EDITS (EXACT IDENTITY + RECEIPT GATE) ===")
for eng_name, info in summary.items():
    print(f"  {eng_name:26s}: {info['passed']:2d}/{info['total']} ({info['pct']:5.1f}%) | eval_ms={info['eval_ms']} ms")
    for cat, cinfo in info["by_category"].items():
        print(f"      - {cat:32s}: {cinfo['passed']}/{cinfo['total']}")


def verify_receipt_enforcement_guard() -> dict[str, Any]:
    """Negative self-tests proving that receipts, exact scope matching, and uniqueness are enforced."""
    mk_txt = file_texts["matrix_kernel.py"]
    # 1. Stale span hash must be rejected
    r_k07 = mint_observation_receipt("matrix_kernel.py", mk_txt, "execute_tile_kernel_07", "function", 191, 219)
    tampered_txt = mk_txt.replace("block_id = 7", "block_id = 999", 1)
    stale_check = verify_and_admit_scoped_edit(
        tampered_txt,
        r_k07,
        "stride_offset = (block_id << 4) + lane_id",
        "stride_offset = 0",
    )
    assert not stale_check["admitted"] and stale_check["reason"] == "STALE_RECEIPT_SPAN_HASH"

    # 2. Out-of-scope target must be rejected
    out_of_scope_check = verify_and_admit_scoped_edit(
        mk_txt,
        r_k07,
        "block_id = 1",  # Exists in execute_tile_kernel_01, not in execute_tile_kernel_07
        "block_id = 999",
    )
    assert not out_of_scope_check["admitted"] and out_of_scope_check["reason"] == "TARGET_NOT_FOUND_IN_SCOPE"

    # 3. Ambiguous repeating target inside scope must be rejected (BM-4)
    r_sync = mint_observation_receipt("matrix_kernel.py", mk_txt, "FRAME_SYNC_STREAM", "variable", 7, 7)
    ambig_target_check = verify_and_admit_scoped_edit(
        mk_txt,
        r_sync,
        "::SYNC::SYNC::",  # Occurs twice non-overlapping inside FRAME_SYNC_STREAM
        "::SYNC::CALIB::",
    )
    assert not ambig_target_check["admitted"] and ambig_target_check["reason"] == "AMBIGUOUS_TARGET_IN_SCOPE"

    # 4. Colliding symbol identities in symbol table must be rejected (BM-3)
    colliding_table = {
        "matrix_kernel.py": [
            {"name": "execute_tile_kernel_07", "kind": "function", "startLine": 10, "endLine": 38},
            {"name": "execute_tile_kernel_07", "kind": "function", "startLine": 191, "endLine": 219},
        ]
    }
    collision_check = resolve_exact_symbol_scope(colliding_table, EDIT_SPECS[1])
    assert not collision_check["scope_resolved"] and collision_check["rejection_reason"] == "AMBIGUOUS_SCOPE_COLLISION"

    return {
        "stale_span_hash_rejected": stale_check["reason"],
        "out_of_scope_target_rejected": out_of_scope_check["reason"],
        "ambiguous_target_in_scope_rejected": ambig_target_check["reason"],
        "ambiguous_scope_collision_rejected": collision_check["rejection_reason"],
        "all_negative_guards_passed": True,
    }


def run_scoped_slice_simulation(ws_name: str, mode: str) -> dict[str, Any]:
    """Applies edits sequentially through enforced ObservationReceipts in a scoped-slice simulation."""
    ws_dir = BENCH_DIR / ws_name
    ws_dir.mkdir(parents=True, exist_ok=True)
    for fname, txt in file_texts.items():
        (ws_dir / fname).write_text(txt, encoding="utf-8", newline="\n")

    # Group specs by (file, group) so multi-edit scopes chain their ObservationReceipt hashes atomically
    by_file_and_group: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for spec in EDIT_SPECS:
        by_file_and_group.setdefault(spec["file"], {}).setdefault(spec["group"], []).append(spec)

    receipts_enforced = 0
    receipts_rejected = 0

    for fname, groups in by_file_and_group.items():
        current_txt = (ws_dir / fname).read_text(encoding="utf-8")
        for _group_name, group_specs in groups.items():
            first_spec = group_specs[0]
            if mode == "waymark_production":
                # Resolve symbol lines on current file text (or from Waymark outline)
                allowed_names = set(first_spec.get("exact_symbol_aliases", (first_spec["expected_symbol"],)))
                matched = [s for s in wm_data["extResults"][fname] if s["name"] in allowed_names]
                if len(matched) != 1:
                    receipts_rejected += len(group_specs)
                    continue
                s_line, e_line = matched[0]["startLine"], matched[0]["endLine"]
                sym_name, sym_kind = matched[0]["name"], matched[0]["kind"]
            elif mode == "ast_grep_rule":
                lang = dict(FIXTURE_FILES)[fname]
                root = sg.SgRoot(current_txt, lang).root()
                nodes = root.find_all({"rule": first_spec["ast_grep_rule"]})
                if len(nodes) != 1:
                    receipts_rejected += len(group_specs)
                    continue
                r = nodes[0].range()
                s_line, e_line = r.start.line + 1, r.end.line + 1
                sym_name, sym_kind = first_spec["expected_symbol"], first_spec["ast_grep_kind"]
            else:
                raise ValueError(f"Unknown simulation mode: {mode}")

            receipt = mint_observation_receipt(fname, current_txt, sym_name, sym_kind, s_line, e_line)
            for spec in group_specs:
                adm = verify_and_admit_scoped_edit(current_txt, receipt, spec["match"], spec["replace"])
                if not adm["admitted"]:
                    receipts_rejected += 1
                    raise RuntimeError(f"Receipt admission rejected edit in {fname} ({sym_name}): {adm['reason']}")
                current_txt = adm["updated_text"]
                receipt = adm["updated_receipt"]
                receipts_enforced += 1

        (ws_dir / fname).write_text(current_txt, encoding="utf-8", newline="\n")

    v_res = check_workspace(ws_dir, ws_name)
    v_res["simulation_type"] = "scoped_slice_simulation (not Patch-DIFF transactional MCP)"
    v_res["receipts_enforced"] = receipts_enforced
    v_res["receipts_rejected"] = receipts_rejected
    return v_res


guard_results = verify_receipt_enforcement_guard()
sim_wm = run_scoped_slice_simulation("ws_waymark_extended", "waymark_production")
sim_sg = run_scoped_slice_simulation("ws_ast_grep_rule", "ast_grep_rule")
print("\n=== SCOPED-SLICE SIMULATION & FINAL-WORKSPACE VERIFICATION (verify_hard_suite.py) ===")
print(f"  Negative receipt guards : {guard_results}")
print(f"  ws_waymark_extended     : {sim_wm['passed']}/{sim_wm['total']} ({sim_wm['accuracy_pct']}%) | receipts_enforced={sim_wm['receipts_enforced']}")
print(f"  ws_ast_grep_rule        : {sim_sg['passed']}/{sim_sg['total']} ({sim_sg['accuracy_pct']}%) | receipts_enforced={sim_sg['receipts_enforced']}")

full_report = {
    "benchmark_metadata": {
        "suite": "Editing-Toolbench/10-26-26 (Workstream D remediated)",
        "simulation_disclaimer": (
            "Workspace verification checks below measure a harness-level scoped-slice simulation "
            "with enforced line-span SHA-256 receipts, NOT an end-to-end integration with Patch-DIFF's "
            "transactional MCP server, PostgreSQL/file-authoritative audit/manifest ledger, SAVE, or replay."
        ),
        "waymark_commit": wm_data.get("waymarkCommit", "09a5c88"),
        "tool_versions": {
            "waymark_engine": "4.0.2+PR4 (09a5c88)",
            "ast_grep_py": "0.51.0",
            "codegraph": "1.6.2",
            "probe": "0.6.0",
            "semgrep": "1.182.1",
            "ripgrep": "15.2.0",
        },
        "fixture_provenance": fixture_provenance,
    },
    "timings_ms": {
        "waymark_production_pr4": {
            "execution_mode": "in_process",
            "cold_first_pass_5_files_ms": wm_data.get("coldPassMs"),
            "warm_pass_5_files_ms": wm_data.get("warmPassMs"),
            "cold_init_overhead_ms": wm_data.get("coldInitOverheadMs"),
        },
        "ast_grep_py": {
            "execution_mode": "in_process",
            "parse_5_files_ms": round(sg_parse_ms, 2),
        },
        "codegraph": {
            "execution_mode": "in_process",
            "cold_init_and_index_ms": round(cg_data["initMs"], 2),
            "warm_query_5_files_ms": round(cg_data["queryMs"], 2),
        },
        "probe": {
            "execution_mode": "cold_cli_subprocess",
            "symbols_5_files_ms": round(probe_ms, 2),
        },
        "semgrep": {
            "execution_mode": "cold_cli_subprocess",
            "single_python_call_win_ms": 9910.0,
            "single_json_call_win_ms": 6168.0,
            "single_markdown_call_win_ms": 6078.0,
        },
    },
    "receipt_enforcement_self_tests": guard_results,
    "engine_summary": summary,
    "scoped_slice_simulation_verification": {
        "waymark_production_pr4_scoped_slice": sim_wm,
        "ast_grep_rule_scoped_slice": sim_sg,
    },
}
(BENCH_DIR / "benchmark_results.json").write_text(json.dumps(full_report, indent=2), encoding="utf-8")
