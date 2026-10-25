"""Read argument domains and history paging shapes without database writes."""

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from app.core.hashing import canonical_sha256
from app.mcp import tools
from app.mcp.external_adapter import ExternalMCPAdapter
from app.services.read_service import find_occurrences

TARGET = uuid.UUID("11111111-1111-1111-1111-111111111111")
HISTORY = [tools.patchdiff_get_pdcp_log, tools.patchdiff_get_manifest_ledger]


class FakeSession:
    def __init__(self, rows=(), found=True):
        self.rows = list(rows)
        self.found = found
        self.queries = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def get(self, *args):
        return SimpleNamespace(target_file_id=TARGET, active_editing_cycle_id=TARGET) if self.found else None
    def scalars(self, query):
        self.queries.append(query)
        return SimpleNamespace(all=lambda: self.rows[:query._limit_clause.value])
    def execute(self, query):
        # Ledger pages join their attempt rows by pdcp_log_id.
        return SimpleNamespace(all=lambda: list(self.rows))


def row(sequence):
    return SimpleNamespace(
        pdcp_log_id=uuid.uuid4(), log_sequence=sequence, ledger_sequence=sequence, status="accepted",
        failure_reason=None, failure_detail=None, failed_change_id=None, before_hash="a" * 64,
        after_hash="b" * 64, before_version=0, after_version=1, pdcp_content_hash="c" * 64,
        protocol_version="patchdiff-tx/1", runtime_version="patchdiff-mvp-0.2.2",
        submission_source="model_response", parent_pdcp_log_id=None, regeneration_attempt=None,
        regeneration_source=None, client_request_id="key", request_fingerprint="d" * 64,
        diagnostic_json=None, created_at=datetime.now(timezone.utc), pdcp_content="record",
        change_id=f"change_{sequence}", intent="Change", input_state=None, output_state=None,
        affected_region=None, user_visible_change=None, risk=None, origin="typed", derived_json={},
        editing_cycle_id=TARGET, change_index=1,
        intent_truncated=False, content_bytes=6, transaction_intent=None, rationales=None,
    )


@pytest.mark.parametrize("context", [-1, -100, True, False, None, "4", 1.0, 1.5, [], {}])
def test_invalid_context_rejects_before_querying(context):
    result = find_occurrences(None, target_file_id=TARGET, text="X", context_chars=context)
    assert result["status"] == "invalid_argument"


@pytest.mark.parametrize("context,expected", [(0, 0), (1, 1), (40, 40), (400, 400), (401, 400), (10000, 400)])
def test_context_zero_and_cap_preserve_exact_search(context, expected):
    content = "a" * 500 + "X" + "b" * 500
    target = SimpleNamespace(target_file_id=TARGET, current_content=content, version=3,
                             current_hash=canonical_sha256(content))
    session = SimpleNamespace(get=lambda *args: target)
    result = find_occurrences(session, target_file_id=TARGET, text="X", context_chars=context)
    assert result["status"] == "ok"
    assert result["occurrence_count"] == 1
    occurrence = result["occurrences"][0]
    assert occurrence["start"] == 500 and occurrence["end"] == 501
    assert len(occurrence["before"]) == len(occurrence["after"]) == expected
    assert target.current_content == content and target.version == 3


def test_default_context_is_40_and_tool_routing_keeps_domain_errors(monkeypatch):
    content = "a" * 100 + "X" + "b" * 100
    target = SimpleNamespace(target_file_id=TARGET, current_content=content, version=0,
                             current_hash=canonical_sha256(content))
    session = FakeSession()
    session.get = lambda *args: target
    monkeypatch.setattr(tools, "SessionLocal", lambda: session)
    default = tools.patchdiff_find_occurrences(target_file_id=str(TARGET), text="X")
    assert len(default["occurrences"][0]["before"]) == 40
    payload = ExternalMCPAdapter().call_tool("patchdiff_find_occurrences", {
        "target_file_id": str(TARGET), "text": "X", "context_chars": -1})
    assert payload["isError"] is False
    assert json.loads(payload["content"][0]["text"])["status"] == "invalid_argument"


@pytest.mark.parametrize("handler", HISTORY)
@pytest.mark.parametrize("field", ["limit", "before_sequence"])
@pytest.mark.parametrize("value", [0, -1, True, False, "2", 1.0, 1.5, [], {}])
def test_history_integer_arguments_have_consistent_empty_errors(handler, field, value):
    result = handler(target_file_id=str(TARGET), **{field: value})
    assert result["status"] == "invalid_argument"
    assert result["entries"] == [] and result["has_more"] is False and result["next_sequence"] is None


@pytest.mark.parametrize("handler,field", [
    (tools.patchdiff_get_pdcp_log, "include_content"),
    (tools.patchdiff_get_manifest_ledger, "include_previous_cycles"),
])
@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_history_flags_are_actual_booleans(handler, field, value):
    result = handler(target_file_id=str(TARGET), **{field: value})
    assert result["status"] == "invalid_argument"
    assert result["entries"] == [] and not result["has_more"] and result["next_sequence"] is None


