# PATCHDIFF_CORE_SPEC.md

## Purpose

This document defines the deterministic PatchDIFF core runtime (`backend/app/core/`, `backend/app/pdcp/`).

The core runtime accepts declarative, non-executable edit transactions—primary typed transactions (`patchdiff-tx/1`) and frozen legacy `.pdcp` (v0.2.3) files—and canonical target text. It validates protocol structure, validates transaction applicability, applies exact `MATCH/REPLACE` operations sequentially in memory, computes runtime-derived change facts, commits atomically per target, logs all accepted and rejected attempts with retry lineage and idempotency, supports SAVE checkpointing, and executes deterministic replay.

The core runtime is deterministic, pure, and trusted.

Transaction inputs are untrusted data.

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built record and verification evidence: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

## Core Architecture & Representation

```text
canonical UTF-8 target text
+ declarative non-executable transaction (patchdiff-tx/1 or .pdcp 0.2.3)
-> lowering into ParsedPDCP representation
-> exact deterministic MATCH (all exact spans counted)
-> immediate sequential REPLACE simulation in memory
-> runtime-derived change_facts calculation
-> per-target atomic Postgres commit under SELECT ... FOR UPDATE
-> append-only PDCP attempt log (accepted and rejected, with lineage & client_request_id)
-> accepted-only manifest ledger (with origin and derived_json)
-> SAVE checkpointing & editing cycle rotation
-> deterministic replay dispatching on (protocol_version, runtime_version)
```

Both input formats lower into the same internal `ParsedPDCP` representation and execute through the same `apply_pdcp_transaction` applier:
- **`patchdiff-tx/1` (primary typed)**: Structured JSON with required `intent`, required state guard (`expected_target_version` and/or `expected_current_hash`), ordered `edits[]` (`match`, `replace`, optional `change_id`, `rationale`, `risk`, `occurrence_index`, `anchor_before`, `anchor_after`), optional `client_request_id`, `parent_pdcp_log_id`, and `attempt`. Persisted in `append_only_pdcp_logs.pdcp_content` as deterministic canonical JSON.
- **`.pdcp` v0.2.3 (frozen legacy/import)**: Declarative text with `PDCP 0.2.3` header, 7 required manifest fields per change block, and `<<<<<<< MATCH` / `=======` / `>>>>>>> REPLACE` delimiters. Persisted as raw text.

Neither format is executable code.

## Canonicalization

Canonicalization applies to:
- target content
- `MATCH` payload
- `REPLACE` payload

Rules:
```text
encoding: UTF-8
newline form: LF
line-ending handling: normalize CRLF and CR to LF
tab handling: preserve tabs exactly
space handling: preserve spaces exactly
trailing whitespace: preserve exactly
trailing final newline: preserve exactly
Unicode normalization: none
```

The runtime must not apply NFC, NFD, NFKC, or NFKD normalization.

## Hashing

Use SHA-256 over UTF-8 bytes of canonicalized target text.

Required hash fields:
- `current_hash`
- `before_hash`
- `after_hash`
- optional `target_hash` (precondition in PDCP header)
- optional `expected_current_hash` (precondition in submit requests)

Rejected attempts use:
```text
before_hash = canonical hash at validation time
after_hash = null
```

## Structural Purity & Format Validation

### Typed Transaction (`patchdiff-tx/1`) Rules
- Top-level JSON object with `format: "patchdiff-tx/1"`, `target_file_id`, `intent` (non-empty string), and `edits` (non-empty array).
- Each edit requires non-empty `match` string and `replace` string (empty string `""` denotes deletion).
- Allowed edit fields: `match`, `replace`, `change_id`, `rationale`, `risk`, `occurrence_index`, `anchor_before`, `anchor_after`. Unknown fields (including `region_hint`) are rejected (`FailureReason.MANIFEST_INVALID`).
- Valid `risk` values: `"low"`, `"medium"`, `"high"`.
- `change_id` defaults to `chg_001`, `chg_002`, ... by 1-based index if omitted or `null`. Duplicate `change_id`s within a transaction reject with `FailureReason.MANIFEST_INVALID`.

