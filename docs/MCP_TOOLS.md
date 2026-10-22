# MCP_TOOLS.md

Unicode boundary: edit-submission strings and metadata must be valid UTF-8/PostgreSQL text. Known-target invalid text returns an audited target_encoding_invalid / PROTOCOL_VALIDATION rejection. Existing pdcp_content TEXT carries reversible ASCII-escaped patchdiff-invalid-input/1 evidence; JSONB holds only safe diagnostics. Read/search string errors return invalid_argument with no edit-attempt row. Valid inputs and discovery operation shapes are unchanged.

Conflicting-key submissions return context_invalid plus a fresh durable rejection log ID. The rejected row uses a NULL key and submitted fingerprint, with original-log linkage and a bounded submitted-key preview. The response continues to echo the submitted key. Exact recovery of the original request remains deduplicated:true without a new row; repeated conflicts each append an immutable attempt.


## Purpose

This document defines the complete MCP tool surface for PatchDIFF.

PatchDIFF is exposed over stdio JSON-RPC (`backend/app/mcp/external_adapter.py`) and an internal Python registry (`backend/app/mcp/server.py`). All tools route through the deterministic service layer (`backend/app/services/`) and execute per-target atomic commits against Postgres.

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built record: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

## MCP Tool Surface Overview

The 20 registered MCP tools are organized into five functional groups:

| Group | Tool Name | Role & Modernized Status |
| --- | --- | --- |
| **1. Target Lifecycle** | `patchdiff_initialize_target` | Initialize canonical target state, active cycle, and initial snapshot in Postgres. |
| | `patchdiff_handle_upload` | Upload alias for `patchdiff_initialize_target`. |
| | `patchdiff_get_target` | Retrieve canonical metadata, current content, hash, and version. |
| | `patchdiff_export_target` | Export canonical target text and metadata for external use. |
| **2. Authoritative Reads & Search** | `patchdiff_read_target` | Authoritative bounded read of target slices by code-point offset with `next_start` continuation. |
| | `patchdiff_read_lines` | Bounded inclusive LF line ranges with range-relative continuation; default 4,000/cap 8,000 code points. |
| | `patchdiff_find_occurrences` | Enumerate exact occurrences (overlapping counted) with bounded context and pagination. |
| **3. Transaction Submission** | `patchdiff_submit_edits` | **Primary typed input** (`patchdiff-tx/1`). Structured `edits[]`, required guards, `client_request_id` idempotency. |
| | `patchdiff_submit_operations` | Guarded `patchdiff-tx/2` ordered match/span operations with required exact expected text on spans; profile 0.3.0. |
| | `patchdiff_submit_replacement` | Guarded sole whole-target replacement (`patchdiff-tx/3`), immutable profile 0.4.0. |
| | `patchdiff_preview` | Read-only advisory evaluation of an explicit transaction format with bounded evidence; submission rechecks. |
| | `patchdiff_submit_pdcp` | **Frozen legacy input** (`0.2.3`). Raw `.pdcp` text with 7 required manifest fields. |
| **4. Checkpoint, Replay & Audit** | `patchdiff_save` | Snapshot current target and rotate editing cycle without target mutation. |
| | `patchdiff_replay` | Deterministically reconstruct target from initial snapshot + accepted logs, reporting component checks. |
| | `patchdiff_get_pdcp_log` | Bounded newest-first page of append-only attempts (accepted/rejected), filtering by status, hash, or request ID. |
| | `patchdiff_get_manifest_ledger` | Retrieve accepted-only manifest ledger entries with `origin` and `derived` facts. |
| **5. Convenience & Deprecated** | `patchdiff_build_prompt_context` | Convenience bounded target prefix (`context_truncated`). |
| | `patchdiff_get_regeneration_context` | **Deprecated** compatibility wrapper. |
| | `patchdiff_build_regeneration_prompt` | **Deprecated** compatibility wrapper. |
| | `patchdiff_request_regeneration` | **Deprecated** compatibility wrapper. |

---

## Guarded editing, reads, preview and diagnostics

