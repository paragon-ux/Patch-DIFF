"""Adversarial stress harness for Challenger M3-2.

Challenges:
1. Migration 0007 downgrade/upgrade, schema validation, and nullable constraint.
2. Finalization materialized_state_checks parity and DB JSONB persistence.
3. Legacy pre-0007 records with NULL materialized_state_checks.
4. Lock contention simulation: lock_wait_ms vs lock_hold_ms separation.
5. Accurate lock_hold_ms and lock_wait_ms recording on all rollback branches.
"""

from __future__ import annotations

import threading
import time
import uuid
import pytest
from alembic import command
from alembic.config import Config
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from sqlalchemy import create_engine, event, text, select, func

from app.core.failures import FailureReason
from app.services.finalize_service import finalize_target
from app.services.pdcp_service import submit_edits
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal, engine
from app.storage.models import CloudTargetFiles, TargetFinalizations, TargetSnapshots, EditingCycles
from app.storage.repositories import select_target_for_update

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "app" / "migrations"
DISPOSABLE_DB_PREFIX = "patchdiff_test_disposable_"


def assert_disposable_migration_db(db_url: str) -> str:
    """Guard against running destructive migration downgrades or table deletes on a shared database (PR23-R4I-TEST-001)."""
    parsed = urlparse(db_url)
    dbname = (parsed.path or "").lstrip("/")
    if not dbname.startswith(DISPOSABLE_DB_PREFIX):
        raise RuntimeError(
            f"Refusing to run destructive migration downgrade/delete on non-disposable database {dbname!r}; "
            f"expected database name starting with {DISPOSABLE_DB_PREFIX!r}."
        )
    return dbname


def _build_db_url_with_name(base_url: str, dbname: str) -> str:
    parsed = urlparse(base_url)
    return urlunparse((parsed.scheme, parsed.netloc, f"/{dbname}", parsed.params, parsed.query, parsed.fragment))


