"""Instrumentation observes actual PostgreSQL lock lifetime without owning its transaction."""
import json
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import performance_events as perf
from app.storage.repositories import select_target_for_update
from backend.tests.integration.helpers import create_target


def test_telemetry_preserves_caller_owned_postgres_transaction_and_content_privacy(tmp_path, monkeypatch):
    marker = "private-performance-canary-content"
    target_id = create_target(marker)
    recorder = perf.PerformanceRecorder(tmp_path / "events.jsonl")
    monkeypatch.setattr(perf, "get_recorder", lambda: recorder)
    engine = create_engine(settings.database_url)
    perf.install_sqlalchemy(engine)
    try:
        with Session(engine) as session:
            with session.begin():
                with perf.span("rpc", target_id=target_id):
                    target = session.execute(select_target_for_update(target_id)).scalar_one()
                    assert target.current_content == marker
                assert session.in_transaction()
                time.sleep(0.02)
        recorder.close()
        raw = recorder.path.read_text(encoding="ascii")
        rows = [json.loads(line) for line in raw.splitlines()]
        held = next(row for row in rows if row["event"] == "lock_hold")
        assert held["duration_ns"] >= 20_000_000 and held["outcome"] == "commit"
        assert marker not in raw and "SELECT" not in raw
        status = json.loads(next(tmp_path.glob("*.status-*.json")).read_text())
        assert status["valid"]
    finally:
        recorder.close()
        engine.dispose()
