"""G-2: verify immutable bytes without exposing evaluator files to agents."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "evaluation" / "structural_retest"
spec = importlib.util.spec_from_file_location("retest_prepare", ROOT / "prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def test_committed_original_supplemental_hashes_and_staging(tmp_path):
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert prepare.validate_inputs(manifest) == []
    destination = tmp_path / "staged"
    receipt = prepare.stage(manifest, "supplemental", destination)
    assert receipt["model_invocations"] == 0 and receipt["oracle_copied"] is False
    for arm in "ABC":
        files = list((destination / arm).iterdir())
        assert len(files) == (5 if arm == "A" else 6)
        assert all(path.name not in {"verify_hard_suite.py", "original_harness.py", "edit_specs.json"} for path in files)
    with pytest.raises(FileExistsError):
        prepare.stage(manifest, "supplemental", destination)
    with pytest.raises(ValueError, match="no authenticated original fixtures"):
        prepare.stage(manifest, "primary", tmp_path / "missing-primary")


def test_preparation_rejects_changed_hash_and_paths_outside_package():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    altered = copy.deepcopy(manifest)
    altered["studies"]["supplemental"]["artifacts"][0]["sha256"] = "0" * 64
    assert "SHA-256 mismatch" in prepare.validate_inputs(altered)[0]
    altered["studies"]["supplemental"]["artifacts"][0]["path"] = "../../requirements.lock"
    assert "Missing or invalid artifact" in prepare.validate_inputs(altered)[0]
