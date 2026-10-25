# PATCHDIFF_CORE_SPEC.md

Bounded rejection evidence: the pure applier returns at most 256 code points of the actual failing buffer (a prefix, or a window around a known failure location) with its total length and prior simulated-change count, never an unbounded failed buffer. For `match_absent` it also returns a response-only copy of at most the first 65,536 code points for near-miss scanning, which the service never persists. The service adds canonical observed identity and persists `diagnostic.failure_context` once. A later sequential failure is labeled `intermediate_buffer`; it does not imply a partial commit. Service/protocol failures use locked canonical state. Response-only `current_context` is fresh on every rejected call, including exact keyed recovery, while the original diagnostic is immutable and old rows are not retrofitted. MCP_TOOLS defines the complete fields, unavailable states and 4,096/8,192 ASCII-escaped JSON byte budgets. Verdicts, accepted facts, hashes, fingerprints and execution profiles remain unchanged.

## Guarded operations, sole replacement and failure evidence

Tool fields and byte budgets are in [MCP_TOOLS.md](MCP_TOOLS.md#guarded-editing-reads-preview-and-diagnostics); this section states the runtime rules.

- **Span operations (`patchdiff-tx/2`, profile `patchdiff-mvp-0.3.0`).** A span carries non-bool integer `start`/`end` with `0 <= start <= end`, in code points of the sequential canonical buffer, plus the exact `expected_text` and `replace`. The applier rejects with `span_out_of_bounds` when `end` exceeds the buffer length, and with `span_expected_text_mismatch` unless `buffer[start:end] == canonicalize_text(expected_text)`. `start == end` with an empty `expected_text` inserts. Match operations keep the 0.2.2 exact-match and selector rules. Span facts add `operation: "span"`. Both span failures are transaction-applicability failures, and their diagnostics report `span_check`, `buffer_length` and up to 64 code points of `actual_text`.
- **Span context (`patchdiff-mvp-0.5.0`).** Optional `expected_before`/`expected_after` must equal `buffer[start-len(expected_before):start]` and `buffer[end:end+len(expected_after)]` after canonicalization; a mismatch is `span_expected_text_mismatch` with `span_check` naming the field. Only a profile with `span_context` accepts them; 0.3.0 rejects the fields at decoding and the applier refuses them under any other profile.
- **Sole replacement (`patchdiff-tx/3`, profile `patchdiff-mvp-0.4.0`).** Exactly one `replace_all` replaces the whole buffer `[0, len(buffer))`; any other operation count or kind rejects. The single fact covers the full original span with `operation: "replace_all"`. Fresh size admission is enforced by the service, not by decoding or replay.
- **Profile gates.** `RuntimeProfile.span_operations` and `RuntimeProfile.replace_all_operations` default to false, so every historical profile and 0.2.2 reject both operation kinds; 0.3.0 enables spans only, 0.4.0 enables both, and 0.5.0 enables spans plus `RuntimeProfile.span_context`. Profiles never change after they write history.
- **Failure evidence.** For `match_ambiguous` and `disambiguation_invalid` the pure applier captures at most five exact candidates (20 code points of context per side, 64-point match preview). When such a failure follows earlier simulated changes, `failure_detail` adds that selectors count the sequential buffer. For `match_absent` it captures the near-miss query (the canonical query of at most 64 code points, otherwise `match_too_large`). For `sequential_match_invalid` it instead records each original occurrence (up to five) with the earlier change that overlapped it, and no near-miss query. Near-miss ranking itself is service-side and response-only.
- **Advisory warnings.** On acceptance the applier reports `no_op_change`, `no_op_transaction`, `occurrence_index_basis_shift` (a sequential `occurrence_index` mapped back through earlier change facts to a different, or no, transaction-start index) and `grapheme_boundary_split` (a conservative UAX #29 approximation). Warnings never change a verdict or a fact; replay calls the applier with `collect_warnings=False`.
- Preview, line reads, correlation IDs and discovery are service/MCP features with no core-runtime effect.

## Purpose

This document defines the deterministic PatchDIFF core runtime (`backend/app/core/`, `backend/app/pdcp/`).

The core runtime accepts declarative, non-executable edit transactions—typed edits (`patchdiff-tx/1`), guarded match/span operations (`patchdiff-tx/2`), sole guarded replacement (`patchdiff-tx/3`) and frozen legacy `.pdcp` (v0.2.3) files—and canonical target text. It validates protocol structure, validates transaction applicability, applies exact `MATCH/REPLACE` operations sequentially in memory, computes runtime-derived change facts, commits atomically per target, logs all accepted and rejected attempts with retry lineage and idempotency, supports SAVE checkpointing, and executes deterministic replay.

The core runtime is deterministic, pure, and trusted.

Transaction inputs are untrusted data.

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built record and verification evidence: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

## Core Architecture & Representation

```text
canonical UTF-8 target text
+ declarative non-executable transaction (patchdiff-tx/1, patchdiff-tx/2, patchdiff-tx/3 or .pdcp 0.2.3)
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

All four input formats lower into the same internal `ParsedPDCP` representation and execute through the same `apply_pdcp_transaction` applier:
- **`patchdiff-tx/1` (primary typed)**: Structured JSON with required `intent`, required state guard (`expected_target_version` and/or `expected_current_hash`), ordered `edits[]` (`match`, `replace`, optional `change_id`, `rationale`, `risk`, `occurrence_index`, `anchor_before`, `anchor_after`), optional `client_request_id`, `parent_pdcp_log_id`, and `attempt`. Persisted in `append_only_pdcp_logs.pdcp_content` as deterministic canonical JSON.
- **`patchdiff-tx/2` (guarded operations)**: Ordered explicit match/span operations, required intent and state guard, sequential canonical code-point spans with exact expected text and optional adjacent-text guards; immutable profile 0.3.0, or 0.5.0 when the guards are used.
- **`patchdiff-tx/3` (sole replacement)**: Exactly one guarded `replace_all`, immutable profile 0.4.0; fresh size admission is a service boundary, not a replay grammar constraint.
- **Legacy `.pdcp` v0.2.3 & historical profiles (`0.1.0`–`0.2.1`)**: Frozen legacy text format and historical replay profiles are specified in [LEGACY_COMPATIBILITY.md](LEGACY_COMPATIBILITY.md).

None of these formats is executable code.

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

### Invalid submission text

Before normal record hashing/storage, reject unpaired surrogate code points and NUL in submitted text or nested metadata. This is representability validation, not Unicode normalization or replacement encoding. Valid non-ASCII and supplementary characters remain supported.

For a resolvable target, the service records target_encoding_invalid at PROTOCOL_VALIDATION through the same locked rejection path. Existing TEXT fields hold a reversible ASCII-escaped patchdiff-invalid-input/1 envelope of the original inputs; diagnostic JSONB contains only safe marker/path strings. The envelope is rejected evidence, never an accepted transaction or a new protocol operation. Valid-input canonical_sha256 and recorded history are unchanged. Invalid input has domain-separated request identity, preserving safe-key rejected-outcome recovery.

Read/search string argument errors use invalid_argument and do not create submission attempts. Malformed/unresolvable target identity cannot create a target-linked attempt and must not be echoed unsafely.

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

A conflicting reuse of an existing request key is a separately audited context_invalid rejection at PRECONDITION_GUARD. It adds a NULL-key attempt carrying the submitted fingerprint and bounded submitted-key/original-log diagnostics; it never changes target state or accepted ledger. Exact outcome recovery adds no row. All separately admitted repeated conflicts remain immutable rows. State inside a caller-owned transaction stays provisional until that owner commits or rolls back.

## Structural Purity & Format Validation

### Typed Transaction (`patchdiff-tx/1`) Rules
- Top-level JSON object with `format: "patchdiff-tx/1"`, `target_file_id`, `intent` (non-empty string), and `edits` (non-empty array).
- Each edit requires non-empty `match` string and `replace` string (empty string `""` denotes deletion).
- Allowed edit fields: `match`, `replace`, `change_id`, `rationale`, `risk`, `occurrence_index`, `anchor_before`, `anchor_after`. Unknown fields (including `region_hint`) are rejected (`FailureReason.MANIFEST_INVALID`).
- Valid `risk` values: `"low"`, `"medium"`, `"high"`.
- `change_id` defaults to `chg_001`, `chg_002`, ... by 1-based index if omitted or `null`. Duplicate `change_id`s within a transaction reject with `FailureReason.MANIFEST_INVALID`.

### Legacy PDCP (v0.2.3) Rules
Frozen `.pdcp` v0.2.3 header, 7-field `# MANIFEST` grammar, and delimiter-collision (`FailureReason.BLOCK_MALFORMED`) rules are documented in [LEGACY_COMPATIBILITY.md](LEGACY_COMPATIBILITY.md#1-frozen-pdcp-v023-wire-format).

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

### Historical Replay Profiles (`patchdiff-mvp-0.1.0` through `0.2.1`)
Historical logs accepted under `patchdiff-mvp-0.1.0`, `0.2.0`, or `0.2.1` are replayed using their recorded profile settings so that accepted history remains deterministically replayable. See [LEGACY_COMPATIBILITY.md](LEGACY_COMPATIBILITY.md#4-historical-runtime-replay-profiles).

## Disambiguation

In match-capable runtime profiles 0.2.2 and later, supplied selecting fields are conjunctive constraints for every match count, including a singleton. With multiple occurrences, selecting fields must resolve exactly one span:
1. `occurrence_index`: 1-based index over the global list of exact occurrences in left-to-right order.
2. `anchor_before`: exact substring that must appear before the candidate span.
3. `anchor_after`: exact substring that must appear after the candidate span.
4. `region_hint`: legacy advisory field supported on `.pdcp` v0.2.3 only (does not select by itself; rejected on typed path).

If 0 occurrences match: reject with `FailureReason.MATCH_ABSENT`.
If multiple occurrences exist with an empty disambiguation mapping: reject with FailureReason.MATCH_AMBIGUOUS. A nonempty advisory-only mapping (for example region_hint alone) rejects with FailureReason.DISAMBIGUATION_INVALID; advisory metadata cannot select an occurrence. A singleton with no selecting fields succeeds.
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
- Optional `expected_target_version` and `expected_current_hash` guards are both checked when supplied; a mismatch rejects without a snapshot.
- By default, manifest ledger reads filter to the active editing cycle.

## Deterministic Replay

Replay reconstructs canonical target state from the `initial_upload` snapshot plus ordered accepted log entries:
1. Verify initial snapshot content against `initial_snapshot.content_hash`.
2. For each accepted log row in sequence:
   - Verify `log.target_file_id == target.target_file_id`.
   - Dispatch parser on `log.protocol_version` (`"0.2.3"`, `"patchdiff-tx/1"`, span-capable `"patchdiff-tx/2"` or sole replacement `"patchdiff-tx/3"`). tx/3 requires replacement-capable profile 0.4.0; replay bypasses fresh service admission size limits.
   - Resolve matcher profile via `SUPPORTED_RUNTIME_PROFILES[log.runtime_version]`.
   - Verify contiguous version chain (`before_version == expected_version`, `after_version == expected_version + 1`).
   - Verify `before_hash == canonical_sha256(replay_buffer)`.
   - Apply edits deterministically in memory, without warning collection.
   - Verify `log.pdcp_content_hash == canonical_sha256(log.pdcp_content)`.
   - Verify `result.after_hash == log.after_hash`.
3. Check reconstructed state against the materialized target and report `materialized_state_checks`:
   - `content_matches`: `target.current_content == replay_buffer` (raw stored text; no pre-comparison normalization)
   - `stored_hash_matches`: `target.current_hash == reconstructed_hash`
   - `recomputed_hash_matches`: `canonical_sha256(target.current_content) == reconstructed_hash`
   - `version_matches`: `target.version == expected_version`

Materialized content health: canonical_sha256 and historical hashes remain unchanged. Successful history reconstruction is independent of materialized_state_matches; replay never repairs storage. CRLF/bare-CR storage divergence is visible even when its canonical hash agrees.
