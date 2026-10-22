"""Live replacement, shared preview parity, nonmutation and owner boundaries."""
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, func, select, text

from app.core.hashing import canonical_sha256
from app.core.versions import REPLACEMENT_RUNTIME_VERSION
from app.pdcp import replacement as replacement_runtime
from app.services import pdcp_service
from app.services.pdcp_service import preview, submit_edits, submit_operations, submit_pdcp, submit_replacement
from app.services.replay_service import replay_target
from app.services.save_service import save_target
from app.storage.db import SessionLocal
from app.storage.models import Base, AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles, Projects
from backend.tests.integration.helpers import create_target, pdcp_for


def table_snapshot():
    with SessionLocal() as session:
        return {table.name: sorted(repr(tuple(row)) for row in session.execute(select(table)))
                for table in Base.metadata.sorted_tables}


def counts(target_id):
    with SessionLocal() as session:
        return tuple(session.scalar(select(func.count()).select_from(model).where(model.target_file_id == target_id))
                     for model in (AppendOnlyPdcpLogs, AppendOnlyManifestLedger))


def replacement_args(target_id, value="new", **extra):
    return {"target_file_id": target_id, "intent": "Replace the complete target", "replacement": value,
            "expected_target_version": 0, **extra}


@pytest.mark.parametrize("before,after,expected", [("old", "new", "new"), ("", "", ""), ("old", "", ""),
    ("", "\U0001f642\r\nx", "\U0001f642\nx")])
def test_replacement_uses_shared_log_ledger_save_replay_and_key_recovery(before, after, expected):
    target_id = create_target(before)
    arguments = replacement_args(target_id, after, client_request_id="replacement-original")
    with SessionLocal() as session:
        accepted = submit_replacement(session, **arguments, include_correlation_id=True)
    assert accepted.status == "accepted" and uuid.UUID(accepted.correlation_id).version == 4
    with SessionLocal() as session:
        log = session.get(AppendOnlyPdcpLogs, accepted.pdcp_log_id)
        assert log.protocol_version == "patchdiff-tx/3" and log.runtime_version == REPLACEMENT_RUNTIME_VERSION
        assert json.loads(log.pdcp_content)["operations"] == [{"op": "replace_all", "replace": after}]
        ledger = session.scalar(select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.pdcp_log_id == log.pdcp_log_id))
        assert ledger.origin == "typed" and ledger.input_state is None
        assert ledger.derived_json["operation"] == "replace_all"
        assert ledger.derived_json["span_end"] == len(before)
        assert session.get(CloudTargetFiles, target_id).current_content == expected
    with SessionLocal() as session:
        recovered = submit_replacement(session, **arguments, include_correlation_id=True)
    assert recovered.deduplicated and recovered.pdcp_log_id == accepted.pdcp_log_id
    assert recovered.correlation_id != accepted.correlation_id and recovered.change_facts == accepted.change_facts
    with SessionLocal() as session:
        save_target(session, target_file_id=target_id)
    with SessionLocal() as session:
        replay = replay_target(session, target_file_id=target_id)
    assert replay.status == "success" and replay.materialized_state_matches and replay.reconstructed_content == expected
    assert counts(target_id) == (1, 1)


@pytest.mark.parametrize("value,expected", [("a" * 1_000_000, "accepted"), ("a" * 1_000_001, "invalid_argument"),
    ("\U0001f642" * 262_144, "accepted"), ("\U0001f642" * 262_144 + "a", "invalid_argument"),
    ("\r\n" * 500_001, "invalid_argument")],
    ids=["chars-equal", "chars-over", "bytes-equal", "bytes-over", "raw-crlf-over"])
def test_real_postgres_inclusive_raw_chars_and_bytes_admission(value, expected):
    target_id = create_target("old")
    before = table_snapshot()
    with SessionLocal() as session:
        result = submit_replacement(session, **replacement_args(target_id, value))
    assert result.status == expected
    if expected == "invalid_argument":
        assert result.pdcp_log_id is None and result.diagnostic["code"] == "replacement_too_large"
        assert table_snapshot() == before and counts(target_id) == (0, 0)
    else:
        assert counts(target_id) == (1, 1)


