from __future__ import annotations

import errno
import grp
import json
import os
import pwd
import re
import stat
from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse, urlunparse

DB_BOOTSTRAP_USER = "patchdiff_bootstrap"
DB_HOST_USER = "patchdiff_host"
DB_AGENT_USER = "patchdiff_agent"
DB_NAME = "patchdiff"
DEFAULT_DOCKER_PORT = 5433

OS_AGENT_USER = "patchdiff-mcp-agent"
OS_MODEL_USER = "patchdiff-model"

DEFAULT_AGENT_SECRET_DIR = Path("/var/lib/patchdiff-mcp-agent")
DEFAULT_AGENT_SECRET_FILE = DEFAULT_AGENT_SECRET_DIR / "db_agent_credentials.json"

FORBIDDEN_DEFAULT_PASSWORDS = frozenset({"patchdiff", "postgres", "password", "admin", "123456", ""})
PRIVILEGED_OS_GROUPS = frozenset({"sudo", "wheel", "admin", "docker", "root"})

AGENT_SELECT_TABLES = (
    "users",
    "projects",
    "project_memberships",
    "cloud_target_files",
    "target_snapshots",
    "editing_cycles",
    "append_only_pdcp_logs",
    "append_only_manifest_ledger",
    "current_pdcp_files",
    "target_scope_observations",
)
AGENT_ONLY_INSERT_TABLES = (
    "target_scope_observations",
    "append_only_pdcp_logs",
    "append_only_manifest_ledger",
    "current_pdcp_files",
)
AGENT_UPDATE_COLUMN_GRANTS: dict[str, tuple[str, ...]] = {
    "cloud_target_files": (
        "current_content",
        "current_hash",
        "version",
        "latest_accepted_pdcp_log_id",
        "updated_at",
    ),
    "target_scope_observations": (
        "accepted_pdcp_log_id",
    ),
    "current_pdcp_files": (
        "editing_cycle_id",
        "protocol_version",
        "pdcp_content",
        "pdcp_content_hash",
        "status",
        "submission_source",
        "parent_pdcp_log_id",
        "regeneration_attempt",
        "regeneration_source",
        "last_pdcp_log_id",
        "updated_at",
    ),
}
HOST_ONLY_TABLES = (
    "target_finalizations",
    "target_finalization_export_chunks",
    "alembic_version",
)
HOST_SELECT_TABLES = (
    *AGENT_SELECT_TABLES,
    "target_finalizations",
    "target_finalization_export_chunks",
)
HOST_INSERT_TABLES = (
    "users",
    "projects",
    "project_memberships",
    "cloud_target_files",
    "target_snapshots",
    "editing_cycles",
    "append_only_pdcp_logs",
    "append_only_manifest_ledger",
    "current_pdcp_files",
    "target_scope_observations",
    "target_finalizations",
    "target_finalization_export_chunks",
)
HOST_UPDATE_COLUMN_GRANTS: dict[str, tuple[str, ...]] = {
    "users": (
        "display_name",
        "updated_at",
    ),
    "projects": (
        "name",
        "updated_at",
    ),
    "cloud_target_files": (
        "current_content",
        "current_hash",
        "version",
        "active_editing_cycle_id",
        "latest_accepted_pdcp_log_id",
        "initial_snapshot_id",
        "updated_at",
    ),
    "editing_cycles": (
        "status",
        "closed_at",
        "closed_by_user_id",
        "save_snapshot_id",
    ),
    "target_scope_observations": (
        "accepted_pdcp_log_id",
    ),
    "current_pdcp_files": (
        "editing_cycle_id",
        "protocol_version",
        "pdcp_content",
        "pdcp_content_hash",
        "status",
        "submission_source",
        "parent_pdcp_log_id",
        "regeneration_attempt",
        "regeneration_source",
        "last_pdcp_log_id",
        "updated_at",
    ),

}

