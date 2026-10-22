"""Bounded preview evidence retains live zero-audit/caller ownership guarantees."""
import pytest
from sqlalchemy import event

from app.core.hashing import canonical_sha256
from app.services.pdcp_service import preview, submit_edits
from app.services.preview_evidence import MAX_PREVIEW_BYTES, json_bytes
from app.storage.db import SessionLocal
from app.storage.models import Projects
from backend.tests.integration.helpers import create_target, pdcp_for
from backend.tests.integration.test_pass_b_submission_preview import table_snapshot


def test_many_preview_facts_are_bounded_without_changing_full_submit_facts_or_pending_owner():
    target_id = create_target("old")
    arguments = {"target_file_id": target_id, "intent": "bounded preview", "expected_target_version": 0,
                 "edits": [{"match": "old", "replace": "old"} for _ in range(40)]}
    before = table_snapshot()
    with SessionLocal() as session:
        session.begin()
        transaction = session.get_transaction()
        pending = Projects(name="preview budget must not flush this")
        session.add(pending)
        statements = []
        connection = session.connection()
        def collect(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(connection, "before_cursor_execute", collect)
        try:
            observed = preview(session, format="patchdiff-tx/1", **arguments)
        finally:
            event.remove(connection, "before_cursor_execute", collect)
        assert observed["status"] == "accepted" and observed["total_change_count"] == 40
        assert observed["returned_fact_count"] == 32 and observed["change_facts_truncated"]
        assert observed["change_facts_omission_reason"] == "fact_count_limit"
        assert observed["after_hash"] == canonical_sha256("old") and json_bytes(observed) <= MAX_PREVIEW_BYTES
        assert session.get_transaction() is transaction and pending in session.new and pending.project_id is None
        assert len(statements) == 1 and "FOR UPDATE" not in statements[0].upper()
        assert table_snapshot() == before
    with SessionLocal() as session:
        accepted = submit_edits(session, **arguments)
    assert accepted.status == "accepted" and len(accepted.change_facts) == 40
    assert observed["change_facts"] == list(accepted.change_facts[:32])


@pytest.mark.parametrize("absent", [False, True])
def test_oversized_legacy_change_identity_is_omitted_whole_without_changing_verdict_or_database(absent):
    target_id = create_target("old")
    giant_id = "identity_" + "\U0001f31f" * 2000
    content = pdcp_for(target_id, ("absent" if absent else "old", "new"))
    content = content.replace("# change_id: chg_001", "# change_id: " + giant_id)
    before = table_snapshot()
    with SessionLocal() as session:
        result = preview(session, target_file_id=target_id, format="0.2.3", pdcp_content=content, expected_target_version=0)
    assert json_bytes(result) <= MAX_PREVIEW_BYTES and table_snapshot() == before
    if absent:
        assert result["status"] == "rejected" and result["failure_reason"] == "match_absent"
        assert result["failed_change_id"] is None
        assert result["evidence_omissions"]["failed_change_id"] == "code_points_limit"
        assert "change_facts" not in result
    else:
        assert result["status"] == "accepted" and result["after_hash"] == canonical_sha256("new")
        assert result["total_change_count"] == 1 and result["returned_fact_count"] == 0
        assert result["change_facts"] == [] and result["change_facts_omission_reason"] == "fact_byte_limit"


def test_oversized_raw_guard_diagnostic_keeps_bounded_context_and_observed_identity_without_audit():
    target_id = create_target("old")
    before = table_snapshot()
    with SessionLocal() as session:
        result = preview(session, target_file_id=target_id, format="patchdiff-tx/1", intent="preview",
                         edits=[{"match": "old", "replace": "new"}], expected_target_version=["x" * 40_000])
    assert result["status"] == "rejected" and result["failure_reason"] == "context_invalid"
    assert result["validation_stage"] == "protocol_validation" and result["current_version"] == 0
    assert result["current_hash"] == canonical_sha256("old") and result["target_file_id"] == str(target_id)
    assert result["diagnostic"]["failure_context"]["text"] == "old"
    assert result["evidence_omissions"]["diagnostic"] == "diagnostic_byte_limit"
    assert json_bytes(result) <= MAX_PREVIEW_BYTES and table_snapshot() == before


@pytest.mark.parametrize("target_id,reason", [("invalid" * 10_000, "code_points_limit"),
    ("\U0001f31f" * 700, "field_byte_limit")], ids=["huge-target-echo", "ascii-escaped-byte-limit"])
def test_invalid_target_echo_is_omitted_with_explicit_reason_without_starting_transaction(target_id, reason):
    before = table_snapshot()
    with SessionLocal() as session:
        result = preview(session, target_file_id=target_id, format="patchdiff-tx/3", intent="preview",
                         replacement="new", expected_target_version=0)
        assert not session.in_transaction()
    assert result["status"] == "rejected" and result["current_context"]["unavailable_reason"] == "invalid_target_id"
    assert result["target_file_id"] is None and result["evidence_omissions"]["target_file_id"] == reason
    assert json_bytes(result) <= MAX_PREVIEW_BYTES and table_snapshot() == before
