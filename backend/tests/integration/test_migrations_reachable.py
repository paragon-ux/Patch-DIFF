from pathlib import Path


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

