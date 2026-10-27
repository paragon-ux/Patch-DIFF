"""Offline SQL rendering for migration 0004 (target_scope_observations)."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parents[2] / "app" / "migrations"


def _config() -> Config:
    config = Config(str(MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS))
    return config


def test_upgrade_creates_target_scope_observations_table_and_indexes() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(_config(), "20261022_0003:20261026_0004", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE target_scope_observations" in sql
    assert "waymark_engine_version TEXT NOT NULL" in sql
    assert "observed_scope_hash VARCHAR(64) NOT NULL" in sql
    assert "accepted_pdcp_log_id UUID" in sql
    assert "CREATE INDEX ix_target_scope_observations_target_version" in sql
    assert "CREATE INDEX ix_target_scope_observations_target_cycle" in sql


def test_downgrade_refuses_before_dropping_target_scope_observations() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), "20261026_0004:20261022_0003", sql=True)
    sql = buffer.getvalue()
    assert "recorded scope observations exist" in sql
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP TABLE target_scope_observations")
