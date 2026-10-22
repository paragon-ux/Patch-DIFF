"""Bounded diagnostic-only comparison; callers must release owned locks first."""
from app.services.rejection_context import bound_candidates, context_identity

MAX_COMPARISON_CELLS = 1_000_000


def near_misses(diagnostic: dict, *, caller_owned: bool) -> dict:
    context = diagnostic.get("failure_context") or {}
    metadata = context_identity(context)
    def omitted(reason):
        return {"kind": "near_miss", "status": "omitted", "omission_reason": reason,
                "candidates": [], "returned_count": 0, "truncated": False, **metadata}
    if caller_owned:
        return omitted("caller_transaction")
    query = diagnostic.get("near_miss_query")
    if not context.get("available") or query is None:
        return omitted("historical_context_unavailable")
    if query.get("omission_reason"):
        return omitted(query["omission_reason"])
    needle, buffer = query["text"], context["text"]
    cells = 0
    ranked = []
    threshold = min(4, max(1, len(needle)//4))
    widths = [length for length in (len(needle)-1, len(needle), len(needle)+1) if length > 0]
    # Ukkonen band: a cell more than `threshold` off the diagonal already costs more than
    # `threshold`, so values are capped at threshold+1 and only banded cells are computed.
    # Every distance <= threshold stays exact; one row per start serves all three widths.
    cap = threshold + 1
    for start in range(len(buffer)-widths[0]+1):
        text = buffer[start:start+widths[-1]]
        previous = [min(offset, cap) for offset in range(len(text)+1)]
        for index, char in enumerate(needle, 1):
            low, high = max(1, index-threshold), min(len(text), index+threshold)
            band = max(0, high-low+1)
            if cells + band > MAX_COMPARISON_CELLS:
                return omitted("work_budget_exhausted")
            cells += band
            current = [min(index, cap)] + [cap] * len(text)
            for offset in range(low, high+1):
                current[offset] = min(current[offset-1]+1, previous[offset]+1,
                                      previous[offset-1]+(char != text[offset-1]), cap)
            previous = current
        for width in widths:
            if width <= len(text) and 0 < previous[width] <= threshold:
                end = start+width
                ranked.append({"distance": previous[width], "start": start, "end": end, "text": buffer[start:end],
                               "before": buffer[max(0, start-16):start], "after": buffer[end:end+16]})
    ranked.sort(key=lambda item: (item["distance"], item["start"], item["end"]))
    result = {"kind": "near_miss", "status": "computed", "omission_reason": None,
              "candidates": ranked[:3], "returned_count": min(3, len(ranked)),
              "truncated": bool(context["truncated"] or len(ranked) > 3), "comparison_cells": cells, **metadata}
    return bound_candidates("near_misses", result)
