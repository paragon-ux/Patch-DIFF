"""Pure wire-contract checks; service admission/recovery stays in integration tests."""
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from app.mcp.editor_contracts import (
    ContractArgumentError, EDITOR_V2_EAGER_TOOLS, EDITOR_V2_ROUTES, EDITOR_V2_TOOLS,
    MAX_RECEIPT_BYTES, is_success, normalize_arguments, project_result, tool_declaration,
)
from app.mcp.external_adapter import _input_schema_for

TARGET = "11111111-1111-4111-8111-111111111111"
BUNDLE = "22222222-2222-4222-8222-222222222222"
SCOPE = "33333333-3333-4333-8333-333333333333"
LOG = "44444444-4444-4444-8444-444444444444"
BATCH = "patchdiff_commit_bundle"
SINGLE = "patchdiff_commit_observation"
VALIDITY = {"protocol_valid": True, "transaction_valid": True,
            "task_correct": "not_evaluated", "semantic": "not_evaluated"}


def declaration(name):
    return tool_declaration(name, _input_schema_for(EDITOR_V2_ROUTES[name]))


def snapshot(name=BATCH):
    return {"target_file_id": TARGET, "expected_target_version": 7, "expected_current_hash": "a" * 64,
            ("observation_bundle_id" if name == BATCH else "observation_id"): BUNDLE if name == BATCH else SCOPE}


def proposal(name=BATCH):
    operations = [{"op": "match", "match": "red", "replace": "blue", "occurrence_index": 2},
                  {"op": "span", "start": 10, "end": 12, "expected_text": "xy", "replace": "z"}]
    result = {"snapshot": snapshot(name), "intent": "Update color", "client_request_id": "edit-1"}
    if name == BATCH:
        result["groups"] = [{"observation_id": SCOPE, "operations": operations}]
    else:
        result["operations"] = operations
    return result


def accepted():
    return {"status": "accepted", "target_file_id": TARGET, "pdcp_log_id": LOG,
            "client_request_id": "edit-1", "deduplicated": False,
            "before_version": 7, "after_version": 8, "version": 8,
            "before_hash": "a" * 64, "after_hash": "b" * 64,
            "current_version": 8, "current_hash": "b" * 64,
            "observation_bundle_id": BUNDLE, "group_count": 1, "change_count": 1,
            "manifest_entries_added": 1, "validity": copy.deepcopy(VALIDITY),
            "warnings": [], "warning_details": [], "warning_count": 0, "warnings_truncated": False,
            "groups": [{"group_index": 0, "observation_id": SCOPE, "change_count": 1}],
            "evidence": {"changes": [{"change_id": "g0:chg_001", "group_index": 0, "operation_index": 0,
                                       "observation_id": SCOPE, "scope_local_start": 24, "scope_local_end": 29,
                                       "matched_chars": 5, "replacement_chars": 6,
                                       "matched_sha256": "c" * 64, "replacement_sha256": "d" * 64}]}}


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


@pytest.mark.parametrize("name", sorted(EDITOR_V2_TOOLS))
def test_declarations_have_valid_examples_and_do_not_modify_legacy_schema(name):
    legacy = _input_schema_for(EDITOR_V2_ROUTES[name])
    before = copy.deepcopy(legacy)
    tool = tool_declaration(name, legacy)
    assert legacy == before
    Draft202012Validator.check_schema(tool["inputSchema"])
    Draft202012Validator.check_schema(tool["outputSchema"])
    for example in tool["inputSchema"].get("examples", []):
        Draft202012Validator(tool["inputSchema"]).validate(example)
        normalize_arguments(name, example)
    assert bool(tool.get("_meta", {}).get("antigravity/alwaysLoad")) == (name in EDITOR_V2_EAGER_TOOLS)
    assert "x-patchdiff-capabilities" not in tool["inputSchema"]


