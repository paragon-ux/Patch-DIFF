"""Deterministic disambiguation for exact PDCP MATCH occurrences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.core.canonicalization import canonicalize_text
from app.core.failures import FailureReason
from app.pdcp.matcher import MatchSpan, find_exact_occurrences

SELECTING_DISAMBIGUATION_FIELDS = frozenset(
    {"anchor_before", "anchor_after", "occurrence_index"}
)


@dataclass(frozen=True, slots=True)
class MatchResolutionError(Exception):
    failure_reason: FailureReason
    failure_detail: str


def resolve_match_span(
    target_text: str,
    match_text: str,
    disambiguation: Mapping[str, str] | None = None,
) -> MatchSpan:
    """Resolve a MATCH payload to exactly one target span or reject canonically."""

    target = canonicalize_text(target_text)
    occurrences = find_exact_occurrences(target, match_text)

    if not occurrences:
        raise MatchResolutionError(FailureReason.MATCH_ABSENT, "MATCH text was not found.")
    if len(occurrences) == 1:
        return occurrences[0]

    disambiguation = disambiguation or {}
    if not SELECTING_DISAMBIGUATION_FIELDS.intersection(disambiguation):
        if disambiguation:
            raise MatchResolutionError(
                FailureReason.DISAMBIGUATION_INVALID,
                "Disambiguation did not select a unique MATCH occurrence.",
            )
        raise MatchResolutionError(
            FailureReason.MATCH_AMBIGUOUS,
            "MATCH text appears multiple times without disambiguation.",
        )

    candidates = list(occurrences)
    occurrence_index = disambiguation.get("occurrence_index")
    if occurrence_index is not None:
        if not occurrence_index.isdigit():
            raise MatchResolutionError(
                FailureReason.DISAMBIGUATION_INVALID,
                "occurrence_index must be a positive integer.",
            )
        selected_index = int(occurrence_index)
        if selected_index < 1 or selected_index > len(occurrences):
            raise MatchResolutionError(
                FailureReason.DISAMBIGUATION_INVALID,
                "occurrence_index is outside the exact occurrence list.",
            )
        candidates = [occurrences[selected_index - 1]]

    anchor_before = disambiguation.get("anchor_before")
    if anchor_before is not None:
        anchor = canonicalize_text(anchor_before)
        candidates = [span for span in candidates if target[: span.start].find(anchor) != -1]

    anchor_after = disambiguation.get("anchor_after")
    if anchor_after is not None:
        anchor = canonicalize_text(anchor_after)
        candidates = [span for span in candidates if target[span.end :].find(anchor) != -1]

    if len(candidates) != 1:
        raise MatchResolutionError(
            FailureReason.DISAMBIGUATION_INVALID,
            "Disambiguation did not select a unique MATCH occurrence.",
        )
    return candidates[0]
