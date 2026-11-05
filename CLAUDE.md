# CLAUDE.md

This file provides guidance for Claude Code and AI assistants operating in the PatchDIFF repository.

---

## 1. Source of Truth & Precedence

When working in this repository, always consult documentation in the following order of precedence:

1. `AGENTS.md` (locked architectural invariants)
2. `docs/papers/modernization-architecture.md` (architectural decisions A1–A8, contracts C1–C6)
3. `docs/papers/product-change-record.md` (product change record and verification scope)
4. `docs/spec/mcp-tools.md` (MCP tool contracts, schemas, byte budgets)
5. `docs/spec/core-runtime.md` (deterministic core runtime specification)
6. `docs/spec/data-model.md` (Postgres schema and migrations `20260510_0001` through `20261105_0006`)
7. `docs/spec/transaction-formats.md` (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`)
8. `docs/spec/profiles/index.md` (startup selection and profile contracts)
9. `docs/spec/structural-batch-editing.md` (structural observation and batch transactions)
10. `docs/guides/host-integration-guide.md` (host loop, reads, retries, and failure handling)
11. `docs/standards/pr-review-standard.md` (PR review standard v1.1.0)
12. `docs/benchmarks/workspace-e2e-benchmark.md` (current comparative results and independent verification; the modernization benchmark is historical evidence)

---

## 2. Core Architectural Invariants

PatchDIFF is a deterministic transaction monitor, not an agent or editor UI. Always preserve:
- Pure deterministic core runtime (`backend/app/core/`, `backend/app/pdcp/`).
- Canonical UTF-8 target text (LF normalized).
- Declarative non-executable transactions (`patchdiff-tx/1`, `tx/2`, `tx/3`).
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
# Pure runtime unit tests
pytest backend/tests/unit -q

# Live Postgres integration tests
export PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
pytest backend/tests/integration -q

# Offline evaluation (payload bytes and applier verdict equivalence)
python backend/tests/verification/offline_eval.py

# Structural batch five-file verification
python backend/tests/verification/structural_batch/verify.py --editor-v2 --host-finalize
```

---

## 4. MCP Server Profiles

Choose the external MCP tool catalog with `PATCHDIFF_MCP_PROFILE`. See the
[profile reference](docs/spec/profiles/index.md) for exact tool lists and
[workspace startup](docs/spec/profiles/workspace-profile.md) for file editing.
