# PatchDIFF MVP Backend Development

## Local Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
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

