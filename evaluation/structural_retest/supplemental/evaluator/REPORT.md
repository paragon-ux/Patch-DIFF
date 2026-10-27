# Empirical Verification Report: Waymark Engine vs. Structural Discovery Alternatives (Workstream D Remediated)

**Date:** 2026-10-26  
**Benchmark Directory:** `Editing-Toolbench/10-26-26`  
**Waymark Production Commit Tested:** `09a5c88` (`main`, PR #4 merged)  

---

## 1. Scope & Methodological Disclaimer (`BM-1`)

This benchmark evaluates **structural discovery engines** across 5 multi-hundred-line fixtures (`20` target scopes, `45` individual edit targets) in Python, JSON, and Markdown.

> **Scoped-Slice Simulation Qualification (`BM-1`):** The final-workspace verification checks (`20/20`) measure a **harness-level scoped-slice simulation** (`run_scoped_slice_simulation()` in `run_all_benchmarks.py`) that enforces line-span SHA-256 observation receipts (`mint_observation_receipt` / `verify_and_admit_scoped_edit`) before applying string replacements within `[start_line, end_line]`. It is **not** an end-to-end execution of Patch-DIFF's transactional MCP server (`patchdiff_read_target` → `patchdiff_submit_edits` → `patchdiff_save`), its audit/manifest ledger (PostgreSQL in the current Patch-DIFF implementation; file-authoritative in the intended architecture), `SAVE`, or replay.

---

## 2. Workstream D Remediations Applied (`BM-1`..`BM-7`)

| Finding ID | Priority | Original Issue | Remediation Implemented in `Editing-Toolbench/10-26-26` |
| :--- | :--- | :--- | :--- |
| **BM-1** | **P1** | Direct Python string slicing was labeled as `scoped_with_patchdiff` / Patch-DIFF integration. | Renamed metrics and pipeline to `scoped_slice_admitted` and `run_scoped_slice_simulation()`, with explicit disclaimers in `benchmark_results.json` and `REPORT.md`. |
| **BM-2** | **P1** | Observation receipts (`e{idx}@{snap_hash}`) were minted as strings but never verified before mutation. | Implemented `mint_observation_receipt()` and `verify_and_admit_scoped_edit()`, enforcing line bounds (`OUT_OF_BOUNDS_RECEIPT`), SHA-256 span freshness (`STALE_RECEIPT_SPAN_HASH`), and target uniqueness (`AMBIGUOUS_TARGET_IN_SCOPE`), plus automated negative self-tests (`verify_receipt_enforcement_guard()`). |
| **BM-3** | **P1** | `eval_symbol_table_engine` used substring matching (`q in s["name"].lower()`) and silently broke ties by smallest line span (`min(...)`). | Replaced with `resolve_exact_symbol_scope()`, requiring exact symbol identity matching (`s["name"] in allowed_exact_names`) and failing closed with `SCOPE_NOT_FOUND` (`0` hits) or `AMBIGUOUS_SCOPE_COLLISION` (`> 1` hits). |
| **BM-4** | **P2** | `mk_sync_overlap` (`FRAME_SYNC_STREAM`) relied on hardcoded `occurrence_in_scope = 1` for an overlapping substring. | Anchored the target to the unique prefix `"HEADER::SYNC::SYNC::SYNC::"` → `"HEADER::SYNC::SYNC::CALIB::"`, eliminating `occurrence_in_scope` so every edit across all 45 targets requires `len(occ) == 1` within its scope. |
| **BM-5** | **P2** | Task `rb_conflict_fence` (`R19`) queried `"4. Literal Patch"`, matching the parent H2 section (`L237–L252`) instead of the fenced code block (`fence:L241`). | Updated `rb_conflict_fence` to require `expected_symbol: "fence:L241"` (`expected_kind: "code_block"`, `L241–L251`). As a result, `waymark_stock_v4.0.2` accurately scores `0/1` on `markdown_code_fence` (`25/45` total instead of `26/45`), while `waymark_production_pr4` scores `1/1` (`45/45`). |
| **BM-6** | **P2** | In-process warm parse timings were compared without qualification against cold CLI subprocess timings. | `waymark_runner.mjs` and `run_all_benchmarks.py` now record `execution_mode` (`in_process` vs `cold_cli_subprocess`), `cold_first_pass_5_files_ms`, `warm_pass_5_files_ms`, and `cold_init_overhead_ms`. |
| **BM-7** | **P3** | Hardcoded Windows paths (`C:\Users\USER\...`) in `waymark_runner.mjs` and `run_all_benchmarks.py`; external `verify_hard_suite.py` reference. | Removed all hardcoded user paths; packaged standalone `verify_hard_suite.py` in `Editing-Toolbench/10-26-26`; resolved `WAYMARK_ROOT` and `probe` portably; recorded SHA-256 fixture provenance and pinned tool versions in `benchmark_results.json`. |

---

## 3. Fixture Provenance Manifest (`BM-7`)

| Fixture | Language | Lines | Bytes | SHA-256 |
| :--- | :--- | :--- | :--- | :--- |
| `matrix_kernel.py` | Python | `730` | `20,762` | `cb8990362835e28735451bf71c87545a1e72b850df44e921b9d72b121b208f02` |
| `schema_defs.py` | Python | `369` | `11,013` | `94b211a8b67b14820cc29b8a1d78f98a07a0c164fd0a7d9d8b58821240a7c702` |
| `validator_engine.py` | Python | `468` | `14,043` | `070cf70875f5cb99c92a460b0ce73469688b7683cd364ab1ba5b5e862583862f` |
| `routing_manifest.json` | JSON | `289` | `7,448` | `4c9fd1fa1cb0802e10a1a2ef6f3a884d39c88fb8159e91bd3931797cfbf35933` |
| `MIGRATION_RUNBOOK.md` | Markdown | `253` | `9,349` | `09e416301d7d74b7320c3974e6c78137cc2fffa3fb0ba0cc6eb04d377ff18dc8` |

---

## 4. Remediated Benchmark Results Across All 45 Hard-Suite Edits

### 4.1 Discovery & Scoped-Slice Admission Scoreboard

| Engine / Mode | Version | Zero-Hint Outline? | Execution Mode | Cold Init / First Pass (5 files) | Warm Query / Parse (5 files) | Admitted Targets (`/45`) | Scoped-Slice Simulation Checks (`/20`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`waymark_stock_v4.0.2`** | `4.0.2` (`eb7db8e`) | **Yes** | `in_process` | `551.69 ms` | `256.88 ms` | `25 / 45` (`55.6%`) | `10 / 20` |
| **`waymark_production_pr4`** | `4.0.2+PR4` (`09a5c88`) | **Yes** | `in_process` | `551.69 ms` | `256.88 ms` | **`45 / 45` (`100.0%`)** | **`20 / 20` (`100.0%`)** |
| **`ast_grep_py_pattern_naive`** | `0.51.0` | No (requires pattern) | `in_process` | — | `20.15 ms` | `3 / 45` (`6.7%`) | — |
| **`ast_grep_py_pattern_typed`** | `0.51.0` | No (requires return-type pattern) | `in_process` | — | `20.15 ms` | `25 / 45` (`55.6%`) | — |
| **`ast_grep_py_rule`** | `0.51.0` | No (requires custom rule dict per target) | `in_process` | — | `20.15 ms` | **`45 / 45` (`100.0%`)** | **`20 / 20` (`100.0%`)** |
| **`codegraph_1.6.2`** | `1.6.2` | Yes (JS/TS/Py only) | `in_process` | `78.59 ms` | `0.78 ms` | `25 / 45` (`55.6%`) | — |
| **`probe_0.6.0`** | `0.6.0` | Yes (`probe symbols`) | `cold_cli_subprocess` | `98.80 ms` | — | `24 / 45` (`53.3%`) | — |
| **`semgrep_1.182.1`** | `1.182.1` | No (requires `-e` pattern) | `cold_cli_subprocess` | `6,078–9,910 ms / call` | — | `25 / 45` (`55.6%`) | — |
| **`ripgrep_15.2.0_literal`** | `15.2.0` | No (lexical string match) | `cold_cli_subprocess` | — | `1.43 ms` | `9 / 45` (`20.0%`) | — |

### 4.2 Per-Category Breakdown (`/45` Targets)

| Category | Total | `waymark_stock` | `waymark_production_pr4` | `ast_grep_naive` | `ast_grep_typed` | `ast_grep_rule` | `codegraph` | `probe` | `ripgrep` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `overlapping_literal_in_constant` (`FRAME_SYNC_STREAM`) | `1` | `0/1` | **`1/1`** | `1/1` | `1/1` | **`1/1`** | `1/1` | `1/1` | `1/1` |
| `repeated_python_function` (`kernel_07/14/21`, `serialize_v3`, `rule_04/11/19/27`) | `21` | `21/21` | **`21/21`** | `0/21` | `21/21` | **`21/21`** | `21/21` | `21/21` | `0/21` |
| `unique_python_function` (`dispatch_kernel_triad`) | `1` | `1/1` | **`1/1`** | `0/1` | `1/1` | **`1/1`** | `1/1` | `1/1` | `1/1` |
| `python_dataclass` (`SettlementEnvelope`) | `1` | `1/1` | **`1/1`** | `1/1` | `1/1` | **`1/1`** | `1/1` | `0/1` | `1/1` |
| `python_constant` (`VALID_SCOPES`) | `1` | `0/1` | **`1/1`** | `1/1` | `1/1` | **`1/1`** | `1/1` | `1/1` | `1/1` |
| `json_top_level_key` (`manifest_version`) | `1` | `1/1` | **`1/1`** | `0/1` | `0/1` | **`1/1`** | `0/1` | `0/1` | `1/1` |
| `json_nested_tenant_object` (`tenants[ten_006/013/018]`) | `15` | `0/15` | **`15/15`** | `0/15` | `0/15` | **`15/15`** | `0/15` | `0/15` | `0/15` |
| `markdown_list_item` (`## 1. Executive Summary`) | `1` | `1/1` | **`1/1`** | `0/1` | `0/1` | **`1/1`** | `0/1` | `0/1` | `1/1` |
| `markdown_table_row` (`row:CHK-14-C`, `row:canary-v3`) | `2` | `0/2` | **`2/2`** | `0/2` | `0/2` | **`2/2`** | `0/2` | `0/2` | `2/2` |
| `markdown_code_fence` (`fence:L241`) | `1` | `0/1` | **`1/1`** | `0/1` | `0/1` | **`1/1`** | `0/1` | `0/1` | `1/1` |
| **Total Admitted (`/45`)** | **`45`** | **`25/45` (`55.6%`)** | **`45/45` (`100.0%`)** | **`3/45` (`6.7%`)** | **`25/45` (`55.6%`)** | **`45/45` (`100.0%`)** | **`25/45` (`55.6%`)** | **`24/45` (`53.3%`)** | **`9/45` (`20.0%`)** |

---

## 5. Negative Receipt & Collision Guard Verification (`BM-2`, `BM-3`, `BM-4`)

`verify_receipt_enforcement_guard()` in `run_all_benchmarks.py` executes four automated negative assertions on every run:

1. **Stale Span Hash Rejection (`STALE_RECEIPT_SPAN_HASH`):** Mutating `block_id = 7` → `block_id = 999` inside `execute_tile_kernel_07` after minting its `ObservationReceipt` causes `verify_and_admit_scoped_edit()` to reject the edit (`admitted: False, reason: "STALE_RECEIPT_SPAN_HASH"`).
2. **Out-of-Scope Target Rejection (`TARGET_NOT_FOUND_IN_SCOPE`):** Attempting to replace `block_id = 1` (from `execute_tile_kernel_01`) using `execute_tile_kernel_07`'s receipt (`L191–L219`) is rejected (`admitted: False, reason: "TARGET_NOT_FOUND_IN_SCOPE"`).
3. **Ambiguous Target in Scope Rejection (`AMBIGUOUS_TARGET_IN_SCOPE`):** Attempting to replace the un-anchored repeating substring `"::SYNC::SYNC::"` inside `FRAME_SYNC_STREAM`'s receipt (`L7–L7`) is rejected (`admitted: False, reason: "AMBIGUOUS_TARGET_IN_SCOPE"`).
4. **Ambiguous Scope Collision Rejection (`AMBIGUOUS_SCOPE_COLLISION`):** Passing a symbol table with two colliding `execute_tile_kernel_07` entries to `resolve_exact_symbol_scope()` is rejected (`scope_resolved: False, rejection_reason: "AMBIGUOUS_SCOPE_COLLISION"`) rather than silently selecting the smaller span.
