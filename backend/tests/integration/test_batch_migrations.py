"""Populated live 0004/0005 roundtrips and evidence-preserving downgrade refusal."""
import json
import uuid

import pytest
from alembic import command
from sqlalchemy import MetaData, Table, text
from sqlalchemy.orm import Session

from app.core.hashing import canonical_sha256
from app.services.pdcp_service import submit_observed_operations
from app.services.replay_service import replay_target
from app.services.scope_observation_service import observe_scope
from app.services.target_service import initialize_target
from backend.tests.integration.test_migrations_reachable import isolated_migrations, seed_legacy_history, snapshot, assert_legacy_preserved


def test_populated_historical_observation_upgrade_downgrade_upgrade(isolated_migrations):
    config, connection = isolated_migrations
    command.upgrade(config, "20261026_0004")
    tid = seed_legacy_history(connection)
    log = connection.execute(text("SELECT * FROM append_only_pdcp_logs WHERE status='accepted'")).mappings().one()
    oid = uuid.uuid4()
    scope = Table("target_scope_observations", MetaData(), autoload_with=connection)
    connection.execute(scope.insert().values(observation_id=oid, target_file_id=tid, editing_cycle_id=log["editing_cycle_id"],
        target_version=0, target_current_hash=log["before_hash"], waymark_engine_version="4.1.0", language="text",
        symbol_name="legacy", symbol_kind="variable", start_line=1, end_line=1, start_column=0, end_column=5,
        scope_start=0, scope_end=5, observed_scope_hash=canonical_sha256("alpha"), accepted_pdcp_log_id=log["pdcp_log_id"]))
    diagnostic = json.dumps({"observation_id": str(oid), "scope_start": 0, "scope_end": 5, "observed_scope_hash": canonical_sha256("alpha")})
    connection.execute(text("UPDATE append_only_pdcp_logs SET diagnostic_json=CAST(:d AS jsonb) WHERE status='accepted'"), {"d": diagnostic})
    baseline = snapshot(connection)
    original = connection.scalar(text("SELECT to_jsonb(o) FROM target_scope_observations o"))
    connection.commit()
    command.upgrade(config, "head")
    assert connection.scalar(text("SELECT observation_bundle_id FROM target_scope_observations")) is None
    connection.commit()
    command.downgrade(config, "20261026_0004")
    assert connection.scalar(text("SELECT to_jsonb(o) FROM target_scope_observations o")) == original
    assert_legacy_preserved(connection, baseline)
    connection.commit()
    command.upgrade(config, "head")
    with Session(bind=connection) as session:
        replay = replay_target(session, target_file_id=tid)
        assert replay.status == "success" and replay.materialized_state_matches


@pytest.mark.parametrize("accepted,remove_links", [(False, False), (True, False), (True, True)])
def test_downgrade_refuses_bundle_and_accepted_batch_evidence(isolated_migrations, accepted, remove_links):
    config, connection = isolated_migrations
    command.upgrade(config, "20261027_0005")
    connection.commit()
    with Session(bind=connection) as session:
        target = initialize_target(session, filename="migrate.py", content="def a():\n    return 1\n\ndef b():\n    return 1\n", target_type="text/x-python")
        bundle = observe_scope(session, target_file_id=target.target_file_id, selections=[{"symbol_name": "a"}, {"symbol_name": "b"}])
        assert bundle["status"] == "observed_batch"
        if accepted:
            result = submit_observed_operations(session, target_file_id=target.target_file_id, intent="Update both",
                observation_bundle_id=bundle["observation_bundle_id"], expected_target_version=0,
                expected_current_hash=target.current_hash, client_request_id="migration-batch",
                groups=[{"observation_id": item["observation_id"], "operations": [{"op": "match", "match": "return 1", "replace": "return 2"}]} for item in bundle["scopes"]])
            assert result.status == "accepted"
            assert session.scalar(text("SELECT count(DISTINCT accepted_pdcp_log_id) FROM target_scope_observations")) == 1
    connection.commit()
    if remove_links:
        # Corrupt test-only authority to prove the durable accepted format independently blocks downgrade.
        connection.execute(text("DELETE FROM target_scope_observations"))
        connection.commit()
    before = snapshot(connection)
    rows = connection.scalar(text("SELECT count(*) FROM target_scope_observations"))
    connection.commit()
    with pytest.raises(Exception, match="Cannot downgrade 20261027_0005: bundled observations or accepted batch evidence exist"):
        command.downgrade(config, "20261026_0004")
    connection.rollback()
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261027_0005"
    assert connection.scalar(text("SELECT count(*) FROM target_scope_observations")) == rows
    assert snapshot(connection) == before
