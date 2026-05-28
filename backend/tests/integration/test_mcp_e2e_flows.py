import uuid

from sqlalchemy import select

from app.mcp import tools  # noqa: F401
from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyPdcpLogs, CloudTargetFiles
from backend.tests.integration.helpers import pdcp_for


def test_mcp_happy_path_upload_context_submit_log_ledger_export() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="happy.txt",
        content="Title\n\nOld sentence.\n",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]

    context = registry.call(
        "patchdiff_build_prompt_context",
        target_file_id=target_id,
        user_request="Replace the old sentence.",
    )
    assert context["target_file_id"] == target_id
    assert context["current_hash"] == upload["current_hash"]
    assert context["version"] == 0
    assert context["target_context"] == "Title\n\nOld sentence.\n"
    assert "MATCH/REPLACE" in context["pdcp_rules"]

    accepted = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("Old sentence.", "New sentence.")),
        expected_target_version=0,
    )
    assert accepted["status"] == "accepted"
    assert accepted["version"] == 1

    target = registry.call("patchdiff_get_target", target_file_id=target_id)
    assert target["current_content"] == "Title\n\nNew sentence.\n"

    log_payload = registry.call("patchdiff_get_pdcp_log", target_file_id=target_id)
    assert log_payload["entries"][0]["status"] == "accepted"
    assert log_payload["entries"][0]["pdcp_log_id"] == accepted["pdcp_log_id"]

    ledger_payload = registry.call("patchdiff_get_manifest_ledger", target_file_id=target_id)
    assert len(ledger_payload["entries"]) == 1
    assert ledger_payload["entries"][0]["change_id"] == "chg_001"

    exported = registry.call("patchdiff_export_target", target_file_id=target_id)
    assert exported["content"] == target["current_content"]
    assert exported["target_type"] == target["target_type"]
    assert exported["version"] == target["version"]
    assert exported["hash"] == target["current_hash"]


def test_mcp_rejection_path_logs_rejection_without_target_or_ledger_mutation() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="reject.txt",
        content="Original text.",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]
    before = registry.call("patchdiff_get_target", target_file_id=target_id)

    rejected = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("Missing text.", "New text.")),
        expected_target_version=0,
    )

    assert rejected["status"] == "rejected"
    assert rejected["failure_reason"] == "match_absent"
    assert rejected["after_hash"] is None

    after = registry.call("patchdiff_get_target", target_file_id=target_id)
    assert after["current_content"] == before["current_content"]
    assert after["current_hash"] == before["current_hash"]
    assert after["version"] == before["version"]

    log_payload = registry.call("patchdiff_get_pdcp_log", target_file_id=target_id)
    assert log_payload["entries"][0]["status"] == "rejected"
    assert log_payload["entries"][0]["failure_reason"] == "match_absent"

    ledger_payload = registry.call("patchdiff_get_manifest_ledger", target_file_id=target_id)
    assert ledger_payload["entries"] == []


def test_mcp_regeneration_flow_preserves_parent_logs_and_mutates_target_once() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="regen.txt",
        content="Alpha sentence.",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]

    rejected = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("Missing sentence.", "Beta sentence.")),
        expected_target_version=0,
    )
    assert rejected["status"] == "rejected"

    regen_context = registry.call(
        "patchdiff_get_regeneration_context",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Replace Alpha with Beta.",
    )
    assert regen_context["status"] == "ready"
    assert regen_context["failure_reason"] == "match_absent"

    regenerated = registry.call(
        "patchdiff_request_regeneration",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Replace Alpha with Beta.",
        regenerated_pdcp_content=pdcp_for(target_id, ("Alpha sentence.", "Beta sentence."), change_id_prefix="regen"),
        regeneration_attempt=1,
        regeneration_source="mcp_e2e_test",
    )
    assert regenerated["status"] == "accepted"
    assert regenerated["parent_pdcp_log_id"] == rejected["pdcp_log_id"]
    assert regenerated["new_pdcp_log_id"] != rejected["pdcp_log_id"]

    target = registry.call("patchdiff_get_target", target_file_id=target_id)
    assert target["current_content"] == "Beta sentence."
    assert target["version"] == 1

    with SessionLocal() as session:
        target_uuid = uuid.UUID(target_id)
        logs = session.scalars(
            select(AppendOnlyPdcpLogs)
            .where(AppendOnlyPdcpLogs.target_file_id == target_uuid)
            .order_by(AppendOnlyPdcpLogs.log_sequence)
        ).all()
        assert [row.status for row in logs] == ["rejected", "accepted"]
        assert str(logs[1].parent_pdcp_log_id) == rejected["pdcp_log_id"]
        assert logs[1].regeneration_attempt == 1
        assert logs[1].regeneration_source == "mcp_e2e_test"

        db_target = session.get(CloudTargetFiles, target_uuid)
        assert db_target.version == 1
