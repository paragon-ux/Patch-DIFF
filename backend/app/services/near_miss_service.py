"""Bounded diagnostic-only comparison; callers must release owned locks first."""
from collections import Counter

from app.services.rejection_context import bound_candidates, context_identity

MAX_COMPARISON_CELLS = 1_000_000
MAX_CANDIDATES = 3
EMPTY_HINT = ("No similar text was found in the scanned range. Search a short exact fragment with "
              "patchdiff_find_occurrences or read the region before retrying.")


def near_misses(diagnostic: dict, *, caller_owned: bool, buffer: str | None = None,
                failure_reason: str | None = None) -> dict:
    """Rank distinct near-miss locations for an absent match.

    ``buffer`` is the bounded in-memory failing buffer of a fresh evaluation; without
    it (exact recovery) only the stored failure context is scanned.
    """
    context = diagnostic.get("failure_context") or {}
    metadata = context_identity(context)

    def omitted(reason):
        return {"kind": "near_miss", "status": "omitted", "omission_reason": reason,
                "candidates": [], "returned_count": 0, "truncated": False, "scope_truncated": False,
                "candidates_truncated": False, "scan_source": None, "scanned_start": None,
                "scanned_end": None, **metadata}
    if failure_reason == "sequential_match_invalid":
        return omitted("sequential_match_consumed")
    if caller_owned:
        return omitted("caller_transaction")
    query = diagnostic.get("near_miss_query")
    if query is None or (buffer is None and not context.get("available")):
        return omitted("historical_context_unavailable")
    if query.get("omission_reason"):
        return omitted(query["omission_reason"])
    if buffer is not None:
        text, offset, source = buffer, 0, "failing_buffer"
        total = context["total_chars"] if context.get("available") else len(buffer)
    else:
        text, offset, source = context["text"], context.get("start") or 0, "stored_failure_context"
        total = context["total_chars"]
    needle = query["text"]
    threshold = min(4, max(1, len(needle)//4))
    widths = [length for length in (len(needle)-1, len(needle), len(needle)+1) if length > 0]
    # Ukkonen band: a cell more than `threshold` off the diagonal already costs more than
    # `threshold`, so values are capped at threshold+1 and only banded cells are computed.
    # Every distance <= threshold stays exact; one row per start serves all three widths.
    cap = threshold + 1
    # Bag distance is a lower bound on edit distance. Characters of the needle missing
    # from the width-len(needle) window bound every window starting here from below
    # (minus one for the longer window), so pruned starts cannot hold a candidate.
    need = Counter(needle)
    have: Counter = Counter()
    missing = len(needle)
    for char in text[:len(needle)]:
        if have[char] < need[char]:
            missing -= 1
        have[char] += 1
    starts = max(0, len(text)-widths[0]+1)
    cells = 0
    processed = 0
    ranked = []
    for start in range(starts):
        if start:
            gone = text[start-1]
            have[gone] -= 1
            if have[gone] < need[gone]:
                missing += 1
            if start+len(needle)-1 < len(text):
                came = text[start+len(needle)-1]
                if have[came] < need[came]:
                    missing -= 1
                have[came] += 1
        if missing - 1 > threshold:
            processed += 1
            continue
        window = text[start:start+widths[-1]]
        previous = [min(offset_, cap) for offset_ in range(len(window)+1)]
        used = 0
        exhausted = abandoned = False
        for index, char in enumerate(needle, 1):
            low, high = max(1, index-threshold), min(len(window), index+threshold)
            band = max(0, high-low+1)
            if cells + used + band > MAX_COMPARISON_CELLS:
                exhausted = True
                break
            used += band
            current = [min(index, cap)] + [cap] * len(window)
            for column in range(low, high+1):
                current[column] = min(current[column-1]+1, previous[column]+1,
                                      previous[column-1]+(char != window[column-1]), cap)
            previous = current
            # Row minima never decrease, so once a whole row exceeds the threshold no window
            # from this start can qualify; abandoning the start keeps the ranking exact.
            if current[0] > threshold and min(current[low:high+1], default=cap) > threshold:
                abandoned = True
                break
        if exhausted:
            break
        cells += used
        processed += 1
        if abandoned:
            continue
        for width in widths:
            if width <= len(window) and 0 < previous[width] <= threshold:
                ranked.append((previous[width], start, start+width))
    if starts and not processed:
        return omitted("work_budget_exhausted")
    ranked.sort()
    chosen = []
    for distance, start, end in ranked:
        if all(end <= other_start or start >= other_end for _, other_start, other_end in chosen):
            chosen.append((distance, start, end))
            if len(chosen) > MAX_CANDIDATES:
                break
    candidates_truncated = len(chosen) > MAX_CANDIDATES
    candidates = [{"distance": distance, "start": offset+start, "end": offset+end, "text": text[start:end],
                   "before": text[max(0, start-16):start], "after": text[end:end+16]}
                  for distance, start, end in chosen[:MAX_CANDIDATES]]
    scope_truncated = processed < starts or offset > 0 or offset + len(text) < total
    result = {"kind": "near_miss", "status": "computed", "omission_reason": None,
              "candidates": candidates, "returned_count": len(candidates),
              "truncated": scope_truncated or candidates_truncated, "scope_truncated": scope_truncated,
              "candidates_truncated": candidates_truncated, "scan_source": source,
              "scanned_start": offset, "scanned_end": offset + processed,
              "comparison_cells": cells, **metadata}
    if not candidates:
        result["hint"] = EMPTY_HINT
    result = bound_candidates("near_misses", result)
    if result["returned_count"] < len(chosen[:MAX_CANDIDATES]):
        result["candidates_truncated"] = True
    return result
