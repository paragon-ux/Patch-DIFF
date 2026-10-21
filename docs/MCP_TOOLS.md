# MCP_TOOLS.md

Unicode boundary: edit-submission strings and metadata must be valid UTF-8/PostgreSQL text. Known-target invalid text returns an audited target_encoding_invalid / PROTOCOL_VALIDATION rejection. Existing pdcp_content TEXT carries reversible ASCII-escaped patchdiff-invalid-input/1 evidence; JSONB holds only safe diagnostics. Read/search string errors return invalid_argument with no edit-attempt row. Valid inputs and discovery operation shapes are unchanged.

Conflicting-key submissions return context_invalid plus a fresh durable rejection log ID. The rejected row uses a NULL key and submitted fingerprint, with original-log linkage and a bounded submitted-key preview. The response continues to echo the submitted key. Exact recovery of the original request remains deduplicated:true without a new row; repeated conflicts each append an immutable attempt.


F01 rejection contexts apply to both submission tools. A new rejection has immutable `diagnostic.failure_context` and top-level response-only `current_context`. Each available object has `available: true`, `selection: "prefix"`, `buffer_stage: "canonical_target" | "intermediate_buffer"`, `prior_changes`, `start: 0`, end-exclusive `end`, `total_chars`, `text`, `truncated`, `observed_target_version` and `observed_target_hash`. The observed identity names canonical target state at transaction start. First-change and service/precondition/protocol/lineage errors use canonical context (`prior_changes: 0`); later application errors use the actual intermediate buffer and count already simulated edits. Current context always describes the refreshed locked canonical target.

Select the longest prefix of at most 256 Unicode code points that fits the actual JSON byte budgets, with `end = len(text)` and `truncated = end < total_chars`. Offsets/counts are code points, not UTF-8 bytes or UTF-16 units. Each complete context is at most 4,096 bytes of compact ASCII-escaped JSON (`ensure_ascii=True`, `separators=(",", ":")`); the combined `{failure_context, current_context}` enrichment including wrapper keys is at most 8,192 such bytes. Reserve combined wrapper overhead in each context budget. Normal valid SHA-256 identities retain the full min(256, total_chars) prefix; corrupted non-ASCII stored hashes can shorten the prefix without truncating identity. Context includes no arbitrary proposer strings or duplicated failed-change ID. Prefix selection never claims an exact failed span or nearest candidate.

Unavailable objects have `available: false`, `unavailable_reason: "invalid_target_id" | "target_not_found" | "unlocked_local_state"`, and null values for every other field above. Available objects have `unavailable_reason: null`. An available empty target has empty text, zero spans/count, and `truncated: false`. Dirty local ORM state is unavailable even if compatibility version/hash fields expose local values.

Exact keyed recovery returns the original stored diagnostic unchanged and separately captures fresh current context; older rows lacking failure context stay unchanged. Accepted responses gain no context field. Context capture does not commit caller-owned transactions or release locks, and their observed state can remain provisional until caller commit. Use authoritative reads/search and a new linked proposal for correction.

## Goal F Pass A contract

The normative [Pass A decision](usability/PASS-A-decision.md) defines F03/F05/F06/F07 fields, bounds, omission states, ownership and compatibility before implementation. `include_correlation_id=false` is a boolean response option on submissions; true emits a fresh UUIDv4 even on exact recovery. Invalid types return pre-admission invalid_argument with no attempt. Correlation never enters durable records, request keys or fingerprints.

