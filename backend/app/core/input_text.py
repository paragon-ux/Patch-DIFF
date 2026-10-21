"""Input text checks shared by pure validation and service persistence boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def is_persistable_text(value: str) -> bool:
    """PostgreSQL text needs UTF-8 scalar values and cannot contain NUL."""
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def invalid_text_paths(value: Any, path: str = "$") -> tuple[str, ...]:
    """Locate invalid JSON strings/keys without consuming a call frame per level."""
    paths = []
    pending = [(value, path)]
    while pending:
        item, item_path = pending.pop()
        if isinstance(item, str):
            if not is_persistable_text(item):
                paths.append(item_path)
        elif isinstance(item, Mapping):
            # Reverse pushes preserve the existing depth-first diagnostic order.
            for key, child in reversed(list(item.items())):
                key_text = str(key)
                safe_key = json.dumps(key_text, ensure_ascii=True)
                pending.append((child, f"{item_path}[{safe_key}]"))
                if not is_persistable_text(key_text):
                    pending.append((key_text, f"{item_path}.<key>{safe_key}"))
        elif isinstance(item, (list, tuple)):
            for index in range(len(item) - 1, -1, -1):
                pending.append((item[index], f"{item_path}[{index}]"))
        # Direct Python callers may supply values serialized with default=str.
        elif item is not None and not isinstance(item, (bool, int, float)):
            if not is_persistable_text(str(item)):
                paths.append(item_path)
    return tuple(paths)


def safe_input_text(value: Any) -> str:
    """Preserve valid echo text; represent invalid input as reversible ASCII JSON."""
    text = str(value)
    return text if is_persistable_text(text) else json.dumps(text, ensure_ascii=True)
