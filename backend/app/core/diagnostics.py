"""Cheap bounded capture while the actual failure buffer exists."""
from app.core.canonicalization import canonicalize_text
from app.pdcp.matcher import MatchSpan

# Fresh near-miss scans see at most this prefix of the failing buffer (response-only copy).
NEAR_MISS_SCAN_CHARS = 65_536


def exact_candidates(buffer: str, occurrences: tuple[MatchSpan, ...]) -> dict:
    items = [{"occurrence_index": index, "start": span.start, "end": span.end,
              "before": buffer[max(0, span.start-20):span.start],
              "match_preview": buffer[span.start:min(span.end, span.start+64)],
              "match_truncated": span.end-span.start > 64, "after": buffer[span.end:span.end+20]}
             for index, span in enumerate(occurrences[:5], 1)]
    truncated = len(occurrences) > len(items)
    return {"kind": "exact_occurrences", "occurrence_count": len(occurrences),
            "returned_count": len(items), "candidates": items, "truncated": truncated,
            "next_occurrence_index": len(items) + 1 if truncated else None}


def near_miss_query(match: str) -> dict:
    if len(match) > 64:
        return {"text": None, "omission_reason": "match_too_large"}
    return {"text": canonicalize_text(match), "omission_reason": None}
