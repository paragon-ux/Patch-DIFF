from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.parser import parse_pdcp
from app.pdcp.protocol_validator import validate_pdcp


def make_pdcp(
    *changes: tuple[str, str, dict[str, str] | None],
    header_hash: str | None = None,
) -> str:
    header = "PDCP 0.2.3\ntarget_file_id: target_123\ntarget_type: text/plain"
    if header_hash is not None:
        header += f"\ntarget_hash: {header_hash}"

    sections = [header]
    for index, (match, replace, extra_fields) in enumerate(changes, start=1):
        fields = {
            "change_id": f"chg_{index:03d}",
            "intent": "Update text.",
            "input_state": "Old text exists.",
            "output_state": "New text exists.",
            "affected_region": "example",
            "user_visible_change": "Text changes.",
            "risk": "low",
        }
        fields.update(extra_fields or {})
        manifest = "\n".join(f"# {key}: {value}" for key, value in fields.items())
        sections.append(
            f"""# MANIFEST
{manifest}

<<<<<<< MATCH
{match}
=======
{replace}
>>>>>>> REPLACE"""
        )
    return "\n\n".join(sections)


def parsed_pdcp(*changes: tuple[str, str, dict[str, str] | None], header_hash: str | None = None):
    parsed = parse_pdcp(make_pdcp(*changes, header_hash=header_hash))
    validate_pdcp(parsed)
    return parsed


def test_single_replacement_accepted() -> None:
    result = apply_pdcp_transaction("hello old world", parsed_pdcp(("old", "new", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "hello new world"


def test_deletion_accepted() -> None:
    result = apply_pdcp_transaction("hello old world", parsed_pdcp(("old ", "", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "hello world"


def test_whitespace_only_replacement_accepted() -> None:
    result = apply_pdcp_transaction("hello old world", parsed_pdcp(("old", "   ", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "hello     world"


def test_anchored_insertion_accepted() -> None:
    result = apply_pdcp_transaction("## Summary\nBody", parsed_pdcp(("## Summary", "## Summary\n\nInserted.", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "## Summary\n\nInserted.\nBody"


def test_zero_length_match_rejects() -> None:
    from app.pdcp.models import PDCPChange, PDCPHeader, PDCPManifest, ParsedPDCP

    parsed = ParsedPDCP(
        header=PDCPHeader("0.2.3", "target_123", "text/plain"),
        changes=(
            PDCPChange(
                change_index=1,
                manifest=PDCPManifest.from_fields(
                    {
                        "change_id": "chg_001",
                        "intent": "Invalid insert.",
                        "input_state": "No match.",
                        "output_state": "Inserted text.",
                        "affected_region": "example",
                        "user_visible_change": "Insertion.",
                        "risk": "low",
                    }
                ),
                match_payload="",
                replace_payload="inserted",
            ),
        ),
        structural_lines=("PDCP 0.2.3",),
    )
    result = apply_pdcp_transaction("target", parsed)
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.BLOCK_MALFORMED


def test_multi_change_sequential_success() -> None:
    result = apply_pdcp_transaction(
        "a b c",
        parsed_pdcp(("a", "A", None), ("b", "B", None), ("c", "C", None)),
    )
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "A B C"


def test_second_change_sees_first_replacement() -> None:
    result = apply_pdcp_transaction(
        "alpha beta",
        parsed_pdcp(("alpha", "gamma", None), ("gamma beta", "done", None)),
    )
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "done"


def test_second_change_against_original_state_returns_sequential_match_invalid() -> None:
    result = apply_pdcp_transaction(
        "alpha beta",
        parsed_pdcp(("alpha", "gamma", None), ("alpha beta", "done", None)),
    )
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.SEQUENTIAL_MATCH_INVALID
    assert result.after_hash is None


def test_overlapping_valid_sequential_edits_accepted() -> None:
    result = apply_pdcp_transaction(
        "abc",
        parsed_pdcp(("ab", "xy", None), ("xyc", "done", None)),
    )
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "done"


def test_overlapping_invalid_sequential_edits_reject_atomically() -> None:
    result = apply_pdcp_transaction(
        "abc",
        parsed_pdcp(("ab", "xy", None), ("abc", "done", None)),
    )
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.SEQUENTIAL_MATCH_INVALID
    assert not hasattr(result, "target_content")


def test_before_hash_and_after_hash_are_correct() -> None:
    result = apply_pdcp_transaction("old", parsed_pdcp(("old", "new", None)))
    assert isinstance(result, AcceptedCoreResult)
    assert result.before_hash == canonical_sha256("old")
    assert result.after_hash == canonical_sha256("new")


def test_header_target_hash_mismatch_rejects() -> None:
    result = apply_pdcp_transaction("old", parsed_pdcp(("old", "new", None), header_hash="a" * 64))
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.TARGET_HASH_MISMATCH


def test_manifest_target_hash_mismatch_rejects_before_match() -> None:
    result = apply_pdcp_transaction("old", parsed_pdcp(("old", "new", {"target_hash": "b" * 64})))
    assert isinstance(result, RejectedCoreResult)
    assert result.failure_reason is FailureReason.TARGET_HASH_MISMATCH


def test_no_mutation_outside_selected_span() -> None:
    result = apply_pdcp_transaction("left old right old", parsed_pdcp(("old", "new", {"occurrence_index": "2"})))
    assert isinstance(result, AcceptedCoreResult)
    assert result.target_content == "left old right new"
