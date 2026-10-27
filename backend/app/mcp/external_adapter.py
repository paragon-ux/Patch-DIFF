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
from app.pdcp.operations import OPERATION_JSON_SCHEMA, OPERATIONS_PROTOCOL_VERSION
from app.pdcp.replacement import MAX_REPLACEMENT_BYTES, MAX_REPLACEMENT_CHARS, REPLACEMENT_PROTOCOL_VERSION
from app.core.line_endings import EXPORT_FORMATS
from app.core.versions import OPERATIONS_RUNTIME_VERSION, REPLACEMENT_RUNTIME_VERSION, SPAN_CONTEXT_RUNTIME_VERSION


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "patchdiff-mvp"
SERVER_VERSION = "0.2.2"
EXPECTED_TOOL_NAMES = registry.names()

_GUARD_RULE = " Requires expected_target_version and/or expected_current_hash; every supplied guard is checked."
_CODE_POINTS = " Offsets are Unicode code points of canonical LF text; UTF-16 hosts such as JavaScript must convert."

TOOL_DESCRIPTIONS: dict[str, str] = {
    "patchdiff_handle_upload": "Initialize a canonical PatchDIFF target from uploaded document content.",
    "patchdiff_initialize_target": "Initialize a canonical PatchDIFF target.",
    "patchdiff_build_prompt_context": "Convenience: build prompt context (bounded target PREFIX, not retrieval; see context_truncated). Prefer patchdiff_read_target / patchdiff_find_occurrences.",
    "patchdiff_submit_pdcp": "Submit untrusted legacy .pdcp (v0.2.3) content through deterministic validation and commit services.",
    "patchdiff_submit_operations": "Submit guarded patchdiff-tx/2 ordered match/span operations, using sequential canonical code-point spans and exact expected_text. Empty spans insert with empty expected_text. "
                                   "Spans refer to the text after earlier operations; for several edits, use descending offsets. "
                                   f"Uses immutable runtime {OPERATIONS_RUNTIME_VERSION}; no replace_all. Optional span expected_before/expected_after "
                                   f"check the exact adjacent text and record runtime {SPAN_CONTEXT_RUNTIME_VERSION}." + _GUARD_RULE + _CODE_POINTS,
    "patchdiff_submit_edits": "Submit a typed edit transaction (exact match/replace strings as fields). Edits apply sequentially: occurrence_index counts the text after earlier edits, so find_occurrences indexes are only valid for the first edit."
                              + _GUARD_RULE + " Supports optional client_request_id idempotency. Same validation, atomic commit and logging as .pdcp.",
    "patchdiff_read_target": "Authoritative bounded read of canonical target text by code-point offset, with version, hash, and next_start continuation." + _CODE_POINTS,
    "patchdiff_submit_replacement": f"Submit a sole guarded replace_all as {REPLACEMENT_PROTOCOL_VERSION}, immutable runtime "
                                    f"{REPLACEMENT_RUNTIME_VERSION}. Fresh raw and canonical replacement limits: "
                                    f"{MAX_REPLACEMENT_CHARS:,} code points and {MAX_REPLACEMENT_BYTES:,} UTF-8 bytes, inclusive. "
                                    "Empty text allowed. Existing-key recovery precedes admission." + _GUARD_RULE,
    "patchdiff_read_lines": "Read an inclusive one-based LF line range from one observed version/hash. Trailing LF creates a final empty line. offset/next_offset are code points within the selected range and next_start is the absolute continuation; include_line_starts lists absolute line offsets. Text defaults to 4000 and caps at 8000. Each page is a new observation." + _CODE_POINTS,
    "patchdiff_preview": "Advisory fresh-proposal evaluation without audit, request keys, writes or row locks. Explicit format 0.2.3, patchdiff-tx/1, patchdiff-tx/2 or patchdiff-tx/3; submit must recheck guards. Prefer version guards to detect ABA changes.",
    "patchdiff_find_occurrences": "List exact occurrences of a string (overlapping counted) with offsets, bounded context, 1-based occurrence_index, and start_occurrence/max_results pagination. Indexes describe the current target, which a transaction's first edit sees." + _CODE_POINTS,
    "patchdiff_get_regeneration_context": "DEPRECATED: host-owned retry replaces this. Return regeneration context for a rejected attempt.",
    "patchdiff_build_regeneration_prompt": "DEPRECATED: host-owned retry replaces this. Build a regeneration prompt from a rejected attempt.",
    "patchdiff_request_regeneration": "DEPRECATED: use patchdiff_submit_edits with parent_pdcp_log_id. Submit regenerated .pdcp content as a new attempt (guards pass through when supplied).",
    "patchdiff_save": "Create a SAVE snapshot and advance the editing cycle without mutating target content. Optional expected_target_version and expected_current_hash guards; prefer the version guard.",
    "patchdiff_replay": "Replay accepted logs (dispatching on protocol_version and runtime_version), verify hash/version chain, and report component-level materialized_state_checks.",
    "patchdiff_export_target": "Export the current target content and metadata. format: original_text (default, legacy alias of canonical LF), canonical_lf, crlf, or original_eol (restore the uniform line endings recorded at upload).",
    "patchdiff_get_target": "Return the current canonical target state, including line endings recorded at upload.",
    "patchdiff_get_pdcp_log": "Return bounded newest-first attempts with has_more/next_sequence; filter by status, content_hash, or exact stored client_request_id.",
    "patchdiff_get_manifest_ledger": "Return the newest bounded ledger page displayed oldest-first, with has_more/next_sequence for backward traversal.",
    "patchdiff_observe_scope": "Discover structural symbols via pinned Waymark Engine or select a unique symbol scope to issue a server-persisted observation_id and bounded canonical text slice." + _CODE_POINTS,
    "patchdiff_submit_observed_operations": "Submit guarded patchdiff-tx/2 match/span operations restricted to a server-issued observed symbol scope. Requires observation_id, expected_target_version, and expected_current_hash. Zero-width insertions must be strictly inside the sequential scope and carry nonempty expected_before and expected_after guards matching adjacent text entirely inside that scope; either boundary rejects." + _CODE_POINTS,
}

