"""Versioned editor wire contracts; no persistence, mutation, or argument repair.

These adapters select an existing service route. Runtime validation and keyed
recovery remain in that service, including for malformed operational values.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

EDITOR_V2_ROUTES = {
    "patchdiff_read_target": "patchdiff_read_target",
    "patchdiff_find_occurrences": "patchdiff_find_occurrences",
    "patchdiff_list_scopes": "patchdiff_observe_scope",
    "patchdiff_observe_scopes": "patchdiff_observe_scope",
    "patchdiff_commit_bundle": "patchdiff_submit_observed_operations",
}
EDITOR_V2_TOOLS = frozenset(EDITOR_V2_ROUTES)
EDITOR_V2_EAGER_TOOLS = EDITOR_V2_TOOLS
MAX_RECEIPT_BYTES = 8192
_COMMIT_TOOLS = frozenset({"patchdiff_commit_bundle"})
_GUARDS = ("target_file_id", "expected_target_version", "expected_current_hash")
_OPTIONAL_SUBMIT = ("source", "parent_pdcp_log_id", "attempt", "client_request_id", "include_correlation_id")
_FIELDS = {
    "patchdiff_read_target": ("target_file_id", "start", "length"),
    "patchdiff_find_occurrences": ("target_file_id", "text", "context_chars", "start_occurrence", "max_results"),
    "patchdiff_list_scopes": ("target_file_id", "query", "kind"),
    "patchdiff_observe_scopes": ("target_file_id", "selections", "max_chars", "include_line_starts"),
}
_DESCRIPTIONS = {
    "patchdiff_read_target": "Read bounded canonical LF text by Unicode code-point offset; returns version, hash and next_start.",
    "patchdiff_find_occurrences": "Find exact overlapping occurrences in the current target, with code-point spans, bounded context and pagination. These indexes are target-wide.",
    "patchdiff_list_scopes": "List structural candidates, optionally filtered by query/kind. Returns names and bounds, not observation authority.",
    "patchdiff_observe_scopes": "Observe 1..32 exact disjoint scopes on one target snapshot. Returns a copyable snapshot and scopes with IDs/text. Total scopes <=65,536 code points, initial text <=32,768.",
    "patchdiff_commit_bundle": "Commit 1..32 groups atomically on one target using the explicit observed snapshot. At most 128 ordered match/span operations total. Each group uses its scope-local sequential buffer; overlapping match indexes start at 1 within that buffer. All groups commit or reject together. Exact keyed retries recover the original outcome.",
}


class ContractArgumentError(ValueError):
    """An unroutable wire envelope, not a service admission rejection."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.failure_detail = detail


def _known(name: str) -> None:
    if name not in EDITOR_V2_TOOLS:
        raise ContractArgumentError("unknown_tool", "Unknown editor v2 tool.")


def _snapshot_fields(name: str) -> tuple[str, ...]:
    return (*_GUARDS, "observation_bundle_id")


def normalize_arguments(name: str, arguments: dict) -> dict:
    """Unpack only the envelope; never coerce values or precheck fresh guards."""
    _known(name)
    if not isinstance(arguments, dict):
        raise ContractArgumentError("invalid_arguments", "Tool arguments must be an object.")
    if name in _COMMIT_TOOLS:
        operation_field = "groups"
        allowed = {"snapshot", "intent", operation_field, *_OPTIONAL_SUBMIT}
        if arguments.keys() - allowed:
            raise ContractArgumentError("unknown_argument", "Unknown field in commit envelope.")
        snapshot = arguments.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ContractArgumentError("invalid_snapshot", "snapshot must be an object containing target_file_id and explicit observation guards.")
        if snapshot.keys() - set(_snapshot_fields(name)):
            raise ContractArgumentError("unknown_snapshot_field", "Unknown field in snapshot.")
        if "target_file_id" not in snapshot:
            raise ContractArgumentError("missing_target", "snapshot.target_file_id is required to route this request.")
        result = {key: value for key, value in arguments.items() if key != "snapshot"}
        result.update(snapshot)
        # Explicit None selects the intended route; missing operational values
        # must reach the known-target service's existing audit/validation path.
        identity = _snapshot_fields(name)[-1]
        result.setdefault(identity, None)
        result.setdefault(operation_field, None)
        result.setdefault("intent", None)
        return result
    if arguments.keys() - set(_FIELDS[name]):
        raise ContractArgumentError("unknown_argument", "Unknown field for this editor tool.")
    if "target_file_id" not in arguments:
        raise ContractArgumentError("missing_target", "target_file_id is required.")
    if name == "patchdiff_find_occurrences" and "text" not in arguments:
        raise ContractArgumentError("missing_argument", "text is required.")
    result = dict(arguments)
    if name == "patchdiff_observe_scopes":
        result.setdefault("selections", None)
    return result


