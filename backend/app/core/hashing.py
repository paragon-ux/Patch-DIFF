"""Shared SHA-256 helpers for canonical PatchDIFF text."""

from __future__ import annotations

import hashlib

from app.core.canonicalization import TextInput, canonicalize_text


def canonical_sha256(value: TextInput) -> str:
    """Hash canonicalized text as lowercase SHA-256 over UTF-8 bytes."""

    canonical = canonicalize_text(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
