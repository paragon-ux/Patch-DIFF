"""Typed PatchDIFF transaction input (`patchdiff-tx/1`).

A typed transaction carries exact payload strings as fields instead of inside a
delimited text envelope. It is decoded into the same ``ParsedPDCP`` structure the
PDCP parser produces, so exactly one applier validates and applies both inputs.

This module is pure: no SQL, FastAPI, MCP, or model dependencies. It never builds
textual PDCP, so delimiter collisions cannot be reintroduced by interpolation.
It also defines the authoritative JSON Schema for typed edit items so MCP tool
discovery and runtime validation stay in lockstep.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.core.failures import FailureReason
from app.core.input_text import invalid_text_paths
from app.core.versions import (
    LEGACY_RUNTIME_VERSION, PREVIOUS_RUNTIME_VERSION, RUNTIME_VERSION,
    resolve_overlapping_matches,
)
from app.pdcp.models import (
    VALID_RISK_VALUES,
    PDCPChange,
    PDCPHeader,
    PDCPManifest,
    ParsedPDCP,
)
from app.pdcp.protocol_validator import ProtocolValidationError

TYPED_PROTOCOL_VERSION = "patchdiff-tx/1"

_TOP_LEVEL_KEYS = frozenset(
    {
        "format",
        "target_file_id",
        "expected_target_version",
        "expected_current_hash",
        "intent",
        "edits",
    }
)
REQUIRED_TYPED_EDIT_FIELDS = ("match", "replace")
ALLOWED_TYPED_EDIT_FIELDS = (
    "anchor_after",
    "anchor_before",
    "change_id",
    "match",
    "occurrence_index",
    "rationale",
    "replace",
    "risk",
)
_EDIT_KEYS = frozenset(ALLOWED_TYPED_EDIT_FIELDS)
_CHANGE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CLIENT_REQUEST_ID_RE = re.compile(r"^[\x21-\x7e]{1,128}$")

# Authoritative JSON Schema for an element of `edits[]` in `patchdiff_submit_edits`.
TYPED_EDIT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["match", "replace"],
    "additionalProperties": False,
    "properties": {
        "match": {
            "type": "string",
            "minLength": 1,
            "description": "Exact canonical substring to match (non-empty).",
        },
        "replace": {
            "type": "string",
            "description": "Exact replacement text (empty string deletes the matched span).",
        },
        "change_id": {
            "type": ["string", "null"],
            "pattern": r"^[A-Za-z0-9_.:-]{1,64}(?![\s\S])",
            "description": "Optional unique identifier within the transaction (defaults to chg_001, ...).",
        },
        "rationale": {
            "type": ["string", "null"],
            "minLength": 1,
            "pattern": r"\S",
            "description": "Optional advisory rationale for this individual edit.",
        },
        "risk": {
            "type": ["string", "null"],
            "enum": ["low", "medium", "high", None],
            "description": "Optional advisory risk level.",
        },
        "occurrence_index": {
            "type": ["integer", "null"],
            "minimum": 1,
            "description": "Optional 1-based index into all exact occurrences (including overlaps).",
        },
        "anchor_before": {
            "type": ["string", "null"],
            "minLength": 1,
            "description": "Optional exact substring that must precede the selected match.",
        },
        "anchor_after": {
            "type": ["string", "null"],
            "minLength": 1,
            "description": "Optional exact substring that must follow the selected match.",
        },
    },
}


@dataclass(frozen=True, slots=True)
class TypedEdit:
    change_id: str
    match: str
    replace: str
    rationale: str | None = None
    risk: str | None = None
    occurrence_index: int | None = None
    anchor_before: str | None = None
    anchor_after: str | None = None


@dataclass(frozen=True, slots=True)
class TypedTransaction:
    target_file_id: str
    intent: str
    edits: tuple[TypedEdit, ...]
    expected_target_version: int | None = None
    expected_current_hash: str | None = None


def validate_client_request_id(client_request_id: Any) -> str | None:
    """Validate optional caller-supplied idempotency key (`client_request_id`)."""

    if client_request_id is None:
        return None
    if not isinstance(client_request_id, str) or not _CLIENT_REQUEST_ID_RE.fullmatch(client_request_id):
        raise _error(
            FailureReason.CONTEXT_INVALID,
            "client_request_id must be 1..128 printable ASCII characters without whitespace.",
        )
    return client_request_id


def build_record(
    *,
    target_file_id: str,
    intent: Any,
    edits: Any,
    expected_target_version: int | None,
    expected_current_hash: str | None,
) -> dict[str, Any]:
    """Assemble the (untrusted) record dict exactly as submitted, plus the format tag."""

    return {
        "format": TYPED_PROTOCOL_VERSION,
        "target_file_id": target_file_id,
        "expected_target_version": expected_target_version,
        "expected_current_hash": expected_current_hash,
        "intent": intent,
        "edits": edits,
    }


def canonical_record_json(record: Mapping[str, Any]) -> str:
    """Deterministic JSON text for a record. Same record -> same text -> same hash."""

    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def decode_record(text: str, *, runtime_version: str = RUNTIME_VERSION) -> TypedTransaction:
    """Decode recorded history under its explicit runtime validation profile."""

    resolve_overlapping_matches(runtime_version)  # Reject unknown profiles before decoding.

    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _error(FailureReason.CONTEXT_INVALID, f"Typed record is not valid JSON: {exc.msg}.") from exc
    return _parse_typed_record(
        record, legacy_change_ids=runtime_version in {LEGACY_RUNTIME_VERSION, PREVIOUS_RUNTIME_VERSION},
    )


def parse_typed_record(record: Any) -> TypedTransaction:
    """Validate an untrusted record and return the typed transaction."""

    if invalid_text_paths(record):
        raise _error(FailureReason.TARGET_ENCODING_INVALID, "Input strings must be UTF-8 without NUL.")
    return _parse_typed_record(record, legacy_change_ids=False)


def _parse_typed_record(record: Any, *, legacy_change_ids: bool) -> TypedTransaction:

    if not isinstance(record, Mapping):
        raise _error(FailureReason.CONTEXT_INVALID, "Typed transaction must be an object.")

    unknown = set(record) - _TOP_LEVEL_KEYS
    if unknown:
        raise _error(
            FailureReason.CONTEXT_INVALID,
            f"Unknown typed transaction field(s): {', '.join(sorted(map(str, unknown)))}.",
        )
    if record.get("format") != TYPED_PROTOCOL_VERSION:
        raise _error(FailureReason.CONTEXT_INVALID, "Unsupported typed transaction format.")

    target_file_id = record.get("target_file_id")
    if not isinstance(target_file_id, str) or target_file_id.strip() == "":
        raise _error(FailureReason.CONTEXT_MISSING, "target_file_id is required.")

    version = record.get("expected_target_version")
    if version is not None and (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < 0
        or version > (2**63 - 1)
    ):
        raise _error(FailureReason.CONTEXT_INVALID, "expected_target_version must be a non-negative integer.")

    expected_hash = record.get("expected_current_hash")
    if expected_hash is not None and (not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash)):
        raise _error(FailureReason.CONTEXT_INVALID, "expected_current_hash must be lowercase SHA-256 hex.")

    intent = record.get("intent")
    if intent is None or (isinstance(intent, str) and intent.strip() == ""):
        raise _error(FailureReason.MANIFEST_MISSING, "intent is required.")
    if not isinstance(intent, str):
        raise _error(FailureReason.MANIFEST_INVALID, "intent must be a string.")

    raw_edits = record.get("edits")
    if raw_edits is None or (isinstance(raw_edits, list) and not raw_edits):
        raise _error(FailureReason.MANIFEST_MISSING, "edits must contain at least one edit.")
    if not isinstance(raw_edits, list):
        raise _error(FailureReason.MANIFEST_INVALID, "edits must be an array.")

    edits: list[TypedEdit] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_edits, start=1):
        edit = _parse_edit(raw, index, legacy_change_ids=legacy_change_ids)
        if edit.change_id in seen_ids:
            raise _error(FailureReason.MANIFEST_INVALID, "Duplicate change_id.", edit.change_id)
        seen_ids.add(edit.change_id)
        edits.append(edit)

    return TypedTransaction(
        target_file_id=target_file_id,
        intent=intent,
        edits=tuple(edits),
        expected_target_version=version,
        expected_current_hash=expected_hash,
    )


def to_parsed_transaction(transaction: TypedTransaction, *, target_type: str) -> ParsedPDCP:
    """Map a typed transaction onto the structure the shared applier consumes.

    Only fields the applier reads are populated on the manifest: ``change_id`` and
    disambiguation. Advisory text stays on ``TypedTransaction`` and never reaches
    matching. The header ``target_hash`` is left unset: guards are enforced by the
    service guard path, not by the PDCP header precondition.
    """

    changes: list[PDCPChange] = []
    for index, edit in enumerate(transaction.edits, start=1):
        fields: dict[str, str] = {"change_id": edit.change_id}
        if edit.occurrence_index is not None:
            fields["occurrence_index"] = str(edit.occurrence_index)
        if edit.anchor_before is not None:
            fields["anchor_before"] = edit.anchor_before
        if edit.anchor_after is not None:
            fields["anchor_after"] = edit.anchor_after
        changes.append(
            PDCPChange(
                change_index=index,
                manifest=PDCPManifest(fields=MappingProxyType(fields)),
                match_payload=edit.match,
                replace_payload=edit.replace,
            )
        )
    return ParsedPDCP(
        header=PDCPHeader(
            protocol_version=TYPED_PROTOCOL_VERSION,
            target_file_id=transaction.target_file_id,
            target_type=target_type,
            target_hash=None,
        ),
        changes=tuple(changes),
        structural_lines=(),
    )


def _parse_edit(raw: Any, index: int, *, legacy_change_ids: bool) -> TypedEdit:
    default_id = f"chg_{index:03d}"
    if not isinstance(raw, Mapping):
        raise _error(FailureReason.MANIFEST_INVALID, "Each edit must be an object.", default_id)

    raw_id = raw.get("change_id")
    change_id = default_id if raw_id is None else raw_id
    # Historical profiles preserve accepted IDs byte-for-byte; new proposals are strict.
    match_id = _CHANGE_ID_RE.match if legacy_change_ids else _CHANGE_ID_RE.fullmatch
    if not isinstance(change_id, str) or not match_id(change_id):
        raise _error(FailureReason.MANIFEST_INVALID, "change_id must match [A-Za-z0-9_.:-]{1,64}.", default_id)

    unknown = set(raw) - _EDIT_KEYS
    if unknown:
        raise _error(
            FailureReason.MANIFEST_INVALID,
            f"Unknown edit field(s): {', '.join(sorted(map(str, unknown)))}.",
            change_id,
        )

    match = raw.get("match")
    replace = raw.get("replace")
    if not isinstance(match, str):
        raise _error(FailureReason.BLOCK_MALFORMED, "match must be a string.", change_id)
    if match == "":
        raise _error(FailureReason.BLOCK_MALFORMED, "MATCH payload must not be empty.", change_id)
    if not isinstance(replace, str):
        raise _error(FailureReason.BLOCK_MALFORMED, "replace must be a string (empty string deletes).", change_id)

    rationale = raw.get("rationale")
    if rationale is not None and (not isinstance(rationale, str) or rationale.strip() == ""):
        raise _error(FailureReason.MANIFEST_INVALID, "rationale must be a non-empty string when present.", change_id)

    risk = raw.get("risk")
    if risk is not None and (not isinstance(risk, str) or risk not in VALID_RISK_VALUES):
        raise _error(FailureReason.MANIFEST_INVALID, "Invalid risk value.", change_id)

    occurrence_index = raw.get("occurrence_index")
    if occurrence_index is not None and (
        isinstance(occurrence_index, bool) or not isinstance(occurrence_index, int) or occurrence_index < 1
    ):
        raise _error(FailureReason.MANIFEST_INVALID, "occurrence_index must be a positive integer.", change_id)

    anchors: dict[str, str | None] = {}
    for key in ("anchor_before", "anchor_after"):
        value = raw.get(key)
        if value is not None and (not isinstance(value, str) or value == ""):
            raise _error(FailureReason.MANIFEST_INVALID, f"{key} must be a non-empty string when present.", change_id)
        anchors[key] = value

    return TypedEdit(
        change_id=change_id,
        match=match,
        replace=replace,
        rationale=rationale,
        risk=risk,
        occurrence_index=occurrence_index,
        anchor_before=anchors["anchor_before"],
        anchor_after=anchors["anchor_after"],
    )


def _error(
    reason: FailureReason,
    detail: str,
    failed_change_id: str | None = None,
) -> ProtocolValidationError:
    return ProtocolValidationError(
        failure_reason=reason,
        failure_detail=detail,
        failed_change_id=failed_change_id,
    )
