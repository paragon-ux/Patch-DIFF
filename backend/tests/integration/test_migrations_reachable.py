from pathlib import Path
import json
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.hashing import canonical_sha256
from app.services.pdcp_service import submit_edits
from app.services.replay_service import replay_target
from app.services.target_service import initialize_target
from app.storage.db import engine
from backend.tests.integration.helpers import pdcp_for


from sqlalchemy import text

from app.storage.db import SessionLocal


ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "backend" / "app" / "migrations"


def test_alembic_config_exists() -> None:
    assert (MIGRATIONS / "alembic.ini").is_file()
    assert (MIGRATIONS / "env.py").is_file()


def test_initial_migration_mentions_required_schema() -> None:
    migration = MIGRATIONS / "versions" / "20260510_0001_initial_schema.py"
    content = migration.read_text(encoding="utf-8")

    for table_name in [
        "users",
        "projects",
        "project_memberships",
        "cloud_target_files",
        "current_pdcp_files",
        "append_only_pdcp_logs",
        "append_only_manifest_ledger",
        "target_snapshots",
        "editing_cycles",
    ]:
        assert table_name in content

    assert "diagnostic_json" in content
    assert "uq_editing_cycles_one_active_per_target" in content


def test_migration_0002_mentions_typed_ledger_and_request_idempotency() -> None:
    migration = MIGRATIONS / "versions" / "20261020_0002_typed_ledger.py"
    content = migration.read_text(encoding="utf-8")

    assert "origin" in content
    assert "derived_json" in content
    assert "client_request_id" in content
    assert "request_fingerprint" in content
    assert "uq_pdcp_logs_target_client_request_id" in content


def test_live_postgres_schema_has_0002_columns_and_unique_index() -> None:
    with SessionLocal() as session:
        ledger_cols = {
            row[0]: row[1]
            for row in session.execute(
                text(
                    "SELECT column_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'append_only_manifest_ledger'"
                )
            ).all()
        }
        assert ledger_cols["origin"] == "NO"
        assert ledger_cols["derived_json"] == "YES"
        for nullable_col in ("input_state", "output_state", "affected_region", "user_visible_change", "risk"):
            assert ledger_cols[nullable_col] == "YES"

        log_cols = {
            row[0]: row[1]
            for row in session.execute(
                text(
                    "SELECT column_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'append_only_pdcp_logs'"
                )
            ).all()
        }
        assert log_cols["client_request_id"] == "YES"
        assert log_cols["request_fingerprint"] == "YES"

        indexes = {
            row[0]
            for row in session.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'append_only_pdcp_logs'")
            ).all()
        }
        assert "uq_pdcp_logs_target_client_request_id" in indexes


# Migration checks own an isolated schema; shared application history is untouched.


@pytest.fixture
def isolated_migrations():
    schema = "patchdiff_migration_" + uuid.uuid4().hex
    with engine.connect() as connection:
        connection.execute(CreateSchema(schema))
        connection.commit()
        try:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config(str(MIGRATIONS / "alembic.ini"))
            config.set_main_option("script_location", str(MIGRATIONS))
            config.attributes["connection"] = connection
            yield config, connection
        finally:
            connection.rollback()
            connection.execute(text("SET search_path TO public"))
            connection.execute(DropSchema(schema, cascade=True))
            connection.commit()


HISTORY_TABLES = ("projects", "cloud_target_files", "editing_cycles", "target_snapshots", "append_only_pdcp_logs", "append_only_manifest_ledger")


def snapshot(connection):
    return {name: sorted((row[0] for row in connection.execute(text(f"SELECT to_jsonb(t) FROM {name} t"))), key=lambda row: json.dumps(row, sort_keys=True)) for name in HISTORY_TABLES}


def assert_legacy_preserved(connection, baseline):
    current = snapshot(connection)
    for name, old_rows in baseline.items():
        assert len(current[name]) == len(old_rows)
        keys = old_rows[0].keys() if old_rows else ()
        actual = sorted(({key: row[key] for key in keys} for row in current[name]), key=lambda row: json.dumps(row, sort_keys=True))
        assert actual == old_rows, name


