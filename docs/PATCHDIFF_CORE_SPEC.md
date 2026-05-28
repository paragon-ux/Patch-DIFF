# PATCHDIFF_CORE_SPEC.md

## Purpose

This document defines the deterministic PatchDIFF core runtime.

The core runtime accepts declarative `.pdcp` files and canonical target text. It validates protocol structure, validates transaction applicability, applies exact `MATCH/REPLACE` changes sequentially in memory, commits atomically, logs accepted and rejected attempts, supports SAVE, and supports deterministic replay.

The core runtime is deterministic and trusted.

PDCP files are untrusted data.

## Core Contract

```text
canonical UTF-8 target text
+ declarative .pdcp transaction
+ exact deterministic MATCH
+ immediate sequential REPLACE
+ atomic commit
+ append-only PDCP log
+ accepted-only manifest ledger
+ SAVE checkpointing
+ deterministic replay
```

## PDCP File Type

PDCP files use the `.pdcp` extension.

PDCP is not Python, JavaScript, JSON, YAML, Markdown, or any target language.

The runtime may be implemented in Python, but PDCP must never be executed by Python.

PDCP is a protocol-native declarative transaction format.

## Protocol Header

The MVP PDCP header should be protocol-native:

```text
PDCP 0.2.3
target_file_id: <id>
target_type: <content-type>
target_hash: <optional-sha256>
```

`target_file_id` is required.

`target_type` is recommended.

`target_hash` is optional and acts as a precondition when supplied.

Do not use Python-style `C = "..."` as the primary target declaration.

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
- optional `target_hash`
- optional `expected_current_hash`

Rejected transactions use:

```text
before_hash = hash at validation time
after_hash = null
```

## Manifest Requirements

Each change must include a manifest immediately before its corresponding `MATCH/REPLACE` block.

Required fields:

- `change_id`
- `intent`
- `input_state`
- `output_state`
- `affected_region`
- `user_visible_change`
- `risk`

Valid `risk` values:

- `low`
- `medium`
- `high`

Manifest line format:

```text
# field_name: value
```

Parsing rules:

- first colon separates field from value
- additional colons remain part of value
- required values must not be empty
- duplicate manifest fields are invalid
- multiline manifest values are not supported in MVP
- duplicate `change_id` values within one PDCP are invalid

## MATCH/REPLACE Format

Each change uses:

```text
<<<<<<< MATCH
exact current target-native text
=======
exact desired target-native text
>>>>>>> REPLACE
```

Rules:

- `MATCH` must be non-empty after canonicalization
- `REPLACE` may be empty
- empty `REPLACE` means deletion
- whitespace-only `REPLACE` is valid
- zero-length cursor insertion is not supported
- insertion must be anchored replacement of existing non-empty text

## Structural Purity

PDCP structural regions are:

- protocol header
- manifest comments
- disambiguation comments
- text outside `MATCH/REPLACE` payloads

Payload regions are:

- `MATCH` text
- `REPLACE` text

Reject obvious executable logic outside payloads:

- imports
- functions
- classes
- loops
- conditionals
- shell commands
- dynamic evaluation
- filesystem calls
- network calls
- tool calls

Payloads may contain code-like text because target files may contain code.

The runtime must never execute payload text.

## Matching Semantics

`MATCH` is an exact optimistic concurrency precondition.

Matching is:

- exact
- case-sensitive
- whitespace-sensitive after canonicalization
- multiline
- left-to-right over Unicode codepoint positions
- performed over the full current in-memory buffer

The runtime must not perform:

- fuzzy matching
- semantic matching
- token matching
- language-aware matching
- fallback matching
- automatic repair

A `MATCH` block must resolve to exactly one span unless disambiguation resolves multiple exact matches to exactly one span.

## Disambiguation

Supported fields:

- `anchor_before`
- `anchor_after`
- `occurrence_index`
- `region_hint`
- `target_hash`

Disambiguation is applied only after multiple exact `MATCH` occurrences are found.

Resolution algorithm:

1. Find all exact full-span `MATCH` occurrences in current buffer.
2. If zero, reject.
3. If one, select it.
4. If multiple, start with all occurrences in left-to-right order.
5. If `occurrence_index` is present, interpret it as 1-based over the global exact occurrence list.
6. If valid, filter to that candidate.
7. If `anchor_before` is present, retain candidates where anchor appears before the candidate span.
8. If `anchor_after` is present, retain candidates where anchor appears after the candidate span.
9. `region_hint` is advisory only and must not select by itself.
10. Exactly one candidate must remain.

If multiple exact occurrences exist and no disambiguation is present, reject with `match_ambiguous`.

If disambiguation fails to resolve exactly one candidate, reject with `disambiguation_invalid`.

## Sequential Mutation

A PDCP file is one atomic transaction containing ordered changes.

Changes execute sequentially against the progressively updated in-memory buffer.

```text
Change 1 sees original target.
Change 2 sees target after Change 1.
Change N sees target after Changes 1..N-1.
```

Do not resolve all matches against the original target before applying replacements.

After a span is selected, apply `REPLACE` immediately to the in-memory buffer.

Commit only after every change succeeds.

## Failure Reasons

PDCP rejection reasons:

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

Replay-only reasons:

```text
replay_hash_mismatch
replay_protocol_invalid
replay_transaction_invalid
```

Do not create new core failure labels without updating tests and docs.

## match_absent vs sequential_match_invalid

If change N, where N > 1, fails to match the current in-memory buffer, and the same `MATCH` text would have matched the original transaction-start buffer, return `sequential_match_invalid`.

Otherwise return `match_absent`.

Both failures reject the full transaction atomically.

## Atomic Commit

A successful commit atomically persists:

- updated target content
- updated target hash
- updated target version
- accepted PDCP log entry
- accepted manifest ledger entries

If any step fails:

- target remains unchanged
- rejected PDCP log is appended when possible
- manifest ledger receives no accepted entries
- `after_hash = null`

No committed target state may exist without a corresponding accepted PDCP log entry.

No accepted manifest ledger entry may exist without a corresponding accepted PDCP log entry.

## Commit Guard

Each submit request should include at least one of:

- `expected_target_version`
- `expected_current_hash`

For Postgres, lock target row during validation/application/commit:

```sql
SELECT *
FROM cloud_target_files
WHERE target_file_id = :target_file_id
FOR UPDATE;
```

Do not allow two commits to the same target to interleave.

Different targets should be able to commit concurrently.

## SAVE

SAVE is checkpoint and active-context compaction.

SAVE must:

- snapshot current canonical target
- close current editing cycle
- create new active editing cycle
- preserve PDCP log
- preserve manifest ledger history
- make default manifest-ledger reads return only active cycle entries

SAVE must not delete append-only history.

If SAVE fails, the existing target, active cycle, logs, and ledger remain intact.

## Replay

Replay reconstructs target state from:

```text
initial canonical target
+ ordered accepted PDCP log entries
```

Replay must not depend on:

- `current_pdcp_file`
- manifest ledger
- snapshots
- current materialized target

Replay algorithm:

1. Load initial canonical target.
2. For each accepted PDCP log entry in order:
   - parse PDCP by protocol version
   - validate protocol
   - apply deterministically against replay buffer
   - compute hash
   - compare with logged `after_hash`
3. Return reconstructed target if all hashes match.

Hash mismatch returns `replay_hash_mismatch`.
