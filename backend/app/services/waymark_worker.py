"""One process-owned, bounded Waymark transport. No document authority is cached here."""
from __future__ import annotations

import atexit
from collections import deque
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import struct
import subprocess
import tempfile
import threading
import time
import uuid

from app.services.performance_events import (
    bridge_environment, collect_bridge_events, process_memory, span, track_child,
)
from app.services.waymark_adapter import resolve_node_executable

PROTOCOL = "patchdiff-waymark-worker/1"
ENGINE_VERSION = "4.1.0"
BRIDGE = Path(__file__).resolve().parents[3] / "integrations" / "waymark"
RESULT_LIMIT = 2 * 1024 * 1024
CONTROL_LIMIT = 4096
STDERR_LIMIT = 65536
STARTUP_TIMEOUT = 7.0
QUEUE_TIMEOUT = 2.0
LOCKED_QUEUE_TIMEOUT = .250
MAX_WAITING = 8
RSS_LIMIT = 1024 ** 3
MAX_REQUESTS = 10000
MAX_AGE = 3600


class WaymarkWorkerError(RuntimeError):
    """Infrastructure failure: propagate through transaction ownership, never audit a verdict."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _error(suffix, message):
    return WaymarkWorkerError("WAYMARK_WORKER_" + suffix, message)


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON member")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("Nonfinite JSON number")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def _process_identity(pid):
    """Creation identity, False for confirmed dead, None for ambiguous access."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return None
            if exit_code.value != 259:  # A terminated Windows process may still have open handles.
                return False
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        # Linux stat comm may contain spaces/parentheses; fields after its final ')' are fixed.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return False if fields[0] == "Z" else fields[19]
    except FileNotFoundError:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return None
    except OSError:
        return None


class _WindowsJob:
    """The handle is intentionally non-inheritable; parent death kills the owned child."""
    def __init__(self, process):
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                        ("Flags", wintypes.DWORD), ("Min", ctypes.c_size_t), ("Max", ctypes.c_size_t),
                        ("Active", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IO", IO)] + [(name, ctypes.c_size_t) for name in
                        ("ProcessMemory", "JobMemory", "PeakProcess", "PeakJob")]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                or not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle))):
            self.close()
            raise _error("STARTUP_FAILED", "Could not establish child process ownership.")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _remove_owned(path, *, seconds=1):
    """Bound delivery even if a filesystem operation stalls; retain failed roots for shutdown."""
    errors = []
    def remove():
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            errors.append(exc)
    thread = threading.Thread(target=remove, daemon=True)
    thread.start()
    thread.join(seconds)
    return not thread.is_alive() and not errors


def _clean_stale_roots():
    base = Path(tempfile.gettempdir()).resolve()
    for root in base.glob("patchdiff-waymark-owner-*"):
        try:
            if root.is_symlink() or root.resolve().parent != base:
                continue
            meta = _strict_json((root / "owner.json").read_bytes())
            pid, identity = meta["pid"], meta["creation_identity"]
            token = str(uuid.UUID(meta["root_uuid"]))
            if (meta["protocol"] != PROTOCOL or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
                    or root.name != f"patchdiff-waymark-owner-{pid}-{token}" or not isinstance(identity, str)):
                continue
            current = _process_identity(pid)
            if current is False or (isinstance(current, str) and current != identity):
                _remove_owned(root)
        except (OSError, ValueError, KeyError, TypeError):
            continue  # Ambiguous roots are never deleted.


