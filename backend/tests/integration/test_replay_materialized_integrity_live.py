"""Raw stored-content health is distinct from successful history reconstruction."""

import pytest
from sqlalchemy import select, update

from app.core.hashing import canonical_sha256
from app.services.pdcp_service import submit_edits
from app.services.replay_service import replay_target
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles,
    CurrentPdcpFiles, EditingCycles, TargetSnapshots,
)
from backend.tests.integration.helpers import create_target

BASELINE = "A\nb"
COMPONENTS = (
    "content_matches", "stored_hash_matches", "recomputed_hash_matches", "version_matches",
)
CASES = [
    ("healthy", {}, (True, True, True, True)),
    ("crlf", {"current_content": "A\r\nb"}, (False, True, True, True)),
    ("bare_cr", {"current_content": "A\rb"}, (False, True, True, True)),
    ("unicode", {"current_content": "A\nβ😀"}, (False, True, False, True)),
    ("hash_only", {"current_hash": "0" * 64}, (True, False, True, True)),
    ("version_only", {"version": 7}, (True, True, True, False)),
]


def stored_target_rows(session, target_id):
    """Read complete rows without ORM identity-cache comparisons masking changes."""
    return tuple(
        (model.__tablename__, tuple(tuple(row) for row in session.execute(
            select(model.__table__).where(model.target_file_id == target_id).order_by(
                *model.__table__.primary_key.columns)
        )))
        for model in (
            CloudTargetFiles, AppendOnlyPdcpLogs, AppendOnlyManifestLedger,
            CurrentPdcpFiles, EditingCycles, TargetSnapshots,
        )
    )


@pytest.mark.parametrize("name,corruption,expected", CASES, ids=[case[0] for case in CASES])
def test_replay_checks_raw_materialized_storage_without_repair(name, corruption, expected):
    target_id = create_target("a\nb")
    with SessionLocal() as session:
        accepted = submit_edits(
            session, target_file_id=target_id, expected_target_version=0,
            intent="Establish replay baseline", edits=[{"match": "a", "replace": "A"}],
            client_request_id="baseline-edit")
        assert accepted.status == "accepted"
    with SessionLocal() as observer:
        baseline_rows = stored_target_rows(observer, target_id)
        assert all(len(rows) == 1 for _, rows in baseline_rows)
        baseline = observer.get(CloudTargetFiles, target_id)
        assert (baseline.current_content, baseline.current_hash, baseline.version) == (
            BASELINE, canonical_sha256(BASELINE), 1)

    with SessionLocal() as owner:
        owner.begin()
        if corruption:
            owner.execute(update(CloudTargetFiles).where(
                CloudTargetFiles.target_file_id == target_id).values(**corruption))
        owner.flush()
        before = stored_target_rows(owner, target_id)
        result = replay_target(owner, target_file_id=target_id)
        assert result.status == "success"
        assert result.failure_reason is None
        assert result.reconstructed_content == BASELINE
        assert result.reconstructed_hash == canonical_sha256(BASELINE)
        assert result.reconstructed_version == 1
        assert result.accepted_transactions_replayed == 1
        assert result.materialized_state_checks == dict(zip(COMPONENTS, expected))
        assert result.materialized_state_matches is all(expected)
        assert result.current_hash == corruption.get("current_hash", canonical_sha256(BASELINE))
        assert result.current_version == corruption.get("version", 1)
        assert owner.in_transaction()
        assert stored_target_rows(owner, target_id) == before
        owner.rollback()

    # The intentionally corrupt transaction was never committed or repaired by replay.
    with SessionLocal() as observer:
        assert stored_target_rows(observer, target_id) == baseline_rows
        healthy = replay_target(observer, target_file_id=target_id)
        assert healthy.status == "success" and healthy.materialized_state_matches
        assert healthy.materialized_state_checks == {component: True for component in COMPONENTS}
        assert healthy.reconstructed_content == BASELINE and healthy.current_version == 1
        assert stored_target_rows(observer, target_id) == baseline_rows
