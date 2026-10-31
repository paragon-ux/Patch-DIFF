# MCP_TOOLS.md

Unicode boundary: edit-submission strings and metadata must be valid UTF-8/PostgreSQL text. Known-target invalid text returns an audited target_encoding_invalid / PROTOCOL_VALIDATION rejection. Existing pdcp_content TEXT carries reversible ASCII-escaped patchdiff-invalid-input/1 evidence; JSONB holds only safe diagnostics. Read/search string errors return invalid_argument with no edit-attempt row. Valid inputs and discovery operation shapes are unchanged.

Conflicting-key submissions return context_invalid with `diagnostic.code: "request_key_conflict"` plus a fresh durable rejection log ID. The rejected row uses a NULL key and submitted fingerprint, with original-log linkage, a bounded submitted-key preview and the differing fingerprint components. The response continues to echo the submitted key. Exact recovery of the original request remains deduplicated:true without a new row; repeated conflicts each append an immutable attempt.


## Purpose

This document defines the complete MCP tool surface for PatchDIFF.

PatchDIFF is exposed over stdio JSON-RPC (`backend/app/mcp/external_adapter.py`) and an internal Python registry (`backend/app/mcp/server.py`). All tools route through the deterministic service layer (`backend/app/services/`) and execute per-target atomic commits against Postgres.

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](../papers/MODERNIZATION_ARCHITECTURE.md).
As-built record: [MODERNIZATION_CHANGE_DOC.md](../papers/MODERNIZATION_CHANGE_DOC.md).

## MCP Tool Surface Overview

The 22 internal tools are organized into the groups below. External stdio MCP
defaults to the **7-tool `editor` profile**; `unobserved` exposes 5, `observed` 6,
`observed_editor` 4, and explicitly selected `full` exposes all 22. The opt-in
`observed_editor` profile contains only read_target, find_occurrences,
observe_scope and submit_observed_operations (all with the `patchdiff_` prefix);
SAVE/replay belong to the separate trusted host session in that role. Both
advertisement and dispatch
enforce the immutable startup `PATCHDIFF_MCP_PROFILE`. Initialization, export,
legacy and administrative tools require `full` at the external boundary.
See [profiles, exact batch contracts and executable examples](STRUCTURAL_BATCH_EDITING.md).

| Group | Tool Name | Role & Modernized Status |
| --- | --- | --- |
| **1. Target Lifecycle** | `patchdiff_initialize_target` | Initialize canonical target state, active cycle, initial snapshot and recorded source line endings in Postgres. |
| | `patchdiff_handle_upload` | Upload alias for `patchdiff_initialize_target`. |
| | `patchdiff_get_target` | Retrieve canonical metadata, current content, hash, version and recorded source line endings. |
| | `patchdiff_export_target` | Export target text in an explicit line-ending format, with metadata. |
| **2. Authoritative Reads & Search** | `patchdiff_read_target` | Authoritative bounded read of target slices by code-point offset with `next_start` continuation. |
| | `patchdiff_read_lines` | Bounded inclusive LF line ranges with range-relative and absolute continuation; default 4,000/cap 8,000 code points. |
| | `patchdiff_find_occurrences` | Enumerate exact occurrences (overlapping counted) with bounded context and pagination. |
| **3. Transaction Submission** | `patchdiff_submit_edits` | **Primary typed input** (`patchdiff-tx/1`). Structured `edits[]`, required guards, `client_request_id` idempotency. |
| | `patchdiff_submit_operations` | Guarded `patchdiff-tx/2` ordered match/span operations with required exact expected text on spans; profile 0.3.0, or 0.5.0 when span context is used. |
| | `patchdiff_submit_replacement` | Guarded sole whole-target replacement (`patchdiff-tx/3`), immutable profile 0.4.0. |
| | `patchdiff_preview` | Read-only advisory evaluation of an explicit transaction format with bounded evidence; submission rechecks. |
| | `patchdiff_submit_pdcp` | **Frozen legacy input** (`0.2.3`). Raw `.pdcp` text with 7 required manifest fields. |
| **4. Checkpoint, Replay & Audit** | `patchdiff_save` | Snapshot current target and rotate editing cycle without target mutation; optional version and hash guards. |
| | `patchdiff_replay` | Deterministically reconstruct target from initial snapshot + accepted logs, reporting component checks. |
| | `patchdiff_finalize_target` | Atomic single-roundtrip SAVE checkpoint, replay verification, and format export under row locking. |
| | `patchdiff_get_pdcp_log` | Bounded newest-first page of append-only attempts (accepted/rejected), filtering by status, hash, or request ID. |
| | `patchdiff_get_manifest_ledger` | Retrieve accepted-only manifest ledger entries with `origin`, `derived` facts and their attempt identity. |
| **5. Convenience & Deprecated** | `patchdiff_build_prompt_context` | Convenience bounded target prefix (`context_truncated`). See [LEGACY_COMPATIBILITY.md](../legacy/LEGACY_COMPATIBILITY.md). |
| | `patchdiff_get_regeneration_context` | **Deprecated** compatibility wrapper. See [LEGACY_COMPATIBILITY.md](../legacy/LEGACY_COMPATIBILITY.md). |
| | `patchdiff_build_regeneration_prompt` | **Deprecated** compatibility wrapper. See [LEGACY_COMPATIBILITY.md](../legacy/LEGACY_COMPATIBILITY.md). |
| | `patchdiff_request_regeneration` | **Deprecated** compatibility wrapper. See [LEGACY_COMPATIBILITY.md](../legacy/LEGACY_COMPATIBILITY.md). |

### Bounded Wire & Context Budgets & Measured Service Latency

