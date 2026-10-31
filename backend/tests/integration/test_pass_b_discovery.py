import json
import os
from pathlib import Path
import subprocess
import sys

from app.core.config import settings


def test_original_published_examples_real_stdio_postgres(tmp_path):
    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "live.json"
    env = {**os.environ, "PYTHONPATH": str(root / "backend"), "PATCHDIFF_MCP_PROFILE": "full", "PATCHDIFF_DATABASE_URL": settings.database_url}
    # The recorded Pass B executor is immutable and covers its original 13
    # examples. Give only that executor its historical examples view; the actual
    # wire catalog is unchanged. Current observed examples execute separately in
    # test_compact_host_workflow.py, including both submission modes and paging.
    harness = r"""
import importlib.util
import json
from pathlib import Path
import sys
root = Path.cwd()
spec = importlib.util.spec_from_file_location("recorded_pass_b", root / "docs/usability/PASS-B-live-verify.py")
recorded = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorded)
rpc = recorded.Client.rpc
def original_examples(self, method, params):
    result = rpc(self, method, params)
    if method == "tools/list":
        for tool in result["tools"]:
            if tool["name"] in {"patchdiff_observe_scope", "patchdiff_submit_observed_operations", "patchdiff_finalize_target"}:
                tool["inputSchema"].pop("examples", None)
    return result
recorded.Client.rpc = original_examples
result = recorded.run()
result["events"] = recorded.EVENTS
result["scope"] = "Original 13 examples; six current observed examples have separate real-stdio coverage."
Path(sys.argv[1]).write_text(json.dumps(result, default=str) + "\n", encoding="utf-8")
"""
    process = subprocess.run([sys.executable, "-X", "utf8", "-c", harness, str(output)],
                             cwd=root, env=env, capture_output=True, timeout=60)
    assert process.returncode == 0, process.stdout.decode("utf-8") + process.stderr.decode("utf-8")
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert len(evidence["executed_pairs"]) == 13 and len(evidence["checks"]) == 4
