"""Shared structural-purity checks for PDCP non-payload regions."""

from __future__ import annotations

import re

EXECUTABLE_OUTSIDE_PAYLOAD_RE = re.compile(
    r"^\s*(def|class|import|from|for|while|if|elif|else|try|except|with)\b"
    r"|applyPDCP\s*\("
    r"|(__import__|eval|exec|open|subprocess|requests|fetch)\s*\("
    r"|^\s*(curl|wget|rm|del|powershell|python|node)\b",
    re.IGNORECASE,
)


def is_executable_structural_line(line: str) -> bool:
    return bool(EXECUTABLE_OUTSIDE_PAYLOAD_RE.search(line))
