"""Dual-route PostgreSQL runtime setup and daemon lifecycle manager for PatchDIFF.

Supports two independent, non-conflicting PostgreSQL runtime routes:
- ``native``: User-space PostgreSQL cluster managed via ``initdb`` / ``pg_ctl``
  (default port ``5434``, data directory ``~/.local/share/patchdiff-runtime/pgdata``).
- ``docker``: Docker Compose PostgreSQL service (``postgres:16.3-alpine``,
  default port ``5433``).

Security & Isolation Invariants:
- Per-installation high-entropy credentials generated via ``secrets.token_urlsafe(32)``
  and stored in ``0600`` operator-owned ``db_credentials.json`` (PR23-R4I-ARCH-001).
- Separate PostgreSQL roles for privileged host lifecycle operations (``patchdiff_admin``)
  and restricted agent editing (``patchdiff_agent``) (PR23-PLAN-MCP-003).
- Mandatory ``scram-sha-256`` authentication for all local socket and TCP loopback
  connections; ``trust`` authentication and known default passwords (``patchdiff``)
  are strictly rejected.
- Foreign Docker containers from other checkouts/projects are never stopped or removed
  (PR23-R4I-SCRIPT-001).
- Packaged ``docker-compose.yml`` resource enables installed wheel setup outside any
  source checkout, with full preflight before mutating state (PR23-R4I-DEP-001).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.resources
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import psycopg
from psycopg import sql


DEFAULT_NATIVE_PORT = 5434
DEFAULT_DOCKER_PORT = 5433
DB_ADMIN_USER = "patchdiff_admin"
DB_AGENT_USER = "patchdiff_agent"
DB_NAME = "patchdiff"
FORBIDDEN_DEFAULT_PASSWORDS = frozenset({"patchdiff", "postgres", "password", "admin", "123456", ""})

AGENT_ALLOWED_TABLES = (
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
ADMIN_ONLY_TABLES = (
    "target_finalizations",
    "alembic_version",
)


def get_default_runtime_dir() -> Path:
    override = os.getenv("PATCHDIFF_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".local" / "share" / "patchdiff-runtime").resolve()


def get_default_native_pgdata(runtime_dir: Path | None = None) -> Path:
    override = os.getenv("PATCHDIFF_NATIVE_PGDATA")
    if override:
        return Path(override).expanduser().resolve()
    base = runtime_dir or get_default_runtime_dir()
    return base / "pgdata"


def get_default_native_pgrun(runtime_dir: Path | None = None) -> Path:
    override = os.getenv("PATCHDIFF_NATIVE_PGRUN")
    if override:
        return Path(override).expanduser().resolve()
    base = runtime_dir or get_default_runtime_dir()
    return base / "pgrun"


def get_credentials_file_path(runtime_dir: Path | None = None) -> Path:
    override = os.getenv("PATCHDIFF_DB_CREDENTIALS_FILE")
    if override:
        return Path(override).expanduser().resolve()
    base = runtime_dir or get_default_runtime_dir()
    return base / "db_credentials.json"


def validate_credential_secret(password: str, label: str = "password") -> str:
    if not isinstance(password, str) or password.strip().lower() in FORBIDDEN_DEFAULT_PASSWORDS or len(password) < 16:
        raise ValueError(
            f"Rejected insecure or known-default {label}; credentials must be high-entropy secrets (>=16 chars, never 'patchdiff')."
        )
    return password


def _atomic_write_json_0600(target_path: Path, payload: dict[str, Any], *, make_backup: bool = False) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if make_backup and target_path.is_file():
        backup_path = target_path.with_suffix(target_path.suffix + ".bak")
        data_orig = target_path.read_bytes()
        fd_b = os.open(
            str(backup_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            os.write(fd_b, data_orig)
            os.fsync(fd_b)
        finally:
            os.close(fd_b)
        os.chmod(backup_path, 0o600)

    serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    tmp_path = target_path.parent / f".{target_path.name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(
        str(tmp_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        written = 0
        view = memoryview(serialized)
        while written < len(serialized):
            written += os.write(fd, view[written:])
        os.fsync(fd)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp_path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)

    try:
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, target_path)
        os.chmod(target_path, 0o600)
        if hasattr(os, "fsync"):
            try:
                dir_fd = os.open(str(target_path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
    finally:
        tmp_path.unlink(missing_ok=True)
    return target_path


def ensure_runtime_credentials(runtime_dir: Path | None = None) -> dict[str, str]:
    """Load or generate per-installation high-entropy DB credentials for admin and agent roles."""
    env_admin_pw = os.getenv("PATCHDIFF_ADMIN_DB_PASSWORD")
    env_agent_pw = os.getenv("PATCHDIFF_AGENT_DB_PASSWORD")
    if env_admin_pw is not None:
        validate_credential_secret(env_admin_pw, "PATCHDIFF_ADMIN_DB_PASSWORD")
    if env_agent_pw is not None:
        validate_credential_secret(env_agent_pw, "PATCHDIFF_AGENT_DB_PASSWORD")

    cred_path = get_credentials_file_path(runtime_dir)
    base_dir = cred_path.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base_dir, 0o700)
    except OSError:
        pass

    if cred_path.is_file():
        st = cred_path.stat()
        if st.st_mode & 0o077:
            os.chmod(cred_path, 0o600)
        raw = json.loads(cred_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Credentials file {cred_path} must contain a JSON object.")
        admin_user = str(raw.get("admin_user") or DB_ADMIN_USER)
        agent_user = str(raw.get("agent_user") or DB_AGENT_USER)
        admin_password = validate_credential_secret(
            env_admin_pw or str(raw.get("admin_password", "")), "admin_password"
        )
        agent_password = validate_credential_secret(
            env_agent_pw or str(raw.get("agent_password", "")), "agent_password"
        )
        dbname = str(raw.get("dbname") or DB_NAME)
        creds = {
            "admin_user": admin_user,
            "admin_password": admin_password,
            "agent_user": agent_user,
            "agent_password": agent_password,
            "dbname": dbname,
            "credentials_file": str(cred_path),
        }
        if env_admin_pw or env_agent_pw:
            _atomic_write_json_0600(cred_path, creds)
        return creds

    admin_password = validate_credential_secret(
        env_admin_pw or secrets.token_urlsafe(32), "admin_password"
    )
    agent_password = validate_credential_secret(
        env_agent_pw or secrets.token_urlsafe(32), "agent_password"
    )
    creds = {
        "admin_user": DB_ADMIN_USER,
        "admin_password": admin_password,
        "agent_user": DB_AGENT_USER,
        "agent_password": agent_password,
        "dbname": DB_NAME,
        "credentials_file": str(cred_path),
    }
    _atomic_write_json_0600(cred_path, creds)
    return creds


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

    # Installed wheel outside source checkout: materialize packaged docker-compose.yml in runtime_dir
    base_runtime = runtime_dir or get_default_runtime_dir()
    docker_dir = base_runtime / "docker"
    docker_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(docker_dir, 0o700)
    except OSError:
        pass
    compose_path = docker_dir / "docker-compose.yml"
    compose_bytes = _read_packaged_compose_bytes()
    if not compose_path.is_file() or compose_path.read_bytes() != compose_bytes:
        tmp_compose = docker_dir / f".docker-compose.{secrets.token_hex(6)}.yml"
        fd = os.open(
            str(tmp_compose),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            os.write(fd, compose_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_compose, compose_path)
    return docker_dir, compose_path


def get_compose_project_name(work_dir: Path) -> str:
    override = os.getenv("PATCHDIFF_COMPOSE_PROJECT")
    if override:
        return override.strip()
    digest = hashlib.sha256(str(work_dir.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"patchdiff-{digest}"


def get_alembic_ini_path() -> Path:
    packaged = Path(__file__).resolve().parents[1] / "migrations" / "alembic.ini"
    if packaged.is_file():
        return packaged
    repo_ini = get_default_repo_root() / "backend" / "app" / "migrations" / "alembic.ini"
    if repo_ini.is_file():
        return repo_ini
    raise FileNotFoundError(f"Could not locate alembic.ini at {packaged} or {repo_ini}")


def build_database_url(
    port: int,
    host: str = "127.0.0.1",
    dbname: str = DB_NAME,
    *,
    role: str = "admin",
    runtime_dir: Path | None = None,
    creds: dict[str, str] | None = None,
) -> str:
    resolved_creds = creds or ensure_runtime_credentials(runtime_dir)
    if role == "agent":
        user = resolved_creds["agent_user"]
        password = resolved_creds["agent_password"]
    else:
        user = resolved_creds["admin_user"]
        password = resolved_creds["admin_password"]
    return f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{dbname}"


def build_psycopg_dsn(
    port: int,
    host: str = "127.0.0.1",
    dbname: str = DB_NAME,
    *,
    role: str = "admin",
    runtime_dir: Path | None = None,
    creds: dict[str, str] | None = None,
) -> str:
    resolved_creds = creds or ensure_runtime_credentials(runtime_dir)
    if role == "agent":
        user = resolved_creds["agent_user"]
        password = resolved_creds["agent_password"]
    else:
        user = resolved_creds["admin_user"]
        password = resolved_creds["admin_password"]
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{dbname}"


def redact_database_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        pass
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
    role: str = "admin",
    runtime_dir: Path | None = None,
    creds: dict[str, str] | None = None,
) -> tuple[bool, str | None]:
    dsn = build_psycopg_dsn(port=port, host=host, dbname=dbname, role=role, runtime_dir=runtime_dir, creds=creds)
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
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


def find_pg_bin_dir() -> Path:
    override = os.getenv("PATCHDIFF_PG_BIN_DIR")
    if override:
        path = Path(override).expanduser().resolve()
        if (path / "pg_ctl").is_file():
            return path
        raise RuntimeError(f"PATCHDIFF_PG_BIN_DIR={override!r} does not contain pg_ctl")

    which_pg_ctl = shutil.which("pg_ctl")
    if which_pg_ctl:
        return Path(which_pg_ctl).resolve().parent

    candidates = sorted(
        glob.glob("/usr/lib/postgresql/*/bin"),
        key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", p)],
        reverse=True,
    )
    for cand in candidates:
        cand_path = Path(cand)
        if (cand_path / "pg_ctl").is_file() and (cand_path / "initdb").is_file():
            return cand_path

    raise RuntimeError(
        "PostgreSQL binaries (pg_ctl, initdb) not found in PATH or /usr/lib/postgresql/*/bin."
    )


def _configure_postgresql_conf(pgdata: Path, pgrun: Path, port: int) -> None:
    conf_path = pgdata / "postgresql.conf"
    if not conf_path.is_file():
        return
    content = conf_path.read_text(encoding="utf-8")
    marker_begin = "# --- PATCHDIFF NATIVE CONFIG BEGIN ---"
    marker_end = "# --- PATCHDIFF NATIVE CONFIG END ---"
    block = (
        f"{marker_begin}\n"
        f"listen_addresses = '127.0.0.1'\n"
        f"port = {port}\n"
        f"unix_socket_directories = '{pgrun.as_posix()}'\n"
        f"unix_socket_permissions = 0700\n"
        f"password_encryption = 'scram-sha-256'\n"
        f"{marker_end}\n"
    )
    if marker_begin in content and marker_end in content:
        pattern = re.compile(
            re.escape(marker_begin) + r".*?" + re.escape(marker_end) + r"\n?",
            re.DOTALL,
        )
        updated = pattern.sub(block, content)
    else:
        updated = content.rstrip("\n") + "\n\n" + block
    conf_path.write_text(updated, encoding="utf-8")


def _configure_pg_hba(pgdata: Path) -> None:
    """Enforce scram-sha-256 on all local and host connections; eliminate any trust rules."""
    hba_path = pgdata / "pg_hba.conf"
    if not hba_path.is_file():
        return
    content = hba_path.read_text(encoding="utf-8")
    marker_begin = "# --- PATCHDIFF NATIVE HBA BEGIN ---"
    marker_end = "# --- PATCHDIFF NATIVE HBA END ---"
    legacy_marker = "# --- PATCHDIFF NATIVE HBA ---"

    # Remove legacy block or any active 'trust' authentication lines
    cleaned_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == legacy_marker:
            continue
        if stripped and not stripped.startswith("#") and re.search(r"\btrust\b", stripped):
            cleaned_lines.append(re.sub(r"\btrust\b", "scram-sha-256", line))
        else:
            cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines) + "\n"

    block = (
        f"{marker_begin}\n"
        "local   all             all                                     scram-sha-256\n"
        "host    all             all             127.0.0.1/32            scram-sha-256\n"
        "host    all             all             ::1/128                 scram-sha-256\n"
        f"{marker_end}\n"
    )
    if marker_begin in cleaned and marker_end in cleaned:
        pattern = re.compile(
            re.escape(marker_begin) + r".*?" + re.escape(marker_end) + r"\n?",
            re.DOTALL,
        )
        updated = pattern.sub(block, cleaned)
    else:
        updated = block + "\n" + cleaned.lstrip("\n")
    hba_path.write_text(updated, encoding="utf-8")


def ensure_native_cluster(
    pgdata: Path,
    pgrun: Path,
    port: int,
    *,
    runtime_dir: Path | None = None,
    creds: dict[str, str] | None = None,
) -> Path:
    pg_bin = find_pg_bin_dir()
    initdb_bin = pg_bin / "initdb"
    resolved_creds = creds or ensure_runtime_credentials(runtime_dir or pgdata.parent)
    pgrun.mkdir(parents=True, exist_ok=True)
    os.chmod(pgrun, 0o700)

    is_new_cluster = not (pgdata / "PG_VERSION").is_file()
    if is_new_cluster:
        pgdata.mkdir(parents=True, exist_ok=True)
        os.chmod(pgdata, 0o700)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as pwf:
            pwf.write(resolved_creds["admin_password"] + "\n")
            pwfile_path = Path(pwf.name)
        try:
            os.chmod(pwfile_path, 0o600)
            cmd = [
                str(initdb_bin),
                "-D",
                str(pgdata),
                "-U",
                resolved_creds["admin_user"],
                f"--pwfile={pwfile_path}",
                "--encoding=UTF8",
                "--locale=C.UTF-8",
                "--auth-local=scram-sha-256",
                "--auth-host=scram-sha-256",
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60.0)
        finally:
            pwfile_path.unlink(missing_ok=True)

    _configure_postgresql_conf(pgdata, pgrun, port)
    if is_new_cluster:
        _configure_pg_hba(pgdata)
    return pg_bin


def _native_pg_ctl_status(pg_bin: Path, pgdata: Path) -> tuple[bool, str]:
    if not (pgdata / "PG_VERSION").is_file():
        return False, "uninitialized"
    pg_ctl = pg_bin / "pg_ctl"
    proc = subprocess.run(
        [str(pg_ctl), "-D", str(pgdata), "status"],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    output = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, output


def _sql_ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def _provision_roles_and_database(port: int, creds: dict[str, str], host: str = "127.0.0.1") -> None:
    """Ensure admin and agent roles exist with high-entropy passwords, database exists, and known 'patchdiff' default fails."""
    admin_user = creds["admin_user"]
    admin_pw = creds["admin_password"]
    agent_user = creds["agent_user"]
    agent_pw = creds["agent_password"]
    dbname = creds["dbname"]

    # Connect using admin credentials (or migrate legacy 'patchdiff' cluster if upgrading in-place)
    conn = None
    for candidate_user, candidate_pw, candidate_db in (
        (admin_user, admin_pw, "postgres"),
        (admin_user, admin_pw, dbname),
        ("patchdiff", "patchdiff", "postgres"),
        ("patchdiff", "patchdiff", dbname),
    ):
        dsn = f"postgresql://{quote(candidate_user, safe='')}:{quote(candidate_pw, safe='')}@{host}:{port}/{candidate_db}"
        try:
            conn = psycopg.connect(dsn, autocommit=True, connect_timeout=3)
            break
        except Exception:
            continue

    if conn is None:
        raise RuntimeError(f"Could not authenticate to PostgreSQL on {host}:{port} to verify roles/database.")

    try:
        # 1. Ensure admin role exists as superuser with scram-sha-256 password
        row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (admin_user,)).fetchone()
        if not row:
            conn.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN SUPERUSER PASSWORD {}").format(
                    sql.Identifier(admin_user), sql.Literal(admin_pw)
                )
            )
        else:
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN SUPERUSER PASSWORD {}").format(
                    sql.Identifier(admin_user), sql.Literal(admin_pw)
                )
            )

        # 2. Ensure least-privilege agent role exists (non-superuser, no createdb, no createrole)
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

        # 3. If legacy 'patchdiff' role exists, rotate its password and disable login so 'patchdiff:patchdiff' always fails
        if "patchdiff" not in {admin_user, agent_user}:
            row_leg = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'patchdiff'").fetchone()
            if row_leg:
                rotated = secrets.token_urlsafe(32)
                conn.execute(
                    sql.SQL("ALTER ROLE {} WITH NOLOGIN PASSWORD {}").format(
                        sql.Identifier("patchdiff"), sql.Literal(rotated)
                    )
                )

        # 4. Ensure target database exists and is owned by admin_user
        row_db = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not row_db:
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(dbname), sql.Identifier(admin_user)
                )
            )
        else:
            conn.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(dbname), sql.Identifier(admin_user)
                )
            )
    finally:
        conn.close()


def enforce_role_table_privileges(
    port: int,
    *,
    runtime_dir: Path | None = None,
    creds: dict[str, str] | None = None,
    host: str = "127.0.0.1",
) -> None:
    """Grant agent role access only to editing tables and revoke access to admin/lifecycle tables."""
    resolved_creds = creds or ensure_runtime_credentials(runtime_dir)
    admin_dsn = build_psycopg_dsn(port=port, host=host, dbname=resolved_creds["dbname"], role="admin", creds=resolved_creds)
    admin_ident = _sql_ident(resolved_creds["admin_user"])
    agent_ident = _sql_ident(resolved_creds["agent_user"])
    db_ident = _sql_ident(resolved_creds["dbname"])

    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
        conn.execute(f"GRANT CONNECT ON DATABASE {db_ident} TO {agent_ident}")
        conn.execute(f"GRANT USAGE ON SCHEMA public TO {agent_ident}")
        conn.execute(f"REVOKE CREATE ON SCHEMA public FROM {agent_ident}")
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {agent_ident}")
        conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {admin_ident} IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE ON TABLES TO {agent_ident}"
        )
        conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {admin_ident} IN SCHEMA public "
            f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {agent_ident}"
        )

        for tbl in AGENT_ALLOWED_TABLES:
            exists = conn.execute("SELECT to_regclass(%s)", (f"public.{tbl}",)).fetchone()
            if exists and exists[0]:
                conn.execute(f"GRANT SELECT, INSERT, UPDATE ON TABLE {_sql_ident(tbl)} TO {agent_ident}")

        for tbl in ADMIN_ONLY_TABLES:
            exists = conn.execute("SELECT to_regclass(%s)", (f"public.{tbl}",)).fetchone()
            if exists and exists[0]:
                conn.execute(f"REVOKE ALL ON TABLE {_sql_ident(tbl)} FROM {agent_ident}")
                conn.execute(f"REVOKE ALL ON TABLE {_sql_ident(tbl)} FROM PUBLIC")


def native_daemon(
    action: str,
    *,
    port: int = DEFAULT_NATIVE_PORT,
    pgdata: Path | None = None,
    pgrun: Path | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    base_runtime = runtime_dir or (pgdata.parent if pgdata is not None else get_default_runtime_dir())
    pgdata_dir = pgdata or get_default_native_pgdata(base_runtime)
    pgrun_dir = pgrun or get_default_native_pgrun(base_runtime)
    creds = ensure_runtime_credentials(base_runtime)
    pg_bin = find_pg_bin_dir()
    pg_ctl = pg_bin / "pg_ctl"
    logfile = pgdata_dir / "postgresql.log"
    admin_url = build_database_url(port=port, role="admin", creds=creds)

    if action == "status":
        running, detail = _native_pg_ctl_status(pg_bin, pgdata_dir)
        db_ready, rev = check_db_connection(port=port, creds=creds) if running else (False, None)
        return {
            "route": "native",
            "action": "status",
            "status": "running" if (running and db_ready) else ("starting" if running else "stopped"),
            "host": "127.0.0.1",
            "port": port,
            "database_url": admin_url,
            "redacted_database_url": redact_database_url(admin_url),
            "db_ready": db_ready,
            "alembic_revision": rev,
            "pgdata": str(pgdata_dir),
            "credentials_file": creds["credentials_file"],
            "backend_detail": detail,
        }

    if action == "stop":
        running, _ = _native_pg_ctl_status(pg_bin, pgdata_dir)
        if running:
            subprocess.run(
                [str(pg_ctl), "-D", str(pgdata_dir), "-m", "fast", "-w", "stop"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30.0,
            )
        _, after_detail = _native_pg_ctl_status(pg_bin, pgdata_dir)
        return {
            "route": "native",
            "action": "stop",
            "status": "stopped",
            "host": "127.0.0.1",
            "port": port,
            "database_url": admin_url,
            "redacted_database_url": redact_database_url(admin_url),
            "db_ready": False,
            "alembic_revision": None,
            "pgdata": str(pgdata_dir),
            "credentials_file": creds["credentials_file"],
            "backend_detail": after_detail,
        }

    if action == "restart":
        native_daemon("stop", port=port, pgdata=pgdata_dir, pgrun=pgrun_dir, runtime_dir=base_runtime)
        res = native_daemon("start", port=port, pgdata=pgdata_dir, pgrun=pgrun_dir, runtime_dir=base_runtime)
        res["action"] = "restart"
        return res

    if action == "start":
        ensure_native_cluster(pgdata_dir, pgrun_dir, port, runtime_dir=base_runtime, creds=creds)
        running, _ = _native_pg_ctl_status(pg_bin, pgdata_dir)
        if not running:
            subprocess.run(
                [str(pg_ctl), "-D", str(pgdata_dir), "-l", str(logfile), "-w", "start"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30.0,
            )
        else:
            subprocess.run(
                [str(pg_ctl), "-D", str(pgdata_dir), "reload"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10.0,
            )

        deadline = time.monotonic() + 15.0
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if is_tcp_port_open(port):
                try:
                    _provision_roles_and_database(port, creds)
                    break
                except Exception as exc:
                    last_err = exc
            time.sleep(0.25)

        # Always enforce scram-sha-256 HBA rules and reload after roles are provisioned
        _configure_pg_hba(pgdata_dir)
        subprocess.run(
            [str(pg_ctl), "-D", str(pgdata_dir), "reload"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )

        running, detail = _native_pg_ctl_status(pg_bin, pgdata_dir)
        db_ready, rev = check_db_connection(port=port, creds=creds)
        if not (running and db_ready):
            raise RuntimeError(
                f"Native PostgreSQL daemon failed to become ready on 127.0.0.1:{port} ({detail}; last_error={last_err})"
            )
        return {
            "route": "native",
            "action": "start",
            "status": "running",
            "host": "127.0.0.1",
            "port": port,
            "database_url": admin_url,
            "redacted_database_url": redact_database_url(admin_url),
            "db_ready": db_ready,
            "alembic_revision": rev,
            "pgdata": str(pgdata_dir),
            "credentials_file": creds["credentials_file"],
            "backend_detail": detail,
        }

    raise ValueError(f"Unsupported daemon action: {action!r}")


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
    """Verify container belongs to this checkout/project; raise RuntimeError on foreign ownership (PR23-R4I-SCRIPT-001)."""
    cname = str(info.get("Name") or "").lstrip("/")
    labels = info.get("Config", {}).get("Labels") or {}
    c_project = labels.get("com.docker.compose.project", "")
    c_workdir = labels.get("com.docker.compose.project.working_dir", "")

    resolved_work = work_dir.resolve()
    if c_workdir:
        try:
            owner_work = Path(c_workdir).resolve()
        except Exception:
            owner_work = Path(c_workdir)
        if owner_work != resolved_work:
            raise RuntimeError(
                f"Foreign Docker container conflict: container {cname!r} belongs to checkout {c_workdir!r} "
                f"(expected {str(resolved_work)!r}). Refusing to stop or remove foreign container."
            )
    elif c_project != project_name:
        raise RuntimeError(
            f"Foreign Docker container conflict: container {cname!r} is not managed by project {project_name!r}. "
            "Refusing to stop or remove foreign container."
        )
    if c_project and c_project not in {project_name, resolved_work.name.lower(), "patch-diff", "patchdiff"}:
        raise RuntimeError(
            f"Foreign Docker container conflict: container {cname!r} belongs to Compose project {c_project!r} "
            f"(expected {project_name!r}). Refusing to stop or remove foreign container."
        )


def _find_project_postgres_container(work_dir: Path, port: int, project_name: str) -> dict[str, Any] | None:
    """Locate this project's postgres container or detect foreign conflicts without ever deleting foreign containers."""
    candidates: list[str] = [f"{project_name}-postgres-1", f"{project_name}_postgres_1", "patchdiff-postgres"]
    for cname in _list_docker_containers_by_filter(f"publish={port}"):
        if cname not in candidates:
            candidates.append(cname)

    owned_info: dict[str, Any] | None = None
    for cand in candidates:
        info = _inspect_docker_container(cand)
        if info is None:
            continue
        bindings = info.get("HostConfig", {}).get("PortBindings", {}).get("5432/tcp") or []
        bound_ports = {str(b.get("HostPort", "")) for b in bindings if isinstance(b, dict)}
        labels = info.get("Config", {}).get("Labels") or {}
        c_workdir = labels.get("com.docker.compose.project.working_dir", "")
        c_project = labels.get("com.docker.compose.project", "")

        # If this container binds our requested port OR has our project name, verify ownership
        if str(port) in bound_ports or c_project == project_name or (c_workdir and Path(c_workdir).resolve() == work_dir.resolve()):
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
    base_runtime = runtime_dir or get_default_runtime_dir()
    work_dir, compose_file = resolve_compose_workspace(repo_root=repo_root, runtime_dir=base_runtime)
    project_name = get_compose_project_name(work_dir)
    creds = ensure_runtime_credentials(base_runtime)
    admin_url = build_database_url(port=port, role="admin", creds=creds)

    compose_env = {
        **os.environ,
        "PATCHDIFF_POSTGRES_PORT": str(port),
        "POSTGRES_DB": creds["dbname"],
        "POSTGRES_USER": creds["admin_user"],
        "POSTGRES_PASSWORD": creds["admin_password"],
    }

    if action == "status":
        info = _find_project_postgres_container(work_dir, port, project_name)
        state = info.get("State", {}) if info else {}
        running = bool(state.get("Running", False))
        status_label = state.get("Status", "not_created") if info else "not_created"
        cname = str(info.get("Name", "")).lstrip("/") if info else f"{project_name}-postgres-1"
        db_ready, rev = check_db_connection(port=port, creds=creds) if running else (False, None)
        return {
            "route": "docker",
            "action": "status",
            "status": "running" if (running and db_ready) else ("starting" if running else "stopped"),
            "host": "127.0.0.1",
            "port": port,
            "database_url": admin_url,
            "redacted_database_url": redact_database_url(admin_url),
            "db_ready": db_ready,
            "alembic_revision": rev,
            "container": cname,
            "project": project_name,
            "credentials_file": creds["credentials_file"],
            "backend_detail": f"container={status_label}",
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
            "route": "docker",
            "action": "stop",
            "status": "stopped",
            "host": "127.0.0.1",
            "port": port,
            "database_url": admin_url,
            "redacted_database_url": redact_database_url(admin_url),
            "db_ready": False,
            "alembic_revision": None,
            "container": cname,
            "project": project_name,
            "credentials_file": creds["credentials_file"],
            "backend_detail": "container=exited",
        }

    if action == "restart":
        docker_daemon("stop", port=port, repo_root=repo_root, runtime_dir=base_runtime)
        res = docker_daemon("start", port=port, repo_root=repo_root, runtime_dir=base_runtime)
        res["action"] = "restart"
        return res

    if action == "start":
        # Verify no foreign container conflict before mutating anything (PR23-R4I-SCRIPT-001)
        existing_info = _find_project_postgres_container(work_dir, port, project_name)
        if existing_info is not None:
            _verify_container_ownership(existing_info, work_dir, project_name)
            labels = existing_info.get("Config", {}).get("Labels") or {}
            c_project = labels.get("com.docker.compose.project", "")
            c_workdir = labels.get("com.docker.compose.project.working_dir", "")
            cname = str(existing_info.get("Name") or "").lstrip("/")
            if cname and c_workdir and Path(c_workdir).resolve() == work_dir.resolve() and c_project != project_name:
                subprocess.run(
                    ["docker", "rm", "-f", cname],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15.0,
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
                    db_ready, rev = check_db_connection(port=port, creds=creds)
                    if db_ready:
                        break
                except Exception as exc:
                    last_err = exc
            time.sleep(0.5)
        if not db_ready:
            raise RuntimeError(
                f"Docker service {project_name}/postgres failed to become ready on 127.0.0.1:{port} (last_error={last_err})"
            )
        info = _find_project_postgres_container(work_dir, port, project_name)
        cname = str(info.get("Name", "")).lstrip("/") if info else f"{project_name}-postgres-1"
        return {
            "route": "docker",
            "action": "start",
            "status": "running",
            "host": "127.0.0.1",
            "port": port,
            "database_url": admin_url,
            "redacted_database_url": redact_database_url(admin_url),
            "db_ready": db_ready,
            "alembic_revision": rev,
            "container": cname,
            "project": project_name,
            "credentials_file": creds["credentials_file"],
            "backend_detail": "container=running",
        }

    raise ValueError(f"Unsupported daemon action: {action!r}")


def preflight_routes(
    routes: list[str],
    *,
    native_port: int,
    docker_port: int,
    repo_root: Path | None = None,
    runtime_dir: Path | None = None,
) -> None:
    """Validate prerequisites for all requested routes before mutating state on any route (PR23-R4I-DEP-001)."""
    base_runtime = runtime_dir or get_default_runtime_dir()
    if "native" in routes:
        find_pg_bin_dir()

    if "docker" in routes:
        work_dir, compose_file = resolve_compose_workspace(repo_root=repo_root, runtime_dir=base_runtime)
        if not compose_file.is_file():
            raise FileNotFoundError(f"docker-compose.yml not found at {compose_file}")
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
        project_name = get_compose_project_name(work_dir)
        _find_project_postgres_container(work_dir, docker_port, project_name)


def run_alembic_upgrade(
    database_url: str,
    *,
    runtime_dir: Path | None = None,
    creds: dict[str, str] | None = None,
) -> str:
    alembic_ini = get_alembic_ini_path()
    env = {
        **os.environ,
        "PATCHDIFF_DATABASE_URL": database_url,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    m = re.search(r":(\d+)/", database_url)
    port = int(m.group(1)) if m else DEFAULT_NATIVE_PORT
    resolved_creds = creds or ensure_runtime_credentials(runtime_dir)
    enforce_role_table_privileges(port, runtime_dir=runtime_dir, creds=resolved_creds)
    _, rev = check_db_connection(port=port, runtime_dir=runtime_dir, creds=resolved_creds)
    if not rev:
        raise RuntimeError(f"Alembic migration completed for {redact_database_url(database_url)}, but alembic_version is empty")
    return rev


def smoke_test_mcp_adapter(database_url: str) -> dict[str, int]:
    from app.services.waymark_adapter import get_waymark_bridge_dir, resolve_node_executable

    bridge_dir = str(get_waymark_bridge_dir())
    node_path = resolve_node_executable()
    counts: dict[str, int] = {}

    for profile, expected_count in (("observed_v2", 5), ("full", 24)):
        env = {
            **os.environ,
            "PATCHDIFF_DATABASE_URL": database_url,
            "PATCHDIFF_MCP_PROFILE": profile,
            "PATCHDIFF_WAYMARK_BRIDGE_DIR": bridge_dir,
            "PATCHDIFF_NODE_BINARY": node_path,
            "PATCHDIFF_WAYMARK_MODE": "resident",
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.mcp.external_adapter"],
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
                err = proc.stderr.read() if proc.stderr else ""
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
    active_route: str,
    native_port: int,
    docker_port: int,
    profile: str = "observed_v2",
    runtime_dir: Path | None = None,
) -> Path:
    """Atomically update host mcp_config.json, failing closed on malformed existing JSON (PR23-R4I-SCRIPT-002)."""
    from app.services.waymark_adapter import get_waymark_bridge_dir, resolve_node_executable

    if active_route not in {"native", "docker"}:
        raise ValueError(f"Invalid active_route {active_route!r}; expected 'native' or 'docker'.")

    creds = ensure_runtime_credentials(runtime_dir)
    active_port = native_port if active_route == "native" else docker_port
    role = "full" if profile == "full" else "agent"
    active_db_url = build_database_url(
        port=active_port,
        role="admin" if role == "full" else "agent",
        runtime_dir=runtime_dir,
        creds=creds,
    )
    bridge_dir = str(get_waymark_bridge_dir())
    node_path = resolve_node_executable()
    backend_dir = str(Path(__file__).resolve().parents[2])

    existing: dict[str, Any] = {}
    if config_path.exists():
        if config_path.is_dir():
            raise ValueError(f"MCP config path {config_path} is a directory, not a file.")
        raw_text = config_path.read_text(encoding="utf-8")
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Existing MCP configuration at {config_path} contains malformed JSON; refusing to overwrite: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Existing MCP configuration at {config_path} must have a JSON object root (got {type(parsed).__name__})."
            )
        if "mcpServers" in parsed and not isinstance(parsed["mcpServers"], dict):
            raise ValueError(
                f"Existing MCP configuration at {config_path} has non-object 'mcpServers' field."
            )
        existing = dict(parsed)

    mcp_servers = dict(existing.get("mcpServers") or {})
    server_entry: dict[str, Any] = {
        "command": sys.executable,
        "args": ["-m", "app.mcp.external_adapter"],
        "env": {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": backend_dir,
            "PATCHDIFF_DATABASE_URL": active_db_url,
            "PATCHDIFF_DB_CREDENTIALS_FILE": creds["credentials_file"],
            "PATCHDIFF_MCP_PROFILE": profile,
            "PATCHDIFF_WAYMARK_MODE": "resident",
            "PATCHDIFF_WAYMARK_BRIDGE_DIR": bridge_dir,
            "PATCHDIFF_NODE_BINARY": node_path,
            "PATCHDIFF_ACTIVE_ROUTE": active_route,
        },
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

    return _atomic_write_json_0600(config_path, existing, make_backup=True)


def resolve_routes(route_arg: str) -> list[str]:
    if route_arg == "both":
        return ["native", "docker"]
    if route_arg in {"native", "docker"}:
        return [route_arg]
    raise ValueError(f"Invalid route {route_arg!r}; expected 'native', 'docker', or 'both'")


def run_daemon_command(
    action: str,
    *,
    route: str = "both",
    native_port: int = DEFAULT_NATIVE_PORT,
    docker_port: int = DEFAULT_DOCKER_PORT,
    repo_root: Path | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    if native_port == docker_port:
        raise ValueError(
            f"native_port ({native_port}) and docker_port ({docker_port}) must be distinct so both routes operate independently."
        )
    results: dict[str, Any] = {}
    for target in resolve_routes(route):
        if target == "native":
            results["native"] = native_daemon(action, port=native_port, runtime_dir=runtime_dir)
        elif target == "docker":
            results["docker"] = docker_daemon(action, port=docker_port, repo_root=repo_root, runtime_dir=runtime_dir)
    return {"command": f"daemon.{action}", "route": route, "routes": results}


def resolve_effective_mcp_route(route: str, mcp_route: str | None) -> str:
    """Resolve effective MCP config route, honoring explicit --mcp-route without silent override (PR23-R4I-MCP-001)."""
    if mcp_route is not None:
        if mcp_route not in {"native", "docker"}:
            raise ValueError(f"Invalid mcp_route {mcp_route!r}; expected 'native' or 'docker'.")
        return mcp_route
    if route == "docker":
        return "docker"
    return "native"


def run_setup_command(
    *,
    route: str = "both",
    native_port: int = DEFAULT_NATIVE_PORT,
    docker_port: int = DEFAULT_DOCKER_PORT,
    mcp_route: str | None = None,
    mcp_config: Path | None = None,
    update_mcp: bool = False,
    repo_root: Path | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    if native_port == docker_port:
        raise ValueError(
            f"native_port ({native_port}) and docker_port ({docker_port}) must be distinct so both routes operate independently."
        )

    routes = resolve_routes(route)
    chosen_mcp_route = resolve_effective_mcp_route(route, mcp_route)

    # 1. Preflight all requested routes BEFORE starting or mutating any route (PR23-R4I-DEP-001)
    preflight_routes(
        routes,
        native_port=native_port,
        docker_port=docker_port,
        repo_root=repo_root,
        runtime_dir=runtime_dir,
    )

    # If user explicitly requested --mcp-route for a route not in `routes`, verify that route is reachable now
    if (update_mcp or mcp_config is not None) and mcp_route is not None and chosen_mcp_route not in routes:
        check_port = native_port if chosen_mcp_route == "native" else docker_port
        ok, _ = check_db_connection(port=check_port, runtime_dir=runtime_dir)
        if not ok:
            raise RuntimeError(
                f"Explicit --mcp-route {chosen_mcp_route!r} was not provisioned by --route {route!r} "
                f"and is not reachable on 127.0.0.1:{check_port}."
            )

    from app.services.waymark_adapter import get_waymark_bridge_dir
    from app.waymark_bridge.bootstrap import bootstrap_bridge, verify_installed_bridge

    bridge_dir = get_waymark_bridge_dir()
    try:
        waymark_version = verify_installed_bridge(bridge_dir)
    except Exception:
        bootstrapped = bootstrap_bridge(bridge_dir)
        waymark_version = verify_installed_bridge(bootstrapped)

    routes_summary: dict[str, Any] = {}
    for target in routes:
        if target == "native":
            d_info = native_daemon("start", port=native_port, runtime_dir=runtime_dir)
        else:
            d_info = docker_daemon("start", port=docker_port, repo_root=repo_root, runtime_dir=runtime_dir)
        db_url = d_info["database_url"]
        rev = run_alembic_upgrade(db_url, runtime_dir=runtime_dir)
        d_info["alembic_revision"] = rev
        d_info["mcp_smoke_tools"] = smoke_test_mcp_adapter(db_url)
        routes_summary[target] = d_info

    updated_config_path: str | None = None
    if update_mcp or mcp_config is not None:
        target_cfg = mcp_config or (Path.home() / ".gemini" / "config" / "mcp_config.json")
        written = update_host_mcp_config(
            target_cfg,
            active_route=chosen_mcp_route,
            native_port=native_port,
            docker_port=docker_port,
            runtime_dir=runtime_dir,
        )
        updated_config_path = str(written)

    return {
        "command": "setup",
        "route": route,
        "mcp_route": chosen_mcp_route,
        "waymark_bridge": {"path": str(bridge_dir), "version": waymark_version},
        "routes": routes_summary,
        "mcp_config_updated": updated_config_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patchdiff-mcp",
        description="PatchDIFF dual-route PostgreSQL setup and daemon lifecycle CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    setup_p = subparsers.add_parser(
        "setup",
        help="Provision, migrate, and smoke-test native (port 5434) and/or docker (port 5433) routes",
    )
    setup_p.add_argument(
        "--route",
        choices=("native", "docker", "both"),
        default="both",
        help="Target route(s) to set up (default: both)",
    )
    setup_p.add_argument(
        "--native-port",
        type=int,
        default=int(os.getenv("PATCHDIFF_NATIVE_POSTGRES_PORT", str(DEFAULT_NATIVE_PORT))),
        help=f"Port for native user-space PostgreSQL cluster (default: {DEFAULT_NATIVE_PORT})",
    )
    setup_p.add_argument(
        "--docker-port",
        type=int,
        default=int(os.getenv("PATCHDIFF_POSTGRES_PORT", str(DEFAULT_DOCKER_PORT))),
        help=f"Port for Docker Compose PostgreSQL service (default: {DEFAULT_DOCKER_PORT})",
    )
    setup_p.add_argument(
        "--mcp-route",
        choices=("native", "docker"),
        default=None,
        help="Which route to bind in the MCP host config when --update-mcp-config is used (default: inferred from --route, preferring native)",
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
        help="Update host MCP configuration to point to the live PatchDIFF MCP adapter",
    )

    daemon_p = subparsers.add_parser(
        "daemon",
        help="Start, stop, restart, or inspect native and docker PostgreSQL daemons identically",
    )
    daemon_p.add_argument(
        "action",
        choices=("start", "stop", "restart", "status"),
        help="Lifecycle action to execute",
    )
    daemon_p.add_argument(
        "--route",
        choices=("native", "docker", "both"),
        default="both",
        help="Target route(s) for lifecycle action (default: both)",
    )
    daemon_p.add_argument(
        "--native-port",
        type=int,
        default=int(os.getenv("PATCHDIFF_NATIVE_POSTGRES_PORT", str(DEFAULT_NATIVE_PORT))),
        help=f"Port for native user-space PostgreSQL cluster (default: {DEFAULT_NATIVE_PORT})",
    )
    daemon_p.add_argument(
        "--docker-port",
        type=int,
        default=int(os.getenv("PATCHDIFF_POSTGRES_PORT", str(DEFAULT_DOCKER_PORT))),
        help=f"Port for Docker Compose PostgreSQL service (default: {DEFAULT_DOCKER_PORT})",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "setup":
            result = run_setup_command(
                route=args.route,
                native_port=args.native_port,
                docker_port=args.docker_port,
                mcp_route=args.mcp_route,
                mcp_config=args.mcp_config,
                update_mcp=args.update_mcp_config,
            )
        elif args.subcommand == "daemon":
            result = run_daemon_command(
                args.action,
                route=args.route,
                native_port=args.native_port,
                docker_port=args.docker_port,
            )
        else:
            parser.error(f"Unknown subcommand: {args.subcommand}")
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


def setup_entrypoint() -> None:
    raise SystemExit(main(["setup", *sys.argv[1:]]))


def daemon_entrypoint() -> None:
    raise SystemExit(main(["daemon", *sys.argv[1:]]))


if __name__ == "__main__":
    raise SystemExit(main())
