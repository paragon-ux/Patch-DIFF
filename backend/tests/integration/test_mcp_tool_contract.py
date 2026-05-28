import inspect
import uuid

from sqlalchemy import func, select

from app.mcp import tools
from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    CurrentPdcpFiles,
    TargetSnapshots,
)
from backend.tests.integration.helpers import pdcp_for


def test_upload_initialize_routes_through_target_service_and_creates_canonical_state(monkeypatch) -> None:
    calls = {"initialize_target": 0}
    original = tools.initialize_target

    def wrapped_initialize_target(*args, **kwargs):
        calls["initialize_target"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(tools, "initialize_target", wrapped_initialize_target)

    upload = registry.call(
        "patchdiff_handle_upload",
        filename="contract.txt",
        content="old\r\n",
        content_type="text/plain",
    )

    assert calls["initialize_target"] == 1
    assert upload["version"] == 0
    with SessionLocal() as session:
        target_id = uuid.UUID(upload["target_file_id"])
        target = session.get(CloudTargetFiles, target_id)
        assert target.current_content == "old\n"
        assert target.active_editing_cycle_id is not None
        snapshot_count = session.scalar(
            select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == target_id)
        )
        assert snapshot_count == 1


def test_submit_routes_through_deterministic_submit_service_and_persists_logs_and_ledger(monkeypatch) -> None:
    calls = {"submit_pdcp": 0}
    original = tools.submit_pdcp

    def wrapped_submit_pdcp(*args, **kwargs):
        calls["submit_pdcp"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(tools, "submit_pdcp", wrapped_submit_pdcp)

    upload = registry.call(
        "patchdiff_initialize_target",
        filename="contract.txt",
        content="old",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]

    accepted = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("old", "new")),
        expected_target_version=0,
    )
    rejected = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("missing", "ignored")),
        expected_target_version=1,
    )

    assert calls["submit_pdcp"] == 2
    assert accepted["status"] == "accepted"
    assert accepted["version"] == 1
    assert rejected["status"] == "rejected"
    assert rejected["failure_reason"] == "match_absent"
    assert rejected["after_hash"] is None

    with SessionLocal() as session:
        target_uuid = uuid.UUID(target_id)
        target = session.get(CloudTargetFiles, target_uuid)
        assert target.current_content == "new"
        assert target.version == 1

        current_pdcp = session.scalar(select(CurrentPdcpFiles).where(CurrentPdcpFiles.target_file_id == target_uuid))
        assert current_pdcp.status == "rejected"
        assert current_pdcp.last_pdcp_log_id == uuid.UUID(rejected["pdcp_log_id"])

        logs = session.scalars(
            select(AppendOnlyPdcpLogs)
            .where(AppendOnlyPdcpLogs.target_file_id == target_uuid)
            .order_by(AppendOnlyPdcpLogs.log_sequence)
        ).all()
        assert [row.status for row in logs] == ["accepted", "rejected"]
        assert logs[1].after_hash is None

        ledger_rows = session.scalars(
            select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == target_uuid)
        ).all()
        assert len(ledger_rows) == 1
        assert ledger_rows[0].pdcp_log_id == uuid.UUID(accepted["pdcp_log_id"])


def test_save_replay_and_export_route_through_services(monkeypatch) -> None:
    calls = {"save_target": 0, "replay_target": 0, "export_target": 0}
    original_save = tools.save_target
    original_replay = tools.replay_target
    original_export = tools.export_target

    def wrapped_save_target(*args, **kwargs):
        calls["save_target"] += 1
        return original_save(*args, **kwargs)

    def wrapped_replay_target(*args, **kwargs):
        calls["replay_target"] += 1
        return original_replay(*args, **kwargs)

    def wrapped_export_target(*args, **kwargs):
        calls["export_target"] += 1
        return original_export(*args, **kwargs)

    monkeypatch.setattr(tools, "save_target", wrapped_save_target)
    monkeypatch.setattr(tools, "replay_target", wrapped_replay_target)
    monkeypatch.setattr(tools, "export_target", wrapped_export_target)

    upload = registry.call(
        "patchdiff_initialize_target",
        filename="contract.txt",
        content="old",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]
    registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("old", "new")),
    )

    saved = registry.call("patchdiff_save", target_file_id=target_id)
    replayed = registry.call("patchdiff_replay", target_file_id=target_id)
    exported = registry.call("patchdiff_export_target", target_file_id=target_id)

    assert calls == {"save_target": 1, "replay_target": 1, "export_target": 1}
    assert saved["status"] == "saved"
    assert replayed["status"] == "success"
    assert exported["content"] == "new"
    assert exported["target_type"] == "text/plain"
    assert exported["hash"] == exported["current_hash"]


def test_log_and_manifest_ledger_tools_return_service_backed_current_state() -> None:
    upload = registry.call(
        "patchdiff_initialize_target",
        filename="contract.txt",
        content="old",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]
    registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("old", "new")),
    )
    registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("missing", "ignored")),
    )

    log_payload = registry.call("patchdiff_get_pdcp_log", target_file_id=target_id)
    ledger_payload = registry.call("patchdiff_get_manifest_ledger", target_file_id=target_id)

    assert [entry["status"] for entry in log_payload["entries"]] == ["rejected", "accepted"]
    assert len(ledger_payload["entries"]) == 1
    assert ledger_payload["entries"][0]["change_id"] == "chg_001"


def test_mcp_tools_do_not_directly_mutate_target_content_or_call_applier() -> None:
    source = inspect.getsource(tools)
    assert ".current_content =" not in source
    assert "CloudTargetFiles.current_content" not in source
    assert "apply_pdcp_transaction" not in source
