"""Transport-only diagnostic, separate from native Codex W1-W12."""
import base64
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = tomllib.loads(Path(r"C:\Users\USER\.codex\config.toml").read_text(encoding="utf-8"))["mcp_servers"]["patchdiff"]

def exchange(env, requests, ascii_escapes):
    stdin = b"".join((json.dumps(x, ensure_ascii=ascii_escapes) + "\n").encode("utf-8") for x in requests)
    proc = subprocess.run([CONFIG["command"], *CONFIG["args"]], input=stdin, capture_output=True, env=env, timeout=30)
    responses = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    return {
        "requests": requests,
        "stdin_base64": base64.b64encode(stdin).decode("ascii"),
        "stdout_base64": base64.b64encode(proc.stdout).decode("ascii"),
        "stderr_base64": base64.b64encode(proc.stderr).decode("ascii"),
        "stdout_all_ascii": all(x < 128 for x in proc.stdout),
        "exit_code": proc.returncode,
        "responses": responses,
    }

def content(record, request_id):
    response = next(x for x in record["responses"] if x.get("id") == request_id)
    assert "result" in response, response
    tool = response["result"]
    assert not tool.get("isError"), tool
    return json.loads(tool["content"][0]["text"])

records = []
for override in (False, True):
    for escaped in (True, False):
        env = os.environ.copy()
        env.update(CONFIG["env"])
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        if override:
            env["PYTHONIOENCODING"] = "utf-8"
        profile = subprocess.run(
            [CONFIG["command"], "-c", "import sys,json; print(json.dumps({'python':sys.version,'stdin_encoding':sys.stdin.encoding,'stdin_errors':sys.stdin.errors,'stdout_encoding':sys.stdout.encoding,'stdout_errors':sys.stdout.errors}))"],
            env=env, capture_output=True, check=True,
        )
        setup = exchange(env, [
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}},
            {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"patchdiff_initialize_target","arguments":{"filename":f"g02-override-{override}-escaped-{escaped}.txt","content_type":"text/plain","content":"hello\n"}}},
        ], True)
        target = content(setup, 2)["target_file_id"]
        proposal = {"target_file_id":target,"expected_target_version":0,"intent":"Replace greeting with one star.","edits":[{"match":"hello","replace":"🌟"}],"client_request_id":f"g02-{override}-{escaped}"}
        edit = exchange(env, [
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}},
            {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"patchdiff_submit_edits","arguments":proposal}},
            {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"patchdiff_export_target","arguments":{"target_file_id":target}}},
        ], escaped)
        submitted = content(edit, 2)
        exported = content(edit, 3)
        summary = {
            "utf8_override":override,"ascii_json_escapes":escaped,
            "process_profile":json.loads(profile.stdout),"target_file_id":target,
            "status":submitted["status"],"exit_code":edit["exit_code"],
            "stdout_all_ascii":edit["stdout_all_ascii"],
            "expected_text":"🌟\n","actual_text":exported["content"],
            "exact_unicode":exported["content"]=="🌟\n",
        }
        records.append({"summary":summary,"setup":setup,"edit_and_export":edit})
        print(json.dumps(summary, ensure_ascii=True))
assert sum(not r["summary"]["exact_unicode"] for r in records) == 1
assert all(r["summary"]["exit_code"] == 0 for r in records)
output = {
    "classification":"Direct subprocess transport diagnostic after native workflows; not native Codex-host execution.",
    "timestamp_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "platform":platform.platform(),"source_head":"b5caa40bd41848420c4323d22ab648847cdc6745",
    "database":CONFIG["env"]["PATCHDIFF_DATABASE_URL"].rsplit("/",1)[1],
    "records":records,
}
(HERE/"transport-results.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")

