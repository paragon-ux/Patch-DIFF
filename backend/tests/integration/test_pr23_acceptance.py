"""Frozen OPEN-finding acceptance: migration safety, replay cost and bounded bytes."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import time
import tracemalloc
import uuid

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from alembic import command

from app.core.config import resolve_database_url
from app.services.export_service import read_finalized_export
from app.services.finalize_service import finalize_target
from app.services.pdcp_service import submit_edits
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal, get_engine
from app.storage.models import TargetFinalizationExportChunks


@pytest.fixture(scope="module")
def isolated_acceptance_database():
    """Keep large fixtures out of later tests' whole-database snapshots."""
    from app.storage import db
    from backend.tests.integration.test_adversarial_m3_2 import (
        _build_db_url_with_name, assert_disposable_migration_db, get_alembic_config,
    )
    name = "patchdiff_test_disposable_acceptance_" + uuid.uuid4().hex
    urls = {role: _build_db_url_with_name(resolve_database_url(role="patchdiff_" + role), name)
            for role in ("bootstrap", "host", "agent")}
    assert_disposable_migration_db(urls["bootstrap"])
    admin = create_engine(resolve_database_url(role="patchdiff_bootstrap"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        with pytest.MonkeyPatch.context() as patch:
            for role, url in urls.items():
                patch.setenv(f"PATCHDIFF_{role.upper()}_DATABASE_URL", url)
            config = get_alembic_config(urls["bootstrap"])
            config.attributes["database_url"] = urls["bootstrap"]
            command.upgrade(config, "head")
            yield
    finally:
        for key, engine in list(db._ENGINES_BY_KEY.items()):
            if engine.url.database == name:
                engine.dispose()
                db._ENGINES_BY_KEY.pop(key)
                db._SESSIONMAKERS_BY_KEY.pop(key, None)
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@pytest.mark.parametrize("size_mib", [10, 100])
def test_complete_large_export_has_bounded_payload_queries_and_page_memory(size_mib, isolated_acceptance_database):
    raw = ("€🌟\r\n" * ((size_mib * 1024 * 1024) // 9)).encode()
    expected_hash = hashlib.sha256(raw).hexdigest()
    with SessionLocal() as session:
        initial = initialize_target(session, filename=f"{size_mib}MiB.txt",content=raw.decode(),target_type="text/plain")
        final = finalize_target(session,target_file_id=initial.target_file_id,expected_target_version=0,
                                client_request_id=str(uuid.uuid4()),format="crlf")
    assert final.status == "ok" and final.content_sha256 == expected_hash
    total_bytes = len(raw)
    del raw
    statements=[]
    engine=get_engine()
    def trace(_conn,_cursor,statement,parameters,_context,_many):
        statements.append(statement)
    event.listen(engine,"before_cursor_execute",trace)
    digest=hashlib.sha256()
    offset=0
    peak=0
    try:
        while offset < total_bytes:
            tracemalloc.start()
            with SessionLocal() as session:
                page=read_finalized_export(session,final.finalization_id,initial.target_file_id,offset,1048576)
            _,page_peak=tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak=max(peak,page_peak)
            assert page["status"] == "ok",page
            block=base64.b64decode(page["content_base64"],validate=True)
            digest.update(block)
            assert len(block) <= 1048576
            offset += len(block)
    finally:
        event.remove(engine,"before_cursor_execute",trace)
        if tracemalloc.is_tracing():tracemalloc.stop()
    assert offset == total_bytes and digest.hexdigest() == expected_hash
    assert peak <= 8*1024*1024, peak
    assert not any("target_snapshots" in statement for statement in statements)
    assert sum("count(" in statement.lower() for statement in statements) == 1
    # Every payload read is a primary-key bounded range, with at most five rows.
    payload_queries=[s for s in statements if "target_finalization_export_chunks.payload" in s]
    assert len(payload_queries) == (total_bytes+1048575)//1048576
    assert all("chunk_index >=" in s and "chunk_index <=" in s for s in payload_queries)


@pytest.mark.parametrize("history_length", [25, 250, 2500])
def test_uncontended_history_replay_queries_are_outside_target_lock(history_length, isolated_acceptance_database, tmp_path):
    import app.services.finalize_service as module
    with SessionLocal() as session:
        initial=initialize_target(session,filename="history.txt",content="a",target_type="text/plain")
        for version in range(history_length):
            accepted=submit_edits(session,target_file_id=initial.target_file_id,
                expected_target_version=version,intent="Preserve replay history",edits=[dict(match="a",replace="a")])
            assert accepted.status == "accepted"
    phases=[]
    locked=False
    engine=get_engine()
    def trace(_conn,_cursor,statement,_parameters,_context,_many):
        nonlocal locked
        if "cloud_target_files" in statement and "FOR UPDATE" in statement:
            locked=True
        if "append_only_pdcp_logs.pdcp_content" in statement:
            phases.append("locked" if locked else "read_snapshot")
    samples=[]
    event.listen(engine,"before_cursor_execute",trace)
    try:
        for _ in range(3):
            phases.clear()
            locked=False
            with SessionLocal() as session:
                final=finalize_target(session,target_file_id=initial.target_file_id,
                    expected_target_version=history_length,client_request_id=str(uuid.uuid4()),format="canonical_lf")
            assert final.status == "ok"
            assert phases and set(phases) == {"read_snapshot"}, phases
            assert locked and final.lock_hold_ms >= 0
            samples.append(dict(lock_hold_ms=final.lock_hold_ms,
                                lock_wait_ms=final.lock_wait_ms,replay_ms=final.replay_ms))
    finally:event.remove(engine,"before_cursor_execute",trace)
    # Measured distributions are evidence, never a wall-clock gate.
    evidence=Path(os.environ.get("PATCHDIFF_TEST_EVIDENCE_DIR",str(tmp_path)))
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/f"lock-timing-{history_length}.json").write_text(
        json.dumps(dict(history_length=history_length,samples=samples),indent=2))


def test_0008_fresh_database_backfill_replay_and_unsafe_downgrade_refusal(monkeypatch):
    from backend.tests.integration.test_adversarial_m3_2 import (
        _build_db_url_with_name, assert_disposable_migration_db, get_alembic_config,
    )
    from backend.tests.integration.test_migrations_reachable import seed_legacy_history
    from app.services.replay_service import replay_target
    base=resolve_database_url(role="patchdiff_bootstrap")
    name="patchdiff_test_disposable_pr23_"+uuid.uuid4().hex
    url=_build_db_url_with_name(base,name)
    assert_disposable_migration_db(url)
    admin=create_engine(base,isolation_level="AUTOCOMMIT")
    disposable=None
    try:
        with admin.connect() as conn:conn.execute(text(f'CREATE DATABASE "{name}"'))
        config=get_alembic_config(url)
        config.attributes["database_url"]=url
        monkeypatch.setenv("PATCHDIFF_DATABASE_URL",url)
        command.upgrade(config,"20261031_0007")
        disposable=create_engine(url)
        with disposable.connect() as conn:
            target_id=seed_legacy_history(conn)
        command.upgrade(config,"head")
        with disposable.connect() as conn:
            assert conn.execute(text("SELECT history_revision FROM cloud_target_files WHERE target_file_id=:id"),dict(id=target_id)).scalar_one()==1
        with Session(disposable) as session:
            replay=replay_target(session,target_file_id=target_id)
            assert replay.status=="success" and replay.materialized_state_matches
        # Clean roundtrip preserves the populated legacy history/revision.
        command.downgrade(config,"20261031_0007")
        command.upgrade(config,"head")
        with Session(disposable) as session:
            final=finalize_target(session,target_file_id=target_id,expected_target_version=1,
                client_request_id=str(uuid.uuid4()),format="canonical_lf")
            assert final.status=="ok"
        with pytest.raises(Exception,match="finalized export chunks exist"):
            command.downgrade(config,"20261031_0007")
        with disposable.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()=="20261101_0008"
    finally:
        if disposable is not None:disposable.dispose()
        with admin.connect() as conn:conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()
