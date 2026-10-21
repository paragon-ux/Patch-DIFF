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
    for width in sorted({length for length in (len(needle)-1, len(needle), len(needle)+1) if length > 0}):
        for start in range(len(buffer)-width+1):
            text = buffer[start:start+width]
            previous = list(range(width+1))
            for index, char in enumerate(needle, 1):
                if cells + width > MAX_COMPARISON_CELLS:
                    return omitted("work_budget_exhausted")
                cells += width
                current = [index]
                for offset, other in enumerate(text, 1):
                    current.append(min(current[-1]+1, previous[offset]+1, previous[offset-1]+(char != other)))
                previous = current
            distance = previous[-1]
            if 0 < distance <= threshold:
                end = start+width
                ranked.append({"distance": distance, "start": start, "end": end, "text": text,
                               "before": buffer[max(0, start-16):start], "after": buffer[end:end+16]})
    ranked.sort(key=lambda item: (item["distance"], item["start"], item["end"]))
    result = {"kind": "near_miss", "status": "computed", "omission_reason": None,
              "candidates": ranked[:3], "returned_count": min(3, len(ranked)),
              "truncated": bool(context["truncated"] or len(ranked) > 3), "comparison_cells": cells, **metadata}
    return bound_candidates("near_misses", result)
