"""Trusted scalar lifecycle recipe. No model, transport, oracle, retry, or resume."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import ntpath
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
        is_reserved = ntpath.isreserved(name) if hasattr(ntpath, "isreserved") else PureWindowsPath(name).is_reserved()
        if (not isinstance(name, str) or not name or name in {".", ".."}
                or PurePosixPath(name).name != name or PureWindowsPath(name).name != name
                or is_reserved or name.endswith((".", " "))
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


class HostWriteBackError(Exception):
    """Host disk write-back failure."""


class PreimageMismatchError(HostWriteBackError):
    """Destination file on disk does not match the expected preimage hash."""


class PathEscapeError(HostWriteBackError):
    """Target destination escapes authorized directory boundary."""


def safe_write_back_file(
    destination_path: Path | str,
    data: bytes,
    *,
    expected_sha256: str,
    preimage_sha256: str | None = None,
    authorized_root: Path | str | None = None,
) -> Path:
    """Safely and atomically write exported bytes to a local destination file.

    Guarantees:
    1. Authorized directory containment: checks realpath against authorized_root if provided.
    2. Symlink escape detection: rejects target paths that resolve outside authorized root.
    3. Preimage conflict check: if destination file exists and preimage_sha256 is supplied,
       verifies existing disk bytes match preimage; rejects with PreimageMismatchError if changed.
    4. Same-directory temp file + fsync: writes data to temp file in destination's directory.
    5. Atomic replace: renames temp file to destination via os.replace.
    6. Directory fsync: syncs parent directory on POSIX systems where supported.
    7. Post-write verification: reads back destination and confirms sha256 matches expected_sha256.
    """
    dest = Path(destination_path).resolve()
    if authorized_root is not None:
        auth_root = Path(authorized_root).resolve()
        try:
            dest.relative_to(auth_root)
        except ValueError:
            raise PathEscapeError(f"Destination {dest} is outside authorized root {auth_root}.")

    # Preimage check
    if dest.is_file():
        if preimage_sha256 is not None:
            actual_preimage = hashlib.sha256(dest.read_bytes()).hexdigest()
            if actual_preimage != preimage_sha256:
                raise PreimageMismatchError(
                    f"Destination {dest} on disk has hash {actual_preimage}, expected {preimage_sha256}."
                )

    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest.parent / f".tmp-{dest.name}-{uuid.uuid4().hex}"

    try:
        with temp_path.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temp_path, dest)

        # Sync parent directory on POSIX
        if hasattr(os, "O_DIRECTORY") and hasattr(os, "fsync"):
            try:
                dir_fd = os.open(str(dest.parent), os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass  # Some filesystems or OSes do not support directory fsync

        # Post-write byte & hash verification
        installed_bytes = dest.read_bytes()
        installed_hash = hashlib.sha256(installed_bytes).hexdigest()
        if installed_hash != expected_sha256:
            raise HostWriteBackError(
                f"Installed file {dest} hash {installed_hash} does not match expected {expected_sha256}."
            )
        return dest
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def finalize_single_target(
    call_tool,
    *,
    target_file_id: str,
    client_request_id: str,
    expected_target_version: int | None = None,
    expected_current_hash: str | None = None,
    format: str = "original_eol",
    destination_path: Path | str | None = None,
    preimage_sha256: str | None = None,
    authorized_root: Path | str | None = None,
) -> dict:
    """Execute single-target atomic finalization via patchdiff_finalize_target and optional disk write-back."""
    args = {
        "target_file_id": target_file_id,
        "client_request_id": client_request_id,
        "format": format,
    }
    if expected_target_version is not None:
        args["expected_target_version"] = expected_target_version
    if expected_current_hash is not None:
        args["expected_current_hash"] = expected_current_hash

    receipt = call_tool("patchdiff_finalize_target", **args)
    if receipt.get("status") != "ok":
        return receipt

    if destination_path is not None and receipt.get("exported_content") is not None:
        raw_bytes = receipt["exported_content"].encode("utf-8")
        safe_write_back_file(
            destination_path,
            raw_bytes,
            expected_sha256=receipt["content_sha256"],
            preimage_sha256=preimage_sha256,
            authorized_root=authorized_root,
        )
        receipt["written_destination"] = str(destination_path)
    return receipt

