"""Offline SQL rendering for migration 0007 (finalization_checks)."""

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


def test_upgrade_adds_materialized_state_checks_column() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(_config(), "20261031_0006:20261031_0007", sql=True)
    sql = buffer.getvalue()
    assert "ALTER TABLE target_finalizations ADD COLUMN materialized_state_checks JSONB" in sql


def test_downgrade_drops_materialized_state_checks_column() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), "20261031_0007:20261031_0006", sql=True)
    sql = buffer.getvalue()
    assert "ALTER TABLE target_finalizations DROP COLUMN materialized_state_checks" in sql
