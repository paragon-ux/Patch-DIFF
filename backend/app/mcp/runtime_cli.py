"""Docker-only PostgreSQL runtime setup and daemon lifecycle manager for PatchDIFF.

Implements PR #23 Stages A, B, and E:
- Bundled PostgreSQL 16.3 Alpine managed through Docker Compose only (default loopback
  127.0.0.1:5433), plus explicit ``--external-database`` mode for operator-managed PostgreSQL.
- Native PostgreSQL provisioning (initdb, pg_ctl, postgresql.conf/pg_hba.conf mutation) and
  dual-route management are removed.
- Three distinct PostgreSQL roles (``patchdiff_bootstrap``, ``patchdiff_host``, ``patchdiff_agent``)
  stored in three separate ``0600`` credential files with ``O_EXCL | O_NOFOLLOW`` creation.
- Strict Docker Compose container label ownership checks (both ``com.docker.compose.project``
  and ``com.docker.compose.project.working_dir``), with zero ``docker rm -f`` or volume deletion.
- Safe descriptor-relative ``.bak`` backup in ``_atomic_write_json_0600`` without ``O_TRUNC``,
  rejecting symlinks, hardlinks, and wrong ownership, and reporting ``durability_uncertain``
  if post-rename directory ``fsync`` fails.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.resources
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import time
from typing import Any
from urllib.parse import quote, urlparse

import psycopg
from psycopg import sql

from app.core.config import (
    AGENT_ONLY_INSERT_TABLES,
    AGENT_SELECT_TABLES,
    AGENT_UPDATE_COLUMN_GRANTS,
    DB_AGENT_USER,
    DB_BOOTSTRAP_USER,
    DB_HOST_USER,
    DB_NAME,
    DEFAULT_DOCKER_PORT,
    FORBIDDEN_DEFAULT_PASSWORDS,
    HOST_INSERT_TABLES,
    HOST_ONLY_TABLES,
    HOST_SELECT_TABLES,
    HOST_UPDATE_COLUMN_GRANTS,
    OS_AGENT_USER,
    OS_MODEL_USER,
    enforce_os_principal_for_operation,
    get_agent_credentials_file_path,
    get_bootstrap_credentials_file_path,
    get_default_runtime_dir,
    get_host_credentials_file_path,
    load_role_credential_file,
    redact_database_url,
    redact_sensitive_text,
    validate_credential_secret,
    validate_dsn_for_role,
)


class ConfigDurabilityUncertainError(RuntimeError):
    """Raised when atomic rename succeeded but parent directory fsync failed (PR23-R5-SCRIPT-001)."""

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(
            f"Configuration file {path} was replaced on disk, but parent directory fsync failed: {detail}"
        )
        self.path = path
        self.detail = detail
        self.status = "durability_uncertain"
        self.installed = True


class SetupPartialFailureError(RuntimeError):
    """Raised when setup fails after partial state progression, carrying structured reconciliation instructions."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        partial_state: dict[str, Any],
        reconciliation_instructions: str,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.partial_state = partial_state
        self.reconciliation_instructions = reconciliation_instructions


def _open_pinned_private_dir(parent_dir: Path, *, create_if_missing: bool = False) -> int:
    if os.name == "nt" or not hasattr(os, "O_NOFOLLOW"):
        raise PermissionError("Unsupported platform for private descriptor-pinned file operations.")
    resolved_parent = Path(os.path.abspath(str(parent_dir.expanduser())))
    if create_if_missing and not os.path.lexists(resolved_parent):
        resolved_parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(resolved_parent, 0o700)

    try:
        lst = os.lstat(resolved_parent)
    except OSError as exc:
        raise FileNotFoundError(f"Parent directory {resolved_parent} does not exist: {exc}") from exc

    if stat.S_ISLNK(lst.st_mode):
        raise PermissionError(f"Refusing symlinked parent directory: {resolved_parent}")
    if not stat.S_ISDIR(lst.st_mode):
        raise PermissionError(f"Parent path is not a directory: {resolved_parent}")
    if hasattr(os, "getuid") and lst.st_uid != os.getuid():
        raise PermissionError(
            f"Parent directory {resolved_parent} has uid={lst.st_uid}, expected current uid={os.getuid()}."
        )
    if (lst.st_mode & 0o022) != 0:
        raise PermissionError(
            f"Parent directory {resolved_parent} must not be group/world writable (mode={oct(lst.st_mode & 0o777)})."
        )

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    dir_fd = os.open(str(resolved_parent), flags)
    try:
        fst = os.fstat(dir_fd)
        if (fst.st_dev, fst.st_ino) != (lst.st_dev, lst.st_ino):
            raise PermissionError(f"Parent directory {resolved_parent} changed inode during open.")
        if not stat.S_ISDIR(fst.st_mode):
            raise PermissionError(f"Opened parent descriptor {resolved_parent} is not a directory.")
        if hasattr(os, "getuid") and fst.st_uid != os.getuid():
            raise PermissionError(f"Opened parent directory {resolved_parent} is not owned by current user.")
        if (fst.st_mode & 0o022) != 0:
            raise PermissionError(
                f"Opened parent directory {resolved_parent} has insecure mode {oct(fst.st_mode & 0o777)}."
            )
    except Exception:
        os.close(dir_fd)
        raise
    return dir_fd


def _validate_regular_leaf_stat(st: os.stat_result, label: str) -> None:
    if stat.S_ISLNK(st.st_mode):
        raise PermissionError(f"Refusing symlink for {label}.")
    if stat.S_ISDIR(st.st_mode):
        raise ValueError(f"{label} is a directory, not a regular file.")
    if not stat.S_ISREG(st.st_mode):
        raise PermissionError(f"{label} must be a regular file.")
    if st.st_nlink != 1:
        raise PermissionError(f"Refusing hardlinked file for {label} (st_nlink={st.st_nlink}).")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise PermissionError(
            f"{label} is owned by uid={st.st_uid}, expected invoking operator uid={os.getuid()}."
        )
    if (st.st_mode & 0o022) != 0:
        raise PermissionError(
            f"{label} must not be group/world writable (mode={oct(st.st_mode & 0o777)})."
        )


