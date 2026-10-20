"""Exact text occurrence detection for PDCP MATCH payloads."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.canonicalization import canonicalize_text


@dataclass(frozen=True, slots=True)
class MatchSpan:
    start: int
    end: int


def find_exact_occurrences(
    target_text: str,
    match_text: str,
    *,
    overlapping: bool = True,
) -> tuple[MatchSpan, ...]:
    """Return exact occurrences in left-to-right order.

    By default every exact span is counted, including overlapping spans, as the core
    spec requires. ``overlapping=False`` reproduces the enumeration used by runtime
    ``patchdiff-mvp-0.1.0`` and exists only so that accepted history written under
    that runtime replays identically.
    """

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
        search_from = start + 1 if overlapping else end
    return tuple(spans)