def seed_legacy_history(connection):
    # Initializer tables are unchanged by 0002; reflect legacy log/ledger columns.
    with Session(bind=connection) as session:
        target = initialize_target(session, filename="legacy.txt", content="alpha", target_type="text/plain")
    metadata = MetaData()
    logs = Table("append_only_pdcp_logs", metadata, autoload_with=connection)
    ledger = Table("append_only_manifest_ledger", metadata, autoload_with=connection)
    targets = Table("cloud_target_files", metadata, autoload_with=connection)
    accepted_id, rejected_id = uuid.uuid4(), uuid.uuid4()
    accepted_content = pdcp_for(target.target_file_id, ("alpha", "beta"))
    rejected_content = pdcp_for(target.target_file_id, ("absent", "ignored"))
    common = dict(target_file_id=target.target_file_id, editing_cycle_id=target.active_editing_cycle_id, submission_source="migration_fixture", protocol_version="0.2.3", runtime_version="patchdiff-mvp-0.1.0", change_count=1)
    connection.execute(logs.insert().values(**common, pdcp_log_id=accepted_id, pdcp_content=accepted_content, pdcp_content_hash=canonical_sha256(accepted_content), status="accepted", before_version=0, after_version=1, before_hash=target.current_hash, after_hash=canonical_sha256("beta")))
    connection.execute(logs.insert().values(**common, pdcp_log_id=rejected_id, pdcp_content=rejected_content, pdcp_content_hash=canonical_sha256(rejected_content), status="rejected", failure_reason="match_absent", failure_detail="MATCH text was not found.", before_version=1, before_hash=canonical_sha256("beta")))
    connection.execute(ledger.insert().values(manifest_entry_id=uuid.uuid4(), target_file_id=target.target_file_id, editing_cycle_id=target.active_editing_cycle_id, pdcp_log_id=accepted_id, change_index=1, change_id="chg_001", intent="Update text.", input_state="Old text exists.", output_state="New text exists.", affected_region="example", user_visible_change="Text changes.", risk="low"))
    connection.execute(targets.update().where(targets.c.target_file_id == target.target_file_id).values(current_content="beta", current_hash=canonical_sha256("beta"), version=1, latest_accepted_pdcp_log_id=accepted_id))
    connection.commit()
    return target.target_file_id


def test_populated_legacy_upgrade_downgrade_upgrade_preserves_history(isolated_migrations):
    config, connection = isolated_migrations
    command.upgrade(config, "20260510_0001")
    target_id = seed_legacy_history(connection)
    baseline = snapshot(connection)
    connection.commit()
    command.upgrade(config, "head")
    assert_legacy_preserved(connection, baseline)
    assert connection.scalar(text("SELECT origin FROM append_only_manifest_ledger")) == "pdcp_manifest"
    assert connection.scalar(text("SELECT client_request_id FROM append_only_pdcp_logs LIMIT 1")) is None
    connection.commit()
    command.downgrade(config, "20260510_0001")
    assert_legacy_preserved(connection, baseline)
    connection.commit()
    command.upgrade(config, "head")
    assert_legacy_preserved(connection, baseline)
    with Session(bind=connection) as session:
        replay = replay_target(session, target_file_id=target_id)
        assert replay.status == "success" and replay.materialized_state_matches
        assert replay.reconstructed_content == "beta" and replay.reconstructed_version == 1


def test_live_migration_refuses_downgrade_when_typed_rows_exist(isolated_migrations):
    config, connection = isolated_migrations
    command.upgrade(config, "head")
    assert connection.scalar(text("SELECT count(*) FROM append_only_manifest_ledger")) == 0
    connection.commit()
    with Session(bind=connection) as session:
        target = initialize_target(session, filename="typed.txt", content="alpha", target_type="text/plain")
        accepted = submit_edits(session, target_file_id=target.target_file_id, expected_target_version=0, intent="Create typed history", edits=[{"match": "alpha", "replace": "beta"}])
        assert accepted.status == "accepted"
    baseline = snapshot(connection)
    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "20261020_0002"
    assert connection.scalar(text("SELECT origin FROM append_only_manifest_ledger")) == "typed"
    connection.commit()
    with pytest.raises(Exception, match="Cannot downgrade 20261020_0002: typed ledger rows exist"):
        command.downgrade(config, "20260510_0001")
    connection.rollback()
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
    assert snapshot(connection) == baseline
    with Session(bind=connection) as session:
        replay = replay_target(session, target_file_id=target.target_file_id)
        assert replay.status == "success" and replay.materialized_state_matches
