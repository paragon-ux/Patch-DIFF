# PatchDIFF MVP Backend Development

## Local Setup

PatchDIFF supports two independent PostgreSQL runtime routes with distinct default ports so both can operate simultaneously:
- **`native` (`127.0.0.1:5434`)**: User-space PostgreSQL cluster (`initdb` / `pg_ctl` in `~/.local/share/patchdiff-runtime/pgdata`).
- **`docker` (`127.0.0.1:5433`)**: Docker Compose `patchdiff-postgres` (`postgres:16.3-alpine`) container.

### Automated Setup & Daemon Lifecycle (Recommended)

```bash
python -m venv .venv
source .venv/bin/activate  # Or Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .

# Provision native (5434), docker (5433), or both; runs Alembic upgrade head,
# bootstraps/verifies the Waymark JS bridge, and smoke-tests the MCP stdio adapter:
patchdiff-mcp setup --route both

# Identical daemon lifecycle commands for native, docker, or both:
patchdiff-mcp daemon start   --route <native|docker|both>
patchdiff-mcp daemon stop    --route <native|docker|both>
patchdiff-mcp daemon restart --route <native|docker|both>
patchdiff-mcp daemon status  --route <native|docker|both>
```

### Manual Step-by-Step Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
npm --prefix integrations/waymark ci
docker compose up -d postgres
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5433/patchdiff"
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

To require a server-issued `observation_id` (`patchdiff_observe_scope` -> `patchdiff_submit_observed_operations`) for all edit submissions and reject unobserved writes (`OBSERVATION_REQUIRED`), set:

```powershell
$env:PATCHDIFF_STRICT_OBSERVATION_MODE = "1"
```
