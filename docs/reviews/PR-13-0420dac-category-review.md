# PR #13 Category Review — Fix PR #11 friction findings FR-1..FR-20

## 1. Review metadata and evidence limits

| Field | Value |
| --- | --- |
| Repository | `paragon-ux/Patch-DIFF` |
| PR | [paragon-ux/Patch-DIFF#13](https://github.com/paragon-ux/Patch-DIFF/pull/13) — "Fix PR #11 friction findings FR-1..FR-20" |
| Review date | 2026-10-22 |
| Reviewer | Claude (Opus 5.5) via Claude Code; the same session that authored the change (self-review, see limits) |
| Standard | [PR Review Standard v1.1.0](../PR_REVIEW_STANDARD.md) |
| Base SHA | `16ce338e0ed251a7bbfc372f29db916e966e1388` (`main`; merge-base equals base) |
| Reviewed head SHA | `0420dac3402f098dae765445abe09b65ad053d3a` (`fix/pr11-friction-followup`) |
| Diff | 57 files, +2,659 / −354 (commits `d121d55` code and tests, `0420dac` documentation) |
| Later commits | The review/evidence commit that adds this file, the live harness and its results, and the friction re-test commit are documentation-only. They do not change the reviewed product files. |

**Evidence actually used**

- Source inspection of every changed runtime, service, MCP, migration, test, skill and active-doc file at `0420dac`, against base `16ce338`.
- The [PR #11 friction review](PR-11-d68c77d-friction-review.md), which defines FR-1..FR-20, and the triage and decision record [friction-followup-decision.md](../usability/friction-followup-decision.md). The decision record was written before the implementation.
- Local execution: Windows 11, Python 3.11.9, SQLAlchemy 2.0.49, Alembic 1.18.4, psycopg 3.3.4, PostgreSQL 16.3 (`postgres:16.3-alpine`). Each run used a fresh, uniquely named database:
  - Full pytest at `0420dac` on `patchdiff_frfu_full2`.
  - Alembic CLI `upgrade head → downgrade -1 → upgrade head` on `patchdiff_frfu_mig`.
  - `evaluation/offline_eval.py`.
  - The unchanged PR #11 harness [PR-11-0f83855-live-verify.py](PR-11-0f83855-live-verify.py) on `patchdiff_frfu_live0`.
  - An adapted copy, [PR-13-0420dac-live-verify.py](PR-13-0420dac-live-verify.py), on `patchdiff_frfu_live2`. It drives a real stdio subprocess (`python -m app.mcp.external_adapter`, inherited `PYTHONIOENCODING=cp1252`) with independent `psql` assertions. Results: [PR-13-0420dac-live-results.json](PR-13-0420dac-live-results.json).
  - A mechanical documentation scan of active docs and skills: word/numeral spacing, verbatim duplicated paragraphs, and local links and anchors.

**Limits**

- Self-review: the reviewer also wrote the change. An independent friction re-test by a separate agent with its own database is part of this PR's closing workflow. It is recorded separately and its claims are checked before merge.
- CI had not finished when this review was written. CI evidence for the PR head and its generated merge commit is recorded in the closing PR comment.
- No external MCP host session (Claude Desktop or Gemini CLI) was run, and no representative production workload was measured.
- The original design paper was not re-read. This change keeps the exact-match, sequential and atomic thesis, and execution confirmed it (§3).

## 2. File-to-category inventory and coverage matrix

| Category | Primary files (count) | Coverage |
| --- | --- | --- |
| ARCH | `AGENTS.md`, `docs/MODERNIZATION_ARCHITECTURE.md`, `docs/PATCHDIFF_CORE_SPEC.md`, `docs/usability/friction-followup-decision.md` (4) | Complete |
| DOC | `README.md`, `CHANGELOG.md`, `docs/HOST_INTEGRATION_GUIDE.md`, `docs/MODERNIZATION_CHANGE_DOC.md`, `docs/MCP_FIRST_MVP.md`, `docs/CODEX_BUILD_PLAN.md`, `docs/CLAUDE_DESKTOP_SETUP.md`, `docs/RELEASE_READINESS.md` (8) | Complete |
| SKILL | `.agents/skills/*/SKILL.md` (4) | Complete |
| MCP | `backend/app/mcp/external_adapter.py`, `backend/app/mcp/tools.py`, `docs/MCP_TOOLS.md` (3) | Complete |
| RUN | `backend/app/core/{advisories,diagnostics,failures,line_endings,result,versions}.py`, `backend/app/pdcp/{applier,models,operations,replacement,typed}.py`, `docs/PDCP_FORMAT.md` (12) | Complete |
| SVC | `backend/app/services/{export_service,near_miss_service,pdcp_service,preview_evidence,read_service,rejection_context,save_service,target_service}.py` (8) | Complete |
| DB | `backend/app/migrations/versions/20261022_0003_source_line_endings.py`, `backend/app/storage/models.py`, `backend/app/services/replay_service.py`, `docs/DATA_MODEL.md` (4) | Complete |
| SCRIPT | None changed at the reviewed head (0) | Dependencies examined: `evaluation/offline_eval.py` (executed) and the PR #11 harness (executed unchanged) |
| TEST | 8 integration and 5 unit test files under `backend/tests/`, plus `docs/TEST_MATRIX.md` (14) | Complete |
| DEP | None changed (0) | Not applicable: no dependency, lockfile, packaging or configuration change |

Unchanged dependencies examined:

- `backend/app/core/canonicalization.py`: CRLF/CR → LF only, no BOM stripping, so `original_eol` restores uniform sources byte for byte.
- `backend/app/pdcp/typed.py`: `_CLIENT_REQUEST_ID_RE`.
- `backend/app/pdcp/disambiguation.py`: selector resolution, which is unchanged.
- `replay_service.replay_target`: it replays accepted rows only, so rejected-row `failure_detail` and diagnostic changes cannot break the replay of history.
- `read_service` history limits: default 50, maximum 200.

## 3. Architecture-to-implementation trace

| Invariant / decision | Contract | Implementation | Verification |
| --- | --- | --- | --- |
| Exact deterministic MATCH; no fuzzy application | AGENTS.md invariants; D6/D7 (near misses response-only) | Matching unchanged. The wider near-miss scan uses `RejectedCoreResult.near_miss_buffer`, a bounded copy of at most 65,536 code points that is passed only to the response and never persisted. | Live: near misses absent from `diagnostic_json` (SQL); a typo at offset 549, beyond the 256-code-point stored prefix, is found with `scan_source: failing_buffer`; candidates are disjoint. Unit: the bag-pruned full-buffer scan equals the unpruned reference ranking (`test_bag_pruned_full_buffer_scan_equals_unpruned_reference`). |
| Immutable runtime profiles; replay dispatch on (protocol, runtime) | Architecture A-series; D2 | New `patchdiff-mvp-0.5.0` profile `(overlap, singleton, spans, no replace_all, span_context)`. `operations_runtime_version(record)` selects it only when a span carries `expected_before`/`expected_after`. Replay passes `allow_span_context=profile.span_context`. | Live SQL: context-guarded tx/2 → `0.5.0`, plain tx/2 → `0.3.0`; replay success over both. Unit: `0.3.0` decode still rejects context keys; records without context are byte-identical to base. |
| Request identity unchanged | C4; D10 decline | The fingerprint excludes `runtime_version`. Conflict comparison (`_conflict_evidence`) is advisory and read-only. | Live: exact-key recovery after later edits; conflicts report `differing_components`/`differing_fields`; recorded `failure_detail` text kept. |
| Canonical LF storage and hashes | Core spec; D3 | `source_line_endings` is computed from the raw upload before canonicalization and stored in a new nullable column. Export transforms only the response text; `current_hash` stays canonical. | Live: CRLF upload → `original_eol` export with `content_sha256 == source_sha256`; mixed → `original_eol_unrecoverable`; null facts → `source_line_endings_unknown`. Migration tests: populated `0002 → 0003 → 0002 → 0003` and downgrade refusal. |
| Append-only attempt log; accepted-only ledger | C3/C4 | Warnings are stored in the accepted row's `diagnostic_json` only when present; rows without warnings keep NULL. The ledger join is read-only. | Live SQL: envelope stored for a warned row; NULL for a plain row; replay adds no rows. |
| Stage-accurate validity | Core spec `ValidationStage` | Span context checks run in the applier (transaction stage), after the existing `expected_text` check. Guard→decode→apply order unchanged. | Live: context mismatch → `span_expected_text_mismatch`, `protocol_valid: true`, `transaction_valid: false`. |
| Host-owned retry | C5; D4 | `RETRYABLE_FAILURE_REASONS` is the single advisory set; `failure_reason` values are unchanged. | Live: `match_absent`, `target_version_mismatch` and `span_expected_text_mismatch` are retryable; a PDCP protocol failure is not. |
| SAVE checkpointing | C6; FR-20 | Optional `expected_target_version`, checked with the hash guard before any snapshot. | Live: stale or invalid guard → no new `target_snapshots` row; matching guards → saved. |

All intentional departures from base behaviour are recorded in the decision document (D1–D14) with their compatibility effects. No higher-priority contract was changed silently.

## 4. Category sections

### ARCH — Architecture and contracts

- **Scope:** the four ARCH files; AGENTS.md invariants and the transaction-format boundary; decisions D1–D14.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** Source reconciliation of each decision against its implementation (§3). The `0.5.0` profile row exists in the architecture runtime table, and the C5b contract describes context guards. AGENTS.md names the new runtime without changing the locked invariants. Every compatibility claim in the decision record (no `failure_reason` change, no fingerprint change, `0.3.0` untouched, migration refusal rule) is backed by a test or a live check.
- **Verdict:** No findings within reviewed scope.

### DOC — Documentation and change records

- **Scope:** the eight DOC files, plus the normative sections they link to in MCP_TOOLS and the core spec.
- **Coverage:** Complete for active documents. Historical records under `docs/usability/**` and `docs/reviews/**` are unchanged except for new files.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:**
  - Mechanical scan of all active docs and skills against base. Word/numeral gluing: 0 real hits; the 3 tokens flagged are two advisory IDs in unchanged `SECURITY.md` and "UUIDv4". Verbatim duplicated paragraphs introduced: 0. Broken local links or anchors: 0.
  - The guide's discovery sequence is a numbered list. Its example UUIDs use the `…-4111-8111-…` form. The remedy table has rows for `request_key_conflict` and `invalid_client_request_id`. §8 "Round-tripping to files" documents `original_eol`.
  - CHANGELOG has an "Unreleased — PR #11 friction follow-up" section that lists the compatibility notes.
- **Verdict:** No findings within reviewed scope.

### SKILL — Skills and agent instructions

- **Scope:** four `SKILL.md` files.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** Every field, enum, runtime and code the skills mention exists in code at `0420dac`. This covers `expected_before`/`expected_after`, `patchdiff-mvp-0.5.0`, `source_line_endings`, the four export formats, `RETRYABLE_FAILURE_REASONS`, `warning_details`, `request_key_conflict`, migration `20261022_0003` and its downgrade refusal.
- **Verdict:** No findings within reviewed scope.

### MCP — MCP schemas and public API

- **Scope:** `external_adapter.py` (descriptions, parameter descriptions, argument errors, wire encoding, capabilities), `tools.py` (response payloads, history and ledger reads), `docs/MCP_TOOLS.md`.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:**
  - **MCP-001 — Ledger pages now load and JSON-decode the stored record of every attempt on the page.** Priority P3 (advisory). Status: open; proposed as a follow-up.
    - Provenance: FR-11 / decision "Joinable audit trail" (read-side join).
    - Evidence: [tools.py:477-491](https://github.com/paragon-ux/Patch-DIFF/blob/0420dac3402f098dae765445abe09b65ad053d3a/backend/app/mcp/tools.py#L477-L491) selects `pdcp_content` for the distinct logs on a ledger page and calls `_decoded_record`, which runs `json.loads`, to read `intent` and per-edit `rationale`. [tools.py:386](https://github.com/paragon-ux/Patch-DIFF/blob/0420dac3402f098dae765445abe09b65ad053d3a/backend/app/mcp/tools.py#L386) decodes each attempt row's record for the bounded `intent`.
    - Trigger: a ledger page (up to 200 rows) over a history of large typed records, for example tx/3 whole-document replacements near 1,000,000 code points.
    - Expected / actual: the response stays small; only bounded fields are returned. The server, however, transfers and parses each full record. Before this PR, ledger reads did not touch `pdcp_content`. Attempt-log reads already loaded full ORM rows, so for them only the parse is new. This is source-derived; no slow call was observed in the live run.
    - Impact: memory and CPU per ledger call grow with record size × page size. The cost is bounded by the existing 200-row page cap and is the same as the cost `get_pdcp_log` already pays. Correctness is unaffected.
    - Remediation: extract `intent` and `rationale` without transferring whole records, for example with a guarded SQL JSON extraction or a stored summary column added by a later migration. Acceptance: a ledger page over large tx/3 rows returns the same fields without selecting `pdcp_content`.
- **Verification:**
  - Live stdio: every top-level parameter of all 20 tools has a description. Submission descriptions repeat the guard rule, and read, search and submit descriptions state code-point offsets. `x-patchdiff-capabilities.span_context` names `0.5.0`, and the export `format` enum has four values. `tools/list` is 34,401 compact bytes, within the 65,536 budget, and all 13 schema examples validate.
  - Unknown or missing arguments return structured `invalid_argument` JSON with `isError: true`. Tool text carries literal UTF-8 even with `PYTHONIOENCODING=cp1252`, and the lone-surrogate path still falls back to ASCII escaping without crashing.
- **Verdict:** No blocking findings; one advisory P3.

### RUN — Core runtime, parsing and validation

- **Scope:** the twelve RUN files.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:**
  - `_basis_shift` maps a sequential selection back through earlier change facts in reverse. A position inside an earlier replacement maps to "produced by earlier changes". The mapping was checked against the live case `cat dog cat dog cat`, where `occurrence_index: 2` after one edit is reported as transaction-start index 3, and against unit cases for copied `find_occurrences` indexes and for sequential indexes that are still reported.
  - Context guards compare exact adjacent text after canonicalization. Empty strings are refused at parse. The CRLF guard `beta\r\n` matched canonical `beta\n` live.
  - Warnings are collected only when `collect_warnings=True`; replay passes `False`.
  - `_span_evidence` returns target text only, at most 64 code points, with the tail used for `expected_before`.
  - `sequential_match_invalid` names the consuming change. Detail text for `prior_changes == 0` is byte-identical to base, which the live check of the PR #11 ambiguity case confirms.
- **Verdict:** No findings within reviewed scope.

### SVC — Services, orchestration and audit semantics

- **Scope:** the eight SVC files.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:**
  - Near-miss ranking:
    - Bag-distance pruning is a valid lower bound (`missing − 1` covers the one-longer window).
    - Ukkonen banding stays exact for distances up to the threshold.
    - A budget stop keeps the ranking computed so far and reports `scanned_end`; `work_budget_exhausted` is returned only when no start was evaluated.
    - Greedy selection guarantees disjoint locations.
    - In the live length probe (20–64 code points), all lengths returned computed candidates in at most 0.13 s. Under PR #11, lengths of 40 and above were omitted.
  - `runtime_version` is threaded through every persistence path, so rejected rows of a context-guarded tx/2 also record `0.5.0`. Live SQL shows both context-mismatch rejections, the acceptance and the empty-context `manifest_invalid` rejection on `0.5.0`.
  - The key-validation `except` covers only `validate_client_request_id`, so `invalid_client_request_id` cannot label other protocol failures.
  - `response_current_context` elides only key-for-key equality. A focused failure window therefore keeps a distinct prefix `current_context`, as D8 specifies (live check).
  - SAVE checks both guards before creating a snapshot.
- **Verdict:** No findings within reviewed scope.

### DB — Database, migrations, replay and concurrency

- **Scope:** migration `20261022_0003`, `CloudTargetFiles.source_line_endings`, the replay profile flag, `docs/DATA_MODEL.md`.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:**
  - The column is nullable JSONB, and existing targets keep NULL ("unknown"); no backfill is claimed.
  - Downgrade raises `Cannot downgrade 20261022_0003: recorded source line endings exist` while any non-null row exists, then drops the column when none do.
  - Live tests:
    - populated legacy data `0002 → 0003 → 0002 → 0003`, with targets, logs and ledger preserved;
    - refusal with recorded rows;
    - the existing `0001`/`0002` roundtrips, with seeding now done through reflected tables so that the new column cannot break older revisions.
  - Offline SQL rendering is tested, and the CLI cycle `upgrade head → downgrade -1 → upgrade head` passes on a fresh database.
  - Replay of `0.5.0`, `0.3.0`, `0.4.0` and `0.2.2` rows succeeds live. Locking is unchanged: the PR #11 two-session lock check still passes in the adapted harness.
- **Verdict:** No findings within reviewed scope.

### SCRIPT — Scripts, evaluation and developer tooling

- **Scope:** no changed files at the reviewed head. Examined: `evaluation/offline_eval.py`, the PR #11 harness, and the new harness copy added with this review.
- **Coverage:** Complete for the examined dependencies.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** `offline_eval.py` exits 0 ("Verdict equivalence on the shared applier: OK"; "Accepted guarded replacement content/hash oracles: OK"). The new harness records every check, exits non-zero on any failure, and was run against a fresh database. Its two adapted PR #11 checks name the decision that changed them (FR-6, FR-8).
- **Verdict:** Not applicable to changed files; no findings in the examined dependencies.

### TEST — Tests and CI

- **Scope:** 13 changed test files and `docs/TEST_MATRIX.md`.
- **Coverage:** Complete for local execution. CI is pending at the time of writing.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:**
  - Full suite at `0420dac`: **1,220 passed = 811 unit + 409 live-PostgreSQL integration**, 0 failed, errored or skipped, in 147 s. The 20 warnings are existing Alembic and Starlette deprecation notices.
  - Inspected assertions in the new tests: DB row counts and runtime columns, stored `diagnostic_json`, target content and version, migration column presence and data preservation, and real stdio response bytes, in addition to returned status.
  - Existing tests changed only where behaviour changed by decision: near misses limited to `match_absent`, the structured unknown-argument error, the 0003 head, and distinct near-miss locations.
  - Independent live run: 230/230 checks, of which 94 target FR-1..FR-20. Every finding has at least one live check, except FR-16, which is documentation-only and checked by source reconciliation and the schema-example checks.
- **Gaps (not defects):**
  - `target_diverged` retryability is covered by unit tests only.
  - No external MCP host session was run.
  - CI results for the PR head and merge commit are recorded at closing.
- **Verdict:** No findings within reviewed scope.

### DEP — Dependencies, packaging and configuration

- **Scope:** no changed files.
- **Coverage:** Not applicable.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** The new migration ships under the existing `app/migrations/versions` package path, so no packaging change is needed. Tests ran in the existing lock-based venv.
- **Verdict:** Not applicable (no dependency or configuration change).

## 5. Cross-category root causes and remediation order

There is no shared defect. MCP-001 comes from serving FR-11's join from the stored record, the only place where transaction intent and per-edit rationale exist today. Making the join cheap needs either SQL-side extraction or a stored summary, and a summary would need a migration. It is advisory, so it is deferred to a follow-up rather than added to this batch.

## 6. Verification record and remaining gaps

| Evidence | Revision | Environment | Result |
| --- | --- | --- | --- |
| Full pytest (local) | `0420dac` | Win 11, Py 3.11.9, PG 16.3, DB `patchdiff_frfu_full2` | 811 unit + 409 integration passed |
| Alembic CLI cycle (local) | `0420dac` | DB `patchdiff_frfu_mig` | `0003 → 0002 → 0003` OK |
| Offline eval (local) | `0420dac` | lock venv | exit 0; equivalence OK; tx/3 oracles OK |
| Unchanged PR #11 harness (local) | `0420dac` | real stdio, DB `patchdiff_frfu_live0` | 135/136; the single failure is the intended FR-8 elision |
| Adapted harness (local) | `0420dac` | real stdio, `PYTHONIOENCODING=cp1252`, independent `psql`, DB `patchdiff_frfu_live2` | 230/230 |
| Documentation scan (local) | `0420dac` | active docs and skills vs base | 0 spacing defects, 0 duplicated paragraphs, 0 broken links |
| CI | PR head and merge commit | GitHub Actions | Pending at writing; recorded at closing |

FR coverage in the live run, as the number of checks per finding:

| FR-1 | FR-2 | FR-3 | FR-4 | FR-5 | FR-6 | FR-7 | FR-8 | FR-9 | FR-10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 10 | 16 | 4 | 2 | 3 | 3 | 4 | 2 | 4 |

| FR-11 | FR-12 | FR-13 | FR-14 | FR-15 | FR-16 | FR-17 | FR-18 | FR-19 | FR-20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | 2 | 3 | 8 | 2 | source | 5 | 3 | 2 | 5 |

There are also 7 replay checks across the FR targets.

Remaining gaps: independent friction re-test (pending in this PR's workflow); CI evidence; no external MCP host session; no production-scale measurement of MCP-001.

## 7. Overall disposition and finding closure table

**Disposition:** No P0/P1/P2 findings. One advisory P3 (MCP-001), deferred with a stated remediation. All material categories are covered by source review and independent local execution. Merge is conditional on two things: green CI for the PR head and its merge commit, and no merge-blocking result from the independent friction re-test. Both are recorded in the closing PR comment.

| ID | Priority | Category | Title | Status |
| --- | --- | --- | --- | --- |
| MCP-001 | P3 (advisory) | MCP | Ledger and attempt pages decode full stored records to expose intent and rationale | Open (follow-up) |

PR #11 friction findings addressed by this PR (closure evidence: decision record, tests, live checks above):

| FR | Severity | Disposition |
| --- | --- | --- |
| FR-1 | high | Fixed with decision D1. Declined: `occurrence_basis` selector |
| FR-2 | high | Fixed with decision D2 (runtime `0.5.0`). Declined: mandatory insertion context |
| FR-3 | high | Fixed with decision D3 (migration `0003`). Mixed-EOL per-line restoration is impossible and is refused explicitly |
| FR-4..FR-8 | medium | Fixed with decisions D4–D8 |
| FR-9 | medium | Fixed |
| FR-10 | medium | Fixed with decision D10. Declined: null/omitted fingerprint normalization |
| FR-11 | medium | Fixed (see MCP-001 for its read cost) |
| FR-12 | medium | History byte budget fixed; tx/3 limit documented. Declined: shared admission cap, bounded audit storage |
| FR-13 | medium | Fixed |
| FR-14 | medium | Fixed with decision D14 |
| FR-15..FR-20 | low | Fixed (FR-17 with decision D11) |
