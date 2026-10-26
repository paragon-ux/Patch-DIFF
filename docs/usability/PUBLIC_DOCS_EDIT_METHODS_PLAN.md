# PatchDIFF Public Documentation Revision Plan (v2 — Post-Review Revision)

**Target Repository & Branch:** `paragon-ux/Patch-DIFF`, branch `perf/pr13-deferred-p3` (PR #14)  
**Purpose:** Replace internal implementation-history framing with accurate, externally understandable product documentation centered on transactional agent editing guarantees, balanced edit-method comparisons, and strictly verified operational measurements.  
**Status:** Revised v2 incorporating all findings from `ChatGPT-Documentation-Review.md`, verified against live repository source and `evaluation/offline_eval.py`.

---

## 0. Review Disposition & Verification Ledger (`ChatGPT-Documentation-Review.md`)

Every P0, P1, and P2 finding from the external documentation review has been verified against the codebase and incorporated into this v2 plan:

| Review ID | Finding Summary | Code / Script Verification | Resolution in v2 Plan |
| :--- | :--- | :--- | :--- |
| **P0-1** | **`tx/3` byte-accounting accuracy:** Fix `246 B` / `51 B` wire-overhead miscalculation for `patchdiff_submit_replacement`. | Verified in `evaluation/offline_eval.py`: for `"old" -> "new"` (`3 B` raw replacement), MCP `arguments` JSON is **`232 B`**, persisted canonical `tx/3` record is **`290 B`**, and complete JSON-RPC `tools/call` line (with fixed `id=1` and terminal LF) is **`341 B`** (`341 - 232 = 109 B` JSON-RPC wrapper; `341 - 290 = 51 B` compares two different representations and is not wire overhead). For the 2 KB rewrite (`LONG_BODY.replace("fox", "cat")`), raw replacement text is **`2,109 B`** (40 lines with 39 `\n` chars), persisted record is **`2,435 B`**, and complete `tools/call` line is **`2,486 B`** (`377 B` above raw content, including 39 bytes of `\n` JSON escaping, `arguments` fields, and JSON-RPC wrapper). | Corrected in Section 4.1 (`evaluation/README.md`) with all four representations (`raw text B`, `MCP arguments B`, `persisted record B`, `complete JSON-RPC tools/call B`) reported in separate columns. |
| **P0-2** | **Incremental-edit byte formula (`+28 B` vs. `+27 B`):** Scenario 1 (`"old" -> "new"`, `151 B`) and Scenario 2 (`5 × 1-byte edits`, `259 B`) use different string lengths (`3 B` vs. `1 B`). | Verified: one minimal edit object in `edits[]` requires **`25 B`** of JSON keys/punctuation (`{"match":"","replace":""}`) + **`1 B`** array comma separator (`,`) + UTF-8 JSON-escaped lengths of `match` and `replace`. For two 1-byte ASCII strings (`{"match":"a","replace":"1"}`), the controlled marginal cost per additional edit is **`28 B`** (`25 + 1 + 1 + 1 = 28 B`). | Corrected in Section 3.4 and Section 4.1 with the exact formula (`26 B + len(escaped_match) + len(escaped_replace)`). |
| **P0-3** | **Remove unmeasured competitive multipliers & speculative token/decoding tables:** Do not present `3–7× smaller`, `3× fewer calls`, or `~4 B ≈ 1 token` / `200–320s` back-of-the-envelope estimates as measured benchmarks. | Verified against `docs/MODERNIZATION_ARCHITECTURE.md` Decision A8: live-model comparative evaluation is **NOT RUN**. Only `evaluation/offline_eval.py` byte counts and local workload benchmarks are measured. | Enforced via Section 2 (*Evidence and Publication Rules*). `README.md` uses verified PatchDIFF-only measurements (`151 B` and `259 B` compact MCP `arguments`); workflow comparisons are explicitly labeled as analytical examples. |
| **P0-4** | **Distinguish edit format from host implementation in comparisons:** OpenAI `apply_patch` delegates atomicity to the host; Anthropic `str_replace` checks exact match/ambiguity; RFC 6902 JSON Patch supports atomic `test` preconditions. | Verified against upstream documentation and `backend/app/`. | Replaced the 6-column table with ChatGPT's balanced 3-column capability matrix (*Text replacement*, *Diff/patch tools*, *PatchDIFF*) using `"Host-dependent"` / `"Implementation-dependent"`, and moved AST/JSON Patch and OT/CRDT to a dedicated *"Alternatives & Tradeoffs"* subsection. |
| **P0-5** | **Keep units strictly separate:** Do not conflate Unicode code points (`4,000` / `8,000`), raw UTF-8 bytes, compact ASCII-escaped JSON bytes (`<= 4,096 B`, `<= 8,192 B`, `<= 18,432 B`), and model tokens. | Verified in `backend/app/mcp/tools.py` (`DEFAULT_READ_LENGTH = 4000`, `MAX_READ_LENGTH = 8000` Unicode code points) and `backend/app/services/rejection_context.py` (`ensure_ascii=True` compact JSON bytes). | Enforced across `README.md`, `evaluation/README.md`, and `docs/MCP_TOOLS.md`; every limit explicitly names its unit. |
| **P1-1** | **Scope latency claims accurately:** `1.7 ms` and `41.9 ms` near-miss figures (5-run medians) and `14.68–445.33 ms` PostgreSQL history figures (7-run medians after warmup) are internal PR #13 vs. PR #14 fixture medians, not universal service-level ceilings or cross-product benchmarks. | Verified in `docs/reviews/PR-14-4f0dddf-category-review.md` and `backend/app/services/near_miss_service.py` (`MAX_COMPARISON_CELLS = 1_000_000`). | Scoped as local benchmark medians on specified fixtures in `evaluation/README.md`, with operational caps (`1,000,000` comparison cells, `65,536` code points) foregrounded in `README.md`. |
| **P1-2** | **Delimiter fixture accuracy:** The 5th `offline_eval.py` scenario tests `"a\n=======\nb"` (standalone `=======` separator collision), not `<<<<<<< MATCH`. | Verified in `evaluation/offline_eval.py` lines 88–97 (`"payload has a delimiter line"` uses `"a\n=======\nb"` -> `rejected:block_malformed` in PDCP v0.2.3 vs. `accepted` in `tx/1` at `162 B` args / `217 B` record). | Corrected in Section 4.1 (`evaluation/README.md`) and `docs/LEGACY_COMPATIBILITY.md`; clarified that JSON string encoding eliminates `.pdcp` delimiter-line collisions while JSON syntax remains validated. |
| **P1-3** | **Near-miss & ambiguity recovery conditions + intermediate-buffer coordinates:** Document scan limits, `text` field name (not `matched_text`), and `prior_changes > 0` coordinate semantics. | Verified in `backend/app/services/near_miss_service.py` line 240 (`"text": text[start:end]`) and `backend/app/pdcp/applier.py` (`buffer_stage = "intermediate_buffer"` when `prior_changes > 0`). | Incorporated into Section 3.6, Section 5 (`docs/MCP_TOOLS.md`), and `docs/HOST_INTEGRATION_GUIDE.md`. |
| **P1-4** | **`patchdiff_preview` advisory & unreserved semantics:** Preview takes no target row lock, writes no rows, and does not reserve a version. | Verified in `backend/app/services/pdcp_service.py` (`preview_pdcp_transaction`). | Documented in Section 3.3, Section 3.6, and Section 5 (`docs/MCP_TOOLS.md`). |
| **P1-5** | **Normative edge cases (`include_content` first-entry exception, `18,432 B` enrichment scope, guarantee boundaries):** Document exact runtime rules. | Verified in `backend/app/mcp/tools.py` line 391 (`if not budget_used or budget_used + size <= MAX_CONTENT_PAGE_BYTES`) and `backend/tests/unit/test_pass_a_diagnostics.py` lines 71–73 (`<= 18432` on enrichment dict). | Incorporated into Section 3.6 and Section 5 (`docs/MCP_TOOLS.md`). |
| **P2-1** | **Streamline `README.md` hierarchy, expand existing `MODERNIZATION_ARCHITECTURE.md` §1.1, and avoid local-only path citations:** Keep first screen focused on product identity and workflow; refine existing §1.1 rather than duplicating it. | Verified against current `README.md` and `docs/MODERNIZATION_ARCHITECTURE.md` on `perf/pr13-deferred-p3`. | Adopted the 7-section `README.md` layout (Section 3), updated Section 6 to refine existing `MODERNIZATION_ARCHITECTURE.md` §1.1, and removed local-only path citations. |

---

## 1. Primary Objective

Explain the value of PatchDIFF to MCP host developers, coding-agent developers, and technical evaluators encountering it for the first time.

The public documentation must answer five questions in order:

1. **What does PatchDIFF do?**
2. **Which problems does it address that simpler editing tools leave to the host?**
3. **What guarantees does the implementation actually enforce?**
4. **What are its operational costs, constraints, and limitations?**
5. **How can a developer try it and verify its behavior?**

Preserve PatchDIFF's central identity: **a deterministic, PostgreSQL-backed, per-target document transaction service exposed through MCP.**

Do not redefine PatchDIFF as an AST editor, generic merge engine, filesystem-wide multi-file transaction manager, or semantic correctness validator. Keep legacy `.pdcp` v0.2.3 syntax and deprecated regeneration wrappers isolated in `docs/LEGACY_COMPATIBILITY.md` with only a single reference pointer in active documentation.

---

## 2. Evidence and Publication Rules (Four-Tier Classification)

All claims in public documentation must use four explicit evidence labels (`docs/MODERNIZATION_ARCHITECTURE.md` Decision A8):

| Evidence Tier | Permitted Wording | Verification Requirements |
| :--- | :--- | :--- |
| **`Measured`** | *"The single-edit `tx/1` fixture serializes to `151` UTF-8 bytes of compact MCP `arguments` (`206` bytes persisted)"*; *"Local 5-run median of `41.9 ms` (`1.7 ms` on varied prose) on the 65,536-code-point benchmark fixture"* | Reproducible via `PYTHONPATH=backend python evaluation/offline_eval.py` or local benchmark scripts with environment, workload, repetition count, and representation named. Internal PR #13 vs. PR #14 benchmarks must be explicitly distinguished from external tool comparisons. |
| **`Derived`** | *"Applying 5 edits takes `1` `patchdiff_submit_edits` invocation vs. `5` single-replacement tool calls"*; *"Each additional minimal edit adds `25 B` object framing + `1 B` comma + escaped string bytes (`+28 B` for two 1-byte ASCII strings)"* | Exact arithmetic or deterministic tool-call counts for an explicitly specified interface workflow; distinguish tool calls from model turns. |
| **`Illustrative`** | *"On a `65,536 B` (`~16,384`-token illustrative at `~4 UTF-8 B ≈ 1 token`) file..."* | Explicitly state conversion assumptions; never promote illustrative byte-to-token rules of thumb to tokenizer measurements. |
| **`Not yet measured`** | *"Whether structured rejection diagnostics reduce end-to-end model recovery turns across diverse tasks requires a controlled live-model study (`NOT RUN`)"* | Explicitly state that controlled live-model experiments have not been run (Decision A8). |

---

## 3. `README.md` Structure — Restoring Concrete Differentiation & 4 Operational Dimensions

```text
1. What is PatchDIFF? — Concise product identity, architecture diagram, and per-target PostgreSQL transaction guarantee
2. Why PatchDIFF Instead of Existing Edit Methods? — Devin's 8-row concrete editing-problem comparison table + specific breakdowns against Full Regeneration, Unified Diff (`apply_patch`), `str_replace`, and Unguarded Line-Range Editing
3. How PatchDIFF Resolves Common Agent-Editing Failures (Strict Matching Without Blind Recovery) — Applicability/selection enforcement vs. semantic correctness; `exact_candidates` (<= 5), `near_misses` (<= 3), `failure_context` (<= 256 code points), `patchdiff_preview`, and `client_request_id` recovery
4. Operational Efficiency: Payload, Context, Tool Calls, and Latency — All 4 user-centric dimensions labeled with `Measured`, `Derived`, `Illustrative`, and `Not yet measured`, distinguishing PR #14 internal server/DB optimizations from external editor comparisons
5. Choosing a Transaction Format & 3-Step Walkthrough — `tx/1` (`patchdiff_submit_edits`), `tx/2` (`patchdiff_submit_operations`), `tx/3` (`patchdiff_submit_replacement`) + exact MCP request/response payloads
6. Guarantees, Operational Bounds, and Limitations — Per-target scope, PostgreSQL authority, host-owned semantics, intermediate-buffer coordinate rule, conservative UAX #29 `grapheme_boundary_split` warning
7. Detailed Documentation & Reproducible Evaluation — Setup, Claude Desktop config, MCP tool surface, test commands, and reference map
```

### 3.1 Concrete Edit-Method Comparison (Devin's 8 Editing Problems)

| Editing Problem | Conventional Approach | What PatchDIFF Provides Directly |
| :--- | :--- | :--- |
| **Small edit in a large file** | Full regeneration emits the complete replacement document on every turn | `patchdiff-tx/1` and `tx/2` emit only the matched/replaced spans plus compact transaction framing |
| **Repeated identical text** | Unique-match replacement (`str_replace`) requires expanding `old_str` with surrounding lines until unique | Explicit `occurrence_index`, `anchor_before` / `anchor_after` (`tx/1`), or guarded `[start, end)` spans (`tx/2`) without enlarging the match |
| **Unified diff formatting** | Agent must construct line-oriented hunks and maintain `@@ -l,s +l,s @@` header arithmetic | Structured JSON fields (`patchdiff_submit_edits` / `patchdiff_submit_operations`); zero hunk-header arithmetic or text-delimiter collision |
| **Coordinate & state drift** | Line-based edits depend on positions remaining unchanged since the agent last read the file | Required `expected_target_version` and/or `expected_current_hash` under `SELECT ... FOR UPDATE`, plus exact `expected_text` and optional `expected_before` / `expected_after` span checks |
| **Multiple changes in one target** | Single-replacement interfaces require $N$ separate tool calls (or leave multi-edit rollback to the host) | One `edits[]` / `operations[]` submission simulated sequentially in memory and committed all-or-nothing per target |
| **Missing or ambiguous match** | Basic interfaces return an error string, leaving the host to search for context in extra turns | Structured rejection with bounded `failure_context` (`<= 256` code points), up to 5 indexed `exact_candidates`, and up to 3 ranked Levenshtein `near_misses` |
| **Lost submission response** | Host must inspect current target state to guess whether a timed-out write succeeded before retrying | Retrying with the same `(target_file_id, client_request_id)` returns the exact recorded outcome (`deduplicated: true`) |
| **Long editing session & audit** | Host must maintain its own history, rejected-attempt logs, and state verification | Append-only attempt log (accepted + rejected), accepted manifest ledger with runtime-derived span/hash facts, `patchdiff_save` cycles, and profile-dispatched `patchdiff_replay` |

### 3.2 Strict Matching Without Blind Recovery

- Explicitly state that **strict matching and state guards enforce transaction applicability and selection constraints** (preventing silent misplacement or unguarded mutation), **not semantic correctness (`task_correct: "not_evaluated"`, `semantic: "not_evaluated"`) or guaranteed agent recovery**.
- Document how `exact_candidates` (up to 5 occurrences), post-commit `near_misses` (up to 3 Levenshtein candidates), `failure_context` (`<= 256` code points), `patchdiff_preview`, and `client_request_id` assist deterministic host-driven recovery without fuzzy auto-mutation.

### 3.3 Four Operational Efficiency Dimensions (`Measured` / `Derived` / `Illustrative` / `Not yet measured`)

1. **Output Payload Size & Scaling:** Measured `offline_eval.py` byte counts (`151 B` 1-edit `tx/1` args, `259 B` 5-edit `tx/1` args, `+28 B` per additional minimal 1-byte edit, `232 B` `tx/3` args / `290 B` record / `341 B` `tools/call` line, `162 B` `=======` delimiter-safe `tx/1` args) + clearly labeled `Derived` / `Illustrative` scaling comparisons against full-document regeneration and context-padded `str_replace`.
2. **Input Context Window Protection:** Enforced runtime bounds across reads (`4,000` default / `8,000` max Unicode code points), occurrence search (`context_chars` default `40` / cap `400`, `max_results` `200`), rejection enrichment (`<= 18,432 B` compact ASCII JSON across newly added enrichment fields), preview (`<= 32,768 B`), and SQL `LATERAL` history paging (`1,048,576 B` UTF-8 page budget with first-entry exception and `pdcp_content_omitted: "page_byte_budget"`).
3. **Tool Invocations (Batching & Recovery Workflows):** `Derived` call counts for 5 edits in one target (`1` `patchdiff_submit_edits` call vs. `5` single-replacement calls) and conditional recovery workflows (ambiguity, missing match, lost response via `client_request_id`), explicitly distinguishing tool invocations from live-model turns (`Not yet measured`).
4. **Latency (Model Decoding Scaling vs. Internal PR #14 Server/DB Benchmarks):** Separate `Illustrative` output-generation scaling from `Measured` internal PR #13 vs. PR #14 server/DB fixture medians (`SVC-001` 5-run medians: `100.2 ms -> 1.7 ms` prose at `585` cells, `708.5 ms -> 41.9 ms` repetitive logs at `142,255` cells; `MCP-001` 7-run medians: `279.6 ms -> 14.68 ms` ledger and `372.4 ms -> 22.85 ms` log on `50 × 400 KB` `tx/3`, plus `136.72 ms` log, `221.59 ms` ledger at `limit=50`, and `445.33 ms` vs. `449.92 ms` ledger at `limit=100` on `20 × 1 MB` `tx/1`).

### 3.6 Guarantees, Operational Bounds, and Limitations

Document exact runtime boundaries clearly near the comparison and measured behavior sections:
- **Requires managed PostgreSQL state:** Targets must be initialized and managed in PostgreSQL; PatchDIFF is a stateful transaction service, not a stateless CLI filter over arbitrary unindexed files.
- **Per-target atomicity only:** Transactions are atomic for a single `target_file_id` under `SELECT ... FOR UPDATE`. Cross-file / multi-target atomic transactions are not provided.
- **No automatic merge or semantic evaluation:** Concurrent conflicting edits are deterministically rejected (`version_mismatch` / `hash_mismatch`). PatchDIFF never evaluates whether an edit is semantically or syntactically valid for the target language (`task_correct: "not_evaluated"`, `semantic: "not_evaluated"`).
- **External file modifications are not tracked:** Exporting a target writes a snapshot; edits made outside PatchDIFF to files on disk are not tracked unless re-uploaded/initialized.
- **Canonical LF text and Unicode code-point indexing:** All target text and submitted strings are canonicalized (`\r\n` and `\r` normalized to `\n`), and all span/read offsets (`start`, `end`, `length`) are 0-based **Unicode code-point** indices. `grapheme_boundary_split` is a conservative UAX #29 approximation (combining marks, ZWJ, regional indicators, emoji modifiers/variation selectors), not a full Unicode segmentation engine.
- **`patchdiff_preview` is advisory and unreserved:** Preview runs the identical validation and in-memory simulation pipeline without acquiring a `SELECT ... FOR UPDATE` lock, writing audit rows, or reserving a target version. Subsequent submission re-locks and re-checks all guards.
- **Conditional near-miss scanning and intermediate-buffer coordinates:** `near_misses` runs only on `match_absent` when `len(match) <= 64` code points, scans at most the first `65,536` code points under a `1,000,000` comparison-cell cap (`MAX_COMPARISON_CELLS`), and is omitted (`omission_reason = "caller_transaction"`) when called inside a caller-owned SQLAlchemy transaction. When an edit fails after earlier edits in the same transaction (`prior_changes > 0`, `buffer_stage = "intermediate_buffer"`), candidate offsets and `occurrence_index` values refer to the **in-memory sequential buffer**, not the persisted canonical target.

---

## 4. `evaluation/README.md` Revision Plan — Authoritative Evidence & Methodology

Make `evaluation/README.md` the single authoritative source for all offline payload accounting, local performance benchmarks, analytical comparisons, and the unexecuted live-model study design.

### 4.1 Offline Payload Byte Accounting (`evaluation/offline_eval.py`)

Report exact UTF-8 byte measurements with strict separation of representations:
1. **Table 1 — `patchdiff-tx/1` and Legacy `.pdcp` v0.2.3 Across All 5 Scenarios:**
   - Separate columns for **Raw Match/Replace Content Bytes**, **MCP `arguments` JSON Bytes** (`patchdiff_submit_edits` minimal vs. matched prose vs. `patchdiff_submit_pdcp`), and **Persisted Canonical Record Bytes** (`append_only_pdcp_logs.pdcp_content`).
   - Explicitly document the **controlled marginal edit size formula**: adding an edit `{ "match": m, "replace": r }` to `edits[]` adds **`25 B`** of JSON object framing (`{"match":"","replace":""}`) + **`1 B`** array comma separator (`,`) + UTF-8 JSON-escaped byte lengths of `m` and `r` (**`28 B`** per additional edit when `m` and `r` are 1-byte ASCII strings, as in Scenario 2's `5 × 1-byte edits`). Explain why `(259 - 151) / 4 = 27 B` reflects the 4-byte difference between Scenario 1 (`"old"`+`"new"` = `6 B` total strings, `151 B`) and a 1-byte-string first edit (`"a"`+`"1"` = `2 B` total strings, `147 B` base + `4 × 28 B = 259 B`).
   - Accurately describe Scenario 5 (`"payload has a delimiter line"`): the fixture payload is `"a\n=======\nb"`, which contains a standalone `=======` separator line that collides with the `.pdcp` v0.2.3 block grammar (`rejected:block_malformed`), whereas `patchdiff-tx/1` encodes it as a standard JSON string (`162 B` MCP `arguments` JSON, `217 B` persisted record) and commits cleanly. Note that JSON string encoding eliminates `.pdcp` delimiter-line collisions while JSON syntax itself remains subject to protocol validation.
2. **Table 2 — Guarded Whole-Target Replacement (`patchdiff-tx/3`) Across All 5 Scenarios:**
   - Report all four byte representations separately so no two representations are conflated:

| `tx/3` Scenario | Raw Replacement Text (`UTF-8 B`) | MCP Tool `arguments` JSON (`UTF-8 B`) | Persisted Canonical `tx/3` Record (`UTF-8 B`) | Complete JSON-RPC `tools/call` Line (`UTF-8 B`, `id=1` + LF) | Oracle Verdict |
| :--- | ---: | ---: | ---: | ---: | :--- |
| `guarded whole-target rewrite` (`"old" -> "new"`) | `3 B` | `232 B` | `290 B` | `341 B` | `accepted` (`OK`) |
| `empty target` (`"" -> "new"`) | `3 B` | `232 B` | `290 B` | `341 B` | `accepted` (`OK`) |
| `empty replacement` (`"old" -> ""`) | `0 B` | `229 B` | `287 B` | `338 B` | `accepted` (`OK`) |
| `unicode, quotes, CRLF` (`'say "hi" \\\r\n🌟'`) | `16 B` raw (`15 B` LF-canonical) | `250 B` | `308 B` | `359 B` | `accepted` (`OK`) |
| `whole-target 2 KB rewrite` (40 lines, 39 `\n` chars) | `2,109 B` | `2,377 B` | `2,435 B` | `2,486 B` | `accepted` (`OK`) |

   - Explicitly note:
     - The complete JSON-RPC `tools/call` wrapper (`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"patchdiff_submit_replacement","arguments":...}}\n`) adds exactly **`109 B`** around the compact MCP `arguments` JSON (`341 - 232 = 109 B`, `2,486 - 2,377 = 109 B`).
     - In the 40-line 2 KB scenario (`2,109 B` raw text), JSON string encoding escapes each of the 39 newline characters (`0x0A`) as the 2-byte sequence `\n` (`+39 B`), yielding `2,109 + 39 + 229 = 2,377 B` for `arguments` and `2,377 + 109 = 2,486 B` for the complete `tools/call` line.

### 4.2 Local Performance Measurements (Near-Miss & PostgreSQL History Queries)

Present the repository's local performance measurements with full methodological context:
- **Test environment:** Windows 11, Python 3.11.9, PostgreSQL 16.3 (`postgres:16.3-alpine` on `127.0.0.1:5432`); 5-run local medians for near-miss scans (`SVC-001`) and 7-run local medians after warmup for PostgreSQL history/ledger queries (`MCP-001`), comparing internal PR #13 baseline vs. PR #14 (not cross-product external benchmarks).
- **Near-miss diagnostic scan (`backend/app/services/near_miss_service.py`):**
  - Varied prose fixture (`65,536` code points, `45`-code-point needle, threshold `4`): `100.2 ms` (`174,897` cells) -> **`1.7 ms`** 5-run local median (`585` comparison cells, **58.9× faster** vs. PR #13).
  - Repetitive structured log fixture (`65,536` code points, `45`-code-point needle, threshold `4`): `708.5 ms` (`1,000,000` cells, truncated at 69% of buffer) -> **`41.9 ms`** 5-run local median (`142,255` comparison cells, **16.9× faster** vs. PR #13 while scanning 100% of the eligible buffer).
  - State clearly that these are local fixture medians under the `MAX_COMPARISON_CELLS = 1,000,000` work budget, not a universal `< 42 ms` latency guarantee across all inputs or hardware.
- **Bounded PostgreSQL history & manifest ledger queries (`backend/app/mcp/tools.py`):**
  - `50 × 400 KB` (`20 MB` total) `patchdiff-tx/3` history: `279.6 ms` -> **`14.68 ms`** on `patchdiff_get_manifest_ledger(limit=50)` (**19.0× faster** vs. PR #13) and `372.4 ms` -> **`22.85 ms`** on `patchdiff_get_pdcp_log(limit=50)` (**16.3× faster** vs. PR #13) (7-run local medians after warmup).
  - `20 × 1 MB` (`20 MB` total) `patchdiff-tx/1` history (5 edits × 200 KB): `305.55 ms` -> **`136.72 ms`** on `patchdiff_get_pdcp_log(limit=50)` (**2.2× faster**), `305.55 ms` -> **`221.59 ms`** on `patchdiff_get_manifest_ledger(limit=50)` (**1.38× faster**), and `449.92 ms` -> **`445.33 ms`** on `patchdiff_get_manifest_ledger(limit=100)` (**1.01×**, at par) (7-run local medians after warmup).
  - State clearly that these measure server-side tool execution against local PostgreSQL, not end-to-end model + transport agent turns.

### 4.3 Analytical Workflow Examples & Proposed Live-Model Study (Decision A8: NOT RUN)

- Include clearly labeled **Analytical Examples** illustrating how multi-edit batching (`edits[]`) and explicit occurrence selection (`occurrence_index` / `anchor_before` / `tx/2` spans) affect request structure compared to single-edit or context-padded calls, with all assumptions stated and zero unmeasured empirical claims.
- Retain and refine the **Proposed Live-Model Comparative Evaluation Protocol (Status: NOT RUN)** specifying controlled requirements:
  - Identical model, system instructions, task corpus, and retry budgets across conditions.
  - Clearly specified host implementations for each compared edit method (`str_replace`, unified diff / `apply_patch`, PatchDIFF `tx/1..3`).
  - Actual tokenizer / API-reported input and output token counts (never byte-divided approximations).
  - First-attempt validity rate, final task success rate, recovery turns, and decomposed latency (model decoding vs. MCP transport vs. server execution).
  - Explicit rule: no comparative speedup or accuracy claim may be promoted to `README.md` until this study is executed and recorded.

---

## 5. `docs/MCP_TOOLS.md` Revision Plan — Normative Contract Accuracy

Keep `docs/MCP_TOOLS.md` strictly normative (no marketing comparisons) and verify/clarify the following exact behavioral rules:

1. **Units on Every Limit:**
   - `patchdiff_read_target`: `start` (0-based Unicode code-point offset), `length` (default `4,000` Unicode code points, max `8,000` Unicode code points).
   - `patchdiff_read_lines`: `start_line` / `end_line` (1-based line numbers), truncated at `8,000` Unicode code points (`truncated: true`, range-relative `next_offset` and absolute `next_start`).
   - `patchdiff_find_occurrences`: `context_chars` (`0..400` Unicode code points, default `40`), `max_results` (`1..200`, default `200`).
   - `patchdiff_submit_replacement` (`tx/3`): `MAX_REPLACEMENT_CHARS = 1,000,000` Unicode code points and `MAX_REPLACEMENT_BYTES = 1,048,576` UTF-8 bytes on both raw and canonical `replacement` text.
2. **Rejection Enrichment Byte Budget (`<= 18,432` Compact ASCII JSON Bytes):**
   - State accurately that the `18,432`-byte budget bounds the compact ASCII-escaped JSON serialization (`ensure_ascii=True, separators=(",", ":")`) of the newly added enrichment fields (`failure_context`, `current_context`, `exact_candidates` / `near_misses`, and `correlation_id`), with `failure_context` and `current_context` each bounded to `<= 4,096 B` (and combined wrapper `<= 8,192 B`) and `exact_candidates` or `near_misses` bounded to `<= 8,192 B`. It does not cap every top-level field of the entire rejection response envelope.
3. **Near-Miss & Ambiguity Candidate Field Names and Intermediate-Buffer Coordinates:**
   - Document exact candidate shapes:
     - `exact_candidates.candidates[]`: `{occurrence_index, start, end, before, match_preview, match_truncated, after}`.
     - `near_misses.candidates[]`: `{distance, start, end, text, before, after}` (uses `text`, not `matched_text`).
   - Document intermediate-buffer coordinate semantics: when `prior_changes > 0` (`buffer_stage = "intermediate_buffer"`), `failure_context`, `exact_candidates`, and `near_misses` report coordinates and occurrence indices against the **in-memory sequential buffer after the earlier simulated changes in that transaction**, not the persisted canonical target. Hosts must not blindly apply intermediate-buffer coordinates to a fresh single-edit transaction against the persisted target without accounting for the earlier changes.
   - Document near-miss omission reasons: `omission_reason` in `{"sequential_match_consumed", "caller_transaction", "historical_context_unavailable", "match_too_large", "work_budget_exhausted"}`.
4. **`patchdiff_preview` Advisory & Unreserved Semantics:**
   - Explicitly state that `patchdiff_preview` takes no `SELECT ... FOR UPDATE` row lock, writes no database rows, does not reserve `current_version` or `current_hash`, and re-checks all guards on subsequent `patchdiff_submit_edits` / `patchdiff_submit_replacement`.
5. **`patchdiff_get_pdcp_log` `include_content=True` Page Budget & First-Entry Exception:**
   - Document the exact behavior in `backend/app/mcp/tools.py` (`MAX_CONTENT_PAGE_BYTES = 1_048_576`): when `include_content=True`, the server tracks cumulative `octet_length(pdcp_content)` across the page. Because the check is `if not budget_used or budget_used + size <= 1_048_576`, the **first entry with non-empty content on the page is always returned whole** even if its `pdcp_content` exceeds `1,048,576` UTF-8 bytes; subsequent entries that would push `budget_used` past `1,048,576` bytes omit `pdcp_content` and set `pdcp_content_omitted: "page_byte_budget"`.

---

## 6. `docs/MODERNIZATION_ARCHITECTURE.md` Revision Plan — Historical Reconciliation

Preserve `docs/PatchDIFF-Concept-Paper-5.md` untouched as a historical design record, and **refine/expand the existing Section 1.1** in `docs/MODERNIZATION_ARCHITECTURE.md` (do not create a duplicate heading):

1. Add a concise **"Historical v0.2.3 Design vs. Current Implementation"** summary table at the top of Section 1.1:

| Historical v0.2.3 Concept Paper Design | Current Modernized Implementation (`patchdiff-tx/1..3` + Runtime `0.2.2`–`0.5.0`) |
| :--- | :--- |
| Text-delimited `.pdcp` v0.2.3 as the primary model-facing transaction format | Structured JSON transactions (`patchdiff-tx/1`, `tx/2`, `tx/3`); `.pdcp` v0.2.3 retained in [`docs/LEGACY_COMPATIBILITY.md`](../LEGACY_COMPATIBILITY.md) for backward compatibility and historical replay |
| 7 mandatory `# MANIFEST` prose fields per change block | Required top-level transaction `intent`, optional per-edit `rationale`, and server-derived `change_facts` (`span_start`, `span_end`, char counts, SHA-256 digests) |
| Server-mediated regeneration prompt/context workflow | Host-owned planning, reading, proposal, and retry loop over MCP |
| Match-only edit representation (`<<<<<<< MATCH` / `>>>>>>> REPLACE`) | Exact match (`tx/1`/`tx/2`), guarded `[start, end)` code-point spans with `expected_text` and adjacency checks (`tx/2`), and guarded whole-target replacement (`tx/3`) |
| Single-dimensional rejection reason without structured recovery slices | Stage-aware `ValidationStage`, bounded `failure_context` / `current_context`, `exact_candidates`, conditional `near_misses`, and read-only `patchdiff_preview` |
| Unkeyed submission retries | Durable idempotent outcome recovery via `(target_file_id, client_request_id)` |
| Single active runtime behavior | Versioned immutable replay profiles (`patchdiff-mvp-0.1.0` through `patchdiff-mvp-0.5.0`) dispatched per `(protocol_version, runtime_version)` |

2. Retain the **H1–H7 Concept Paper Hypotheses vs. Implemented Mechanisms** table right below it, clearly distinguishing:
   - What the historical v0.2.3 paper hypothesized (H1–H7),
   - Which historical v0.2.3 format limitations motivated the modernization,
   - Which deterministic runtime mechanism now implements each architectural goal, and
   - What is verified today (deterministic tests, `evaluation/offline_eval.py` byte counts, local benchmarks) vs. what remains a **comparative hypothesis (live-model evaluation: NOT RUN)**.

---

## 7. Cross-Document Source-of-Truth Map

Maintain a single authoritative source for each category of information and link rather than duplicate:

| Information Category | Primary Normative Source | Role of Other Documents |
| :--- | :--- | :--- |
| Product identity, balanced capability comparison, workflow, and runtime boundaries | [`README.md`](../../README.md) | Entry point for new visitors; links to deep-dive docs. |
| Offline byte accounting, local benchmark methodology, and live-model study design | [`evaluation/README.md`](../../evaluation/README.md) | Single home for full quantitative tables and benchmark context. |
| MCP tool schemas, request/response field names, units, and exact edge-case rules | [`docs/MCP_TOOLS.md`](../MCP_TOOLS.md) | Normative interface contract. |
| Architecture decisions (A1–A8), contracts (C1–C6), and Concept Paper reconciliation | [`docs/MODERNIZATION_ARCHITECTURE.md`](../MODERNIZATION_ARCHITECTURE.md) | Architectural authority. |
| Frozen `.pdcp` v0.2.3 syntax, `patchdiff_submit_pdcp`, deprecated wrappers, and old replay profiles | [`docs/LEGACY_COMPATIBILITY.md`](../LEGACY_COMPATIBILITY.md) | Single consolidated home for legacy compatibility; referenced via a single pointer elsewhere. |
| Host-owned loop, recovery patterns, and intermediate-buffer coordinate rules | [`docs/HOST_INTEGRATION_GUIDE.md`](../HOST_INTEGRATION_GUIDE.md) | Practical integration guidance for agent builders. |
| Conceptual design rationale, generalized `tx/1..3` formal model, edit-method tradeoffs, and research hypotheses (`H1`–`H7`) | [`docs/PatchDIFF-Concept-Paper-6.md`](../PatchDIFF-Concept-Paper-6.md) | Current conceptual whitepaper; supersedes untouched historical `docs/PatchDIFF-Concept-Paper-5.md`. Normative specs (`AGENTS.md`, `MCP_TOOLS.md`, `PATCHDIFF_CORE_SPEC.md`, `DATA_MODEL.md`, `PDCP_FORMAT.md`) remain authoritative for executable schemas and runtime limits. |

---

## 8. Verification & Release Gate

Before declaring the documentation revision complete:

1. Run `PYTHONPATH=backend python evaluation/offline_eval.py` and confirm every byte count in `README.md`, `evaluation/README.md`, `docs/PDCP_FORMAT.md`, and `docs/LEGACY_COMPATIBILITY.md` matches the script output (`151 B`, `206 B`, `259 B`, `314 B`, `232 B`, `290 B`, `341 B`, `2,109 B`, `2,377 B`, `2,435 B`, `2,486 B`, `162 B`, `217 B`).
2. Run the pure unit test suite (`pytest backend/tests/unit`).
3. Run the live PostgreSQL integration test suite (`pytest backend/tests/integration`), including real stdio MCP subprocess workflows.
4. Check all modified Markdown files for CRLF (`\r\n`) preservation, valid relative GitHub links, and absence of local-only file path citations.
5. Verify that `docs/PatchDIFF-Concept-Paper-5.md` and prior immutable review files in `docs/reviews/` are untouched.
6. Record a SHA-specific PR Review Standard v1.1.0 category review in `docs/reviews/` against the final head SHA.
