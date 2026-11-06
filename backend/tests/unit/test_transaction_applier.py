from dataclasses import replace

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.typed import build_record, parse_typed_record, to_parsed_transaction


def parsed_edits(*changes, header_hash=None):
    edits = [{"match": match, "replace": replacement, **(selectors or {})}
             for match, replacement, selectors in changes]
    record = build_record(target_file_id="11111111-1111-1111-8111-111111111111",
                          expected_target_version=0, expected_current_hash=None,
                          intent="Update text", edits=edits)
    parsed = to_parsed_transaction(parse_typed_record(record), target_type="text/plain")
    return replace(parsed, header=replace(parsed.header, target_hash=header_hash))


def test_single_replacement_accepted() -> None:
    result = apply_pdcp_transaction("hello old world", parsed_edits(("old", "new", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "hello new world"


def test_deletion_accepted() -> None:
    result = apply_pdcp_transaction("hello old world", parsed_edits(("old ", "", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "hello world"


def test_whitespace_only_replacement_accepted() -> None:
    result = apply_pdcp_transaction("hello old world", parsed_edits(("old", "   ", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "hello     world"


def test_anchored_insertion_accepted() -> None:
    result = apply_pdcp_transaction("## Summary\nBody", parsed_edits(("## Summary", "## Summary\n\nInserted.", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "## Summary\n\nInserted.\nBody"


def test_zero_length_match_rejects() -> None:
    parsed = parsed_edits(("target", "inserted", None))
    parsed = replace(parsed, changes=(replace(parsed.changes[0], match_payload=""),))
    result = apply_pdcp_transaction("target", parsed)
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.BLOCK_MALFORMED


def test_multi_change_sequential_success() -> None:
    result = apply_pdcp_transaction(
        "a b c",
        parsed_edits(("a", "A", None), ("b", "B", None), ("c", "C", None)),
    )
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "A B C"


def test_second_change_sees_first_replacement() -> None:
    result = apply_pdcp_transaction(
        "alpha beta",
        parsed_edits(("alpha", "gamma", None), ("gamma beta", "done", None)),
    )
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "done"


def test_second_change_against_original_state_returns_sequential_match_invalid() -> None:
    result = apply_pdcp_transaction(
        "alpha beta",
        parsed_edits(("alpha", "gamma", None), ("alpha beta", "done", None)),
    )
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.SEQUENTIAL_MATCH_INVALID
    assert result.after_hash is None


def test_overlapping_valid_sequential_edits_accepted() -> None:
    result = apply_pdcp_transaction(
        "abc",
        parsed_edits(("ab", "xy", None), ("xyc", "done", None)),
    )
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "done"


def test_overlapping_invalid_sequential_edits_reject_atomically() -> None:
    result = apply_pdcp_transaction(
        "abc",
        parsed_edits(("ab", "xy", None), ("abc", "done", None)),
    )
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.SEQUENTIAL_MATCH_INVALID
    assert not hasattr(result, "target_content")


def test_before_hash_and_after_hash_are_correct() -> None:
    result = apply_pdcp_transaction("old", parsed_edits(("old", "new", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.before_hash == canonical_sha256("old")
    assert result.after_hash == canonical_sha256("new")


def test_header_target_hash_mismatch_rejects() -> None:
    result = apply_pdcp_transaction("old", parsed_edits(("old", "new", None), header_hash="a" * 64))
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.TARGET_HASH_MISMATCH


def test_no_mutation_outside_selected_span() -> None:
    result = apply_pdcp_transaction("left old right old", parsed_edits(("old", "new", {"occurrence_index": 2})))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "left old right new"