def _write_all_and_fsync(fd: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(data):
        n = os.write(fd, view[written:])
        if n <= 0:
            raise OSError("Short write to temporary file descriptor.")
        written += n
    os.fsync(fd)


def _atomic_write_json_0600(
    target_path: Path,
    payload: dict[str, Any],
    *,
    make_backup: bool = False,
) -> Path:
    """Atomically write JSON with 0600 permissions and safe descriptor-relative .bak backup (PR23-R5-SCRIPT-001)."""
    abs_target = Path(os.path.abspath(str(target_path.expanduser())))
    parent_dir = abs_target.parent
    target_name = abs_target.name
    bak_name = f"{target_name}.bak"

    dir_fd = _open_pinned_private_dir(parent_dir, create_if_missing=True)
    try:
        orig_stat: os.stat_result | None = None
        orig_bytes: bytes = b""
        try:
            orig_stat = os.stat(target_name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            orig_stat = None

        if orig_stat is not None:
            _validate_regular_leaf_stat(orig_stat, f"target file {abs_target}")
            fd_orig = os.open(
                target_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dir_fd,
            )
            try:
                fst_orig = os.fstat(fd_orig)
                _validate_regular_leaf_stat(fst_orig, f"opened target file {abs_target}")
                if (fst_orig.st_dev, fst_orig.st_ino) != (orig_stat.st_dev, orig_stat.st_ino):
                    raise PermissionError(f"Target file {abs_target} changed inode before backup.")
                chunks: list[bytes] = []
                while True:
                    buf = os.read(fd_orig, 65536)
                    if not buf:
                        break
                    chunks.append(buf)
                orig_bytes = b"".join(chunks)
            finally:
                os.close(fd_orig)

        if make_backup and orig_stat is not None:
            existing_bak_stat: os.stat_result | None = None
            try:
                existing_bak_stat = os.stat(bak_name, dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                existing_bak_stat = None

            if existing_bak_stat is not None:
                _validate_regular_leaf_stat(existing_bak_stat, f"backup file {abs_target}.bak")

            tmp_bak_name = f".{bak_name}.{secrets.token_hex(8)}.tmp"
            fd_tb = os.open(
                tmp_bak_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=dir_fd,
            )
            try:
                os.fchmod(fd_tb, 0o600)
                _write_all_and_fsync(fd_tb, orig_bytes)
            except Exception:
                try:
                    os.close(fd_tb)
                except OSError:
                    pass
                try:
                    os.unlink(tmp_bak_name, dir_fd=dir_fd)
                except OSError:
                    pass
                raise
            else:
                os.close(fd_tb)

            try:
                # Re-verify .bak state immediately before descriptor-relative replace
                try:
                    recheck_bak = os.stat(bak_name, dir_fd=dir_fd, follow_symlinks=False)
                except FileNotFoundError:
                    if existing_bak_stat is not None:
                        raise PermissionError(f"Backup file {abs_target}.bak disappeared before replacement.")
                else:
                    if existing_bak_stat is None:
                        raise PermissionError(f"Backup file {abs_target}.bak appeared unexpectedly before replacement.")
                    _validate_regular_leaf_stat(recheck_bak, f"backup file {abs_target}.bak")
                    if (recheck_bak.st_dev, recheck_bak.st_ino) != (
                        existing_bak_stat.st_dev,
                        existing_bak_stat.st_ino,
                    ):
                        raise PermissionError(f"Backup file {abs_target}.bak changed inode before replacement.")

                os.replace(tmp_bak_name, bak_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            except Exception:
                try:
                    os.unlink(tmp_bak_name, dir_fd=dir_fd)
                except OSError:
                    pass
                raise

        serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        tmp_main_name = f".{target_name}.{secrets.token_hex(8)}.tmp"
        fd_tm = os.open(
            tmp_main_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=dir_fd,
        )
        try:
            os.fchmod(fd_tm, 0o600)
            _write_all_and_fsync(fd_tm, serialized)
        except Exception:
            try:
                os.close(fd_tm)
            except OSError:
                pass
            try:
                os.unlink(tmp_main_name, dir_fd=dir_fd)
            except OSError:
                pass
            raise
        else:
            os.close(fd_tm)

        try:
            # Re-verify target file state immediately before descriptor-relative replace
            try:
                recheck_orig = os.stat(target_name, dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                if orig_stat is not None:
                    raise PermissionError(f"Target file {abs_target} disappeared before replacement.")
            else:
                if orig_stat is None:
                    raise PermissionError(f"Target file {abs_target} appeared unexpectedly before replacement.")
                _validate_regular_leaf_stat(recheck_orig, f"target file {abs_target}")
                if (recheck_orig.st_dev, recheck_orig.st_ino) != (orig_stat.st_dev, orig_stat.st_ino):
                    raise PermissionError(f"Target file {abs_target} changed inode before replacement.")

            os.replace(tmp_main_name, target_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except Exception:
            try:
                os.unlink(tmp_main_name, dir_fd=dir_fd)
            except OSError:
                pass
            raise

        try:
            os.fsync(dir_fd)
        except OSError as exc:
            raise ConfigDurabilityUncertainError(abs_target, str(exc)) from exc
    finally:
        os.close(dir_fd)

    return abs_target


def _create_credential_file_once_0600(
    cred_path: Path,
    payload: dict[str, Any],
    *,
    target_owner_user: str | None = None,
) -> None:
    """Create a private 0600 credential file exactly once with O_EXCL | O_NOFOLLOW; never overwrite."""
    abs_path = Path(os.path.abspath(str(cred_path.expanduser())))
    parent = abs_path.parent

    if target_owner_user is not None:
        try:
            pw_ent = pwd.getpwnam(target_owner_user)
        except KeyError:
            pw_ent = None
    else:
        pw_ent = None

    if pw_ent is not None and pw_ent.pw_uid != os.getuid():
        serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if os.getuid() != 0:
            helper = (
                "import json, sys; from pathlib import Path; "
                "from app.mcp.runtime_cli import _create_credential_file_once_0600; "
                "_create_credential_file_once_0600(Path(sys.argv[1]), json.load(sys.stdin), "
                "target_owner_user='patchdiff-mcp-agent')"
            )
            proc = subprocess.run(
                ["sudo", "-n", "--preserve-env=PYTHONPATH", "--", sys.executable,
                 "-c", helper, str(abs_path)], input=serialized,
                capture_output=True, timeout=15.0,
            )
            if proc.returncode != 0:
                detail = redact_sensitive_text(
                    (proc.stderr or b"").decode("utf-8", errors="replace"),
                    (str(payload.get("password", "")),),
                )
                raise PermissionError(f"Could not install service-owned credential: {detail}")
            return

        created_parent = False
        try:
            parent.mkdir(mode=0o700)
            created_parent = True
        except FileExistsError:
            pass
        if created_parent:
            os.chown(parent, pw_ent.pw_uid, pw_ent.pw_gid)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            st = os.fstat(parent_fd)
            if st.st_uid != pw_ent.pw_uid or stat.S_IMODE(st.st_mode) != 0o700:
                raise PermissionError("Agent credential directory must already have service ownership and mode 0700.")
            fd = os.open(abs_path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent_fd)
            try:
                os.fchmod(fd, 0o600)
                os.fchown(fd, pw_ent.pw_uid, pw_ent.pw_gid)
                _write_all_and_fsync(fd, serialized)
            except BaseException:
                os.unlink(abs_path.name, dir_fd=parent_fd)
                raise
            finally:
                os.close(fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return

    dir_fd = _open_pinned_private_dir(parent, create_if_missing=True)
    try:
        serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(
            abs_path.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=dir_fd,
        )
        try:
            os.fchmod(fd, 0o600)
            _write_all_and_fsync(fd, serialized)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(abs_path.name, dir_fd=dir_fd)
            except OSError:
                pass
            raise
        else:
            os.close(fd)
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _load_agent_credential_for_operator(agent_path: Path) -> dict[str, Any]:
    """Load the agent credential file during operator setup/daemon."""
    service = pwd.getpwnam(OS_AGENT_USER)
    try:
        return load_role_credential_file(
            agent_path, expected_role=DB_AGENT_USER, expected_owner_uid=service.pw_uid,
        )
    except PermissionError:
        # When agent_path is owned by patchdiff-mcp-agent (0600 in /var/lib/patchdiff-mcp-agent),
        # read and verify via privileged inspection as patchdiff-mcp-agent.
        try:
            pw_ent = pwd.getpwnam(OS_AGENT_USER)
        except KeyError:
            raise
        helper = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from app.core.config import load_role_credential_file\n"
            "print(json.dumps(load_role_credential_file(Path(sys.argv[1]), expected_role='patchdiff_agent')))\n"
        )
        proc = subprocess.run(
            ["sudo", "-n", "-u", OS_AGENT_USER, "--preserve-env=PYTHONPATH", "--", sys.executable, "-c", helper, str(agent_path)],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        if proc.returncode != 0:
            raise PermissionError(
                f"Failed to verify agent credential file {agent_path}: {(proc.stderr or proc.stdout).strip()}"
            )
        parsed = json.loads(proc.stdout)
        if not isinstance(parsed, dict) or parsed.get("username") != DB_AGENT_USER:
            raise PermissionError(f"Agent credential file {agent_path} has invalid role payload.")
        validate_credential_secret(str(parsed.get("password", "")), f"{DB_AGENT_USER} password")
        return parsed


def _resolve_agent_cred_path_for_runtime(runtime_dir: Path | None) -> Path:
    return get_agent_credentials_file_path(runtime_dir)


def preflight_credential_paths(runtime_dir: Path | None = None, *, port: int = DEFAULT_DOCKER_PORT) -> None:
    """Preflight credential file paths before creating any credentials or starting containers."""
    boot_path = get_bootstrap_credentials_file_path(runtime_dir)
    host_path = get_host_credentials_file_path(runtime_dir)
    agent_path = _resolve_agent_cred_path_for_runtime(runtime_dir)

    for path in (boot_path, host_path):
        if os.path.lexists(path.parent):
            directory = _open_pinned_private_dir(path.parent, create_if_missing=False)
            os.close(directory)
    if os.path.lexists(agent_path.parent):
        service_uid = pwd.getpwnam(OS_AGENT_USER).pw_uid
        parent = agent_path.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != service_uid
                or stat.S_IMODE(parent.st_mode) != 0o700):
            raise PermissionError("Agent credential parent must be a service-owned 0700 directory.")

    for path, role in (
        (boot_path, DB_BOOTSTRAP_USER),
        (host_path, DB_HOST_USER),
    ):
        if os.path.lexists(path):
            load_role_credential_file(path, expected_role=role)

    if os.path.lexists(agent_path):
        _load_agent_credential_for_operator(agent_path)


def ensure_runtime_credentials(
    runtime_dir: Path | None = None,
    *,
    port: int = DEFAULT_DOCKER_PORT,
    host: str = "127.0.0.1",
) -> dict[str, Any]:
    """Load or generate three separate 0600 credential files (bootstrap, host, agent) without overwriting existing files."""
    enforce_os_principal_for_operation("setup")
    preflight_credential_paths(runtime_dir, port=port)

    boot_path = get_bootstrap_credentials_file_path(runtime_dir)
    host_path = get_host_credentials_file_path(runtime_dir)
    agent_path = _resolve_agent_cred_path_for_runtime(runtime_dir)

    env_boot_pw = os.getenv("PATCHDIFF_BOOTSTRAP_DB_PASSWORD")
    env_host_pw = os.getenv("PATCHDIFF_HOST_DB_PASSWORD")
    env_agent_pw = os.getenv("PATCHDIFF_AGENT_DB_PASSWORD")
    for val, label in (
        (env_boot_pw, "PATCHDIFF_BOOTSTRAP_DB_PASSWORD"),
        (env_host_pw, "PATCHDIFF_HOST_DB_PASSWORD"),
        (env_agent_pw, "PATCHDIFF_AGENT_DB_PASSWORD"),
    ):
        if val is not None:
            validate_credential_secret(val, label)

    # 1. Bootstrap credentials
    if os.path.lexists(boot_path):
        boot_cred = load_role_credential_file(boot_path, expected_role=DB_BOOTSTRAP_USER)
    else:
        boot_pw = validate_credential_secret(env_boot_pw or secrets.token_urlsafe(32), "bootstrap_password")
        boot_cred = {
            "role": DB_BOOTSTRAP_USER,
            "username": DB_BOOTSTRAP_USER,
            "password": boot_pw,
            "host": host,
            "port": port,
            "dbname": DB_NAME,
        }
        _create_credential_file_once_0600(boot_path, boot_cred)

    # 2. Host credentials
    if os.path.lexists(host_path):
        host_cred = load_role_credential_file(host_path, expected_role=DB_HOST_USER)
    else:
        host_pw = validate_credential_secret(env_host_pw or secrets.token_urlsafe(32), "host_password")
        if host_pw == boot_cred["password"]:
            host_pw = secrets.token_urlsafe(32)
        host_cred = {
            "role": DB_HOST_USER,
            "username": DB_HOST_USER,
            "password": host_pw,
            "host": host,
            "port": port,
            "dbname": DB_NAME,
        }
        _create_credential_file_once_0600(host_path, host_cred)

    # 3. Agent credentials
    target_agent_owner = OS_AGENT_USER
    # Setup has already validated the accounts; a path override never changes
    # the agent secret's required owner to the operator.
    pwd.getpwnam(OS_AGENT_USER)

    agent_exists = os.path.lexists(agent_path)
    if not agent_exists and target_agent_owner is not None:
        # Check via sudo if /var/lib/patchdiff-mcp-agent is 0700 owned by patchdiff-mcp-agent
        chk = subprocess.run(
            ["sudo", "-n", "-u", OS_AGENT_USER, "--", "test", "-e", str(agent_path)],
            capture_output=True,
            timeout=5.0,
        )
        agent_exists = chk.returncode == 0

    if agent_exists:
        agent_cred = _load_agent_credential_for_operator(agent_path)
    else:
        agent_pw = validate_credential_secret(env_agent_pw or secrets.token_urlsafe(32), "agent_password")
        while agent_pw in {boot_cred["password"], host_cred["password"]}:
            agent_pw = secrets.token_urlsafe(32)
        agent_cred = {
            "role": DB_AGENT_USER,
            "username": DB_AGENT_USER,
            "password": agent_pw,
            "host": host,
            "port": port,
            "dbname": DB_NAME,
        }
        _create_credential_file_once_0600(agent_path, agent_cred, target_owner_user=target_agent_owner)

    if len({boot_cred["password"], host_cred["password"], agent_cred["password"]}) != 3:
        raise PermissionError("Bootstrap, host, and agent database passwords must be three distinct secrets.")

    return {
        "bootstrap_user": DB_BOOTSTRAP_USER,
        "bootstrap_password": boot_cred["password"],
        "bootstrap_credentials_file": str(boot_path),
        "host_user": DB_HOST_USER,
        "host_password": host_cred["password"],
        "host_credentials_file": str(host_path),
        "agent_user": DB_AGENT_USER,
        "agent_password": agent_cred["password"],
        "agent_credentials_file": str(agent_path),
        "dbname": str(boot_cred.get("dbname") or DB_NAME),
    }


def _read_existing_credentials_readonly(runtime_dir: Path | None = None) -> dict[str, Any] | None:
    """Read existing bootstrap/host credentials without creating or modifying any files (used by read-only status)."""
    boot_path = get_bootstrap_credentials_file_path(runtime_dir)
    host_path = get_host_credentials_file_path(runtime_dir)
    if not os.path.lexists(boot_path) or not os.path.lexists(host_path):
        return None
    try:
        boot_cred = load_role_credential_file(boot_path, expected_role=DB_BOOTSTRAP_USER)
        host_cred = load_role_credential_file(host_path, expected_role=DB_HOST_USER)
        return {
            "bootstrap_user": DB_BOOTSTRAP_USER,
            "bootstrap_password": boot_cred["password"],
            "bootstrap_credentials_file": str(boot_path),
            "host_user": DB_HOST_USER,
            "host_password": host_cred["password"],
            "host_credentials_file": str(host_path),
            "dbname": str(boot_cred.get("dbname") or DB_NAME),
        }
    except Exception:
        return None


def get_default_repo_root() -> Path:
    override = os.getenv("PATCHDIFF_REPO_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "docker-compose.yml").is_file():
        return candidate
    cwd = Path.cwd().resolve()
    if (cwd / "docker-compose.yml").is_file():
        return cwd
    return candidate


def _read_packaged_compose_bytes() -> bytes:
    resource_file = Path(__file__).resolve().parent / "resources" / "docker-compose.yml"
    if resource_file.is_file():
        return resource_file.read_bytes()
    pkg_files = importlib.resources.files("app.mcp.resources")
    return pkg_files.joinpath("docker-compose.yml").read_bytes()


def resolve_compose_workspace(
    repo_root: Path | None = None,
    runtime_dir: Path | None = None,
    *,
    read_only: bool = False,
) -> tuple[Path, Path]:
    """Return (working_dir, compose_file_path) using repo checkout if present, or packaged wheel resource."""
    if repo_root is not None:
        resolved = repo_root.expanduser().resolve()
        compose_path = resolved / "docker-compose.yml"
        if not compose_path.is_file():
            raise FileNotFoundError(f"docker-compose.yml not found at explicit repo_root {compose_path}")
        return resolved, compose_path

    env_root = os.getenv("PATCHDIFF_REPO_ROOT")
    if env_root:
        resolved = Path(env_root).expanduser().resolve()
        compose_path = resolved / "docker-compose.yml"
        if not compose_path.is_file():
            raise FileNotFoundError(f"docker-compose.yml not found at PATCHDIFF_REPO_ROOT={compose_path}")
        return resolved, compose_path

    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "docker-compose.yml").is_file() and (candidate / "pyproject.toml").is_file():
        return candidate, candidate / "docker-compose.yml"

    base_runtime = runtime_dir or get_default_runtime_dir()
    docker_dir = (base_runtime / "docker").resolve()
    compose_path = docker_dir / "docker-compose.yml"
    compose_bytes = _read_packaged_compose_bytes()
    if read_only:
        return docker_dir, compose_path

    dir_fd = _open_pinned_private_dir(docker_dir, create_if_missing=True)
    try:
        if not compose_path.is_file() or compose_path.read_bytes() != compose_bytes:
            tmp_name = f".docker-compose.{secrets.token_hex(6)}.yml"
            fd = os.open(
                tmp_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=dir_fd,
            )
            try:
                os.fchmod(fd, 0o600)
                _write_all_and_fsync(fd, compose_bytes)
            finally:
                os.close(fd)
            os.replace(tmp_name, "docker-compose.yml", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return docker_dir, compose_path


def get_compose_project_name(work_dir: Path) -> str:
    """Derive Compose project name: 'patchdiff-' + first 12 lowercase hex chars of SHA-256 of resolved work_dir."""
    override = os.getenv("PATCHDIFF_COMPOSE_PROJECT")
    if override:
        return override.strip()
    digest = hashlib.sha256(str(work_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"patchdiff-{digest}"


def get_alembic_ini_path() -> Path:
    packaged = Path(__file__).resolve().parents[1] / "migrations" / "alembic.ini"
    if packaged.is_file():
        return packaged
    repo_ini = get_default_repo_root() / "backend" / "app" / "migrations" / "alembic.ini"
    if repo_ini.is_file():
        return repo_ini
    raise FileNotFoundError(f"Could not locate alembic.ini at {packaged} or {repo_ini}")


def _role_user_and_password(role: str, creds: dict[str, Any]) -> tuple[str, str]:
    norm = role.strip().lower()
    if norm in {"agent", DB_AGENT_USER}:
        return creds["agent_user"], creds["agent_password"]
    if norm in {"host", DB_HOST_USER}:
        return creds["host_user"], creds["host_password"]
    if norm in {"bootstrap", "admin", DB_BOOTSTRAP_USER}:
        return creds["bootstrap_user"], creds["bootstrap_password"]
    raise ValueError(f"Unknown database role {role!r}; expected bootstrap, host, or agent.")


def build_database_url(
    port: int,
    host: str = "127.0.0.1",
    dbname: str = DB_NAME,
    *,
    role: str = "bootstrap",
    runtime_dir: Path | None = None,
    creds: dict[str, Any] | None = None,
) -> str:
    resolved_creds = creds or ensure_runtime_credentials(runtime_dir, port=port, host=host)
    user, password = _role_user_and_password(role, resolved_creds)
    return f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{dbname}"


def build_psycopg_dsn(
    port: int,
    host: str = "127.0.0.1",
    dbname: str = DB_NAME,
    *,
    role: str = "bootstrap",
    runtime_dir: Path | None = None,
    creds: dict[str, Any] | None = None,
) -> str:
    resolved_creds = creds or ensure_runtime_credentials(runtime_dir, port=port, host=host)
    user, password = _role_user_and_password(role, resolved_creds)
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{dbname}"


def _to_psycopg_dsn(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    return url


def is_tcp_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_db_connection(
    port: int,
    host: str = "127.0.0.1",
    dbname: str = DB_NAME,
    *,
    role: str = "bootstrap",
    runtime_dir: Path | None = None,
    creds: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    if creds is None:
        creds = _read_existing_credentials_readonly(runtime_dir)
        if creds is None:
            return False, None
    dsn = build_psycopg_dsn(port=port, host=host, dbname=dbname, role=role, runtime_dir=runtime_dir, creds=creds)
    return check_dsn_connection(dsn)


def check_dsn_connection(dsn: str) -> tuple[bool, str | None]:
    pg_dsn = _to_psycopg_dsn(dsn)
    try:
        with psycopg.connect(pg_dsn, connect_timeout=2) as conn:
            conn.execute("SELECT 1").fetchone()
            rev = None
            try:
                row = conn.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
                if row:
                    rev = str(row[0])
            except psycopg.Error:
                conn.rollback()
            return True, rev
    except Exception:
        return False, None


def _sql_ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def _provision_roles_and_database(port: int, creds: dict[str, Any], host: str = "127.0.0.1") -> None:
    """Provision patchdiff_bootstrap, patchdiff_host, and patchdiff_agent roles and database."""
    boot_user = creds["bootstrap_user"]
    boot_pw = creds["bootstrap_password"]
    host_user = creds["host_user"]
    host_pw = creds["host_password"]
    agent_user = creds["agent_user"]
    agent_pw = creds["agent_password"]
    dbname = creds["dbname"]

    conn = None
    for candidate_user, candidate_pw, candidate_db in (
        (boot_user, boot_pw, "postgres"),
        (boot_user, boot_pw, dbname),
    ):
        dsn = f"postgresql://{quote(candidate_user, safe='')}:{quote(candidate_pw, safe='')}@{host}:{port}/{candidate_db}"
        try:
            conn = psycopg.connect(dsn, autocommit=True, connect_timeout=3)
            break
        except Exception:
            continue

    if conn is None:
        raise RuntimeError(
            f"Could not authenticate to PostgreSQL on {host}:{port} as {boot_user!r}. "
            "Verify that container credentials match db_bootstrap_credentials.json."
        )

    try:
        # 1. Ensure bootstrap role exists as superuser
        row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (boot_user,)).fetchone()
        if not row:
            conn.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN SUPERUSER PASSWORD {}").format(
                    sql.Identifier(boot_user), sql.Literal(boot_pw)
                )
            )
        else:
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN SUPERUSER PASSWORD {}").format(
                    sql.Identifier(boot_user), sql.Literal(boot_pw)
                )
            )

        # 2. Ensure least-privilege host role exists (NOSUPERUSER NOCREATEDB NOCREATEROLE)
        row_host = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (host_user,)).fetchone()
        if not row_host:
            conn.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    sql.Identifier(host_user), sql.Literal(host_pw)
                )
            )
        else:
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    sql.Identifier(host_user), sql.Literal(host_pw)
                )
            )

        # 3. Ensure least-privilege agent role exists (NOSUPERUSER NOCREATEDB NOCREATEROLE)
        row_ag = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (agent_user,)).fetchone()
        if not row_ag:
            conn.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    sql.Identifier(agent_user), sql.Literal(agent_pw)
                )
            )
        else:
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    sql.Identifier(agent_user), sql.Literal(agent_pw)
                )
            )

        # 4. Disable any legacy 'patchdiff' or 'patchdiff_admin' roles so legacy defaults can never log in
        for legacy_role in ("patchdiff", "patchdiff_admin"):
            if legacy_role not in {boot_user, host_user, agent_user}:
                row_leg = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (legacy_role,)).fetchone()
                if row_leg:
                    rotated = secrets.token_urlsafe(32)
                    conn.execute(
                        sql.SQL("ALTER ROLE {} WITH NOSUPERUSER NOCREATEDB NOCREATEROLE NOLOGIN PASSWORD {}").format(
                            sql.Identifier(legacy_role), sql.Literal(rotated)
                        )
                    )

        # 5. Ensure target database exists and is owned by bootstrap role
        row_db = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not row_db:
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(dbname), sql.Identifier(boot_user)
                )
            )
        else:
            conn.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(dbname), sql.Identifier(boot_user)
                )
            )
    finally:
        conn.close()


