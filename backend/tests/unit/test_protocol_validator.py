import pytest

from app.core.failures import FailureReason
from app.pdcp.models import PDCPChange, PDCPHeader, PDCPManifest, ParsedPDCP
from app.pdcp.parser import parse_pdcp
import app.pdcp.protocol_validator as protocol_validator
from app.pdcp.protocol_validator import ProtocolValidationError, validate_pdcp


def valid_pdcp(match: str = "old", replace: str = "new") -> str:
    return f"""PDCP 0.2.3
target_file_id: target_123
target_type: text/plain

# MANIFEST
# change_id: chg_001
# intent: Update text.
# input_state: Old text exists.
# output_state: New text exists.
# affected_region: example
# user_visible_change: Text changes.
# risk: low

<<<<<<< MATCH
{match}
=======
{replace}
>>>>>>> REPLACE"""


def assert_validation_rejects(parsed: ParsedPDCP, reason: FailureReason) -> None:
    with pytest.raises(ProtocolValidationError) as exc_info:
        validate_pdcp(parsed)
    assert exc_info.value.failure_reason is reason


def test_valid_parsed_pdcp_validates() -> None:
    validate_pdcp(parse_pdcp(valid_pdcp()))


def test_invalid_protocol_version_rejects() -> None:
    parsed = _parsed_with(header=PDCPHeader("0.1.0", "target_123", "text/plain"))
    assert_validation_rejects(parsed, FailureReason.CONTEXT_INVALID)


def test_missing_header_values_reject() -> None:
    assert_validation_rejects(
        _parsed_with(header=PDCPHeader("0.2.3", "", "text/plain")),
        FailureReason.CONTEXT_MISSING,
    )
    assert_validation_rejects(
        _parsed_with(header=PDCPHeader("0.2.3", "target_123", "")),
        FailureReason.CONTEXT_MISSING,
    )


def test_invalid_header_hash_shape_rejects() -> None:
    parsed = _parsed_with(header=PDCPHeader("0.2.3", "target_123", "text/plain", "abc"))
    assert_validation_rejects(parsed, FailureReason.CONTEXT_INVALID)


def test_header_manifest_target_hash_conflict_rejects_target_hash_mismatch() -> None:
    header_hash = "a" * 64
    manifest_hash = "b" * 64
    parsed = _parsed_with(
        header=PDCPHeader("0.2.3", "target_123", "text/plain", header_hash),
        fields={"target_hash": manifest_hash},
    )
    assert_validation_rejects(parsed, FailureReason.TARGET_HASH_MISMATCH)


def test_matching_header_manifest_target_hash_validates() -> None:
    digest = "a" * 64
    parsed = _parsed_with(
        header=PDCPHeader("0.2.3", "target_123", "text/plain", digest),
        fields={"target_hash": digest},
    )
    validate_pdcp(parsed)


def test_invalid_manifest_hash_shape_rejects() -> None:
    parsed = _parsed_with(fields={"target_hash": "ABC"})
    assert_validation_rejects(parsed, FailureReason.MANIFEST_INVALID)


def test_invalid_occurrence_index_rejects() -> None:
    for value in ("0", "-1", "abc"):
        assert_validation_rejects(_parsed_with(fields={"occurrence_index": value}), FailureReason.MANIFEST_INVALID)


def test_invalid_risk_rejects() -> None:
    parsed = _parsed_with(fields={"risk": "severe"})
    assert_validation_rejects(parsed, FailureReason.MANIFEST_INVALID)


def test_duplicate_change_ids_reject() -> None:
    first = _change("chg_001")
    second = _change("chg_001", index=2)
    parsed = ParsedPDCP(
        header=PDCPHeader("0.2.3", "target_123", "text/plain"),
        changes=(first, second),
        structural_lines=("PDCP 0.2.3", "target_file_id: target_123", "target_type: text/plain"),
    )
    assert_validation_rejects(parsed, FailureReason.MANIFEST_INVALID)


def test_executable_structural_content_rejects() -> None:
    parsed = _parsed_with(structural_lines=("PDCP 0.2.3", "def applyPDCP():"))
    assert_validation_rejects(parsed, FailureReason.EXECUTABLE_LOGIC_DETECTED)


def test_invalid_freeform_structural_content_rejects() -> None:
    parsed = _parsed_with(structural_lines=("PDCP 0.2.3", "freeform prose"))
    assert_validation_rejects(parsed, FailureReason.CONTEXT_INVALID)


def test_code_like_payload_content_remains_allowed() -> None:
    parsed = _parsed_with(match_payload="def old():\n    pass", replace_payload="def old():\n    return True")
    validate_pdcp(parsed)


def test_validator_does_not_import_storage_mcp_or_model_code() -> None:
    import inspect

    validate_pdcp(parse_pdcp(valid_pdcp()))
    source = inspect.getsource(protocol_validator)
    assert "app.storage" not in source
    assert "app.services" not in source
    assert "app.api" not in source


def _parsed_with(
    *,
    header: PDCPHeader | None = None,
    fields: dict[str, str] | None = None,
    structural_lines: tuple[str, ...] | None = None,
    match_payload: str = "old",
    replace_payload: str = "new",
) -> ParsedPDCP:
    return ParsedPDCP(
        header=header or PDCPHeader("0.2.3", "target_123", "text/plain"),
        changes=(_change("chg_001", fields=fields, match_payload=match_payload, replace_payload=replace_payload),),
        structural_lines=structural_lines
        or ("PDCP 0.2.3", "target_file_id: target_123", "target_type: text/plain"),
    )


def _change(
    change_id: str,
    *,
    index: int = 1,
    fields: dict[str, str] | None = None,
    match_payload: str = "old",
    replace_payload: str = "new",
) -> PDCPChange:
    manifest_fields = {
        "change_id": change_id,
        "intent": "Update text.",
        "input_state": "Old text exists.",
        "output_state": "New text exists.",
        "affected_region": "example",
        "user_visible_change": "Text changes.",
        "risk": "low",
    }
    if fields:
        manifest_fields.update(fields)
    return PDCPChange(
        change_index=index,
        manifest=PDCPManifest.from_fields(manifest_fields),
        match_payload=match_payload,
        replace_payload=replace_payload,
    )
