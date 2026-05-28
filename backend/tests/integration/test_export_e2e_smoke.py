from sqlalchemy import select

from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles
from backend.tests.integration.helpers import pdcp_for


def test_export_does_not_mutate_target_state() -> None:
    upload = registry.call(
        "patchdiff_initialize_target",
        filename="example.txt",
        content="old",
        content_type="text/plain",
    )
    before = registry.call("patchdiff_get_target", target_file_id=upload["target_file_id"])
    exported = registry.call("patchdiff_export_target", target_file_id=upload["target_file_id"])
    after = registry.call("patchdiff_get_target", target_file_id=upload["target_file_id"])
    assert exported["content"] == "old"
    assert exported["target_type"] == "text/plain"
    assert exported["version"] == 0
    assert exported["hash"] == before["current_hash"]
    assert before == after


def test_upload_prompt_reject_regenerate_accept_save_replay_export_smoke() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="story.txt",
        content="Title\n\nOld sentence.\n",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]

    prompt_context = registry.call(
        "patchdiff_build_prompt_context",
        target_file_id=target_id,
        user_request="Replace the old sentence.",
    )
    assert prompt_context["target_file_id"] == target_id
    assert prompt_context["target_context"] == "Title\n\nOld sentence.\n"
    assert "MATCH/REPLACE" in prompt_context["pdcp_rules"]

    rejected = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("Missing sentence.", "New sentence.")),
        expected_target_version=0,
    )
    assert rejected["status"] == "rejected"
    assert rejected["failure_reason"] == "match_absent"
    assert rejected["after_hash"] is None
    assert rejected["diagnostic"]["requires_new_pdcp"] is True

    regen_context = registry.call(
        "patchdiff_get_regeneration_context",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Replace the old sentence.",
    )
    assert regen_context["failure_reason"] == "match_absent"
    assert regen_context["current_hash"] == rejected["current_hash"]

    regen_prompt = registry.call(
        "patchdiff_build_regeneration_prompt",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Replace the old sentence.",
    )
    assert "Generate a fresh declarative .pdcp transaction" in regen_prompt["prompt"]

    regenerated = registry.call(
        "patchdiff_request_regeneration",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Replace the old sentence.",
        regenerated_pdcp_content=pdcp_for(
            target_id,
            ("Old sentence.", "New sentence."),
            change_id_prefix="regen",
        ),
        regeneration_attempt=1,
        regeneration_source="smoke_test",
    )
    assert regenerated["status"] == "accepted"
    accepted_result = regenerated["result"]
    assert accepted_result["status"] == "accepted"
    assert accepted_result["version"] == 1
    assert accepted_result["manifest_entries_added"] == 1

    target = registry.call("patchdiff_get_target", target_file_id=target_id)
    assert target["current_content"] == "Title\n\nNew sentence.\n"

    with SessionLocal() as session:
        logs = session.scalars(
            select(AppendOnlyPdcpLogs)
            .where(AppendOnlyPdcpLogs.target_file_id == target_id)
            .order_by(AppendOnlyPdcpLogs.log_sequence)
        ).all()
        ledger_rows = session.scalars(
            select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == target_id)
        ).all()
        assert [row.status for row in logs] == ["rejected", "accepted"]
        assert str(logs[1].parent_pdcp_log_id) == rejected["pdcp_log_id"]
        assert len(ledger_rows) == 1
        assert ledger_rows[0].change_id == "regen_001"

    saved = registry.call("patchdiff_save", target_file_id=target_id)
    assert saved["status"] == "saved"

    replayed = registry.call("patchdiff_replay", target_file_id=target_id)
    assert replayed["status"] == "success"
    assert replayed["reconstructed_hash"] == replayed["current_hash"]

    exported = registry.call("patchdiff_export_target", target_file_id=target_id)
    assert exported["content"] == "Title\n\nNew sentence.\n"
    assert exported["target_type"] == "text/plain"
    assert exported["version"] == 1
    assert exported["hash"] == replayed["current_hash"]


def test_health_endpoints_report_liveness_and_readiness(client) -> None:
    assert client.get("/health/live").json()["status"] == "ok"
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ok"
