"""Offline SQL rendering for migration 0006 (target_finalizations)."""

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


def test_upgrade_creates_target_finalizations_table_and_indexes() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(_config(), "20261027_0005:20261031_0006", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE target_finalizations" in sql
    assert "client_request_id VARCHAR(128) NOT NULL" in sql
    assert "request_fingerprint VARCHAR(64) NOT NULL" in sql
    assert "finalization_id UUID NOT NULL" in sql
    assert "source_line_endings JSONB" in sql
    assert "uq_target_finalizations_target_key" in sql
    assert "CREATE INDEX ix_target_finalizations_target_key" in sql
    assert "CREATE INDEX ix_target_finalizations_target_created" in sql


def test_downgrade_refuses_before_dropping_target_finalizations() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), "20261031_0006:20261027_0005", sql=True)
    sql = buffer.getvalue()
    assert "target finalization records exist" in sql
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP TABLE target_finalizations")