def test_existing_key_outcome_and_conflict_precede_stricter_fresh_limits_and_replay_bypasses_them(monkeypatch):
    target_id = create_target("old")
    arguments = replacement_args(target_id, "a long accepted value", client_request_id="size-history")
    with SessionLocal() as session:
        original = submit_replacement(session, **arguments)
    monkeypatch.setattr(replacement_runtime, "MAX_REPLACEMENT_CHARS", 2)
    monkeypatch.setattr(replacement_runtime, "MAX_REPLACEMENT_BYTES", 2)
    with SessionLocal() as session:
        recovered = submit_replacement(session, **arguments)
    assert recovered.deduplicated and recovered.pdcp_log_id == original.pdcp_log_id
    with SessionLocal() as session:
        conflict = submit_replacement(session, **{**arguments, "replacement": "different oversized value"})
    assert conflict.status == "rejected" and conflict.pdcp_log_id is not None
    assert conflict.failure_detail.startswith("client_request_id was already used")
    with SessionLocal() as session:
        fresh = submit_replacement(session, **{**arguments, "client_request_id": "fresh"})
    assert fresh.status == "invalid_argument" and counts(target_id) == (2, 1)
    with SessionLocal() as session:
        replay = replay_target(session, target_file_id=target_id)
    assert replay.status == "success" and replay.materialized_state_matches
    # Old tx/1 admission remains unchanged even under these stricter replacement limits.
    with SessionLocal() as session:
        old_format = submit_edits(session, target_file_id=target_id, intent="old format", expected_target_version=1,
                                  edits=[{"match": "a long accepted value", "replace": "still larger than two"}])
    assert old_format.status == "accepted"


@pytest.mark.parametrize("bad", ["\ud800", "\x00", "\udfff"])
def test_invalid_unicode_beats_oversize_and_stale_guard_is_safely_audited_and_recoverable(bad):
    target_id = create_target("old")
    arguments = replacement_args(target_id, "a" * 1_000_001 + bad,
                                 expected_target_version=999, client_request_id="invalid-large")
    with SessionLocal() as session:
        result = submit_replacement(session, **arguments)
    assert result.status == "rejected" and result.failure_reason.value == "target_encoding_invalid"
    with SessionLocal() as session:
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log.diagnostic_json["evidence_format"] == "patchdiff-invalid-input/1"
        assert json.loads(log.pdcp_content)["inputs"]["record"]["operations"][0]["replace"] == arguments["replacement"]
    with SessionLocal() as session:
        retry = submit_replacement(session, **arguments)
    assert retry.deduplicated and retry.diagnostic == result.diagnostic and counts(target_id) == (1, 0)


@pytest.mark.parametrize("commit", [False, True])
def test_replacement_retains_caller_lock_and_transaction_until_owner_ends(commit):
    target_id = create_target("old")
    with SessionLocal() as owner:
        owner.begin()
        transaction = owner.get_transaction()
        result = submit_replacement(owner, **replacement_args(target_id))
        assert result.status == "accepted" and owner.get_transaction() is transaction
        assert counts(target_id) == (0, 0)
        (owner.commit if commit else owner.rollback)()
    assert counts(target_id) == ((1, 1) if commit else (0, 0))


def test_replacement_writer_waits_for_real_lock_then_rechecks_version():
    target_id = create_target("old")
    pid = []
    with SessionLocal() as owner, ThreadPoolExecutor(max_workers=1) as pool:
        owner.begin()
        first = submit_replacement(owner, **replacement_args(target_id, "first"))
        owner_pid = owner.scalar(text("SELECT pg_backend_pid()"))
        def second():
            with SessionLocal() as session:
                pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                result = submit_replacement(session, **replacement_args(target_id, "second"))
                session.commit()
                return result
        future = pool.submit(second)
        blocked = False
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if pid:
                    with SessionLocal() as monitor:
                        blocked = owner_pid in monitor.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid[0]})
                    if blocked:
                        break
                time.sleep(.02)
            assert blocked and not future.done() and first.status == "accepted"
        finally:
            owner.commit()
        rejected = future.result(timeout=10)
    assert rejected.failure_reason.value == "target_version_mismatch" and counts(target_id) == (2, 1)