class _Generation:
    def __init__(self, owner):
        self.owner = owner
        self.id = str(uuid.uuid4())
        self.root = owner.root / ("generation-" + self.id)
        self.root.mkdir()
        self.frames = queue.Queue(maxsize=2)
        self.lock = threading.Lock()
        self.expected = None
        self.error = None
        self.sequence = 0
        self.completed = 0
        self.born = time.monotonic()
        self.job = None
        self.proc = None
        self.threads = []
        self.stopping = threading.Event()
        self.ready = False
        digest = hashlib.sha256()
        for name in ("discovery_core.mjs", "worker.mjs"):
            raw = (BRIDGE / name).read_bytes()
            digest.update(f"{name}\0{len(raw)}\0".encode("ascii"))
            digest.update(raw)
        self.bridge_hash = digest.hexdigest()

    def start(self):
        env = {**os.environ, "TMPDIR": str(self.root), "TEMP": str(self.root), "TMP": str(self.root)}
        env.update(bridge_environment(self.root / "startup-events.jsonl"))
        self.proc = subprocess.Popen([self.owner.node, "--max-old-space-size=768", str(self.owner.script), str(self.root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, bufsize=0, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, start_new_session=os.name != "nt")
        if os.name == "nt":
            self.job = _WindowsJob(self.proc)
        track_child(self.proc.pid, active=True)
        for target in (self._read_frames, self._read_stderr, self._monitor):
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread)
            thread.start()
        reply = self.exchange("hello", "0", {"engine_version": ENGINE_VERSION,
            "bridge_sha256": self.bridge_hash, "owner_pid": self.owner.pid}, STARTUP_TIMEOUT, "ready")
        if reply["bridge_sha256"] != self.bridge_hash or reply["worker_pid"] != self.proc.pid:
            raise _error("PROTOCOL_ERROR", "Readiness identity mismatch.")
        if reply["engine_version"] != ENGINE_VERSION:
            # Adapter maps this to the historical domain error.
            return reply["engine_version"]
        self.ready = True
        if "PATCHDIFF_BRIDGE_PERF_FILE" in env:
            collect_bridge_events(self.root / "startup-events.jsonl")
        return ENGINE_VERSION

    def poison(self, error):
        with self.lock:
            if self.error is None:
                self.error = error
            self.ready = False
        self._kill()
        self.owner.notify()

    def _kill(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                if os.name == "nt":
                    self.proc.kill()
                else:
                    os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _read_exact(self, size):
        result = bytearray()
        while len(result) < size:
            raw = self.proc.stdout.read(min(65536, size - len(result)))
            if not raw:
                raise ValueError("Partial frame or child exit")
            result.extend(raw)
        return bytes(result)

    def _read_frames(self):
        try:
            while not self.stopping.is_set():
                size = struct.unpack(">I", self._read_exact(4))[0]
                with self.lock:
                    result_pending = self.expected is not None and self.expected[0] == "result"
                limit = RESULT_LIMIT + CONTROL_LIMIT if result_pending else CONTROL_LIMIT
                if not 0 < size <= limit:
                    raise ValueError("Invalid frame size")
                value = _strict_json(self._read_exact(size))
                with self.lock:
                    expected = self.expected
                    if not expected or not isinstance(value, dict):
                        raise ValueError("Unsolicited frame")
                    kind, request_id = expected
                    extra = {"ready": {"engine_version", "bridge_sha256", "worker_pid"},
                             "closed": set(), "result": {"result", "result_bytes"}}[kind]
                    if (set(value) != {"protocol", "type", "generation", "id"} | extra or
                            value["protocol"] != PROTOCOL or value["type"] != kind or
                            value["generation"] != self.id or value["id"] != request_id or
                            (kind != "result" and size > CONTROL_LIMIT)):
                        raise ValueError("Frame association mismatch")
                    self.expected = None
                self.frames.put_nowait(value)
        except (OSError, ValueError, KeyError, TypeError, queue.Full):
            if not self.stopping.is_set():
                self.poison(_error("PROTOCOL_ERROR", "Worker lost frame association or exited."))

    def _read_stderr(self):
        count = 0
        try:
            while not self.stopping.is_set():
                raw = self.proc.stderr.read(min(4096, STDERR_LIMIT + 1 - count))
                if not raw:
                    return
                count += len(raw)
                if count > STDERR_LIMIT:
                    self.poison(_error("PROTOCOL_ERROR", "Worker exceeded the stderr limit."))
                    return
        except OSError:
            pass

    def _monitor(self):
        while not self.stopping.wait(.1):
            memory = process_memory(self.proc.pid)
            if memory and memory[0] > RSS_LIMIT:
                self.poison(_error("RSS_LIMIT", "Worker exceeded its sampled RSS limit."))
                return

    def exchange(self, kind, request_id, fields, timeout, response_type, cancel=None):
        deadline = time.monotonic() + timeout
        raw = json.dumps({"protocol": PROTOCOL, "type": kind, "generation": self.id, "id": request_id,
                          **fields}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(raw) > CONTROL_LIMIT:
            raise _error("PROTOCOL_ERROR", "Oversized parent control frame.")
        with self.lock:
            if self.error:
                raise self.error
            if self.expected is not None or not self.frames.empty():
                raise _error("PROTOCOL_ERROR", "Unexpected pending worker data.")
            self.expected = (response_type, request_id)
        write_errors = []
        def write():
            try:
                data = memoryview(struct.pack(">I", len(raw)) + raw)
                with span("ipc_write", bytes_count=len(data)):
                    while data:
                        written = self.proc.stdin.write(data)
                        if not written:
                            raise OSError("Worker pipe closed")
                        data = data[written:]
            except (OSError, ValueError) as exc:
                write_errors.append(exc)
        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        with span("ipc_read"):
            while True:
                if cancel is not None and cancel.is_set():
                    raise _error("CANCELLED", "Invocation was cancelled.")
                if self.owner.closed:
                    raise _error("CANCELLED", "Serving process is shutting down.")
                if self.error:
                    raise self.error
                if write_errors:
                    raise _error("PROTOCOL_ERROR", "Worker pipe write failed.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired("Waymark worker", timeout)
                try:
                    value = self.frames.get(timeout=min(.05, remaining))
                    writer.join(timeout=max(0, deadline - time.monotonic()))
                    if writer.is_alive() or self.error or write_errors:
                        raise self.error or _error("PROTOCOL_ERROR", "Worker pipe write failed." if write_errors else "Worker did not consume its control frame.")
                    return value
                except queue.Empty:
                    continue

    def close(self):
        self.ready = False
        self.stopping.set()
        self._kill()
        if self.proc is not None:
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.owner.unhealthy = True
            if self.job:
                self.job.close()
            for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:
                    pipe.close()
                except OSError:
                    pass
            for thread in self.threads:
                thread.join(timeout=.05)
            track_child(self.proc.pid, active=False)
        if not _remove_owned(self.root):
            self.owner.pending_cleanup.add(self.root)
            self.owner.unhealthy = True


class WaymarkWorkerOwner:
    def __init__(self, *, mode=None, node=None, script=None):
        self.pid = os.getpid()
        self.mode = mode or os.getenv("PATCHDIFF_WAYMARK_MODE", "oneshot")
        if self.mode not in ("oneshot", "resident"):
            raise ValueError("Unknown PATCHDIFF_WAYMARK_MODE; expected oneshot or resident")
        if os.getenv("PATCHDIFF_WAYMARK_WORKERS", "1") != "1":
            raise ValueError("Only one resident Waymark worker is supported in this release")
        self.node = resolve_node_executable(node)
        self.script = script or BRIDGE / "worker.mjs"
        self.condition = threading.Condition()
        self.lifecycle = threading.RLock()
        self.waiting = deque()
        self.launches = deque()
        self.active = False
        self.closed = False
        self.unhealthy = False
        self.generation = None
        self.root = None
        self.pending_cleanup = set()
        self.references = 0

    def notify(self):
        with self.condition:
            self.condition.notify_all()

    def _ready(self):
        generation = self.generation
        return (generation is not None and generation.ready and not generation.error and
                generation.proc.poll() is None and generation.completed < MAX_REQUESTS and
                time.monotonic() - generation.born < MAX_AGE)

    @contextmanager
    def permit(self, *, locked=False, cancel=None):
        ticket = object()
        deadline = time.monotonic() + (LOCKED_QUEUE_TIMEOUT if locked else QUEUE_TIMEOUT)
        with span("worker_queue"):
            with self.condition:
                if len(self.waiting) >= MAX_WAITING:
                    raise _error("QUEUE_FULL", "Discovery queue is full.")
                self.waiting.append(ticket)
                try:
                    while True:
                        if self.closed or (cancel is not None and cancel.is_set()):
                            raise _error("CANCELLED", "Discovery was cancelled.")
                        if self.unhealthy:
                            raise _error("UNHEALTHY", "Worker cleanup requires owner shutdown.")
                        if self.waiting[0] is ticket and not self.active and (not locked or self._ready()):
                            self.waiting.popleft()
                            self.active = True
                            break
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise _error("QUEUE_TIMEOUT", "No ready discovery capacity before admission deadline.")
                        self.condition.wait(min(.05, remaining))
                except BaseException:
                    self.waiting.remove(ticket)
                    self.condition.notify_all()
                    raise
        try:
            yield
        finally:
            with self.condition:
                self.active = False
                self.condition.notify_all()

    def _ensure_ready(self):
        with self.lifecycle:
            if self.closed:
                raise _error("CANCELLED", "Serving process is shutting down.")
            if self._ready():
                return ENGINE_VERSION
            if self.generation is not None:
                self.generation.close()
                self.generation = None
            if self.unhealthy:
                raise _error("UNHEALTHY", "Previous worker could not be cleaned up.")
            now = time.monotonic()
            while self.launches and self.launches[0] <= now - 60:
                self.launches.popleft()
            if len(self.launches) >= 3:
                raise _error("RESTART_LIMIT", "Worker launch limit reached; host may retry later.")
            if self.root is None:
                _clean_stale_roots()
                token = str(uuid.uuid4())
                self.root = Path(tempfile.gettempdir()).resolve() / f"patchdiff-waymark-owner-{self.pid}-{token}"
                self.root.mkdir(mode=0o700)
                identity = _process_identity(self.pid)
                (self.root / "owner.json").write_text(json.dumps({"protocol": PROTOCOL, "pid": self.pid,
                    "creation_identity": identity, "root_uuid": token, "root_name": self.root.name}), encoding="ascii")
            self.launches.append(now)
            self.generation = _Generation(self)
            with span("worker_spawn_ready"):
                try:
                    return self.generation.start()
                except subprocess.TimeoutExpired as exc:
                    raise _error("STARTUP_FAILED", "Worker readiness deadline expired.") from exc

    def prewarm(self):
        if self.mode == "resident":
            with self.permit():
                try:
                    return self._ensure_ready()
                except BaseException:
                    self.retire()
                    raise

    def retire(self):
        with self.lifecycle:
            if self.generation is not None:
                self.generation.close()
                self.generation = None
        self.notify()

    def discover(self, payload, *, timeout, locked=False, cancel=None):
        outer = time.monotonic() + timeout + 13
        with self.permit(locked=locked, cancel=cancel):
            request_root = None
            try:
                if not locked:
                    version = self._ensure_ready()
                    if version != ENGINE_VERSION:
                        self.retire()
                        return json.dumps({"ok": False, "waymark_engine_version": version}).encode("utf-8")
                generation = self.generation
                if not self._ready():
                    raise _error("QUEUE_TIMEOUT", "Ready worker became unavailable before dispatch.")
                active_deadline = min(time.monotonic() + timeout, outer - 3)
                request_root = generation.root / ("request-" + str(uuid.uuid4()))
                request_root.mkdir()
                telemetry = bridge_environment(request_root / "bridge-events.jsonl")
                if telemetry:
                    (request_root / "performance.json").write_text(json.dumps(telemetry), encoding="ascii")
                digest = hashlib.sha256()
                size = 0
                encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                with (request_root / "input.json").open("xb") as stream:
                    for piece in encoder.iterencode(payload):
                        for start in range(0, len(piece), 65536):
                            if self.closed or (cancel is not None and cancel.is_set()):
                                raise _error("CANCELLED", "Invocation was cancelled while spooling.")
                            if time.monotonic() >= active_deadline:
                                raise subprocess.TimeoutExpired("Waymark worker", timeout)
                            raw = piece[start:start + 65536].encode("utf-8")
                            stream.write(raw)
                            digest.update(raw)
                            size += len(raw)
                generation.sequence += 1
                if generation.sequence > 18446744073709551615:
                    raise _error("PROTOCOL_ERROR", "Worker request ID range exhausted.")
                response = generation.exchange("discover", str(generation.sequence),
                    {"request_dir": request_root.name, "input_bytes": str(size), "input_sha256": digest.hexdigest()},
                    max(0, active_deadline - time.monotonic()), "result", cancel=cancel)
                actual = response["result_bytes"]
                if isinstance(actual, bool) or not isinstance(actual, int) or actual < 1:
                    raise _error("PROTOCOL_ERROR", "Invalid result byte count.")
                if actual > RESULT_LIMIT:
                    self.retire()
                    return b" " * (RESULT_LIMIT + 1)
                result = response["result"]
                encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
                if actual != len(encoded):
                    raise _error("PROTOCOL_ERROR", "Result byte count mismatch.")
                generation.completed += 1
                if telemetry:
                    collect_bridge_events(request_root / "bridge-events.jsonl")
                return encoded
            except OSError as exc:
                self.retire()
                if request_root is not None:
                    raise _error("PROTOCOL_ERROR", "Worker request file I/O failed.") from exc
                raise
            except (WaymarkWorkerError, subprocess.TimeoutExpired):
                self.retire()
                raise
            except ValueError as exc:
                self.retire()
                raise _error("PROTOCOL_ERROR", "Invalid worker response.") from exc
            except BaseException:
                self.retire()
                raise
            finally:
                if request_root is not None and not _remove_owned(request_root):
                    self.pending_cleanup.add(request_root)
                    self.unhealthy = True
                    raise _error("UNHEALTHY", "Request directory cleanup failed.")

    def close(self):
        self.closed = True
        self.notify()
        self.retire()
        for path in list(self.pending_cleanup):
            if _remove_owned(path):
                self.pending_cleanup.discard(path)
        if self.root is not None and not _remove_owned(self.root):
            self.pending_cleanup.add(self.root)


_owner = None
_owner_lock = threading.RLock()


def get_process_worker_owner():
    global _owner
    with _owner_lock:
        if _owner is None or _owner.pid != os.getpid() or _owner.closed:
            _owner = WaymarkWorkerOwner()
        return _owner


def close_process_worker_owner():
    global _owner
    with _owner_lock:
        if _owner is not None and _owner.pid == os.getpid():
            _owner.close()
            _owner = None


@contextmanager
def serving_worker_owner(*, prewarm=False):
    owner = get_process_worker_owner()
    with _owner_lock:
        owner.references += 1
    try:
        if prewarm:
            try:
                owner.prewarm()
            except (WaymarkWorkerError, OSError):
                pass  # Recorded-key recovery must remain available without discovery capacity.
        yield owner
    finally:
        with _owner_lock:
            owner.references -= 1
            if owner.references == 0:
                close_process_worker_owner()


def _after_fork():
    global _owner, _owner_lock
    if _owner is not None and _owner.generation is not None:
        proc = _owner.generation.proc
        if proc is not None:
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                pipe.close()
    _owner, _owner_lock = None, threading.RLock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)
atexit.register(close_process_worker_owner)
