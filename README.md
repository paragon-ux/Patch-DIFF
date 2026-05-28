# PatchDIFF MVP

PatchDIFF MVP is an MCP-first, server-side document editing backend.

The backend receives upload and edit events through MCP orchestration, stores canonical target state in Postgres, validates declarative `.pdcp` transactions deterministically, commits accepted edits atomically, logs accepted and rejected attempts, and supports SAVE, export, and replay.

The MVP does not include a frontend or chat UI. The intended user surface is a chatbot/model that emits declarative `.pdcp` content, while PatchDIFF owns validation, persistence, and deterministic application.

## Prerequisites

- Python 3.11+
- Docker Desktop with Docker Compose
- PowerShell on Windows

## Quick Setup

From the repo root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
docker compose up -d postgres
alembic -c backend/app/migrations/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```

The API will run at:

```text
http://127.0.0.1:8000
```

## Configuration

By default, the app connects to the local Docker Compose Postgres instance:

```text
postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff
```

Override it with:

```powershell
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff"
```

## Database

Start Postgres:

```powershell
docker compose up -d postgres
```

Run migrations:

```powershell
alembic -c backend/app/migrations/alembic.ini upgrade head
```

Stop Postgres:

```powershell
docker compose stop postgres
```

## Health Checks

With the server running:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

- `/health/live` verifies the FastAPI app is running.
- `/health/ready` verifies Postgres is reachable.

## External MCP Adapter Setup

PatchDIFF exposes a stdio JSON-RPC MCP adapter for external MCP hosts such as Claude Desktop.

The adapter is intentionally thin:

- It uses `backend/app/mcp/external_adapter.py` as the transport boundary.
- It delegates tool behavior to the existing internal MCP registry/wrapper layer.
- It does not directly mutate target content or bypass deterministic PDCP validation.
- It still requires Postgres because target state, logs, SAVE, and replay are persisted there.

Full Claude Desktop setup instructions live in [docs/CLAUDE_DESKTOP_SETUP.md](docs/CLAUDE_DESKTOP_SETUP.md).

Start Postgres and run migrations before connecting an MCP host:

```powershell
docker compose up -d postgres
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

Claude Desktop server config:

```json
{
  "mcpServers": {
    "patchdiff": {
      "type": "stdio",
      "command": "C:\\Users\\USER\\Desktop\\Frameworks\\Patch-DIFF\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp.external_adapter"],
      "env": {
        "PYTHONPATH": "C:\\Users\\USER\\Desktop\\Frameworks\\Patch-DIFF\\backend",
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

Primary MCP tools exposed through the adapter:

```text
patchdiff_handle_upload
patchdiff_initialize_target
patchdiff_build_prompt_context
patchdiff_submit_pdcp
patchdiff_get_regeneration_context
patchdiff_build_regeneration_prompt
patchdiff_request_regeneration
patchdiff_get_target
patchdiff_export_target
patchdiff_save
patchdiff_replay
patchdiff_get_pdcp_log
patchdiff_get_manifest_ledger
```

Internal registry usage for local debugging lives in [README_INTERNAL_MCP.md](README_INTERNAL_MCP.md).

## Tests

Run the full suite:

```powershell
py -3 -m pytest
```

Run subsets:

```powershell
py -3 -m pytest backend\tests\unit
py -3 -m pytest backend\tests\integration
```

Integration tests expect Postgres to be available through Docker Compose. SQLite is not used for MVP persistence correctness.

## ChatGPT Manual PDCP Output Tip

When asking ChatGPT to generate `.pdcp` content, request the output inside a literal Markdown code block.

Recommended wording:

```text
Return the result as a Markdown code block containing literal plain text.
Do not use Markdown quote formatting.
Do not escape the delimiters.
Do not add spaces inside delimiter lines.
The delimiter lines must be exactly:

<<<<<<< MATCH
=======
>>>>>>> REPLACE
```

---

## Project Layout

```text
backend/app/api          FastAPI health/API wiring
backend/app/core         Deterministic shared primitives
backend/app/pdcp         Declarative PDCP parser, validator, matcher, applier
backend/app/services     Workflow services for submit, SAVE, replay, export, context
backend/app/storage      SQLAlchemy models, sessions, repositories
backend/app/mcp          Internal MCP registry plus external stdio adapter
backend/app/migrations   Alembic migration setup
backend/tests            Unit and Postgres-backed integration tests
docs                     MCP-first build docs and phase prompts
```

## MVP Boundaries

- PDCP files are declarative `.pdcp` transactions, not executable code.
- Target content mutation comes only from accepted `.pdcp` transactions.
- MCP orchestration must submit PDCP through the deterministic validation path.
- Regenerated PDCP is a separate attempt and must be validated from scratch.
- SAVE creates snapshots and editing cycles but does not alter target content.
- Postgres is the MVP persistence backend.

## Reference Docs

Read these first when changing behavior:

```text
AGENTS.md
docs/MCP_FIRST_MVP.md
docs/PATCHDIFF_CORE_SPEC.md
docs/MCP_TOOLS.md
docs/DATA_MODEL.md
docs/PDCP_FORMAT.md
docs/TEST_MATRIX.md
docs/CODEX_BUILD_PLAN.md
```
