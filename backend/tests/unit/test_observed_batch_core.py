"""Pure observed batch r1 admission and assembly checks."""
import uuid

import pytest

from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.pdcp.observed_batch import (BATCH_PROTOCOL_VERSION, BatchScope, BatchValidationError,
                                     apply_observed_batch, parse_batch_request)


def batch(operations=None):
    text = "left abcd middle abcd right"
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    record = {"format": BATCH_PROTOCOL_VERSION, "target_file_id": str(uuid.uuid4()),
              "observation_bundle_id": str(uuid.uuid4()), "expected_target_version": 0,
              "expected_current_hash": canonical_sha256(text), "intent": "Change both scopes",
              "groups": [{"observation_id": oid, "operations": operations or [
                  {"op": "match", "match": "abcd", "replace": "ABCDE"},
                  {"op": "span", "start": 1, "end": 2, "expected_text": "B", "replace": "🌟"}]} for oid in ids]}
    scopes = tuple(BatchScope(oid, i, start, start + 4, canonical_sha256("abcd"))
                   for i, (oid, start) in enumerate(zip(ids, (5, 17))))
    return text, record, scopes


def test_batch_scope_local_sequential_spans_and_descending_assembly():
    text, record, scopes = batch()
    result = apply_observed_batch(text, parse_batch_request(record), scopes, target_type="text/plain")
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "left A🌟CDE middle A🌟CDE right"
    assert [f["group_index"] for f in result.change_facts] == [0, 0, 1, 1]
    assert [f["scope_local_start"] for f in result.change_facts] == [0, 1, 0, 1]
    assert len({f["change_id"] for f in result.change_facts}) == 4


@pytest.mark.parametrize("at", [0, 4])
def test_batch_boundary_insertions_reject(at):
    text, record, scopes = batch([{"op": "span", "start": at, "end": at, "expected_text": "", "replace": "!",
                                  "expected_before": "a", "expected_after": "b"}])
    result = apply_observed_batch(text, parse_batch_request(record), scopes, target_type="text/plain")
    assert isinstance(result, RejectedCoreResult)
    assert result.diagnostic["code"] == "BATCH_OPERATION_OUTSIDE_SCOPE"


def test_batch_failure_in_last_group_returns_no_assembled_content():
    text, record, scopes = batch()
    record["groups"][-1]["operations"] = [{"op": "match", "match": "left", "replace": "WRONG"}]
    result = apply_observed_batch(text, parse_batch_request(record), scopes, target_type="text/plain")
    assert isinstance(result, RejectedCoreResult)
    assert result.before_hash == canonical_sha256(text)
    assert result.diagnostic["group_index"] == 1
    assert result.failure_buffer.text == "abcd"


@pytest.mark.parametrize("mutation,code", [("empty", "INVALID_BATCH_REQUEST"), ("duplicate", "BATCH_GROUP_INVALID"),
                                         ("many", "BATCH_LIMIT_EXCEEDED"), ("ops", "BATCH_LIMIT_EXCEEDED")])
def test_batch_admission(mutation, code):
    _, record, _ = batch()
    if mutation == "empty": record["groups"] = []
    if mutation == "duplicate": record["groups"][1]["observation_id"] = record["groups"][0]["observation_id"]
    if mutation == "many": record["groups"] *= 17
    if mutation == "ops": record["groups"][0]["operations"] *= 65
    with pytest.raises(BatchValidationError) as exc:
        parse_batch_request(record)
    assert exc.value.code == code


def test_batch_no_op_warning_describes_whole_transaction():
    text, record, scopes = batch()
    record["groups"][0]["operations"] = [{"op": "match", "match": "abcd", "replace": "abcd"}]
    result = apply_observed_batch(text, parse_batch_request(record), scopes, target_type="text/plain")
    assert not any(warning["code"] == "no_op_transaction" for warning in result.warnings)
    record["groups"][1]["operations"] = record["groups"][0]["operations"]
    result = apply_observed_batch(text, parse_batch_request(record), scopes, target_type="text/plain")
    assert [warning["code"] for warning in result.warnings].count("no_op_transaction") == 1
