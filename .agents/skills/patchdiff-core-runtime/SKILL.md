---
name: patchdiff-core-runtime
description: "Use when implementing or reviewing the deterministic PatchDIFF core runtime: typed and .pdcp parsing, protocol validation, canonicalization, exact MATCH/REPLACE, overlapping match enumeration, disambiguation, sequential application, runtime-derived change facts, and stage-aware validity reporting."
---

# PatchDIFF Core Runtime Skill

## Core Boundary

The PatchDIFF core runtime (`backend/app/core/`, `backend/app/pdcp/`) is pure and deterministic.

It receives declarative transactions (`patchdiff-tx/1` typed edits, `patchdiff-tx/2` guarded operations or `0.2.3` legacy `.pdcp` text) and validates them against canonical target state.

The core runtime may:

- parse `patchdiff-tx/1`, `patchdiff-tx/2` and `0.2.3` transaction formats
- validate protocol structure and transaction applicability
- enumerate exact `MATCH` occurrences (including overlapping spans in `patchdiff-mvp-0.2.2`)
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

PatchDIFF supports four declarative transaction input formats:

1. **Typed transaction (`patchdiff-tx/1`, primary)**:
   - Structured JSON: `target_file_id`, required guard (`expected_target_version` and/or `expected_current_hash`), top-level `intent`, ordered `edits[]`.
   - Each edit contains required `match` and `replace`, plus optional advisory `change_id`, `rationale`, `risk`, and disambiguation fields (`occurrence_index`, `anchor_before`, `anchor_after`).
   - Parsed by `backend/app/pdcp/typed.py`. Delimiter-collision-free; minimal mandatory prose overhead.
2. **Guarded operations (`patchdiff-tx/2`)**: explicit ordered match/span records via patchdiff_submit_operations; mandatory guard, exact expected_text, sequential canonical code-point spans and explicit empty-span insertion on immutable 0.3.0.
3. **Sole replacement (`patchdiff-tx/3`)** via patchdiff_submit_replacement, mandatory guards and immutable0.4.0. It supports exactly one explicit replace_all, never a mixed transaction. Fresh service size limits are not replay/parser restrictions.
4. **Legacy `.pdcp` (v0.2.3, frozen)**:
   - Declarative plain text with `PDCP 0.2.3` header, 7 required manifest fields per block, and `<<<<<<< MATCH` / `=======` / `>>>>>>> REPLACE` delimiters.
   - Parsed by `backend/app/pdcp/parser.py`. Retained for backward compatibility and historical replay.

None of these formats is executable code. All lower into `ParsedPDCP` and execute through the shared `apply_pdcp_transaction` applier.

## Line Endings & Canonical Target Text

Target text in memory and Postgres must always be LF-normalized UTF-8 (`\n`).

Incoming CRLF (`\r\n`) and CR (`\r`) must be normalized to LF before processing.

Exact string matching operates on character code-points, case-sensitive and whitespace-sensitive.

Invalid submission strings, including nested metadata, must reject before normal hashing/storage if they contain unpaired surrogates or NUL. The service stores reversible ASCII-escaped rejection evidence; pure validation helpers must not depend on SQLAlchemy or transport. Valid Unicode and valid-input canonical hashes remain unchanged.

## Match Enumeration & Overlapping Spans

In `patchdiff-mvp-0.2.2`, string searching enumerates **all exact occurrences**, including overlapping matches:

```python
# app/pdcp/matcher.py
def find_exact_occurrences(target_text: str, match_text: str, *, overlapping: bool = True) -> tuple[MatchSpan, ...]:
    ...
```

For legacy replay under `patchdiff-mvp-0.1.0`, non-overlapping stepping (`index += len(pattern)`) is preserved.

If pattern is not found: return `match_absent`.
If multiple occurrences have empty disambiguation: return match_ambiguous. A nonempty advisory-only mapping returns disambiguation_invalid. Supplied selecting constraints that fail return disambiguation_invalid, including for one occurrence under the current profile.

## Disambiguation

When a `MATCH` pattern occurs multiple times in the current buffer, explicit disambiguation is required:

1. `occurrence_index` (1-based integer index among all matches, matching `patchdiff_find_occurrences`).
2. `anchor_before` (literal substring occurring anywhere preceding the intended match in the buffer).
3. `anchor_after` (literal substring occurring anywhere following the intended match in the buffer).
4. Legacy `region_hint` is advisory-only in `0.2.3`; it never selects a candidate. Typed edits do not accept it.

