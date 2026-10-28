"""Opt-in, bounded timing evidence; telemetry never changes transaction outcomes."""
from __future__ import annotations

import atexit
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import os
from pathlib import Path
import queue
import threading
import time
import uuid

EVENTS = frozenset((
    "rpc", "task", "host_gap", "worker_queue", "worker_spawn_ready", "bridge_import",
    "bridge_temp_write", "bridge_discover", "bridge_result_encode", "bridge_cleanup",
    "ipc_write", "ipc_read", "lock_wait", "lock_hold", "sql", "coordinate_conversion",
    "observation_validation", "applier", "commit", "replay_capture", "replay_reconstruct",
    "checkpoint_verify", "snapshot_export",
))
_invocation = ContextVar("patchdiff_perf_invocation", default=None)
_target = ContextVar("patchdiff_perf_target", default=None)
_owner = None
_owner_pid = None
_owner_lock = threading.Lock()
_session_observers_installed = False
_memory_api = None
_memory_lock = threading.Lock()


def _windows_memory_api():
    # ctypes caches POINTER(Structure) types globally; define this type only once per process.
    global _memory_api
    if _memory_api is None:
        with _memory_lock:
            if _memory_api is not None:
                return _memory_api
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            _memory_api = ctypes, Counters, kernel, psapi
    return _memory_api


def process_memory(pid):
    """Return current and OS-observed peak RSS in bytes, or None after process exit."""
    try:
        if os.name == "nt":
            ctypes, Counters, kernel, psapi = _windows_memory_api()
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                return None
            try:
                counters = Counters()
                counters.cb = ctypes.sizeof(counters)
                if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    return None
                return counters.WorkingSetSize, counters.PeakWorkingSetSize
            finally:
                kernel.CloseHandle(handle)
        values = {}
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                values[line.split(':', 1)[0]] = int(line.split()[1]) * 1024
        return values["VmRSS"], values["VmHWM"]
    except (OSError, KeyError, ValueError):
        return None


def _uuid(value):
    try:
        return str(uuid.UUID(str(value))) if value is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