def _object(properties: dict, required: tuple | list = ()) -> dict:
    result = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        result["required"] = list(required)
    return result


def _input_schema(name: str, legacy: dict) -> dict:
    properties = legacy["properties"]
    if name in _COMMIT_TOOLS:
        operation_field = "groups"
        fields = ("intent", operation_field, *_OPTIONAL_SUBMIT)
        chosen = {key: copy.deepcopy(properties[key]) for key in fields}
        snapshot = {key: copy.deepcopy(properties[key]) for key in _snapshot_fields(name)}
        identity = _snapshot_fields(name)[-1]
        snapshot[identity]["description"] = "Observation identity returned in this snapshot; copy the exact value."
        chosen["snapshot"] = _object(snapshot, _snapshot_fields(name))
        chosen["snapshot"]["description"] = "Explicit target, both guards and observation identity returned by observation; copied without refreshing or inferring values."
        required = ["snapshot", "intent", operation_field, "client_request_id"]
        chosen["client_request_id"]["type"] = "string"
        chosen["groups"]["description"] = "Pair each returned scope observation_id with ordered operations in that scope's sequential local buffer; at most 128 operations total."
        result = _object(chosen, required)
    else:
        chosen = {key: copy.deepcopy(properties[key]) for key in _FIELDS[name]}
        required = ["target_file_id"]
        required += {"patchdiff_find_occurrences": ["text"], "patchdiff_observe_scopes": ["selections"]}.get(name, [])
        result = _object(chosen, required)
    examples = []
    for example in legacy.get("examples", []):
        if name in _COMMIT_TOOLS:
            identity = _snapshot_fields(name)[-1]
            if identity not in example:
                continue
            candidate = {key: copy.deepcopy(value) for key, value in example.items() if key not in _snapshot_fields(name)}
            candidate["snapshot"] = {key: copy.deepcopy(example[key]) for key in _snapshot_fields(name)}
        else:
            if example.keys() - set(_FIELDS[name]):
                continue
            if any(key not in example for key in result.get("required", [])):
                continue
            candidate = copy.deepcopy(example)
        examples.append(candidate)
    if examples:
        result["examples"] = examples
    # Deliberately do not copy mode-dependent x-patchdiff-capabilities or root
    # single/batch constraints from the legacy union. Nested operations survive.
    return result


def _output_schema(name: str) -> dict:
    nullable_string = {"type": ["string", "null"]}
    state = _object({"version": {"type": ["integer", "null"]}, "hash": nullable_string}, ("version", "hash"))
    collection = _object({"items": {"type": "array"}, "total": {"type": "integer", "minimum": 0},
                          "truncated": {"type": "boolean"}}, ("items", "total", "truncated"))
    properties: dict[str, Any] = {"status": {"type": "string"}, "target_file_id": nullable_string,
                                "code": nullable_string, "failure_detail": {"type": "string"},
                                "diagnostic": {"type": "object"}, "presentation": {"type": "object"}}
    if name in _COMMIT_TOOLS:
        properties.update({
            "transaction": _object({"pdcp_log_id": nullable_string, "client_request_id": nullable_string,
                                     "deduplicated": {"type": "boolean"}, "before": state, "after": state,
                                     "operation_count": {"type": ["integer", "null"]},
                                     "group_count": {"type": ["integer", "null"]}},
                                    ("pdcp_log_id", "client_request_id", "deduplicated", "before", "after")),
            "current": state, "validity": {"type": "object"}, "warnings": collection, "scopes": collection,
        })
    elif name == "patchdiff_observe_scopes":
        commit = "patchdiff_commit_bundle"
        properties["snapshot"] = _object({key: ({"type": "integer"} if key == "expected_target_version" else {"type": "string"})
                                           for key in _snapshot_fields(commit)}, _snapshot_fields(commit))
        properties.update({"scopes": {"type": "array", "items": {"type": "object"}}, "text": {"type": "string"},
                           "truncated": {"type": "boolean"}, "next_offset": {"type": ["integer", "null"]}})
    else:
        properties.update({"text": {"type": "string"}, "version": {"type": "integer"},
                           "current_hash": {"type": "string"}, "target_version": {"type": "integer"},
                           "target_current_hash": {"type": "string"}, "candidates": {"type": "array", "items": {"type": "object"}},
                           "occurrences": {"type": "array", "items": {"type": "object"}},
                           "truncated": {"type": "boolean"}, "next_start": {"type": ["integer", "null"]},
                           "next_offset": {"type": ["integer", "null"]}, "next_occurrence_index": {"type": ["integer", "null"]}})
    # Service-specific failure metadata remains extensible; advertised common
    # fields are typed for both accepted and rejected outcomes.
    return {"type": "object", "required": ["status"], "properties": properties, "additionalProperties": True}


