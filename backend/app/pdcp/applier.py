"""Deterministic in-memory PDCP transaction application."""

from __future__ import annotations

from app.core.canonicalization import canonicalize_text
from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.pdcp.disambiguation import MatchResolutionError, resolve_match_span
from app.pdcp.matcher import find_exact_occurrences
from app.pdcp.models import ParsedPDCP


def apply_pdcp_transaction(
    target_text: str,
    parsed: ParsedPDCP,
) -> AcceptedCoreResult | RejectedCoreResult:
    """Apply a parsed+validated PDCP transaction to an in-memory buffer."""

    original = canonicalize_text(target_text)
    current = original
    before_hash = canonical_sha256(original)

    if parsed.header.target_hash is not None and parsed.header.target_hash != before_hash:
        return _rejected(
            FailureReason.TARGET_HASH_MISMATCH,
            "PDCP target_hash does not match the current target hash.",
            before_hash,
        )

    for change in parsed.changes:
        change_id = change.manifest.change_id
        if change.match_payload == "":
            return _rejected(
                FailureReason.BLOCK_MALFORMED,
                "MATCH payload must not be empty.",
                before_hash,
                change_id,
            )

        manifest_target_hash = change.manifest.fields.get("target_hash")
        if manifest_target_hash is not None and manifest_target_hash != canonical_sha256(current):
            return _rejected(
                FailureReason.TARGET_HASH_MISMATCH,
                "Manifest target_hash does not match the current target hash.",
                before_hash,
                change_id,
            )

        try:
            span = resolve_match_span(current, change.match_payload, change.manifest.disambiguation)
        except MatchResolutionError as exc:
            reason = exc.failure_reason
            if (
                reason is FailureReason.MATCH_ABSENT
                and change.change_index > 1
                and find_exact_occurrences(original, change.match_payload)
            ):
                reason = FailureReason.SEQUENTIAL_MATCH_INVALID
            return _rejected(reason, exc.failure_detail, before_hash, change_id)

        replacement = canonicalize_text(change.replace_payload)
        current = current[: span.start] + replacement + current[span.end :]

    return AcceptedCoreResult(
        before_hash=before_hash,
        after_hash=canonical_sha256(current),
        target_content=current,
        change_count=len(parsed.changes),
        manifest_entries=tuple(change.manifest for change in parsed.changes),
    )


def _rejected(
    reason: FailureReason,
    detail: str,
    before_hash: str,
    failed_change_id: str | None = None,
) -> RejectedCoreResult:
    return RejectedCoreResult(
        failure_reason=reason,
        failure_detail=detail,
        before_hash=before_hash,
        failed_change_id=failed_change_id,
        diagnostic={
            "retryable": reason
            in {
                FailureReason.MATCH_ABSENT,
                FailureReason.MATCH_AMBIGUOUS,
                FailureReason.DISAMBIGUATION_INVALID,
                FailureReason.SEQUENTIAL_MATCH_INVALID,
                FailureReason.TARGET_HASH_MISMATCH,
            },
            "requires_new_pdcp": True,
        },
    )
