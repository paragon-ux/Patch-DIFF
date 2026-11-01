"""Trusted scalar lifecycle recipe. No model, transport, oracle, retry, or resume."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import errno
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
import hashlib
import json
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
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


def _read_all_fd(fd: int) -> bytes:
    """Read all bytes from an open file descriptor until EOF."""
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_trusted_directory_fd(
    fd: int,
    label: str,
    *,
    allow_sticky_world_writable: bool = False,
) -> tuple[int, int]:
    """Verify directory fd is a live regular directory owned by a trusted user without unsafe world-write permissions."""
    try:
        st = os.fstat(fd)
    except OSError as exc:
        raise PathEscapeError(f"Failed to fstat directory {label}: {exc}") from exc

    if not stat.S_ISDIR(st.st_mode):
        raise PathEscapeError(f"Descriptor for {label} is not a directory.")
    if st.st_nlink < 1:
        raise PathEscapeError(f"Directory {label} has been unlinked (st_nlink={st.st_nlink}).")

    if hasattr(os, "geteuid"):
        euid = os.geteuid()
        if st.st_uid not in (euid, 0):
            raise PathEscapeError(
                f"Directory {label} is owned by untrusted uid {st.st_uid} (expected {euid} or 0)."
            )

    if st.st_mode & stat.S_IWOTH:
        is_sticky = bool(st.st_mode & getattr(stat, "S_ISVTX", 0o1000))
        if not (allow_sticky_world_writable and is_sticky):
            raise PathEscapeError(
                f"Directory {label} is world-writable (mode={ oct(st.st_mode & 0o7777) }); "
                "refusing write-back in untrusted directory."
            )

    return (st.st_dev, st.st_ino)


def _verify_directory_chain(
    root_fd: int,
    root_dev_ino: tuple[int, int],
    chain: list[tuple[int, str, int, tuple[int, int]]],
    *,
    root_path: Path | None = None,
) -> None:
    """Verify that the pinned root and every traversed subdirectory remain attached and un-swapped."""
    cur_st = os.fstat(root_fd)
    if (cur_st.st_dev, cur_st.st_ino) != root_dev_ino or cur_st.st_nlink < 1:
        raise PathEscapeError("Authorized root directory identity changed or was unlinked during write-back.")
    if root_path is not None:
        try:
            path_st = os.lstat(str(root_path))
        except OSError as exc:
            raise PathEscapeError(f"Authorized root path {root_path} vanished during write-back: {exc}") from exc
        if stat.S_ISLNK(path_st.st_mode) or (path_st.st_dev, path_st.st_ino) != root_dev_ino:
            raise PathEscapeError(f"Authorized root {root_path} was replaced or relocated during write-back.")

    for parent_fd, comp_name, child_fd, expected_dev_ino in chain:
        child_fstat = os.fstat(child_fd)
        if (child_fstat.st_dev, child_fstat.st_ino) != expected_dev_ino or child_fstat.st_nlink < 1:
            raise PathEscapeError(f"Directory component {comp_name!r} identity changed or was unlinked.")
        if child_fstat.st_mode & stat.S_IWOTH:
            raise PathEscapeError(f"Directory component {comp_name!r} became world-writable during traversal.")
        try:
            entry_lstat = os.lstat(comp_name, dir_fd=parent_fd)
        except OSError as exc:
            raise PathEscapeError(f"Directory component {comp_name!r} was removed or renamed: {exc}") from exc
        if stat.S_ISLNK(entry_lstat.st_mode) or (entry_lstat.st_dev, entry_lstat.st_ino) != expected_dev_ino:
            raise PathEscapeError(
                f"Directory component {comp_name!r} was swapped or replaced after traversal."
            )
        try:
            dotdot_st = os.stat("..", dir_fd=child_fd)
            parent_st = os.fstat(parent_fd)
            if (dotdot_st.st_dev, dotdot_st.st_ino) != (parent_st.st_dev, parent_st.st_ino):
                raise PathEscapeError(
                    f"Directory component {comp_name!r} parent linkage ('..') no longer matches parent directory."
                )
        except OSError as exc:
            raise PathEscapeError(f"Failed to verify parent linkage for {comp_name!r}: {exc}") from exc


def _acquire_verified_lock_fd(parent_dir_fd: int, lock_name: str) -> tuple[int, tuple[int, int]]:
    """Open and lock .lock-{leaf} with O_NOFOLLOW, regular-file fstat verification, and post-flock inode identity check."""
    if fcntl is None or not hasattr(fcntl, "flock"):
        raise HostWriteBackError("POSIX fcntl.flock writer coordination is required on this platform.")
    if not hasattr(os, "O_NOFOLLOW"):
        raise HostWriteBackError("OS does not support O_NOFOLLOW; refusing unsafe lock marker open.")

    for _attempt in range(3):
        try:
            pre_st = os.lstat(lock_name, dir_fd=parent_dir_fd)
            if stat.S_ISLNK(pre_st.st_mode):
                raise PathEscapeError(f"Lock marker {lock_name!r} is a symlink.")
            if not stat.S_ISREG(pre_st.st_mode):
                raise HostWriteBackError(f"Lock marker {lock_name!r} is not a regular file.")
        except FileNotFoundError:
            pass

        lock_flags = (
            os.O_CREAT
            | os.O_RDWR
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            fd = os.open(lock_name, lock_flags, 0o600, dir_fd=parent_dir_fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PathEscapeError(f"Lock marker {lock_name!r} is a symlink (ELOOP).") from exc
            raise HostWriteBackError(f"Failed to open lock file {lock_name!r}: {exc}") from exc

        try:
            fd_st = os.fstat(fd)
            if not stat.S_ISREG(fd_st.st_mode):
                raise HostWriteBackError(
                    f"Lock marker {lock_name!r} descriptor is not a regular file (mode={oct(fd_st.st_mode)})."
                )
            if hasattr(os, "geteuid") and fd_st.st_uid not in (os.geteuid(), 0):
                raise HostWriteBackError(
                    f"Lock marker {lock_name!r} is owned by untrusted uid {fd_st.st_uid}."
                )

            fcntl.flock(fd, fcntl.LOCK_EX)

            # Verify after acquiring flock that the directory entry still points to this exact open regular file inode
            post_fd_st = os.fstat(fd)
            if post_fd_st.st_nlink < 1:
                os.close(fd)
                continue
            try:
                dir_entry_st = os.lstat(lock_name, dir_fd=parent_dir_fd)
            except FileNotFoundError:
                os.close(fd)
                continue
            if stat.S_ISLNK(dir_entry_st.st_mode):
                raise PathEscapeError(f"Lock marker {lock_name!r} was replaced with a symlink during lock wait.")
            if not stat.S_ISREG(dir_entry_st.st_mode):
                raise HostWriteBackError(f"Lock marker {lock_name!r} was replaced with a non-regular file.")
            if (dir_entry_st.st_dev, dir_entry_st.st_ino) != (post_fd_st.st_dev, post_fd_st.st_ino):
                os.close(fd)
                continue

            return fd, (post_fd_st.st_dev, post_fd_st.st_ino)
        except Exception:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    raise HostWriteBackError(
        f"Lock marker {lock_name!r} inode was repeatedly replaced during lock acquisition (concurrent tampering detected)."
    )


def safe_write_back_file(
    destination_path: Path | str,
    data: bytes,
    *,
    expected_sha256: str,
    preimage_sha256: str | None = None,
    authorized_root: Path | str | None = None,
    allow_unconditional_overwrite: bool = False,
    _after_preimage_hook=None,
) -> Path:
    """Safely and atomically write exported bytes to a local destination file.

    Threat Model & Boundaries (PR23-PLAN-ARCH-002, PR23-R3-SCRIPT-001/003, PR23-R4I-SCRIPT-003):
    - PostgreSQL commit and host filesystem write-back are separate resource boundaries; there is no
      cross-resource distributed transaction between PostgreSQL and the local OS filesystem.
    - Enforces descriptor-relative traversal with O_NOFOLLOW, trusted directory ownership/permission
      checks (rejecting world-writable directories inside authorized_root), parent linkage ('..') and
      (st_dev, st_ino) chain verification before replacement, and O_NOFOLLOW regular-file lock-marker
      inode verification.
    - Writer coordination uses fcntl.flock on the verified lock marker for cooperating host writers,
      plus pre-replace destination (st_dev, st_ino, st_mtime_ns, st_size) and content digest re-verification
      to detect uncooperative concurrent modifications before replacement. Hostile privileged local users or
      kernel-level adversaries who mutate directory hierarchies while bypassing permissions are outside scope
      and cause fail-closed termination where detectable.
    """
    # 1. Pre-write digest verification (PR23-R3-SCRIPT-002)
    if not isinstance(data, (bytes, bytearray)):
        raise HostWriteBackError(f"data must be bytes, got {type(data).__name__}")
    data_bytes = bytes(data)

    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
    ):
        raise HostWriteBackError(f"Invalid expected_sha256 format: {expected_sha256!r}")
    expected_sha256 = expected_sha256.lower()

    data_hash = hashlib.sha256(data_bytes).hexdigest()
    if data_hash != expected_sha256:
        raise HostWriteBackError(
            f"Pre-write digest verification failed: data hash {data_hash} does not match expected_sha256 {expected_sha256}."
        )

    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise HostWriteBackError("Platform lacks required O_NOFOLLOW / O_DIRECTORY descriptor safeguards.")

    # 2. Descriptor-relative traversal (PR23-R3-SCRIPT-001)
    dest = Path(destination_path)
    opened_fds: list[int] = []
    lock_fd: int | None = None
    temp_name: str | None = None
    parent_dir_fd: int | None = None
    root_fd: int | None = None
    root_dev_ino: tuple[int, int] | None = None
    auth_root_resolved: Path | None = None
    dir_chain: list[tuple[int, str, int, tuple[int, int]]] = []

    try:
        if authorized_root is not None:
            raw_auth_root = Path(authorized_root)
            if raw_auth_root.is_symlink():
                raise PathEscapeError(f"Authorized root {raw_auth_root} must not be a symlink.")
            auth_root = raw_auth_root.resolve()
            auth_root_resolved = auth_root
            if not auth_root.is_dir():
                raise PathEscapeError(f"Authorized root {auth_root} does not exist or is not a directory.")

            if dest.is_absolute():
                try:
                    lexical_rel = dest.relative_to(auth_root)
                except ValueError:
                    try:
                        lexical_rel = dest.relative_to(raw_auth_root)
                    except ValueError:
                        raise PathEscapeError(f"Destination {dest} is outside authorized root {auth_root}.")
                rel_parts = lexical_rel.parts
            else:
                rel_parts = dest.parts

            if any(p == ".." for p in rel_parts):
                raise PathEscapeError(f"Destination {dest} contains parent traversal ('..').")

            clean_parts = [p for p in rel_parts if p not in ("", ".")]
            if not clean_parts:
                raise PathEscapeError(f"Destination {dest} specifies root directory, not a file.")

            dir_components = clean_parts[:-1]
            leaf_name = clean_parts[-1]

            try:
                auth_flags = (
                    os.O_DIRECTORY
                    | os.O_RDONLY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0)
                )
                auth_fd = os.open(str(auth_root), auth_flags)
            except OSError as exc:
                raise PathEscapeError(f"Cannot open authorized root {auth_root}: {exc}") from exc
            opened_fds.append(auth_fd)
            root_fd = auth_fd
            root_dev_ino = _verify_trusted_directory_fd(
                auth_fd,
                f"authorized_root({auth_root})",
                allow_sticky_world_writable=False,
            )
            current_fd = auth_fd

            for comp in dir_components:
                if "/" in comp or "\\" in comp or comp in (".", ".."):
                    raise PathEscapeError(f"Invalid path component: {comp!r}")

                comp_flags = (
                    os.O_DIRECTORY
                    | os.O_RDONLY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0)
                )
                try:
                    next_fd = os.open(comp, comp_flags, dir_fd=current_fd)
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        try:
                            st = os.lstat(comp, dir_fd=current_fd)
                            if stat.S_ISLNK(st.st_mode):
                                raise PathEscapeError(f"Path component {comp!r} is a symlink.") from exc
                        except OSError:
                            pass
                        raise PathEscapeError(f"Path component {comp!r} is not a directory.") from exc
                    elif exc.errno == errno.ENOENT:
                        try:
                            os.mkdir(comp, mode=0o755, dir_fd=current_fd)
                        except FileExistsError:
                            pass
                        except OSError as me:
                            raise HostWriteBackError(f"Failed to create directory {comp!r}: {me}") from me
                        try:
                            next_fd = os.open(comp, comp_flags, dir_fd=current_fd)
                        except OSError as oe:
                            raise PathEscapeError(f"Failed to open created directory {comp!r}: {oe}") from oe
                    else:
                        raise PathEscapeError(f"Error traversing component {comp!r}: {exc}") from exc

                opened_fds.append(next_fd)
                comp_dev_ino = _verify_trusted_directory_fd(
                    next_fd,
                    f"component({comp})",
                    allow_sticky_world_writable=False,
                )
                dir_chain.append((current_fd, comp, next_fd, comp_dev_ino))
                current_fd = next_fd

            parent_dir_fd = current_fd
            resolved_dest = auth_root.joinpath(*clean_parts)
        else:
            if any(p == ".." for p in dest.parts):
                raise PathEscapeError(f"Destination {dest} contains parent traversal ('..').")
            abs_dest = dest if dest.is_absolute() else (Path.cwd() / dest)
            dest_parent = abs_dest.parent
            if dest_parent.is_symlink():
                raise PathEscapeError(f"Destination parent {dest_parent} is a symlink.")
            dest_parent.mkdir(parents=True, exist_ok=True)
            parent_flags = (
                os.O_DIRECTORY
                | os.O_RDONLY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                parent_dir_fd = os.open(str(dest_parent), parent_flags)
            except OSError as exc:
                raise PathEscapeError(f"Cannot open destination parent {dest_parent}: {exc}") from exc
            opened_fds.append(parent_dir_fd)
            root_fd = parent_dir_fd
            root_dev_ino = _verify_trusted_directory_fd(
                parent_dir_fd,
                f"destination_parent({dest_parent})",
                allow_sticky_world_writable=True,
            )
            auth_root_resolved = dest_parent.resolve()
            leaf_name = abs_dest.name
            resolved_dest = auth_root_resolved / leaf_name

        if "/" in leaf_name or "\\" in leaf_name or leaf_name in (".", ".."):
            raise PathEscapeError(f"Invalid destination leaf name: {leaf_name!r}")

        # 3. Writer coordination & hardened lock marker (PR23-R3-SCRIPT-003, PR23-R4I-SCRIPT-003)
        lock_name = f".lock-{leaf_name}"
        lock_fd, lock_dev_ino = _acquire_verified_lock_fd(parent_dir_fd, lock_name)
        opened_fds.append(lock_fd)

        # Verify directory hierarchy integrity after acquiring lock
        assert root_fd is not None and root_dev_ino is not None
        _verify_directory_chain(root_fd, root_dev_ino, dir_chain, root_path=auth_root_resolved)

        # 4. Leaf validation & preimage check (PR23-R3-SCRIPT-005) - held under lock!
        try:
            st = os.lstat(leaf_name, dir_fd=parent_dir_fd)
            dest_exists = True
        except FileNotFoundError:
            dest_exists = False
            st = None

        preimage_stat_sig: tuple[int, int, int, int] | None = None
        if dest_exists:
            assert st is not None
            if stat.S_ISLNK(st.st_mode):
                raise PathEscapeError(f"Destination {leaf_name!r} is a symlink.")
            if stat.S_ISDIR(st.st_mode):
                raise HostWriteBackError(f"Destination {leaf_name!r} is a directory, not a file.")
            if not stat.S_ISREG(st.st_mode):
                raise HostWriteBackError(f"Destination {leaf_name!r} is not a regular file.")

            if preimage_sha256 is None and not allow_unconditional_overwrite:
                raise PreimageMismatchError(
                    f"Destination file {resolved_dest} already exists; preimage_sha256 is required unless allow_unconditional_overwrite=True"
                )

            read_fd = os.open(
                leaf_name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_dir_fd,
            )
            try:
                read_st = os.fstat(read_fd)
                if not stat.S_ISREG(read_st.st_mode) or (read_st.st_dev, read_st.st_ino) != (st.st_dev, st.st_ino):
                    raise PreimageMismatchError(f"Destination {resolved_dest} changed during preimage open.")
                preimage_stat_sig = (read_st.st_dev, read_st.st_ino, read_st.st_mtime_ns, read_st.st_size)
                if preimage_sha256 is not None:
                    existing_bytes = _read_all_fd(read_fd)
                    actual_preimage = hashlib.sha256(existing_bytes).hexdigest()
                    if actual_preimage != preimage_sha256.lower():
                        raise PreimageMismatchError(
                            f"Destination {resolved_dest} on disk has hash {actual_preimage}, expected {preimage_sha256}."
                        )
            finally:
                os.close(read_fd)
        else:
            if preimage_sha256 is not None:
                raise PreimageMismatchError(
                    f"Destination file {resolved_dest} does not exist, but preimage_sha256 was expected."
                )

        if _after_preimage_hook is not None:
            _after_preimage_hook()

        # 5. Write to temporary file in pinned parent directory
        temp_name = f".tmp-{leaf_name}-{uuid.uuid4().hex}"
        temp_flags = (
            os.O_CREAT
            | os.O_EXCL
            | os.O_RDWR
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        temp_fd = os.open(temp_name, temp_flags, 0o600, dir_fd=parent_dir_fd)
        try:
            view = memoryview(data_bytes)
            written = 0
            while written < len(data_bytes):
                n = os.write(temp_fd, view[written:])
                written += n
            os.fsync(temp_fd)

            os.lseek(temp_fd, 0, os.SEEK_SET)
            written_bytes = _read_all_fd(temp_fd)
            if hashlib.sha256(written_bytes).hexdigest() != expected_sha256:
                raise HostWriteBackError(
                    f"Temporary file {temp_name} failed pre-replace digest verification."
                )
        finally:
            os.close(temp_fd)

        # 6. Pre-replace containment & concurrent-modification verification (PR23-R3-SCRIPT-001/003, PR23-R4I-SCRIPT-003)
        _verify_directory_chain(root_fd, root_dev_ino, dir_chain, root_path=auth_root_resolved)

        try:
            lock_check_st = os.lstat(lock_name, dir_fd=parent_dir_fd)
        except OSError as exc:
            raise HostWriteBackError(f"Lock marker {lock_name!r} vanished before replacement: {exc}") from exc
        if not stat.S_ISREG(lock_check_st.st_mode) or (lock_check_st.st_dev, lock_check_st.st_ino) != lock_dev_ino:
            raise HostWriteBackError(f"Lock marker {lock_name!r} identity changed before replacement.")

        if not allow_unconditional_overwrite:
            try:
                cur_dest_st = os.lstat(leaf_name, dir_fd=parent_dir_fd)
                cur_exists = True
            except FileNotFoundError:
                cur_dest_st = None
                cur_exists = False

            if cur_exists != dest_exists:
                raise PreimageMismatchError(
                    f"Destination {resolved_dest} existence changed concurrently before replacement."
                )
            if cur_exists and cur_dest_st is not None:
                if stat.S_ISLNK(cur_dest_st.st_mode):
                    raise PathEscapeError(f"Destination {leaf_name!r} was replaced with a symlink before replacement.")
                cur_sig = (cur_dest_st.st_dev, cur_dest_st.st_ino, cur_dest_st.st_mtime_ns, cur_dest_st.st_size)
                if cur_sig != preimage_stat_sig:
                    raise PreimageMismatchError(
                        f"Destination {resolved_dest} was modified concurrently by an external writer before replacement."
                    )
                if preimage_sha256 is not None:
                    recheck_fd = os.open(
                        leaf_name,
                        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                        dir_fd=parent_dir_fd,
                    )
                    try:
                        recheck_bytes = _read_all_fd(recheck_fd)
                    finally:
                        os.close(recheck_fd)
                    if hashlib.sha256(recheck_bytes).hexdigest() != preimage_sha256.lower():
                        raise PreimageMismatchError(
                            f"Destination {resolved_dest} content changed concurrently before replacement."
                        )

        # 7. Atomic replacement
        os.replace(temp_name, leaf_name, src_dir_fd=parent_dir_fd, dst_dir_fd=parent_dir_fd)
        temp_name = None

        # 8. Parent directory fsync
        if hasattr(os, "fsync"):
            try:
                os.fsync(parent_dir_fd)
            except OSError:
                pass

        # 9. Post-write verification under lock (defense in depth)
        verify_fd = os.open(
            leaf_name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_dir_fd,
        )
        try:
            installed_bytes = _read_all_fd(verify_fd)
            installed_hash = hashlib.sha256(installed_bytes).hexdigest()
            if installed_hash != expected_sha256:
                raise HostWriteBackError(
                    f"Installed file {resolved_dest} hash {installed_hash} does not match expected {expected_sha256}."
                )
        finally:
            os.close(verify_fd)

        return resolved_dest

    except Exception:
        if temp_name is not None and parent_dir_fd is not None:
            try:
                os.unlink(temp_name, dir_fd=parent_dir_fd)
            except OSError:
                pass
        raise
    finally:
        if lock_fd is not None:
            try:
                if fcntl is not None and hasattr(fcntl, "flock"):
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        for fd in reversed(opened_fds):
            try:
                os.close(fd)
            except OSError:
                pass


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
    allow_unconditional_overwrite: bool = False,
    raise_on_disk_error: bool = False,
) -> dict:
    """Execute single-target atomic finalization via patchdiff_finalize_target and truthful disk write-back.

    Separates database outcome ('db_status') from host disk outcome ('disk_status').
    For deferred content delivery (>1 MiB), pages finalized chunks via patchdiff_read_finalized_export,
    verifies complete assembled SHA-256 and byte length, and performs atomic write-back.
    Never reports false success when disk write-back is unfulfilled.
    """
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
    db_status = receipt.get("status")
    receipt["db_status"] = db_status

    if db_status != "ok":
        receipt["disk_status"] = "skipped"
        receipt["written_destination"] = None
        return receipt

    if destination_path is None:
        receipt["disk_status"] = "skipped"
        receipt["written_destination"] = None
        return receipt

    # PR23-R3-SCRIPT-004: Handle write-back (Case A: inline, Case B: deferred)
    exported_content = receipt.get("exported_content")
    if exported_content is not None:
        raw_bytes = exported_content.encode("utf-8")
        expected_sha256 = receipt.get("content_sha256")
        if expected_sha256 is None:
            expected_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    else:
        # Case B: Deferred delivery (>1 MiB export)
        finalization_id = receipt.get("finalization_id")
        if not finalization_id:
            msg = "Finalize receipt missing finalization_id for deferred export retrieval"
            receipt["disk_status"] = "error"
            receipt["written_destination"] = None
            receipt["status"] = "error"
            receipt["disk_error"] = msg
            if raise_on_disk_error:
                raise HostWriteBackError(msg)
            return receipt

        chunks: list[bytes] = []
        offset = 0
        limit = 262144
        expected_sha256 = receipt.get("content_sha256")
        expected_bytes = receipt.get("content_bytes")

        try:
            while True:
                read_res = call_tool(
                    "patchdiff_read_finalized_export",
                    finalization_id=finalization_id,
                    target_file_id=target_file_id,
                    offset=offset,
                    limit=limit,
                )
                if not isinstance(read_res, dict) or read_res.get("status") != "ok":
                    detail = (
                        read_res.get("failure_detail")
                        or read_res.get("error")
                        or read_res.get("status")
                        if isinstance(read_res, dict)
                        else str(read_res)
                    )
                    raise HostWriteBackError(f"Deferred read failed at offset {offset}: {detail}")

                content_b64 = read_res.get("content_base64")
                if content_b64 is None:
                    raise HostWriteBackError(f"Deferred export response missing content_base64 at offset {offset}")

                try:
                    chunk = base64.b64decode(content_b64, validate=True)
                except Exception as b64_err:
                    raise HostWriteBackError(f"Invalid base64 payload at offset {offset}: {b64_err}") from b64_err

                chunks.append(chunk)

                if not read_res.get("has_more"):
                    break

                next_offset = read_res.get("next_offset")
                if next_offset is None or next_offset <= offset:
                    raise HostWriteBackError(
                        f"Invalid pagination response: next_offset={next_offset} with offset={offset}"
                    )
                offset = next_offset

            raw_bytes = b"".join(chunks)

            # Assembled integrity verification
            computed_sha = hashlib.sha256(raw_bytes).hexdigest()
            if expected_sha256 is not None and computed_sha != expected_sha256:
                raise HostWriteBackError(
                    f"Deferred assembled bytes SHA-256 {computed_sha} does not match expected {expected_sha256}"
                )

            if expected_bytes is not None and len(raw_bytes) != expected_bytes:
                raise HostWriteBackError(
                    f"Deferred assembled bytes length {len(raw_bytes)} does not match expected {expected_bytes}"
                )

        except Exception as exc:
            receipt["disk_status"] = "error"
            receipt["written_destination"] = None
            receipt["status"] = "error"
            receipt["disk_error"] = str(exc)
            if raise_on_disk_error:
                raise
            return receipt

    try:
        written_path = safe_write_back_file(
            destination_path,
            raw_bytes,
            expected_sha256=expected_sha256,
            preimage_sha256=preimage_sha256,
            authorized_root=authorized_root,
            allow_unconditional_overwrite=allow_unconditional_overwrite,
        )
        receipt["disk_status"] = "written"
        receipt["written_destination"] = str(written_path)
        receipt["status"] = "ok"
        return receipt
    except Exception as exc:
        receipt["disk_status"] = "error"
        receipt["written_destination"] = None
        receipt["status"] = "error"
        receipt["disk_error"] = str(exc)
        if raise_on_disk_error:
            raise
        return receipt

