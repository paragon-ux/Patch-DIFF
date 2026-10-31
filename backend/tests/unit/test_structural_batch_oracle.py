"""G2-1: complete bytes, including collateral changes invisible to behavior checks."""
import hashlib
import json
import shutil

import pytest

from backend.tests.verification.structural_batch.evaluate import check, complete_primary
from backend.tests.verification.structural_batch.primary.evaluator import full_byte_oracle as oracle


def test_positive_reference_passes_both_oracles_without_writing_bytecode(tmp_path):
    oracle.generate(tmp_path / "gold")
    result = complete_primary(tmp_path / "gold")
    assert result["complete_correct"]
    assert result["behavioral"]["passed"] == result["behavioral"]["total"] == 20
    assert {p.name for p in (tmp_path / "gold").iterdir()} == set(oracle.SOURCE_HASHES)
    assert oracle.reference_manifest(oracle.expected()) == json.loads((oracle.Path(oracle.__file__).parent / "reference_hashes.json").read_text())


@pytest.mark.parametrize("corruption", ["unchanged", "overlap", "kernel", "rule", "tenant", "row", "append", "comment", "missing", "extra", "rename", "eol", "one_byte"])
def test_reject_collateral_or_missing_changes(tmp_path, corruption):
    reference = oracle.expected()
    files = dict(reference)
    if corruption == "unchanged":
        files = {name: (oracle.ROOT / "primary/fixtures" / name).read_bytes() for name in reference}
    elif corruption == "overlap":
        files["matrix_kernel.py"] = files["matrix_kernel.py"].replace(b"HEADER::SYNC::SYNC::CALIB::SYNC::SYNC::TRAILER", b"HEADER::SYNC::CALIB::SYNC::SYNC::SYNC::TRAILER")
    elif corruption == "kernel":
        files["matrix_kernel.py"] = files["matrix_kernel.py"].replace(b"stride_offset = (block_id << 4) + lane_id", b"stride_offset = (block_id << 5) + (lane_id * 3)", 1)
    elif corruption == "rule":
        files["validator_engine.py"] = files["validator_engine.py"].replace(b"max_drift = 30\n", b"max_drift = 31\n", 1)
    elif corruption == "tenant":
        files["routing_manifest.json"] = files["routing_manifest.json"].replace(b'"wire_version": "v2"', b'"wire_version": "v3"', 1)
    elif corruption == "row":
        files["MIGRATION_RUNBOOK.md"] = files["MIGRATION_RUNBOOK.md"].replace(b"CHK-01-C", b"CHK-01-X")
    elif corruption == "append":
        files["schema_defs.py"] += b"\n# unrelated addition\n"
    elif corruption == "comment":
        files["matrix_kernel.py"] = files["matrix_kernel.py"].replace(b"deterministic saturation", b"changed saturation", 1)
    elif corruption == "missing":
        del files["schema_defs.py"]
    elif corruption == "extra":
        files["extra.txt"] = b"unrelated\n"
    elif corruption == "rename":
        files["renamed.py"] = files.pop("schema_defs.py")
    elif corruption == "eol":
        files["schema_defs.py"] = files["schema_defs.py"].replace(b"\n", b"\r\n")
    elif corruption == "one_byte":
        files["schema_defs.py"] = b"#" + files["schema_defs.py"][1:]
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    result = complete_primary(tmp_path)
    assert not result["complete_correct"] and not result["full_byte"]["passed"]
    assert result["behavioral"].get("skipped")
    for diff in result["full_byte"]["differences"]:
        if "error" not in diff:
            assert diff["first_differing_byte"] >= 0
            assert diff["expected_sha256"] == hashlib.sha256(reference[diff["filename"]]).hexdigest()
            assert len(diff["expected_context_hex"]) <= 96


def test_behavior_alone_does_not_detect_appended_comment(tmp_path):
    oracle.generate(tmp_path / "workspace")
    with (tmp_path / "workspace/schema_defs.py").open("ab") as out:
        out.write(b"# collateral comment\n")
    result = check("primary", tmp_path / "workspace")
    assert result["passed"] == result["total"] == 20
    assert not oracle.compare(tmp_path / "workspace")["passed"]


def test_source_authentication_precedes_reference_generation(tmp_path):
    for name in oracle.SOURCE_HASHES:
        shutil.copyfile(oracle.ROOT / "primary/fixtures" / name, tmp_path / name)
    (tmp_path / "schema_defs.py").write_bytes(b"untrusted")
    with pytest.raises(ValueError, match="Unauthenticated source"):
        oracle.expected(tmp_path)
