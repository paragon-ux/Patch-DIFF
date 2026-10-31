"""Live raw-byte MCP transport coverage independent of the parent's text encoding."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles

BACKEND = Path(__file__).resolve().parents[2]


def _request(request_id: int, name: str, arguments: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def _exchange(messages: list[dict], env: dict[str, str], escaped: bool) -> list[dict]:
    wire = b"".join((json.dumps(message, ensure_ascii=escaped) + "\n").encode("utf-8") for message in messages)
    proc = subprocess.run(
        [sys.executable, "-m", "app.mcp.external_adapter"],
        input=wire, capture_output=True, cwd=BACKEND, env=env, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    responses = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [response["id"] for response in responses] == [message["id"] for message in messages]
    return [response["result"] for response in responses]


def _payload(result: dict) -> dict:
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


@pytest.mark.parametrize("ambient_encoding", [None, "cp1252:surrogateescape"])
@pytest.mark.parametrize("escaped", [False, True], ids=["literal-utf8", "ascii-escapes"])
def test_live_stdio_unicode_and_audit_survive_ambient_codepages(ambient_encoding: str | None, escaped: bool) -> None:
    env = os.environ.copy()
    env["PATCHDIFF_MCP_PROFILE"] = "full"
    env.update(PYTHONPATH=str(BACKEND), PATCHDIFF_DATABASE_URL=settings.database_url)
    env.pop("PYTHONIOENCODING", None)
    env.pop("PYTHONUTF8", None)
    if ambient_encoding:
        env["PYTHONIOENCODING"] = ambient_encoding
    original = "Hello 🌟 café 中文\r\n"
    canonical = "Hello 🌟 café 中文\n"
    replacement = "Done 🎉 résumé 東京"
    upload = _payload(_exchange([_request(1, "patchdiff_handle_upload", {
        "filename": "unicode-roundtrip.txt", "content_type": "text/plain", "content": original,
    })], env, escaped)[0])
    target_id = upload["target_file_id"]
    proposal = {
        "target_file_id": target_id, "expected_target_version": 0, "intent": "Update multilingual greeting.",
        "edits": [{"match": canonical.rstrip("\n"), "replace": replacement}],
        "client_request_id": str(uuid.uuid4()),
    }
    results = _exchange([
        _request(1, "patchdiff_read_target", {"target_file_id": target_id}),
        _request(2, "patchdiff_find_occurrences", {"target_file_id": target_id, "text": "🌟 café 中文", "context_chars": 0}),
        _request(3, "patchdiff_submit_edits", proposal),
        _request(4, "patchdiff_submit_edits", proposal),
        _request(5, "patchdiff_read_target", {"target_file_id": target_id, "version": 1}),
        _request(6, "patchdiff_get_target", {"target_file_id": target_id}),
        _request(7, "patchdiff_export_target", {"target_file_id": target_id}),
        _request(8, "patchdiff_save", {"target_file_id": target_id}),
        _request(9, "patchdiff_replay", {"target_file_id": target_id}),
    ], env, escaped)
    assert _payload(results[0])["text"] == canonical
    found = _payload(results[1])
    assert found["occurrence_count"] == 1 and found["version"] == 0
    assert found["current_hash"] == upload["current_hash"]
    accepted, recovered = _payload(results[2]), _payload(results[3])
    assert accepted["status"] == "accepted" and accepted["version"] == 1
    assert recovered["deduplicated"] is True and recovered["pdcp_log_id"] == accepted["pdcp_log_id"]
    unknown = json.loads(results[4]["content"][0]["text"])
    assert results[4]["isError"] is True and unknown["status"] == "invalid_argument"
    assert unknown["code"] == "unknown_argument" and unknown["unknown_arguments"] == ["version"]
    assert _payload(results[5])["current_content"] == replacement + "\n"
    assert _payload(results[6])["content"] == replacement + "\n"
    assert _payload(results[7])["status"] == "saved"
    replay = _payload(results[8])
    assert replay["status"] == "success" and replay["materialized_state_matches"] is True
    assert all(replay["materialized_state_checks"].values())

    # Valid JSON escapes still reach the audited domain boundary after wire decoding.
    invalid = _exchange([
        _request(index, "patchdiff_submit_edits", {
            "target_file_id": target_id, "expected_target_version": 1, "intent": "Reject invalid replacement.",
            "edits": [{"match": replacement, "replace": text}], "client_request_id": str(uuid.uuid4()),
        })
        for index, text in enumerate(("\ud800", "\0"), start=1)
    ], env, True)
    for result in invalid:
        rejection = _payload(result)
        assert rejection["status"] == "rejected"
        assert rejection["failure_reason"] == "target_encoding_invalid"
        assert rejection["diagnostic"]["validation_stage"] == "protocol_validation"

    malformed = (json.dumps(_request(1, "patchdiff_submit_edits", {
        "target_file_id": target_id, "expected_target_version": 1, "intent": "Must not reach dispatch.",
        "edits": [{"match": replacement, "replace": "INVALID_WIRE"}],
    }), ensure_ascii=True) + "\n").encode("ascii").replace(b"INVALID_WIRE", b"\xff")
    proc = subprocess.run(
        [sys.executable, "-m", "app.mcp.external_adapter"],
        input=malformed, capture_output=True, cwd=BACKEND, env=env, timeout=30,
    )
    assert proc.returncode != 0 and proc.stdout == b""
    assert b"UnicodeDecodeError" in proc.stderr

    with SessionLocal() as session:
        target_uuid = uuid.UUID(target_id)
        target = session.get(CloudTargetFiles, target_uuid)
        assert target is not None and target.current_content == replacement + "\n" and target.version == 1
        logs = session.scalars(select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_uuid)).all()
        ledger = session.scalars(select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == target_uuid)).all()
        assert len(logs) == 3 and len(ledger) == 1
        assert sum(log.status == "accepted" for log in logs) == 1
        rejections = [log for log in logs if log.status == "rejected"]
        assert len(rejections) == 2
        assert all(json.loads(log.pdcp_content)["evidence_format"] == "patchdiff-invalid-input/1" for log in rejections)
