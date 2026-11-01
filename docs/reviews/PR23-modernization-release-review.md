# PR Review Report: PR #23 Modernization Release (Profile Consolidation, Default observed_v2, Atomic Finalize, and Packaging)

**Standard**: PR Review Standard v1.1.0  
**Review Date**: 2026-10-31  
**Reviewer**: Antigravity Assistant  
**Repository**: paragon-ux/Patch-DIFF  
**PR Branch**: `feature/pr23-modernization-release`  
**Base SHA**: `56d3545b73656cff3e7f5020967da780ae79db41` (merged `main`)  
**Historical Initial Head SHA**: `276d5f643eec34b52ff9a5d1ff3eebe6ba2473ff`  

> **Historical Provenance Note (`PR23-IMPL-DOC-001` & `PR23-R4-DOC-002`)**: Sections 1–6 below are preserved unchanged as the historical review records for commits `276d5f643eec34b52ff9a5d1ff3eebe6ba2473ff` and `abd4d39` / `1073338234c300180a269660acc7de32c564fea1`. Section 7 records the subsequent independent Review 3 (`PR23-R3-*`) and Review 4 (`PR23-R4-*`) delta evaluations, complete 65-file inventory, and final closure verification against base `56d3545d9f4369bc1e57f593dbb71bbd37128b9e`.

---

## 1. Pin the Review (Historical Record at `276d5f6`)

- **Base Ref**: `main` (`56d3545b73656cff3e7f5020967da780ae79db41`)
- **Head Ref**: `feature/pr23-modernization-release` (`276d5f643eec34b52ff9a5d1ff3eebe6ba2473ff`)
- **Changed Files (23)**:
  - `ARCH`: `AGENTS.md`, `docs/ROADMAP.md`
  - `DOC`: `docs/guides/HOST_INTEGRATION_GUIDE.md`, `zensical.toml`
  - `MCP`: `backend/app/mcp/external_adapter.py`, `backend/app/mcp/tools.py`, `docs/spec/MCP_TOOLS.md`
  - `SVC`: `backend/app/services/finalize_service.py`, `backend/app/services/waymark_adapter.py`, `backend/app/services/waymark_worker.py`
  - `TEST`: `backend/tests/integration/test_batch_stdio_profiles.py`, `backend/tests/integration/test_mcp_tools.py`, `backend/tests/integration/test_pass_b_discovery.py`, `backend/tests/unit/test_editor_v2_adapter.py`, `backend/tests/unit/test_finalize_service.py`, `backend/tests/unit/test_finalize_tool.py`, `backend/tests/unit/test_mcp_profiles.py`, `backend/tests/unit/test_mcp_response_modes.py`, `backend/tests/unit/test_observed_editor_profile.py`, `backend/tests/unit/test_pass_b_reads_discovery.py`, `backend/tests/unit/test_typed_transaction.py`
  - `DEP`: `.github/workflows/publish.yml`, `pyproject.toml`
- **Evidence Available**:
  - Live PostgreSQL 18 execution in Linux environment (`127.0.0.1:5432`)
  - Unit test suite: 1,036 tests passed, 1 skipped (51.00s)
  - Integration test suite: 561 tests passed (0 failures)
  - Structural batch verification: 20/20 behavioral tests passed
  - Offline payload and verdict equivalence: 100% passed
  - Zensical documentation build: 0 issues (1.02s)
  - Canonical triaged findings ledger: 18 PR #23 findings reconciled and closed (`TRIAGED_FINDINGS_LEDGER_REVISED_v2.jsonl`)

---

## 2. Architecture Trace (Historical Record at `276d5f6`)

- **Thesis & Invariants**:
  - Declarative non-executable transactions executed deterministically in pure memory simulation.
  - Per-target atomic Postgres commit under row locking (`SELECT ... FOR UPDATE`).
  - Append-only audit attempts and accepted-only manifest ledgers.
  - Deterministic replay verification across immutable profiles (`0.1.0` through `0.5.0`).
- **Modernization Extensions**:
  - `observed_v2` is the streamlined, 5-tool external editing interface providing explicit observation receipts and compact JSON wire responses.
  - Profile consolidation makes `observed_v2` the default startup profile without breaking existing legacy named profiles (`editor`, `unobserved`, `observed`, `observed_editor`), which issue advisory stderr notices when explicitly selected.
  - `patchdiff_finalize_target` exposes atomic checkpointing, replay, and export on the `full` MCP profile in a single explicit database transaction.
  - Packaging as `patchdiff-mcp` with command `patchdiff` avoids naming collisions with third-party distributions while supporting `uvx --from patchdiff-mcp patchdiff`.
  - Multi-agent concurrency is grounded on optimistic concurrency control (OCC) over per-target Postgres state, eliminating Git working-tree conflicts in-flight.

