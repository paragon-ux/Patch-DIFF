"""Trusted scalar lifecycle and host write-back recipe.

Implements PR #23 Stage D (PR23-PLAN-ARCH-002, PR23-R3-SCRIPT-001, PR23-R3-SCRIPT-003, PR23-R5-SCRIPT-002):
- PostgreSQL commit and host filesystem write-back are separate resource boundaries.
- Cooperative-write-only POSIX trusted-tree contract:
  - ``safe_write_back_file`` requires an explicit ``authorized_root`` owned by the invoking
    operator UID with private permissions (``0700`` or ``0750``, zero group/world write bits).
  - ``authorized_root`` is pinned by walking from ``/`` through every lexical ancestor
    using ``openat`` + ``O_DIRECTORY | O_NOFOLLOW`` (allowing a root-owned sticky ``/tmp``
    ancestor only *outside* ``authorized_root``, and rejecting any other group/world-writable
    ancestor or any writable interior directory).
  - Newly created interior directories use mode ``0700``.
  - Permanent per-file ``.lock-<leaf>`` marker (mode ``<= 0600``, ``st_nlink == 1``, regular file,
    never unlinked or replaced during normal operation) verified before and after blocking
    ``flock(LOCK_EX)``.
  - An uncooperative process running as the same operator UID that ignores ``flock`` cannot be
    protected by portable POSIX ``rename`` and is outside this contract; the editor/model OS
    principals are excluded by OS permission boundaries (Stage B).
  - Post-rename directory ``fsync`` failure is never swallowed: it raises
    ``DurabilityUncertainError`` (``installed=True, durability='uncertain'``) and maps to
    ``disk_status='durability_uncertain', status='error', reconciliation_required=True``.
"""

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
from typing import Any
import uuid


class _TargetFailure(Exception):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _TargetFailure(message)


def _write_new(path: Path, data: bytes) -> None:
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        if created:
            try:
                path.unlink()
            except OSError:
                pass
        raise


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("ascii")


def _manifest(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a nonempty list of trusted accepted receipts")
    result, ids, names = [], set(), set()
    for item in targets:
        item = dict(item)
        for key in ("target_file_id", "accepted_pdcp_log_id"):
            item[key] = str(uuid.UUID(item[key]))
        name = item["filename"]
        is_reserved = ntpath.isreserved(name) if hasattr(ntpath, "isreserved") else PureWindowsPath(name).is_reserved()
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or PurePosixPath(name).name != name
            or PureWindowsPath(name).name != name
            or is_reserved
            or name.endswith((".", " "))
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in name)
        ):
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
    """Finalize trusted accepted states once; caller owns finite RPC deadlines."""
    targets = _manifest(targets)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    (root / "exports").mkdir()
    _write_new(root / "manifest.json", _json_bytes(targets))
    report = {
        "status": "failed",
        "targets": [
            {
                "filename": item["filename"],
                "target_file_id": item["target_file_id"],
                "accepted_pdcp_log_id": item["accepted_pdcp_log_id"],
                "status": "not_attempted",
                "phase": None,
            }
            for item in targets
        ],
    }

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
            if not (
                saved.get("status") == "saved"
                and saved.get("target_file_id") == tid
                and saved.get("version") == version
                and saved.get("current_hash") == hash_
            ):
                raise RuntimeError("Malformed or mismatched SAVE receipt")
            identities = {
                key: str(uuid.UUID(saved[key]))
                for key in ("snapshot_id", "closed_editing_cycle_id", "new_editing_cycle_id")
            }
            event("save_confirmed", "patchdiff_save", response=saved)
            confirmed = True
            outcome.update(identities)

            outcome["phase"] = "replay"
            event("request", "patchdiff_replay", {"target_file_id": tid})
            replay = call_tool("patchdiff_replay", target_file_id=tid)
            event("response", "patchdiff_replay", response=replay)
            checks = replay.get("materialized_state_checks") or {}
            _require(
                replay.get("status") == "success"
                and replay.get("target_file_id") == tid
                and replay.get("materialized_state_matches") is True
                and all(
                    checks.get(key) is True
                    for key in (
                        "content_matches",
                        "stored_hash_matches",
                        "recomputed_hash_matches",
                        "version_matches",
                    )
                )
                and replay.get("reconstructed_version") == replay.get("current_version") == version
                and replay.get("reconstructed_hash") == replay.get("current_hash") == hash_,
                "Replay did not verify the expected materialized state",
            )
            outcome["replay_checks"] = checks

            outcome["phase"] = "export"
            arguments = {"target_file_id": tid, "format": "canonical_lf"}
            event("request", "patchdiff_export_target", arguments)
            exported = call_tool("patchdiff_export_target", **arguments)
            event("response", "patchdiff_export_target", response=exported)
            _require(
                exported.get("status") == "ok"
                and exported.get("filename") == item["filename"]
                and exported.get("version") == version
                and exported.get("format") == "canonical_lf"
                and exported.get("hash") == exported.get("current_hash") == hash_
                and exported.get("content_sha256") == hash_
                and isinstance(exported.get("content"), str),
                "Export receipt does not match the expected state",
            )
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
        report.update(
            status="uncertain" if "save_uncertain" in statuses else "failed",
            evidence_error=str(exc),
            phase="evidence",
        )
    return report


