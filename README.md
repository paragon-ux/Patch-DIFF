# PatchDIFF

PatchDIFF is an MCP-first, server-side deterministic document transaction service.

PatchDIFF receives document-upload, read/search, and edit-submission requests over MCP, manages canonical target state in Postgres, validates untrusted edit transactions deterministically, applies accepted edits atomically per target, logs all accepted and rejected attempts in an append-only log with retry lineage and request idempotency, records accepted changes in an append-only manifest ledger with runtime-derived span/hash facts, and supports SAVE checkpointing, export, and deterministic replay.

The host/chatbot owns planning, context selection, proposal generation, and retries. PatchDIFF owns authoritative document state, validation, and atomic commits.

This update adds guarded span edits and explicit whole-target replacement, bounded line reads, a keyless advisory preview, and structured rejection evidence. Existing accepted history keeps its recorded semantics. See the [release notes](CHANGELOG.md), [release checklist](docs/RELEASE_READINESS.md) and [security policy](SECURITY.md).

```text
PatchDIFF server = deterministic transaction runtime + authoritative read/commit service
MCP = transport/interface (stdio JSON-RPC / internal registry)
Host / Chatbot / Model = planning, context selection, proposal generator, retry owner
Postgres = canonical working substrate
```

PatchDIFF is not a chat UI, rich document editor, semantic patch language, AST rewrite engine, fuzzy matcher, automatic merge system, or full-document regeneration workflow.

## Prerequisites

- Python 3.11+
- Docker Desktop with Docker Compose
- PowerShell on Windows (or bash on Linux/macOS)

## Quick Setup

From the repo root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
docker compose up -d postgres
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```

The FastAPI server runs at `http://127.0.0.1:8000` (used for health checks and HTTP APIs). The primary interface for external MCP clients (such as Claude Desktop) is the stdio MCP adapter.

For MCP-only use, stop after migrations and configure the host below; Uvicorn is optional. Compose publishes PostgreSQL on `127.0.0.1:5432` only. The example database password is for isolated local development; see [SECURITY.md](SECURITY.md) before using real data or another deployment.

## Configuration

By default, the app connects to the local Docker Compose Postgres instance:

```text
postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff
```

Override it with:

```powershell
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff"
```

## Database Migrations

Start Postgres:

```powershell
docker compose up -d postgres
```

Run migrations (`20260510_0001` and `20261020_0002`):

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

## Health Checks

With FastAPI running:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

- `/health/live` verifies the FastAPI app process is responsive.
- `/health/ready` verifies Postgres is reachable and responsive.

## External MCP Adapter Setup (Claude Desktop)

PatchDIFF exposes a stdio JSON-RPC MCP adapter for external MCP hosts such as Claude Desktop.

