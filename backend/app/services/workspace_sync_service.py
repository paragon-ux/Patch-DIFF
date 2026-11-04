"""Cooperatively owned workspace publication; separate from the PG checkpoint."""

from __future__ import annotations

import errno
import hashlib
from contextlib import ExitStack, contextmanager
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from app.core.failures import FailureReason
from app.core.line_endings import apply_eol, eol_name, export_eol

WORKSPACE_EOL_FORMATS = ("original_eol", "canonical_lf", "crlf")
_WIN_RESERVED_RE = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9\xb9\xb2\xb3]|lpt[1-9\xb9\xb2\xb3])(?:\..*)?$",
    re.IGNORECASE,
)
_ILLEGAL_SEGMENT_CHARS = frozenset('<>:"|?*')


class WorkspaceSyncError(Exception):
    def __init__(self, reason: FailureReason, code: str, detail: str, *, receipt: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.reason = reason
        self.code = code
        self.detail = detail
        self.receipt = receipt


@dataclass(frozen=True, slots=True)
class WorkspaceSyncReceipt:
    synced_path: str
    disk_sha256: str
    bytes_written: int
    content_eol: str
    durability: str = "confirmed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "synced_path": self.synced_path,
            "disk_sha256": self.disk_sha256,
            "bytes_written": self.bytes_written,
            "content_eol": self.content_eol,
            "publication": "installed",
            "durability": self.durability,
        }


def _is_reparse_or_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        st = path.lstat()
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_workspace_file(
    workspace_root: str | os.PathLike[str] | None,
    filename: str,
) -> tuple[Path, Path, str]:
    if workspace_root is None or (isinstance(workspace_root, str) and not workspace_root.strip()):
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_MISSING,
            "workspace_root_unconfigured",
            "PATCHDIFF_WORKSPACE_ROOT is not configured.",
        )
    root_candidate = Path(workspace_root)
    if not root_candidate.exists() or not root_candidate.is_dir():
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID,
            "workspace_root_invalid",
            "Configured PATCHDIFF_WORKSPACE_ROOT does not exist or is not a directory.",
        )
    root_real = root_candidate.resolve(strict=True)

    if not isinstance(filename, str) or not filename:
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID,
            "workspace_path_invalid",
            "Target filename must be a non-empty relative path.",
        )
    try:
        filename.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID,
            "workspace_path_invalid",
            "Target filename must be valid UTF-8.",
        ) from exc

    if (
        any(ord(ch) < 32 or ch in _ILLEGAL_SEGMENT_CHARS for ch in filename)
        or filename.startswith(("/", "\\"))
        or PureWindowsPath(filename).drive != ""
    ):
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID,
            "workspace_path_invalid",
            "Target filename must be a safe relative path within the workspace.",
        )

    segments = filename.replace("\\", "/").split("/")
    for seg in segments:
        if (
            not seg
            or seg in {".", ".."}
            or seg.endswith((".", " "))
            or _WIN_RESERVED_RE.match(seg)
            or PureWindowsPath(seg).is_reserved()
        ):
            raise WorkspaceSyncError(
                FailureReason.CONTEXT_INVALID,
                "workspace_path_invalid",
                f"Target path segment {seg!r} is not permitted.",
            )

    cur = root_real
    for idx, seg in enumerate(segments):
        cur = cur / seg
        if _is_reparse_or_symlink(cur):
            raise WorkspaceSyncError(
                FailureReason.CONTEXT_INVALID,
                "workspace_symlink_escape",
                "Workspace path must not traverse symbolic links or junctions.",
            )
        if idx < len(segments) - 1 and cur.exists() and not cur.is_dir():
            raise WorkspaceSyncError(
                FailureReason.CONTEXT_INVALID,
                "workspace_path_invalid",
                "Intermediate workspace path component is not a directory.",
            )

    if not cur.resolve(strict=False).is_relative_to(root_real):
        raise WorkspaceSyncError(
            FailureReason.CONTEXT_INVALID,
            "workspace_path_invalid",
            "Resolved target path escapes PATCHDIFF_WORKSPACE_ROOT.",
        )
    return root_real, cur, "/".join(segments)



