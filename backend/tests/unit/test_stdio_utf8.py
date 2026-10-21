"""UTF-8 process-boundary regressions; injectable serve_stdio stays independent."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.mcp import external_adapter

BACKEND = Path(__file__).resolve().parents[2]


def _subprocess(messages: bytes) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env.update(PYTHONPATH=str(BACKEND), PYTHONIOENCODING="cp1252:surrogateescape")
    env.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, "-m", "app.mcp.external_adapter"],
        input=messages,
        capture_output=True,
        cwd=BACKEND,
        env=env,
        timeout=30,
    )


def test_raw_utf8_tool_argument_is_not_decoded_as_ambient_cp1252() -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "patchdiff_read_target", "arguments": {"target_file_id": "🌟"}},
    }
    completed = _subprocess((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(json.loads(completed.stdout)["result"]["content"][0]["text"])
    assert result["target_file_id"] == "🌟"


def test_main_configures_existing_stream_wrappers_before_serving(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="surrogateescape")
    outgoing = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="replace")
    monkeypatch.setattr(external_adapter.sys, "stdin", incoming)
    monkeypatch.setattr(external_adapter.sys, "stdout", outgoing)
    seen = []

    def serve() -> None:
        seen.append((incoming.encoding, incoming.errors, outgoing.encoding, outgoing.errors))

    monkeypatch.setattr(external_adapter, "serve_stdio", serve)
    external_adapter.main()
    assert seen == [("utf-8", "strict", "utf-8", "strict")]


def test_injected_text_streams_remain_usable() -> None:
    incoming = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n')
    outgoing = io.StringIO()
    external_adapter.serve_stdio(incoming, outgoing)
    assert json.loads(outgoing.getvalue())["result"]["serverInfo"]["name"] == "patchdiff-mvp"


def test_invalid_utf8_wire_bytes_fail_before_tool_dispatch() -> None:
    completed = _subprocess(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"bad":"\xff"}}\n')
    assert completed.returncode != 0
    assert completed.stdout == b""
    assert b"UnicodeDecodeError" in completed.stderr
