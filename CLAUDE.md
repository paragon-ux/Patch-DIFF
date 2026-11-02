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
6. `docs/spec/DATA_MODEL.md` (Postgres schema and migrations `20260510_0001` through `20261101_0008`)
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

### Database Setup & Daemon Lifecycle

Linux/WSL2 setup requires the operator, nonlogin `patchdiff-mcp-agent` service and nonlogin `patchdiff-model` shell as distinct UIDs. Only the operator controls Docker and bootstrap/host secrets; the model has no database secret. Follow [the deployment guide](docs/guides/CLAUDE_DESKTOP_SETUP.md); no same-UID fallback exists.

```bash
# As operator, provision PostgreSQL 16.3 Alpine via Docker Compose on loopback 5433:
patchdiff-mcp-setup
patchdiff-mcp-daemon start
patchdiff-mcp-daemon stop
patchdiff-mcp-daemon restart
patchdiff-mcp-daemon status
```

Setup upgrades through `20261101_0008`. Use `--port` or `PATCHDIFF_POSTGRES_PORT` to change the port. Stop preserves containers and volumes; status is read-only. An already-running external PostgreSQL 16+ database requires three explicit private role URLs and `patchdiff-mcp-setup --external-database`, which runs no Docker or native provisioning. Existing native PGDATA is preserved; see [the migration guide](docs/guides/NATIVE_POSTGRES_MIGRATION.md).

### Running Tests
```bash
# Pure runtime unit tests
pytest backend/tests/unit -q

# Live tests require explicit private credentials against a disposable PostgreSQL 16 database.
PATCHDIFF_WAYMARK_MODE=resident python -m pytest backend/tests/integration -q

# Offline evaluation (payload bytes and applier verdict equivalence)
PATCHDIFF_WAYMARK_MODE=resident python -m backend.tests.verification.offline_eval

# Structural batch five-file verification
PATCHDIFF_WAYMARK_MODE=resident python backend/tests/verification/structural_batch/verify.py --editor-v2 --host-finalize
```

---

## 4. MCP Server Profiles

External MCP supports startup profile configuration via `PATCHDIFF_MCP_PROFILE`:
- `observed_v2` (default, 5 tools): `patchdiff_list_scopes`, `patchdiff_find_occurrences`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`, `patchdiff_read_target`.
- `full` (24 tools): Complete tool surface including `patchdiff_finalize_target` and `patchdiff_read_finalized_export`.
- Legacy compatibility profiles (`editor` [7], `observed` [6], `unobserved` [5], `observed_editor` [4], `unobserved_editor` [3], `hybrid_editor` [1]): Retained for backward compatibility with a once-per-process stderr migration notice.

The `full` process runs as operator using nonsuperuser `patchdiff_host`; the default editor runs as `patchdiff-mcp-agent` using allowlisted `patchdiff_agent`. Bootstrap is confined to migrations. Profiles do not authenticate callers. Finalization binds pre-lock replay to a database-owned history revision and immutable export chunks; filesystem write-back remains a separate cooperative operation in an explicit operator-private root. Post-rename directory fsync failure is `durability_uncertain` and requires reconciliation against the same finalization.