This section is the normative contract for guarded operations (`patchdiff-tx/2`), sole replacement (`patchdiff-tx/3`), line reads, preview, response options and bounded rejection evidence. Other documents summarize it and link here. Recorded decisions: [F01](usability/F01-decision.md), [Pass A](usability/PASS-A-decision.md) and [Pass B](usability/PASS-B-decision.md).

Byte budgets below count compact ASCII-escaped JSON (`ensure_ascii=True`, `separators=(",", ":")`) and exclude the JSON-RPC envelope. Offsets and counts are Unicode code points, not UTF-8 bytes or UTF-16 units.

### `patchdiff_submit_operations` (`patchdiff-tx/2`)

`patchdiff_submit_operations(target_file_id, intent, operations, expected_target_version=null, expected_current_hash=null, source="model_response", parent_pdcp_log_id=null, attempt=null, client_request_id=null, include_correlation_id=false)` uses the same guard, lineage, audited rejection, acceptance, ledger and recovery response contract as typed edits. At least one guard is required, and every supplied guard is checked. Missing or invalid guard syntax follows the existing `PROTOCOL_VALIDATION` path; stale valid guards reject at `PRECONDITION_GUARD`.

Each operation is one of:

- Match: `{op: "match", match, replace, change_id?, rationale?, risk?, occurrence_index?, anchor_before?, anchor_after?}`, with the unchanged exact-match selector rules.
- Span: `{op: "span", start, end, expected_text, replace, change_id?, rationale?, risk?}`. `start` and `end` are non-bool integers in `0..2^63-1`, `end` is exclusive and `end >= start`. Selectors and unknown fields reject. Coordinates refer to the sequential canonical buffer, that is, the text after earlier operations in the same transaction. The canonical `expected_text` must equal that span exactly; newlines in `expected_text` and `replace` are canonicalized before application. Explicit insertion uses `start == end` with an empty `expected_text`.

Mixed match/span transactions are atomic. Span applicability failures are `span_out_of_bounds` and `span_expected_text_mismatch`; either rejects the whole transaction with no partial facts or ledger rows. New records use immutable runtime `patchdiff-mvp-0.3.0`, which enables spans but not `replace_all`. Typed-match and legacy records keep `patchdiff-mvp-0.2.2` with unchanged records, fingerprints and profiles. Replay refuses unsupported profile/operation pairs. Span facts add `operation: "span"` to the existing runtime-derived spans, counts and hashes, and the ledger `origin` stays `typed`. No migration is required.

### `patchdiff_submit_replacement` (`patchdiff-tx/3`)

`patchdiff_submit_replacement(target_file_id, intent, replacement, expected_target_version?, expected_current_hash?, source="model_response", parent_pdcp_log_id?, attempt?, client_request_id?, include_correlation_id=false)` records exactly one guarded `replace_all` through the existing locked pipeline under immutable runtime `patchdiff-mvp-0.4.0`; tx/2 and `0.3.0` are unchanged. At least one guard is required, every supplied guard is checked, and the tool returns the normal submission response. An empty replacement is valid. One typed ledger row records the full original span with `operation: "replace_all"`.

Fresh admission limits apply to the raw replacement and to its canonical result: at most 1,000,000 code points and at most 1,048,576 UTF-8 bytes each, inclusive, checked in the order raw code points, raw bytes, canonical code points, canonical bytes. A valid oversized fresh replacement returns `status: "invalid_argument"`, `pdcp_log_id: null`, `diagnostic.code: "replacement_too_large"` and a `limit_exceeded` domain; no attempt or current-PDCP row is written.

Ordering: invalid text is classified first, through the audited Unicode path. An existing `client_request_id` is then recovered (same fingerprint) or audited as a conflict (different fingerprint) before fresh admission runs. A conflict audit row therefore stores the complete submitted record even when it exceeds the fresh limits, as every tx/1 and tx/2 attempt does; the limits bound what can be admitted as a new replacement, not the size of audit evidence. Replay never applies admission limits.

### `patchdiff_read_lines`