# Illustrative resources; hosts bind real IDs, guards, parents and returned cursors.
_EXAMPLE_TARGET = "11111111-1111-4111-8111-111111111111"
TOOL_EXAMPLES: dict[str, list[dict[str, Any]]] = {
    "patchdiff_submit_edits": [
        {"target_file_id": _EXAMPLE_TARGET, "intent": "Rename the second alpha", "expected_target_version": 0,
         "client_request_id": "example-accept", "edits": [{"match": "alpha", "replace": "beta", "occurrence_index": 2}]},
        {"target_file_id": _EXAMPLE_TARGET, "intent": "Demonstrate a missing match", "expected_target_version": 1,
         "edits": [{"match": "missing phrase", "replace": "present"}]},
        {"target_file_id": _EXAMPLE_TARGET, "intent": "Retry using observed exact text", "expected_target_version": 1,
         "parent_pdcp_log_id": "22222222-2222-4222-8222-222222222222", "attempt": 1,
         "edits": [{"match": "beta", "replace": "gamma"}]},
    ],
    "patchdiff_read_target": [{"target_file_id": _EXAMPLE_TARGET, "start": 0, "length": 120}],
    "patchdiff_find_occurrences": [{"target_file_id": _EXAMPLE_TARGET, "text": "alpha", "context_chars": 20,
                                    "start_occurrence": 1, "max_results": 5}],
    "patchdiff_get_pdcp_log": [{"target_file_id": _EXAMPLE_TARGET, "limit": 2},
                               {"target_file_id": _EXAMPLE_TARGET, "limit": 2, "before_sequence": 3}],
    "patchdiff_get_manifest_ledger": [{"target_file_id": _EXAMPLE_TARGET, "limit": 2},
                                      {"target_file_id": _EXAMPLE_TARGET, "limit": 2, "before_sequence": 3}],
    "patchdiff_submit_operations": [{"target_file_id": _EXAMPLE_TARGET, "intent": "Insert at the beginning",
                                     "expected_target_version": 2,
                                     "operations": [{"op": "span", "start": 0, "end": 0, "expected_text": "", "replace": "Note: "}]}],
    "patchdiff_submit_replacement": [{"target_file_id": _EXAMPLE_TARGET, "intent": "Replace the whole target explicitly",
                                      "expected_target_version": 3, "replacement": "Final text\n"}],
    "patchdiff_read_lines": [{"target_file_id": _EXAMPLE_TARGET, "start_line": 1, "end_line": 1, "max_chars": 120}],
    "patchdiff_preview": [{"target_file_id": _EXAMPLE_TARGET, "format": "patchdiff-tx/1", "intent": "Preview an exact edit",
                           "expected_target_version": 4, "edits": [{"match": "Final", "replace": "Reviewed"}]}],
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
        args = arguments or {}
        argument_error = _argument_error(name, args)
        if argument_error is not None:
            return {"content": [{"type": "text", "text": _dumps(argument_error, sort_keys=True)}], "isError": True}
        try:
            payload = registry.call(name, **args)
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
            # The JSON-RPC line stays ASCII: hosts that mis-decode stdout cannot corrupt text, and
            # U+2028/U+2029/U+0085 cannot split lines. Tool-result text inside it is literal.
            output_stream.write(json.dumps(response, separators=(",", ":"), sort_keys=True) + "\n")
            output_stream.flush()


def main() -> None:
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    serve_stdio()


def _dumps(value: Any, **options: Any) -> str:
    """Tool-result JSON with literal characters; ASCII escapes if strict UTF-8 cannot encode it."""
    text = json.dumps(value, ensure_ascii=False, **options)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(value, ensure_ascii=True, **options)
    return text


def _argument_error(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Structured invalid_argument for unknown or missing tool arguments."""
    parameters = inspect.signature(registry.handler(name)).parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return None
    unknown = sorted(str(key) for key in arguments if key not in parameters)
    missing = sorted(key for key, parameter in parameters.items()
                     if parameter.default is inspect.Parameter.empty and key not in arguments)
    if not unknown and not missing:
        return None
    code = "unknown_argument" if unknown else "missing_argument"
    names = unknown or missing
    adjective = "Unknown" if unknown else "Missing required"
    error: dict[str, Any] = {"status": "invalid_argument", "code": code, "tool": name,
                             "failure_detail": f"{adjective} argument(s) for {name}: {', '.join(names)}."}
    if unknown:
        error["unknown_arguments"] = unknown
    if missing:
        error["missing_arguments"] = missing
    return error


_PARAMETER_DESCRIPTIONS: dict[str, str] = {
    "target_file_id": "Target UUID returned by patchdiff_initialize_target.",
    "intent": "Required advisory summary of the whole transaction; recorded, never used for matching.",
    "expected_target_version": "Version guard from your read; rejects if the target moved. Detects ABA changes that a hash cannot.",
    "expected_current_hash": "Lowercase SHA-256 of canonical LF text from your read; rejects if the content differs.",
    "source": "Advisory submission source label recorded on the attempt.",
    "parent_pdcp_log_id": "UUID of the rejected attempt this proposal retries (same target).",
    "attempt": "Your own 1-based retry counter, recorded as lineage.",
    "regeneration_attempt": "Legacy retry counter, recorded as lineage.",
    "regeneration_source": "Legacy retry source label.",
    "client_request_id": "Idempotency key: 1-128 printable ASCII characters without whitespace. Resend the identical proposal with it to recover a lost response.",
    "pdcp_content": "Raw legacy PDCP 0.2.3 text.",
    "edits": "Ordered exact match/replace edits; each sees the text after earlier edits.",
    "operations": "Ordered match/span operations; span offsets refer to the text after earlier operations.",
    "replacement": "Complete replacement text for the whole target.",
    "start": "Inclusive start offset in code points.",
    "length": "Maximum code points to return (default 4000, cap 8000).",
    "start_line": "First line to read, one-based.",
    "end_line": "Last line to read, inclusive (default: last line).",
    "offset": "Code-point offset within the selected line range; continue with next_offset.",
    "max_chars": "Maximum code points to return (default 4000, cap 8000).",
    "include_line_starts": "Also return absolute start offsets of selected lines that begin on this page.",
    "text": "Exact text to locate; overlapping occurrences are counted.",
    "start_occurrence": "First 1-based occurrence to return; continue with next_occurrence_index.",
    "max_results": "Maximum occurrences to return (cap 200).",
    "format": "Explicit transaction format of the proposal.",
    "export_after_save": "Also return a default export after a successful SAVE.",
    "include_previous_cycles": "Include ledger entries from editing cycles closed by SAVE (default: active cycle only).",
    "status": "Filter attempts by status.",
    "content_hash": "Filter attempts by pdcp_content_hash.",
    "include_content": "Return stored pdcp_content (bounded per page; the first entry is always whole).",
    "pdcp_log_id": "Attempt UUID.",
    "user_request": "Original user request text.",
    "filename": "Document filename.",
    "content": "Initial document text; line endings are normalized to LF and recorded.",
    "content_type": "MIME type or language identifier.",
    "project_id": "Optional project UUID.",
    "context_policy": "Context policy name.",
    "regenerated_pdcp_content": "Regenerated legacy PDCP 0.2.3 text.",
    "query": "Optional case-insensitive substring filter over Waymark symbol names during candidate discovery.",
    "symbol_name": "Exact Waymark symbol name (or parent.name) to select uniquely and issue an observation_id.",
    "kind": "Optional Waymark symbol kind filter (e.g. function, class, method, variable, property, object, section, table_row, code_block).",
    "observation_id": "Server-issued UUID identifying a verified structural scope observation.",
}


def _input_schema_for(name: str) -> dict[str, Any]:
    handler = registry.handler(name)
    signature = inspect.signature(handler)
    type_hints = get_type_hints(handler)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter_name, parameter in signature.parameters.items():
        if name in {"patchdiff_submit_edits", "patchdiff_preview"} and parameter_name == "edits":
            properties[parameter_name] = {
                "type": "array",
                "minItems": 1,
                "items": copy.deepcopy(TYPED_EDIT_JSON_SCHEMA),
            }
        elif name in {"patchdiff_submit_operations", "patchdiff_submit_observed_operations", "patchdiff_preview"} and parameter_name == "operations":
            properties[parameter_name] = {"type": "array", "minItems": 1, "items": copy.deepcopy(OPERATION_JSON_SCHEMA)}
        else:
            properties[parameter_name] = _schema_for_annotation(type_hints.get(parameter_name, parameter.annotation))
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter_name)
    # Advertise structural domains; the service still validates and audits requests.
    for field, constraints in {
        "expected_target_version": {"minimum": 0, "maximum": 2**63 - 1},
        "expected_current_hash": {"pattern": r"^[0-9a-f]{64}(?![\s\S])"},
        "attempt": {"minimum": 1, "maximum": 2**31 - 1},
        "regeneration_attempt": {"minimum": 1, "maximum": 2**31 - 1},
        "client_request_id": {"pattern": r"^[\x21-\x7e]{1,128}(?![\s\S])"},
    }.items():
        if field in properties:
            properties[field].update(constraints)
    if name == "patchdiff_find_occurrences":
        properties["context_chars"].update({
            "minimum": 0, "default": 40,
            "description": "Context on each side in code points; non-negative, capped at 400.",
        })
    if name in {"patchdiff_get_pdcp_log", "patchdiff_get_manifest_ledger"}:
        properties["limit"].update({
            "minimum": 1, "default": 50,
            "description": "Omitted/null selects 50 entries; positive integers are capped at 200.",
        })
        properties["before_sequence"].update({
            "minimum": 1, "description": "Exclusive upper sequence bound; use next_sequence.",
        })
    if name == "patchdiff_get_pdcp_log":
        properties["status"]["enum"] = ["accepted", "rejected", None]
        properties["include_content"]["default"] = False
        properties["client_request_id"].pop("pattern", None)
        properties["client_request_id"]["description"] = "Exact stored request key; historical syntax is accepted."
    if name == "patchdiff_get_manifest_ledger":
        properties["include_previous_cycles"]["default"] = False
    if name == "patchdiff_read_lines":
        for field, minimum in (("start_line", 1), ("end_line", 1), ("offset", 0), ("max_chars", 1)):
            properties[field]["minimum"] = minimum
        properties["start_line"]["default"] = 1
        properties["offset"]["default"] = 0
        properties["include_line_starts"]["default"] = False
    if name == "patchdiff_observe_scope":
        for field, minimum in (("offset", 0), ("max_chars", 1)):
            properties[field]["minimum"] = minimum
        properties["offset"]["default"] = 0
        properties["include_line_starts"]["default"] = False
    if name == "patchdiff_export_target":
        properties["format"].update({"enum": list(EXPORT_FORMATS), "default": "original_text",
                                     "description": "original_text (legacy alias of canonical_lf), canonical_lf, crlf, or original_eol."})
    if name == "patchdiff_save":
        properties["export_after_save"]["default"] = False
    if name == "patchdiff_preview":
        properties["format"]["enum"] = ["0.2.3", "patchdiff-tx/1", "patchdiff-tx/2", "patchdiff-tx/3"]
    if name in {"patchdiff_submit_edits", "patchdiff_submit_operations", "patchdiff_submit_observed_operations", "patchdiff_submit_replacement"}:
        properties["intent"].update({"minLength": 1, "pattern": r"\S"})
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    if name in {"patchdiff_submit_edits", "patchdiff_submit_operations", "patchdiff_submit_replacement"}:
        schema["anyOf"] = [
            {
                "required": ["expected_target_version"],
                "properties": {"expected_target_version": {"type": "integer"}},
            },
            {
                "required": ["expected_current_hash"],
                "properties": {"expected_current_hash": {"type": "string"}},
            },
        ]
    if "include_correlation_id" in properties:
        properties["include_correlation_id"].update({"default": False, "description": "Opt in to a fresh response-only UUID invocation ID; never a retry key."})
    for field, schema_ in properties.items():
        if field in _PARAMETER_DESCRIPTIONS and "description" not in schema_:
            schema_["description"] = _PARAMETER_DESCRIPTIONS[field]
    if name == "patchdiff_preview" and "format" in properties:
        properties["format"]["description"] = "Explicit format: 0.2.3, patchdiff-tx/1, patchdiff-tx/2 or patchdiff-tx/3."
    if name == "patchdiff_submit_operations":
        schema["x-patchdiff-capabilities"] = {
            "protocol_version": OPERATIONS_PROTOCOL_VERSION, "runtime_version": OPERATIONS_RUNTIME_VERSION,
            "operations": ["match", "span"], "coordinates": "sequential_code_points", "zero_length_insertion": True,
            "span_context": {"fields": ["expected_before", "expected_after"], "runtime_version": SPAN_CONTEXT_RUNTIME_VERSION},
        }
    if name == "patchdiff_submit_observed_operations":
        span_schema = properties["operations"]["items"]["oneOf"][1]
        span_schema["description"] = (
            "Nonempty spans must stay within the sequential observed scope. Insertions (start == end) "
            "must be strictly interior and require both nonempty adjacency guards entirely within that scope. "
            "The service checks coordinate equality, boundaries and adjacency against the sequential buffer."
        )
        span_schema["allOf"] = [{
            "if": {"properties": {"expected_text": {"const": ""}}, "required": ["expected_text"]},
            "then": {
                "required": ["expected_before", "expected_after"],
                "properties": {key: {"type": "string", "minLength": 1}
                               for key in ("expected_before", "expected_after")},
            },
        }]
        for req_field in ("observation_id", "expected_target_version", "expected_current_hash"):
            if req_field not in schema.setdefault("required", []):
                schema["required"].append(req_field)
        schema["x-patchdiff-capabilities"] = {
            "protocol_version": OPERATIONS_PROTOCOL_VERSION, "runtime_version": OPERATIONS_RUNTIME_VERSION,
            "operations": ["match", "span"], "coordinates": "sequential_code_points", "zero_length_insertion": True,
            "requires_observation": True,
            "observed_insertion": {"position": "strictly_interior", "boundary_insertions": False,
                                   "required_guards": ["expected_before", "expected_after"],
                                   "guards_within_scope": True, "adjacency": "sequential_buffer"},
            "span_context": {"fields": ["expected_before", "expected_after"], "runtime_version": SPAN_CONTEXT_RUNTIME_VERSION},
        }
    if name == "patchdiff_submit_replacement":
        schema["x-patchdiff-capabilities"] = {
            "protocol_version": REPLACEMENT_PROTOCOL_VERSION, "runtime_version": REPLACEMENT_RUNTIME_VERSION,
            "operations": ["replace_all"], "max_code_points": MAX_REPLACEMENT_CHARS, "max_utf8_bytes": MAX_REPLACEMENT_BYTES,
        }
    if name == "patchdiff_preview":
        schema["allOf"] = []
        for format_, field in (("0.2.3", "pdcp_content"), ("patchdiff-tx/1", "edits"),
                               ("patchdiff-tx/2", "operations"), ("patchdiff-tx/3", "replacement")):
            branch = {"required": [field], "properties": {field: {"type": "array" if field in {"edits", "operations"} else "string"}}}
            if format_ != "0.2.3":
                branch["required"].append("intent")
                branch["properties"]["intent"] = {"type": "string", "minLength": 1, "pattern": r"\S"}
                branch["anyOf"] = [
                    {"required": ["expected_target_version"], "properties": {"expected_target_version": {"type": "integer"}}},
                    {"required": ["expected_current_hash"], "properties": {"expected_current_hash": {"type": "string"}}},
                ]
            irrelevant = {"intent", "edits", "operations", "replacement", "pdcp_content"} - {field}
            if format_ != "0.2.3":
                irrelevant.remove("intent")
            branch["not"] = {"anyOf": [{"required": [other]} for other in sorted(irrelevant)]}
            schema["allOf"].append({"if": {"properties": {"format": {"const": format_}}}, "then": branch})
    if name in TOOL_EXAMPLES:
        schema["examples"] = copy.deepcopy(TOOL_EXAMPLES[name])
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
        "content": [{"type": "text", "text": _dumps(payload, sort_keys=True)}],
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
