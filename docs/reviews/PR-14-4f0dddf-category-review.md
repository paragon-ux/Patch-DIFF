# PR #14 Category Review — Resolve PR #13 Deferred Near-Miss (SVC-001) and Ledger-Read (MCP-001) P3 Findings & Public Documentation Upgrade

## 1. Review metadata and evidence limits

| Field | Value |
| --- | --- |
| Repository | `paragon-ux/Patch-DIFF` |
| PR | [paragon-ux/Patch-DIFF#14](https://github.com/paragon-ux/Patch-DIFF/pull/14) |
| Review date | 2026-10-25 |
| Reviewer | Antigravity (category & delta review following Devin's PR #14 review) |
| Standard | [PR Review Standard v1.1.0](../PR_REVIEW_STANDARD.md) |
| Predecessor reviews | [PR-13-0420dac-category-review.md](PR-13-0420dac-category-review.md) (`MCP-001`), [PR-13-ac842bb-delta-review.md](PR-13-ac842bb-delta-review.md) (`SVC-001`), [PR-13-de6e7c2-friction-review.md](PR-13-de6e7c2-friction-review.md) (`NF-5`, `NF-8`), [PR-13-aa88cd5-friction-recheck.md](PR-13-aa88cd5-friction-recheck.md) |
| Base SHA | `d09fbc8422bbc22543b0b209c2f689b3e341e3b2` (`origin/main`, PR #13 merge commit) |
| Head SHA | `4f0dddfbf420fbd02fbace82409d37f89bb7c185` (`perf/pr13-deferred-p3`) |
| Delta | 19 files changed, +1,318 / −243 |
| CI runs | Verified locally against live PostgreSQL 16.3 and offline evaluation; GitHub Actions triggered on push |

### Changed-file inventory (`d09fbc8..4f0dddf`)

1. `CHANGELOG.md` (+2 / −0) — Primary category: `DOC`
2. `README.md` (+216 / −24) — Primary category: `DOC`
3. `README_INTERNAL_MCP.md` (+2 / −8) — Primary category: `DOC`
4. `backend/app/mcp/tools.py` (+229 / −39) — Primary category: `MCP`
5. `backend/app/services/near_miss_service.py` (+181 / −57) — Primary category: `SVC`
6. `backend/tests/integration/test_friction_followup_live.py` (+157 / −0) — Primary category: `TEST`
7. `backend/tests/unit/test_friction_followup.py` (+123 / −0) — Primary category: `TEST`
8. `backend/tests/unit/test_mcp_arguments_paging.py` (+1 / −0) — Primary category: `TEST`
9. `docs/HOST_INTEGRATION_GUIDE.md` (+4 / −16) — Primary category: `DOC`
10. `docs/LEGACY_COMPATIBILITY.md` (+154 / −0) — Primary category: `DOC`
11. `docs/MCP_FIRST_MVP.md` (+12 / −2) — Primary category: `ARCH`
12. `docs/MCP_TOOLS.md` (+21 / −10) — Primary category: `MCP`
13. `docs/MODERNIZATION_ARCHITECTURE.md` (+17 / −3) — Primary category: `ARCH`
14. `docs/MODERNIZATION_CHANGE_DOC.md` (+4 / −4) — Primary category: `DOC`
15. `docs/PATCHDIFF_CORE_SPEC.md` (+4 / −7) — Primary category: `ARCH`
16. `docs/PDCP_FORMAT.md` (+119 / −60) — Primary category: `ARCH`
17. `docs/TEST_MATRIX.md` (+2 / −2) — Primary category: `DOC`
18. `docs/usability/friction-followup-decision.md` (+5 / −0) — Primary category: `ARCH`
19. `evaluation/README.md` (+68 / −14) — Primary category: `DOC`

### Unchanged dependencies examined

- `docs/PatchDIFF-Concept-Paper-5.md` (design thesis: exact deterministic matching, non-fuzzy core runtime, PostgreSQL canonical authority, append-only audit trail)
- `AGENTS.md`, `docs/DATA_MODEL.md`
- `backend/app/services/pdcp_service.py` (caller of `near_misses_from_rejected_result` and `near_misses`)
- `backend/app/storage/models.py` (`AppendOnlyPdcpLogs`, `AppendOnlyManifestLedger`)
- `backend/app/pdcp/typed.py`, `backend/app/pdcp/operations.py`, `backend/app/pdcp/replacement.py` (canonical JSON serialization with `sort_keys=True`)
- `backend/tests/unit/test_pass_a_diagnostics.py`, `backend/tests/integration/test_mcp_history_paging_live.py`, `backend/tests/integration/test_friction_followup_stdio.py`

### Evidence available and limits

- **Source inspection:** Full diff `d09fbc8..4f0dddf` and all referenced unchanged callers, models, and contracts.
- **Local execution:**
  - Full unit and live-PostgreSQL integration suite (`pytest backend/tests -q`, **1,226 passed**: 816 unit + 410 integration) against isolated database `patchdiff_fx_full_suite_20261025` on `postgres:16.3-alpine` (`127.0.0.1:5432`), dropped upon completion; unit suite re-verified on `4f0dddf` (`816 passed`).
  - Offline byte and verdict equivalence evaluation (`evaluation/offline_eval.py`, exit 0).
  - Controlled before/after latency benchmarks on 65,536-code-point repetitive and varied-prose buffers (`SVC-001`), 50 × 400 KB `patchdiff-tx/3` history/ledger pages (`MCP-001`), and 20 × 1 MB `patchdiff-tx/1` (5 edits × 200 KB each) history/ledger pages (`MCP-001`, `FX-01`).
  - Committed fixed-seed (`random.Random(12345)`) strict-path fuzz test (`test_candidate_starts_strict_path_and_loop2_and_leading_insertion_exactness`) verifying strict-path coverage (`strict_hits >= 50`), Loop-2-only hits (`loop2_only_hits >= 15`), and leading-insertion hits (`leading_ins_hits >= 15`) against the unpruned Levenshtein reference (`FX-03`).
- **Limits:** Self-review incorporating independent PR review findings (`CK-01`..`CK-13`, `FX-01`..`FX-12`) from Devin; local single-machine timings on Windows 11 / Python 3.11.9 / PostgreSQL 16.3.

---

## 2. File-to-category inventory and coverage matrix

| ID | Category | Primary changed files | Cross-referenced files / unchanged dependencies | Coverage | Verdict |
| --- | --- | --- | --- | --- | --- |
| ARCH | Architecture and contracts | `docs/MODERNIZATION_ARCHITECTURE.md`, `docs/MCP_FIRST_MVP.md`, `docs/PATCHDIFF_CORE_SPEC.md`, `docs/PDCP_FORMAT.md`, `docs/usability/friction-followup-decision.md` | `AGENTS.md`, `docs/PatchDIFF-Concept-Paper-5.md` | Complete | Pass (no findings) |
| DOC | Documentation and change records | `CHANGELOG.md`, `README.md`, `README_INTERNAL_MCP.md`, `evaluation/README.md`, `docs/LEGACY_COMPATIBILITY.md`, `docs/HOST_INTEGRATION_GUIDE.md`, `docs/MODERNIZATION_CHANGE_DOC.md`, `docs/TEST_MATRIX.md` | `docs/MCP_TOOLS.md`, `docs/usability/friction-followup-decision.md` | Complete | Pass (no findings) |
| SKILL | Skills and agent instructions | None | `.agents/skills/patchdiff-core-runtime/SKILL.md`, `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`, `.agents/skills/patchdiff-persistence-replay-save/SKILL.md`, `.agents/skills/patchdiff-testing-review/SKILL.md` | Complete (unchanged verification) | Pass (no findings) |
| MCP | MCP schemas and public API | `backend/app/mcp/tools.py`, `docs/MCP_TOOLS.md` | `backend/app/mcp/external_adapter.py`, `backend/app/pdcp/typed.py`, `backend/app/pdcp/operations.py`, `backend/app/pdcp/replacement.py` | Complete | Pass (`MCP-001` & `FX-01`/`FX-02`/`FX-06`..`FX-09`/`FX-12` closed) |
| RUN | Core runtime, parsing, and replay | None | `backend/app/core/`, `backend/app/pdcp/` | Complete (unchanged verification) | Pass (no findings) |
| SVC | Services, persistence, and migrations | `backend/app/services/near_miss_service.py` | `backend/app/services/pdcp_service.py`, `backend/app/storage/models.py` | Complete | Pass (`SVC-001` & `FX-03`..`FX-05` closed) |
| TEST | Tests, harnesses, and evaluation | `backend/tests/unit/test_friction_followup.py`, `backend/tests/unit/test_mcp_arguments_paging.py`, `backend/tests/integration/test_friction_followup_live.py` | `backend/tests/unit/test_pass_a_diagnostics.py`, `backend/tests/integration/test_mcp_history_paging_live.py`, `evaluation/offline_eval.py` | Complete | Pass (`FX-03`, `FX-04`, `FX-06`, `FX-10` closed) |
| DEP | Dependencies, packaging, and configuration | None | `pyproject.toml`, `docker-compose.yml` | Not applicable | Not applicable |

---

## 3. Architecture and design trace (`Concept Paper 5` → `AGENTS.md` → `A1–A8` / `C1–C6` → code)

1. **`docs/PatchDIFF-Concept-Paper-5.md` & `AGENTS.md` invariants:**
   - The core runtime (`backend/app/core/`, `backend/app/pdcp/`) remains 100% pure, deterministic, and exact-match-only. Neither `SVC-001` nor `MCP-001` touches `backend/app/core/` or `backend/app/pdcp/`.
   - Post-commit advisory `near_misses` remain strictly response-only in `backend/app/services/near_miss_service.py`, never persisting to PostgreSQL, never mutating the target, and never altering verdicts or failure labels.
   - `AppendOnlyPdcpLogs` and `AppendOnlyManifestLedger` remain immutable and append-only; no schema migration, persisted record format, hash, request fingerprint, or runtime profile (`0.2.2`, `0.3.0`, `0.4.0`, `0.5.0`) is modified.
2. **Contract trace for `SVC-001` (`backend/app/services/near_miss_service.py`):**
   - `near_misses` evaluates windows of lengths `len(needle) - 1`, `len(needle)`, and `len(needle) + 1` (positive widths) across up to `MAX_SCAN_BUFFER_CHARS = 65,536` code points under `MAX_COMPARISON_CELLS = 1,000,000`.
   - `_candidate_starts` partitions `needle` into `threshold + 1` disjoint pieces. By the pigeonhole principle, any window within Levenshtein distance `<= threshold` must contain at least one piece unchanged (`str.find` enumeration), shifting its start by at most `±threshold` from the piece's offset in `needle`. When piece occurrences exceed `starts // 2`, `_candidate_starts` merges adjacent unedited pieces into contiguous `2`-piece runs (`len(pieces) >= 2`) and checks 3-character 1-edit variations on rare pieces (`len >= 3 * (threshold + 1)`), covering both windows with `<= threshold - 1` edits among the first `threshold` pieces (Loop 1) and windows where all first `threshold` pieces have 1 edit and the last piece is exact (Loop 2), including leading insertions at `pos_k == 0`.
   - `_window_distances` evaluates each candidate window start using an exact Ukkonen-banded (`band_radius = (threshold + 1) // 2`) Landau–Vishkin diagonal-wave DP (`reach` along diagonals `d in [-band_radius, band_radius]` for edit distances `e = 0..threshold`, extended via `os.path.commonprefix`).
   - `comparison_cells` charges `max(1, min(len(query), reached_row)) * (2 * band_radius + 1)` cells per evaluated window start. If `comparison_cells + window_cells > MAX_COMPARISON_CELLS`, the over-budget window is discarded before updating `comparison_cells` or `scanned_end`, preserving the exact ranking of `[0, scanned_end)`.
3. **Contract trace for `MCP-001` (`backend/app/mcp/tools.py`):**
   - `patchdiff_get_pdcp_log` defers `AppendOnlyPdcpLogs.pdcp_content` on the primary ORM query and joins `_attempt_meta_lateral(log_alias)` (`AppendOnlyPdcpLogs.__table__.alias("l")`) via `LATERAL (... OFFSET 0)` to project bounded `intent` (`<= 256` chars) and `intent_truncated`.
   - For records `> 64 KB`, `_attempt_meta_lateral` uses guarded 4 KB slice fast paths: `left(l.pdcp_content, 4096)` split at `,"operations":[` for `patchdiff-tx/2` and `patchdiff-tx/3`, and `right(l.pdcp_content, 4096)` stripped through the last `,"format":"patchdiff-tx/1",` marker (`regexp_replace(..., '^.*,"format":"patchdiff-tx/1",', '{', 's')`) for `patchdiff-tx/1`. Both slices require `pg_input_is_valid(..., 'jsonb')`, `jsonb_typeof(...) = 'object'`, `NOT (? 'evidence_format')`, and `? 'intent'`, falling back to full `(l.pdcp_content)::jsonb` whenever a slice lacks `'intent'` (e.g., `intent > 4 KB` or non-canonical key order).
   - `patchdiff_get_manifest_ledger` checks whether any row on the page requires JSON extraction (`row.origin == "typed" and (row.derived_json or {}).get("operation") != "replace_all"`). On `patchdiff-tx/3`-only or legacy `0.2.3` pages (`needs_json == False`), it does not touch `pdcp_content` at all (`tx/3` uses `row.intent`, `rationale = None`). When `needs_json == True`, it joins `_ledger_meta_lateral(log_alias)`, which casts `l.pdcp_content::json` at most once per `patchdiff-tx/1` or `patchdiff-tx/2` attempt row (`OFFSET 0`) and projects `transaction_intent` and `rationales` via `json_to_record` and `json_array_elements`.

---

## 4. Category-by-category review

### ARCH — Architecture and contracts

- **Scope:** `docs/MODERNIZATION_ARCHITECTURE.md`, `docs/MCP_FIRST_MVP.md`, `docs/PATCHDIFF_CORE_SPEC.md`, `docs/PDCP_FORMAT.md`, `docs/usability/friction-followup-decision.md`.
- **Coverage:** Complete (`5/5` files inspected against `AGENTS.md` and `docs/PatchDIFF-Concept-Paper-5.md`).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Comments:** `docs/MODERNIZATION_ARCHITECTURE.md` bridges `docs/PatchDIFF-Concept-Paper-5.md` Section 23 hypotheses (`H1`–`H7`) and Section 26/28 limitations to the modernized `patchdiff-tx/1..3` contracts and `PR #14` benchmarks (`offline_eval.py`, `SVC-001`, `MCP-001`), while preserving `docs/PatchDIFF-Concept-Paper-5.md` untouched. `docs/PDCP_FORMAT.md`, `docs/MCP_FIRST_MVP.md`, and `docs/PATCHDIFF_CORE_SPEC.md` foreground the active typed JSON formats (`patchdiff-tx/1`, `tx/2`, `tx/3`) and reference `docs/LEGACY_COMPATIBILITY.md` for frozen `.pdcp` v0.2.3 and historical replay profiles (`0.1.0`–`0.2.1`).
- **Verification gaps:** None.
- **Verdict:** Pass.

### DOC — Documentation and change records

- **Scope:** `CHANGELOG.md`, `README.md`, `README_INTERNAL_MCP.md`, `evaluation/README.md`, `docs/LEGACY_COMPATIBILITY.md`, `docs/HOST_INTEGRATION_GUIDE.md`, `docs/MODERNIZATION_CHANGE_DOC.md`, `docs/TEST_MATRIX.md`.
- **Coverage:** Complete (`8/8` files inspected against `docs/MCP_TOOLS.md`, `evaluation/offline_eval.py`, and implementation behavior).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Comments:**
  - `docs/LEGACY_COMPATIBILITY.md` consolidates all frozen `.pdcp` v0.2.3 syntax rules, `patchdiff_submit_pdcp`, deprecated regeneration wrappers (`patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`), historical runtime replay profiles (`0.1.0`–`0.2.1`), and the `.pdcp` vs. `patchdiff-tx/1` byte/delimiter comparison into one reference document, with concise pointers in the active docs.
  - `README.md` and `evaluation/README.md` present the reproducible `evaluation/offline_eval.py` payload byte tables, `SVC-001` 65,536-code-point near-miss benchmarks (`1.7 ms` prose, `41.9 ms` repetitive log), `MCP-001` PostgreSQL 16+ `LATERAL` history/ledger benchmarks (`14.68 ms` / `22.85 ms` on 20 MB `tx/3`, `136.72 ms` / `221.59 ms` on 20 MB `tx/1`), hard context budgets, ecosystem comparison matrix, and 3-step typed JSON walkthrough.
  - `docs/MCP_TOOLS.md` and `CHANGELOG.md` document the `comparison_cells` formula (`max(1, min(len(query), reached_row)) * (2 * band_radius + 1)`), the at-most-one-window overshoot discarded at the `MAX_COMPARISON_CELLS` boundary (`FX-04`, `FX-05`), and the PostgreSQL 16+ `pg_input_is_valid` `LATERAL` projections (`FX-12`).
- **Verification gaps:** None.
- **Verdict:** Pass.

### SKILL — Skills and agent instructions

- **Scope:** None (`.agents/skills/` unchanged).
- **Coverage:** Complete (verified `.agents/skills/` against updated `near_miss_service.py` and `tools.py`).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification gaps:** None.
- **Verdict:** Pass.

### MCP — MCP schemas and public API

- **Scope:** `backend/app/mcp/tools.py`, `docs/MCP_TOOLS.md`.
- **Coverage:** Complete (`2/2` files inspected and benchmarked against live PostgreSQL 16.3).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope (`FX-01` repeated-SQL-cast regression on large `tx/1` ledger pages resolved via single-cast `_ledger_meta_lateral` with `OFFSET 0` and 4 KB tail slice in `_attempt_meta_lateral`).
- **P3 findings:** None identified within reviewed scope (`MCP-001` closed).
- **Measured latency (`MCP-001` & `FX-01`, Windows 11, PostgreSQL 16.3, 7-run medians after warmup):**
  - **50 × 400 KB (`20 MB`) `patchdiff-tx/3` records (`limit=50`):**
    - `patchdiff_get_manifest_ledger`: **279.6 ms** on `d09fbc8` → **14.68 ms** on `4f0dddf` (**19.0× speedup**, zero `pdcp_content` access).
    - `patchdiff_get_pdcp_log`: **372.4 ms** on `d09fbc8` → **22.85 ms** on `4f0dddf` (**16.3× speedup** via 4 KB head slice).
  - **20 × 1 MB (`20 MB`) `patchdiff-tx/1` records (5 edits × 200 KB each):**
    - `patchdiff_get_manifest_ledger(limit=50)` (10 logs): **305.55 ms** on `d09fbc8` → **221.59 ms** on `4f0dddf` (vs. 2,699.19 ms in initial multi-cast SQL before `FX-01`).
    - `patchdiff_get_manifest_ledger(limit=100)` (20 logs): **449.92 ms** on `d09fbc8` → **445.33 ms** on `4f0dddf`.
    - `patchdiff_get_pdcp_log(limit=50)` (20 logs): **136.72 ms** on `4f0dddf` (via 4 KB tail slice).
- **Verification gaps:** None.
- **Verdict:** Pass (`MCP-001` closed).

### RUN — Core runtime, parsing, and replay

- **Scope:** None (`backend/app/core/` and `backend/app/pdcp/` unchanged).
- **Coverage:** Complete (verified zero changes to core runtime and canonical JSON key order pinned in unit tests).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification gaps:** None.
- **Verdict:** Pass.

### SVC — Services, persistence, and migrations

- **Scope:** `backend/app/services/near_miss_service.py`.
- **Coverage:** Complete (`1/1` file inspected, unit-tested, fuzz-tested, and benchmarked).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope (`SVC-001` closed).
- **Measured latency (`SVC-001`, Windows 11, Python 3.11.9, 5-run medians):**
  - **65,536-code-point repetitive structured log buffer (`needle` len 45, `threshold=4`):**
    - Before (`d09fbc8`): **708.5 ms** (`scanned_end=45,404`, `scope_truncated=True`, `comparison_cells=1,000,000` — stopped early at 69% of buffer).
    - After (`4f0dddf`): **41.9 ms** (`scanned_end=65,493`, `scope_truncated=False`, `comparison_cells=142,255` — **16.9× faster** and scans 100% of the buffer).
  - **65,536-code-point varied prose buffer (`needle` len 45, `threshold=4`):**
    - Before (`d09fbc8`): **100.2 ms** (`scanned_end=65,493`, `scope_truncated=False`, `comparison_cells=174,897`).
    - After (`4f0dddf`): **1.7 ms** (`scanned_end=65,493`, `scope_truncated=False`, `comparison_cells=585` — **58.9× faster**).
- **Verification gaps:** None.
- **Verdict:** Pass (`SVC-001` closed).

### TEST — Tests, harnesses, and evaluation

- **Scope:** `backend/tests/unit/test_friction_followup.py`, `backend/tests/unit/test_mcp_arguments_paging.py`, `backend/tests/integration/test_friction_followup_live.py`.
- **Coverage:** Complete (`3/3` files inspected and executed).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Comments:**
  - `test_candidate_starts_strict_path_and_loop2_and_leading_insertion_exactness` (`FX-03`) uses fixed seed `12345` over 120 trials on 3- and 4-symbol alphabets (`len(needle) in 16..22`, `starts > 120`), asserting `strict_hits >= 50`, `loop2_only_hits >= 15`, `leading_ins_hits >= 15`, and exact ranking agreement with `_reference`.
  - `test_near_misses_cell_cap_boundary_stops_cleanly` (`FX-04`) verifies clean stopping at `MAX_COMPARISON_CELLS` without charging the discarded over-cap window.
  - `test_canonical_typed_records_keep_expected_key_order` (`FX-02`) pins canonical JSON key order across `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`.
  - `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` (`FX-01`, `FX-02`, `FX-10`) verifies: (a) zero `pdcp_content` column selection via `before_cursor_execute` and `after_cursor_execute` hooks, (b) `include_content=True` 1 MB page budget enforcement on `3 × 600 KB` `tx/3` records, (c) `patchdiff-invalid-input/1` evidence envelope storage and skipping on `bad\x00intent`, (d) `> 64 KB` `tx/1` attempt with literal `,"format":"patchdiff-tx/1",` inside JSON strings, (e) `> 64 KB` `tx/2` attempt with `> 4 KB` intent (`4,200` chars) falling back to full JSON and truncating to 256 chars, (f) `_attempt_meta_lateral` `? 'intent'` fallback on `> 64 KB` reordered `tx/1` and `tx/2` JSON records, and (g) `_ledger_meta_lateral` preservation of empty-string rationale `""` vs `null`/omitted.
- **Verification gaps:** None.
- **Verdict:** Pass.

### DEP — Dependencies, packaging, and configuration

- **Scope:** None.
- **Coverage:** Not applicable.
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification gaps:** None.
- **Verdict:** Not applicable.

---

## 5. Devin PR #14 Review (`CK-01`..`CK-13` / `FX-01`..`FX-12`) Resolution Summary

| Item | Requirement | Resolution |
| --- | --- | --- |
| `FX-01` | Eliminate repeated JSON casts on `tx/1`/`tx/2` ledger pages; preserve `""` rationale vs `None`; add guarded `tx/1` tail slice in `_attempt_meta_lateral`; benchmark 20 × 1 MB `tx/1` | `_ledger_meta_lateral` uses a single `LATERAL (... OFFSET 0)` casting `l.pdcp_content::json` once per row (`tx/1` and `tx/2` only) and preserves `""` vs `null`/omitted rationale. `_attempt_meta_lateral` uses a guarded 4 KB tail slice (`regexp_replace(right(l.pdcp_content, 4096), '^.*,"format":"patchdiff-tx/1",', '{', 's')`) with `? 'intent'` fallback. |
| `FX-02` | Guard 4 KB slices with `? 'intent'` fallback and pin canonical JSON key order | Added `AND ... ? 'intent'` to both head (`tx/2`, `tx/3`) and tail (`tx/1`) 4 KB slices in `_attempt_meta_lateral`; added `test_canonical_typed_records_keep_expected_key_order`. |
| `FX-03` | Commit fixed-seed strict-path fuzz test verifying Loop-2-only and leading-insertion exactness | Added `test_candidate_starts_strict_path_and_loop2_and_leading_insertion_exactness` (`seed=12345`) in `backend/tests/unit/test_friction_followup.py`. |
| `FX-04` | Document at-most-one-window overshoot discarded at `MAX_COMPARISON_CELLS` boundary and add boundary test | Documented in `docs/MCP_TOOLS.md` and `CHANGELOG.md`; added `test_near_misses_cell_cap_boundary_stops_cleanly`. |
| `FX-05` | Document `comparison_cells` formula in `docs/MCP_TOOLS.md` and `CHANGELOG.md` | Updated `docs/MCP_TOOLS.md` and `CHANGELOG.md` with `max(1, min(len(query), reached_row)) * (2 * band_radius + 1)`. |
| `FX-06` | Update `FakeSession` in `test_mcp_arguments_paging.py` and remove fallback branches in `tools.py` | Updated `row(sequence)` in `test_mcp_arguments_paging.py` and deleted fallback branches in `patchdiff_get_pdcp_log` and `patchdiff_get_manifest_ledger`. |
| `FX-07` | Remove dead helpers `_decoded_record` and `_record_field` after grepping for callers | Verified zero other callers in repository; deleted `_decoded_record`, `_record_field`, and unused `import json` from `backend/app/mcp/tools.py`. |
| `FX-08` | Restrict ledger JSON extraction to `patchdiff-tx/1` and `patchdiff-tx/2` | `_ledger_meta_lateral` checks `l.protocol_version IN ('patchdiff-tx/1', 'patchdiff-tx/2')`; `tx/3` pages skip `_ledger_meta_lateral` entirely (`needs_json == False`). |
| `FX-09` | Remove hardcoded `append_only_pdcp_logs.` table references in SQL helpers | Derived column qualifiers from `AppendOnlyPdcpLogs.__table__.alias("l")` (`log_alias.name`); verified zero occurrences of `append_only_pdcp_logs.` in `backend/app/mcp/tools.py`. |
| `FX-10` | Strengthen live integration test (`evidence_format`, `include_content=True` budget, SQL statement checks) | Expanded `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` in `backend/tests/integration/test_friction_followup_live.py`. |
| `FX-11` | Rewrite review record last against final SHA with accurate helper names, `tx/1` benchmark, and fuzz test | Updated review record to `PR-14-4f0dddf-category-review.md` covering both `FX-01`..`FX-12` and the public documentation / `LEGACY_COMPATIBILITY.md` upgrade. |
| `FX-12` | Note PostgreSQL 16+ `pg_input_is_valid` requirement in docs/changelog | Documented in `docs/MCP_TOOLS.md`, `README.md`, `evaluation/README.md`, and `CHANGELOG.md`. |

---

## 6. Verification record and remaining gaps

| Check | Revision | Environment | Result |
| --- | --- | --- | --- |
| Full pytest suite (`pytest backend/tests -q`) | `bfbba27` / `4f0dddf` | Windows 11, Python 3.11.9, PostgreSQL 16.3 (`patchdiff-postgres`), isolated DB `patchdiff_fx_full_suite_20261025` (dropped after run) | **1,226 passed** (816 unit + 410 live-PostgreSQL integration), 0 failed, 0 skipped |
| Offline evaluation (`evaluation/offline_eval.py`) | `4f0dddf` | Windows 11, Python 3.11.9 | **Exit 0** (`Verdict equivalence on the shared applier: OK`, `Accepted guarded replacement content/hash oracles: OK`) |
| Fixed-seed strict-path fuzz test (`test_candidate_starts_strict_path_and_loop2_and_leading_insertion_exactness`) | `4f0dddf` | Windows 11, Python 3.11.9 | **Passed** (`strict_hits >= 50`, `loop2_only_hits >= 15`, `leading_ins_hits >= 15`, 100% exact ranking match) |
| Live E2E `MCP-001` benchmarks (`tx/1` 20 × 1 MB & `tx/3` 50 × 400 KB) | `bfbba27` / `4f0dddf` | Windows 11, Python 3.11.9, PostgreSQL 16.3, isolated DB `patchdiff_fx_bench_20261025` (dropped after run) | `tx/1` ledger `limit=50`: **221.59 ms** (vs. 305.55 ms base); `tx/1` ledger `limit=100`: **445.33 ms** (vs. 449.92 ms base); `tx/1` log `limit=50`: **136.72 ms**; `tx/3` ledger `limit=50`: **14.68 ms**; `tx/3` log `limit=50`: **22.85 ms** |

---

## 7. Overall disposition and finding closure table

**Overall disposition:** **Approve** (all material categories reviewed; zero open P0/P1/P2/P3 findings; `SVC-001`, `MCP-001`, PR #14 review items `FX-01`..`FX-12`, and the public documentation / `LEGACY_COMPATIBILITY.md` upgrade closed with unit tests, live-PostgreSQL integration tests, and before/after latency measurements).

| Finding ID | Friction / Review ID | Category | Priority | Status | Fix commit | Verification evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `SVC-001` | `NF-5`, `FX-03`..`FX-05` | `SVC` | P3 (advisory) | **Closed** | `bfbba27` / `4f0dddf` | `test_repetitive_64k_buffer_scans_to_end_within_work_bound`, `test_candidate_starts_strict_path_and_loop2_and_leading_insertion_exactness`, `test_near_misses_cell_cap_boundary_stops_cleanly` (`test_friction_followup.py`); 65,536-cp repetitive buffer: 708.5 ms (`scanned_end=45404`, `scope_truncated=True`) → **41.9 ms** (`scanned_end=65493`, `scope_truncated=False`, `142,255` cells); 65,536-cp varied prose: 100.2 ms → **1.7 ms** |
| `MCP-001` | `NF-8`, `FX-01`, `FX-02`, `FX-06`..`FX-12` | `MCP` | P3 (advisory) | **Closed** | `bfbba27` / `4f0dddf` | `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` (`test_friction_followup_live.py`), `test_canonical_typed_records_keep_expected_key_order` (`test_friction_followup.py`), `test_mcp_arguments_paging.py`; `tx/3` 50 × 400 KB ledger page: 279.6 ms → **14.68 ms**; `tx/3` log page: 372.4 ms → **22.85 ms**; `tx/1` 20 × 1 MB ledger page (`limit=50`): 305.55 ms → **221.59 ms**; `tx/1` log page (`limit=50`): **136.72 ms** |