Under 0.2.2 every supplied selector must hold even for one occurrence. A singleton without selecting fields succeeds; legacy region_hint alone remains advisory. Older recorded profiles retain the singleton early return during replay.

Anchors are not required to be strictly adjacent to the match; they match as substrings anywhere within the preceding or following buffer text. If the disambiguator does not isolate exactly one occurrence, reject with `disambiguation_invalid`.

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
- `matched_chars`: length (character count) of matched text
- `replacement_chars`: length (character count) of replacement text
- `matched_sha256`: SHA-256 hash of matched text
- `replacement_sha256`: SHA-256 hash of replacement text

These facts are returned in `change_facts` and persisted in `append_only_manifest_ledger.derived_json`.

## Stage-Aware Validity Reporting

Use the actual `ValidationStage` reached (C2), not a failure-code guess. Known-target malformed attempts are durably rejected; missing/malformed target identity cannot create a target-linked attempt.

| Stage | Meaning on rejection | `protocol_valid` | `transaction_valid` |
| --- | --- | --- | --- |
| `PRECONDITION_GUARD` | Missing/unknown target, missing required guard, invalid or stale version/hash metadata before decode | `null` | `null` |
| `PROTOCOL_VALIDATION` | Structural decode/validation, invalid attempt metadata or lineage | `false` | `null` |
| `TRANSACTION_APPLICABILITY` | Structurally valid proposal cannot apply: absent/ambiguous/sequential match or a legacy header hash that disagrees with the live target after protocol validation | `true` | `false` |
| `COMMIT_GUARD` | Simulation succeeded but final target-integrity guard fails | `true` | `true` |
| `ACCEPTED` | Transaction accepted | `true` | `true` |

`null` means the phase was not reached, not false. Header/manifest hash inconsistency remains a protocol failure; a pre-parse hash guard mismatch remains a precondition failure. Parent lineage or attempt validation can reject before the transaction body is decoded; their stage is `PROTOCOL_VALIDATION`.

`task_correct` and `semantic` always report `"not_evaluated"`. A true transaction-valid result at a failed commit guard proves simulation, not a committed update or task correctness.

## Atomic Commit Result

The transaction is the smallest atomic unit:
- If all edits apply successfully: target advances to `new_version`, `new_hash` is computed, and `change_facts` are emitted.
- If any edit fails: target remains unchanged, failure reason and diagnostic are surfaced, and `after_hash = null`.

## F01 rejection context

Keep immutable `diagnostic.failure_context` separate from response-only fresh `current_context`. Capture only the actual failing buffer prefix (at most 256 code points), counts and prior simulated changes; label canonical versus intermediate state and use transaction-start canonical observed hash/version. Do not retain an unbounded failed buffer, alter verdicts/profiles/fingerprints, retrofit old diagnostics, commit caller transactions or release their locks. Explicit unavailable contexts cover malformed/missing targets and unlocked local state. MCP_TOOLS specifies fields and actual compact ASCII-escaped JSON byte caps:4096 per context and8192 combined including wrapper keys. Tests must cover non-BMP/escapes, sequential buffers, refreshed recovery after later edits, audit/ledger nonmutation and caller rollback.

## Pass A additions

Follow docs/usability/PASS-A-decision.md and normative contracts: tx/2 ordered match/span operations use mandatory guards, exact expected text, sequential canonical code-point spans and explicit empty-span insertion through the shared applier/profile 0.3.0. Old formats/profiles/fingerprints remain unchanged; no replace_all yet. Correlation is opt-in response-only UUID metadata. Persist bounded exact failure candidates/query once; compute response-only bounded near misses only after service-owned commit/lock release, or explicitly omit for caller ownership. Preserve all original recovered diagnostics and actual byte/work budgets. Run focused PG/stdio matrices while iterating; root runs one consolidated full verification/review per user-authorized pass.

## Pass B additions

Follow docs/usability/PASS-B-decision.md: explicit tx/3 sole whole-target replacement uses immutable0.4.0, mandatory guards, inclusive raw/result byte/code-point admission limits and existing-key recovery before stricter fresh admission; old formats/profiles/identity remain unchanged. Read-only LF line ranges use coherent column observations and bounded offset continuation. Zero-audit advisory preview shares submit's evaluator and preserves every managed table/caller transaction, with no request-key option or submit-rollback. Publish bounded discovery examples and execute every advertised pair over actual stdio/PG. Implement the whole batch before root's final suite/manual/review; avoid routine intermediate test loops. Data/performance evidence is local synthetic only.