FORMATS = ["0.2.3", "patchdiff-tx/1", "patchdiff-tx/2", "patchdiff-tx/3"]


def proposal_for(format_, target_id, case):
    match, after = ("absent" if case == "absent" else "old"), ("\ud800" if case == "encoding" else "new")
    arguments = {"expected_target_version": 0}
    if format_ == "0.2.3":
        arguments["pdcp_content"] = pdcp_for(target_id, (match, after))
        submit = submit_pdcp
    elif format_ == "patchdiff-tx/1":
        arguments.update(intent="preview parity", edits=[{"match": match, "replace": after}])
        submit = submit_edits
    elif format_ == "patchdiff-tx/2":
        arguments.update(intent="preview parity", operations=[{"op": "match", "match": match, "replace": after}])
        submit = submit_operations
    else:
        arguments.update(intent="preview parity", replacement=after)
        submit = submit_replacement
    if case == "missing_guard":
        arguments.pop("expected_target_version")
    elif case in {"stale", "encoding"}:
        arguments["expected_target_version"] = 999
    elif case == "invalid_guard":
        arguments["expected_target_version"] = True
    elif case == "hash_guard":
        arguments["expected_current_hash"] = "0" * 64
    elif case == "malformed":
        arguments[next(field for field in ("pdcp_content", "edits", "operations", "replacement") if field in arguments)] = 42
        if format_ == "0.2.3":
            arguments["pdcp_content"] = "malformed PDCP"
    return submit, arguments


@pytest.mark.parametrize("format_", FORMATS)
@pytest.mark.parametrize("case", ["accepted", "absent", "missing_guard", "stale", "invalid_guard", "hash_guard", "malformed", "encoding"])
def test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change(format_, case):
    target_id = create_target("old")
    submit, arguments = proposal_for(format_, target_id, case)
    before = table_snapshot()
    with SessionLocal() as session:
        observed = preview(session, target_file_id=target_id, format=format_, **arguments)
    assert table_snapshot() == before and observed["preview"] and observed["advisory"]
    assert "pdcp_log_id" not in observed and "near_misses" not in observed
    with SessionLocal() as session:
        submitted = submit(session, target_file_id=target_id, **arguments)
    assert observed["status"] == submitted.status
    assert observed["validation_stage"] == submitted.validation_stage.value
    assert observed["current_hash"] == canonical_sha256("old") and observed["current_version"] == 0
    assert observed["after_hash"] == submitted.after_hash
    if submitted.status == "accepted":
        assert observed["change_facts"] == list(submitted.change_facts)
        assert "target_content" not in observed
    else:
        assert "change_facts" not in observed
        assert observed["failure_reason"] == submitted.failure_reason.value
        assert observed["failed_change_id"] == submitted.failed_change_id
        assert observed["diagnostic"]["failure_context"] == submitted.diagnostic["failure_context"]


