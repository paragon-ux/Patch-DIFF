"""Live integration tests for Docker-only runtime CLI, two-project coexistence, external DB mode, and Stage B SQL least privilege."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from unittest.mock import patch
import uuid

import psycopg
import pytest

from app.core.hashing import canonical_sha256
from app.mcp import runtime_cli


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(autouse=True)
def _private_tmp_umask(tmp_path: Path):
    old_umask = os.umask(0o077)
    os.chmod(tmp_path, 0o700)
    try:
        yield
    finally:
        os.umask(old_umask)


def test_two_independent_docker_compose_deployments_coexist_and_preserve_volumes(tmp_path: Path, monkeypatch):
    """Stage A (PR23-R5-ARCH-002, PR23-R4I-SCRIPT-001): Two scoped Compose checkouts coexist on separate ports and preserve volumes."""
    monkeypatch.delenv("PATCHDIFF_COMPOSE_PROJECT", raising=False)
    repo_root = Path(__file__).resolve().parents[3]
    compose_src = repo_root / "docker-compose.yml"

    checkout_a = tmp_path / "checkout_a"
    checkout_b = tmp_path / "checkout_b"
    rt_a = tmp_path / "rt_a"
    rt_b = tmp_path / "rt_b"
    checkout_a.mkdir(mode=0o700)
    checkout_b.mkdir(mode=0o700)
    shutil.copy2(compose_src, checkout_a / "docker-compose.yml")
    shutil.copy2(compose_src, checkout_b / "docker-compose.yml")

    port_a = _pick_free_port()
    port_b = _pick_free_port()
    while port_b == port_a:
        port_b = _pick_free_port()

    proj_a = runtime_cli.get_compose_project_name(checkout_a)
    proj_b = runtime_cli.get_compose_project_name(checkout_b)
    assert proj_a != proj_b
    assert len(proj_a) == len("patchdiff-") + 12
    assert len(proj_b) == len("patchdiff-") + 12

    try:
        # 1. Read-only status before start creates zero credential files and zero containers
        st_a0 = runtime_cli.docker_daemon("status", port=port_a, repo_root=checkout_a, runtime_dir=rt_a)
        assert st_a0["status"] == "stopped"
        assert not (rt_a / "db_bootstrap_credentials.json").exists()

        # 2. Start both independent Compose deployments concurrently
        start_a = runtime_cli.docker_daemon("start", port=port_a, repo_root=checkout_a, runtime_dir=rt_a)
        start_b = runtime_cli.docker_daemon("start", port=port_b, repo_root=checkout_b, runtime_dir=rt_b)
        assert start_a["status"] == "running" and start_a["db_ready"] is True
        assert start_b["status"] == "running" and start_b["db_ready"] is True
        assert "database_url" not in start_a and "database_url" not in start_b

        # 3. Verify SCRAM-SHA-256 rejects known default passwords
        for bad_dsn in (
            f"postgresql://patchdiff:patchdiff@127.0.0.1:{port_a}/patchdiff",
            f"postgresql://patchdiff_bootstrap:patchdiff@127.0.0.1:{port_a}/patchdiff",
            f"postgresql://patchdiff_admin:patchdiff@127.0.0.1:{port_a}/patchdiff",
        ):
            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(bad_dsn, connect_timeout=2).close()

        # 4. Run Alembic upgrade on deployment A and test external-database setup against deployment B
        creds_a = runtime_cli.ensure_runtime_credentials(rt_a, port=port_a)
        boot_url_a = runtime_cli.build_database_url(port_a, role="bootstrap", runtime_dir=rt_a, creds=creds_a)
        rev_a = runtime_cli.run_alembic_upgrade(boot_url_a, runtime_dir=rt_a, creds=creds_a)
        assert rev_a == "20261101_0008"

        creds_b = runtime_cli.ensure_runtime_credentials(rt_b, port=port_b)
        boot_url_b = runtime_cli.build_database_url(port_b, role="bootstrap", runtime_dir=rt_b, creds=creds_b)
        host_url_b = runtime_cli.build_database_url(port_b, role="host", runtime_dir=rt_b, creds=creds_b)
        agent_url_b = runtime_cli.build_database_url(port_b, role="agent", runtime_dir=rt_b, creds=creds_b)

        monkeypatch.setenv("PATCHDIFF_BOOTSTRAP_DATABASE_URL", boot_url_b)
        monkeypatch.setenv("PATCHDIFF_HOST_DATABASE_URL", host_url_b)
        monkeypatch.setenv("PATCHDIFF_AGENT_DATABASE_URL", agent_url_b)

        # In --external-database mode, zero docker or native subprocesses may be invoked
        real_run = subprocess.run

        def guard_no_docker_or_native(cmd, *args, **kwargs):
            first = str(cmd[0]) if cmd else ""
            assert "docker" not in first and "initdb" not in first and "pg_ctl" not in first, (
                f"Forbidden subprocess in --external-database mode: {cmd}"
            )
            return real_run(cmd, *args, **kwargs)

        with patch("app.mcp.runtime_cli.subprocess.run", side_effect=guard_no_docker_or_native):
            ext_res = runtime_cli.run_setup_command(
                external_database=True,
                runtime_dir=tmp_path / "ext_rt",
            )
        assert ext_res["mode"] == "external_database"
        assert ext_res["status"] == "ready"
        assert ext_res["alembic_revision"] == "20261101_0008"
        assert ext_res["mcp_smoke_tools"] == {"observed_v2": 5, "full": 24}

        # 5. Stopping deployment A leaves deployment B running and preserves both named volumes
        stop_a = runtime_cli.docker_daemon("stop", port=port_a, repo_root=checkout_a, runtime_dir=rt_a)
        assert stop_a["status"] == "stopped"
        st_b = runtime_cli.docker_daemon("status", port=port_b, repo_root=checkout_b, runtime_dir=rt_b)
        assert st_b["status"] == "running" and st_b["db_ready"] is True

        vols = subprocess.run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert any(proj_a in v for v in vols), f"Volume for {proj_a} was not preserved"
        assert any(proj_b in v for v in vols), f"Volume for {proj_b} was not preserved"
    finally:
        for port, root, rt in ((port_a, checkout_a, rt_a), (port_b, checkout_b, rt_b)):
            try:
                runtime_cli.docker_daemon("stop", port=port, repo_root=root, runtime_dir=rt)
            except Exception:
                pass


def test_stage_b_live_sql_privilege_matrix_and_immutability_triggers():
    """Stage B & C (PR23-R5-DB-001, PR23-PLAN-MCP-003): Direct SQL negative tests for patchdiff_agent and patchdiff_host."""
    creds = runtime_cli.ensure_runtime_credentials()
    port = int(json.loads(Path(creds["bootstrap_credentials_file"]).read_text())["port"])
    boot_dsn = runtime_cli.build_psycopg_dsn(port=port, role="bootstrap", creds=creds, dbname=creds["dbname"])
    host_dsn = runtime_cli.build_psycopg_dsn(port=port, role="host", creds=creds, dbname=creds["dbname"])
    agent_dsn = runtime_cli.build_psycopg_dsn(port=port, role="agent", creds=creds, dbname=creds["dbname"])

    project_id = uuid.uuid4()
    target_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    new_cycle_id = uuid.uuid4()
    snap_id = uuid.uuid4()
    log_id = uuid.uuid4()
    manifest_id = uuid.uuid4()
    obs_id = uuid.uuid4()
    fin_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    init_hash = canonical_sha256("hello\n")
    after_hash = canonical_sha256("world\n")

    # 1. Seed a target, cycle, snapshot, finalization, and export chunk as patchdiff_host
    with psycopg.connect(host_dsn, autocommit=True) as host_conn:
        cur_role, is_super = host_conn.execute(
            "SELECT current_user, usesuper FROM pg_user WHERE usename = current_user"
        ).fetchone()
        assert cur_role == "patchdiff_host" and is_super is False

        with host_conn.transaction():
            host_conn.execute(
                "INSERT INTO projects (project_id, name) VALUES (%s, %s)",
                (project_id, "sql-priv-test"),
            )
            host_conn.execute(
                """
                INSERT INTO cloud_target_files (
                    target_file_id, project_id, filename, target_type,
                    current_content, current_hash, version, history_revision, active_editing_cycle_id
                ) VALUES (%s, %s, 'priv.txt', 'text/plain', 'hello\n', %s, 0, 0, %s)
                """,
                (target_id, project_id, init_hash, new_cycle_id),
            )
            host_conn.execute(
                "INSERT INTO editing_cycles (editing_cycle_id, target_file_id, cycle_index, status) VALUES (%s, %s, 0, 'closed')",
                (cycle_id, target_id),
            )
            host_conn.execute(
                "INSERT INTO editing_cycles (editing_cycle_id, target_file_id, cycle_index, status) VALUES (%s, %s, 1, 'active')",
                (new_cycle_id, target_id),
            )
            host_conn.execute(
                """
                INSERT INTO target_snapshots (
                    snapshot_id, target_file_id, editing_cycle_id, content, content_hash, version, snapshot_reason
                ) VALUES (%s, %s, %s, 'hello\n', %s, 0, 'initial_upload')
                """,
                (snap_id, target_id, cycle_id, init_hash),
            )
            host_conn.execute(
                """
                INSERT INTO target_finalizations (
                    finalization_id, target_file_id, client_request_id, fingerprint_version,
                    request_fingerprint, status, snapshot_id, closed_editing_cycle_id,
                    new_editing_cycle_id, saved_target_version, canonical_current_hash,
                    content_sha256, content_bytes, export_format, materialized_state_checks
                ) VALUES (
                    %s, %s, 'req-priv-1', 1, 'fp-priv-1', 'completed', %s, %s, %s, 0, %s, %s, 6, 'canonical_lf',
                    '{"content_matches": true, "stored_hash_matches": true, "recomputed_hash_matches": true, "version_matches": true}'::jsonb
                )
                """,
                (fin_id, target_id, snap_id, cycle_id, new_cycle_id, init_hash, init_hash),
            )
            host_conn.execute(
                """
                INSERT INTO target_finalization_export_chunks (
                    finalization_id, chunk_index, payload, payload_sha256, byte_length
                ) VALUES (%s, 0, %s, %s, 6)
                """,
                (fin_id, b"hello\n", init_hash),
            )

        # Host is DENIED DDL and DENIED history_revision column update
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            host_conn.execute("CREATE TABLE host_forbidden_ddl (id int)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            host_conn.execute(
                "UPDATE cloud_target_files SET history_revision = 99 WHERE target_file_id = %s",
                (target_id,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            host_conn.execute("SELECT version_num FROM alembic_version")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            host_conn.execute("UPDATE target_finalizations SET content_bytes = 0 WHERE finalization_id = %s", (fin_id,))

    # 2. Verify patchdiff_agent allowlisted DML and strict negative SQL denials
    with psycopg.connect(agent_dsn, autocommit=True) as agent_conn:
        cur_role, is_super = agent_conn.execute(
            "SELECT current_user, usesuper FROM pg_user WHERE usename = current_user"
        ).fetchone()
        assert cur_role == "patchdiff_agent" and is_super is False

        # Agent is DENIED access to target_finalizations, target_finalization_export_chunks, alembic_version, and DDL
        for forbidden_sql in (
            "SELECT count(*) FROM target_finalizations",
            "SELECT count(*) FROM target_finalization_export_chunks",
            "SELECT version_num FROM alembic_version",
            "CREATE TABLE agent_forbidden_ddl (id int)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                agent_conn.execute(forbidden_sql)

        # Agent is DENIED INSERT on target_snapshots and editing_cycles
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent_conn.execute(
                """
                INSERT INTO target_snapshots (
                    snapshot_id, target_file_id, editing_cycle_id, content, content_hash, version, snapshot_reason
                ) VALUES (%s, %s, %s, 'rogue', %s, 0, 'save')
                """,
                (uuid.uuid4(), target_id, cycle_id, init_hash),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent_conn.execute(
                "INSERT INTO editing_cycles (editing_cycle_id, target_file_id, cycle_index, status) VALUES (%s, %s, 1, 'active')",
                (uuid.uuid4(), target_id),
            )

        # Agent is DENIED UPDATE on active_editing_cycle_id and history_revision on cloud_target_files
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent_conn.execute(
                "UPDATE cloud_target_files SET active_editing_cycle_id = %s WHERE target_file_id = %s",
                (uuid.uuid4(), target_id),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent_conn.execute(
                "UPDATE cloud_target_files SET history_revision = 42 WHERE target_file_id = %s",
                (target_id,),
            )

        # Agent CAN insert scope observation and accepted log, which automatically increments history_revision via trigger!
        agent_conn.execute(
            """
            INSERT INTO target_scope_observations (
                observation_id, target_file_id, editing_cycle_id, target_version,
                target_current_hash, waymark_engine_version, language, symbol_name, symbol_kind,
                start_line, start_column, end_line, end_column, scope_start, scope_end, observed_scope_hash
            ) VALUES (%s, %s, %s, 0, %s, '0.1.0', 'text', 'hello', 'section', 1, 1, 1, 6, 0, 6, %s)
            """,
            (obs_id, target_id, new_cycle_id, init_hash, init_hash),
        )
        agent_conn.execute(
            """
            INSERT INTO append_only_pdcp_logs (
                pdcp_log_id, target_file_id, editing_cycle_id, submission_source,
                protocol_version, runtime_version, pdcp_content, pdcp_content_hash,
                status, change_count, before_version, after_version, before_hash, after_hash
            ) VALUES (%s, %s, %s, 'agent_test', 'patchdiff-tx/1', 'patchdiff-mvp-0.2.2', '{}', %s, 'accepted', 1, 0, 1, %s, %s)
            """,
            (log_id, target_id, new_cycle_id, init_hash, init_hash, after_hash),
        )
        agent_conn.execute(
            """
            INSERT INTO append_only_manifest_ledger (
                manifest_entry_id, target_file_id, editing_cycle_id, pdcp_log_id,
                change_index, change_id, origin, intent
            ) VALUES (%s, %s, %s, %s, 1, 'chg_1', 'typed', 'test')
            """,
            (manifest_id, target_id, new_cycle_id, log_id),
        )

        # Verify history_revision incremented to 1 on accepted log insert
        rev_after_log = agent_conn.execute(
            "SELECT history_revision FROM cloud_target_files WHERE target_file_id = %s",
            (target_id,),
        ).fetchone()[0]
        assert rev_after_log == 1

        # One-shot observation link: linking to non-existent/wrong log is rejected by trigger
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent_conn.execute(
                "UPDATE target_scope_observations SET accepted_pdcp_log_id = %s WHERE observation_id = %s",
                (uuid.uuid4(), obs_id),
            )

        # Valid one-shot transition NULL -> matching accepted log succeeds and increments history_revision to 2
        agent_conn.execute(
            "UPDATE target_scope_observations SET accepted_pdcp_log_id = %s WHERE observation_id = %s",
            (log_id, obs_id),
        )
        rev_after_obs = agent_conn.execute(
            "SELECT history_revision FROM cloud_target_files WHERE target_file_id = %s",
            (target_id,),
        ).fetchone()[0]
        assert rev_after_obs == 2

        # Pre-linked INSERT must not bypass the one-shot linkage/revision trigger.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent_conn.execute(
                """INSERT INTO target_scope_observations (
                    observation_id, target_file_id, editing_cycle_id, target_version,
                    target_current_hash, waymark_engine_version, language, symbol_name, symbol_kind,
                    start_line, start_column, end_line, end_column, scope_start, scope_end,
                    observed_scope_hash, accepted_pdcp_log_id
                ) VALUES (%s,%s,%s,0,%s,'0.1.0','text','injected','section',1,1,1,6,0,6,%s,%s)""",
                (uuid.uuid4(), target_id, new_cycle_id, init_hash, init_hash, log_id),
            )
        assert agent_conn.execute(
            "SELECT has_function_privilege(current_user, 'patchdiff_bump_target_history_revision()', 'EXECUTE')"
        ).fetchone()[0] is False
        assert agent_conn.execute(
            "SELECT has_function_privilege(current_user, 'patchdiff_lock_finalized_export(uuid)', 'EXECUTE')"
        ).fetchone()[0] is False

        # Second update to accepted_pdcp_log_id (once non-NULL) is rejected by immutability trigger!
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent_conn.execute(
                "UPDATE target_scope_observations SET accepted_pdcp_log_id = %s WHERE observation_id = %s",
                (log_id, obs_id),
            )

    # 3. Verify immutability triggers reject UPDATE/DELETE even for superuser patchdiff_bootstrap!
    with psycopg.connect(boot_dsn, autocommit=True) as boot_conn:
        for immutable_sql, params in (
            ("UPDATE append_only_pdcp_logs SET status = 'rejected' WHERE pdcp_log_id = %s", (log_id,)),
            ("DELETE FROM append_only_pdcp_logs WHERE pdcp_log_id = %s", (log_id,)),
            ("UPDATE append_only_manifest_ledger SET intent = 'tampered' WHERE manifest_entry_id = %s", (manifest_id,)),
            ("DELETE FROM append_only_manifest_ledger WHERE manifest_entry_id = %s", (manifest_id,)),
            ("UPDATE target_snapshots SET content = 'tampered' WHERE snapshot_id = %s", (snap_id,)),
            ("DELETE FROM target_snapshots WHERE snapshot_id = %s", (snap_id,)),
            ("UPDATE target_finalization_export_chunks SET payload = %s WHERE finalization_id = %s", (b"bad", fin_id)),
            ("DELETE FROM target_finalization_export_chunks WHERE finalization_id = %s", (fin_id,)),
            ("DELETE FROM target_scope_observations WHERE observation_id = %s", (obs_id,)),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                boot_conn.execute(immutable_sql, params)
