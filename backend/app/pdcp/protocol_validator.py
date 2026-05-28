"""Protocol validation for parsed declarative PDCP transaction objects."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.failures import FailureReason
from app.pdcp.models import (
    REQUIRED_MANIFEST_FIELDS,
    SUPPORTED_MANIFEST_FIELDS,
    SUPPORTED_PROTOCOL_VERSION,
    VALID_RISK_VALUES,
    ParsedPDCP,
)
from app.pdcp.parser import (
    MATCH_DELIMITER,
    PDCP_SIGNATURE,
    REPLACE_DELIMITER,
    SEPARATOR_DELIMITER,
)
from app.pdcp.structural import is_executable_structural_line

SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ProtocolValidationError(Exception):
    failure_reason: FailureReason
    failure_detail: str
    failed_change_id: str | None = None


def validate_pdcp(parsed: ParsedPDCP) -> None:
    """Validate parsed PDCP structure without inspecting target applicability."""

    _validate_header(parsed)
    _validate_structural_lines(parsed.structural_lines)

    seen_change_ids: set[str] = set()
    for change in parsed.changes:
        manifest = change.manifest
        fields = manifest.fields
        change_id = fields.get("change_id")

        missing = REQUIRED_MANIFEST_FIELDS - fields.keys()
        if missing:
            raise _error(
                FailureReason.MANIFEST_INVALID,
                f"Missing manifest field(s): {', '.join(sorted(missing))}.",
                change_id,
            )
        unsupported = set(fields.keys()) - SUPPORTED_MANIFEST_FIELDS
        if unsupported:
            raise _error(
                FailureReason.MANIFEST_INVALID,
                f"Unsupported manifest field(s): {', '.join(sorted(unsupported))}.",
                change_id,
            )

        for field_name, value in fields.items():
            if value.strip() == "":
                raise _error(
                    FailureReason.MANIFEST_INVALID,
                    f"Empty manifest field: {field_name}.",
                    change_id,
                )

        if fields["risk"] not in VALID_RISK_VALUES:
            raise _error(FailureReason.MANIFEST_INVALID, "Invalid risk value.", change_id)
        if change_id in seen_change_ids:
            raise _error(FailureReason.MANIFEST_INVALID, "Duplicate change_id.", change_id)
        seen_change_ids.add(change_id)

        _validate_occurrence_index(fields.get("occurrence_index"), change_id)
        _validate_manifest_hash(parsed.header.target_hash, fields.get("target_hash"), change_id)

        if change.match_payload == "":
            raise _error(FailureReason.BLOCK_MALFORMED, "MATCH payload must not be empty.", change_id)


def _validate_header(parsed: ParsedPDCP) -> None:
    header = parsed.header
    if header.protocol_version != SUPPORTED_PROTOCOL_VERSION:
        raise _error(FailureReason.CONTEXT_INVALID, "Unsupported PDCP protocol version.")
    if header.target_file_id.strip() == "":
        raise _error(FailureReason.CONTEXT_MISSING, "target_file_id is required.")
    if header.target_type.strip() == "":
        raise _error(FailureReason.CONTEXT_MISSING, "target_type is required.")
    if header.target_hash is not None and not _is_sha256_hex(header.target_hash):
        raise _error(FailureReason.CONTEXT_INVALID, "target_hash must be lowercase SHA-256 hex.")


def _validate_structural_lines(lines: tuple[str, ...]) -> None:
    for line in lines:
        if is_executable_structural_line(line):
            raise _error(
                FailureReason.EXECUTABLE_LOGIC_DETECTED,
                "Executable-looking logic is not allowed outside payloads.",
            )
        if _is_allowed_structural_line(line):
            continue
        raise _error(FailureReason.CONTEXT_INVALID, "Invalid non-payload PDCP structure.")


def _is_allowed_structural_line(line: str) -> bool:
    return (
        line == ""
        or line == PDCP_SIGNATURE
        or line == "# MANIFEST"
        or line == MATCH_DELIMITER
        or line == SEPARATOR_DELIMITER
        or line == REPLACE_DELIMITER
        or line.startswith("target_file_id:")
        or line.startswith("target_type:")
        or line.startswith("target_hash:")
        or line.startswith("# ")
    )


def _validate_occurrence_index(value: str | None, change_id: str | None) -> None:
    if value is None:
        return
    if not value.isdigit() or int(value) < 1:
        raise _error(FailureReason.MANIFEST_INVALID, "occurrence_index must be a positive integer.", change_id)


def _validate_manifest_hash(
    header_target_hash: str | None,
    manifest_target_hash: str | None,
    change_id: str | None,
) -> None:
    if manifest_target_hash is None:
        return
    if not _is_sha256_hex(manifest_target_hash):
        raise _error(
            FailureReason.MANIFEST_INVALID,
            "Manifest target_hash must be lowercase SHA-256 hex.",
            change_id,
        )
    if header_target_hash is not None and header_target_hash != manifest_target_hash:
        raise _error(
            FailureReason.TARGET_HASH_MISMATCH,
            "Header target_hash and manifest target_hash conflict.",
            change_id,
        )


def _is_sha256_hex(value: str) -> bool:
    return bool(SHA256_HEX_RE.fullmatch(value))


def _error(
    reason: FailureReason, detail: str, failed_change_id: str | None = None
) -> ProtocolValidationError:
    return ProtocolValidationError(reason, detail, failed_change_id)