class PerformanceRecorder:
    def __init__(self, path: Path, *, capacity=4096):
        if not path.is_absolute():
            raise ValueError("Performance event path must be absolute.")
        self.path, self.pid = path, os.getpid()
        self.run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, path.resolve().as_uri()))
        self.instance_id = uuid.uuid4().hex
        self.queue = queue.Queue(maxsize=capacity)
        self.dropped = self.written = 0
        memory_mode = os.getenv("PATCHDIFF_PERF_MEMORY", "1")
        self.memory_enabled = memory_mode == "1"
        self.error = None if memory_mode in {"0", "1"} else "invalid_memory_configuration"
        self.closed = False
        self.children = set()
        self._streams = ()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._write, name="patchdiff-perf-writer", daemon=True)
        self._thread.start()

    def emit(self, event, start_ns, duration_ns, *, invocation_id=None, target_id=None,
             count=None, bytes_count=None, outcome="ok", generation=None, request_id=None, source_pid=None):
        if self.closed or self.error is not None:
            return
        if event not in EVENTS or outcome not in {"ok", "error", "commit", "rollback"}:
            self.dropped += 1
            return
        record = {
            "schema": "patchdiff-perf/1", "run_id": self.run_id, "pid": self.pid,
            "invocation_id": _uuid(invocation_id) or _invocation.get() or str(uuid.uuid4()),
            "event": event, "start_ns": start_ns, "duration_ns": duration_ns, "outcome": outcome,
        }
        if isinstance(source_pid, int) and not isinstance(source_pid, bool) and source_pid > 0:
            record["pid"] = source_pid
        target_id = _uuid(target_id) or _target.get()
        if target_id:
            record["target_id"] = target_id
        for key, value in (("count", count), ("bytes", bytes_count)):
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                record[key] = value
        if _uuid(generation):
            record["generation"] = _uuid(generation)
        if isinstance(request_id, str) and request_id.isascii() and request_id.isdecimal() and len(request_id) <= 20:
            record["request_id"] = request_id
        try:
            raw = (json.dumps(record, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
            if len(raw) > 2048:
                self.dropped += 1
                return
            self.queue.put_nowait(raw)
        except (queue.Full, TypeError, ValueError):
            self.dropped += 1

    @staticmethod
    def _write_locked(stream, lock, raw):
        # Separate MCP processes can share an evidence path; only writer threads wait for its lock.
        deadline = time.monotonic() + 1
        while True:
            try:
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
        try:
            view = memoryview(raw)
            while view:
                written = stream.write(view)
                if not written:
                    raise OSError("Telemetry write made no progress.")
                view = view[written:]
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with ExitStack() as stack:
                stream = stack.enter_context(self.path.open("ab", buffering=0))
                lock = stack.enter_context(Path(str(self.path) + ".lock").open("a+b", buffering=0))
                memory = stack.enter_context(Path(str(self.path) + ".memory.jsonl").open("ab", buffering=0)) if self.memory_enabled else None
                self._streams = (stream, lock) + ((memory,) if memory is not None else ())
                lock.seek(0, os.SEEK_END)
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                next_memory = 0
                while not self._stop.is_set() or not self.queue.empty():
                    if self.memory_enabled and time.monotonic() >= next_memory:
                        for pid in {self.pid} | self.children.copy():
                            measured = process_memory(pid)
                            if measured is not None:
                                row = {"schema": "patchdiff-memory/1", "run_id": self.run_id,
                                       "pid": pid, "owner_pid": self.pid, "time_ns": time.perf_counter_ns(),
                                       "rss_bytes": measured[0], "os_peak_rss_bytes": measured[1]}
                                self._write_locked(memory, lock, (json.dumps(row, separators=(",", ":")) + "\n").encode("ascii"))
                        next_memory = time.monotonic() + 0.05
                    try:
                        raw = self.queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    self._write_locked(stream, lock, raw)
                    self.written += 1
        except Exception:
            self.error = "writer_failed"

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._stop.set()
        self._thread.join(timeout=2)
        if self._thread.is_alive():
            self.error = "writer_shutdown_timeout"
        status = {"schema": "patchdiff-perf-status/1", "pid": self.pid, "run_id": self.run_id,
                  "written": self.written, "dropped": self.dropped, "error": self.error,
                  "memory_sampling_enabled": self.memory_enabled,
                  "valid": self.error is None and self.dropped == 0 and self.queue.empty()}
        try:
            Path(str(self.path) + f".status-{self.pid}-{self.instance_id}.json").write_text(json.dumps(status) + "\n", encoding="ascii")
        except OSError:
            self.error = "status_write_failed"


def get_recorder():
    global _owner, _owner_pid
    pid = os.getpid()
    if _owner_pid != pid:
        with _owner_lock:
            if _owner_pid != pid:
                _owner, _owner_pid = None, pid
                value = os.getenv("PATCHDIFF_PERF_EVENTS")
                if value:
                    try:
                        _owner = PerformanceRecorder(Path(value))
                    except Exception:
                        # Missing/invalid status invalidates measurements, never the transaction.
                        _owner = None
    return _owner


def close_performance_events():
    if _owner_pid == os.getpid() and _owner is not None:
        _owner.close()


def bridge_environment(path):
    if get_recorder() is None:
        return {}
    return {"PATCHDIFF_BRIDGE_PERF_FILE": str(path),
            "PATCHDIFF_BRIDGE_PERF_INVOCATION": _invocation.get() or str(uuid.uuid4())}


def track_child(pid, *, active):
    recorder = get_recorder()
    if recorder is not None:
        if active:
            recorder.children.add(pid)
        else:
            recorder.children.discard(pid)


def collect_bridge_events(path):
    recorder = get_recorder()
    if recorder is None:
        return
    try:
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("Bridge telemetry cap exceeded.")
        lines = raw.decode("ascii").splitlines()
        if not lines or len(lines) > 64:
            raise ValueError("Missing or excessive bridge telemetry.")
        for line in lines:
            row = json.loads(line)
            if set(row) != {"event", "start_ns", "duration_ns", "pid", "invocation_id"}:
                raise ValueError("Invalid bridge telemetry fields.")
            if row["event"] not in EVENTS or not row["event"].startswith("bridge_"):
                raise ValueError("Invalid bridge event.")
            start, duration = int(row["start_ns"]), int(row["duration_ns"])
            if (start < 0 or duration < 0 or _uuid(row["invocation_id"]) is None
                    or isinstance(row["pid"], bool) or not isinstance(row["pid"], int) or row["pid"] <= 0):
                raise ValueError("Invalid bridge telemetry values.")
            recorder.emit(row["event"], start, duration, invocation_id=row["invocation_id"], source_pid=row["pid"])
    except Exception:
        recorder.dropped += 1


@contextmanager
def span(event, *, target_id=None, count=None, bytes_count=None):
    recorder = get_recorder()
    if recorder is None:
        yield
        return
    token = _invocation.set(_invocation.get() or str(uuid.uuid4()))
    target_token = _target.set(_uuid(target_id) or _target.get())
    start, outcome = time.perf_counter_ns(), "ok"
    try:
        yield
    except BaseException:
        outcome = "error"
        raise
    finally:
        recorder.emit(event, start, time.perf_counter_ns() - start, count=count,
                      bytes_count=bytes_count, outcome=outcome)
        _target.reset(target_token)
        _invocation.reset(token)


def timed(event):
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            with span(event, target_id=kwargs.get("target_file_id")):
                return function(*args, **kwargs)
        return call
    return decorate


def install_sqlalchemy(engine):
    """Observe SQL and actual root transaction lifetime, including caller-owned transactions."""
    global _session_observers_installed
    if get_recorder() is None or getattr(engine, "_patchdiff_perf_installed", False):
        return
    engine._patchdiff_perf_installed = True
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    @event.listens_for(engine, "before_cursor_execute")
    def before(connection, cursor, statement, parameters, context, executemany):
        context._patchdiff_perf_start = time.perf_counter_ns()

    @event.listens_for(engine, "after_cursor_execute")
    def after(connection, cursor, statement, parameters, context, executemany):
        now = time.perf_counter_ns()
        recorder = get_recorder()
        if recorder is None:
            return
        recorder.emit("sql", context._patchdiff_perf_start, now - context._patchdiff_perf_start, count=1)
        target_id = context.execution_options.get("patchdiff_perf_target_lock")
        if target_id:
            recorder.emit("lock_wait", context._patchdiff_perf_start, now - context._patchdiff_perf_start, target_id=target_id)
            state = connection.info.get("patchdiff_perf_state")
            if state is not None:
                state["locks"].setdefault(str(target_id), (now, _invocation.get()))

    @event.listens_for(engine, "commit")
    def committing(connection):
        state = connection.info.get("patchdiff_perf_state")
        if state is not None:
            state["commit_start"] = time.perf_counter_ns()

    @event.listens_for(engine.pool, "checkin")
    def checked_in(dbapi_connection, connection_record):
        connection_record.info.pop("patchdiff_perf_state", None)

    if _session_observers_installed:
        return
    _session_observers_installed = True

    @event.listens_for(Session, "after_begin")
    def begun(session, transaction, connection):
        if not getattr(connection.engine, "_patchdiff_perf_installed", False) or transaction.parent is not None:
            return
        state = {"locks": {}, "commit_start": None}
        connection.info["patchdiff_perf_state"] = state
        session.info.setdefault("patchdiff_perf_transactions", []).append(state)

    @event.listens_for(Session, "after_commit")
    def committed(session):
        if not session.in_nested_transaction():
            session.info["patchdiff_perf_committed"] = True

    @event.listens_for(Session, "after_transaction_end")
    def ended(session, transaction):
        if transaction.parent is not None:
            return
        states = session.info.pop("patchdiff_perf_transactions", [])
        successful = session.info.pop("patchdiff_perf_committed", False)
        now = time.perf_counter_ns()
        recorder = get_recorder()
        if recorder is None:
            return
        for state in states:
            if state["commit_start"] is not None:
                recorder.emit("commit", state["commit_start"], now - state["commit_start"], outcome="commit" if successful else "rollback")
            for target_id, (start, invocation) in state["locks"].items():
                recorder.emit("lock_hold", start, now - start, invocation_id=invocation,
                              target_id=target_id, outcome="commit" if successful else "rollback")

def _after_fork():
    global _owner, _owner_pid, _owner_lock, _memory_lock
    if _owner is not None:
        for stream in _owner._streams:
            try:
                stream.close()
            except OSError:
                pass
    _owner, _owner_pid = None, None
    _owner_lock, _memory_lock = threading.Lock(), threading.Lock()
    _invocation.set(None)
    _target.set(None)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)
atexit.register(close_performance_events)