_STRICT_OBSERVATION_MODE_OVERRIDE: ContextVar[bool | None] = ContextVar(
    "patchdiff_strict_observation_mode_override",
    default=None,
)
_ACTIVE_MCP_PROFILE_CTX: ContextVar[str | None] = ContextVar(
    "patchdiff_active_mcp_profile_ctx",
    default=None,
)
_PROCESS_MCP_PROFILE: str | None = None
_PROCESS_REQUIRED_DB_ROLE: str | None = None


def _parse_bool_env(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_strict_observation_mode_enabled() -> bool:
    """Return True when every target-mutating submission route must carry a valid observation."""
    override = _STRICT_OBSERVATION_MODE_OVERRIDE.get()
    if override is not None:
        return override
    return _parse_bool_env(os.getenv("PATCHDIFF_STRICT_OBSERVATION_MODE"))


@contextmanager
def strict_observation_mode(enabled: bool = True):
    """Context-manager / test-fixture hook to toggle strict observation mode deterministically."""
    token = _STRICT_OBSERVATION_MODE_OVERRIDE.set(bool(enabled))
    try:
        yield
    finally:
        _STRICT_OBSERVATION_MODE_OVERRIDE.reset(token)


@contextmanager
def active_mcp_profile_context(profile: str):
    """Bind the active MCP profile for the current tool invocation."""
    token = _ACTIVE_MCP_PROFILE_CTX.set(profile)
    try:
        yield
    finally:
        _ACTIVE_MCP_PROFILE_CTX.reset(token)


def get_active_mcp_profile() -> str | None:
    ctx_profile = _ACTIVE_MCP_PROFILE_CTX.get()
    if ctx_profile is not None:
        return ctx_profile
    return _PROCESS_MCP_PROFILE


def get_required_db_role_for_profile(profile: str | None = None) -> str | None:
    effective = profile or get_active_mcp_profile()
    if effective is None:
        return _PROCESS_REQUIRED_DB_ROLE
    return DB_HOST_USER if effective == "full" else DB_AGENT_USER


def validate_credential_secret(password: str, label: str = "password") -> str:
    if (
        not isinstance(password, str)
        or password.strip().lower() in FORBIDDEN_DEFAULT_PASSWORDS
        or len(password) < 32
    ):
        raise ValueError(
            f"Rejected insecure or known-default {label}; credentials must be high-entropy secrets (>=32 chars, never 'patchdiff')."
        )
    return password


def redact_database_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        return ""
    try:
        parsed = urlparse(url)
        if parsed.password is not None:
            user_part = f"{parsed.username}:***" if parsed.username else "***"
            host_part = parsed.hostname or ""
            netloc = f"{user_part}@{host_part}" if host_part else user_part
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        pass
    return re.sub(r"(://[^:/@\s]+:)[^@\s]+(@)", r"\1***\2", url)


def redact_sensitive_text(text: str, extra_secrets: Iterable[str] = ()) -> str:
    if not isinstance(text, str) or not text:
        return ""
    out = re.sub(r"(postgresql(?:\+\w+)?://[^:/@\s]+:)[^@\s]+(@)", r"\1***\2", text)
    out = re.sub(r"(?i)(password\s*[=:]\s*)([^\s,;\"']+)", r"\1***", out)
    out = re.sub(r"(?i)(POSTGRES_PASSWORD\s*[=:]\s*)([^\s,;\"']+)", r"\1***", out)
    for env_key in (
        "POSTGRES_PASSWORD",
        "PATCHDIFF_BOOTSTRAP_DB_PASSWORD",
        "PATCHDIFF_HOST_DB_PASSWORD",
        "PATCHDIFF_AGENT_DB_PASSWORD",
        "PATCHDIFF_ADMIN_DB_PASSWORD",
    ):
        val = os.getenv(env_key)
        if val:
            out = out.replace(val, "***").replace(quote(val, safe=""), "***")
    for url_env in (
        "PATCHDIFF_DATABASE_URL",
        "PATCHDIFF_BOOTSTRAP_DATABASE_URL",
        "PATCHDIFF_HOST_DATABASE_URL",
        "PATCHDIFF_AGENT_DATABASE_URL",
    ):
        raw_u = os.getenv(url_env)
        if raw_u:
            try:
                pw = urlparse(raw_u).password
                if pw:
                    unq = unquote(pw)
                    out = out.replace(pw, "***").replace(unq, "***").replace(quote(unq, safe=""), "***")
            except Exception:
                pass
    for sec in extra_secrets:
        if isinstance(sec, str) and sec:
            out = out.replace(sec, "***").replace(quote(sec, safe=""), "***")
    return out


def get_default_runtime_dir() -> Path:
    override = os.getenv("PATCHDIFF_RUNTIME_DIR")
    if override:
        return Path(os.path.abspath(Path(override).expanduser()))
    return Path(os.path.abspath(Path.home() / ".local" / "share" / "patchdiff-runtime"))


def get_bootstrap_credentials_file_path(runtime_dir: Path | None = None) -> Path:
    override = os.getenv("PATCHDIFF_BOOTSTRAP_CREDENTIALS_FILE") or os.getenv("PATCHDIFF_BOOTSTRAP_CREDENTIAL_FILE")
    if override:
        return Path(os.path.abspath(Path(override).expanduser()))
    base = runtime_dir or get_default_runtime_dir()
    return Path(os.path.abspath(base.expanduser())) / "db_bootstrap_credentials.json"


def get_host_credentials_file_path(runtime_dir: Path | None = None) -> Path:
    override = os.getenv("PATCHDIFF_HOST_CREDENTIALS_FILE") or os.getenv("PATCHDIFF_HOST_CREDENTIAL_FILE")
    if override:
        return Path(os.path.abspath(Path(override).expanduser()))
    base = runtime_dir or get_default_runtime_dir()
    return Path(os.path.abspath(base.expanduser())) / "db_host_credentials.json"


def get_agent_credentials_file_path(runtime_dir: Path | None = None) -> Path:
    override = os.getenv("PATCHDIFF_AGENT_CREDENTIALS_FILE") or os.getenv("PATCHDIFF_AGENT_CREDENTIAL_FILE")
    if override:
        return Path(os.path.abspath(Path(override).expanduser()))
    return DEFAULT_AGENT_SECRET_FILE


def _get_effective_os_username() -> str:
    try:
        return pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:
        return ""


def _lookup_passwd(username: str) -> pwd.struct_passwd | None:
    try:
        return pwd.getpwnam(username)
    except KeyError:
        return None


def _user_groups(username: str, primary_gid: int) -> set[str]:
    names: set[str] = set()
    try:
        names.add(grp.getgrgid(primary_gid).gr_name)
    except KeyError:
        pass
    for g in grp.getgrall():
        if username in g.gr_mem:
            names.add(g.gr_name)
    return names


def verify_three_uid_separation(*, require_accounts: bool = True) -> dict[str, int]:
    """Validate operator, patchdiff-mcp-agent, and patchdiff-model POSIX account boundaries."""
    agent_pw = _lookup_passwd(OS_AGENT_USER)
    model_pw = _lookup_passwd(OS_MODEL_USER)
    if agent_pw is None or model_pw is None:
        raise PermissionError(
            f"Three-UID POSIX separation is missing: unprivileged accounts {OS_AGENT_USER!r} and "
            f"{OS_MODEL_USER!r} must both exist. Create them as root:\n"
            f"  sudo useradd --system --no-create-home --shell /usr/sbin/nologin {OS_AGENT_USER}\n"
            f"  sudo useradd --system --no-create-home --shell /usr/sbin/nologin {OS_MODEL_USER}"
        )

    if agent_pw.pw_uid == 0 or model_pw.pw_uid == 0:
        raise PermissionError(f"Unprivileged principals {OS_AGENT_USER!r} and {OS_MODEL_USER!r} must never have UID 0.")
    if agent_pw.pw_uid == model_pw.pw_uid:
        raise PermissionError(
            f"Three-UID isolation violation: {OS_AGENT_USER!r} and {OS_MODEL_USER!r} share UID {agent_pw.pw_uid}."
        )

    for acct_pw in (agent_pw, model_pw):
        bad_groups = _user_groups(acct_pw.pw_name, acct_pw.pw_gid) & PRIVILEGED_OS_GROUPS
        if bad_groups:
            raise PermissionError(
                f"Unprivileged account {acct_pw.pw_name!r} must not belong to privileged groups: {sorted(bad_groups)}"
            )

    return {
        OS_AGENT_USER: agent_pw.pw_uid,
        OS_MODEL_USER: model_pw.pw_uid,
    }


def enforce_os_principal_for_operation(operation: str, *, profile: str | None = None) -> None:
    """Enforce OS UID boundaries for setup, daemon, and MCP profile startup before any DB or Docker access."""
    euid = os.geteuid()
    ename = _get_effective_os_username()
    agent_pw = _lookup_passwd(OS_AGENT_USER)
    model_pw = _lookup_passwd(OS_MODEL_USER)

    if ename == OS_MODEL_USER or (model_pw is not None and euid == model_pw.pw_uid):
        raise PermissionError(
            f"Untrusted model/sandbox OS principal {OS_MODEL_USER!r} (uid={euid}) is prohibited from running {operation}."
        )

    if ename == OS_AGENT_USER or (agent_pw is not None and euid == agent_pw.pw_uid):
        if operation in {"setup", "daemon", "bootstrap"}:
            raise PermissionError(
                f"Unprivileged editor service principal {OS_AGENT_USER!r} (uid={euid}) cannot run operator command {operation!r}."
            )
        if profile == "full":
            raise PermissionError(
                f"Unprivileged editor service principal {OS_AGENT_USER!r} (uid={euid}) is prohibited from starting PATCHDIFF_MCP_PROFILE='full'."
            )

    if operation in {"setup", "daemon"} or (operation == "mcp" and profile != "full"):
        uids = verify_three_uid_separation(require_accounts=True)
        assert uids is not None
        if operation == "mcp" and profile != "full" and euid != uids[OS_AGENT_USER]:
            raise PermissionError(
                f"Editor MCP profile {profile!r} must run as service UID {OS_AGENT_USER!r} (uid={uids[OS_AGENT_USER]}), "
                f"not UID {euid}. Launch via: sudo -n -u {OS_AGENT_USER} -- <installed-path>/patchdiff-mcp"
            )
        if operation in {"setup", "daemon"} or profile == "full":
            if euid in {uids[OS_AGENT_USER], uids[OS_MODEL_USER]}:
                raise PermissionError(
                    f"Operator operation {operation!r} (profile={profile!r}) must run as operator UID, not {euid}."
                )


@contextmanager
def _credential_parent_fd(path: Path, owner_uid: int):
    """Pin a private credential parent without following any lexical ancestor."""
    descriptors = [os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)]
    try:
        parts = path.parent.parts[1:]
        for index, part in enumerate(parts):
            try:
                directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                    dir_fd=descriptors[-1])
            except OSError as exc:
                raise PermissionError("Credential directory path is inaccessible or contains a symlink.") from exc
            descriptors.append(directory)
            st = os.fstat(directory)
            mode = stat.S_IMODE(st.st_mode)
            final = index == len(parts)-1
            if final:
                if st.st_uid != owner_uid or mode != 0o700:
                    raise PermissionError("Credentials directory must have expected ownership and mode 0o700.")
            else:
                sticky_tmp = part == "tmp" and index == 0 and st.st_uid == 0 and bool(st.st_mode & stat.S_ISVTX)
                if st.st_uid not in {0, owner_uid} or (mode & 0o022 and not sticky_tmp):
                    raise PermissionError("Credential ancestor has unexpected ownership or writable permissions.")
        if not parts:
            raise PermissionError("Credentials require a private parent directory.")
        yield descriptors[-1]
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def load_role_credential_file(
    cred_path: Path,
    *,
    expected_role: str,
    expected_owner_uid: int | None = None,
) -> dict[str, Any]:
    """Read and validate a single-role 0600 JSON secret file without following symlinks or hardlinks."""
    owner_uid = os.geteuid() if expected_owner_uid is None else expected_owner_uid
    cred_path = Path(os.path.abspath(cred_path.expanduser()))
    with _credential_parent_fd(cred_path, owner_uid) as parent_fd:
        try:
            lst = os.stat(cred_path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Required credential file {cred_path} for role {expected_role!r} does not exist.") from exc
        except OSError as exc:
            raise PermissionError(f"Could not stat credential file {cred_path}: {exc.strerror}") from exc

        if stat.S_ISLNK(lst.st_mode):
            raise PermissionError(f"Rejected symlink credential file {cred_path}.")
        if not stat.S_ISREG(lst.st_mode):
            raise PermissionError(f"Credential file {cred_path} must be a regular file.")
        if lst.st_nlink != 1:
            raise PermissionError(f"Rejected hardlinked credential file {cred_path} (st_nlink={lst.st_nlink}).")
        if stat.S_IMODE(lst.st_mode) != 0o600:
            raise PermissionError(
                f"Credential file {cred_path} has insecure mode {oct(stat.S_IMODE(lst.st_mode))}; expected 0o600."
            )
        if lst.st_uid != owner_uid:
            raise PermissionError(
                f"Credential file {cred_path} is owned by uid={lst.st_uid}, expected uid={owner_uid}."
            )

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(cred_path.name, flags, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PermissionError(f"Rejected symlink credential file {cred_path}.") from exc
            raise PermissionError(f"Failed to open credential file {cred_path}: {exc.strerror}") from exc

        try:
            fst = os.fstat(fd)
            if (fst.st_dev, fst.st_ino) != (lst.st_dev, lst.st_ino):
                raise PermissionError(f"Credential file {cred_path} inode changed during open.")
            if not stat.S_ISREG(fst.st_mode) or fst.st_nlink != 1 or stat.S_IMODE(fst.st_mode) != 0o600 or fst.st_uid != owner_uid:
                raise PermissionError(f"Credential file {cred_path} failed post-open ownership/mode/link validation.")
            chunks: list[bytes] = []
            while True:
                buf = os.read(fd, 65536)
                if not buf:
                    break
                chunks.append(buf)
            raw_bytes = b"".join(chunks)
        finally:
            os.close(fd)

    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Credential file {cred_path} does not contain valid UTF-8 JSON.") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"Credential file {cred_path} must contain a JSON object.")

    forbidden_mixed_keys = {
        "admin_user",
        "admin_password",
        "bootstrap_user",
        "bootstrap_password",
        "host_user",
        "host_password",
        "agent_user",
        "agent_password",
    }
    if forbidden_mixed_keys & set(parsed.keys()):
        raise PermissionError(
            f"Rejected mixed-role credential file {cred_path}; each role must use its own separate secret file."
        )

    role_val = str(parsed.get("role") or "")
    user_val = str(parsed.get("username") or "")
    if role_val != expected_role or user_val != expected_role:
        raise PermissionError(
            f"Credential file {cred_path} role/username mismatch: got role={role_val!r}, username={user_val!r}, expected {expected_role!r}."
        )
    password = validate_credential_secret(str(parsed.get("password") or ""), f"{expected_role} password")
    host = str(parsed.get("host") or "127.0.0.1")
    port = int(parsed.get("port") or os.getenv("PATCHDIFF_POSTGRES_PORT") or DEFAULT_DOCKER_PORT)
    dbname = str(parsed.get("dbname") or DB_NAME)
    return {
        "role": expected_role,
        "username": expected_role,
        "password": password,
        "host": host,
        "port": port,
        "dbname": dbname,
        "credentials_file": str(cred_path),
    }


def validate_dsn_for_role(url: str, *, required_role: str | None, disallow_bootstrap: bool = False) -> str:
    """Validate that an explicit DSN uses a high-entropy password and matches the required DB role."""
    if not isinstance(url, str) or not url.strip():
        raise RuntimeError("Database URL is empty.")
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgresql"):
        raise ValueError("Database URL must use a postgresql:// or postgresql+psycopg:// scheme.")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if not username:
        raise PermissionError("Database URL is missing a role username.")
    validate_credential_secret(password, f"database password for role {username!r}")
    if disallow_bootstrap and username == DB_BOOTSTRAP_USER:
        raise PermissionError(
            f"Database role {DB_BOOTSTRAP_USER!r} is reserved for migrations/setup and is never accepted for MCP startup."
        )
    if required_role is not None and username != required_role:
        raise PermissionError(
            f"Database URL role {username!r} does not match required role {required_role!r}."
        )
    return url


def resolve_mcp_profile_and_validate_startup(
    profile: str | None = None,
    *,
    lock_process: bool = False,
) -> tuple[str, str]:
    """Resolve effective MCP profile and enforce OS UID + DB role invariants BEFORE importing app.storage.db."""
    global _PROCESS_MCP_PROFILE, _PROCESS_REQUIRED_DB_ROLE

    selected = (os.getenv("PATCHDIFF_MCP_PROFILE", "observed_v2") if profile is None else profile).strip()
    if not selected:
        selected = "observed_v2"
    if selected not in {
        "observed_v2", "full", "editor", "unobserved", "unobserved_editor",
        "hybrid_editor", "observed", "observed_editor",
    }:
        raise ValueError(f"Unknown PATCHDIFF_MCP_PROFILE: {selected!r}.")

    required_role = DB_HOST_USER if selected == "full" else DB_AGENT_USER

    role_env = os.getenv("PATCHDIFF_DB_ROLE")
    if role_env is not None and role_env.strip():
        norm_role = role_env.strip().lower()
        if norm_role in {"bootstrap", DB_BOOTSTRAP_USER}:
            raise PermissionError(
                f"PATCHDIFF_DB_ROLE={role_env!r} is forbidden: {DB_BOOTSTRAP_USER!r} is never accepted by any MCP startup path."
            )
        if selected != "full" and norm_role in {"host", DB_HOST_USER, "admin", "patchdiff_admin"}:
            raise PermissionError(
                f"Editing profile {selected!r} must never select {role_env!r}; required role is {DB_AGENT_USER!r}."
            )
        if selected == "full" and norm_role in {"agent", DB_AGENT_USER}:
            raise PermissionError(
                f"MCP profile 'full' requires {DB_HOST_USER!r}, not {role_env!r}."
            )

    enforce_os_principal_for_operation("mcp", profile=selected)

    explicit_url = os.getenv("PATCHDIFF_DATABASE_URL")
    if explicit_url:
        validate_dsn_for_role(explicit_url, required_role=required_role, disallow_bootstrap=True)
    if required_role == DB_AGENT_USER and os.getenv("PATCHDIFF_AGENT_DATABASE_URL"):
        validate_dsn_for_role(
            os.environ["PATCHDIFF_AGENT_DATABASE_URL"],
            required_role=DB_AGENT_USER,
            disallow_bootstrap=True,
        )
    if required_role == DB_HOST_USER and os.getenv("PATCHDIFF_HOST_DATABASE_URL"):
        validate_dsn_for_role(
            os.environ["PATCHDIFF_HOST_DATABASE_URL"],
            required_role=DB_HOST_USER,
            disallow_bootstrap=True,
        )

    resolve_database_url(profile=selected, role=required_role)

    if lock_process:
        _PROCESS_MCP_PROFILE = selected
        _PROCESS_REQUIRED_DB_ROLE = required_role

    return selected, required_role


def _build_sqlalchemy_url(cred: dict[str, Any]) -> str:
    user = quote(str(cred["username"]), safe="")
    pw = quote(str(cred["password"]), safe="")
    host = str(cred.get("host") or "127.0.0.1")
    port = int(cred.get("port") or os.getenv("PATCHDIFF_POSTGRES_PORT") or DEFAULT_DOCKER_PORT)
    dbname = str(cred.get("dbname") or DB_NAME)
    return f"postgresql+psycopg://{user}:{pw}@{host}:{port}/{dbname}"


def resolve_database_url(*, profile: str | None = None, role: str | None = None) -> str:
    """Resolve the database URL for the given MCP profile or role without any 'patchdiff:patchdiff' fallback."""
    effective_profile = profile or get_active_mcp_profile()
    disallow_bootstrap = effective_profile is not None

    if role is not None:
        required_role: str | None = role
    elif effective_profile is not None:
        required_role = DB_HOST_USER if effective_profile == "full" else DB_AGENT_USER
    else:
        required_role = _PROCESS_REQUIRED_DB_ROLE

    # Administrative callers explicitly select the bootstrap role, independently
    # of an MCP process's single-process DSN override.
    explicit = (
        os.getenv("PATCHDIFF_BOOTSTRAP_DATABASE_URL")
        if required_role == DB_BOOTSTRAP_USER
        else os.getenv("PATCHDIFF_DATABASE_URL")
    )
    if explicit:
        return validate_dsn_for_role(explicit, required_role=required_role, disallow_bootstrap=disallow_bootstrap)

    if required_role == DB_AGENT_USER:
        env_agent = os.getenv("PATCHDIFF_AGENT_DATABASE_URL")
        if env_agent:
            return validate_dsn_for_role(env_agent, required_role=DB_AGENT_USER, disallow_bootstrap=True)
        cred_path = get_agent_credentials_file_path()
        cred = load_role_credential_file(cred_path, expected_role=DB_AGENT_USER)
        return _build_sqlalchemy_url(cred)

    if required_role == DB_HOST_USER:
        enforce_os_principal_for_operation("mcp", profile="full")
        env_host = os.getenv("PATCHDIFF_HOST_DATABASE_URL")
        if env_host:
            return validate_dsn_for_role(env_host, required_role=DB_HOST_USER, disallow_bootstrap=True)
        cred_path = get_host_credentials_file_path()
        cred = load_role_credential_file(cred_path, expected_role=DB_HOST_USER)
        return _build_sqlalchemy_url(cred)

    if required_role == DB_BOOTSTRAP_USER:
        enforce_os_principal_for_operation("bootstrap")
        env_boot = os.getenv("PATCHDIFF_BOOTSTRAP_DATABASE_URL")
        if env_boot:
            return validate_dsn_for_role(env_boot, required_role=DB_BOOTSTRAP_USER, disallow_bootstrap=False)
        cred_path = get_bootstrap_credentials_file_path()
        cred = load_role_credential_file(cred_path, expected_role=DB_BOOTSTRAP_USER)
        return _build_sqlalchemy_url(cred)

    # Unscoped service/test caller outside MCP adapter: prefer host role over bootstrap
    for env_var, exp_role in (
        ("PATCHDIFF_HOST_DATABASE_URL", DB_HOST_USER),
        ("PATCHDIFF_BOOTSTRAP_DATABASE_URL", DB_BOOTSTRAP_USER),
    ):
        val = os.getenv(env_var)
        if val:
            return validate_dsn_for_role(val, required_role=exp_role, disallow_bootstrap=False)

    for getter, exp_role in (
        (get_host_credentials_file_path, DB_HOST_USER),
        (get_bootstrap_credentials_file_path, DB_BOOTSTRAP_USER),
    ):
        path = getter()
        if path.exists():
            cred = load_role_credential_file(path, expected_role=exp_role)
            return _build_sqlalchemy_url(cred)

    raise RuntimeError(
        "Database credentials are not configured. Run 'patchdiff-mcp-setup' or supply an explicit role-specific database URL; "
        "implicit default password fallback was removed in PR #23."
    )


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("PATCHDIFF_APP_NAME", "PatchDIFF MVP")
    environment: str = os.getenv("PATCHDIFF_ENV", "local")

    @property
    def database_url(self) -> str:
        return resolve_database_url()

    @property
    def host_database_url(self) -> str:
        return resolve_database_url(profile="full", role=DB_HOST_USER)

    @property
    def agent_database_url(self) -> str:
        return resolve_database_url(profile="observed_v2", role=DB_AGENT_USER)

    def database_url_for_profile(self, profile: str) -> str:
        role = DB_HOST_USER if profile == "full" else DB_AGENT_USER
        return resolve_database_url(profile=profile, role=role)

    @property
    def strict_observation_mode(self) -> bool:
        return is_strict_observation_mode_enabled()


settings = Settings()
