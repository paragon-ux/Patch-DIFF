from fastapi.testclient import TestClient
import pytest


@pytest.fixture(autouse=True)
def frozen_retest_compatibility_profile(request, monkeypatch):
    # The frozen controller retains its bytes; its trusted operator opts into the compatibility catalog.
    if request.module.__name__.split(".")[-1].startswith("test_retest_"):
        monkeypatch.setenv("PATCHDIFF_MCP_PROFILE", "full")

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