@contextmanager
def _workspace_file(workspace_root, filename: str, *, create_parents: bool = False):
    """Pin directory handles and lease the physical destination directory for IO.

    The lease is advisory. Other writers must cooperate, and the configured root
    and opened directories must not be moved out of the workspace during IO.
    """
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_platform_unsupported",
                                 "Workspace IO requires POSIX descriptor-relative IO and directory flock.")
    import fcntl

    root, _, relative = resolve_workspace_file(workspace_root, filename)
    try:
        with ExitStack() as stack:
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root_fd)
            st = os.fstat(root_fd)
            identity = f"{st.st_dev}:{st.st_ino}"
            parent_fd = root_fd
            parts = relative.split("/")
            for part in parts[:-1]:
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                except FileNotFoundError:
                    if not create_parents:
                        raise
                    os.mkdir(part, dir_fd=parent_fd)
                    os.fsync(parent_fd)
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                stack.callback(os.close, child)
                parent_fd = child
            try:
                fcntl.flock(parent_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_busy",
                                         "Another managed operation owns the destination directory; no file was published.") from exc
            yield parent_fd, parts[-1], relative, identity
    except WorkspaceSyncError:
        raise
    except OSError as exc:
        code = "workspace_symlink_escape" if exc.errno in (errno.ELOOP, errno.ENOTDIR) else "workspace_io_error"
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, code,
                                 "Workspace IO failed before a confirmed publication.") from exc


def _read_regular(parent_fd: int, name: str) -> tuple[bytes, int]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_path_invalid",
                                     "Workspace source must be a regular file.")
        return stream.read(), stat.S_IMODE(st.st_mode)


def read_workspace_source_with_identity(workspace_root, filename: str) -> tuple[bytes, str, str]:
    try:
        with _workspace_file(workspace_root, filename) as (parent, name, relative, identity):
            try:
                raw, _ = _read_regular(parent, name)
            except FileNotFoundError as exc:
                raise WorkspaceSyncError(FailureReason.TARGET_NOT_FOUND, "workspace_file_not_found",
                                         "Workspace source does not exist.") from exc
    except WorkspaceSyncError:
        raise
    if b"\x00" in raw:
        raise WorkspaceSyncError(FailureReason.TARGET_ENCODING_INVALID, "target_encoding_invalid",
                                 "Workspace file must not contain NUL bytes.")
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkspaceSyncError(FailureReason.TARGET_ENCODING_INVALID, "target_encoding_invalid",
                                 "Workspace file must be valid UTF-8 text.") from exc
    return raw, relative, identity


def read_workspace_source(workspace_root, filename: str) -> tuple[bytes, str]:
    raw, relative, _ = read_workspace_source_with_identity(workspace_root, filename)
    return raw, relative


