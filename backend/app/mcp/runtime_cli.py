"""Dual-route PostgreSQL runtime setup and daemon lifecycle manager for PatchDIFF.

Supports two independent, non-conflicting PostgreSQL runtime routes:
- ``native``: User-space PostgreSQL cluster managed via ``initdb`` / ``pg_ctl``
  (default port ``5434``, data directory ``~/.local/share/patchdiff-runtime/pgdata``).
- ``docker``: Docker Compose ``patchdiff-postgres`` container (``postgres:16.3-alpine``,
  default port ``5433``).

Both routes use distinct ports so they can run simultaneously and independently,
and both expose identical lifecycle commands:
- ``setup``
- ``daemon start``
- ``daemon stop``
- ``daemon restart``
- ``daemon status``
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

import psycopg


DEFAULT_NATIVE_PORT = 5434
DEFAULT_DOCKER_PORT = 5433
DB_USER = "patchdiff"
DB_PASSWORD = "patchdiff"
DB_NAME = "patchdiff"
DOCKER_CONTAINER_NAME = "patchdiff-postgres"
ORPHAN_CONTAINERS = ("patchdiff-pgweb",)


def get_default_runtime_dir() -> Path:
    override = os.getenv("PATCHDIFF_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".local" / "share" / "patchdiff-runtime").resolve()


def get_default_native_pgdata() -> Path:
    override = os.getenv("PATCHDIFF_NATIVE_PGDATA")
    if override:
        return Path(override).expanduser().resolve()
    return get_default_runtime_dir() / "pgdata"


def get_default_native_pgrun() -> Path:
    override = os.getenv("PATCHDIFF_NATIVE_PGRUN")
    if override:
        return Path(override).expanduser().resolve()
    return get_default_runtime_dir() / "pgrun"


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


def get_alembic_ini_path() -> Path:
    packaged = Path(__file__).resolve().parents[1] / "migrations" / "alembic.ini"
    if packaged.is_file():
        return packaged
    repo_ini = get_default_repo_root() / "backend" / "app" / "migrations" / "alembic.ini"
    if repo_ini.is_file():
        return repo_ini
    raise FileNotFoundError(f"Could not locate alembic.ini at {packaged} or {repo_ini}")


def build_database_url(port: int, host: str = "127.0.0.1", dbname: str = DB_NAME) -> str:
    return f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{host}:{port}/{dbname}"


def build_psycopg_dsn(port: int, host: str = "127.0.0.1", dbname: str = DB_NAME) -> str:
    return f"postgresql://{DB_USER}:{DB_PASSWORD}@{host}:{port}/{dbname}"


def is_tcp_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_db_connection(port: int, host: str = "127.0.0.1", dbname: str = DB_NAME) -> tuple[bool, str | None]:
    dsn = build_psycopg_dsn(port=port, host=host, dbname=dbname)
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
    hba_path = pgdata / "pg_hba.conf"
    if not hba_path.is_file():
        return
    content = hba_path.read_text(encoding="utf-8")
    marker = "# --- PATCHDIFF NATIVE HBA ---"
    if marker in content:
        return
    rules = (
        f"\n{marker}\n"
        "local   all             all                                     trust\n"
        "host    all             all             127.0.0.1/32            scram-sha-256\n"
        "host    all             all             ::1/128                 scram-sha-256\n"
    )
    hba_path.write_text(rules + "\n" + content, encoding="utf-8")


def ensure_native_cluster(pgdata: Path, pgrun: Path, port: int) -> Path:
    pg_bin = find_pg_bin_dir()
    initdb_bin = pg_bin / "initdb"
    pgrun.mkdir(parents=True, exist_ok=True)
    os.chmod(pgrun, 0o700)

    if not (pgdata / "PG_VERSION").is_file():
        pgdata.mkdir(parents=True, exist_ok=True)
        os.chmod(pgdata, 0o700)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as pwf:
            pwf.write(DB_PASSWORD + "\n")
            pwfile_path = Path(pwf.name)
        try:
            os.chmod(pwfile_path, 0o600)
            cmd = [
                str(initdb_bin),
                "-D",
                str(pgdata),
                "-U",
                DB_USER,
                f"--pwfile={pwfile_path}",
                "--encoding=UTF8",
                "--locale=C.UTF-8",
                "--auth-local=trust",
                "--auth-host=scram-sha-256",
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60.0)
        finally:
            pwfile_path.unlink(missing_ok=True)

    _configure_postgresql_conf(pgdata, pgrun, port)
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


def _ensure_native_database_exists(port: int) -> None:
    ok, _ = check_db_connection(port=port, dbname=DB_NAME)
    if ok:
        return
    postgres_dsn = build_psycopg_dsn(port=port, dbname="postgres")
    with psycopg.connect(postgres_dsn, autocommit=True, connect_timeout=5) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)
        ).fetchone()
        if not row:
            conn.execute(f'CREATE DATABASE "{DB_NAME}" OWNER "{DB_USER}"')


def native_daemon(
    action: str,
    *,
    port: int = DEFAULT_NATIVE_PORT,
    pgdata: Path | None = None,
    pgrun: Path | None = None,
) -> dict[str, Any]:
    pgdata_dir = pgdata or get_default_native_pgdata()
    pgrun_dir = pgrun or get_default_native_pgrun()
    pg_bin = find_pg_bin_dir()
    pg_ctl = pg_bin / "pg_ctl"
    logfile = pgdata_dir / "postgresql.log"

    if action == "status":
        running, detail = _native_pg_ctl_status(pg_bin, pgdata_dir)
        db_ready, rev = check_db_connection(port=port) if running else (False, None)
        return {
            "route": "native",
            "action": "status",
            "status": "running" if (running and db_ready) else ("starting" if running else "stopped"),
            "host": "127.0.0.1",
            "port": port,
            "database_url": build_database_url(port=port),
            "db_ready": db_ready,
            "alembic_revision": rev,
            "pgdata": str(pgdata_dir),
            "backend_detail": detail,
        }

    if action == "stop":
        running, detail = _native_pg_ctl_status(pg_bin, pgdata_dir)
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
            "database_url": build_database_url(port=port),
            "db_ready": False,
            "alembic_revision": None,
            "pgdata": str(pgdata_dir),
            "backend_detail": after_detail,
        }

    if action == "restart":
        native_daemon("stop", port=port, pgdata=pgdata_dir, pgrun=pgrun_dir)
        res = native_daemon("start", port=port, pgdata=pgdata_dir, pgrun=pgrun_dir)
        res["action"] = "restart"
        return res

    if action == "start":
        ensure_native_cluster(pgdata_dir, pgrun_dir, port)
        running, _ = _native_pg_ctl_status(pg_bin, pgdata_dir)
        if not running:
            subprocess.run(
                [str(pg_ctl), "-D", str(pgdata_dir), "-l", str(logfile), "-w", "start"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30.0,
            )
        # Wait for readiness and ensure patchdiff database exists
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if is_tcp_port_open(port):
                try:
                    _ensure_native_database_exists(port)
                    break
                except Exception:
                    pass
            time.sleep(0.25)

        running, detail = _native_pg_ctl_status(pg_bin, pgdata_dir)
        db_ready, rev = check_db_connection(port=port)
        if not (running and db_ready):
            raise RuntimeError(
                f"Native PostgreSQL daemon failed to become ready on 127.0.0.1:{port} ({detail})"
            )
        return {
            "route": "native",
            "action": "start",
            "status": "running",
            "host": "127.0.0.1",
            "port": port,
            "database_url": build_database_url(port=port),
            "db_ready": db_ready,
            "alembic_revision": rev,
            "pgdata": str(pgdata_dir),
            "backend_detail": detail,
        }

    raise ValueError(f"Unsupported daemon action: {action!r}")


def _ensure_compose_env_port(repo_root: Path, port: int) -> None:
    env_file = repo_root / ".env"
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


def _inspect_docker_container(name: str) -> dict[str, Any] | None:
    proc = subprocess.run(
        ["docker", "inspect", name],
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


def _clean_stale_docker_containers(repo_root: Path, port: int) -> None:
    for orphan in ORPHAN_CONTAINERS:
        info = _inspect_docker_container(orphan)
        if info is not None:
            subprocess.run(
                ["docker", "rm", "-f", orphan],
                capture_output=True,
                text=True,
                timeout=15.0,
            )

    info = _inspect_docker_container(DOCKER_CONTAINER_NAME)
    if info is None:
        return

    labels = info.get("Config", {}).get("Labels") or {}
    working_dir = labels.get("com.docker.compose.project.working_dir", "")
    bindings = (
        info.get("HostConfig", {}).get("PortBindings", {}).get("5432/tcp") or []
    )
    bound_ports = {str(b.get("HostPort", "")) for b in bindings if isinstance(b, dict)}
    expected_port = str(port)

    mismatch_workdir = bool(working_dir) and Path(working_dir) != repo_root
    mismatch_port = bound_ports != {expected_port}
    if mismatch_workdir or mismatch_port:
        subprocess.run(
            ["docker", "rm", "-f", DOCKER_CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=15.0,
        )


def docker_daemon(
    action: str,
    *,
    port: int = DEFAULT_DOCKER_PORT,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    root = repo_root or get_default_repo_root()
    compose_file = root / "docker-compose.yml"
    if not compose_file.is_file():
        raise FileNotFoundError(f"docker-compose.yml not found at {compose_file}")

    compose_env = {
        **os.environ,
        "PATCHDIFF_POSTGRES_PORT": str(port),
    }

    if action == "status":
        info = _inspect_docker_container(DOCKER_CONTAINER_NAME)
        state = info.get("State", {}) if info else {}
        running = bool(state.get("Running", False))
        status_label = state.get("Status", "not_created") if info else "not_created"
        db_ready, rev = check_db_connection(port=port) if running else (False, None)
        return {
            "route": "docker",
            "action": "status",
            "status": "running" if (running and db_ready) else ("starting" if running else "stopped"),
            "host": "127.0.0.1",
            "port": port,
            "database_url": build_database_url(port=port),
            "db_ready": db_ready,
            "alembic_revision": rev,
            "container": DOCKER_CONTAINER_NAME,
            "backend_detail": f"container={status_label}",
        }

    if action == "stop":
        info = _inspect_docker_container(DOCKER_CONTAINER_NAME)
        if info is not None:
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "stop", "postgres"],
                cwd=str(root),
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
            "database_url": build_database_url(port=port),
            "db_ready": False,
            "alembic_revision": None,
            "container": DOCKER_CONTAINER_NAME,
            "backend_detail": "container=exited",
        }

    if action == "restart":
        docker_daemon("stop", port=port, repo_root=root)
        res = docker_daemon("start", port=port, repo_root=root)
        res["action"] = "restart"
        return res

    if action == "start":
        _ensure_compose_env_port(root, port)
        _clean_stale_docker_containers(root, port)
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d", "postgres"],
            cwd=str(root),
            env=compose_env,
            check=True,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        deadline = time.monotonic() + 30.0
        db_ready = False
        rev = None
        while time.monotonic() < deadline:
            db_ready, rev = check_db_connection(port=port)
            if db_ready:
                break
            time.sleep(0.5)
        if not db_ready:
            raise RuntimeError(
                f"Docker container {DOCKER_CONTAINER_NAME} failed to become ready on 127.0.0.1:{port}"
            )
        return {
            "route": "docker",
            "action": "start",
            "status": "running",
            "host": "127.0.0.1",
            "port": port,
            "database_url": build_database_url(port=port),
            "db_ready": db_ready,
            "alembic_revision": rev,
            "container": DOCKER_CONTAINER_NAME,
            "backend_detail": "container=running",
        }

    raise ValueError(f"Unsupported daemon action: {action!r}")


def run_alembic_upgrade(database_url: str) -> str:
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
    # Extract port from URL to query version
    m = re.search(r":(\d+)/", database_url)
    port = int(m.group(1)) if m else DEFAULT_NATIVE_PORT
    _, rev = check_db_connection(port=port)
    if not rev:
        raise RuntimeError(f"Alembic migration completed for {database_url}, but alembic_version is empty")
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
) -> Path:
    from app.services.waymark_adapter import get_waymark_bridge_dir, resolve_node_executable

    active_port = native_port if active_route == "native" else docker_port
    active_db_url = build_database_url(port=active_port)
    bridge_dir = str(get_waymark_bridge_dir())
    node_path = resolve_node_executable()
    backend_dir = str(Path(__file__).resolve().parents[2])

    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    mcp_servers = existing.setdefault("mcpServers", {})
    server_entry: dict[str, Any] = {
        "command": sys.executable,
        "args": ["-m", "app.mcp.external_adapter"],
        "env": {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": backend_dir,
            "PATCHDIFF_DATABASE_URL": active_db_url,
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
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return config_path


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
) -> dict[str, Any]:
    if native_port == docker_port:
        raise ValueError(
            f"native_port ({native_port}) and docker_port ({docker_port}) must be distinct so both routes operate independently."
        )
    results: dict[str, Any] = {}
    for target in resolve_routes(route):
        if target == "native":
            results["native"] = native_daemon(action, port=native_port)
        elif target == "docker":
            results["docker"] = docker_daemon(action, port=docker_port)
    return {"command": f"daemon.{action}", "route": route, "routes": results}


def run_setup_command(
    *,
    route: str = "both",
    native_port: int = DEFAULT_NATIVE_PORT,
    docker_port: int = DEFAULT_DOCKER_PORT,
    mcp_route: str = "native",
    mcp_config: Path | None = None,
    update_mcp: bool = False,
) -> dict[str, Any]:
    if native_port == docker_port:
        raise ValueError(
            f"native_port ({native_port}) and docker_port ({docker_port}) must be distinct so both routes operate independently."
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
    for target in resolve_routes(route):
        if target == "native":
            d_info = native_daemon("start", port=native_port)
        else:
            d_info = docker_daemon("start", port=docker_port)
        db_url = d_info["database_url"]
        rev = run_alembic_upgrade(db_url)
        d_info["alembic_revision"] = rev
        d_info["mcp_smoke_tools"] = smoke_test_mcp_adapter(db_url)
        routes_summary[target] = d_info

    updated_config_path: str | None = None
    if update_mcp or mcp_config is not None:
        target_cfg = mcp_config or (Path.home() / ".gemini" / "config" / "mcp_config.json")
        chosen_route = mcp_route if mcp_route in {"native", "docker"} else "native"
        if route in {"native", "docker"} and mcp_route == "native" and route == "docker":
            chosen_route = "docker"
        written = update_host_mcp_config(
            target_cfg,
            active_route=chosen_route,
            native_port=native_port,
            docker_port=docker_port,
        )
        updated_config_path = str(written)

    return {
        "command": "setup",
        "route": route,
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
        help=f"Port for Docker Compose patchdiff-postgres container (default: {DEFAULT_DOCKER_PORT})",
    )
    setup_p.add_argument(
        "--mcp-route",
        choices=("native", "docker"),
        default="native",
        help="Which route to bind in the MCP host config when --update-mcp-config is used (default: native)",
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
        help=f"Port for Docker Compose patchdiff-postgres container (default: {DEFAULT_DOCKER_PORT})",
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
