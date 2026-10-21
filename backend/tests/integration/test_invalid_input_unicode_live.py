"""Actual PostgreSQL and stdio proof for safely audited invalid input."""

import json
from dataclasses import asdict
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.input_text import invalid_text_paths
from app.core.validity import ValidationStage
from app.core.versions import PRE_SELECTOR_RUNTIME_VERSION
from app.pdcp.typed import canonical_record_json, decode_record
from app.services import pdcp_service
from app.services.replay_service import replay_target
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles
from backend.tests.integration.helpers import create_target, pdcp_for


def arguments(target_id, value="\ud800"):
    return dict(target_file_id=target_id, expected_target_version=0, intent="Unicode rejection",
                edits=[{"match": "alpha", "replace": value}], client_request_id="unicode-attempt")


@pytest.mark.parametrize("bad", ["\ud800", "\udfff", "\x00"])
@pytest.mark.parametrize("case", ["replace", "metadata", "nested_key", "legacy"])
def test_invalid_strings_are_durable_safe_and_recoverable(bad, case):
    target_id = create_target("alpha")
    args = arguments(target_id, bad)
    if case == "metadata":
        args.update(edits=[{"match": "alpha", "replace": "beta"}], submission_source=bad,
                    expected_current_hash=bad, parent_pdcp_log_id=bad, attempt=bad)
    elif case == "nested_key":
        args["edits"] = [{"match": "alpha", "replace": "beta", "unknown": {bad: [bad]}}]
    elif case == "legacy":
        args = dict(target_file_id=target_id,
                    pdcp_content=pdcp_for(target_id, ("alpha", bad)),
                    expected_target_version=0, client_request_id="unicode-attempt",
                    regeneration_source=bad)
    submit = pdcp_service.submit_pdcp if case == "legacy" else pdcp_service.submit_edits
    with SessionLocal() as session:
        result = submit(session, **args)
        assert result.failure_reason is FailureReason.TARGET_ENCODING_INVALID
        assert result.validation_stage is ValidationStage.PROTOCOL_VALIDATION
        assert result.pdcp_log_id is not None
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target.current_content == "alpha" and target.version == 0
        assert target.current_hash == canonical_sha256("alpha")
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log.pdcp_content.isascii()
        assert log.pdcp_content_hash == canonical_sha256(log.pdcp_content)
        assert log.diagnostic_json["evidence_format"] == "patchdiff-invalid-input/1"
        assert not invalid_text_paths(log.diagnostic_json)
        envelope = json.loads(log.pdcp_content)
        assert envelope["evidence_format"] == "patchdiff-invalid-input/1"
        assert invalid_text_paths(envelope["inputs"])
        assert session.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id
        )) == 0
    # Recovery must precede stale guards even after a later real edit.
    with SessionLocal() as session:
        good = pdcp_service.submit_edits(session, target_file_id=target_id,
            expected_target_version=0, intent="Real edit", edits=[{"match": "alpha", "replace": "gamma"}])
        assert good.status == "accepted"
    with SessionLocal() as session:
        recovered = submit(session, **args)
        assert recovered.deduplicated
        assert recovered.pdcp_log_id == result.pdcp_log_id
        assert recovered.failure_reason is FailureReason.TARGET_ENCODING_INVALID
        assert recovered.before_version == 0 and recovered.current_version == 1
        assert recovered.diagnostic == result.diagnostic
        assert session.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id
        )) == 2


@pytest.mark.parametrize("invalid_key", ["\ud800", "\udfff", "\x00"])
def test_invalid_request_key_is_never_bound_or_persisted_as_a_key(invalid_key):
    target_id = create_target("alpha")
    with SessionLocal() as session:
        result = pdcp_service.submit_edits(session, **{
            **arguments(target_id, "beta"), "client_request_id": invalid_key,
        })
        assert result.failure_reason is FailureReason.TARGET_ENCODING_INVALID
    with SessionLocal() as session:
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log.client_request_id is None
        assert log.request_fingerprint is None
        assert json.loads(log.pdcp_content)["inputs"]["client_request_id"] == invalid_key


