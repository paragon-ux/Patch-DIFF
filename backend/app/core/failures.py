"""Canonical PatchDIFF failure labels."""

from __future__ import annotations

from enum import StrEnum


class FailureReason(StrEnum):
    CONTEXT_MISSING = "context_missing"
    CONTEXT_INVALID = "context_invalid"
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_ENCODING_INVALID = "target_encoding_invalid"
    MANIFEST_MISSING = "manifest_missing"
    MANIFEST_INVALID = "manifest_invalid"
    BLOCK_MALFORMED = "block_malformed"
    MATCH_ABSENT = "match_absent"
    MATCH_AMBIGUOUS = "match_ambiguous"
    DISAMBIGUATION_INVALID = "disambiguation_invalid"
    TARGET_HASH_MISMATCH = "target_hash_mismatch"
    TARGET_VERSION_MISMATCH = "target_version_mismatch"
    TARGET_DIVERGED = "target_diverged"
    EXECUTABLE_LOGIC_DETECTED = "executable_logic_detected"
    SEQUENTIAL_MATCH_INVALID = "sequential_match_invalid"
    TRANSACTION_INTERNAL_ERROR = "transaction_internal_error"
    REPLAY_HASH_MISMATCH = "replay_hash_mismatch"
    REPLAY_PROTOCOL_INVALID = "replay_protocol_invalid"
    REPLAY_TRANSACTION_INVALID = "replay_transaction_invalid"


PDCP_REJECTION_REASONS: frozenset[FailureReason] = frozenset(
    {
        FailureReason.CONTEXT_MISSING,
        FailureReason.CONTEXT_INVALID,
        FailureReason.TARGET_NOT_FOUND,
        FailureReason.TARGET_ENCODING_INVALID,
        FailureReason.MANIFEST_MISSING,
        FailureReason.MANIFEST_INVALID,
        FailureReason.BLOCK_MALFORMED,
        FailureReason.MATCH_ABSENT,
        FailureReason.MATCH_AMBIGUOUS,
        FailureReason.DISAMBIGUATION_INVALID,
        FailureReason.TARGET_HASH_MISMATCH,
        FailureReason.TARGET_VERSION_MISMATCH,
        FailureReason.TARGET_DIVERGED,
        FailureReason.EXECUTABLE_LOGIC_DETECTED,
        FailureReason.SEQUENTIAL_MATCH_INVALID,
        FailureReason.TRANSACTION_INTERNAL_ERROR,
    }
)

REPLAY_FAILURE_REASONS: frozenset[FailureReason] = frozenset(
    {
        FailureReason.REPLAY_HASH_MISMATCH,
        FailureReason.REPLAY_PROTOCOL_INVALID,
        FailureReason.REPLAY_TRANSACTION_INVALID,
    }
)
