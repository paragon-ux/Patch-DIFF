"""Integration smoke test for built package wheel, MCP stdio server, and two-process lifecycle.

Verifies (PR23-R3-TEST-001):
1. Distributable wheel built and installed in isolated virtualenv outside repository checkout.
2. Console script entry point executable with zero repository source on sys.path.
3. Waymark JavaScript bridge and waymark-engine dependency provisioned and running via installed package.
4. Two distinct processes: trusted host (PATCHDIFF_MCP_PROFILE=full) and editor (default observed_v2).
5. Full lifecycle: target initialization, scope listing, scope observation, guarded bundle commit,
   host finalization with decoupled timing metrics, and immutable finalized-export paging against live PostgreSQL without repository PYTHONPATH.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import pytest


@pytest.fixture(scope="session")
def isolated_wheel_installation():
    """Install the current artifact with pip in a new venv; never borrow host packages."""
    import hashlib
    repo_root = Path(__file__).resolve().parents[3]
    outside = Path(tempfile.mkdtemp(prefix="pr23-wheel-"))
    dist_dir = outside / "dist"
    evidence_dir = Path(os.getenv("PATCHDIFF_TEST_EVIDENCE_DIR", str(outside)))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = outside / "provenance.json"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True)
    evidence = {
        "status": "FAIL", "phase": "build_or_install",
        "source_head": head.stdout.strip() if head.returncode == 0 else None,
        "source_files_sha256": {
            str(path.relative_to(repo_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (repo_root / "pyproject.toml", Path(__file__),
                         Path(__file__).with_name("test_adversarial_m4_wheel_smoke.py"),
                         Path(__file__).with_name("wheel_lifecycle_driver.py"))
        },
    }
    evidence_path.write_text(json.dumps(evidence, indent=2))
    shutil.copy2(evidence_path, evidence_dir / "wheel-provenance.json")
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in {"PYTHONPATH", "PATCHDIFF_WAYMARK_BRIDGE_DIR"}}
    supplied = os.getenv("PATCHDIFF_TEST_WHEEL_PATH")
    if supplied:
        wheel_path = Path(supplied).resolve(strict=True)
        dist_dir = wheel_path.parent
    else:
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--sdist",
                        "--outdir", str(dist_dir)], cwd=repo_root, env=clean_env, check=True,
                       capture_output=True, text=True)
        wheel_path, = dist_dir.glob("*.whl")
    evidence["artifacts"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in dist_dir.iterdir() if path.is_file() and path.name.endswith((".whl", ".tar.gz"))
    }
    evidence_path.write_text(json.dumps(evidence, indent=2))
    shutil.copy2(evidence_path, evidence_dir / "wheel-provenance.json")
    venv_dir = outside / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    python_bin = venv_dir / "bin/python"
    subprocess.run([str(python_bin), "-m", "pip", "install", "--no-cache-dir", str(wheel_path)],
                   cwd=outside, env=clean_env, check=True, capture_output=True, text=True)
    subprocess.run([str(python_bin), "-m", "pip", "check"], cwd=outside,
                   env=clean_env, check=True, capture_output=True, text=True)
    freeze = subprocess.check_output([str(python_bin), "-m", "pip", "freeze"],
                                     cwd=outside, env=clean_env, text=True)
    probe = json.loads(subprocess.check_output([str(python_bin), "-c",
        "import app,json,sys; from pathlib import Path; "
        "print(json.dumps(dict(app_file=app.__file__,sys_path=sys.path,"
        "bridge=str(Path(app.__file__).parent/'waymark_bridge'))))"],
        cwd=outside, env=clean_env, text=True))
    assert str(venv_dir) in probe["app_file"]
    assert all(str(repo_root) not in entry for entry in probe["sys_path"])
    assert not list(venv_dir.rglob("base-deps.pth"))
    from app.services.waymark_adapter import resolve_node_executable
    node_path = resolve_node_executable()
    bridge_dir = Path(probe["bridge"])
    bridge_env = {**clean_env, "PATH": f"{Path(node_path).parent}:{clean_env.get('PATH', '')}"}
    for extra in ([], ["--check-only"]):
        subprocess.run([str(python_bin), "-m", "app.waymark_bridge.bootstrap",
                        "--target-dir", str(bridge_dir), *extra], cwd=outside,
                       env=bridge_env, check=True, capture_output=True, text=True)
    asset_paths = [bridge_dir / name for name in (
        "discover.mjs", "discovery_core.mjs", "worker.mjs", "package.json", "package-lock.json",
        "node_modules/waymark-engine/package.json",
    )]
    evidence.update({**probe, "status": "PASS", "phase": "wheel_installation",
        "pip_check": "PASS", "pip_freeze": freeze,
        "node_version": subprocess.check_output([node_path, "--version"], text=True).strip(),
        "waymark_assets": {str(path.relative_to(bridge_dir)): {
            "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        } for path in asset_paths},
    })
    evidence_path.write_text(json.dumps(evidence, indent=2))
    shutil.copy2(evidence_path, evidence_dir / "wheel-provenance.json")
    return dict(venv_dir=venv_dir, python_bin=python_bin,
                patchdiff_bin=venv_dir / "bin/patchdiff-mcp", bridge_dir=bridge_dir,
                pkg_bridge_dir=bridge_dir, node_path=node_path, wheel_path=wheel_path,
                outside=outside, evidence_path=evidence_path)


@pytest.fixture(scope="session")
def wheel_linux_fixture(isolated_wheel_installation):
    """Dedicated Compose DB and disposable Linux users; preserve all Docker volumes."""
    import hashlib
    import secrets
    import socket
    install = isolated_wheel_installation
    repo = Path(__file__).resolve().parents[3]
    root = install["outside"] / "linux"
    root.mkdir(mode=0o700)
    password = secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    project = "patchdiff-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    compose = root / "docker-compose.yml"
    shutil.copy2(repo / "backend/app/mcp/resources/docker-compose.yml", compose)
    compose_env = {**os.environ, "POSTGRES_PASSWORD":password,
                   "POSTGRES_USER":"patchdiff_bootstrap", "PATCHDIFF_POSTGRES_PORT":str(port)}
    compose_cmd = ["docker","compose","-p",project,"-f",str(compose)]
    container = project + "-linux"
    evidence_dir = Path(os.getenv("PATCHDIFF_TEST_EVIDENCE_DIR", str(install["outside"])))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"status": "FAIL", "phase": "linux_acceptance",
                "wheel_sha256": hashlib.sha256(install["wheel_path"].read_bytes()).hexdigest()}
    result_path = evidence_dir / "wheel-linux-result.json"
    result_path.write_text(json.dumps(evidence, indent=2))
    def run(args, **kw):
        result = subprocess.run(args, capture_output=True, text=True, **kw)
        from app.core.config import redact_sensitive_text
        (root / "last-command.log").write_text(redact_sensitive_text(result.stdout + result.stderr, (password,)))
        if result.returncode != 0:
            evidence.update(command=args, returncode=result.returncode,
                            error=redact_sensitive_text(result.stderr, (password,)))
            result_path.write_text(json.dumps(evidence, indent=2))
        assert result.returncode == 0, redact_sensitive_text(result.stderr, (password,))
        return result
    try:
        run([*compose_cmd,"up","-d","--wait","postgres"],cwd=root,env=compose_env)
        run(["docker","run","-d","--name",container,"--network",project+"_default",
             "python:3.11-bookworm","sleep","infinity"])
        run(["docker","exec",container,"sh","-c",
             "apt-get update -qq && apt-get install -y -qq sudo >/tmp/apt-install.log"])
        run(["docker","exec",container,"mkdir","-p","/opt/dist","/harness"])
        run(["docker","cp",str(install["wheel_path"]),container+":/opt/dist/package.whl"])
        # Preserve a valid distribution filename for pip and uvx.
        wheel = "/opt/dist/" + install["wheel_path"].name
        run(["docker","exec",container,"mv","/opt/dist/package.whl",wheel])
        run(["docker","exec",container,"chmod","0644",wheel])
        run(["docker","cp",str(Path(install["node_path"]).resolve().parent.parent),container+":/opt/node"])
        run(["docker","exec",container,"sh","-c",
             "ln -s /opt/node/bin/node /usr/local/bin/node && ln -s /opt/node/bin/npm /usr/local/bin/npm"])
        for source in (repo/"backend/tests/integration/wheel_lifecycle_driver.py", repo/"examples/host_finalize.py"):
            run(["docker","cp",str(source),container+":/harness/"+source.name])
        run(["docker","exec",container,"python","-m","venv","/opt/venv"])
        run(["docker","exec",container,"/opt/venv/bin/python","-m","pip","install","--no-cache-dir",wheel,"uv"])
        run(["docker","exec",container,"/opt/venv/bin/python","-m","pip","check"])
        for extra in ([], ["--check-only"]):
            run(["docker","exec",container,"/opt/venv/bin/python","-m","app.waymark_bridge.bootstrap",
                 "--target-dir","/opt/venv/lib/python3.11/site-packages/app/waymark_bridge",*extra])
        result = run(["docker","exec","-i",container,"/opt/venv/bin/python","/harness/wheel_lifecycle_driver.py"],
                     input=json.dumps(dict(db_host="postgres",bootstrap_password=password,wheel=wheel,
                                           wheel_sha256=evidence["wheel_sha256"])))
        evidence = json.loads(result.stdout.splitlines()[-1])
        assert evidence["status"] == "PASS"
        (root/"linux-result.json").write_text(json.dumps(evidence,indent=2))
        shutil.copy2(install["evidence_path"],evidence_dir/"wheel-provenance.json")
        result_path.write_text(json.dumps(evidence,indent=2))
        yield evidence
    finally:
        # Stop only resources created by this fixture. Never remove containers/volumes.
        subprocess.run(["docker","stop",container],capture_output=True)
        subprocess.run([*compose_cmd,"stop","postgres"],cwd=root,env=compose_env,capture_output=True)


def test_isolated_installed_wheel_full_lifecycle(wheel_linux_fixture):
    assert wheel_linux_fixture["content_bytes"] > 1048576
    assert len({wheel_linux_fixture[k] for k in ("operator_uid","editor_uid","model_uid")}) == 3


def test_two_process_mcp_lifecycle_live_pg(wheel_linux_fixture):
    assert wheel_linux_fixture["status"] == "PASS"


def test_isolated_installed_wheel_stdio(wheel_linux_fixture):
    assert wheel_linux_fixture["status"] == "PASS"
