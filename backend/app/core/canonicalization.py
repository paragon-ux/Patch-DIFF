"""Canonical text handling for deterministic PatchDIFF runtime code."""

from __future__ import annotations


TextInput = str | bytes


def canonicalize_text(value: TextInput) -> str:
    """Return PatchDIFF canonical text without trimming or Unicode normalization."""

    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="strict")
    elif isinstance(value, str):
        text = value
    else:
        raise TypeError("canonicalize_text expects str or UTF-8 bytes")

    return text.replace("\r\n", "\n").replace("\r", "\n")
