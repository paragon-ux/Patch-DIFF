"""Parser for protocol-native declarative `.pdcp` transaction files."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.canonicalization import TextInput, canonicalize_text
from app.core.failures import FailureReason
from app.pdcp.models import (
    REQUIRED_MANIFEST_FIELDS,
    SUPPORTED_MANIFEST_FIELDS,
    SUPPORTED_PROTOCOL_VERSION,
    VALID_RISK_VALUES,
    PDCPChange,
    PDCPHeader,
    PDCPManifest,
    ParsedPDCP,
)
from app.pdcp.structural import is_executable_structural_line

PDCP_SIGNATURE = f"PDCP {SUPPORTED_PROTOCOL_VERSION}"
MATCH_DELIMITER = "<<<<<<< MATCH"
SEPARATOR_DELIMITER = "======="
REPLACE_DELIMITER = ">>>>>>> REPLACE"
DELIMITER_LINES = frozenset(
    {MATCH_DELIMITER, SEPARATOR_DELIMITER, REPLACE_DELIMITER}
)

@dataclass(frozen=True, slots=True)
class PDCPParseError(Exception):
    failure_reason: FailureReason
    failure_detail: str
    failed_change_id: str | None = None


def parse_pdcp(content: TextInput) -> ParsedPDCP:
    text = canonicalize_text(content)
    lines = text.split("\n")
    structural_lines: list[str] = []

    if not lines or lines[0] != PDCP_SIGNATURE:
        if lines and lines[0].startswith("C ="):
            raise _error(FailureReason.CONTEXT_INVALID, "Python-style PDCP headers are invalid.")
        raise _error(FailureReason.CONTEXT_INVALID, "Missing or invalid PDCP protocol header.")

    structural_lines.append(lines[0])
    index = 1
    header, index = _parse_header(lines, index, structural_lines)

    changes: list[PDCPChange] = []
    seen_change_ids: set[str] = set()
    while index < len(lines):
        line = lines[index]
        if line == "":
            structural_lines.append(line)
            index += 1
            continue
        _reject_executable_line(line)
        if line != "# MANIFEST":
            raise _error(FailureReason.MANIFEST_MISSING, "Expected # MANIFEST before change block.")

        structural_lines.append(line)
        manifest, index = _parse_manifest(lines, index + 1, structural_lines)
        if manifest.change_id in seen_change_ids:
            raise _error(
                FailureReason.MANIFEST_INVALID,
                "Duplicate change_id within PDCP file.",
                manifest.change_id,
            )
        seen_change_ids.add(manifest.change_id)

        while index < len(lines) and lines[index] == "":
            structural_lines.append(lines[index])
            index += 1
        if index >= len(lines) or lines[index] != MATCH_DELIMITER:
            raise _error(
                FailureReason.BLOCK_MALFORMED,
                "Expected MATCH delimiter after manifest.",
                manifest.change_id,
            )

        match_payload, replace_payload, index = _parse_block(
            lines, index, manifest.change_id, structural_lines
        )
        changes.append(
            PDCPChange(
                change_index=len(changes) + 1,
                manifest=manifest,
                match_payload=match_payload,
                replace_payload=replace_payload,
            )
        )

    if not changes:
        raise _error(FailureReason.MANIFEST_MISSING, "PDCP contains no manifest/change blocks.")

    return ParsedPDCP(
        header=header,
        changes=tuple(changes),
        structural_lines=tuple(structural_lines),
    )


def _parse_header(
    lines: list[str], index: int, structural_lines: list[str]
) -> tuple[PDCPHeader, int]:
    if index >= len(lines):
        raise _error(FailureReason.CONTEXT_MISSING, "Missing target_file_id header.")

    target_file_id, index = _required_header_value(
        lines, index, "target_file_id", "Missing target_file_id header.", structural_lines
    )
    target_type, index = _required_header_value(
        lines, index, "target_type", "Missing target_type header.", structural_lines
    )

    target_hash: str | None = None
    if index < len(lines) and lines[index].startswith("target_hash:"):
        structural_lines.append(lines[index])
        target_hash = _split_header_line(lines[index], "target_hash")
        if target_hash == "":
            raise _error(FailureReason.CONTEXT_INVALID, "target_hash header must not be empty.")
        index += 1

    if index < len(lines):
        line = lines[index]
        if line and not line.startswith("# MANIFEST"):
            _reject_executable_line(line)
            if ":" in line and not line.startswith("# "):
                raise _error(FailureReason.CONTEXT_INVALID, "Unknown header field.")

    return (
        PDCPHeader(
            protocol_version=SUPPORTED_PROTOCOL_VERSION,
            target_file_id=target_file_id,
            target_type=target_type,
            target_hash=target_hash,
        ),
        index,
    )


def _required_header_value(
    lines: list[str],
    index: int,
    field_name: str,
    missing_detail: str,
    structural_lines: list[str],
) -> tuple[str, int]:
    if index >= len(lines) or not lines[index].startswith(f"{field_name}:"):
        raise _error(FailureReason.CONTEXT_MISSING, missing_detail)

    structural_lines.append(lines[index])
    value = _split_header_line(lines[index], field_name)
    if value == "":
        raise _error(FailureReason.CONTEXT_MISSING, missing_detail)
    return value, index + 1


def _split_header_line(line: str, field_name: str) -> str:
    prefix = f"{field_name}:"
    if not line.startswith(prefix):
        raise _error(FailureReason.CONTEXT_INVALID, f"Malformed {field_name} header.")
    value = line[len(prefix) :]
    return value[1:] if value.startswith(" ") else value


def _parse_manifest(
    lines: list[str], index: int, structural_lines: list[str]
) -> tuple[PDCPManifest, int]:
    fields: dict[str, str] = {}
    while index < len(lines):
        line = lines[index]
        if line == MATCH_DELIMITER:
            break
        if line == "":
            structural_lines.append(line)
            index += 1
            continue
        _reject_executable_line(line)
        if not line.startswith("# "):
            raise _error(FailureReason.MANIFEST_INVALID, "Manifest line must start with '# '.")
        if line == "# MANIFEST":
            raise _error(FailureReason.MANIFEST_INVALID, "Unexpected nested manifest block.")

        structural_lines.append(line)
        field, value = _parse_manifest_field(line)
        if field not in SUPPORTED_MANIFEST_FIELDS:
            raise _error(FailureReason.MANIFEST_INVALID, f"Unsupported manifest field: {field}.")
        if field in fields:
            raise _error(FailureReason.MANIFEST_INVALID, f"Duplicate manifest field: {field}.")
        if value.strip() == "":
            raise _error(FailureReason.MANIFEST_INVALID, f"Empty manifest field: {field}.")
        fields[field] = value
        index += 1

    missing_fields = REQUIRED_MANIFEST_FIELDS - fields.keys()
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise _error(FailureReason.MANIFEST_INVALID, f"Missing manifest field(s): {missing}.")
    if fields["risk"] not in VALID_RISK_VALUES:
        raise _error(FailureReason.MANIFEST_INVALID, "Invalid manifest risk value.")

    return PDCPManifest.from_fields(fields), index


def _parse_manifest_field(line: str) -> tuple[str, str]:
    body = line[2:]
    if ":" not in body:
        raise _error(FailureReason.MANIFEST_INVALID, "Manifest field is missing ':'.")
    field, raw_value = body.split(":", 1)
    if field == "" or field.strip() != field:
        raise _error(FailureReason.MANIFEST_INVALID, "Manifest field name is invalid.")
    value = raw_value[1:] if raw_value.startswith(" ") else raw_value
    return field, value


def _parse_block(
    lines: list[str],
    index: int,
    change_id: str,
    structural_lines: list[str],
) -> tuple[str, str, int]:
    structural_lines.append(lines[index])
    index += 1
    match_lines: list[str] = []
    while index < len(lines):
        line = lines[index]
        if line == SEPARATOR_DELIMITER:
            break
        if line in {MATCH_DELIMITER, REPLACE_DELIMITER}:
            raise _error(FailureReason.BLOCK_MALFORMED, "Delimiter collision in MATCH payload.", change_id)
        match_lines.append(line)
        index += 1

    if index >= len(lines) or lines[index] != SEPARATOR_DELIMITER:
        raise _error(FailureReason.BLOCK_MALFORMED, "Missing MATCH/REPLACE separator.", change_id)
    structural_lines.append(lines[index])
    index += 1

    replace_lines: list[str] = []
    while index < len(lines):
        line = lines[index]
        if line == REPLACE_DELIMITER:
            break
        if line in {MATCH_DELIMITER, SEPARATOR_DELIMITER}:
            raise _error(FailureReason.BLOCK_MALFORMED, "Delimiter collision in REPLACE payload.", change_id)
        replace_lines.append(line)
        index += 1

    if index >= len(lines) or lines[index] != REPLACE_DELIMITER:
        raise _error(FailureReason.BLOCK_MALFORMED, "Missing REPLACE delimiter.", change_id)
    structural_lines.append(lines[index])
    index += 1

    match_payload = canonicalize_text("\n".join(match_lines))
    replace_payload = canonicalize_text("\n".join(replace_lines))
    if match_payload == "":
        raise _error(FailureReason.BLOCK_MALFORMED, "MATCH payload must not be empty.", change_id)

    return match_payload, replace_payload, index


def _reject_executable_line(line: str) -> None:
    if is_executable_structural_line(line):
        raise _error(
            FailureReason.EXECUTABLE_LOGIC_DETECTED,
            "Executable-looking logic is not allowed outside payloads.",
        )


def _error(
    reason: FailureReason, detail: str, failed_change_id: str | None = None
) -> PDCPParseError:
    return PDCPParseError(reason, detail, failed_change_id)
