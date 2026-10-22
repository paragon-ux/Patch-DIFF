---
name: patchdiff-testing-review
description: "Use when adding tests, reviewing implementation, verifying completion, or auditing for PatchDIFF protocol and MCP-first architectural consistency."
---

# PatchDIFF Testing and Review Skill

## Verification Standards

Do not claim completion unless verification passes against live Postgres.

PatchDIFF verification spans four rigorous layers:

1. **Pure Unit Tests (`backend/tests/unit/`)**:
   - Matcher, disambiguator, and sequential applier.
   - Equivalence of `patchdiff-tx/1` typed records and `.pdcp` v0.2.3 on the shared applier.
   - Version profile resolution (`SUPPORTED_RUNTIME_PROFILES`).
   - Stage-aware validity level computation (`ValidationStage` -> 4 levels).
   - Stdio adapter JSON-RPC protocol compliance (e.g., `-32602` on invalid params).
   - Offline Alembic migration rendering and downgrade safety checks.
2. **Postgres Integration Tests (`backend/tests/integration/`)**:
   - Full tool workflows via internal registry against live Postgres.
   - Concurrency guards, row-level locking (`SELECT ... FOR UPDATE`), and stale version/hash rejections.
   - Request idempotency via `client_request_id` (safe retry after commit, replay response caching, conflict rejection on changed parameters).
   - Live Alembic migration verification: full `0001 -> 0002 -> 0001 -> 0002` upgrade/downgrade cycle, and data-loss prevention guard when typed ledger rows exist.
   - Deterministic replay with `materialized_state_checks` verification.
3. **External Stdio MCP Subprocess Tests (`backend/tests/integration/test_external_mcp_e2e.py`)**:
   - Launches `backend/app/mcp/external_adapter.py` as a real OS child process over stdin/stdout pipes.
   - Executes full multi-turn editing workflows (`patchdiff_initialize_target` -> `patchdiff_read_target` -> `patchdiff_submit_edits` -> `patchdiff_save` -> `patchdiff_replay` -> `patchdiff_export_target`).
   - Verifies JSON-RPC 2.0 framing, `tools/list` schema advertising, and error handling.
4. **Offline Evaluation (`evaluation/offline_eval.py`)**:
   - Evaluates byte overhead and applier verdict equivalence across 5 canonical scenarios:
     1. 1 tiny edit
     2. 5 small edits
     3. 1 edit, 2 KB span
     4. Quotes, backslashes, and Unicode
     5. Payload containing a literal delimiter line (`<<<<<<< MATCH`)
   - Reports exact UTF-8 byte sizes for persisted records (`pdcp_content`) and wire MCP tool arguments.
   - Confirms verdict equivalence between formats on the shared applier.

## How To Run Tests

```powershell
# 1. Pure unit tests
.\.venv\Scripts\python.exe -m pytest backend/tests/unit -q

# 2. Live Postgres integration tests (Postgres running on localhost:5432)
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
.\.venv\Scripts\python.exe -m pytest backend/tests/integration -q

# 3. Full test suite
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
.\.venv\Scripts\python.exe -m pytest -q

# 4. Offline evaluation
.\.venv\Scripts\python.exe evaluation/offline_eval.py
```

## Review Checklist

When reviewing PatchDIFF code or documentation, audit against these invariants:

- [ ] **Core Purity**: Core runtime files (`backend/app/core/`, `backend/app/pdcp/`) must have zero imports of FastAPI, SQLAlchemy, Postgres, MCP, or LLM SDKs.
- [ ] **Language Neutrality**: Matcher and applier treat text as exact character sequences (LF-normalized UTF-8); no AST, language heuristics, or fuzzy matching.
- [ ] **Overlapping Matches**: In `patchdiff-mvp-0.2.2`, string search finds all exact occurrences including overlaps; legacy non-overlapping is preserved under `patchdiff-mvp-0.1.0`.
- [ ] **Singleton Selectors**: Current 0.2.2 enforces every selecting constraint for single and repeated matches; all historical profiles preserve ignored singleton selectors. Test typed/legacy and intermediate buffers plus real PostgreSQL/stdio rejection.
- [ ] **Sequential In-Memory Simulation**: Edits apply sequentially to in-memory buffers; intermediate state transitions are verified; `change_facts` are emitted.
- [ ] **Per-Target Atomic Commit**: Commits occur under `SELECT ... FOR UPDATE`; all edits apply or none do; no cross-target transactions.
- [ ] **Append-Only Lineage**: Every attempt logs to `append_only_pdcp_logs`; rejected attempts preserve failure reasons; retry attempts track `parent_pdcp_log_id`.
- [ ] **Request Idempotency**: `client_request_id` prevents duplicate application, returns cached responses with `deduplicated: true`, and rejects fingerprint conflicts.
- [ ] **Manifest Ledger**: Records accepted edits only, sets `origin` (`'typed'` or `'pdcp_manifest'`), and populates `derived_json` with runtime facts.
- [ ] **Stage-Aware Validity**: Reports four levels (`protocol_valid`, `transaction_valid`, `task_correct`, `semantic`). `task_correct` and `semantic` must always be `"not_evaluated"`.
- [ ] **Deterministic Replay**: Dispatches on `(protocol_version, runtime_version)` profiles; verifies initial snapshot hash, per-log content hash, and returns `materialized_state_checks`.
- [ ] **Documentation Coherence**: Main body of all active documents reflects modernized contracts; no contradictory "Modernization amendment" footers remain.

## Reporting Work

When reporting completion, be concise and provide concrete proof:

```text
Implemented / Remediated X.

Changed:
- path/to/file.py
- docs/FILE.md

Verified:
- Unit tests: N passed
- Integration tests: N passed (live Postgres)
- Subprocess E2E: passed
- Offline eval: passed (verdict equivalence verified)
```

## Goal F additions

When testing or reviewing Goal F behavior, cover:

- tx/2 spans: sequential coordinates, insertion, CRLF `expected_text`, out-of-bounds and mismatch atomicity, selectors and boolean coordinates rejected, profile gates and replay.
- tx/3: inclusive admission boundaries, recovery/conflict before admission, empty replacement, replay without limits.
- Preview: verdicts identical to submission, zero managed-table changes, no blocking on a locked row, budget and omission metadata.
- Diagnostics: failure versus current context, intermediate-buffer labeling, exact-key recovery, near misses only after a service-owned commit, banded near-miss results equal to an unbanded Levenshtein reference.
- Discovery: every advertised example executed over real stdio and PostgreSQL; capability metadata equal to the runtime constants.
