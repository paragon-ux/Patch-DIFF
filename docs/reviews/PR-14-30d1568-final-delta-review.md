# PR #14 Final Delta-Review Supplement (`586bc31` -> `30d1568`)

- **Review Standard:** [PR Review Standard v1.1.0](../PR_REVIEW_STANDARD.md) (especially §5 Commit-Pinned Evidence & Closure)
- **Repository / Branch:** `paragon-ux/Patch-DIFF` — `perf/pr13-deferred-p3` (PR [#14](https://github.com/paragon-ux/Patch-DIFF/pull/14))
- **Base Commit (`main`):** `d09fbc8422bbc22543b0b209c2f689b3e341e3b2` (`d09fbc8`)
- **Prior 10-Category Review HEAD:** `371192fbf934e0a1418d3e35c49eb0519cc39f39` (`371192f`), documented in [`docs/reviews/PR-14-371192f-final-category-review.md`](PR-14-371192f-final-category-review.md) (committed at `586bc316f26d0ba4e524febb436c65cfdcc8836a`)
- **Substantive Correction HEAD Reviewed:** `30d15688f72324cb9647a989d3974e15345689b7` (`30d1568`)
- **Reviewer:** Antigravity (Independent Final Delta Verification & Review Closure)
- **Date:** 2026-10-25
- **Overall Verdict:** **Approve (`0 P1 / 0 P2 / 0 P3` open findings)**

---

## 1. Scope & Relationship to Prior Review Records

This document is the authoritative **final delta-review supplement** for PR [#14](https://github.com/paragon-ux/Patch-DIFF/pull/14) at substantive commit [`30d15688f72324cb9647a989d3974e15345689b7`](https://github.com/paragon-ux/Patch-DIFF/commit/30d15688f72324cb9647a989d3974e15345689b7). It supplements—and preserves untouched—the full 10-category review [`docs/reviews/PR-14-371192f-final-category-review.md`](PR-14-371192f-final-category-review.md) and all earlier historical SHA-specific review records (`PR-14-bfbba27-category-review.md`, `PR-14-aa0c5d3-category-review.md`).

Between `586bc316f26d0ba4e524febb436c65cfdcc8836a` and `30d15688f72324cb9647a989d3974e15345689b7`, exactly three files changed (`3 files changed, 15 insertions(+), 7 deletions(-)`):

| Changed File in `586bc31..30d1568` | Primary Category | Bounded Change Summary |
| :--- | :--- | :--- |
| [`docs/PatchDIFF-Concept-Paper-6.md`](../PatchDIFF-Concept-Paper-6.md) | `DOC` | Corrected §4.2 payload accounting (`23 B` raw match/replace text vs. `69 B` compact UTF-8 JSON edit object) and §10.2 precondition guard stage mapping (`target_version_mismatch` and `target_hash_mismatch` both at `precondition_guard` with `null`/`null` validity; `target_diverged` separated as post-simulation `commit_guard` with `true`/`true` validity). |
| [`README.md`](../../README.md) | `DOC` | Separated traditional `diff -u` numeric `@@ -l,s +l,s @@` hunk-header arithmetic from OpenAI-style V4A `apply_patch` file-operation envelopes (`*** Update File:`) and contextual `@@` markers in §1. |
| [`backend/app/mcp/tools.py`](../../backend/app/mcp/tools.py) | `DB` / `MCP` | Added explanatory source comment and local constants `json_open_brace = "{"` / `json_close_brace = "}"` interpolated into `_attempt_meta_lateral` so the single-brace SQL literals `'{'` and `'}'` are self-evident without altering a single byte of emitted SQL. |

---

## 2. Category Impact Assessment (`586bc31..30d1568`)

In accordance with [PR Review Standard v1.1.0](../PR_REVIEW_STANDARD.md), the delta `586bc31..30d1568` affects the categories below as follows, while the prior review [`PR-14-371192f-final-category-review.md`](PR-14-371192f-final-category-review.md) continues to govern all remaining required categories (`SKILL`, `RUN`, `SVC`, `SCRIPT`, `DEP`):

- **`ARCH` (Architecture & System Boundaries):** **Assessed — No architectural boundary changes (`0 P1 / 0 P2 / 0 P3`, Verdict: Pass).** The documentation refinements in [`docs/PatchDIFF-Concept-Paper-6.md`](../PatchDIFF-Concept-Paper-6.md) and [`README.md`](../../README.md) align the paper's formal model and external comparisons with the existing runtime and service boundaries without modifying any runtime behavior.
- **`DOC` (Documentation & Protocol Specification Consistency):** **Assessed — 3 remnant P2 documentation inaccuracies resolved at `30d1568` (`0 P1 / 0 P2 / 0 P3` remaining, Verdict: Pass).** Fixed §10.2 hash-guard stage attribution, §4.2 69-byte compact edit object accounting, and `README.md` §1 `diff -u` vs. V4A `apply_patch` comparison.
- **`MCP` (MCP Transport & Tool Surface):** **Assessed — Non-functional source clarity edit only (`0 P1 / 0 P2 / 0 P3`, Verdict: Pass).** `_attempt_meta_lateral` in [`backend/app/mcp/tools.py`](../../backend/app/mcp/tools.py) interpolates `json_open_brace` and `json_close_brace` to make Python f-string brace escaping self-explanatory; compiled PostgreSQL SQL is verified byte-for-byte identical (`compiled_before == compiled_after`).
- **`DB` (Database, SQL & Persistence):** **Assessed — Non-functional SQL source clarity edit verified against live PostgreSQL (`0 P1 / 0 P2 / 0 P3`, Verdict: Pass).** The generated `LATERAL (... OFFSET 0)` SQL query, `head_slice` (`split_part(h.head, ',"operations":[', 1) || '}'`), and `tail_slice` (`regexp_replace(h.tail, '^.*,"format":"patchdiff-tx/1",', '{', 's')`) are unchanged and pass live PostgreSQL verification.
- **`TEST` (Test Coverage & Evaluation):** **Assessed — Existing unit, live PostgreSQL integration, and offline evaluator suites verified (`0 P1 / 0 P2 / 0 P3`, Verdict: Pass).** `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` (including `fast_path_tx3`), `test_friction_followup.py`, `test_pass_a_diagnostics.py`, and `evaluation/offline_eval.py` all pass at `30d1568`.
- **Remaining Required Categories (`SKILL`, `RUN`, `SVC`, `SCRIPT`, `DEP`):** Unchanged by `586bc31..30d1568`; full coverage statements, empty P1/P2/P3 buckets, and `Pass` verdicts in [`PR-14-371192f-final-category-review.md`](PR-14-371192f-final-category-review.md) remain in force.

---

## 3. Commit-Pinned Finding Records & Reviewer Closure

### Finding 1 — Concept Paper §10.2 Typed `expected_current_hash` Stage Mapping (`DOC`, P2)

- **Priority:** `P2`
- **Location:** [`docs/PatchDIFF-Concept-Paper-6.md#L230-L235`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/docs/PatchDIFF-Concept-Paper-6.md#L230-L235) (before: [`371192f/docs/PatchDIFF-Concept-Paper-6.md#L230-L235`](https://github.com/paragon-ux/Patch-DIFF/blob/371192fbf934e0a1418d3e35c49eb0519cc39f39/docs/PatchDIFF-Concept-Paper-6.md#L230-L235))
- **Expected vs. Actual Behavior:**
  - *Runtime Truth:* In [`backend/app/services/pdcp_service.py#L991-L1062`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/services/pdcp_service.py#L991-L1062) (`_guard_rejection`), when both `expected_target_version` and `expected_current_hash` are supplied, version is checked first ([`#L1040-L1050`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/services/pdcp_service.py#L1040-L1050)), followed by hash ([`#L1051-L1061`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/services/pdcp_service.py#L1051-L1061)). Both stale `expected_target_version` (`FailureReason.TARGET_VERSION_MISMATCH`) and stale `expected_current_hash` (`FailureReason.TARGET_HASH_MISMATCH`) reject at `ValidationStage.PRECONDITION_GUARD`, which [`backend/app/core/validity.py#L99-L106`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/core/validity.py#L99-L106) maps to `protocol_valid: None` (`null`) and `transaction_valid: None` (`null`). By contrast, `FailureReason.TARGET_DIVERGED` is a post-simulation check in [`backend/app/services/pdcp_service.py#L860-L894`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/services/pdcp_service.py#L860-L894) at `ValidationStage.COMMIT_GUARD`, which [`backend/app/core/validity.py#L120-L127`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/core/validity.py#L120-L127) maps to `protocol_valid: True` and `transaction_valid: True`.
  - *Prior Manuscript Defect (`371192f`):* §10.2 stated that $\neg\text{GuardOK}(\mathcal{S}, g_v, g_h)$ rejected with `target_hash_mismatch` at `transaction_applicability` and grouped `target_diverged` at `commit_guard` inside initial `GuardOK` failure.
- **Fix SHA:** [`30d15688f72324cb9647a989d3974e15345689b7`](https://github.com/paragon-ux/Patch-DIFF/commit/30d15688f72324cb9647a989d3974e15345689b7)
- **Verification Evidence & Closure:** Inspected [`docs/PatchDIFF-Concept-Paper-6.md#L234`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/docs/PatchDIFF-Concept-Paper-6.md#L234) and confirmed §10.2 now states version-first evaluation, `target_version_mismatch` and `target_hash_mismatch` at `precondition_guard` (`protocol_valid: null`, `transaction_valid: null`), and separates post-simulation `target_diverged` at `commit_guard` (`protocol_valid: true`, `transaction_valid: true`). The §15 validity table ([`#L337-L360`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/docs/PatchDIFF-Concept-Paper-6.md#L337-L360)) remains intact and consistent. **Status: Closed (Confirmed & Fixed at `30d1568`).**

---

### Finding 2 — Concept Paper §4.2 23-Byte vs. 69-Byte Edit Payload Accounting (`DOC`, P2)

- **Priority:** `P2`
- **Location:** [`docs/PatchDIFF-Concept-Paper-6.md#L86`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/docs/PatchDIFF-Concept-Paper-6.md#L86) (before: [`371192f/docs/PatchDIFF-Concept-Paper-6.md#L86`](https://github.com/paragon-ux/Patch-DIFF/blob/371192fbf934e0a1418d3e35c49eb0519cc39f39/docs/PatchDIFF-Concept-Paper-6.md#L86))
- **Expected vs. Actual Behavior:**
  - *Deterministic UTF-8 Accounting:* Raw match/replacement strings `"retry: false"` (`12 B`) and `"retry: true"` (`11 B`) total `23 B`, whereas the complete compact JSON edit object `{"match":"retry: false","replace":"retry: true","occurrence_index":2}` is `69 B` (`"match":"retry: false"` = `22 B`, `"replace":"retry: true"` = `23 B`, `"occurrence_index":2` = `20 B`, plus `4 B` for `{},`), excluding the top-level transaction envelope and MCP `tools/call` framing.
  - *Prior Manuscript Defect (`371192f`):* §4.2 wrote `(versus 23 B for "match":"retry: false","replace":"retry: true" plus "occurrence_index":2 in patchdiff-tx/1)`, conflating the `23 B` raw string length with the serialized edit object.
- **Fix SHA:** [`30d15688f72324cb9647a989d3974e15345689b7`](https://github.com/paragon-ux/Patch-DIFF/commit/30d15688f72324cb9647a989d3974e15345689b7)
- **Verification Evidence & Closure:** Inspected [`docs/PatchDIFF-Concept-Paper-6.md#L86`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/docs/PatchDIFF-Concept-Paper-6.md#L86) and verified in Python (`len('{"match":"retry: false","replace":"retry: true","occurrence_index":2}'.encode('utf-8')) == 69`) that both the `23 B` raw text figure and the `69 B` compact UTF-8 JSON edit object figure (along with the explicit `180 B` / `360 B` illustrative `str_replace` assumption and envelope boundary) are stated accurately. **Status: Closed (Confirmed & Fixed at `30d1568`).**

---

### Finding 3 — `README.md` §1 `diff -u` vs. V4A `apply_patch` Comparison (`DOC`, P2)

- **Priority:** `P2`
- **Location:** [`README.md#L22-L38`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/README.md#L22-L38) (before: [`371192f/README.md#L22-L38`](https://github.com/paragon-ux/Patch-DIFF/blob/371192fbf934e0a1418d3e35c49eb0519cc39f39/README.md#L22-L38))
- **Expected vs. Actual Behavior:**
  - *External Specification Distinction:* Traditional `diff -u` unified diffs require numeric `@@ -l,s +l,s @@` hunk-header counts, whereas OpenAI-style V4A `apply_patch` uses file-operation envelopes (`*** Begin Patch` / `*** Update File:`) and contextual `@@` markers without mandatory numeric hunk counts.
  - *Prior `README.md` Defect (`371192f`):* Grouped `apply_patch` under "Unified diff formatting" and attributed numeric `@@ -l,s +l,s @@` header arithmetic to the combined category in the §1 table (`#L28`), even though Concept Paper §4.1 ([`docs/PatchDIFF-Concept-Paper-6.md#L76-L81`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/docs/PatchDIFF-Concept-Paper-6.md#L76-L81)) already distinguished them.
- **Fix SHA:** [`30d15688f72324cb9647a989d3974e15345689b7`](https://github.com/paragon-ux/Patch-DIFF/commit/30d15688f72324cb9647a989d3974e15345689b7)
- **Verification Evidence & Closure:** Inspected [`README.md#L22-L38`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/README.md#L22-L38) and confirmed that row 3 of the §1 table (`#L28`) and the comparative bullet (`#L38`) explicitly distinguish `diff -u` numeric hunk headers from V4A `apply_patch` file-operation envelopes and contextual `@@` markers while preserving PatchDIFF's structured JSON, version/hash guard, per-target PostgreSQL atomicity, and audit/retry advantages. **Status: Closed (Confirmed & Fixed at `30d1568`).**

---

### Finding 4 — `_attempt_meta_lateral` f-String SQL Closing Brace Clarity (`DB` / `MCP`, P3 — False Positive Clarified in Source)

- **Priority:** `P3` (Explanatory source clarification of repeated external false positive)
- **Location:** [`backend/app/mcp/tools.py#L712-L792`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/mcp/tools.py#L712-L792) (specifically [`#L717-L725`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/mcp/tools.py#L717-L725) and [`#L761-L764`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/mcp/tools.py#L761-L764))
- **Expected vs. Actual Behavior:**
  - *Runtime Truth:* `_attempt_meta_lateral` builds its SQL inside a Python f-string (`text(f'''...''')`). In the prior revision ([`371192f/backend/app/mcp/tools.py#L754`](https://github.com/paragon-ux/Patch-DIFF/blob/371192fbf934e0a1418d3e35c49eb0519cc39f39/backend/app/mcp/tools.py#L754)), `'}}'` was valid Python f-string escaping that emitted a single `'}'` in PostgreSQL SQL (`split_part(h.head, ',"operations":[', 1) || '}' AS head_slice`). Automated reviewers repeatedly misread the Python f-string source token `'}}'` as a two-brace SQL literal.
  - *Explanatory Source Edit (`30d1568`):* Defined local constants `json_open_brace = "{"` and `json_close_brace = "}"` with an adjacent explanatory comment ([`#L717-L724`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/mcp/tools.py#L717-L724)) and interpolated `{json_close_brace}` / `{json_open_brace}` at [`#L762-L764`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/mcp/tools.py#L762-L764).
- **Fix SHA:** [`30d15688f72324cb9647a989d3974e15345689b7`](https://github.com/paragon-ux/Patch-DIFF/commit/30d15688f72324cb9647a989d3974e15345689b7)
- **Verification Evidence & Closure:**
  1. Verified via SQLAlchemy PostgreSQL dialect compilation (`stmt.compile(dialect=postgresql.dialect())`) that `compiled_before == compiled_after` byte-for-byte, emitting:
     - `split_part(h.head, ',"operations":[', 1) || '}' AS head_slice`
     - `regexp_replace(h.tail, '^.*,"format":"patchdiff-tx/1",', '{', 's') AS tail_slice`
  2. Verified against live PostgreSQL 16 via `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` in [`backend/tests/integration/test_friction_followup_live.py#L368-L543`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/tests/integration/test_friction_followup_live.py#L368-L543) (including the `fast_path_tx3` regression assertion at [`#L523-L543`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/tests/integration/test_friction_followup_live.py#L523-L543), which proves a `> 64 KB` `patchdiff-tx/3` record whose body after `,"operations":[` is invalid JSON extracts `intent == "tx3-head-slice-fast-path"` via the 4 KB `head_slice` fast path).
  - **Status: Closed (False Positive — Correct f-string escaping; made self-explanatory in source at `30d1568`).**

---

### Finding 5 — Previously Resolved Items (Immutable Citation Index, Do Not Reopen)

1. **`SVC-001` Near-Miss Positional Pigeonhole Filter & Landau–Vishkin Diagonal-Wave DP:**
   - Implementation: [`backend/app/services/near_miss_service.py#L10-L108`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/services/near_miss_service.py#L10-L108) (`_candidate_starts`) and [`backend/app/services/near_miss_service.py#L110-L169`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/services/near_miss_service.py#L110-L169) (`_window_distances`, using 8-code-point slice comparisons at [`#L120-L123`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/services/near_miss_service.py#L120-L123) and [`#L154-L160`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/app/services/near_miss_service.py#L154-L160)).
   - Verification Tests: [`backend/tests/unit/test_friction_followup.py#L265-L382`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/tests/unit/test_friction_followup.py#L265-L382) (`test_bag_pruned_full_buffer_scan_equals_unpruned_reference` at [`#L265-L298`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/tests/unit/test_friction_followup.py#L265-L298), `test_repetitive_64k_buffer_scans_to_end_within_work_bound` at [`#L300-L315`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/tests/unit/test_friction_followup.py#L300-L315), `test_candidate_starts_strict_path_and_loop2_and_leading_insertion_exactness` at [`#L317-L363`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/tests/unit/test_friction_followup.py#L317-L363), and `test_near_misses_cell_cap_boundary_stops_cleanly` at [`#L365-L382`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/backend/tests/unit/test_friction_followup.py#L365-L382)).
   - Evaluation Documentation: [`evaluation/README.md#L70-L80`](https://github.com/paragon-ux/Patch-DIFF/blob/30d15688f72324cb9647a989d3974e15345689b7/evaluation/README.md#L70-L80) (reporting `120` seeded differential trials + `150` randomized multi-edit cases).
2. **`DB` / `SCRIPT` Category Coverage & PR Description `os.path.commonprefix` Wording:**
   - Resolved in [`docs/reviews/PR-14-371192f-final-category-review.md`](PR-14-371192f-final-category-review.md) and in the PR [#14](https://github.com/paragon-ux/Patch-DIFF/pull/14) description.

---

## 4. Verification Summary at `30d15688f72324cb9647a989d3974e15345689b7`

1. **Source Inspection & Byte-for-Byte SQL Equivalence:**
   - Verified `compiled_before == compiled_after` on `_attempt_meta_lateral` under `postgresql.dialect()`.
   - Verified `0` bare LF bytes and `0` broken relative links across `docs/PatchDIFF-Concept-Paper-6.md`, `README.md`, `backend/app/mcp/tools.py`, and `docs/reviews/PR-14-30d1568-final-delta-review.md`.
2. **Local Execution Evidence:**
   - `PYTHONPATH=backend python evaluation/offline_eval.py`: **Exit 0** (`Verdict equivalence on the shared applier: OK`, `Accepted guarded replacement content/hash oracles: OK`).
   - Targeted unit and live-PostgreSQL suite (`pytest backend/tests/integration/test_friction_followup_live.py backend/tests/unit/test_friction_followup.py backend/tests/unit/test_pass_a_diagnostics.py -q`): **`85 passed`** (`0 failed`, `0 skipped`).
3. **Final Verdict:** **Approve (`0 P1 / 0 P2 / 0 P3` open findings).**
