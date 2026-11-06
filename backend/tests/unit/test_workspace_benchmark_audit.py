"""Captured benchmark output admission must not change existing evidence."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


AUDIT = Path(__file__).resolve().parents[3] / "backend/tests/verification/workspace_benchmark_audit.py"


@pytest.mark.parametrize("existing", [False, True])
def test_audit_rejects_output_inside_packet_before_loading_captures(tmp_path, existing):
    packet = tmp_path / "packet"
    packet.mkdir()
    receipt = packet / "result.json"
    receipt.write_bytes(b"original capture\n")
    output = receipt if existing else packet / "new-audit.json"

    completed = _run(packet, output, tmp_path)

    assert completed.returncode != 0
    assert "Audit output must be outside the captured packet" in completed.stderr
    assert receipt.read_bytes() == b"original capture\n"
    assert {path.name for path in packet.iterdir()} == {"result.json"}


def test_audit_rejects_existing_external_output_before_loading_captures(tmp_path):
    packet = tmp_path / "packet"
    packet.mkdir()
    output = tmp_path / "previous-audit.json"
    output.write_bytes(b"previous report\n")

    completed = _run(packet, output, tmp_path)

    assert completed.returncode != 0
    assert "Audit output must be a new file" in completed.stderr
    assert output.read_bytes() == b"previous report\n"
    assert not list(packet.iterdir())


def _run(packet, output, cwd):
    return subprocess.run(
        [sys.executable, "-B", str(AUDIT), str(packet), str(output)],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=10,
    )
