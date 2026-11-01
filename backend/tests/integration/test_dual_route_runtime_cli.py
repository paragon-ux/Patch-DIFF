"""Integration tests for dual-route PostgreSQL setup, credential/role isolation, and daemon lifecycle CLI."""

from __future__ import annotations

from pathlib import Path
import socket
from urllib.parse import quote
import psycopg
import pytest

from app.mcp import runtime_cli


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_native_daemon_lifecycle_and_credential_role_isolation(tmp_path: Path):
    """Verify native PostgreSQL cluster init, scram-sha-256 enforcement, role separation, and lifecycle (PR23-R4I-ARCH-001)."""
    try:
        runtime_cli.find_pg_bin_dir()
    except RuntimeError:
        pytest.skip("PostgreSQL server binaries (initdb/pg_ctl) not installed on this runner")

    runtime_dir = tmp_path / "runtime"
    pgdata = runtime_dir / "pgdata"
    pgrun = runtime_dir / "pgrun"
    port = _pick_free_port()

    try:
        # 1. Initial status before creation -> stopped
        st0 = runtime_cli.native_daemon("status", port=port, pgdata=pgdata, pgrun=pgrun, runtime_dir=runtime_dir)
        assert st0["route"] == "native"
        assert st0["status"] == "stopped"
        assert st0["db_ready"] is False

        # 2. Start daemon -> initializes cluster with scram-sha-256 and unique credentials
        started = runtime_cli.native_daemon("start", port=port, pgdata=pgdata, pgrun=pgrun, runtime_dir=runtime_dir)
        assert started["status"] == "running"
        assert started["db_ready"] is True
        assert started["port"] == port

        # 3. Assert known default 'patchdiff:patchdiff' and unauthenticated local/TCP connections FAIL
        for bad_dsn in (
            f"postgresql://patchdiff:patchdiff@127.0.0.1:{port}/patchdiff",
            f"postgresql://patchdiff_admin:patchdiff@127.0.0.1:{port}/patchdiff",
            f"postgresql://patchdiff_admin@127.0.0.1:{port}/patchdiff",
            f"postgresql://patchdiff_admin@/patchdiff?host={pgrun.as_posix()}&port={port}",
        ):
            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(bad_dsn, connect_timeout=2).close()

        # 4. Apply Alembic migrations and enforce least-privilege role separation
        rev = runtime_cli.run_alembic_upgrade(started["database_url"], runtime_dir=runtime_dir)
        assert rev == "20261031_0007"

        # 5. Verify agent role can query editing tables but is DENIED access to target_finalizations and DDL
        creds = runtime_cli.ensure_runtime_credentials(runtime_dir)
        agent_dsn = runtime_cli.build_psycopg_dsn(port=port, role="agent", creds=creds)
        with psycopg.connect(agent_dsn, autocommit=True, connect_timeout=3) as agent_conn:
            # Allowed: SELECT on cloud_target_files
            rows = agent_conn.execute("SELECT count(*) FROM cloud_target_files").fetchone()
            assert rows is not None and rows[0] == 0

            # Denied: SELECT on target_finalizations (privileged host table)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                agent_conn.execute("SELECT count(*) FROM target_finalizations")

            # Denied: SELECT on alembic_version
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                agent_conn.execute("SELECT version_num FROM alembic_version")

            # Denied: DDL (CREATE TABLE)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                agent_conn.execute("CREATE TABLE unauthorized_agent_table (id int)")

        st1 = runtime_cli.native_daemon("status", port=port, pgdata=pgdata, pgrun=pgrun, runtime_dir=runtime_dir)
        assert st1["status"] == "running"
        assert st1["db_ready"] is True
        assert st1["alembic_revision"] == "20261031_0007"

        # 6. Restart daemon -> remains running and preserves migrated schema
        restarted = runtime_cli.native_daemon("restart", port=port, pgdata=pgdata, pgrun=pgrun, runtime_dir=runtime_dir)
        assert restarted["action"] == "restart"
        assert restarted["status"] == "running"
        assert restarted["db_ready"] is True
        assert restarted["alembic_revision"] == "20261031_0007"

        # 7. Stop daemon -> cleanly stops server and frees port
        stopped = runtime_cli.native_daemon("stop", port=port, pgdata=pgdata, pgrun=pgrun, runtime_dir=runtime_dir)
        assert stopped["status"] == "stopped"
        assert stopped["db_ready"] is False
        assert not runtime_cli.is_tcp_port_open(port)
    finally:
        try:
            runtime_cli.native_daemon("stop", port=port, pgdata=pgdata, pgrun=pgrun, runtime_dir=runtime_dir)
        except Exception:
            pass
