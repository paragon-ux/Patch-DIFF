---
name: patchdiff-testing-review
description: Use when adding tests, reviewing implementation, verifying completion, or checking for PatchDIFF protocol and MCP-first architecture drift.
---

# PatchDIFF Testing And Review Skill

## Completion Rule

Do not claim completion unless relevant tests pass.

Changes touching parser, validator, matcher, applier, persistence, SAVE, replay, MCP orchestration, or regeneration flow must include or update tests.

Use `TEST_MATRIX.md` as the complete source of truth once it exists.

Do not rely on SQLite to prove persistence correctness.

Do not assume a frontend.

## Core Parser And Protocol Tests

Required categories:

- valid minimal `.pdcp` parses
- protocol-native PDCP header parses
- missing protocol header rejects
- missing target ID rejects
- malformed target header rejects
- missing manifest rejects
- missing required manifest field rejects
- duplicate manifest field rejects
- invalid risk rejects
- duplicate `change_id` rejects
- malformed `MATCH/REPLACE` block rejects
- empty `MATCH` rejects
- delimiter collision rejects deterministically
- executable logic outside payload rejects
- executable-looking text inside payload is allowed

## MATCH Tests

Required categories:

- exact single match succeeds
- zero match rejects
- duplicate match rejects
- disambiguated duplicate succeeds
- invalid disambiguation rejects
- case mismatch rejects
- whitespace mismatch rejects
- multiline match succeeds
- CRLF target canonicalizes to LF
- Unicode-equivalent but codepoint-different strings do not silently normalize

## Replacement Tests

Required categories:

- empty `REPLACE` deletes
- whitespace-only `REPLACE` succeeds
- anchored insertion succeeds
- zero-length insertion rejects

## Sequential Mutation Tests

Required categories:

- second change sees first change's replacement
- second change against original state returns `sequential_match_invalid`
- overlapping sequential edits succeed when valid
- overlapping sequential edits fail when invalid

## Transaction Tests

Required categories:

- one failed change rolls back all changes
- rejected PDCP appends log when possible but does not append manifest ledger
- accepted PDCP appends log and manifest ledger
- `before_hash` and `after_hash` are correct
- target hash mismatch rejects
- target version mismatch rejects
- target divergence rejects
- accepted transaction mutates only selected `MATCH` spans

## Postgres Integration Tests

Required categories:

- Alembic migrations create schema
- accepted transaction is atomic
- rejected transaction does not mutate target
- row-level locking prevents same-target interleaving
- different targets can commit independently
- target version/hash guards work
- append-only PDCP log is preserved
- accepted-only manifest ledger is preserved
- rejected attempts remain visible
- regeneration attempts are separate log entries
- SAVE snapshots and advances editing cycle
- SAVE failure does not clear active context
- replay reconstructs target from accepted logs
- altered log causes replay hash mismatch

## MCP Contract Tests

Required categories:

- upload event initializes target
- upload event creates initial snapshot and editing cycle
- prompt context is constructed from target metadata, manifest ledger, and relevant spans
- model PDCP response is stored as pending current PDCP
- submitted PDCP reaches deterministic core runtime
- accepted PDCP returns success status to MCP caller
- rejected PDCP returns structured diagnostics to MCP caller
- regeneration prompt is constructed after rejection
- regenerated PDCP is submitted as a new attempt
- regenerated PDCP is validated from scratch
- MCP orchestration cannot bypass core validation
- MCP orchestration cannot write directly to target content
- export returns current canonical target
- SAVE can be triggered through MCP
- replay can be triggered through MCP

## Regeneration Flow Tests

Required categories:

- `match_absent` maps to context refresh recommendation
- `match_ambiguous` maps to disambiguation recommendation
- malformed PDCP maps to format-fix recommendation
- regenerated PDCP creates a new attempt
- regenerated accepted PDCP does not erase prior rejected attempt
- regenerated rejected PDCP remains logged
- regeneration retry limits, if implemented, are adapter policy
- core runtime never calls model/MCP during validation
- model/MCP output is treated as untrusted until core validation succeeds

## Review Mode

If the user asks for a review, prioritize findings.

Report:

- correctness bugs
- MCP-first architecture drift
- executable-PDCP drift
- frontend-first assumptions
- protocol drift
- atomicity violations
- replay inconsistencies
- duplicate logic
- missing tests
- unclear failure labels
- SAVE/history violations
- security-boundary violations
- hidden mutation outside selected `MATCH` spans
- direct target writes from MCP orchestration
- SQLite usage as MVP persistence

Findings should come before summaries.

If no findings are found, state that clearly and mention residual risks or testing gaps.

## Code Quality Checks

Before adding a helper, search for existing implementations.

Watch for duplicate logic in:

- canonicalization
- hashing
- PDCP header parsing
- manifest parsing
- failure labels
- exact occurrence detection
- disambiguation
- transaction application
- replay
- SAVE cycle handling
- MCP tool response shapes
- regeneration diagnostic mapping

Repeated functions with similar behavior are a review finding.

Prefer one shared implementation.

## Verification

Run the narrowest useful test command first.

Then run the broader suite when feasible.

Do not claim tests passed unless they were actually run.

If tests cannot be run, state:

- what was not run
- why it was not run
- what command should be run next

## Git Safety

You may be in a dirty worktree.

Never revert user changes unless explicitly asked.

Never use destructive commands such as:

```text
git reset --hard
git checkout -- <path>
```

unless explicitly approved.

Do not amend commits unless explicitly requested.

If unexpected unrelated changes appear, stop and ask the user how to proceed.

Keep edits focused and avoid broad refactors unless necessary.

## Final Response Shape

When reporting work, be concise.

Prefer:

```text
Implemented X.

Changed:
- path/to/file.py
- tests/test_file.py

Verified:
- pytest ...

Notes:
- ...
```

List tests run.

List tests not run.

Do not paste large files unless requested.

Do not claim completion without verification.