def get_alembic_config(db_url: str | None = None) -> Config:
    cfg = Config(str(MIGRATIONS_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if db_url is not None:
        cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_adversarial_migration_0007_schema_and_reversibility(monkeypatch: pytest.MonkeyPatch):
    """Adversarially challenge migration 0007 in an isolated disposable database without touching shared state (PR23-R4I-TEST-001)."""
    from app.core.config import resolve_database_url
    base_url = resolve_database_url(role="patchdiff_bootstrap")

    # 0. Guard must refuse to operate on the shared database
    with pytest.raises(RuntimeError, match="Refusing to run destructive migration"):
        assert_disposable_migration_db(_build_db_url_with_name(base_url, "patchdiff"))

    disposable_db = f"{DISPOSABLE_DB_PREFIX}m3_2_{uuid.uuid4().hex[:8]}"
    disposable_url = _build_db_url_with_name(base_url, disposable_db)
    assert_disposable_migration_db(disposable_url)

    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    disposable_engine = None
    try:
        with admin_engine.connect() as admin_conn:
            admin_conn.execute(text(f'CREATE DATABASE "{disposable_db}"'))

        monkeypatch.setenv("PATCHDIFF_DATABASE_URL", disposable_url)
        cfg = get_alembic_config(disposable_url)
        disposable_engine = create_engine(disposable_url)

        # Upgrade fresh disposable database to head (20261031_0007)
        command.upgrade(cfg, "head")

        # 1. Downgrade to 20261031_0006 in isolated disposable DB
        command.downgrade(cfg, "20261031_0006")

        with disposable_engine.connect() as conn:
            cols = conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'target_finalizations' AND column_name = 'materialized_state_checks';
            """)).fetchall()
            assert len(cols) == 0, "Column must be completely dropped after downgrade to 0006"

        # 2. Upgrade back to head (20261031_0007)
        command.upgrade(cfg, "head")

        with disposable_engine.connect() as conn:
            cols = conn.execute(text("""
                SELECT column_name, data_type, is_nullable, udt_name
                FROM information_schema.columns
                WHERE table_name = 'target_finalizations' AND column_name = 'materialized_state_checks';
            """)).fetchall()
            assert len(cols) == 1, "Column must exist after upgrade to 0007"
            col_name, data_type, is_nullable, udt_name = cols[0]
            assert col_name == "materialized_state_checks"
            assert data_type == "USER-DEFINED" or udt_name == "jsonb", f"Expected jsonb, got {data_type} / {udt_name}"
            assert is_nullable == "YES", f"Expected nullable=YES, got {is_nullable}"
    finally:
        if disposable_engine is not None:
            disposable_engine.dispose()
        with admin_engine.connect() as admin_conn:
            admin_conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :dname AND pid <> pg_backend_pid()"
                ),
                {"dname": disposable_db},
            )
            admin_conn.execute(text(f'DROP DATABASE IF EXISTS "{disposable_db}"'))
        admin_engine.dispose()


def test_adversarial_finalization_checks_persistence_and_idempotent_parity():
    """Verify live finalization persists JSONB checks and idempotent retry returns 100% parity."""
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="adversarial_checks.txt",
            content="Alpha Bravo Charlie\nDelta Echo Foxtrot\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash

    client_request_id = f"adv-checks-{uuid.uuid4()}"

    # Initial finalization
    with SessionLocal() as session:
        res1 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )

    assert res1.status == "ok"
    assert res1.is_idempotent_replay is False
    assert res1.materialized_state_matches is True
    assert isinstance(res1.materialized_state_checks, dict)
    assert res1.materialized_state_checks["content_matches"] is True
    assert res1.materialized_state_checks["stored_hash_matches"] is True
    assert res1.materialized_state_checks["recomputed_hash_matches"] is True
    assert res1.materialized_state_checks["version_matches"] is True

    # Assert raw database row in PostgreSQL has identical JSONB
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT materialized_state_checks FROM target_finalizations WHERE client_request_id = :cid"),
            {"cid": client_request_id},
        ).fetchone()
        assert row is not None
        db_checks = row[0]
        assert db_checks == res1.materialized_state_checks

    # Advance target version by editing
    with SessionLocal() as session:
        edit_res = submit_edits(
            session,
            target_file_id=target_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            intent="Mutate target after finalization",
            edits=[{"match": "Alpha", "replace": "Omega"}],
        )
        assert edit_res.status == "accepted"

    # Idempotent retry with original arguments
    with SessionLocal() as session:
        res2 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )

    assert res2.status == "ok"
    assert res2.is_idempotent_replay is True
    assert res2.materialized_state_matches is True
    assert res2.materialized_state_checks == res1.materialized_state_checks
    assert res2.finalization_id == res1.finalization_id
    assert res2.content_sha256 == res1.content_sha256
    assert res2.exported_content == res1.exported_content
    assert res2.version == res1.version


def test_adversarial_legacy_records_null_checks_handling():
    """Verify clean handling when historical finalization records have NULL materialized_state_checks."""
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="legacy_checks.txt",
            content="Legacy Content Line 1\nLine 2\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash

    client_request_id = f"adv-legacy-{uuid.uuid4()}"

    with SessionLocal() as session:
        res1 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )
    assert res1.status == "ok"

    # Simulate historical pre-0007 record by forcibly setting materialized_state_checks to NULL in DB
    from app.storage.db import create_bootstrap_engine
    maintenance = create_bootstrap_engine()
    with maintenance.begin() as conn:
        conn.execute(
            text("UPDATE target_finalizations SET materialized_state_checks = NULL WHERE client_request_id = :cid"),
            {"cid": client_request_id},
        )

    maintenance.dispose()

    # Now execute idempotent retry
    with SessionLocal() as session:
        res_legacy = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )

    assert res_legacy.status == "ok"
    assert res_legacy.is_idempotent_replay is True
    assert res_legacy.materialized_state_matches is True
    assert res_legacy.materialized_state_checks is None  # Cleanly returns None without failure!
    assert res_legacy.finalization_id == res1.finalization_id
    assert res_legacy.exported_content == res1.exported_content


def test_adversarial_lock_contention_wait_vs_hold_separation():
    """Prove actual PostgreSQL blocking with barriers; record timings without load gates."""
    with SessionLocal() as session:
        init = initialize_target(session, filename="contention_test.txt",
                                 content="Contention Target\nLine 2\n", target_type="text/plain")
    acquired = threading.Event()
    release = threading.Event()
    attempting = threading.Event()
    state = {}
    errors = []
    competitor_name = "pr23-contending-finalizer"

    def holder():
        try:
            with SessionLocal() as session:
                session.execute(select_target_for_update(init.target_file_id)).scalar_one()
                acquired.set()
                if not release.wait(30):
                    raise TimeoutError("Finalizer never reached the blocked row lock")
                session.rollback()
        except BaseException as exc:
            errors.append(exc)
            acquired.set()

    def before_lock(conn, _cursor, statement, _parameters, _context, _many):
        if (threading.current_thread().name == competitor_name
                and "cloud_target_files" in statement and "FOR UPDATE" in statement):
            state["pid"] = conn.connection.driver_connection.info.backend_pid
            attempting.set()

    def after_lock(_conn, _cursor, statement, _parameters, _context, _many):
        if (threading.current_thread().name == competitor_name
                and "cloud_target_files" in statement and "FOR UPDATE" in statement):
            state["acquired_after_release"] = release.is_set()

    def competitor():
        try:
            if not acquired.wait(30):
                raise TimeoutError("Holder did not acquire the target lock")
            with SessionLocal() as session:
                state["result"] = finalize_target(
                    session, target_file_id=init.target_file_id,
                    client_request_id=f"fin-contend-{uuid.uuid4()}",
                    expected_target_version=init.version, expected_current_hash=init.current_hash,
                    format="canonical_lf")
        except BaseException as exc:
            errors.append(exc)

    event.listen(engine, "before_cursor_execute", before_lock)
    event.listen(engine, "after_cursor_execute", after_lock)
    threads = [threading.Thread(target=holder),
               threading.Thread(target=competitor, name=competitor_name)]
    for thread in threads:
        thread.start()
    try:
        assert attempting.wait(30), errors
        deadline = time.monotonic() + 20
        blocked = False
        while time.monotonic() < deadline:
            with SessionLocal() as session:
                blocked = bool(session.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"),
                                               {"pid": state["pid"]}).scalar_one())
            if blocked:
                break
            time.sleep(0.01)
        assert blocked, "PostgreSQL never reported the finalizer blocked on the holder"
    finally:
        release.set()
        for thread in threads:
            thread.join(30)
        event.remove(engine, "before_cursor_execute", before_lock)
        event.remove(engine, "after_cursor_execute", after_lock)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors, errors
    assert state["acquired_after_release"] is True
    result = state["result"]
    assert result.status == "ok"
    assert result.lock_wait_ms >= 0 and result.lock_hold_ms >= 0
    print(f"\n[Empirical Timing] lock_wait_ms={result.lock_wait_ms:.2f}ms, "
          f"lock_hold_ms={result.lock_hold_ms:.2f}ms")


def test_adversarial_rollback_branches_record_accurate_hold_time():
    """Verify that all rollback branches accurately record lock_hold_ms and lock_wait_ms."""
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="rollback_timing.txt",
            content="Rollback Line 1\nLine 2\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash

    # Branch 1: Version mismatch
    with SessionLocal() as session:
        res_v = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"rb-v-{uuid.uuid4()}",
            expected_target_version=99999,  # Mismatch
            format="canonical_lf",
        )
    assert res_v.status == "rejected"
    assert res_v.failure_reason == FailureReason.TARGET_VERSION_MISMATCH
    assert res_v.lock_wait_ms is not None and res_v.lock_wait_ms >= 0
    assert res_v.lock_hold_ms is not None and res_v.lock_hold_ms > 0

    # Branch 2: Hash mismatch
    with SessionLocal() as session:
        res_h = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"rb-h-{uuid.uuid4()}",
            expected_target_version=v0,
            expected_current_hash="f" * 64,  # Mismatch
            format="canonical_lf",
        )
    assert res_h.status == "rejected"
    assert res_h.failure_reason == FailureReason.TARGET_HASH_MISMATCH
    assert res_h.lock_wait_ms is not None and res_h.lock_wait_ms >= 0
    assert res_h.lock_hold_ms is not None and res_h.lock_hold_ms > 0

    # Branch 3: Target not found
    with SessionLocal() as session:
        res_not_found = finalize_target(
            session,
            target_file_id=uuid.uuid4(),  # Non-existent
            client_request_id=f"rb-nf-{uuid.uuid4()}",
            expected_target_version=0,
            format="canonical_lf",
        )
    assert res_not_found.status == "rejected"
    assert res_not_found.failure_reason == FailureReason.TARGET_NOT_FOUND
    assert res_not_found.lock_wait_ms is not None and res_not_found.lock_wait_ms >= 0
    assert res_not_found.lock_hold_ms is not None and res_not_found.lock_hold_ms >= 0

    # Branch 4: Request key conflict
    cid = f"rb-conflict-{uuid.uuid4()}"
    with SessionLocal() as session:
        res_first = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=cid,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )
        assert res_first.status == "ok"

    with SessionLocal() as session:
        res_conflict = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=cid,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="crlf",  # Differing format!
        )
    assert res_conflict.status == "rejected"
    assert res_conflict.failure_code == "request_key_conflict"
    assert res_conflict.lock_wait_ms is not None and res_conflict.lock_wait_ms >= 0
    assert res_conflict.lock_hold_ms is not None and res_conflict.lock_hold_ms > 0

    # Branch 5: Replay hash divergence
    with SessionLocal() as session:
        init_corrupt = initialize_target(
            session,
            filename="corrupt_replay.txt",
            content="Corrupt Replay Test\n",
            target_type="text/plain",
        )
        corrupt_id = init_corrupt.target_file_id

    # Corrupt target hash
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE cloud_target_files SET current_hash = :fake WHERE target_file_id = :tid"),
            {"fake": "0" * 64, "tid": corrupt_id},
        )

    with SessionLocal() as session:
        res_replay_fail = finalize_target(
            session,
            target_file_id=corrupt_id,
            client_request_id=f"rb-replay-{uuid.uuid4()}",
            expected_current_hash="0" * 64,
            format="canonical_lf",
        )
    assert res_replay_fail.status == "rejected"
    assert res_replay_fail.failure_reason == FailureReason.REPLAY_HASH_MISMATCH
    assert res_replay_fail.lock_wait_ms is not None and res_replay_fail.lock_wait_ms >= 0
    assert res_replay_fail.lock_hold_ms is not None and res_replay_fail.lock_hold_ms > 0

    # Branch 6: Export unrecoverable EOL failure
    with SessionLocal() as session:
        init_eol = initialize_target(
            session,
            filename="mixed_eol_rb.txt",
            content="Line 1\r\nLine 2\n",
            target_type="text/plain",
        )
        eol_id = init_eol.target_file_id

    with SessionLocal() as session:
        res_eol_fail = finalize_target(
            session,
            target_file_id=eol_id,
            client_request_id=f"rb-eol-{uuid.uuid4()}",
            expected_target_version=0,
            format="original_eol",
        )
    assert res_eol_fail.status == "invalid_argument"
    assert res_eol_fail.failure_code == "original_eol_unrecoverable"
    assert res_eol_fail.lock_wait_ms is not None and res_eol_fail.lock_wait_ms >= 0
    assert res_eol_fail.lock_hold_ms is not None and res_eol_fail.lock_hold_ms > 0


def test_adversarial_preflight_rejections_no_lock_acquisition():
    """Verify preflight argument rejections fail fast without acquiring row locks or touching DB transactions."""
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="preflight_test.txt",
            content="Preflight Test Content\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id

    # 1. Bad UUID
    with SessionLocal() as session:
        res = finalize_target(
            session,
            target_file_id="not-a-uuid",
            client_request_id="req-123",
            expected_target_version=0,
        )
    assert res.status == "rejected"
    assert res.failure_reason == FailureReason.CONTEXT_INVALID
    assert res.lock_wait_ms is None
    assert res.lock_hold_ms is None
    assert session.in_transaction() is False

    # 2. Bad client_request_id
    with SessionLocal() as session:
        res = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id="bad id with spaces",
            expected_target_version=0,
        )
    assert res.status == "rejected"
    assert res.failure_reason == FailureReason.CONTEXT_INVALID
    assert res.lock_wait_ms is None
    assert res.lock_hold_ms is None
    assert session.in_transaction() is False

    # 3. Missing guards
    with SessionLocal() as session:
        res = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id="req-valid-1",
            expected_target_version=None,
            expected_current_hash=None,
        )
    assert res.status == "rejected"
    assert res.failure_reason == FailureReason.CONTEXT_INVALID
    assert res.lock_wait_ms is None
    assert res.lock_hold_ms is None
    assert session.in_transaction() is False

    # 4. Bad format
    with SessionLocal() as session:
        res = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id="req-valid-2",
            expected_target_version=0,
            format="invalid_format_xyz",
        )
    assert res.status == "rejected"
    assert res.failure_reason == FailureReason.CONTEXT_INVALID
    assert res.lock_wait_ms is None
    assert res.lock_hold_ms is None
    assert session.in_transaction() is False


def test_adversarial_concurrent_identical_finalization_race():
    """Verify that racing threads calling finalize_target with identical client_request_id serialize safely.
    
    One thread completes initial finalization; the competitor safely recovers the cached receipt
    via keyed idempotency, yielding 100% check parity and 0 duplicate snapshots/cycles.
    """
    with SessionLocal() as session:
        init = initialize_target(
            session,
            filename="concurrent_race.txt",
            content="Line A\nLine B\n",
            target_type="text/plain",
        )
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash

    client_request_id = f"race-{uuid.uuid4()}"
    barrier = threading.Barrier(2)
    results = [None, None]

    def runner(idx: int):
        barrier.wait()  # Synchronize threads to hit finalize simultaneously
        with SessionLocal() as session:
            res = finalize_target(
                session,
                target_file_id=target_id,
                client_request_id=client_request_id,
                expected_target_version=v0,
                expected_current_hash=h0,
                format="canonical_lf",
            )
            results[idx] = res

    t0 = threading.Thread(target=runner, args=(0,))
    t1 = threading.Thread(target=runner, args=(1,))

    t0.start()
    t1.start()
    t0.join()
    t1.join()

    r0, r1 = results
    assert r0 is not None and r1 is not None
    assert r0.status == "ok"
    assert r1.status == "ok"

    # Exactly one is initial finalization, exactly one is idempotent replay
    replays = [r0.is_idempotent_replay, r1.is_idempotent_replay]
    assert False in replays
    assert True in replays

    # Both return identical finalization_id and identical materialized_state_checks
    assert r0.finalization_id == r1.finalization_id
    assert r0.materialized_state_checks == r1.materialized_state_checks
    assert r0.materialized_state_matches is True
    assert r1.materialized_state_matches is True
    assert r0.exported_content == r1.exported_content
    assert r0.snapshot_id == r1.snapshot_id

    # The competitor had to wait for the first thread to commit: assert lock_wait_ms > 0
    replay_result = r0 if r0.is_idempotent_replay else r1
    assert replay_result.lock_wait_ms is not None and replay_result.lock_wait_ms > 0
    assert replay_result.lock_hold_ms is not None and replay_result.lock_hold_ms > 0

    # Ensure no duplicates in DB
    with SessionLocal() as session:
        snapshots_count = session.execute(
            select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == target_id)
        ).scalar()
        cycles_count = session.execute(
            select(func.count()).select_from(EditingCycles).where(EditingCycles.target_file_id == target_id)
        ).scalar()
        finalizations_count = session.execute(
            select(func.count()).select_from(TargetFinalizations).where(
                TargetFinalizations.target_file_id == target_id,
                TargetFinalizations.client_request_id == client_request_id,
            )
        ).scalar()
        assert snapshots_count == 2
        assert cycles_count == 2
        assert finalizations_count == 1

