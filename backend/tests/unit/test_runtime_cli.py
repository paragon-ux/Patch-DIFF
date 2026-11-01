"""Unit tests for dual-route PostgreSQL setup and daemon lifecycle CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from unittest.mock import MagicMock, patch
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


def test_credentials_generation_permissions_and_default_rejection(tmp_path: Path):
    """PR23-R4I-ARCH-001: High-entropy credentials generated with 0600 mode; 'patchdiff' default rejected."""
    for bad_pw in ("patchdiff", "postgres", "password", "short", ""):
        with pytest.raises(ValueError, match="Rejected insecure or known-default"):
            runtime_cli.validate_credential_secret(bad_pw)

    creds = runtime_cli.ensure_runtime_credentials(tmp_path)
    assert creds["admin_user"] == "patchdiff_admin"
    assert creds["agent_user"] == "patchdiff_agent"
    assert creds["admin_password"] != "patchdiff"
    assert creds["agent_password"] != "patchdiff"
    assert creds["admin_password"] != creds["agent_password"]
    assert len(creds["admin_password"]) >= 32
    assert len(creds["agent_password"]) >= 32

    cred_file = Path(creds["credentials_file"])
    assert cred_file.is_file()
    mode = stat.S_IMODE(cred_file.stat().st_mode)
    assert mode == 0o600

    # Reloading returns identical persisted credentials
    creds2 = runtime_cli.ensure_runtime_credentials(tmp_path)
    assert creds2 == creds


def test_configure_postgresql_conf_and_pg_hba_strict_scram_no_trust(tmp_path: Path):
    """PR23-R4I-ARCH-001: pg_hba.conf enforces scram-sha-256 on all connections and eliminates trust."""
    pgdata = tmp_path / "pgdata"
    pgrun = tmp_path / "pgrun"
    pgdata.mkdir()
    pgrun.mkdir()

    conf = pgdata / "postgresql.conf"
    conf.write_text("# base config\nmax_connections = 100\n", encoding="utf-8")
    hba = pgdata / "pg_hba.conf"
    hba.write_text(
        "# base hba\n"
        "local   all             all                                     trust\n"
        "host    all             all             127.0.0.1/32            trust\n",
        encoding="utf-8",
    )

    runtime_cli._configure_postgresql_conf(pgdata, pgrun, 5434)
    first_conf = conf.read_text(encoding="utf-8")
    assert "port = 5434" in first_conf
    assert f"unix_socket_directories = '{pgrun.as_posix()}'" in first_conf
    assert "unix_socket_permissions = 0700" in first_conf
    assert "password_encryption = 'scram-sha-256'" in first_conf

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
    # Zero non-comment lines may contain 'trust'
    active_lines = [ln for ln in second_hba.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert active_lines
    for ln in active_lines:
        assert "trust" not in ln.split()


def test_foreign_docker_container_never_removed_or_stopped(tmp_path: Path):
    """PR23-R4I-SCRIPT-001: Foreign project/checkout container causes conflict error with zero docker rm/stop calls."""
    checkout_a = tmp_path / "checkout_a"
    checkout_b = tmp_path / "checkout_b"
    checkout_a.mkdir()
    checkout_b.mkdir()
    (checkout_b / "docker-compose.yml").write_text("services:\n  postgres:\n    image: postgres:16.3-alpine\n", encoding="utf-8")

    foreign_inspect = {
        "Name": "/patchdiff-postgres",
        "State": {"Running": True, "Status": "running"},
        "Config": {
            "Labels": {
                "com.docker.compose.project": "patchdiff-foreign",
                "com.docker.compose.project.working_dir": str(checkout_a.resolve()),
            }
        },
        "HostConfig": {
            "PortBindings": {
                "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5433"}]
            }
        },
    }

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["docker", "ps"]:
            return MagicMock(returncode=0, stdout="patchdiff-postgres\n", stderr="")
        if cmd[:2] == ["docker", "inspect"]:
            return MagicMock(returncode=0, stdout=json.dumps([foreign_inspect]), stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("app.mcp.runtime_cli.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError, match="Foreign Docker container conflict"):
            runtime_cli.docker_daemon("start", port=5433, repo_root=checkout_b, runtime_dir=tmp_path / "rt")
        with pytest.raises(RuntimeError, match="Foreign Docker container conflict"):
            runtime_cli.docker_daemon("stop", port=5433, repo_root=checkout_b, runtime_dir=tmp_path / "rt")

    # Assert zero docker rm or docker compose stop calls were made!
    for c in calls:
        assert "rm" not in c, f"Forbidden docker rm call executed: {c}"
        assert "stop" not in c, f"Forbidden docker stop call on foreign container executed: {c}"


def test_packaged_compose_workspace_materializes_outside_checkout(tmp_path: Path, monkeypatch):
    """PR23-R4I-DEP-001: resolve_compose_workspace materializes packaged docker-compose.yml when outside repo."""
    monkeypatch.delenv("PATCHDIFF_REPO_ROOT", raising=False)
    # Simulate installed package location where parents[3] has no docker-compose.yml
    fake_pkg_file = tmp_path / "venv" / "lib" / "python3.11" / "site-packages" / "app" / "mcp" / "runtime_cli.py"
    fake_pkg_file.parent.mkdir(parents=True)
    res_dir = fake_pkg_file.parent / "resources"
    res_dir.mkdir()
    real_compose = (Path(__file__).resolve().parents[3] / "docker-compose.yml").read_bytes()
    (res_dir / "docker-compose.yml").write_bytes(real_compose)

    runtime_dir = tmp_path / "runtime"
    with patch.object(runtime_cli, "__file__", str(fake_pkg_file)):
        work_dir, compose_file = runtime_cli.resolve_compose_workspace(repo_root=None, runtime_dir=runtime_dir)
        assert compose_file.is_file()
        assert work_dir == runtime_dir / "docker"
        assert compose_file.read_bytes() == real_compose


def test_setup_preflight_fails_before_starting_native_when_docker_missing(tmp_path: Path):
    """PR23-R4I-DEP-001: setup --route both fails preflight without starting native when Docker is unavailable."""
    native_called = False

    def fake_native(*args, **kwargs):
        nonlocal native_called
        native_called = True
        return {}

    with (
        patch("app.mcp.runtime_cli.find_pg_bin_dir", return_value=Path("/usr/bin")),
        patch("app.mcp.runtime_cli.shutil.which", return_value=None),
        patch("app.mcp.runtime_cli.native_daemon", side_effect=fake_native),
    ):
        with pytest.raises(RuntimeError, match="Docker CLI .* is not installed"):
            runtime_cli.run_setup_command(route="both", runtime_dir=tmp_path)

    assert native_called is False, "native_daemon must not be called when docker preflight fails"


def test_explicit_mcp_route_native_not_overwritten_by_docker_route(tmp_path: Path):
    """PR23-R4I-MCP-001: setup --route docker --mcp-route native honors native or fails if unreachable; never writes docker URL."""
    cfg_path = tmp_path / "mcp_config.json"

    # 1. Omitted mcp_route (None) with route='docker' infers 'docker'
    assert runtime_cli.resolve_effective_mcp_route("docker", None) == "docker"
    assert runtime_cli.resolve_effective_mcp_route("native", None) == "native"
    assert runtime_cli.resolve_effective_mcp_route("both", None) == "native"

    # 2. Explicit mcp_route='native' with route='docker' is NEVER overwritten to 'docker'
    assert runtime_cli.resolve_effective_mcp_route("docker", "native") == "native"
    assert runtime_cli.resolve_effective_mcp_route("native", "docker") == "docker"

    # 3. When native is unreachable and user runs setup --route docker --mcp-route native --update-mcp-config, it rejects!
    with (
        patch("app.mcp.runtime_cli.preflight_routes"),
        patch("app.mcp.runtime_cli.check_db_connection", return_value=(False, None)),
    ):
        with pytest.raises(RuntimeError, match="Explicit --mcp-route 'native' was not provisioned"):
            runtime_cli.run_setup_command(
                route="docker",
                mcp_route="native",
                mcp_config=cfg_path,
                update_mcp=True,
                runtime_dir=tmp_path,
            )
    assert not cfg_path.exists()

    # 4. When native IS reachable, setup --route docker --mcp-route native writes the native port (5434), never docker (5433)
    with (
        patch("app.mcp.runtime_cli.preflight_routes"),
        patch("app.mcp.runtime_cli.check_db_connection", return_value=(True, "20261031_0007")),
        patch("app.mcp.runtime_cli.docker_daemon", return_value={"database_url": "postgresql+psycopg://u:p@127.0.0.1:5433/patchdiff"}),
        patch("app.mcp.runtime_cli.run_alembic_upgrade", return_value="20261031_0007"),
        patch("app.mcp.runtime_cli.smoke_test_mcp_adapter", return_value={"observed_v2": 5, "full": 24}),
        patch("app.waymark_bridge.bootstrap.verify_installed_bridge", return_value="4.1.0"),
    ):
        res = runtime_cli.run_setup_command(
            route="docker",
            native_port=5434,
            docker_port=5433,
            mcp_route="native",
            mcp_config=cfg_path,
            update_mcp=True,
            runtime_dir=tmp_path,
        )
    assert res["mcp_route"] == "native"
    written_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    env_written = written_cfg["mcpServers"]["patchdiff"]["env"]
    assert env_written["PATCHDIFF_ACTIVE_ROUTE"] == "native"
    assert ":5434/patchdiff" in env_written["PATCHDIFF_DATABASE_URL"]
    assert ":5433/patchdiff" not in env_written["PATCHDIFF_DATABASE_URL"]


def test_update_host_mcp_config_preserves_malformed_and_writes_atomically_0600(tmp_path: Path):
    """PR23-R4I-SCRIPT-002: Malformed JSON is never overwritten; valid config retains unrelated servers and mode 0600."""
    cfg_path = tmp_path / "mcp_config.json"
    malformed_content = '{"mcpServers": {"other": {"command": "foo"}}, BROKEN JSON'
    cfg_path.write_text(malformed_content, encoding="utf-8")

    with pytest.raises(ValueError, match="malformed JSON"):
        runtime_cli.update_host_mcp_config(
            cfg_path,
            active_route="native",
            native_port=5434,
            docker_port=5433,
            runtime_dir=tmp_path,
        )
    # Original malformed file must remain completely untouched!
    assert cfg_path.read_text(encoding="utf-8") == malformed_content

    # Valid existing config with unrelated server
    valid_initial = {
        "mcpServers": {
            "unrelated_server": {"command": "/bin/echo", "args": ["hello"]},
        },
        "customTopLevelKey": True,
    }
    cfg_path.write_text(json.dumps(valid_initial), encoding="utf-8")

    # Simulate crash during os.replace: original file must remain intact
    with patch("app.mcp.runtime_cli.os.replace", side_effect=OSError("simulated crash before replace")):
        with pytest.raises(OSError, match="simulated crash"):
            runtime_cli.update_host_mcp_config(
                cfg_path,
                active_route="native",
                native_port=5434,
                docker_port=5433,
                runtime_dir=tmp_path,
            )
    assert json.loads(cfg_path.read_text(encoding="utf-8")) == valid_initial

    # Successful atomic update
    runtime_cli.update_host_mcp_config(
        cfg_path,
        active_route="native",
        native_port=5434,
        docker_port=5433,
        runtime_dir=tmp_path,
    )
    updated = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert updated["customTopLevelKey"] is True
    assert updated["mcpServers"]["unrelated_server"] == {"command": "/bin/echo", "args": ["hello"]}
    env_native = updated["mcpServers"]["patchdiff"]["env"]
    assert env_native["PATCHDIFF_ACTIVE_ROUTE"] == "native"
    assert ":5434/patchdiff" in env_native["PATCHDIFF_DATABASE_URL"]
    assert "patchdiff_agent:" in env_native["PATCHDIFF_DATABASE_URL"]
    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600
    assert (tmp_path / "mcp_config.json.bak").is_file()


def test_cli_parser_accepts_setup_and_daemon_commands():
    parser = runtime_cli.build_parser()

    args_setup = parser.parse_args(["setup", "--route", "both", "--native-port", "5434", "--docker-port", "5433", "--update-mcp-config"])
    assert args_setup.subcommand == "setup"
    assert args_setup.route == "both"
    assert args_setup.native_port == 5434
    assert args_setup.docker_port == 5433
    assert args_setup.mcp_route is None
    assert args_setup.update_mcp_config is True

    for action in ("start", "stop", "restart", "status"):
        for route in ("native", "docker", "both"):
            args_daemon = parser.parse_args(["daemon", action, "--route", route])
            assert args_daemon.subcommand == "daemon"
            assert args_daemon.action == action
            assert args_daemon.route == route