def test_catalog_and_mutating_annotations_are_honest():
    assert len(EDITOR_V2_TOOLS) == 8 and len(EDITOR_V2_EAGER_TOOLS) == 6
    for name in EDITOR_V2_TOOLS:
        annotations = declaration(name)["annotations"]
        writes = name in {BATCH, SINGLE, "patchdiff_observe_one", "patchdiff_observe_scopes"}
        assert annotations["readOnlyHint"] is not writes
        assert not annotations["openWorldHint"]
        if writes:
            assert annotations["idempotentHint"] is False
            assert annotations["destructiveHint"] == (name in {BATCH, SINGLE})


@pytest.mark.parametrize("name", [BATCH, SINGLE])
def test_normalization_preserves_values_order_metadata_and_exact_retry(name):
    args = proposal(name)
    args.update({"source": "client", "parent_pdcp_log_id": LOG, "attempt": 3, "include_correlation_id": True})
    before = copy.deepcopy(args)
    normalized = normalize_arguments(name, args)
    assert normalized == {**args["snapshot"], **{key: value for key, value in args.items() if key != "snapshot"}}
    assert args == before
    assert normalize_arguments(name, copy.deepcopy(args)) == normalized
    Draft202012Validator(declaration(name)["inputSchema"]).validate(args)
    for key, bad in [("expected_target_version", "7"), ("expected_current_hash", "BAD"),
                     ("target_file_id", TARGET.upper())]:
        changed = copy.deepcopy(args)
        changed["snapshot"][key] = bad
        assert normalize_arguments(name, changed)[key] == bad


def test_batch_supports_one_many_and_mixed_ordered_operations():
    args = proposal()
    args["groups"] *= 2
    args["groups"][1] = copy.deepcopy(args["groups"][0])
    args["groups"][1]["observation_id"] = LOG
    normalized = normalize_arguments(BATCH, args)
    assert normalized["groups"] == args["groups"]
    Draft202012Validator(declaration(BATCH)["inputSchema"]).validate(args)
    assert "operations" not in normalized and "observation_id" not in normalized
    assert "oneOf" not in declaration(BATCH)["inputSchema"]
    assert len(declaration(BATCH)["inputSchema"]["properties"]["groups"]["items"]["properties"]["operations"]["items"]["oneOf"]) == 2


@pytest.mark.parametrize("name", [BATCH, SINGLE])
def test_known_target_missing_operational_fields_are_audited_by_service(name):
    # A valid advertised request requires more, but admission remains authoritative.
    result = normalize_arguments(name, {"snapshot": {"target_file_id": TARGET}})
    assert result["target_file_id"] == TARGET
    assert result["intent"] is None
    assert "expected_current_hash" not in result
    assert "expected_target_version" not in result
    assert "client_request_id" not in result
    assert result["observation_bundle_id" if name == BATCH else "observation_id"] is None
    assert result["groups" if name == BATCH else "operations"] is None
    args = proposal(name)
    args["snapshot"]["expected_target_version"] = None
    args["client_request_id"] = None
    assert normalize_arguments(name, args)["expected_target_version"] is None
    assert normalize_arguments(name, args)["client_request_id"] is None


@pytest.mark.parametrize("name,args,code", [
    (BATCH, {"snapshot": None}, "invalid_snapshot"),
    (BATCH, {"snapshot": {}}, "missing_target"),
    (BATCH, {"snapshot": {"target_file_id": TARGET, "observation_id": SCOPE}}, "unknown_snapshot_field"),
    (BATCH, {"snapshot": snapshot(), "operations": []}, "unknown_argument"),
    (SINGLE, {"snapshot": snapshot(SINGLE), "groups": []}, "unknown_argument"),
    ("patchdiff_list_scopes", {"target_file_id": TARGET, "selections": []}, "unknown_argument"),
    ("patchdiff_observe_scopes", {"target_file_id": TARGET, "query": "x"}, "unknown_argument"),
    ("patchdiff_observe_one", {"target_file_id": TARGET}, "missing_identity"),
    ("patchdiff_observe_one", {"target_file_id": TARGET, "symbol_name": None}, "missing_identity"),
    ("patchdiff_read_observation", {"target_file_id": TARGET}, "missing_identity"),
    ("patchdiff_read_observation", {"target_file_id": TARGET, "observation_id": None}, "missing_identity"),
])
def test_unroutable_or_mixed_envelopes_fail_without_guessing(name, args, code):
    with pytest.raises(ContractArgumentError) as exc:
        normalize_arguments(name, args)
    assert exc.value.code == code
    assert exc.value.detail == exc.value.failure_detail


