"""Explicit match/span operations: immutable patchdiff-tx/2 representation."""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.core.failures import FailureReason
from app.core.input_text import invalid_text_paths
from app.core.versions import OPERATIONS_RUNTIME_VERSION, resolve_runtime_profile
from app.pdcp.protocol_validator import ProtocolValidationError
from app.pdcp.models import ParsedPDCP
from app.pdcp.typed import (
    TYPED_EDIT_JSON_SCHEMA, TypedEdit, TypedTransaction, build_record,
    parse_typed_record, to_parsed_transaction,
)

OPERATIONS_PROTOCOL_VERSION = "patchdiff-tx/2"
_COMMON = {"change_id", "rationale", "risk", "replace"}
_SPAN_FIELDS = _COMMON | {"op", "start", "end", "expected_text"}
_TOP_FIELDS = {"format", "target_file_id", "intent", "operations", "expected_target_version", "expected_current_hash"}

_match_schema = copy.deepcopy(TYPED_EDIT_JSON_SCHEMA)
_match_schema["properties"]["op"] = {"const": "match", "type": "string"}
_match_schema["required"] = ["op", "match", "replace"]
_span_schema = {
    "type": "object", "additionalProperties": False,
    "required": ["op", "start", "end", "expected_text", "replace"],
    "properties": {**{key: copy.deepcopy(TYPED_EDIT_JSON_SCHEMA["properties"][key]) for key in _COMMON},
                   "op": {"const": "span", "type": "string"},
                   "start": {"type": "integer", "minimum": 0, "maximum": 2**63-1},
                   "end": {"type": "integer", "minimum": 0, "maximum": 2**63-1},
                   "expected_text": {"type": "string"}},
}
OPERATION_JSON_SCHEMA = {"oneOf": [_match_schema, _span_schema]}


@dataclass(frozen=True, slots=True)
class SpanEdit(TypedEdit):
    start: int = 0
    end: int = 0


def build_operations_record(*, target_file_id: str, intent: Any, operations: Any,
                            expected_target_version: int | None, expected_current_hash: str | None) -> dict:
    return {"format": OPERATIONS_PROTOCOL_VERSION, "target_file_id": target_file_id,
            "intent": intent, "operations": operations, "expected_target_version": expected_target_version,
            "expected_current_hash": expected_current_hash}


def parse_operations_record(record: Any) -> TypedTransaction:
    if invalid_text_paths(record):
        raise ProtocolValidationError(FailureReason.TARGET_ENCODING_INVALID, "Input strings must be UTF-8 without NUL.")
    if not isinstance(record, Mapping) or set(record) - _TOP_FIELDS or record.get("format") != OPERATIONS_PROTOCOL_VERSION:
        raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "Unsupported operations transaction fields or format.")
    operations = record.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ProtocolValidationError(FailureReason.MANIFEST_MISSING, "operations must be a non-empty array.")
    normalized = []
    for raw in operations:
        if not isinstance(raw, Mapping) or raw.get("op") not in ("match", "span"):
            raise ProtocolValidationError(FailureReason.MANIFEST_INVALID, "Each operation requires op=match or op=span.")
        if raw["op"] == "match":
            normalized.append({key: value for key, value in raw.items() if key != "op"})
        else:
            if set(raw) - _SPAN_FIELDS:
                raise ProtocolValidationError(FailureReason.MANIFEST_INVALID, "Unknown span fields; selectors are not allowed.")
            start, end = raw.get("start"), raw.get("end")
            if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**63-1
                   for value in (start, end)) or end < start:
                raise ProtocolValidationError(FailureReason.BLOCK_MALFORMED, "Span start/end must be non-negative integers with end>=start.")
            if not isinstance(raw.get("expected_text"), str):
                raise ProtocolValidationError(FailureReason.BLOCK_MALFORMED, "Span expected_text must be a string.")
            normalized.append({**{key: value for key, value in raw.items() if key in _COMMON}, "match": "span"})
    common = parse_typed_record(build_record(
        target_file_id=record.get("target_file_id"), intent=record.get("intent"), edits=normalized,
        expected_target_version=record.get("expected_target_version"), expected_current_hash=record.get("expected_current_hash")))
    edits = tuple(SpanEdit(edit.change_id, raw["expected_text"], edit.replace, edit.rationale, edit.risk,
                          start=raw["start"], end=raw["end"]) if raw["op"] == "span" else edit
                  for raw, edit in zip(operations, common.edits))
    return replace(common, edits=edits)


def to_parsed_operations(transaction: TypedTransaction, *, target_type: str) -> ParsedPDCP:
    parsed = to_parsed_transaction(transaction, target_type=target_type)
    changes = tuple(replace(change, operation="span", span_start=edit.start, span_end=edit.end)
                    if isinstance(edit, SpanEdit) else change for change, edit in zip(parsed.changes, transaction.edits))
    return replace(parsed, header=replace(parsed.header, protocol_version=OPERATIONS_PROTOCOL_VERSION), changes=changes)


def decode_operations_record(text: str, *, runtime_version: str = OPERATIONS_RUNTIME_VERSION) -> TypedTransaction:
    if not resolve_runtime_profile(runtime_version).span_operations:
        raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "Recorded profile does not support operations transactions.")
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "Operations record is not valid JSON.") from exc
    return parse_operations_record(record)