@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_invalid_rejection_respects_caller_owned_transaction(finish):
    target_id = create_target("alpha")
    with SessionLocal() as owner:
        transaction = owner.begin()
        result = pdcp_service.submit_edits(owner, **arguments(target_id))
        assert owner.in_transaction()
        with SessionLocal() as observer:
            assert observer.get(AppendOnlyPdcpLogs, result.pdcp_log_id) is None
        getattr(transaction, finish)()
    with SessionLocal() as observer:
        log = observer.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert (log is not None) is (finish == "commit")
        target = observer.get(CloudTargetFiles, target_id)
        assert target.current_content == "alpha" and target.version == 0


def terminal_outcome(result):
    """Compare the recorded outcome, excluding intentionally refreshed target state."""
    values = asdict(result)
    for name in ("deduplicated", "current_hash", "current_version"):
        values.pop(name)
    return values


@pytest.mark.parametrize("first_status", ["accepted", "rejected"])
def test_historical_nul_anchor_outcome_recovers_before_and_after_later_edits(monkeypatch, first_status):
    target_id = create_target("alpha")
    args = arguments(target_id, "beta")
    args["edits"][0].update(
        anchor_before="\x00", match="alpha" if first_status == "accepted" else "absent")
    with SessionLocal() as session:
        # Reconstruct the pre-fix boundary; only JSON-escaped NUL is stored in TEXT.
        with monkeypatch.context() as old:
            old.setattr(pdcp_service, "RUNTIME_VERSION", PRE_SELECTOR_RUNTIME_VERSION)
            old.setattr(pdcp_service, "invalid_text_paths", lambda value: ())
            old.setattr(pdcp_service, "parse_typed_record", lambda record: decode_record(
                canonical_record_json(record), runtime_version=PRE_SELECTOR_RUNTIME_VERSION))
            original = pdcp_service.submit_edits(session, **args)
        assert original.status == first_status
        if first_status == "rejected":
            assert original.failure_reason is FailureReason.MATCH_ABSENT
        expected_outcome = terminal_outcome(original)
        log = session.get(AppendOnlyPdcpLogs, original.pdcp_log_id)
        recorded = (
            log.pdcp_log_id, log.pdcp_content, log.pdcp_content_hash, log.request_fingerprint,
            log.before_hash, log.after_hash, log.before_version, log.after_version,
            json.dumps(log.diagnostic_json, sort_keys=True),
        )

        def original_evidence():
            session.refresh(log)
            original_ledger = session.scalars(select(AppendOnlyManifestLedger).where(
                AppendOnlyManifestLedger.pdcp_log_id == original.pdcp_log_id
            ).order_by(AppendOnlyManifestLedger.change_index)).all()
            return (
                (
                    log.pdcp_log_id, log.pdcp_content, log.pdcp_content_hash, log.request_fingerprint,
                    log.before_hash, log.after_hash, log.before_version, log.after_version,
                    json.dumps(log.diagnostic_json, sort_keys=True),
                ),
                tuple((row.change_id, row.origin, json.dumps(row.derived_json, sort_keys=True))
                      for row in original_ledger),
            )

        recorded_evidence = original_evidence()
        assert recorded_evidence[0] == recorded
        assert "\\u0000" in log.pdcp_content and "\x00" not in log.pdcp_content
        replay = replay_target(session, target_file_id=target_id)
        assert replay.status == "success" and replay.materialized_state_matches
        content = "beta" if first_status == "accepted" else "alpha"
        version = 1 if first_status == "accepted" else 0
        assert replay.reconstructed_content == content
        immediate = pdcp_service.submit_edits(session, **args)
        assert immediate.deduplicated
        assert terminal_outcome(immediate) == expected_outcome
        assert immediate.current_version == version
        assert immediate.current_hash == canonical_sha256(content)
        assert original_evidence() == recorded_evidence
        assert session.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)) == 1
        assert session.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id)) == version
        session.commit()

        later = pdcp_service.submit_edits(
            session, target_file_id=target_id, expected_target_version=version,
            intent="Later normal edit", edits=[{"match": content, "replace": "gamma"}],
            client_request_id="later-normal-edit")
        assert later.status == "accepted"
        recovered = pdcp_service.submit_edits(session, **args)
        assert recovered.deduplicated
        assert terminal_outcome(recovered) == expected_outcome
        assert recovered.current_version == version + 1
        assert recovered.current_hash == canonical_sha256("gamma")
        assert original_evidence() == recorded_evidence
        assert session.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)) == 2
        assert session.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id)) == version + 1
        final_replay = replay_target(session, target_file_id=target_id)
        assert final_replay.status == "success" and final_replay.materialized_state_matches
        assert final_replay.reconstructed_content == "gamma"


