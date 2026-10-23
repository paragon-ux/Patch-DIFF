# PR #11 friction follow-up: triage and decisions

Source: [PR-11-d68c77d-friction-review.md](../reviews/PR-11-d68c77d-friction-review.md) (FR-1..FR-20: 0 blocking, 3 high, 11 medium, 6 low). Base: `origin/main` at merge commit `16ce338`. This record is written before production changes and governs them.

## Compatibility rules for this batch

1. Existing `failure_reason` values, request fingerprints, recorded runtime profiles (`patchdiff-mvp-0.1.0` .. `0.4.0`) and the canonical record JSON of every request that is valid today stay byte-identical. No new failure label is introduced.
2. A change that makes previously rejected input acceptable gets a new immutable profile. Recorded profiles never gain semantics.
3. Response changes are additive: new keys, never removed or retyped keys. The one exception is the FR-8 elision of a duplicate `current_context`, which uses the already documented unavailable-object shape.
4. New persisted facts apply to new rows only. Historical rows are never rewritten or retrofitted. Exact keyed recovery returns what was stored.
5. Replay never reads diagnostics, warnings or line-ending metadata. Replay results for existing history are unchanged.

## Triage summary

| FR | Severity | Disposition | Persisted / profile impact |
| --- | --- | --- | --- |
| FR-1 | high | Fix with decision D1 | New `failure_detail` text when `prior_changes > 0`; accepted-row warnings (D11) |
| FR-2 | high | Fix with decision D2 | New immutable profile `patchdiff-mvp-0.5.0` for tx/2 span context; warnings (D11) |
| FR-3 | high | Fix with decision D3 | Migration `20261022_0003` adds `cloud_target_files.source_line_endings` |
| FR-4 | medium | Fix with decision D4 | `diagnostic.retryable` on new rejected rows |
| FR-5 | medium | Fix with decision D5 | New diagnostic keys on new span rejections |
| FR-6 | medium | Fix with decision D6 | None (response-only scan metadata) |
| FR-7 | medium | Fix with decision D7 | New `failure_detail` and diagnostic keys for new `sequential_match_invalid` rows |
| FR-8 | medium | Fix with decision D8 | New `failure_context.selection` value on new rows |
| FR-9 | medium | Fix now | None |
| FR-10 | medium | Fix with decision D10; decline fingerprint normalization | New diagnostic keys on new conflict/key-syntax rows |
| FR-11 | medium | Fix now | None (read-side join) |
| FR-12 | medium | Fix the history byte budget; document the tx/3 limit; decline a shared admission cap and bounded audit storage | None |
| FR-13 | medium | Fix now | None |
| FR-14 | medium | Fix with decision D14 | None |
| FR-15 | low | Fix now | None |
| FR-16 | low | Fix now | None |
| FR-17 | low | Fix with decision D11 | Accepted-row warnings |
| FR-18 | low | Fix now; admission rule unchanged | None |
| FR-19 | low | Fix now | None |
| FR-20 | low | Fix now | None |

## Decisions

### D1 (FR-1) Sequential `occurrence_index` basis

The selector semantics stay as they are: an `occurrence_index` counts exact occurrences in the sequential buffer that the edit sees, after earlier edits in the same transaction. Changing that basis would change acceptance for recorded history. The fix makes the basis explicit and detectable:

- The guide, MCP_TOOLS, the `occurrence_index` schema description and the `patchdiff_submit_edits`/`patchdiff_submit_operations` tool descriptions state the basis. They say that `find_occurrences` and `exact_candidates` indexes are only valid for the first edit, or for one edit per transaction, and recommend tx/2 spans in descending offset order for multi-occurrence edits.
- When `match_ambiguous` or `disambiguation_invalid` fires with `prior_changes > 0`, the runtime appends one sentence to `failure_detail` naming the sequential basis and the number of earlier simulated changes. The detail for `prior_changes == 0` is byte-identical to today.
- Accepted transactions carry an `occurrence_index_basis_shift` warning (D11) when an edit's `occurrence_index` resolved to an occurrence whose transaction-start index differs, or that did not exist at transaction start. The runtime maps the selected span back through the earlier changes' recorded spans. This turns the friction review's silent wrong edit into an accepted edit that is flagged.

Declined: an `occurrence_basis: "transaction_start"` selector. It would need a new protocol path and selector semantics. Descending tx/2 spans already express the same intent exactly, and the D11 warning detects the mistake. It can be reconsidered as its own profile.

### D2 (FR-2) Span context guards and grapheme warnings

