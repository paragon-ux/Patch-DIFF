"""Approved dependency-order PR integration, with exact-tree and fresh-CI gates."""
import datetime, hashlib, json, re, subprocess, time
from pathlib import Path
REPO="paragon-ux/Patch-DIFF"
BASE="feature/modernization-argon-remediation"
HERE=Path(__file__).resolve().parent
EXPECTED={5:"d8c71fe0dd02666463d443db9b713ea9bd8ffa4e",6:"fda5adba8c1912e207443ad4cdd964f7c0c5bc60",7:"dd5877de5d50ccae19faca12a6fb8463a291ec60",8:"226ab2210be84f53527c1f0edb6acecd4564ec27",9:"b5caa40bd41848420c4323d22ab648847cdc6745",10:"4ce9bf9e07ad07c969e0a4722bc1f17eaca8e3d4"}
LEDGER={"authorization":"User accepted merging the approved modernization/Goal G stack and beginning accepted Goal F.","starting_pr1":"b33faaf332e269019747772602afff34f9829e5c","pr4_merge":"d950d92b912b8e07a4219871019019ca07e67e5f","steps":[]}
if (HERE/"merge-ledger.json").exists():
    LEDGER=json.loads((HERE/"merge-ledger.json").read_text(encoding="utf-8"))
    if "stopped_with_error" in LEDGER:
        LEDGER.setdefault("recovered_attempt_errors",[]).append(LEDGER.pop("stopped_with_error"))
def command(args):
    if args[0] != "api":
        args = [*args, "--repo", REPO]
    r=subprocess.run(["gh",*args],capture_output=True,text=True,encoding="utf-8")
    if r.returncode: raise RuntimeError(f"gh command failed {args[:3]}: {r.stderr}")
    return r.stdout
def api(path,*args):
    value=command(["api",path,*args])
    return json.loads(value) if value.strip() else None
def pr(number):
    return api(f"repos/{REPO}/pulls/{number}")
def commit(sha):
    return api(f"repos/{REPO}/commits/{sha}")
def save():
    (HERE/"merge-ledger.json").write_text(json.dumps(LEDGER,indent=2)+"\n",encoding="utf-8")
def announce(**data):
    print(json.dumps(data),flush=True)
