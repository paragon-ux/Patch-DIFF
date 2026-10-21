"""Invalid text is represented safely without changing valid request identity."""

import json
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.input_text import invalid_text_paths, is_persistable_text, safe_input_text
from app.core.validity import ValidationStage
from app.pdcp.parser import PDCPParseError, parse_pdcp
from app.pdcp.protocol_validator import ProtocolValidationError
from app.pdcp.typed import canonical_record_json, decode_record, parse_typed_record
from app.services import pdcp_service
from app.services.export_service import export_target, get_target
from app.services.prompt_context_service import build_prompt_context
from app.services.read_service import find_occurrences, read_target
from backend.tests.unit.test_typed_transaction import pdcp_text, record

BAD = ["\ud800", "\udfff", "\x00"]
FIELDS = [
    "intent", "match", "replace", "anchor_before", "anchor_after", "rationale",
    "risk", "change_id", "occurrence_index", "expected_target_version", "expected_current_hash",
    "submission_source", "parent_pdcp_log_id", "attempt", "client_request_id",
    "nested", "unknown_key",
]


class FakeSession:
    identity_map = {}
    no_autoflush = nullcontext()

    def identity_key(self, *args):
        return args

    def execute(self, statement):
        assert not invalid_text_paths(statement.compile().params)
        return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(
            target_file_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            current_content="alpha", current_hash=canonical_sha256("alpha"), version=0,
        ))

    def scalar(self, statement):
        assert not invalid_text_paths(statement.compile().params)
        return None


@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("field", FIELDS)
def test_every_input_field_reaches_safe_encoding_rejection(monkeypatch, bad, field):
    args = dict(target_file_id="11111111-1111-1111-1111-111111111111",
                expected_target_version=0, intent="Update",
                edits=[{"match": "alpha", "replace": "beta"}], client_request_id="safe-key")
    if field in {"match", "replace", "anchor_before", "anchor_after", "rationale",
                 "risk", "change_id", "occurrence_index"}:
        args["edits"][0][field] = bad
    elif field == "nested":
        args["edits"][0]["unknown"] = {"inner": [bad]}
    elif field == "unknown_key":
        args["edits"][0][bad] = "value"
    else:
        args[field] = bad
    monkeypatch.setattr(pdcp_service, "_transaction", lambda session: nullcontext())
    monkeypatch.setattr(pdcp_service, "_resolve_parent_log", lambda *a: (None, None))
    monkeypatch.setattr(pdcp_service, "_upsert_current_pdcp", lambda *a, **kw: kw)
    monkeypatch.setattr(pdcp_service, "_persist_rejection", lambda *a, **kw: kw)
    result = pdcp_service.submit_edits(FakeSession(), **args)
    assert result["rejection"].failure_reason is FailureReason.TARGET_ENCODING_INVALID
    assert result["stage"] is ValidationStage.PROTOCOL_VALIDATION
    assert result["pdcp_content"].isascii()
    assert not invalid_text_paths(result["current_pdcp"])
    assert not invalid_text_paths(result["rejection"].diagnostic)
    evidence = json.loads(result["pdcp_content"])
    assert evidence["evidence_format"] == "patchdiff-invalid-input/1"
    assert invalid_text_paths(evidence["inputs"])
    if field == "client_request_id":
        assert result["client_request_id"] is None
    else:
        assert result["client_request_id"] == "safe-key"


@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("field", ["pdcp_content", "regeneration_source", "submission_source"])
def test_legacy_text_and_metadata_are_checked_before_hashing(monkeypatch, bad, field):
    args = dict(target_file_id="11111111-1111-1111-1111-111111111111",
                pdcp_content=pdcp_text(("alpha", "beta", None)))
    args[field] = bad
    monkeypatch.setattr(pdcp_service, "_transaction", lambda session: nullcontext())
    monkeypatch.setattr(pdcp_service, "_resolve_parent_log", lambda *a: (None, None))
    monkeypatch.setattr(pdcp_service, "_upsert_current_pdcp", lambda *a, **kw: kw)
    monkeypatch.setattr(pdcp_service, "_persist_rejection", lambda *a, **kw: kw)
    result = pdcp_service.submit_pdcp(FakeSession(), **args)
    assert result["rejection"].failure_reason is FailureReason.TARGET_ENCODING_INVALID
    assert result["pdcp_content"].isascii()
    assert json.loads(result["pdcp_content"])["inputs"][field if field != "pdcp_content" else "record"] == bad


@pytest.mark.parametrize("bad", BAD)
def test_pure_new_proposals_reject_invalid_text_without_affecting_historical_decoder(bad):
    value = record([{"match": "alpha", "replace": bad}])
    with pytest.raises(ProtocolValidationError) as error:
        parse_typed_record(value)
    assert error.value.failure_reason is FailureReason.TARGET_ENCODING_INVALID
    with pytest.raises(PDCPParseError) as error:
        parse_pdcp(pdcp_text(("alpha", bad, None)))
    assert error.value.failure_reason is FailureReason.TARGET_ENCODING_INVALID
    historical = record([{"match": "alpha", "replace": "beta", "anchor_before": "\x00"}])
    assert decode_record(canonical_record_json(historical), runtime_version="patchdiff-mvp-0.2.1").edits[0].anchor_before == "\x00"