- tx/2 span operations gain optional `expected_before` and `expected_after` (non-empty strings or null). After canonicalization, each must equal the text immediately adjacent to the span in the sequential buffer: `buffer[start-len(expected_before):start]` and `buffer[end:end+len(expected_after)]`. They are not anywhere-before/after anchors. A mismatch rejects with the existing `span_expected_text_mismatch` label and `diagnostic.span_check: "expected_before" | "expected_after"`, so hosts keep one remedy row.
- These fields are rejected today, so accepting them changes acceptance. A tx/2 record whose span operations contain either key is recorded under the new immutable runtime `patchdiff-mvp-0.5.0`, profile `(overlapping, singleton selectors, spans, no replace_all, span_context)`. A tx/2 record without those keys keeps `patchdiff-mvp-0.3.0` with an identical record, fingerprint and profile. Replay of `0.3.0` rows still rejects the keys, and `0.3.0` never gains them. The protocol stays `patchdiff-tx/2`. The fingerprint does not include the runtime version, so request identity is unchanged.
- Context stays optional. Requiring it for insertions would break existing hosts.
- Accepted transactions carry a `grapheme_boundary_split` warning (D11) when a resolved span boundary falls inside a likely grapheme cluster, for any operation type. The check is a deterministic conservative approximation, not full UAX #29: it flags a boundary before a combining mark, ZWJ, variation selector, emoji modifier or tag character, a boundary after a ZWJ, and a boundary between the two halves of a regional-indicator pair. Canonical text contains no CR, so a CRLF pair can never be split and needs no check.
- Tool descriptions for the read, search and submission tools say that offsets are Unicode code points and that UTF-16 hosts such as JavaScript must convert.

### D3 (FR-3) Source line endings and honoured export formats

- Canonical text and hashes are unchanged: storage stays LF-normalized.
- Migration `20261022_0003` adds nullable JSONB `cloud_target_files.source_line_endings`. New targets record `{style, lf, crlf, cr, normalized, source_code_points, source_utf8_bytes, source_sha256}` from the raw upload before canonicalization. `style` is `none`, `lf`, `crlf`, `cr` or `mixed`. `source_sha256` is SHA-256 of the raw UTF-8 bytes, so a host can verify its file before canonicalizing. Existing targets keep NULL, meaning unknown. No backfill is attempted, because the raw upload was never stored.
- `patchdiff_initialize_target`, `patchdiff_handle_upload` and `patchdiff_get_target` return `source_line_endings`.
- `patchdiff_export_target(format)` becomes an enum: `original_text` (default; legacy alias that keeps returning canonical LF text, documented as such), `canonical_lf`, `crlf` and `original_eol`. `original_eol` restores a uniform recorded style (`none`/`lf` → LF, `crlf` → CRLF, `cr` → CR). It returns `invalid_argument` with `code: "original_eol_unrecoverable"` for mixed sources, because per-line endings were never stored, and with `code: "source_line_endings_unknown"` for targets created before 0003. Unknown format values return `invalid_argument` with `code: "unsupported_export_format"`. They were silently echoed before; the only valid value earlier hosts could rely on was the default. The response adds `content_eol` and `content_sha256` (SHA-256 of the exported UTF-8 bytes). `hash`/`current_hash` remain the canonical hash.
- Downgrade from 0003 refuses when any target has recorded line endings, so recorded facts are never silently destroyed. This follows the 0002 rule. Without such rows it drops the column. Tests cover populated legacy upgrade → downgrade → upgrade, plus refusal with recorded rows.

### D4 (FR-4) One retryable set

`app.core.failures.RETRYABLE_FAILURE_REASONS` becomes the only definition, used by the applier and the service. It contains `match_absent`, `match_ambiguous`, `disambiguation_invalid`, `sequential_match_invalid`, `span_out_of_bounds`, `span_expected_text_mismatch`, `target_hash_mismatch`, `target_version_mismatch` and `target_diverged`. Definition: the same target can accept a new proposal derived from a fresh read; the identical request will not succeed. `target_diverged` is added because the guide already maps it to "re-read and re-derive". The flag is advisory and applies to new rows only. Stored rows and keyed recovery keep their recorded value.

### D5 (FR-5) What is at the span

New span rejections add bounded diagnostics in failing-buffer coordinates: `span_check`, `buffer_length`, and for text mismatches `actual_text` (at most 64 code points), `actual_text_truncated`, `expected_chars` and `actual_chars`. `actual_text` is target text, never proposer text. The existing `failure_detail` strings are unchanged.

### D6 (FR-6) Near-miss scan scope