def test_preview_ordinary_snapshot_ignores_stale_cache_and_keeps_pending_unrelated_state_without_writes_or_locks():
    target_id = create_target("old")
    with SessionLocal() as session:
        cached = session.get(CloudTargetFiles, target_id)
        transaction = session.get_transaction()
        with SessionLocal() as writer:
            submit_replacement(writer, **replacement_args(target_id, "new"))
        pending = Projects(name="must remain pending")
        session.add(pending)
        before = table_snapshot()
        statements = []
        connection = session.connection()
        def collect(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(connection, "before_cursor_execute", collect)
        try:
            result = preview(session, target_file_id=target_id, format="patchdiff-tx/3", intent="preview",
                             replacement="next", expected_target_version=1)
        finally:
            event.remove(connection, "before_cursor_execute", collect)
        assert result["status"] == "accepted" and result["current_version"] == 1
        assert cached.version == 0 and cached.current_content == "old"
        assert pending in session.new and pending.project_id is None and session.get_transaction() is transaction
        assert len(statements) == 1 and statements[0].lstrip().upper().startswith("SELECT")
        assert "FOR UPDATE" not in statements[0].upper() and table_snapshot() == before


def test_preview_rejects_dirty_local_target_without_refresh_flush_rollback_or_audit():
    target_id = create_target("old")
    before = table_snapshot()
    with SessionLocal() as session:
        local = session.get(CloudTargetFiles, target_id)
        local.current_content = "pending direct edit"
        transaction = session.get_transaction()
        result = preview(session, target_file_id=target_id, format="patchdiff-tx/3", intent="preview",
                         replacement="new", expected_target_version=0)
        assert result["status"] == "rejected" and result["current_context"]["unavailable_reason"] == "unlocked_local_state"
        assert local.current_content == "pending direct edit" and local in session.dirty
        assert session.get_transaction() is transaction and table_snapshot() == before


def test_preview_sequential_rejection_exposes_intermediate_context_without_partial_facts():
    target_id = create_target("old")
    with SessionLocal() as session:
        result = preview(session, target_file_id=target_id, format="patchdiff-tx/2", intent="preview",
            expected_target_version=0, operations=[{"op": "span", "start": 0, "end": 3, "expected_text": "old", "replace": "new"},
                {"op": "span", "start": 0, "end": 3, "expected_text": "old", "replace": "X"}])
    context = result["diagnostic"]["failure_context"]
    assert result["failure_reason"] == "span_expected_text_mismatch" and "change_facts" not in result
    assert context["text"] == "new" and context["prior_changes"] == 1 and context["buffer_stage"] == "intermediate_buffer"
    assert counts(target_id) == (0, 0)


def test_preview_version_guard_detects_later_hash_aba_and_does_not_reserve_request_key():
    target_id = create_target("old")
    with SessionLocal() as session:
        result = preview(session, target_file_id=target_id, format="patchdiff-tx/3", intent="preview",
                         replacement="proposed", expected_target_version=0, expected_current_hash=canonical_sha256("old"))
    assert result["status"] == "accepted" and counts(target_id) == (0, 0)
    for version, value in enumerate(("temporary", "old")):
        with SessionLocal() as session:
            assert submit_replacement(session, **replacement_args(target_id, value, expected_target_version=version)).status == "accepted"
    with SessionLocal() as session:
        stale = submit_replacement(session, **replacement_args(target_id, "proposed", client_request_id="after-preview",
                                                               expected_current_hash=canonical_sha256("old")))
    assert stale.failure_reason.value == "target_version_mismatch" and counts(target_id) == (3, 2)


@pytest.mark.parametrize("target_id,reason", [("malformed", "invalid_target_id"), (str(uuid.uuid4()), "target_not_found")])
def test_preview_unavailable_targets_are_unlinked(target_id, reason):
    before = table_snapshot()
    with SessionLocal() as session:
        result = preview(session, target_file_id=target_id, format="patchdiff-tx/3", intent="preview", replacement="x",
                         expected_target_version=0)
    assert result["status"] == "rejected" and result["current_context"]["unavailable_reason"] == reason
    assert table_snapshot() == before


@pytest.mark.parametrize("extra", [{"client_request_id": "reserved"}, {"parent_pdcp_log_id": None}, {"edits": None},
    {"include_correlation_id": False}, {"audit": False}])
def test_preview_rejects_irrelevant_or_identity_parameters_even_null(extra):
    with SessionLocal() as session:
        result = preview(session, target_file_id=uuid.uuid4(), format="patchdiff-tx/3", intent="preview", replacement="new", **extra)
        assert not session.in_transaction()
    assert result["status"] == "invalid_argument" and result["code"] == "irrelevant_proposal_fields"


def test_oversized_replacement_does_not_flush_pending_unrelated_state_or_take_request_key():
    target_id = create_target("old")
    before = table_snapshot()
    with SessionLocal() as session:
        session.begin()
        transaction = session.get_transaction()
        pending = Projects(name="no premature flush")
        session.add(pending)
        result = submit_replacement(session, **replacement_args(target_id, "a" * 1_000_001, client_request_id="not-reserved"))
        assert result.status == "invalid_argument" and pending in session.new and pending.project_id is None
        assert session.get_transaction() is transaction and table_snapshot() == before
