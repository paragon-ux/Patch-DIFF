import json
import os
from pathlib import Path
import subprocess
import sys

from app.core.config import settings


def test_every_published_example_real_stdio_postgres(tmp_path):
    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "live.json"
    env = {**os.environ, "PYTHONPATH": str(root / "backend"), "PATCHDIFF_DATABASE_URL": settings.database_url}
    process = subprocess.run([sys.executable, "-X", "utf8", str(root / "docs/usability/PASS-B-live-verify.py"), str(output)],
                             cwd=root, env=env, capture_output=True, timeout=60)
    assert process.returncode == 0, process.stdout.decode("utf-8") + process.stderr.decode("utf-8")
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert len(evidence["executed_pairs"]) == 13 and len(evidence["checks"]) == 4
