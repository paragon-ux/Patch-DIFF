"""Local JSON-lines lifecycle fixture. No SDK, network, model or solved output."""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--description", type=Path, required=True)
parser.add_argument("--trace", type=Path, required=True)
parser.add_argument("--mode", choices=["noop", "timeout", "exit"], default="noop")
args = parser.parse_args()
description = json.loads(args.description.read_text(encoding="utf-8"))
provider_session = str(uuid.uuid4())
context_id = str(uuid.uuid4())
turns = 0


def record(event, **data):
    with args.trace.open("a", encoding="utf-8", newline="\n") as trace:
        trace.write(json.dumps({"event": event, "pid": os.getpid(), "provider_session": provider_session, **data}) + "\n")


record("started")
for line in sys.stdin:
    request = json.loads(line)
    method, params = request["method"], request["params"]
    if method == "host/describe":
        record("describe")
        result = description
    elif method == "host/open":
        record("open", context_id=context_id, arm=params["arm"], replicate=params["replicate"])
        result = {"context_id": context_id, "permissions_applied": True, "fresh_context": True}
    elif method == "host/turn":
        turns += 1
        record("turn", context_id=params["context_id"], limits=params["limits"], tool_results=params["tool_results"])
        if args.mode != "noop" and turns == 2:
            if args.mode == "exit":
                os._exit(23)
            time.sleep(60)  # Parent deadline must kill/reap this process.
        result = {"provider": "SYNTHETIC-NO-PROVIDER", "model_id": "SYNTHETIC-NO-MODEL", "reasoning": "High",
                  "provider_request_id": str(uuid.uuid4()), "synthetic": True,
                  "usage": {"input_tokens": 1, "output_tokens": 1, "cached_tokens": 0, "reasoning_tokens": 0},
                  "finished": args.mode == "noop", "tool_calls": []}
        if args.mode != "noop" and turns == 1:
            result["tool_calls"] = [{"id": "synthetic-native-noop", "name": "edit_file", "arguments": {
                "Path": "schema_defs.py", "Target": "from __future__ import annotations",
                "Replacement": "from __future__ import annotations"}}]
    elif method == "host/close":
        record("close", context_id=params["context_id"])
        result = {"closed": True}
    else:
        raise ValueError("Unexpected fixture method")
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
record("eof")
