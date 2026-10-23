"""Advisory accepted-transaction warnings: deterministic, verdict-neutral, replay-ignored."""

from __future__ import annotations

import unicodedata
from typing import Any

MAX_WARNING_DETAILS = 16

_ZWJ = "‍"


def _in(char: str, *ranges: tuple[int, int]) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in ranges)


def _regional(char: str) -> bool:
    return _in(char, (0x1F1E6, 0x1F1FF))


def _extends(char: str) -> bool:
    return unicodedata.category(char) in {"Mn", "Mc", "Me"} or char == _ZWJ or _in(
        char,
        (0xFE00, 0xFE0F),  # variation selectors
        (0xE0100, 0xE01EF),  # variation selectors supplement
        (0x1F3FB, 0x1F3FF),  # emoji modifiers
        (0xE0020, 0xE007F),  # tag characters
    )


def _hangul(char: str) -> str | None:
    code = ord(char)
    if 0x1100 <= code <= 0x115F or 0xA960 <= code <= 0xA97F:
        return "L"
    if 0x1160 <= code <= 0x11A7 or 0xD7B0 <= code <= 0xD7C6:
        return "V"
    if 0x11A8 <= code <= 0x11FF or 0xD7CB <= code <= 0xD7FB:
        return "T"
    if 0xAC00 <= code <= 0xD7A3:
        return "LV" if (code - 0xAC00) % 28 == 0 else "LVT"
    return None


def splits_grapheme(text: str, position: int) -> bool:
    """Conservative check that a boundary at ``position`` falls inside a grapheme cluster.

    This approximates UAX #29 for the common cases (combining marks, ZWJ sequences,
    variation selectors, emoji modifiers, tags, regional-indicator pairs and Hangul
    jamo). It is advisory only and never affects acceptance.
    """

    if position <= 0 or position >= len(text):
        return False
    before, after = text[position - 1], text[position]
    if _extends(after) or before == _ZWJ:
        return True
    if _regional(before) and _regional(after):
        run = 0
        index = position - 1
        while index >= 0 and _regional(text[index]):
            run += 1
            index -= 1
        return run % 2 == 1
    left, right = _hangul(before), _hangul(after)
    if left is None or right is None:
        return False
    return (
        (left == "L" and right in {"L", "V", "LV", "LVT"})
        or (left in {"LV", "V"} and right in {"V", "T"})
        or (left in {"LVT", "T"} and right == "T")
    )


def warning(code: str, detail: str, **fields: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail, **fields}


def bounded_warnings(details: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Stored/returned warning envelope: at most MAX_WARNING_DETAILS details."""

    kept = [dict(item) for item in details[:MAX_WARNING_DETAILS]]
    return {"warnings": kept, "warning_count": len(details), "warnings_truncated": len(details) > len(kept)}


def warning_strings(details: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[str]:
    return [f"{item['code']}: {item['detail']}" for item in details]