def inspect_ci(number,head,base):
    deadline=time.monotonic()+900
    last=None
    while time.monotonic()<deadline:
        runs=api(f"repos/{REPO}/actions/runs?head_sha={head}&per_page=30")["workflow_runs"]
        candidates=[r for r in runs if r["event"]=="pull_request" and r["head_sha"]==head]
        candidates.sort(key=lambda r:r["id"],reverse=True)
        if candidates:
            run=candidates[0]
            if run["status"]=="completed":
                assert run["conclusion"]=="success",f"PR{number} CI failed: {run['html_url']}"
                logs=command(["run","view",str(run["id"]),"--log"])
                (HERE/f"PR-{number}-CI-{run['id']}.txt").write_text(logs,encoding="utf-8")
                lines=logs.splitlines()
                actual=None
                for i,line in enumerate(lines):
                    if "git log -1 --format=%H" in line and i+1<len(lines):
                        actual=lines[i+1].split()[-1]
                assert actual and re.fullmatch("[0-9a-f]{40}",actual),"Missing actual checkout SHA"
                material=commit(actual)
                assert material["commit"]["tree"]["sha"]==commit(head)["commit"]["tree"]["sha"],"CI tested a different tree"
                parents={p["sha"] for p in material["parents"]}
                assert {head,base}<=parents,f"Wrong generated-merge parents: {parents}"
                counts=[int(m.group(1)) for m in re.finditer(r"(\d+) passed",logs)]
                assert len(counts)>=2 and "Verdict equivalence on the shared applier: OK" in logs
                assert "Migrate (upgrade, downgrade one step, upgrade again)" in logs
                return {"run_id":run["id"],"url":run["html_url"],"head_sha":head,"base_sha":base,"executed_merge_sha":actual,"tree_sha":material["commit"]["tree"]["sha"],"passed_counts":counts,"offline_equivalence":"OK","log_sha256":hashlib.sha256(logs.encode()).hexdigest()}
            state=(run["id"],run["status"])
            if state!=last:
                announce(pr=number,phase="fresh_CI",run=run["id"],status=run["status"])
                last=state
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for fresh CI on PR{number}")
try:
    for number,original in EXPECTED.items():
        item=pr(number)
        if item.get("merged"):
            prior=next((r for r in LEDGER["steps"] if r["pr"]==number and r.get("merge_sha")),None)
            assert prior and prior["merge_sha"]==item["merge_commit_sha"],"Unexpected already-merged PR"
            announce(pr=number,phase="verified_prior_merge",sha=prior["merge_sha"])
            continue
        assert item["state"]=="open",f"PR{number} no longer open; inspect"
        original_tree=commit(original)["commit"]["tree"]["sha"]
        assert commit(item["head"]["sha"])["commit"]["tree"]["sha"]==original_tree,"Unexpected head content"
        if item["draft"]:
            command(["pr","ready",str(number)])
        if item["base"]["ref"]!=BASE:
            command(["pr","edit",str(number),"--base",BASE])
        item=pr(number)
        base=api(f"repos/{REPO}/git/ref/heads/{BASE}")["object"]["sha"]
        refreshed=api(f"repos/{REPO}/merges","-X","POST","-f",f"base={item['head']['ref']}","-f",f"head={BASE}","-f",f"commit_message=Merge approved modernization base for PR {number} integration checks")
        head=refreshed["sha"] if refreshed else api(f"repos/{REPO}/git/ref/heads/{item['head']['ref']}")["object"]["sha"]
        for attempt in range(30):
            item=pr(number)
            if item["head"]["sha"]==head and item["base"]["sha"]==base:
                break
            time.sleep(2)
        assert item["head"]["sha"]==head and item["base"]["sha"]==base,"GitHub PR metadata did not converge"
        assert commit(head)["commit"]["tree"]["sha"]==original_tree,"Base refresh changed reviewed content"
        record={"pr":number,"original_reviewed_head":original,"refreshed_head":head,"base_sha":base,"reviewed_tree_preserved":True}
        LEDGER["steps"]=[r for r in LEDGER["steps"] if r["pr"]!=number]
        LEDGER["steps"].append(record);save()
        announce(pr=number,phase="base_refreshed",head=head,reviewed_tree_preserved=True)
        record["CI"]=inspect_ci(number,head,base);save()
        current=pr(number)
        assert current["head"]["sha"]==head and current["base"]["sha"]==base,"PR moved while verifying"
        merged=api(f"repos/{REPO}/pulls/{number}/merge","-X","PUT","-f",f"sha={head}","-f","merge_method=merge")
        assert merged["merged"] is True,merged
        record["merge_sha"]=merged["sha"];save()
        announce(pr=number,phase="merged",sha=merged["sha"],CI=record["CI"]["run_id"],passed_counts=record["CI"]["passed_counts"])
    current=pr(1)
    final=api(f"repos/{REPO}/git/ref/heads/{BASE}")["object"]["sha"]
    for attempt in range(30):
        current=pr(1)
        if current["head"]["sha"]==final:
            break
        time.sleep(2)
    assert current["head"]["sha"]==final,"Consolidated PR metadata did not converge"
    assert commit(final)["commit"]["tree"]["sha"]==commit(EXPECTED[10])["commit"]["tree"]["sha"],"Consolidation differs from accepted final material"
    LEDGER["consolidated_pr1_head"]=final
    LEDGER["consolidated_tree_matches_reviewed_goal_g_head"]=True
    LEDGER["PR1_CI"]=inspect_ci(1,final,current["base"]["sha"])
    LEDGER["ready_for_independent_consolidation_recheck"]=True
    save()
    announce(phase="stack_integrated_PR1_ready",head=final,CI=LEDGER["PR1_CI"]["run_id"])
except BaseException as error:
    LEDGER["stopped_with_error"]=str(error);save()
    announce(phase="stopped",error=str(error))
    raise

