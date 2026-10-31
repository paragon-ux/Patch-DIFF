"""C-1: scope admission is checked against each sequential buffer."""
import pytest

from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.operations import build_operations_record, parse_operations_record, to_parsed_operations


def apply(operations, *, scope=(2, 6)):
    record = build_operations_record(target_file_id="target", intent="Insertion policy",
                                    operations=operations, expected_target_version=0, expected_current_hash=None)
    parsed = to_parsed_operations(parse_operations_record(record), target_type="text/plain")
    return apply_pdcp_transaction("xxabcdyy", parsed, allow_span_operations=True,
                                  allow_span_context=True, scope_bounds=scope)


def insertion(at=4, **guards):
    return {"op": "span", "start": at, "end": at, "expected_text": "", "replace": "!", **guards}


@pytest.mark.parametrize("at", [2, 6])
def test_observed_boundary_insertions_reject_even_with_matching_guards(at):
    result = apply([insertion(at, expected_before="xxabcdyy"[at-1:at],
                             expected_after="xxabcdyy"[at:at+1])])
    assert isinstance(result, RejectedCoreResult)
    assert result.diagnostic["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"


@pytest.mark.parametrize("guards", [{}, {"expected_before": "b"}, {"expected_after": "c"},
                                    {"expected_before": None, "expected_after": "c"}])
def test_observed_interior_insertions_require_both_guards(guards):
    result = apply([insertion(**guards)])
    assert isinstance(result, RejectedCoreResult)
    assert result.diagnostic["code"] == "OBSERVED_INSERTION_GUARDS_REQUIRED"


@pytest.mark.parametrize("before,after", [("xab", "c"), ("b", "cdy")])
def test_matching_guards_cannot_extend_outside_observed_scope(before, after):
    result = apply([insertion(expected_before=before, expected_after=after)])
    assert isinstance(result, RejectedCoreResult)
    assert result.diagnostic["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"


@pytest.mark.parametrize("before,after", [("a", "c"), ("b", "d")])
def test_guards_must_be_immediately_adjacent(before, after):
    result = apply([insertion(expected_before=before, expected_after=after)])
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason.value == "span_expected_text_mismatch"


def test_interior_insertion_accepts_exact_guards_touching_scope_edges():
    result = apply([insertion(expected_before="ab", expected_after="cd")])
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "xxab!cdyy"


def test_later_insertion_uses_changed_scope_and_adjacent_sequential_text():
    grow = {"op": "span", "start": 2, "end": 3, "expected_text": "a", "replace": "AAA"}
    result = apply([grow, insertion(7, expected_before="c", expected_after="d")])
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "xxAAAbc!dyy"
    stale = apply([grow, insertion(7, expected_before="b", expected_after="d")])
    assert isinstance(stale, RejectedCoreResult)
    assert stale.failure_buffer.prior_changes == 1


def test_shrunk_scope_boundary_insertion_rejects_atomically():
    shrink = {"op": "span", "start": 2, "end": 5, "expected_text": "abc", "replace": ""}
    result = apply([shrink, insertion(3, expected_before="d", expected_after="y")])
    assert isinstance(result, RejectedCoreResult)
    assert result.diagnostic["code"] == "OPERATION_OUTSIDE_OBSERVED_SCOPE"


@pytest.mark.parametrize("at", [0, 2, 6, 8])
def test_historical_unobserved_insertions_still_accept_without_guards(at):
    result = apply([insertion(at)], scope=None)
    assert isinstance(result, AcceptedCoreResult)


def test_nonempty_edit_can_replace_entire_observed_scope():
    result = apply([{"op": "span", "start": 2, "end": 6, "expected_text": "abcd", "replace": "A"}])
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "xxAyy"
