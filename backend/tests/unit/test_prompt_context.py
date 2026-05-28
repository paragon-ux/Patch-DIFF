from app.services.prompt_context_service import pdcp_rules_text


def test_pdcp_rules_are_declarative_and_non_executable() -> None:
    rules = pdcp_rules_text()
    assert ".pdcp" in rules
    assert "non-executable" in rules
    assert "MATCH/REPLACE" in rules
    assert "apply functions" in rules


def test_pdcp_rules_include_complete_manifest_and_delimiter_contract() -> None:
    rules = pdcp_rules_text(
        target_file_id="target-123",
        target_type="text/plain",
        current_hash="a" * 64,
        target_context="Original sentence.",
    )

    for field in [
        "change_id",
        "intent",
        "input_state",
        "output_state",
        "affected_region",
        "user_visible_change",
        "risk",
    ]:
        assert f"# {field}: <value>" in rules
    assert "Allowed manifest fields are exactly:" in rules
    assert "Unknown manifest fields are invalid." in rules
    assert "Valid risk values are exactly: high, low, medium" in rules
    assert "<<<<<<< MATCH" in rules
    assert "=======" in rules
    assert ">>>>>>> REPLACE" in rules


def test_pdcp_rules_include_valid_minimal_example_for_current_target() -> None:
    rules = pdcp_rules_text(
        target_file_id="target-123",
        target_type="text/plain",
        current_hash="b" * 64,
        target_context="Original sentence.",
    )

    assert "Valid minimal PDCP example for this target:" in rules
    assert "PDCP 0.2.3" in rules
    assert "target_file_id: target-123" in rules
    assert "target_type: text/plain" in rules
    assert f"target_hash: {'b' * 64}" in rules
    assert "Original phrase." in rules
    assert "Updated phrase." in rules
    assert "<add the requested change here>" not in rules
    assert "Output raw .pdcp content only." in rules


def test_pdcp_rules_include_literal_replacement_scope_and_audit_guidance() -> None:
    rules = pdcp_rules_text(
        target_file_id="target-123",
        target_type="text/plain",
        current_hash="b" * 64,
        target_context='Change "document" to "doc".',
    )

    assert "Quoted literal replacements are case-sensitive by default" in rules
    assert "case-insensitive replacement or capitalization variants" in rules
    assert "Do not change capitalization variants unless requested" in rules
    assert "If changing capitalization variants, the manifest must say so." in rules
    assert "prefer one change block per actual occurrence" in rules
    assert "multiple occurrences in the same MATCH payload" in rules
    assert "Report the actual number of changed occurrences." in rules
    assert "Report whether capitalization variants were changed." in rules
    assert "Do not summarize manifest entry count as occurrence count." in rules
