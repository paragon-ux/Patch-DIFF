"""Immutable observed batch r1: scope-local tx/2 evaluation and descending assembly.

This module has no discovery or persistence dependencies. Scope evidence is supplied
by the locked service on admission and by authoritative recorded rows on replay.
"""
from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, replace
from typing import Any

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.input_text import invalid_text_paths
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.core.versions import BATCH_RUNTIME_VERSION
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.models import ParsedPDCP
from app.pdcp.operations import OPERATION_JSON_SCHEMA, build_operations_record, parse_operations_record, to_parsed_operations
from app.pdcp.typed import TypedTransaction

BATCH_PROTOCOL_VERSION = "patchdiff-observed-batch/1"
BATCH_UNSET = object()
MAX_BATCH_SCOPES = 32
MAX_BATCH_OPERATIONS = 128
MAX_BATCH_TOTAL_SCOPE_CHARS = 65_536
MAX_BATCH_INITIAL_TEXT_CHARS = 32_768
BATCH_ERROR_CODES = (
    "INVALID_BATCH_REQUEST", "BATCH_LIMIT_EXCEEDED", "BUNDLE_RESPONSE_TOO_LARGE",
    "BUNDLE_SELECTION_NOT_FOUND", "BUNDLE_SELECTION_AMBIGUOUS", "BUNDLE_SCOPE_OVERLAP",
    "BUNDLE_SCOPE_DUPLICATE", "BUNDLE_NOT_FOUND", "BUNDLE_TARGET_MISMATCH",
    "BUNDLE_CYCLE_MISMATCH", "BUNDLE_VERSION_MISMATCH", "BUNDLE_HASH_MISMATCH",
    "BUNDLE_ALREADY_CONSUMED", "BATCH_GROUP_INVALID", "BATCH_OPERATION_OUTSIDE_SCOPE",
    "BATCH_OPERATION_REJECTED", "BATCH_REPLAY_INTEGRITY_FAILURE",
)
SELECTION_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["symbol_name"],
    "properties": {"symbol_name": {"type": "string", "minLength": 1, "pattern": r"\S"},
                   "kind": {"type": "string", "minLength": 1, "pattern": r"\S"}},
}
GROUP_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["observation_id", "operations"],
    "properties": {"observation_id": {"type": "string", "format": "uuid"},
                   "operations": {"type": "array", "minItems": 1, "maxItems": MAX_BATCH_OPERATIONS,
                                  "items": copy.deepcopy(OPERATION_JSON_SCHEMA)}},
}


class BatchValidationError(ValueError):
    def __init__(self, code: str, detail: str, *, group_index: int | None = None,
                 observation_id: str | None = None, underlying_code: str | None = None):
        super().__init__(detail)
        self.code = code
        self.diagnostic = {"code": code}
        if group_index is not None:
            self.diagnostic["group_index"] = group_index
        if observation_id is not None:
            self.diagnostic["observation_id"] = observation_id
        if underlying_code is not None:
            self.diagnostic["underlying_code"] = underlying_code


@dataclass(frozen=True, slots=True)
class BatchGroup:
    observation_id: str
    transaction: TypedTransaction


@dataclass(frozen=True, slots=True)
class BatchScope:
    observation_id: str
    bundle_ordinal: int
    scope_start: int
    scope_end: int
    observed_scope_hash: str

    def evidence(self) -> dict:
        return {"observation_id": self.observation_id, "bundle_ordinal": self.bundle_ordinal,
                "scope_start": self.scope_start, "scope_end": self.scope_end,
                "observed_scope_hash": self.observed_scope_hash}


