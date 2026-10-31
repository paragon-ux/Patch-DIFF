"""Real Node lifecycle, parity and deliberately broken private transports."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app.services import waymark_worker as worker
from app.services.waymark_adapter import discover_symbols_from_content, WAYMARK_DISCOVER_SCRIPT


@pytest.fixture
def resident(monkeypatch):
    worker.close_process_worker_owner()
    owner = worker.WaymarkWorkerOwner(mode="resident")
    monkeypatch.setattr(worker, "_owner", owner)
    try:
        yield owner
    finally:
        owner.close()


@pytest.mark.parametrize("filename,content,filters", [
    ("a.py", 'class A:\n    def f(self):\n        return "🌟"\n', {}),
    ("a.py", "ONE = 1\nTWO = 2\n", {"query": "tw", "kind": "variable"}),
    ("a.json", '{"items": [{"name": "🌟"}], "x/y": {"a": 1}}', {"kind": "object"}),
    ("a.md", "# Heading\n\n| A | B |\n|---|---|\n| x | y |\n", {}),
    ("a.json", "{broken", {}),
    ("a.txt", "unsupported\n", {}),
])
def test_shared_evaluator_has_exact_domain_parity(resident, filename, content, filters):
    resident_result = discover_symbols_from_content(filename=filename, content=content, **filters)
    oneshot_result = discover_symbols_from_content(filename=filename, content=content,
                                                   discover_script=WAYMARK_DISCOVER_SCRIPT, **filters)
    assert resident_result.to_dict() == oneshot_result.to_dict()


def test_same_pid_fresh_source_unicode_filters_and_clean_shutdown(resident):
    first = discover_symbols_from_content(filename="same.py", content="ONE = 1\n")
    pid = resident.generation.proc.pid
    second = discover_symbols_from_content(filename="same.py", content="TWO = '🌟'\n")
    assert first.symbols[0].name == "ONE" and second.symbols[0].name == "TWO"
    assert resident.generation.proc.pid == pid and resident.generation.completed == 2
    root = resident.root
    process = resident.generation.proc
    assert list(resident.generation.root.glob("request-*")) == []
    resident.close()
    assert process.poll() is not None and not root.exists()


def test_transport_has_no_eight_mib_source_cutoff(resident):
    content = "x" * (8 * 1024 * 1024 + 1)
    result = discover_symbols_from_content(filename="large.txt", content=content)
    legacy = discover_symbols_from_content(filename="large.txt", content=content, discover_script=WAYMARK_DISCOVER_SCRIPT)
    # Waymark's existing admission is unchanged; the new control transport imposed no cutoff.
    assert result.error.code == legacy.error.code == "FILE_TOO_LARGE"
    assert resident.generation.completed == 1


def test_locked_submission_does_not_start_child_and_has_short_deadline(resident, monkeypatch):
    elapsed, waits = [0.0], []
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: elapsed[0]))
    def wait(timeout):
        waits.append(timeout)
        elapsed[0] += timeout
    monkeypatch.setattr(resident.condition, "wait", wait)
    with pytest.raises(worker.WaymarkWorkerError, match="WAYMARK_WORKER_QUEUE_TIMEOUT"):
        discover_symbols_from_content(filename="a.py", content="X=1", _locked_submission=True)
    assert sum(waits) == pytest.approx(.250)
    assert all(0 < interval <= .05 for interval in waits)
    assert resident.generation is None and not resident.launches and not resident.waiting


def test_fifo_expired_tickets_queue_full_and_cancel(resident, monkeypatch):
    monkeypatch.setattr(resident, "_ready", lambda: True)
    entered = []
    release = threading.Event()
    def queued(number, locked=False, cancel=None):
        try:
            with resident.permit(locked=locked, cancel=cancel):
                entered.append(number)
        except worker.WaymarkWorkerError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=10) as pool:
        with resident.permit():
            futures = []
            for number in range(8):
                futures.append(pool.submit(queued, number, number == 0))
                deadline = time.monotonic() + 1
                while len(resident.waiting) != number + 1 and time.monotonic() < deadline:
                    time.sleep(.001)
            assert queued(99) == "WAYMARK_WORKER_QUEUE_FULL"
            assert futures[0].result(timeout=1) == "WAYMARK_WORKER_QUEUE_TIMEOUT"
        assert all(future.result(timeout=2) is None for future in futures[1:])
    assert entered == list(range(1, 8)) and not resident.waiting
    release.set()
    assert queued(100, cancel=release) == "WAYMARK_WORKER_CANCELLED"


def fake_script(tmp_path, behavior):
    script = tmp_path / "fake.mjs"
    script.write_text('''import fs from 'node:fs';
function exact(n) { const b=Buffer.alloc(n); let o=0; while(o<n) { const c=fs.readSync(0,b,o,n-o); if(!c)process.exit(); o+=c; } return b; }
function read() { return JSON.parse(exact(exact(4).readUInt32BE()).toString('utf8')); }
function send(m) { const b=Buffer.from(JSON.stringify(m)); const h=Buffer.alloc(4);h.writeUInt32BE(b.length);fs.writeSync(1,Buffer.concat([h,b])); }
const hello=read();
send({protocol:hello.protocol,type:'ready',generation:hello.generation,id:'0',engine_version:'4.1.0',bridge_sha256:hello.bridge_sha256,worker_pid:process.pid});
const request=read();
''' + behavior, encoding="utf-8")
    return script


@pytest.mark.parametrize("behavior", [
    "send({...request,type:'result',generation:'00000000-0000-0000-0000-000000000000',result:{},result_bytes:3});",
    "fs.writeSync(1,Buffer.from([0,32,16,1]));setInterval(()=>{},1000);",
    "fs.writeSync(1,Buffer.from([0,0,0,2,255,255]));setInterval(()=>{},1000);",
    "fs.writeSync(1,Buffer.alloc(65537,65));setInterval(()=>{},1000);",
    "fs.writeSync(2,Buffer.alloc(65537,65));setInterval(()=>{},1000);",
    "fs.writeSync(1,Buffer.from([0,0,0,15,123]));process.exit();",
])
def test_protocol_faults_retire_generation_without_retry(resident, tmp_path, behavior):
    resident.script = fake_script(tmp_path, behavior)
    with pytest.raises(worker.WaymarkWorkerError, match="WAYMARK_WORKER_PROTOCOL_ERROR"):
        discover_symbols_from_content(filename="a.py", content="X=1\n")
    assert resident.generation is None and len(resident.launches) == 1


def test_active_timeout_preserves_domain_code_and_never_retries(resident, tmp_path):
    resident.script = fake_script(tmp_path, "setInterval(()=>{},1000);")
    start = time.monotonic()
    result = discover_symbols_from_content(filename="a.py", content="X=1\n", timeout_seconds=.1)
    assert result.error.code == "WAYMARK_TIMEOUT" and resident.generation is None
    assert time.monotonic() - start < 1.5 and len(resident.launches) == 1


def test_startup_timeout_is_infrastructure_and_output_cap_retains_domain_code(resident, tmp_path, monkeypatch):
    resident.script = tmp_path / "stalled.mjs"
    resident.script.write_text("setInterval(()=>{},1000);", encoding="utf-8")
    monkeypatch.setattr(worker, "STARTUP_TIMEOUT", .1)
    start = time.monotonic()
    with pytest.raises(worker.WaymarkWorkerError, match="STARTUP_FAILED"):
        discover_symbols_from_content(filename="a.py", content="X=1")
    assert time.monotonic() - start < 1.5 and resident.generation is None
    monkeypatch.setattr(worker, "STARTUP_TIMEOUT", 7)
    resident.script = fake_script(tmp_path,
        "send({protocol:request.protocol,type:'result',generation:request.generation,id:request.id,result:null,result_bytes:2097153});setInterval(()=>{},1000);")
    result = discover_symbols_from_content(filename="a.py", content="X=1")
    assert result.error.code == "WAYMARK_OUTPUT_TOO_LARGE" and resident.generation is None


def test_oversized_readiness_length_is_rejected_before_reading_body(resident, tmp_path):
    resident.script = tmp_path / "oversized-ready.mjs"
    resident.script.write_text("import fs from 'node:fs';fs.writeSync(1,Buffer.from([0,0,16,1]));setInterval(()=>{},1000);", encoding="utf-8")
    start = time.monotonic()
    with pytest.raises(worker.WaymarkWorkerError, match="PROTOCOL_ERROR"):
        discover_symbols_from_content(filename="a.py", content="X=1")
    assert time.monotonic() - start < 1.5


def test_pin_mismatch_and_invalid_engine_result_use_shared_decoder(resident, tmp_path):
    resident.script = fake_script(tmp_path, "setInterval(()=>{},1000);")
    resident.script.write_text(resident.script.read_text().replace("engine_version:'4.1.0'", "engine_version:'0.0.0'"))
    result = discover_symbols_from_content(filename="a.py", content="X=1")
    assert result.error.code == "WAYMARK_VERSION_MISMATCH" and resident.generation is None
    resident.script = fake_script(tmp_path,
        "const result={ok:true,waymark_engine_version:'4.1.0',symbols:'bad'};send({protocol:request.protocol,type:'result',generation:request.generation,id:request.id,result,result_bytes:Buffer.byteLength(JSON.stringify(result))+1});setInterval(()=>{},1000);")
    result = discover_symbols_from_content(filename="a.py", content="X=1")
    assert result.error.code == "WAYMARK_INVALID_OUTPUT"


def test_sampled_rss_limit_is_an_infrastructure_failure(resident, monkeypatch):
    monkeypatch.setattr(worker, "process_memory", lambda pid: (worker.RSS_LIMIT + 1, worker.RSS_LIMIT + 1))
    with pytest.raises(worker.WaymarkWorkerError, match="RSS_LIMIT"):
        discover_symbols_from_content(filename="a.py", content="X=1")
    assert resident.generation is None


def test_cancellation_interrupts_active_child_and_cleans_root(resident, tmp_path):
    resident.script = fake_script(tmp_path, "setInterval(()=>{},1000);")
    cancellation = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(discover_symbols_from_content, filename="a.py", content="X=1\n",
                             _cancel_event=cancellation)
        deadline = time.monotonic() + 3
        while (resident.generation is None or not resident.generation.ready) and time.monotonic() < deadline:
            time.sleep(.01)
        cancellation.set()
        with pytest.raises(worker.WaymarkWorkerError, match="CANCELLED"):
            future.result(timeout=3)
    assert resident.generation is None and not list(resident.root.glob("generation-*"))


def test_restart_budget_and_normal_retirement(resident, monkeypatch):
    monkeypatch.setattr(worker, "MAX_REQUESTS", 1)
    pids = []
    for _ in range(3):
        assert discover_symbols_from_content(filename="a.py", content="X=1").ok
        pids.append(resident.generation.proc.pid)
    assert len(set(pids)) == 3
    with pytest.raises(worker.WaymarkWorkerError, match="RESTART_LIMIT"):
        discover_symbols_from_content(filename="a.py", content="X=1")


def test_cleanup_failure_is_operational_and_owner_is_unhealthy(resident, monkeypatch):
    assert discover_symbols_from_content(filename="a.py", content="X=1").ok
    original = worker._remove_owned
    monkeypatch.setattr(worker, "_remove_owned", lambda *a, **k: False)
    with pytest.raises(worker.WaymarkWorkerError, match="UNHEALTHY"):
        discover_symbols_from_content(filename="a.py", content="X=1")
    with pytest.raises(worker.WaymarkWorkerError, match="UNHEALTHY"):
        discover_symbols_from_content(filename="a.py", content="X=1")
    monkeypatch.setattr(worker, "_remove_owned", original)


def test_nested_lifetimes_and_unknown_configuration(monkeypatch):
    worker.close_process_worker_owner()
    monkeypatch.setenv("PATCHDIFF_WAYMARK_MODE", "oneshot")
    with worker.serving_worker_owner() as first:
        with worker.serving_worker_owner() as second:
            assert first is second and first.references == 2 and first.generation is None
        assert not first.closed
    assert first.closed
    monkeypatch.setenv("PATCHDIFF_WAYMARK_MODE", "bogus")
    with pytest.raises(ValueError, match="Unknown PATCHDIFF_WAYMARK_MODE"):
        worker.get_process_worker_owner()


def test_abrupt_parent_exit_kills_child_and_next_start_removes_only_its_root(tmp_path):
    program = '''import json, time
from app.services.waymark_worker import WaymarkWorkerOwner
owner=WaymarkWorkerOwner(mode='resident')
owner.prewarm()
print(json.dumps({'pid':owner.generation.proc.pid,'root':str(owner.root)}),flush=True)
time.sleep(30)
'''
    process = subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])})
    try:
        identity = json.loads(process.stdout.readline())
        child_identity = worker._process_identity(identity["pid"])
        process.kill()
        process.wait(timeout=3)
        deadline = time.monotonic() + 3
        while worker._process_identity(identity["pid"]) == child_identity and time.monotonic() < deadline:
            time.sleep(.02)
        assert worker._process_identity(identity["pid"]) != child_identity
        assert Path(identity["root"]).exists()
        worker._clean_stale_roots()
        assert not Path(identity["root"]).exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        process.stdout.close()
        process.stderr.close()


@pytest.mark.parametrize("failure", [None, "cancel", "timeout", "pipe"])
def test_ipc_trace_encloses_polling_and_records_only_terminal_outcome(tmp_path, monkeypatch, failure):
    import queue
    import uuid
    from app.services import performance_events as perf
    monkeypatch.setenv("PATCHDIFF_PERF_MEMORY", "0")
    recorder = perf.PerformanceRecorder(tmp_path / "events.jsonl")
    monkeypatch.setattr(perf, "get_recorder", lambda: recorder)
    polls = []
    class Frames:
        def empty(self): return True
        def get(self, timeout):
            polls.append(timeout)
            if len(polls) == 1: raise queue.Empty
            return {"result": "ready"}
    def write(data):
        if failure == "pipe": raise BrokenPipeError("closed")
        return len(data)
    generation = object.__new__(worker._Generation)
    generation.id, generation.lock = str(uuid.uuid4()), threading.Lock()
    generation.error, generation.expected, generation.frames = None, None, Frames()
    generation.owner = SimpleNamespace(closed=False)
    generation.proc = SimpleNamespace(stdin=SimpleNamespace(write=write))
    cancel = threading.Event()
    if failure == "cancel": cancel.set()
    try:
        if failure:
            with pytest.raises((worker.WaymarkWorkerError, subprocess.TimeoutExpired)):
                generation.exchange("discover", "1", {}, 0 if failure == "timeout" else 1, "result", cancel)
        else:
            assert generation.exchange("discover", "1", {}, 1, "result") == {"result": "ready"}
            assert len(polls) == 2
    finally:
        recorder.close()
    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    reads = [event for event in events if event["event"] == "ipc_read"]
    assert len(reads) == 1 and reads[0]["outcome"] == ("error" if failure else "ok")


def test_exchange_queued_frame_does_not_win_over_pipe_write_error():
    """Regression test: queued frame arriving during polling must not mask a failed pipe write."""
    import uuid
    from types import SimpleNamespace
    from app.services import waymark_worker as worker

    class Frames:
        def empty(self):
            return True

        def get(self, timeout):
            return {"result": "stale_or_premature_frame"}

    def broken_write(data):
        raise BrokenPipeError("Pipe broke during write")

    generation = object.__new__(worker._Generation)
    generation.id, generation.lock = str(uuid.uuid4()), threading.Lock()
    generation.error, generation.expected, generation.frames = None, None, Frames()
    generation.owner = SimpleNamespace(closed=False)
    generation.proc = SimpleNamespace(stdin=SimpleNamespace(write=broken_write))

    with pytest.raises(worker.WaymarkWorkerError) as exc_info:
        generation.exchange("discover", "1", {}, 1, "result")
    assert "Worker pipe write failed." in str(exc_info.value)


def test_exchange_writer_catches_value_error_on_closed_stream():
    """Regression test: ValueError from writing to a closed stream must be caught as a bounded worker error."""
    import uuid
    from types import SimpleNamespace
    from app.services import waymark_worker as worker

    class Frames:
        def empty(self):
            return True

        def get(self, timeout):
            raise queue.Empty()

    def closed_stream_write(data):
        raise ValueError("I/O operation on closed file")

    generation = object.__new__(worker._Generation)
    generation.id, generation.lock = str(uuid.uuid4()), threading.Lock()
    generation.error, generation.expected, generation.frames = None, None, Frames()
    generation.owner = SimpleNamespace(closed=False)
    generation.proc = SimpleNamespace(stdin=SimpleNamespace(write=closed_stream_write))

    with pytest.raises(worker.WaymarkWorkerError) as exc_info:
        generation.exchange("discover", "1", {}, 0.5, "result")
    assert "Worker pipe write failed." in str(exc_info.value)

