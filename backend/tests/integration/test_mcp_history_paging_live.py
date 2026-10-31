"""Real PostgreSQL filters/cursors, display orders, and stdio history smoke."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.hashing import canonical_sha256
from app.mcp import tools
from app.services import pdcp_service
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs
from backend.tests.integration.helpers import create_target


def history_with_gaps():
    target_id = create_target("alpha")
    other_id = create_target("other")
    with SessionLocal() as session:
        for index in range(10):
            result = pdcp_service.submit_edits(
                session, target_file_id=target_id, expected_current_hash=canonical_sha256("alpha"),
                intent="Repeated guarded proposal",
                edits=[{"match": "alpha" if index % 2 == 0 else "absent", "replace": "alpha"}],
                client_request_id="first-key" if index == 0 else None)
            assert result.status == ("accepted" if index % 2 == 0 else "rejected")
            assert pdcp_service.submit_edits(
                session, target_file_id=other_id, expected_current_hash=canonical_sha256("other"),
                intent="Interleave another target", edits=[{"match": "other", "replace": "other"}],
            ).status == "accepted"
    with SessionLocal() as observer:
        attempts = observer.scalars(select(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id
        ).order_by(AppendOnlyPdcpLogs.log_sequence.desc())).all()
        ledger = observer.scalars(select(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id
        ).order_by(AppendOnlyManifestLedger.ledger_sequence.desc())).all()
    return target_id, attempts, ledger


def traverse(handler, target_id, first, sequence, limit, **filters):
    pages = []
    page = first
    previous_cursor = None
    for _ in range(20):
        values = [entry[sequence] for entry in page["entries"]]
        assert len(values) <= limit
        expected_order = sorted(values, reverse=sequence == "log_sequence")
        assert values == expected_order
        pages.extend(values)
        if not page["has_more"]:
            assert page["next_sequence"] is None
            break
        assert values and page["next_sequence"] == min(values)
        cursor = page["next_sequence"]
        assert previous_cursor is None or cursor < previous_cursor
        previous_cursor = cursor
        page = handler(target_file_id=str(target_id), limit=limit, before_sequence=cursor, **filters)
    else:
        pytest.fail("history traversal failed to terminate within its bounded page count")
    assert len(set(pages)) == len(pages)
    return pages


def test_both_histories_traverse_gaps_and_ignore_newer_insertions_between_calls():
    target_id, logs, ledger = history_with_gaps()
    initial_attempts = [log.log_sequence for log in logs]
    initial_ledger = [entry.ledger_sequence for entry in ledger]
    assert all(a - b > 1 for a, b in zip(initial_attempts, initial_attempts[1:]))
    assert all(a - b > 1 for a, b in zip(initial_ledger, initial_ledger[1:]))
    first_attempt = tools.patchdiff_get_pdcp_log(target_file_id=str(target_id), limit=3)
    first_ledger = tools.patchdiff_get_manifest_ledger(target_file_id=str(target_id), limit=2)
    with SessionLocal() as session:
        newer = pdcp_service.submit_edits(
            session, target_file_id=target_id, expected_current_hash=canonical_sha256("alpha"),
            intent="Newer row after first page", edits=[{"match": "alpha", "replace": "alpha"}])
        assert newer.status == "accepted"
    attempts_seen = traverse(tools.patchdiff_get_pdcp_log, target_id, first_attempt, "log_sequence", 3)
    ledger_seen = traverse(tools.patchdiff_get_manifest_ledger, target_id, first_ledger, "ledger_sequence", 2)
    assert attempts_seen == initial_attempts
    assert set(ledger_seen) == set(initial_ledger)
    assert len(ledger_seen) == len(initial_ledger)


def test_status_hash_key_and_cursor_filters_apply_before_page_lookahead():
    target_id, logs, _ = history_with_gaps()
    rejected = [log for log in logs if log.status == "rejected"]
    assert len(rejected) == 5
    shared_hash = rejected[0].pdcp_content_hash
    assert all(log.pdcp_content_hash == shared_hash for log in rejected)
    first = tools.patchdiff_get_pdcp_log(
        target_file_id=str(target_id), limit=3, status="rejected", content_hash=shared_hash,
        include_content=True)
    assert len(first["entries"]) == 3 and first["has_more"]
    assert all(entry["status"] == "rejected" and "pdcp_content" in entry for entry in first["entries"])
    seen = traverse(tools.patchdiff_get_pdcp_log, target_id, first, "log_sequence", 3,
                    status="rejected", content_hash=shared_hash, include_content=True)
    assert seen == [log.log_sequence for log in rejected]
    exclusive = tools.patchdiff_get_pdcp_log(
        target_file_id=str(target_id), limit=3, before_sequence=rejected[0].log_sequence,
        status="rejected", content_hash=shared_hash)
    assert all(entry["log_sequence"] < rejected[0].log_sequence for entry in exclusive["entries"])
    assert len(exclusive["entries"]) == 3 and exclusive["has_more"]
    key_page = tools.patchdiff_get_pdcp_log(
        target_file_id=str(target_id), client_request_id="first-key", limit=1)
    assert len(key_page["entries"]) == 1 and key_page["entries"][0]["client_request_id"] == "first-key"
    assert not key_page["has_more"] and key_page["next_sequence"] is None
    for filters in (
        {"status": "accepted", "content_hash": shared_hash},
        {"content_hash": "safe but not a hash"},
        {"client_request_id": "safe Unicode é😀"},
    ):
        empty = tools.patchdiff_get_pdcp_log(target_file_id=str(target_id), **filters)
        assert empty["entries"] == [] and not empty["has_more"] and empty["next_sequence"] is None


@pytest.mark.parametrize("handler", [tools.patchdiff_get_pdcp_log, tools.patchdiff_get_manifest_ledger])
def test_existing_empty_and_missing_targets_have_terminal_empty_pages(handler):
    target_id = create_target("empty history")
    empty = handler(target_file_id=str(target_id))
    assert empty["entries"] == [] and empty["has_more"] is False and empty["next_sequence"] is None
    missing = handler(target_file_id=str(uuid.uuid4()), limit=None)
    assert missing["status"] == "not_found"
    assert missing["entries"] == [] and missing["has_more"] is False and missing["next_sequence"] is None


def test_exact_stored_legacy_key_is_queryable_without_new_submission_key_validation(monkeypatch):
    target_id = create_target("alpha")
    with SessionLocal() as session:
        with monkeypatch.context() as legacy:
            legacy.setattr(pdcp_service, "validate_client_request_id", lambda value: value)
            original = pdcp_service.submit_edits(
                session, target_file_id=target_id, expected_target_version=0,
                intent="Persisted legacy key", edits=[{"match": "alpha", "replace": "beta"}],
                client_request_id="legacy\n")
        assert original.status == "accepted"
    page = tools.patchdiff_get_pdcp_log(target_file_id=str(target_id), client_request_id="legacy\n")
    assert len(page["entries"]) == 1 and page["entries"][0]["pdcp_log_id"] == str(original.pdcp_log_id)
    assert page["entries"][0]["client_request_id"] == "legacy\n"
    assert page["has_more"] is False and page["next_sequence"] is None


def test_real_stdio_history_pages_keep_both_orders_and_cursor_metadata():
    target_id, logs, ledger = history_with_gaps()
    backend = Path(__file__).resolve().parents[2]
    log_sequences = [log.log_sequence for log in logs]
    ledger_sequences = [entry.ledger_sequence for entry in ledger]
    calls = [
        ("patchdiff_get_pdcp_log", {"target_file_id": str(target_id), "limit": 3}),
        ("patchdiff_get_pdcp_log", {"target_file_id": str(target_id), "limit": 3,
                                   "before_sequence": log_sequences[2]}),
        ("patchdiff_get_manifest_ledger", {"target_file_id": str(target_id), "limit": 2}),
        ("patchdiff_get_manifest_ledger", {"target_file_id": str(target_id), "limit": 2,
                                          "before_sequence": ledger_sequences[1]}),
        ("patchdiff_find_occurrences", {"target_file_id": str(target_id), "text": "alpha", "context_chars": -1}),
        ("patchdiff_get_pdcp_log", {"target_file_id": str(target_id), "limit": False}),
    ]
    messages = [
        {"jsonrpc": "2.0", "id": index, "method": "tools/call",
         "params": {"name": name, "arguments": arguments}}
        for index, (name, arguments) in enumerate(calls, 1)
    ]
    process = subprocess.run([sys.executable, "-m", "app.mcp.external_adapter"],
        input="\n".join(json.dumps(message) for message in messages) + "\n",
        capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend),
             "PATCHDIFF_MCP_PROFILE": "full", "PATCHDIFF_DATABASE_URL": settings.database_url})
    assert process.returncode == 0, process.stderr
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(replies) == len(calls)
    assert all(reply["result"]["isError"] is False for reply in replies)
    attempt1, attempt2, ledger1, ledger2, invalid_context, invalid_limit = [
        json.loads(reply["result"]["content"][0]["text"]) for reply in replies]
    assert [entry["log_sequence"] for entry in attempt1["entries"]] == log_sequences[:3]
    assert [entry["log_sequence"] for entry in attempt2["entries"]] == log_sequences[3:6]
    assert attempt1["next_sequence"] == log_sequences[2] and attempt2["next_sequence"] == log_sequences[5]
    assert [entry["ledger_sequence"] for entry in ledger1["entries"]] == list(reversed(ledger_sequences[:2]))
    assert [entry["ledger_sequence"] for entry in ledger2["entries"]] == list(reversed(ledger_sequences[2:4]))
    assert ledger1["next_sequence"] == ledger_sequences[1] and ledger2["next_sequence"] == ledger_sequences[3]
    assert all(page["has_more"] for page in (attempt1, attempt2, ledger1, ledger2))
    assert invalid_context["status"] == invalid_limit["status"] == "invalid_argument"
    assert invalid_limit["entries"] == [] and not invalid_limit["has_more"] and invalid_limit["next_sequence"] is None
