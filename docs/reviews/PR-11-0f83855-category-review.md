# PR #11 Category Review — Guarded editing operations, bounded diagnostics and advisory tools

## 1. Review metadata and evidence limits

| Field | Value |
| --- | --- |
| Repository | `paragon-ux/Patch-DIFF` |
| PR | [paragon-ux/Patch-DIFF#11](https://github.com/paragon-ux/Patch-DIFF/pull/11) — "Add guarded editing operations, bounded diagnostics and advisory tools" |
| Review date | 2026-10-22 |
| Reviewer | Claude (Opus 5.5) via Claude Code, at the request of the repository owner |
| Standard | [PR Review Standard v1.1.0](../PR_REVIEW_STANDARD.md) |
| Base SHA | `2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10` (`main`; merge-base equals base) |
| Head SHA | `0f838557b17d32139d25d429a9c563cdb9025ca6` (`feature/goal-f-rejection-context`) |
| Diff | 153 files, +20,288 / −496 (64 product/doc/test/config files; 89 evidence and prior-review files under `docs/usability/` and `docs/reviews/`) |

**Evidence actually used**

- Source inspection of every changed runtime, service, MCP, test, configuration, skill and normative-doc file at the head SHA (local worktree of `refs/pull/11/head`).
- Local execution (this reviewer, Windows 11, Python 3.11.9, fresh venv from the PR's `requirements.lock`, `pip check` clean, 40 pins):
  - Full pytest suite against an isolated live PostgreSQL database (`postgres:16.3-alpine`, DB `patchdiff_pr11_review`, Alembic head `20261020_0002`).
  - Independent live run: a new harness ([PR-11-0f83855-live-verify.py](PR-11-0f83855-live-verify.py)) driving a **real stdio subprocess** (`python -m app.mcp.external_adapter`, inherited `PYTHONIOENCODING=cp1252`) against a separate isolated DB (`patchdiff_pr11_live`) with independent `psql` SQL assertions. Results: [PR-11-0f83855-live-results.json](PR-11-0f83855-live-results.json).
  - `evaluation/offline_eval.py`.
  - Wheel built from `git archive HEAD`, installed into a clean venv outside the checkout, migrated a fresh DB (`patchdiff_pr11_wheel`) with the installed `alembic.ini`, and served stdio from a neutral cwd.
- CI inspection (GitHub API + job logs): run [39855519186](https://github.com/paragon-ux/Patch-DIFF/actions/runs/39855519186) (`push`, executed head `0f83855`) and run [39855527933](https://github.com/paragon-ux/Patch-DIFF/actions/runs/39855527933) (`pull_request`, checkout log shows generated merge `656383de` = `Merge 0f83855 into 2ee7ce4`). Both `success`; the merge-run log reports `755 passed` for unit tests.

**Not used / limits**

- The 89 committed evidence and prior-review artifacts (`docs/usability/**`, `docs/reviews/Goal-F-*`, `integration-*`, `release-readiness-*`) were inventoried and spot-read, **not** byte-verified against their manifests. Their verdicts were not inherited; every runtime claim below was re-established by independent execution.
- The Devin change plan and Goal F authority snapshots (`docs/usability/accepted/*`) were read only where needed to locate the decision behind a behavior (Pass A / Pass B decisions). The original design paper was not re-read: this PR extends formats and diagnostics but does not alter the exact-match / sequential / atomic thesis, which was verified by execution.
- No representative production workload, multi-host MCP client, or container-image scan was performed.

## 2. File-to-category inventory and coverage matrix

| Category | Primary files (count) | Coverage |
| --- | --- | --- |
| ARCH | `AGENTS.md`, `docs/MODERNIZATION_ARCHITECTURE.md`, `docs/PATCHDIFF_CORE_SPEC.md`, `docs/usability/{F01,PASS-A,PASS-B}-decision.md`, `docs/usability/EXECUTION-PLAN.md`, `docs/usability/accepted/*` (3) — 10 | Complete for contracts; authority snapshots spot-read |
| DOC | `README.md`, `README_DEV.md`, `README_INTERNAL_MCP.md`, `CHANGELOG.md`, `docs/{MODERNIZATION_CHANGE_DOC,HOST_INTEGRATION_GUIDE,MCP_FIRST_MVP,CODEX_BUILD_PLAN,CLAUDE_DESKTOP_SETUP,RELEASE_READINESS}.md`, `docs/reviews/*` (6), `docs/usability/*.md` ledgers/verification (7), `docs/usability/internal/*` (1), `docs/usability/{integration,release}/*.md` (2) — 26 | Normative/public docs complete; historical review/ledger records inventoried only |
| SKILL | `.agents/skills/*/SKILL.md` — 4 | Complete |
| MCP | `backend/app/mcp/external_adapter.py`, `backend/app/mcp/tools.py`, `docs/MCP_TOOLS.md` — 3 | Complete |
| RUN | `backend/app/core/{diagnostics,failures,result,validity,versions}.py`, `backend/app/pdcp/{applier,models,operations,replacement}.py`, `docs/PDCP_FORMAT.md` — 10 | Complete |
| SVC | `backend/app/services/{pdcp_service,near_miss_service,preview_evidence,read_service,rejection_context}.py` — 5 | Complete |
| DB | `backend/app/services/replay_service.py`, `docs/DATA_MODEL.md` — 2 (no migration added) | Complete |
| SCRIPT | `evaluation/offline_eval.py`, `evaluation/README.md`, `docs/usability/**/*.py` (8) — 10 | Offline eval complete; historical verification scripts inventoried only |
| TEST | `backend/tests/**` (16), `docs/TEST_MATRIX.md`, `docs/usability/**` captures (`*.xml` 9, `*.txt` 33, `*.json` 18) — 77 | Product tests complete; captures not byte-verified |
| DEP | `pyproject.toml`, `requirements.lock`, `docker-compose.yml`, `.gitattributes`, `.gitignore`, `LICENSE`, `SECURITY.md` — 7 | Complete |

Unchanged dependencies examined: `backend/app/pdcp/typed.py` (TypedEdit field order used positionally by `SpanEdit`), `backend/app/core/canonicalization.py`, `backend/app/pdcp/disambiguation.py` call path, `main`'s `pdcp_service._submit` (guard→decode ordering), Alembic `env.py`/`alembic.ini`, live DB check constraints (no protocol/runtime enum constraint, so no migration is needed).

## 3. Architecture-to-implementation trace

| Invariant / decision | Contract | Implementation | Verification |
| --- | --- | --- | --- |
| Exact deterministic match; no fuzzy application | AGENTS.md invariants; PASS-A decision (near misses response-only) | `applier.py` match path unchanged; spans compare `current[start:end] == canonicalize(expected_text)`; near misses computed only in `_submission_response` after the owned transaction exits and never persisted | Live: near misses absent from `diagnostic_json` (SQL); unit/integration tests `test_near_miss_comparison_starts_after_service_commit_and_real_lock_release` |
| Sequential in-memory simulation, atomic per-target commit | Core spec; tx/2 "sequential canonical code-point" coordinates | `apply_pdcp_transaction` loop; spans validated against the evolving buffer; `_submit` single `SELECT … FOR UPDATE` | Live: mixed span/match with shifted coordinates over 🌟 accepted; second-op mismatch rejected whole (no ledger rows, version unchanged); second session blocked on a held row lock, then rejected `target_version_mismatch` |
| Immutable runtime profiles; replay dispatch on (protocol, runtime) | Architecture; `SUPPORTED_RUNTIME_PROFILES` | New `0.3.0` (span) and `0.4.0` (span+replace_all) profiles; `_runtime_version` pairs tx/2→0.3.0, tx/3→0.4.0, tx/1 & 0.2.3→0.2.2; replay decoders gate on profile flags | Live SQL: pairings exactly as specified; replay `success` with all `materialized_state_checks` true over tx/1 → 0.2.3 → (rejected tx/2) → SAVE → tx/2 (parent lineage) → tx/3 → tx/1; replay detected an out-of-band SQL version bump |
| Stage-accurate validity | Core spec ValidationStage | Guard→decode→apply ordering unchanged from `main`; protocol validation of whole tx precedes applicability | Live multi-fault: stale guard + malformed span → `precondition_guard`, `protocol_valid: null`; applicability-failing op followed by malformed op → `protocol_validation`, `protocol_valid: false` |
| Append-only attempt log, idempotency, lineage | C4; AGENTS.md | Shared `_submit`; recovery precedes guards and tx/3 fresh admission | Live: exact-key replay returns original accept/rejection (original `failure_context` unchanged, fresh `current_context`); conflict audited as NULL-key row; parent lineage stored |
| Bounded diagnostics / preview without writes | PASS-A / PASS-B decisions; MCP_TOOLS | `rejection_context.py`, `diagnostics.py`, `preview_evidence.py`; `_preview` uses `observe_target` (no lock) | Live: preview of all four formats wrote nothing (logs, ledger, target, current_pdcp unchanged by SQL); preview completed while another session held `FOR UPDATE`; 40-fact preview returned 32 facts with explicit truncation, ≤ 32,768 bytes |

No intentional departure from a higher-priority contract was found; new behavior is backed by recorded decisions (`docs/usability/PASS-A-decision.md`, `PASS-B-decision.md`, `F01-decision.md`).

## 4. Category sections

### ARCH — Architecture and contracts

- **Scope:** files listed in §2; AGENTS.md invariants and boundary block; Pass A/B decisions.
- **Coverage:** Complete for normative contracts; authority snapshots spot-read.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:**
  - **ARCH-001 — AGENTS.md boundary block and section heading still describe only two/three formats.** Status: open.
    - Provenance: AGENTS.md is precedence #1 (locked invariants).
    - Evidence: [AGENTS.md:50](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/AGENTS.md#L50) heading lists tx/1, tx/2 and `.pdcp` only; [AGENTS.md:64-72](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/AGENTS.md#L64-L72) still says "`patchdiff-tx/1` or `.pdcp` = declarative, non-executable transaction artifact … Neither `patchdiff-tx/1` nor `.pdcp` is executable code", while the same section now enumerates four formats.
    - Impact: the locked non-executable boundary statement does not name tx/2/tx/3; an agent reading the boundary literally gets an incomplete invariant. Text-only; runtime unaffected.
    - Remediation: name all four formats in the heading and boundary block. Acceptance: source reconciliation.
- **Verification:** Source inspection; contracts traced to live behavior in §3.
- **Verdict:** No blocking findings; one P3.

### DOC — Documentation and change records

- **Scope:** README*, CHANGELOG, change record, host guide, MVP, build plan, desktop setup, release readiness, data model/format docs (cross-referenced), prior reviews (inventoried).
- **Coverage:** Partial — public/normative docs complete; historical review/ledger/evidence records inventoried, not byte-verified.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:**
  - **DOC-001 — Systematic missing spaces between words and numerals, and verbatim-duplicated dense paragraphs, in normative docs.** Status: open.
    - Evidence (diff-added lines, scanned mechanically): `docs/MCP_TOOLS.md` 21 occurrences, `docs/PATCHDIFF_CORE_SPEC.md` 13, `docs/MODERNIZATION_ARCHITECTURE.md` 12, `docs/HOST_INTEGRATION_GUIDE.md` 11, `docs/DATA_MODEL.md` 8, `docs/PDCP_FORMAT.md` 6, `AGENTS.md` 6, plus all four skills. Examples: "immutable0.4.0", "limits are1,000,000 code points and1,048,576", "default4000/cap8000", "at most65,536", "its32768byte payload budget", "At leastone guard". The same "Guarded replacement, line reads and preview" paragraphs are pasted verbatim into AGENTS.md, MCP_TOOLS, HOST guide, architecture, core spec, data model and PDCP format docs.
    - Impact: normative limits are harder to read and search (e.g. grepping "1,000,000 code points" misses "are1,000,000"); duplication multiplies future drift. Values themselves match code constants (checked: 1,000,000 / 1,048,576 / 4,000 / 8,000 / 32,768 / 32 / 2,048 / 16,384 / 8,192 / 18,432).
    - Remediation: restore spacing; keep one normative statement (MCP_TOOLS / core spec) and link to it elsewhere. Acceptance: source reconciliation plus a re-run of the spacing scan returning zero hits.
  - **DOC-002 — Role descriptions of `docs/MODERNIZATION_CHANGE_DOC.md` are stale after its rewrite.** Status: open.
    - Evidence: [AGENTS.md:37](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/AGENTS.md#L37) and [README.md:179](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/README.md#L179) say it holds a "reconciliation table"; [MODERNIZATION_ARCHITECTURE.md:250](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/docs/MODERNIZATION_ARCHITECTURE.md#L250) calls it the authoritative record of A1–A8, C1–C6 and E1–E8. The rewritten 56-line "Product Change Record" contains none of those IDs (0 matches; `main` had 6) and no reconciliation table — that content moved to `docs/usability/internal/MODERNIZATION_CHANGE_DOC-973ba79.md`, which AGENTS.md does not list among historical records.
    - Impact: the precedence list points readers to content that is no longer there.
    - Remediation: update the three descriptions and list the internal archive as a historical record. Acceptance: source reconciliation.
- **Verification:** Source inspection; mechanical spacing scan of diff-added lines; constants cross-checked against `preview_evidence.py`, `replacement.py`, `read_service.py`.
- **Verdict:** No blocking findings; two P3; coverage partial for historical records only.

### SKILL — Skills and agent instructions

- **Scope:** the four `.agents/skills/*/SKILL.md` files.
- **Coverage:** Complete. All 12 backticked identifiers/paths added by the PR resolve in code or docs.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:**
  - **SKILL-001 — Stale/contradictory format statements and duplicated boilerplate.** Status: open.
    - Evidence: each skill's "Pass A additions" ends "no replace_all yet" (e.g. [core-runtime SKILL.md:148](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/.agents/skills/patchdiff-core-runtime/SKILL.md#L148)) directly above "Pass B additions" introducing tx/3 replace_all; [core-runtime SKILL.md:16](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/.agents/skills/patchdiff-core-runtime/SKILL.md#L16) lists parsing for tx/1, tx/2 and 0.2.3 only, while the same file says four formats. The F01/Pass A/Pass B sections are identical across all four skills and carry DOC-001 spacing defects.
    - Impact: agent guidance can be read as "replace_all is not supported". Low; runtime unaffected.
    - Remediation: say "tx/2 has no replace_all; tx/3 provides sole replace_all", add tx/3 to the capability list, and keep each skill's addition scoped to its layer. Acceptance: source reconciliation.
- **Verification:** Identifier resolution script; manual read.
- **Verdict:** No blocking findings; one P3.

### MCP — MCP schemas and public API

- **Scope:** `external_adapter.py`, `tools.py`, `docs/MCP_TOOLS.md`.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:**
  - **MCP-001 — Advertised `patchdiff_submit_operations` description says "runtime0.3.0".** Status: open.
    - Evidence: [external_adapter.py:33](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/backend/app/mcp/external_adapter.py#L33); observed verbatim in the live `tools/list` response.
    - Impact: the model-facing description names a runtime identifier that does not exist (actual `patchdiff-mvp-0.3.0`, which `x-patchdiff-capabilities` reports correctly).
    - Remediation: "Uses immutable runtime patchdiff-mvp-0.3.0", ideally formatted from `OPERATIONS_RUNTIME_VERSION`. Acceptance: discovery unit test asserting the description contains the constant.
  - **MCP-002 — `submit_replacement` capability metadata hard-codes literals.** Status: open (advisory).
    - Evidence: [external_adapter.py:256-260](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/backend/app/mcp/external_adapter.py#L256-L260) hard-code `"patchdiff-tx/3"`, `"patchdiff-mvp-0.4.0"`, `1_000_000`, `1_048_576`, while the operations block uses `OPERATIONS_PROTOCOL_VERSION`/`OPERATIONS_RUNTIME_VERSION`.
    - Impact: drift risk only; values currently correct.
    - Remediation: use `REPLACEMENT_PROTOCOL_VERSION`, `REPLACEMENT_RUNTIME_VERSION`, `MAX_REPLACEMENT_CHARS`, `MAX_REPLACEMENT_BYTES`. Acceptance: unit equality assertion.
- **Verification (live, real stdio):** 20 tools advertised; 13 examples across 9 tools, each validated against its own `inputSchema` (Draft 2020-12); all 20 `inputSchema`s are valid JSON Schema; `tools/list` and examples within 65,536 / 8,192 compact bytes; preview `format` enum; non-boolean `include_correlation_id` → `invalid_argument` with no attempt row; correlation UUIDv4 fresh on dedup and absent from all stored text/JSON (SQL).
- **Verdict:** No blocking findings; two P3.

### RUN — Core runtime, parsing and validation

- **Scope:** `core/*`, `pdcp/{applier,models,operations,replacement}.py`, `docs/PDCP_FORMAT.md`.
- **Coverage:** Complete. Core purity holds (no FastAPI/SQLAlchemy/MCP imports added to `core/` or `pdcp/`).
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** Source review of span bounds (bool/int/range checks in both parser and applier), `SpanEdit` positional construction against `TypedEdit` field order, replace_all sole-op gate, profile flags defaulting to `False` for historical profiles. Live: insertion, CRLF `expected_text` canonicalization, astral-plane code-point coordinates, `span_out_of_bounds` (`protocol_valid: true`, `transaction_valid: false`), `span_expected_text_mismatch` on an intermediate buffer, selectors on spans, `end < start`, boolean coordinates, `replace_all` inside tx/2, lone surrogate → durable `target_encoding_invalid`; tx/3 inclusive 1,000,000-code-point boundary accepted, 1,000,001 and 400,000×"中" (1.2 MB) rejected with the correct `limit_exceeded` domain.
- **Verdict:** No findings within reviewed scope.

### SVC — Services, orchestration and audit semantics

- **Scope:** `pdcp_service.py` (+351/−111), `near_miss_service.py`, `preview_evidence.py`, `read_service.py`, `rejection_context.py`.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:**
  - **SVC-001 — Near-miss queries of 40–64 code points are admitted but never served on a full prefix, after ~0.5 s of discarded work.** Status: open.
    - Provenance: PASS-A decision / MCP_TOOLS: queries up to 64 code points, comparison bounded at 1,000,000 cells, omission explicit.
    - Evidence: [diagnostics.py:16-19](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/backend/app/core/diagnostics.py#L16-L19) admits ≤ 64; [near_miss_service.py:22-32](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/backend/app/services/near_miss_service.py#L22-L32) runs a full DP per window for widths n−1..n+1 and checks the budget incrementally. Over a 256-point prefix the work is Σ(257−w)·n·w ≈ 1.04 M cells at n = 40.
    - Observed (live stdio, 256+-point target): n = 20/30/38 → `computed`, 0.19/0.29/0.52 s; n = 40/48/64 → `omitted: work_budget_exhausted`, 0.56/0.62/0.52 s.
    - Impact: for any document longer than 256 code points, typo suggestions for sentence-length matches (a common model failure) are always omitted, yet each such rejection still spends ~0.5 s CPU on the single-threaded stdio loop. Advisory feature only; verdicts unaffected.
    - Remediation: compute the cell total up front and omit immediately when it exceeds the budget, or use a banded / bit-parallel (Myers) edit distance so the advertised 64-point bound is actually served; alternatively lower the admitted bound to what the budget can serve and document it.
    - Acceptance: test that a 64-point near-miss over a full prefix either computes or omits with `comparison_cells == 0`, and that its latency does not scale with the budget.
  - **SVC-002 — tx/3 admission caps do not bound what the key-conflict path persists.** Status: open (advisory).
    - Provenance: MCP_TOOLS / PASS-B decision: "existing-key recovery/conflict precedes fresh admission"; "oversized valid fresh replacements return … without writes".
    - Evidence: conflict branch [pdcp_service.py:617-679](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/backend/app/services/pdcp_service.py#L617-L679) persists the full record before the fresh-admission check at [682-691](https://github.com/paragon-ux/Patch-DIFF/blob/0f838557b17d32139d25d429a9c563cdb9025ca6/backend/app/services/pdcp_service.py#L682-L691).
    - Observed: reusing an existing `client_request_id` with a 1,200,000-character replacement wrote a rejected row whose `pdcp_content` is 1,200,214 characters.
    - Impact: the ordering is as documented, and tx/1/tx/2 have no size caps, so this is not a new exposure class. However, the docs present the caps as limiting writes without saying that conflict audit rows can exceed them.
    - Remediation: either document explicitly that conflict audit rows may carry over-limit proposals, or store bounded evidence (hash + length + prefix) for over-limit conflicting proposals. Acceptance: doc reconciliation, or an integration test asserting the bounded row.
- **Verification:** Source review of `_submit` ordering (identity check → key recovery/conflict → admission → current-PDCP upsert → encoding → parent → attempt → guard/decode/apply → final guard → persist), `_submission_response` post-commit near-miss, `_preview` observation and pending-local rejection, `bound_preview` and context budgets. Live: absent/ambiguous/stale/no-guard/conflict paths, intermediate-buffer failure context, rejected exact-key recovery (original context preserved, current context refreshed, near misses recomputed), all 20 tools, history paging traversing every attempt and ledger row exactly once.
- **Verdict:** No blocking findings; two P3.

### DB — Database, migrations, replay and concurrency

- **Scope:** `replay_service.py`, `docs/DATA_MODEL.md`; schema unchanged (no migration).
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** Live DB constraints checked (no protocol/runtime enum, so new pairings need no migration). Suite ran live `upgrade → downgrade → upgrade` with populated legacy data and downgrade refusal with typed rows (`test_migrations_reachable.py`). Live two-session concurrency: preview returned in < 1.5 s while another session held `FOR UPDATE`; a tx/2 submit blocked on the lock and, after the holder committed a version bump, rejected `target_version_mismatch` (no lost update). Replay: mixed-protocol target across SAVE → `success` with all component checks true; deliberately tampered target → `failed: Logged version chain is not contiguous`.
- **Verdict:** No findings within reviewed scope.

### SCRIPT — Scripts, evaluation and developer tooling

- **Scope:** `evaluation/offline_eval.py`, `evaluation/README.md`; `docs/usability/**/*.py` inventoried.
- **Coverage:** Partial — offline evaluation complete; historical verification scripts not executed.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** Local run exit 0: verdict equivalence OK (named delimiter-collision exception only); five tx/3 content/hash oracles OK. Exit code now requires both equivalence and replacement oracles. Output states it measures bytes only, not tokens or model success.
- **Gap:** no tx/2 scenario in the offline evaluation (TEST_MATRIX does not claim one).
- **Verdict:** No findings within reviewed scope; partial coverage of historical scripts.

### TEST — Tests and CI

- **Scope:** 16 changed test files; `docs/TEST_MATRIX.md`; committed captures inventoried.
- **Coverage:** Product tests complete; committed captures not byte-verified.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:**
  - Local full suite at `0f83855`: **1,144 passed = 755 unit + 389 live-PostgreSQL integration**, 0 failed/errored/skipped (JUnit tally).
  - CI: push run on head `0f83855`, PR run on generated merge `656383de` (parents `2ee7ce4`, `0f83855`); both success.
  - Assertions inspected: new tests check DB row counts, target content/version, ledger `derived_json` equality with returned facts, replay outcomes and stdio responses — not just status strings. Two-session lock tests exist (`test_replacement_writer_waits_for_real_lock_then_rechecks_version`).
- **Gaps (not defects):** no explicit tx/2 multi-fault stage test (verified live, §3); no test that 40–64-point near misses are ever computed (SVC-001).
- **Verdict:** No findings within reviewed scope.

### DEP — Dependencies, packaging and configuration

- **Scope:** `pyproject.toml`, `requirements.lock`, `docker-compose.yml`, `.gitattributes`, `.gitignore`, `LICENSE`, `SECURITY.md`.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:**
  - Fresh venv from the lock: 40 pins, `pip check` clean.
  - Wheel built from `git archive HEAD` (sha256 `1fd69696…40fb8`; differs from the PR's recorded hash as expected for a different build time/toolchain): 55 entries, 50 `app/` files, includes `migrations/alembic.ini`, `script.py.mako`, `env.py` and both versions, no tests.
  - Installed outside the checkout: `alembic -c <site-packages>/app/migrations/alembic.ini upgrade head` migrated a fresh DB, and stdio `initialize_target` succeeded from a neutral cwd.
  - Compose binds `127.0.0.1:5432`. The running local container still publishes `0.0.0.0:5432`, as SECURITY.md states.
  - Pin bumps (anyio, certifi, Mako, pytest, starlette) match SECURITY.md. Advisory claims not independently re-queried.
- **Verdict:** No findings within reviewed scope.

## 5. Cross-category root causes and remediation order

- **Shared root cause of DOC-001, SKILL-001, ARCH-001 and MCP-001:** contract text was generated in a compressed, numeral-adjacent style and then pasted into many files. Fix the single source paragraph, restore spacing, and replace copies with links. This closes four findings in one pass.
- **SVC-001** is independent. A cheap up-front cell estimate fixes the latency and makes omissions honest. Serving the full 64-point bound needs an algorithm change.
- **SVC-002 and MCP-002** are advisory; address them with the docs pass.

Suggested order: MCP-001 (model-facing) → DOC-001/SKILL-001/ARCH-001/DOC-002 (one docs commit) → SVC-001 → advisories.

## 6. Verification record and remaining gaps

| Evidence | Revision | Environment | Result |
| --- | --- | --- | --- |
| Full pytest (local) | `0f83855` | Win 11, Py 3.11.9, lock venv, PG 16.3 isolated DB | 755 unit + 389 integration passed |
| Live stdio harness (local) | `0f83855` | real subprocess, isolated DB, independent `psql` | 135 / 136 checks passed; the 1 failure is MCP-001 |
| Offline eval (local) | `0f83855` | lock venv | exit 0; equivalence OK; tx/3 oracles OK |
| Installed wheel (local) | `git archive 0f83855` | clean venv, neutral cwd, fresh DB | migrate OK; stdio OK |
| CI push run 39855519186 | `0f83855` | GitHub Actions | success |
| CI PR run 39855527933 | merge `656383de` | GitHub Actions | success (755 unit passed per log) |

Live-run coverage: all 20 tools were called over stdio. Final DB outcome mix: 0.2.3 accepted 2; tx/1 accepted 5 / rejected 15; tx/2 accepted 5 / rejected 11; tx/3 accepted 5 / rejected 2. Every protocol/runtime pairing was as specified.

Remaining gaps:

- Committed evidence captures were not byte-verified against their manifests.
- Historical `docs/usability/**/*.py` scripts were not executed.
- No representative-size or production-performance measurement beyond the near-miss latency probe.
- No external MCP host (Claude Desktop etc.) session.
- Advisory database not re-queried.

## 7. Overall disposition and finding closure table

**Disposition:** No P0/P1/P2 findings. Eight P3 findings, two of them advisory. Runtime, service, MCP, DB, DEP and TEST categories are fully covered by source review and independent live execution. DOC, SCRIPT and TEST are partial only for committed historical evidence artifacts, which this review did not rely on because verification was re-run independently. They are not material to merge correctness.

**Recommendation: approve once the owner and Devin review the P3s.** No blocking findings remain. Fix MCP-001 and the DOC-001 spacing before merging to `main`, because both are public, model-facing text. Per the PR description, the PR stays open for Devin and owner approval. This review does not merge.

| ID | Priority | Category | Title | Status |
| --- | --- | --- | --- | --- |
| MCP-001 | P3 | MCP | Advertised description says "runtime0.3.0" | Open |
| DOC-001 | P3 | DOC | Word/numeral spacing defects and duplicated normative paragraphs | Open |
| DOC-002 | P3 | DOC | Stale role descriptions of the rewritten change record | Open |
| ARCH-001 | P3 | ARCH | AGENTS.md boundary block omits tx/2/tx/3 | Open |
| SKILL-001 | P3 | SKILL | "no replace_all yet" / capability list omits tx/3 | Open |
| SVC-001 | P3 | SVC | 40–64-point near misses never served; ~0.5 s wasted per rejection | Open |
| SVC-002 | P3 (advisory) | SVC | Key-conflict path persists over-cap tx/3 proposals | Open |
| MCP-002 | P3 (advisory) | MCP | Replacement capability metadata hard-codes literals | Open |