`patchdiff_read_lines(target_file_id, start_line=1, end_line=null, offset=0, max_chars=null)` returns `status: "ok"`, `target_file_id`, `version`, `current_hash`, `total_chars`, `total_lines`, the selected `start_line`/`end_line`, absolute `range_start`/`range_end`, page `start`/`end`, exact `text`, `truncated` and range-relative `next_offset`.

- Lines are one-based and LF-only. `end_line` is inclusive (default: last line), and each line includes its trailing LF. A trailing LF creates a final empty line; an empty target has one empty line.
- Page and range ends are exclusive code-point offsets. Omitted or null `max_chars` defaults to 4,000; larger values cap at 8,000. An `offset` equal to the range length returns an empty final page.
- Booleans, non-integers, non-positive line numbers or sizes, a negative offset and out-of-range coordinates return `invalid_argument`; an unknown target returns `not_found`.
- The read is one ordinary column observation under `no_autoflush`. It never flushes, refreshes or edits local ORM state and never normalizes corrupt storage. Each continuation page is a new observation and can see a newer version.

### `patchdiff_preview`

`patchdiff_preview(target_file_id, format, expected_target_version?, expected_current_hash?, <proposal>)` evaluates a fresh proposal with the same read-only guard/decode/apply evaluator as submission, from one coherent observation. Format `0.2.3` uses only `pdcp_content`; `patchdiff-tx/1` uses `intent` and `edits`; `patchdiff-tx/2` uses `intent` and `operations`; `patchdiff-tx/3` uses `intent` and `replacement`. Fields that belong to another format reject even when explicitly null. Typed formats require a guard. There is no request key, lineage, audit or correlation option.

Preview writes no row, takes no lock, and never commits or rolls back. It returns `preview: true`, `advisory: true`, status, stage and validity, plus `current_version`/`current_hash` and `before_version`/`before_hash` from the same observation. Accepted previews include `after_hash` and `change_facts`; rejected previews include bounded original diagnostics and never partial facts. Pending local ORM changes to the target return unavailable context without flushing. A valid oversized replacement receives the same no-attempt `replacement_too_large` classification as submission. Preview never computes near misses and never reflects a historical keyed outcome. Submission always re-locks and rechecks guards; prefer a version guard, because a hash alone cannot detect intervening no-op or ABA changes.

Preview evidence is bounded:

- The complete returned payload is at most 32,768 bytes.
- Accepted evidence is a prefix of at most 32 whole facts, each at most 2,048 bytes, and at most 16,384 bytes including the `change_facts` wrapper. `total_change_count`, `returned_fact_count`, `change_facts_truncated`, `change_facts_omission_reason` and `evidence_omissions` report what was omitted.
- Each textual evidence field is at most 1,024 code points and 8,192 wrapper bytes. An oversized failed-change ID or invalid-target echo is omitted as null, never shortened into a different identity.
- The diagnostic wrapper is at most 16,384 bytes. When it is exceeded, bounded `failure_context` is kept if it fits and other evidence is omitted with an explicit reason.
- If the complete payload still exceeds its cap, diagnostic evidence, `failure_detail`, `failed_change_id`, an invalid-target echo and `current_context` are omitted in that order, then trailing whole accepted facts are dropped. Each omission is recorded.

Verdict, stage, validity, a valid target UUID, observed version/hash and accepted `after_hash` are always retained. Preview never returns full proposed target text. This projection does not change full submission or recovery facts or stored diagnostics.

### Response option: `include_correlation_id`

All submission tools accept `include_correlation_id` (boolean, default `false`). When `true`, each invocation, including exact recovery, returns a fresh UUIDv4 `correlation_id`. It is never stored and never enters request keys or fingerprints. A non-boolean value returns `invalid_argument` before admission, with no attempt row.

### Bounded rejection context

A new rejection carries immutable `diagnostic.failure_context` and top-level, response-only `current_context`. Each available object has `available: true`, `unavailable_reason: null`, `selection: "prefix"`, `buffer_stage: "canonical_target" | "intermediate_buffer"`, `prior_changes`, `start: 0`, end-exclusive `end`, `total_chars`, `text`, `truncated`, `observed_target_version` and `observed_target_hash`.

