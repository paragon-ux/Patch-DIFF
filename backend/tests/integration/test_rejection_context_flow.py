"""Live PostgreSQL and public stdio F01 rejection evidence/observation checks."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.hashing import canonical_sha256
from app.mcp.tools import _submit_result_to_payload
from app.services.pdcp_service import submit_edits, submit_pdcp
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles
from backend.tests.integration.helpers import create_target, pdcp_for


def _counts(session, target_id):
    return tuple(session.scalar(select(func.count()).select_from(model).where(model.target_file_id == target_id))
                 for model in (AppendOnlyPdcpLogs, AppendOnlyManifestLedger))


def _submit(session, target_id, **kwargs):
    return submit_edits(session, **{
        "target_file_id": target_id, "intent": "F01 test", "expected_target_version": 0,
        "edits": [{"match": "alpha", "replace": "ALPHA"}], **kwargs,
    })


def _assert_context(context, content, version=0, *, prior=0, target_content=None):
    assert context == {
        "available": True, "unavailable_reason": None, "selection": "prefix",
        "buffer_stage": "intermediate_buffer" if prior else "canonical_target", "prior_changes": prior,
        "start": 0, "end": min(256, len(content)), "total_chars": len(content),
        "text": content[:256], "truncated": len(content) > 256,
        "observed_target_version": version,
        "observed_target_hash": canonical_sha256(content if target_content is None else target_content),
    }


@pytest.mark.parametrize("case,reason", [
    ("stale_version", "target_version_mismatch"), ("stale_hash", "target_hash_mismatch"),
    ("protocol", "manifest_missing"), ("encoding", "target_encoding_invalid"),
    ("lineage", "context_invalid"), ("request_key", "context_invalid"), ("attempt", "context_invalid"),
    ("absent", "match_absent"), ("ambiguous", "match_ambiguous"),
    ("selector", "disambiguation_invalid"), ("sequential", "sequential_match_invalid"),
    ("later_absent", "match_absent"), ("later_ambiguous", "match_ambiguous"),
    ("later_selector", "disambiguation_invalid"), ("commit_guard", "target_diverged"),
])
def test_locked_rejections_capture_original_buffer_without_mutation(case, reason):
    content = "alpha alpha" if case == "ambiguous" else "alpha beta"
    target_id = create_target(content)
    options = {
        "stale_version": {"expected_target_version": 1},
        "stale_hash": {"expected_current_hash": "0" * 64},
        "protocol": {"edits": []},
        "encoding": {"edits": [{"match": "alpha", "replace": "\ud800"}]},
        "lineage": {"parent_pdcp_log_id": str(uuid.uuid4())},
        "request_key": {"client_request_id": "invalid key"},
        "attempt": {"attempt": 0},
        "absent": {"edits": [{"match": "absent", "replace": "x"}]},
        "selector": {"edits": [{"match": "alpha", "replace": "x", "occurrence_index": 2}]},
        "sequential": {"edits": [{"match": "alpha", "replace": "ALPHA"}, {"match": "alpha", "replace": "x"}]},
        "later_absent": {"edits": [{"match": "alpha", "replace": "ALPHA"}, {"match": "absent", "replace": "x"}]},
        "later_ambiguous": {"edits": [{"match": "alpha", "replace": "z z"}, {"match": "z", "replace": "x"}]},
        "later_selector": {"edits": [{"match": "alpha", "replace": "ALPHA"}, {"match": "ALPHA", "replace": "x", "occurrence_index": 2}]},
        "commit_guard": {"_before_final_guard": lambda target: setattr(target, "version", target.version + 1)},
    }.get(case, {})
    with SessionLocal() as session:
        result = _submit(session, target_id, **options)
    assert result.failure_reason.value == reason
    prior = int(case in ("sequential", "later_absent", "later_ambiguous", "later_selector"))
    failed_content = "z z beta" if case == "later_ambiguous" else "ALPHA beta" if prior else content
    _assert_context(result.diagnostic["failure_context"], failed_content,
                    prior=prior, target_content=content)
    _assert_context(result.current_context, content)
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert (target.current_content, target.version, target.current_hash) == (content, 0, canonical_sha256(content))
        assert _counts(session, target_id) == (1, 0)
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log.diagnostic_json == result.diagnostic
        assert "current_context" not in log.diagnostic_json
        assert log.after_hash is None and log.after_version is None


@pytest.mark.parametrize("content", ["", "x" * 255, "x" * 256, "x" * 257, "\U0001f642" * 400, '\x01\t\n"\\' * 100])
def test_locked_context_empty_unicode_and_cap_boundaries(content):
    target_id = create_target(content)
    with SessionLocal() as session:
        result = _submit(session, target_id, edits=[{"match": "missing", "replace": "x"}])
    _assert_context(result.current_context, content)
    assert result.diagnostic["failure_context"] == result.current_context
    payload = {"failure_context": result.diagnostic["failure_context"], "current_context": result.current_context}
    assert len(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 8192


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("historical", [False, True])
def test_recovered_rejection_keeps_exact_original_diagnostic_and_fresh_locked_context(legacy, historical):
    target_id = create_target("alpha beta")
    args = {"target_file_id": target_id, "expected_target_version": 0, "client_request_id": "f01-original"}
    if legacy:
        args["pdcp_content"] = pdcp_for(target_id, ("missing", "x"))
        submit = submit_pdcp
    else:
        args.update(intent="F01 recovery", edits=[{"match": "missing", "replace": "x"}])
        submit = submit_edits
    with SessionLocal() as session:
        first = submit(session, **args)
    if historical:
        # Fixture a pre-F01 row; this is not a product retrofit or an API mutation.
        with SessionLocal.begin() as session:
            log = session.get(AppendOnlyPdcpLogs, first.pdcp_log_id)
            log.diagnostic_json = {key: value for key, value in log.diagnostic_json.items() if key != "failure_context"}
    with SessionLocal() as session:
        original = json.dumps(session.get(AppendOnlyPdcpLogs, first.pdcp_log_id).diagnostic_json, sort_keys=True)
    with SessionLocal() as session:
        accepted = _submit(session, target_id)
        assert accepted.status == "accepted"
        assert "current_context" not in _submit_result_to_payload(accepted)
    with SessionLocal() as session:
        recovered = submit(session, **args)
    assert recovered.deduplicated is True and recovered.pdcp_log_id == first.pdcp_log_id
    assert json.dumps(recovered.diagnostic, sort_keys=True) == original
    assert ("failure_context" in recovered.diagnostic) is not historical
    _assert_context(recovered.current_context, "ALPHA beta", version=1)
    if not historical:
        assert recovered.diagnostic["failure_context"] == first.current_context
    with SessionLocal() as session:
        assert _counts(session, target_id) == (2, 1)
        assert json.dumps(session.get(AppendOnlyPdcpLogs, first.pdcp_log_id).diagnostic_json, sort_keys=True) == original


def test_stale_identity_map_is_refreshed_before_context_capture():
    target_id = create_target("alpha beta")
    with SessionLocal() as stale:
        old = stale.get(CloudTargetFiles, target_id)
        with SessionLocal() as writer:
            assert _submit(writer, target_id).status == "accepted"
        result = _submit(stale, target_id)
        assert result.failure_reason.value == "target_version_mismatch"
        assert old.version == 1
        _assert_context(result.current_context, "ALPHA beta", version=1)
        assert result.diagnostic["failure_context"] == result.current_context
        stale.rollback()


@pytest.mark.parametrize("commit", [False, True])
def test_caller_retains_transaction_and_provisional_rejection_ownership(commit):
    target_id = create_target("alpha beta")
    with SessionLocal() as owner:
        owner.begin()
        result = _submit(owner, target_id, edits=[{"match": "missing", "replace": "x"}])
        assert owner.in_transaction()
        _assert_context(result.current_context, "alpha beta")
        with SessionLocal() as observer:
            assert _counts(observer, target_id) == (0, 0)
        if commit:
            owner.commit()
        else:
            owner.rollback()
    with SessionLocal() as observer:
        assert _counts(observer, target_id) == (int(commit), 0)
        assert observer.get(CloudTargetFiles, target_id).current_content == "alpha beta"


@pytest.mark.parametrize("kind", ["invalid_target_id", "target_not_found", "unlocked_local_state"])
def test_unlocked_or_unknown_context_is_explicitly_unavailable(kind):
    target_id = create_target("alpha")
    with SessionLocal() as session:
        if kind == "unlocked_local_state":
            target = session.get(CloudTargetFiles, target_id)
            target.current_content = "uncommitted local text"
            target.current_hash = "local_hash"
            target.version = 999
        result = _submit(session, "invalid" if kind == "invalid_target_id" else
                         uuid.uuid4() if kind == "target_not_found" else target_id)
        assert result.pdcp_log_id is None
        assert result.current_context == result.diagnostic["failure_context"]
        assert result.current_context["available"] is False
        assert result.current_context["unavailable_reason"] == kind
        assert result.current_context["text"] is None
        assert result.current_context["observed_target_hash"] is None
        if kind == "unlocked_local_state":
            assert result.current_hash == "local_hash" and result.current_version == 999
        session.rollback()
    with SessionLocal() as session:
        assert _counts(session, target_id) == (0, 0)
        assert session.get(CloudTargetFiles, target_id).current_content == "alpha"


def test_corrupt_non_ascii_hash_retains_identity_but_still_obeys_json_byte_caps():
    content = "\U0001f642" * 400
    target_id = create_target(content)
    with SessionLocal.begin() as session:
        session.execute(update(CloudTargetFiles).where(CloudTargetFiles.target_file_id == target_id)
                        .values(current_hash="\U0001f642" * 64, version=2**63-1))
    with SessionLocal() as session:
        result = _submit(session, target_id)
    assert result.failure_reason.value == "target_version_mismatch"
    for context in (result.current_context, result.diagnostic["failure_context"]):
        assert context["observed_target_hash"] == "\U0001f642" * 64
        assert context["observed_target_version"] == 2**63-1
        assert context["text"] == content[:context["end"]]
        assert context["end"] < 256 and context["truncated"] is True
        assert len(json.dumps(context, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 4096
    assert len(json.dumps({"failure_context": result.diagnostic["failure_context"], "current_context": result.current_context},
                          ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 8192


def test_real_stdio_rejection_context_and_recovery_with_independent_sql():
    backend = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(backend), "PATCHDIFF_DATABASE_URL": settings.database_url}
    proc = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], cwd=backend, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sequence = 0
    def call(name, arguments):
        nonlocal sequence
        sequence += 1
        request = {"jsonrpc": "2.0", "id": sequence, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments}}
        proc.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        proc.stdin.flush()
        response = json.loads(proc.stdout.readline())
        assert response["id"] == sequence and response["result"]["isError"] is False
        return json.loads(response["result"]["content"][0]["text"])
    try:
        init = call("patchdiff_initialize_target", {"filename": "f01-stdio.txt", "content": "alpha \U0001f642",
                                                    "content_type": "text/plain"})
        target_id = init["target_file_id"]
        args = {"target_file_id": target_id, "intent": "F01 stdio", "expected_target_version": 0,
                "client_request_id": "f01-stdio", "edits": [{"match": "alpha", "replace": "ALPHA"},
                                                              {"match": "alpha", "replace": "x"}]}
        first = call("patchdiff_submit_edits", args)
        assert first["failure_reason"] == "sequential_match_invalid"
        _assert_context(first["diagnostic"]["failure_context"], "ALPHA \U0001f642", prior=1, target_content="alpha \U0001f642")
        _assert_context(first["current_context"], "alpha \U0001f642")
        accepted = call("patchdiff_submit_edits", {**args, "client_request_id": "f01-stdio-next",
                                                  "edits": args["edits"][:1]})
        assert accepted["status"] == "accepted" and "current_context" not in accepted
        recovered = call("patchdiff_submit_edits", args)
        assert recovered["deduplicated"] is True
        assert recovered["diagnostic"] == first["diagnostic"]
        _assert_context(recovered["current_context"], "ALPHA \U0001f642", version=1)
        with SessionLocal() as session:
            target_uuid = uuid.UUID(target_id)
            assert _counts(session, target_uuid) == (2, 1)
            log = session.get(AppendOnlyPdcpLogs, uuid.UUID(first["pdcp_log_id"]))
            assert log.diagnostic_json == first["diagnostic"]
            assert session.get(CloudTargetFiles, target_uuid).current_content == "ALPHA \U0001f642"
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
        if proc.poll() is None:
            proc.kill()
        assert proc.returncode == 0, proc.stderr.read().decode("utf-8")


@pytest.mark.parametrize("case,reason", [
    ("stale", "target_version_mismatch"), ("protocol", "block_malformed"),
    ("encoding", "target_encoding_invalid"), ("lineage", "context_invalid"),
    ("header", "target_hash_mismatch"), ("absent", "match_absent"),
    ("ambiguous", "match_ambiguous"), ("selector", "disambiguation_invalid"),
    ("sequential", "sequential_match_invalid"),
])
def test_legacy_uses_same_bounded_locked_rejection_path(case, reason):
    content = "alpha alpha" if case == "ambiguous" else "alpha beta"
    target_id = create_target(content)
    changes = [("absent", "x")] if case == "absent" else [("alpha", "ALPHA")]
    if case == "sequential":
        changes += [("alpha", "x")]
    pdcp = pdcp_for(target_id, *changes, header_hash="0" * 64 if case == "header" else None)
    if case == "protocol":
        pdcp = pdcp.replace("=======", "BAD")
    if case == "encoding":
        pdcp += "\ud800"
    if case == "selector":
        pdcp = pdcp.replace("# risk: low", "# risk: low\n# occurrence_index: 2")
    with SessionLocal() as session:
        result = submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp,
                             expected_target_version=1 if case == "stale" else 0,
                             parent_pdcp_log_id=uuid.uuid4() if case == "lineage" else None)
    assert result.failure_reason.value == reason
    _assert_context(result.diagnostic["failure_context"], "ALPHA beta" if case == "sequential" else content,
                    prior=int(case == "sequential"), target_content=content)
    _assert_context(result.current_context, content)
    assert result.diagnostic["format"] == "0.2.3" and result.diagnostic["requires_new_pdcp"] is True
    with SessionLocal() as session:
        assert _counts(session, target_id) == (1, 0)
        assert session.get(CloudTargetFiles, target_id).current_content == content
