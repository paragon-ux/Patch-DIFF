"""Append-only evaluator evidence and budgets; no token estimates or auto retries."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def wire(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(wire(value)).hexdigest()


def redact(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if re.search(r"password|secret|authorization|credential|api[_-]?key|access[_-]?token|cookie", k, re.I)
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
        return re.sub(r"(?i)(bearer\s+|(?:api[_-]?key|password|secret|access_token)[=:]\s*)[^\s,;]+", r"\1[REDACTED]", value)
    return value


class Evidence:
    def __init__(self, path: Path, identity: dict):
        self.file = path.open("x", encoding="utf-8", newline="\n")
        self.identity = identity
        self.sequence = 0
        self.previous = None

    def emit(self, kind: str, **payload):
        record = {**self.identity, "sequence": self.sequence, "previous_sha256": self.previous,
                  "timestamp": datetime.now(timezone.utc).isoformat(), "event": kind, **redact(payload)}
        self.previous = digest(record)
        self.file.write(wire({**record, "sha256": self.previous}).decode() + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())
        self.sequence += 1

    def close(self):
        self.file.close()


def verify_events(path: Path) -> list[dict]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    previous = None
    for i, record in enumerate(records):
        data = {k: v for k, v in record.items() if k != "sha256"}
        if record["sequence"] != i or record["previous_sha256"] != previous or digest(data) != record["sha256"]:
            raise ValueError("Incomplete or altered telemetry chain")
        previous = record["sha256"]
    if not records or records[-1]["event"] != "archive_complete":
        raise ValueError("Incomplete telemetry: no terminal archive record")
    return records


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, conditions: dict, clock=time.monotonic):
        self.conditions = conditions
        self.clock = clock
        self.started = clock()
        self.calls = self.tokens = self.retries = 0
        self.pending: dict[str, dict] = {}

    def deadline_remaining(self):
        remaining = self.conditions["wall_clock_budget_seconds"] - (self.clock() - self.started)
        if remaining <= 0:
            raise BudgetExceeded("wall_clock")
        return remaining

    def remaining(self):
        remaining = self.deadline_remaining()
        if self.tokens >= self.conditions["model_token_budget_per_task"]:
            raise BudgetExceeded("actual_model_tokens")
        return remaining

    def usage(self, usage: dict):
        # Provider contract: output includes reasoning; input includes cached tokens.
        # Breakdowns are recorded, never added again to the total.
        for key in ("input_tokens", "output_tokens"):
            if type(usage.get(key)) is not int or usage[key] < 0:
                raise ValueError(f"Missing/invalid actual provider usage: {key}")
        for key, parent in (("cached_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
            if usage.get(key) is not None and (type(usage[key]) is not int or not 0 <= usage[key] <= usage[parent]):
                raise ValueError(f"Invalid provider breakdown: {key}")
        self.tokens += usage["input_tokens"] + usage["output_tokens"]
        if self.tokens > self.conditions["model_token_budget_per_task"]:
            raise BudgetExceeded("actual_model_tokens")

    def tool(self, target: str | None, args: dict, editing: bool):
        self.deadline_remaining()
        if self.calls >= self.conditions["max_tool_calls_per_task"]:
            raise BudgetExceeded("tool_calls")
        self.calls += 1
        previous = self.pending.get(target) if editing else None
        if previous:
            if self.retries >= self.conditions["max_retries_after_rejected_edit_per_task"]:
                raise BudgetExceeded("editing_retries")
            self.retries += 1
            if previous["outcome"] == "lost_response" and (not args.get("client_request_id") or digest(args) != previous["arguments_sha256"]):
                raise ValueError("Lost MCP response requires explicit identical request-key retry")
            if previous.get("pdcp_log_id") and (args.get("parent_pdcp_log_id") != previous["pdcp_log_id"]
                                                or args.get("attempt") != previous["attempt"] + 1):
                raise ValueError("Rejected MCP retry requires parent log and incremented attempt")
        return previous

    def outcome(self, target, args, result, outcome):
        if outcome in {"rejected", "lost_response"}:
            self.pending[target] = {"outcome": outcome, "arguments_sha256": digest(args),
                                    "request_key": args.get("client_request_id"),
                                    "pdcp_log_id": result.get("pdcp_log_id"), "attempt": args.get("attempt", 1)}
        else:
            self.pending.pop(target, None)
