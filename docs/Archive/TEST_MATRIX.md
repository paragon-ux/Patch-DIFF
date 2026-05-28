# TEST_MATRIX.md

## Scope

This document defines the required test matrix for the MCP-first PatchDIFF MVP.

The matrix covers:

- deterministic core parser and protocol behavior
- exact `MATCH/REPLACE` validation and application
- Postgres persistence, locking, SAVE, and replay
- MCP upload, prompt-context, submit, regeneration, and export orchestration

This matrix assumes a chatbot-plus-MCP flow. It does not assume a frontend.

## Failure Labels

Core rejection labels that tests should assert explicitly where relevant:

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

Replay-only labels:

```text
replay_hash_mismatch
replay_protocol_invalid
replay_transaction_invalid
```

Failure mapping for guard-related tests:

```text
target_version_mismatch:
request expected_target_version precondition fails before validation begins

target_hash_mismatch:
request expected_current_hash or PDCP target_hash precondition fails before validation begins

target_diverged:
target row changes after validation/simulation but before the final commit guard inside the same transaction attempt
```

## 1. Core Parser And Protocol Tests

- Parse a minimal valid `.pdcp` file with `PDCP 0.2.3`, `target_file_id`, `target_type`, one manifest, and one block.
  Expected: parse succeeds.
- Reject missing first line `PDCP 0.2.3`.
  Expected: `context_invalid`.
- Reject missing `target_file_id`.
  Expected: `context_missing`.
- Reject missing `target_type`.
  Expected: `context_missing`.
- Reject Python-style `C = ...` header in MCP-first MVP.
  Expected: `context_invalid`.
- Reject unknown header field.
  Expected: `context_invalid`.
- Reject missing `# MANIFEST`.
  Expected: `manifest_missing`.
- Reject missing required manifest field.
  Expected: `manifest_invalid`.
- Reject duplicate manifest field in one change.
  Expected: `manifest_invalid`.
- Reject empty manifest value.
  Expected: `manifest_invalid`.
- Reject invalid `risk`.
  Expected: `manifest_invalid`.
- Reject duplicate `change_id` within one `.pdcp` file.
  Expected: `manifest_invalid`.
- Reject malformed `MATCH/REPLACE` delimiters or block ordering.
  Expected: `block_malformed`.
- Reject empty `MATCH`.
  Expected: `block_malformed`.
- Reject delimiter collision in payload.
  Expected: `block_malformed`.
- Reject executable logic outside payload.
  Expected: `executable_logic_detected`.
- Allow code-like text inside payload when it belongs to the target content.
  Expected: parse succeeds and runtime treats payload as opaque text.

## 2. Exact `MATCH` Tests

- Exact single `MATCH` over the current canonical target succeeds.
  Expected: accepted.
- Zero exact matches reject.
  Expected: `match_absent`.
- Multiple exact matches without disambiguation reject.
  Expected: `match_ambiguous`.
- Duplicate exact matches with valid `occurrence_index` resolve to one span.
  Expected: accepted.
- Duplicate exact matches with valid anchors resolve to one span.
  Expected: accepted.
- Invalid `occurrence_index` rejects.
  Expected: `disambiguation_invalid`.
- Anchors that leave zero candidates reject.
  Expected: `disambiguation_invalid`.
- Anchors that still leave multiple candidates reject.
  Expected: `disambiguation_invalid`.
- `MATCH` remains case-sensitive.
  Expected: `match_absent`.
- `MATCH` remains whitespace-sensitive after canonicalization.
  Expected: `match_absent`.
- Multiline exact `MATCH` succeeds.
  Expected: accepted.
- CRLF target input canonicalizes to LF before matching.
  Expected: accepted when canonical text matches after normalization.
- Unicode-equivalent but codepoint-different strings do not silently normalize.
  Expected: `match_absent`.

## 3. Replacement, Deletion, And Insertion Tests

- Non-empty `MATCH` plus non-empty `REPLACE` performs exact replacement.
  Expected: accepted.
- Non-empty `MATCH` plus empty `REPLACE` performs deletion.
  Expected: accepted.
- Whitespace-only `REPLACE` is allowed.
  Expected: accepted.
- Anchored insertion using replacement of existing non-empty text succeeds.
  Expected: accepted.
- Zero-length cursor insertion rejects.
  Expected: `block_malformed`.
- Replacement mutates only the selected exact `MATCH` span.
  Expected: accepted with unchanged surrounding content.

## 4. Sequential Mutation Tests

- Change 2 sees the buffer after Change 1, not the original target.
  Expected: accepted when written against progressively updated state.
