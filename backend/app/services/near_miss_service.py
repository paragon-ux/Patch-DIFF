"""Bounded diagnostic-only comparison; callers must release owned locks first."""
from app.services.rejection_context import bound_candidates, context_identity

MAX_COMPARISON_CELLS = 1_000_000
MAX_CANDIDATES = 3
EMPTY_HINT = ("No similar text was found in the scanned range. Search a short exact fragment with "
              "patchdiff_find_occurrences or read the region before retrying.")


def _candidate_starts(text: str, needle: str, threshold: int, band_radius: int,
                      starts: int, max_width: int):
    """Exact positional pigeonhole filter over disjoint needle pieces.

    Any window of width in ``len(needle) + {-1, 0, +1}`` within Levenshtein
    distance ``threshold`` has diagonal drift at most ``band_radius = (threshold + 1) // 2``.
    Partitioning ``needle`` into ``>= threshold + 1`` disjoint pieces means either at
    least one of the ``threshold`` rarest pieces appears unedited at its aligned offset,
    or every one of those ``threshold`` pieces has 1 edit (leaving one half unedited) and
    all remaining pieces appear unedited. Falls back to ``range(starts)`` on homogeneous
    or dense repetitive inputs so budget-bounded scans start immediately.
    """
    needle_len = len(needle)
    if needle_len < threshold + 1 or starts <= 64:
        return range(starts)
    step = 3 if needle_len >= 3 * (threshold + 1) else (2 if needle_len >= 2 * (threshold + 1) else 1)
    piece_count = needle_len // step
    pieces = []
    for idx in range(piece_count):
        pos = idx * step
        sub = needle[pos:needle_len if idx == piece_count - 1 else pos + step]
        pieces.append((pos, sub, text.count(sub)))
    pieces.sort(key=lambda item: item[2])
    if pieces[threshold][2] > starts // 8 or sum(c for _, _, c in pieces[:threshold]) > starts // 4:
        return range(starts)

    candidates: set[int] = set()
    find = text.find
    for pos, sub, _ in pieces[:threshold]:
        sub_len = len(sub)
        at = find(sub)
        while at != -1:
            lo = max(0, at - pos - band_radius, at + sub_len - max_width)
            hi = min(starts - 1, at - pos + band_radius, at)
            for s in range(lo, hi + 1):
                candidates.add(s)
            at = find(sub, at + 1)

    unedited = sorted(pieces[threshold:], key=lambda item: item[0])
    runs: list[tuple[int, str, int]] = []
    for pos, sub, _ in unedited:
        if runs and runs[-1][0] + runs[-1][2] == pos:
            prev_pos, prev_sub, prev_len = runs[-1]
            runs[-1] = (prev_pos, prev_sub + sub, prev_len + len(sub))
        else:
            runs.append((pos, sub, len(sub)))

    piece_checks = [
        (pos, len(sub), sub[:2], sub[1:3], sub[0] + sub[2], sub[0], sub[2])
        if len(sub) == 3 else (pos, len(sub), sub[:len(sub) // 2], sub[len(sub) // 2:], "", "", "")
        for pos, sub, _ in pieces[:threshold] if len(sub) >= 2
    ]

    anchor_idx = 0 if runs[0][0] == 0 else min(range(len(runs)), key=lambda i: text.count(runs[i][1]))
    pos_k, sub_k, sub_k_len = runs[anchor_idx]
    other_runs = [runs[i] for i in range(len(runs)) if i != anchor_idx]
    text_len = len(text)
    at = find(sub_k)
    while at != -1:
        if pos_k == 0:
            lo = hi = at if at < starts else -1
        else:
            lo = max(0, at - pos_k - band_radius, at + sub_k_len - max_width)
            hi = min(starts - 1, at - pos_k + band_radius, at)
        for s in range(lo, hi + 1) if lo >= 0 else ():
            if s in candidates:
                continue
            win_end = min(text_len, s + max_width)
            ok = True
            for r_pos, r_sub, r_len in other_runs:
                if r_pos == 0:
                    if not text.startswith(r_sub, s):
                        ok = False
                        break
                else:
                    r_lo = max(s, s + r_pos - band_radius)
                    r_hi = min(win_end, s + r_pos + r_len + band_radius)
                    if find(r_sub, r_lo, r_hi) == -1:
                        ok = False
                        break
            if ok:
                for p_pos, p_len, ab, bc, ac, c0, c2 in piece_checks:
                    seg_lo = max(s, s + p_pos - band_radius)
                    seg_hi = min(win_end, s + p_pos + p_len + band_radius)
                    if find(ab, seg_lo, seg_hi) != -1 or find(bc, seg_lo, seg_hi) != -1:
                        continue
                    if p_len == 3:
                        if find(ac, seg_lo, seg_hi) != -1:
                            continue
                        seg = text[seg_lo:seg_hi]
                        if any(seg[idx] == c0 and seg[idx + 2] == c2 for idx in range(len(seg) - 2)):
                            continue
                    ok = False
                    break
            if ok:
                candidates.add(s)
        at = find(sub_k, at + 1)
    return sorted(candidates)


def _window_distances(needle: str, window: str, widths: list[int],
                      threshold: int, band_radius: int) -> tuple[int, list[tuple[int, int]]]:
    """Exact Landau-Vishkin diagonal-wave edit distance across all target widths."""
    needle_len = len(needle)
    window_len = len(window)
    limit = min(needle_len, window_len)
    if needle_len == window_len and needle == window:
        i = needle_len
    else:
        i = 0
        while i + 8 <= limit and needle[i:i + 8] == window[i:i + 8]:
            i += 8
        while i < limit and needle[i] == window[i]:
            i += 1
    prev_wave = {0: i}
    reached = i
    best: dict[int, int] = {}
    if i == needle_len and needle_len in widths:
        best[needle_len] = 0

    for dist in range(1, threshold + 1):
        curr_wave = dict(prev_wave)
        d_bound = min(dist, band_radius)
        for diag in range(-d_bound, d_bound + 1):
            row = prev_wave.get(diag, -1)
            same = prev_wave.get(diag)
            if same is not None:
                r_max = min(same, needle_len - 1, window_len - 1 - diag)
                if max(0, -diag) <= r_max and r_max + 1 > row:
                    row = r_max + 1
            ins = prev_wave.get(diag - 1)
            if ins is not None:
                r_max = min(ins, needle_len, window_len - diag)
                if max(0, 1 - diag) <= r_max and r_max > row:
                    row = r_max
            dele = prev_wave.get(diag + 1)
            if dele is not None:
                r_max = min(dele, needle_len - 1, window_len - 1 - diag)
                if max(0, -1 - diag) <= r_max and r_max + 1 > row:
                    row = r_max + 1
            if row < 0:
                continue
            col = row + diag
            if 0 <= col <= window_len:
                while (row + 8 <= needle_len and col + 8 <= window_len
                       and needle[row:row + 8] == window[col:col + 8]):
                    row += 8
                    col += 8
                while row < needle_len and col < window_len and needle[row] == window[col]:
                    row += 1
                    col += 1
                curr_wave[diag] = row
                if row > reached:
                    reached = row
                if row == needle_len and col in widths and col not in best:
                    best[col] = dist
        prev_wave = curr_wave

    return reached, [(dist, width) for width, dist in best.items() if dist > 0]


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
    # For target widths in len(needle) + {-1, 0, +1} and edit distance <= threshold,
    # any optimal alignment satisfies I + D <= threshold and |I - D| <= 1, so its diagonal
    # offset |col - row| never exceeds band_radius = (threshold + 1) // 2.
    band_radius = (threshold + 1) // 2
    band_width = 2 * band_radius + 1
    starts = max(0, len(text)-widths[0]+1)
    if starts and MAX_COMPARISON_CELLS < band_width:
        return omitted("work_budget_exhausted")
    cells = 0
    processed = 0
    ranked = []
    exhausted = False
    for start in _candidate_starts(text, needle, threshold, band_radius, starts, widths[-1]):
        window = text[start:start+widths[-1]]
        reached, matches = _window_distances(needle, window, widths, threshold, band_radius)
        used = max(1, min(len(needle), reached)) * band_width
        if cells + used > MAX_COMPARISON_CELLS:
            processed = start
            exhausted = True
            break
        cells += used
        processed = start + 1
        for distance, width in matches:
            ranked.append((distance, start, start+width))
    if not exhausted:
        processed = starts
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

