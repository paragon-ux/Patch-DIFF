import json
import uuid

from sqlalchemy import select

from app.mcp.external_adapter import ExternalMCPAdapter
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs
from backend.tests.integration.helpers import pdcp_for


def _call(adapter: ExternalMCPAdapter, name: str, arguments: dict) -> dict:
    result = adapter.handle_request(
        {
            "jsonrpc": "2.0",
            "id": name,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert result["jsonrpc"] == "2.0"
    assert result["result"]["isError"] is False
    return json.loads(result["result"]["content"][0]["text"])


def test_external_mcp_happy_path_matches_internal_product_flow() -> None:
    adapter = ExternalMCPAdapter()

    upload = _call(
        adapter,
        "patchdiff_handle_upload",
        {"filename": "external-happy.txt", "content": "Title\n\nOld sentence.\n", "content_type": "text/plain"},
    )
    target_id = upload["target_file_id"]

    context = _call(
        adapter,
        "patchdiff_build_prompt_context",
        {"target_file_id": target_id, "user_request": "Replace the old sentence."},
    )
    assert context["target_file_id"] == target_id
    assert context["current_hash"] == upload["current_hash"]
    assert "MATCH/REPLACE" in context["pdcp_rules"]

    accepted = _call(
        adapter,
        "patchdiff_submit_pdcp",
        {
            "target_file_id": target_id,
            "pdcp_content": pdcp_for(target_id, ("Old sentence.", "New sentence.")),
            "expected_target_version": 0,
        },
    )
    assert accepted["status"] == "accepted"
    assert accepted["version"] == 1

    target = _call(adapter, "patchdiff_get_target", {"target_file_id": target_id})
    assert target["current_content"] == "Title\n\nNew sentence.\n"

    log_payload = _call(adapter, "patchdiff_get_pdcp_log", {"target_file_id": target_id})
    ledger_payload = _call(adapter, "patchdiff_get_manifest_ledger", {"target_file_id": target_id})
    exported = _call(adapter, "patchdiff_export_target", {"target_file_id": target_id})

    assert log_payload["entries"][0]["status"] == "accepted"
    assert log_payload["entries"][0]["pdcp_log_id"] == accepted["pdcp_log_id"]
    assert len(ledger_payload["entries"]) == 1
    assert exported["content"] == target["current_content"]
    assert exported["hash"] == target["current_hash"]


def test_external_mcp_rejects_invalid_and_malformed_pdcp_without_mutation() -> None:
    adapter = ExternalMCPAdapter()

    upload = _call(
        adapter,
        "patchdiff_handle_upload",
        {"filename": "external-reject.txt", "content": "Original sentence.", "content_type": "text/plain"},
    )
    target_id = upload["target_file_id"]
    before = _call(adapter, "patchdiff_get_target", {"target_file_id": target_id})

    rejected = _call(
        adapter,
        "patchdiff_submit_pdcp",
        {
            "target_file_id": target_id,
            "pdcp_content": pdcp_for(target_id, ("Missing sentence.", "Ignored sentence.")),
            "expected_target_version": 0,
        },
    )
    malformed = _call(
        adapter,
        "patchdiff_submit_pdcp",
        {
            "target_file_id": target_id,
            "pdcp_content": pdcp_for(target_id, ("Original sentence.", "New sentence.")).replace(
                "=======", "================================================="
            ),
            "expected_target_version": 0,
        },
    )
    after = _call(adapter, "patchdiff_get_target", {"target_file_id": target_id})
    ledger_payload = _call(adapter, "patchdiff_get_manifest_ledger", {"target_file_id": target_id})

    assert rejected["status"] == "rejected"
    assert rejected["failure_reason"] == "match_absent"
    assert rejected["after_hash"] is None
    assert malformed["status"] == "rejected"
    assert malformed["failure_reason"] == "block_malformed"
    assert malformed["after_hash"] is None
    assert after["current_content"] == before["current_content"]
    assert after["current_hash"] == before["current_hash"]
    assert after["version"] == before["version"]
    assert ledger_payload["entries"] == []


def test_external_mcp_regeneration_save_replay_and_export_preserve_internal_semantics() -> None:
    adapter = ExternalMCPAdapter()

    upload = _call(
        adapter,
        "patchdiff_handle_upload",
        {"filename": "external-regen.txt", "content": "Alpha sentence.", "content_type": "text/plain"},
    )
    target_id = upload["target_file_id"]

    rejected = _call(
        adapter,
        "patchdiff_submit_pdcp",
        {
            "target_file_id": target_id,
            "pdcp_content": pdcp_for(target_id, ("Missing sentence.", "Beta sentence.")),
            "expected_target_version": 0,
        },
    )
    regen_context = _call(
        adapter,
        "patchdiff_get_regeneration_context",
        {"pdcp_log_id": rejected["pdcp_log_id"], "user_request": "Replace Alpha with Beta."},
    )
    regenerated = _call(
        adapter,
        "patchdiff_request_regeneration",
        {
            "pdcp_log_id": rejected["pdcp_log_id"],
            "user_request": "Replace Alpha with Beta.",
            "regenerated_pdcp_content": pdcp_for(
                target_id, ("Alpha sentence.", "Beta sentence."), change_id_prefix="external_regen"
            ),
            "regeneration_attempt": 1,
            "regeneration_source": "external_mcp_e2e_test",
        },
    )
    before_save = _call(adapter, "patchdiff_get_target", {"target_file_id": target_id})
    saved = _call(adapter, "patchdiff_save", {"target_file_id": target_id, "expected_current_hash": before_save["current_hash"]})
    after_save = _call(adapter, "patchdiff_get_target", {"target_file_id": target_id})
    replayed = _call(adapter, "patchdiff_replay", {"target_file_id": target_id})
    exported = _call(adapter, "patchdiff_export_target", {"target_file_id": target_id})

    assert regen_context["status"] == "ready"
    assert regenerated["status"] == "accepted"
    assert regenerated["parent_pdcp_log_id"] == rejected["pdcp_log_id"]
    assert regenerated["new_pdcp_log_id"] != rejected["pdcp_log_id"]
    assert before_save["current_content"] == "Beta sentence."
    assert saved["status"] == "saved"
    assert after_save["current_content"] == before_save["current_content"]
    assert after_save["current_hash"] == before_save["current_hash"]
    assert replayed["status"] == "success"
    assert replayed["reconstructed_hash"] == after_save["current_hash"]
    assert exported["content"] == after_save["current_content"]
    assert exported["hash"] == after_save["current_hash"]

    with SessionLocal() as session:
        logs = session.scalars(
            select(AppendOnlyPdcpLogs)
            .where(AppendOnlyPdcpLogs.target_file_id == uuid.UUID(target_id))
            .order_by(AppendOnlyPdcpLogs.log_sequence)
        ).all()
        ledger_rows = session.scalars(
            select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == uuid.UUID(target_id))
        ).all()

    assert [row.status for row in logs] == ["rejected", "accepted"]
    assert str(logs[1].parent_pdcp_log_id) == rejected["pdcp_log_id"]
    assert logs[1].regeneration_source == "external_mcp_e2e_test"
    assert len(ledger_rows) == 1
    assert ledger_rows[0].pdcp_log_id == logs[1].pdcp_log_id
