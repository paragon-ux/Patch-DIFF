"""Offline migration checks: render SQL for the full chain without a database.

This proves the revision chain and that DDL renders for the PostgreSQL dialect.
Live upgrade/downgrade/upgrade and data-preservation checks run in the Postgres
integration suite (`backend/tests/integration/test_migrations_reachable.py`).
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

MIGRATIONS = Path(__file__).resolve().parents[2] / "app" / "migrations"


def _config() -> Config:
    config = Config(str(MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS))
    return config


def test_typed_ledger_revision_sits_between_initial_and_line_ending_revisions() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["20261026_0004"]
    assert script.get_revision("20261026_0004").down_revision == "20261022_0003"
    assert script.get_revision("20261022_0003").down_revision == "20261020_0002"
    assert script.get_revision("20261020_0002").down_revision == "20260510_0001"


def test_upgrade_sql_renders_typed_ledger_and_request_idempotency_columns() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(_config(), "20260510_0001:20261020_0002", sql=True)
    sql = buffer.getvalue()
    assert "ADD COLUMN origin TEXT DEFAULT 'pdcp_manifest' NOT NULL" in sql
    assert "ADD COLUMN derived_json JSONB" in sql
    assert "ADD COLUMN client_request_id TEXT" in sql
    assert "ADD COLUMN request_fingerprint VARCHAR(64)" in sql
    assert "uq_pdcp_logs_target_client_request_id" in sql
    for column in ("input_state", "output_state", "affected_region", "user_visible_change", "risk"):
        assert f"ALTER COLUMN {column} DROP NOT NULL" in sql


def test_downgrade_refuses_to_destroy_typed_rows() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), "20261020_0002:20260510_0001", sql=True)
    sql = buffer.getvalue()
    assert "typed ledger rows exist" in sql
    assert sql.index("RAISE EXCEPTION") < sql.index("SET NOT NULL")
    assert "DROP INDEX uq_pdcp_logs_target_client_request_id" in sql
    assert "DROP COLUMN client_request_id" in sql
    assert "DROP COLUMN request_fingerprint" in sql
