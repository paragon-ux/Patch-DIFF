"""Live PostgreSQL and real stdio for the consolidated Pass A pipeline."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.hashing import canonical_sha256
from app.core.validity import ValidationStage
from app.core.versions import OPERATIONS_RUNTIME_VERSION, RUNTIME_VERSION
from app.mcp.tools import _submit_result_to_payload
from app.services import pdcp_service, near_miss_service
from app.services.pdcp_service import submit_edits, submit_operations, submit_pdcp
from app.services.replay_service import replay_target
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles
from app.storage.repositories import select_target_for_update
from backend.tests.integration.helpers import create_target, pdcp_for


def span(start=0, end=1, expected_text="a", replace="A", **extra):
    return {"op": "span", "start": start, "end": end, "expected_text": expected_text, "replace": replace, **extra}


def args(target_id, operations=None, **extra):
    return {"target_file_id": target_id, "intent": "Pass A", "operations": operations or [span()],
            "expected_target_version": 0, **extra}


def counts(session, target_id):
    return tuple(session.scalar(select(func.count()).select_from(model).where(model.target_file_id == target_id))
                 for model in (AppendOnlyPdcpLogs, AppendOnlyManifestLedger))


def make_call(format_, target_id, rejected=False):
    match = "absent" if rejected else "alpha"
    common = {"target_file_id": target_id, "expected_target_version": 0, "client_request_id": "pass-a-original"}
    if format_ == "legacy":
        return submit_pdcp, {**common, "pdcp_content": pdcp_for(target_id, (match, "beta"))}
    if format_ == "typed":
        return submit_edits, {**common, "intent": "Pass A", "edits": [{"match": match, "replace": "beta"}]}
    return submit_operations, {**common, "intent": "Pass A", "operations": [{"op": "match", "match": match, "replace": "beta"}]}


@pytest.mark.parametrize("format_", ["legacy", "typed", "operations"])
@pytest.mark.parametrize("rejected", [False, True])
def test_correlation_defaults_fresh_uuid_recovery_and_fingerprint_exclusion(format_, rejected):
    target_id = create_target("alpha")
    submit, arguments = make_call(format_, target_id, rejected)
    with SessionLocal() as session:
        original = submit(session, **arguments)
    assert original.status == ("rejected" if rejected else "accepted")
    assert "correlation_id" not in _submit_result_to_payload(original)
    recovered = []
    for flag in (True, True, False):
        with SessionLocal() as session:
            recovered.append(submit(session, **arguments, include_correlation_id=flag))
    assert all(item.deduplicated and item.pdcp_log_id == original.pdcp_log_id for item in recovered)
    first, second = [uuid.UUID(item.correlation_id) for item in recovered[:2]]
    assert first.version == second.version == 4 and first != second
    assert str(first) not in (str(original.pdcp_log_id), arguments["client_request_id"])
    assert recovered[-1].correlation_id is None
    with SessionLocal() as session:
        assert counts(session, target_id) == (1, 0 if rejected else 1)
        log = session.get(AppendOnlyPdcpLogs, original.pdcp_log_id)
        assert "correlation" not in log.pdcp_content and "correlation" not in json.dumps(log.diagnostic_json)
        assert log.client_request_id == arguments["client_request_id"]


@pytest.mark.parametrize("format_", ["legacy", "typed", "operations"])
@pytest.mark.parametrize("flag", [None, 0, 1, "true", [], {}])
def test_invalid_correlation_type_is_explicit_no_admission(format_, flag):
    target_id = create_target("alpha")
    submit, arguments = make_call(format_, target_id)
    with SessionLocal() as session:
        result = submit(session, **arguments, include_correlation_id=flag)
        assert not session.in_transaction()
    assert _submit_result_to_payload(result)["status"] == "invalid_argument"
    assert result.pdcp_log_id is None
    with SessionLocal() as session:
        assert counts(session, target_id) == (0, 0)
        assert session.get(CloudTargetFiles, target_id).version == 0


def test_correlation_does_not_create_or_replace_unkeyed_retry_identity():
    target_id = create_target("a")
    for version in (0, 1):
        with SessionLocal() as session:
            result = submit_operations(session, **args(target_id, [span(replace="a")],
                                                       expected_target_version=version, include_correlation_id=True))
        assert result.status == "accepted" and not result.deduplicated
    with SessionLocal() as session:
        assert counts(session, target_id) == (2, 2)
        assert session.scalars(select(AppendOnlyPdcpLogs.client_request_id).where(AppendOnlyPdcpLogs.target_file_id == target_id)).all() == [None, None]


@pytest.mark.parametrize("content,operations,expected", [
    ("a\U0001f642b", [span(1, 2, "\U0001f642", "\U0001f30e")], "a\U0001f30eb"),
    ("", [span(0, 0, "", "a")], "a"),
    ("a", [span(1, 1, "", "b")], "ab"),
    ("a", [span(0, 1, "a", "")], ""),
    ("a\r\nb", [span(1, 2, "\r\n", "X")], "aXb"),
    ("alpha beta", [span(0, 5, "alpha", "A"), {"op": "match", "match": "beta", "replace": "B"}, span(2, 3, "B", "\U0001f642")], "A \U0001f642"),
])
def test_operations_persist_shared_runtime_facts_and_replay(content, operations, expected):
    target_id = create_target(content)
    with SessionLocal() as session:
        result = submit_operations(session, **args(target_id, operations, client_request_id="ops"))
    assert result.status == "accepted" and result.manifest_entries_added == len(operations)
    with SessionLocal() as session:
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert (log.protocol_version, log.runtime_version) == ("patchdiff-tx/2", OPERATIONS_RUNTIME_VERSION)
        assert json.loads(log.pdcp_content)["operations"] == operations
        assert log.pdcp_content_hash == canonical_sha256(log.pdcp_content)
        ledger = session.scalars(select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.pdcp_log_id == log.pdcp_log_id)
                                 .order_by(AppendOnlyManifestLedger.change_index)).all()
        assert len(ledger) == len(operations) and all(row.origin == "typed" for row in ledger)
        assert tuple(row.derived_json for row in ledger) == result.change_facts
        replay = replay_target(session, target_file_id=target_id)
        assert replay.status == "success" and replay.materialized_state_matches is True
        assert replay.reconstructed_content == expected


@pytest.mark.parametrize("operations,guard,reason,stage", [
    ([span(0, 2, "a", "x")], 0, "span_out_of_bounds", ValidationStage.TRANSACTION_APPLICABILITY),
    ([span(expected_text="wrong")], 0, "span_expected_text_mismatch", ValidationStage.TRANSACTION_APPLICABILITY),
    ([span(replace="b"), span(expected_text="a")], 0, "span_expected_text_mismatch", ValidationStage.TRANSACTION_APPLICABILITY),
    ([span(start=True)], 0, "block_malformed", ValidationStage.PROTOCOL_VALIDATION),
    ([span(occurrence_index=1)], 0, "manifest_invalid", ValidationStage.PROTOCOL_VALIDATION),
    ([span(expected_text="\ud800")], 0, "target_encoding_invalid", ValidationStage.PROTOCOL_VALIDATION),
    ([span()], 1, "target_version_mismatch", ValidationStage.PRECONDITION_GUARD),
    ([span()], None, "context_missing", ValidationStage.PROTOCOL_VALIDATION),
])
def test_invalid_operations_are_audited_once_without_partial_mutation(operations, guard, reason, stage):
    target_id = create_target("a")
    with SessionLocal() as session:
        result = submit_operations(session, **args(target_id, operations, expected_target_version=guard))
    assert result.failure_reason.value == reason and result.validation_stage is stage
    assert result.diagnostic["format"] == "patchdiff-tx/2" and "requires_new_pdcp" not in result.diagnostic
    with SessionLocal() as session:
        assert counts(session, target_id) == (1, 0)
        assert session.get(CloudTargetFiles, target_id).current_content == "a"
        assert session.get(CloudTargetFiles, target_id).version == 0


@pytest.mark.parametrize("commit", [False, True])
def test_operations_respect_caller_transaction_commit_and_rollback(commit):
    target_id = create_target("a")
    with SessionLocal() as owner:
        owner.begin()
        result = submit_operations(owner, **args(target_id, include_correlation_id=True))
        assert result.status == "accepted" and owner.in_transaction()
        with SessionLocal() as observer:
            assert counts(observer, target_id) == (0, 0)
            assert observer.get(CloudTargetFiles, target_id).current_content == "a"
        owner.commit() if commit else owner.rollback()
    with SessionLocal() as session:
        assert counts(session, target_id) == (int(commit), int(commit))
        assert session.get(CloudTargetFiles, target_id).current_content == ("A" if commit else "a")


def test_mixed_historical_protocols_replay_and_new_profile_fail_closed():
    target_id = create_target("a")
    with SessionLocal() as session:
        assert submit_edits(session, target_file_id=target_id, intent="old", edits=[{"match": "a", "replace": "b"}], expected_target_version=0).status == "accepted"
        current = submit_operations(session, **args(target_id, [span(0, 1, "b", "c")], expected_target_version=1, client_request_id="new"))
        assert current.status == "accepted"
        assert submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("c", "d")), expected_target_version=2).status == "accepted"
    with SessionLocal() as session:
        logs = session.scalars(select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_id).order_by(AppendOnlyPdcpLogs.log_sequence)).all()
        assert [log.runtime_version for log in logs] == [RUNTIME_VERSION, OPERATIONS_RUNTIME_VERSION, RUNTIME_VERSION]
        assert replay_target(session, target_file_id=target_id).reconstructed_content == "d"
        for profile in (RUNTIME_VERSION, "future-runtime"):
            logs[1].runtime_version = profile
            session.flush()
            result = replay_target(session, target_file_id=target_id)
            assert result.status == "failed" and result.failure_reason.value == "replay_protocol_invalid"
        session.rollback()
    with SessionLocal() as session:
        assert replay_target(session, target_file_id=target_id).materialized_state_matches is True


def test_operation_identity_and_conflict_preserve_the_original_record():
    target_id = create_target("a")
    arguments = args(target_id, client_request_id="ops-id")
    with SessionLocal() as session:
        original = submit_operations(session, **arguments)
    with SessionLocal() as session:
        recovered = submit_operations(session, **arguments, include_correlation_id=True)
        conflict = submit_operations(session, **{**arguments, "operations": [span(rationale="new claim")]})
        assert recovered.deduplicated and recovered.pdcp_log_id == original.pdcp_log_id
        assert conflict.failure_reason.value == "context_invalid" and conflict.pdcp_log_id != original.pdcp_log_id
        session.commit()
    with SessionLocal() as session:
        assert counts(session, target_id) == (2, 1)
        assert session.get(AppendOnlyPdcpLogs, conflict.pdcp_log_id).client_request_id is None
        assert json.loads(session.get(AppendOnlyPdcpLogs, original.pdcp_log_id).pdcp_content)["operations"] == [span()]


def test_exact_candidates_are_bounded_labeled_intermediate_evidence():
    target_id = create_target("alpha")
    with SessionLocal() as session:
        result = submit_operations(session, **args(target_id, [span(0, 5, "alpha", "z" * 10), {"op": "match", "match": "zz", "replace": "x"}]))
    exact = result.diagnostic["exact_candidates"]
    assert result.failure_reason.value == "match_ambiguous"
    assert exact["occurrence_count"] == 9 and exact["returned_count"] == 5 and exact["truncated"] is True
    assert [candidate["start"] for candidate in exact["candidates"]] == [0, 1, 2, 3, 4]
    assert exact["buffer_stage"] == "intermediate_buffer" and exact["prior_changes"] == 1
    assert exact["observed_target_hash"] == canonical_sha256("alpha")
    assert result.current_context["text"] == "alpha"
    with SessionLocal() as session:
        assert counts(session, target_id) == (1, 0)
        assert session.get(AppendOnlyPdcpLogs, result.pdcp_log_id).diagnostic_json == result.diagnostic


def test_near_miss_comparison_starts_after_service_commit_and_real_lock_release(monkeypatch):
    target_id = create_target("foo  bar")
    actual = pdcp_service.near_misses
    with SessionLocal() as service:
        def check(diagnostic, *, caller_owned):
            assert caller_owned is False and not service.in_transaction()
            with SessionLocal.begin() as independent:
                independent.execute(text("SET LOCAL lock_timeout = '250ms'"))
                assert independent.execute(select_target_for_update(str(target_id))).scalar_one().current_content == "foo  bar"
                assert counts(independent, target_id) == (1, 0)
            return actual(diagnostic, caller_owned=caller_owned)
        monkeypatch.setattr(pdcp_service, "near_misses", check)
        result = submit_edits(service, target_file_id=target_id, expected_target_version=0, intent="space",
                              edits=[{"match": "foo bar", "replace": "x"}])
    assert result.near_misses["status"] == "computed" and result.near_misses["candidates"]


@pytest.mark.parametrize("commit", [False, True])
def test_caller_near_misses_skip_comparison_and_keep_lock_until_owner_end(monkeypatch, commit):
    target_id = create_target("foo  bar")
    monkeypatch.setattr(near_miss_service, "MAX_COMPARISON_CELLS", 0)
    with SessionLocal() as owner:
        owner.begin()
        result = submit_edits(owner, target_file_id=target_id, expected_target_version=0, intent="space",
                              edits=[{"match": "foo bar", "replace": "x"}])
        assert result.near_misses["omission_reason"] == "caller_transaction" and owner.in_transaction()
        with SessionLocal.begin() as independent:
            independent.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError):
                independent.execute(select_target_for_update(str(target_id)))
            independent.rollback()
        owner.commit() if commit else owner.rollback()
    with SessionLocal() as session:
        assert counts(session, target_id) == (int(commit), 0)


def test_unexpected_postcommit_enrichment_failure_propagates_without_undo_or_second_attempt(monkeypatch):
    target_id = create_target("foo  bar")
    arguments = dict(target_file_id=target_id, intent="space", expected_target_version=0,
                     edits=[{"match": "foo bar", "replace": "x"}], client_request_id="postcommit")
    def explode(*args, **kwargs):
        raise RuntimeError("postcommit diagnostic failure")
    with monkeypatch.context() as patch:
        patch.setattr(pdcp_service, "near_misses", explode)
        with SessionLocal() as session, pytest.raises(RuntimeError, match="postcommit diagnostic failure"):
            submit_edits(session, **arguments)
    with SessionLocal() as session:
        assert counts(session, target_id) == (1, 0)
        recovered = submit_edits(session, **arguments)
        assert recovered.deduplicated
    with SessionLocal() as session:
        assert counts(session, target_id) == (1, 0)


def test_original_near_miss_inputs_and_result_stay_separate_from_fresh_recovery(monkeypatch):
    target_id = create_target("foo  bar")
    arguments = dict(target_file_id=target_id, intent="space", expected_target_version=0,
                     edits=[{"match": "foo bar", "replace": "x"}], client_request_id="near-original")
    with SessionLocal() as session:
        first = submit_edits(session, **arguments)
    with SessionLocal() as session:
        assert submit_operations(session, **args(target_id, [span(0, 8, "foo  bar", "later")])).status == "accepted"
    with SessionLocal() as session:
        recovered = submit_edits(session, **arguments, include_correlation_id=True)
    assert recovered.diagnostic == first.diagnostic and recovered.near_misses == first.near_misses
    assert recovered.current_context["text"] == "later" and recovered.current_context["observed_target_version"] == 1
    assert recovered.near_misses["observed_target_version"] == 0
    with SessionLocal() as session:
        assert counts(session, target_id) == (2, 1)
        assert session.get(AppendOnlyPdcpLogs, first.pdcp_log_id).diagnostic_json == first.diagnostic


def test_real_stdio_operations_schema_correlation_candidates_and_replay():
    backend = Path(__file__).resolve().parents[2]
    process = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend), "PATCHDIFF_DATABASE_URL": settings.database_url})
    sequence = 0
    def rpc(method, params):
        nonlocal sequence
        sequence += 1
        process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": sequence, "method": method, "params": params}, ensure_ascii=False)+"\n").encode("utf-8"))
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        assert response["id"] == sequence
        return response["result"]
    def call(name, arguments):
        response = rpc("tools/call", {"name": name, "arguments": arguments})
        assert response["isError"] is False, response
        return json.loads(response["content"][0]["text"])
    try:
        schemas = {tool["name"]: tool["inputSchema"] for tool in rpc("tools/list", {})["tools"]}
        schema = schemas["patchdiff_submit_operations"]
        assert schema["x-patchdiff-capabilities"]["runtime_version"] == OPERATIONS_RUNTIME_VERSION
        assert schema["properties"]["include_correlation_id"] == {
            "type": "boolean", "default": False,
            "description": "Opt in to a fresh response-only UUID invocation ID; never a retry key."}
        initial = call("patchdiff_initialize_target", {"filename": "pass-a-stdio.txt", "content": "a\U0001f642", "content_type": "text/plain"})
        target_id = initial["target_file_id"]
        arguments = args(target_id, [span(1, 2, "\U0001f642", "\U0001f30e")], client_request_id="wire", include_correlation_id=True)
        assert Draft202012Validator(schema).is_valid(arguments)
        first = call("patchdiff_submit_operations", arguments)
        second = call("patchdiff_submit_operations", arguments)
        assert first["status"] == "accepted" and second["deduplicated"] is True
        assert first["correlation_id"] != second["correlation_id"]
        rejected = call("patchdiff_submit_operations", args(target_id, [span(0, 0, "", "zz"), {"op": "match", "match": "z", "replace": "x"}], expected_target_version=1))
        assert rejected["failure_reason"] == "match_ambiguous"
        assert rejected["diagnostic"]["exact_candidates"]["buffer_stage"] == "intermediate_buffer"
        replay = call("patchdiff_replay", {"target_file_id": target_id})
        assert replay["status"] == "success" and replay["materialized_state_matches"] is True
        with SessionLocal() as session:
            assert counts(session, uuid.UUID(target_id)) == (2, 1)
            assert session.get(CloudTargetFiles, uuid.UUID(target_id)).current_content == "a\U0001f30e"
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        assert process.returncode == 0, process.stderr.read().decode("utf-8")


@pytest.mark.parametrize("target_id", ["invalid", str(uuid.uuid4())])
def test_opted_in_unlinked_rejections_still_get_invocation_metadata(target_id):
    with SessionLocal() as session:
        result = submit_operations(session, **args(target_id, include_correlation_id=True))
    assert result.status == "rejected" and result.pdcp_log_id is None
    assert uuid.UUID(result.correlation_id).version == 4


def test_expected_enrichment_omission_and_historical_recovery_do_not_rewrite_rows(monkeypatch):
    target_id = create_target("alphb")
    arguments = dict(target_file_id=target_id, intent="near", expected_target_version=0,
                     edits=[{"match": "alpha", "replace": "x"}], client_request_id="historical-query")
    with monkeypatch.context() as patch:
        patch.setattr(near_miss_service, "MAX_COMPARISON_CELLS", 0)
        with SessionLocal() as session:
            first = submit_edits(session, **arguments)
    assert first.status == "rejected" and first.near_misses["omission_reason"] == "work_budget_exhausted"
    with SessionLocal.begin() as session:
        log = session.get(AppendOnlyPdcpLogs, first.pdcp_log_id)
        historical = {key: value for key, value in log.diagnostic_json.items() if key != "near_miss_query"}
        log.diagnostic_json = historical
    with SessionLocal() as session:
        result = submit_edits(session, **arguments)
    assert result.deduplicated and result.near_misses["omission_reason"] == "historical_context_unavailable"
    assert result.diagnostic == historical
    with SessionLocal() as session:
        assert counts(session, target_id) == (1, 0)
        assert session.get(AppendOnlyPdcpLogs, first.pdcp_log_id).diagnostic_json == historical
