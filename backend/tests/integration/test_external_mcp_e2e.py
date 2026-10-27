import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.mcp.external_adapter import ExternalMCPAdapter
from app.pdcp.typed import ALLOWED_TYPED_EDIT_FIELDS, REQUIRED_TYPED_EDIT_FIELDS
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs
from backend.tests.integration.helpers import pdcp_for

BACKEND = Path(__file__).resolve().parents[2]


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
    adapter = ExternalMCPAdapter(profile="full")

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
    adapter = ExternalMCPAdapter(profile="full")

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
    adapter = ExternalMCPAdapter(profile="full")

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
    saved = _call(
        adapter, "patchdiff_save", {"target_file_id": target_id, "expected_current_hash": before_save["current_hash"]}
    )
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


def test_real_stdio_subprocess_mcp_full_modernized_workflow() -> None:
    """Real child-process stdio MCP test backed by live Postgres (Section 6 product workflow)."""

    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "PATCHDIFF_MCP_PROFILE": "full", "PATCHDIFF_DATABASE_URL": settings.database_url,
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.mcp.external_adapter"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=BACKEND,
        env=env,
    )
    req_counter = 0

    def rpc(method: str, params: dict | None = None) -> dict:
        nonlocal req_counter
        req_counter += 1
        msg = {"jsonrpc": "2.0", "id": req_counter, "method": method}
        if params is not None:
            msg["params"] = params
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        assert line, f"Subprocess exited prematurely: {proc.stderr.read() if proc.stderr else ''}"
        resp = json.loads(line)
        assert resp["id"] == req_counter
        return resp

    def call_tool(name: str, arguments: dict) -> dict:
        resp = rpc("tools/call", {"name": name, "arguments": arguments})
        assert resp["result"]["isError"] is False, resp
        return json.loads(resp["result"]["content"][0]["text"])

    try:
        # 1. initialize and tools/list
        init = rpc("initialize", {})
        assert init["result"]["serverInfo"]["name"] == "patchdiff-mvp"
        listed = rpc("tools/list", {})
        tools_by_name = {t["name"]: t for t in listed["result"]["tools"]}
        edits_schema = tools_by_name["patchdiff_submit_edits"]["inputSchema"]["properties"]["edits"]
        assert set(edits_schema["items"]["properties"].keys()) == set(ALLOWED_TYPED_EDIT_FIELDS)
        assert set(edits_schema["items"]["required"]) == set(REQUIRED_TYPED_EDIT_FIELDS)

        # 2. target initialization
        initial_doc = "status: draft\nsection: overview\nstatus: draft\n"
        uploaded = call_tool(
            "patchdiff_initialize_target",
            {
                "filename": "stdio-workflow.md",
                "content": initial_doc,
                "content_type": "text/markdown",
            },
        )
        target_id = uploaded["target_file_id"]
        assert uploaded["version"] == 0

        # Exercise malformed submissions in the real child process on a separate target.
        from jsonschema import Draft202012Validator
        probe = call_tool("patchdiff_initialize_target", {
            "filename": "stdio-boundaries.txt", "content": "alpha", "content_type": "text/plain",
        })
        probe_id = probe["target_file_id"]
        schema = tools_by_name["patchdiff_submit_edits"]["inputSchema"]
        base_args = {"target_file_id": probe_id, "intent": "Update", "edits": [{"match": "alpha", "replace": "beta"}]}
        for args in (
            base_args,
            {**base_args, "expected_current_hash": "a" * 64 + "\n"},
            {**base_args, "expected_target_version": 0, "edits": [{"match": "alpha", "replace": "beta", "change_id": "section:1\n"}]},
        ):
            assert not Draft202012Validator(schema).is_valid(args)
            assert call_tool("patchdiff_submit_edits", args)["status"] == "rejected"
        legacy_rejected = call_tool("patchdiff_submit_pdcp", {
            "target_file_id": probe_id, "pdcp_content": pdcp_for(probe_id, ("alpha", "beta")),
            "expected_current_hash": "a" * 64 + "\n",
        })
        assert legacy_rejected["failure_reason"] == "context_invalid"
        history = call_tool("patchdiff_get_pdcp_log", {"target_file_id": probe_id})
        assert len(history["entries"]) == 4
        assert all(row["status"] == "rejected" for row in history["entries"])
        assert call_tool("patchdiff_get_manifest_ledger", {"target_file_id": probe_id})["entries"] == []
        unchanged = call_tool("patchdiff_get_target", {"target_file_id": probe_id})
        assert unchanged["current_content"] == "alpha" and unchanged["version"] == 0
        assert call_tool("patchdiff_submit_edits", {**base_args, "expected_target_version": 0, "client_request_id": "req-001"})["status"] == "accepted"

        # 3. authoritative read / occurrence inspection
        read_res = call_tool("patchdiff_read_target", {"target_file_id": target_id, "start": 0, "length": 100})
        assert read_res["status"] == "ok"
        assert read_res["text"] == initial_doc
        assert read_res["next_start"] is None

        occ_res = call_tool(
            "patchdiff_find_occurrences",
            {"target_file_id": target_id, "text": "status: draft", "context_chars": 20},
        )
        assert occ_res["status"] == "ok"
        assert occ_res["occurrence_count"] == 2
        assert [o["occurrence_index"] for o in occ_res["occurrences"]] == [1, 2]

        # 4. rejected typed submission (ambiguous match without selector)
        rejected = call_tool(
            "patchdiff_submit_edits",
            {
                "target_file_id": target_id,
                "intent": "Publish second section status.",
                "edits": [{"match": "status: draft", "replace": "status: published"}],
                "expected_target_version": 0,
                "client_request_id": "stdio-req-1",
            },
        )
        assert rejected["status"] == "rejected"
        assert rejected["failure_reason"] == "match_ambiguous"
        assert rejected["diagnostic"]["format"] == "patchdiff-tx/1"
        assert rejected["diagnostic"]["occurrence_count"] == 2
        assert rejected["diagnostic"]["requires_new_submission"] is True
        assert "requires_new_pdcp" not in rejected["diagnostic"]
        assert rejected["validity"] == {
            "protocol_valid": True,
            "transaction_valid": False,
            "task_correct": "not_evaluated",
            "semantic": "not_evaluated",
        }

        # 5. host-side disambiguation and accepted resubmission with lineage
        accepted = call_tool(
            "patchdiff_submit_edits",
            {
                "target_file_id": target_id,
                "intent": "Publish second section status.",
                "edits": [
                    {
                        "change_id": "chg_001",
                        "match": "status: draft",
                        "replace": "status: published",
                        "occurrence_index": occ_res["occurrences"][1]["occurrence_index"],
                        "rationale": "Select the second occurrence after section: overview.",
                        "risk": "low",
                    }
                ],
                "expected_target_version": 0,
                "parent_pdcp_log_id": rejected["pdcp_log_id"],
                "attempt": 2,
                "client_request_id": "stdio-req-2",
            },
        )
        assert accepted["status"] == "accepted"
        assert accepted["version"] == 1
        assert accepted["deduplicated"] is False
        assert accepted["validity"] == {
            "protocol_valid": True,
            "transaction_valid": True,
            "task_correct": "not_evaluated",
            "semantic": "not_evaluated",
        }

        # Verify lost-response retry over stdio returns deduplicated terminal outcome
        retry_accepted = call_tool(
            "patchdiff_submit_edits",
            {
                "target_file_id": target_id,
                "intent": "Publish second section status.",
                "edits": [
                    {
                        "change_id": "chg_001",
                        "match": "status: draft",
                        "replace": "status: published",
                        "occurrence_index": 2,
                        "rationale": "Select the second occurrence after section: overview.",
                        "risk": "low",
                    }
                ],
                "expected_target_version": 0,
                "parent_pdcp_log_id": rejected["pdcp_log_id"],
                "attempt": 2,
                "client_request_id": "stdio-req-2",
            },
        )
        assert retry_accepted["status"] == "accepted"
        assert retry_accepted["deduplicated"] is True
        assert retry_accepted["pdcp_log_id"] == accepted["pdcp_log_id"]

        # 6. SAVE checkpoint
        saved = call_tool(
            "patchdiff_save",
            {"target_file_id": target_id, "expected_current_hash": accepted["after_hash"]},
        )
        assert saved["status"] == "saved"
        assert saved["version"] == 1

        # 7. replay verification
        replayed = call_tool("patchdiff_replay", {"target_file_id": target_id})
        assert replayed["status"] == "success"
        assert replayed["accepted_transactions_replayed"] == 1
        assert replayed["materialized_state_matches"] is True
        assert replayed["materialized_state_checks"] == {
            "content_matches": True,
            "stored_hash_matches": True,
            "recomputed_hash_matches": True,
            "version_matches": True,
        }

        # 8. export and history inspection
        exported = call_tool("patchdiff_export_target", {"target_file_id": target_id})
        assert exported["content"] == "status: draft\nsection: overview\nstatus: published\n"
        assert exported["version"] == 1

        logs = call_tool("patchdiff_get_pdcp_log", {"target_file_id": target_id})
        assert len(logs["entries"]) == 2
        assert [e["status"] for e in logs["entries"]] == ["accepted", "rejected"]
        assert logs["entries"][0]["parent_pdcp_log_id"] == rejected["pdcp_log_id"]
        assert logs["entries"][0]["client_request_id"] == "stdio-req-2"

        ledger = call_tool(
            "patchdiff_get_manifest_ledger",
            {"target_file_id": target_id, "include_previous_cycles": True},
        )
        assert len(ledger["entries"]) == 1
        assert ledger["entries"][0]["origin"] == "typed"
        assert ledger["entries"][0]["derived"]["span_start"] == occ_res["occurrences"][1]["start"]
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=10)
    assert proc.returncode == 0
