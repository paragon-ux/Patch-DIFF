"""Compare actual discovery with live submission and durable audit outcomes."""
import copy
import json
import uuid

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import select

from app.mcp.external_adapter import ExternalMCPAdapter
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles, CurrentPdcpFiles
from backend.tests.integration.helpers import pdcp_for


def call(adapter, name, args):
    response = adapter.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
    assert response["result"]["isError"] is False, response
    return json.loads(response["result"]["content"][0]["text"])


CASES = [
    ("omitted_guard", {}, False),
    ("null_guard", {"expected_target_version": None}, False),
    ("null_guards", {"expected_target_version": None, "expected_current_hash": None}, False),
    ("version", {"expected_target_version": 0}, True),
    ("hash", {"expected_current_hash": "CURRENT"}, True),
    ("both", {"expected_target_version": 0, "expected_current_hash": "CURRENT"}, True),
    ("null_unused_hash", {"expected_target_version": 0, "expected_current_hash": None}, True),
    ("blank_intent", {"intent": " \t\n", "expected_target_version": 0}, False),
    ("intent_type", {"intent": 3, "expected_target_version": 0}, False),
    ("blank_rationale", {"edits": [{"match": "alpha", "replace": "beta", "rationale": " \n"}], "expected_target_version": 0}, False),
    ("null_edit_fields", {"edits": [{"match": "alpha", "replace": "beta", "change_id": None, "rationale": None, "risk": None, "occurrence_index": None, "anchor_before": None, "anchor_after": None}], "expected_target_version": 0, "attempt": None}, True),
    ("colon_id", {"edits": [{"match": "alpha", "replace": "beta", "change_id": "section:1"}], "expected_target_version": 0}, True),
    ("newline_id", {"edits": [{"match": "alpha", "replace": "beta", "change_id": "section:1\n"}], "expected_target_version": 0}, False),
    ("long_id", {"edits": [{"match": "alpha", "replace": "beta", "change_id": "x" * 65}], "expected_target_version": 0}, False),
    ("punctuation_id", {"edits": [{"match": "alpha", "replace": "beta", "change_id": "section/1"}], "expected_target_version": 0}, False),
    ("negative_version", {"expected_target_version": -1}, False),
    ("bool_version", {"expected_target_version": True}, False),
    ("string_version", {"expected_target_version": "0"}, False),
    ("overflow_version", {"expected_target_version": 2**63}, False),
    ("nonhex_hash", {"expected_current_hash": "g" * 64}, False),
    ("newline_hash", {"expected_current_hash": "a" * 64 + "\n"}, False),
    ("oversized_hash", {"expected_current_hash": "a" * 65}, False),
    ("hash_type", {"expected_current_hash": []}, False),
    ("zero_attempt", {"expected_target_version": 0, "attempt": 0}, False),
    ("bool_attempt", {"expected_target_version": 0, "attempt": True}, False),
    ("string_attempt", {"expected_target_version": 0, "attempt": "1"}, False),
    ("overflow_attempt", {"expected_target_version": 0, "attempt": 2**31}, False),
    ("max_attempt", {"expected_target_version": 0, "attempt": 2**31 - 1}, True),
    ("request_id", {"expected_target_version": 0, "client_request_id": "req-001"}, True),
    ("newline_request_id", {"expected_target_version": 0, "client_request_id": "req-001\n"}, False),
]


@pytest.mark.parametrize("name,overrides,valid", CASES, ids=[case[0] for case in CASES])
def test_discovery_domains_match_live_rejection_and_audit(name, overrides, valid):
    adapter = ExternalMCPAdapter()
    listed = adapter.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    schema = next(tool["inputSchema"] for tool in listed["result"]["tools"] if tool["name"] == "patchdiff_submit_edits")
    Draft202012Validator.check_schema(schema)
    target = call(adapter, "patchdiff_initialize_target", {"filename": f"{uuid.uuid4()}.txt", "content": "alpha", "content_type": "text/plain"})
    args = {"target_file_id": target["target_file_id"], "intent": "Update", "edits": [{"match": "alpha", "replace": "beta"}], **copy.deepcopy(overrides)}
    if args.get("expected_current_hash") == "CURRENT":
        args["expected_current_hash"] = target["current_hash"]
    assert Draft202012Validator(schema).is_valid(args) is valid
    result = call(adapter, "patchdiff_submit_edits", args)
    assert result["status"] == ("accepted" if valid else "rejected")
    with SessionLocal() as session:
        target_uuid = uuid.UUID(target["target_file_id"])
        stored = session.get(CloudTargetFiles, target_uuid)
        logs = session.scalars(select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_uuid)).all()
        ledger = session.scalars(select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == target_uuid)).all()
        assert len(logs) == 1 and logs[0].status == result["status"]
        assert stored.current_content == ("beta" if valid else "alpha")
        assert stored.version == (1 if valid else 0)
        assert len(ledger) == (1 if valid else 0)
    if not valid:
        assert call(adapter, "patchdiff_submit_edits", {"target_file_id": target["target_file_id"], "intent": "Follow-up", "edits": [{"match": "alpha", "replace": "beta"}], "expected_target_version": 0})["status"] == "accepted"


@pytest.mark.parametrize("tool", ["patchdiff_submit_edits", "patchdiff_submit_pdcp"])
def test_newline_hash_guard_is_durably_rejected_with_raw_evidence(tool):
    adapter = ExternalMCPAdapter()
    target = call(adapter, "patchdiff_initialize_target", {"filename": "newline-guard.txt", "content": "alpha", "content_type": "text/plain"})
    target_id = uuid.UUID(target["target_file_id"])
    proposal = {"intent": "Update", "edits": [{"match": "alpha", "replace": "beta"}]} if tool.endswith("edits") else {"pdcp_content": pdcp_for(target_id, ("alpha", "beta"))}
    args = {"target_file_id": str(target_id), "expected_current_hash": "a" * 64 + "\n", **proposal}
    rejected = call(adapter, tool, args)
    assert rejected["failure_reason"] == "context_invalid"
    with SessionLocal() as session:
        log = session.get(AppendOnlyPdcpLogs, uuid.UUID(rejected["pdcp_log_id"]))
        current = session.scalar(select(CurrentPdcpFiles).where(CurrentPdcpFiles.target_file_id == target_id))
        assert log.status == "rejected" and current.status == "rejected"
        assert log.expected_current_hash is None
        assert log.diagnostic_json["raw_expected_current_hash"] == args["expected_current_hash"]
        stored = session.get(CloudTargetFiles, target_id)
        assert stored.current_content == "alpha" and stored.version == 0
        assert not session.scalars(select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == target_id)).all()
    args["expected_current_hash"] = target["current_hash"]
    assert call(adapter, tool, args)["status"] == "accepted"


def test_schema_numeric_domain_does_not_replace_business_guards():
    adapter = ExternalMCPAdapter()
    schema = next(t["inputSchema"] for t in adapter.list_tools() if t["name"] == "patchdiff_submit_edits")
    target = call(adapter, "patchdiff_initialize_target", {"filename": "max-version.txt", "content": "alpha", "content_type": "text/plain"})
    args = {"target_file_id": target["target_file_id"], "intent": "Update", "edits": [{"match": "alpha", "replace": "beta"}], "expected_target_version": 2**63 - 1}
    assert Draft202012Validator(schema).is_valid(args)
    assert call(adapter, "patchdiff_submit_edits", args)["failure_reason"] == "target_version_mismatch"
