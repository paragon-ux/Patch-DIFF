"""Trusted scalar lifecycle recipe. No model, transport, oracle, retry, or resume."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import uuid


class _TargetFailure(Exception):
    pass


def _require(condition, message):
    if not condition:
        raise _TargetFailure(message)


def _write_new(path, data):
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        if created:
            # A failed final report must not masquerade as a complete receipt.
            try:
                path.unlink()
            except OSError:
                pass
        raise


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("ascii")


def _manifest(targets):
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a nonempty list of trusted accepted receipts")
    result, ids, names = [], set(), set()
    for item in targets:
        item = dict(item)
        for key in ("target_file_id", "accepted_pdcp_log_id"):
            item[key] = str(uuid.UUID(item[key]))
        name = item["filename"]
        if (not isinstance(name, str) or not name or name in {".", ".."}
                or PurePosixPath(name).name != name or PureWindowsPath(name).name != name
                or PureWindowsPath(name).is_reserved() or name.endswith((".", " "))
                or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in name)):
            raise ValueError("filename must be a safe Windows/POSIX basename")
        name.encode("utf-8")
        version = item["expected_target_version"]
        if isinstance(version, bool) or not isinstance(version, int) or not 0 <= version <= 2**63 - 1:
            raise ValueError("invalid expected_target_version")
        hash_ = item["expected_current_hash"]
        if not isinstance(hash_, str) or not re.fullmatch("[0-9a-f]{64}", hash_):
            raise ValueError("invalid expected_current_hash")
        if item["target_file_id"] in ids or name.casefold() in names:
            raise ValueError("duplicate target or case-insensitive filename")
        ids.add(item["target_file_id"])
        names.add(name.casefold())
        result.append(item)
    return result


def finalize_targets(call_tool, targets, output_dir) -> dict:
    """Finalize trusted accepted states once; caller owns finite RPC deadlines.

    call_tool(name, **arguments) returns a decoded domain payload or raises.
    A SAVE dispatch without a valid durable receipt is uncertain, never retried.
    Evidence failures return incomplete state; results.json is then best-effort.
    """
    targets = _manifest(targets)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    (root / "exports").mkdir()
    _write_new(root / "manifest.json", _json_bytes(targets))
    report = {"status": "failed", "targets": [
        {"filename": item["filename"], "target_file_id": item["target_file_id"],
         "accepted_pdcp_log_id": item["accepted_pdcp_log_id"], "status": "not_attempted", "phase": None}
        for item in targets]}

    def event(kind, name, arguments=None, response=None):
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "kind": kind, "tool": name}
        if arguments is not None:
            entry["arguments"] = arguments
        if response is not None:
            entry["response"] = response
        with (root / "events.jsonl").open("ab") as stream:
            stream.write(json.dumps(entry, ensure_ascii=True).encode("ascii") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())

    for item, outcome in zip(targets, report["targets"]):
        tid, version, hash_ = item["target_file_id"], item["expected_target_version"], item["expected_current_hash"]
        dispatched = confirmed = False
        outcome["phase"] = "save"
        try:
            arguments = {"target_file_id": tid, "expected_target_version": version, "expected_current_hash": hash_}
            event("save_pending", "patchdiff_save", arguments)
            dispatched = True
            saved = call_tool("patchdiff_save", **arguments)
            event("response", "patchdiff_save", response=saved)
            if saved.get("status") in {"rejected", "invalid_argument", "not_found"} and saved.get("target_file_id") == tid:
                raise _TargetFailure(f"SAVE rejected: {saved}")
            if not (saved.get("status") == "saved" and saved.get("target_file_id") == tid
                    and saved.get("version") == version and saved.get("current_hash") == hash_):
                raise RuntimeError("Malformed or mismatched SAVE receipt")
            identities = {key: str(uuid.UUID(saved[key])) for key in (
                "snapshot_id", "closed_editing_cycle_id", "new_editing_cycle_id")}
            event("save_confirmed", "patchdiff_save", response=saved)
            confirmed = True
            outcome.update(identities)

            outcome["phase"] = "replay"
            event("request", "patchdiff_replay", {"target_file_id": tid})
            replay = call_tool("patchdiff_replay", target_file_id=tid)
            event("response", "patchdiff_replay", response=replay)
            checks = replay.get("materialized_state_checks") or {}
            _require(replay.get("status") == "success" and replay.get("target_file_id") == tid
                     and replay.get("materialized_state_matches") is True
                     and all(checks.get(key) is True for key in (
                         "content_matches", "stored_hash_matches", "recomputed_hash_matches", "version_matches"))
                     and replay.get("reconstructed_version") == replay.get("current_version") == version
                     and replay.get("reconstructed_hash") == replay.get("current_hash") == hash_,
                     "Replay did not verify the expected materialized state")
            outcome["replay_checks"] = checks

            outcome["phase"] = "export"
            arguments = {"target_file_id": tid, "format": "canonical_lf"}
            event("request", "patchdiff_export_target", arguments)
            exported = call_tool("patchdiff_export_target", **arguments)
            event("response", "patchdiff_export_target", response=exported)
            _require(exported.get("status") == "ok" and exported.get("filename") == item["filename"]
                     and exported.get("version") == version and exported.get("format") == "canonical_lf"
                     and exported.get("hash") == exported.get("current_hash") == hash_
                     and exported.get("content_sha256") == hash_ and isinstance(exported.get("content"), str),
                     "Export receipt does not match the expected state")
            data = exported["content"].encode("utf-8")
            _require(b"\r" not in data and hashlib.sha256(data).hexdigest() == hash_, "Export bytes/hash mismatch")
            _write_new(root / "exports" / item["filename"], data)
            outcome.update(status="complete", export_sha256=hash_)
        except _TargetFailure as exc:
            outcome.update(status="failed", error=str(exc))
        except Exception as exc:
            outcome.update(status="save_uncertain" if dispatched and not confirmed else "failed", error=str(exc))
            break

    statuses = {item["status"] for item in report["targets"]}
    report["status"] = "uncertain" if "save_uncertain" in statuses else "complete" if statuses == {"complete"} else "failed"
    try:
        _write_new(root / "results.json", _json_bytes(report))
    except OSError as exc:
        report.update(status="uncertain" if "save_uncertain" in statuses else "failed",
                      evidence_error=str(exc), phase="evidence")
    return report