The adapter process uses strict UTF-8 for stdin/stdout, including Windows pipes, independently of the locale or PYTHONIOENCODING setting. Older revisions require PYTHONIOENCODING=utf-8 in the server environment to avoid misdecoding literal Unicode requests. See [the setup guide](docs/CLAUDE_DESKTOP_SETUP.md) for transport and restart guidance.

Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "patchdiff": {
      "type": "stdio",
      "command": "C:\\path\\to\\Patch-DIFF\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp.external_adapter"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\Patch-DIFF\\backend",
        "PATCHDIFF_DATABASE_URL": "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff"
      }
    }
  }
}
```

Quick stdio smoke check from the repo root:

```powershell
$env:PYTHONPATH = "backend"
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | .\.venv\Scripts\python.exe -m app.mcp.external_adapter
```

Expected response includes:

```json
{
  "serverInfo": {
    "name": "patchdiff-mvp"
  }
}
```

See [docs/CLAUDE_DESKTOP_SETUP.md](docs/CLAUDE_DESKTOP_SETUP.md) for full setup guidance.

## MCP Tool Surface

- **Document Lifecycle**: `patchdiff_handle_upload`, `patchdiff_initialize_target`, `patchdiff_get_target`, `patchdiff_export_target`
- **Authoritative Reads & Exact Search**: `patchdiff_read_target` (bounded slices with `next_start`), `patchdiff_read_lines` (inclusive LF ranges with `next_offset`), `patchdiff_find_occurrences` (exact spans with context and pagination)
- **Guarded Submission**: `patchdiff_submit_edits` (`patchdiff-tx/1`), `patchdiff_submit_operations` (sequential match/span edits, `patchdiff-tx/2`), `patchdiff_submit_replacement` (sole explicit whole-target replacement, `patchdiff-tx/3`), `patchdiff_submit_pdcp` (legacy `.pdcp` format)
- **Checkpoints, Replay & History**: `patchdiff_save` (editing cycle rotation), `patchdiff_replay` (deterministic profile-dispatched reconstruction), `patchdiff_get_pdcp_log` (bounded attempt log), `patchdiff_get_manifest_ledger` (accepted changes with runtime facts)
- **Advisory Preview & Legacy Compatibility**: `patchdiff_preview` (bounded verdict/facts without audit, keys or target mutation); `patchdiff_build_prompt_context` (bounded prefix convenience), and deprecated `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`

See [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) and [docs/HOST_INTEGRATION_GUIDE.md](docs/HOST_INTEGRATION_GUIDE.md).

Discovery advertises 20 tools and 13 executable examples across nine tools. Bind examples to actual target IDs, guards, rejection parents and returned cursors. A preview does not reserve state: subsequent submission must recheck a version or hash guard. Span and whole-target replacement always require a guard; a version guard also detects intervening no-op/ABA edits. Correlation IDs are opt-in invocation metadata, separate from caller-known retry keys.

## Testing & Offline Evaluation

Run unit and integration tests against live Postgres:

```powershell
# Unit tests (pure runtime)
.\.venv\Scripts\python.exe -m pytest backend/tests/unit -q

# Integration tests (live Postgres & real stdio subprocess)
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
.\.venv\Scripts\python.exe -m pytest backend/tests/integration -q

# Offline evaluation (payload bytes and applier verdict equivalence)
.\.venv\Scripts\python.exe evaluation/offline_eval.py
```

## Project Layout

```text
backend/app/api          FastAPI health and HTTP API routes
backend/app/core         Pure deterministic runtime primitives, version profiles, validity stages
backend/app/pdcp         Declarative typed and PDCP parsers, matcher, disambiguator, applier
backend/app/services     Authoritative services (submit, read, search, save, replay, export)
backend/app/storage      SQLAlchemy models, database session management, migrations
backend/app/mcp          MCP tool definitions, internal registry, and external stdio adapter
backend/app/migrations   Alembic migration versions (0001 initial, 0002 typed ledger)
backend/tests            Unit tests and live Postgres integration tests
evaluation               Offline payload and verdict equivalence evaluation harness
docs                     Modernized architecture, core spec, data model, tool contracts, guides
```

## Reference Documentation

Read in order of precedence:

1. `AGENTS.md` (locked architectural invariants)
2. `docs/MODERNIZATION_ARCHITECTURE.md` (architectural decisions A1–A8 and contracts C1–C6)
3. `docs/MODERNIZATION_CHANGE_DOC.md` (current product change record: formats, compatibility and verification scope)
4. `docs/MCP_TOOLS.md` (MCP tool contracts and schemas)
5. `docs/PATCHDIFF_CORE_SPEC.md` (deterministic core runtime specification)
6. `docs/DATA_MODEL.md` (Postgres schema and migrations `0001` + `0002`)
7. `docs/PDCP_FORMAT.md` (`patchdiff-tx/1`, guarded operations `patchdiff-tx/2`, sole replacement `patchdiff-tx/3`, legacy `.pdcp`)
8. `docs/HOST_INTEGRATION_GUIDE.md` (host-owned loop, reads, guards, retries, and failure handling)
9. `docs/TEST_MATRIX.md` & `docs/CODEX_BUILD_PLAN.md`

## License

[MIT](LICENSE), selected by the repository owner. Third-party packages retain their own licenses; the release checklist records dependency and security review limits.
