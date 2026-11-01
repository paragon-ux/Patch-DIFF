"""Unit tests for dual-route PostgreSQL setup and daemon lifecycle CLI."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.mcp import runtime_cli


def test_resolve_routes():
    assert runtime_cli.resolve_routes("native") == ["native"]
    assert runtime_cli.resolve_routes("docker") == ["docker"]
    assert runtime_cli.resolve_routes("both") == ["native", "docker"]
    with pytest.raises(ValueError, match="Invalid route"):
        runtime_cli.resolve_routes("invalid")


def test_distinct_ports_enforced_in_daemon_and_setup():
    with pytest.raises(ValueError, match="must be distinct"):
        runtime_cli.run_daemon_command("status", route="both", native_port=5433, docker_port=5433)
    with pytest.raises(ValueError, match="must be distinct"):
        runtime_cli.run_setup_command(route="both", native_port=5434, docker_port=5434)


def test_configure_postgresql_conf_and_pg_hba_idempotent(tmp_path: Path):
    pgdata = tmp_path / "pgdata"
    pgrun = tmp_path / "pgrun"
    pgdata.mkdir()
    pgrun.mkdir()

    conf = pgdata / "postgresql.conf"
    conf.write_text("# base config\nmax_connections = 100\n", encoding="utf-8")
    hba = pgdata / "pg_hba.conf"
    hba.write_text("# base hba\n", encoding="utf-8")

    runtime_cli._configure_postgresql_conf(pgdata, pgrun, 5434)
    first_conf = conf.read_text(encoding="utf-8")
    assert "port = 5434" in first_conf
    assert f"unix_socket_directories = '{pgrun.as_posix()}'" in first_conf

    # Updating port replaces existing managed block without duplicating markers
    runtime_cli._configure_postgresql_conf(pgdata, pgrun, 5435)
    second_conf = conf.read_text(encoding="utf-8")
    assert "port = 5435" in second_conf
    assert "port = 5434" not in second_conf
    assert second_conf.count("# --- PATCHDIFF NATIVE CONFIG BEGIN ---") == 1

    runtime_cli._configure_pg_hba(pgdata)
    first_hba = hba.read_text(encoding="utf-8")
    runtime_cli._configure_pg_hba(pgdata)
    second_hba = hba.read_text(encoding="utf-8")
    assert first_hba == second_hba
    assert "scram-sha-256" in second_hba


def test_ensure_compose_env_port_creates_and_updates(tmp_path: Path):
    runtime_cli._ensure_compose_env_port(tmp_path, 5433)
    env_file = tmp_path / ".env"
    assert env_file.read_text(encoding="utf-8") == "PATCHDIFF_POSTGRES_PORT=5433\n"

    env_file.write_text("OTHER_VAR=1\nPATCHDIFF_POSTGRES_PORT=5432\n", encoding="utf-8")
    runtime_cli._ensure_compose_env_port(tmp_path, 5433)
    assert env_file.read_text(encoding="utf-8") == "OTHER_VAR=1\nPATCHDIFF_POSTGRES_PORT=5433\n"


def test_update_host_mcp_config_for_both_routes(tmp_path: Path):
    cfg_path = tmp_path / "mcp_config.json"

    runtime_cli.update_host_mcp_config(
        cfg_path,
        active_route="native",
        native_port=5434,
        docker_port=5433,
    )
    data_native = json.loads(cfg_path.read_text(encoding="utf-8"))
    env_native = data_native["mcpServers"]["patchdiff"]["env"]
    assert env_native["PATCHDIFF_ACTIVE_ROUTE"] == "native"
    assert ":5434/patchdiff" in env_native["PATCHDIFF_DATABASE_URL"]
    assert env_native["PATCHDIFF_MCP_PROFILE"] == "observed_v2"
    assert env_native["PATCHDIFF_WAYMARK_MODE"] == "resident"

    runtime_cli.update_host_mcp_config(
        cfg_path,
        active_route="docker",
        native_port=5434,
        docker_port=5433,
    )
    data_docker = json.loads(cfg_path.read_text(encoding="utf-8"))
    env_docker = data_docker["mcpServers"]["patchdiff"]["env"]
    assert env_docker["PATCHDIFF_ACTIVE_ROUTE"] == "docker"
    assert ":5433/patchdiff" in env_docker["PATCHDIFF_DATABASE_URL"]


def test_cli_parser_accepts_setup_and_daemon_commands():
    parser = runtime_cli.build_parser()

    args_setup = parser.parse_args(["setup", "--route", "both", "--native-port", "5434", "--docker-port", "5433", "--update-mcp-config"])
    assert args_setup.subcommand == "setup"
    assert args_setup.route == "both"
    assert args_setup.native_port == 5434
    assert args_setup.docker_port == 5433
    assert args_setup.update_mcp_config is True

    for action in ("start", "stop", "restart", "status"):
        for route in ("native", "docker", "both"):
            args_daemon = parser.parse_args(["daemon", action, "--route", route])
            assert args_daemon.subcommand == "daemon"
            assert args_daemon.action == action
            assert args_daemon.route == route