- Fresh rejections scan a bounded in-memory copy of the failing buffer, at most 65,536 code points from its start, instead of only the 256-code-point stored prefix. The copy is response-only and never persisted; the applier keeps the bounded copy, never the whole buffer. A sliding character-count lower bound (bag distance) skips windows that cannot be within the threshold, so rankings stay exact. The 1,000,000-cell work cap still bounds the dynamic program. When the cap is reached, the scan stops at a window-start boundary and reports the scanned range. It no longer discards the ranking computed so far. `work_budget_exhausted` remains for the case where no window start could be evaluated.
- New fields: `scan_source` (`failing_buffer` or `stored_failure_context`), `scanned_start`/`scanned_end` (the window-start range searched), `scope_truncated` and `candidates_truncated`. `truncated` keeps its meaning (either one). When no candidate is found, a `hint` names `patchdiff_find_occurrences` on a short fragment. Exact recovery of older rows still scans only their stored context.
- `failure_detail` for `match_absent` is unchanged: it is shared with legacy PDCP and pinned by history.

### D7 (FR-7) Distinct near-miss locations and consumed matches

- Near-miss candidates are selected greedily in `(distance, start, end)` order, skipping any window that overlaps one already selected, so three candidates name up to three locations.
- `sequential_match_invalid` now persists `original_occurrence_count` and up to five `original_occurrences` in transaction-start coordinates, each with the `consumed_by_change_id`/`consumed_by_change_index` of the earlier change that overlapped it. Its `failure_detail` becomes "MATCH text was consumed by earlier change <id> in this transaction." for new rows. It no longer persists `near_miss_query`, and the response returns near misses as omitted with `omission_reason: "sequential_match_consumed"`. Older rows recovered by key get the same omission.

### D8 (FR-8) Focused and deduplicated rejection context

- When the runtime knows the failure location and it would not be visible near the start of the prefix (location + 64 > 256), `failure_context` becomes a window of at most 256 code points around that location, with `selection: "failure_window"` and its real `start`/`end`. Known locations: span start (out-of-bounds uses the buffer end), the first exact candidate for ambiguity failures, and the span start for context-guard mismatches. Otherwise `selection` stays `"prefix"` and nothing changes. The byte budgets are unchanged, and shrinking keeps the location inside the window.
- On MCP responses, a `current_context` that would equal `diagnostic.failure_context` key for key is returned as an unavailable object with `unavailable_reason: "same_as_failure_context"`. Hosts already handle unavailable objects; they read `diagnostic.failure_context` instead. The Python service result still carries the full object.

### FR-9 Current state on accepted and deduplicated responses

Accepted responses add `current_version` and `current_hash`. On a fresh acceptance they equal `version`/`after_hash`. On deduplicated recovery they name the target's current state. Additive only.

### D10 (FR-10) Request-key diagnostics

- `failure_reason` stays `context_invalid`. A key conflict adds `diagnostic.code: "request_key_conflict"`, `differing_components` (fingerprint envelope members that differ from the stored row: `protocol_version`, `pdcp_content_hash`, `expected_target_version`, `expected_current_hash`, `parent_pdcp_log_id`) and `differing_fields` (at most 10 JSON paths where the canonical typed records differ, for example `edits[0].rationale`). Invalid key syntax adds `diagnostic.code: "invalid_client_request_id"`.
- The guide gets a table row for both codes and recommends `patchdiff_get_pdcp_log(client_request_id=…)`.
- Declined: normalizing `null` and omitted optional fields in fingerprints. Recorded keyed rows must keep recovering under their stored fingerprints. The guide's identity rules already say a null field is a different proposal; the new `differing_fields` names the exact path.

### FR-11 Joinable audit trail

Ledger entries add `pdcp_log_id`, `change_index`, `editing_cycle_id`, `log_sequence`, `before_version`, `after_version`, `transaction_intent` and `rationale`. The last two are parsed from the stored typed record; they are null for legacy PDCP rows, whose manifest intent is already the row intent. Attempt entries add `attempt` (alias of `regeneration_attempt`), plus `intent` (at most 256 code points) and `intent_truncated` for typed records. The guide documents `include_previous_cycles` after SAVE, and documents that `log_sequence` and `ledger_sequence` are global across targets, with gaps per target. Read-side only.

### FR-12 Size limits

