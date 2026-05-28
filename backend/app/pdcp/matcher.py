"""Exact text occurrence detection for PDCP MATCH payloads."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.canonicalization import canonicalize_text


@dataclass(frozen=True, slots=True)
class MatchSpan:
    start: int
    end: int


def find_exact_occurrences(target_text: str, match_text: str) -> tuple[MatchSpan, ...]:
    """Return non-overlapping exact occurrences in left-to-right order."""

    target = canonicalize_text(target_text)
    needle = canonicalize_text(match_text)
    if needle == "":
        return ()

    spans: list[MatchSpan] = []
    search_from = 0
    while True:
        start = target.find(needle, search_from)
        if start == -1:
            break
        end = start + len(needle)
        spans.append(MatchSpan(start=start, end=end))
        search_from = end
    return tuple(spans)
