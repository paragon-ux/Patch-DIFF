"""Deterministic in-memory PDCP transaction application."""

from __future__ import annotations

from app.core.canonicalization import canonicalize_text
from app.core.failures import FailureReason
from app.core.diagnostics import exact_candidates, near_miss_query
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, FailureBufferContext, RejectedCoreResult
from app.pdcp.disambiguation import MatchResolutionError, resolve_match_span
from app.pdcp.matcher import MatchSpan, find_exact_occurrences
from app.pdcp.models import ParsedPDCP


def apply_pdcp_transaction(
    target_text: str,
    parsed: ParsedPDCP,
    *,
    overlapping_matches: bool = True,
    enforce_singleton_selectors: bool = True,
    allow_span_operations: bool = False,
) -> AcceptedCoreResult | RejectedCoreResult:
    """Apply a parsed+validated transaction to an in-memory buffer.

    ``overlapping_matches=False`` selects the legacy MATCH enumeration of runtime
    ``patchdiff-mvp-0.1.0``. Disabling singleton selector enforcement retains
    the ignored-selector behavior of recorded profiles through 0.2.1.
    """

    original = canonicalize_text(target_text)
    current = original
    before_hash = canonical_sha256(original)

    if parsed.header.target_hash is not None and parsed.header.target_hash != before_hash:
        return _rejected(
            FailureReason.TARGET_HASH_MISMATCH,
            "PDCP target_hash does not match the current target hash.",
            before_hash,
            buffer=current,
        )

    change_facts: list[dict] = []
    for change in parsed.changes:
        change_id = change.manifest.change_id
        if change.operation != "match":
            if change.operation != "span" or not allow_span_operations:
                return _rejected(FailureReason.BLOCK_MALFORMED, "Operation is unsupported by this runtime profile.",
                                 before_hash, change_id, buffer=current, prior_changes=len(change_facts))
            start, end = change.span_start, change.span_end
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end)) or not 0 <= start <= end <= len(current):
                return _rejected(FailureReason.SPAN_OUT_OF_BOUNDS, "Span is outside the sequential buffer.",
                                 before_hash, change_id, buffer=current, prior_changes=len(change_facts))
            if current[start:end] != canonicalize_text(change.match_payload):
                return _rejected(FailureReason.SPAN_EXPECTED_TEXT_MISMATCH, "Span expected_text does not match the sequential buffer.",
                                 before_hash, change_id, buffer=current, prior_changes=len(change_facts))
            span = MatchSpan(start, end)
        else:
            if change.match_payload == "":
                return _rejected(
                    FailureReason.BLOCK_MALFORMED,
                    "MATCH payload must not be empty.",
                    before_hash,
                    change_id,
                    buffer=current,
                    prior_changes=len(change_facts),
                )

            manifest_target_hash = change.manifest.fields.get("target_hash")
            if manifest_target_hash is not None and manifest_target_hash != canonical_sha256(current):
                return _rejected(
                    FailureReason.TARGET_HASH_MISMATCH,
                    "Manifest target_hash does not match the current target hash.",
                    before_hash,
                    change_id,
                    buffer=current,
                    prior_changes=len(change_facts),
                )

            try:
                span = resolve_match_span(
                    current,
                    change.match_payload,
                    change.manifest.disambiguation,
                    overlapping=overlapping_matches,
                    enforce_singleton_selectors=enforce_singleton_selectors,
                )
            except MatchResolutionError as exc:
                reason = exc.failure_reason
                if (
                    reason is FailureReason.MATCH_ABSENT
                    and change.change_index > 1
                    and find_exact_occurrences(original, change.match_payload, overlapping=overlapping_matches)
                ):
                    reason = FailureReason.SEQUENTIAL_MATCH_INVALID
                extra: dict = {}
                if reason in {FailureReason.MATCH_AMBIGUOUS, FailureReason.DISAMBIGUATION_INVALID}:
                    occurrences = find_exact_occurrences(current, change.match_payload, overlapping=overlapping_matches)
                    extra["occurrence_count"] = len(occurrences)
                    extra["exact_candidates"] = exact_candidates(current, occurrences)
                if reason in {FailureReason.MATCH_ABSENT, FailureReason.SEQUENTIAL_MATCH_INVALID}:
                    extra["near_miss_query"] = near_miss_query(change.match_payload)
                return _rejected(
                    reason, exc.failure_detail, before_hash, change_id, extra,
                    buffer=current, prior_changes=len(change_facts),
                )

        replacement = canonicalize_text(change.replace_payload)
        matched = current[span.start : span.end]
        current = current[: span.start] + replacement + current[span.end :]
        change_facts.append(
            {
                "change_id": change_id,
                "change_index": change.change_index,
                "span_start": span.start,
                "span_end": span.end,
                "matched_chars": len(matched),
                "replacement_chars": len(replacement),
                "matched_sha256": canonical_sha256(matched),
                "replacement_sha256": canonical_sha256(replacement),
            }
        )
        if change.operation == "span":
            change_facts[-1]["operation"] = "span"

    return AcceptedCoreResult(
        before_hash=before_hash,
        after_hash=canonical_sha256(current),
        target_content=current,
        change_count=len(parsed.changes),
        manifest_entries=tuple(change.manifest for change in parsed.changes),
        change_facts=tuple(change_facts),
    )


def _rejected(
    reason: FailureReason,
    detail: str,
    before_hash: str,
    failed_change_id: str | None = None,
    extra_diagnostic: dict | None = None,
    *,
    buffer: str,
    prior_changes: int = 0,
) -> RejectedCoreResult:
    diagnostic = {
        "retryable": reason
        in {
            FailureReason.MATCH_ABSENT,
            FailureReason.MATCH_AMBIGUOUS,
            FailureReason.DISAMBIGUATION_INVALID,
            FailureReason.SEQUENTIAL_MATCH_INVALID,
            FailureReason.TARGET_HASH_MISMATCH,
        },
        "requires_new_submission": True,
        "requires_new_pdcp": True,
    }
    if extra_diagnostic:
        diagnostic.update(extra_diagnostic)
    return RejectedCoreResult(
        failure_reason=reason,
        failure_detail=detail,
        before_hash=before_hash,
        failed_change_id=failed_change_id,
        diagnostic=diagnostic,
        failure_buffer=FailureBufferContext.capture(buffer, prior_changes),
    )
