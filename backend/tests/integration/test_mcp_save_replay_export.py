import uuid

from sqlalchemy import func, select

from app.mcp import tools  # noqa: F401
from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    CloudTargetFiles,
    CurrentPdcpFiles,
    EditingCycles,
    TargetSnapshots,
)
from backend.tests.integration.helpers import pdcp_for


def test_mcp_save_creates_snapshot_cycle_transition_without_target_content_mutation() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="save.txt",
        content="old",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]
    registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("old", "new")),
    )

    before = registry.call("patchdiff_get_target", target_file_id=target_id)
    saved = registry.call("patchdiff_save", target_file_id=target_id, expected_current_hash=before["current_hash"])
    after = registry.call("patchdiff_get_target", target_file_id=target_id)

    assert saved["status"] == "saved"
    assert saved["snapshot_id"]
    assert saved["closed_editing_cycle_id"]
    assert saved["new_editing_cycle_id"]
    assert after["current_content"] == before["current_content"]
    assert after["current_hash"] == before["current_hash"]
    assert after["version"] == before["version"]

    with SessionLocal() as session:
        target_uuid = uuid.UUID(target_id)
        snapshot_count = session.scalar(
            select(func.count()).select_from(TargetSnapshots).where(
                TargetSnapshots.target_file_id == target_uuid,
                TargetSnapshots.snapshot_reason == "save_checkpoint",
            )
        )
        active_cycle_count = session.scalar(
            select(func.count()).select_from(EditingCycles).where(
                EditingCycles.target_file_id == target_uuid,
                EditingCycles.status == "active",
            )
        )
        assert snapshot_count == 1
        assert active_cycle_count == 1


def test_mcp_replay_reconstructs_hash_and_ignores_current_pdcp_and_manifest_ledger() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="replay.txt",
        content="old",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]
    registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("old", "new")),
    )

    with SessionLocal() as session:
        target_uuid = uuid.UUID(target_id)
        current_pdcp = session.scalar(select(CurrentPdcpFiles).where(CurrentPdcpFiles.target_file_id == target_uuid))
        current_pdcp.pdcp_content = "corrupted display-only PDCP"
        ledger = session.scalar(
            select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == target_uuid)
        )
        ledger.intent = "corrupted non-operational manifest summary"
        session.commit()

    replayed = registry.call("patchdiff_replay", target_file_id=target_id)
    target = registry.call("patchdiff_get_target", target_file_id=target_id)

    assert replayed["status"] == "success"
    assert replayed["reconstructed_hash"] == target["current_hash"]
    assert replayed["current_hash"] == target["current_hash"]
    assert replayed["accepted_transactions_replayed"] == 1


def test_mcp_export_returns_current_canonical_content_type_version_and_hash() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="export.md",
        content="old",
        content_type="text/markdown",
    )
    target_id = upload["target_file_id"]
    registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=pdcp_for(target_id, ("old", "new")),
    )

    exported = registry.call("patchdiff_export_target", target_file_id=target_id)

    assert exported["content"] == "new"
    assert exported["target_type"] == "text/markdown"
    assert exported["content_type"] == "text/markdown"
    assert exported["version"] == 1
    assert exported["hash"]

    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, uuid.UUID(target_id))
        assert exported["content"] == target.current_content
        assert exported["hash"] == target.current_hash
        assert exported["version"] == target.version
