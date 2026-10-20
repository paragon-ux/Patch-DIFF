"""Validity levels, versions, read helpers, and a pure host-loop simulation (C1-C6)."""

from __future__ import annotations

import pytest

from app.core.failures import FailureReason
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.core.validity import NOT_EVALUATED, ValidationStage, validity_levels
from app.core.versions import (
    LEGACY_RUNTIME_VERSION,
    RUNTIME_VERSION,
    UnsupportedRuntimeVersionError,
    resolve_overlapping_matches,
    uses_overlapping_matches,
)
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.typed import build_record, parse_typed_record, to_parsed_transaction
from app.services.read_service import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    clamp_limit,
    occurrence_report,
    slice_content,
)


# --- validity (C2) ----------------------------------------------------------------


def test_accepted_reports_protocol_and_transaction_valid_but_never_task_or_semantic() -> None:
    levels = validity_levels("accepted", None)
    assert levels == {
        "protocol_valid": True,
        "transaction_valid": True,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }


@pytest.mark.parametrize(
    ("reason", "protocol", "transaction"),
    [
        (FailureReason.MANIFEST_INVALID, False, None),
        (FailureReason.BLOCK_MALFORMED, False, None),
        (FailureReason.CONTEXT_MISSING, False, None),
        (FailureReason.EXECUTABLE_LOGIC_DETECTED, False, None),
        (FailureReason.MATCH_ABSENT, True, False),
        (FailureReason.MATCH_AMBIGUOUS, True, False),
        (FailureReason.SEQUENTIAL_MATCH_INVALID, True, False),
        (FailureReason.TARGET_HASH_MISMATCH, True, False),
        (FailureReason.TARGET_VERSION_MISMATCH, None, None),
        (FailureReason.TARGET_DIVERGED, True, True),
        (FailureReason.TARGET_NOT_FOUND, None, None),
    ],
)
def test_rejections_report_only_the_stages_actually_evaluated(reason, protocol, transaction) -> None:
    levels = validity_levels("rejected", reason.value)
    assert levels["protocol_valid"] is protocol
    assert levels["transaction_valid"] is transaction
    assert levels["task_correct"] == NOT_EVALUATED
    assert levels["semantic"] == NOT_EVALUATED


def test_stage_aware_validity_distinguishes_precondition_vs_applicability_and_commit_guard() -> None:
    # Pre-parse expected_current_hash mismatch -> PRECONDITION_GUARD (protocol & transaction not evaluated)
    pre_hash = validity_levels(
        "rejected",
        FailureReason.TARGET_HASH_MISMATCH,
        stage=ValidationStage.PRECONDITION_GUARD,
    )
    assert pre_hash == {
        "protocol_valid": None,
        "transaction_valid": None,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }

    # PDCP header target_hash mismatch after parsing/protocol validation -> TRANSACTION_APPLICABILITY
    in_core_hash = validity_levels(
        "rejected",
        FailureReason.TARGET_HASH_MISMATCH,
        stage=ValidationStage.TRANSACTION_APPLICABILITY,
    )
    assert in_core_hash == {
        "protocol_valid": True,
        "transaction_valid": False,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }

    # Post-simulation commit guard failure -> COMMIT_GUARD (protocol & transaction succeeded)
    commit_guard = validity_levels(
        "rejected",
        FailureReason.TARGET_DIVERGED,
        stage=ValidationStage.COMMIT_GUARD,
    )
    assert commit_guard == {
        "protocol_valid": True,
        "transaction_valid": True,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }


# --- versions (C3) ----------------------------------------------------------------


def test_explicit_runtime_profile_dispatch_and_unknown_version_rejection() -> None:
    assert resolve_overlapping_matches(RUNTIME_VERSION) is True
    assert resolve_overlapping_matches(LEGACY_RUNTIME_VERSION) is False
    assert uses_overlapping_matches(RUNTIME_VERSION) is True
    assert uses_overlapping_matches(LEGACY_RUNTIME_VERSION) is False
    assert RUNTIME_VERSION != LEGACY_RUNTIME_VERSION

    with pytest.raises(UnsupportedRuntimeVersionError):
        resolve_overlapping_matches("some-future-version")
    with pytest.raises(UnsupportedRuntimeVersionError):
        uses_overlapping_matches(None)


# --- read helpers (C6) ------------------------------------------------------------


