"""Engineering-only pin refresh. Changes invalidate any existing Gate 2 approval."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = ("controller.py", "host_adapter.py", "telemetry.py", "preflight.py", "mcp_session.py", "native.py",
           "synthetic.py", "prepare.py", "evaluate.py", "freeze.py", "host_config.example.json",
           "primary/evaluator/full_byte_oracle.py", "primary/evaluator/reference_hashes.json")


def freeze():
    path = ROOT / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["reviewed_head"] = "9e7f9614728ad5098d543c1f2f98774ae0f4fe6c"
    manifest["gate_2"] = "closed"
    manifest["study_id"] = "primary-original-21-five-file-v1"
    manifest["controller"] = {"version": "primary-controller/1", "interface_version": "patchdiff-retest-host/1",
                               "live_execution_default": "disabled",
                               "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}}
    primary = manifest["studies"]["primary"]
    primary["full_byte_oracle"] = {"source": "primary/evaluator/full_byte_oracle.py",
                                   "reference_manifest": "primary/evaluator/reference_hashes.json",
                                   "reference_sha256": hashlib.sha256((ROOT / "primary/evaluator/reference_hashes.json").read_bytes()).hexdigest(),
                                   "expected_files": json.loads((ROOT / "primary/evaluator/reference_hashes.json").read_text()),
                                   "representations": "one explicit representation from original task, with original surrounding indentation/EOL; no post-result tolerance"}
    primary["missing"] = ["independent review of final full-byte oracle/controller commit and manifest",
                          "owner-verified actual Gemini 3.8 Flash High provider/host/permissions/usage evidence",
                          "external Gate 2 approval bound to exact commit, raw manifest SHA and host-evidence SHA"]
    primary["evaluation_command"] = "python evaluation/structural_retest/evaluate.py --study primary --workspace <exported-arm-directory> (requires BOTH full-byte and original behavioral oracles)"
    manifest["host_contract"] = {"configuration_example": "host_config.example.json", "interface": "host_adapter.py",
                                 "required_fields": ["provider", "exact_provider_model_id", "effective_reasoning_setting", "host_name", "host_version", "decoding_settings", "context_limit", "output_limit", "tool_permissions", "model_configuration_timestamp"],
                                 "required_usage": ["actual input_tokens", "actual output_tokens", "cached_tokens or explicit missing flag", "reasoning_tokens or explicit missing flag"],
                                 "token_accounting": "input includes cached; output includes reasoning; sum input+output only; host hard total-token reservation/cancellation required",
                                 "real_host_verification": "pending; no real Gemini binding supplied; declared display name/booleans alone are not verification",
                                 "native_binding": "reviewed executable path/hash/version and confined rtk read; controller exact replace-all edit_file broker",
                                 "mcp_binding": "real stdio tools/list schema digest plus strict-mode child configuration and independent disposable databases"}
    manifest["approval_requirements"] = {"external_review": "PR #16 GitHub review permalink resolved from API, not local approved flag",
                                         "binding": ["Gate 2 approved", "exact commit SHA", "raw manifest SHA-256", "host evidence canonical JSON SHA-256", "study_id", "independent_review=true", "live_execution_authorized=true"],
                                         "separate_action": "--execute with execution_enabled=true and clean reviewed checkout",
                                         "current_approval": None}
    manifest["verification_state"] = {"offline": "implementation and deterministic tests available; see exact-commit evidence report",
                                        "external_host": "pending owner evidence and independent review", "measured_sessions": "not executed"}
    manifest["execution_blockers"] = primary["missing"] + ["Supplemental remains separately gated and is not dispatched by this controller"]
    path.write_bytes((json.dumps(manifest, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))


if __name__ == "__main__":
    freeze()
