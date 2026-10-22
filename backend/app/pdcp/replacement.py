"""Frozen tx/3 sole replacement format; admission limits are not replay rules."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from app.core.canonicalization import canonicalize_text
from app.core.failures import FailureReason
from app.core.input_text import invalid_text_paths
from app.core.versions import REPLACEMENT_RUNTIME_VERSION, resolve_runtime_profile
from app.pdcp.models import ParsedPDCP
from app.pdcp.protocol_validator import ProtocolValidationError
from app.pdcp.typed import TypedTransaction, build_record, parse_typed_record, to_parsed_transaction

REPLACEMENT_PROTOCOL_VERSION = "patchdiff-tx/3"
MAX_REPLACEMENT_CHARS = 1_000_000
MAX_REPLACEMENT_BYTES = 1_048_576
_TOP_FIELDS = {"format", "target_file_id", "intent", "operations", "expected_target_version", "expected_current_hash"}


def build_replacement_record(*, target_file_id: str, intent: Any, replacement: Any,
                             expected_target_version: Any, expected_current_hash: Any) -> dict:
    return {"format": REPLACEMENT_PROTOCOL_VERSION, "target_file_id": target_file_id,
            "intent": intent, "operations": [{"op": "replace_all", "replace": replacement}],
            "expected_target_version": expected_target_version, "expected_current_hash": expected_current_hash}


def replacement_size_error(replacement: Any) -> str | None:
    """Call only after invalid-text classification; invalid shape goes to decoding."""
    if not isinstance(replacement, str):
        return None
    if len(replacement) > MAX_REPLACEMENT_CHARS:
        return "raw_code_points"
    if len(replacement.encode("utf-8")) > MAX_REPLACEMENT_BYTES:
        return "raw_utf8_bytes"
    canonical = canonicalize_text(replacement)
    if len(canonical) > MAX_REPLACEMENT_CHARS:
        return "result_code_points"
    if len(canonical.encode("utf-8")) > MAX_REPLACEMENT_BYTES:
        return "result_utf8_bytes"
    return None


def parse_replacement_record(record: Any) -> TypedTransaction:
    if invalid_text_paths(record):
        raise ProtocolValidationError(FailureReason.TARGET_ENCODING_INVALID, "Input strings must be UTF-8 without NUL.")
    if not isinstance(record, Mapping) or set(record) - _TOP_FIELDS or record.get("format") != REPLACEMENT_PROTOCOL_VERSION:
        raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "Unsupported replacement transaction fields or format.")
    operations = record.get("operations")
    if (not isinstance(operations, list) or len(operations) != 1 or not isinstance(operations[0], Mapping)
            or set(operations[0]) != {"op", "replace"} or operations[0].get("op") != "replace_all"):
        raise ProtocolValidationError(FailureReason.MANIFEST_INVALID, "tx/3 requires exactly one sole replace_all operation with op and replace.")
    return parse_typed_record(build_record(
        target_file_id=record.get("target_file_id"), intent=record.get("intent"),
        edits=[{"match": "replace_all", "replace": operations[0]["replace"]}],
        expected_target_version=record.get("expected_target_version"), expected_current_hash=record.get("expected_current_hash")))


def to_parsed_replacement(transaction: TypedTransaction, *, target_type: str) -> ParsedPDCP:
    parsed = to_parsed_transaction(transaction, target_type=target_type)
    return replace(parsed, header=replace(parsed.header, protocol_version=REPLACEMENT_PROTOCOL_VERSION),
                   changes=tuple(replace(change, operation="replace_all", match_payload="") for change in parsed.changes))


def decode_replacement_record(text: str, *, runtime_version: str = REPLACEMENT_RUNTIME_VERSION) -> TypedTransaction:
    if not resolve_runtime_profile(runtime_version).replace_all_operations:
        raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "Recorded profile does not support replacement transactions.")
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolValidationError(FailureReason.CONTEXT_INVALID, "Replacement record is not valid JSON.") from exc
    return parse_replacement_record(record)
