"""Primary-study controller. Default is offline; never selects a live model.

--dry-run-synthetic uses a deterministic non-model host and REAL disposable MCP
databases. Its outputs are infrastructure evidence, never comparative results.
--execute additionally requires a reviewed clean commit, external Gate 2 review,
verified owner host bridge and explicit execution_enabled configuration.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Permit the documented direct script command as well as python -m.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.structural_retest import evaluate, prepare
from evaluation.structural_retest.host_adapter import BridgeHost, TOOLS
from evaluation.structural_retest.mcp_session import MCPSession, REPO, disposable_database
from evaluation.structural_retest.native import NativeTools, verify_binding
from evaluation.structural_retest.preflight import validate_approval, validate_host
from evaluation.structural_retest.synthetic import SyntheticHost
from evaluation.structural_retest.telemetry import Budget, BudgetExceeded, Evidence, digest, redact, verify_events, wire

ROOT = Path(__file__).resolve().parent
VERSION = "primary-controller/1"
STAGES = ("PREPARED", "PREFLIGHT_VERIFIED", "INITIALIZED", "AGENT_RUNNING",
          "AGENT_FINISHED_OR_BUDGET_EXHAUSTED", "SAVE_AND_EXPORT", "REPLAY_VALIDATION",
          "HIDDEN_ORACLE_EVALUATION", "EVIDENCE_ARCHIVED")
EDIT_TOOLS = {"edit_file", "patchdiff_submit_edits", "patchdiff_submit_observed_operations"}


def inputs(manifest):
    return prepare.validate_inputs(manifest) + ([] if manifest.get("controller", {}).get("source_sha256") else ["Missing controller pins"])


class Run:
    def __init__(self, destination, arm, replicate, manifest, host, description, database_factory=disposable_database,
                 session_factory=MCPSession, native_factory=NativeTools, clock=time.monotonic):
        self.path, self.arm, self.replicate = destination, arm, replicate
        self.manifest, self.host, self.description = manifest, host, description
        self.database_factory, self.session_factory, self.native_factory = database_factory, session_factory, native_factory
        self.clock = clock
        self.targets, self.observations, self.tool_ids = {}, set(), set()
        self.session = self.context_id = None
        self.stage = "PREPARED"
        self.path.mkdir(parents=True, exist_ok=False)
        self.visible = self.path / "agent-files"
        self.visible.mkdir()
        self.exports = self.path / "exports"
        self.exports.mkdir()
        self.sources = {Path(a["path"]).name: (ROOT / a["path"]).read_bytes()
                        for a in manifest["studies"]["primary"]["artifacts"] if a["role"] == "fixture"}
        self.evidence = Evidence(self.path / "events.jsonl", {"run_id": self.path.name, "arm": arm, "replicate": replicate,
                                 "synthetic": host.synthetic, "manifest_sha256": digest(manifest), "controller_version": VERSION})
        self.result = {"run_id": self.path.name, "arm": arm, "replicate": replicate, "synthetic": host.synthetic,
                       "measured_model_invocations": 0, "outcome": "pending", "failures": []}

    def advance(self, stage):
        if STAGES.index(stage) != STAGES.index(self.stage) + 1:
            raise ValueError("Illegal controller stage transition")
        self.stage = stage
        self.evidence.emit("stage", stage=stage)

    def failure(self, exc):
        failure = {"stage": self.stage, "classification": type(exc).__name__, "detail": str(exc)}
        self.result["failures"].append(redact(failure))
        self.evidence.emit("failure", **failure)

    async def tool_call(self, name, args, *, agent=False, call_id=None):
        call_id = call_id or str(uuid.uuid4())
        started = self.clock()
        category = ("waymark_discovery" if name == "patchdiff_observe_scope" else "native" if name in TOOLS["A"]
                    else "mcp_database_initialization" if name == "patchdiff_initialize_target" else
                    "mcp_transaction" if name in EDIT_TOOLS else "mcp_control")
        self.evidence.emit("tool_start", tool_name=name, call_id=call_id, agent=agent, category=category,
                           arguments=args, arguments_utf8_bytes=len(wire(args)), arguments_sha256=digest(args),
                           attempt=args.get("attempt", 1), request_key=args.get("client_request_id"))
        result, outcome = {}, "error"
        target = args.get("target_file_id", args.get("Path"))
        if self.arm == "A" and name == "edit_file" and isinstance(target, str):
            target = str((self.visible / target).resolve())
        editing = name in EDIT_TOOLS
        admitted = False
        try:
            if agent:
                if call_id in self.tool_ids:
                    raise PermissionError("Duplicate host tool call ID")
                self.tool_ids.add(call_id)
                previous = self.budget.tool(target, args, editing)
                if name not in TOOLS[self.arm]:
                    raise PermissionError("Tool not in arm allowlist")
                if self.arm != "A" and target not in self.targets.values():
                    raise PermissionError("Target does not belong to this arm/replicate")
                if self.arm == "C" and editing and args.get("observation_id") not in self.observations:
                    raise PermissionError("Observation not issued to this arm context")
                if self.arm != "A" and editing and not args.get("client_request_id"):
                    raise ValueError("MCP editing requires explicit request key")
                if previous and previous["outcome"] == "lost_response" and self.session.process is not None and self.session.process.returncode is not None:
                    self.evidence.emit("explicit_retry_reconnect", request_key=args["client_request_id"])
                    await asyncio.wait_for(self.session.start(), self.budget.remaining())
                timeout = min(self.budget.deadline_remaining(), self.manifest["conditions"]["tool_timeout_seconds"])
            else:
                timeout = self.manifest["conditions"]["tool_timeout_seconds"]
            admitted = True
            action = self.native.call(name, args) if self.arm == "A" else self.session.call(name, args)
            result = await asyncio.wait_for(action, timeout)
            outcome = result.get("status", "ok")
            if outcome in {"invalid_argument", "not_found", "error"}:
                raise ValueError("Tool returned " + outcome)
            if name == "patchdiff_observe_scope" and result.get("observation_id"):
                self.observations.add(result["observation_id"])
            return result
        except PermissionError as exc:
            outcome = "unauthorized_rejected"
            self.failure(exc)
            return {"status": outcome, "error": str(exc)}
        except (TimeoutError, ConnectionError) as exc:
            outcome = "lost_response" if editing and self.arm != "A" else "timeout_or_transport_error"
            result = {"status": outcome, "error": type(exc).__name__}
            self.failure(exc)
            if agent:
                return result
            raise
        finally:
            if agent and editing and admitted and outcome not in {"error", "unauthorized_rejected"}:
                self.budget.outcome(target, args, result, outcome)
            self.evidence.emit("tool_end", tool_name=name, call_id=call_id, outcome=outcome,
                               duration_seconds=self.clock() - started, result=result,
                               result_utf8_bytes=len(wire(result)), result_sha256=digest(result),
                               retry_count=self.budget.retries if agent else None,
                               component_timings_unavailable=["database_internal", "waymark_engine_internal"] if self.arm != "A" else [])

    async def agent_loop(self):
        spec = {"arm": self.arm, "replicate": self.replicate,
                "task": (ROOT / "primary/prompts/TASK.md").read_text(encoding="utf-8"),
                "tool_instructions": (ROOT / f"primary/prompts/tools_{self.arm}.md").read_text(encoding="utf-8"),
                "allowed_tools": sorted(TOOLS[self.arm]), "targets": self.targets,
                "workspace": str(self.visible) if self.arm == "A" else None,
                "permissions": {"broker_only_tools": True, "filesystem_denied": True, "network_denied": True,
                                "evaluator_access": False, "other_context_access": False},
                "expected_configuration": self.description["arms"][self.arm]}
        self.context_id = await asyncio.wait_for(self.host.open_context(spec), 30)
        if self.context_id in self.used_contexts:
            raise ValueError("Host reused a context")
        self.used_contexts.add(self.context_id)
        self.evidence.emit("context_opened", context_id=self.context_id, visible_specification=spec)
        self.budget = Budget(self.manifest["conditions"], self.clock)
        results = []
        while True:
            remaining = self.budget.remaining()
            limits = {"deadline_seconds": remaining, "remaining_total_tokens": self.manifest["conditions"]["model_token_budget_per_task"] - self.budget.tokens,
                      "output_limit": min(self.description["arms"][self.arm]["output_limit"], self.manifest["conditions"]["model_token_budget_per_task"] - self.budget.tokens),
                      "automatic_transport_retries": 0}
            self.evidence.emit("provider_request", context_id=self.context_id, limits=limits, tool_results_sha256=digest(results))
            started = self.clock()
            if not self.host.synthetic:
                self.result["measured_model_invocations"] += 1
            response = await asyncio.wait_for(self.host.turn(self.context_id, results, limits), remaining)
            usage = response.get("usage", {})
            self.evidence.emit("provider_response", metadata=response, duration_seconds=self.clock() - started,
                               usage=usage, missing_usage_fields=[k for k in ("input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens") if usage.get(k) is None])
            self.budget.usage(usage)
            info = self.description["arms"][self.arm]
            if (response.get("model_id") != info["exact_provider_model_id"] or response.get("provider") != info["provider"]
                    or response.get("reasoning") != info["effective_reasoning_setting"] or response.get("synthetic") is not self.host.synthetic
                    or not response.get("provider_request_id")):
                raise ValueError("Provider response identity/setting/metadata mismatch")
            self.budget.deadline_remaining()
            results = []
            for call in response.get("tool_calls", []):
                result = await self.tool_call(call["name"], call["arguments"], agent=True, call_id=call["id"])
                results.append({"call_id": call["id"], "result": result})
                self.budget.deadline_remaining()
            if response.get("finished") is True:
                break

    async def audit(self, target_id):
        history = {}
        for name, sequence in (("patchdiff_get_pdcp_log", "log_sequence"), ("patchdiff_get_manifest_ledger", "ledger_sequence")):
            cursor, rows = None, []
            while True:
                args = {"target_file_id": target_id, "limit": 100}
                if name == "patchdiff_get_pdcp_log":
                    args["include_content"] = True
                else:
                    args["include_previous_cycles"] = True
                if cursor is not None:
                    args["before_sequence"] = cursor
                result = await self.tool_call(name, args)
                entries = result.get("entries")
                if not isinstance(entries, list):
                    raise ValueError("Incomplete MCP audit page")
                rows.extend(entries)
                if not result.get("has_more"):
                    break
                next_cursor = result.get("next_sequence")
                if not next_cursor or (cursor is not None and next_cursor >= cursor) or not entries:
                    raise ValueError("Nonprogressing audit cursor")
                cursor = next_cursor
            if len({row[sequence] for row in rows}) != len(rows):
                raise ValueError("Duplicate audit entries")
            if name == "patchdiff_get_pdcp_log":
                for row in rows:
                    if row.get("pdcp_content") is None:
                        page = await self.tool_call(name, {"target_file_id": target_id, "limit": 1,
                                                          "before_sequence": row[sequence] + 1, "include_content": True})
                        if len(page.get("entries", [])) != 1 or page["entries"][0]["pdcp_log_id"] != row["pdcp_log_id"] or page["entries"][0].get("pdcp_content") is None:
                            raise ValueError("Audit transaction content missing")
                        row.update(page["entries"][0])
                    if hashlib.sha256(row["pdcp_content"].encode()).hexdigest() != row["pdcp_content_hash"]:
                        raise ValueError("Audit content hash mismatch")
                    if self.arm == "C" and row["status"] == "accepted" and not row.get("diagnostic", {}).get("observation_id"):
                        raise ValueError("Accepted C log lacks observation marker")
            history[name] = rows
        accepted = {row["pdcp_log_id"] for row in history["patchdiff_get_pdcp_log"] if row["status"] == "accepted"}
        ledger_ids = {row["pdcp_log_id"] for row in history["patchdiff_get_manifest_ledger"]}
        if accepted != ledger_ids:
            raise ValueError("Accepted attempts/manifest linkage mismatch")
        self.evidence.emit("audit_integrity", target_file_id=target_id, history=history,
                           observation_linkage="authoritative replay validates accepted scope links; rejected attempts retain request/diagnostic provenance and no accepted linkage")

    async def execute(self, config, used_contexts):
        self.used_contexts = used_contexts
        self.evidence.emit("prepared", frozen_configuration=self.manifest, host_evidence=self.description,
                           original_hashes={name: hashlib.sha256(data).hexdigest() for name, data in self.sources.items()},
                           environment={"python": sys.version, "os": platform.platform(), "executable": sys.executable},
                           external_approval=config.get("verified_approval"))
        try:
            if not self.host.synthetic:
                authorization = config.get("_live_authorization")
                if not isinstance(authorization, LiveAuthorization) or authorization.host_sha256 != digest(self.description):
                    raise ValueError("Live Run requires independently authorized study entry point")
            errors = inputs(self.manifest) + validate_host(self.description, synthetic=self.host.synthetic)
            if errors:
                raise ValueError("; ".join(errors))
            self.advance("PREFLIGHT_VERIFIED")
            started = self.clock()
            if self.arm == "A":
                for name, data in self.sources.items():
                    (self.visible / name).write_bytes(data)
                self.native = self.native_factory(self.visible, set(self.sources), config.get("rtk_path", "rtk"))
                if not self.host.synthetic:
                    binding_errors = await verify_binding(self.description["arms"]["A"]["native_binding"], config.get("rtk_path"))
                    if binding_errors:
                        raise ValueError("; ".join(binding_errors))
            else:
                database_url = await self.database_factory(config["admin_database_url"], self.evidence)
                self.session = self.session_factory(database_url, self.arm)
                self.session.trace = lambda kind, payload, raw: self.evidence.emit(kind, payload=payload, wire_utf8_bytes=len(raw), wire_sha256=hashlib.sha256(raw).hexdigest())
                await asyncio.wait_for(self.session.start(), 30)
                schema_hash = digest(self.session.schemas)
                if not self.host.synthetic and schema_hash != self.description["arms"][self.arm].get("mcp_schema_sha256"):
                    raise ValueError("Actual MCP schemas do not match reviewed host binding")
                self.evidence.emit("mcp_discovery", schema_sha256=schema_hash, schemas=self.session.schemas)
                self.targets = await self.session.initialize(self.sources, self.tool_call)
            self.evidence.emit("initialized", targets=self.targets, cold_startup_seconds=self.clock() - started,
                               strict_observation=self.arm == "C", native_initial_hashes_verified=self.arm == "A")
            self.advance("INITIALIZED")
            self.advance("AGENT_RUNNING")
            try:
                await self.agent_loop()
                self.result["agent_outcome"] = "finished"
            except (BudgetExceeded, TimeoutError) as exc:
                self.result["agent_outcome"] = "budget_exhausted"
                self.failure(exc)
            except Exception as exc:
                self.result["agent_outcome"] = "failed"
                self.failure(exc)
            finally:
                if self.context_id:
                    await asyncio.wait_for(self.host.close_context(self.context_id), 30)
                    self.evidence.emit("context_closed", context_id=self.context_id)
            self.advance("AGENT_FINISHED_OR_BUDGET_EXHAUSTED")
            self.advance("SAVE_AND_EXPORT")
            if self.arm == "A":
                # Preserve unexpected entries too: the oracle, not the exporter, rejects them.
                shutil.copytree(self.visible, self.exports, dirs_exist_ok=True, symlinks=True)
            else:
                for name, target_id in self.targets.items():
                    target = await self.tool_call("patchdiff_get_target", {"target_file_id": target_id})
                    saved = await self.tool_call("patchdiff_save", {"target_file_id": target_id, "expected_current_hash": target["current_hash"], "expected_target_version": target["version"]})
                    if saved.get("status") != "saved":
                        raise ValueError("SAVE failed")
                    exported = await self.tool_call("patchdiff_export_target", {"target_file_id": target_id, "format": "original_eol"})
                    content = exported.get("content", "").encode("utf-8")
                    if (exported.get("status") != "ok" or exported.get("content_sha256") != hashlib.sha256(content).hexdigest()
                            or exported.get("source_line_endings", {}).get("source_sha256") != hashlib.sha256(self.sources[name]).hexdigest()):
                        raise ValueError("Export hash/EOL restoration failed")
                    (self.exports / name).write_bytes(content)
            self.advance("REPLAY_VALIDATION")
            for target_id in self.targets.values():
                replay = await self.tool_call("patchdiff_replay", {"target_file_id": target_id})
                if (replay.get("status") != "success" or replay.get("materialized_state_matches") is not True
                        or set(replay.get("materialized_state_checks", {})) != {"content_matches", "stored_hash_matches", "recomputed_hash_matches", "version_matches"}
                        or not all(replay["materialized_state_checks"].values())):
                    raise ValueError("Authoritative replay/materialized state/observation integrity failed")
                await self.audit(target_id)
            self.advance("HIDDEN_ORACLE_EVALUATION")
            oracle = evaluate.complete_primary(self.exports)
            self.evidence.emit("hidden_oracle", result=oracle)
            self.result["oracle"] = oracle
            self.result["outcome"] = "passed" if oracle["complete_correct"] and not self.result["failures"] else "failed"
        except Exception as exc:
            self.failure(exc)
            self.result["outcome"] = "failed"
        finally:
            if self.session:
                await self.session.close()
            self.result["last_stage"] = self.stage
            if self.stage == "HIDDEN_ORACLE_EVALUATION":
                self.advance("EVIDENCE_ARCHIVED")
            else:
                self.evidence.emit("failure_archive", failed_stage=self.stage)
            self.result["archived"] = True
            self.evidence.emit("artifact_inventory", files={p.relative_to(self.path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in self.path.rglob("*") if p.is_file() and not p.is_symlink() and p.name != "events.jsonl"})
            self.evidence.emit("archive_complete", result=self.result)
            self.evidence.close()
            verify_events(self.path / "events.jsonl")
            (self.path / "result.json").write_bytes(wire(self.result) + b"\n")
        return self.result


async def tool_binding_errors(description, config, schema_sha256):
    errors = []
    for arm in "BC":
        if description.get("arms", {}).get(arm, {}).get("mcp_schema_sha256") != schema_sha256:
            errors.append(f"{arm}: actual MCP schema differs from reviewed binding")
    errors += await verify_binding(description.get("arms", {}).get("A", {}).get("native_binding"), config.get("rtk_path"))
    return errors


async def run_study(destination, manifest, host, config, **factories):
    description = await asyncio.wait_for(host.describe(), 30)
    if not host.synthetic:
        if config.get("execution_enabled") is not True or description != config.get("host_evidence") or validate_host(description):
            raise ValueError("Live host execution disabled/unverified")
        approval = validate_approval(config.get("approval_receipt", {}), reviewed_checkout(),
                                     hashlib.sha256((ROOT / "manifest.json").read_bytes()).hexdigest(), digest(description))
        if manifest != json.loads((ROOT / "manifest.json").read_text(encoding="utf-8")):
            raise ValueError("Live manifest differs from reviewed bytes")
        config = {**config, "_live_authorization": LiveAuthorization(digest(description), approval)}
        # Verify ALL arm bindings before the first measured context, not only
        # when its arm is eventually reached in the balanced order.
        discovery = MCPSession(config["admin_database_url"], "C")
        try:
            await asyncio.wait_for(discovery.start(), 30)
            binding_errors = await tool_binding_errors(description, config, digest(discovery.schemas))
            if binding_errors:
                raise ValueError("; ".join(binding_errors))
        finally:
            await discovery.close()
    destination.mkdir(parents=True, exist_ok=False)
    plan = [{"replicate": replicate, "arm": arm, "run_id": f"r{replicate}-{arm}", "outcome": "not_started"}
            for replicate, order in enumerate(manifest["conditions"]["arm_orders"], 1) for arm in order]
    (destination / "plan.json").write_bytes(wire({"synthetic": host.synthetic, "runs": plan}) + b"\n")
    results, contexts = [], set()
    for item in plan:
        run = Run(destination / item["run_id"], item["arm"], item["replicate"], manifest, host, description, **factories)
        result = await run.execute(config, contexts)
        results.append(result)
        # Append one result for EVERY scheduled run, including failed preflight.
        with (destination / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as out:
            out.write(wire(result).decode() + "\n")
    summary = {"synthetic": host.synthetic, "comparative_results": False if host.synthetic else True,
               "scheduled": len(plan), "archived": len(results), "measured_model_invocations": sum(r["measured_model_invocations"] for r in results),
               "results": results, "gate_2": "closed" if host.synthetic else "external_approval_required"}
    (destination / "summary.json").write_bytes(wire(summary) + b"\n")
    return summary


def reviewed_checkout():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip():
        raise ValueError("Live execution requires a clean reviewed checkout")
    return commit


class LiveAuthorization:
    def __init__(self, host_sha256, approval):
        self.host_sha256, self.approval = host_sha256, approval


async def cli(args):
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    errors = inputs(manifest)
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    if args.check_inputs:
        print(json.dumps({"errors": errors, "live_model_invocations": 0}, indent=2))
        return bool(errors)
    if args.preflight_offline:
        errors += validate_host(config.get("host_evidence", {}))
        # tools/list is a real stdio MCP call; it does not connect to Postgres.
        session = MCPSession(os.environ.get("PATCHDIFF_DATABASE_URL", "postgresql+psycopg://unused:unused@localhost/unused"), "C")
        try:
            await asyncio.wait_for(session.start(), 30)
            schema_sha = digest(session.schemas)
            errors += await tool_binding_errors(config.get("host_evidence", {}), config, schema_sha)
        finally:
            await session.close()
        print(json.dumps({"errors": errors, "mcp_schema_sha256": schema_sha, "live_model_invocations": 0,
                          "execution": "blocked" if errors else "requires_external_approval_and_execute"}, indent=2))
        return 2 if errors else 0
    if errors:
        raise ValueError("; ".join(errors))
    if not args.destination:
        raise ValueError("New --destination required")
    config["admin_database_url"] = os.environ.get("PATCHDIFF_RETEST_ADMIN_URL", "")
    if not config["admin_database_url"]:
        raise ValueError("PATCHDIFF_RETEST_ADMIN_URL required (never place credentials in config)")
    if args.dry_run_synthetic:
        host = SyntheticHost()
    else:
        if config.get("execution_enabled") is not True or not args.approval:
            raise ValueError("Live execution disabled: explicit configuration and external approval required")
        command = config.get("host_bridge_command")
        if not isinstance(command, list) or not command or not all(isinstance(s, str) for s in command):
            raise ValueError("Owner-reviewed host bridge command required")
        host = BridgeHost(command)
        await host.start()
        description = await asyncio.wait_for(host.describe(), 30)
        host_errors = validate_host(description)
        if host_errors or description != config.get("host_evidence"):
            await host.close()
            raise ValueError("Unverified/changed real host evidence: " + "; ".join(host_errors))
        approval = validate_approval(json.loads(args.approval.read_text()), reviewed_checkout(),
                                     hashlib.sha256((ROOT / "manifest.json").read_bytes()).hexdigest(), digest(description))
        config["verified_approval"] = approval
        config["approval_receipt"] = json.loads(args.approval.read_text())
    try:
        summary = await run_study(args.destination, manifest, host, config)
        print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
        # Synthetic no-op host MUST fail correctness: this is not a solved run.
        return 0 if host.synthetic and summary["measured_model_invocations"] == 0 and summary["archived"] == 9 else int(any(r["outcome"] != "passed" for r in summary["results"]))
    finally:
        if isinstance(host, BridgeHost):
            await host.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for option in ("check-inputs", "preflight-offline", "dry-run-synthetic", "execute"):
        mode.add_argument("--" + option, action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--destination", type=Path)
    try:
        raise SystemExit(asyncio.run(cli(parser.parse_args())))
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"error": redact(str(exc)), "execution": "refused"}), file=sys.stderr)
        raise SystemExit(2)