- Change 2 that only matches the original target but not the post-Change-1 buffer rejects.
  Expected: `sequential_match_invalid`.
- Overlapping sequential edits that remain valid after earlier replacement succeed.
  Expected: accepted.
- Overlapping sequential edits that become invalid after earlier replacement reject atomically.
  Expected: `sequential_match_invalid` or `match_absent`, depending on original-target match behavior.

## 5. Disambiguation Tests

- Header-level `target_hash` guard is enforced before applying the transaction.
  Expected: `target_hash_mismatch` before validation begins when the header precondition is stale.
- Manifest-level `target_hash` guard is enforced before `MATCH` evaluation for that change.
  Expected: `target_hash_mismatch` before validation begins when the change-level precondition is stale.
- `region_hint` alone never selects a candidate.
  Expected: `match_ambiguous` or `disambiguation_invalid`.
- Combination of `occurrence_index`, `anchor_before`, and `anchor_after` can reduce duplicates to one candidate.
  Expected: accepted.
- Disambiguation never performs fuzzy or semantic resolution.
  Expected: rejection if exact constraints do not isolate one candidate.

## 6. Structural Purity Tests

- Reject `def`, `class`, `import`, shell commands, tool-call syntax, or network-call syntax outside payload.
  Expected: `executable_logic_detected`.
- Reject free-form non-manifest prose outside payload and outside the header.
  Expected: `context_invalid` or `block_malformed`, depending on parser stage.
- Accept payload text that itself contains source code or shell text because the target may be code.
  Expected: accepted if the rest of the file is valid.

## 7. Transaction Atomicity Tests

- One failed change in a multi-change PDCP rolls back the entire transaction.
  Expected: target remains unchanged, one rejected PDCP log row exists, no manifest ledger rows added.
- Accepted multi-change PDCP updates target, log, and manifest ledger atomically.
  Expected: target updated once, one accepted PDCP log row, all manifest entries present.
- `before_hash` equals the current target hash at validation time.
  Expected: asserted on both accepted and rejected rows.
- `after_hash` is populated only for accepted rows.
  Expected: accepted row has value, rejected row is `NULL`.
- Runtime does not partially commit a successful first change if a later change fails.
  Expected: no visible target mutation.

## 8. Postgres Persistence Tests

- Alembic migrations create all required tables and constraints.
  Expected: schema matches `DATA_MODEL.md`.
- Initial upload creates target row, editing cycle, and initial snapshot.
  Expected: all rows exist with consistent IDs and hashes.
- Accepted transaction is atomic under Postgres.
  Expected: target, PDCP log, and manifest ledger commit together.
- Rejected transaction does not mutate target.
  Expected: target content/hash/version unchanged.
- `current_pdcp_files` is mutable and non-authoritative.
  Expected: later submissions overwrite/update current row while append-only logs remain intact.
- Append-only tables reject updates/deletes at the application layer and are never used as mutable state.
  Expected: only inserts occur for logs, ledger, and snapshots.
- Rejected attempts remain visible.
  Expected: log query returns them with failure metadata.

## 9. Row-Level Lock And Divergence Tests

- Two concurrent submissions to the same `target_file_id` cannot interleave target writes.
  Expected: one transaction acquires the row lock first; the other waits or fails deterministically.
- Different targets can commit concurrently.
  Expected: no cross-target blocking beyond normal database scheduling.
- Stale `expected_target_version` rejects.
  Expected: `target_version_mismatch` before validation begins.
- Stale `expected_current_hash` rejects.
  Expected: `target_hash_mismatch` before validation begins.
- Target row changes after validation/simulation but before the final commit guard in the same transaction attempt.
  Expected: `target_diverged`.
- Same-target locking is enforced with Postgres row-level locking, not a frontend lock or in-memory mutex alone.
  Expected: integration proof against real Postgres.

## 10. Manifest Ledger Tests

- Accepted PDCP appends manifest ledger entries in the same order as the change blocks.
  Expected: ordered ledger entries linked to the accepted PDCP log row.
- Rejected PDCP does not append manifest ledger entries.
  Expected: zero new ledger rows.
- Active manifest queries return only entries for the active editing cycle by default.
  Expected: previous-cycle entries excluded unless explicitly requested.
- Ledger history remains readable across SAVE boundaries.
  Expected: include-previous-cycles query returns full append-only history.

## 11. SAVE Tests

- SAVE snapshots the current canonical target.
  Expected: new `target_snapshots` row with current hash and version.
- SAVE closes the current editing cycle and opens a new active cycle.
  Expected: exactly one active cycle remains.
- SAVE preserves append-only PDCP log history.
  Expected: no log deletion or rewrite.
