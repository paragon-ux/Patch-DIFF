import base64
import hashlib
import importlib.resources
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from zipfile import ZipFile

import psycopg

ROOT = Path(__file__).resolve().parent
DB = "patchdiff_release_package_20261022"
URL = f"postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/{DB}"
os.environ["PATCHDIFF_DATABASE_URL"] = URL
os.environ.pop("PYTHONPATH", None)
os.environ.pop("PYTHONIOENCODING", None)
os.environ.pop("PYTHONUTF8", None)
env = os.environ.copy()
record = {"source_commit": "9473e8bdfc64ae2c2630146af53e2c3428f1ca55", "events": []}
wheel_path = ROOT / "wheels-9473e8b/patchdiff_mvp-0.1.0-py3-none-any.whl"
record["wheel_sha256"] = hashlib.sha256(wheel_path.read_bytes()).hexdigest()

with psycopg.connect("postgresql://patchdiff:patchdiff@127.0.0.1:5432/postgres", autocommit=True, connect_timeout=5) as conn:
    existed = conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB,)).fetchone() is not None
    if not existed:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(DB)))
record["database_existed"] = existed

import app.mcp.external_adapter as adapter
installed_app = Path(adapter.__file__).resolve().parents[1]
assert "site-packages" in str(installed_app).lower(), installed_app
record["installed_app"] = str(installed_app)
with ZipFile(wheel_path) as wheel:
    names = wheel.namelist()
    assert not any(name.startswith("tests/") for name in names)
    for name in ("app/migrations/alembic.ini", "app/migrations/script.py.mako"):
        assert name in names
    source_names = [name for name in names if name.startswith("app/") and name.endswith(".py")]
    for name in source_names:
        assert (installed_app / name[4:]).read_bytes() == wheel.read(name), name
    record["installed_source_count"] = len(source_names)
    license_name = next(name for name in names if name.endswith("/licenses/LICENSE"))
    assert b"MIT License" in wheel.read(license_name)

ini = str(importlib.resources.files("app").joinpath("migrations/alembic.ini"))
migration = subprocess.run([sys.executable, "-m", "alembic", "-c", ini, "upgrade", "head"],
                           cwd=ROOT, env=env, capture_output=True, timeout=30)
record["migration_stdout"] = migration.stdout.decode("utf-8")
record["migration_stderr"] = migration.stderr.decode("utf-8")
assert migration.returncode == 0, record

proc = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], cwd=ROOT, env=env,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
responses = queue.Queue()
errors = []
def read():
    for raw in proc.stdout:
        responses.put(raw)
    responses.put(None)
threading.Thread(target=read, daemon=True).start()
threading.Thread(target=lambda: errors.extend(proc.stderr.readlines()), daemon=True).start()
index = 0
def rpc(method, params):
    global index
    index += 1
    request = {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
    wire = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    proc.stdin.write(wire); proc.stdin.flush()
    raw = responses.get(timeout=30)
    assert raw is not None, errors
    record["events"].append({"stdin_base64": base64.b64encode(wire).decode(), "stdout_base64": base64.b64encode(raw).decode()})
    result = json.loads(raw)
    assert result["id"] == index and "error" not in result, result
    return result["result"]
def call(name, arguments):
    result = rpc("tools/call", {"name": name, "arguments": arguments})
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])

try:
    rpc("initialize", {})
    tools = rpc("tools/list", {})["tools"]
    assert len(tools) == 20 and sum(len(tool["inputSchema"].get("examples", [])) for tool in tools) == 13
    target = call("patchdiff_initialize_target", {"filename": "installed-🌟.txt", "content_type": "text/plain", "content": "old 🌟\r\n"})["target_file_id"]
    record["target_file_id"] = target
    original = {"target_file_id": target, "intent": "Replace explicitly", "expected_target_version": 0,
                "replacement": "new 中\n", "client_request_id": "installed-original"}
    observed = call("patchdiff_preview", {key: value for key, value in {**original, "format": "patchdiff-tx/3"}.items() if key != "client_request_id"})
    assert observed["status"] == "accepted" and observed["returned_fact_count"] == 1 and not observed["change_facts_truncated"]
    first = call("patchdiff_submit_replacement", original)
    assert first["status"] == "accepted" and first["version"] == 1
    assert call("patchdiff_submit_operations", {"target_file_id": target, "intent": "Insert", "expected_target_version": 1,
        "operations": [{"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": "!"}]})["status"] == "accepted"
    assert call("patchdiff_submit_edits", {"target_file_id": target, "intent": "Rename", "expected_target_version": 2,
        "edits": [{"match": "new", "replace": "done"}]})["status"] == "accepted"
    legacy = f"PDCP 0.2.3\ntarget_file_id: {target}\ntarget_type: text/plain\n\n# MANIFEST\n# change_id: installed_legacy\n# intent: Rename.\n# input_state: Done.\n# output_state: Ready.\n# affected_region: line\n# user_visible_change: label\n# risk: low\n\n<<<<<<< MATCH\ndone\n=======\nready\n>>>>>>> REPLACE"
    assert call("patchdiff_submit_pdcp", {"target_file_id": target, "pdcp_content": legacy, "expected_target_version": 3})["status"] == "accepted"
    recovered = call("patchdiff_submit_replacement", original)
    assert recovered["deduplicated"] and recovered["pdcp_log_id"] == first["pdcp_log_id"]
    assert call("patchdiff_read_lines", {"target_file_id": target, "start_line": 1, "end_line": 1})["text"] == "!ready 中\n"
    assert call("patchdiff_save", {"target_file_id": target})["status"] == "saved"
    replay = call("patchdiff_replay", {"target_file_id": target})
    assert replay["status"] == "success" and all(replay["materialized_state_checks"].values())
    assert call("patchdiff_export_target", {"target_file_id": target})["content"] == "!ready 中\n"
    record["replay"] = replay
finally:
    proc.stdin.close()
    proc.wait(timeout=10)
assert proc.returncode == 0, errors

with psycopg.connect(URL.replace("postgresql+psycopg://", "postgresql://"), options="-c default_transaction_read_only=on", connect_timeout=5) as conn:
    current = conn.execute("SELECT current_content,version,current_hash FROM cloud_target_files WHERE target_file_id=%s", (target,)).fetchone()
    assert current == ("!ready 中\n", 4, hashlib.sha256("!ready 中\n".encode()).hexdigest())
    attempts = conn.execute("SELECT protocol_version,runtime_version,status FROM append_only_pdcp_logs WHERE target_file_id=%s ORDER BY log_sequence", (target,)).fetchall()
    assert len(attempts) == 4 and all(row[2] == "accepted" for row in attempts)
    assert conn.execute("SELECT count(*) FROM append_only_manifest_ledger WHERE target_file_id=%s", (target,)).fetchone()[0] == 4
    record["sql"] = {"current": current, "attempts": attempts, "ledger_count": 4}

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                          cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    deadline = time.monotonic() + 15
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/live", timeout=1) as response:
                assert response.status == 200
                record["health_live"] = json.load(response)
            break
        except (OSError, TimeoutError):
            if server.poll() is not None or time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=5) as response:
        assert response.status == 200
        record["health_ready"] = json.load(response)
finally:
    server.terminate(); server.wait(timeout=10)

record["helper_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(ROOT / "installed-package-smoke.json").write_text(json.dumps(record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "PASS", "installed_source_count": record["installed_source_count"], "target": target, "wire_events": len(record["events"]), "wheel_sha256": record["wheel_sha256"]}))
