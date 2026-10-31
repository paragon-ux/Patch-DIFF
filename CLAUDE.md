# CLAUDE.md

This file provides guidance for Claude Code and AI assistants operating in the PatchDIFF repository.

---

## 1. Source of Truth & Precedence

When working in this repository, always consult documentation in the following order of precedence:

1. `AGENTS.md` (locked architectural invariants)
2. `docs/papers/MODERNIZATION_ARCHITECTURE.md` (architectural decisions A1–A8, contracts C1–C6)
3. `docs/papers/MODERNIZATION_CHANGE_DOC.md` (product change record and verification scope)
4. `docs/spec/MCP_TOOLS.md` (MCP tool contracts, schemas, byte budgets)
5. `docs/spec/PATCHDIFF_CORE_SPEC.md` (deterministic core runtime specification)
6. `docs/spec/DATA_MODEL.md` (Postgres schema and migrations `20260510_0001` through `20261027_0005`)
7. `docs/spec/PDCP_FORMAT.md` (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`)
8. `docs/spec/MCP_EDITOR_V2.md` (streamlined 5-tool `observed_v2` profile)
9. `docs/spec/STRUCTURAL_BATCH_EDITING.md` (structural observation and batch transactions)
10. `docs/guides/HOST_INTEGRATION_GUIDE.md` (host loop, reads, retries, and failure handling)
11. `docs/standards/PR_REVIEW_STANDARD.md` (PR review standard v1.1.0)
12. `docs/benchmarks/modernized_benchmark_report.md` (certified empirical benchmark results)

---

## 2. Core Architectural Invariants

PatchDIFF is a deterministic transaction monitor, not an agent or editor UI. Always preserve:
- Pure deterministic core runtime (`backend/app/core/`, `backend/app/pdcp/`).
- Canonical UTF-8 target text (LF normalized).
- Declarative non-executable transactions (`patchdiff-tx/1`, `tx/2`, `tx/3`, legacy `.pdcp` v0.2.3).
- Exact deterministic MATCH (enumerating all occurrences).
- Sequential in-memory REPLACE simulation.
- Per-target atomic commit under PostgreSQL `SELECT ... FOR UPDATE`.
- Append-only attempt log (`append_only_pdcp_logs`) recording accepted and rejected attempts with idempotency and retry lineage.
- Accepted-only manifest ledger (`append_only_manifest_ledger`) with runtime-derived span/hash facts.
- Deterministic profile-dispatched replay (`patchdiff_replay`).

---

## 3. Common Development Commands

### Environment Setup
```bash
source .venv/bin/activate  # Or Windows: .\.venv\Scripts\Activate.ps1
export PYTHONPATH=".:backend"
```

### Database & Migrations
```bash
docker compose up -d postgres
alembic -c backend/app/migrations/alembic.ini upgrade head
```

### Running Tests
```bash
# Pure runtime unit tests (1,020 tests)
pytest backend/tests/unit -q

# Live Postgres integration tests (561 tests)
export PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
pytest backend/tests/integration -q

# Offline evaluation (payload bytes and applier verdict equivalence)
python backend/tests/verification/offline_eval.py

# Structural batch five-file verification
python backend/tests/verification/structural_batch/verify.py --editor-v2 --host-finalize
```

---

## 4. MCP Server Profiles

External MCP supports startup profile configuration via `PATCHDIFF_MCP_PROFILE`:
- `editor` (default, 7 tools): `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_edits`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay`.
- `observed_v2` (5 tools): `patchdiff_list_scopes`, `patchdiff_find_occurrences`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`, `patchdiff_read_target`.
- `hybrid_editor` (1 tool): `patchdiff_submit_edits`.
- `observed_editor` (4 tools): delegated editing without lifecycle calls.
- `unobserved` (5 tools)
- `observed` (6 tools)
- `full` (22 tools): explicit compatibility profile.