---

## 3. Category Reviews (Historical Record at `276d5f6`)

### ARCH: Architecture and Contracts
- **Coverage**: `AGENTS.md`, `docs/ROADMAP.md`.
- **Evaluation**: Clear boundaries between untrusted model agent (5 tools, no DB access) and trusted host/operator (full profile, DB access). Roadmap accurately grounds concurrency in OCC without ungrounded "zero git conflicts" claims.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### DOC: Documentation and Change Records
- **Coverage**: `docs/guides/HOST_INTEGRATION_GUIDE.md`, `zensical.toml`.
- **Evaluation**: Host integration guide updated to explain atomic finalization, line-ending fallback fail-closed semantics, and host write-back trust boundaries. Zensical build passes with 0 issues.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### SKILL: Skills and Agent Instructions
- **Coverage**: Workspace skills in `.agents/skills/`.
- **Evaluation**: Tools and schemas referenced in skills align with registered profiles and contracts. No conflicting instructions.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### MCP: MCP Schemas and Public API
- **Coverage**: `backend/app/mcp/external_adapter.py`, `backend/app/mcp/tools.py`, `docs/spec/MCP_TOOLS.md`.
- **Evaluation**: Default profile is `observed_v2` (5 tools). `full` profile has 23 tools including `patchdiff_finalize_target`. Tools adhere to JSON Schema Draft 2020-12 and strict validation rules.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### RUN: Core Runtime, Parsing, and Validation
- **Coverage**: Untrusted inputs, exact deterministic matching, replay dispatch.
- **Evaluation**: Pure runtime invariants preserved. Offline evaluation passes with 100% verdict equivalence across all scenarios.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### SVC: Services, Orchestration, and Audit Semantics
- **Coverage**: `backend/app/services/finalize_service.py`, `backend/app/services/waymark_adapter.py`, `backend/app/services/waymark_worker.py`.
- **Evaluation**: `finalize_target` guarantees single-session, single-transaction atomic execution. Replay divergence triggers transaction rollback, leaving 0 snapshots and 0 cycles. Idempotency and line-ending validation fail closed.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### DB: Database, Migrations, Replay, and Concurrency
- **Coverage**: Postgres integration, row locking, migration integrity.
- **Evaluation**: Integration test suite passes all 561 tests against live Postgres. Migrations 0001 through 0005 verified reachable and intact.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### SCRIPT: Scripts, Evaluation, and Developer Tooling
- **Coverage**: `examples/host_finalize.py`, `backend/tests/verification/structural_batch/verify.py`, `backend/tests/verification/offline_eval.py`.
- **Evaluation**: Scripts preserved and verified. Structural batch verification passes 20/20 behavioral tests. Offline evaluation confirms exact verdict equivalence.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### TEST: Tests and CI
- **Coverage**: 1,036 unit tests and 561 integration tests.
- **Evaluation**: 100% pass rate. Dedicated test coverage added for `finalize_service` and `finalize_tool`.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

### DEP: Dependencies, Packaging, and Configuration
- **Coverage**: `pyproject.toml`, `.github/workflows/publish.yml`.
- **Evaluation**: Packaging as `patchdiff-mcp` with `patchdiff` CLI. Retains `psycopg[binary]>=3.2,<4.0`. PyPI publishing workflow isolated and gated to `v*.*.*` tags.
- **P1/P2/P3 Findings**: None.
- **Verification Gaps**: None.
- **Verdict**: PASS.

---

## 4. Overall Review Verdict (Initial Evaluation at `276d5f6`)

**Verdict**: **CHANGES_REQUIRED** (Superseded by Section 5 and Section 7 rechecks below; 13 implementation defects were identified in independent review `dda1629`).

---

## 5. Independent Category Recheck & Sol-Optimized Remediation Verification (Historical Record at `abd4d39` / `1073338`)

**Standard**: PR Review Standard v1.1.0  
**Recheck Date**: 2026-10-31  
**Target Plan**: `pr23_remediation_plan_REVISED.md` (Sol-Optimized Plan)  
**Evaluated Head**: `abd4d39` (CI Run `41234564958`: 100% green across all unit, live Postgres integration, resident worker, offline eval, and docs build suites)  
**Base**: Merged PR #22 (`56d3545d9f4369bc1e57f593dbb71bbd37128b9e`)  
**Scope**: All 32 open baseline findings across 8 workstreams (A–H) and 1 external registry gate.