def test_route_errors_do_not_echo_untrusted_unknown_field_names():
    with pytest.raises(ContractArgumentError) as exc:
        normalize_arguments(BATCH, {"secret-value" * 1000: 1})
    assert "secret-value" not in str(exc.value)
    assert normalize_arguments("patchdiff_observe_scopes", {"target_file_id": TARGET}) == {"target_file_id": TARGET, "selections": None}
    assert normalize_arguments("patchdiff_read_observation", {"target_file_id": TARGET, "observation_id": 123})["observation_id"] == 123


@pytest.mark.parametrize("name,identity,status,commit", [
    ("patchdiff_observe_scopes", "observation_bundle_id", "observed_batch", BATCH),
    ("patchdiff_observe_one", "observation_id", "observed", SINGLE),
])
def test_observation_snapshot_is_directly_reusable_and_source_is_unchanged(name, identity, status, commit):
    source = {"status": status, "target_file_id": TARGET, "target_version": 7, "target_current_hash": "a" * 64,
              identity: BUNDLE if commit == BATCH else SCOPE, "text": "exact\r\n\u03bb", "offset": 0,
              "truncated": True, "next_offset": 9, "scope_end": 100000,
              "scopes": [{"observation_id": SCOPE, "text": "exact", "next_offset": None}]}
    original = copy.deepcopy(source)
    projected = project_result(name, source)
    assert source == original
    assert projected["snapshot"] == snapshot(commit)
    assert projected["text"] == source["text"]
    assert projected["scope_end"] == 100000  # Compatibility observation does not shrink to a batch limit.
    args = proposal(commit)
    args["snapshot"] = projected["snapshot"]
    assert normalize_arguments(commit, args)[identity] == source[identity]
    Draft202012Validator(declaration(name)["outputSchema"]).validate(projected)


def test_paging_never_invents_bundle_or_fresh_snapshot():
    payload = {"status": "observed", "mode": "scope_page", "observation_id": SCOPE,
               "text": "page", "offset": 4, "next_offset": 8, "truncated": True}
    assert project_result("patchdiff_read_observation", payload) == payload


@pytest.mark.parametrize("name", [BATCH, SINGLE])
def test_receipt_original_state_survives_recovery_and_does_not_use_proposal_as_evidence(name):
    original = accepted()
    before = copy.deepcopy(original)
    receipt = project_result(name, original, arguments={"intent": "UNTRUSTED CLAIM", "groups": ["invented"]})
    assert original == before
    assert receipt["transaction"]["before"] == {"version": 7, "hash": "a" * 64}
    assert receipt["transaction"]["after"] == {"version": 8, "hash": "b" * 64}
    assert receipt["transaction"]["operation_count"] == receipt["transaction"]["group_count"] == 1
    # Uncheckable per-change span/hash facts and group lists stay in the ledger, not the receipt.
    assert "changes" not in receipt and "scopes" not in receipt
    assert "c" * 64 not in json.dumps(receipt)
    assert "UNTRUSTED" not in json.dumps(receipt)
    recovered = copy.deepcopy(original)
    recovered.update(deduplicated=True, current_version=11, current_hash="f" * 64)
    second = project_result(name, recovered)
    assert second["transaction"] == {**receipt["transaction"], "deduplicated": True}
    assert second["current"] == {"version": 11, "hash": "f" * 64}
    assert second["transaction"]["deduplicated"]
    assert receipt["validity"] == VALIDITY
    Draft202012Validator(declaration(name)["outputSchema"]).validate(second)


def test_missing_original_versions_are_not_inferred_from_alias_or_current():
    payload = accepted()
    del payload["before_version"]
    del payload["after_version"]
    payload["current_version"] = 99
    result = project_result(SINGLE, payload)
    assert result["transaction"]["before"]["version"] is None
    assert result["transaction"]["after"]["version"] is None


