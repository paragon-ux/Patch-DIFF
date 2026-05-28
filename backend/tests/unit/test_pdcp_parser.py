import pytest

from app.core.failures import FailureReason
from app.pdcp.parser import PDCPParseError, parse_pdcp


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


def assert_rejects(content: str, reason: FailureReason) -> None:
    with pytest.raises(PDCPParseError) as exc_info:
        parse_pdcp(content)
    assert exc_info.value.failure_reason is reason


def test_minimal_valid_pdcp_parses() -> None:
    parsed = parse_pdcp(valid_pdcp())
    assert parsed.header.protocol_version == "0.2.3"
    assert parsed.header.target_file_id == "target_123"
    assert parsed.header.target_type == "text/plain"
    assert parsed.changes[0].manifest.change_id == "chg_001"
    assert parsed.changes[0].match_payload == "old"
    assert parsed.changes[0].replace_payload == "new"


def test_multiple_change_pdcp_parses() -> None:
    content = valid_pdcp() + """

# MANIFEST
# change_id: chg_002
# intent: Update more text.
# input_state: More old text exists.
# output_state: More new text exists.
# affected_region: second example
# user_visible_change: More text changes.
# risk: medium

<<<<<<< MATCH
before
=======
after
>>>>>>> REPLACE"""
    parsed = parse_pdcp(content)
    assert [change.manifest.change_id for change in parsed.changes] == ["chg_001", "chg_002"]


def test_header_level_target_hash_parses() -> None:
    digest = "a" * 64
    parsed = parse_pdcp(valid_pdcp().replace("target_type: text/plain", f"target_type: text/plain\ntarget_hash: {digest}"))
    assert parsed.header.target_hash == digest


def test_manifest_optional_disambiguation_fields_parse() -> None:
    digest = "b" * 64
    content = valid_pdcp().replace(
        "# risk: low",
        "\n".join(
            [
                "# risk: low",
                "# anchor_before: intro",
                "# anchor_after: outro",
                "# occurrence_index: 2",
                "# region_hint: body",
                f"# target_hash: {digest}",
            ]
        ),
    )
    parsed = parse_pdcp(content)
    assert parsed.changes[0].manifest.disambiguation == {
        "anchor_before": "intro",
        "anchor_after": "outro",
        "occurrence_index": "2",
        "region_hint": "body",
        "target_hash": digest,
    }


def test_manifest_values_keep_additional_colons() -> None:
    parsed = parse_pdcp(valid_pdcp().replace("# intent: Update text.", "# intent: Update section: details."))
    assert parsed.changes[0].manifest.fields["intent"] == "Update section: details."


def test_python_style_header_rejects() -> None:
    assert_rejects('C = "target_file_id:target_123"\n', FailureReason.CONTEXT_INVALID)


def test_unknown_header_field_rejects() -> None:
    content = valid_pdcp().replace("target_type: text/plain", "target_type: text/plain\nunknown: nope")
    assert_rejects(content, FailureReason.CONTEXT_INVALID)


def test_missing_target_file_id_rejects() -> None:
    assert_rejects(valid_pdcp().replace("target_file_id: target_123\n", ""), FailureReason.CONTEXT_MISSING)


def test_missing_target_type_rejects() -> None:
    assert_rejects(valid_pdcp().replace("target_type: text/plain\n", ""), FailureReason.CONTEXT_MISSING)


def test_missing_manifest_rejects() -> None:
    content = """PDCP 0.2.3
target_file_id: target_123
target_type: text/plain

<<<<<<< MATCH
old
=======
new
>>>>>>> REPLACE"""
    assert_rejects(content, FailureReason.MANIFEST_MISSING)


def test_missing_required_manifest_field_rejects() -> None:
    assert_rejects(valid_pdcp().replace("# risk: low\n", ""), FailureReason.MANIFEST_INVALID)


def test_duplicate_manifest_field_rejects() -> None:
    assert_rejects(valid_pdcp().replace("# risk: low", "# risk: low\n# risk: medium"), FailureReason.MANIFEST_INVALID)


def test_empty_manifest_value_rejects() -> None:
    assert_rejects(valid_pdcp().replace("# intent: Update text.", "# intent: "), FailureReason.MANIFEST_INVALID)


def test_invalid_risk_rejects() -> None:
    assert_rejects(valid_pdcp().replace("# risk: low", "# risk: severe"), FailureReason.MANIFEST_INVALID)


def test_duplicate_change_id_rejects() -> None:
    content = valid_pdcp() + "\n\n" + valid_pdcp().split("\n", 4)[4]
    assert_rejects(content, FailureReason.MANIFEST_INVALID)


def test_malformed_delimiters_reject() -> None:
    assert_rejects(valid_pdcp().replace("=======", "----"), FailureReason.BLOCK_MALFORMED)


def test_empty_match_rejects() -> None:
    content = valid_pdcp(match="")
    assert_rejects(content, FailureReason.BLOCK_MALFORMED)


def test_delimiter_collision_rejects() -> None:
    content = valid_pdcp(replace="new\n<<<<<<< MATCH")
    assert_rejects(content, FailureReason.BLOCK_MALFORMED)


def test_executable_logic_outside_payload_rejects() -> None:
    content = valid_pdcp().replace("# MANIFEST", "def applyPDCP():\n    pass\n\n# MANIFEST")
    assert_rejects(content, FailureReason.EXECUTABLE_LOGIC_DETECTED)


def test_code_like_text_inside_payload_is_allowed() -> None:
    parsed = parse_pdcp(valid_pdcp(match="def existing():\n    pass", replace="def existing():\n    return True"))
    assert parsed.changes[0].match_payload == "def existing():\n    pass"
