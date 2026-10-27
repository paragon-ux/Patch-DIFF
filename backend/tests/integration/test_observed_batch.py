"""Live PostgreSQL bundle admission, atomicity, authority and replay regressions."""
import copy
import json
import threading
import uuid

import pytest
from sqlalchemy import select

from app.core.hashing import canonical_sha256
from app.mcp import tools  # noqa: F401
from app.mcp.server import registry
from app.pdcp.typed import canonical_record_json
from app.services import scope_observation_service as observations
from app.services.pdcp_service import submit_observed_operations
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles, TargetScopeObservations


def initialized(count=2, body="    return 'abcd'", prefix=""):
    content = prefix + "\n\n".join(f"def f{i}():\n{body}" for i in range(count)) + "\n"
    target = registry.call("patchdiff_initialize_target", filename="batch.py", content=content, content_type="text/x-python")
    return target, [{"symbol_name": f"f{i}", "kind": "function"} for i in range(count)]


def observe(target, selectors, **options):
    return registry.call("patchdiff_observe_scope", target_file_id=target["target_file_id"], selections=selectors, **options)


def request(target, bundle):
    return dict(target_file_id=target["target_file_id"], observation_bundle_id=bundle["observation_bundle_id"],
                expected_target_version=0, expected_current_hash=target["current_hash"], intent="Update selected functions",
                client_request_id=str(uuid.uuid4()), groups=[{"observation_id": scope["observation_id"], "operations": [
                    {"op": "match", "match": "abcd", "replace": "ABCDE", "rationale": f"Update group {index}"},
                    {"op": "match", "match": "BCD", "replace": "🌟", "occurrence_index": 1}]} for index, scope in enumerate(bundle["scopes"])])


def submit(args):
    return registry.call("patchdiff_submit_observed_operations", **args)


def state(target):
    tid = uuid.UUID(target["target_file_id"])
    with SessionLocal() as session:
        row = session.get(CloudTargetFiles, tid)
        logs = session.scalars(select(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == tid)).all()
        ledger = session.scalars(select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.target_file_id == tid)).all()
        scopes = session.scalars(select(TargetScopeObservations).where(TargetScopeObservations.target_file_id == tid)).all()
        return row.current_content, row.version, logs, ledger, scopes


@pytest.mark.parametrize("count", [2, 5, 20, 32])
def test_bundle_one_discovery_per_snapshot_and_one_atomic_commit(count, monkeypatch):
    target, selectors = initialized(count, prefix="# 🌟 non-BMP prefix\n")
    discover = observations.discover_symbols_from_content
    calls = []
    def track(**kwargs):
        calls.append(kwargs["content"])
        return discover(**kwargs)
    monkeypatch.setattr(observations, "discover_symbols_from_content", track)
    bundle = observe(target, selectors)
    assert bundle["status"] == "observed_batch" and len(bundle["scopes"]) == count
    assert len(calls) == 1
    args = request(target, bundle)
    accepted = submit(args)
    assert accepted["status"] == "accepted", accepted
    assert len(calls) == 2  # one further discovery under the target lock for ALL groups
    content, version, logs, ledger, scopes = state(target)
    assert version == 1 and len(logs) == 1 and len(ledger) == count * 2
    assert len({scope.accepted_pdcp_log_id for scope in scopes}) == 1
    assert content.count("return 'A🌟E'") == count
    assert [fact.derived_json["group_index"] for fact in sorted(ledger, key=lambda fact: fact.change_index)] == [i for i in range(count) for _ in range(2)]
    assert accepted["before_version"] == 0 and accepted["after_version"] == 1
    recovered = submit(args)
    assert recovered["pdcp_log_id"] == accepted["pdcp_log_id"] and recovered["deduplicated"]
    assert recovered["groups"] == accepted["groups"] and len(calls) == 2
    history = registry.call("patchdiff_get_manifest_ledger", target_file_id=target["target_file_id"], limit=200)
    assert history["entries"][0]["transaction_intent"] == args["intent"]
    assert history["entries"][0]["rationale"] == "Update group 0"
    registry.call("patchdiff_save", target_file_id=target["target_file_id"])
    monkeypatch.setattr(observations, "discover_symbols_from_content", lambda **kw: pytest.fail("Replay invoked Waymark"))
    replay = registry.call("patchdiff_replay", target_file_id=target["target_file_id"])
    assert replay["status"] == "success" and replay["materialized_state_matches"]
    assert registry.call("patchdiff_export_target", target_file_id=target["target_file_id"])["content"] == content


