---
name: patchdiff-core-runtime
description: Use when implementing or reviewing the deterministic PatchDIFF core runtime: typed and .pdcp parsing, protocol validation, canonicalization, exact MATCH/REPLACE, overlapping match enumeration, disambiguation, sequential application, runtime-derived change facts, and stage-aware validity reporting.
---

# PatchDIFF Core Runtime Skill

## Core Boundary

The PatchDIFF core runtime (`backend/app/core/`, `backend/app/pdcp/`) is pure and deterministic.

It receives declarative transactions (`patchdiff-tx/1` typed records or `0.2.3` legacy `.pdcp` text) and validates them against canonical target state.

The core runtime may:

- parse `patchdiff-tx/1` and `0.2.3` transaction formats
- validate protocol structure and transaction applicability
- enumerate exact `MATCH` occurrences (including overlapping spans in `patchdiff-mvp-0.2.0`)
- resolve explicit disambiguation (`occurrence_index`, `anchor_before`, `anchor_after`, and legacy `region_hint`)
- simulate sequential `MATCH/REPLACE` operations in memory
- compute runtime-derived `change_facts` (`span_start`, `span_end`, char lengths, SHA-256 digests)
- reject invalid transactions without target mutation
- classify stage-aware validity (`ValidationStage` -> `protocol_valid`, `transaction_valid`, `task_correct`, `semantic`)
- support deterministic replay across recorded `(protocol_version, runtime_version)` profiles

The core runtime must not:

- call an LLM or hold model credentials
- call an MCP tool or depend on FastAPI / SQLAlchemy / Postgres
- construct prompts or run an agent loop
- silently repair submitted transactions
- perform fuzzy, semantic, or AST matching
- perform automatic merge or partial commits
- execute model-generated code

Every transaction, however produced, is untrusted until validated by the deterministic core runtime.

## Transaction Input Formats

PatchDIFF supports two declarative transaction input formats:

1. **Typed transaction (`patchdiff-tx/1`, primary)**:
   - Structured JSON: `target_file_id`, required guard (`expected_target_version` and/or `expected_current_hash`), top-level `intent`, ordered `edits[]`.
   - Each edit contains required `match` and `replace`, plus optional advisory `change_id`, `rationale`, `risk`, and disambiguation fields (`occurrence_index`, `anchor_before`, `anchor_after`).
   - Parsed by `backend/app/pdcp/typed.py`. Delimiter-collision-free; minimal mandatory prose overhead.
2. **Legacy `.pdcp` (v0.2.3, frozen)**:
   - Declarative plain text with `PDCP 0.2.3` header, 7 required manifest fields per block, and `<<<<<<< MATCH` / `=======` / `>>>>>>> REPLACE` delimiters.
   - Parsed by `backend/app/pdcp/parser.py`. Retained for backward compatibility and historical replay.

Neither format is executable code. Both lower into `ParsedPDCP` and execute through the shared `apply_pdcp_transaction` applier.

## Line Endings & Canonical Target Text

Target text in memory and Postgres must always be LF-normalized UTF-8 (`\n`).

Incoming CRLF (`\r\n`) and CR (`\r`) must be normalized to LF before processing.

Exact string matching operates on character code-points, case-sensitive and whitespace-sensitive.

## Match Enumeration & Overlapping Spans

In `patchdiff-mvp-0.2.0`, string searching enumerates **all exact occurrences**, including overlapping matches:

```python
# app/pdcp/matcher.py
def find_all_occurrences(text: str, pattern: str, overlapping: bool = True) -> list[int]:
    ...
```

For legacy replay under `patchdiff-mvp-0.1.0`, non-overlapping stepping (`index += len(pattern)`) is preserved.

If pattern is not found: return `match_absent`.
If pattern occurs multiple times and disambiguation is missing or fails: return `match_ambiguous`.

## Disambiguation

When a `MATCH` pattern occurs multiple times in the current buffer, explicit disambiguation is required:

1. `occurrence_index` (0-based integer index among all matches).
2. `anchor_before` (literal prefix immediately preceding the intended match).
3. `anchor_after` (literal suffix immediately following the intended match).
4. Legacy `region_hint` (line range hint in `0.2.3`).

If the disambiguator does not isolate exactly one occurrence, reject with `disambiguation_invalid`.

## Sequential In-Memory Simulation

Edits in a transaction are applied sequentially to an in-memory buffer:

1. Edit 1 matches against initial transaction-start text.
2. Edit 1 replaces its match in memory, producing intermediate buffer $T_1$.
3. Edit 2 matches against intermediate buffer $T_1$.
4. Repeat for all $N$ edits.

If Edit $k$ ($k > 1$) fails to match $T_{k-1}$:
- Check if Edit $k$'s match text existed in the initial start buffer $T_0$.
- If it existed in $T_0$, return `sequential_match_invalid`.
- Otherwise return `match_absent`.

Both reject the entire transaction atomically.

## Runtime-Derived Change Facts

During sequential application, the applier computes exact runtime facts for each applied change:
- `span_start`: code-point offset where match began in intermediate buffer
- `span_end`: code-point offset where match ended (`span_start + len(match)`)
- `match_length`: length of matched text
- `replace_length`: length of replacement text
- `match_sha256`: SHA-256 hash of matched text
- `replace_sha256`: SHA-256 hash of replacement text

These facts are returned in `change_facts` and persisted in `append_only_manifest_ledger.derived_json`.

## Stage-Aware Validity Reporting

Validation failures are categorized by `ValidationStage`:
- `PROTOCOL_DECODE`: syntax errors, invalid JSON, missing required fields.
- `TARGET_RESOLUTION`: target file not found.
- `CONCURRENCY_GUARD`: `target_version_mismatch`, `target_hash_mismatch`, `target_diverged`.
- `MATCH_RESOLUTION`: `match_absent`, `match_ambiguous`, `disambiguation_invalid`.
- `SEQUENTIAL_SIMULATION`: `sequential_match_invalid`.

The core runtime reports four validity levels:
- `protocol_valid`: boolean
- `transaction_valid`: boolean
- `task_correct`: always `"not_evaluated"` (evaluated by host test runners/linters)
- `semantic`: always `"not_evaluated"` (evaluated by host/user review)

Acceptance means protocol-valid and transaction-valid. It never claims task correctness.

## Atomic Commit Result

The transaction is the smallest atomic unit:
- If all edits apply successfully: target advances to `new_version`, `new_hash` is computed, and `change_facts` are emitted.
- If any edit fails: target remains unchanged, failure reason and diagnostic are surfaced, and `after_hash = null`.