| Surface / Operation | Hard Wire / Context Cap | Measured Performance / Scaling (`PR #14`) |
| --- | --- | --- |
| **Discovery (`tools/list`)** | `<= 65,536 B` total (`<= 8,192 B` for 13 executable examples across 9 tools) | Deterministic deep-copied schema |
| **Authoritative Reads (`patchdiff_read_target`, `patchdiff_read_lines`)** | `4,000` default / `8,000` max Unicode code points per call | Single-row observation with `next_start` / `next_offset` |
| **Exact Search (`patchdiff_find_occurrences`)** | `context_chars` default `40` / cap `400`; `max_results` cap `200` | Counts all overlapping occurrences (`patchdiff-mvp-0.2.2`) |
| **Typed Submission (`patchdiff_submit_edits`, `tx/1`)** | $O(\text{delta})$ wire size | **`151 B`** wire (`206 B` stored) for 1 edit; **`259 B`** wire (`314 B` stored) for 5 edits |
| **Whole-Target Replacement (`patchdiff_submit_replacement`, `tx/3`)** | Fresh admission `<= 1,000,000` code points and `<= 1,048,576 B` UTF-8 (raw & canonical) | **`232 B`** `arguments` JSON / **`290 B`** stored / **`341 B`** `tools/call` line (`3 B` rewrite); `2,377 B` / `2,435 B` / `2,486 B` (`2,109 B` 2 KB rewrite) |
| **Advisory Preview (`patchdiff_preview`)** | `<= 32,768 B` total (`<= 16,384 B` for up to 32 facts at `<= 2,048 B` each; `<= 16,384 B` diagnostics) | Keyless read-only evaluation without locks or audit writes |
| **Rejection Enrichment (`exact_candidates`, `near_misses`, contexts)** | `<= 18,432 B` compact ASCII JSON across newly added enrichment fields (`<= 4,096 B` per context, `<= 8,192 B` candidates/near misses, `<= 256` code points `failure_context`) | Local 5-run near-miss medians on 65,536-code-point fixtures (`SVC-001`): **`1.7 ms`** prose (**58.9× faster** vs. PR #13), **`41.9 ms`** repetitive logs (**16.9× faster**, 100% scanned) |
| **History & Ledger Paging (`patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`)** | `limit` default `50` / cap `200`; `include_content=True` on `patchdiff_get_pdcp_log` uses a `1,048,576 B` UTF-8 page budget (first entry with content returned whole; later entries over budget set `pdcp_content_omitted: "page_byte_budget"`) | Local 7-run medians over 20 MB history (`MCP-001`): **`14.68 ms`** ledger / **`22.85 ms`** log on `50 × 400 KB` `tx/3` (**16–19× faster** vs. PR #13); **`136.72 ms`** log / **`221.59 ms`** ledger (`limit=50`) on `20 × 1 MB` `tx/1` |

---

## Guarded editing, reads, preview and diagnostics

This section is the normative contract for guarded operations (`patchdiff-tx/2`), sole replacement (`patchdiff-tx/3`), line reads, preview, response options, accepted-transaction warnings, bounded rejection evidence and line-ending export. Other documents summarize it and link here. Recorded decisions: [F01](https://github.com/paragon-ux/Patch-DIFF/blob/main/docs/usability/F01-decision.md), [Pass A](https://github.com/paragon-ux/Patch-DIFF/blob/main/docs/usability/PASS-A-decision.md), [Pass B](https://github.com/paragon-ux/Patch-DIFF/blob/main/docs/usability/PASS-B-decision.md) and the [PR #11 friction follow-up](https://github.com/paragon-ux/Patch-DIFF/blob/main/docs/usability/friction-followup-decision.md).

Byte budgets below count compact ASCII-escaped JSON (`ensure_ascii=True`, `separators=(",", ":")`) and exclude the JSON-RPC envelope. Tool-result text is literal and its JSON-RPC line is ASCII-escaped (see [Discovery, argument errors and examples](#discovery-argument-errors-and-examples)). Offsets and counts are Unicode code points, not UTF-8 bytes or UTF-16 units: a JavaScript or TypeScript host must convert its UTF-16 string indexes before sending a span or reading an offset.

### `patchdiff_submit_operations` (`patchdiff-tx/2`)

`patchdiff_submit_operations(target_file_id, intent, operations, expected_target_version=null, expected_current_hash=null, source="model_response", parent_pdcp_log_id=null, attempt=null, client_request_id=null, include_correlation_id=false)` uses the same guard, lineage, audited rejection, acceptance, ledger and recovery response contract as typed edits. At least one guard is required, and every supplied guard is checked. Missing or invalid guard syntax follows the existing `PROTOCOL_VALIDATION` path; stale valid guards reject at `PRECONDITION_GUARD`.

Each operation is one of:

- Match: `{op: "match", match, replace, change_id?, rationale?, risk?, occurrence_index?, anchor_before?, anchor_after?}`, with the unchanged exact-match selector rules.
- Span: `{op: "span", start, end, expected_text, replace, change_id?, rationale?, risk?, expected_before?, expected_after?}`. `start` and `end` are non-bool integers in `0..2^63-1`, `end` is exclusive and `end >= start`. Selectors and unknown fields reject. Coordinates refer to the sequential canonical buffer, that is, the text after earlier operations in the same transaction. For several edits taken from one read, order spans by descending `start` so earlier offsets stay valid. The canonical `expected_text` must equal that span exactly; newlines in `expected_text` and `replace` are canonicalized before application. Explicit insertion uses `start == end` with an empty `expected_text`.
- Span context: optional `expected_before` and `expected_after` are non-empty strings or null. After canonicalization they must equal the text immediately adjacent to the span in the sequential buffer, `buffer[start-len(expected_before):start]` and `buffer[end:end+len(expected_after)]`. Unlike anchors, they are adjacent, not anywhere-before/after. They are the way to verify an insertion, which has no `expected_text` to check.

Mixed match/span transactions are atomic. Span applicability failures are `span_out_of_bounds` and `span_expected_text_mismatch` (including context mismatches); either rejects the whole transaction with no partial facts or ledger rows. Their diagnostics add `span_check` (`bounds`, `expected_text`, `expected_before` or `expected_after`) and `buffer_length`. Text checks also add `actual_text`, at most 64 code points of what is actually there in failing-buffer coordinates (the end nearest the span for `expected_before`), plus `actual_text_truncated`, `expected_chars` and `actual_chars`. `failure_detail` strings for the existing checks are unchanged.

Runtime profiles are immutable. A tx/2 record without `expected_before`/`expected_after` keys uses runtime `patchdiff-mvp-0.3.0` with an unchanged record, fingerprint and profile; `0.3.0` still rejects those keys. A tx/2 record whose span operations contain either key, even with a null value, is recorded under `patchdiff-mvp-0.5.0`, which adds only span context. Typed-match and legacy records keep `patchdiff-mvp-0.2.2`. Replay dispatches on the recorded runtime and refuses unsupported profile/operation pairs. Span facts add `operation: "span"` to the existing runtime-derived spans, counts and hashes, and the ledger `origin` stays `typed`. No migration is required for tx/2.

### `patchdiff_submit_replacement` (`patchdiff-tx/3`)

`patchdiff_submit_replacement(target_file_id, intent, replacement, expected_target_version?, expected_current_hash?, source="model_response", parent_pdcp_log_id?, attempt?, client_request_id?, include_correlation_id=false)` records exactly one guarded `replace_all` through the existing locked pipeline under immutable runtime `patchdiff-mvp-0.4.0`; tx/2 and `0.3.0` are unchanged. At least one guard is required, every supplied guard is checked, and the tool returns the normal submission response. An empty replacement is valid. One typed ledger row records the full original span with `operation: "replace_all"`.

Fresh admission limits apply to the raw replacement and to its canonical result: at most 1,000,000 code points and at most 1,048,576 UTF-8 bytes each, inclusive, checked in the order raw code points, raw bytes, canonical code points, canonical bytes. A valid oversized fresh replacement returns `status: "invalid_argument"`, `code: "replacement_too_large"`, `pdcp_log_id: null` and a `diagnostic` with `code`, `limit_exceeded`, `actual`, `limit`, `canonical_code_points`, `canonical_utf8_bytes` and `canonical_would_fit`. No attempt or current-PDCP row is written. `canonical_would_fit: true` means the raw limit failed only because of CRLF or CR line endings: send the text with LF line endings.

These limits are specific to sole replacement. They bound one whole-document string that a model must produce in a single field. tx/1 and tx/2 have no admission cap, because each of their payload strings is an exact excerpt or edit. Use them when the change really is a set of edits, not to get around this limit.

Ordering: invalid text is classified first, through the audited Unicode path. An existing `client_request_id` is then recovered (same fingerprint) or audited as a conflict (different fingerprint) before fresh admission runs. A conflict audit row therefore stores the complete submitted record even when it exceeds the fresh limits, as every tx/1 and tx/2 attempt does; the limits bound what can be admitted as a new replacement, not the size of audit evidence. Replay never applies admission limits.

### `patchdiff_read_lines`

`patchdiff_read_lines(target_file_id, start_line=1, end_line=null, offset=0, max_chars=null, include_line_starts=false)` returns `status: "ok"`, `target_file_id`, `version`, `current_hash`, `total_chars`, `total_lines`, the selected `start_line`/`end_line`, absolute `range_start`/`range_end`, page `start`/`end`, exact `text`, `truncated`, range-relative `next_offset` and absolute `next_start`.

- Lines are one-based and LF-only. `end_line` is inclusive (default: last line), and each line includes its trailing LF. A trailing LF creates a final empty line; an empty target has one empty line.
- Page and range ends are exclusive code-point offsets. Omitted or null `max_chars` defaults to 4,000; larger values cap at 8,000. An `offset` equal to the range length returns an empty final page.
- Continuation: pass `next_offset` back as `offset` with the same line range, or pass `next_start` as `patchdiff_read_target.start`. Both are null on the last page. `next_offset` is relative to `range_start`; never pass it to `read_target`.
- `include_line_starts: true` adds `line_starts: [{line, start}]`, the absolute start offset of every selected line that begins inside the returned page. Use it to turn a line number into a span offset without a second read.
- Booleans, non-integers, non-positive line numbers or sizes, a negative offset, a non-boolean `include_line_starts` and out-of-range coordinates return `invalid_argument`; an unknown target returns `not_found`.
- The read is one ordinary column observation under `no_autoflush`. It never flushes, refreshes or edits local ORM state and never normalizes corrupt storage. Each continuation page is a new observation and can see a newer version.

### `patchdiff_preview`

`patchdiff_preview(target_file_id, format, expected_target_version?, expected_current_hash?, <proposal>)` evaluates a fresh proposal with the same read-only guard/decode/apply evaluator as submission, from one coherent observation. Format `0.2.3` uses only `pdcp_content`; `patchdiff-tx/1` uses `intent` and `edits`; `patchdiff-tx/2` uses `intent` and `operations` (span context selects `0.5.0` exactly as submission does); `patchdiff-tx/3` uses `intent` and `replacement`. Fields that belong to another format reject even when explicitly null. Typed formats require a guard. There is no request key, lineage, audit or correlation option; passing one over MCP returns the structured unknown-argument error below.

Preview writes no row, takes no lock, and never commits or rolls back. It returns `preview: true`, `advisory: true`, status, stage and validity, plus `current_version`/`current_hash` and `before_version`/`before_hash` from the same observation. Accepted previews include `after_hash`, `change_facts` and the same warnings a submission would return. Rejected previews include bounded original diagnostics and never partial facts. For `match_absent`, preview computes `near_misses` inline with the same function and budget as submission; it holds no lock, so the caller-transaction omission does not apply. Pending local ORM changes to the target return unavailable context without flushing. A valid oversized replacement receives the same no-attempt `replacement_too_large` classification as submission. Preview never reflects a historical keyed outcome. Its own `invalid_argument` responses carry `code` with both `detail` and `failure_detail`. Submission always re-locks and rechecks guards; prefer a version guard, because a hash alone cannot detect intervening no-op or ABA changes.

Preview evidence is bounded:

- The complete returned payload is at most 32,768 bytes.
- Accepted evidence is a prefix of at most 32 whole facts, each at most 2,048 bytes, and at most 16,384 bytes including the `change_facts` wrapper. `total_change_count`, `returned_fact_count`, `change_facts_truncated`, `change_facts_omission_reason` and `evidence_omissions` report what was omitted.
- Each textual evidence field is at most 1,024 code points and 8,192 wrapper bytes. An oversized failed-change ID or invalid-target echo is omitted as null, never shortened into a different identity.
- The diagnostic wrapper is at most 16,384 bytes. When it is exceeded, bounded `failure_context` is kept if it fits and other evidence is omitted with an explicit reason.
- If the complete payload still exceeds its cap, `near_misses`, `warning_details`, `warnings`, diagnostic evidence, `failure_detail`, `failed_change_id`, an invalid-target echo and `current_context` are omitted in that order, then trailing whole accepted facts are dropped. Each omission is recorded.

Verdict, stage, validity, a valid target UUID, observed version/hash and accepted `after_hash` are always retained. Preview never returns full proposed target text. This projection does not change full submission or recovery facts or stored diagnostics.

### Response option: `include_correlation_id`

Every submission tool except the deprecated `patchdiff_request_regeneration` accepts `include_correlation_id` (boolean, default `false`). When `true`, each invocation, including exact recovery, returns a fresh UUIDv4 `correlation_id`. It is never stored and never enters request keys or fingerprints. A non-boolean value returns `invalid_argument` with `code: "invalid_include_correlation_id"` before admission, with no attempt row.

### Accepted responses, current state and warnings

Accepted submission responses carry `version` and `after_hash` (the outcome of this attempt) and `current_version` and `current_hash` (the target now). On a fresh acceptance the pairs are equal. On `deduplicated: true` recovery, `version`/`after_hash` name the recorded outcome and `current_version`/`current_hash` name the target's current state, so a host can track state from any response.

Warnings are advisory. They never change the verdict, and replay ignores them. Codes:

- `no_op_change`: the change's matched text equals its replacement.
- `no_op_transaction`: the transaction leaves the text unchanged (`before_hash == after_hash`) while the version still advances. A hash-only guard cannot detect this; prefer a version guard.
- `occurrence_index_basis_shift`: an `occurrence_index` resolved, after earlier edits in the same transaction, to the occurrence that had a different index at transaction start (`transaction_start_occurrence_index`), or to text those edits produced (`null`). The warning reports the basis difference, not intent: a host that meant sequential indexes got the edit it asked for, while a host that copied indexes from `patchdiff_find_occurrences` or `exact_candidates` for several same-string edits edited a different occurrence than it read. The runtime maps the selected span back through the earlier changes' recorded spans to find this.
- `grapheme_boundary_split`: a resolved span boundary (`start`, `end` or `insertion`, with its sequential `offset`) falls inside a likely grapheme cluster. The check is a deterministic conservative approximation of UAX #29: a boundary before a combining mark, ZWJ, variation selector, emoji modifier or tag character, after a ZWJ, between the two halves of a regional-indicator pair, or inside a Hangul jamo sequence. A UTF-16 offset sent as a code-point offset typically triggers it; a deliberate edit of a modifier or combining mark triggers it too. Canonical text contains no CR, so no CRLF pair can be split.

`warnings` is a list of strings, each `"<code>: <detail>"`. `warning_details` lists objects `{code, detail, change_id?, change_index?, ...}`, at most 16, with `warning_count` and `warnings_truncated`. An accepted row with at least one warning stores `diagnostic_json: {warnings, warning_count, warnings_truncated}`; other accepted rows keep `diagnostic_json = NULL`. Exact keyed recovery returns the stored warnings; accepted rows recorded before this change recover with none.

### Retryable rejections

`diagnostic.retryable` is advisory and follows one shared definition: the same target can accept a new proposal derived from a fresh read, while resending the identical request will not succeed. It is `true` for `match_absent`, `match_ambiguous`, `disambiguation_invalid`, `sequential_match_invalid`, `span_out_of_bounds`, `span_expected_text_mismatch`, `target_hash_mismatch`, `target_version_mismatch` and `target_diverged`, and `false` for request-shape, encoding, lineage, request-key and target-identity failures. Stored rows and keyed recovery keep the value recorded when the row was written.

### Bounded rejection context

A new rejection carries immutable `diagnostic.failure_context` and top-level, response-only `current_context`. Each available object has `available: true`, `unavailable_reason: null`, `selection: "prefix" | "failure_window"`, `buffer_stage: "canonical_target" | "intermediate_buffer"`, `prior_changes`, `start`, end-exclusive `end`, `total_chars`, `text`, `truncated`, `observed_target_version` and `observed_target_hash`.

- The observed identity names canonical target state at transaction start. First-change, service, precondition, protocol and lineage errors use canonical context (`prior_changes: 0`). Later application errors use the actual intermediate buffer and count the edits already simulated; those edits were not committed, so never apply intermediate offsets to committed content. `current_context` always describes the refreshed, locked canonical target as a prefix.
- A prefix context is the longest prefix of at most 256 code points that fits the byte budgets, with `start = 0`. When the runtime knows the failure location and fewer than 64 code points of it would be visible in that prefix, `failure_context` is instead a window of at most 256 code points around the location, with `selection: "failure_window"` and its real `start`/`end`. Known locations are the span start (the buffer end for `span_out_of_bounds`; the span end for `expected_after`) and the first exact candidate of an ambiguity failure. `truncated` is `true` whenever the text is shorter than `total_chars`. Each complete context is at most 4,096 bytes, and the combined `{failure_context, current_context}` enrichment, wrapper keys included, is at most 8,192 bytes. Normal SHA-256 identities keep the full 256-code-point text; a corrupted non-ASCII stored hash can shorten the text, keeping the location inside a window, but never the identity. Context contains no proposer strings or duplicated failed-change ID.
- Unavailable objects have `available: false`, `unavailable_reason: "invalid_target_id" | "target_not_found" | "unlocked_local_state" | "same_as_failure_context"`, and null for every other field. On MCP responses, including preview, a `current_context` that would equal `diagnostic.failure_context` key for key is returned as `unavailable_reason: "same_as_failure_context"`; read `diagnostic.failure_context` instead. The Python service result keeps the full object. An available empty target has empty text, zero offsets and `truncated: false`. Dirty local ORM state is unavailable even when compatibility version/hash fields expose local values.
- Exact keyed recovery returns the original stored diagnostic unchanged and captures a fresh `current_context`; older rows without failure context are not retrofitted. Accepted responses carry no context. Context capture never commits caller-owned transactions or releases their locks, so their observed state can remain provisional until the caller commits. Use reads, search and a new linked proposal to correct a rejection.

### Exact candidates, consumed matches and near misses

- `match_ambiguous` and `disambiguation_invalid` failures retain at most five exact candidates (occurrence index, span, 20 code points of context per side and a match preview of at most 64 code points) within 8,192 bytes including the wrapper, plus stage, prior-change count, observed identity, explicit truncation and `next_occurrence_index` (null when nothing was cut). When `buffer_stage` is `canonical_target`, continue with `patchdiff_find_occurrences(text=<match>, start_occurrence=next_occurrence_index)`. Candidates list exact occurrences in the failing buffer; they are not certified to satisfy the failed selectors, and there is no automatic selection. When the failure follows earlier changes, `failure_detail` adds a sentence saying that selectors count the sequential buffer after that many simulated changes.
- `sequential_match_invalid` failures record `original_occurrence_count` and up to five `original_occurrences` in transaction-start coordinates, each with the `consumed_by_change_id`/`consumed_by_change_index` of the earlier change that overlapped it. `failure_detail` reads "MATCH text was consumed by earlier change <id> in this transaction." These rows store no `near_miss_query`, and their `near_misses` are omitted with `omission_reason: "sequential_match_consumed"`, because similar text in the edited buffer is unrelated to the consumed match.
- `match_absent` failures persist `diagnostic.near_miss_query`: the canonical query when its raw length is at most 64 code points, otherwise `omission_reason: "match_too_large"`, within 1,024 wrapper bytes.
- Response-only `near_misses` are computed only after a service-owned transaction has committed and released its lock. Caller-owned transactions return `omission_reason: "caller_transaction"`. A fresh rejection scans a bounded in-memory copy of the failing buffer, at most its first 65,536 code points, which is never persisted (`scan_source: "failing_buffer"`). Exact recovery scans only the stored failure context (`scan_source: "stored_failure_context"`), so recovered near misses can be narrower than the original response.
- Windows have the query length minus one, the query length and the query length plus one (positive lengths only). Distance is code-point Levenshtein, accepted when nonzero and at most `min(4, max(1, len(query) // 4))`. Candidates are chosen in `(distance, start, end)` order, skipping any window that overlaps one already chosen, so up to three candidates name up to three distinct locations. Each has absolute `start`/`end` in failing-buffer coordinates and 16 code points of context per side, within 8,192 wrapper bytes.
- Distances come from an exact Ukkonen-banded Landau–Vishkin diagonal-wave dynamic program (`band_radius = (threshold + 1) // 2`). An exact positional pigeonhole filter over disjoint needle pieces skips window starts that cannot hold a candidate within the threshold, so the ranking is identical to an unpruned search. `comparison_cells` counts banded cells evaluated (`max(1, min(len(query), reached_row)) * (2 * band_radius + 1)` per evaluated window start), with a 1,000,000-cell cap. Because the diagonal wave evaluates a window start as a unit before checking `comparison_cells + window_cells > 1_000_000`, at most one final window is evaluated and discarded when the cap is reached, while `comparison_cells` and `scanned_end` record only committed window starts (`comparison_cells <= 1_000_000`) and keep the exact ranking of the range scanned so far. Both varied prose (`1.7 ms` median, `585` cells vs. `100.2 ms` before — **58.9× faster**) and structured repetitive logs (`41.9 ms` median, `142,255` cells, `100%` scanned vs. `708.5 ms` truncated at `69%` before — **16.9× faster**) scan the full 65,536-code-point buffer in tens of milliseconds; only homogeneous inputs where every needle piece repeats across the buffer hit the cell cap early. `work_budget_exhausted` is returned only when not one window start could be evaluated; historical outcomes without stored inputs return `historical_context_unavailable`.
- `scanned_start`/`scanned_end` give the window-start range searched. `scope_truncated` is true when that range does not cover the whole failing buffer, and `candidates_truncated` when more distinct locations qualified than were returned; `truncated` is true when either is. An empty computed list includes a `hint` naming `patchdiff_find_occurrences`. Near misses never change the verdict. Unexpected post-commit errors propagate without claiming rollback. All newly added enrichment fields together are at most 18,432 bytes; this excludes preexisting arbitrary evidence.

### Request-key diagnostics

Reusing a `client_request_id` for a different proposal on the same target rejects with `failure_reason: "context_invalid"` at `PRECONDITION_GUARD` and `diagnostic.code: "request_key_conflict"`. The diagnostic adds `existing_pdcp_log_id`, `differing_components` (fingerprint envelope members that differ from the stored row: `protocol_version`, `pdcp_content_hash`, `expected_target_version`, `expected_current_hash`, `parent_pdcp_log_id`) and, for typed records, `differing_fields` (at most 10 record paths such as `edits[0].rationale`) with `differing_fields_truncated`. These comparisons are advisory; the fingerprint decides. A key with invalid syntax rejects with `context_invalid` and `diagnostic.code: "invalid_client_request_id"`. Recover an original outcome with the identical proposal and key, or inspect it with `patchdiff_get_pdcp_log(client_request_id=…)`.

### Line endings and export formats

Storage is canonical: every upload is normalized to LF before hashing, and `current_hash` is the SHA-256 of that LF text. `patchdiff_initialize_target` records the raw upload's line endings before normalization and returns them as `source_line_endings: {style, lf, crlf, cr, normalized, source_code_points, source_utf8_bytes, source_sha256}`. `style` is `none`, `lf`, `crlf`, `cr` or `mixed`; a CRLF pair counts once; `source_sha256` is the SHA-256 of the raw UTF-8 upload bytes, so a host can compare its local file without canonicalizing it. Targets created before migration `20261022_0003` return `source_line_endings: null` (unknown).

`patchdiff_export_target(format)` accepts exactly:

| `format` | Returned `content` |
| --- | --- |
| `original_text` (default) | Canonical LF text. Legacy alias of `canonical_lf`; it never meant original bytes. |
| `canonical_lf` | Canonical LF text. |
| `crlf` | Canonical text with every LF written as CRLF. |
| `original_eol` | Canonical text written in the recorded uniform style: `none`/`lf` → LF, `crlf` → CRLF, `cr` → CR. |

`original_eol` returns `invalid_argument` with `code: "original_eol_unrecoverable"` for a `mixed` upload, because per-line endings were never stored, and with `code: "source_line_endings_unknown"` for a target without recorded facts. Any other `format` returns `invalid_argument` with `code: "unsupported_export_format"` and `allowed_formats`. The export response adds `content_eol` and `content_sha256` (SHA-256 of the returned content's UTF-8 bytes); `hash` and `current_hash` remain the canonical hash. An unedited CRLF upload exported with `original_eol` has `content_sha256 == source_line_endings.source_sha256`. Line endings in edit payloads are canonicalized like everything else, so `original_eol` applies the recorded style to new lines too.

### Discovery, argument errors and examples

Advertised regular expressions use syntax accepted by RE2-based MCP hosts.
Strict end-of-string constraints combine `$` with a JSON Schema `not` constraint
against a trailing LF; nullable fields still accept null. This preserves the
runtime's exact identifier/hash domains without advertising unsupported lookahead.

`tools/list` gives every top-level parameter a one-line description (units, coordinate frame, guard semantics or cursor meaning). Submission tool descriptions repeat the guard rule in prose for hosts that drop `anyOf`. It advertises the tx/2 operation schema and, for both newer submission tools, `x-patchdiff-capabilities` derived from the runtime constants: protocol, immutable runtime and allowed operations, plus either coordinate, insertion and `span_context` support (`fields` and the `0.5.0` runtime) or size limits. It also publishes 13 schema-conforming `inputSchema.examples` across nine tools, deep-copied per result. The complete `{tools: [...]}` payload is at most 65,536 bytes and the complete examples map at most 8,192 bytes. Examples are illustrative arguments: hosts must bind real target IDs, guards, parents and cursors (see the host guide's discovery sequence). Every advertised example runs over real stdio and PostgreSQL in the test suite; this is API coverage, not a model-success or production-performance claim.

Tool results are JSON text in `content[0].text` with literal characters (not `\uXXXX` escapes), so after parsing the JSON-RPC envelope a host hands the model literal text. The JSON-RPC line itself is ASCII-escaped: it is pure ASCII on the wire, a host that decodes stdout with a locale code page cannot corrupt it, and U+2028, U+2029 or U+0085 in document text cannot split it. If the tool text cannot be encoded as strict UTF-8 (a lone surrogate), that one result falls back to ASCII escapes; parsed values are identical either way. A call with unknown or missing argument names never reaches the tool. It returns `isError: true` with a JSON payload `{status: "invalid_argument", code: "unknown_argument" | "missing_argument", tool, failure_detail, unknown_arguments?, missing_arguments?}`. Every other `invalid_argument` response has `status` and `failure_detail`, and adds `code` where a stable machine code exists.

---

## 1. Target Lifecycle Tools

### `patchdiff_initialize_target` / `patchdiff_handle_upload`
- **Arguments**:
  - `filename` (`string`, required): document filename.
  - `content` (`string`, required): initial document text; line endings are normalized to LF and recorded.
  - `content_type` (`string`, required): MIME type or language identifier (e.g. `"text/markdown"`).
  - `project_id` (`string | null`, optional): project UUID.
- **Returns** (live output for a one-line CRLF upload; hashes shortened):
  ```json
  {
    "status": "ok",
    "target_file_id": "UUID",
    "filename": "doc.md",
    "target_type": "text/markdown",
    "version": 0,
    "current_hash": "b22ebf77...",
    "active_editing_cycle_id": "UUID",
    "source_line_endings": {
      "style": "crlf",
      "lf": 0,
      "crlf": 1,
      "cr": 0,
      "normalized": true,
      "source_code_points": 18,
      "source_utf8_bytes": 18,
      "source_sha256": "0e66cb5c..."
    }
  }
  ```

### `patchdiff_get_target`
- **Arguments**: `target_file_id` (`string`, required).
- **Returns**: `status: "ok"`, `target_file_id`, `filename`, `target_type`, `current_content`, `current_hash`, `version`, `active_editing_cycle_id`, `source_line_endings`.

### `patchdiff_export_target`
- **Arguments**: `target_file_id` (`string`, required), `format` (`"original_text" | "canonical_lf" | "crlf" | "original_eol"`, default `"original_text"`). See [Line endings and export formats](#line-endings-and-export-formats).
- **Returns**: `status: "ok"`, `filename`, `content_type`, `target_type`, `content`, `version`, `hash`, `current_hash`, `format`, `content_eol`, `content_sha256`, `source_line_endings`.

---

## 2. Authoritative Reads & Search Tools

### `patchdiff_read_target`
Authoritative read of canonical target text by code-point offset, returning version, hash, and continuation tokens.
- **Arguments**:
  - `target_file_id` (`string`, required): target UUID.
  - `start` (`integer >= 0`, default `0`): code-point start offset.
  - `length` (`integer >= 1 | null`, optional): maximum code points to read (clamped to `1..8000`, default `4000`).
- **Returns**:
  ```json
  {
    "status": "ok",
    "target_file_id": "UUID",
    "version": 1,
    "current_hash": "sha256...",
    "start": 0,
    "end": 4000,
    "text": "...",
    "total_chars": 12500,
    "truncated": true,
    "next_start": 4000
  }
  ```

### `patchdiff_find_occurrences`
Lists exact occurrences of `text` (overlapping spans counted) with bounded context and pagination. Indexes describe the current target, which is the buffer the first edit of a transaction sees; later edits in the same transaction see renumbered occurrences.
- **Arguments**:
  - `target_file_id` (`string`, required).
  - `text` (`string`, required): exact string to locate.
  - `context_chars` (non-bool integer >= 0, default 40): context window before/after each match, clamped to 400. Negative, boolean, null, string and float values return invalid_argument.
  - `start_occurrence` (`integer >= 1`, default `1`): 1-based occurrence index to start from.
  - `max_results` (`integer >= 1`, default `200`): maximum occurrences to return.
- **Returns**:
  ```json
  {
    "status": "ok",
    "target_file_id": "UUID",
    "version": 1,
    "current_hash": "sha256...",
    "occurrence_count": 5,
    "returned_count": 2,
    "start_occurrence": 1,
    "occurrences": [
      {
        "occurrence_index": 1,
        "start": 120,
        "end": 134,
        "before": "...prefix...",
        "after": "...suffix..."
      }
    ],
    "truncated": true,
    "next_occurrence_index": 3
  }
  ```

---

## 3. Transaction Submission Tools

### `patchdiff_submit_edits` (Primary Typed Transaction)
Submits a structured edit proposal (`protocol_version = "patchdiff-tx/1"`). Validated deterministically and committed atomically under `SELECT ... FOR UPDATE`.
- **Arguments**:
  - `target_file_id` (`string`, required): target UUID.
  - `intent` (`string`, required): high-level summary of the transaction intent.
  - `edits` (`array`, required, `minItems: 1`): ordered list of edit blocks conforming to `TYPED_EDIT_JSON_SCHEMA`:
    - `match` (`string`, required non-empty): exact target text to match.
    - `replace` (`string`, required): replacement text (empty `""` denotes deletion).
    - `change_id` (`string | null`, optional): alphanumeric identifier (defaults to `chg_001`, `chg_002`, ...).
    - `rationale` (`string | null`, optional): per-edit explanation.
    - `risk` (`"low" | "medium" | "high" | null`, optional).
    - `occurrence_index` (`integer >= 1 | null`, optional): 1-based selector over exact occurrences in the buffer this edit sees, that is, after earlier edits in the same transaction. Indexes from `patchdiff_find_occurrences` or `exact_candidates` are valid only for the first edit, or for one edit per transaction. For several same-string edits, use tx/2 spans in descending order. Enforced even when only one match exists.
    - All supplied selectors must hold together. Excluding singleton selectors reject with disambiguation_invalid; anchors retain anywhere-before/after semantics. This applies to new typed and legacy submissions under runtime 0.2.2; older logs replay under their recorded behavior.
    - `anchor_before` (`string | null`, optional): substring that must occur anywhere before the match.
    - `anchor_after` (`string | null`, optional): substring that must occur anywhere after the match.
  - `expected_target_version` (`integer | null`, optional): target version guard.
  - `expected_current_hash` (`string | null`, optional): 64-hex SHA-256 target hash guard.
  - `client_request_id` (`string | null`, optional): 1..128 printable ASCII characters for request deduplication.
  - `parent_pdcp_log_id` (`string | null`, optional): UUID of rejected parent attempt when retrying.
  - `attempt` (`integer | null`, optional): retry attempt number (1-based).
  - `source` (`string`, default `"model_response"`).
  - `include_correlation_id` (`boolean`, default `false`).
- **Rule**: At least one of `expected_target_version` or `expected_current_hash` is **required**.

#### Accepted Response
Live output for `edits: [{"match": "alpha", "replace": "gamma", "occurrence_index": 2}]` on `alpha beta alpha`; hashes shortened.
```json
{
  "status": "accepted",
  "target_file_id": "UUID",
  "before_hash": "b22ebf77...",
  "after_hash": "adf7157c...",
  "version": 1,
  "current_version": 1,
  "current_hash": "adf7157c...",
  "pdcp_log_id": "UUID",
  "manifest_entries_added": 1,
  "warnings": [],
  "warning_details": [],
  "warning_count": 0,
  "warnings_truncated": false,
  "validity": {
    "protocol_valid": true,
    "transaction_valid": true,
    "task_correct": "not_evaluated",
    "semantic": "not_evaluated"
  },
  "evidence": {
    "changes": [
      {
        "change_id": "chg_001",
        "change_index": 1,
        "span_start": 11,
        "span_end": 16,
        "matched_chars": 5,
        "replacement_chars": 5,
        "matched_sha256": "8ed3f6ad...",
        "replacement_sha256": "be9d587d..."
      }
    ]
  },
  "deduplicated": false,
  "client_request_id": "req-002"
}
```

Span and replacement facts also carry `operation` (`"span"` or `"replace_all"`).

#### Rejected Response
Live output for an unselected `alpha` on the same target; hashes and the repeated context are shortened.
```json
{
  "status": "rejected",
  "target_file_id": "UUID",
  "failure_reason": "match_ambiguous",
  "failure_detail": "MATCH text appears multiple times without disambiguation.",
  "failed_change_id": "chg_001",
  "before_hash": "b22ebf77...",
  "after_hash": null,
  "current_version": 0,
  "current_hash": "b22ebf77...",
  "pdcp_log_id": "UUID",
  "diagnostic": {
    "format": "patchdiff-tx/1",
    "occurrence_count": 2,
    "exact_candidates": {
      "kind": "exact_occurrences",
      "occurrence_count": 2,
      "returned_count": 2,
      "candidates": [
        {"occurrence_index": 1, "start": 0, "end": 5, "before": "", "match_preview": "alpha",
         "match_truncated": false, "after": " beta alpha\n"},
        {"occurrence_index": 2, "start": 11, "end": 16, "before": "alpha beta ", "match_preview": "alpha",
         "match_truncated": false, "after": "\n"}
      ],
      "truncated": false,
      "next_occurrence_index": null,
      "buffer_stage": "canonical_target",
      "prior_changes": 0,
      "observed_target_version": 0,
      "observed_target_hash": "b22ebf77..."
    },
    "retryable": true,
    "requires_new_submission": true,
    "validation_stage": "transaction_applicability",
    "failure_context": {
      "available": true, "unavailable_reason": null, "selection": "prefix",
      "buffer_stage": "canonical_target", "prior_changes": 0, "start": 0, "end": 17,
      "total_chars": 17, "text": "alpha beta alpha\n", "truncated": false,
      "observed_target_version": 0, "observed_target_hash": "b22ebf77..."
    }
  },
  "current_context": {
    "available": false, "unavailable_reason": "same_as_failure_context", "selection": null,
    "buffer_stage": null, "prior_changes": null, "start": null, "end": null, "total_chars": null,
    "text": null, "truncated": null, "observed_target_version": null, "observed_target_hash": null
  },
  "validity": {
    "protocol_valid": true,
    "transaction_valid": false,
    "task_correct": "not_evaluated",
    "semantic": "not_evaluated"
  },
  "deduplicated": false,
  "client_request_id": "req-001"
}
```

### `patchdiff_submit_pdcp` (Frozen Legacy Input)
Retained for backward compatibility with frozen `.pdcp` v0.2.3 text transactions. New integrations should use `patchdiff_submit_edits` (`patchdiff-tx/1`), `patchdiff_submit_operations` (`patchdiff-tx/2`), or `patchdiff_submit_replacement` (`patchdiff-tx/3`). See [LEGACY_COMPATIBILITY.md](../legacy/LEGACY_COMPATIBILITY.md#2-legacy-mcp-submission-tool-patchdiff_submit_pdcp) for arguments and legacy format details.

---

## 4. Checkpoint, Replay & Bounded Audit Tools

### `patchdiff_save`
Creates a `TargetSnapshots` row (`snapshot_reason = "save_checkpoint"`), closes the active cycle, and opens a new cycle. Does not mutate target text.
- **Arguments**: `target_file_id`, optional `expected_target_version` (non-negative integer), optional `expected_current_hash`, optional `export_after_save` (`boolean`). Both guards are checked when supplied; prefer the version guard, which detects ABA changes that a hash cannot.
- **Returns**: `status: "saved"`, `target_file_id`, `snapshot_id`, `closed_editing_cycle_id`, `new_editing_cycle_id`, `current_hash`, `version`. A stale version returns `status: "rejected"` with `failure_reason: "target_version_mismatch"`, a stale hash `target_hash_mismatch`, and an invalid version `context_invalid`; none writes a snapshot. `export_after_save` adds a default-format `export`.

### `patchdiff_replay`
Replays accepted logs against the initial snapshot, dispatching on `(protocol_version, runtime_version)`. A successful reconstruction may still report materialized_state_matches=false. content_matches compares raw stored content with the canonical reconstructed buffer; canonical hash checks retain their existing meaning. Replay reports divergence and never repairs storage. Replay never evaluates warnings, diagnostics or line-ending metadata.
- **Arguments**: `target_file_id`.
- **Returns**:
  ```json
  {
    "status": "success",
    "target_file_id": "UUID",
    "reconstructed_hash": "sha256...",
    "current_hash": "sha256...",
    "reconstructed_version": 2,
    "current_version": 2,
    "accepted_transactions_replayed": 2,
    "materialized_state_matches": true,
    "materialized_state_checks": {
      "content_matches": true,
      "stored_hash_matches": true,
      "recomputed_hash_matches": true,
      "version_matches": true
    }
  }
  ```

### `patchdiff_finalize_target`
Atomically executes SAVE checkpointing, deterministic replay verification, and format export in a single PostgreSQL session and transaction under `SELECT ... FOR UPDATE` row locking. Available on the `full` profile.
- **Arguments**:
  - `target_file_id` (`string`, required): UUID of the canonical target.
  - `expected_target_version` (`integer`, optional): Expected current target version.
  - `expected_current_hash` (`string`, optional): Expected SHA-256 hash.
  - `format` (`string`, optional, default `"original_eol"`): Output line-ending format (`"original_eol"`, `"canonical_lf"`, `"crlf"`, `"original_text"`).
  - `client_request_id` (`string`, optional): Client invocation correlation ID.
- **Database Atomicity**: If replay verification fails (`materialized_state_matches is not True`), the entire database transaction rolls back, leaving zero snapshots created and zero editing cycle mutations.
- **Returns**:
  ```json
  {
    "status": "ok",
    "target_file_id": "UUID",
    "filename": "main.py",
    "version": 2,
    "current_hash": "sha256...",
    "snapshot_id": "UUID",
    "closed_editing_cycle_id": "UUID",
    "new_editing_cycle_id": "UUID",
    "materialized_state_matches": true,
    "materialized_state_checks": {
      "content_matches": true,
      "stored_hash_matches": true,
      "recomputed_hash_matches": true,
      "version_matches": true
    },
    "exported_content": "...",
    "content_sha256": "sha256...",
    "format": "original_eol",
    "source_line_endings": "crlf"
  }
  ```

### `patchdiff_get_pdcp_log`
Returns a bounded, newest-first page of append-only attempts (accepted and rejected).
- **Arguments**:
  - `target_file_id` (`string`, required).
  - `limit` (positive non-bool integer or null, default 50): omitted/null selects 50; values above 200 clamp to 200.
  - `before_sequence` (`integer >= 1 | null`, optional): exclusive positive non-bool integer continuation token.
  - `status` (`"accepted" | "rejected" | null`, optional).
  - `content_hash` (`string | null`, optional): filter by `pdcp_content_hash`.
  - `client_request_id` (`string | null`, optional): exact safe-string lookup, including already-persisted legacy IDs; this filter does not impose new-submission key syntax.
  - `include_content` (`boolean`, default `false`).
- **Returns**: `entries[]` containing sequence, hashes, versions, failure reason/detail, lineage (`parent_pdcp_log_id`, `regeneration_attempt` and its alias `attempt`), `client_request_id`, `request_fingerprint`, `diagnostic` (warnings on accepted rows that have them), `intent` (the typed record's transaction intent, at most 256 code points, with `intent_truncated`; null for legacy PDCP) and timestamps. Also returns has_more and next_sequence. Fetch limit+1 after all filters; next_sequence is the smallest returned log_sequence when another page exists, otherwise null. Empty/not-found/invalid responses have entries=[], has_more=false, next_sequence=null. Unknown targets return not_found; invalid argument types return invalid_argument.
- **Content budget**: with `include_content: true`, returned `pdcp_content` is limited to 1,048,576 UTF-8 bytes per page. The first entry with content is always returned whole, so `limit: 1` fetches any row. Later entries over budget return `pdcp_content: null` with `pdcp_content_omitted: "page_byte_budget"`; fetch them with `limit: 1` and `before_sequence` set to one above their `log_sequence`.

### `patchdiff_get_manifest_ledger`
Returns bounded, oldest-first accepted manifest ledger entries within the newest page.
- **Arguments**:
  - `target_file_id` (`string`, required): target UUID.
  - `include_previous_cycles` (`boolean`, optional, default `false`): include entries from editing cycles closed by `patchdiff_save`. After a SAVE, the default call returns only the new, possibly empty, active cycle.
  - `limit` (positive non-bool integer or null, optional): default 50, cap 200. Omitted/null selects 50; zero/negative/boolean/float/string values return invalid_argument.
  - `before_sequence` (`integer >= 1 | null`, optional): exclusive upper bound on `ledger_sequence` for paging backward.
- **Returns** (live output; hashes and timestamps shortened):
  ```json
  {
    "entries": [
      {
        "ledger_sequence": 626,
        "pdcp_log_id": "UUID",
        "log_sequence": 827,
        "before_version": 0,
        "after_version": 1,
        "editing_cycle_id": "UUID",
        "change_index": 1,
        "change_id": "chg_001",
        "intent": "Rename alpha",
        "transaction_intent": "Rename alpha",
        "rationale": null,
        "input_state": null,
        "output_state": null,
        "affected_region": null,
        "user_visible_change": null,
        "risk": null,
        "origin": "typed",
        "derived": {
          "change_id": "chg_001",
          "change_index": 1,
          "span_start": 11,
          "span_end": 16,
          "matched_chars": 5,
          "replacement_chars": 5,
          "matched_sha256": "8ed3f6ad...",
          "replacement_sha256": "be9d587d..."
        },
        "created_at": "2026-10-22T23:28:20Z"
      }
    ],
    "has_more": false,
    "next_sequence": null
  }
  ```
- **Joining**: `pdcp_log_id` and `log_sequence` join a ledger row to its attempt. For typed rows, `intent` keeps its stored meaning (the edit's rationale when present, otherwise the transaction intent), while `transaction_intent` and `rationale` are extracted in PostgreSQL 16+ (`pg_input_is_valid`) `LATERAL` SQL from the stored `patchdiff-tx/1` or `patchdiff-tx/2` record without transferring or decoding full `pdcp_content` payloads in Python (for `patchdiff-tx/3` whole-document replacements, `transaction_intent` comes directly from `intent` and `rationale` is null without touching `pdcp_content`; `patchdiff_get_pdcp_log` similarly extracts bounded `intent` via guarded 4 KB head/tail slice fast paths on `> 64 KB` records with `? 'intent'` fallback). Legacy PDCP rows and `patchdiff-invalid-input/1` evidence envelopes return null for both. `log_sequence` and `ledger_sequence` are global across targets, so one target's sequences have gaps.
- **Ordering and cursor example**: For sequences 1..10 with limit 3, attempts return [10,9,8], ledger [8,9,10], both next_sequence=8. A ledger call with before_sequence=8 returns [5,6,7]. Both cursors are exclusive; ledger reverses only the selected newest page for display. Newer inserted rows are excluded from continuation below a previous cursor. Both history tools return the same empty continuation fields; include flags must be boolean.
- **Caller Note**: Traversal must restart if `patchdiff_save` rotates the active editing cycle during an active-cycle-only traversal. Callers migrating from the legacy unbounded behavior must page via `before_sequence`.

---

## 5. Convenience & Deprecated Compatibility Wrappers

`patchdiff_build_prompt_context` and the deprecated server-mediated regeneration wrappers (`patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`) are retained solely for backward compatibility. Modern hosts use `patchdiff_read_target`, `patchdiff_read_lines`, `patchdiff_find_occurrences`, and host-owned retries via `patchdiff_submit_edits(..., parent_pdcp_log_id=...)`. See [LEGACY_COMPATIBILITY.md](../legacy/LEGACY_COMPATIBILITY.md#3-deprecated-regeneration-prompt-prefix-wrappers) for legacy wrapper specifications.


---

## Structural Observation and Scoped Submission (`waymark-engine@4.1.0`)

### `patchdiff_observe_scope`

The public `tools/list` schemas include task-independent examples for filtered
candidate discovery, direct single selection, batch selection, observation paging,
and separate single/batch submissions. Bind illustrative IDs, both guards and
returned cursors to actual receipts. Candidate discovery issues no observation;
known exact identities can be selected directly. Preserve returned Markdown names
including punctuation; ambiguous identities reject. Exact match strings can
include literal newlines. `find_occurrences` indexes the whole current target;
batch groups instead count overlapping matches from one inside their own
scope-local sequential buffer after earlier operations. A preceding catalog is
not mandatory, and single/batch fields cannot be mixed.

Discover structural symbol candidates or select a unique symbol scope in the authoritative PostgreSQL target snapshot using the pinned `waymark-engine@4.1.0` package.

Bundle mode additionally accepts `selections: [{symbol_name, kind?}, ...]`
(1–32 exact, unique, nonempty, disjoint scopes), exclusive with single selectors,
query, observation ID, top-level kind and nonzero offset. One target snapshot and
one Waymark pass serve all selections; no partial issuance occurs.
`status: "observed_batch"` returns a bundle ID, both target guards, engine/language,
and ordered scope receipts. Total scope contents cap at 65,536 code points;
initial text totals cap at 32,768 (`BUNDLE_RESPONSE_TOO_LARGE`), with existing
per-scope default 4,000 / max 8,000 pages and ID pagination. Selection failures
identify `selection_index`. [Exact fields and lifecycle](STRUCTURAL_BATCH_EDITING.md#observation-contract).

- **Arguments**:
  - `target_file_id` (UUID string, required)
  - `query` (string | null, optional): case-insensitive substring filter for candidate discovery when `symbol_name` is omitted.
  - `symbol_name` (string | null, optional): exact Waymark symbol name (or `parent.name`) to select uniquely and issue a server-persisted `observation_id`.
  - `kind` (string | null, optional): Waymark symbol kind filter (`function`, `class`, `method`, `variable`, `config_item`, `object`, `section`, `table_row`, `code_block`, etc.).
  - `observation_id` (UUID string | null, optional): existing server-issued observation UUID for paginating a large observed scope (`mode: "scope_page"`).
  - `offset` (`integer >= 0`, default `0`): code-point offset within `[scope_start, scope_end)`.
  - `max_chars` (`integer >= 1 | null`, default `4000`, cap `8000`): maximum code points returned on the page.
  - `include_line_starts` (`boolean`, default `false`): include 1-based line start offsets within the returned page.
The optional top-level `query`, `symbol_name` and `kind` values must be nonblank
when supplied. Omission/null means that selector or filter is absent; omitting
`query` removes only the query filter. Discovery advertises `minLength: 1` to
reject empty strings; the service also rejects whitespace-only strings, including
Unicode whitespace. Nonblank strings are not implicitly trimmed.

- **Modes & Fail-Closed Guarantees**:
  - **Candidate discovery** (`symbol_name` omitted): returns `status: "candidates"`, `observation_id: null`, and bounded structural candidates.
  - **Exact selection** (`symbol_name` provided):
    - `0` matches -> `status: "not_found"`, `code: "SCOPE_NOT_FOUND"`, `observation_id: null`.
    - `> 1` matches -> `status: "ambiguous"`, `code: "AMBIGUOUS_SCOPE_SELECTION"`, `observation_id: null`, at most 200 matching candidates, `total_candidates` and `candidates_truncated` (never silently picks the smallest span).
    - `1` match -> persists a `target_scope_observations` row and returns `status: "observed"`, `observation_id`, `target_version`, `target_current_hash`, `scope_start`, `scope_end`, `observed_scope_hash`, and bounded canonical slice `text`.

### `patchdiff_submit_observed_operations`
Submit guarded `patchdiff-tx/2` `match`/`span` operations restricted to a server-issued `observation_id`.

Alternatively submit one atomic batch with `observation_bundle_id`, `groups`,
`intent`, **both** target guards and mandatory `client_request_id`. Each group
contains exactly one unique bundle `observation_id` and nonempty tx/2 `operations`;
allow 1–32 groups, at most 128 operations total, and nonempty bundle subsets.
Single and batch forms are mutually exclusive. Batch spans and match selectors
use each group's own **scope-local sequential buffer**; single form spans remain
absolute. One Waymark pass re-verifies all participating scopes under the target
lock. A failed batch consumes no receipts and adds no accepted ledger rows.
Success assembles descending original spans, writes one accepted log and advances
version once, returning before/after versions, bundle ID, group/change counts and
bounded group summaries. Key recovery precedes stale guards; changed bodies
conflict through the existing audited mechanism.

The internal durable pair is `patchdiff-observed-batch/1` /
`patchdiff-observed-batch-r1`; replay requires every exact authoritative link,
scope hash, bundle and ordered group mapping without invoking Waymark. Migration
0005 preserves historical single linkage via a partial unique index.
[Batch errors, replay and executable examples](STRUCTURAL_BATCH_EDITING.md).

- **Arguments**:
  - `target_file_id` (UUID string, required)
  - `observation_id` (UUID string, required): server-issued observation UUID from `patchdiff_observe_scope`.
  - `intent` (non-whitespace string, required)
  - `operations` (non-empty array of `match` / `span` operations, required)
  - `expected_target_version` (`integer >= 0`, required)
  - `expected_current_hash` (64-char lowercase hex SHA-256, required)
  - `source`, `parent_pdcp_log_id`, `attempt`, `client_request_id`, `include_correlation_id` (optional)
- **Locked Admission Guarantees**:
  - Acquires `SELECT ... FOR UPDATE` on `cloud_target_files` and `target_scope_observations`.
  - Rejects and logs in `append_only_pdcp_logs` any missing (`OBSERVATION_REQUIRED`), malformed (`INVALID_OBSERVATION_ID`), unknown (`UNKNOWN_OBSERVATION_ID`), cross-target (`OBSERVATION_TARGET_MISMATCH`), closed-cycle (`OBSERVATION_CYCLE_MISMATCH`), already-consumed (`OBSERVATION_ALREADY_CONSUMED`), or stale (`STALE_OBSERVATION_VERSION`, `STALE_OBSERVATION_HASH`) observation.
  - Nonempty `span` and `match` edits must remain within `[scope_start, scope_end)`; a full-scope replacement is allowed. The running scope end adjusts after each sequential operation.
  - Zero-width insertions (`start == end`, `expected_text: ""`) require `scope_start < start < scope_end`. Both boundaries reject, including with otherwise matching guards. Both nonempty `expected_before` and `expected_after` are mandatory, must match immediately adjacent text, and must lie entirely within the current sequential scope. Missing guards reject with `span_expected_text_mismatch` / `OBSERVED_INSERTION_GUARDS_REQUIRED`; mismatching guards reject with `span_expected_text_mismatch`. Out-of-scope spans, boundary insertions and guards crossing the scope reject with `span_out_of_bounds` / `OPERATION_OUTSIDE_OBSERVED_SCOPE`. Every rejection is atomic and audited. Unobserved historical insertion behavior is unchanged.
  - Observation pagination rejects a closed cycle after SAVE with `OBSERVATION_CYCLE_MISMATCH`, even when content, hash and version are unchanged.
  - Replay of an accepted log carrying `observation_id` requires exactly one matching authoritative observation row. Identity, accepted-log linkage, target, editing cycle, preimage version/hash, recorded scope bounds and scope hash must match the replay buffer; missing or altered evidence fails with `replay_protocol_invalid`. Diagnostic offsets never replace a missing row. Genuinely unobserved history retains its existing path.
  - When `PATCHDIFF_STRICT_OBSERVATION_MODE=1` is enabled, all unobserved write tools (`patchdiff_submit_edits`, `patchdiff_submit_operations`, `patchdiff_submit_replacement`, `patchdiff_submit_pdcp`, `patchdiff_request_regeneration`) are rejected and logged with `code: "OBSERVATION_REQUIRED"`.
## External response representations

`PATCHDIFF_MCP_RESPONSE_MODE` is frozen at external-adapter startup. Unset or
`detailed` preserves existing result bodies and serialization; `compact` is an
opt-in presentation contract. Unknown values prevent startup. Trusted embeddings
can pass response_mode to ExternalMCPAdapter. A request cannot change the mode.
The mode is independent of profile and does not change tools/list names, callable
tools, input schemas, request identity, audit, runtime/replay profiles or guards.

Only these successful result shapes are projected:

| Tool/status | Compact projection |
| --- | --- |
| patchdiff_submit_observed_operations / accepted | Omit evidence and groups if present; retain every other field, including warnings, warning_details, warning_count, warnings_truncated, validity, all identities/guards/aliases, counts and deduplicated. |
| patchdiff_observe_scope / candidates | Preserve envelope/count/order/truncation; entries retain name, kind, parent, start_line, end_line. |
| patchdiff_observe_scope / observed_batch | Preserve envelope/scopes; omit each scope's start, end, max_chars, next_start, start_line and end_line. Keep original bounds/length/hash, observation/ordinal/symbol, exact text, offset, truncated, next_offset and requested absolute line_starts. |

Projected results include `presentation: {mode: "compact", omitted: [...]}`.
Omission names are evidence, groups, candidate_details, duplicate_page_metadata;
only actual omissions are listed. Compact JSON uses no optional separator spaces
and retains existing Unicode safety. Single observed selections/pages, every
failure/diagnostic and unrelated tools keep their existing representation.
Mode-specific tool descriptions announce compact presentation.

Exact request recovery uses the receiving session's representation of the same
stored outcome; the request fingerprint never includes response mode. Full facts
remain in the detailed representation and append-only persistence, retrievable by
a separate trusted detailed/full operator. Compact mode does not guarantee that
arbitrary source-rich responses fit a host's spill limit. Use existing query/kind,
direct selection and observation pagination; never silently truncate source.

## Versioned editor profile

The opt-in `observed_v2` external profile exposes five purpose-specific tools through the existing services (`patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, and `patchdiff_commit_bundle`). Its exact tool list, snapshot envelope, bounded receipts, negotiated MCP revisions and error semantics are specified in [MCP_EDITOR_V2.md](MCP_EDITOR_V2.md). All legacy profiles and internal 22 handlers retain their contracts.
