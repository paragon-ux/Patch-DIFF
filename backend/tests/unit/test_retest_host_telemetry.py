import copy
import json

import pytest

from evaluation.structural_retest.host_adapter import TOOLS
from evaluation.structural_retest.preflight import validate_approval, validate_host
from evaluation.structural_retest.synthetic import description
from evaluation.structural_retest.telemetry import Budget, BudgetExceeded, Evidence, digest, verify_events, wire


@pytest.mark.parametrize("defect", ["missing", "display_only", "inherit", "reasoning", "model", "decoding", "output", "permission", "capability", "semantics", "usage", "build", "timestamp"])
def test_host_preflight_fails_closed(defect):
    info = description()
    assert not validate_host(info, synthetic=True)
    arm = info["arms"]["C"]
    if defect == "missing":
        del arm["provider"]
    elif defect == "display_only":
        arm["provider_evidence"]["verified"] = False
    elif defect == "inherit":
        arm["effective_reasoning_setting"] = "inherit"
    elif defect == "reasoning":
        arm["effective_reasoning_setting"] = "Low"
    elif defect == "model":
        arm["exact_provider_model_id"] = "other"
    elif defect == "decoding":
        arm["decoding_settings"] = {"temperature": .9}
    elif defect == "output":
        arm["output_limit"] = 1
    elif defect == "permission":
        arm["tool_permissions"].append("edit_file")
    elif defect == "capability":
        arm["capabilities"].remove("filesystem_denied")
    elif defect == "semantics":
        arm["tool_semantics"] = {}
    elif defect == "usage":
        arm["usage_contract"]["actual_input_output"] = False
    elif defect == "build":
        arm["host_version"] = None
    else:
        arm["model_configuration_timestamp"] = "yesterday"
    assert validate_host(info, synthetic=True)
    assert validate_host(info)  # Synthetic identity cannot satisfy live preflight.


def test_gate_approval_requires_external_review_bound_to_commit_manifest_host():
    commit, manifest, host = "a" * 40, "b" * 64, "c" * 64
    binding = {"gate": "Gate 2", "decision": "approved", "study_id": "primary-original-21-five-file-v1",
               "commit": commit, "manifest_sha256": manifest, "host_evidence_sha256": host,
               "independent_review": True, "live_execution_authorized": True}
    review = {"commit_id": commit, "body": "```json\n" + json.dumps(binding) + "\n```",
              "state": "COMMENTED", "submitted_at": "synthetic-test", "user": {"login": "synthetic-reviewer"}}
    receipt = {"review_url": "synthetic-only", "review_sha256": digest(review)}
    assert validate_approval(receipt, commit, manifest, host, lambda _: review)["binding"] == binding
    for c, m, h in [("d" * 40, manifest, host), (commit, "e" * 64, host), (commit, manifest, "f" * 64)]:
        with pytest.raises(ValueError):
            validate_approval(receipt, c, m, h, lambda _: review)
    with pytest.raises(ValueError):
        validate_approval({"gate_2": "approved"}, commit, manifest, host, lambda _: {})
    with pytest.raises(ValueError):
        validate_approval(receipt, commit, manifest, host, lambda _: {**review, "body": "not approved"})


@pytest.fixture
def conditions():
    return {"wall_clock_budget_seconds": 600, "model_token_budget_per_task": 16000,
            "max_tool_calls_per_task": 96, "tool_timeout_seconds": 30,
            "max_retries_after_rejected_edit_per_task": 2, "automatic_transport_retries": 0}


def test_calls_time_tokens_and_missing_usage(conditions):
    now = [0]
    b = Budget(conditions, lambda: now[0])
    for _ in range(96):
        b.tool(None, {}, False)
    with pytest.raises(BudgetExceeded, match="tool_calls"):
        b.tool(None, {}, False)
    now[0] = 600
    with pytest.raises(BudgetExceeded, match="wall_clock"):
        b.remaining()
    b = Budget(conditions)
    with pytest.raises(ValueError, match="actual provider usage"):
        b.usage({"output_tokens": 5})
    b.usage({"input_tokens": 15990, "output_tokens": 10, "cached_tokens": 1000, "reasoning_tokens": 5})
    assert b.tokens == 16000  # Breakdowns must not be double counted.
    with pytest.raises(BudgetExceeded, match="actual_model_tokens"):
        b.remaining()


def test_retry_accounting_first_reject_and_lost_idempotent(conditions):
    b = Budget(conditions)
    args = {"client_request_id": "key", "attempt": 1}
    assert b.tool("target", args, True) is None and b.retries == 0
    b.outcome("target", args, {}, "lost_response")
    b.tool("target", args, True)
    assert b.retries == 1
    b.outcome("target", args, {"pdcp_log_id": "log"}, "rejected")
    b.tool("target", {"attempt": 2, "parent_pdcp_log_id": "log"}, True)
    assert b.retries == 2
    with pytest.raises(BudgetExceeded, match="editing_retries"):
        b.tool("target", args, True)
    b = Budget(conditions)
    b.outcome("target", args, {}, "lost_response")
    with pytest.raises(ValueError, match="identical request-key"):
        b.tool("target", {"client_request_id": "different"}, True)
    b = Budget(conditions)
    b.outcome("target", args, {"pdcp_log_id": "log"}, "rejected")
    with pytest.raises(ValueError, match="parent log"):
        b.tool("target", args, True)


def test_evidence_bytes_redaction_append_chain_and_truncation(tmp_path):
    path = tmp_path / "events.jsonl"
    evidence = Evidence(path, {"run_id": "test", "arm": "A", "replicate": 1})
    args = {"Path": "unicode.py", "Target": "café", "Replacement": "☃"}
    evidence.emit("tool", arguments=args, arguments_utf8_bytes=len(wire(args)),
                  authorization="Bearer bad", database_url="postgresql://user:pw@host/db",
                  nested={"api_key": "never-log", "output_tokens": 10})
    evidence.emit("archive_complete", outcome="failed")
    evidence.close()
    records = verify_events(path)
    assert records[0]["arguments_utf8_bytes"] == len(wire(records[0]["arguments"]))
    assert records[0]["nested"]["output_tokens"] == 10
    assert "never-log" not in path.read_text() and "user:pw" not in path.read_text() and "Bearer bad" not in path.read_text()
    with pytest.raises(FileExistsError):
        Evidence(path, {})
    path.write_text(path.read_text().splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="Incomplete telemetry"):
        verify_events(path)


def test_example_offline_preflight_uses_real_schema_discovery_but_blocks_model():
    import subprocess
    import sys
    from evaluation.structural_retest.controller import ROOT
    result = subprocess.run([sys.executable, str(ROOT / "controller.py"), "--preflight-offline", "--config", str(ROOT / "host_config.example.json")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["execution"] == "blocked" and report["live_model_invocations"] == 0
    assert len(report["mcp_schema_sha256"]) == 64 and report["errors"]
