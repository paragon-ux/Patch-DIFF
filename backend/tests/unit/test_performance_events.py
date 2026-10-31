"""Telemetry bounds/privacy and real SQLAlchemy transaction-lifetime observation."""
import json
import os
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services import performance_events as perf


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    recorder = perf.PerformanceRecorder(tmp_path / "events.jsonl")
    monkeypatch.setattr(perf, "get_recorder", lambda: recorder)
    yield recorder
    recorder.close()


def rows(recorder):
    recorder.close()
    return [json.loads(line) for line in recorder.path.read_text(encoding="ascii").splitlines()]


def test_disabled_and_writer_failure_do_not_change_results(tmp_path, monkeypatch):
    monkeypatch.setattr(perf, "get_recorder", lambda: None)
    assert perf.timed("rpc")(lambda: {"status": "accepted"})() == {"status": "accepted"}
    recorder = perf.PerformanceRecorder(tmp_path)  # A directory cannot be the output file.
    monkeypatch.setattr(perf, "get_recorder", lambda: recorder)
    assert perf.timed("rpc")(lambda: 17)() == 17
    recorder.close()
    assert recorder.error == "writer_failed"


def test_nested_spans_correlate_without_logging_arguments(recorded):
    secret = 'private-target-content-and-client-key'
    target = str(uuid.uuid4())
    with perf.span("rpc", target_id=target):
        with perf.span("applier"):
            assert secret
    data = rows(recorded)
    assert len(data) == 2 and len({row["invocation_id"] for row in data}) == 1
    assert all(row["target_id"] == target for row in data)
    assert secret not in recorded.path.read_text()
    assert all(row["duration_ns"] >= 0 and len(json.dumps(row).encode("ascii")) < 2048 for row in data)
    status = json.loads(next(recorded.path.parent.glob("*.status-*.json")).read_text())
    assert status["valid"] and status["written"] == 2


def test_overflow_invalidates_evidence_without_blocking_or_changing_exception(recorded):
    recorded._stop.set()
    recorded._thread.join(timeout=2)
    recorded.queue = __import__('queue').Queue(maxsize=1)
    recorded.emit("rpc", 1, 2)
    recorded.emit("rpc", 1, 2)
    assert recorded.dropped == 1
    with pytest.raises(ValueError, match="original failure"):
        with perf.span("rpc"):
            raise ValueError("original failure")
    recorded.close()
    status = json.loads(next(recorded.path.parent.glob("*.status-*.json")).read_text())
    assert not status["valid"]


def test_root_caller_transaction_controls_lock_hold_and_commit_timing(recorded):
    engine = create_engine("sqlite://")
    perf.install_sqlalchemy(engine)
    target = str(uuid.uuid4())
    with Session(engine) as session:
        with session.begin():
            with perf.span("rpc", target_id=target):
                session.execute(text("SELECT 1").execution_options(patchdiff_perf_target_lock=target))
            # The service/RPC scope has ended; its caller still holds the root transaction.
            time.sleep(0.01)
    data = rows(recorded)
    lock = next(row for row in data if row["event"] == "lock_hold")
    assert lock["duration_ns"] >= 10_000_000 and lock["outcome"] == "commit"
    assert any(row["event"] == "commit" for row in data)
    assert all("SELECT" not in json.dumps(row) for row in data)
    engine.dispose()


def test_rollback_is_not_reported_as_commit(recorded):
    engine = create_engine("sqlite://")
    perf.install_sqlalchemy(engine)
    with Session(engine) as session:
        session.execute(text("SELECT 1").execution_options(patchdiff_perf_target_lock=str(uuid.uuid4())))
        session.rollback()
    data = rows(recorded)
    assert next(row for row in data if row["event"] == "lock_hold")["outcome"] == "rollback"
    engine.dispose()


def test_bridge_events_preserve_child_clock_identity_and_reject_unbounded_input(recorded, tmp_path):
    bridge = tmp_path / "bridge.jsonl"
    bridge.write_text(json.dumps({"event": "bridge_import", "start_ns": "123", "duration_ns": "42",
                                  "pid": 12345, "invocation_id": str(uuid.uuid4())}) + "\n", encoding="ascii")
    perf.collect_bridge_events(bridge)
    bridge.write_bytes(b"x" * 65537)
    perf.collect_bridge_events(bridge)
    data = rows(recorded)
    assert data[0]["pid"] == 12345 and data[0]["start_ns"] == 123
    assert recorded.dropped == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows ctypes resource monitor")
def test_repeated_rss_sampling_reuses_its_ctypes_pointer_type():
    import ctypes
    assert perf.process_memory(os.getpid())[0] > 0
    before = len(ctypes._pointer_type_cache)
    for _ in range(100):
        assert perf.process_memory(os.getpid())[0] > 0
    assert len(ctypes._pointer_type_cache) == before


def test_recorder_loss_after_engine_configuration_does_not_change_sql(recorded, monkeypatch):
    engine = create_engine("sqlite://")
    perf.install_sqlalchemy(engine)
    monkeypatch.setattr(perf, "get_recorder", lambda: None)
    with Session(engine) as session:
        assert session.execute(text("SELECT 1").execution_options(patchdiff_perf_target_lock=str(uuid.uuid4()))).scalar_one() == 1
        session.commit()
    engine.dispose()


def test_memory_sampling_can_be_disabled_without_losing_timing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATCHDIFF_PERF_MEMORY", "0")
    monkeypatch.setattr(perf, "process_memory", lambda pid: pytest.fail("Diagnostic RSS sampling disabled"))
    recorder = perf.PerformanceRecorder(tmp_path / "events.jsonl")
    monkeypatch.setattr(perf, "get_recorder", lambda: recorder)
    recorder.children.add(12345)
    assert perf.timed("rpc")(lambda: 17)() == 17
    assert [row["event"] for row in rows(recorder)] == ["rpc"]
    status = json.loads(next(tmp_path.glob("*.status-*.json")).read_text())
    assert status["valid"] and status["memory_sampling_enabled"] is False
    assert not list(tmp_path.glob("*.memory.jsonl"))


@pytest.mark.parametrize("value", ["", "true", "2"])
def test_invalid_memory_setting_invalidates_only_telemetry(tmp_path, monkeypatch, value):
    monkeypatch.setenv("PATCHDIFF_PERF_MEMORY", value)
    recorder = perf.PerformanceRecorder(tmp_path / "events.jsonl")
    monkeypatch.setattr(perf, "get_recorder", lambda: recorder)
    assert perf.timed("rpc")(lambda: "accepted")() == "accepted"
    recorder.close()
    status = json.loads(next(tmp_path.glob("*.status-*.json")).read_text())
    assert not status["valid"] and status["error"] == "invalid_memory_configuration"
