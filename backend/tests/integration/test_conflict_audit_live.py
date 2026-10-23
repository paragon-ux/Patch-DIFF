"""Immutable conflict attempts, real row-lock interleavings, and terminal recovery."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.input_text import invalid_text_paths
from app.core.validity import ValidationStage
from app.services import pdcp_service
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles
from backend.tests.integration.helpers import create_target, pdcp_for


def arguments(target_id, status="accepted"):
    return dict(target_file_id=target_id, expected_target_version=0, intent="Original request",
                edits=[{"match": "alpha" if status == "accepted" else "absent", "replace": "beta"}],
                client_request_id="stable-key")


def terminal(result):
    result = asdict(result)
    for key in ("deduplicated", "current_hash", "current_version", "current_context", "near_misses", "correlation_id",
                "near_miss_buffer"):
        result.pop(key)
    return result


@pytest.mark.parametrize("format_", ["typed", "legacy"])
@pytest.mark.parametrize("first_status", ["accepted", "rejected"])
@pytest.mark.parametrize("replacement", ["gamma", "\ud800"])
def test_repeated_conflicts_append_null_key_attempts_preserving_original(format_, first_status, replacement):
    target_id = create_target("alpha")
    args = arguments(target_id, first_status)
    if format_ == "legacy":
        args = dict(target_file_id=target_id, expected_target_version=0,
                    pdcp_content=pdcp_for(target_id, (
                        "alpha" if first_status == "accepted" else "absent", "beta")),
                    client_request_id="stable-key")
    submit = pdcp_service.submit_edits if format_ == "typed" else pdcp_service.submit_pdcp
    with SessionLocal() as session:
        original = submit(session, **args)
        assert original.status == first_status
    with SessionLocal() as session:
        log = session.get(AppendOnlyPdcpLogs, original.pdcp_log_id)
        original_bytes = (log.pdcp_content, log.pdcp_content_hash, log.request_fingerprint)
        conflict_args = {**args}
        if format_ == "typed":
            conflict_args.update(intent="Different proposal", edits=[{
                "match": "alpha" if first_status == "accepted" else "absent", "replace": replacement}])
        else:
            conflict_args["pdcp_content"] = pdcp_for(target_id, (
                "alpha" if first_status == "accepted" else "absent", replacement))
        conflicts = [submit(session, **conflict_args) for _ in range(3)]
        assert len({attempt.pdcp_log_id for attempt in conflicts}) == 3
        assert all(attempt.status == "rejected" and not attempt.deduplicated for attempt in conflicts)
        for attempt in conflicts:
            assert attempt.failure_reason is FailureReason.CONTEXT_INVALID
            assert attempt.client_request_id == "stable-key"
            assert attempt.validation_stage is ValidationStage.PRECONDITION_GUARD
            assert attempt.diagnostic["existing_pdcp_log_id"] == str(original.pdcp_log_id)
            assert attempt.diagnostic["submitted_client_request_id"] == "stable-key"
        recovered = submit(session, **args)
        assert recovered.deduplicated and terminal(recovered) == terminal(original)
        session.commit()
    with SessionLocal() as observer:
        logs = observer.scalars(select(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id
        ).order_by(AppendOnlyPdcpLogs.log_sequence)).all()
        assert len(logs) == 4
        assert logs[0].client_request_id == "stable-key"
        assert (logs[0].pdcp_content, logs[0].pdcp_content_hash, logs[0].request_fingerprint) == original_bytes
        for conflict in logs[1:]:
            assert conflict.client_request_id is None
            assert conflict.request_fingerprint != logs[0].request_fingerprint
            domain = conflict.diagnostic_json.get("evidence_format")
            assert conflict.request_fingerprint == pdcp_service._compute_request_fingerprint(
                protocol_version=conflict.protocol_version, target_file_id=str(target_id),
                pdcp_content_hash=conflict.pdcp_content_hash, expected_target_version=0,
                expected_current_hash=None, parent_pdcp_log_id=None, identity_domain=domain)
            assert not invalid_text_paths(conflict.diagnostic_json)
            if replacement == "\ud800":
                assert domain == "patchdiff-invalid-input/1" and conflict.pdcp_content.isascii()
        assert len({log.request_fingerprint for log in logs[1:]}) == 1
        target = observer.get(CloudTargetFiles, target_id)
        assert target.current_content == ("beta" if first_status == "accepted" else "alpha")
        assert target.version == (1 if first_status == "accepted" else 0)
        assert observer.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id)) == target.version


@pytest.mark.parametrize("first_status", ["accepted", "rejected"])
@pytest.mark.parametrize("finish", ["commit", "rollback"])
@pytest.mark.parametrize("second_payload", ["identical", "conflicting"])
def test_concurrent_keyed_requests_serialize_at_read_committed(first_status, finish, second_payload):
    target_id = create_target("alpha")
    args = arguments(target_id, first_status)
    second_args = {**args}
    if second_payload == "conflicting":
        second_args["intent"] = "Second proposal"
    ready = Event()
    second_pid = []
    with SessionLocal() as first, ThreadPoolExecutor(max_workers=1) as executor:
        first_transaction = first.begin()
        first.execute(text("SET LOCAL lock_timeout = '8s'"))
        first.execute(text("SET LOCAL statement_timeout = '15s'"))
        assert first.scalar(text("SHOW transaction_isolation")) == "read committed"
        first_pid = first.scalar(text("SELECT pg_backend_pid()"))
        original = pdcp_service.submit_edits(first, **args)
        assert first.in_transaction()

        def second_request():
            with SessionLocal() as second, second.begin():
                second.execute(text("SET LOCAL lock_timeout = '8s'"))
                second.execute(text("SET LOCAL statement_timeout = '15s'"))
                assert second.scalar(text("SHOW transaction_isolation")) == "read committed"
                second_pid.append(second.scalar(text("SELECT pg_backend_pid()")))
                ready.set()
                return pdcp_service.submit_edits(second, **second_args)

        future = executor.submit(second_request)
        try:
            assert ready.wait(5), "second connection did not reach its submit"
            blockers = []
            poll_pause = Event()
            deadline = time.monotonic() + 5
            with SessionLocal() as monitor:
                while time.monotonic() < deadline:
                    blockers = monitor.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": second_pid[0]})
                    if first_pid in blockers:
                        break
                    poll_pause.wait(0.01)
                assert first_pid in blockers, "no observed PostgreSQL target-lock wait"
                assert not future.done()
                assert monitor.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
                    AppendOnlyPdcpLogs.target_file_id == target_id)) == 0
                assert monitor.get(CloudTargetFiles, target_id).version == 0
            getattr(first_transaction, finish)()
            result = future.result(timeout=10)
        finally:
            if first.in_transaction():
                first.rollback()

    with SessionLocal() as observer:
        logs = observer.scalars(select(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)).all()
        committed_conflict = finish == "commit" and second_payload == "conflicting"
        assert len(logs) == (2 if committed_conflict else 1)
        assert len([log for log in logs if log.client_request_id == "stable-key"]) == 1
        if finish == "commit" and second_payload == "identical":
            assert result.deduplicated and terminal(result) == terminal(original)
        elif committed_conflict:
            assert result.failure_reason is FailureReason.CONTEXT_INVALID and not result.deduplicated
            assert result.pdcp_log_id != original.pdcp_log_id
            assert observer.get(AppendOnlyPdcpLogs, result.pdcp_log_id).client_request_id is None
        else:
            assert not result.deduplicated and result.status == first_status
            assert result.pdcp_log_id != original.pdcp_log_id
            assert observer.get(AppendOnlyPdcpLogs, original.pdcp_log_id) is None
        target = observer.get(CloudTargetFiles, target_id)
        assert target.version == (1 if first_status == "accepted" else 0)
        assert target.current_content == ("beta" if first_status == "accepted" else "alpha")
        assert observer.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id)) == target.version


@pytest.mark.parametrize("first_status", ["accepted", "rejected"])
@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_conflict_audit_respects_caller_owned_transaction(first_status, finish):
    target_id = create_target("alpha")
    args = arguments(target_id, first_status)
    with SessionLocal() as session:
        original = pdcp_service.submit_edits(session, **args)
    conflict_args = {**args, "intent": "Conflicting proposal"}
    with SessionLocal() as owner:
        transaction = owner.begin()
        conflicts = [pdcp_service.submit_edits(owner, **conflict_args) for _ in range(2)]
        assert owner.in_transaction()
        assert len({conflict.pdcp_log_id for conflict in conflicts}) == 2
        with SessionLocal() as observer:
            assert observer.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
                AppendOnlyPdcpLogs.target_file_id == target_id)) == 1
            assert all(observer.get(AppendOnlyPdcpLogs, conflict.pdcp_log_id) is None
                       for conflict in conflicts)
        getattr(transaction, finish)()
    with SessionLocal() as observer:
        assert observer.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)) == (3 if finish == "commit" else 1)
        target = observer.get(CloudTargetFiles, target_id)
        assert target.version == (1 if first_status == "accepted" else 0)
        assert observer.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id)) == target.version
        recovered = pdcp_service.submit_edits(observer, **args)
        assert recovered.deduplicated and terminal(recovered) == terminal(original)


@pytest.mark.parametrize("kind", [
    "accepted", "precondition_rejection", "protocol_rejection",
    "applicability_rejection", "commit_guard_rejection",
])
def test_recovery_preserves_complete_terminal_evidence_after_later_edit(kind):
    target_id = create_target("alpha")
    args = arguments(target_id)
    expected_stage = {
        "accepted": ValidationStage.ACCEPTED,
        "precondition_rejection": ValidationStage.PRECONDITION_GUARD,
        "protocol_rejection": ValidationStage.PROTOCOL_VALIDATION,
        "applicability_rejection": ValidationStage.TRANSACTION_APPLICABILITY,
        "commit_guard_rejection": ValidationStage.COMMIT_GUARD,
    }[kind]
    if kind == "accepted":
        args["edits"].append({"match": "beta", "replace": "gamma"})
    elif kind == "precondition_rejection":
        args["expected_target_version"] = 99
    elif kind == "protocol_rejection":
        args["edits"][0]["risk"] = "not-valid"
    elif kind == "applicability_rejection":
        args["edits"][0]["match"] = "absent"
    else:
        args["_before_final_guard"] = lambda target: setattr(target, "version", target.version + 1)
    with SessionLocal() as session:
        original = pdcp_service.submit_edits(session, **args)
        assert original.validation_stage is expected_stage
        assert original.status == ("accepted" if kind == "accepted" else "rejected")
    args.pop("_before_final_guard", None)
    with SessionLocal() as session:
        original_log = session.get(AppendOnlyPdcpLogs, original.pdcp_log_id)

        def snapshot():
            session.refresh(original_log)
            facts = session.scalars(select(AppendOnlyManifestLedger).where(
                AppendOnlyManifestLedger.pdcp_log_id == original.pdcp_log_id
            ).order_by(AppendOnlyManifestLedger.change_index)).all()
            return (
                original_log.pdcp_log_id, original_log.pdcp_content, original_log.pdcp_content_hash,
                original_log.request_fingerprint, original_log.before_hash, original_log.after_hash,
                original_log.before_version, original_log.after_version, original_log.failure_reason,
                original_log.failure_detail, original_log.failed_change_id,
                json.dumps(original_log.diagnostic_json, sort_keys=True),
                tuple((row.change_id, json.dumps(row.derived_json, sort_keys=True)) for row in facts),
            )

        original_snapshot = snapshot()
        immediate = pdcp_service.submit_edits(session, **args)
        assert immediate.deduplicated and terminal(immediate) == terminal(original)
        assert snapshot() == original_snapshot
        session.commit()
        accepted_original = kind == "accepted"
        later = pdcp_service.submit_edits(
            session, target_file_id=target_id,
            expected_target_version=1 if accepted_original else 0,
            intent="Later independent edit",
            edits=[{"match": "gamma" if accepted_original else "alpha", "replace": "later"}],
            client_request_id="later-key")
        assert later.status == "accepted"
        recovered = pdcp_service.submit_edits(session, **args)
        assert recovered.deduplicated and terminal(recovered) == terminal(original)
        assert recovered.current_version == (2 if accepted_original else 1)
        assert recovered.current_hash == canonical_sha256("later")
        assert snapshot() == original_snapshot
        assert session.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)) == 2
        assert session.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id)) == (3 if accepted_original else 1)
        if accepted_original:
            assert len(recovered.change_facts) == recovered.manifest_entries_added == 2
        else:
            assert recovered.diagnostic == original.diagnostic
            assert recovered.failure_reason == original.failure_reason
            assert recovered.current_context["text"] == "later"
            assert recovered.current_context["observed_target_version"] == 1
            assert recovered.current_context["observed_target_hash"] == recovered.current_hash
            assert recovered.diagnostic["failure_context"]["text"] == "alpha"


def test_real_stdio_conflict_audit_and_original_recovery():
    target_id = create_target("alpha")
    backend = Path(__file__).resolve().parents[2]
    original_args = arguments(str(target_id))
    calls = [
        ("patchdiff_submit_edits", original_args),
        ("patchdiff_submit_edits", {**original_args, "intent": "Conflicting proposal"}),
        ("patchdiff_submit_edits", original_args),
        ("patchdiff_get_pdcp_log", {"target_file_id": str(target_id)}),
    ]
    messages = [
        {"jsonrpc": "2.0", "id": index, "method": "tools/call",
         "params": {"name": name, "arguments": kwargs}}
        for index, (name, kwargs) in enumerate(calls, 1)
    ]
    process = subprocess.run([sys.executable, "-m", "app.mcp.external_adapter"],
        input="\n".join(json.dumps(message) for message in messages) + "\n",
        capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend),
             "PATCHDIFF_DATABASE_URL": settings.database_url})
    assert process.returncode == 0, process.stderr
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(replies) == len(calls)
    assert all(reply["result"]["isError"] is False for reply in replies)
    original, conflict, recovered, history = [
        json.loads(reply["result"]["content"][0]["text"]) for reply in replies]
    assert original["status"] == recovered["status"] == "accepted"
    assert recovered["deduplicated"] and recovered["pdcp_log_id"] == original["pdcp_log_id"]
    assert recovered["evidence"] == original["evidence"]
    assert conflict["status"] == "rejected" and conflict["failure_reason"] == "context_invalid"
    assert conflict["pdcp_log_id"] != original["pdcp_log_id"]
    assert conflict["client_request_id"] == "stable-key"
    assert conflict["diagnostic"]["existing_pdcp_log_id"] == original["pdcp_log_id"]
    assert len(history["entries"]) == 2
    assert history["entries"][0]["pdcp_log_id"] == conflict["pdcp_log_id"]
    assert history["entries"][0]["client_request_id"] is None
    assert history["entries"][1]["client_request_id"] == "stable-key"
