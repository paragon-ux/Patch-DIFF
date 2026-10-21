"""Read-only independent database and frontmatter verification after native tasks."""
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path
import psycopg
import yaml

HERE = Path(__file__).resolve().parent
REPO = Path(r"C:\Users\USER\Desktop\Frameworks\Antigravity-playground\patch-diff\Patch-DIFF")
FIXTURES = REPO.parent / "fixtures"
TARGETS = {
    "T1":"d1db49b2-88c2-4809-95a3-dd91e7b5f742",
    "T2":"70243aba-dc77-4c29-be97-5d3e1b121cd7",
    "T3":"620f5653-b379-4871-8485-3b88c6b3ec87",
    "T4":"a6eca964-05c3-44ce-bb6d-3f6db4a9e52e",
    "T5":"ce39e26f-34ea-4bcf-9ba7-b7964e22213e",
}
names = {"T1":"config.yaml","T2":"README.md","T3":"notes.txt","T4":"large.md","T5":"tiny.txt"}
expected = {key:(FIXTURES/name).read_text(encoding="utf-8") for key,name in names.items()}
expected["T1"] = expected["T1"].replace("max_overflow: 10\n  timeout: 30","max_overflow: 10\n  timeout: 90").replace("version: 1.0.4","version: 1.0.5").replace("workers: 4","workers: 8")
inside = False
lines = []
for line in expected["T2"].splitlines(keepends=True):
    if line.startswith("~~~") or line.startswith(chr(96)*3):
        inside = not inside
    lines.append(line if inside else line.replace("DataPulse","TelemetryFlow"))
expected["T2"] = "".join(lines).replace("## Overview","## Product Overview").replace("## Product Overview\n\n","## Product Overview\n\nTelemetryFlow connects ingestion, transformation, and delivery in one auditable pipeline.\n\n").replace("- [Overview](#overview)","- [Product Overview](#product-overview)")
start = expected["T2"].index("## Benchmarks")
end = expected["T2"].index("## Contributing",start)
replacement = """## Benchmarks

Updated 2026 benchmark results use a 16 vCPU host with 64 GB RAM.

| Ingestion Mode | Throughput (events/sec) | P99 Latency (ms) |
| :--- | :--- | :--- |
| Direct Sync | 250,000 | 1.80 |
| Micro-batch (10ms) | 960,000 | 4.20 |
| Ring-buffered | 1,780,000 | 0.85 |

The sustained run completed without dropped messages.

"""
expected["T2"] = expected["T2"][:start] + replacement + expected["T2"][end:]
expected["T3"] = expected["T3"].replace("Status: In Progress 🚀","Status: Completed 🎉").replace("这是一个包含中文字符的测试段落，用于验证多语言文本处理的正确性。","Đây là đoạn kiểm thử đa ngôn ngữ, xác nhận Unicode chính xác.")
expected["T4"] = expected["T4"].replace("threshold is set to 99.95 percent.","threshold is set to 99.99 percent.")
expected["T5"] = expected["T5"].replace("hello","hello again")
config = tomllib.loads(Path(r"C:\Users\USER\.codex\config.toml").read_text(encoding="utf-8"))["mcp_servers"]["patchdiff"]
dburl = config["env"]["PATCHDIFF_DATABASE_URL"].replace("postgresql+psycopg://","postgresql://",1)
checks = {}
with psycopg.connect(dburl) as conn:
    for key, target in TARGETS.items():
        text, version = conn.execute("SELECT current_content,version FROM cloud_target_files WHERE target_file_id=%s",(target,)).fetchone()
        assert text == expected[key], f"{key}: text differs from independent oracle"
        log_counts = conn.execute("SELECT status,count(*) FROM append_only_pdcp_logs WHERE target_file_id=%s GROUP BY status",(target,)).fetchall()
        ledger_count = conn.execute("SELECT count(*) FROM append_only_manifest_ledger WHERE target_file_id=%s",(target,)).fetchone()[0]
        checks[key]={"target_file_id":target,"exact_content":True,"version":version,"sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),"logs":dict(log_counts),"ledger_rows":ledger_count}
    parent, attempt = conn.execute("SELECT parent_pdcp_log_id,regeneration_attempt FROM append_only_pdcp_logs WHERE pdcp_log_id=%s",("ff37b035-5fdb-4d04-aa90-b0e17a5d63f7",)).fetchone()
    assert str(parent) == "0e61b4fe-9866-418e-9f8e-041bea5fc191" and attempt == 2
    wrong = conn.execute("SELECT current_content FROM cloud_target_files WHERE target_file_id=%s",("4b0b66aa-8c30-4efe-aa6c-e4308c2e111f",)).fetchone()[0]
    assert wrong == "ðŸŒŸ\n"
    database = conn.execute("SELECT current_database(),version(),current_setting('transaction_isolation')").fetchone()

frontmatter = []
for file in sorted((REPO/".agents/skills").glob("*/SKILL.md")):
    header = file.read_text(encoding="utf-8").split("---",2)[1]
    try:
        yaml.safe_load(header)
        result = {"file":str(file.relative_to(REPO)),"original_valid":True}
    except yaml.YAMLError as error:
        revised = "\n".join("description: "+json.dumps(line.partition(":")[2].strip()) if line.startswith("description:") else line for line in header.splitlines())
        yaml.safe_load(revised)
        result = {"file":str(file.relative_to(REPO)),"original_valid":False,"error":str(error),"quoted_description_valid":True}
    frontmatter.append(result)

head = subprocess.run(["git","rev-parse","HEAD"],cwd=REPO,capture_output=True,text=True,check=True).stdout.strip()
assert head == "b5caa40bd41848420c4323d22ab648847cdc6745"
status = subprocess.run(["git","status","--short"],cwd=REPO,capture_output=True,text=True,check=True).stdout
assert not any(line and not line.startswith("?? ") for line in status.splitlines()), status
output = {"classification":"Post-workflow independent read-only SQL and YAML parsing; not native workflow calls.","source_head":head,"source_tracked_tree_unchanged":True,"database":database[0],"postgres_version":database[1],"isolation":database[2],"main_targets":checks,"W8_lineage_verified":True,"G02_wrong_text_independently_verified_in_SQL":True,"frontmatter":frontmatter}
(HERE/"independent-verification.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(output,ensure_ascii=True,indent=2))

