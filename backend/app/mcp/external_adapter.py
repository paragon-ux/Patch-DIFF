"""External MCP stdio adapter for the PatchDIFF internal tool registry.

The adapter is intentionally thin: transport concerns live here, while all
PatchDIFF behavior remains owned by the existing internal registry/tool layer.
"""

from __future__ import annotations

import copy
import inspect
import json
import os
import sys
from dataclasses import dataclass
from types import NoneType, UnionType
from typing import Any, TextIO, get_args, get_origin, get_type_hints

from app.mcp import tools as _registered_tools  # noqa: F401 - imports register tool handlers
from app.mcp.server import registry
from app.mcp.editor_contracts import (
    EDITOR_V2_TOOLS, EDITOR_V2_ROUTES, ContractArgumentError,
    tool_declaration, normalize_arguments, project_result, is_success,
)
from app.pdcp.typed import TYPED_EDIT_JSON_SCHEMA
from app.pdcp.operations import OPERATION_JSON_SCHEMA, OPERATIONS_PROTOCOL_VERSION
from app.pdcp.replacement import MAX_REPLACEMENT_BYTES, MAX_REPLACEMENT_CHARS, REPLACEMENT_PROTOCOL_VERSION
from app.core.line_endings import EXPORT_FORMATS
from app.core.versions import OPERATIONS_RUNTIME_VERSION, REPLACEMENT_RUNTIME_VERSION, SPAN_CONTEXT_RUNTIME_VERSION
from app.pdcp.observed_batch import (SELECTION_JSON_SCHEMA, GROUP_JSON_SCHEMA, MAX_BATCH_SCOPES,
                                     MAX_BATCH_OPERATIONS, BATCH_ERROR_CODES, BATCH_PROTOCOL_VERSION, BATCH_RUNTIME_VERSION)


PROTOCOL_VERSION = "2024-11-05"  # Legacy fallback for clients without a revision.
SUPPORTED_PROTOCOL_VERSIONS = (PROTOCOL_VERSION, "2025-06-18", "2025-11-25")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]
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
    "patchdiff_observe_scope": (
        "Observe structural scopes via pinned Waymark Engine. Routes: target_file_id alone, or optional nonblank "
        "query/kind filters, returns candidates only (no observation receipt); omit query to list without that filter. "
        "symbol_name selects one exact scope and returns observation_id + bounded text. selections selects 1..32 "
        "disjoint scopes on one snapshot and returns observation_bundle_id + scopes[]. Known exact identities need "
        "no preceding discovery. Use returned names verbatim, including Markdown punctuation; ambiguity rejects. "
        "observation_id + offset pages an issued scope; continue with next_offset. "
        "selections cannot mix with query, symbol_name, observation_id, top-level kind or nonzero offset."
    ) + _CODE_POINTS,
    "patchdiff_submit_observed_operations": (
        "Commit one guarded atomic target transaction. Both forms require target_file_id, intent, "
        "expected_target_version and expected_current_hash. Choose exactly one: single observation_id + operations "
        "(absolute sequential spans), or batch observation_bundle_id + groups + client_request_id "
        "(scope-local sequential spans). Omit the other form's fields, even null placeholders. "
        "Each group pairs a returned scopes[].observation_id with your proposed operations. Operations run "
        "sequentially; batch match indexes are 1-based overlapping occurrences within that group's buffer, "
        "not global find_occurrences indexes. Exact matches may contain newlines. At most 32 groups/128 operations. "
        "Any failure rejects the entire transaction. Spans stay within their observed scope; insertions must be "
        "strictly interior with both nonempty expected_before/expected_after guards inside that scope."
    ) + _CODE_POINTS,
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
    "patchdiff_observe_scope": [
        {"target_file_id": _EXAMPLE_TARGET, "query": "alp", "kind": "function"},
        {"target_file_id": _EXAMPLE_TARGET, "symbol_name": "alpha", "kind": "function"},
        {"target_file_id": _EXAMPLE_TARGET, "selections": [{"symbol_name": "alpha", "kind": "function"},
                                                                      {"symbol_name": "beta", "kind": "function"}], "max_chars": 8},
        {"target_file_id": _EXAMPLE_TARGET, "observation_id": "22222222-2222-4222-8222-222222222222", "offset": 8},
    ],
    "patchdiff_submit_observed_operations": [
        {"target_file_id": _EXAMPLE_TARGET, "observation_id": "22222222-2222-4222-8222-222222222222",
         "expected_target_version": 0, "expected_current_hash": "0" * 64, "intent": "Update exact multiline text in one scope",
         "operations": [{"op": "match", "match": '# ababa\n    return "alpha"',
                         "replace": '# ababa\n    return "gamma"'}]},
        {"target_file_id": _EXAMPLE_TARGET, "observation_bundle_id": "33333333-3333-4333-8333-333333333333",
         "expected_target_version": 0, "expected_current_hash": "0" * 64, "client_request_id": "example-observed-batch",
         "intent": "Update two disjoint scopes atomically", "groups": [
             {"observation_id": "22222222-2222-4222-8222-222222222222",
              "operations": [{"op": "match", "match": "aba", "replace": "XYZ", "occurrence_index": 2}]},
             {"observation_id": "44444444-4444-4444-8444-444444444444",
              "operations": [{"op": "match", "match": "beta", "replace": "delta", "occurrence_index": 2}]},
         ]},
    ],
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


