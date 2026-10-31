"""Deterministic in-memory PDCP transaction application."""

from __future__ import annotations

from app.core.advisories import splits_grapheme, warning
from app.core.canonicalization import canonicalize_text
from app.core.failures import RETRYABLE_FAILURE_REASONS, FailureReason
from app.core.diagnostics import NEAR_MISS_SCAN_CHARS, exact_candidates, near_miss_query
from app.core.hashing import canonical_sha256
from app.core.result import AcceptedCoreResult, FailureBufferContext, RejectedCoreResult
from app.pdcp.disambiguation import MatchResolutionError, resolve_match_span
from app.pdcp.matcher import MatchSpan, find_exact_occurrences
from app.pdcp.models import ParsedPDCP

ACTUAL_TEXT_CHARS = 64
MAX_ORIGINAL_OCCURRENCES = 5


def apply_pdcp_transaction(
    target_text: str,
    parsed: ParsedPDCP,
    *,
    overlapping_matches: bool = True,
    enforce_singleton_selectors: bool = True,
    allow_span_operations: bool = False,
    allow_replace_all_operations: bool = False,
    allow_span_context: bool = False,
    collect_warnings: bool = True,
    scope_bounds: tuple[int, int] | None = None,
) -> AcceptedCoreResult | RejectedCoreResult:
    """Apply a parsed+validated transaction to an in-memory buffer.

    ``overlapping_matches=False`` selects the legacy MATCH enumeration of runtime
    ``patchdiff-mvp-0.1.0``. Disabling singleton selector enforcement retains
    the ignored-selector behavior of recorded profiles through 0.2.1. Warnings are
    advisory and never change the verdict; replay disables their collection.
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
    warnings: list[dict] = []
    running_scope: list[int] | None = [scope_bounds[0], scope_bounds[1]] if scope_bounds is not None else None
    for change in parsed.changes:
        change_id = change.manifest.change_id
        prior = len(change_facts)
        if change.operation == "replace_all":
            if not allow_replace_all_operations or len(parsed.changes) != 1 or running_scope is not None:
                return _rejected(FailureReason.BLOCK_MALFORMED, "Sole replacement is unsupported by this runtime profile.",
                                 before_hash, change_id, buffer=current, prior_changes=prior)
            span = MatchSpan(0, len(current))
        elif change.operation != "match":
            if change.operation != "span" or not allow_span_operations:
                return _rejected(FailureReason.BLOCK_MALFORMED, "Operation is unsupported by this runtime profile.",
                                 before_hash, change_id, buffer=current, prior_changes=prior)
            if (change.expected_before is not None or change.expected_after is not None) and not allow_span_context:
                return _rejected(FailureReason.BLOCK_MALFORMED, "Span context is unsupported by this runtime profile.",
                                 before_hash, change_id, buffer=current, prior_changes=prior)
            start, end = change.span_start, change.span_end
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end)) or not 0 <= start <= end <= len(current):
                return _rejected(FailureReason.SPAN_OUT_OF_BOUNDS, "Span is outside the sequential buffer.",
                                 before_hash, change_id, {"span_check": "bounds", "buffer_length": len(current)},
                                 buffer=current, prior_changes=prior, focus=len(current))
            if running_scope is not None and not (
                running_scope[0] < start < running_scope[1] if start == end
                else running_scope[0] <= start < end <= running_scope[1]
            ):
                return _rejected(
                    FailureReason.SPAN_OUT_OF_BOUNDS,
                    f"Span [{start}, {end}) is outside the observed scope [{running_scope[0]}, {running_scope[1]}).",
                    before_hash,
                    change_id,
                    {
                        "code": "OPERATION_OUTSIDE_OBSERVED_SCOPE",
                        "span_check": "observed_scope_bounds",
                        "observed_scope_start": running_scope[0],
                        "observed_scope_end": running_scope[1],
                        "operation_start": start,
                        "operation_end": end,
                        "buffer_length": len(current),
                    },
                    buffer=current,
                    prior_changes=prior,
                    focus=start,
                )
            if running_scope is not None and start == end:
                before = canonicalize_text(change.expected_before or "")
                after = canonicalize_text(change.expected_after or "")
                if not before or not after:
                    return _rejected(
                        FailureReason.SPAN_EXPECTED_TEXT_MISMATCH,
                        "Observed insertions require nonempty expected_before and expected_after adjacency guards.",
                        before_hash, change_id, {"code": "OBSERVED_INSERTION_GUARDS_REQUIRED"},
                        buffer=current, prior_changes=prior, focus=start)
                if start - len(before) < running_scope[0] or end + len(after) > running_scope[1]:
                    return _rejected(
                        FailureReason.SPAN_OUT_OF_BOUNDS,
                        "Observed insertion adjacency guards must remain inside the sequential observed scope.",
                        before_hash, change_id, {"code": "OPERATION_OUTSIDE_OBSERVED_SCOPE"},
                        buffer=current, prior_changes=prior, focus=start)
            expected = canonicalize_text(change.match_payload)
            actual = current[start:end]
            if actual != expected:
                return _rejected(FailureReason.SPAN_EXPECTED_TEXT_MISMATCH, "Span expected_text does not match the sequential buffer.",
                                 before_hash, change_id, _span_evidence("expected_text", current, actual, expected),
                                 buffer=current, prior_changes=prior, focus=start)
            if change.expected_before is not None:
                context = canonicalize_text(change.expected_before)
                actual = current[max(0, start - len(context)):start]
                if actual != context:
                    return _rejected(
                        FailureReason.SPAN_EXPECTED_TEXT_MISMATCH,
                        "Span expected_before does not match the text immediately before start in the sequential buffer.",
                        before_hash, change_id, _span_evidence("expected_before", current, actual, context, tail=True),
                        buffer=current, prior_changes=prior, focus=start)
            if change.expected_after is not None:
                context = canonicalize_text(change.expected_after)
                actual = current[end:end + len(context)]
                if actual != context:
                    return _rejected(
                        FailureReason.SPAN_EXPECTED_TEXT_MISMATCH,
                        "Span expected_after does not match the text immediately after end in the sequential buffer.",
                        before_hash, change_id, _span_evidence("expected_after", current, actual, context),
                        buffer=current, prior_changes=prior, focus=end)
            span = MatchSpan(start, end)
        else:
            if change.match_payload == "":
                return _rejected(
                    FailureReason.BLOCK_MALFORMED,
                    "MATCH payload must not be empty.",
                    before_hash,
                    change_id,
                    buffer=current,
                    prior_changes=prior,
                )

            manifest_target_hash = change.manifest.fields.get("target_hash")
            if manifest_target_hash is not None and manifest_target_hash != canonical_sha256(current):
                return _rejected(
                    FailureReason.TARGET_HASH_MISMATCH,
                    "Manifest target_hash does not match the current target hash.",
                    before_hash,
                    change_id,
                    buffer=current,
                    prior_changes=prior,
                )

            if running_scope is not None:
                scope_start_cur, scope_end_cur = running_scope[0], running_scope[1]
                scope_slice = current[scope_start_cur:scope_end_cur]
                needle = canonicalize_text(change.match_payload)
                scope_occurrences = find_exact_occurrences(scope_slice, needle, overlapping=overlapping_matches)
                whole_occurrences = find_exact_occurrences(current, needle, overlapping=overlapping_matches)
                if not scope_occurrences and whole_occurrences:
                    return _rejected(
                        FailureReason.SPAN_OUT_OF_BOUNDS,
                        f"Match for {change_id} resolves outside the observed scope [{scope_start_cur}, {scope_end_cur}).",
                        before_hash,
                        change_id,
                        {
                            "code": "OPERATION_OUTSIDE_OBSERVED_SCOPE",
                            "span_check": "observed_scope_bounds",
                            "observed_scope_start": scope_start_cur,
                            "observed_scope_end": scope_end_cur,
                            "buffer_length": len(current),
                        },
                        buffer=current,
                        prior_changes=prior,
                        focus=scope_start_cur,
                    )
                try:
                    rel_span = resolve_match_span(
                        scope_slice,
                        change.match_payload,
                        change.manifest.disambiguation,
                        overlapping=overlapping_matches,
                        enforce_singleton_selectors=enforce_singleton_selectors,
                    )
                    span = MatchSpan(scope_start_cur + rel_span.start, scope_start_cur + rel_span.end)
                except MatchResolutionError as exc:
                    return _match_rejection(
                        exc, change, original, current, change_facts, before_hash, overlapping_matches,
                    )
            else:
                try:
                    span = resolve_match_span(
                        current,
                        change.match_payload,
                        change.manifest.disambiguation,
                        overlapping=overlapping_matches,
                        enforce_singleton_selectors=enforce_singleton_selectors,
                    )
                except MatchResolutionError as exc:
                    return _match_rejection(
                        exc, change, original, current, change_facts, before_hash, overlapping_matches,
                    )
            if collect_warnings and prior and "occurrence_index" in change.manifest.disambiguation:
                shifted = _basis_shift(original, change, span, change_facts, overlapping_matches)
                if shifted is not None:
                    warnings.append(shifted)

        replacement = canonicalize_text(change.replace_payload)
        matched = current[span.start : span.end]
        if collect_warnings:
            warnings.extend(_grapheme_warnings(current, span, change_id, change.change_index))
            if matched == replacement:
                warnings.append(warning("no_op_change", f"{change_id} replaces text with identical text.",
                                        change_id=change_id, change_index=change.change_index))
        current = current[: span.start] + replacement + current[span.end :]
        if running_scope is not None:
            running_scope[1] += len(replacement) - (span.end - span.start)
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
        if change.operation != "match":
            change_facts[-1]["operation"] = change.operation

    after_hash = canonical_sha256(current)
    if collect_warnings and after_hash == before_hash:
        warnings.append(warning("no_op_transaction", "The transaction leaves the target text unchanged; the version still advances."))
    return AcceptedCoreResult(
        before_hash=before_hash,
        after_hash=after_hash,
        target_content=current,
        change_count=len(parsed.changes),
        manifest_entries=tuple(change.manifest for change in parsed.changes),
        change_facts=tuple(change_facts),
        warnings=tuple(warnings),
    )


def _match_rejection(exc, change, original, current, change_facts, before_hash, overlapping_matches) -> RejectedCoreResult:
    change_id = change.manifest.change_id
    prior = len(change_facts)
    reason = exc.failure_reason
    detail = exc.failure_detail
    extra: dict = {}
    focus = None
    near_miss_buffer = None
    if reason is FailureReason.MATCH_ABSENT and change.change_index > 1:
        original_occurrences = find_exact_occurrences(original, change.match_payload, overlapping=overlapping_matches)
        if original_occurrences:
            reason = FailureReason.SEQUENTIAL_MATCH_INVALID
            consumed = _consumed_occurrences(original_occurrences[:MAX_ORIGINAL_OCCURRENCES], change_facts)
            consumer = consumed[0]["consumed_by_change_id"]
            detail = (f"MATCH text was consumed by earlier change {consumer} in this transaction."
                      if consumer is not None else "MATCH text was consumed by earlier changes in this transaction.")
            extra["original_occurrence_count"] = len(original_occurrences)
            extra["original_occurrences"] = consumed
    if reason in {FailureReason.MATCH_AMBIGUOUS, FailureReason.DISAMBIGUATION_INVALID}:
        occurrences = find_exact_occurrences(current, change.match_payload, overlapping=overlapping_matches)
        extra["occurrence_count"] = len(occurrences)
        extra["exact_candidates"] = exact_candidates(current, occurrences)
        focus = occurrences[0].start if occurrences else None
        if prior:
            detail += (f" Selectors count exact occurrences in the sequential buffer after {prior} earlier"
                       " simulated change(s), not at transaction start.")
    if reason is FailureReason.MATCH_ABSENT:
        extra["near_miss_query"] = near_miss_query(change.match_payload)
        near_miss_buffer = current[:NEAR_MISS_SCAN_CHARS]
    return _rejected(reason, detail, before_hash, change_id, extra, buffer=current, prior_changes=prior,
                     focus=focus, near_miss_buffer=near_miss_buffer)


def _span_evidence(check: str, buffer: str, actual: str, expected: str, *, tail: bool = False) -> dict:
    shown = actual[-ACTUAL_TEXT_CHARS:] if tail else actual[:ACTUAL_TEXT_CHARS]
    return {"span_check": check, "buffer_length": len(buffer), "actual_text": shown,
            "actual_text_truncated": len(shown) < len(actual), "expected_chars": len(expected),
            "actual_chars": len(actual)}


def _grapheme_warnings(buffer: str, span: MatchSpan, change_id: str, change_index: int) -> list[dict]:
    boundaries = (("insertion", span.start),) if span.start == span.end else (("start", span.start), ("end", span.end))
    return [warning("grapheme_boundary_split",
                    f"{change_id} {name} offset {offset} falls inside a likely grapheme cluster; offsets are code points.",
                    change_id=change_id, change_index=change_index, boundary=name, offset=offset)
            for name, offset in boundaries if splits_grapheme(buffer, offset)]


def _basis_shift(original, change, span, change_facts, overlapping) -> dict | None:
    """Map a sequential selection back to transaction-start coordinates."""
    requested = int(change.manifest.disambiguation["occurrence_index"])
    position = span.start
    for fact in reversed(change_facts):
        start, end, length = fact["span_start"], fact["span_end"], fact["replacement_chars"]
        if position < start:
            continue
        if position >= start + length:
            position += (end - start) - length
            continue
        position = None
        break
    needle = canonicalize_text(change.match_payload)
    index = None
    if position is not None and original[position:position + len(needle)] == needle:
        index = next((number for number, occurrence in enumerate(
            find_exact_occurrences(original, needle, overlapping=overlapping), 1) if occurrence.start == position), None)
    if index == requested:
        return None
    change_id = change.manifest.change_id
    if index is None:
        detail = (f"{change_id} occurrence_index {requested} selected text produced by earlier changes in this"
                  " transaction; indexes count the sequential buffer, not transaction start.")
    else:
        detail = (f"{change_id} occurrence_index {requested} selected the occurrence that was index {index} at"
                  " transaction start; indexes count the sequential buffer after earlier changes.")
    return warning("occurrence_index_basis_shift", detail, change_id=change_id, change_index=change.change_index,
                   occurrence_index=requested, transaction_start_occurrence_index=index)


def _consumed_occurrences(occurrences, change_facts) -> list[dict]:
    """Name the earlier change that overlapped each original occurrence."""
    result = []
    for number, occurrence in enumerate(occurrences, 1):
        low, high = occurrence.start, occurrence.end
        consumer = None
        for fact in change_facts:
            start, end, length = fact["span_start"], fact["span_end"], fact["replacement_chars"]
            if (start <= low) if start == end else (end <= low):
                shift = length - (end - start)
                low, high = low + shift, high + shift
            elif start >= high:
                continue
            else:
                consumer = fact
                break
        result.append({"occurrence_index": number, "start": occurrence.start, "end": occurrence.end,
                       "consumed_by_change_id": consumer["change_id"] if consumer else None,
                       "consumed_by_change_index": consumer["change_index"] if consumer else None})
    return result


def _rejected(
    reason: FailureReason,
    detail: str,
    before_hash: str,
    failed_change_id: str | None = None,
    extra_diagnostic: dict | None = None,
    *,
    buffer: str,
    prior_changes: int = 0,
    focus: int | None = None,
    near_miss_buffer: str | None = None,
) -> RejectedCoreResult:
    diagnostic = {
        "retryable": reason in RETRYABLE_FAILURE_REASONS,
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
        failure_buffer=FailureBufferContext.capture(buffer, prior_changes, focus),
        near_miss_buffer=near_miss_buffer,
    )