@pytest.mark.parametrize("field", ["content_hash", "client_request_id"])
@pytest.mark.parametrize("value", [False, True, 7, 1.5, [], {}])
def test_history_filters_reject_nonstring_values_before_binding(field, value):
    result = tools.patchdiff_get_pdcp_log(target_file_id=str(TARGET), **{field: value})
    assert result["status"] == "invalid_argument"
    assert result["entries"] == [] and result["next_sequence"] is None and not result["has_more"]


@pytest.mark.parametrize("status", ["", "pending", "ACCEPTED", False, 1, [], {}])
def test_history_status_rejects_values_outside_terminal_enum(status):
    result = tools.patchdiff_get_pdcp_log(target_file_id=str(TARGET), status=status)
    assert result["status"] == "invalid_argument" and result["entries"] == []
    assert not result["has_more"] and result["next_sequence"] is None


@pytest.mark.parametrize("handler", HISTORY)
@pytest.mark.parametrize("count", [0, 1, 3, 4, 10])
def test_history_page_boundaries_and_display_order(monkeypatch, handler, count):
    session = FakeSession([row(sequence) for sequence in range(count, 0, -1)])
    monkeypatch.setattr(tools, "SessionLocal", lambda: session)
    result = handler(target_file_id=str(TARGET), limit=3)
    expected = list(range(count, max(count - 3, 0), -1))
    sequence_key = "log_sequence"
    if handler is tools.patchdiff_get_manifest_ledger:
        expected.reverse()
        sequence_key = "ledger_sequence"
    assert [entry[sequence_key] for entry in result["entries"]] == expected
    if handler is tools.patchdiff_get_pdcp_log:
        assert all("pdcp_content" not in entry for entry in result["entries"])
    assert result["has_more"] is (count > 3)
    assert result["next_sequence"] == (min(expected) if count > 3 else None)
    assert session.queries[0]._limit_clause.value == 4


@pytest.mark.parametrize("handler", HISTORY)
@pytest.mark.parametrize("limit,count", [("omitted", 50), (None, 50), (7, 7), (200, 200), (201, 200), (10000, 200)])
def test_history_defaults_and_caps(monkeypatch, handler, limit, count):
    session = FakeSession([row(sequence) for sequence in range(250, 0, -1)])
    monkeypatch.setattr(tools, "SessionLocal", lambda: session)
    kwargs = {} if limit == "omitted" else {"limit": limit}
    result = handler(target_file_id=str(TARGET), **kwargs)
    assert len(result["entries"]) == count
    assert result["has_more"]
    assert result["next_sequence"] == 251 - count
    assert session.queries[0]._limit_clause.value == count + 1


@pytest.mark.parametrize("handler", HISTORY)
def test_unknown_and_malformed_targets_have_empty_continuation(monkeypatch, handler):
    session = FakeSession(found=False)
    monkeypatch.setattr(tools, "SessionLocal", lambda: session)
    for target, status in [(str(TARGET), "not_found"), ("invalid", "invalid_argument"), ("\ud800", "invalid_argument")]:
        result = handler(target_file_id=target)
        assert result["status"] == status
        assert result["entries"] == [] and result["has_more"] is False and result["next_sequence"] is None
    assert session.queries == []


def test_discovery_agrees_with_bounds_nullable_history_and_legacy_key_lookup():
    schemas = {item["name"]: item["inputSchema"] for item in ExternalMCPAdapter().list_tools()}
    context = schemas["patchdiff_find_occurrences"]["properties"]["context_chars"]
    assert context["type"] == "integer" and context["minimum"] == 0 and context["default"] == 40
    assert "maximum" not in context and "400" in context["description"]
    validator = Draft202012Validator(schemas["patchdiff_find_occurrences"])
    base = {"target_file_id": str(TARGET), "text": "X"}
    assert validator.is_valid({**base, "context_chars": 401})
    for value in (-1, True, "2", None):
        assert not validator.is_valid({**base, "context_chars": value})
    for name in ("patchdiff_get_pdcp_log", "patchdiff_get_manifest_ledger"):
        properties = schemas[name]["properties"]
        assert set(properties["limit"]["type"]) == {"integer", "null"}
        assert properties["limit"]["minimum"] == 1 and properties["limit"]["default"] == 50
        assert "maximum" not in properties["limit"] and "200" in properties["limit"]["description"]
        validator = Draft202012Validator(schemas[name])
        assert validator.is_valid({"target_file_id": str(TARGET), "limit": None})
        assert validator.is_valid({"target_file_id": str(TARGET), "limit": 201})
        assert not validator.is_valid({"target_file_id": str(TARGET), "before_sequence": False})
    lookup = schemas["patchdiff_get_pdcp_log"]["properties"]["client_request_id"]
    assert "pattern" not in lookup
    assert Draft202012Validator(schemas["patchdiff_get_pdcp_log"]).is_valid(
        {"target_file_id": str(TARGET), "client_request_id": "legacy\n"})
    assert "pattern" in schemas["patchdiff_submit_edits"]["properties"]["client_request_id"]
    assert schemas["patchdiff_get_pdcp_log"]["properties"]["status"]["enum"] == ["accepted", "rejected", None]