_BASE_EDITOR_TOOLS = frozenset({"patchdiff_read_target", "patchdiff_find_occurrences", "patchdiff_save", "patchdiff_replay"})
MCP_PROFILES = {
    "editor": _BASE_EDITOR_TOOLS | {"patchdiff_observe_scope", "patchdiff_submit_edits", "patchdiff_submit_observed_operations"},
    "unobserved": _BASE_EDITOR_TOOLS | {"patchdiff_submit_edits"},
    "unobserved_editor": frozenset({"patchdiff_read_target", "patchdiff_find_occurrences", "patchdiff_submit_edits"}),
    "observed": _BASE_EDITOR_TOOLS | {"patchdiff_observe_scope", "patchdiff_submit_observed_operations"},
    "observed_editor": frozenset({"patchdiff_read_target", "patchdiff_find_occurrences",
                                  "patchdiff_observe_scope", "patchdiff_submit_observed_operations"}),
    "observed_v2": EDITOR_V2_TOOLS,
    "full": frozenset(EXPECTED_TOOL_NAMES),
}


@dataclass(frozen=True, slots=True, init=False)
class ExternalMCPAdapter:
    """Minimal JSON-RPC MCP adapter backed by the internal PatchDIFF registry."""

    profile: str
    response_mode: str
    _tool_names: tuple[str, ...]
    _protocol_version: str
    _initialized: bool

    def __init__(self, *, profile: str | None = None, response_mode: str | None = None):
        selected = os.getenv("PATCHDIFF_MCP_PROFILE", "editor") if profile is None else profile
        if selected not in MCP_PROFILES:
            raise ValueError(f"Unknown PATCHDIFF_MCP_PROFILE: {selected!r}; expected editor, unobserved, unobserved_editor, observed, observed_editor, observed_v2 or full.")
        object.__setattr__(self, "profile", selected)
        object.__setattr__(self, "_protocol_version", PROTOCOL_VERSION)
        object.__setattr__(self, "_initialized", False)
        mode = os.getenv("PATCHDIFF_MCP_RESPONSE_MODE", "detailed") if response_mode is None else response_mode
        if mode not in {"detailed", "compact"}:
            raise ValueError(f"Unknown PATCHDIFF_MCP_RESPONSE_MODE: {mode!r}; expected detailed or compact.")
        object.__setattr__(self, "response_mode", mode)
        object.__setattr__(self, "_tool_names", tuple(sorted(MCP_PROFILES[selected])))

    def list_tools(self) -> list[dict[str, Any]]:
        if self.profile == "observed_v2":
            declarations = []
            for name in self._tool_names:
                declaration = tool_declaration(name, _input_schema_for(EDITOR_V2_ROUTES[name]))
                if self._protocol_version == PROTOCOL_VERSION:
                    for key in ("outputSchema", "annotations", "_meta"):
                        declaration.pop(key, None)
                declarations.append(declaration)
            return declarations
        return [
            {
                "name": name,
                "description": TOOL_DESCRIPTIONS.get(name, f"PatchDIFF tool {name}.") + (
                    " This session uses compact success responses; supplementary evidence requires a detailed session."
                    if self.response_mode == "compact" and name in {"patchdiff_observe_scope", "patchdiff_submit_observed_operations"}
                    else ""),
                "inputSchema": _input_schema_for(name),
            }
            for name in self._tool_names
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self._tool_names:
            return _tool_error(f"Unknown PatchDIFF MCP tool: {name}")
        args = arguments or {}
        if self.profile == "observed_v2":
            return self._call_editor_tool(name, args)
        argument_error = _argument_error(name, args)
        if argument_error is not None:
            return {"content": [{"type": "text", "text": _dumps(argument_error, sort_keys=True)}], "isError": True}
        try:
            payload = registry.call(name, **args)
        except TypeError as exc:
            return _tool_error(f"Invalid arguments for {name}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive transport boundary
            return _tool_error(f"PatchDIFF MCP tool failed: {exc}")
        if self.response_mode == "compact":
            projected = _compact_payload(name, payload)
            if projected is not payload:
                return _tool_result(projected, compact=True)
        return _tool_result(payload)

    def _call_editor_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = normalize_arguments(name, arguments)
        except ContractArgumentError as exc:
            payload = {"status": "invalid_argument", "code": exc.code, "failure_detail": exc.detail}
        else:
            route = EDITOR_V2_ROUTES[name]
            payload = _argument_error(route, normalized)
            if payload is None:
                try:
                    if name == "patchdiff_commit_bundle":
                        payload = _registered_tools.submit_editor_operations(**normalized)
                    else:
                        payload = registry.call(route, **normalized)
                except Exception:  # An infrastructure failure cannot establish a transaction outcome.
                    payload = {"status": "outcome_unknown", "code": "execution_failed",
                               "failure_detail": "Tool execution failed; transaction outcome is unknown."}
        success = is_success(name, payload)
        projected = project_result(name, payload, arguments=arguments)
        result = {"content": [{"type": "text", "text": _dumps(projected, sort_keys=True, separators=(",", ":"))}],
                  "isError": not success}
        if self._protocol_version != PROTOCOL_VERSION:
            result["structuredContent"] = projected
        return result

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")

        if method in {"notifications/initialized", "initialized"}:
            return None
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _rpc_error(request_id, -32600, "Invalid JSON-RPC request.")

        if method == "initialize":
            params = request.get("params", {})
            if not isinstance(params, dict):
                return _rpc_error(request_id, -32602, "initialize params must be an object.")
            requested = params.get("protocolVersion", PROTOCOL_VERSION)
            if not isinstance(requested, str):
                return _rpc_error(request_id, -32602, "protocolVersion must be a string.")
            negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
            if self._initialized and negotiated != self._protocol_version:
                return _rpc_error(request_id, -32602, "A connection cannot renegotiate its protocol revision.")
            object.__setattr__(self, "_protocol_version", negotiated)
            object.__setattr__(self, "_initialized", True)
            return _rpc_result(
                request_id,
                {"protocolVersion": negotiated, "capabilities": {"tools": {}},
                 "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}},
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

    from app.services.waymark_worker import serving_worker_owner
    with serving_worker_owner(prewarm=True):
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
    "query": "Optional case-insensitive substring filter over Waymark symbol names for candidate discovery, which issues no observation receipt.",
    "symbol_name": "Exact returned Waymark symbol name (or parent.name), including Markdown punctuation, to select uniquely and issue an observation_id. Ambiguity rejects.",
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
        for field in ("query", "symbol_name", "kind"):
            properties[field]["minLength"] = 1
            properties[field]["description"] = _PARAMETER_DESCRIPTIONS[field] + " Nonblank when supplied; omitted/null means absent."
        properties["query"]["description"] += " Absence removes only the query filter."
        for field, minimum in (("offset", 0), ("max_chars", 1)):
            properties[field]["minimum"] = minimum
        properties["offset"]["default"] = 0
        properties["offset"]["description"] = "Code-point offset within the observed scope; page with observation_id and the returned next_offset."
        properties["observation_id"]["description"] = "Issued scope UUID for paging with offset; omit symbol_name, query and selections."
        properties["include_line_starts"]["default"] = False
        properties["selections"] = {"type": "array", "minItems": 1, "maxItems": MAX_BATCH_SCOPES,
                                    "uniqueItems": True, "items": copy.deepcopy(SELECTION_JSON_SCHEMA),
                                    "description": "Select 1..32 exact disjoint scopes on one snapshot; returns observation_bundle_id and scopes with observation_id/text. Initial text <=32,768; total scope text <=65,536 code points."}
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
        for req_field in ("expected_target_version", "expected_current_hash"):
            if req_field not in schema.setdefault("required", []):
                schema["required"].append(req_field)
        properties["expected_target_version"]["type"] = "integer"
        properties["expected_current_hash"]["type"] = "string"
        properties["observation_id"] = {"type": "string", "format": "uuid", "description": "Single form only: issued scope UUID paired with top-level operations; omit in batch form."}
        properties["observation_bundle_id"] = {"type": "string", "format": "uuid", "description": "Batch form only: returned bundle UUID paired with groups and client_request_id; omit in single form."}
        properties["operations"]["description"] = "Single form only: proposed sequential match/span operations within observation_id; span offsets are absolute. Omit in batch form."
        group_schema = copy.deepcopy(GROUP_JSON_SCHEMA)
        group_schema["properties"]["observation_id"]["description"] = "Copy an observation_id from the selected bundle's scopes array."
        group_schema["properties"]["operations"]["description"] = "Your proposed operations, evaluated sequentially within this scope's original slice; span offsets are scope-local."
        group_schema["properties"]["operations"]["items"] = copy.deepcopy(properties["operations"]["items"])
        match_schema = group_schema["properties"]["operations"]["items"]["oneOf"][0]
        match_schema["properties"]["occurrence_index"]["description"] = "One-based overlapping occurrence in this scope's sequential buffer after earlier operations, not the global target."
        match_schema["properties"]["match"]["description"] = "Exact text, including any literal newlines, inside this group's sequential scope buffer."
        properties["groups"] = {"type": "array", "minItems": 1, "maxItems": MAX_BATCH_SCOPES, "items": group_schema,
                                "description": "Batch form only: pair each selected scopes[].observation_id with proposed operations; do not copy scope objects. At most 128 operations total; each group uses its own scope-local sequential buffer."}
        schema["oneOf"] = [
            {"required": ["observation_id", "operations"],
             "not": {"anyOf": [{"required": [key]} for key in ("observation_bundle_id", "groups")]}},
            {"required": ["observation_bundle_id", "groups", "client_request_id"],
             "properties": {"client_request_id": {"type": "string"}},
             "not": {"anyOf": [{"required": [key]} for key in ("observation_id", "operations")]}},
        ]
        schema["x-patchdiff-capabilities"] = {
            "protocol_version": OPERATIONS_PROTOCOL_VERSION, "runtime_version": OPERATIONS_RUNTIME_VERSION,
            "operations": ["match", "span"], "coordinates": "sequential_code_points", "zero_length_insertion": True,
            "requires_observation": True,
            "observed_insertion": {"position": "strictly_interior", "boundary_insertions": False,
                                   "required_guards": ["expected_before", "expected_after"],
                                   "guards_within_scope": True, "adjacency": "sequential_buffer"},
            "span_context": {"fields": ["expected_before", "expected_after"], "runtime_version": SPAN_CONTEXT_RUNTIME_VERSION},
            "batch": {"protocol_version": BATCH_PROTOCOL_VERSION, "runtime_version": BATCH_RUNTIME_VERSION,
                      "max_scopes": MAX_BATCH_SCOPES, "max_operations": MAX_BATCH_OPERATIONS,
                      "coordinates": "scope_local_sequential_code_points", "error_codes": list(BATCH_ERROR_CODES)},
        }
    if name == "patchdiff_observe_scope":
        schema["allOf"] = [{"if": {"required": ["selections"]}, "then": {
            "not": {"anyOf": [{"required": [key]} for key in ("symbol_name", "query", "observation_id", "kind")]},
            "properties": {"offset": {"const": 0}},
        }}]
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
    _portable_schema_patterns(schema)
    return schema


def _portable_schema_patterns(schema: Any) -> None:
    if isinstance(schema, dict):
        pattern = schema.get("pattern")
        suffix = r"(?![\s\S])"
        if isinstance(pattern, str) and pattern.endswith(suffix):
            # RE2 hosts reject lookahead; $ alone permits a final LF in other engines.
            schema["pattern"] = pattern[:-len(suffix)] + "$"
            schema.setdefault("allOf", []).append({"not": {"type": "string", "pattern": "\n"}})
        if "enum" in schema and isinstance(schema["enum"], list):
            # OpenAPI / Gemini hosts reject null/empty values in enum declarations.
            schema["enum"] = [v for v in schema["enum"] if v is not None and v != ""]
        for key, value in schema.items():
            if key != "examples":
                _portable_schema_patterns(value)
    elif isinstance(schema, list):
        for value in schema:
            _portable_schema_patterns(value)


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


def _compact_payload(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Response-only projection; authoritative results and stored facts stay complete."""
    omitted = []
    result = dict(payload)
    if name == "patchdiff_submit_observed_operations" and payload.get("status") == "accepted":
        for key in ("evidence", "groups"):
            if key in result:
                del result[key]
                omitted.append(key)
    elif name == "patchdiff_observe_scope" and payload.get("status") == "candidates":
        fields = {"name", "kind", "parent", "start_line", "end_line"}
        result["candidates"] = [{key: value for key, value in item.items() if key in fields}
                                for item in payload["candidates"]]
        if any(set(item) - fields for item in payload["candidates"]):
            omitted.append("candidate_details")
    elif name == "patchdiff_observe_scope" and payload.get("status") == "observed_batch":
        fields = {"start", "end", "max_chars", "next_start", "start_line", "end_line"}
        result["scopes"] = [{key: value for key, value in item.items() if key not in fields}
                            for item in payload["scopes"]]
        if any(set(item) & fields for item in payload["scopes"]):
            omitted.append("duplicate_page_metadata")
    else:
        return payload
    result["presentation"] = {"mode": "compact", "omitted": omitted}
    return result


def _tool_result(payload: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _dumps(payload, sort_keys=True, **({"separators": (",", ":")} if compact else {}))}],
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
