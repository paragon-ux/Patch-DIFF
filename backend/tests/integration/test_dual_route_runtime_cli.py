"""Integration tests for dual-route PostgreSQL setup and daemon lifecycle CLI."""

from __future__ import annotations

from pathlib import Path
import socket
import pytest

from app.mcp import runtime_cli


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_native_daemon_lifecycle_start_stop_restart_status(tmp_path: Path):
    """Verify full native PostgreSQL cluster init, start, status, restart, and stop on an isolated port."""
    try:
        runtime_cli.find_pg_bin_dir()
    except RuntimeError:
        pytest.skip("PostgreSQL server binaries (initdb/pg_ctl) not installed on this runner")

    pgdata = tmp_path / "pgdata"
    pgrun = tmp_path / "pgrun"
    port = _pick_free_port()

    try:
        # 1. Initial status before creation -> stopped
        st0 = runtime_cli.native_daemon("status", port=port, pgdata=pgdata, pgrun=pgrun)
        assert st0["route"] == "native"
        assert st0["status"] == "stopped"
        assert st0["db_ready"] is False

        # 2. Start daemon -> initializes cluster and starts postgres on isolated port
        started = runtime_cli.native_daemon("start", port=port, pgdata=pgdata, pgrun=pgrun)
        assert started["status"] == "running"
        assert started["db_ready"] is True
        assert started["port"] == port

        # 3. Apply Alembic migrations and verify head revision
        rev = runtime_cli.run_alembic_upgrade(started["database_url"])
        assert rev == "20261031_0007"

        st1 = runtime_cli.native_daemon("status", port=port, pgdata=pgdata, pgrun=pgrun)
        assert st1["status"] == "running"
        assert st1["db_ready"] is True
        assert st1["alembic_revision"] == "20261031_0007"

        # 4. Restart daemon -> remains running and preserves migrated schema
        restarted = runtime_cli.native_daemon("restart", port=port, pgdata=pgdata, pgrun=pgrun)
        assert restarted["action"] == "restart"
        assert restarted["status"] == "running"
        assert restarted["db_ready"] is True
        assert restarted["alembic_revision"] == "20261031_0007"

        # 5. Stop daemon -> cleanly stops server and frees port
        stopped = runtime_cli.native_daemon("stop", port=port, pgdata=pgdata, pgrun=pgrun)
        assert stopped["status"] == "stopped"
        assert stopped["db_ready"] is False
        assert not runtime_cli.is_tcp_port_open(port)
    finally:
        try:
            runtime_cli.native_daemon("stop", port=port, pgdata=pgdata, pgrun=pgrun)
        except Exception:
            pass
