"""Source line-ending facts recorded at upload; canonical storage stays LF-only."""

from __future__ import annotations

import hashlib
from typing import Any

from app.core.canonicalization import TextInput

EXPORT_FORMATS = ("original_text", "canonical_lf", "crlf", "original_eol")
_STYLE_EOL = {"none": "\n", "lf": "\n", "crlf": "\r\n", "cr": "\r"}


def source_line_endings(value: TextInput) -> dict[str, Any]:
    """Count raw line endings before canonicalization (CRLF counts once)."""

    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    text = raw.decode("utf-8", errors="strict")
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    kinds = [name for name, count in (("lf", lf), ("crlf", crlf), ("cr", cr)) if count]
    style = "none" if not kinds else kinds[0] if len(kinds) == 1 else "mixed"
    return {
        "style": style,
        "lf": lf,
        "crlf": crlf,
        "cr": cr,
        "normalized": bool(crlf or cr),
        "source_code_points": len(text),
        "source_utf8_bytes": len(raw),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


def export_eol(export_format: str, recorded: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """Return (eol, error_code) for an export format and the recorded source facts."""

    if export_format in {"original_text", "canonical_lf"}:
        return "\n", None
    if export_format == "crlf":
        return "\r\n", None
    if export_format != "original_eol":
        return None, "unsupported_export_format"
    if not isinstance(recorded, dict) or recorded.get("style") not in {*_STYLE_EOL, "mixed"}:
        return None, "source_line_endings_unknown"
    if recorded["style"] == "mixed":
        return None, "original_eol_unrecoverable"
    return _STYLE_EOL[recorded["style"]], None


def apply_eol(canonical: str, eol: str) -> str:
    return canonical if eol == "\n" else canonical.replace("\n", eol)


def eol_name(eol: str) -> str:
    return {"\n": "lf", "\r\n": "crlf", "\r": "cr"}[eol]
