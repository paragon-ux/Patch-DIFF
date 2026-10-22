"""Frozen replacement grammar/profile and explicit admission boundary tests."""
import json
from dataclasses import replace

import pytest

from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.core.versions import REPLACEMENT_RUNTIME_VERSION, SUPPORTED_RUNTIME_PROFILES
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.operations import parse_operations_record
from app.pdcp.protocol_validator import ProtocolValidationError
from app.pdcp.replacement import (
    MAX_REPLACEMENT_BYTES, MAX_REPLACEMENT_CHARS, build_replacement_record,
    decode_replacement_record, parse_replacement_record, replacement_size_error, to_parsed_replacement,
)
from app.pdcp.typed import canonical_record_json


def record(value="new"):
    return build_replacement_record(target_file_id="target", intent="Replace explicitly", replacement=value,
                                    expected_target_version=0, expected_current_hash=None)


@pytest.mark.parametrize("before,after,expected", [("old", "new", "new"), ("", "", ""), ("old", "", ""),
    ("", "\U0001f642", "\U0001f642"), ("a\nb", "\U0001f642\r\nx\ry", "\U0001f642\nx\ny")])
def test_replace_all_full_span_facts_and_canonical_text(before, after, expected):
    typed = parse_replacement_record(record(after))
    parsed = to_parsed_replacement(typed, target_type="text/plain")
    result = apply_pdcp_transaction(before, parsed, allow_replace_all_operations=True)
    assert isinstance(result, AcceptedCoreResult) and result.target_content == expected
    assert result.change_facts == ({"change_id": "chg_001", "change_index": 1, "operation": "replace_all",
        "span_start": 0, "span_end": len(before), "matched_chars": len(before), "replacement_chars": len(expected),
        "matched_sha256": canonical_sha256(before), "replacement_sha256": canonical_sha256(expected)},)
    mixed = replace(parsed, changes=parsed.changes * 2)
    assert isinstance(apply_pdcp_transaction(before, mixed, allow_replace_all_operations=True), RejectedCoreResult)


@pytest.mark.parametrize("profile", list(SUPPORTED_RUNTIME_PROFILES))
def test_replacement_replay_requires_explicit_new_profile(profile):
    if profile == REPLACEMENT_RUNTIME_VERSION:
        assert decode_replacement_record(canonical_record_json(record()), runtime_version=profile).edits[0].replace == "new"
    else:
        with pytest.raises(ProtocolValidationError):
            decode_replacement_record(canonical_record_json(record()), runtime_version=profile)
        assert not SUPPORTED_RUNTIME_PROFILES[profile].replace_all_operations
    parsed = to_parsed_replacement(parse_replacement_record(record()), target_type="text/plain")
    assert isinstance(apply_pdcp_transaction("old", parsed), RejectedCoreResult)


@pytest.mark.parametrize("operations", [[], [{"op": "match", "match": "a", "replace": "b"}],
    [{"op": "replace_all", "replace": "a"}, {"op": "replace_all", "replace": "b"}],
    [{"op": "replace_all", "replace": "a", "start": 0}], [{"op": "replace_all"}],
    [{"op": "replace_all", "replace": 4}], None])
def test_strict_sole_operation_grammar(operations):
    with pytest.raises(ProtocolValidationError):
        parse_replacement_record({**record(), "operations": operations})
    with pytest.raises(ProtocolValidationError):
        parse_operations_record({**record(), "format": "patchdiff-tx/2"})


@pytest.mark.parametrize("value,dimension", [("a" * MAX_REPLACEMENT_CHARS, None),
    ("a" * (MAX_REPLACEMENT_CHARS + 1), "raw_code_points"),
    ("\U0001f642" * (MAX_REPLACEMENT_BYTES // 4), None),
    ("\U0001f642" * (MAX_REPLACEMENT_BYTES // 4) + "a", "raw_utf8_bytes"),
    ("\r\n" * 500_001, "raw_code_points"), (None, None)],
    ids=["chars-equal", "chars-over", "bytes-equal", "bytes-over", "raw-crlf-over", "wrong-shape"])
def test_admission_limits_are_inclusive_and_apply_before_normalization(value, dimension):
    assert replacement_size_error(value) == dimension


def test_replay_ignores_stricter_fresh_admission_limits(monkeypatch):
    from app.pdcp import replacement
    serialized = canonical_record_json(record("long accepted text"))
    monkeypatch.setattr(replacement, "MAX_REPLACEMENT_CHARS", 2)
    monkeypatch.setattr(replacement, "MAX_REPLACEMENT_BYTES", 2)
    assert replacement_size_error("long accepted text") == "raw_code_points"
    assert decode_replacement_record(serialized).edits[0].replace == "long accepted text"
    assert json.loads(serialized)["operations"] == [{"op": "replace_all", "replace": "long accepted text"}]


@pytest.mark.parametrize("value", ["\ud800", "\x00", "\udfff"])
def test_invalid_unicode_is_domain_rejection_before_utf8_size_encoding(value):
    with pytest.raises(ProtocolValidationError) as caught:
        parse_replacement_record(record(value))
    assert caught.value.failure_reason.value == "target_encoding_invalid"
