import copy
import hashlib
import json
import uuid

import pytest

from examples import host_finalize as finalizer


def setup_targets(count=1, filename="results.json"):
    content = "changed 🌟\n"
    targets = [{"filename": filename if i == 0 else f"target{i}.txt", "target_file_id": str(uuid.uuid4()),
                "accepted_pdcp_log_id": str(uuid.uuid4()), "expected_target_version": 1,
                "expected_current_hash": hashlib.sha256(content.encode()).hexdigest()} for i in range(count)]
    calls = []
    def call(name, **args):
        calls.append((name, args))
        item = next(t for t in targets if t["target_file_id"] == args["target_file_id"])
        common = {"target_file_id": item["target_file_id"], "current_hash": item["expected_current_hash"]}
        if name == "patchdiff_save":
            return {**common, "status": "saved", "version": 1,
                    **{k: str(uuid.uuid4()) for k in ("snapshot_id", "closed_editing_cycle_id", "new_editing_cycle_id")}}
        if name == "patchdiff_replay":
            return {**common, "status": "success", "materialized_state_matches": True,
                    "reconstructed_version": 1, "current_version": 1, "reconstructed_hash": common["current_hash"],
                    "materialized_state_checks": {k: True for k in (
                        "content_matches", "stored_hash_matches", "recomputed_hash_matches", "version_matches")}}
        return {"status": "ok", "filename": item["filename"], "content": content, "version": 1,
                "current_hash": common["current_hash"], "hash": common["current_hash"],
                "content_sha256": common["current_hash"], "format": "canonical_lf"}
    return targets, calls, call


def test_success_separates_export_names_from_control_artifacts_and_refuses_rerun(tmp_path):
    targets, calls, call = setup_targets(2)
    result = finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert result["status"] == "complete" and len(calls) == 6
    assert json.loads((tmp_path / "run/results.json").read_text()) == result
    assert (tmp_path / "run/exports/results.json").read_bytes() == "changed 🌟\n".encode()
    events = [json.loads(l) for l in (tmp_path / "run/events.jsonl").read_text().splitlines()]
    assert sum(e["kind"] == "save_pending" for e in events) == 2
    with pytest.raises(FileExistsError): finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert len(calls) == 6


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "CON", "nul.txt", "COM1.py", "x.", "x ", "a:b", "x\x00"])
def test_unsafe_names_fail_before_any_call(tmp_path, name):
    targets, calls, call = setup_targets(filename=name)
    with pytest.raises(ValueError): finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert not calls and not (tmp_path / "run").exists()


@pytest.mark.parametrize("field,value", [("expected_target_version", True), ("expected_target_version", -1),
    ("expected_current_hash", "bad"), ("accepted_pdcp_log_id", "bad")])
def test_invalid_manifest_fails_before_any_call(tmp_path, field, value):
    targets, calls, call = setup_targets()
    targets[0][field] = value
    with pytest.raises(ValueError): finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert not calls


def test_case_insensitive_duplicate_names_preflight_all_targets(tmp_path):
    targets, calls, call = setup_targets(2)
    targets[1]["filename"] = "RESULTS.JSON"
    with pytest.raises(ValueError): finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert not calls


@pytest.mark.parametrize("failure", ["lost", "malformed", "rejected", "replay", "export"])
def test_failure_paths_do_not_retry_save_or_claim_success(tmp_path, failure):
    targets, calls, call = setup_targets(2)
    def faulty(name, **args):
        result = call(name, **args)
        if args["target_file_id"] == targets[0]["target_file_id"]:
            if name == "patchdiff_save":
                if failure == "lost": raise TimeoutError("response lost")
                if failure == "malformed": return {"status": "saved"}
                if failure == "rejected": return {"status": "rejected", "target_file_id": args["target_file_id"]}
            if name == "patchdiff_replay" and failure == "replay":
                result["materialized_state_checks"]["content_matches"] = False
            if name == "patchdiff_export_target" and failure == "export": result["content"] += "collateral"
        return result
    result = finalizer.finalize_targets(faulty, targets, tmp_path / "run")
    uncertain = failure in {"lost", "malformed"}
    assert result["status"] == ("uncertain" if uncertain else "failed")
    assert result["targets"][0]["status"] == ("save_uncertain" if uncertain else "failed")
    assert result["targets"][1]["status"] == ("not_attempted" if uncertain else "complete")
    assert sum(name == "patchdiff_save" and args["target_file_id"] == targets[0]["target_file_id"] for name, args in calls) == 1
    if failure in {"lost", "malformed", "rejected"}:
        assert not any(name != "patchdiff_save" and args["target_file_id"] == targets[0]["target_file_id"] for name, args in calls)


def test_failed_save_receipt_fsync_preserves_pending_and_stops_calls(tmp_path, monkeypatch):
    targets, calls, call = setup_targets(2)
    fsync = finalizer.os.fsync
    counter = 0
    def fail_receipt(fd):
        nonlocal counter
        counter += 1
        if counter == 3: raise OSError("disk failure after SAVE")
        fsync(fd)
    monkeypatch.setattr(finalizer.os, "fsync", fail_receipt)
    result = finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert result["status"] == "uncertain" and len(calls) == 1
    assert '"save_pending"' in (tmp_path / "run/events.jsonl").read_text()


@pytest.mark.parametrize("failed_name", ["results.json", "exports/results.json"])
def test_evidence_failure_returns_incomplete_without_false_receipt(tmp_path, monkeypatch, failed_name):
    targets, calls, call = setup_targets(2)
    write = finalizer._write_new
    def failing(path, data):
        if path.relative_to(tmp_path / "run").as_posix() == failed_name: raise OSError("disk full")
        write(path, data)
    monkeypatch.setattr(finalizer, "_write_new", failing)
    result = finalizer.finalize_targets(call, targets, tmp_path / "run")
    assert result["status"] == "failed"
    if failed_name == "results.json":
        assert result["evidence_error"] and not (tmp_path / "run/results.json").exists()
    else:
        assert result["targets"][1]["status"] == "not_attempted" and len(calls) == 3
