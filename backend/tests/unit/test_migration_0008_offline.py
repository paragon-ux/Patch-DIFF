"""Offline migration checks for 20261101_0008 (PR #23 integrity, history_revision, export chunks, SQL privileges)."""

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


def test_migration_0008_is_head_and_revises_0007() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["20261101_0008"]
    rev = script.get_revision("20261101_0008")
    assert rev is not None
    assert rev.down_revision == "20261031_0007"


def test_migration_0008_upgrade_sql_renders_history_revision_chunks_and_triggers() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(_config(), "20261031_0007:20261101_0008", sql=True)
    sql = buffer.getvalue()
    assert "ADD COLUMN history_revision BIGINT DEFAULT 0 NOT NULL" in sql
    assert "CREATE TABLE target_finalization_export_chunks" in sql
    assert "ck_target_finalization_export_chunks_byte_length" in sql
    assert "patchdiff_enforce_immutable_audit_row" in sql
    assert "patchdiff_enforce_scope_observation_immutability" in sql
    assert "patchdiff_bump_target_history_revision" in sql
    assert "SECURITY DEFINER" in sql
    assert "patchdiff_agent" in sql
    assert "patchdiff_host" in sql


def test_migration_0008_downgrade_refuses_when_export_chunks_exist() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), "20261101_0008:20261031_0007", sql=True)
    sql = buffer.getvalue()
    assert "Cannot downgrade 20261101_0008: finalized export chunks exist" in sql
    assert "DROP TABLE target_finalization_export_chunks" in sql
    assert "DROP COLUMN history_revision" in sql
