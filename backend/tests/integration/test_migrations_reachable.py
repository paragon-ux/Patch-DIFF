from pathlib import Path

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
