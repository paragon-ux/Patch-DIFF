"""Regression for bootstrapping into the installed package's own bridge directory."""
from app.waymark_bridge import bootstrap


def test_bootstrap_into_packaged_directory_does_not_copy_a_file_onto_itself(tmp_path, monkeypatch):
    for name in bootstrap.BRIDGE_FILES:
        (tmp_path / name).write_text("packaged asset")
    monkeypatch.setattr(bootstrap, "get_packaged_bridge_dir", lambda: tmp_path)
    monkeypatch.setattr(bootstrap, "verify_node_binary", lambda _: (22, 0, 0))
    monkeypatch.setattr(bootstrap, "verify_installed_bridge", lambda _: "4.1.0")
    monkeypatch.setattr("app.services.waymark_adapter.resolve_node_executable", lambda _: "/node")
    assert bootstrap.bootstrap_bridge(tmp_path) == tmp_path
    assert (tmp_path / "discover.mjs").read_text() == "packaged asset"
