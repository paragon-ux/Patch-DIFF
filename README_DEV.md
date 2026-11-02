# PatchDIFF MVP Backend Development

## Local Setup

The sole managed database runtime is PostgreSQL 16.3 Alpine through Docker Compose on `127.0.0.1:5433`. Linux/WSL2 deployment requires separate operator, `patchdiff-mcp-agent` service and `patchdiff-model` shell UIDs, with private single-role database credentials. Follow [the deployment guide](docs/guides/CLAUDE_DESKTOP_SETUP.md) before running setup; missing separation fails closed.

### Automated Setup & Daemon Lifecycle

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .

# As operator after the required accounts/private paths exist:
patchdiff-mcp-setup
patchdiff-mcp-daemon start
patchdiff-mcp-daemon stop
patchdiff-mcp-daemon restart
patchdiff-mcp-daemon status
```

Setup applies migrations through `20261101_0008`, provisions the three PostgreSQL roles, verifies the Waymark bridge and checks both MCP connections. Change the Docker port with `--port` or `PATCHDIFF_POSTGRES_PORT`. Status is read-only; stop preserves containers and volumes.

For an already-running PostgreSQL 16+ instance, privately supply `PATCHDIFF_BOOTSTRAP_DATABASE_URL`, `PATCHDIFF_HOST_DATABASE_URL` and `PATCHDIFF_AGENT_DATABASE_URL`, then run `patchdiff-mcp-setup --external-database`. That path performs no database lifecycle commands. Existing native PGDATA remains untouched; follow [the non-destructive migration guide](docs/guides/NATIVE_POSTGRES_MIGRATION.md) when needed.

The FastAPI development server can run as the trusted operator with its explicitly configured host connection:

```bash
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
