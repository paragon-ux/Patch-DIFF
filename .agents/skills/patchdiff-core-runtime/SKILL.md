---
name: patchdiff-core-runtime
description: Use when implementing or reviewing the deterministic PatchDIFF core runtime: .pdcp parsing, protocol validation, canonicalization, exact MATCH/REPLACE, disambiguation, transaction application, and failure labels.
---

# PatchDIFF Core Runtime Skill

## Core Boundary

PatchDIFF core runtime is deterministic.

It receives declarative `.pdcp` transaction files and validates them against canonical target state.

The core runtime may:

- parse `.pdcp` files
- validate protocol structure
- validate transaction applicability
- apply accepted transactions atomically
- reject invalid transactions without target mutation
- return structured rejection diagnostics
- support deterministic replay inputs

The core runtime must not:

- call an LLM
- call an MCP tool
- construct prompts
- choose a model
- hold model credentials
- run an agent loop
- silently repair submitted PDCP
- perform fuzzy matching
- perform semantic matching
- perform automatic merge
- partially commit a failed transaction
- execute model-generated code

Every PDCP, however produced, is untrusted until validated by the deterministic core runtime.

## PDCP File Boundary

PDCP files use the `.pdcp` extension.

PDCP is a declarative PatchDIFF transaction format, not Python, JavaScript, C, JSON, YAML, or any target language.

The trusted runtime may be implemented in Python, for example as `changeOperator.py`.

The `.pdcp` file itself must never be executable.

Keep this boundary:

```text
.pdcp file = declarative transaction artifact
.py file = trusted runtime implementation
target file = Markdown/Python/YAML/JSON/prose/etc.
```

Do not use Python-style target declarations as the primary PDCP header.

Use protocol-native PDCP headers defined in `PDCP_FORMAT.md`.

## Forbidden PDCP Content

Do not introduce into `.pdcp` files:

- executable recursion functions
- generated `applyPDCP` functions
- imports
- loops
- conditionals
- runtime logic
- tool calls
- shell commands
- network calls
- filesystem calls

Payloads may contain code-like text when that text belongs to the target file.

Executable-looking text inside `MATCH` or `REPLACE` payloads is opaque target-native text.

Executable logic outside payloads is invalid.

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

Do not apply NFC, NFD, NFKC, or NFKD normalization.

Use one shared canonicalization helper.

## Hashing

Use SHA-256 over UTF-8 bytes of canonicalized target text.

Use one shared hash helper.

Required hash concepts:

- `current_hash`
- `before_hash`
- `after_hash`
- optional `target_hash`
- optional `expected_current_hash`

For rejected transactions:

```text
before_hash = hash at validation time
after_hash = null
```

## MATCH/REPLACE Semantics

`MATCH` is an exact optimistic concurrency precondition.

`REPLACE` is target-native replacement text.

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

A `MATCH` block must match exactly one span unless disambiguation resolves multiple exact occurrences to exactly one span.

Zero matches reject.

Multiple unresolved matches reject.

## Sequential Mutation

A PDCP file is one atomic transaction containing ordered changes.

Changes are evaluated sequentially against the progressively updated in-memory buffer.

```text
Change 1 sees the original target.
Change 2 sees the target after Change 1.
Change 3 sees the target after Changes 1 and 2.
```

Do not resolve all `MATCH` blocks against the original target before applying replacements.

After each selected `MATCH` span is replaced, mutate the in-memory buffer immediately.

Commit only the final buffer after every change succeeds.

## Deletion And Insertion

Deletion:

```text
non-empty MATCH + empty REPLACE = deletion
```

Whitespace-only `REPLACE` is valid.

Zero-length `MATCH` is invalid.

Pure insertion must be represented as anchored replacement:

```text
<<<<<<< MATCH
Existing anchor text
=======
Existing anchor text

Inserted content.
>>>>>>> REPLACE
```

Do not implement cursor insertion in the MVP.

## Disambiguation

Disambiguation applies only after multiple exact `MATCH` occurrences are found.

Supported fields:

- `anchor_before`
- `anchor_after`
- `occurrence_index`
- `region_hint`
- `target_hash`

Resolution algorithm:

```text
1. Find all exact full-span MATCH occurrences in the current in-memory buffer.
2. If zero occurrences exist, reject.
3. If exactly one occurrence exists, select it.
4. If multiple occurrences exist, start with all exact occurrences in left-to-right order.
5. If occurrence_index is present, interpret it as 1-based over the global list of exact occurrences.
6. If occurrence_index is valid, filter to that one candidate.
7. If anchor_before is present, retain candidates where anchor_before appears before the candidate span.
8. If anchor_after is present, retain candidates where anchor_after appears after the candidate span.
9. region_hint is advisory only and must not select a candidate.
10. If exactly one candidate remains, select it.
11. If zero or multiple candidates remain, reject with disambiguation_invalid.
```

If multiple exact occurrences exist and no disambiguation is present, return `match_ambiguous`.

If disambiguation is present but does not resolve exactly one candidate, return `disambiguation_invalid`.

## Failure Labels

Use only the canonical failure enum from `PATCHDIFF_CORE_SPEC.md` and `TEST_MATRIX.md`.

Core PDCP rejection reasons include:

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

Replay-only failure reasons include:

```text
replay_hash_mismatch
replay_protocol_invalid
replay_transaction_invalid
```

Do not create new failure labels without updating the controlling build docs and tests.

## match_absent vs sequential_match_invalid

When a `MATCH` fails during a later change, distinguish ordinary absence from sequential invalidity.

Rule:

```text
If change N, where N > 1, fails to match the current in-memory buffer,
and the same MATCH text would have matched the original transaction-start buffer,
return sequential_match_invalid.

Otherwise return match_absent.
```

Both failures reject the full transaction atomically.

## Atomic Application Result

A PDCP file is the smallest atomic commit unit.

No target mutation may be committed until:

- parsing succeeds
- protocol validation succeeds
- target exists
- hash/version guards pass
- every `MATCH` resolves exactly once or disambiguates exactly once
- every replacement succeeds in memory
- final hash is computed

If any step fails:

- target remains unchanged
- failure is surfaced with a canonical failure reason
- `after_hash = null`

The core runtime should return a deterministic result object that the service/persistence layer can use to commit accepted transactions or log rejected transactions.