def tool_declaration(name: str, legacy_schema: dict) -> dict:
    _known(name)
    writes = name in _COMMIT_TOOLS or name == "patchdiff_observe_scopes"
    annotations = {"readOnlyHint": not writes, "openWorldHint": False}
    if writes:
        annotations.update({"destructiveHint": name in _COMMIT_TOOLS, "idempotentHint": False})
    result = {"name": name, "description": _DESCRIPTIONS[name], "inputSchema": _input_schema(name, legacy_schema),
              "outputSchema": _output_schema(name), "annotations": annotations}
    if name in EDITOR_V2_EAGER_TOOLS:
        result["_meta"] = {"antigravity/alwaysLoad": True}
    return result


def is_success(name: str, payload: dict) -> bool:
    _known(name)
    statuses = {
        "patchdiff_read_target": {"ok"}, "patchdiff_find_occurrences": {"ok"},
        "patchdiff_list_scopes": {"candidates"}, "patchdiff_observe_scopes": {"observed_batch", "observed"},
        "patchdiff_commit_bundle": {"accepted"},
    }
    return isinstance(payload, dict) and payload.get("status") in statuses[name]


def _encoded(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")


def _fits(result: dict) -> bool:
    return len(_encoded(result)) <= MAX_RECEIPT_BYTES


def _omit(result: dict, field: str) -> None:
    presentation = result["presentation"]
    presentation["truncated"] = True
    if field not in presentation["omitted_fields"]:
        presentation["omitted_fields"].append(field)


def _header(result: dict, key: str, value: Any) -> Any:
    # Admitted UUIDs/hashes/keys are bounded by the service. Invalid-input echoes
    # are not: never present a shortened attacker string as an authentic ID.
    encoded = _encoded(value)
    if len(encoded) > 512:
        _omit(result, key)
        result["presentation"].setdefault("omitted_values", {})[key] = {
            "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}
        return None
    return copy.deepcopy(value)


def _optional(result: dict, key: str, value: Any) -> None:
    result[key] = copy.deepcopy(value)
    if _fits(result):
        return
    del result[key]
    _omit(result, key)
    if isinstance(value, str):
        # Keep a bounded explanatory prefix; presentation marks it incomplete.
        lo, hi = 0, len(value)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            result[key] = value[:mid]
            if _fits(result):
                lo = mid
            else:
                hi = mid - 1
        result[key] = value[:lo]


def _collection(result: dict, key: str, items: list, total: int, truncated: bool = False, **extra: Any) -> None:
    result[key] = {"items": [], "total": total, "truncated": truncated, **extra}
    for item in items:
        result[key]["items"].append(copy.deepcopy(item))
        if not _fits(result):
            result[key]["items"].pop()
            result[key]["truncated"] = True
            _omit(result, key)
            break
    if truncated or len(result[key]["items"]) < total:
        result[key]["truncated"] = True


def _receipt(name: str, payload: dict) -> dict:
    result: dict[str, Any] = {"status": payload.get("status", "error"),
                              "presentation": {"max_bytes": MAX_RECEIPT_BYTES, "truncated": False, "omitted_fields": []}}
    for key in ("target_file_id", "code", "failure_reason", "failed_change_id", "correlation_id", "observation_bundle_id"):
        if key in payload:
            result[key] = _header(result, key, payload[key])
    if "code" not in result and isinstance(payload.get("diagnostic"), dict) and "code" in payload["diagnostic"]:
        result["code"] = _header(result, "code", payload["diagnostic"]["code"])
    if name in _COMMIT_TOOLS:
        result["transaction"] = {
            "pdcp_log_id": _header(result, "transaction.pdcp_log_id", payload.get("pdcp_log_id")),
            "client_request_id": _header(result, "transaction.client_request_id", payload.get("client_request_id")),
            "deduplicated": payload.get("deduplicated", False),
            "before": {"version": payload.get("before_version"), "hash": _header(result, "transaction.before.hash", payload.get("before_hash"))},
            "after": {"version": payload.get("after_version"), "hash": _header(result, "transaction.after.hash", payload.get("after_hash"))},
        }
        if "change_count" in payload or "manifest_entries_added" in payload:
            result["transaction"]["operation_count"] = payload.get("change_count", payload.get("manifest_entries_added"))
        if "group_count" in payload:
            result["transaction"]["group_count"] = payload["group_count"]
    elif "pdcp_log_id" in payload:
        result["pdcp_log_id"] = _header(result, "pdcp_log_id", payload["pdcp_log_id"])
    if "current_version" in payload or "current_hash" in payload:
        result["current"] = {"version": payload.get("current_version"), "hash": _header(result, "current.hash", payload.get("current_hash"))}
    if "validity" in payload:
        result["validity"] = copy.deepcopy(payload["validity"])
    for key in ("validation_stage", "outcome"):
        if key in payload:
            result[key] = _header(result, key, payload[key])
    # Reserve collection shells and omission metadata before admitting optional
    # content, so all later trimming preserves whole-result rather than per-list bounds.
    if name in _COMMIT_TOOLS:
        for key in ("warnings", "scopes"):
            result[key] = {"items": [], "total": 0, "truncated": False}
    diagnostic = payload.get("diagnostic")
    if isinstance(diagnostic, dict):
        essential = {key: _header(result, "diagnostic." + key, diagnostic[key]) for key in
                     ("code", "underlying_code", "group_index", "operation_index", "observation_id", "stage", "validation_stage", "retryable")
                     if key in diagnostic}
        result["diagnostic"] = essential
        for key, value in diagnostic.items():
            if key in essential:
                continue
            result["diagnostic"][key] = copy.deepcopy(value)
            if not _fits(result):
                del result["diagnostic"][key]
                _omit(result, "diagnostic")
    if name in _COMMIT_TOOLS:
        details = payload.get("warning_details")
        warnings = details if isinstance(details, list) and details else payload.get("warnings", [])
        _collection(result, "warnings", warnings, payload.get("warning_count", len(warnings)), payload.get("warnings_truncated", False))
        scopes = []
        for group in payload.get("groups", []):
            scopes.append({("operation_count" if key == "change_count" else key): copy.deepcopy(value) for key, value in group.items()})
        _collection(result, "scopes", scopes, payload.get("group_count", len(scopes)))
    for key in ("failure_detail", "current_context", "near_misses", "error"):
        if key in payload:
            _optional(result, key, payload[key])
    # Metadata can grow while arrays are filled. Finish by dropping whole entries,
    # keeping totals/flags intact and preserving mandatory outcome/identity fields.
    for key in ("scopes", "warnings"):
        while not _fits(result) and isinstance(result.get(key), dict) and result[key].get("items"):
            result[key]["items"].pop()
            result[key]["truncated"] = True
            _omit(result, key)
    if not _fits(result):
        for key in ("failure_detail", "current_context", "near_misses", "error", "diagnostic"):
            if key in result:
                del result[key]
                _omit(result, key)
                if _fits(result):
                    break
    if not _fits(result):
        raise ValueError("Mandatory editor receipt fields exceed the response budget.")
    return result


def project_result(name: str, payload: dict, *, arguments: dict | None = None) -> dict:
    """Project supplied service evidence only; arguments never establish success."""
    _known(name)
    if name in _COMMIT_TOOLS or not is_success(name, payload):
        return _receipt(name, payload)
    result = copy.deepcopy(payload)
    if name == "patchdiff_observe_scopes":
        identity = "observation_bundle_id"
        result["snapshot"] = {"target_file_id": result.pop("target_file_id"),
                              "expected_target_version": result.pop("target_version"),
                              "expected_current_hash": result.pop("target_current_hash"),
                              identity: result.pop(identity)}
        result.pop("mode", None)
    return result
