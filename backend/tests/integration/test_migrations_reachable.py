from pathlib import Path
from types import SimpleNamespace
import json
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.hashing import canonical_sha256
from app.services.export_service import export_target
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

        target_cols = {
            row[0]: (row[1], row[2])
            for row in session.execute(
                text(
                    "SELECT column_name, is_nullable, data_type "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'cloud_target_files'"
                )
            ).all()
        }
        assert target_cols["source_line_endings"] == ("YES", "jsonb")


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


def seed_legacy_target(connection, content="alpha"):
    """Insert an initialized target through reflected tables, valid at any revision."""
    metadata = MetaData()
    projects = Table("projects", metadata, autoload_with=connection)
    targets = Table("cloud_target_files", metadata, autoload_with=connection)
    cycles = Table("editing_cycles", metadata, autoload_with=connection)
    snapshots = Table("target_snapshots", metadata, autoload_with=connection)
    project_id, target_id, cycle_id, snapshot_id = (uuid.uuid4() for _ in range(4))
    digest = canonical_sha256(content)
    connection.execute(projects.insert().values(project_id=project_id, name="legacy"))
    connection.execute(targets.insert().values(
        target_file_id=target_id, project_id=project_id, filename="legacy.txt", target_type="text/plain",
        current_content=content, current_hash=digest, version=0, active_editing_cycle_id=cycle_id))
    connection.execute(cycles.insert().values(editing_cycle_id=cycle_id, target_file_id=target_id, cycle_index=0,
                                              status="active"))
    connection.execute(snapshots.insert().values(snapshot_id=snapshot_id, target_file_id=target_id,
                                                 editing_cycle_id=cycle_id, content=content, content_hash=digest,
                                                 version=0, snapshot_reason="initial_upload"))
    connection.execute(targets.update().where(targets.c.target_file_id == target_id).values(
        initial_snapshot_id=snapshot_id))
    return SimpleNamespace(target_file_id=target_id, active_editing_cycle_id=cycle_id, current_hash=digest)


def seed_legacy_history(connection):
    # The ORM model tracks head, so legacy rows are written through reflected tables.
    target = seed_legacy_target(connection)
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
    # Simulate a typed target created before 0003 so only the 0002 refusal is exercised.
    connection.execute(text("UPDATE cloud_target_files SET source_line_endings = NULL"))
    connection.commit()
    command.downgrade(config, "20261020_0002")
    connection.commit()
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
    command.upgrade(config, "head")
    connection.commit()
    with Session(bind=connection) as session:
        replay = replay_target(session, target_file_id=target.target_file_id)
        assert replay.status == "success" and replay.materialized_state_matches


def test_populated_0002_upgrade_downgrade_upgrade_through_0003_preserves_history(isolated_migrations):
    config, connection = isolated_migrations
    command.upgrade(config, "20261020_0002")
    target_id = seed_legacy_history(connection)
    baseline = snapshot(connection)
    connection.commit()
    command.upgrade(config, "head")
    assert_legacy_preserved(connection, baseline)
    assert connection.scalar(text("SELECT source_line_endings FROM cloud_target_files")) is None
    connection.commit()
    command.downgrade(config, "20261020_0002")
    assert_legacy_preserved(connection, baseline)
    columns = {row[0] for row in connection.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'cloud_target_files' "
        "AND table_schema = current_schema()"))}
    assert "source_line_endings" not in columns
    connection.commit()
    command.upgrade(config, "head")
    assert_legacy_preserved(connection, baseline)
    connection.commit()
    with Session(bind=connection) as session:
        replay = replay_target(session, target_file_id=target_id)
        assert replay.status == "success" and replay.materialized_state_matches
        unknown = export_target(session, target_file_id=target_id, format="original_eol")
        assert unknown["status"] == "invalid_argument" and unknown["code"] == "source_line_endings_unknown"
        assert export_target(session, target_file_id=target_id, format="crlf")["content"] == "beta"


def test_live_0003_downgrade_refuses_when_line_endings_are_recorded(isolated_migrations):
    config, connection = isolated_migrations
    command.upgrade(config, "head")
    connection.commit()
    with Session(bind=connection) as session:
        target = initialize_target(session, filename="crlf.txt", content="one\r\ntwo\r\n", target_type="text/plain")
    recorded = connection.scalar(text("SELECT source_line_endings FROM cloud_target_files"))
    assert recorded["style"] == "crlf" and recorded["crlf"] == 2 and recorded["normalized"] is True
    baseline = snapshot(connection)
    connection.commit()
    with pytest.raises(Exception, match="Cannot downgrade 20261022_0003: recorded source line endings exist"):
        command.downgrade(config, "20261020_0002")
    connection.rollback()
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261022_0003"
    assert snapshot(connection) == baseline
    with Session(bind=connection) as session:
        exported = export_target(session, target_file_id=target.target_file_id, format="original_eol")
        assert exported["content"] == "one\r\ntwo\r\n" and exported["content_eol"] == "crlf"