class HostWriteBackError(Exception):
    """Host disk write-back failure."""

    installed: bool = False
    durability: str = "not_installed"


class PreimageMismatchError(HostWriteBackError):
    """Destination file on disk does not match the expected preimage hash."""


class PathEscapeError(HostWriteBackError):
    """Target destination escapes authorized directory boundary or violates private-tree permissions."""


class DurabilityUncertainError(HostWriteBackError):
    """Raised when atomic rename succeeded on disk, but post-rename directory fsync failed (PR23-R5-SCRIPT-002)."""

    installed: bool = True
    durability: str = "uncertain"

    def __init__(
        self,
        message: str,
        *,
        destination_path: Path,
        expected_sha256: str,
        finalization_id: str | None = None,
        post_rename_verified: bool = False,
    ) -> None:
        super().__init__(message)
        self.installed = True
        self.durability = "uncertain"
        self.destination_path = destination_path
        self.expected_sha256 = expected_sha256
        self.finalization_id = finalization_id
        self.post_rename_verified = post_rename_verified


def _read_all_fd(fd: int) -> bytes:
    """Read all bytes from an open file descriptor until EOF."""
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_ancestor_directory_fd(fd: int, label: str) -> tuple[int, int]:
    """Verify an ancestor directory strictly outside authorized_root."""
    try:
        st = os.fstat(fd)
    except OSError as exc:
        raise PathEscapeError(f"Failed to fstat ancestor directory {label}: {exc}") from exc

    if not stat.S_ISDIR(st.st_mode):
        raise PathEscapeError(f"Ancestor descriptor for {label} is not a directory.")
    if st.st_nlink < 1:
        raise PathEscapeError(f"Ancestor directory {label} has been unlinked (st_nlink={st.st_nlink}).")

    euid = os.geteuid()
    if st.st_uid not in (euid, 0):
        raise PathEscapeError(
            f"Ancestor directory {label} is owned by untrusted uid {st.st_uid} (expected {euid} or 0)."
        )

    # Outside authorized_root, only a root-owned sticky directory (e.g. /tmp) may be world/group-writable.
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        is_sticky = bool(st.st_mode & getattr(stat, "S_ISVTX", 0o1000))
        if not (st.st_uid == 0 and is_sticky and (st.st_mode & stat.S_IWGRP) == 0 or (st.st_uid == 0 and is_sticky)):
            raise PathEscapeError(
                f"Ancestor directory {label} is writable without root-owned sticky protection "
                f"(uid={st.st_uid}, mode={oct(st.st_mode & 0o7777)})."
            )
        if st.st_uid != 0 or not is_sticky:
            raise PathEscapeError(
                f"Ancestor directory {label} is group/world-writable and not a root-owned sticky directory "
                f"(uid={st.st_uid}, mode={oct(st.st_mode & 0o7777)})."
            )

    return (st.st_dev, st.st_ino)


def _verify_private_tree_directory_fd(
    fd: int,
    label: str,
    *,
    is_authorized_root: bool = False,
) -> tuple[int, int]:
    """Verify authorized_root or an interior descendant directory satisfies the private-tree contract."""
    try:
        st = os.fstat(fd)
    except OSError as exc:
        raise PathEscapeError(f"Failed to fstat directory {label}: {exc}") from exc

    if not stat.S_ISDIR(st.st_mode):
        raise PathEscapeError(f"Descriptor for {label} is not a directory.")
    if st.st_nlink < 1:
        raise PathEscapeError(f"Directory {label} has been unlinked (st_nlink={st.st_nlink}).")

    euid = os.geteuid()
    if st.st_uid != euid:
        raise PathEscapeError(
            f"Directory {label} is owned by foreign uid {st.st_uid}; expected operator uid {euid}."
        )

    mode_bits = st.st_mode & 0o777
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise PathEscapeError(
            f"Directory {label} has forbidden group/world write bits (mode={oct(mode_bits)}); "
            "all directories in authorized_root must reject S_IWGRP | S_IWOTH."
        )

    if is_authorized_root:
        if mode_bits not in (0o700, 0o750):
            raise PathEscapeError(
                f"Authorized root {label} has mode {oct(mode_bits)}; required mode is 0700 or 0750 "
                "(private to operator UID without group-write or world access)."
            )
    else:
        if mode_bits not in (0o700, 0o750):
            raise PathEscapeError(
                f"Interior directory {label} has mode {oct(mode_bits)}; interior directories must be private (0700 or 0750)."
            )

    return (st.st_dev, st.st_ino)


