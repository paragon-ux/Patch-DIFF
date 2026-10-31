import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import app

if not os.getenv("PATCHDIFF_NODE_BINARY") and not shutil.which("node"):
    for fallback in (
        Path.home() / ".local" / "bin" / "node",
        Path.home() / ".local" / "share" / "patchdiff-runtime" / "node-v22.19.0-linux-x64" / "bin" / "node",
    ):
        if fallback.is_file() and os.access(fallback, os.X_OK):
            os.environ["PATCHDIFF_NODE_BINARY"] = str(fallback)
            local_bin = str(fallback.parent)
            if local_bin not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = f"{local_bin}{os.pathsep}{os.environ.get('PATH', '')}"
            break


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

