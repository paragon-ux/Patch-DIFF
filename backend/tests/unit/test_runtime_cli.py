"""Unit tests for Docker-only runtime CLI, 3-role credential isolation, and safe atomic config backup (Stages A, B, E)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest

from app.core import config as core_config
from app.mcp import runtime_cli


@pytest.fixture(autouse=True)
def _private_tmp_umask(tmp_path: Path):
    old_umask = os.umask(0o077)
    os.chmod(tmp_path, 0o700)
    try:
        yield
    finally:
        os.umask(old_umask)


def test_native_and_dual_route_functions_completely_removed():
    """Stage A (PR23-R5-ARCH-002): All native PostgreSQL and dual-route provisioning symbols are removed."""
    removed_symbols = (
        "find_pg_bin_dir",
        "ensure_native_cluster",
        "native_daemon",
        "_native_pg_ctl_status",
        "_configure_postgresql_conf",
        "_configure_pg_hba",
        "resolve_routes",
        "resolve_effective_mcp_route",
        "DEFAULT_NATIVE_PORT",
    )
    for sym in removed_symbols:
        assert not hasattr(runtime_cli, sym), f"Obsolete symbol {sym} must not exist on runtime_cli"


@pytest.mark.parametrize(
    "obsolete_argv",
    [
        ["setup", "--route", "native"],
        ["setup", "--route", "both"],
        ["setup", "--route", "docker"],
        ["setup", "--mcp-route", "native"],
        ["setup", "--native-port", "5434"],
        ["setup", "--docker-port", "5433"],
        ["daemon", "status", "--route", "native"],
        ["daemon", "start", "--route", "both"],
        ["daemon", "stop", "--docker-port", "5433"],
    ],
)
def test_obsolete_route_and_port_flags_exit_2(obsolete_argv: list[str]):
    """Stage A: Obsolete route/port flags are removed and rejected by argparse with exit code 2."""
    parser = runtime_cli.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(obsolete_argv)
    assert exc_info.value.code == 2


def test_compose_project_name_uses_12_hex_sha256_of_canonical_workdir(tmp_path: Path, monkeypatch):
    """Stage A (PR23-R4I-SCRIPT-001): Compose project identity is 'patchdiff-' + 12 hex SHA-256 of resolved workdir."""
    monkeypatch.delenv("PATCHDIFF_COMPOSE_PROJECT", raising=False)
    workdir = tmp_path / "workspace"
    workdir.mkdir(mode=0o700)
    expected_digest = hashlib.sha256(str(workdir.resolve()).encode("utf-8")).hexdigest()[:12]
    assert runtime_cli.get_compose_project_name(workdir) == f"patchdiff-{expected_digest}"


def test_foreign_and_same_workdir_different_project_containers_never_removed_or_stopped(tmp_path: Path):
    """Stage A (PR23-R4I-SCRIPT-001): Both foreign workdir and same-workdir/different-project fail closed with zero docker rm/stop."""
    checkout_a = tmp_path / "checkout_a"
    checkout_b = tmp_path / "checkout_b"
    checkout_a.mkdir(mode=0o700)
    checkout_b.mkdir(mode=0o700)
    (checkout_b / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres:16.3-alpine\n",
        encoding="utf-8",
    )

    # Case 1: Foreign working_dir occupying port 5433
    foreign_inspect = {
        "Name": "/patchdiff-postgres",
        "State": {"Running": True, "Status": "running"},
        "Config": {
            "Labels": {
                "com.docker.compose.project": "patchdiff-foreign12345",
                "com.docker.compose.project.working_dir": str(checkout_a.resolve()),
            }
        },
        "HostConfig": {
            "PortBindings": {
                "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5433"}]
            }
        },
    }

    # Case 2: Same working_dir (`checkout_b`) but DIFFERENT project label (e.g. legacy 10-hex or custom project)
    same_workdir_diff_project_inspect = {
        "Name": "/patchdiff-legacy-postgres",
        "State": {"Running": True, "Status": "running"},
        "Config": {
            "Labels": {
                "com.docker.compose.project": "patchdiff-legacy10hx",
                "com.docker.compose.project.working_dir": str(checkout_b.resolve()),
            }
        },
        "HostConfig": {
            "PortBindings": {
                "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5433"}]
            }
        },
    }

    for inspect_payload, expected_err in (
        (foreign_inspect, "Foreign Docker container conflict"),
        (same_workdir_diff_project_inspect, "Docker Compose project conflict"),
    ):
        calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["docker", "ps"]:
                return MagicMock(returncode=0, stdout="container-1\n", stderr="")
            if cmd[:2] == ["docker", "inspect"]:
                return MagicMock(returncode=0, stdout=json.dumps([inspect_payload]), stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("app.mcp.runtime_cli.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match=expected_err):
                runtime_cli.docker_daemon("start", port=5433, repo_root=checkout_b, runtime_dir=tmp_path / "rt")
            with pytest.raises(RuntimeError, match=expected_err):
                runtime_cli.docker_daemon("stop", port=5433, repo_root=checkout_b, runtime_dir=tmp_path / "rt")

        for c in calls:
            assert "rm" not in c, f"Forbidden docker rm call executed: {c}"
            assert "stop" not in c, f"Forbidden docker stop call executed: {c}"


def test_daemon_status_is_strictly_read_only_and_creates_no_credentials(tmp_path: Path):
    """Stage A: `daemon status` never generates credentials or starts containers."""
    runtime_dir = tmp_path / "readonly_rt"
    checkout = tmp_path / "checkout"
    checkout.mkdir(mode=0o700)
    (checkout / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres:16.3-alpine\n",
        encoding="utf-8",
    )

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["docker", "ps"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["docker", "inspect"]:
            return MagicMock(returncode=1, stdout="", stderr="not found")
        raise AssertionError(f"Unexpected subprocess call during status: {cmd}")

    with patch("app.mcp.runtime_cli.subprocess.run", side_effect=fake_run):
        res = runtime_cli.docker_daemon(
            "status",
            port=5433,
            repo_root=checkout,
            runtime_dir=runtime_dir,
        )

    assert res["status"] == "stopped"
    assert "database_url" not in res
    assert not (runtime_dir / "db_bootstrap_credentials.json").exists()
    assert not (runtime_dir / "db_host_credentials.json").exists()
    assert not (runtime_dir / "agent" / "db_agent_credentials.json").exists()


def test_separate_three_role_credential_files_and_redaction(tmp_path: Path):
    """Stage B (PR23-R4I-ARCH-001, PR23-R5-DEP-001): Three separate 0600 files, 3 distinct >=32-byte secrets, and full redaction."""
    for bad_pw in ("patchdiff", "postgres", "password", "short", ""):
        with pytest.raises(ValueError, match="Rejected|at least 32"):
            runtime_cli.validate_credential_secret(bad_pw)

    rt_dir = tmp_path / "operator_rt"
    creds = runtime_cli.ensure_runtime_credentials(rt_dir, port=5433)

    assert creds["bootstrap_user"] == "patchdiff_bootstrap"
    assert creds["host_user"] == "patchdiff_host"
    assert creds["agent_user"] == "patchdiff_agent"

    pw_boot = creds["bootstrap_password"]
    pw_host = creds["host_password"]
    pw_agent = creds["agent_password"]
    assert len({pw_boot, pw_host, pw_agent}) == 3
    for pw in (pw_boot, pw_host, pw_agent):
        assert len(pw) >= 32

    boot_file = Path(creds["bootstrap_credentials_file"])
    host_file = Path(creds["host_credentials_file"])
    agent_file = Path(creds["agent_credentials_file"])
    for fpath in (boot_file, host_file, agent_file):
        assert fpath.is_file()
        assert stat.S_IMODE(fpath.stat().st_mode) == 0o600

    # Agent secret file must NEVER contain bootstrap or host passwords
    agent_raw = agent_file.read_text(encoding="utf-8")
    assert pw_boot not in agent_raw
    assert pw_host not in agent_raw
    assert "patchdiff_bootstrap" not in agent_raw
    assert "patchdiff_host" not in agent_raw

    # Reloading returns identical secrets without rotating
    creds2 = runtime_cli.ensure_runtime_credentials(rt_dir, port=5433)
    assert creds2 == creds

    # Redaction strips raw and URL-encoded forms of all 3 secrets
    raw_msg = (
        f"dsn1=postgresql+psycopg://patchdiff_bootstrap:{quote(pw_boot, safe='')}@127.0.0.1:5433/patchdiff "
        f"dsn2=postgresql+psycopg://patchdiff_host:{pw_host}@127.0.0.1:5433/patchdiff "
        f"agent_pw={pw_agent}"
    )
    redacted = core_config.redact_sensitive_text(raw_msg, extra_secrets=(pw_boot, pw_host, pw_agent))
    for pw in (pw_boot, pw_host, pw_agent):
        assert pw not in redacted
        assert quote(pw, safe="") not in redacted


def test_stage_b_mcp_startup_role_and_principal_enforcement(monkeypatch):
    """Stage B (PR23-R5-ARCH-001, PR23-PLAN-MCP-003): Reject bootstrap role, role/profile mismatch, and model/agent UID violations."""
    # 1. Bootstrap role is forbidden in all MCP profiles
    monkeypatch.setenv("PATCHDIFF_DB_ROLE", "patchdiff_bootstrap")
    with pytest.raises(PermissionError, match="forbidden"):
        core_config.resolve_mcp_profile_and_validate_startup("observed_v2")
    with pytest.raises(PermissionError, match="forbidden"):
        core_config.resolve_mcp_profile_and_validate_startup("full")

    # 2. Editing profile must never select patchdiff_host
    monkeypatch.setenv("PATCHDIFF_DB_ROLE", "patchdiff_host")
    with pytest.raises(PermissionError, match="Editing profile"):
        core_config.resolve_mcp_profile_and_validate_startup("observed_v2")

    # 3. Full profile must never select patchdiff_agent
    monkeypatch.setenv("PATCHDIFF_DB_ROLE", "patchdiff_agent")
    with pytest.raises(PermissionError, match="requires 'patchdiff_host'"):
        core_config.resolve_mcp_profile_and_validate_startup("full")
    monkeypatch.delenv("PATCHDIFF_DB_ROLE", raising=False)

    # 4. Untrusted model principal `patchdiff-model` is rejected on setup, daemon, and mcp
    with patch("app.core.config._get_effective_os_username", return_value="patchdiff-model"):
        for op in ("setup", "daemon", "mcp"):
            with pytest.raises(PermissionError, match="Untrusted model/sandbox OS principal"):
                core_config.enforce_os_principal_for_operation(op, profile="observed_v2")

    # 5. Unprivileged service principal `patchdiff-mcp-agent` cannot run setup, daemon, or full profile
    with patch("app.core.config._get_effective_os_username", return_value="patchdiff-mcp-agent"):
        for op in ("setup", "daemon"):
            with pytest.raises(PermissionError, match="Unprivileged editor service principal"):
                core_config.enforce_os_principal_for_operation(op)
        with pytest.raises(PermissionError, match="prohibited from starting PATCHDIFF_MCP_PROFILE='full'"):
            core_config.enforce_os_principal_for_operation("mcp", profile="full")


def test_external_database_mode_invokes_zero_docker_or_native_subprocesses(tmp_path: Path, monkeypatch):
    """Stage A: --external-database validates 3 role DSNs, runs zero docker/initdb/pg_ctl calls, and migrates via bootstrap DSN."""
    boot_url = "postgresql+psycopg://patchdiff_bootstrap:BootSecret_0123456789abcdef0123456789@127.0.0.1:5433/patchdiff"
    host_url = "postgresql+psycopg://patchdiff_host:HostSecret_0123456789abcdef0123456789@127.0.0.1:5433/patchdiff"
    agent_url = "postgresql+psycopg://patchdiff_agent:AgentSecret_0123456789abcdef0123456789@127.0.0.1:5433/patchdiff"

    monkeypatch.setenv("PATCHDIFF_BOOTSTRAP_DATABASE_URL", boot_url)
    monkeypatch.setenv("PATCHDIFF_HOST_DATABASE_URL", host_url)
    monkeypatch.setenv("PATCHDIFF_AGENT_DATABASE_URL", agent_url)

    subproc_calls: list[list[str]] = []

    def forbidden_subproc(cmd, *args, **kwargs):
        subproc_calls.append(list(cmd))
        raise AssertionError(f"Subprocess call forbidden in external database mode: {cmd}")

    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn

    def fake_execute(query, *args, **kwargs):
        res = MagicMock()
        if "server_version_num" in str(query):
            res.fetchone.return_value = ("160003",)
        elif "SELECT current_user" in str(query):
            res.fetchone.return_value = ("patchdiff_bootstrap",)
        return res

    fake_conn.execute.side_effect = fake_execute

    with (
        patch("app.mcp.runtime_cli.subprocess.run", side_effect=forbidden_subproc),
        patch("app.mcp.runtime_cli.psycopg.connect", return_value=fake_conn),
        patch("app.mcp.runtime_cli.run_alembic_upgrade", return_value="20261101_0008"),
        patch("app.mcp.runtime_cli.verify_role_connections"),
        patch("app.mcp.runtime_cli.smoke_test_mcp_adapter", return_value={"observed_v2": 5, "full": 24}),
        patch("app.waymark_bridge.bootstrap.verify_installed_bridge", return_value="0.1.0"),
    ):
        res = runtime_cli.run_setup_command(
            external_database=True,
            runtime_dir=tmp_path / "rt",
        )

    assert subproc_calls == []
    assert res["mode"] == "external_database"
    assert res["status"] == "ready"
    serialized = json.dumps(res)
    assert "BootSecret_" not in serialized
    assert "HostSecret_" not in serialized
    assert "AgentSecret_" not in serialized
    assert "database_url" not in res


def test_stage_e_atomic_write_json_0600_rejects_bak_symlink_hardlink_and_malformed_json(
    tmp_path: Path, monkeypatch
):
    """Stage E (PR23-R5-SCRIPT-001): Safe .bak handling without O_TRUNC; rejects symlinks, hardlinks, malformed JSON, and dir fsync failure."""
    rt_dir = tmp_path / "rt"
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(mode=0o700)
    cfg_path = cfg_dir / "mcp_config.json"

    # 1. Malformed JSON fails closed before touching anything or creating .bak
    malformed = '{"mcpServers": {"other": 123}, BROKEN'
    cfg_path.write_text(malformed, encoding="utf-8")
    os.chmod(cfg_path, 0o600)

    with pytest.raises(ValueError, match="malformed JSON"):
        runtime_cli.update_host_mcp_config(
            cfg_path,
            port=5433,
            runtime_dir=rt_dir,
        )
    assert cfg_path.read_text(encoding="utf-8") == malformed
    assert not (cfg_dir / "mcp_config.json.bak").exists()

    # Write valid initial config
    valid_initial = {"mcpServers": {"existing": {"command": "/bin/true"}}, "keep": 1}
    cfg_path.write_text(json.dumps(valid_initial), encoding="utf-8")
    os.chmod(cfg_path, 0o600)

    # 2. Planted .bak symlink to a sentinel file -> rejected, sentinel untouched!
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("SENTINEL_UNTOUCHED", encoding="utf-8")
    bak_path = cfg_dir / "mcp_config.json.bak"
    bak_path.symlink_to(sentinel)

    with pytest.raises(PermissionError, match="symlink"):
        runtime_cli.update_host_mcp_config(
            cfg_path,
            port=5433,
            runtime_dir=rt_dir,
        )
    assert sentinel.read_text(encoding="utf-8") == "SENTINEL_UNTOUCHED"
    assert json.loads(cfg_path.read_text(encoding="utf-8")) == valid_initial
    bak_path.unlink()

    # 3. Hardlinked .bak (st_nlink > 1) -> rejected, hardlink target untouched!
    hardlink_target = tmp_path / "hardlinked_victim.txt"
    hardlink_target.write_text("HARDLINK_UNTOUCHED", encoding="utf-8")
    os.chmod(hardlink_target, 0o600)
    os.link(hardlink_target, bak_path)

    try:
        with pytest.raises(PermissionError, match="hardlinked"):
            runtime_cli.update_host_mcp_config(
                cfg_path,
                port=5433,
                runtime_dir=rt_dir,
            )
        assert hardlink_target.read_text(encoding="utf-8") == "HARDLINK_UNTOUCHED"
        assert json.loads(cfg_path.read_text(encoding="utf-8")) == valid_initial
    finally:
        bak_path.unlink(missing_ok=True)

    # 4. Successful update creates 0600 .bak with original content and 0600 updated config without inline secrets
    written_path = runtime_cli.update_host_mcp_config(
        cfg_path,
        port=5433,
        runtime_dir=rt_dir,
    )
    assert written_path == cfg_path.resolve()
    assert bak_path.is_file()
    assert stat.S_IMODE(bak_path.stat().st_mode) == 0o600
    assert json.loads(bak_path.read_text(encoding="utf-8")) == valid_initial

    updated_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert updated_cfg["keep"] == 1
    assert updated_cfg["mcpServers"]["existing"] == {"command": "/bin/true"}
    pd_entry = updated_cfg["mcpServers"]["patchdiff"]
    # Host MCP config must NOT inline database passwords or PATCHDIFF_DATABASE_URL
    assert "PATCHDIFF_DATABASE_URL" not in pd_entry.get("env", {})

    # 5. Post-rename directory fsync failure raises ConfigDurabilityUncertainError
    real_fsync = os.fsync

    def fail_dir_fsync(fd: int):
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            raise OSError("Simulated parent directory fsync error")
        return real_fsync(fd)

    monkeypatch.setattr(runtime_cli.os, "fsync", fail_dir_fsync)
    with pytest.raises(runtime_cli.ConfigDurabilityUncertainError) as exc_info:
        runtime_cli.update_host_mcp_config(
            cfg_path,
            port=5433,
            runtime_dir=rt_dir,
        )
    assert exc_info.value.status == "durability_uncertain"
    assert exc_info.value.installed is True


def test_credential_reader_rejects_symlinked_ancestor(tmp_path):
    real = tmp_path / "real"
    private = real / "private"
    private.mkdir(parents=True, mode=0o700)
    secret = private / "host.json"
    secret.write_text(json.dumps(dict(role="patchdiff_host", username="patchdiff_host",
        password="a-high-entropy-test-only-secret-" + "7f9b"*8)))
    secret.chmod(0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(PermissionError, match="symlink"):
        core_config.load_role_credential_file(alias / "private/host.json",expected_role="patchdiff_host")
    assert core_config.load_role_credential_file(secret,expected_role="patchdiff_host")["username"] == "patchdiff_host"


def test_three_uid_checks_cannot_be_disabled_by_environment(monkeypatch):
    monkeypatch.setenv("PATCHDIFF_ENFORCE_THREE_UIDS", "0")
    monkeypatch.setattr(core_config, "_lookup_passwd", lambda _: None)
    monkeypatch.setattr(core_config, "_get_effective_os_username", lambda: "operator")
    with pytest.raises(PermissionError, match="Three-UID POSIX separation is missing"):
        core_config.resolve_mcp_profile_and_validate_startup("observed_v2")
