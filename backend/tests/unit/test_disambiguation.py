import pytest

from app.core.failures import FailureReason
from app.pdcp.disambiguation import MatchResolutionError, resolve_match_span
from app.pdcp.matcher import MatchSpan


def assert_resolution_rejects(
    target_text: str,
    match_text: str,
    disambiguation: dict[str, str] | None,
    reason: FailureReason,
) -> None:
    with pytest.raises(MatchResolutionError) as exc_info:
        resolve_match_span(target_text, match_text, disambiguation)
    assert exc_info.value.failure_reason is reason


def test_single_occurrence_resolves() -> None:
    assert resolve_match_span("alpha beta", "beta") == MatchSpan(6, 10)


def test_zero_match_rejects_match_absent() -> None:
    assert_resolution_rejects("alpha", "beta", None, FailureReason.MATCH_ABSENT)


def test_duplicate_match_without_disambiguation_rejects_match_ambiguous() -> None:
    assert_resolution_rejects("x x", "x", None, FailureReason.MATCH_AMBIGUOUS)


def test_occurrence_index_selects_correct_candidate() -> None:
    assert resolve_match_span("x x x", "x", {"occurrence_index": "2"}) == MatchSpan(2, 3)


def test_invalid_occurrence_index_rejects() -> None:
    assert_resolution_rejects("x x", "x", {"occurrence_index": "3"}, FailureReason.DISAMBIGUATION_INVALID)
    assert_resolution_rejects("x x", "x", {"occurrence_index": "0"}, FailureReason.DISAMBIGUATION_INVALID)
    assert_resolution_rejects("x x", "x", {"occurrence_index": "abc"}, FailureReason.DISAMBIGUATION_INVALID)


def test_anchor_before_selects_candidate() -> None:
    assert resolve_match_span("intro x middle x", "x", {"anchor_before": "middle"}) == MatchSpan(15, 16)


def test_anchor_after_selects_candidate() -> None:
    assert resolve_match_span("x middle x outro", "x", {"anchor_after": "middle"}) == MatchSpan(0, 1)


def test_combined_occurrence_and_anchors_select_candidate() -> None:
    assert resolve_match_span(
        "intro x middle x outro",
        "x",
        {"occurrence_index": "2", "anchor_before": "middle", "anchor_after": "outro"},
    ) == MatchSpan(15, 16)


def test_anchors_leaving_zero_candidates_reject() -> None:
    assert_resolution_rejects("x middle x", "x", {"anchor_before": "missing"}, FailureReason.DISAMBIGUATION_INVALID)


def test_anchors_leaving_multiple_candidates_reject() -> None:
    assert_resolution_rejects("intro x x", "x", {"anchor_before": "intro"}, FailureReason.DISAMBIGUATION_INVALID)


def test_region_hint_alone_does_not_select_candidate() -> None:
    assert_resolution_rejects("x x", "x", {"region_hint": "first"}, FailureReason.DISAMBIGUATION_INVALID)
