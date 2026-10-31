"""Live PostgreSQL negative regressions for PR #16 findings B/C/D/F."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from app.mcp import tools  # noqa: F401
from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles, TargetScopeObservations


def initialized():
    target = registry.call("patchdiff_initialize_target", filename="neighbors.py",
                           content="def first():\n    return 'abcd'\n\ndef second():\n    return 'abcd'\n",
                           content_type="text/x-python")
    obs = registry.call("patchdiff_observe_scope", target_file_id=target["target_file_id"], symbol_name="first")
    assert obs["status"] == "observed"
    return target, obs


def submit(target, obs, operations):
    return registry.call("patchdiff_submit_observed_operations", target_file_id=target["target_file_id"],
                         observation_id=obs["observation_id"], expected_target_version=0,
                         expected_current_hash=target["current_hash"], intent="Remediation regression",
                         operations=operations)


@pytest.mark.parametrize("mutation", ["delete", "unlink", "wrong_id", "null_id", "remove_id", "target", "cycle",
                                     "version", "preimage_hash", "bounds", "diagnostic_bounds", "boolean_bounds",
                                     "scope_hash", "both_scope_hashes", "diagnostic_scope_hash"])
def test_observed_replay_rejects_missing_or_tampered_authority(mutation):
    target, obs = initialized()
    accepted = submit(target, obs, [{"op": "match", "match": "abcd", "replace": "ABCD"}])
    assert accepted["status"] == "accepted"
    tid = target["target_file_id"]
    registry.call("patchdiff_save", target_file_id=tid)
    pristine = registry.call("patchdiff_replay", target_file_id=tid)
    assert pristine["status"] == "success" and pristine["materialized_state_matches"] is True
    other, other_obs = initialized()
    with SessionLocal.begin() as session:
        row = session.get(TargetScopeObservations, uuid.UUID(obs["observation_id"]))
        log = session.get(AppendOnlyPdcpLogs, uuid.UUID(accepted["pdcp_log_id"]))
        diagnostic = dict(log.diagnostic_json)
        if mutation == "delete":
            session.delete(row)
        elif mutation == "unlink":
            row.accepted_pdcp_log_id = None
        elif mutation == "wrong_id":
            diagnostic["observation_id"] = other_obs["observation_id"]
        elif mutation == "null_id":
            diagnostic["observation_id"] = None
        elif mutation == "remove_id":
            del diagnostic["observation_id"]
        elif mutation == "target":
            row.target_file_id = uuid.UUID(other["target_file_id"])
        elif mutation == "cycle":
            row.editing_cycle_id = session.get(CloudTargetFiles, uuid.UUID(tid)).active_editing_cycle_id
        elif mutation == "version":
            row.target_version += 1
        elif mutation == "preimage_hash":
            row.target_current_hash = "0" * 64
        elif mutation == "bounds":
            row.scope_end += 1
        elif mutation == "diagnostic_bounds":
            diagnostic["scope_end"] += 1
        elif mutation == "boolean_bounds":
            diagnostic["scope_start"] = False
        elif mutation == "scope_hash":
            row.observed_scope_hash = "0" * 64
        elif mutation == "both_scope_hashes":
            row.observed_scope_hash = diagnostic["observed_scope_hash"] = "0" * 64
        elif mutation == "diagnostic_scope_hash":
            diagnostic["observed_scope_hash"] = "0" * 64
        log.diagnostic_json = diagnostic
        flag_modified(log, "diagnostic_json")
    replay = registry.call("patchdiff_replay", target_file_id=tid)
    assert replay["status"] == "failed"
    assert replay["failure_reason"] == "replay_protocol_invalid"
    assert replay["pdcp_log_id"] == accepted["pdcp_log_id"]
    assert replay["accepted_transactions_replayed"] == 0


def test_database_rejects_duplicate_observation_linkage():
    target, obs = initialized()
    second = registry.call("patchdiff_observe_scope", target_file_id=target["target_file_id"], symbol_name="second")
    accepted = submit(target, obs, [{"op": "match", "match": "abcd", "replace": "ABCD"}])
    with pytest.raises(IntegrityError), SessionLocal.begin() as session:
        row = session.get(TargetScopeObservations, uuid.UUID(second["observation_id"]))
        row.accepted_pdcp_log_id = uuid.UUID(accepted["pdcp_log_id"])
        session.flush()
    replay = registry.call("patchdiff_replay", target_file_id=target["target_file_id"])
    assert replay["status"] == "success" and replay["materialized_state_matches"] is True


@pytest.mark.parametrize("kind", ["start", "end", "missing", "one_guard", "outside_before", "outside_after", "wrong_before", "wrong_after"])
def test_observed_insertion_rejection_is_audited_without_mutation(kind):
    target, obs = initialized()
    tid = target["target_file_id"]
    original = registry.call("patchdiff_export_target", target_file_id=tid)["content"]
    at = original.index("bc")
    guards = {"expected_before": "a", "expected_after": "b"}
    if kind == "start":
        at = obs["scope_start"]
    elif kind == "end":
        at = obs["scope_end"]
    elif kind == "missing":
        guards = {}
    elif kind == "one_guard":
        del guards["expected_after"]
    elif kind == "outside_before":
        guards["expected_before"] = "x" * (at - obs["scope_start"] + 1)
    elif kind == "outside_after":
        guards["expected_after"] = original[at:obs["scope_end"] + 1]
    elif kind == "wrong_before":
        guards["expected_before"] = "d"
    elif kind == "wrong_after":
        guards["expected_after"] = "d"
    result = submit(target, obs, [{"op": "span", "start": at, "end": at,
                                   "expected_text": "", "replace": "!", **guards}])
    assert result["status"] == "rejected"
    assert registry.call("patchdiff_export_target", target_file_id=tid)["content"] == original
    with SessionLocal() as session:
        row = session.get(CloudTargetFiles, uuid.UUID(tid))
        assert row.version == 0 and row.current_hash == target["current_hash"]
        assert session.query(AppendOnlyManifestLedger).filter_by(target_file_id=row.target_file_id).count() == 0
        assert session.query(AppendOnlyPdcpLogs).filter_by(target_file_id=row.target_file_id, status="rejected").count() == 1
        assert session.get(TargetScopeObservations, uuid.UUID(obs["observation_id"])).accepted_pdcp_log_id is None


def test_observed_interior_insertion_accepts_and_replays():
    target, obs = initialized()
    tid = target["target_file_id"]
    original = registry.call("patchdiff_export_target", target_file_id=tid)["content"]
    at = original.index("bc")
    result = submit(target, obs, [{"op": "span", "start": at, "end": at, "expected_text": "",
                                   "replace": "!", "expected_before": "a", "expected_after": "b"}])
    assert result["status"] == "accepted"
    assert registry.call("patchdiff_export_target", target_file_id=tid)["content"] == original[:at] + "!" + original[at:]
    registry.call("patchdiff_save", target_file_id=tid)
    replay = registry.call("patchdiff_replay", target_file_id=tid)
    assert replay["status"] == "success" and replay["materialized_state_matches"] is True


def test_save_invalidates_unconsumed_observation_pages_without_changing_version_or_hash():
    target, obs = initialized()
    tid = target["target_file_id"]
    registry.call("patchdiff_save", target_file_id=tid)
    page = registry.call("patchdiff_observe_scope", target_file_id=tid,
                         observation_id=obs["observation_id"], offset=1, max_chars=5)
    assert page["status"] == "rejected" and page["code"] == "OBSERVATION_CYCLE_MISMATCH"
    assert page["target_version"] == 0 and page["target_current_hash"] == target["current_hash"]
    assert "text" not in page


def test_ambiguous_exact_selection_caps_candidates_and_preserves_total():
    content = "\n".join(f"class Worker{i}:\n    def execute(self):\n        return {i}\n" for i in range(205))
    target = registry.call("patchdiff_initialize_target", filename="many_workers.py", content=content, content_type="text/x-python")
    result = registry.call("patchdiff_observe_scope", target_file_id=target["target_file_id"], symbol_name="execute")
    assert result["status"] == "ambiguous" and result["observation_id"] is None
    assert len(result["candidates"]) == 200
    assert result["total_candidates"] == 205 and result["candidates_truncated"] is True


@pytest.mark.parametrize("edge", ["scope_start", "scope_end"])
def test_json_neighbor_boundary_insertion_cannot_escape_object(edge):
    content = '{"items": [{"id": "first", "value": 1}, {"id": "second", "value": 1}]}\n'
    target = registry.call("patchdiff_initialize_target", filename="neighbors.json", content=content,
                           content_type="application/json")
    tid = target["target_file_id"]
    obs = registry.call("patchdiff_observe_scope", target_file_id=tid, symbol_name="items[first]")
    assert obs["status"] == "observed"
    at = obs[edge]
    result = submit(target, obs, [{"op": "span", "start": at, "end": at, "expected_text": "",
                                   "replace": "!", "expected_before": content[at-1:at],
                                   "expected_after": content[at:at+1]}])
    assert result["status"] == "rejected" and result["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"
    assert registry.call("patchdiff_export_target", target_file_id=tid)["content"] == content
