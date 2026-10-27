"""Live PostgreSQL and actual stdio regression for singleton constraints."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.failures import FailureReason
from app.core.versions import (
    LEGACY_RUNTIME_VERSION, PREVIOUS_RUNTIME_VERSION, PRE_SELECTOR_RUNTIME_VERSION,
    RUNTIME_VERSION,
)
from app.services import pdcp_service
from app.services.replay_service import replay_target
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles
from backend.tests.integration.helpers import create_target, pdcp_for


def submit(session, target_id, format_, match="hello", replace="goodbye", version=0, **selectors):
    if format_ == "typed":
        return pdcp_service.submit_edits(
            session, target_file_id=target_id, expected_target_version=version,
            intent="Check singleton selectors", edits=[{
                "match": match, "replace": replace, **selectors,
            }],
        )
    content = pdcp_for(target_id, (match, replace))
    content = content.replace("# risk: low", "# risk: low" + "".join(
        f"\n# {key}: {value}" for key, value in selectors.items()
    ))
    return pdcp_service.submit_pdcp(
        session, target_file_id=target_id, pdcp_content=content,
        expected_target_version=version,
    )


@pytest.mark.parametrize("format_", ["typed", "legacy"])
@pytest.mark.parametrize("selectors", [
    {"occurrence_index": 2}, {"anchor_before": "missing"}, {"anchor_after": "missing"},
    {"occurrence_index": 1, "anchor_before": "missing", "anchor_after": "missing"},
])
def test_singleton_constraint_rejection_is_durable_without_materialization(format_, selectors):
    target_id = create_target("hello")
    with SessionLocal() as session:
        result = submit(session, target_id, format_, **selectors)
        assert result.status == "rejected"
        assert result.failure_reason is FailureReason.DISAMBIGUATION_INVALID
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        assert target.current_content == "hello" and target.version == 0
        assert target.current_hash == result.before_hash
        logs = session.scalars(select(AppendOnlyPdcpLogs).where(
            AppendOnlyPdcpLogs.target_file_id == target_id
        )).all()
        assert len(logs) == 1 and logs[0].pdcp_log_id == result.pdcp_log_id
        assert logs[0].runtime_version == RUNTIME_VERSION
        assert logs[0].status == "rejected"
        assert logs[0].failure_reason == FailureReason.DISAMBIGUATION_INVALID.value
        assert session.scalar(select(func.count()).select_from(AppendOnlyManifestLedger).where(
            AppendOnlyManifestLedger.target_file_id == target_id
        )) == 0


@pytest.mark.parametrize("format_", ["typed", "legacy"])
@pytest.mark.parametrize("historical_runtime", [
    LEGACY_RUNTIME_VERSION, PREVIOUS_RUNTIME_VERSION, PRE_SELECTOR_RUNTIME_VERSION,
])
def test_ignored_selector_history_replays_under_its_recorded_profile(monkeypatch, format_, historical_runtime):
    target_id = create_target("hello")
    with SessionLocal() as session:
        with monkeypatch.context() as old:
            old.setattr(pdcp_service, "RUNTIME_VERSION", historical_runtime)
            original = submit(session, target_id, format_, occurrence_index=2)
        assert original.status == "accepted"
        log = session.get(AppendOnlyPdcpLogs, original.pdcp_log_id)
        recorded = (log.pdcp_content, log.pdcp_content_hash, log.request_fingerprint)
        assert log.runtime_version == historical_runtime
        historical = replay_target(session, target_file_id=target_id)
        assert historical.status == "success" and historical.materialized_state_matches
        assert historical.reconstructed_content == "goodbye"
        rejected = submit(session, target_id, format_, match="goodbye", version=1, occurrence_index=2)
        assert rejected.failure_reason is FailureReason.DISAMBIGUATION_INVALID
        accepted = submit(session, target_id, format_, match="goodbye", replace="world", version=1)
        assert accepted.status == "accepted"
        session.commit()
        mixed = replay_target(session, target_file_id=target_id)
        assert mixed.status == "success" and mixed.materialized_state_matches
        assert mixed.reconstructed_content == "world" and mixed.reconstructed_version == 2
        assert (log.pdcp_content, log.pdcp_content_hash, log.request_fingerprint) == recorded
        assert session.get(AppendOnlyPdcpLogs, accepted.pdcp_log_id).runtime_version == RUNTIME_VERSION


def test_real_stdio_rejects_singleton_selector_and_exposes_persisted_attempt():
    target_id = create_target("hello")
    backend = Path(__file__).resolve().parents[2]
    calls = [
        ("patchdiff_submit_edits", {
            "target_file_id": str(target_id), "expected_target_version": 0,
            "intent": "Do not ignore my selector",
            "edits": [{"match": "hello", "replace": "goodbye", "occurrence_index": 2}],
        }),
        ("patchdiff_get_target", {"target_file_id": str(target_id)}),
        ("patchdiff_get_pdcp_log", {"target_file_id": str(target_id)}),
        ("patchdiff_replay", {"target_file_id": str(target_id)}),
    ]
    messages = [
        {"jsonrpc": "2.0", "id": i, "method": "tools/call",
         "params": {"name": name, "arguments": arguments}}
        for i, (name, arguments) in enumerate(calls, 1)
    ]
    process = subprocess.run(
        [sys.executable, "-m", "app.mcp.external_adapter"],
        input="\n".join(json.dumps(message) for message in messages) + "\n",
        capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend),
             "PATCHDIFF_MCP_PROFILE": "full", "PATCHDIFF_DATABASE_URL": settings.database_url},
    )
    assert process.returncode == 0, process.stderr
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == list(range(1, 5))
    assert all(reply["result"]["isError"] is False for reply in replies)
    rejected, target, history, replay = [
        json.loads(reply["result"]["content"][0]["text"]) for reply in replies
    ]
    assert rejected["status"] == "rejected"
    assert rejected["failure_reason"] == "disambiguation_invalid"
    assert target["current_content"] == "hello" and target["version"] == 0
    assert len(history["entries"]) == 1
    assert history["entries"][0]["pdcp_log_id"] == rejected["pdcp_log_id"]
    assert replay["status"] == "success" and replay["materialized_state_matches"]