- The observed identity names canonical target state at transaction start. First-change, service, precondition, protocol and lineage errors use canonical context (`prior_changes: 0`). Later application errors use the actual intermediate buffer and count the edits already simulated; those edits were not committed, so never apply intermediate offsets to committed content. `current_context` always describes the refreshed, locked canonical target.
- Each context is the longest prefix of at most 256 code points that fits the byte budgets, with `end = len(text)` and `truncated = end < total_chars`. Each complete context is at most 4,096 bytes, and the combined `{failure_context, current_context}` enrichment, wrapper keys included, is at most 8,192 bytes. Normal SHA-256 identities keep the full `min(256, total_chars)` prefix; a corrupted non-ASCII stored hash can shorten the prefix but never the identity. Context contains no proposer strings or duplicated failed-change ID, and does not claim to locate the failed span.
- Unavailable objects have `available: false`, `unavailable_reason: "invalid_target_id" | "target_not_found" | "unlocked_local_state"`, and null for every other field. An available empty target has empty text, zero offsets and `truncated: false`. Dirty local ORM state is unavailable even when compatibility version/hash fields expose local values.
- Exact keyed recovery returns the original stored diagnostic unchanged and captures a fresh `current_context`; older rows without failure context are not retrofitted. Accepted responses carry no context. Context capture never commits caller-owned transactions or releases their locks, so their observed state can remain provisional until the caller commits. Use reads, search and a new linked proposal to correct a rejection.

### Exact candidates and near misses

- `match_ambiguous` and `disambiguation_invalid` failures retain at most five exact candidates (occurrence index, span, 20 code points of context per side and a match preview of at most 64 code points) within 8,192 bytes including the wrapper, plus stage, prior-change count, observed identity and explicit truncation. Candidates list exact occurrences; they are not certified to satisfy the failed selectors, and there is no cursor or automatic selection.
- `match_absent` and `sequential_match_invalid` failures persist `diagnostic.near_miss_query`: the canonical query when its raw length is at most 64 code points, otherwise `omission_reason: "match_too_large"`, within 1,024 wrapper bytes.
- Response-only `near_misses` are computed only after a service-owned transaction has committed and released its lock, and only from the stored failure prefix (at most 256 code points) and query. Caller-owned transactions return `omission_reason: "caller_transaction"`.
- Windows have the query length minus one, the query length and the query length plus one (positive lengths only). Distance is code-point Levenshtein, accepted when nonzero and at most `min(4, max(1, len(query) // 4))`. At most three candidates are returned, ranked by `(distance, start, end)`, each with 16 code points of context per side, within 8,192 wrapper bytes.
- Distances come from an exact Ukkonen-banded dynamic program: cells farther than the threshold from the diagonal are not evaluated, so `comparison_cells` counts banded cells only. A 64-point query over a full 256-point prefix needs at most 147,456 cells, well under the 1,000,000-cell work cap. Exhausting the cap returns `work_budget_exhausted` with no partial ranking; historical outcomes without stored inputs return `historical_context_unavailable`.
- `truncated` reflects prefix omission or candidate-count truncation. Near misses never promise distant matches and never change the verdict. Unexpected post-commit errors propagate without claiming rollback. All newly added enrichment fields together are at most 18,432 bytes; this excludes preexisting arbitrary evidence.

### Discovery capabilities and examples