@pytest.mark.parametrize("case,code", [("missing", "BUNDLE_SELECTION_NOT_FOUND"), ("duplicate", "BUNDLE_SCOPE_DUPLICATE"),
    ("empty", "INVALID_BATCH_REQUEST"), ("many", "BATCH_LIMIT_EXCEEDED"), ("mixed", "INVALID_BATCH_REQUEST"),
    ("substring", "BUNDLE_SELECTION_NOT_FOUND"), ("extra", "INVALID_BATCH_REQUEST")])
def test_bundle_selection_failures_never_persist_partial_rows(case, code):
    target, selectors = initialized()
    options = {}
    if case == "missing": selectors[-1]["symbol_name"] = "absent"
    if case == "duplicate": selectors[-1] = selectors[0]
    if case == "empty": selectors = []
    if case == "many": selectors *= 17
    if case == "mixed": options["symbol_name"] = "f0"
    if case == "substring": selectors[-1]["symbol_name"] = "f"
    if case == "extra": selectors[-1]["parent"] = "x"
    result = observe(target, selectors, **options)
    assert result["code"] == code
    assert not state(target)[-1]


@pytest.mark.parametrize("size,count,code", [(7000, 9, "BUNDLE_RESPONSE_TOO_LARGE"), (24000, 3, "BATCH_LIMIT_EXCEEDED")])
def test_bundle_response_and_total_selection_limits(size, count, code):
    target, selectors = initialized(count, body="    value = '" + "x" * size + "'\n    return value")
    result = observe(target, selectors)
    assert result["code"] == code, result
    assert not state(target)[-1]


def test_bundle_scope_pagination_and_nonempty_subset():
    target, selectors = initialized(2, body="    value = '" + "x" * 9000 + "'\n    return 'abcd'")
    bundle = observe(target, selectors)
    first = bundle["scopes"][0]
    assert first["truncated"] and first["next_offset"] == 4000
    page = registry.call("patchdiff_observe_scope", target_file_id=target["target_file_id"],
                         observation_id=first["observation_id"], offset=first["next_offset"])
    assert page["status"] == "observed" and page["offset"] == 4000
    args = request(target, bundle)
    args["groups"] = args["groups"][:1]
    assert submit(args)["status"] == "accepted"
    rows = state(target)[-1]
    assert sum(row.accepted_pdcp_log_id is None for row in rows) == 1
    args["client_request_id"] = str(uuid.uuid4())
    args["groups"] = [{"observation_id": bundle["scopes"][1]["observation_id"],
                       "operations": [{"op": "match", "match": "abcd", "replace": "z"}]}]
    assert submit(args)["code"] == "BUNDLE_VERSION_MISMATCH"


@pytest.mark.parametrize("case,code", [("last", "BATCH_OPERATION_REJECTED"), ("outside", "BATCH_OPERATION_OUTSIDE_SCOPE"),
    ("duplicate", "BATCH_GROUP_INVALID"), ("unknown", "BATCH_GROUP_INVALID"), ("foreign", "BATCH_GROUP_INVALID"),
    ("bundle", "BUNDLE_NOT_FOUND"), ("missing_key", "INVALID_BATCH_REQUEST"), ("mixed", "INVALID_BATCH_REQUEST"),
    ("operations", "BATCH_LIMIT_EXCEEDED")])
