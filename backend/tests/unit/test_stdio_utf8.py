"""UTF-8 process-boundary regressions; injectable serve_stdio stays independent."""
from __future__ import annotations

import io
from typing import Any
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

    def serve(*args: object, **kwargs: object) -> None:
        seen.append((incoming.encoding, incoming.errors, outgoing.encoding, outgoing.errors))

    monkeypatch.setattr(external_adapter, "serve_stdio", serve)
    external_adapter.main([])
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


def test_main_help_flag_prints_help_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    external_adapter.main(["--help"])
    captured = capsys.readouterr()
    assert "PatchDIFF MCP Server (patchdiff-mcp)" in captured.out
    assert "PATCHDIFF_DATABASE_URL" in captured.out


def test_main_version_flag_prints_version_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    external_adapter.main(["--version"])
    captured = capsys.readouterr()
    assert captured.out.strip() == f"patchdiff-mcp {external_adapter.SERVER_VERSION}"


def test_main_migrate_flag_executes_upgrade(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from alembic import command
    calls = []
    def fake_upgrade(config, revision):
        calls.append((config.config_file_name, revision))
    monkeypatch.setattr(command, "upgrade", fake_upgrade)
    external_adapter.main(["--migrate"])
    captured = capsys.readouterr()
    assert len(calls) == 1
    assert calls[0][0].endswith("alembic.ini")
    assert calls[0][1] == "head"
    assert "PatchDIFF database migrations upgraded to head." in captured.out

def test_main_profile_and_response_mode_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_serve(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(external_adapter, "serve_stdio", fake_serve)
    incoming = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    outgoing = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(external_adapter.sys, "stdin", incoming)
    monkeypatch.setattr(external_adapter.sys, "stdout", outgoing)

    external_adapter.main(["--profile", "observed_workspace", "--response-mode", "compact"])
    assert seen == {"profile": "observed_workspace", "response_mode": "compact"}


def test_main_rejects_missing_profile_argument(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        external_adapter.main(["--profile"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "requires an argument" in captured.err


def test_main_rejects_unknown_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        external_adapter.main(["--unknown-flag"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized option" in captured.err


def test_main_rejects_invalid_profile(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        external_adapter.main(["--profile", "invalid_profile"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "unknown profile" in captured.err


def test_pure_python_profiles_do_not_prewarm_waymark_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import nullcontext
    from app.services import waymark_worker
    prewarmed: list[bool] = []

    def fake_serving_worker_owner(*, prewarm: bool = False) -> Any:
        prewarmed.append(prewarm)
        return nullcontext()

    monkeypatch.setattr(waymark_worker, "serving_worker_owner", fake_serving_worker_owner)

    incoming = io.StringIO()
    outgoing = io.StringIO()
    external_adapter.serve_stdio(incoming, outgoing, profile="unobserved_editor")
    assert prewarmed == []

    external_adapter.serve_stdio(incoming, outgoing, profile="editor")
    assert prewarmed == [True]
