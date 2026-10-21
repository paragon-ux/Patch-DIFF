"""Accepted historical inputs retain replay and request-ID outcome recovery."""
import re

import pytest
from sqlalchemy import select

from app.core.failures import FailureReason
from app.core.versions import PREVIOUS_RUNTIME_VERSION, RUNTIME_VERSION
from app.pdcp.typed import canonical_record_json, decode_record
from app.services import pdcp_service
from app.services.replay_service import replay_target
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyPdcpLogs
from backend.tests.integration.helpers import create_target


def test_pre_fix_change_id_history_replays_but_new_submissions_are_strict(monkeypatch):
    target_id = create_target("alpha")
    historical_args = dict(target_file_id=target_id, expected_target_version=0, intent="Historical update", edits=[{"match": "alpha", "replace": "beta", "change_id": "legacy\n"}])
    with SessionLocal() as session:
        # Recreate the pre-fix decoder acceptance under its recorded profile.
        with monkeypatch.context() as legacy:
            legacy.setattr(pdcp_service, "RUNTIME_VERSION", PREVIOUS_RUNTIME_VERSION)
            legacy.setattr(pdcp_service, "parse_typed_record", lambda record: decode_record(canonical_record_json(record), runtime_version=PREVIOUS_RUNTIME_VERSION))
            accepted = pdcp_service.submit_edits(session, **historical_args)
            assert accepted.status == "accepted"
        old_log = session.get(AppendOnlyPdcpLogs, accepted.pdcp_log_id)
        assert old_log.runtime_version == PREVIOUS_RUNTIME_VERSION
        assert '"legacy\\n"' in old_log.pdcp_content
        replay = replay_target(session, target_file_id=target_id)
        assert replay.status == "success" and replay.materialized_state_matches
        rejected = pdcp_service.submit_edits(session, **{**historical_args, "expected_target_version": 1, "edits": [{"match": "beta", "replace": "gamma", "change_id": "legacy\n"}]})
        assert rejected.failure_reason is FailureReason.MANIFEST_INVALID
        new = pdcp_service.submit_edits(session, target_file_id=target_id, expected_target_version=1, intent="Current update", edits=[{"match": "beta", "replace": "gamma", "change_id": "current:1"}])
        assert new.status == "accepted"
        assert session.get(AppendOnlyPdcpLogs, new.pdcp_log_id).runtime_version == RUNTIME_VERSION
        session.commit()
        mixed = replay_target(session, target_file_id=target_id)
        assert mixed.status == "success" and mixed.materialized_state_matches
        assert mixed.reconstructed_content == "gamma" and mixed.reconstructed_version == 2


@pytest.mark.parametrize("first_status", ["accepted", "rejected"])
def test_pre_fix_request_ids_recover_recorded_outcomes_only(monkeypatch, first_status):
    target_id = create_target("alpha")
    legacy_key = "legacy-" + first_status + "\n"
    args = dict(target_file_id=target_id, expected_target_version=0, intent="Legacy request", edits=[{"match": "alpha" if first_status == "accepted" else "absent", "replace": "beta"}], client_request_id=legacy_key)
    with SessionLocal() as session:
        with monkeypatch.context() as legacy:
            legacy.setattr(pdcp_service, "RUNTIME_VERSION", PREVIOUS_RUNTIME_VERSION)
            # Exact old key grammar: dollar can match immediately before final newline.
            legacy.setattr(pdcp_service, "validate_client_request_id", lambda value: value if re.match(r"^[\x21-\x7e]{1,128}$", value) else None)
            original = pdcp_service.submit_edits(session, **args)
        assert original.status == first_status
        recovered = pdcp_service.submit_edits(session, **args)
        assert recovered.deduplicated is True
        assert recovered.pdcp_log_id == original.pdcp_log_id and recovered.status == first_status
        conflict = pdcp_service.submit_edits(session, **{**args, "intent": "Different payload"})
        assert conflict.failure_reason is FailureReason.CONTEXT_INVALID
        logs = session.scalars(select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == target_id)).all()
        assert len(logs) == 2
        keyed = [log for log in logs if log.client_request_id == legacy_key]
        conflicts = [log for log in logs if log.client_request_id is None]
        assert len(keyed) == len(conflicts) == 1
        assert keyed[0].pdcp_log_id == original.pdcp_log_id
        assert conflicts[0].pdcp_log_id == conflict.pdcp_log_id
        assert conflicts[0].diagnostic_json["submitted_client_request_id"] == legacy_key
    another = create_target("alpha")
    with SessionLocal() as session:
        new_invalid = pdcp_service.submit_edits(session, **{**args, "target_file_id": another})
        assert new_invalid.failure_reason is FailureReason.CONTEXT_INVALID
        assert session.get(AppendOnlyPdcpLogs, new_invalid.pdcp_log_id).client_request_id is None