def test_real_stdio_invalid_unicode_is_a_domain_rejection_with_readable_evidence():
    target_id = create_target("alpha")
    backend = Path(__file__).resolve().parents[2]
    calls = [
        ("patchdiff_submit_edits", arguments(str(target_id))),
        ("patchdiff_get_pdcp_log", {"target_file_id": str(target_id), "include_content": True}),
        ("patchdiff_find_occurrences", {"target_file_id": str(target_id), "text": "\udfff"}),
        ("patchdiff_export_target", {"target_file_id": str(target_id), "format": "\ud800"}),
        ("patchdiff_read_target", {"target_file_id": "\ud800"}),
    ]
    messages = [
        {"jsonrpc": "2.0", "id": index, "method": "tools/call",
         "params": {"name": name, "arguments": kwargs}}
        for index, (name, kwargs) in enumerate(calls, 1)
    ]
    process = subprocess.run([sys.executable, "-m", "app.mcp.external_adapter"],
        input="\n".join(json.dumps(message, ensure_ascii=True) for message in messages) + "\n",
        capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend),
             "PATCHDIFF_DATABASE_URL": settings.database_url})
    assert process.returncode == 0, process.stderr
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(replies) == len(calls)
    assert all(reply["result"]["isError"] is False for reply in replies)
    rejected, history, *reads = [json.loads(reply["result"]["content"][0]["text"]) for reply in replies]
    assert rejected["failure_reason"] == "target_encoding_invalid"
    assert rejected["diagnostic"]["validation_stage"] == "protocol_validation"
    log = history["entries"][0]
    assert log["pdcp_log_id"] == rejected["pdcp_log_id"]
    evidence = json.loads(log["pdcp_content"])
    assert evidence["inputs"]["record"]["edits"][0]["replace"] == "\ud800"
    assert not invalid_text_paths(log)
    assert all(read["status"] == "invalid_argument" for read in reads)
    assert not invalid_text_paths(reads)


@pytest.mark.parametrize("bad_parent", ["\ud800", "\x00"])
def test_historical_rejected_invalid_parent_keeps_original_keyed_recovery(monkeypatch, bad_parent):
    target_id = create_target("alpha")
    args = arguments(target_id, "beta")
    args["parent_pdcp_log_id"] = bad_parent
    with SessionLocal() as session:
        with monkeypatch.context() as old:
            old.setattr(pdcp_service, "RUNTIME_VERSION", PRE_SELECTOR_RUNTIME_VERSION)
            old.setattr(pdcp_service, "invalid_text_paths", lambda value: ())
            original = pdcp_service.submit_edits(session, **args)
        assert original.failure_reason is FailureReason.CONTEXT_INVALID
        log = session.get(AppendOnlyPdcpLogs, original.pdcp_log_id)
        recorded = (log.pdcp_content, log.pdcp_content_hash, log.request_fingerprint)
        assert "evidence_format" not in log.diagnostic_json
        recovered = pdcp_service.submit_edits(session, **args)
        assert recovered.deduplicated and recovered.pdcp_log_id == original.pdcp_log_id
        assert recovered.failure_reason is FailureReason.CONTEXT_INVALID
        assert terminal_outcome(recovered) == terminal_outcome(original)
        assert (log.pdcp_content, log.pdcp_content_hash, log.request_fingerprint) == recorded
        assert session.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)) == 1
        session.commit()
        later = pdcp_service.submit_edits(
            session, target_file_id=target_id, expected_target_version=0,
            intent="Later normal edit", edits=[{"match": "alpha", "replace": "gamma"}])
        assert later.status == "accepted"
        recovered = pdcp_service.submit_edits(session, **args)
        assert recovered.deduplicated and terminal_outcome(recovered) == terminal_outcome(original)
        assert recovered.current_version == 1 and recovered.current_hash == canonical_sha256("gamma")
        session.refresh(log)
        assert (log.pdcp_content, log.pdcp_content_hash, log.request_fingerprint) == recorded
        assert session.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)) == 2
        assert session.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id)) == 1


