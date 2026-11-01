import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import app

os.environ.setdefault("PATCHDIFF_WAYMARK_MODE", "resident")

if not os.getenv("PATCHDIFF_NODE_BINARY") and not shutil.which("node"):
    runtime_root = Path.home() / ".local" / "share" / "patchdiff-runtime"
    candidates = [Path.home() / ".local" / "bin" / "node"]
    if runtime_root.is_dir():
        candidates.extend(sorted(runtime_root.glob("node-v*/bin/node"), reverse=True))
    for fallback in candidates:
        if fallback.is_file() and os.access(fallback, os.X_OK):
            os.environ["PATCHDIFF_NODE_BINARY"] = str(fallback)
            local_bin = str(fallback.parent)
            if local_bin not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = f"{local_bin}{os.pathsep}{os.environ.get('PATH', '')}"
            break


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

