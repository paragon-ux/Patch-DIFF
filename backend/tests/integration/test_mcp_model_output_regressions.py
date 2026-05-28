import pytest

from app.mcp import tools  # noqa: F401
from app.mcp.server import registry
from backend.tests.integration.helpers import pdcp_for


def _submit_corrupted_pdcp(content: str) -> tuple[dict, dict, dict]:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="malformed.txt",
        content="Original sentence.",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]
    before = registry.call("patchdiff_get_target", target_file_id=target_id)
    rejected = registry.call("patchdiff_submit_pdcp", target_file_id=target_id, pdcp_content=content)
    after = registry.call("patchdiff_get_target", target_file_id=target_id)
    return before, rejected, after


@pytest.mark.parametrize(
    ("name", "mutate", "expected_reason"),
    [
        (
            "corrupted_separator",
            lambda pdcp: pdcp.replace("=======", "================================================="),
            "block_malformed",
        ),
        (
            "corrupted_replace_terminator",
            lambda pdcp: pdcp.replace(">>>>>>> REPLACE", "> > > > > > > REPLACE"),
            "block_malformed",
        ),
        (
            "extra_prose_before",
            lambda pdcp: "Here is the patch:\n" + pdcp,
            "context_invalid",
        ),
        (
            "extra_prose_after",
            lambda pdcp: pdcp + "\nThis should help.",
            "manifest_missing",
        ),
        (
            "blockquote_rendered_delimiters",
            lambda pdcp: pdcp.replace("<<<<<<< MATCH", "> <<<<<<< MATCH")
            .replace("=======", "> =======")
            .replace(">>>>>>> REPLACE", "> >>>>>>> REPLACE"),
            "manifest_invalid",
        ),
        (
            "full_rewritten_document",
            lambda pdcp: "Original sentence.\n\nNew rewritten document.",
            "context_invalid",
        ),
        (
            "executable_apply_function",
            lambda pdcp: pdcp.replace("# MANIFEST", "def applyPDCP():\n    pass\n\n# MANIFEST"),
            "executable_logic_detected",
        ),
        (
            "missing_manifest_field",
            lambda pdcp: pdcp.replace("# risk: low\n", ""),
            "manifest_invalid",
        ),
    ],
)
def test_mcp_rejects_renderer_or_model_corrupted_pdcp_outputs(name, mutate, expected_reason) -> None:
    valid = pdcp_for("00000000-0000-0000-0000-000000000000", ("Original sentence.", "Updated sentence."))
    corrupted = mutate(valid)

    before, rejected, after = _submit_corrupted_pdcp(corrupted)

    assert rejected["status"] == "rejected", name
    assert rejected["failure_reason"] == expected_reason
    assert rejected["after_hash"] is None
    assert rejected["pdcp_log_id"]
    assert after["current_content"] == before["current_content"]
    assert after["current_hash"] == before["current_hash"]
    assert after["version"] == before["version"]

    regen_context = registry.call(
        "patchdiff_get_regeneration_context",
        pdcp_log_id=rejected["pdcp_log_id"],
        user_request="Regenerate from clean target context.",
    )
    assert regen_context["status"] == "ready"
    assert regen_context["failure_reason"] == expected_reason
    assert regen_context["rejected_pdcp_content"] == corrupted


def test_mcp_accepts_raw_code_block_contents_without_markdown_fences() -> None:
    upload = registry.call(
        "patchdiff_handle_upload",
        filename="raw-code-block.txt",
        content="Original sentence.",
        content_type="text/plain",
    )
    target_id = upload["target_file_id"]
    raw_code_block_contents = pdcp_for(target_id, ("Original sentence.", "Updated sentence."))

    accepted = registry.call(
        "patchdiff_submit_pdcp",
        target_file_id=target_id,
        pdcp_content=raw_code_block_contents,
        expected_target_version=0,
    )

    assert accepted["status"] == "accepted"
    assert accepted["version"] == 1
    target = registry.call("patchdiff_get_target", target_file_id=target_id)
    assert target["current_content"] == "Updated sentence."