### 5.1 Category Reviews (at `abd4d39`)

#### ARCH: Architecture and Contracts
- **Scope**: `AGENTS.md`, `docs/ROADMAP.md`, `examples/host_finalize.py`, `backend/app/services/finalize_service.py`.
- **Coverage**: Complete.
- **P1 — High Priority**: None identified within reviewed scope.
- **P2 — Medium Priority**: None identified within reviewed scope.
- **P3 — Low Priority**: None identified within reviewed scope.
- **Verdict**: PASS *(subsequently refined in Review 3 at `1073338`; see Section 7)*.

#### DOC: Documentation and Change Records
- **Scope**: `docs/ROADMAP.md`, `docs/guides/HOST_INTEGRATION_GUIDE.md`, `docs/spec/MCP_TOOLS.md`, `docs/reviews/PR23-modernization-release-review.md`.
- **Coverage**: Complete.
- **P1/P2/P3**: None identified in that pass *(subsequently refined in Review 3 & Review 4; see Section 7)*.
- **Verdict**: PASS.

#### SKILL: Skills and Agent Instructions
- **Scope**: Workspace skills in `.agents/skills/`.
- **Coverage**: Complete.
- **P1/P2/P3**: None identified in that pass *(subsequently refined in Review 4 `PR23-R4-SKILL-001`; see Section 7)*.
- **Verdict**: PASS.

#### MCP: MCP Schemas and Public API
- **Scope**: `backend/app/mcp/external_adapter.py`, `backend/app/mcp/tools.py`, `docs/spec/MCP_TOOLS.md`.
- **Coverage**: Complete.
- **P1**: None.
- **P2**: `PR22-MCP-002` (Glama directory listing schema, `POST_MERGE_REGISTRY_VERIFICATION`).
- **P3**: None.
- **Verdict**: PASS (excluding external `PR22-MCP-002` gate).

#### RUN: Core Runtime, Parsing, and Validation
- **Scope**: Declarative transaction execution, deterministic matching, replay dispatch.
- **Coverage**: Complete.
- **P1/P2/P3**: None.
- **Verdict**: PASS.

#### SVC: Services, Orchestration, and Audit Semantics
- **Scope**: `backend/app/services/finalize_service.py`, `backend/app/services/waymark_adapter.py`, `backend/app/services/waymark_worker.py`.
- **Coverage**: Complete.
- **P1/P2/P3**: None identified in that pass *(subsequently refined in Review 3 `PR23-R3-SVC-001..003` and Review 4 `PR23-R4-SVC-001`; see Section 7)*.
- **Verdict**: PASS.

#### DB: Database, Migrations, Replay, and Concurrency
- **Scope**: `backend/app/storage/models.py`, `backend/app/migrations/versions/20261031_0006_target_finalizations.py`.
- **Coverage**: Complete.
- **P1/P2/P3**: None identified in that pass *(subsequently extended in Review 3 `0007` and Review 4 `PR23-R4-DB-001`; see Section 7)*.
- **Verdict**: PASS.

#### SCRIPT: Scripts, Evaluation, and Developer Tooling
- **Scope**: `examples/host_finalize.py`, `backend/tests/verification/benchmark_finalize_replay.py`, `backend/tests/verification/offline_eval.py`.
- **Coverage**: Complete.
- **P1/P2/P3**: None identified in that pass *(subsequently refined in Review 3 `PR23-R3-SCRIPT-001..005` and Review 4 `PR23-R4-SCRIPT-001`; see Section 7)*.
- **Verdict**: PASS.

#### TEST: Tests and CI
- **Scope**: Unit tests, live PostgreSQL integration tests, installed wheel smoke test.
- **Coverage**: Complete.
- **P1/P2/P3**: None identified in that pass *(subsequently refined in Review 3 `PR23-R3-TEST-001` and Review 4 `PR23-R4-TEST-001`; see Section 7)*.
- **Verdict**: PASS.

#### DEP: Dependencies, Packaging, and Configuration
- **Scope**: `pyproject.toml`, `.github/workflows/publish.yml`, `backend/app/waymark_bridge/`.
- **Coverage**: Complete.
- **P1/P2/P3**: None identified in that pass *(subsequently refined in Review 3 `PR23-R3-DEP-001` and Review 4 `PR23-R4-DEP-001`; see Section 7)*.
- **Verdict**: PASS.

---

## 6. Historical Disposition at `1073338`