New applicability ambiguity/selector failures retain at most five exact candidates (20 code points each side,64 match preview;8192 compact ASCII-escaped JSON bytes including wrapper), stage/prior-change/observed identity and explicit truncation; no cursor or selection. Absent/sequential failures retain at most 64 code points of immutable query evidence (1024 wrapper bytes). Response-only near misses compare only the original at-most-256-point failure prefix after actual successful service-owned commit/lock release; caller-owned transactions omit with caller_transaction. Work is at most 1,000,000 Levenshtein cells, windows query length±1, distance threshold min(4,max(1,length//4)), at most three candidates ranked distance/start/end,16-point context each side and8192 wrapper bytes. Exhaustion/oversize/historical inputs have explicit omission; unexpected post-commit errors propagate without claiming rollback. Original diagnostics stay immutable on recovery. New enrichment fields combined are at most18432 compact ASCII-escaped JSON bytes; this excludes preexisting arbitrary evidence.

`patchdiff_submit_operations` records `patchdiff-tx/2`: intent, mandatory guard and ordered explicit match/span operations. Span start/end are non-bool integers 0..2^63-1, end exclusive and end>=start; expected_text/replace are required strings. Coordinates describe each sequential canonical buffer; exact canonical expected text must equal that span. Empty-span insertion is allowed with empty expected text; selectors on span and unknown fields/operations reject. Mixed match/span edits are atomic. Applicability errors are span_out_of_bounds and span_expected_text_mismatch. Both forms use the existing locked submit/rejection/ledger path. New records use immutable patchdiff-mvp-0.3.0 enabling span operations; old forms keep 0.2.2 and unchanged records/fingerprints/profiles. Replay refuses unsupported profile/operation pairs. Span facts include operation=span and existing runtime-derived hashes/spans/counts; ledger origin remains typed. No migration or replace_all in 0.3.0. Discovery advertises operation schema and x-patchdiff-capabilities; worked discovery examples remain Pass B.


## Purpose

This document defines the complete MCP tool surface for PatchDIFF.

PatchDIFF is exposed over stdio JSON-RPC (`backend/app/mcp/external_adapter.py`) and an internal Python registry (`backend/app/mcp/server.py`). All tools route through the deterministic service layer (`backend/app/services/`) and execute per-target atomic commits against Postgres.

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built record: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

## MCP Tool Surface Overview

The 17 registered MCP tools are organized into five functional groups:

| Group | Tool Name | Role & Modernized Status |
| --- | --- | --- |
| **1. Target Lifecycle** | `patchdiff_initialize_target` | Initialize canonical target state, active cycle, and initial snapshot in Postgres. |
| | `patchdiff_handle_upload` | Upload alias for `patchdiff_initialize_target`. |
| | `patchdiff_get_target` | Retrieve canonical metadata, current content, hash, and version. |
| | `patchdiff_export_target` | Export canonical target text and metadata for external use. |
| **2. Authoritative Reads & Search** | `patchdiff_read_target` | Authoritative bounded read of target slices by code-point offset with `next_start` continuation. |
| | `patchdiff_find_occurrences` | Enumerate exact occurrences (overlapping counted) with bounded context and pagination. |
| **3. Transaction Submission** | `patchdiff_submit_edits` | **Primary typed input** (`patchdiff-tx/1`). Structured `edits[]`, required guards, `client_request_id` idempotency. |
| | `patchdiff_submit_operations` | Guarded `patchdiff-tx/2` ordered match/span operations with required exact expected text on spans; profile 0.3.0. |
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

## Guarded operations and response options

`patchdiff_submit_operations(target_file_id, intent, operations, expected_target_version=null, expected_current_hash=null, source="model_response", parent_pdcp_log_id=null, attempt=null, client_request_id=null, include_correlation_id=false)` uses the same guard, lineage, audited rejection, acceptance, ledger and recovery response contract as typed edits. At leastone guard is required and every supplied guard is checked. Missing/invalid guard syntax follows the existing PROTOCOL_VALIDATION path; stale valid guards reject at PRECONDITION_GUARD.

Each operation is one of:

- Match: `{op:"match",match,replace,change_id?,rationale?,risk?,occurrence_index?,anchor_before?,anchor_after?}` with unchanged exact-match selector rules.
- Span: `{op:"span",start,end,expected_text,replace,change_id?,rationale?,risk?}`. Unknown fields and selectors reject. Coordinates are sequential canonical code points; start/end are non-bool integers 0..2^63-1, end>=start. Explicit insertion uses start=end and empty expected_text. Expected/replacement newlines canonicalize before application. Span bounds or expected-text mismatch reject the entire transaction without partial facts or ledger rows.

All submission tools accept the optional boolean response flag. UUID correlation is invocation-only, including on dedup; false/omitted preserves correlation omission. Invalid types return invalid_argument before admission with no attempt. Exact diagnostic candidates name all exact occurrences, not candidates certified to satisfy failed selectors. Near misses are response-only suggestions within original bounded context and do not change the verdict. See Pass A bounds above. Discovery's x-patchdiff-capabilities names the tx/2 format, immutable profile, allowed operation names, sequential-code-point coordinates and insertion support. No new executable discovery examples are claimed in this pass.

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
  - `context_chars` (non-bool integer >=0, default40): context window before/after each match, clamped to400. Negative, boolean, null, string and float values return invalid_argument.
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
  - `limit` (positive non-bool integer or null, default50): omitted/null selects50; values above200 clamp to200.
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
  - `limit` (positive non-bool integer or null, optional): default50, cap200. Omitted/null selects50; zero/negative/boolean/float/string values return invalid_argument.
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
- **Ordering and cursor example**: For sequences1..10 with limit3, attempts return [10,9,8], ledger [8,9,10], both next_sequence=8. A ledger call with before_sequence=8 returns [5,6,7]. Both cursors are exclusive; ledger reverses only the selected newest page for display. Newer inserted rows are excluded from continuation below a previous cursor. Both history tools return the same empty continuation fields; include flags must be boolean.
- **Caller Note**: Traversal must restart if `patchdiff_save` rotates the active editing cycle during an active-cycle-only traversal. Callers migrating from the legacy unbounded behavior must page via `before_sequence`.

---

## 5. Convenience & Deprecated Compatibility Wrappers

- `patchdiff_build_prompt_context`: Convenience preview returning the first 4,000 characters (`content[:4000]`) with `context_truncated: true` and active manifest summary. Not a retrieval engine; hosts requiring authoritative spans must call `patchdiff_read_target` and `patchdiff_find_occurrences`.
- `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`: **Deprecated** server-mediated retry tools retained only for backward compatibility. Hosts should inspect diagnostics from `patchdiff_submit_edits`, re-read via `patchdiff_read_target` / `patchdiff_find_occurrences`, and resubmit with `parent_pdcp_log_id`.
