# PatchDIFF MVP Backend Development

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

To require a server-issued `observation_id` (`patchdiff_observe_scope` -> `patchdiff_submit_observed_operations`) for all edit submissions and reject unobserved writes (`OBSERVATION_REQUIRED`), set:

```powershell
$env:PATCHDIFF_STRICT_OBSERVATION_MODE = "1"
```
