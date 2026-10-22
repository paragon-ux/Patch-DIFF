"""Goal F main baseline live verification, outside pytest; emits raw-byte/SQL evidence."""
import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import psycopg

ROOT = Path(__file__).resolve().parents[2]
DB = "patchdiff_goal_f_baseline_manual_20261021"
URL = f"postgresql://patchdiff:patchdiff@127.0.0.1:5432/{DB}"
RUNS = []
def exchange(env, requests, escaped):
    wire = b""
    for request in requests:
        # Escaped invalid Unicode is valid JSON wire data and must reach domain validation.
        try:
            line = json.dumps(request, ensure_ascii=escaped)
            wire += (line+"\n").encode("utf-8")
        except UnicodeEncodeError:
            wire += (json.dumps(request, ensure_ascii=True)+"\n").encode("utf-8")
    result = subprocess.run([sys.executable,"-m","app.mcp.external_adapter"],input=wire,capture_output=True,cwd=ROOT,env=env,timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8",errors="backslashreplace")
    responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    RUNS.append({"requests":requests,"stdin_base64":base64.b64encode(wire).decode(),"stdout_base64":base64.b64encode(result.stdout).decode(),"stderr_base64":base64.b64encode(result.stderr).decode(),"exit_code":result.returncode})
    return {r["id"]:r for r in responses}

def req(index,name,args):
    return {"jsonrpc":"2.0","id":index,"method":"tools/call","params":{"name":name,"arguments":args}}
def payload(responses,index):
    result=responses[index]["result"]
    assert not result.get("isError"),result
    return json.loads(result["content"][0]["text"])
def stats(target):
    with psycopg.connect(URL) as conn:
        text,version=conn.execute("SELECT current_content,version FROM cloud_target_files WHERE target_file_id=%s",(target,)).fetchone()
        logs=dict(conn.execute("SELECT status,count(*) FROM append_only_pdcp_logs WHERE target_file_id=%s GROUP BY status",(target,)).fetchall())
        ledger=conn.execute("SELECT count(*) FROM append_only_manifest_ledger WHERE target_file_id=%s",(target,)).fetchone()[0]
        return {"content":text,"version":version,"logs":logs,"ledger":ledger}

summaries=[]
for profile in ("absent","cp1252"):
    for escaped in (False,True):
        env=os.environ.copy()
        env.pop("PYTHONIOENCODING",None);env.pop("PYTHONUTF8",None)
        env.update(PYTHONPATH=str(ROOT/"backend"),PATCHDIFF_DATABASE_URL=URL.replace("postgresql://","postgresql+psycopg://",1))
        if profile=="cp1252":
            env["PYTHONIOENCODING"]="cp1252:surrogateescape"
        initial="hello\r\ncafé 世界 🚀\r\n"
        init=exchange(env,[{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}},req(2,"patchdiff_handle_upload",{"filename":f"manual-{profile}-{escaped}.txt","content_type":"text/plain","content":initial})],escaped)
        target=payload(init,2)["target_file_id"]
        proposal={"target_file_id":target,"expected_target_version":0,"intent":"Preserve Unicode exactly.","edits":[{"match":"hello","replace":"🌟 café 世界"}],"client_request_id":f"manual-{profile}-{escaped}"}
        bad_nul={**proposal,"expected_target_version":1,"edits":[{"match":"🌟 café 世界","replace":"bad\u0000"}],"client_request_id":f"nul-{profile}-{escaped}"}
        bad_surrogate={**proposal,"expected_target_version":1,"edits":[{"match":"🌟 café 世界","replace":"bad\ud800"}],"client_request_id":f"surrogate-{profile}-{escaped}"}
        responses=exchange(env,[
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}},
            {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},
            req(3,"patchdiff_read_target",{"target_file_id":target,"start":0,"length":100}),
            req(4,"patchdiff_find_occurrences",{"target_file_id":target,"text":"世界","context_chars":20}),
            req(5,"patchdiff_submit_edits",proposal),
            req(6,"patchdiff_submit_edits",proposal),
            req(7,"patchdiff_read_target",{"target_file_id":target,"version":1}),
            req(8,"patchdiff_read_target",{"target_file_id":target,"length":100}),
            req(9,"patchdiff_submit_edits",bad_nul),
            req(10,"patchdiff_submit_edits",bad_surrogate),
            req(11,"patchdiff_save",{"target_file_id":target}),
            req(12,"patchdiff_replay",{"target_file_id":target}),
            req(13,"patchdiff_export_target",{"target_file_id":target}),
        ],escaped)
        assert len(responses[2]["result"]["tools"])==16
        assert payload(responses,3)["text"]==initial.replace("\r\n","\n")
        search=payload(responses,4)
        assert search["version"]==0 and search["occurrence_count"]==1 and search["current_hash"]
        accepted=payload(responses,5)
        recovered=payload(responses,6)
        assert accepted["status"]=="accepted" and recovered["deduplicated"] is True
        assert accepted["pdcp_log_id"]==recovered["pdcp_log_id"]
        assert responses[7]["result"]["isError"] is True
        expected="🌟 café 世界\ncafé 世界 🚀\n"
        assert payload(responses,8)["text"]==expected
        for index in (9,10):
            rejection=payload(responses,index)
            assert rejection["status"]=="rejected" and rejection["failure_reason"]=="target_encoding_invalid"
        assert payload(responses,11)["status"]=="saved"
        replay=payload(responses,12)
        assert replay["status"]=="success" and replay["materialized_state_matches"] is True
        assert payload(responses,13)["content"]==expected
        state=stats(target)
        assert state=={"content":expected,"version":1,"logs":{"accepted":1,"rejected":2},"ledger":1},state

        # Invalid wire bytes are outside JSON/domain audit; no new mutation may be admitted.
        bad=req(1,"patchdiff_submit_edits",{**proposal,"expected_target_version":1,"edits":[{"match":"🌟 café 世界","replace":"BAD_BYTE"}],"client_request_id":f"wire-{profile}-{escaped}"})
        wire=(json.dumps(bad,ensure_ascii=True)+"\n").encode().replace(b"BAD_BYTE",b"\xff")
        broken=subprocess.run([sys.executable,"-m","app.mcp.external_adapter"],input=wire,capture_output=True,cwd=ROOT,env=env,timeout=30)
        assert broken.returncode!=0
        assert stats(target)==state,"Malformed wire input changed persisted state"
        RUNS.append({"classification":"malformed UTF-8 wire control","stdin_base64":base64.b64encode(wire).decode(),"stdout_base64":base64.b64encode(broken.stdout).decode(),"stderr_base64":base64.b64encode(broken.stderr).decode(),"exit_code":broken.returncode})
        summaries.append({"profile":profile,"json_ascii_escaped":escaped,"target_file_id":target,"exact_SQL_state":state,"replay":replay["materialized_state_checks"],"malformed_wire_no_mutation":True})
        print(json.dumps({"profile":profile,"escaped":escaped,"target":target,"passed":True}),flush=True)
head=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
files=["backend/app/mcp/external_adapter.py","docs/usability/BASELINE-live-verify.py"]
record={"classification":"Manual outside-pytest real public MCP stdio subprocesses plus independent SQL; installed native host remains on its recorded reproduction checkout; baseline executes merged main.","timestamp_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"executed_head":head,"python":sys.version,"database":DB,"source_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files},"summaries":summaries,"runs":RUNS}
(ROOT/"docs/usability/BASELINE-live-results.json").write_text(json.dumps(record,ensure_ascii=True,indent=2)+"\n",encoding="utf-8")
print("Four raw-byte/escaped profiles passed; SQL state, audited rejections, recovery, SAVE/replay and malformed-wire nonmutation verified.",flush=True)

