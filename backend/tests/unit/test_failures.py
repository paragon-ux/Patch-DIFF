from app.core.failures import (
    PDCP_REJECTION_REASONS,
    REPLAY_FAILURE_REASONS,
    FailureReason,
)


def test_all_pdcp_rejection_labels_are_present() -> None:
    assert {reason.value for reason in PDCP_REJECTION_REASONS} == {
        "context_missing",
        "context_invalid",
        "target_not_found",
        "target_encoding_invalid",
        "manifest_missing",
        "manifest_invalid",
        "block_malformed",
        "match_absent",
        "match_ambiguous",
        "disambiguation_invalid",
        "target_hash_mismatch",
        "target_version_mismatch",
        "target_diverged",
        "executable_logic_detected",
        "sequential_match_invalid",
        "transaction_internal_error",
    }


def test_replay_only_labels_are_separate() -> None:
    assert {reason.value for reason in REPLAY_FAILURE_REASONS} == {
        "replay_hash_mismatch",
        "replay_protocol_invalid",
        "replay_transaction_invalid",
    }
    assert PDCP_REJECTION_REASONS.isdisjoint(REPLAY_FAILURE_REASONS)


def test_failure_enum_does_not_include_extra_labels() -> None:
    assert set(FailureReason) == PDCP_REJECTION_REASONS | REPLAY_FAILURE_REASONS