@pytest.mark.parametrize("finish", ["commit", "rollback"])
@pytest.mark.parametrize("replacement", ["beta", "\ud800"])
def test_regeneration_wrapper_does_not_commit_the_callers_transaction(finish, replacement):
    from app.services.regeneration_service import request_regeneration
    target_id = create_target("alpha")
    with SessionLocal() as session:
        parent = pdcp_service.submit_edits(session, target_file_id=target_id,
            expected_target_version=0, intent="Rejected parent",
            edits=[{"match": "absent", "replace": "unused"}])
    with SessionLocal() as owner:
        transaction = owner.begin()
        output = request_regeneration(
            owner, pdcp_log_id=parent.pdcp_log_id,
            regenerated_pdcp_content=pdcp_for(target_id, ("alpha", replacement)),
            expected_target_version=0,
        )
        result = output["result"]
        assert owner.in_transaction()
        with SessionLocal() as observer:
            assert observer.get(AppendOnlyPdcpLogs, result.pdcp_log_id) is None
            assert observer.get(CloudTargetFiles, target_id).version == 0
        getattr(transaction, finish)()
    with SessionLocal() as observer:
        log = observer.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert (log is not None) is (finish == "commit")
        target = observer.get(CloudTargetFiles, target_id)
        expected_version = 1 if finish == "commit" and replacement == "beta" else 0
        assert target.version == expected_version
        if replacement == "\ud800":
            assert result.failure_reason is FailureReason.TARGET_ENCODING_INVALID


def test_standalone_mcp_regeneration_wrapper_persists_its_own_transaction():
    from app.mcp.tools import patchdiff_request_regeneration
    target_id = create_target("alpha")
    with SessionLocal() as session:
        parent = pdcp_service.submit_edits(session, target_file_id=target_id,
            expected_target_version=0, intent="Rejected parent",
            edits=[{"match": "absent", "replace": "unused"}])
    output = patchdiff_request_regeneration(
        pdcp_log_id=str(parent.pdcp_log_id),
        regenerated_pdcp_content=pdcp_for(target_id, ("alpha", "beta")),
        expected_target_version=0,
    )
    assert output["status"] == "accepted"
    with SessionLocal() as observer:
        assert observer.get(CloudTargetFiles, target_id).current_content == "beta"
        assert observer.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)) == 2


@pytest.mark.parametrize("leaf", ["\ud800", "\x00", "deep valid 😀"])
def test_depth_500_json_reaches_a_durable_domain_rejection(leaf):
    target_id = create_target("alpha")
    nested = leaf
    for _ in range(500):
        nested = [nested]
    wire = json.dumps(nested, ensure_ascii=True)
    assert len(wire) < 1200
    decoded = json.loads(wire)
    args = arguments(target_id, "beta")
    args["edits"][0]["unknown"] = decoded
    with SessionLocal() as session:
        result = pdcp_service.submit_edits(session, **args)
        expected = (FailureReason.MANIFEST_INVALID if leaf == "deep valid 😀"
                    else FailureReason.TARGET_ENCODING_INVALID)
        assert result.failure_reason is expected
        assert result.validation_stage is ValidationStage.PROTOCOL_VALIDATION
    with SessionLocal() as observer:
        log = observer.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log is not None and log.status == "rejected"
        assert not invalid_text_paths(log.diagnostic_json)
        stored = json.loads(log.pdcp_content)
        if expected is FailureReason.TARGET_ENCODING_INVALID:
            assert stored["evidence_format"] == "patchdiff-invalid-input/1"
            stored = stored["inputs"]["record"]
        recovered = stored["edits"][0]["unknown"]
        for _ in range(500):
            recovered = recovered[0]
        assert recovered == leaf
        target = observer.get(CloudTargetFiles, target_id)
        assert target.current_content == "alpha" and target.version == 0
        assert observer.scalar(select(func.count()).select_from(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id)) == 1
        assert observer.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id)) == 0
