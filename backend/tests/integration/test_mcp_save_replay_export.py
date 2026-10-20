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


def test_arch_002_manifest_ledger_pagination_and_cycles() -> None:
    # 1. Initialize target with 250 distinct lines
    initial_lines = [f"item_{i:03d} = old" for i in range(1, 251)]
    content = "\n".join(initial_lines)
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="manifest_paging.txt",
        content=content,
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]

    # 2. Cycle 1: Submit 110 edits in one atomic transaction
    edits_c1 = [{"match": f"item_{i:03d} = old", "replace": f"item_{i:03d} = c1"} for i in range(1, 111)]
    res1 = registry.call(
        "patchdiff_submit_edits",
        target_file_id=target_id,
        intent="cycle 1 bulk edit",
        edits=edits_c1,
        expected_target_version=0,
    )
    assert res1["status"] == "accepted"

    # Save target: closes cycle 1 (sequences 1..110), opens cycle 2
    saved = registry.call(
        "patchdiff_save",
        target_file_id=target_id,
        expected_current_hash=res1["after_hash"],
    )
    assert saved["status"] == "saved"

    # 3. Cycle 2: Submit 120 edits (sequences 111..230)
    edits_c2 = [{"match": f"item_{i:03d} = old", "replace": f"item_{i:03d} = c2"} for i in range(111, 231)]
    res2 = registry.call(
        "patchdiff_submit_edits",
        target_file_id=target_id,
        intent="cycle 2 bulk edit",
        edits=edits_c2,
        expected_target_version=1,
    )
    assert res2["status"] == "accepted"

    # 4. Verify default limit (50) and active cycle only (default include_previous_cycles=False)
    page_def = registry.call("patchdiff_get_manifest_ledger", target_file_id=target_id)
    assert len(page_def["entries"]) == 50
    assert page_def["has_more"] is True
    assert page_def["next_sequence"] == page_def["entries"][0]["ledger_sequence"]
    seqs_def = [e["ledger_sequence"] for e in page_def["entries"]]
    assert seqs_def == sorted(seqs_def)
    assert len(set(seqs_def)) == 50

    # Explicit null limit produces identical default page
    page_null = registry.call("patchdiff_get_manifest_ledger", target_file_id=target_id, limit=None)
    assert len(page_null["entries"]) == 50
    assert page_null["has_more"] is True
    assert [e["ledger_sequence"] for e in page_null["entries"]] == seqs_def

    # 5. Verify max cap (clamped to 200) across all cycles
    page_cap = registry.call(
        "patchdiff_get_manifest_ledger",
        target_file_id=target_id,
        include_previous_cycles=True,
        limit=500,
    )
    assert len(page_cap["entries"]) == 200
    assert page_cap["has_more"] is True
    assert page_cap["next_sequence"] == page_cap["entries"][0]["ledger_sequence"]
    seqs_cap = [e["ledger_sequence"] for e in page_cap["entries"]]
    assert seqs_cap == sorted(seqs_cap)
    assert len(set(seqs_cap)) == 200

    # 6. Complete backward traversal across all 230 entries without gaps or duplicates
    collected_entries = []
    before_seq = None
    while True:
        page = registry.call(
            "patchdiff_get_manifest_ledger",
            target_file_id=target_id,
            include_previous_cycles=True,
            limit=50,
            before_sequence=before_seq,
        )
        collected_entries = page["entries"] + collected_entries
        if not page["has_more"]:
            assert page["next_sequence"] is None
            break
        assert page["next_sequence"] is not None
        before_seq = page["next_sequence"]

    assert len(collected_entries) == 230
    all_seqs = [e["ledger_sequence"] for e in collected_entries]
    assert all_seqs == sorted(all_seqs)
    assert len(set(all_seqs)) == 230

    # 7. Invalid argument validation
    assert (
        registry.call("patchdiff_get_manifest_ledger", target_file_id=target_id, before_sequence=0)["status"]
        == "invalid_argument"
    )
    assert (
        registry.call("patchdiff_get_manifest_ledger", target_file_id=target_id, limit=0)["status"]
        == "invalid_argument"
    )

