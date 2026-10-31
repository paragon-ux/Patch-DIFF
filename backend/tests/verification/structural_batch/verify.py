"""Deterministic five-file capability check over real stdio MCP and live Postgres.

Uses pinned declarative selections/operations extracted from the original
exploratory C transcript. No transcript or experiment result is needed at runtime.
The independent primary oracle checks full bytes before importing Python outputs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from backend.tests.verification.structural_batch.evaluate import complete_primary
from backend.tests.verification.structural_batch.primary.evaluator.full_byte_oracle import SOURCE_HASHES, expected

PRIMARY = Path(__file__).resolve().parent / "primary"
OPERATIONS_SHA256 = "43625f22c9c2bf46c6fddbb2757c1b940bfbcdd9b55a52b239ac61a4a853a70a"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def original_plan():
    """Pinned declarative backend regression input; never a live-model task."""
    raw = (Path(__file__).parent / "operations.json").read_bytes()
    if sha(raw) != OPERATIONS_SHA256:
        raise ValueError("Changed deterministic operation fixture")
    plan = json.loads(raw)
    if set(plan) != set(SOURCE_HASHES) or sum(len(groups) for groups in plan.values()) != 20 or sum(len(g["operations"]) for groups in plan.values() for g in groups) != 54:
        raise ValueError("Unexpected deterministic operation inventory")
    return plan


class MCP:
    def __init__(self, profile, database_url=None, *, response_mode=None, rpc_timeout_seconds=30, protocol_version=None):
        if not 0 < rpc_timeout_seconds < float("inf"):
            raise ValueError("RPC timeout must be finite and positive")
        self.protocol_version = protocol_version or ("2025-11-25" if profile == "observed_v2" else None)
        self.rpc_timeout_seconds, self.closed = rpc_timeout_seconds, False
        self.profile, self.sequence, self.calls, self.events = profile, 0, Counter(), []
        env = {**os.environ, "PYTHONPATH": str(REPO / "backend"), "PATCHDIFF_MCP_PROFILE": profile,
               "PATCHDIFF_STRICT_OBSERVATION_MODE": "1" if profile in {"observed", "observed_editor", "observed_v2"} else "0"}
        if database_url: env["PATCHDIFF_DATABASE_URL"] = database_url
        if response_mode is not None: env["PATCHDIFF_MCP_RESPONSE_MODE"] = response_mode
        self.response_mode = env.get("PATCHDIFF_MCP_RESPONSE_MODE", "detailed")
        self.stderr = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen([sys.executable, "-m", "app.mcp.external_adapter"], cwd=REPO,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, env=env)
        except BaseException:
            self.stderr.close()
            raise

    def __enter__(self):
        try:
            self.rpc("initialize", {"protocolVersion": self.protocol_version} if self.protocol_version else {})
            self.catalog = self.rpc("tools/list", {})
            self.catalog_wire_bytes = self.last_wire_bytes
            return self
        except BaseException:
            self.close(force=True)
            raise

    def __exit__(self, *args):
        self.close()

    def close(self, *, force=False):
        if self.closed: return
        self.closed = True
        if force and self.process.poll() is None: self.process.kill()
        try: self.process.stdin.close()
        except (BrokenPipeError, OSError): pass
        try: self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        self.process.stdout.close()
        self.stderr.close()

    def rpc(self, method, params):
        if self.closed: raise RuntimeError("MCP peer is closed")
        self.sequence += 1
        message = (json.dumps({"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params}) + "\n").encode("utf-8")
        completed = queue.Queue(maxsize=1)
        def exchange():
            try:
                self.process.stdin.write(message)
                self.process.stdin.flush()
                completed.put((self.process.stdout.readline(), None))
            except Exception as exc:
                completed.put((None, exc))
        reader = threading.Thread(target=exchange, daemon=True)
        reader.start()
        try:
            try:
                raw, error = completed.get(timeout=self.rpc_timeout_seconds)
            except queue.Empty:
                raise TimeoutError(f"MCP {method} exceeded {self.rpc_timeout_seconds}s; outcome may be uncertain") from None
            if error: raise error
            if not raw:
                self.stderr.seek(0)
                raise RuntimeError("MCP EOF: " + self.stderr.read(65536).decode("utf-8", errors="replace"))
            self.last_wire_bytes = len(raw)
            reply = json.loads(raw)
            if reply.get("id") != self.sequence or "result" not in reply: raise RuntimeError(reply)
            return reply["result"]
        except BaseException:
            self.close(force=True)
            raise
        finally:
            reader.join(timeout=1)

    def call(self, name, **arguments):
        self.calls[name] += 1
        started = time.perf_counter()
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"): raise RuntimeError(result)
        payload = json.loads(result["content"][0]["text"])
        if self.profile == "observed_v2":
            from jsonschema import Draft202012Validator
            assert result["structuredContent"] == payload
            declaration = next(t for t in self.catalog["tools"] if t["name"] == name)
            Draft202012Validator(declaration["inputSchema"]).validate(arguments)
            Draft202012Validator(declaration["outputSchema"]).validate(payload)
        self.events.append({"tool": name, "arguments": arguments, "response": payload,
                            "result_utf8_bytes": len(result["content"][0]["text"].encode("utf-8")),
                            "jsonrpc_line_bytes": self.last_wire_bytes,
                            "elapsed_seconds": time.perf_counter() - started})
        return payload


def run(destination, database_url=None, *, host_finalize=False, editor_v2=False):
    if editor_v2 and not host_finalize:
        raise ValueError("observed_v2 requires separate trusted --host-finalize")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    exports = destination / "exports"
    if not host_finalize: exports.mkdir()
    expected()  # authenticates frozen task/source hashes before using their content
    plan = original_plan()
    profiles = {}
    for profile in ("editor", "unobserved", "observed", "observed_editor", "observed_v2", "full"):
        with MCP(profile, database_url) as client:
            profiles[profile] = {"tool_count": len(client.catalog["tools"]),
                                 "tools_list_jsonrpc_line_bytes": client.catalog_wire_bytes,
                                 "tools_result_utf8_bytes": len(json.dumps(client.catalog, sort_keys=True, separators=(",", ":")).encode("utf-8"))}
    files, manifest = [], []
    with MCP("full", database_url, response_mode="detailed" if host_finalize else None) as lifecycle, MCP("observed_v2" if editor_v2 else "observed_editor" if host_finalize else "observed", database_url) as editor:
        for name, groups in plan.items():
            content = (PRIMARY / "fixtures" / name).read_bytes()
            assert sha(content) == SOURCE_HASHES[name]
            target = lifecycle.call("patchdiff_initialize_target", filename=name, content=content.decode("utf-8"),
                content_type={".py": "text/x-python", ".json": "application/json", ".md": "text/markdown"}[Path(name).suffix])
            assert target["status"] == "ok"
            tid = target["target_file_id"]
            if editor_v2:
                bundle = editor.call("patchdiff_observe_scopes", target_file_id=tid, selections=[g["selection"] for g in groups])
                assert bundle["status"] == "observed_batch", bundle
                receipt = editor.call("patchdiff_commit_bundle", snapshot=bundle["snapshot"],
                    intent="Apply the original primary task to selected structures",
                    client_request_id="deterministic-structural-batch", groups=[{"observation_id": scope["observation_id"],
                        "operations": group["operations"]} for scope, group in zip(bundle["scopes"], groups)])
                assert receipt["status"] == "accepted" and receipt["transaction"]["after"]["version"] == 1, receipt
                assert receipt["current"] == receipt["transaction"]["after"]
                assert receipt["transaction"]["group_count"] == len(groups)
                assert receipt["transaction"]["operation_count"] == sum(len(g["operations"]) for g in groups)
                accepted = {"after_version": receipt["transaction"]["after"]["version"],
                            "after_hash": receipt["transaction"]["after"]["hash"],
                            "pdcp_log_id": receipt["transaction"]["pdcp_log_id"],
                            "change_count": receipt["transaction"]["operation_count"]}
            else:
                bundle = editor.call("patchdiff_observe_scope", target_file_id=tid, selections=[g["selection"] for g in groups])
                assert bundle["status"] == "observed_batch", bundle
                accepted = editor.call("patchdiff_submit_observed_operations", target_file_id=tid,
                    observation_bundle_id=bundle["observation_bundle_id"], expected_target_version=0,
                    expected_current_hash=target["current_hash"], intent="Apply the original primary task to selected structures",
                    client_request_id="deterministic-structural-batch", groups=[{"observation_id": scope["observation_id"],
                        "operations": group["operations"]} for scope, group in zip(bundle["scopes"], groups)])
                assert accepted["status"] == "accepted" and accepted["after_version"] == 1, accepted
                if editor.response_mode == "compact":
                    assert bundle["presentation"]["mode"] == accepted["presentation"]["mode"] == "compact"
                    assert "evidence" not in accepted and "groups" not in accepted
                else:
                    assert "evidence" in accepted and "presentation" not in accepted
            replay = None
            if not host_finalize:
                saved = editor.call("patchdiff_save", target_file_id=tid, expected_target_version=1, expected_current_hash=accepted["after_hash"])
                replay = editor.call("patchdiff_replay", target_file_id=tid)
                assert saved["status"] == "saved" and replay["status"] == "success" and replay["materialized_state_matches"]
                exported = lifecycle.call("patchdiff_export_target", target_file_id=tid)
                (exports / name).write_bytes(exported["content"].encode("utf-8"))
            manifest.append({"filename": name, "target_file_id": tid, "expected_target_version": accepted["after_version"],
                             "expected_current_hash": accepted["after_hash"], "accepted_pdcp_log_id": accepted["pdcp_log_id"]})
            files.append({"filename": name, "target_file_id": tid, "group_count": len(groups),
                          "operation_count": accepted["change_count"], "after_version": 1, "pdcp_log_id": accepted["pdcp_log_id"],
                          "replay_checks": replay["materialized_state_checks"] if replay else None})
        finalization = None
        if host_finalize:
            from examples.host_finalize import finalize_targets
            finalization = finalize_targets(lifecycle.call, manifest, destination / "finalization")
            assert finalization["status"] == "complete", finalization
            assert editor.calls["patchdiff_save"] == editor.calls["patchdiff_replay"] == 0
            exports = destination / "finalization" / "exports"
        for index, file in enumerate(files):
            tid, name = file["target_file_id"], file["filename"]
            file["output_sha256"] = sha((exports / name).read_bytes())
            if host_finalize: file["replay_checks"] = finalization["targets"][index]["replay_checks"]
            history = lifecycle.call("patchdiff_get_pdcp_log", target_file_id=tid)
            ledger = lifecycle.call("patchdiff_get_manifest_ledger", target_file_id=tid, include_previous_cycles=True, limit=200)
            assert len(history["entries"]) == 1 and history["entries"][0]["status"] == "accepted"
            assert len(ledger["entries"]) == file["operation_count"]
        oracle = complete_primary(exports)
        assert oracle["complete_correct"] and oracle["behavioral"]["passed"] == oracle["behavioral"]["total"] == 20, oracle
        result = {"kind": "deterministic_api_capability_check", "model_invocations": 0, "gate2": "closed",
                  "files": files, "oracle": oracle, "profiles": profiles, "host_finalized": host_finalize, "editor_v2": editor_v2,
                  "response_modes": {"editor": editor.response_mode, "operator": lifecycle.response_mode},
                  "editing_tools_calls": dict(editor.calls),
                  "trusted_lifecycle_tools_calls": dict(lifecycle.calls),
                  "editing_tools_call_total": sum(editor.calls.values()), "candidate_discovery_calls": 0,
                  "method": "Real stdio tools/call lines counted by explicit role; initialize/export/history are trusted lifecycle calls. tools/list and initialize handshakes are excluded from editing call counts.",
                  "original_exploratory_C": {"observations": 25, "submissions": 20, "save": 5, "replay": 5, "search": 1, "total_mcp_calls": 56},
                  "limitation": "No model timing, context, cost or comparative performance claim. Exact symbols and operation payloads are supplied by the archived exploratory transcript."}
        (destination / "requests_responses.json").write_text(json.dumps({"editing": editor.events, "lifecycle": lifecycle.events}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        (destination / "results.json").write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-finalize", action="store_true", help="Use trusted scalar finalization after all five editing batches")
    parser.add_argument("--editor-v2", action="store_true", help="Exercise observed_v2 schemas/receipts over negotiated 2025 MCP; requires --host-finalize")
    args = parser.parse_args()
    result = run(args.output, host_finalize=args.host_finalize, editor_v2=args.editor_v2)
    print(json.dumps({"passed": result["oracle"]["complete_correct"], "behavioral": "20/20",
                      "editing_tools_call_total": result["editing_tools_call_total"], "profiles": result["profiles"], "model_invocations": 0}, indent=2))