- SAVE preserves manifest ledger history while default reads shift to the new active cycle.
  Expected: prior ledger rows remain queryable.
- SAVE failure does not clear active context or create a partial new cycle.
  Expected: original active cycle remains active; no orphaned snapshot/cycle state.

## 12. Replay Tests

- Replay reconstructs the current target from the initial canonical target plus accepted PDCP log entries in order.
  Expected: reconstructed hash equals current target hash.
- Replay ignores `current_pdcp_files`.
  Expected: current pending display state does not affect reconstruction.
- Replay ignores manifest ledger and snapshots as authoritative history.
  Expected: reconstruction succeeds using accepted logs alone.
- Corrupted accepted PDCP log content rejects replay.
  Expected: `replay_protocol_invalid` or `replay_transaction_invalid`, depending on failure mode.
- Corrupted accepted `after_hash` rejects replay.
  Expected: `replay_hash_mismatch`.

## 13. MCP Upload, Context, Submission, And Export Tests

- `patchdiff_handle_upload` accepts UTF-8 text content and initializes target state.
  Expected: target metadata returned with version `0`, current hash, and active editing cycle.
- Upload creates initial snapshot and editing cycle.
  Expected: snapshot reason `initial_upload`, one active cycle.
- `patchdiff_build_prompt_context` includes target metadata, active manifest summary, user request, PDCP rules, and relevant target context.
  Expected: no frontend-only assumptions in payload.
- `patchdiff_submit_pdcp` stores the submission in `current_pdcp_files` before validation.
  Expected: current row exists with `pending_validation` and submitted content.
- Valid `.pdcp` submission returns accepted result to the MCP caller.
  Expected: accepted status, log ID, before/after hashes, incremented version.
- Invalid `.pdcp` submission returns structured diagnostics to the MCP caller.
  Expected: rejected status, failure reason, failure detail, and failed change ID when relevant.
- `patchdiff_get_target` returns current canonical target state.
  Expected: current content/hash/version match `cloud_target_files`.
- `patchdiff_export_target` returns exported current target content.
  Expected: no mutation, content equals canonical target.

## 14. MCP Regeneration Orchestration Tests

- Rejected initial submission produces a rejected PDCP log row.
  Expected: `status = rejected` with failure metadata.
- `patchdiff_get_regeneration_context` returns current target metadata, active manifest summary, rejection diagnostics, and PDCP rules.
  Expected: regeneration context is deterministic and based on current canonical state.
- `patchdiff_build_regeneration_prompt` constructs an MCP orchestration prompt package from deterministic rejection context.
  Expected: prompt construction stays outside the deterministic core runtime.
- `patchdiff_request_regeneration`, if retained, is treated as an MCP orchestration tool and any regenerated `.pdcp` returns through `patchdiff_submit_pdcp` as a new attempt, not a rewrite of the rejected attempt.
  Expected: new `pdcp_log_id`, preserved prior rejected row, `parent_pdcp_log_id` linkage present when configured.
- Regenerated PDCP is validated from scratch against current canonical target.
  Expected: same parser/validator/applier path as any other submission.
- Accepted regenerated PDCP does not erase the rejected parent attempt.
  Expected: both log rows remain visible.
- Rejected regenerated PDCP also remains logged.
  Expected: new rejected row exists with its own failure metadata.
- Regeneration attempt counters and sources are recorded when the orchestration layer provides them.
  Expected: `regeneration_attempt` and `regeneration_source` fields populated consistently.

## 15. Core Boundary And Bypass Tests

- MCP orchestration cannot write directly to `cloud_target_files.current_content`.
  Expected: target mutation happens only through accepted core runtime transaction flow.
- MCP orchestration cannot mark a rejected attempt as accepted.
  Expected: accepted rows exist only when the deterministic core returns success.
- Regenerated PDCP cannot be applied directly by the MCP layer.
  Expected: regenerated content must pass through `patchdiff_submit_pdcp` and full validation.
- Core runtime never calls a model, never calls an MCP tool, and never constructs prompts during validation.
  Expected: no model/MCP hooks invoked from deterministic core tests.
- Model output is always treated as untrusted until validation succeeds.
  Expected: malformed or stale PDCP stays rejected even if delivered by orchestration.

## Coverage Expectations

The later coding pass should include:

- pure runtime unit tests for parser, canonicalization, matcher, disambiguation, and failure mapping
- Postgres integration tests for atomicity, locking, SAVE, and replay
- MCP contract tests for upload, prompt context, submit, regeneration, SAVE, replay, and export

Do not use SQLite to prove persistence correctness, row-level locking, SAVE semantics, or replay correctness.