def test_batch_rejection_audits_once_and_consumes_nothing(case, code):
    target, selectors = initialized()
    bundle = observe(target, selectors)
    args = request(target, bundle)
    if case == "last": args["groups"][-1]["operations"][0]["match"] = "not in scope"
    if case == "outside": args["groups"][-1]["operations"] = [{"op": "span", "start": 0, "end": 1000, "expected_text": "", "replace": "x"}]
    if case == "duplicate": args["groups"][-1]["observation_id"] = args["groups"][0]["observation_id"]
    if case == "unknown": args["groups"][-1]["observation_id"] = str(uuid.uuid4())
    if case == "foreign":
        other, other_selectors = initialized()
        args["groups"][-1]["observation_id"] = observe(other, other_selectors)["scopes"][0]["observation_id"]
    if case == "bundle": args["observation_bundle_id"] = str(uuid.uuid4())
    if case == "missing_key": args.pop("client_request_id")
    if case == "mixed": args["operations"] = args["groups"][0]["operations"]
    if case == "operations": args["groups"][0]["operations"] *= 65
    before = state(target)[0]
    result = submit(args)
    assert result["status"] == "rejected" and result["code"] == code, result
    content, version, logs, ledger, scopes = state(target)
    assert content == before and version == 0 and not ledger
    assert [log.status for log in logs] == ["rejected"]
    assert all(row.accepted_pdcp_log_id is None for row in scopes)
    assert "def f0" not in json.dumps(result.get("diagnostic", {}))


@pytest.mark.parametrize("field", ["groups", "observation_bundle_id", "intent", "expected_target_version"])
def test_batch_key_conflicts_are_audited_and_never_reapply(field):
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    assert submit(args)["status"] == "accepted"
    changed = copy.deepcopy(args)
    if field == "groups": changed[field].reverse()
    if field == "observation_bundle_id": changed[field] = str(uuid.uuid4())
    if field == "intent": changed[field] += " changed"
    if field == "expected_target_version": changed[field] = 1
    conflict = submit(changed)
    assert conflict["code"] == "request_key_conflict"
    assert state(target)[1] == 1 and len(state(target)[2]) == 2


@pytest.mark.parametrize("mutation", ["unlink", "delete", "target", "cycle", "version", "preimage", "bounds", "scope_hash",
    "bundle", "ordinal", "extra", "record_hash", "operations", "order", "missing_evidence", "boolean_bounds", "runtime",
    "unknown_runtime", "duplicate_group", "missing_group", "group_order"])
def test_batch_replay_fails_closed_on_corrupted_authority(mutation, monkeypatch):
    target, selectors = initialized(3)
    bundle = observe(target, selectors)
    args = request(target, bundle)
    args["groups"] = args["groups"][:2]
    accepted = submit(args)
    assert accepted["status"] == "accepted"
    before = state(target)[:2]
    other, _ = initialized()
    registry.call("patchdiff_save", target_file_id=target["target_file_id"])
    with SessionLocal.begin() as session:
        row = session.get(TargetScopeObservations, uuid.UUID(bundle["scopes"][0]["observation_id"]))
        log = session.get(AppendOnlyPdcpLogs, uuid.UUID(accepted["pdcp_log_id"]))
        record = json.loads(log.pdcp_content)
        if mutation == "unlink": row.accepted_pdcp_log_id = None
        if mutation == "delete": session.delete(row)
        if mutation == "target": row.target_file_id = uuid.UUID(other["target_file_id"])
        if mutation == "cycle": row.editing_cycle_id = session.get(CloudTargetFiles, uuid.UUID(target["target_file_id"])).active_editing_cycle_id
        if mutation == "version": row.target_version += 1
        if mutation == "preimage": row.target_current_hash = "0" * 64
        if mutation == "bounds": row.scope_end += 1
        if mutation == "scope_hash": row.observed_scope_hash = "0" * 64
        if mutation == "bundle": row.observation_bundle_id = uuid.uuid4()
        if mutation == "ordinal": row.bundle_ordinal = 31
        if mutation == "extra": session.get(TargetScopeObservations, uuid.UUID(bundle["scopes"][2]["observation_id"])).accepted_pdcp_log_id = log.pdcp_log_id
        if mutation == "record_hash": log.pdcp_content_hash = "0" * 64
        if mutation == "operations": record["groups"][1]["operations"][0]["replace"] = "WRONG"
        if mutation == "order": record["scope_evidence"].reverse()
        if mutation == "missing_evidence": record.pop("scope_evidence")
        if mutation == "boolean_bounds": record["scope_evidence"][0]["scope_start"] = False
        if mutation == "runtime": log.runtime_version = "patchdiff-mvp-0.5.0"
        if mutation == "unknown_runtime": log.runtime_version = "batch-unknown"
        if mutation == "duplicate_group": record["groups"][-1]["observation_id"] = record["groups"][0]["observation_id"]
        if mutation == "missing_group": record["groups"].pop()
        if mutation == "group_order":
            record["groups"].reverse()
            record["scope_evidence"].reverse()
            for index, evidence in enumerate(record["scope_evidence"]): evidence["group_index"] = index
        if mutation in {"operations", "order", "missing_evidence", "boolean_bounds", "duplicate_group", "missing_group", "group_order"}:
            log.pdcp_content = canonical_record_json(record)
            log.pdcp_content_hash = canonical_sha256(log.pdcp_content)
    monkeypatch.setattr(observations, "discover_symbols_from_content", lambda **kw: pytest.fail("Replay invoked Waymark"))
    replay = registry.call("patchdiff_replay", target_file_id=target["target_file_id"])
    assert replay["status"] == "failed" and replay["code"] == "BATCH_REPLAY_INTEGRITY_FAILURE", replay
    assert state(target)[:2] == before


