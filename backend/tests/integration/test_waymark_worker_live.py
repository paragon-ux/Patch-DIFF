"""Resident transport preserves locked transaction ownership and durable recovery."""
import copy
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.services import waymark_worker as worker
from app.services.pdcp_service import submit_observed_operations
from app.storage.db import SessionLocal
from app.storage.models import CloudTargetFiles
from backend.tests.integration.test_observed_batch import initialized, observe, request, state, submit
from app.mcp.server import registry


@pytest.fixture
def resident(monkeypatch):
    worker.close_process_worker_owner()
    owner = worker.WaymarkWorkerOwner(mode="resident")
    monkeypatch.setattr(worker, "_owner", owner)
    try:
        yield owner
    finally:
        owner.close()


def test_recovery_conflict_and_replay_work_with_worker_unavailable(resident):
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    accepted = submit(args)
    assert accepted["status"] == "accepted"
    resident.retire()
    resident.unhealthy = True
    recovered = submit(args)
    assert recovered["deduplicated"] and recovered["pdcp_log_id"] == accepted["pdcp_log_id"]
    conflict = copy.deepcopy(args)
    conflict["intent"] = "A different request with the same key"
    rejected = submit(conflict)
    assert rejected["status"] == "rejected" and rejected["pdcp_log_id"] != accepted["pdcp_log_id"]
    assert len(state(target)[2]) == 2
    assert registry.call("patchdiff_replay", target_file_id=target["target_file_id"])["materialized_state_matches"]
    assert resident.generation is None


def test_service_owned_admission_timeout_releases_lock_without_attempt(resident):
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    resident.retire()
    launches = len(resident.launches)
    with pytest.raises(worker.WaymarkWorkerError, match="QUEUE_TIMEOUT"):
        submit(args)
    content, version, logs, ledger, scopes = state(target)
    assert version == 0 and not logs and not ledger and all(row.accepted_pdcp_log_id is None for row in scopes)
    assert len(resident.launches) == launches and resident.generation is None
    with SessionLocal.begin() as session:
        session.execute(text("SET LOCAL lock_timeout = '100ms'"))
        assert session.scalar(select(CloudTargetFiles).where(
            CloudTargetFiles.target_file_id == uuid.UUID(target["target_file_id"])).with_for_update()) is not None


def test_caller_owned_admission_timeout_preserves_transaction_until_caller_rollback(resident):
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    resident.retire()
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
        with pytest.raises(worker.WaymarkWorkerError, match="QUEUE_TIMEOUT"):
            submit_observed_operations(session, **args)
        assert session.in_transaction()
        with SessionLocal.begin() as contender:
            contender.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError):
                contender.scalar(select(CloudTargetFiles).where(
                    CloudTargetFiles.target_file_id == uuid.UUID(target["target_file_id"])).with_for_update())
        session.rollback()
    assert not state(target)[2]
