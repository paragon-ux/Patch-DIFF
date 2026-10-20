"""Enforcement boundary for the managed target (architecture decision A4).

Only the service commit path may assign `current_content`; initial creation in
`target_service` passes it to the constructor. This is a source-level guard, not a
runtime proof: it cannot stop a separate database writer or host-side file edits.
"""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
ASSIGNMENT = re.compile(r"\.current_content\s*=[^=]")
ALLOWED_ASSIGNERS = {"services/pdcp_service.py"}


def test_only_the_submit_service_assigns_target_content() -> None:
    offenders = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if ASSIGNMENT.search(path.read_text(encoding="utf-8")) and rel not in ALLOWED_ASSIGNERS:
            offenders.append(rel)
    assert offenders == []


def test_mcp_layer_never_calls_the_applier_or_assigns_content() -> None:
    for name in ("mcp/tools.py", "mcp/external_adapter.py"):
        source = (APP / name).read_text(encoding="utf-8")
        assert not ASSIGNMENT.search(source)
        assert "apply_pdcp_transaction" not in source