def _pin_authorized_root_from_slash(raw_auth_root: Path) -> tuple[int, tuple[int, int], Path, list[int], list[tuple[int, str, int, tuple[int, int], bool]]]:
    """Pin authorized_root by walking from '/' through its lexical absolute ancestors with O_DIRECTORY | O_NOFOLLOW."""
    if any(p == ".." for p in raw_auth_root.parts):
        raise PathEscapeError(f"Authorized root {raw_auth_root} contains parent traversal ('..').")

    abs_auth_str = os.path.abspath(str(raw_auth_root.expanduser()))
    lexical_root = Path(abs_auth_str)
    parts = [p for p in lexical_root.parts if p not in ("/", "")]
    if not parts:
        raise PathEscapeError("Authorized root cannot be '/'.")

    dir_flags = (
        os.O_DIRECTORY
        | os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    opened_fds: list[int] = []
    chain: list[tuple[int, str, int, tuple[int, int], bool]] = []

    try:
        slash_fd = os.open("/", dir_flags)
        opened_fds.append(slash_fd)
        slash_dev_ino = _verify_ancestor_directory_fd(slash_fd, "/")
        cur_fd = slash_fd

        # Walk ancestors strictly above authorized_root
        for idx, comp in enumerate(parts[:-1]):
            try:
                next_fd = os.open(comp, dir_flags, dir_fd=cur_fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise PathEscapeError(
                        f"Ancestor component {comp!r} of authorized_root {lexical_root} is a symlink or non-directory."
                    ) from exc
                raise PathEscapeError(
                    f"Cannot open ancestor component {comp!r} of authorized_root {lexical_root}: {exc}"
                ) from exc
            opened_fds.append(next_fd)
            dev_ino = _verify_ancestor_directory_fd(next_fd, f"ancestor(/{'/'.join(parts[:idx + 1])})")
            chain.append((cur_fd, comp, next_fd, dev_ino, True))
            cur_fd = next_fd

        # Open the authorized_root leaf itself without following symlinks
        root_leaf = parts[-1]
        try:
            auth_fd = os.open(root_leaf, dir_flags, dir_fd=cur_fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                try:
                    st_l = os.lstat(root_leaf, dir_fd=cur_fd)
                    if stat.S_ISLNK(st_l.st_mode):
                        raise PathEscapeError(f"Authorized root {lexical_root} must not be a symlink.") from exc
                except OSError:
                    pass
                raise PathEscapeError(f"Authorized root {lexical_root} is not a directory.") from exc
            raise PathEscapeError(f"Authorized root {lexical_root} does not exist or cannot be opened: {exc}") from exc
        opened_fds.append(auth_fd)
        auth_dev_ino = _verify_private_tree_directory_fd(
            auth_fd,
            f"authorized_root({lexical_root})",
            is_authorized_root=True,
        )
        chain.append((cur_fd, root_leaf, auth_fd, auth_dev_ino, False))
        return slash_fd, slash_dev_ino, lexical_root, opened_fds, chain
    except Exception:
        for fd in reversed(opened_fds):
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _verify_directory_chain(
    slash_fd: int,
    slash_dev_ino: tuple[int, int],
    chain: list[tuple[int, str, int, tuple[int, int], bool]],
    *,
    root_path: Path | None = None,
    root_dev_ino: tuple[int, int] | None = None,
) -> None:
    """Verify that '/' and every traversed ancestor, authorized_root, and interior subdirectory remain un-swapped."""
    cur_st = os.fstat(slash_fd)
    if (cur_st.st_dev, cur_st.st_ino) != slash_dev_ino or cur_st.st_nlink < 1:
        raise PathEscapeError("Root '/' directory identity changed during write-back.")

    if root_path is not None and root_dev_ino is not None:
        try:
            path_st = os.lstat(str(root_path))
        except OSError as exc:
            raise PathEscapeError(f"Authorized root path {root_path} vanished during write-back: {exc}") from exc
        if stat.S_ISLNK(path_st.st_mode) or (path_st.st_dev, path_st.st_ino) != root_dev_ino:
            raise PathEscapeError(f"Authorized root {root_path} was replaced or relocated during write-back.")

    for parent_fd, comp_name, child_fd, expected_dev_ino, is_outside_ancestor in chain:
        if is_outside_ancestor:
            actual_dev_ino = _verify_ancestor_directory_fd(child_fd, f"ancestor({comp_name})")
        else:
            actual_dev_ino = _verify_private_tree_directory_fd(child_fd, f"component({comp_name})")

        if actual_dev_ino != expected_dev_ino:
            raise PathEscapeError(f"Directory component {comp_name!r} identity changed during write-back.")

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


def _validate_lock_stat(st: os.stat_result, lock_name: str) -> None:
    if stat.S_ISLNK(st.st_mode):
        raise PathEscapeError(f"Lock marker {lock_name!r} is a symlink.")
    if not stat.S_ISREG(st.st_mode):
        raise HostWriteBackError(f"Lock marker {lock_name!r} is not a regular file.")
    if st.st_nlink != 1:
        raise HostWriteBackError(
            f"Lock marker {lock_name!r} must have link count 1 (got st_nlink={st.st_nlink})."
        )
    euid = os.geteuid()
    if st.st_uid != euid:
        raise HostWriteBackError(
            f"Lock marker {lock_name!r} is owned by foreign uid {st.st_uid} (expected operator uid {euid})."
        )
    if (st.st_mode & 0o177) != 0:
        raise HostWriteBackError(
            f"Lock marker {lock_name!r} has insecure mode {oct(st.st_mode & 0o777)}; required mode <= 0600."
        )


def _acquire_verified_lock_fd(parent_dir_fd: int, lock_name: str) -> tuple[int, tuple[int, int]]:
    """Open and lock permanent .lock-{leaf} with O_NOFOLLOW|O_CLOEXEC, verifying owner/type/nlink/mode before and after flock."""
    if fcntl is None or not hasattr(fcntl, "flock"):
        raise HostWriteBackError("POSIX fcntl.flock writer coordination is required on this platform.")
    if not hasattr(os, "O_NOFOLLOW"):
        raise HostWriteBackError("OS does not support O_NOFOLLOW; refusing unsafe lock marker open.")

    try:
        pre_st = os.lstat(lock_name, dir_fd=parent_dir_fd)
    except FileNotFoundError:
        pre_st = None

    if pre_st is not None:
        _validate_lock_stat(pre_st, lock_name)

    lock_flags = (
        os.O_CREAT
        | os.O_RDWR
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(lock_name, lock_flags, 0o600, dir_fd=parent_dir_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise PathEscapeError(f"Lock marker {lock_name!r} is a symlink (ELOOP).") from exc
        raise HostWriteBackError(f"Failed to open lock file {lock_name!r}: {exc}") from exc

    try:
        fd_st = os.fstat(fd)
        _validate_lock_stat(fd_st, lock_name)
        if pre_st is not None and (fd_st.st_dev, fd_st.st_ino) != (pre_st.st_dev, pre_st.st_ino):
            raise HostWriteBackError(f"Lock marker {lock_name!r} inode changed during open.")

        try:
            entry_before = os.lstat(lock_name, dir_fd=parent_dir_fd)
        except OSError as exc:
            raise HostWriteBackError(f"Lock marker {lock_name!r} disappeared before flock: {exc}") from exc
        _validate_lock_stat(entry_before, lock_name)
        if (entry_before.st_dev, entry_before.st_ino) != (fd_st.st_dev, fd_st.st_ino):
            raise HostWriteBackError(f"Lock marker {lock_name!r} directory entry diverged before flock.")

        fcntl.flock(fd, fcntl.LOCK_EX)

        # Re-verify owner, regular-file type, link count 1, mode <= 0600, and stable inode after acquiring LOCK_EX
        post_fd_st = os.fstat(fd)
        _validate_lock_stat(post_fd_st, lock_name)
        if (post_fd_st.st_dev, post_fd_st.st_ino) != (fd_st.st_dev, fd_st.st_ino):
            raise HostWriteBackError(f"Lock marker {lock_name!r} inode changed while waiting for flock.")

        try:
            dir_entry_st = os.lstat(lock_name, dir_fd=parent_dir_fd)
        except OSError as exc:
            raise HostWriteBackError(f"Lock marker {lock_name!r} was unlinked while waiting for flock: {exc}") from exc
        _validate_lock_stat(dir_entry_st, lock_name)
        if (dir_entry_st.st_dev, dir_entry_st.st_ino) != (post_fd_st.st_dev, post_fd_st.st_ino):
            raise HostWriteBackError(f"Lock marker {lock_name!r} was replaced while waiting for flock.")

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


def _validate_existing_destination_stat(st: os.stat_result, leaf_name: str, resolved_dest: Path) -> int:
    if stat.S_ISLNK(st.st_mode):
        raise PathEscapeError(f"Destination {leaf_name!r} is a symlink.")
    if stat.S_ISDIR(st.st_mode):
        raise HostWriteBackError(f"Destination {leaf_name!r} is a directory, not a file.")
    if not stat.S_ISREG(st.st_mode):
        raise HostWriteBackError(f"Destination {leaf_name!r} is not a regular file.")
    if st.st_nlink != 1:
        raise HostWriteBackError(
            f"Destination {resolved_dest} is hardlinked (st_nlink={st.st_nlink}); refusing write-back."
        )
    euid = os.geteuid()
    if st.st_uid != euid:
        raise PathEscapeError(
            f"Destination {resolved_dest} is owned by foreign uid {st.st_uid} (expected operator uid {euid})."
        )
    mode_bits = st.st_mode & 0o777
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise PathEscapeError(
            f"Destination {resolved_dest} has forbidden group/world write bits (mode={oct(mode_bits)})."
        )
    if st.st_mode & 0o007:
        raise PathEscapeError(
            f"Destination {resolved_dest} has world permission bits (mode={oct(mode_bits)}) violating private-tree policy."
        )
    return mode_bits


def safe_write_back_file(
    destination_path: Path | str,
    data: bytes,
    *,
    expected_sha256: str,
    preimage_sha256: str | None = None,
    authorized_root: Path | str | None = None,
    allow_unconditional_overwrite: bool = False,
    finalization_id: str | None = None,
    reconcile_installed: bool = False,
    _after_preimage_hook=None,
) -> Path:
    """Safely write exported bytes to a destination file inside a pinned private operator tree.

    Cooperative-Writer & Private-Tree Contract (Stage D):
    - Requires an explicit ``authorized_root`` owned by the operator UID (mode ``0700`` or ``0750``).
    - Walks from ``/`` through all lexical ancestors with ``O_DIRECTORY | O_NOFOLLOW``, allowing
      a root-owned sticky ``/tmp`` ancestor only outside ``authorized_root``.
    - Newly created interior directories use ``0700``.
    - Uses a permanent ``.lock-<leaf>`` marker (``<= 0600``, ``st_nlink == 1``) held across preimage
      verification, temp write+fsync, pre-replace recheck, ``os.replace``, parent ``fsync``, and
      post-write verification.
    - An adversarial same-UID writer that ignores ``flock`` cannot be prevented from racing a
      POSIX ``rename`` and is outside this supported contract.
    - Does not swallow post-rename directory ``fsync`` failure: raises ``DurabilityUncertainError``
      with ``installed=True, durability='uncertain'``.
    """
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

    if os.name == "nt" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY") or not hasattr(os, "geteuid"):
        raise HostWriteBackError("Platform lacks required POSIX O_NOFOLLOW / O_DIRECTORY / UID safeguards.")

    if authorized_root is None or str(authorized_root).strip() == "":
        raise PathEscapeError(
            "safe_write_back_file requires an explicit authorized_root; implicit authorized_root=None is forbidden."
        )

    dest = Path(destination_path)
    if any(p == ".." for p in dest.parts):
        raise PathEscapeError(f"Destination {dest} contains parent traversal ('..').")

    raw_auth_root = Path(authorized_root)
    slash_fd: int | None = None
    slash_dev_ino: tuple[int, int] | None = None
    auth_root_lexical: Path | None = None
    opened_fds: list[int] = []
    dir_chain: list[tuple[int, str, int, tuple[int, int], bool]] = []
    lock_fd: int | None = None
    temp_name: str | None = None
    parent_dir_fd: int | None = None

    try:
        slash_fd, slash_dev_ino, auth_root_lexical, opened_fds, dir_chain = _pin_authorized_root_from_slash(
            raw_auth_root
        )
        auth_fd = dir_chain[-1][2]
        auth_dev_ino = dir_chain[-1][3]

        if dest.is_absolute():
            abs_dest_lexical = Path(os.path.abspath(str(dest)))
            if any(p == ".." for p in dest.parts):
                raise PathEscapeError(f"Destination {dest} contains parent traversal ('..').")
            try:
                lexical_rel = abs_dest_lexical.relative_to(auth_root_lexical)
            except ValueError:
                raise PathEscapeError(
                    f"Destination {dest} is outside authorized root {auth_root_lexical}."
                )
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
        if "/" in leaf_name or "\\" in leaf_name or leaf_name in (".", "..") or leaf_name.startswith(".lock-"):
            raise PathEscapeError(f"Invalid destination leaf name: {leaf_name!r}")

        current_fd = auth_fd
        comp_flags = (
            os.O_DIRECTORY
            | os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        for comp in dir_components:
            if "/" in comp or "\\" in comp or comp in (".", ".."):
                raise PathEscapeError(f"Invalid path component: {comp!r}")
            try:
                next_fd = os.open(comp, comp_flags, dir_fd=current_fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    try:
                        st_c = os.lstat(comp, dir_fd=current_fd)
                        if stat.S_ISLNK(st_c.st_mode):
                            raise PathEscapeError(f"Path component {comp!r} is a symlink.") from exc
                    except OSError:
                        pass
                    raise PathEscapeError(f"Path component {comp!r} is not a directory.") from exc
                elif exc.errno == errno.ENOENT:
                    try:
                        os.mkdir(comp, mode=0o700, dir_fd=current_fd)
                    except OSError as me:
                        raise HostWriteBackError(f"Failed to create interior directory {comp!r}: {me}") from me
                    try:
                        next_fd = os.open(comp, comp_flags, dir_fd=current_fd)
                        os.fchmod(next_fd, 0o700)
                    except OSError as oe:
                        raise PathEscapeError(f"Failed to open created directory {comp!r}: {oe}") from oe
                else:
                    raise PathEscapeError(f"Error traversing component {comp!r}: {exc}") from exc

            opened_fds.append(next_fd)
            comp_dev_ino = _verify_private_tree_directory_fd(
                next_fd,
                f"component({comp})",
                is_authorized_root=False,
            )
            dir_chain.append((current_fd, comp, next_fd, comp_dev_ino, False))
            current_fd = next_fd

        parent_dir_fd = current_fd
        resolved_dest = auth_root_lexical.joinpath(*clean_parts)

        # Acquire permanent .lock-<leaf> marker
        lock_name = f".lock-{leaf_name}"
        lock_fd, lock_dev_ino = _acquire_verified_lock_fd(parent_dir_fd, lock_name)
        opened_fds.append(lock_fd)

        # Verify entire directory chain from '/' after acquiring lock
        _verify_directory_chain(
            slash_fd,
            slash_dev_ino,
            dir_chain,
            root_path=auth_root_lexical,
            root_dev_ino=auth_dev_ino,
        )

        # Inspect existing destination under lock
        try:
            st = os.lstat(leaf_name, dir_fd=parent_dir_fd)
            dest_exists = True
        except FileNotFoundError:
            dest_exists = False
            st = None

        target_mode = 0o600
        preimage_stat_sig: tuple[int, int, int, int] | None = None
        if dest_exists:
            assert st is not None
            target_mode = _validate_existing_destination_stat(st, leaf_name, resolved_dest)

            read_fd = os.open(
                leaf_name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_dir_fd,
            )
            try:
                read_st = os.fstat(read_fd)
                _validate_existing_destination_stat(read_st, leaf_name, resolved_dest)
                if (read_st.st_dev, read_st.st_ino) != (st.st_dev, st.st_ino):
                    raise PreimageMismatchError(f"Destination {resolved_dest} changed during preimage open.")
                preimage_stat_sig = (read_st.st_dev, read_st.st_ino, read_st.st_mtime_ns, read_st.st_size)
                existing_bytes = _read_all_fd(read_fd)
                actual_preimage = hashlib.sha256(existing_bytes).hexdigest()

                # Reconciliation path: if reconciling a previously installed durability_uncertain write
                # and the file on disk already matches expected_sha256, fsync file + parent directory directly.
                if reconcile_installed and actual_preimage == expected_sha256:
                    os.fsync(read_fd)
                    try:
                        os.fsync(parent_dir_fd)
                    except OSError as fsync_exc:
                        raise DurabilityUncertainError(
                            f"Reconciliation parent directory fsync failed for {resolved_dest}: {fsync_exc}",
                            destination_path=resolved_dest,
                            expected_sha256=expected_sha256,
                            finalization_id=finalization_id,
                            post_rename_verified=True,
                        ) from fsync_exc
                    return resolved_dest
            finally:
                os.close(read_fd)

            if preimage_sha256 is None and not allow_unconditional_overwrite:
                raise PreimageMismatchError(
                    f"Destination file {resolved_dest} already exists; preimage_sha256 is required unless allow_unconditional_overwrite=True"
                )
            if preimage_sha256 is not None and actual_preimage != preimage_sha256.lower():
                raise PreimageMismatchError(
                    f"Destination {resolved_dest} on disk has hash {actual_preimage}, expected {preimage_sha256}."
                )
        else:
            if preimage_sha256 is not None:
                raise PreimageMismatchError(
                    f"Destination file {resolved_dest} does not exist, but preimage_sha256 was expected."
                )

        if _after_preimage_hook is not None:
            _after_preimage_hook()

        # Create same-directory temp with O_EXCL | O_NOFOLLOW, mode 0600
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
            os.fchmod(temp_fd, target_mode)
            view = memoryview(data_bytes)
            written = 0
            while written < len(data_bytes):
                n = os.write(temp_fd, view[written:])
                if n <= 0:
                    raise HostWriteBackError("Short write to temporary write-back file.")
                written += n
            os.fsync(temp_fd)
            temp_fstat = os.fstat(temp_fd)
            temp_dev_ino = (temp_fstat.st_dev, temp_fstat.st_ino)
        finally:
            os.close(temp_fd)

        # Reopen and rehash temp file before replacement (Stage D item 5)
        reopen_temp_fd = os.open(
            temp_name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_dir_fd,
        )
        try:
            reopen_st = os.fstat(reopen_temp_fd)
            if (reopen_st.st_dev, reopen_st.st_ino) != temp_dev_ino or reopen_st.st_nlink != 1:
                raise HostWriteBackError(f"Temporary file {temp_name} inode/link changed before replacement.")
            written_bytes = _read_all_fd(reopen_temp_fd)
            if hashlib.sha256(written_bytes).hexdigest() != expected_sha256:
                raise HostWriteBackError(
                    f"Temporary file {temp_name} failed pre-replace digest verification."
                )
        finally:
            os.close(reopen_temp_fd)

        # Revalidate pinned directory chain and lock marker immediately before rename
        _verify_directory_chain(
            slash_fd,
            slash_dev_ino,
            dir_chain,
            root_path=auth_root_lexical,
            root_dev_ino=auth_dev_ino,
        )

        try:
            lock_check_st = os.lstat(lock_name, dir_fd=parent_dir_fd)
        except OSError as exc:
            raise HostWriteBackError(f"Lock marker {lock_name!r} vanished before replacement: {exc}") from exc
        _validate_lock_stat(lock_check_st, lock_name)
        if (lock_check_st.st_dev, lock_check_st.st_ino) != lock_dev_ino:
            raise HostWriteBackError(f"Lock marker {lock_name!r} identity changed before replacement.")

        # Re-read destination under lock and check inode and content before rename
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
            _validate_existing_destination_stat(cur_dest_st, leaf_name, resolved_dest)
            if not allow_unconditional_overwrite:
                cur_sig = (cur_dest_st.st_dev, cur_dest_st.st_ino, cur_dest_st.st_mtime_ns, cur_dest_st.st_size)
                if cur_sig != preimage_stat_sig:
                    raise PreimageMismatchError(
                        f"Destination {resolved_dest} was modified concurrently before replacement."
                    )
                if preimage_sha256 is not None:
                    recheck_fd = os.open(
                        leaf_name,
                        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                        dir_fd=parent_dir_fd,
                    )
                    try:
                        recheck_st = os.fstat(recheck_fd)
                        if (recheck_st.st_dev, recheck_st.st_ino) != (cur_dest_st.st_dev, cur_dest_st.st_ino):
                            raise PreimageMismatchError(
                                f"Destination {resolved_dest} inode changed during pre-replace recheck."
                            )
                        recheck_bytes = _read_all_fd(recheck_fd)
                    finally:
                        os.close(recheck_fd)
                    if hashlib.sha256(recheck_bytes).hexdigest() != preimage_sha256.lower():
                        raise PreimageMismatchError(
                            f"Destination {resolved_dest} content changed concurrently before replacement."
                        )

        # Atomic replacement
        os.replace(temp_name, leaf_name, src_dir_fd=parent_dir_fd, dst_dir_fd=parent_dir_fd)
        temp_name = None

        # Parent directory fsync: NEVER swallow failure (PR23-R5-SCRIPT-002)
        dir_fsync_err: OSError | None = None
        try:
            os.fsync(parent_dir_fd)
        except OSError as exc:
            dir_fsync_err = exc

        # Post-rename verification of current destination hash under lock
        post_verified = False
        post_verify_err: Exception | None = None
        try:
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
                post_verified = True
            finally:
                os.close(verify_fd)
        except Exception as v_exc:
            post_verify_err = v_exc

        if dir_fsync_err is not None:
            raise DurabilityUncertainError(
                f"Destination {resolved_dest} was replaced on disk, but parent directory fsync failed: {dir_fsync_err}",
                destination_path=resolved_dest,
                expected_sha256=expected_sha256,
                finalization_id=finalization_id,
                post_rename_verified=post_verified,
            ) from dir_fsync_err

        if post_verify_err is not None:
            err = HostWriteBackError(str(post_verify_err))
            err.installed = True
            err.durability = "uncertain"
            raise err from post_verify_err

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


def _fetch_finalized_export_bytes(
    call_tool,
    *,
    finalization_id: str,
    target_file_id: str,
    expected_sha256: str | None = None,
    expected_bytes: int | None = None,
) -> tuple[bytes, str]:
    chunks: list[bytes] = []
    offset = 0
    limit = 262144
    pinned_sha = expected_sha256

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

        page_sha = read_res.get("content_sha256")
        if pinned_sha is None and isinstance(page_sha, str):
            pinned_sha = page_sha
        elif pinned_sha is not None and page_sha is not None and page_sha != pinned_sha:
            raise HostWriteBackError(
                f"Deferred export content_sha256 {page_sha} does not match pinned {pinned_sha}"
            )

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
    computed_sha = hashlib.sha256(raw_bytes).hexdigest()
    if pinned_sha is not None and computed_sha != pinned_sha:
        raise HostWriteBackError(
            f"Deferred assembled bytes SHA-256 {computed_sha} does not match expected {pinned_sha}"
        )
    if expected_bytes is not None and len(raw_bytes) != expected_bytes:
        raise HostWriteBackError(
            f"Deferred assembled bytes length {len(raw_bytes)} does not match expected {expected_bytes}"
        )
    return raw_bytes, pinned_sha or computed_sha


def reconcile_finalized_write_back(
    call_tool,
    *,
    finalization_id: str,
    target_file_id: str,
    destination_path: Path | str,
    authorized_root: Path | str,
    expected_sha256: str | None = None,
    preimage_sha256: str | None = None,
    allow_unconditional_overwrite: bool = False,
) -> dict[str, Any]:
    """Reconcile a previously committed finalization onto disk without creating a new SAVE checkpoint."""
    try:
        raw_bytes, verified_sha = _fetch_finalized_export_bytes(
            call_tool,
            finalization_id=finalization_id,
            target_file_id=target_file_id,
            expected_sha256=expected_sha256,
        )
        written_path = safe_write_back_file(
            destination_path,
            raw_bytes,
            expected_sha256=verified_sha,
            preimage_sha256=preimage_sha256,
            authorized_root=authorized_root,
            allow_unconditional_overwrite=allow_unconditional_overwrite,
            finalization_id=finalization_id,
            reconcile_installed=True,
        )
        return {
            "status": "ok",
            "db_status": "ok",
            "disk_status": "written",
            "installed": True,
            "reconciliation_required": False,
            "finalization_id": finalization_id,
            "target_file_id": target_file_id,
            "content_sha256": verified_sha,
            "destination_path": str(written_path),
            "written_destination": str(written_path),
        }
    except DurabilityUncertainError as exc:
        return {
            "status": "error",
            "db_status": "ok",
            "disk_status": "durability_uncertain",
            "installed": True,
            "reconciliation_required": True,
            "finalization_id": finalization_id,
            "target_file_id": target_file_id,
            "content_sha256": exc.expected_sha256,
            "pinned_content_sha256": exc.expected_sha256,
            "destination_path": str(exc.destination_path),
            "written_destination": None,
            "disk_error": str(exc),
        }
    except Exception as exc:
        installed = bool(getattr(exc, "installed", False))
        return {
            "status": "error",
            "db_status": "ok",
            "disk_status": "durability_uncertain" if installed else "rejected",
            "installed": installed,
            "reconciliation_required": installed,
            "finalization_id": finalization_id,
            "target_file_id": target_file_id,
            "content_sha256": expected_sha256,
            "destination_path": str(destination_path),
            "written_destination": str(destination_path) if installed else None,
            "disk_error": str(exc),
        }


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
    reconcile_installed: bool = False,
) -> dict:
    """Execute single-target atomic finalization via patchdiff_finalize_target and truthful disk write-back.

    Separates database outcome ('db_status') from host disk outcome ('disk_status'):
    - ``db_status='ok'`` only after finalization committed.
    - ``disk_status`` is exclusively ``not_requested | written | rejected | durability_uncertain``.
    - Overall ``status='ok'`` ONLY when DB succeeded and either ``disk_status=='not_requested'``
      or ``disk_status=='written'``.
    - When post-rename directory fsync fails, ``disk_status='durability_uncertain'``,
      ``status='error'``, ``installed=True``, ``reconciliation_required=True``.
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

    receipt = dict(call_tool("patchdiff_finalize_target", **args))
    db_status = receipt.get("status")
    receipt["db_status"] = db_status

    if db_status != "ok":
        receipt["disk_status"] = "not_requested" if destination_path is None else "rejected"
        receipt["installed"] = False
        receipt["reconciliation_required"] = False
        receipt["written_destination"] = None
        return receipt

    if destination_path is None:
        receipt["disk_status"] = "not_requested"
        receipt["installed"] = False
        receipt["reconciliation_required"] = False
        receipt["written_destination"] = None
        receipt["status"] = "ok"
        return receipt

    finalization_id = receipt.get("finalization_id")
    expected_sha256 = receipt.get("content_sha256")
    expected_bytes = receipt.get("content_bytes")
    is_retry = bool(receipt.get("is_idempotent_replay", False)) or reconcile_installed

    exported_content = receipt.get("exported_content")
    if exported_content is not None:
        raw_bytes = exported_content.encode("utf-8")
        if expected_sha256 is None:
            expected_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    else:
        if not finalization_id:
            msg = "Finalize receipt missing finalization_id for deferred export retrieval"
            receipt["disk_status"] = "rejected"
            receipt["installed"] = False
            receipt["reconciliation_required"] = False
            receipt["written_destination"] = None
            receipt["status"] = "error"
            receipt["disk_error"] = msg
            if raise_on_disk_error:
                raise HostWriteBackError(msg)
            return receipt

        try:
            raw_bytes, expected_sha256 = _fetch_finalized_export_bytes(
                call_tool,
                finalization_id=str(finalization_id),
                target_file_id=target_file_id,
                expected_sha256=expected_sha256,
                expected_bytes=expected_bytes,
            )
        except Exception as exc:
            receipt["disk_status"] = "rejected"
            receipt["installed"] = False
            receipt["reconciliation_required"] = False
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
            finalization_id=str(finalization_id) if finalization_id else None,
            reconcile_installed=is_retry,
        )
        receipt["disk_status"] = "written"
        receipt["installed"] = True
        receipt["reconciliation_required"] = False
        receipt["destination_path"] = str(written_path)
        receipt["written_destination"] = str(written_path)
        receipt["status"] = "ok"
        return receipt
    except DurabilityUncertainError as exc:
        receipt["disk_status"] = "durability_uncertain"
        receipt["installed"] = True
        receipt["reconciliation_required"] = True
        receipt["pinned_content_sha256"] = expected_sha256
        receipt["destination_path"] = str(exc.destination_path)
        receipt["written_destination"] = None
        receipt["status"] = "error"
        receipt["disk_error"] = str(exc)
        if raise_on_disk_error:
            raise
        return receipt
    except Exception as exc:
        installed = bool(getattr(exc, "installed", False))
        receipt["disk_status"] = "durability_uncertain" if installed else "rejected"
        receipt["installed"] = installed
        receipt["reconciliation_required"] = installed
        receipt["pinned_content_sha256"] = expected_sha256
        receipt["destination_path"] = str(destination_path)
        receipt["written_destination"] = None
        receipt["status"] = "error"
        receipt["disk_error"] = str(exc)
        if raise_on_disk_error:
            raise
        return receipt
