"""Real stdio subprocess checks for tool shapes changed by the PR #11 friction follow-up."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator

from app.core.config import settings
from app.core.versions import SPAN_CONTEXT_RUNTIME_VERSION
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyPdcpLogs, CloudTargetFiles


def test_real_stdio_friction_followup_shapes():
    backend = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(backend), "PATCHDIFF_DATABASE_URL": settings.database_url}
    env.pop("PYTHONIOENCODING", None)
    process = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=backend, env=env)
    sequence = 0
    raw_lines = []

    def rpc(method, params):
        nonlocal sequence
        sequence += 1
        message = {"jsonrpc": "2.0", "id": sequence, "method": method, "params": params}
        process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        process.stdin.flush()
        line = process.stdout.readline()
        raw_lines.append(line)
        response = json.loads(line.decode("utf-8"))
        assert response["id"] == sequence
        return response["result"]

    def call(name, arguments, *, error=False, schema_valid=True):
        response = rpc("tools/call", {"name": name, "arguments": arguments})
        assert response["isError"] is error, response
        payload = json.loads(response["content"][0]["text"])
        if schema_valid and not error:
            assert Draft202012Validator(schemas[name]).is_valid(arguments), (name, arguments)
        return payload

    try:
        tools = rpc("tools/list", {})["tools"]
        schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
        assert all(prop.get("description") for schema in schemas.values() for prop in schema["properties"].values())
        assert schemas["patchdiff_export_target"]["properties"]["format"]["enum"] == [
            "original_text", "canonical_lf", "crlf", "original_eol"]
        assert schemas["patchdiff_save"]["properties"]["expected_target_version"]["minimum"] == 0
        assert schemas["patchdiff_read_lines"]["properties"]["include_line_starts"]["type"] == "boolean"

        # FR-3: CRLF upload facts and an honoured export format, with literal UTF-8 on the wire.
        content = "# Intro \U0001f30d\r\nalpha\r\nbeta\r\n"
        upload = call("patchdiff_initialize_target", {"filename": "i18n.md", "content": content,
                                                      "content_type": "text/markdown"})
        assert upload["status"] == "ok" and upload["source_line_endings"]["style"] == "crlf"
        target_id = upload["target_file_id"]
        read = call("patchdiff_read_target", {"target_file_id": target_id})
        assert read["text"] == "# Intro \U0001f30d\nalpha\nbeta\n"
        # The JSON-RPC line is pure ASCII; the tool text inside it carries literal characters.
        tool_text = json.loads(raw_lines[-1].decode("ascii"))["result"]["content"][0]["text"]
        assert "\U0001f30d" in tool_text and "\\ud83c" not in tool_text
        separators = call("patchdiff_initialize_target", {"filename": "seps.txt", "content": "a\u2028b\u2029c\x85d\n",
                                                          "content_type": "text/plain"})
        echoed = call("patchdiff_read_target", {"target_file_id": separators["target_file_id"]})
        assert echoed["text"] == "a\u2028b\u2029c\x85d\n" and raw_lines[-1].isascii()
        assert raw_lines[-1].count(b"\n") == 1 and len(raw_lines[-1].decode("ascii").splitlines()) == 1
        exported = call("patchdiff_export_target", {"target_file_id": target_id, "format": "original_eol"})
        assert exported["content"] == content and exported["content_eol"] == "crlf"
        assert exported["content_sha256"] == upload["source_line_endings"]["source_sha256"]
        unsupported = call("patchdiff_export_target", {"target_file_id": target_id, "format": "docx"}, schema_valid=False)
        assert unsupported["code"] == "unsupported_export_format"

        # FR-13: line offsets without arithmetic.
        lines = call("patchdiff_read_lines", {"target_file_id": target_id, "start_line": 2, "end_line": 3,
                                              "include_line_starts": True, "max_chars": 4})
        assert lines["line_starts"] == [{"line": 2, "start": 10}] and lines["next_start"] == 14

        # FR-2: span context records the immutable 0.5.0 profile; a stale insertion offset is caught.
        stale = call("patchdiff_submit_operations", {
            "target_file_id": target_id, "intent": "Insert gamma", "expected_target_version": 0,
            "operations": [{"op": "span", "start": 20, "end": 20, "expected_text": "", "replace": "gamma\n",
                            "expected_before": "beta\n"}]})
        assert stale["status"] == "rejected" and stale["diagnostic"]["span_check"] == "expected_before"
        assert stale["diagnostic"]["retryable"] is True and stale["diagnostic"]["actual_text"] == "\nbeta"
        # FR-8: the duplicate current context is elided in favour of diagnostic.failure_context.
        assert stale["current_context"]["unavailable_reason"] == "same_as_failure_context"
        accepted = call("patchdiff_submit_operations", {
            "target_file_id": target_id, "intent": "Insert gamma", "expected_target_version": 0,
            "parent_pdcp_log_id": stale["pdcp_log_id"], "attempt": 2,
            "operations": [{"op": "span", "start": 21, "end": 21, "expected_text": "", "replace": "gamma\n",
                            "expected_before": "beta\n"}]})
        assert accepted["status"] == "accepted" and accepted["current_version"] == 1
        assert accepted["current_hash"] == accepted["after_hash"] and accepted["warnings"] == []
        with SessionLocal() as session:
            assert session.get(AppendOnlyPdcpLogs, uuid.UUID(accepted["pdcp_log_id"])).runtime_version == \
                SPAN_CONTEXT_RUNTIME_VERSION

        # FR-1/FR-17: sequential index warning and no-op warning.
        warned = call("patchdiff_submit_edits", {
            "target_file_id": target_id, "intent": "Rename", "expected_target_version": 1,
            "edits": [{"match": "a", "replace": "A", "occurrence_index": 1}, {"match": "a", "replace": "A", "occurrence_index": 1}]})
        assert warned["status"] == "accepted" and warned["warning_details"][0]["code"] == "occurrence_index_basis_shift"
        assert warned["warning_details"][0]["transaction_start_occurrence_index"] == 2

        # FR-19 and FR-14: preview near misses, and a structured unknown-argument error.
        near = call("patchdiff_preview", {"target_file_id": target_id, "format": "patchdiff-tx/1", "intent": "x",
                                          "expected_target_version": 2, "edits": [{"match": "gamme", "replace": "g"}]})
        assert near["near_misses"]["candidates"][0]["start"] == 21
        unknown = call("patchdiff_preview", {"target_file_id": target_id, "format": "patchdiff-tx/1",
                                             "include_correlation_id": True}, error=True)
        assert unknown["status"] == "invalid_argument" and unknown["code"] == "unknown_argument"

        # FR-11/FR-20: joinable ledger and version-guarded SAVE.
        ledger = call("patchdiff_get_manifest_ledger", {"target_file_id": target_id})["entries"]
        assert ledger[-1]["pdcp_log_id"] == warned["pdcp_log_id"] and ledger[-1]["transaction_intent"] == "Rename"
        assert call("patchdiff_save", {"target_file_id": target_id, "expected_target_version": 1})["failure_reason"] == \
            "target_version_mismatch"
        saved = call("patchdiff_save", {"target_file_id": target_id, "expected_target_version": 2})
        assert saved["status"] == "saved"
        replay = call("patchdiff_replay", {"target_file_id": target_id})
        assert replay["status"] == "success" and replay["materialized_state_matches"] is True
        with SessionLocal() as session:
            assert session.get(CloudTargetFiles, uuid.UUID(target_id)).version == 2
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        assert process.returncode == 0, process.stderr.read().decode("utf-8")