def validate_batch_envelope(record: Any) -> tuple[str, ...]:
    fields = {"format", "target_file_id", "observation_bundle_id", "expected_target_version",
              "expected_current_hash", "intent", "groups"}
    if invalid_text_paths(record):
        raise BatchValidationError("INVALID_BATCH_REQUEST", "Batch strings must be UTF-8 without NUL.")
    if not isinstance(record, dict) or set(record) != fields or record.get("format") != BATCH_PROTOCOL_VERSION:
        raise BatchValidationError("INVALID_BATCH_REQUEST", "Invalid batch envelope.")
    if not isinstance(record["intent"], str) or not record["intent"].strip():
        raise BatchValidationError("INVALID_BATCH_REQUEST", "intent must be a nonempty string.")
    try:
        for key in ("target_file_id", "observation_bundle_id"):
            uuid.UUID(record[key])
    except (ValueError, TypeError, AttributeError):
        raise BatchValidationError("INVALID_BATCH_REQUEST", "Target and bundle IDs must be UUID strings.") from None
    if (type(record["expected_target_version"]) is not int or not 0 <= record["expected_target_version"] < 2**63
            or not isinstance(record["expected_current_hash"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["expected_current_hash"])):
        raise BatchValidationError("INVALID_BATCH_REQUEST", "Both version and SHA-256 guards are required.")
    groups = record["groups"]
    if not isinstance(groups, list) or not groups:
        raise BatchValidationError("INVALID_BATCH_REQUEST", "groups must be a nonempty array.")
    if len(groups) > MAX_BATCH_SCOPES:
        raise BatchValidationError("BATCH_LIMIT_EXCEEDED", "At most 32 groups are allowed.")
    seen = set()
    parsed = []
    count = 0
    for index, group in enumerate(groups):
        if not isinstance(group, dict) or set(group) != {"observation_id", "operations"}:
            raise BatchValidationError("BATCH_GROUP_INVALID", "Invalid group fields.", group_index=index)
        try:
            oid = str(uuid.UUID(group["observation_id"]))
        except (ValueError, TypeError, AttributeError):
            raise BatchValidationError("BATCH_GROUP_INVALID", "Invalid observation UUID.", group_index=index) from None
        if oid in seen:
            raise BatchValidationError("BATCH_GROUP_INVALID", "Repeated group observation.", group_index=index, observation_id=oid)
        seen.add(oid)
        if not isinstance(group["operations"], list) or not group["operations"]:
            raise BatchValidationError("BATCH_GROUP_INVALID", "Each group needs operations.", group_index=index, observation_id=oid)
        count += len(group["operations"])
        if count > MAX_BATCH_OPERATIONS:
            raise BatchValidationError("BATCH_LIMIT_EXCEEDED", "At most 128 operations are allowed.", group_index=index, observation_id=oid)
        parsed.append(oid)
    return tuple(parsed)


def parse_batch_request(record: Any) -> tuple[BatchGroup, ...]:
    observation_ids = validate_batch_envelope(record)
    parsed = []
    for index, (oid, group) in enumerate(zip(observation_ids, record["groups"])):
        from app.pdcp.protocol_validator import ProtocolValidationError
        try:
            typed = parse_operations_record(build_operations_record(
                target_file_id=record["target_file_id"], intent=record["intent"], operations=group["operations"],
                expected_target_version=record["expected_target_version"], expected_current_hash=record["expected_current_hash"]))
        except ProtocolValidationError as exc:
            raise BatchValidationError("BATCH_GROUP_INVALID", exc.failure_detail, group_index=index,
                                       observation_id=oid, underlying_code=exc.failure_reason.value) from exc
        # IDs are unique across the ledger even when groups use the same client IDs.
        typed = replace(typed, edits=tuple(replace(edit, change_id=f"g{index}:{edit.change_id}") for edit in typed.edits))
        parsed.append(BatchGroup(oid, typed))
    return tuple(parsed)


def flatten_batch(groups: tuple[BatchGroup, ...], *, target_type: str) -> tuple[ParsedPDCP, TypedTransaction]:
    typed = replace(groups[0].transaction, edits=tuple(edit for group in groups for edit in group.transaction.edits))
    changes = tuple(change for group in groups for change in to_parsed_operations(group.transaction, target_type=target_type).changes)
    parsed = to_parsed_operations(typed, target_type=target_type)
    return replace(parsed, header=replace(parsed.header, protocol_version=BATCH_PROTOCOL_VERSION),
                   changes=tuple(replace(change, change_index=index) for index, change in enumerate(changes, 1))), typed


def validate_scope_set(content: str, scopes: tuple[BatchScope, ...]) -> None:
    ordered = sorted(scopes, key=lambda scope: scope.scope_start)
    for index, scope in enumerate(ordered):
        if (type(scope.scope_start) is not int or type(scope.scope_end) is not int
                or not 0 <= scope.scope_start < scope.scope_end <= len(content)):
            raise BatchValidationError("BATCH_OPERATION_OUTSIDE_SCOPE", "Invalid original scope bounds.")
        if canonical_sha256(content[scope.scope_start:scope.scope_end]) != scope.observed_scope_hash:
            raise BatchValidationError("BUNDLE_HASH_MISMATCH", "Original scope hash differs.")
        if index and ordered[index - 1].scope_end > scope.scope_start:
            raise BatchValidationError("BUNDLE_SCOPE_OVERLAP", "Selected scopes overlap or nest.")


def apply_observed_batch(content: str, groups: tuple[BatchGroup, ...], scopes: tuple[BatchScope, ...],
                         *, target_type: str, collect_warnings: bool = True) -> AcceptedCoreResult | RejectedCoreResult:
    validate_scope_set(content, scopes)
    if len(scopes) != len(groups) or any(g.observation_id != s.observation_id for g, s in zip(groups, scopes)):
        raise BatchValidationError("BATCH_GROUP_INVALID", "Scope order must match group order.")
    outputs, facts, warnings = [], [], []
    no_op_transaction = None
    for index, (group, scope) in enumerate(zip(groups, scopes)):
        local = content[scope.scope_start:scope.scope_end]
        parsed = to_parsed_operations(group.transaction, target_type=target_type)
        # The service has checked the global guard; the local applier checks the actual slice hash.
        parsed = replace(parsed, header=replace(parsed.header, target_hash=scope.observed_scope_hash))
        result = apply_pdcp_transaction(local, parsed, allow_span_operations=True, allow_span_context=True,
                                        scope_bounds=(0, len(local)), collect_warnings=collect_warnings)
        if isinstance(result, RejectedCoreResult):
            underlying = (result.diagnostic or {}).get("code", result.failure_reason.value)
            code = "BATCH_OPERATION_OUTSIDE_SCOPE" if result.failure_reason == FailureReason.SPAN_OUT_OF_BOUNDS else "BATCH_OPERATION_REJECTED"
            return replace(result, before_hash=canonical_sha256(content), near_miss_buffer=None,
                           diagnostic={**(result.diagnostic or {}), "code": code, "group_index": index,
                                       "observation_id": group.observation_id, "underlying_code": underlying})
        outputs.append((scope.scope_start, scope.scope_end, result.target_content))
        for fact in result.change_facts:
            facts.append({**fact, "change_index": len(facts) + 1, "group_index": index,
                          "bundle_ordinal": scope.bundle_ordinal, "operation_index": fact["change_index"] - 1,
                          "observation_id": group.observation_id, "scope_start": scope.scope_start,
                          "scope_end": scope.scope_end, "scope_local_start": fact["span_start"],
                          "scope_local_end": fact["span_end"]})
        for warning in result.warnings:
            if warning["code"] == "no_op_transaction":
                no_op_transaction = warning
            else:
                warnings.append({**warning, "group_index": index})
    final = content
    for start, end, replacement in sorted(outputs, reverse=True):
        final = final[:start] + replacement + final[end:]
    if final == content and no_op_transaction is not None:
        warnings.append(no_op_transaction)
    return AcceptedCoreResult(before_hash=canonical_sha256(content), after_hash=canonical_sha256(final),
                              target_content=final, change_count=len(facts), change_facts=tuple(facts), warnings=tuple(warnings))
