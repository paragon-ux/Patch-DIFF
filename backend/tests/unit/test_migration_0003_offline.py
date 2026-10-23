"""Offline SQL rendering for migration 0003; live populated checks run in the integration suite."""

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


def test_upgrade_adds_nullable_source_line_endings_without_backfill() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(_config(), "20261020_0002:20261022_0003", sql=True)
    sql = buffer.getvalue()
    assert "ALTER TABLE cloud_target_files ADD COLUMN source_line_endings JSONB" in sql
    assert "NOT NULL" not in sql.split("ADD COLUMN source_line_endings", 1)[1].split(";", 1)[0]
    assert "UPDATE cloud_target_files" not in sql


def test_downgrade_refuses_before_dropping_recorded_line_endings() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), "20261022_0003:20261020_0002", sql=True)
    sql = buffer.getvalue()
    assert "recorded source line endings exist" in sql
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP COLUMN source_line_endings")