### Legacy PDCP (v0.2.3) Rules
- Protocol header: `PDCP 0.2.3`, required `target_file_id`, optional `target_type`, optional `target_hash`.
- Exactly one `# MANIFEST` block immediately before each `MATCH/REPLACE` block.
- 7 required manifest fields: `change_id`, `intent`, `input_state`, `output_state`, `affected_region`, `user_visible_change`, `risk`.
- Delimiters `<<<<<<< MATCH`, `=======`, `>>>>>>> REPLACE`. Payloads containing lines equal to a delimiter reject with `FailureReason.BLOCK_MALFORMED`.

### Executable Logic Rejection
Reject obvious executable code outside payloads: imports, functions, classes, loops, conditionals, shell commands, dynamic evaluation, filesystem calls, network calls, tool calls (`FailureReason.EXECUTABLE_LOGIC_DETECTED`).

Payloads may contain code-like text because target documents may contain code. The runtime must never execute payload text.

## Matching Semantics & Overlap Enumeration

`MATCH` is an exact optimistic concurrency precondition.

Matching is:
- exact, case-sensitive, whitespace-sensitive after LF canonicalization, multiline, left-to-right over Unicode codepoints.
- evaluated over the progressively updated in-memory buffer.
- non-fuzzy: no semantic, AST, token, or automatic-repair matching.

### Overlapping-Match Enumeration (`patchdiff-mvp-0.2.2`)
All exact occurrences of `MATCH` across the buffer are enumerated, including overlapping occurrences (advancing the search index by 1 code point rather than `len(match)`). For example, matching `"aa"` in `"aaa"` yields 2 occurrences (spans `0..2` and `1..3`) and rejects with `FailureReason.MATCH_AMBIGUOUS` unless explicitly disambiguated.

### Legacy Non-Overlapping Replay Mode (`patchdiff-mvp-0.1.0`)
Historical logs accepted under runtime `patchdiff-mvp-0.1.0` (which advanced the search index by `len(match)`) are replayed using the recorded non-overlapping profile so that accepted history remains deterministically replayable.

## Disambiguation

In current runtime 0.2.2, supplied selecting fields are conjunctive constraints for every match count, including a singleton. With multiple occurrences, selecting fields must resolve exactly one span:
1. `occurrence_index`: 1-based index over the global list of exact occurrences in left-to-right order.
2. `anchor_before`: exact substring that must appear before the candidate span.
3. `anchor_after`: exact substring that must appear after the candidate span.
4. `region_hint`: legacy advisory field supported on `.pdcp` v0.2.3 only (does not select by itself; rejected on typed path).

If 0 occurrences match: reject with `FailureReason.MATCH_ABSENT`.
If multiple occurrences exist with no selecting fields: reject with FailureReason.MATCH_AMBIGUOUS. Advisory legacy region_hint cannot select an occurrence. A singleton with no selecting fields succeeds.
If supplied selecting constraints fail to leave exactly one span, including an out-of-range singleton index or excluding anchor: reject with FailureReason.DISAMBIGUATION_INVALID. Anchors may occur anywhere strictly before/after the selected span; adjacency is not required.

Historical 0.1.0, 0.2.0 and 0.2.1 logs retain the ignored-singleton-selector behavior. Profile 0.2.2 changes that setting only; overlap enumeration and historical change-ID grammars retain their existing behavior. Unknown/missing profiles fail closed.

## Sequential In-Memory Simulation & Derived Facts

A transaction is executed sequentially against an in-memory buffer:
- Edit 1 applies to the transaction-start target text.
- Edit 2 applies to the buffer resulting from Edit 1.
- Edit $N$ applies to the buffer resulting from Edits $1..N-1$.

If Edit $N$ ($N > 1$) fails to match the current buffer, but would have matched the original transaction-start target, return `FailureReason.SEQUENTIAL_MATCH_INVALID`.

### Runtime-Derived Change Facts
For each accepted edit, the runtime computes authoritative facts against the progressively updated buffer:
- `span_start`: code-point start offset in the buffer.
- `span_end`: code-point end offset in the buffer.
- `matched_chars`: length of matched text.
- `replacement_chars`: length of replacement text.
- `matched_sha256`: SHA-256 of matched text.
- `replacement_sha256`: SHA-256 of replacement text.

These facts are persisted in `append_only_manifest_ledger.derived_json` for both typed (`origin='typed'`) and legacy PDCP (`origin='pdcp_manifest'`) transactions.