def enforce_role_table_privileges_dsn(
    bootstrap_dsn: str,
    *,
    host_user: str = DB_HOST_USER,
    agent_user: str = DB_AGENT_USER,
    schema: str = "public",
) -> None:
    """Enforce the Stage B table and column-level SQL privilege matrix for patchdiff_host and patchdiff_agent."""
    pg_dsn = _to_psycopg_dsn(bootstrap_dsn)
    parsed = urlparse(pg_dsn)
    dbname = (parsed.path or "").lstrip("/") or DB_NAME

    host_ident = _sql_ident(host_user)
    agent_ident = _sql_ident(agent_user)
    db_ident = _sql_ident(dbname)
    schema_ident = _sql_ident(schema)

    all_managed_tables = set(HOST_SELECT_TABLES) | set(HOST_ONLY_TABLES)

    with psycopg.connect(pg_dsn, autocommit=True, connect_timeout=5) as conn:
        for role_name, role_ident in ((host_user, host_ident), (agent_user, agent_ident)):
            row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,)).fetchone()
            if not row:
                raise RuntimeError(f"Required PostgreSQL role {role_name!r} does not exist.")
            conn.execute(f"ALTER ROLE {role_ident} WITH NOSUPERUSER NOCREATEDB NOCREATEROLE")
            conn.execute(f"GRANT CONNECT ON DATABASE {db_ident} TO {role_ident}")
            conn.execute(f"GRANT USAGE ON SCHEMA {schema_ident} TO {role_ident}")
            conn.execute(f"REVOKE CREATE ON SCHEMA {schema_ident} FROM {role_ident}")

        conn.execute(f"REVOKE CREATE ON SCHEMA {schema_ident} FROM PUBLIC")

        # Remove any broad default privileges that may have been set previously
        boot_user = parsed.username or DB_BOOTSTRAP_USER
        boot_ident = _sql_ident(boot_user)
        conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {boot_ident} IN SCHEMA {schema_ident} "
            f"REVOKE ALL ON TABLES FROM {agent_ident}, {host_ident}, PUBLIC"
        )

        # Table REVOKE does not erase column ACLs left by an earlier policy.
        relations = conn.execute(
            "SELECT c.relname, string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
            "WHERE n.nspname=%s AND c.relkind IN ('r','p') GROUP BY c.relname", (schema,)
        ).fetchall()
        for table, columns in relations:
            relation = f"{schema_ident}.{_sql_ident(table)}"
            conn.execute(f"REVOKE ALL ON TABLE {relation} FROM {agent_ident}, {host_ident}, PUBLIC")
            conn.execute(f"REVOKE ALL ({columns}) ON TABLE {relation} FROM {agent_ident}, {host_ident}, PUBLIC")
        conn.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema_ident} FROM {agent_ident}, {host_ident}, PUBLIC")
        for sequence in ("append_only_pdcp_logs_log_sequence_seq", "append_only_manifest_ledger_ledger_sequence_seq"):
            if conn.execute("SELECT to_regclass(%s)", (f"{schema}.{sequence}",)).fetchone()[0]:
                conn.execute(f"GRANT USAGE, SELECT ON SEQUENCE {schema_ident}.{_sql_ident(sequence)} TO {agent_ident}, {host_ident}")

        # 1. patchdiff_host grants
        for tbl in HOST_SELECT_TABLES:
            exists = conn.execute("SELECT to_regclass(%s)", (f"{schema}.{tbl}",)).fetchone()
            if exists and exists[0]:
                conn.execute(f"GRANT SELECT ON TABLE {schema_ident}.{_sql_ident(tbl)} TO {host_ident}")

        for tbl in HOST_INSERT_TABLES:
            exists = conn.execute("SELECT to_regclass(%s)", (f"{schema}.{tbl}",)).fetchone()
            if exists and exists[0]:
                conn.execute(f"GRANT INSERT ON TABLE {schema_ident}.{_sql_ident(tbl)} TO {host_ident}")

        for tbl, cols in HOST_UPDATE_COLUMN_GRANTS.items():
            exists = conn.execute("SELECT to_regclass(%s)", (f"{schema}.{tbl}",)).fetchone()
            if exists and exists[0]:
                col_list = ", ".join(_sql_ident(c) for c in cols)
                conn.execute(
                    f"GRANT UPDATE ({col_list}) ON TABLE {schema_ident}.{_sql_ident(tbl)} TO {host_ident}"
                )



        # 2. patchdiff_agent grants (strictly allowlisted)
        for tbl in AGENT_SELECT_TABLES:
            exists = conn.execute("SELECT to_regclass(%s)", (f"{schema}.{tbl}",)).fetchone()
            if exists and exists[0]:
                conn.execute(f"GRANT SELECT ON TABLE {schema_ident}.{_sql_ident(tbl)} TO {agent_ident}")

        for tbl in AGENT_ONLY_INSERT_TABLES:
            exists = conn.execute("SELECT to_regclass(%s)", (f"{schema}.{tbl}",)).fetchone()
            if exists and exists[0]:
                conn.execute(f"GRANT INSERT ON TABLE {schema_ident}.{_sql_ident(tbl)} TO {agent_ident}")

        for tbl, cols in AGENT_UPDATE_COLUMN_GRANTS.items():
            exists = conn.execute("SELECT to_regclass(%s)", (f"{schema}.{tbl}",)).fetchone()
            if exists and exists[0]:
                col_list = ", ".join(_sql_ident(c) for c in cols)
                conn.execute(
                    f"GRANT UPDATE ({col_list}) ON TABLE {schema_ident}.{_sql_ident(tbl)} TO {agent_ident}"
                )




