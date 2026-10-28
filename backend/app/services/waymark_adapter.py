"""Read-only Python adapter over the pinned `waymark-engine@4.1.0` npm package.

Target content is read exclusively from Patch-DIFF's authoritative PostgreSQL
state (`CloudTargetFiles`) and passed to `integrations/waymark/discover.mjs`
over stdin using an explicit argument vector (`shell=False`).
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.input_text import invalid_text_paths
from app.storage.models import CloudTargetFiles
from app.services.performance_events import span, bridge_environment, collect_bridge_events, track_child

EXPECTED_WAYMARK_ENGINE_VERSION = "4.1.0"
WAYMARK_INTEGRATION_DIR = Path(__file__).resolve().parents[3] / "integrations" / "waymark"
WAYMARK_DISCOVER_SCRIPT = WAYMARK_INTEGRATION_DIR / "discover.mjs"

DEFAULT_WAYMARK_TIMEOUT_SECONDS = 15.0
MAX_WAYMARK_STDOUT_BYTES = 2 * 1024 * 1024
MAX_WAYMARK_STDERR_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class WaymarkPosition:
    line: int
    column: int

    def to_dict(self) -> dict[str, int]:
        return {"line": self.line, "column": self.column}


@dataclass(frozen=True, slots=True)
class WaymarkSymbol:
    name: str
    kind: str
    parent: str | None
    signature: str | None
    start: WaymarkPosition
    end: WaymarkPosition

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "parent": self.parent,
            "signature": self.signature,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class WaymarkAdapterError:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class WaymarkDiscoveryResult:
    ok: bool
    waymark_engine_version: str | None
    language: str | None
    symbols: tuple[WaymarkSymbol, ...]
    error: WaymarkAdapterError | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "waymark_engine_version": self.waymark_engine_version,
            "language": self.language,
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "error": self.error.to_dict() if self.error is not None else None,
        }


@dataclass(frozen=True, slots=True)
class AuthoritativeTargetSnapshot:
    target_file_id: uuid.UUID
    filename: str
    target_type: str
    current_content: str
    current_version: int
    current_hash: str


def observe_authoritative_target(
    session: Session,
    target_file_id: uuid.UUID,
) -> AuthoritativeTargetSnapshot | None:
    """Read target metadata and canonical LF content from PostgreSQL without flushing."""
    with session.no_autoflush:
        row = session.execute(
            select(
                CloudTargetFiles.target_file_id,
                CloudTargetFiles.filename,
                CloudTargetFiles.target_type,
                CloudTargetFiles.current_content,
                CloudTargetFiles.version,
                CloudTargetFiles.current_hash,
            ).where(CloudTargetFiles.target_file_id == target_file_id)
        ).one_or_none()
    return AuthoritativeTargetSnapshot(*row) if row is not None else None


def resolve_node_executable(explicit_node: str | None = None) -> str:
    candidate = explicit_node or os.getenv("PATCHDIFF_NODE_BINARY") or shutil.which("node") or "node"
    return str(candidate)


def _run_bounded_discovery(
    argv: list[str], input_bytes: bytes, timeout: float, stdout_limit: int, stderr_limit: int,
) -> subprocess.CompletedProcess:
    """Drain both pipes concurrently, retaining at most each cap plus one sentinel byte."""
    outputs = [bytearray(), bytearray()]
    limits = [stdout_limit, stderr_limit]
    # A file-backed stdin avoids blocking a writer while a noisy child fills its pipes.
    with tempfile.TemporaryDirectory(prefix="patchdiff-waymark-run-") as run_dir, tempfile.TemporaryFile(dir=run_dir) as source:
        with span("ipc_write", bytes_count=len(input_bytes)):
            source.write(input_bytes)
            source.seek(0)
        child_env = {**os.environ, "TMPDIR": run_dir, "TEMP": run_dir, "TMP": run_dir}
        perf_path = Path(run_dir) / "bridge-events.jsonl"
        child_env.update(bridge_environment(perf_path))
        # The parent owns Node's temp root, including cleanup after forced termination.
        with subprocess.Popen(argv, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              shell=False, env=child_env) as proc:
            track_child(proc.pid, active=True)
            def read_pipe(index, pipe):
                while True:
                    chunk = pipe.read(min(65536, limits[index] + 1 - len(outputs[index])))
                    if not chunk:
                        return
                    outputs[index].extend(chunk)
                    if len(outputs[index]) > limits[index]:
                        proc.kill()
                        return

            readers = [threading.Thread(target=read_pipe, args=(index, pipe))
                       for index, pipe in enumerate((proc.stdout, proc.stderr))]
            for reader in readers:
                reader.start()
            try:
                proc.wait(timeout=timeout)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                for reader in readers:
                    reader.join()
                track_child(proc.pid, active=False)
            if "PATCHDIFF_BRIDGE_PERF_FILE" in child_env:
                collect_bridge_events(perf_path)
            return subprocess.CompletedProcess(argv, proc.returncode, bytes(outputs[0]), bytes(outputs[1]))


def discover_symbols_from_content(
    *,
    filename: str,
    content: str,
    query: str | None = None,
    kind: str | None = None,
    symbol_name: str | None = None,
    timeout_seconds: float = DEFAULT_WAYMARK_TIMEOUT_SECONDS,
    node_executable: str | None = None,
    discover_script: Path | None = None,
    max_stdout_bytes: int = MAX_WAYMARK_STDOUT_BYTES,
    max_stderr_bytes: int = MAX_WAYMARK_STDERR_BYTES,
    _locked_submission: bool = False,
    _cancel_event=None,
) -> WaymarkDiscoveryResult:
    """Run read-only Waymark symbol discovery against canonical in-memory target text."""
    if invalid_text_paths(
        {
            "filename": filename,
            "content": content,
            "query": query,
            "kind": kind,
            "symbol_name": symbol_name,
        }
    ):
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="INVALID_INPUT_ENCODING",
                message="Discovery inputs must be valid UTF-8 strings without NUL.",
            ),
        )
    if not isinstance(filename, str) or not filename.strip():
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="INVALID_INPUT",
                message="filename must be a non-empty string.",
            ),
        )
    if not isinstance(content, str):
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="INVALID_INPUT",
                message="content must be a string.",
            ),
        )
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="INVALID_INPUT",
                message="timeout_seconds must be a positive number.",
            ),
        )

    script_path = discover_script if discover_script is not None else WAYMARK_DISCOVER_SCRIPT
    if not script_path.is_file():
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_BRIDGE_UNAVAILABLE",
                message=f"Waymark discovery bridge script was not found at {script_path}.",
            ),
        )

    payload = {
        "filename": filename,
        "content": content,
        "query": query,
        "kind": kind,
        "symbol_name": symbol_name,
    }
    argv = [resolve_node_executable(node_executable), str(script_path)]

    try:
        from app.services.waymark_worker import get_process_worker_owner
        explicit_runner = (discover_script is not None or node_executable is not None or
                           max_stdout_bytes != MAX_WAYMARK_STDOUT_BYTES or max_stderr_bytes != MAX_WAYMARK_STDERR_BYTES)
        owner = None if explicit_runner else get_process_worker_owner()
        if owner is not None and owner.mode == "resident":
            raw = owner.discover(payload, timeout=float(timeout_seconds), locked=_locked_submission, cancel=_cancel_event)
            completed = subprocess.CompletedProcess(argv, 0, raw, b"")
        else:
            input_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            completed = _run_bounded_discovery(
                argv, input_bytes, float(timeout_seconds), max_stdout_bytes, max_stderr_bytes,
            )
    except subprocess.TimeoutExpired:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_TIMEOUT",
                message=f"Waymark discovery timed out after {timeout_seconds}s.",
            ),
        )
    except OSError as exc:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_PROCESS_ERROR",
                message=f"Failed to invoke Node for Waymark discovery: {exc}",
            ),
        )

    return _decode_discovery_result(completed, max_stdout_bytes, max_stderr_bytes)


def _decode_discovery_result(completed, max_stdout_bytes, max_stderr_bytes):
    """Identical validation for one-shot and resident results."""
    stdout_bytes = completed.stdout or b""
    stderr_bytes = completed.stderr or b""
    if len(stdout_bytes) > max_stdout_bytes:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_OUTPUT_TOO_LARGE",
                message=f"Waymark discovery stdout exceeded {max_stdout_bytes} bytes.",
            ),
        )
    if len(stderr_bytes) > max_stderr_bytes:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_OUTPUT_TOO_LARGE",
                message=f"Waymark discovery stderr exceeded {max_stderr_bytes} bytes.",
            ),
        )

    try:
        stdout_text = stdout_bytes.decode("utf-8").strip()
    except UnicodeDecodeError:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_INVALID_OUTPUT",
                message="Waymark discovery emitted non-UTF-8 stdout.",
            ),
        )

    if not stdout_text:
        stderr_preview = stderr_bytes.decode("utf-8", errors="replace").strip()[:512]
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_PROCESS_ERROR",
                message=stderr_preview or f"Waymark discovery exited with code {completed.returncode} and empty stdout.",
            ),
        )

    try:
        parsed = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_INVALID_OUTPUT",
                message=f"Waymark discovery emitted invalid JSON on stdout: {exc.msg}.",
            ),
        )

    if not isinstance(parsed, dict) or not isinstance(parsed.get("ok"), bool):
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_INVALID_OUTPUT",
                message="Waymark discovery payload is missing boolean 'ok'.",
            ),
        )

    version = parsed.get("waymark_engine_version")
    if not isinstance(version, str) or version != EXPECTED_WAYMARK_ENGINE_VERSION:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=version if isinstance(version, str) else None,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_VERSION_MISMATCH",
                message=(
                    f"Expected waymark-engine@{EXPECTED_WAYMARK_ENGINE_VERSION}, "
                    f"got {version!r}."
                ),
            ),
        )

    if not parsed["ok"]:
        raw_err = parsed.get("error")
        if isinstance(raw_err, dict):
            code = str(raw_err.get("code") or "WAYMARK_DISCOVERY_ERROR")
            message = str(raw_err.get("message") or "Waymark symbol discovery failed.")
        else:
            code = "WAYMARK_DISCOVERY_ERROR"
            message = "Waymark symbol discovery failed."
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=version,
            language=parsed.get("language") if isinstance(parsed.get("language"), str) else None,
            symbols=(),
            error=WaymarkAdapterError(code=code, message=message),
        )

    raw_symbols = parsed.get("symbols")
    if not isinstance(raw_symbols, list):
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=version,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_INVALID_OUTPUT",
                message="Waymark discovery payload 'symbols' must be a list.",
            ),
        )

    symbols: list[WaymarkSymbol] = []
    try:
        for item in raw_symbols:
            if not isinstance(item, dict):
                raise ValueError("Symbol entry must be an object.")
            name = item.get("name")
            sym_kind = item.get("kind")
            parent = item.get("parent")
            signature = item.get("signature")
            start = item.get("start")
            end = item.get("end")
            if not isinstance(name, str) or not name:
                raise ValueError("Symbol 'name' must be a non-empty string.")
            if not isinstance(sym_kind, str) or not sym_kind:
                raise ValueError("Symbol 'kind' must be a non-empty string.")
            if parent is not None and not isinstance(parent, str):
                raise ValueError("Symbol 'parent' must be a string or null.")
            if signature is not None and not isinstance(signature, str):
                raise ValueError("Symbol 'signature' must be a string or null.")
            if not isinstance(start, dict) or not isinstance(end, dict):
                raise ValueError("Symbol 'start' and 'end' must be objects.")
            s_line, s_col = start.get("line"), start.get("column")
            e_line, e_col = end.get("line"), end.get("column")
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (s_line, s_col, e_line, e_col)):
                raise ValueError("Symbol line/column coordinates must be integers.")
            if s_line < 1 or e_line < s_line or s_col < 0 or e_col < 0:
                raise ValueError("Symbol coordinates are out of range.")
            symbols.append(
                WaymarkSymbol(
                    name=name,
                    kind=sym_kind,
                    parent=parent,
                    signature=signature,
                    start=WaymarkPosition(line=s_line, column=s_col),
                    end=WaymarkPosition(line=e_line, column=e_col),
                )
            )
    except ValueError as exc:
        return WaymarkDiscoveryResult(
            ok=False,
            waymark_engine_version=version,
            language=None,
            symbols=(),
            error=WaymarkAdapterError(
                code="WAYMARK_INVALID_OUTPUT",
                message=f"Invalid symbol entry in Waymark output: {exc}",
            ),
        )

    language = parsed.get("language")
    return WaymarkDiscoveryResult(
        ok=True,
        waymark_engine_version=version,
        language=language if isinstance(language, str) else None,
        symbols=tuple(symbols),
        error=None,
    )


def discover_target_symbols(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    query: str | None = None,
    kind: str | None = None,
    symbol_name: str | None = None,
    timeout_seconds: float = DEFAULT_WAYMARK_TIMEOUT_SECONDS,
) -> tuple[AuthoritativeTargetSnapshot | None, WaymarkDiscoveryResult | None]:
    """Read authoritative target content from PostgreSQL and run Waymark discovery."""
    try:
        target_uuid = (
            target_file_id
            if isinstance(target_file_id, uuid.UUID)
            else uuid.UUID(str(target_file_id))
        )
    except (ValueError, TypeError):
        return None, None
    target = observe_authoritative_target(session, target_uuid)
    if target is None:
        return None, None
    result = discover_symbols_from_content(
        filename=target.filename,
        content=target.current_content,
        query=query,
        kind=kind,
        symbol_name=symbol_name,
        timeout_seconds=timeout_seconds,
    )
    return target, result