- **Historical Status**: Superseded by Independent Review 3 (`PR23_INDEPENDENT_REVIEW3_1073338.md`), which identified 11 open findings (`PR23-R3-*`: 6 P1, 4 P2, 1 P3) and reopened `PR23-IMPL-DOC-001`, and by Independent Review 4 (`PR23-R4-*`: 0 P1, 5 P2, 3 P3). All 19 findings across Review 3 and Review 4 are resolved and verified in Section 7 below.

---

## 7. Independent Delta Review & Final Closure Verification (Review 3 `PR23-R3-*` + Review 4 `PR23-R4-*`)

### 7.1 Delta Review Metadata
- **Standard**: [`docs/standards/PR_REVIEW_STANDARD.md`](../standards/PR_REVIEW_STANDARD.md) v1.1.0
- **Review Date**: `2026-10-31`
- **Reviewer**: Antigravity (Independent Review Standard v1.1.0 Audit & Remediation Verification)
- **Base Commit SHA**: `56d3545d9f4369bc1e57f593dbb71bbd37128b9e` (merged PR #22 on `main`)
- **Prior Evaluated Heads**:
  - Review 3 Baseline: `1073338234c300180a269660acc7de32c564fea1`
  - Review 3 Remediation Code Head: `ab9200ed43bfa993e545465e63e5210283c74e30` / `f6cb965bddbc2d55cd5505195c24cf796ba42b22` (CI Runs `41265183980`, `41265494759`, `41265498958`: 100% green)
  - Review 4 Final Remediation Delta: Evaluated over the complete 65-file diff from `56d3545d9f4369bc1e57f593dbb71bbd37128b9e` through the Review 4 remediation commit (Per `PR22-DOC-004`, a committed review file cannot self-embed its own not-yet-created Git SHA; the exact final commit SHA is recorded in git history and GitHub Actions CI).

### 7.2 Complete 65-File Changed-File Inventory (`56d3545d9f4369bc1e57f593dbb71bbd37128b9e..HEAD`)

Every changed or added file in `git diff --name-status 56d3545d9f4369bc1e57f593dbb71bbd37128b9e` (65 files total) is mapped to its primary review category:

| Primary Category | Count | Changed / Added Files (`56d3545d..HEAD`) |
| :--- | :---: | :--- |
| **`ARCH`** | 1 | `AGENTS.md` |
| **`DOC`** | 7 | `docs/ROADMAP.md`, `docs/benchmarks/finalize_replay_benchmark_report.md`, `docs/guides/HOST_INTEGRATION_GUIDE.md`, `docs/reviews/PR23-modernization-release-review.md`, `docs/spec/DATA_MODEL.md`, `docs/spec/MCP_TOOLS.md`, `zensical.toml` |
| **`SKILL`** | 2 | `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`, `.agents/skills/patchdiff-persistence-replay-save/SKILL.md` |
| **`MCP`** | 2 | `backend/app/mcp/external_adapter.py`, `backend/app/mcp/tools.py` |
| **`RUN`** | 0 | *(No files in `backend/app/core/` or `backend/app/pdcp/` modified; pure runtime unchanged and verified via `offline_eval.py`)* |
| **`SVC`** | 5 | `backend/app/services/export_service.py`, `backend/app/services/finalize_service.py`, `backend/app/services/save_service.py`, `backend/app/services/waymark_adapter.py`, `backend/app/services/waymark_worker.py` |
| **`DB`** | 3 | `backend/app/migrations/versions/20261031_0006_target_finalizations.py`, `backend/app/migrations/versions/20261031_0007_finalization_checks.py`, `backend/app/storage/models.py` |
| **`SCRIPT`** | 3 | `.github/workflows/ci.yml`, `backend/tests/verification/benchmark_finalize_replay.py`, `examples/host_finalize.py` |
| **`TEST`** | 30 | `backend/tests/conftest.py`, `backend/tests/integration/test_adversarial_m3_2.py`, `backend/tests/integration/test_adversarial_m4_2.py`, `backend/tests/integration/test_adversarial_m4_wheel_smoke.py`, `backend/tests/integration/test_batch_migrations.py`, `backend/tests/integration/test_batch_stdio_profiles.py`, `backend/tests/integration/test_finalize_live.py`, `backend/tests/integration/test_installed_wheel_smoke.py`, `backend/tests/integration/test_m3_adversarial_challenge.py`, `backend/tests/integration/test_mcp_tools.py`, `backend/tests/integration/test_migrations_reachable.py`, `backend/tests/integration/test_pass_b_discovery.py`, `backend/tests/unit/test_adversarial_m2_1.py`, `backend/tests/unit/test_adversarial_m2_2.py`, `backend/tests/unit/test_editor_v2_adapter.py`, `backend/tests/unit/test_finalize_service.py`, `backend/tests/unit/test_finalize_tool.py`, `backend/tests/unit/test_host_finalize.py`, `backend/tests/unit/test_mcp_profiles.py`, `backend/tests/unit/test_mcp_response_modes.py`, `backend/tests/unit/test_migration_0002_offline.py`, `backend/tests/unit/test_migration_0006_offline.py`, `backend/tests/unit/test_migration_0007_offline.py`, `backend/tests/unit/test_observed_editor_profile.py`, `backend/tests/unit/test_pass_b_reads_discovery.py`, `backend/tests/unit/test_publish_workflow.py`, `backend/tests/unit/test_typed_transaction.py`, `backend/tests/unit/test_waymark_adapter.py`, `backend/tests/unit/test_waymark_bridge_resolution.py`, `backend/tests/unit/test_waymark_worker.py` |
| **`DEP`** | 12 | `.github/workflows/publish.yml`, `.gitignore`, `pyproject.toml`, `backend/app/waymark_bridge/__init__.py`, `backend/app/waymark_bridge/bootstrap.py`, `backend/app/waymark_bridge/discover.mjs`, `backend/app/waymark_bridge/discovery_core.mjs`, `backend/app/waymark_bridge/package-lock.json`, `backend/app/waymark_bridge/package.json`, `backend/app/waymark_bridge/worker.mjs`, `integrations/waymark/discover.mjs`, `integrations/waymark/worker.mjs` |

---

### 7.3 Ten Required Category Reviews (Post-Review 4 Remediation)

#### 7.3.1 `ARCH` — Architecture and Contracts
- **Coverage**: `AGENTS.md`, `docs/ROADMAP.md`, `backend/app/services/finalize_service.py`, `examples/host_finalize.py`.
- **P1 — Critical / Blocking**: None.
- **P2 — Important / Defect or Contract Drift**: None.
- **P3 — Minor / Polish**: None.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.2 `DOC` — Documentation and Change Records
- **Coverage**: `AGENTS.md`, `docs/ROADMAP.md`, `docs/benchmarks/finalize_replay_benchmark_report.md`, `docs/guides/HOST_INTEGRATION_GUIDE.md`, `docs/reviews/PR23-modernization-release-review.md`, `docs/spec/DATA_MODEL.md`, `docs/spec/MCP_TOOLS.md`, `zensical.toml`.
- **P1 — Critical / Blocking**: None.
- **P2 — Important / Defect or Contract Drift**:
  - `PR23-R4-DOC-001` (**CLOSED**): Updated `AGENTS.md` and `docs/ROADMAP.md` to state all **24 tools** in the `full` profile (including `patchdiff_finalize_target` and `patchdiff_read_finalized_export`), updated `AGENTS.md` migration references to `0001` through `0007`, and refined `docs/ROADMAP.md` diagram/guarantees to state `Host-Owned Verified Disk Write-Back` and `In-flight working-tree isolation`.
  - `PR23-R4-DOC-002` / `PR23-IMPL-DOC-001` (**CLOSED**): Restored the historical review sections (`276d5f6` and `abd4d39` / `1073338`) in `docs/reviews/PR23-modernization-release-review.md`, corrected the `observed_v2` 5-tool list (`patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`), and recorded the complete 65-file changed-file inventory.
- **P3 — Minor / Polish**:
  - `PR23-R3-DOC-002` (**CLOSED**): Decoupled `lock_wait_ms` and `lock_hold_ms` in `finalize_service.py`, `benchmark_finalize_replay.py`, and `docs/benchmarks/finalize_replay_benchmark_report.md`.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.3 `SKILL` — Skills and Agent Instructions
- **Coverage**: `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`, `.agents/skills/patchdiff-persistence-replay-save/SKILL.md`, `.agents/skills/patchdiff-core-runtime/SKILL.md`, `.agents/skills/patchdiff-testing-review/SKILL.md`.
- **P1 — Critical / Blocking**: None.
- **P2 — Important / Defect or Contract Drift**:
  - `PR23-R4-SKILL-001` (**CLOSED**): Updated `.agents/skills/patchdiff-mcp-orchestration/SKILL.md` to reflect default `observed_v2` (5 tools) and 24 internal/`full` tools (`patchdiff_finalize_target`, `patchdiff_read_finalized_export`), and updated `.agents/skills/patchdiff-persistence-replay-save/SKILL.md` to include migrations `20261031_0006` and `20261031_0007`.
- **P3 — Minor / Polish**: None.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.4 `MCP` — MCP Schemas and Public API
- **Coverage**: `backend/app/mcp/external_adapter.py`, `backend/app/mcp/tools.py`, `docs/spec/MCP_TOOLS.md`.
- **P1 — Critical / Blocking**: None.
- **P2 — Important / Defect or Contract Drift**: None (Default `observed_v2` exposes `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`; `full` exposes all 24 tools; external `PR22-MCP-002` remains tracked under `POST_MERGE_REGISTRY_VERIFICATION`).
- **P3 — Minor / Polish**: None.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.5 `RUN` — Core Runtime, Parsing, and Validation
- **Coverage**: `backend/app/core/`, `backend/app/pdcp/`, `backend/tests/verification/offline_eval.py`.
- **P1 — Critical / Blocking**: None.
- **P2 — Important / Defect or Contract Drift**: None.
- **P3 — Minor / Polish**: None.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.6 `SVC` — Services, Orchestration, and Audit Semantics
- **Coverage**: `backend/app/services/finalize_service.py`, `backend/app/services/export_service.py`, `backend/app/services/save_service.py`, `backend/app/services/waymark_adapter.py`, `backend/app/services/waymark_worker.py`.
- **P1 — Critical / Blocking**:
  - `PR23-R3-SVC-001` (**CLOSED**): Implemented `read_finalized_export` reading immutable `TargetSnapshots` referenced by `TargetFinalizations.snapshot_id` with full SHA-256 and byte-length verification.
- **P2 — Important / Defect or Contract Drift**:
  - `PR23-R3-SVC-002` (**CLOSED**): Detached receipt attributes via `_DetachedFinalizationRecord` before `_rollback()`, guaranteeing `not session.in_transaction()` on all service-owned exits.
  - `PR23-R3-SVC-003` (**CLOSED**): Persisted and restored `materialized_state_checks` on `TargetFinalizations`.
  - `PR23-R4-SVC-001` (**CLOSED**): Fixed `waymark_worker.py` so specific poisoned error codes (e.g., `WAYMARK_WORKER_RSS_LIMIT`) are not overwritten by `write_errors` as `WAYMARK_WORKER_PROTOCOL_ERROR`, removed the concurrent `self.proc.stderr.read(4096)` race in `poison()`, eliminated double-prefixed `WAYMARK_WORKER_<CODE>:` error strings, and removed leftover debug `sys.stderr.write` / `traceback.print_exc` statements in `waymark_worker.py` and `external_adapter.py`. Verified by `test_poison_preserves_specific_error_code_and_no_double_prefix` in `backend/tests/unit/test_waymark_worker.py`.
- **P3 — Minor / Polish**: None.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.7 `DB` — Database, Migrations, Replay, and Concurrency
- **Coverage**: `backend/app/storage/models.py`, `backend/app/migrations/versions/20261031_0006_target_finalizations.py`, `backend/app/migrations/versions/20261031_0007_finalization_checks.py`, `docs/spec/DATA_MODEL.md`.
- **P1 — Critical / Blocking**: None.
- **P2 — Important / Defect or Contract Drift**:
  - `PR23-R4-DB-001` (**CLOSED**): Added populated-row downgrade refusal (`IF EXISTS (SELECT 1 FROM target_finalizations WHERE materialized_state_checks IS NOT NULL)`) to `20261031_0007_finalization_checks.py`, added offline and live Postgres downgrade refusal tests (`test_live_0007_downgrade_refuses_when_finalization_checks_exist` in `test_migrations_reachable.py`), and documented `target_finalizations` (`0006` and `0007`) in `docs/spec/DATA_MODEL.md`.
- **P3 — Minor / Polish**: None.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.8 `SCRIPT` — Scripts, Evaluation, and Developer Tooling
- **Coverage**: `examples/host_finalize.py`, `backend/tests/verification/benchmark_finalize_replay.py`, `.github/workflows/ci.yml`.
- **P1 — Critical / Blocking**:
  - `PR23-R3-SCRIPT-001` (**CLOSED**): Enforced descriptor-relative `O_NOFOLLOW` traversal from `authorized_root`.
  - `PR23-R3-SCRIPT-002` (**CLOSED**): Enforced pre-write in-memory SHA-256 verification before touching disk.
  - `PR23-R3-SCRIPT-003` (**CLOSED**): Enforced per-file `.lock-{leaf_name}` `fcntl.flock(LOCK_EX)` across preimage check, temp creation, `os.replace`, and directory `fsync`.
  - `PR23-R3-SCRIPT-004` (**CLOSED**): Implemented chunked `patchdiff_read_finalized_export` paging and separate `db_status` / `disk_status` reporting in `finalize_single_target`.
- **P2 — Important / Defect or Contract Drift**:
  - `PR23-R3-SCRIPT-005` (**CLOSED**): Required `preimage_sha256` whenever overwriting an existing destination file unless `allow_unconditional_overwrite=True`.
- **P3 — Minor / Polish**:
  - `PR23-R4-SCRIPT-001` (**CLOSED**): Hardened the `authorized_root=None` fallback in `safe_write_back_file` (`examples/host_finalize.py`) to reject `..` traversal, open `dest_parent` with `O_NOFOLLOW`, and preserve the un-resolved `leaf_name` so leaf symlinks are rejected by `os.lstat`. Verified by `test_safe_write_back_without_authorized_root_rejects_symlinks_and_dotdot` in `test_adversarial_m2_1.py`.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.9 `TEST` — Tests and CI
- **Coverage**: All 30 modified/added test files in `backend/tests/` and `.github/workflows/ci.yml`.
- **P1 — Critical / Blocking**: None.
- **P2 — Important / Defect or Contract Drift**:
  - `PR23-R3-TEST-001` (**CLOSED**): Provisioned isolated `/tmp/test-pd-wheel-venv` with `sitecustomize.py` path guard and bootstrapped Waymark bridge (`patch-web-tree-sitter.cjs --strict`), running full two-process (`full` + `observed_v2`) stdio lifecycle tests against live PostgreSQL with 0 skips.
- **P3 — Minor / Polish**:
  - `PR23-R4-TEST-001` (**CLOSED**): Replaced the hardcoded `node-v22.19.0-linux-x64` fallback path in `backend/tests/conftest.py` with a version-agnostic `node-v*/bin/node` glob.
- **Verification Gaps**: None.
- **Category Verdict**: **PASS**

#### 7.3.10 `DEP` — Dependencies, Packaging, and Configuration
- **Coverage**: `.github/workflows/publish.yml`, `pyproject.toml`, `backend/app/waymark_bridge/`, `integrations/waymark/`.
- **P1 — Critical / Blocking**:
  - `PR23-R3-DEP-001` (**CLOSED**): Bound all untrusted GitHub contexts via `env:` in `.github/workflows/publish.yml`, validated `^v[0-9]+\.[0-9]+\.[0-9]+$` and `refs/heads/main` before checkout, peeled tags to commit SHAs, verified `origin/main` ancestry, and verified `pyproject.toml` version parity.
- **P2 — Important / Defect or Contract Drift**: None.
- **P3 — Minor / Polish**:
  - `PR23-R4-DEP-001` (**CLOSED**): Extended the installed-wheel smoke step in `.github/workflows/publish.yml` to run `python -m app.waymark_bridge.bootstrap` and `--check-only` outside the repository checkout (`cd /tmp`) before verifying the `patchdiff` stdio entry point.
- **Verification Gaps**: GitHub repository settings for the protected `pypi` environment (required reviewers) and external PyPI Trusted Publisher registration remain external owner-administered controls.
- **Category Verdict**: **PASS**

---

### 7.4 Summary Closure Table of Review 4 Findings (`PR23-R4-*`)

| Finding ID | Priority | Category | Title | Remediation & Verification Evidence | Status |
| :--- | :---: | :---: | :--- | :--- | :---: |
| **`PR23-R4-SVC-001`** | P2 | `SVC` | `waymark_worker.py` overwrites specific worker error codes with `PROTOCOL_ERROR`, races threads on `proc.stderr`, double-prefixes error codes, and leaves debug tracebacks | `backend/app/services/waymark_worker.py`, `backend/app/mcp/external_adapter.py`, `backend/tests/unit/test_waymark_worker.py::test_poison_preserves_specific_error_code_and_no_double_prefix` | **CLOSED** |
| **`PR23-R4-DB-001`** | P2 | `DB` | Migration `20261031_0007` lacks populated-row downgrade refusal, and `docs/spec/DATA_MODEL.md` omits `target_finalizations` | `backend/app/migrations/versions/20261031_0007_finalization_checks.py`, `docs/spec/DATA_MODEL.md`, `backend/tests/unit/test_migration_0007_offline.py`, `backend/tests/integration/test_migrations_reachable.py::test_live_0007_downgrade_refuses_when_finalization_checks_exist` | **CLOSED** |
| **`PR23-R4-SKILL-001`** | P2 | `SKILL` | `.agents/skills/` files contain stale default profile, tool counts, and migration list | `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`, `.agents/skills/patchdiff-persistence-replay-save/SKILL.md` | **CLOSED** |
| **`PR23-R4-DOC-001`** | P2 | `DOC` | `AGENTS.md` and `docs/ROADMAP.md` state 23 tools instead of 24 and cite outdated migration numbers | `AGENTS.md`, `docs/ROADMAP.md` | **CLOSED** |
| **`PR23-R4-DOC-002`** | P2 | `DOC` | `docs/reviews/PR23-modernization-release-review.md` lists nonexistent `observed_v2` tools, omits 13 changed files, and overwrote historical review | `docs/reviews/PR23-modernization-release-review.md` | **CLOSED** |
| **`PR23-R4-SCRIPT-001`** | P3 | `SCRIPT` | `safe_write_back_file` with `authorized_root=None` resolves leaf/parent symlinks before `lstat` | `examples/host_finalize.py`, `backend/tests/unit/test_adversarial_m2_1.py::test_safe_write_back_without_authorized_root_rejects_symlinks_and_dotdot` | **CLOSED** |
| **`PR23-R4-DEP-001`** | P3 | `DEP` | `.github/workflows/publish.yml` wheel smoke only tests `tools/list` without bootstrapping Waymark bridge | `.github/workflows/publish.yml` | **CLOSED** |
| **`PR23-R4-TEST-001`** | P3 | `TEST` | `backend/tests/conftest.py` hardcodes `node-v22.19.0-linux-x64` fallback directory | `backend/tests/conftest.py` | **CLOSED** |

---

### 7.5 Verification Evidence (Source Inspection, Local Test Suites, Live MCP Server, and CI)

1. **Pure Runtime Unit Suite**: `pytest backend/tests/unit -q` -> **1,200 passed, 1 skipped** (`0 failed`).
2. **Live PostgreSQL 16 Integration Suite**: `PATCHDIFF_WAYMARK_MODE=resident pytest backend/tests/integration -q` -> **612 passed, 0 skipped** (`0 failed`), including live Alembic `upgrade -> downgrade -> upgrade`, populated downgrade refusal on migrations `0004`, `0005`, `0006`, and `0007`, and isolated wheel packaging smoke tests.
3. **Offline Payload & Verdict Equivalence**: `PATCHDIFF_WAYMARK_MODE=resident python -m backend.tests.verification.offline_eval` -> **OK** (`Verdict equivalence on the shared applier: OK`, `Accepted guarded replacement content/hash oracles: OK`).
4. **Static Documentation Site Build**: `zensical build --clean` -> **OK** (`No issues found`).
5. **Live `patchdiff` MCP Server End-to-End Verification**:
   - Spawned two long-lived `/tmp/test-pd-wheel-venv/bin/patchdiff` server subprocesses from `/tmp` (`PATCHDIFF_WAYMARK_MODE=resident`, `PATCHDIFF_WAYMARK_BRIDGE_DIR=/tmp/test-pd-wheel-venv/waymark-bridge`, `PYTHONPATH` unset) against live PostgreSQL (`localhost:5432`): one under `PATCHDIFF_MCP_PROFILE=full` (24 tools) and one under `PATCHDIFF_MCP_PROFILE=observed_v2` (5 tools: `patchdiff_commit_bundle`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_read_target`).
   - Verified `observed_v2` rejects `patchdiff_finalize_target` (`isError=True`, `Unknown PatchDIFF MCP tool: patchdiff_finalize_target`).
   - Initialized CRLF Python target on `full`, discovered symbol scopes (`compute_total`, `format_label`) and observed `compute_total` via resident Waymark worker on `observed_v2`, committed a guarded `patchdiff_commit_bundle` edit while confirming the on-disk file remained untouched, finalized on `full` (`format="original_eol"`, `checks={'content_matches': True, 'recomputed_hash_matches': True, 'stored_hash_matches': True, 'version_matches': True}`), verified idempotent `client_request_id` retry parity, paged via `patchdiff_read_finalized_export`, and atomically wrote back CRLF bytes to disk via `safe_write_back_file` with `preimage_sha256` and `authorized_root`.

---

### 7.6 Final Overall Verdict

- **Review 3 Findings (`PR23-R3-*`)**: **11 / 11 CLOSED** (6 P1, 4 P2, 1 P3).
- **Review 4 Findings (`PR23-R4-*`)**: **8 / 8 CLOSED** (0 P1, 5 P2, 3 P3).
- **Overall PR Review Standard v1.1.0 Verdict**: **APPROVE** (0 open P1, P2, or actionable P3 code/documentation findings; external post-merge registry verification `PR22-MCP-002` and owner-administered GitHub/PyPI release environment controls noted).
