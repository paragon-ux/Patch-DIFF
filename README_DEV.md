# PatchDIFF backend development

Use this checkout for backend development and verification. To connect an MCP
host to the installed package, follow the [workspace quickstart](docs/guides/workspace-quickstart.md).

## Local Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
npm --prefix integrations/waymark ci
docker compose up -d postgres
alembic -c backend/app/migrations/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```

## Health Checks

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

`/health/live` checks that the FastAPI app is importable and running.
`/health/ready` checks that Postgres is reachable with the configured `PATCHDIFF_DATABASE_URL`.


## Waymark Structural Observation Adapter

Patch-DIFF pins `waymark-engine@4.1.0` inside `integrations/waymark/` (`package.json` and `package-lock.json`).
Install the pinned Node dependency before running unit or integration tests:

```powershell
npm --prefix integrations/waymark ci
```

Enable strict observation to require server-issued scope authority for
writes. Unobserved submissions return `OBSERVATION_REQUIRED`. Start the
server with an [observed profile](docs/spec/profiles/index.md) and set:

```powershell
$env:PATCHDIFF_STRICT_OBSERVATION_MODE = "1"
```
