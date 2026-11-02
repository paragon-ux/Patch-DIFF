"""Installed-artifact acceptance driver, copied into a disposable Linux UID fixture.

This file is test code, never packaged in the wheel. Run as the fixture operator.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import uuid
import zipfile


def main():
    config = json.load(sys.stdin)
    from app.core.config import resolve_database_url
    from app.mcp.runtime_cli import (
        ensure_runtime_credentials, build_database_url, _provision_roles_and_database,
        run_alembic_upgrade,
    )
    from app.storage.db import get_engine
    from sqlalchemy import text

    for name in ("patchdiff-mcp-agent", "patchdiff-model"):
        try:
            pwd.getpwnam(name)
        except KeyError:
            subprocess.run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", name], check=True)
    operator = Path("/operator")
    operator.mkdir(mode=0o700, exist_ok=True)
    os.environ["PATCHDIFF_RUNTIME_DIR"] = str(operator / "runtime")
    os.environ["PATCHDIFF_BOOTSTRAP_DB_PASSWORD"] = config["bootstrap_password"]
    creds = ensure_runtime_credentials(port=5432, host=config["db_host"])
    _provision_roles_and_database(5432, creds, host=config["db_host"])
    boot_url = build_database_url(5432, role="bootstrap", creds=creds, host=config["db_host"])
    assert run_alembic_upgrade(boot_url) == "20261101_0008"
    # Bootstrap password was fixed by the independent Compose instance.
    host_url = build_database_url(5432, role="host", creds=creds, host=config["db_host"])
    os.environ["PATCHDIFF_HOST_DATABASE_URL"] = host_url

    python = sys.executable
    entrypoint = str(Path(python).parent / "patchdiff-mcp")
    wheel_sha256 = hashlib.sha256(Path(config["wheel"]).read_bytes()).hexdigest()
    assert wheel_sha256 == config["wheel_sha256"]
    agent = pwd.getpwnam("patchdiff-mcp-agent")
    model = pwd.getpwnam("patchdiff-model")
    secret_paths = [creds[k] for k in ("bootstrap_credentials_file", "host_credentials_file", "agent_credentials_file")]
    for uid, denied_paths in ((model.pw_uid, secret_paths), (agent.pw_uid, secret_paths[:2])):
        check = subprocess.run([python, "-c",
            "import os,sys; from pathlib import Path; "
            "assert all(not os.access(p, os.R_OK) for p in sys.argv[1:]); "
            "assert not os.access('/var/run/docker.sock',os.R_OK|os.W_OK)", *denied_paths],
            user=uid, group=model.pw_gid if uid == model.pw_uid else agent.pw_gid, extra_groups=[],
            cwd="/tmp", env={"PATH":os.environ["PATH"]}, capture_output=True, text=True)
        assert check.returncode == 0, check.stderr
        for forged_profile in ("full",):
            denied = subprocess.run([entrypoint], user=uid,
                group=model.pw_gid if uid == model.pw_uid else agent.pw_gid, extra_groups=[],
                cwd="/tmp", env={"PATH":os.environ["PATH"], "PATCHDIFF_MCP_PROFILE":forged_profile,
                "PATCHDIFF_DATABASE_URL":host_url}, input="", capture_output=True, text=True)
            assert denied.returncode != 0 and not denied.stdout
    # The model cannot use the trusted launch path to impersonate the service.
    denied = subprocess.run(["sudo", "-n", "-u", "patchdiff-mcp-agent", "--", entrypoint],
        user=model.pw_uid, group=model.pw_gid, extra_groups=[], cwd="/tmp",
        env={"PATH":os.environ["PATH"]}, input="", capture_output=True, text=True)
    assert denied.returncode != 0

    host_env = {"PATH":os.environ["PATH"], "PATCHDIFF_MCP_PROFILE":"full",
                "PATCHDIFF_RUNTIME_DIR":str(operator / "runtime"), "PGAPPNAME":"pr23-wheel-host"}
    # No profile or DSN in editor environment. Its default secret is service-owned.
    editor_env = {"PATH":os.environ["PATH"], "PGAPPNAME":"pr23-wheel-editor"}
    host = subprocess.Popen([entrypoint], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd="/tmp", env=host_env)
    editor = subprocess.Popen(["sudo", "-n", "-u", "patchdiff-mcp-agent", "--", entrypoint],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, cwd="/tmp", env=editor_env)
    sequence = 0
    def rpc(process, method, params=None):
        nonlocal sequence
        sequence += 1
        process.stdin.write(json.dumps(dict(jsonrpc="2.0", id=sequence, method=method, params=params or {}))+"\n")
        process.stdin.flush()
        line = process.stdout.readline()
        assert line, process.stderr.read()
        result = json.loads(line)
        assert result["id"] == sequence and "error" not in result, result
        return result["result"]
    def tool(process, name, args):
        result = rpc(process, "tools/call", {"name":name,"arguments":args})
        assert not result.get("isError"), result
        return json.loads(result["content"][0]["text"])
    try:
        assert len(rpc(editor,"tools/list")["tools"]) == 5
        assert len(rpc(host,"tools/list")["tools"]) == 24
        assert rpc(editor,"tools/call",{"name":"patchdiff_finalize_target","arguments":{}})["isError"]
        original = "def multiply(a, b):\n    return a * b\n"
        replacement = "return a * b + 1\n" + "# filler\n" * 150000
        initial = tool(host,"patchdiff_initialize_target",dict(filename="wheel.py",content=original,content_type="text/x-python"))
        target = initial["target_file_id"]
        discovered = tool(editor,"patchdiff_list_scopes",dict(target_file_id=target))
        assert any(c["name"] == "multiply" for c in discovered["candidates"])
        observed = tool(editor,"patchdiff_observe_scopes",dict(target_file_id=target,selections=[dict(symbol_name="multiply")]))
        request = dict(snapshot=observed["snapshot"], intent="Verify installed wheel guarded editing",
            client_request_id=str(uuid.uuid4()), groups=[dict(observation_id=observed["scopes"][0]["observation_id"],
                operations=[dict(op="match",match="return a * b",replace=replacement)])])
        accepted = tool(editor,"patchdiff_commit_bundle",request)
        assert accepted["status"] == "accepted"
        recovered = tool(editor,"patchdiff_commit_bundle",request)["transaction"]
        assert recovered["deduplicated"] is True
        assert {k:v for k,v in recovered.items() if k != "deduplicated"} == {
            k:v for k,v in accepted["transaction"].items() if k != "deduplicated"}
        fin_args = dict(target_file_id=target,expected_target_version=1,client_request_id=str(uuid.uuid4()),format="canonical_lf")
        final = tool(host,"patchdiff_finalize_target",fin_args)
        assert final["status"] == "ok" and final["content_delivery"] == "deferred"
        assert all(final["materialized_state_checks"].values())
        again = tool(host,"patchdiff_finalize_target",fin_args)
        assert again["finalization_id"] == final["finalization_id"] and again["is_idempotent_replay"]
        replay = tool(host,"patchdiff_replay",dict(target_file_id=target))
        assert replay["materialized_state_matches"]
        content = bytearray()
        offset = 0
        while True:
            page = tool(host,"patchdiff_read_finalized_export",dict(target_file_id=target,
                finalization_id=final["finalization_id"],offset=offset,limit=1048576))
            content.extend(base64.b64decode(page["content_base64"],validate=True))
            if not page["has_more"]: break
            offset = page["next_offset"]
        expected = original.replace("return a * b",replacement).encode()
        assert content == expected
        assert hashlib.sha256(content).hexdigest() == final["content_sha256"]
        sys.path.insert(0,"/harness")
        from host_finalize import safe_write_back_file
        destination = operator / "output.py"
        safe_write_back_file(destination,bytes(content),expected_sha256=final["content_sha256"],authorized_root=operator,
                             preimage_sha256=hashlib.sha256(destination.read_bytes()).hexdigest() if destination.exists() else None)
        assert destination.read_bytes() == expected
        for profile, role in (("full","patchdiff_host"),):
            url = resolve_database_url(profile=profile)
            import psycopg
            with psycopg.connect(url.replace("postgresql+psycopg://","postgresql://")) as connection:
                host_db_user = connection.execute("SELECT current_user").fetchone()[0]
                assert host_db_user == role
        role_check = subprocess.run(["sudo", "-n", "-u", "patchdiff-mcp-agent", "--", python, "-c",
            "from app.core.config import resolve_mcp_profile_and_validate_startup; "
            "resolve_mcp_profile_and_validate_startup(lock_process=True); "
            "from app.storage.db import get_engine; from sqlalchemy import text; "
            "c=get_engine().connect(); print(c.execute(text('SELECT current_user')).scalar())"],
            cwd="/tmp", env={"PATH":os.environ["PATH"]}, capture_output=True,text=True,check=True)
        assert role_check.stdout.strip() == "patchdiff_agent"
        uvx = str(Path(python).parent / "uvx")
        uvx_wire = "\n".join(json.dumps(dict(jsonrpc="2.0", id=i, method=method, params={}))
                             for i,method in ((1,"initialize"),(2,"tools/list"))) + "\n"
        local_uvx = subprocess.run(["sudo","-n","-u","patchdiff-mcp-agent","--","env",
            "UV_CACHE_DIR=/var/lib/patchdiff-mcp-agent/uv-cache-"+uuid.uuid4().hex,
            "UV_TOOL_DIR=/var/lib/patchdiff-mcp-agent/uv-tools-"+uuid.uuid4().hex,
            "PATCHDIFF_WAYMARK_BRIDGE_DIR="+str(Path(__import__("app").__file__).parent/"waymark_bridge"),
            uvx,"--from",config["wheel"],"patchdiff"], cwd="/tmp", env={"PATH":os.environ["PATH"]},
            input=uvx_wire,capture_output=True,text=True)
        assert local_uvx.returncode == 0, local_uvx.stderr
        uvx_responses = [json.loads(line) for line in local_uvx.stdout.splitlines()]
        assert len(uvx_responses[-1]["result"]["tools"]) == 5
        import app
        from app.services.waymark_adapter import get_waymark_bridge_dir
        bridge = get_waymark_bridge_dir()
        assets = {name: {"path": str(bridge / name),
                         "sha256": hashlib.sha256((bridge / name).read_bytes()).hexdigest()}
                  for name in ("discover.mjs", "discovery_core.mjs", "worker.mjs", "package.json", "package-lock.json")}
        with zipfile.ZipFile(config["wheel"]) as artifact:
            for name, fact in assets.items():
                assert hashlib.sha256(artifact.read("app/waymark_bridge/" + name)).hexdigest() == fact["sha256"]
        result = dict(status="PASS",target_file_id=target,finalization_id=final["finalization_id"],
                      content_sha256=final["content_sha256"],content_bytes=len(content),
                      editor_uid=agent.pw_uid,model_uid=model.pw_uid,operator_uid=os.getuid(),
                      database_roles={"editor": role_check.stdout.strip(), "host": host_db_user},
                      wheel_sha256=wheel_sha256, app_file=app.__file__, sys_path=sys.path,
                      waymark_assets=assets,
                      waymark_engine_version=json.loads((bridge / "node_modules/waymark-engine/package.json").read_text())["version"],
                      node_version=subprocess.check_output(["node", "--version"],text=True).strip(),
                      pip_freeze=subprocess.check_output([python,"-m","pip","freeze"],text=True),
                      local_wheel_uvx="PASS")
        print(json.dumps(result))
    finally:
        for process in (editor,host):
            process.stdin.close()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate(); process.wait(timeout=5)

if __name__ == "__main__":
    main()