def test_batch_concurrent_writer_waits_then_rejects_stale_snapshot():
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    locked, release = threading.Event(), threading.Event()
    result, errors = {}, []
    def first():
        try:
            with SessionLocal() as session:
                result["first"] = submit_observed_operations(session, **args,
                    _before_final_guard=lambda target: (locked.set(), release.wait(15)))
        except BaseException as exc: errors.append(exc)
    thread = threading.Thread(target=first)
    thread.start()
    assert locked.wait(10)
    second_started = threading.Event()
    def second():
        try:
            second_started.set()
            result["second"] = submit({**args, "client_request_id": str(uuid.uuid4())})
        except BaseException as exc: errors.append(exc)
    waiter = threading.Thread(target=second)
    waiter.start()
    assert second_started.wait(5)
    # Observe the actual blocked backend rather than inferring contention from thread timing.
    import time
    from sqlalchemy import text
    blocked = False
    try:
        for _ in range(100):
            with SessionLocal() as session:
                blocked = bool(session.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%cloud_target_files%FOR UPDATE%')")))
            if blocked: break
            time.sleep(.02)
        assert blocked
    finally:
        release.set()
        thread.join(20)
        waiter.join(20)
    assert not errors and not thread.is_alive() and not waiter.is_alive()
    assert result["first"].status == "accepted" and result["second"]["code"] == "BUNDLE_VERSION_MISMATCH"
    assert state(target)[1] == 1 and [r.status for r in sorted(state(target)[2], key=lambda row: row.log_sequence)] == ["accepted", "rejected"]


@pytest.mark.parametrize("case,code", [("adjacent", None), ("overlap", "BUNDLE_SCOPE_OVERLAP"),
    ("nested", "BUNDLE_SCOPE_OVERLAP"), ("ambiguous", "BUNDLE_SELECTION_AMBIGUOUS"),
    ("duplicate_bounds", "BUNDLE_SCOPE_DUPLICATE"), ("empty", "INVALID_BATCH_REQUEST")])
def test_exact_selection_geometry_and_ambiguity(case, code, monkeypatch):
    from app.services.waymark_adapter import WaymarkDiscoveryResult, WaymarkSymbol, WaymarkPosition
    target = registry.call("patchdiff_initialize_target", filename="geometry.py", content="abcdefghij", content_type="text/x-python")
    bounds = {"adjacent": [(0, 5), (5, 10)], "overlap": [(0, 5), (3, 8)], "nested": [(0, 10), (3, 8)],
              "duplicate_bounds": [(0, 5), (0, 5)], "empty": [(0, 5), (6, 6)], "ambiguous": [(0, 5), (5, 10)]}[case]
    symbols = tuple(WaymarkSymbol("f0" if case == "ambiguous" else f"f{i}", "function", None, None,
                                  WaymarkPosition(1, start), WaymarkPosition(1, end)) for i, (start, end) in enumerate(bounds))
    monkeypatch.setattr(observations, "discover_symbols_from_content", lambda **kw: WaymarkDiscoveryResult(True, "4.1.0", "python", symbols))
    result = observe(target, [{"symbol_name": "f0"}, {"symbol_name": "f1"}])
    if code:
        assert result["code"] == code and not state(target)[-1]
        assert "selection_index" in result
    else:
        assert result["status"] == "observed_batch" and len(state(target)[-1]) == 2


def test_batch_local_spans_interior_insertion_and_scope_occurrence_indexes():
    target, selectors = initialized(2, body="    return 'abcd abcd'")
    bundle = observe(target, selectors)
    args = request(target, bundle)
    for group, scope in zip(args["groups"], bundle["scopes"]):
        at = scope["text"].index("abcd") + 1
        group["operations"] = [
            {"op": "match", "match": "abcd", "replace": "ABCD", "occurrence_index": 2},
            {"op": "span", "start": at, "end": at, "expected_text": "", "replace": "🌟", "expected_before": "a", "expected_after": "b"}]
    assert submit(args)["status"] == "accepted"
    assert state(target)[0].count("a🌟bcd ABCD") == 2


@pytest.mark.parametrize("mutation,code", [("target", "BUNDLE_TARGET_MISMATCH"), ("cycle", "BUNDLE_CYCLE_MISMATCH"),
    ("version", "BUNDLE_VERSION_MISMATCH"), ("hash", "BUNDLE_HASH_MISMATCH"), ("scope_hash", "BATCH_GROUP_INVALID"),
    ("consumed", "BUNDLE_ALREADY_CONSUMED")])
def test_batch_invalid_authority_rejects_entire_request(mutation, code):
    target, selectors = initialized()
    bundle = observe(target, selectors)
    args = request(target, bundle)
    other, other_selectors = initialized()
    other_args = request(other, observe(other, other_selectors))
    other_log = submit(other_args)["pdcp_log_id"]
    with SessionLocal.begin() as session:
        row = session.get(TargetScopeObservations, uuid.UUID(bundle["scopes"][-1]["observation_id"]))
        if mutation == "target": row.target_file_id = uuid.UUID(other["target_file_id"])
        if mutation == "cycle": row.editing_cycle_id = uuid.UUID(other["active_editing_cycle_id"])
        if mutation == "version": row.target_version = 1
        if mutation == "hash": row.target_current_hash = "0" * 64
        if mutation == "scope_hash": row.observed_scope_hash = "0" * 64
        if mutation == "consumed": row.accepted_pdcp_log_id = uuid.UUID(other_log)
    result = submit(args)
    assert result["status"] == "rejected" and result["code"] == code, result
    assert state(target)[1] == 0 and len(state(target)[2]) == 1 and not state(target)[3]


def test_batch_verifies_entire_locked_preimage_hash():
    target, selectors = initialized(prefix="# untouched preface\n")
    args = request(target, observe(target, selectors))
    with SessionLocal.begin() as session:
        row = session.get(CloudTargetFiles, uuid.UUID(target["target_file_id"]))
        row.current_content = row.current_content.replace("untouched", "corrupted")
    result = submit(args)
    assert result["code"] == "BUNDLE_HASH_MISMATCH"
    assert state(target)[1] == 0 and not state(target)[3]


def test_batch_infrastructure_exception_rolls_back_content_audit_and_all_links(monkeypatch):
    from app.services import pdcp_service
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    before = state(target)[:2]
    persist = pdcp_service._persist_acceptance
    def fail_after_persistence(*a, **kw):
        persist(*a, **kw)
        raise RuntimeError("injected failure before commit")
    monkeypatch.setattr(pdcp_service, "_persist_acceptance", fail_after_persistence)
    with pytest.raises(RuntimeError, match="injected failure"):
        submit(args)
    content, version, logs, ledger, scopes = state(target)
    assert (content, version) == before and not logs and not ledger
    assert all(row.accepted_pdcp_log_id is None for row in scopes)


def test_batch_rejected_outcome_recovers_and_explicit_lineage_can_succeed():
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    args["groups"][-1]["operations"][0]["match"] = "missing"
    rejected = submit(args)
    recovered = submit(args)
    assert recovered["deduplicated"] and recovered["pdcp_log_id"] == rejected["pdcp_log_id"]
    assert len(state(target)[2]) == 1
    args["groups"][-1]["operations"][0]["match"] = "abcd"
    args.update(client_request_id=str(uuid.uuid4()), parent_pdcp_log_id=rejected["pdcp_log_id"], attempt=2)
    assert submit(args)["status"] == "accepted"
    logs = sorted(state(target)[2], key=lambda row: row.log_sequence)
    assert str(logs[-1].parent_pdcp_log_id) == rejected["pdcp_log_id"]


def test_batch_invalid_text_uses_shared_durable_safe_evidence():
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    args["groups"][-1]["operations"][0]["replace"] = "\x00\ud800"
    rejected = submit(args)
    assert rejected["failure_reason"] == "target_encoding_invalid" and rejected["validity"]["protocol_valid"] is False
    recovered = submit(args)
    assert recovered["deduplicated"] and recovered["pdcp_log_id"] == rejected["pdcp_log_id"]
    assert len(state(target)[2]) == 1 and state(target)[1] == 0 and not state(target)[3]
    assert json.loads(state(target)[2][0].pdcp_content)["evidence_format"] == "patchdiff-invalid-input/1"


def test_batch_caller_owned_rollback_leaves_observations_unconsumed():
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    with SessionLocal() as session:
        session.begin()
        result = submit_observed_operations(session, **args)
        assert result.status == "accepted" and session.in_transaction()
        session.rollback()
    assert state(target)[1] == 0 and not state(target)[2] and not state(target)[3]
    assert all(row.accepted_pdcp_log_id is None for row in state(target)[4])


def test_markdown_bundle_edits_table_row_and_literal_fenced_block():
    content = '# Checklist\n\n| Check ID | Owner | State |\n| --- | --- | --- |\n| CHK-14-C | Ops | OPEN |\n\n```text\n<<<<<<< MATCH\nepoch_unit = "sec"\n=======\nepoch_unit = "sec"\n>>>>>>> REPLACE\n```\n'
    target = registry.call("patchdiff_initialize_target", filename="literal.md", content=content, content_type="text/markdown")
    bundle = observe(target, [{"symbol_name": "row:CHK-14-C", "kind": "table_row"}, {"symbol_name": "fence:L7", "kind": "code_block"}])
    assert bundle["status"] == "observed_batch"
    args = request(target, bundle)
    args["groups"][0]["operations"] = [{"op": "match", "match": "OPEN", "replace": "READY"}]
    args["groups"][1]["operations"] = [{"op": "match", "match": 'epoch_unit = "sec"', "replace": 'epoch_unit = "ns"', "occurrence_index": 2}]
    assert submit(args)["status"] == "accepted"
    assert state(target)[0] == content.replace("OPEN", "READY").replace('=======\nepoch_unit = "sec"', '=======\nepoch_unit = "ns"')


def test_batch_stale_guard_precedes_operation_decode_and_reports_reached_stage():
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    args["expected_target_version"] = 9
    args["groups"][-1]["operations"] = [{"op": "unknown"}]
    result = submit(args)
    assert result["code"] == "BUNDLE_VERSION_MISMATCH"
    assert result["validity"]["protocol_valid"] is None and result["validity"]["transaction_valid"] is None


def test_batch_mixed_explicit_null_fields_are_rejected():
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    args["observation_id"] = None
    assert submit(args)["code"] == "INVALID_BATCH_REQUEST"
    assert observe(target, None)["code"] == "INVALID_BATCH_REQUEST"


def test_bundle_rejects_pending_caller_changes_without_flushing_or_discarding():
    target, selectors = initialized()
    with SessionLocal() as session:
        row = session.get(CloudTargetFiles, uuid.UUID(target["target_file_id"]))
        original = row.current_content
        row.current_content += "# pending\n"
        result = observations.observe_scope(session, target_file_id=row.target_file_id, selections=selectors)
        assert result["code"] == "INVALID_BATCH_REQUEST" and row.current_content.endswith("# pending\n")
        session.rollback()
    assert state(target)[0] == original and not state(target)[-1]


def test_batch_uuid_spelling_keeps_raw_request_identity_and_canonical_replay_ids():
    target, selectors = initialized()
    args = request(target, observe(target, selectors))
    args["observation_bundle_id"] = args["observation_bundle_id"].upper()
    for group in args["groups"]: group["observation_id"] = group["observation_id"].upper()
    accepted = submit(args)
    assert accepted["status"] == "accepted"
    assert submit(args)["deduplicated"]
    replay = registry.call("patchdiff_replay", target_file_id=target["target_file_id"])
    assert replay["status"] == "success" and replay["materialized_state_matches"]
    # Only durable IDs are canonicalized. A changed request body retains distinct request identity.
    args["observation_bundle_id"] = args["observation_bundle_id"].lower()
    assert submit(args)["code"] == "request_key_conflict"