@pytest.mark.parametrize("value", ["é", "😀", "𝄞", "a\r\nb", "\\ud800", ""])
def test_normal_text_and_canonical_hash_are_unchanged(value):
    assert is_persistable_text(value)
    proposal = record([{"match": "alpha", "replace": value}])
    expected = json.dumps(proposal, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    assert canonical_record_json(proposal) == expected
    assert parse_typed_record(proposal).edits[0].replace == value
    assert canonical_sha256(expected) == canonical_sha256(canonical_record_json(proposal))


def test_invalid_fingerprint_domain_cannot_alias_valid_ascii_evidence_payload():
    args = dict(protocol_version="0.2.3", target_file_id="target",
                pdcp_content_hash="a" * 64, expected_target_version=0,
                expected_current_hash=None, parent_pdcp_log_id=None)
    ordinary = pdcp_service._compute_request_fingerprint(**args)
    assert ordinary == canonical_sha256(json.dumps(args, sort_keys=True, separators=(",", ":")))
    assert ordinary != pdcp_service._compute_request_fingerprint(
        **args, identity_domain="patchdiff-invalid-input/1"
    )


@pytest.mark.parametrize("bad", BAD)
def test_read_string_inputs_reject_before_session_access_and_echo_safely(bad):
    target = "11111111-1111-1111-1111-111111111111"
    results = [
        find_occurrences(None, target_file_id=target, text=bad),
        find_occurrences(None, target_file_id=target, text="alpha", context_chars=bad),
        read_target(None, target_file_id=bad),
        get_target(None, target_file_id=bad),
        export_target(None, target_file_id=bad),
        export_target(None, target_file_id=target, format=bad),
        build_prompt_context(None, target_file_id=target, user_request=bad),
        build_prompt_context(None, target_file_id=target, user_request="Update", context_policy=bad),
    ]
    for result in results:
        assert result["status"] == "invalid_argument"
        assert not invalid_text_paths(result)
    submitted = pdcp_service.submit_edits(None, target_file_id=bad, intent="Edit", edits=[])
    assert submitted.pdcp_log_id is None
    assert is_persistable_text(submitted.target_file_id)
    assert json.loads(safe_input_text(bad)) == bad


@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("field", ["status", "content_hash", "client_request_id", "before_sequence", "limit"])
def test_history_filter_strings_reject_without_binding(bad, field):
    from app.mcp.tools import patchdiff_get_pdcp_log
    result = patchdiff_get_pdcp_log(
        target_file_id="11111111-1111-1111-1111-111111111111", **{field: bad})
    assert result["status"] == "invalid_argument"
    assert not invalid_text_paths(result)


@pytest.mark.parametrize("bad", BAD)
def test_ledger_and_deprecated_context_reads_reject_invalid_strings(bad):
    from app.mcp.tools import patchdiff_get_manifest_ledger
    from app.services.regeneration_service import build_regeneration_context
    result = patchdiff_get_manifest_ledger(
        target_file_id="11111111-1111-1111-1111-111111111111", include_previous_cycles=bad)
    assert result["status"] == "invalid_argument"
    result = build_regeneration_context(None, pdcp_log_id=bad, user_request=bad)
    assert result["status"] == "invalid_argument"
    assert not invalid_text_paths(result)


def test_deprecated_prompt_keeps_the_structured_invalid_argument():
    from app.services.regeneration_service import build_regeneration_prompt
    error = {"status": "invalid_argument", "failure_detail": "Invalid read input."}
    assert build_regeneration_prompt(error) is error


@pytest.mark.parametrize("leaf", [*BAD, "deep valid 😀"])
def test_depth_500_json_is_checked_without_python_recursion(monkeypatch, leaf):
    nested = leaf
    for _ in range(500):
        nested = [nested]
    wire = json.dumps(nested, ensure_ascii=True)
    assert len(wire) < 1200
    decoded = json.loads(wire)
    assert json.dumps(decoded, ensure_ascii=True) == wire
    args = dict(target_file_id="11111111-1111-1111-1111-111111111111",
                expected_target_version=0, intent="Deep input",
                edits=[{"match": "alpha", "replace": "beta", "unknown": decoded}],
                client_request_id="deep-key")
    monkeypatch.setattr(pdcp_service, "_transaction", lambda session: nullcontext())
    monkeypatch.setattr(pdcp_service, "_resolve_parent_log", lambda *a: (None, None))
    monkeypatch.setattr(pdcp_service, "_upsert_current_pdcp", lambda *a, **kw: kw)
    monkeypatch.setattr(pdcp_service, "_persist_rejection", lambda *a, **kw: kw)
    result = pdcp_service.submit_edits(FakeSession(), **args)
    expected = FailureReason.TARGET_ENCODING_INVALID if leaf in BAD else FailureReason.MANIFEST_INVALID
    assert result["rejection"].failure_reason is expected
    assert result["stage"] is ValidationStage.PROTOCOL_VALIDATION
    assert not invalid_text_paths(result["rejection"].diagnostic)
    stored = json.loads(result["pdcp_content"])
    if leaf in BAD:
        assert stored["evidence_format"] == "patchdiff-invalid-input/1"
        assert result["rejection"].diagnostic["invalid_input_paths_truncated"] is True
        assert result["pdcp_content"].isascii()
        stored = stored["inputs"]["record"]
    recovered = stored["edits"][0]["unknown"]
    for _ in range(500):
        recovered = recovered[0]
    assert recovered == leaf


def test_iterative_text_walk_preserves_depth_first_key_and_value_path_order():
    value = {"\ud800": [{"k": "\x00"}], "last": "\udfff"}
    key_path = json.dumps("\ud800", ensure_ascii=True)
    assert invalid_text_paths(value) == (
        f"$.<key>{key_path}", f'$[{key_path}][0]["k"]' , '$["last"]',
    )
