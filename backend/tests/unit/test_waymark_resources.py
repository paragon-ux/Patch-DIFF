"""Resolve pinned bridge resources in source checkouts and installed wheels."""

from app.services import waymark_adapter, waymark_worker


def test_source_checkout_keeps_existing_bridge_location(tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    module = repo / "backend/app/services/waymark_adapter.py"
    bridge = repo / "integrations/waymark"
    bridge.mkdir(parents=True)
    (bridge / "discover.mjs").write_text("source bridge")
    monkeypatch.setattr(waymark_adapter, "__file__", str(module))

    assert waymark_adapter._waymark_integration_dir() == bridge


def test_installed_wheel_prefers_packaged_resources_over_old_staging(tmp_path, monkeypatch):
    python_lib = tmp_path / "venv/lib/python3.11"
    module = python_lib / "site-packages/app/services/waymark_adapter.py"
    packaged = python_lib / "site-packages/integrations/waymark"
    old_staging = python_lib / "integrations/waymark"
    for bridge in (packaged, old_staging):
        bridge.mkdir(parents=True)
        (bridge / "discover.mjs").write_text("bridge")
    monkeypatch.setattr(waymark_adapter, "__file__", str(module))

    assert waymark_adapter._waymark_integration_dir() == packaged


def test_resident_and_oneshot_use_the_same_bridge():
    assert waymark_worker.BRIDGE == waymark_adapter.WAYMARK_INTEGRATION_DIR
    assert (waymark_worker.BRIDGE / "worker.mjs").is_file()
    assert (waymark_worker.BRIDGE / "package-lock.json").is_file()
