import inspect

from app.mcp import tools
from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import CloudTargetFiles, CurrentPdcpFiles
from backend.tests.integration.helpers import pdcp_for


def test_required_tool_names_are_registered() -> None:
    assert set(registry.names()) == {
        "patchdiff_handle_upload",
        "patchdiff_initialize_target",
        "patchdiff_build_prompt_context",
        "patchdiff_submit_pdcp",
        "patchdiff_get_regeneration_context",
        "patchdiff_build_regeneration_prompt",
        "patchdiff_request_regeneration",
        "patchdiff_get_target",
        "patchdiff_export_target",
        "patchdiff_save",
        "patchdiff_replay",
        "patchdiff_get_pdcp_log",
        "patchdiff_get_manifest_ledger",
    }


def test_upload_initializes_target_through_service() -> None:
    result = registry.call(
        "patchdiff_handle_upload",
        filename="example.txt",
        content="old\r\n",
        content_type="text/plain",
    )
    assert result["target_file_id"]
    assert result["version"] == 0
    assert result["target_type"] == "text/plain"
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, result["target_file_id"])
        assert target.current_content == "old\n"


def test_submit_valid_pdcp_returns_accepted_result_and_current_pdcp_row() -> None:
    upload = registry.call(
        "patchdiff_initialize_target",
        filename="example.txt",
        content="old",
        content_type="text/plain",
    )
    submit = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=upload["target_file_id"],
        pdcp_content=pdcp_for(upload["target_file_id"], ("old", "new")),
        expected_target_version=0,
    )
    assert submit["status"] == "accepted"
    assert submit["after_hash"]
    assert submit["version"] == 1
    assert submit["manifest_entries_added"] == 1
    assert submit["warnings"] == []
    with SessionLocal() as session:
        current = session.query(CurrentPdcpFiles).filter_by(target_file_id=upload["target_file_id"]).one()
        assert current.status == "accepted"


def test_submit_invalid_pdcp_returns_rejected_diagnostics() -> None:
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
    assert rejected["status"] == "rejected"
    assert rejected["failure_reason"] == "match_absent"
    assert rejected["after_hash"] is None
    assert rejected["diagnostic"]["requires_new_pdcp"] is True


def test_export_save_and_replay_call_services() -> None:
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
    exported = registry.call("patchdiff_export_target", target_file_id=upload["target_file_id"])
    assert exported["content"] == "new"
    saved = registry.call("patchdiff_save", target_file_id=upload["target_file_id"], export_after_save=True)
    assert saved["status"] == "saved"
    assert saved["export"]["content"] == "new"
    replayed = registry.call("patchdiff_replay", target_file_id=upload["target_file_id"])
    assert replayed["status"] == "success"
    assert replayed["reconstructed_hash"] == replayed["current_hash"]


def test_tool_layer_does_not_directly_mutate_target_content() -> None:
    source = inspect.getsource(tools)
    assert ".current_content =" not in source
    assert "apply_pdcp_transaction" not in source