@pytest.mark.parametrize("name", [BATCH, SINGLE])
def test_whole_receipt_bounds_all_collections_unicode_and_diagnostics(name):
    payload = accepted()
    payload["evidence"]["changes"] *= 128
    payload["groups"] *= 32
    payload["change_count"] = 128
    payload["group_count"] = 32
    payload["warning_details"] = [{"code": "no_op_change", "message": "\U0001f642" * 3000}] * 20
    payload["warning_count"] = 20
    payload["diagnostic"] = {"code": "SOME_CODE", "stage": "accepted", "group_index": 0,
                              "failure_context": {"text": "\U0001f642" * 20000}}
    payload["failure_detail"] = "\U0001f642" * 10000
    payload["current_context"] = {"text": "x" * 10000}
    receipt = project_result(name, payload)
    assert encoded_size(receipt) <= MAX_RECEIPT_BYTES
    assert receipt["transaction"]["pdcp_log_id"] == LOG
    assert receipt["code"] == "SOME_CODE"
    assert receipt["validity"] == VALIDITY
    assert receipt["presentation"]["truncated"]
    assert receipt["warnings"]["total"] == 20
    assert receipt["transaction"]["group_count"] == 32
    assert receipt["transaction"]["operation_count"] == 128
    assert receipt["warnings"]["truncated"]
    assert "diagnostic" in receipt["presentation"]["omitted_fields"]
    Draft202012Validator(declaration(name)["outputSchema"]).validate(receipt)


def test_rejection_preserves_stage_log_code_and_does_not_turn_unknown_into_rejected():
    payload = {"status": "rejected", "target_file_id": TARGET, "pdcp_log_id": LOG,
               "client_request_id": "edit-1", "current_version": 9, "current_hash": "a" * 64,
               "validity": {"protocol_valid": True, "transaction_valid": False, "task_correct": "not_evaluated", "semantic": "not_evaluated"},
               "diagnostic": {"code": "BUNDLE_VERSION_MISMATCH", "stage": "precondition_guard", "group_index": 0,
                              "observation_id": SCOPE, "retryable": True}, "failure_detail": "stale"}
    receipt = project_result(BATCH, payload)
    assert receipt["code"] == "BUNDLE_VERSION_MISMATCH"
    assert receipt["diagnostic"] == payload["diagnostic"]
    assert receipt["validity"] == payload["validity"]
    assert receipt["transaction"]["pdcp_log_id"] == LOG
    assert not is_success(BATCH, receipt)
    unknown = project_result(BATCH, {"status": "error", "code": "infrastructure_error", "outcome": "unknown", "failure_detail": "timeout"})
    assert unknown["status"] == "error" and unknown["outcome"] == "unknown"
    assert unknown["transaction"]["pdcp_log_id"] is None


def test_unbounded_invalid_target_echo_is_explicitly_omitted_not_forged_as_short_id():
    result = project_result(BATCH, {"status": "invalid_argument", "target_file_id": "x" * 20000, "code": "invalid_target"})
    assert result["target_file_id"] is None
    assert result["presentation"]["omitted_values"]["target_file_id"]["bytes"] > 20000
    assert len(result["presentation"]["omitted_values"]["target_file_id"]["sha256"]) == 64
    assert encoded_size(result) <= MAX_RECEIPT_BYTES


@pytest.mark.parametrize("status", ["rejected", "invalid_argument", "not_found", "discovery_error", "error"])
def test_errors_are_never_success(status):
    for name in EDITOR_V2_TOOLS:
        assert not is_success(name, {"status": status})
        error = project_result(name, {"status": status, "code": "example", "failure_detail": "detail"})
        Draft202012Validator(declaration(name)["outputSchema"]).validate(error)


def test_upstream_warning_omission_is_preserved_even_when_no_items_arrive():
    payload = accepted()
    payload.update(warning_count=5, warnings_truncated=True)
    result = project_result(BATCH, payload)
    assert result["warnings"] == {"items": [], "total": 5, "truncated": True}