def enforce_role_table_privileges(
    port: int,
    *,
    runtime_dir: Path | None = None,
    creds: dict[str, Any] | None = None,
    host: str = "127.0.0.1",
) -> None:
    resolved_creds = creds or ensure_runtime_credentials(runtime_dir, port=port, host=host)
    boot_dsn = build_psycopg_dsn(
        port=port,
        host=host,
        dbname=resolved_creds["dbname"],
        role="bootstrap",
        creds=resolved_creds,
    )
    enforce_role_table_privileges_dsn(
        boot_dsn,
        host_user=resolved_creds["host_user"],
        agent_user=resolved_creds["agent_user"],
    )


def _ensure_compose_env_port(work_dir: Path, port: int) -> None:
    env_file = work_dir / ".env"
    key = "PATCHDIFF_POSTGRES_PORT"
    line = f"{key}={port}"
    if env_file.is_file():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        replaced = False
        new_lines = []
        for existing in lines:
            if existing.strip().startswith(f"{key}="):
                new_lines.append(line)
                replaced = True
            else:
                new_lines.append(existing)
        if not replaced:
            new_lines.append(line)
        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        env_file.write_text(line + "\n", encoding="utf-8")


def _inspect_docker_container(name_or_id: str) -> dict[str, Any] | None:
    proc = subprocess.run(
        ["docker", "inspect", name_or_id],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    if proc.returncode != 0:
        return None
    try:
        items = json.loads(proc.stdout)
        return items[0] if items else None
    except Exception:
        return None


def _list_docker_containers_by_filter(filter_expr: str) -> list[str]:
    proc = subprocess.run(
        ["docker", "ps", "-a", "--filter", filter_expr, "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _verify_container_ownership(info: dict[str, Any], work_dir: Path, project_name: str) -> None:
    """Verify container has BOTH exact com.docker.compose.project and com.docker.compose.project.working_dir (PR23-R4I-SCRIPT-001)."""
    cname = str(info.get("Name") or info.get("Id") or "<unknown>").lstrip("/")
    cid = str(info.get("Id") or "")[:12]
    labels = info.get("Config", {}).get("Labels") or {}
    c_project = labels.get("com.docker.compose.project", "")
    c_workdir = labels.get("com.docker.compose.project.working_dir", "")

    resolved_work = work_dir.resolve()
    if not c_project or not c_workdir:
        raise RuntimeError(
            f"Foreign or unlabeled Docker container conflict: container {cname!r} (id={cid!r}) is missing "
            f"Compose ownership labels (project={c_project!r}, working_dir={c_workdir!r}; "
            f"expected project={project_name!r}, working_dir={str(resolved_work)!r}). "
            "Refusing to mutate or remove container."
        )

    try:
        owner_work = Path(c_workdir).resolve()
    except Exception:
        owner_work = Path(c_workdir)

    if owner_work != resolved_work:
        raise RuntimeError(
            f"Foreign Docker container conflict: container {cname!r} (id={cid!r}) belongs to working_dir {c_workdir!r} "
            f"(expected {str(resolved_work)!r}). Refusing to stop or remove foreign container."
        )

    if c_project != project_name:
        raise RuntimeError(
            f"Docker Compose project conflict: container {cname!r} (id={cid!r}) in working_dir {c_workdir!r} "
            f"belongs to project {c_project!r} (expected {project_name!r}). "
            "Refusing to stop or remove container."
        )


def _find_project_postgres_container(work_dir: Path, port: int, project_name: str) -> dict[str, Any] | None:
    """Locate this project's postgres container or detect conflicts without ever deleting containers."""
    resolved_work = work_dir.resolve()
    candidates: list[str] = [f"{project_name}-postgres-1", f"{project_name}_postgres_1"]
    for filter_expr in (
        f"publish={port}",
        f"label=com.docker.compose.project={project_name}",
        f"label=com.docker.compose.project.working_dir={resolved_work}",
    ):
        for cname in _list_docker_containers_by_filter(filter_expr):
            if cname not in candidates:
                candidates.append(cname)

    owned_info: dict[str, Any] | None = None
    for cand in candidates:
        info = _inspect_docker_container(cand)
        if info is None:
            continue
        is_running = bool(info.get("State", {}).get("Running", False))
        bindings = info.get("HostConfig", {}).get("PortBindings", {}).get("5432/tcp") or []
        bound_ports = {str(b.get("HostPort", "")) for b in bindings if isinstance(b, dict)}
        labels = info.get("Config", {}).get("Labels") or {}
        c_project = labels.get("com.docker.compose.project", "")

        if (is_running and str(port) in bound_ports) or c_project == project_name:
            _verify_container_ownership(info, work_dir, project_name)
            owned_info = info
            break
    return owned_info


def docker_daemon(
    action: str,
    *,
    port: int = DEFAULT_DOCKER_PORT,
    repo_root: Path | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    enforce_os_principal_for_operation("daemon")
    base_runtime = runtime_dir or get_default_runtime_dir()

    if action == "status":
        work_dir, _ = resolve_compose_workspace(repo_root=repo_root, runtime_dir=base_runtime, read_only=True)
        project_name = get_compose_project_name(work_dir)
        info = _find_project_postgres_container(work_dir, port, project_name)
        state = info.get("State", {}) if info else {}
        running = bool(state.get("Running", False))
        status_label = state.get("Status", "not_created") if info else "not_created"
        cname = str(info.get("Name", "")).lstrip("/") if info else f"{project_name}-postgres-1"
        existing_creds = _read_existing_credentials_readonly(base_runtime)
        db_ready, rev = (
            check_db_connection(port=port, role="bootstrap", runtime_dir=base_runtime, creds=existing_creds)
            if (running and existing_creds is not None)
            else (False, None)
        )
        redacted_url = (
            f"postgresql+psycopg://{DB_HOST_USER}:***@127.0.0.1:{port}/{DB_NAME}"
        )
        return {
            "action": "status",
            "status": "running" if (running and db_ready) else ("starting" if running else "stopped"),
            "host": "127.0.0.1",
            "port": port,
            "redacted_database_url": redacted_url,
            "db_ready": db_ready,
            "alembic_revision": rev,
            "container": cname,
            "project": project_name,
            "backend_detail": f"container={status_label}",
        }

    work_dir, compose_file = resolve_compose_workspace(repo_root=repo_root, runtime_dir=base_runtime)
    project_name = get_compose_project_name(work_dir)
    creds = ensure_runtime_credentials(base_runtime, port=port)
    host_redacted_url = redact_database_url(build_database_url(port=port, role="host", creds=creds))

    compose_env = {
        **os.environ,
        "PATCHDIFF_POSTGRES_PORT": str(port),
        "POSTGRES_DB": creds["dbname"],
        "POSTGRES_USER": creds["bootstrap_user"],
        "POSTGRES_PASSWORD": creds["bootstrap_password"],
    }

    if action == "stop":
        info = _find_project_postgres_container(work_dir, port, project_name)
        cname = str(info.get("Name", "")).lstrip("/") if info else f"{project_name}-postgres-1"
        if info is not None:
            _verify_container_ownership(info, work_dir, project_name)
            subprocess.run(
                ["docker", "compose", "-p", project_name, "-f", str(compose_file), "stop", "postgres"],
                cwd=str(work_dir),
                env=compose_env,
                check=True,
                capture_output=True,
                text=True,
                timeout=30.0,
            )
        return {
            "action": "stop",
            "status": "stopped",
            "host": "127.0.0.1",
            "port": port,
            "redacted_database_url": host_redacted_url,
            "db_ready": False,
            "alembic_revision": None,
            "container": cname,
            "project": project_name,
            "backend_detail": "container=exited",
        }

    if action == "restart":
        docker_daemon("stop", port=port, repo_root=repo_root, runtime_dir=base_runtime)
        res = docker_daemon("start", port=port, repo_root=repo_root, runtime_dir=base_runtime)
        res["action"] = "restart"
        return res

    if action == "start":
        existing_info = _find_project_postgres_container(work_dir, port, project_name)
        if existing_info is not None:
            _verify_container_ownership(existing_info, work_dir, project_name)
        elif is_tcp_port_open(port):
            raise RuntimeError(
                f"Loopback port 127.0.0.1:{port} is already in use by an unknown or non-Docker process. "
                "Refusing to start PostgreSQL container on occupied port."
            )

        _ensure_compose_env_port(work_dir, port)
        subprocess.run(
            ["docker", "compose", "-p", project_name, "-f", str(compose_file), "up", "-d", "postgres"],
            cwd=str(work_dir),
            env=compose_env,
            check=True,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        deadline = time.monotonic() + 30.0
        db_ready = False
        rev = None
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if is_tcp_port_open(port):
                try:
                    _provision_roles_and_database(port, creds)
                    db_ready, rev = check_db_connection(port=port, role="bootstrap", creds=creds)
                    if db_ready:
                        break
                except Exception as exc:
                    last_err = exc
            time.sleep(0.5)
        if not db_ready:
            err_msg = redact_sensitive_text(
                str(last_err) if last_err else "timeout",
                extra_secrets=(
                    creds["bootstrap_password"],
                    creds["host_password"],
                    creds["agent_password"],
                ),
            )
            raise RuntimeError(
                f"Docker service {project_name}/postgres failed to become ready on 127.0.0.1:{port} (last_error={err_msg})"
            )
        info = _find_project_postgres_container(work_dir, port, project_name)
        cname = str(info.get("Name", "")).lstrip("/") if info else f"{project_name}-postgres-1"
        return {
            "action": "start",
            "status": "running",
            "host": "127.0.0.1",
            "port": port,
            "redacted_database_url": host_redacted_url,
            "db_ready": db_ready,
            "alembic_revision": rev,
            "container": cname,
            "project": project_name,
            "backend_detail": "container=running",
        }

    raise ValueError(f"Unsupported daemon action: {action!r}")


def preflight_docker_setup(
    *,
    port: int = DEFAULT_DOCKER_PORT,
    repo_root: Path | None = None,
    runtime_dir: Path | None = None,
) -> None:
    """Preflight Docker daemon, Compose v2 plugin, port ownership, Compose asset, and credential paths before mutation."""
    enforce_os_principal_for_operation("setup")
    base_runtime = runtime_dir or get_default_runtime_dir()

    # 1. Verify packaged Compose asset is readable before touching disk
    compose_bytes = _read_packaged_compose_bytes()
    if b"postgres:16.3-alpine" not in compose_bytes:
        raise RuntimeError("Packaged docker-compose.yml asset is missing postgres:16.3-alpine service definition.")

    # 2. Verify credential path integrity before creating/mutating any files
    preflight_credential_paths(base_runtime, port=port)

    # 3. Verify Docker CLI, daemon, and Compose v2 plugin
    if not shutil.which("docker"):
        raise RuntimeError("Docker CLI ('docker') is not installed or not in PATH.")
    info_proc = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    if info_proc.returncode != 0:
        detail = (info_proc.stderr or info_proc.stdout or "").strip()
        raise RuntimeError(f"Docker daemon is not running or unreachable: {detail}")

    compose_ver = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    if compose_ver.returncode != 0:
        detail = (compose_ver.stderr or compose_ver.stdout or "").strip()
        raise RuntimeError(f"Docker Compose v2 plugin ('docker compose') is unavailable: {detail}")

    # 4. Verify container ownership and port availability without mutating disk
    work_dir, _ = resolve_compose_workspace(repo_root=repo_root, runtime_dir=base_runtime, read_only=True)
    project_name = get_compose_project_name(work_dir)
    existing = _find_project_postgres_container(work_dir, port, project_name)
    if existing is None and is_tcp_port_open(port):
        raise RuntimeError(
            f"Loopback port 127.0.0.1:{port} is already occupied by a foreign process or container."
        )


def _validate_and_preflight_external_dsns() -> tuple[str, str, str, str, int, str]:
    """Validate PATCHDIFF_BOOTSTRAP_DATABASE_URL, PATCHDIFF_HOST_DATABASE_URL, PATCHDIFF_AGENT_DATABASE_URL."""
    enforce_os_principal_for_operation("setup")
    boot_url = os.getenv("PATCHDIFF_BOOTSTRAP_DATABASE_URL", "").strip()
    host_url = os.getenv("PATCHDIFF_HOST_DATABASE_URL", "").strip()
    agent_url = os.getenv("PATCHDIFF_AGENT_DATABASE_URL", "").strip()

    if not boot_url or not host_url or not agent_url:
        raise RuntimeError(
            "External database setup (--external-database) requires all three environment variables: "
            "PATCHDIFF_BOOTSTRAP_DATABASE_URL, PATCHDIFF_HOST_DATABASE_URL, and PATCHDIFF_AGENT_DATABASE_URL."
        )

    validate_dsn_for_role(boot_url, required_role=DB_BOOTSTRAP_USER, disallow_bootstrap=False)
    validate_dsn_for_role(host_url, required_role=DB_HOST_USER, disallow_bootstrap=True)
    validate_dsn_for_role(agent_url, required_role=DB_AGENT_USER, disallow_bootstrap=True)

    p_boot = urlparse(_to_psycopg_dsn(boot_url))
    p_host = urlparse(_to_psycopg_dsn(host_url))
    p_agent = urlparse(_to_psycopg_dsn(agent_url))

    endpoints = {
        (p_boot.hostname or "127.0.0.1", p_boot.port or 5432, (p_boot.path or "").lstrip("/")),
        (p_host.hostname or "127.0.0.1", p_host.port or 5432, (p_host.path or "").lstrip("/")),
        (p_agent.hostname or "127.0.0.1", p_agent.port or 5432, (p_agent.path or "").lstrip("/")),
    }
    if len(endpoints) != 1:
        raise ValueError(
            "External database URLs (PATCHDIFF_BOOTSTRAP_DATABASE_URL, PATCHDIFF_HOST_DATABASE_URL, "
            "PATCHDIFF_AGENT_DATABASE_URL) must target the exact same PostgreSQL host, port, and database name."
        )

    users = {p_boot.username, p_host.username, p_agent.username}
    if users != {DB_BOOTSTRAP_USER, DB_HOST_USER, DB_AGENT_USER}:
        raise ValueError(
            f"External database URLs must use distinct role usernames "
            f"{DB_BOOTSTRAP_USER!r}, {DB_HOST_USER!r}, and {DB_AGENT_USER!r}."
        )

    if len({p_boot.password, p_host.password, p_agent.password}) != 3:
        raise ValueError("External database role passwords must be three distinct high-entropy secrets.")

    endpoint_host, endpoint_port, endpoint_db = next(iter(endpoints))

    # Verify reachability and PostgreSQL server major version >= 16 using bootstrap DSN
    try:
        with psycopg.connect(_to_psycopg_dsn(boot_url), connect_timeout=5) as conn:
            ver_row = conn.execute("SHOW server_version_num").fetchone()
            ver_num = int(ver_row[0]) if ver_row else 0
            if ver_num < 160000:
                raise RuntimeError(
                    f"External PostgreSQL server version is {ver_num} (< 160000); PostgreSQL 16+ is required."
                )
            user_row = conn.execute("SELECT current_user").fetchone()
            cur_user = str(user_row[0]) if user_row else ""
            if cur_user != DB_BOOTSTRAP_USER:
                raise PermissionError(
                    f"Bootstrap connection authenticated as {cur_user!r}, expected {DB_BOOTSTRAP_USER!r}."
                )
    except (RuntimeError, PermissionError, ValueError):
        raise
    except Exception as exc:
        redacted = redact_sensitive_text(
            str(exc),
            extra_secrets=(p_boot.password or "", p_host.password or "", p_agent.password or ""),
        )
        raise RuntimeError(
            f"Could not connect to external PostgreSQL at {endpoint_host}:{endpoint_port}/{endpoint_db}: {redacted}"
        ) from exc

    return boot_url, host_url, agent_url, endpoint_host, endpoint_port, endpoint_db


def verify_role_connections(host_dsn: str, agent_dsn: str) -> None:
    """Verify that patchdiff_host and patchdiff_agent authenticate as their exact non-superuser roles."""
    for dsn, expected_role in ((host_dsn, DB_HOST_USER), (agent_dsn, DB_AGENT_USER)):
        with psycopg.connect(_to_psycopg_dsn(dsn), connect_timeout=5) as conn:
            row = conn.execute(
                "SELECT current_user, usesuper FROM pg_user WHERE usename = current_user"
            ).fetchone()
            if not row or str(row[0]) != expected_role:
                raise PermissionError(
                    f"Database role verification failed: expected {expected_role!r}, got {row[0] if row else None!r}"
                )
            if bool(row[1]):
                raise PermissionError(f"Service role {expected_role!r} must not be a PostgreSQL superuser.")


def run_alembic_upgrade(
    bootstrap_database_url: str,
    *,
    runtime_dir: Path | None = None,
    creds: dict[str, Any] | None = None,
) -> str:
    validate_dsn_for_role(bootstrap_database_url, required_role=DB_BOOTSTRAP_USER, disallow_bootstrap=False)
    alembic_ini = get_alembic_ini_path()
    env = {
        **os.environ,
        "PATCHDIFF_DATABASE_URL": bootstrap_database_url,
    }
    env.pop("PATCHDIFF_MCP_PROFILE", None)
    env.pop("PATCHDIFF_DB_ROLE", None)

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=90.0,
    )
    if proc.returncode != 0:
        err = redact_sensitive_text((proc.stderr or proc.stdout or "").strip())
        raise RuntimeError(f"Alembic migration failed for {redact_database_url(bootstrap_database_url)}: {err}")

    enforce_role_table_privileges_dsn(bootstrap_database_url)
    ok, rev = check_dsn_connection(bootstrap_database_url)
    if not ok or not rev:
        raise RuntimeError(
            f"Alembic migration completed for {redact_database_url(bootstrap_database_url)}, "
            "but alembic_version is empty or unreadable."
        )
    return rev


def smoke_test_mcp_adapter(
    *,
    host_database_url: str,
    agent_database_url: str,
) -> dict[str, int]:
    from app.services.waymark_adapter import get_waymark_bridge_dir, resolve_node_executable

    bridge_dir = str(get_waymark_bridge_dir())
    node_path = resolve_node_executable()
    app_root = str(Path(__file__).resolve().parents[2])
    existing_pypath = os.environ.get("PYTHONPATH", "").strip()
    pypath = f"{app_root}:{existing_pypath}" if existing_pypath else app_root
    counts: dict[str, int] = {}

    for profile, dsn, expected_count in (
        ("observed_v2", agent_database_url, 5),
        ("full", host_database_url, 24),
    ):
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": os.environ.get("HOME", "/"),
            "PYTHONPATH": pypath,
            "PATCHDIFF_DATABASE_URL": dsn,
            "PATCHDIFF_MCP_PROFILE": profile,
            "PATCHDIFF_WAYMARK_BRIDGE_DIR": bridge_dir,
            "PATCHDIFF_NODE_BINARY": node_path,
            "PATCHDIFF_WAYMARK_MODE": "resident",
        }
        env.pop("PATCHDIFF_DB_ROLE", None)
        command = [sys.executable, "-m", "app.mcp.external_adapter"]
        if profile != "full":
            env.pop("HOME", None)
            command = ["sudo", "-n", "-u", OS_AGENT_USER,
                       "--preserve-env=PYTHONPATH,PATCHDIFF_DATABASE_URL,PATCHDIFF_MCP_PROFILE,PATCHDIFF_WAYMARK_BRIDGE_DIR,PATCHDIFF_NODE_BINARY,PATCHDIFF_WAYMARK_MODE",
                       "--", *command]
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            assert proc.stdin is not None and proc.stdout is not None
            init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            proc.stdin.write(json.dumps(init_req) + "\n" + json.dumps(list_req) + "\n")
            proc.stdin.flush()
            init_line = proc.stdout.readline()
            list_line = proc.stdout.readline()
            if not init_line or not list_line:
                err = redact_sensitive_text(proc.stderr.read() if proc.stderr else "")
                raise RuntimeError(f"MCP smoke test failed for profile={profile}: {err}")
            list_resp = json.loads(list_line)
            tools = list_resp.get("result", {}).get("tools", [])
            if len(tools) != expected_count:
                raise RuntimeError(
                    f"MCP profile {profile} returned {len(tools)} tools, expected {expected_count}"
                )
            counts[profile] = len(tools)
        finally:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
    return counts


def update_host_mcp_config(
    config_path: Path,
    *,
    port: int = DEFAULT_DOCKER_PORT,
    profile: str = "observed_v2",
    runtime_dir: Path | None = None,
) -> Path:
    """Atomically update host mcp_config.json without embedding bootstrap/host DSNs in agent config (Stage B & E)."""
    from app.services.waymark_adapter import get_waymark_bridge_dir, resolve_node_executable

    abs_config = Path(os.path.abspath(str(config_path.expanduser())))
    parent_dir = abs_config.parent

    # Verify parent and existing file before any credential generation or backup (Stage E)
    dir_fd = _open_pinned_private_dir(parent_dir, create_if_missing=True)
    try:
        existing: dict[str, Any] = {}
        try:
            st = os.stat(abs_config.name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            st = None

        if st is not None:
            _validate_regular_leaf_stat(st, f"MCP config path {abs_config}")
            fd_cfg = os.open(
                abs_config.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dir_fd,
            )
            try:
                fst = os.fstat(fd_cfg)
                _validate_regular_leaf_stat(fst, f"MCP config path {abs_config}")
                raw_bytes = b""
                while True:
                    chunk = os.read(fd_cfg, 65536)
                    if not chunk:
                        break
                    raw_bytes += chunk
                raw_text = raw_bytes.decode("utf-8")
            finally:
                os.close(fd_cfg)

            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Existing MCP configuration at {abs_config} contains malformed JSON; refusing to overwrite: {exc}"
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError(
                    f"Existing MCP configuration at {abs_config} must have a JSON object root (got {type(parsed).__name__})."
                )
            if "mcpServers" in parsed and not isinstance(parsed["mcpServers"], dict):
                raise ValueError(
                    f"Existing MCP configuration at {abs_config} has non-object 'mcpServers' field."
                )
            existing = dict(parsed)
    finally:
        os.close(dir_fd)

    creds = ensure_runtime_credentials(runtime_dir, port=port)
    bridge_dir = str(get_waymark_bridge_dir())
    node_path = resolve_node_executable()

    env_block: dict[str, str] = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATCHDIFF_MCP_PROFILE": profile,
        "PATCHDIFF_POSTGRES_PORT": str(port),
        "PATCHDIFF_WAYMARK_MODE": "resident",
        "PATCHDIFF_WAYMARK_BRIDGE_DIR": bridge_dir,
        "PATCHDIFF_NODE_BINARY": node_path,
    }
    if profile == "full":
        env_block["PATCHDIFF_HOST_CREDENTIAL_FILE"] = creds["host_credentials_file"]
    else:
        env_block["PATCHDIFF_AGENT_CREDENTIAL_FILE"] = creds["agent_credentials_file"]

    mcp_servers = dict(existing.get("mcpServers") or {})
    installed_bin = shutil.which("patchdiff-mcp") or str(Path(sys.executable).resolve().parent / "patchdiff-mcp")
    server_entry: dict[str, Any] = {
        "command": installed_bin if Path(installed_bin).is_file() else sys.executable,
        "args": [] if Path(installed_bin).is_file() else ["-m", "app.mcp.external_adapter"],
        "env": env_block,
        "tools": {
            "patchdiff_commit_bundle": {"eager": True},
            "patchdiff_find_occurrences": {"eager": True},
            "patchdiff_list_scopes": {"eager": True},
            "patchdiff_observe_scopes": {"eager": True},
            "patchdiff_read_target": {"eager": True},
        },
    }
    mcp_servers["patchdiff"] = server_entry
    existing["mcpServers"] = mcp_servers

    return _atomic_write_json_0600(abs_config, existing, make_backup=True)


def run_daemon_command(
    action: str,
    *,
    port: int = DEFAULT_DOCKER_PORT,
    repo_root: Path | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    d_info = docker_daemon(action, port=port, repo_root=repo_root, runtime_dir=runtime_dir)
    return {"command": f"daemon.{action}", "docker": d_info}


def run_setup_command(
    *,
    port: int = DEFAULT_DOCKER_PORT,
    external_database: bool = False,
    mcp_config: Path | None = None,
    update_mcp: bool = False,
    repo_root: Path | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    enforce_os_principal_for_operation("setup")

    if external_database:
        boot_url, host_url, agent_url, ext_host, ext_port, ext_db = _validate_and_preflight_external_dsns()
        from app.services.waymark_adapter import get_waymark_bridge_dir
        from app.waymark_bridge.bootstrap import bootstrap_bridge, verify_installed_bridge

        bridge_dir = get_waymark_bridge_dir()
        try:
            waymark_version = verify_installed_bridge(bridge_dir)
        except Exception:
            bootstrapped = bootstrap_bridge(bridge_dir)
            waymark_version = verify_installed_bridge(bootstrapped)

        rev = run_alembic_upgrade(boot_url)
        verify_role_connections(host_url, agent_url)
        smoke = smoke_test_mcp_adapter(host_database_url=host_url, agent_database_url=agent_url)
        return {
            "command": "setup",
            "mode": "external_database",
            "status": "ready",
            "host": ext_host,
            "port": ext_port,
            "dbname": ext_db,
            "redacted_bootstrap_database_url": redact_database_url(boot_url),
            "redacted_host_database_url": redact_database_url(host_url),
            "redacted_agent_database_url": redact_database_url(agent_url),
            "alembic_revision": rev,
            "mcp_smoke_tools": smoke,
            "waymark_bridge": {"path": str(bridge_dir), "version": waymark_version},
        }

    # Bundled Docker Compose setup: preflight everything before creating credentials or containers
    preflight_docker_setup(port=port, repo_root=repo_root, runtime_dir=runtime_dir)

    from app.services.waymark_adapter import get_waymark_bridge_dir
    from app.waymark_bridge.bootstrap import bootstrap_bridge, verify_installed_bridge

    bridge_dir = get_waymark_bridge_dir()
    try:
        waymark_version = verify_installed_bridge(bridge_dir)
    except Exception:
        bootstrapped = bootstrap_bridge(bridge_dir)
        waymark_version = verify_installed_bridge(bootstrapped)

    creds = ensure_runtime_credentials(runtime_dir, port=port)
    d_info = docker_daemon("start", port=port, repo_root=repo_root, runtime_dir=runtime_dir)

    boot_url = build_database_url(port=port, role="bootstrap", runtime_dir=runtime_dir, creds=creds)
    host_url = build_database_url(port=port, role="host", runtime_dir=runtime_dir, creds=creds)
    agent_url = build_database_url(port=port, role="agent", runtime_dir=runtime_dir, creds=creds)

    try:
        rev = run_alembic_upgrade(boot_url, runtime_dir=runtime_dir, creds=creds)
        verify_role_connections(host_url, agent_url)
        smoke = smoke_test_mcp_adapter(host_database_url=host_url, agent_database_url=agent_url)
    except Exception as exc:
        redacted_err = redact_sensitive_text(
            str(exc),
            extra_secrets=(
                creds["bootstrap_password"],
                creds["host_password"],
                creds["agent_password"],
            ),
        )
        raise SetupPartialFailureError(
            f"Docker PostgreSQL container started, but post-start migration/verification failed: {redacted_err}",
            stage="post_container_start",
            partial_state={
                "container": d_info.get("container"),
                "project": d_info.get("project"),
                "port": port,
                "redacted_database_url": redact_database_url(host_url),
            },
            reconciliation_instructions=(
                "Inspect PostgreSQL logs with 'docker logs <container>', resolve the schema or role error, "
                "and re-run 'patchdiff-mcp-setup'."
            ),
        ) from exc

    d_info["alembic_revision"] = rev
    d_info["mcp_smoke_tools"] = smoke

    updated_config_path: str | None = None
    if update_mcp or mcp_config is not None:
        target_cfg = mcp_config or (Path.home() / ".gemini" / "config" / "mcp_config.json")
        written = update_host_mcp_config(
            target_cfg,
            port=port,
            runtime_dir=runtime_dir,
        )
        updated_config_path = str(written)

    return {
        "command": "setup",
        "mode": "docker",
        "status": "ready",
        "waymark_bridge": {"path": str(bridge_dir), "version": waymark_version},
        "docker": d_info,
        "redacted_host_database_url": redact_database_url(host_url),
        "redacted_agent_database_url": redact_database_url(agent_url),
        "mcp_config_updated": updated_config_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patchdiff-mcp",
        description="PatchDIFF Docker-only PostgreSQL setup and daemon lifecycle CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    setup_p = subparsers.add_parser(
        "setup",
        help="Provision, migrate, and smoke-test Docker Compose PostgreSQL (default 127.0.0.1:5433) or --external-database",
    )
    setup_p.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PATCHDIFF_POSTGRES_PORT", str(DEFAULT_DOCKER_PORT))),
        help=f"Loopback port for Docker Compose PostgreSQL service (default: {DEFAULT_DOCKER_PORT})",
    )
    setup_p.add_argument(
        "--external-database",
        action="store_true",
        help="Connect to an already-running external PostgreSQL 16+ instance using PATCHDIFF_BOOTSTRAP_DATABASE_URL, PATCHDIFF_HOST_DATABASE_URL, and PATCHDIFF_AGENT_DATABASE_URL without Docker or native provisioning",
    )
    setup_p.add_argument(
        "--mcp-config",
        type=Path,
        default=None,
        help="Path to host mcp_config.json to update (default: ~/.gemini/config/mcp_config.json when --update-mcp-config is set)",
    )
    setup_p.add_argument(
        "--update-mcp-config",
        action="store_true",
        help="Update host MCP configuration to point to the PatchDIFF MCP adapter",
    )

    daemon_p = subparsers.add_parser(
        "daemon",
        help="Start, stop, restart, or inspect the checkout-scoped Docker Compose PostgreSQL service",
    )
    daemon_p.add_argument(
        "action",
        choices=("start", "stop", "restart", "status"),
        help="Lifecycle action to execute",
    )
    daemon_p.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PATCHDIFF_POSTGRES_PORT", str(DEFAULT_DOCKER_PORT))),
        help=f"Loopback port for Docker Compose PostgreSQL service (default: {DEFAULT_DOCKER_PORT})",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(effective_argv)
    try:
        if args.subcommand == "setup":
            result = run_setup_command(
                port=args.port,
                external_database=args.external_database,
                mcp_config=args.mcp_config,
                update_mcp=args.update_mcp_config,
            )
        elif args.subcommand == "daemon":
            result = run_daemon_command(
                args.action,
                port=args.port,
            )
        else:
            parser.error(f"Unknown subcommand: {args.subcommand}")
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ConfigDurabilityUncertainError as exc:
        payload = {
            "status": "durability_uncertain",
            "installed": True,
            "path": str(exc.path),
            "error": redact_sensitive_text(str(exc)),
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    except SetupPartialFailureError as exc:
        payload = {
            "status": "partial_failure",
            "stage": exc.stage,
            "partial_state": exc.partial_state,
            "reconciliation_instructions": exc.reconciliation_instructions,
            "error": redact_sensitive_text(str(exc)),
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            json.dumps({"status": "error", "error": redact_sensitive_text(str(exc))}, indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return 1


def setup_entrypoint() -> None:
    raise SystemExit(main(["setup", *sys.argv[1:]]))


def daemon_entrypoint() -> None:
    raise SystemExit(main(["daemon", *sys.argv[1:]]))


if __name__ == "__main__":
    raise SystemExit(main())
