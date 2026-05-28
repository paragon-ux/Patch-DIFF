from app.mcp import tools  # noqa: F401
from app.mcp.server import registry
from backend.tests.integration.helpers import pdcp_for


REQUIRED_MANIFEST_FIELDS = [
    "change_id",
    "intent",
    "input_state",
    "output_state",
    "affected_region",
    "user_visible_change",
    "risk",
]


def test_mcp_prompt_context_exposes_full_model_facing_pdcp_contract() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="prompt-contract.txt",
        content="Original sentence.",
        content_type="text/plain",
    )

    context = registry.call(
        "patchdiff_build_prompt_context",
        target_file_id=upload["target_file_id"],
        user_request="Update the sentence.",
    )
    rules = context["pdcp_rules"]

    assert f"target_file_id: {upload['target_file_id']}" in rules
    assert "target_type: text/plain" in rules
    assert f"target_hash: {upload['current_hash']}" in rules
    for field in REQUIRED_MANIFEST_FIELDS:
        assert f"# {field}: <value>" in rules
    assert "Allowed manifest fields are exactly:" in rules
    assert "Unknown manifest fields are invalid." in rules
    assert "Valid risk values are exactly: high, low, medium" in rules
    assert "<<<<<<< MATCH" in rules
    assert "=======" in rules
    assert ">>>>>>> REPLACE" in rules
    assert "Each change block must have exactly one # MANIFEST block" in rules
    assert "MATCH payload must be non-empty." in rules
    assert "Empty REPLACE means deletion." in rules
    assert "case-sensitive, whitespace-sensitive" in rules
    assert "Output raw .pdcp content only." in rules
    assert "Valid minimal PDCP example for this target:" in rules
    assert "Original phrase." in rules
    assert "Updated phrase." in rules
    assert "<add the requested change here>" not in rules


def test_manifest_invalid_diagnostic_and_regeneration_prompt_include_allowed_fields() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="unsupported-manifest-field.txt",
        content="Original sentence.",
        content_type="text/plain",
    )
    pdcp = pdcp_for(upload["target_file_id"], ("Original sentence.", "Updated sentence.")).replace(
        "# intent: Update text.\n",
        "# intent: Update text.\n# summary: Claude guessed this unsupported field.\n",
    )

    rejected = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=upload["target_file_id"],
        pdcp_content=pdcp,
    )
    assert rejected["status"] == "rejected"
    assert rejected["failure_reason"] == "manifest_invalid"
    assert "allowed_manifest_fields" in rejected["diagnostic"]
    for field in REQUIRED_MANIFEST_FIELDS:
        assert field in rejected["diagnostic"]["allowed_manifest_fields"]
    assert "summary" not in rejected["diagnostic"]["allowed_manifest_fields"]

    context = registry.call(
        "patchdiff_get_regeneration_context",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Regenerate without guessed manifest fields.",
    )
    assert context["diagnostic"]["allowed_manifest_fields"] == rejected["diagnostic"]["allowed_manifest_fields"]
    assert "Unknown manifest fields are invalid." in context["pdcp_rules"]
    assert "<<<<<<< MATCH" in context["pdcp_rules"]

    prompt = registry.call(
        "patchdiff_build_regeneration_prompt",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Regenerate without guessed manifest fields.",
    )
    assert "allowed manifest fields" in prompt["prompt"].lower()
    for field in REQUIRED_MANIFEST_FIELDS:
        assert f"# {field}: <value>" in prompt["prompt"]
    assert ">>>>>>> REPLACE" in prompt["prompt"]


def test_mcp_prompt_context_includes_literal_replacement_audit_policy() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="literal-policy.txt",
        content="Document document document.",
        content_type="text/plain",
    )
    context = registry.call(
        "patchdiff_build_prompt_context",
        target_file_id=upload["target_file_id"],
        user_request='Change every occurrence of "document" to "doc".',
    )

    contract = context["pdcp_rules"]
    assert "Quoted literal replacements are case-sensitive by default" in contract
    assert "case-insensitive replacement or capitalization variants" in contract
    assert "Do not change capitalization variants unless requested" in contract
    assert "If changing capitalization variants, the manifest must say so." in contract
    assert "prefer one change block per actual occurrence" in contract
    assert "multiple occurrences in the same MATCH payload" in contract
    assert "Report the actual number of changed occurrences." in contract
    assert "Report whether capitalization variants were changed." in contract
    assert "Do not summarize manifest entry count as occurrence count." in contract


def test_claude_style_manifest_guessing_is_preventable_by_returned_contract() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="claude-sequence.txt",
        content="Alpha line.",
        content_type="text/plain",
    )
    context = registry.call(
        "patchdiff_build_prompt_context",
        target_file_id=upload["target_file_id"],
        user_request="Change Alpha to Beta.",
    )

    contract = context["pdcp_rules"]
    assert "Allowed manifest fields are exactly:" in contract
    assert "Unknown manifest fields are invalid." in contract
    assert "Valid risk values are exactly:" in contract
    assert "Each change block must have exactly one # MANIFEST block" in contract
    assert "Output raw .pdcp content only." in contract
    assert "no Markdown fences, blockquotes, or surrounding prose" in contract


def test_existing_malformed_pdcp_still_rejects_and_existing_valid_pdcp_still_accepts() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="valid-and-malformed.txt",
        content="Original sentence.",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]
    valid = pdcp_for(target_id, ("Original sentence.", "Updated sentence."))
    malformed = valid.replace("=======", "=================================================")

    rejected = registry.call("patchdiff_submit_pdcp", target_file_id=target_id, pdcp_content=malformed)
    assert rejected["status"] == "rejected"
    assert rejected["failure_reason"] == "block_malformed"
    assert rejected["after_hash"] is None
    target_after_rejection = registry.call("patchdiff_get_target", target_file_id=target_id)
    assert target_after_rejection["current_content"] == "Original sentence."

    accepted = registry.call("patchdiff_submit_pdcp", target_file_id=target_id, pdcp_content=valid)
    assert accepted["status"] == "accepted"
    target_after_acceptance = registry.call("patchdiff_get_target", target_file_id=target_id)
    assert target_after_acceptance["current_content"] == "Updated sentence."
