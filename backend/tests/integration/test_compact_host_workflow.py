"""Compact editor + detailed trusted lifecycle over real stdio and PostgreSQL."""
import json
import uuid

from sqlalchemy import select

from app.storage.db import SessionLocal
from app.storage.models import CloudTargetFiles, EditingCycles, TargetSnapshots
from backend.tests.integration.test_observed_batch import request, state
from backend.tests.verification.structural_batch.verify import MCP
from examples.host_finalize import finalize_targets


def test_compact_editor_recovery_paging_and_host_scalar_finalization(tmp_path):
    manifest = []
    with MCP("observed", response_mode="compact") as editor, MCP("full", response_mode="detailed") as operator:
        assert len(editor.catalog["tools"]) == 6
        for index in range(2):
            target = operator.call("patchdiff_initialize_target", filename=f"target{index}.py",
                content="# 🌟\n" + "\n\n".join(f"def f{i}():\n    return 'abcd'" for i in range(2)) + "\n",
                content_type="text/x-python")
            selectors = [{"symbol_name": f"f{i}", "kind": "function"} for i in range(2)]
            tid = target["target_file_id"]
            candidates = editor.call("patchdiff_observe_scope", target_file_id=tid, kind="function")
            assert candidates["status"] == "candidates" and len(candidates["candidates"]) == 2
            assert set(candidates["candidates"][0]) == {"name", "kind", "parent", "start_line", "end_line"}
            bundle = editor.call("patchdiff_observe_scope", target_file_id=tid, selections=selectors,
                                 max_chars=5, include_line_starts=True)
            assert bundle["scopes"][0]["truncated"] and "start" not in bundle["scopes"][0]
            scope = bundle["scopes"][0]
            assert scope["line_starts"][0]["start"] == scope["scope_start"]
            page = editor.call("patchdiff_observe_scope", target_file_id=tid,
                               observation_id=scope["observation_id"], offset=scope["next_offset"])
            assert page["mode"] == "scope_page" and "presentation" not in page
            assert scope["text"] + page["text"] == state(target)[0][scope["scope_start"]:scope["scope_end"]]
            arguments = request(target, bundle)
            # Include a real stored warning, then an ordinary exact edit.
            arguments["groups"][0]["operations"].insert(0, {"op": "match", "match": "abcd", "replace": "abcd"})
            accepted = editor.call("patchdiff_submit_observed_operations", **arguments)
            assert accepted["status"] == "accepted" and accepted["warning_count"] > 0
            assert "evidence" not in accepted and "groups" not in accepted and accepted["change_count"] == 5
            recovered = editor.call("patchdiff_submit_observed_operations", **arguments)
            rich = operator.call("patchdiff_submit_observed_operations", **arguments)
            assert recovered["deduplicated"] and rich["deduplicated"]
            assert rich["evidence"]["changes"] and rich["groups"]
            for key in ("pdcp_log_id", "after_hash", "warnings", "warning_details", "warning_count", "validity"):
                assert rich[key] == recovered[key] == accepted[key]
            assert len(state(target)[2]) == 1  # Recovery appended no attempt.
            stale = {**arguments, "client_request_id": str(uuid.uuid4())}
            rejected = editor.call("patchdiff_submit_observed_operations", **stale)
            assert rejected["status"] == "rejected" and "presentation" not in rejected and rejected["diagnostic"]
            manifest.append({"filename": f"target{index}.py", "target_file_id": tid,
                             "expected_target_version": 1, "expected_current_hash": accepted["after_hash"],
                             "accepted_pdcp_log_id": accepted["pdcp_log_id"]})
        before = {}
        with SessionLocal() as session:
            rows = [session.get(CloudTargetFiles, uuid.UUID(item["target_file_id"])) for item in manifest]
            assert len({row.project_id for row in rows}) == 2
            before = {str(row.target_file_id): (row.current_content, row.version, row.current_hash) for row in rows}
        result = finalize_targets(operator.call, manifest, tmp_path / "finalization")
        assert result["status"] == "complete", result
        assert editor.calls["patchdiff_save"] == editor.calls["patchdiff_replay"] == 0
        assert operator.calls["patchdiff_save"] == operator.calls["patchdiff_replay"] == 2
        with SessionLocal() as session:
            for item in manifest:
                tid = uuid.UUID(item["target_file_id"])
                row = session.get(CloudTargetFiles, tid)
                assert (row.current_content, row.version, row.current_hash) == before[str(tid)]
                snapshots = session.scalars(select(TargetSnapshots).where(TargetSnapshots.target_file_id == tid,
                                                                         TargetSnapshots.snapshot_reason == "save_checkpoint")).all()
                cycles = session.scalars(select(EditingCycles).where(EditingCycles.target_file_id == tid)).all()
                assert len(snapshots) == 1 and len(cycles) == 2
                assert sum(c.status == "closed" for c in cycles) == 1
                assert (tmp_path / "finalization/exports" / item["filename"]).read_bytes() == row.current_content.encode()
