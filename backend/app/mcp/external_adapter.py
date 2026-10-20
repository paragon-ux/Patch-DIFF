"""External MCP stdio adapter for the PatchDIFF internal tool registry.

The adapter is intentionally thin: transport concerns live here, while all
PatchDIFF behavior remains owned by the existing internal registry/tool layer.
"""

from __future__ import annotations

import copy
import inspect
import json
import sys
from types import NoneType, UnionType
from typing import Any, TextIO, get_args, get_origin, get_type_hints

from app.mcp import tools as _registered_tools  # noqa: F401 - imports register tool handlers
from app.mcp.server import registry
from app.pdcp.typed import TYPED_EDIT_JSON_SCHEMA


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "patchdiff-mvp"
SERVER_VERSION = "0.2.0"
EXPECTED_TOOL_NAMES = registry.names()

TOOL_DESCRIPTIONS: dict[str, str] = {
    "patchdiff_handle_upload": "Initialize a canonical PatchDIFF target from uploaded document content.",
    "patchdiff_initialize_target": "Initialize a canonical PatchDIFF target.",
    "patchdiff_build_prompt_context": "Convenience: build prompt context (bounded target PREFIX, not retrieval; see context_truncated). Prefer patchdiff_read_target / patchdiff_find_occurrences.",
    "patchdiff_submit_pdcp": "Submit untrusted legacy .pdcp (v0.2.3) content through deterministic validation and commit services.",
    "patchdiff_submit_edits": "Submit a typed edit transaction (exact match/replace strings as fields). Requires expected_target_version and/or expected_current_hash. Supports optional client_request_id idempotency. Same validation, atomic commit and logging as .pdcp.",
    "patchdiff_read_target": "Authoritative bounded read of canonical target text by code-point offset, with version, hash, and next_start continuation.",
    "patchdiff_find_occurrences": "List exact occurrences of a string (overlapping counted) with offsets, bounded context, 1-based occurrence_index, and start_occurrence/max_results pagination.",
    "patchdiff_get_regeneration_context": "DEPRECATED: host-owned retry replaces this. Return regeneration context for a rejected attempt.",
    "patchdiff_build_regeneration_prompt": "DEPRECATED: host-owned retry replaces this. Build a regeneration prompt from a rejected attempt.",
    "patchdiff_request_regeneration": "DEPRECATED: use patchdiff_submit_edits with parent_pdcp_log_id. Submit regenerated .pdcp content as a new attempt (guards pass through when supplied).",
    "patchdiff_save": "Create a SAVE snapshot and advance the editing cycle without mutating target content.",
    "patchdiff_replay": "Replay accepted logs (dispatching on protocol_version and runtime_version), verify hash/version chain, and report component-level materialized_state_checks.",
    "patchdiff_export_target": "Export the current canonical target content and metadata.",
    "patchdiff_get_target": "Return the current canonical target state.",
    "patchdiff_get_pdcp_log": "Return a bounded, newest-first page of append-only attempts (accepted and rejected); filter by status, content_hash, or client_request_id.",
    "patchdiff_get_manifest_ledger": "Return accepted-only manifest ledger entries for a target.",
}


class ExternalMCPAdapter:
    """Minimal JSON-RPC MCP adapter backed by the internal PatchDIFF registry."""

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": TOOL_DESCRIPTIONS.get(name, f"PatchDIFF tool {name}."),
                "inputSchema": _input_schema_for(name),
            }
            for name in registry.names()
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in registry.names():
            return _tool_error(f"Unknown PatchDIFF MCP tool: {name}")
        try:
            payload = registry.call(name, **(arguments or {}))
        except TypeError as exc:
            return _tool_error(f"Invalid arguments for {name}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive transport boundary
            return _tool_error(f"PatchDIFF MCP tool failed: {exc}")
        return _tool_result(payload)

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")

        if method in {"notifications/initialized", "initialized"}:
            return None
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _rpc_error(request_id, -32600, "Invalid JSON-RPC request.")

        if method == "initialize":
            return _rpc_result(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method == "tools/list":
            return _rpc_result(request_id, {"tools": self.list_tools()})
        if method == "tools/call":
            params = request.get("params")
            if params is None:
                params = {}
            if not isinstance(params, dict):
                return _rpc_error(request_id, -32602, "tools/call params must be an object.")
            name = params.get("name")
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return _rpc_error(request_id, -32602, "tools/call requires name and object arguments.")
            return _rpc_result(request_id, self.call_tool(name, arguments))
        if method == "resources/list":
            return _rpc_result(request_id, {"resources": []})
        if method == "prompts/list":
            return _rpc_result(request_id, {"prompts": []})
        return _rpc_error(request_id, -32601, f"Unsupported MCP method: {method}")


def serve_stdio(input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> None:
    """Serve newline-delimited JSON-RPC requests over stdio."""

    adapter = ExternalMCPAdapter()
    for line in input_stream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _rpc_error(None, -32700, f"Parse error: {exc.msg}")
        else:
            if not isinstance(request, dict):
                response = _rpc_error(None, -32600, "JSON-RPC message must be an object.")
            else:
                response = adapter.handle_request(request)
        if response is not None:
            output_stream.write(json.dumps(response, separators=(",", ":"), sort_keys=True) + "\n")
            output_stream.flush()


def main() -> None:
    serve_stdio()


def _input_schema_for(name: str) -> dict[str, Any]:
    handler = registry.handler(name)
    signature = inspect.signature(handler)
    type_hints = get_type_hints(handler)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter_name, parameter in signature.parameters.items():
        if name == "patchdiff_submit_edits" and parameter_name == "edits":
            properties[parameter_name] = {
                "type": "array",
                "minItems": 1,
                "items": copy.deepcopy(TYPED_EDIT_JSON_SCHEMA),
            }
        else:
            properties[parameter_name] = _schema_for_annotation(type_hints.get(parameter_name, parameter.annotation))
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter_name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _schema_for_annotation(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty:
        return {}

    origin = get_origin(annotation)
    if origin in {UnionType, None} and hasattr(annotation, "__args__"):
        args = get_args(annotation)
    elif origin is not None:
        args = get_args(annotation)
    else:
        args = ()

    if args and NoneType in args:
        non_null = [arg for arg in args if arg is not NoneType]
        if len(non_null) == 1:
            schema = _schema_for_annotation(non_null[0])
            schema_type = schema.get("type")
            if isinstance(schema_type, str):
                schema["type"] = [schema_type, "null"]
            return schema

    if origin is list or annotation is list:
        item_schema = _schema_for_annotation(args[0]) if args else {}
        return {"type": "array", "items": item_schema}
    if origin is dict or annotation is dict:
        return {"type": "object"}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is float:
        return {"type": "number"}
    return {}


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
        "isError": False,
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
