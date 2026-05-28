from app.services.prompt_context_service import pdcp_rules_text
from app.services.regeneration_service import build_regeneration_prompt


def test_regeneration_prompt_includes_complete_pdcp_generation_contract() -> None:
    rules = pdcp_rules_text(
        target_file_id="target-regen",
        target_type="text/plain",
        current_hash="c" * 64,
        target_context="Old text.",
    )
    prompt = build_regeneration_prompt(
        {
            "status": "ready",
            "target_file_id": "target-regen",
            "pdcp_log_id": "log-123",
            "failure_reason": "manifest_invalid",
            "failure_detail": "Unsupported manifest field: summary.",
            "failed_change_id": None,
            "current_version": 0,
            "current_hash": "c" * 64,
            "fresh_target_context": "Old text.",
            "pdcp_rules": rules,
            "user_request": "Fix the manifest.",
        }
    )

    text = prompt["prompt"]
    for field in [
        "change_id",
        "intent",
        "input_state",
        "output_state",
        "affected_region",
        "user_visible_change",
        "risk",
    ]:
        assert f"# {field}: <value>" in text
    assert "<<<<<<< MATCH" in text
    assert "=======" in text
    assert ">>>>>>> REPLACE" in text
    assert "Unknown manifest fields are invalid." in text
    assert "target_file_id: target-regen" in text
    assert f"target_hash: {'c' * 64}" in text
    assert "Quoted literal replacements are case-sensitive by default" in text
    assert "Do not summarize manifest entry count as occurrence count." in text
    assert "Original phrase." in text
    assert "Updated phrase." in text
    assert "<add the requested change here>" not in text
