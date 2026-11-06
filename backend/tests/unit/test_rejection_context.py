"""Pure failing-buffer capture and actual JSON-byte budget checks."""

import json
import sys
from dataclasses import replace

import pytest

from app.core.result import FailureBufferContext, RejectedCoreResult
from app.core.hashing import canonical_sha256
from app.pdcp.applier import apply_pdcp_transaction
from app.services.rejection_context import available_context, unavailable_context
from backend.tests.unit.test_transaction_applier import parsed_edits


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")


@pytest.mark.parametrize("text", ["", "x" * 255, "x" * 256, "x" * 257, "\U0001f642" * 300, '\x01\t\n"\\' * 80])
def test_context_exact_codepoint_prefix_and_empty_target(text):
    context = available_context(FailureBufferContext.capture(text), observed_target_version=2**63-1,
                                observed_target_hash="f" * 64)
    assert context["text"] == text[:256]
    assert context["end"] == min(256, len(text))
    assert context["total_chars"] == len(text)
    assert context["truncated"] is (len(text) > 256)
    assert context["buffer_stage"] == "canonical_target"
    assert len(encoded(context)) <= 4096


def test_context_actual_maximum_metadata_and_corrupt_non_ascii_identity():
    buffer = FailureBufferContext("\U0001f642" * 256, sys.maxsize, sys.maxsize)
    contexts = [available_context(buffer, observed_target_version=-(2**63), observed_target_hash=h)
                for h in ["f" * 64, "\U0001f642" * 64]]
    for context in contexts:
        assert len(encoded(context)) <= 4096
        assert context["text"] == buffer.text[:context["end"]]
        assert context["truncated"] is True
        assert context["total_chars"] == sys.maxsize
        assert context["prior_changes"] == sys.maxsize
        assert context["observed_target_version"] == -(2**63)
    corrupt = contexts[1]
    assert corrupt["observed_target_hash"] == "\U0001f642" * 64
    assert corrupt["end"] < 256
    assert len(encoded({"failure_context": corrupt, "current_context": corrupt})) <= 8192
    longer = {**corrupt, "text": buffer.text[:corrupt["end"] + 1], "end": corrupt["end"] + 1}
    assert len(encoded({"failure_context": longer, "current_context": longer})) > 8192


@pytest.mark.parametrize("reason", ["invalid_target_id", "target_not_found", "unlocked_local_state"])
def test_unavailable_has_no_fabricated_text_or_identity(reason):
    context = unavailable_context(reason)
    assert context.pop("available") is False
    assert context.pop("unavailable_reason") == reason
    assert set(context.values()) == {None}


@pytest.mark.parametrize("initial,changes,expected,prior,reason", [
    ("alpha", [("missing", "x", None)], "alpha", 0, "match_absent"),
    ("alpha alpha", [("alpha", "x", None)], "alpha alpha", 0, "match_ambiguous"),
    ("alpha", [("alpha", "x", {"occurrence_index": 2})], "alpha", 0, "disambiguation_invalid"),
    ("alpha beta", [("alpha", "ALPHA", None), ("alpha", "x", None)], "ALPHA beta", 1, "sequential_match_invalid"),
    ("alpha beta", [("alpha", "ALPHA", None), ("absent", "x", None)], "ALPHA beta", 1, "match_absent"),
])
def test_applier_captures_actual_failed_buffer(initial, changes, expected, prior, reason):
    result = apply_pdcp_transaction(initial, parsed_edits(*changes))
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason.value == reason
    assert result.before_hash == canonical_sha256(initial)
    assert result.failure_buffer == FailureBufferContext(expected, len(expected), prior)
    assert not hasattr(result, "target_content")


def test_applier_never_retains_whole_intermediate_buffer():
    replacement = "\U0001f642" * 10000
    result = apply_pdcp_transaction("alpha", parsed_edits(("alpha", replacement, None), ("missing", "x", None)))
    assert result.failure_buffer.text == replacement[:256]
    assert result.failure_buffer.total_chars == 10000
    assert result.failure_buffer.prior_changes == 1


def test_applier_captures_scope_hash_failure():
    parsed = parsed_edits(("alpha", "new", None), header_hash="0" * 64)
    result = apply_pdcp_transaction("alpha", parsed)
    assert result.failure_buffer == FailureBufferContext("alpha", 5, 0)


def test_empty_match_core_guard_keeps_actual_failure_buffer():
    parsed = parsed_edits(("alpha", "new", None))
    parsed = replace(parsed, changes=(replace(parsed.changes[0], match_payload=""),))
    result = apply_pdcp_transaction("alpha", parsed)
    assert result.failure_reason.value == "block_malformed"
    assert result.failure_buffer == FailureBufferContext("alpha", 5, 0)