def sync_target_file_to_workspace(target: Any, *, workspace_root, eol_format: str = "original_eol") -> WorkspaceSyncReceipt:
    """Publish under a cooperative destination-directory lease; never claim a PG/file transaction.

    On failure after installation, the exception carries the installed receipt.
    The caller must report a partial outcome and require explicit reconciliation.
    """
    if eol_format not in WORKSPACE_EOL_FORMATS:
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "unsupported_workspace_eol_format",
                                 "workspace_eol_format must be one of: " + ", ".join(WORKSPACE_EOL_FORMATS))
    eol, error = export_eol(eol_format, target.source_line_endings)
    if error is not None or eol is None:
        raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, error or "source_line_endings_unknown",
                                 "Cannot restore original EOL; explicitly select canonical_lf or crlf.")
    rendered = apply_eol(target.current_content, eol).encode("utf-8")
    digest = hashlib.sha256(rendered).hexdigest()
    recorded = dict(target.source_line_endings) if isinstance(target.source_line_endings, dict) else {}
    expected = recorded.get("last_synced_disk_sha256") or recorded.get("source_sha256")
    tracked = bool(recorded.get("workspace_tracked") or "last_synced_disk_sha256" in recorded)
    installed = durable = False
    receipt = None
    try:
        with _workspace_file(workspace_root, target.filename, create_parents=not tracked) as (parent, name, relative, identity):
            if recorded.get("workspace_root_identity") not in (None, identity):
                raise WorkspaceSyncError(FailureReason.CONTEXT_INVALID, "workspace_binding_mismatch",
                                         "Target belongs to a different workspace; initialize a new target explicitly.")
            try:
                before, mode = _read_regular(parent, name)
            except FileNotFoundError:
                before, mode = None, None
            if (before is None and tracked) or (before is not None and hashlib.sha256(before).hexdigest() != expected):
                raise WorkspaceSyncError(FailureReason.TARGET_DIVERGED, "external_disk_drift",
                                         "Workspace baseline differs; re-read and initialize a new target explicitly.")
            receipt = WorkspaceSyncReceipt(relative, digest, len(rendered), eol_name(eol))
            tmp = f".patchdiff-{uuid.uuid4().hex}.tmp"
            created = installed = False
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                created = True
                with os.fdopen(fd, "wb") as stream:
                    stream.write(rendered)
                    stream.flush()
                    if mode is not None:
                        os.fchmod(stream.fileno(), mode)
                    os.fsync(stream.fileno())
                # Catch unmanaged drift while staging. Non-cooperating writers after
                # this check are outside the advisory ownership contract.
                try:
                    current, _ = _read_regular(parent, name)
                except FileNotFoundError:
                    current = None
                if current != before:
                    raise WorkspaceSyncError(FailureReason.TARGET_DIVERGED, "external_disk_drift",
                                             "Workspace changed while staging; nothing was published.")
                if before is None:
                    try:
                        os.link(tmp, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    except FileExistsError as exc:
                        raise WorkspaceSyncError(FailureReason.TARGET_DIVERGED, "external_disk_drift",
                                                 "A new file appeared during publication; it was preserved.") from exc
                    installed = True
                    os.unlink(tmp, dir_fd=parent)
                else:
                    os.replace(tmp, name, src_dir_fd=parent, dst_dir_fd=parent)
                    installed = True
                created = False
                os.fsync(parent)
                durable = True
            except OSError as exc:
                partial = WorkspaceSyncReceipt(relative, digest, len(rendered), eol_name(eol), "uncertain").as_dict() if installed else None
                raise WorkspaceSyncError(FailureReason.TRANSACTION_INTERNAL_ERROR,
                                         "workspace_durability_uncertain" if installed else "workspace_io_error",
                                         "File installed; durability is uncertain." if installed else "Workspace staging failed; no file was published.",
                                         receipt=partial) from exc
            finally:
                if created:
                    try:
                        os.unlink(tmp, dir_fd=parent)
                    except OSError:
                        pass
            target.source_line_endings = {**recorded, "workspace_tracked": True,
                                         "workspace_root_identity": identity,
                                         "last_synced_disk_sha256": digest, "last_synced_version": target.version}
            return receipt

    except Exception as exc:
        # Directory-handle teardown runs after the yielded body. Its errors must
        # preserve installation facts just like errors during directory fsync.
        if installed and not (isinstance(exc, WorkspaceSyncError) and exc.receipt is not None):
            partial = WorkspaceSyncReceipt(receipt.synced_path, digest, len(rendered), eol_name(eol),
                                           "confirmed" if durable else "uncertain").as_dict()
            raise WorkspaceSyncError(FailureReason.TRANSACTION_INTERNAL_ERROR, "workspace_post_install_error",
                                     "File installed; managed IO teardown failed.", receipt=partial) from exc
        raise