def test_slice_content_is_bounded_and_reports_truncation_and_next_start() -> None:
    page = slice_content("abcdefghij", start=2, length=3)
    assert (page["start"], page["end"], page["text"], page["truncated"], page["total_chars"], page["next_start"]) == (
        2,
        5,
        "cde",
        True,
        10,
        5,
    )
    tail = slice_content("abcdefghij", start=8, length=100)
    assert tail["text"] == "ij" and tail["truncated"] is False and tail["next_start"] is None


def test_slice_content_clamps_hostile_arguments() -> None:
    assert slice_content("abc", start=-5, length=-1)["text"] == ""
    assert slice_content("abc", start=99)["text"] == ""
    assert slice_content("a" * 50, start=0, length=None, max_length=10)["truncated"] is True


def test_slice_content_uses_canonical_line_endings() -> None:
    assert slice_content("a\r\nb")["text"] == "a\nb"


def test_occurrence_report_numbers_match_the_disambiguator_including_overlaps() -> None:
    report = occurrence_report("aaa", "aa", context_chars=1)
    assert report["occurrence_count"] == 2
    assert report["returned_count"] == 2
    assert report["next_occurrence_index"] is None
    assert [(o["occurrence_index"], o["start"], o["end"]) for o in report["occurrences"]] == [(1, 0, 2), (2, 1, 3)]
    assert report["occurrences"][0]["after"] == "a"


def test_occurrence_report_is_bounded_and_paginates_via_start_occurrence() -> None:
    report = occurrence_report("x" * 10, "x", start_occurrence=1, max_results=4)
    assert report["occurrence_count"] == 10
    assert report["returned_count"] == 4
    assert report["truncated"] is True
    assert report["next_occurrence_index"] == 5
    assert [o["occurrence_index"] for o in report["occurrences"]] == [1, 2, 3, 4]

    page2 = occurrence_report("x" * 10, "x", start_occurrence=report["next_occurrence_index"], max_results=4)
    assert [o["occurrence_index"] for o in page2["occurrences"]] == [5, 6, 7, 8]
    assert page2["next_occurrence_index"] == 9

    page3 = occurrence_report("x" * 10, "x", start_occurrence=page2["next_occurrence_index"], max_results=4)
    assert [o["occurrence_index"] for o in page3["occurrences"]] == [9, 10]
    assert page3["truncated"] is False
    assert page3["next_occurrence_index"] is None


def test_clamp_limit() -> None:
    assert clamp_limit(None) == DEFAULT_HISTORY_LIMIT
    assert clamp_limit(0) == 1
    assert clamp_limit(10_000) == MAX_HISTORY_LIMIT
    assert clamp_limit(7) == 7


# --- Host-loop acceptance scenario, pure-core simulation --------------------------


def _submit(content: str, version: int, edits):
    """Stand-in for the service commit path: decode -> apply -> (content, version) or rejection."""

    record = build_record(
        target_file_id="t1",
        intent="Replace the label.",
        edits=edits,
        expected_target_version=version,
        expected_current_hash=None,
    )
    typed = parse_typed_record(record)
    return apply_pdcp_transaction(content, to_parsed_transaction(typed, target_type="text/plain"))


def test_host_loop_reject_inspect_revise_succeeds_without_regeneration_tools() -> None:
    """Host submits an ambiguous edit -> receives MATCH_AMBIGUOUS with occurrence count ->
    calls occurrence_report (the core of patchdiff_find_occurrences) -> resubmits with
    occurrence_index -> accepted. No server-side regeneration prompt or context tool involved.
    """

    target = "label: draft\nbody: keep\nlabel: draft\n"

    # Attempt 1: bare match is ambiguous.
    first = _submit(target, 0, [{"match": "label: draft", "replace": "label: final"}])
    assert isinstance(first, RejectedCoreResult)
    assert first.failure_reason is FailureReason.MATCH_AMBIGUOUS
    assert first.diagnostic["occurrence_count"] == 2
    assert first.diagnostic["requires_new_submission"] is True

    # Host inspects occurrences directly and picks the second one.
    found = occurrence_report(target, "label: draft", context_chars=12)
    assert found["occurrence_count"] == 2
    second_occ = found["occurrences"][1]
    assert second_occ["occurrence_index"] == 2
    assert "keep\n" in second_occ["before"]

    # Attempt 2: disambiguated by occurrence_index -> accepted.
    second = _submit(
        target,
        0,
        [{"match": "label: draft", "replace": "label: final", "occurrence_index": 2}],
    )
    assert isinstance(second, AcceptedCoreResult)
    assert second.target_content == "label: draft\nbody: keep\nlabel: final\n"
    assert second.change_facts[0]["span_start"] == second_occ["start"]