## Validation Stages & Validity Reporting

Validation progress is tracked via `ValidationStage`:
1. `PRECONDITION_GUARD`: Target lookup, UUID validation, idempotency check, or pre-parse version/hash mismatch. Reports `protocol_valid: null, transaction_valid: null`.
2. `PROTOCOL_VALIDATION`: Format parsing and structural validation. Reports `protocol_valid: false, transaction_valid: null`.
3. `TRANSACTION_APPLICABILITY`: Core matching and simulation. Reports `protocol_valid: true, transaction_valid: false`.
4. `COMMIT_GUARD`: Post-simulation state re-check (`TARGET_DIVERGED`). Reports `protocol_valid: true, transaction_valid: true`.
5. `ACCEPTED`: Transaction committed. Reports `protocol_valid: true, transaction_valid: true`.

Every submit result carries `validity`:
- `protocol_valid`: boolean or `null`
- `transaction_valid`: boolean or `null`
- `task_correct`: `"not_evaluated"`
- `semantic`: `"not_evaluated"`

PatchDIFF never claims task correctness or semantic validity without a real evaluator.

## Failure Reasons

Canonical core failure labels:
```text
context_missing
context_invalid
target_not_found
target_encoding_invalid
manifest_missing
manifest_invalid
block_malformed
match_absent
match_ambiguous
disambiguation_invalid
target_hash_mismatch
target_version_mismatch
target_diverged
executable_logic_detected
sequential_match_invalid
transaction_internal_error
```

Replay-only failure labels:
```text
replay_hash_mismatch
replay_protocol_invalid
replay_transaction_invalid
```

## Per-Target Atomic Commit

Under Postgres `SELECT ... FOR UPDATE` on `cloud_target_files`:
1. Verify `expected_target_version` and/or `expected_current_hash`.
2. Check `client_request_id` idempotency.
3. Simulate all edits in memory and compute `change_facts`.
4. Verify `target.version` and `target.current_hash` have not diverged.
5. Persist updated `cloud_target_files`, new `append_only_pdcp_logs` row, and new `append_only_manifest_ledger` rows in a single atomic transaction.

If any check or edit fails:
- Target content, version, and hash remain completely unchanged.
- A rejected attempt is logged in `append_only_pdcp_logs` with `status: "rejected"`, `after_hash: null`, `failure_reason`, `diagnostic_json`, and `client_request_id`.
- Zero rows are added to `append_only_manifest_ledger`.

## SAVE Checkpoint

`patchdiff_save` rotates the editing cycle:
- Captures a `TargetSnapshots` row with `snapshot_reason = "save_checkpoint"`.
- Closes the active `EditingCycles` row (`status = "closed"`, `save_snapshot_id`).
- Creates a new `EditingCycles` row (`status = "active"`).
- Target content, version, hash, logs, and ledger history remain intact.
- By default, manifest ledger reads filter to the active editing cycle.

## Deterministic Replay

Replay reconstructs canonical target state from the `initial_upload` snapshot plus ordered accepted log entries:
1. Verify initial snapshot content against `initial_snapshot.content_hash`.
2. For each accepted log row in sequence:
   - Verify `log.target_file_id == target.target_file_id`.
   - Dispatch parser on `log.protocol_version` (`"0.2.3"` or `"patchdiff-tx/1"`).
   - Resolve matcher profile via `SUPPORTED_RUNTIME_PROFILES[log.runtime_version]`.
   - Verify contiguous version chain (`before_version == expected_version`, `after_version == expected_version + 1`).
   - Verify `before_hash == canonical_sha256(replay_buffer)`.
   - Apply edits deterministically in memory.
   - Verify `log.pdcp_content_hash == canonical_sha256(log.pdcp_content)`.
   - Verify `result.after_hash == log.after_hash`.
3. Check reconstructed state against the materialized target and report `materialized_state_checks`:
   - `content_matches`: `canonicalize(target.current_content) == replay_buffer`
   - `stored_hash_matches`: `target.current_hash == reconstructed_hash`
   - `recomputed_hash_matches`: `canonical_sha256(target.current_content) == reconstructed_hash`
   - `version_matches`: `target.version == expected_version`