`tools/list` advertises the tx/2 operation schema and, for both new submission tools, `x-patchdiff-capabilities` derived from the runtime constants (protocol, immutable runtime, allowed operations, and either coordinate/insertion support or size limits). It also publishes 13 schema-conforming `inputSchema.examples` across nine tools, deep-copied per result. The complete `{tools: [...]}` payload is at most 65,536 bytes and the complete examples map at most 8,192 bytes. Examples are illustrative arguments: hosts must bind real target IDs, guards, parents and cursors (see the host guide's executable sequence). Every advertised example runs over real stdio and PostgreSQL in the test suite; this is API coverage, not a model-success or production-performance claim.

---

## 1. Target Lifecycle Tools

### `patchdiff_initialize_target` / `patchdiff_handle_upload`
- **Arguments**:
  - `filename` (`string`, required): document filename.
  - `content` (`string`, required): initial document text.
  - `content_type` (`string`, required): MIME type or language identifier (e.g. `"text/markdown"`).
  - `project_id` (`string | null`, optional): project UUID.
- **Returns**:
  ```json
  {
    "target_file_id": "UUID",
    "filename": "stdio-workflow.md",
    "target_type": "text/markdown",
    "version": 0,
    "current_hash": "sha256...",
    "active_editing_cycle_id": "UUID"
  }
  ```

### `patchdiff_get_target`
- **Arguments**: `target_file_id` (`string`, required).
- **Returns**: `target_file_id`, `filename`, `target_type`, `current_content`, `current_hash`, `version`, `active_editing_cycle_id`.

### `patchdiff_export_target`
- **Arguments**: `target_file_id` (`string`, required), `format` (`string`, default `"original_text"`).
- **Returns**: `filename`, `content_type`, `target_type`, `content`, `version`, `hash`, `current_hash`, `format`.

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
Lists exact occurrences of `text` (overlapping spans counted) with bounded context and pagination.
- **Arguments**:
  - `target_file_id` (`string`, required).
  - `text` (`string`, required): exact string to locate.
  - `context_chars` (non-bool integer >=0, default 40): context window before/after each match, clamped to 400. Negative, boolean, null, string and float values return invalid_argument.
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
    - `occurrence_index` (`integer >= 1 | null`, optional): 1-based selector over exact occurrences; enforced even when only one match exists.
    - All supplied selectors must hold together. Excluding singleton selectors reject with disambiguation_invalid; anchors retain anywhere-before/after semantics. This applies to new typed and legacy submissions under runtime 0.2.2; older logs replay under their recorded behavior.
    - `anchor_before` (`string | null`, optional): preceding substring context.
    - `anchor_after` (`string | null`, optional): succeeding substring context.
  - `expected_target_version` (`integer | null`, optional): target version guard.
  - `expected_current_hash` (`string | null`, optional): 64-hex SHA-256 target hash guard.
  - `client_request_id` (`string | null`, optional): 1..128 printable ASCII characters for request deduplication.
  - `parent_pdcp_log_id` (`string | null`, optional): UUID of rejected parent attempt when retrying.
  - `attempt` (`integer | null`, optional): retry attempt number (1-based).
  - `source` (`string`, default `"model_response"`).
- **Rule**: At least one of `expected_target_version` or `expected_current_hash` is **required**.

#### Accepted Response
```json
{
  "status": "accepted",
  "target_file_id": "UUID",
  "before_hash": "sha256...",
  "after_hash": "sha256...",
  "version": 1,
  "pdcp_log_id": "UUID",
  "manifest_entries_added": 1,
  "warnings": [],
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
        "span_start": 120,
        "span_end": 134,
        "matched_chars": 14,
        "replacement_chars": 18,
        "matched_sha256": "sha256...",
        "replacement_sha256": "sha256..."
      }
    ]
  },
  "deduplicated": false,
  "client_request_id": "req-001"
}
```

#### Rejected Response
```json
{
  "status": "rejected",
  "target_file_id": "UUID",
  "failure_reason": "match_ambiguous",
  "failure_detail": "match matched 2 exact occurrences in the current buffer.",
  "failed_change_id": "chg_001",
  "before_hash": "sha256...",
  "after_hash": null,
  "current_version": 0,
  "current_hash": "sha256...",
  "pdcp_log_id": "UUID",
  "diagnostic": {
    "format": "patchdiff-tx/1",
    "occurrence_count": 2,
    "retryable": true,
    "requires_new_submission": true,
    "validation_stage": "transaction_applicability"
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
Submits a raw declarative `.pdcp` v0.2.3 document. Shares the same applier, atomicity, logging, and response structure as `patchdiff_submit_edits`.
- **Arguments**: `target_file_id`, `pdcp_content`, optional `expected_target_version`, `expected_current_hash`, `client_request_id`, `parent_pdcp_log_id`, `regeneration_attempt`, `regeneration_source`, `source`.

---

## 4. Checkpoint, Replay & Bounded Audit Tools

### `patchdiff_save`
Creates a `TargetSnapshots` row (`snapshot_reason = "save_checkpoint"`), closes the active cycle, and opens a new cycle. Does not mutate target text.
- **Arguments**: `target_file_id`, optional `expected_current_hash`, optional `export_after_save` (`boolean`).
- **Returns**: `status: "saved"`, `target_file_id`, `snapshot_id`, `closed_editing_cycle_id`, `new_editing_cycle_id`, `current_hash`, `version`.

### `patchdiff_replay`
Replays accepted logs against the initial snapshot, dispatching on `(protocol_version, runtime_version)`. A successful reconstruction may still report materialized_state_matches=false. content_matches compares raw stored content with the canonical reconstructed buffer; canonical hash checks retain their existing meaning. Replay reports divergence and never repairs storage.
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
- **Returns**: `entries[]` containing sequence, hashes, versions, failure reason/detail, `client_request_id`, `request_fingerprint`, `diagnostic`, and timestamps. Also returns has_more and next_sequence. Fetch limit+1 after all filters; next_sequence is the smallest returned log_sequence when another page exists, otherwise null. Empty/not-found/invalid responses have entries=[], has_more=false, next_sequence=null. Unknown targets return not_found; invalid argument types return invalid_argument.

### `patchdiff_get_manifest_ledger`
Returns bounded, oldest-first accepted manifest ledger entries within the newest page.
- **Arguments**:
  - `target_file_id` (`string`, required): target UUID.
  - `include_previous_cycles` (`boolean`, optional, default `false`): include entries from closed editing cycles.
  - `limit` (positive non-bool integer or null, optional): default 50, cap 200. Omitted/null selects 50; zero/negative/boolean/float/string values return invalid_argument.
  - `before_sequence` (`integer >= 1 | null`, optional): exclusive upper bound on `ledger_sequence` for paging backward.
- **Returns**:
  ```json
  {
    "entries": [
      {
        "ledger_sequence": 1,
        "change_id": "chg_001",
        "intent": "Initial edit",
        "input_state": null,
        "output_state": null,
        "affected_region": null,
        "user_visible_change": null,
        "risk": "low",
        "origin": "typed",
        "derived": {
          "span_start": 0,
          "span_end": 10,
          "matched_chars": 10,
          "replacement_chars": 12,
          "matched_sha256": "...",
          "replacement_sha256": "..."
        },
        "created_at": "2026-10-20T12:00:00Z"
      }
    ],
    "has_more": false,
    "next_sequence": null
  }
  ```
- **Ordering and cursor example**: For sequences 1..10 with limit 3, attempts return [10,9,8], ledger [8,9,10], both next_sequence=8. A ledger call with before_sequence=8 returns [5,6,7]. Both cursors are exclusive; ledger reverses only the selected newest page for display. Newer inserted rows are excluded from continuation below a previous cursor. Both history tools return the same empty continuation fields; include flags must be boolean.
- **Caller Note**: Traversal must restart if `patchdiff_save` rotates the active editing cycle during an active-cycle-only traversal. Callers migrating from the legacy unbounded behavior must page via `before_sequence`.

---

## 5. Convenience & Deprecated Compatibility Wrappers

- `patchdiff_build_prompt_context`: Convenience preview returning the first 4,000 characters (`content[:4000]`) with `context_truncated: true` and active manifest summary. Not a retrieval engine; hosts requiring authoritative spans must call `patchdiff_read_target` and `patchdiff_find_occurrences`.
- `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`: **Deprecated** server-mediated retry tools retained only for backward compatibility. Hosts should inspect diagnostics from `patchdiff_submit_edits`, re-read via `patchdiff_read_target` / `patchdiff_find_occurrences`, and resubmit with `parent_pdcp_log_id`.
