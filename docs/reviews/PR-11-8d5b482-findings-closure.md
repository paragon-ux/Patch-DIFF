# PR #11 Findings Closure — fix commit `8d5b482`

Predecessor review: [PR-11-0f83855-category-review.md](PR-11-0f83855-category-review.md) (head `0f838557b17d32139d25d429a9c563cdb9025ca6`, PR Review Standard v1.1.0).

| Field | Value |
| --- | --- |
| PR | [paragon-ux/Patch-DIFF#11](https://github.com/paragon-ux/Patch-DIFF/pull/11) |
| Fix commit | `8d5b482` — "fix: close PR #11 review findings" (parent `8949392`, which records the review) |
| Recheck date | 2026-10-22 |
| Reviewer recheck | Claude (Opus 5.5), the author of the predecessor review |
| Scope of delta | 17 files: 2 runtime/service, 2 unit-test, 9 active docs, `AGENTS.md`, `README.md`, 4 skills. No schema, migration, persisted-format or fingerprint change. |

## Recheck evidence (local, this revision)

| Evidence | Result |
| --- | --- |
| Full pytest, fresh isolated PostgreSQL DB at Alembic head | **757 unit + 389 integration passed**, 0 failed/errored/skipped. Unit count is +2 from 755: one obsolete test replaced, three added. |
| Independent live stdio harness ([PR-11-0f83855-live-verify.py](PR-11-0f83855-live-verify.py), unchanged), fresh DB | **136/136** checks passed ([PR-11-8d5b482-live-results.json](PR-11-8d5b482-live-results.json)); the predecessor run was 135/136 |
| `evaluation/offline_eval.py` | exit 0; verdict equivalence OK; five tx/3 oracles OK |
| Word/numeral spacing scan over 23 active docs and skills | 0 hits; the same files had 126 before the fix |
| Verbatim-duplicate scan (paragraphs over 120 characters) | The 10 PR-introduced duplicates are removed. Four short pre-existing cross-reference and invariant lines remain, intentionally. |

CI on the pushed head is recorded by the merge step. It is not claimed here.

## Finding closure

| ID | Priority | Fix | Evidence at `8d5b482` | Recheck | Residual |
| --- | --- | --- | --- | --- | --- |
| MCP-001 | P3 | `patchdiff_submit_operations` description is built from `OPERATIONS_RUNTIME_VERSION` and now reads "runtime patchdiff-mvp-0.3.0" | Live `tools/list` check passes; unit `test_capability_metadata_and_descriptions_derive_from_runtime_constants` also rejects any `runtime\d` / `immutable\d` / `profile\d` glue in descriptions | Closed | None |
| MCP-002 | P3 | Replacement description and `x-patchdiff-capabilities` use `REPLACEMENT_PROTOCOL_VERSION`, `REPLACEMENT_RUNTIME_VERSION`, `MAX_REPLACEMENT_CHARS` and `MAX_REPLACEMENT_BYTES` | Same unit test asserts equality with the constants | Closed | None |
| SVC-001 | P3 | `near_miss_service` uses an exact Ukkonen-banded DP. Cells farther than the threshold from the diagonal are capped at threshold+1 and never evaluated, and one row per start serves all three window widths. The PASS-A contract (windows, threshold, ranking, 1,000,000-cell cap, omissions) is unchanged; only `comparison_cells` counts fewer cells. | `test_banded_ranking_equals_unbanded_reference`: 300 seeded random cases, identical ranked candidates and truncation versus the unbanded reference. `test_full_prefix_64_point_query_is_served_within_budget`: 64-point typo over a full prefix is computed, distance 1, ≤ 147,456 cells. Live: query lengths 20/30/38/40/48/64 all `computed` with 3 candidates, 0.07–0.19 s per call; the predecessor run omitted 40/48/64 after ~0.5 s. The MAX=0 exhaustion tests still pass. | Closed | Near misses still search only the first 256 code points (documented by design) |
| SVC-002 | P3 (advisory) | Chose the documentation remediation: MCP_TOOLS replacement section, DATA_MODEL storage section and the persistence skill state that key-conflict audit rows keep the complete submitted record regardless of fresh limits, as tx/1 and tx/2 attempts always do | Source reconciliation. Behavior is unchanged and covered by the existing `test_existing_key_outcome_and_conflict_precede_stricter_fresh_limits_and_replay_bypasses_them` | Closed | No size bound on audit evidence for any format; this is an explicit, documented property |
| DOC-001 | P3 | One normative "Guarded editing, reads, preview and diagnostics" section in MCP_TOOLS. HOST guide, architecture, core spec, data model and PDCP format docs carry layer-specific summaries that link to it. Spacing restored across all active docs, including older glue in C4/C6 and the history sections. | Spacing scan 0 hits; duplicate scan clean for PR-introduced text; all stated limits re-checked against code constants | Closed | Historical records under `docs/usability/**` and `docs/reviews/**` are intentionally unchanged to preserve provenance and hashes |
| DOC-002 | P3 | AGENTS.md item 3 and README item 3 describe the change record as "current product change record: formats, compatibility and verification scope". The architecture Layer 1/2 rows name where A1–A8, C1–C6 and E1–E8 live and list `docs/usability/**`, including the archived as-built record, and `docs/reviews/*` as preserved records. | Source reconciliation | Closed | None |
| ARCH-001 | P3 | The AGENTS.md heading, boundary block and "None of … is executable code" sentence name tx/1, tx/2, tx/3 and `.pdcp`. The host workflow names `read_lines`, `preview`, operations and replacement. | Source reconciliation | Closed | None |
| SKILL-001 | P3 | Each skill has one layer-specific "Goal F additions" section; "no replace_all yet" is removed; the core-runtime capability list and intro include tx/3 | Identifier check plus source reconciliation | Closed | None |

## Category re-review of the delta

- **RUN:** No change.
- **SVC:** Near-miss algorithm change rechecked for exactness. Values outside the band are clamped at threshold+1. Clamped recurrences preserve `min(D, threshold+1)`, so every reported distance ≤ threshold equals the true Levenshtein distance. No persistence, lock or ordering change.
- **MCP:** Description and metadata text change only; schemas and examples are unchanged (live schema/example validation passes).
- **TEST:** One test encoded the old exhaustion behavior and was replaced. It now uses a stronger reference-equivalence property test plus a served-budget test, and exhaustion is still covered under a monkeypatched cap.
- **DOC / ARCH / SKILL:** Normative content was preserved and consolidated. No contract was weakened. The near-miss contract gains the banded-cell statement.
- **DB / DEP / SCRIPT:** Not affected.

**Disposition:** All eight predecessor findings are closed with fix commit, evidence and reviewer recheck. No new findings. The PR remains subject to CI on the pushed head and to the owner-requested friction review before merge.