- `get_pdcp_log(include_content=true)` adds a 1,048,576-byte page budget over the UTF-8 size of returned `pdcp_content`. The first entry with content is always returned whole, so any row can be fetched with `limit: 1`. Later entries over budget return `pdcp_content: null` with `pdcp_content_omitted: "page_byte_budget"`. Paging is unchanged.
- The tx/3 limit is documented as specific to sole replacement. It bounds a single whole-document string field that a model can produce in one step. tx/1 and tx/2 keep no admission cap, and the guide no longer suggests splitting an oversized replacement into operations to get around the limit.
- Declined: a shared admission cap. It would reject tx/1/tx/2 requests that existing hosts send successfully today. Also declined: bounding stored rejected payloads, because the append-only attempt log records every attempt in full by contract.

### FR-13 Line-read coordinates

`patchdiff_read_lines` adds an absolute `next_start` (null when not truncated) next to the unchanged range-relative `next_offset`. A new opt-in `include_line_starts: false` returns `line_starts: [{line, start}]` for every selected line that starts inside the returned page. Additive.

### D14 (FR-14) Wire encoding and response envelope

- Tool-result text and JSON-RPC lines are serialized with `ensure_ascii=False`. If a payload cannot be encoded as strict UTF-8, for example because a lone surrogate reached an echo, that one message falls back to ASCII escaping. The process never crashes on output. Parsed JSON values are identical.
- Unknown or missing tool arguments return a structured JSON `invalid_argument` payload as the tool-result text, with `code: "unknown_argument"` or `"missing_argument"` and the argument names. The result keeps `isError: true`, because the call never reached the tool. Previously the text was a Python `TypeError` message.
- `patchdiff_initialize_target`, `patchdiff_handle_upload`, `patchdiff_get_target` and `patchdiff_export_target` add `status: "ok"` on success. Preview `invalid_argument` adds `failure_detail` next to its existing `code`/`detail`. Submission `invalid_argument` adds a top-level `code`. Accepted responses gain `current_version`/`current_hash` (FR-9). Existing keys are kept.

### FR-15, FR-16 Schema descriptions and examples

Every top-level tool parameter gets a one-line description: units and coordinate frame, guard semantics, cursor meaning. The guard rule is mirrored in submission tool descriptions for hosts that strip `anyOf`. The `tools/list` budget (65,536 bytes) is rechecked. MCP_TOOLS examples are regenerated from live output, the `include_correlation_id` statement excludes the deprecated wrapper, guide UUIDs use the `…-4111-8111-…` form, and the discovery sequence becomes a numbered list.

### D11 (FR-17 and the FR-1/FR-2 warnings) Accepted-transaction warnings

- Accepted results carry advisory warnings that never change the verdict:
  - `no_op_change`: a change's matched text equals its replacement.
  - `no_op_transaction`: `before_hash == after_hash`.
  - `occurrence_index_basis_shift` (D1).
  - `grapheme_boundary_split` (D2).
- `warnings` stays a list of strings, each starting with its code. A new `warning_details` list carries objects `{code, detail, change_id?, change_index?, …}`. At most 16 details are returned, with `warning_count` and `warnings_truncated`.
- Accepted rows with at least one warning persist `diagnostic_json: {"warnings": [...], "warning_count": n, "warnings_truncated": bool}`. Accepted rows without warnings keep `diagnostic_json = NULL`, as today. Exact keyed recovery returns the stored warnings. Older accepted rows recover with none. Preview returns the same warnings within its budget.

### FR-18 Missing numbers

`exact_candidates` adds `next_occurrence_index` when truncated, to continue with `patchdiff_find_occurrences(start_occurrence=…)` on the canonical target. `replacement_too_large` adds `actual`, `limit`, `canonical_code_points`, `canonical_utf8_bytes` and `canonical_would_fit`. The admission rule itself (raw and canonical limits, in that order) is unchanged.

### FR-19 Preview recovery parity

Preview computes `near_misses` inline for `match_absent`, using the same function and budget. It holds no lock, so the caller-transaction omission does not apply. Unknown preview arguments such as `include_correlation_id` return the structured `invalid_argument` from D14. Preview still has no request key, lineage, audit or correlation option.

### FR-20 Version guard on SAVE

`patchdiff_save` accepts optional `expected_target_version`. A mismatch returns `status: "rejected"`, `failure_reason: "target_version_mismatch"` and no snapshot. An invalid value returns `context_invalid`. Both guards are checked when supplied.

## Verification plan

Each finding gets unit tests for the pure behavior, live PostgreSQL integration tests for persisted and response effects, and real stdio subprocess checks for every changed tool shape. Migration 0003 gets offline SQL rendering plus live populated upgrade → downgrade → upgrade and refusal tests. Final evidence: the full pytest suite on an isolated database, `evaluation/offline_eval.py`, and an adapted copy of the PR #11 live stdio harness. A PR Review Standard v1.1.0 review is stored in `docs/reviews/`.
