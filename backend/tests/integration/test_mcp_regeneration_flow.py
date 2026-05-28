import inspect

from sqlalchemy import select

from app.mcp import tools
from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyPdcpLogs
from backend.tests.integration.helpers import pdcp_for


def test_prompt_context_includes_target_metadata_manifest_summary_request_and_rules() -> None:
    upload = registry.call(
        "patchdiff_initialize_target",
        filename="example.txt",
        content="old",
        content_type="text/plain",
    )
    registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=upload["target_file_id"],
        pdcp_content=pdcp_for(upload["target_file_id"], ("old", "new")),
    )
    context = registry.call(
        "patchdiff_build_prompt_context",
        target_file_id=upload["target_file_id"],
        user_request="Make the text newer.",
    )
    assert context["target_file_id"] == upload["target_file_id"]
    assert context["target_type"] == "text/plain"
    assert context["version"] == 1
    assert context["manifest_summary"][0]["change_id"] == "chg_001"
    assert context["user_request"] == "Make the text newer."
    assert "MATCH/REPLACE" in context["pdcp_rules"]


def test_regeneration_context_and_prompt_include_rejection_diagnostics() -> None:
    upload = registry.call(
        "patchdiff_initialize_target",
        filename="example.txt",
        content="old",
        content_type="text/plain",
    )
    rejected = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=upload["target_file_id"],
        pdcp_content=pdcp_for(upload["target_file_id"], ("missing", "new")),
    )
    context = registry.call(
        "patchdiff_get_regeneration_context",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Fix it.",
    )
    assert context["failure_reason"] == "match_absent"
    assert context["current_hash"] == rejected["current_hash"]
    assert context["rejected_pdcp_content"]
    prompt = registry.call(
        "patchdiff_build_regeneration_prompt",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Fix it.",
    )
    assert "Failure reason: match_absent" in prompt["prompt"]
    assert "Do not generate executable apply functions" in prompt["prompt"]


def test_regenerated_pdcp_submits_as_new_lineage_attempt_and_preserves_parent() -> None:
    upload = registry.call(
        "patchdiff_initialize_target",
        filename="example.txt",
        content="old",
        content_type="text/plain",
    )
    rejected = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=upload["target_file_id"],
        pdcp_content=pdcp_for(upload["target_file_id"], ("missing", "new")),
    )
    regenerated = registry.call(
        "patchdiff_request_regeneration",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Fix it.",
        regenerated_pdcp_content=pdcp_for(upload["target_file_id"], ("old", "new"), change_id_prefix="regen"),
        regeneration_attempt=1,
        regeneration_source="test_host",
    )
    assert regenerated["status"] == "accepted"
    assert regenerated["parent_pdcp_log_id"] == rejected["pdcp_log_id"]
    assert regenerated["new_pdcp_log_id"] != rejected["pdcp_log_id"]

    with SessionLocal() as session:
        parent = session.get(AppendOnlyPdcpLogs, rejected["pdcp_log_id"])
        child = session.get(AppendOnlyPdcpLogs, regenerated["new_pdcp_log_id"])
        assert parent.status == "rejected"
        assert child.status == "accepted"
        assert str(child.parent_pdcp_log_id) == rejected["pdcp_log_id"]
        assert child.regeneration_attempt == 1
        assert child.regeneration_source == "test_host"


def test_rejected_regenerated_pdcp_remains_logged() -> None:
    upload = registry.call(
        "patchdiff_initialize_target",
        filename="example.txt",
        content="old",
        content_type="text/plain",
    )
    rejected = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=upload["target_file_id"],
        pdcp_content=pdcp_for(upload["target_file_id"], ("missing", "new")),
    )
    regenerated = registry.call(
        "patchdiff_request_regeneration",
        pdcp_log_id=rejected["pdcp_log_id"],
        regenerated_pdcp_content=pdcp_for(upload["target_file_id"], ("still missing", "new"), change_id_prefix="regenbad"),
        regeneration_attempt=2,
        regeneration_source="test_host",
    )
    assert regenerated["status"] == "rejected"
    with SessionLocal() as session:
        logs = session.scalars(
            select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == upload["target_file_id"])
        ).all()
        assert [row.status for row in logs].count("rejected") == 2


def test_deterministic_core_runtime_does_not_construct_prompts_or_import_mcp() -> None:
    import app.pdcp.applier as applier

    source = inspect.getsource(applier)
    assert "prompt" not in source.lower()
    assert "app.mcp" not in source
    assert "call_model" not in source.lower()
    assert "choose_model" not in source.lower()
    assert "tool" not in source.lower()
    assert "applyPDCP" not in inspect.getsource(tools)
