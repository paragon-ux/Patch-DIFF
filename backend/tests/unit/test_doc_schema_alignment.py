"""Mechanical alignment tests between code/ORM schemas and active normative documentation (PR23-R4I-DOC-001, PR23-R4I-DOC-002, PR23-PLAN-DOC-001, PR23-IMPL-DOC-002)."""

from __future__ import annotations

from pathlib import Path
from sqlalchemy import inspect

from app.storage.models import TargetFinalizations

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_target_finalizations_columns_and_error_codes_match_docs():
    """Verify TargetFinalizations ORM columns and finalization error codes match DATA_MODEL.md and MODERNIZATION_CHANGE_DOC.md."""
    mapper = inspect(TargetFinalizations)
    orm_columns = {col.key for col in mapper.columns}

    data_model_text = (REPO_ROOT / "docs" / "spec" / "DATA_MODEL.md").read_text(encoding="utf-8")
    for col in orm_columns:
        assert f"`{col}`" in data_model_text, f"ORM column {col!r} missing from docs/spec/DATA_MODEL.md"

    assert "request_key_conflict" in data_model_text
    assert "request_id_conflict" not in data_model_text

    change_doc_text = (REPO_ROOT / "docs" / "papers" / "MODERNIZATION_CHANGE_DOC.md").read_text(encoding="utf-8")
    assert "`exported_content`" in change_doc_text
    assert "`materialized_state_checks`" in change_doc_text
    assert "exported_bytes" not in change_doc_text
    assert "replay_checks_json" not in change_doc_text


def test_mcp_tools_and_host_guide_error_and_status_vocabulary():
    """Verify MCP_TOOLS.md and HOST_INTEGRATION_GUIDE.md document actual runtime error strings and db_status values."""
    mcp_tools_text = (REPO_ROOT / "docs" / "spec" / "MCP_TOOLS.md").read_text(encoding="utf-8")
    assert "Unknown PatchDIFF MCP tool:" in mcp_tools_text

    host_guide_text = (REPO_ROOT / "docs" / "guides" / "HOST_INTEGRATION_GUIDE.md").read_text(encoding="utf-8")
    for db_status_val in ('"ok"', '"rejected"', '"invalid_argument"', '"not_found"', '"error"'):
        assert db_status_val in host_guide_text, f"db_status value {db_status_val} missing from HOST_INTEGRATION_GUIDE.md"

    assert "patchdiff_host" in host_guide_text
    assert "patchdiff_agent" in host_guide_text
    assert "scram-sha-256" in host_guide_text


def test_active_docs_and_skills_profile_and_migration_alignment():
    """Verify active docs and skills agree on observed_v2 default (5 tools), full (24 tools), and migrations through 0008."""
    for rel_path in (
        "AGENTS.md",
        "README.md",
        "docs/ROADMAP.md",
        ".agents/skills/patchdiff-mcp-orchestration/SKILL.md",
    ):
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert "observed_v2" in text, f"{rel_path} missing observed_v2"
        assert "24" in text, f"{rel_path} missing 24-tool full profile count"

    for rel_path in (
        "AGENTS.md",
        "docs/spec/DATA_MODEL.md",
        ".agents/skills/patchdiff-persistence-replay-save/SKILL.md",
    ):
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert "0008" in text, f"{rel_path} missing migration 0008 reference"
