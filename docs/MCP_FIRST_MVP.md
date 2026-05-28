# MCP_FIRST_MVP.md

## Purpose

PatchDIFF MVP is MCP-first and server-side.

The user interacts through a chatbot/model host. PatchDIFF exposes MCP orchestration tools, stores canonical target state in Postgres, validates declarative `.pdcp` transactions deterministically, applies accepted edits atomically, logs accepted and rejected attempts, supports SAVE/export/replay, and returns structured status to the MCP caller.

This document is the active build source of truth for the current milestone.

## Architecture

```text
PatchDIFF server = MCP orchestration + deterministic runtime
MCP = transport/interface
Chatbot/model = PDCP generator
Postgres = canonical working substrate
```

The model emits declarative PDCP. PatchDIFF owns parsing, validation, exact matching, deterministic application, persistence, SAVE, replay, export, and diagnostics.

The MVP user surface is not a frontend. Do not add a chat UI, standalone web app, rich editor, or debug console as the product surface for this milestone.

## Current Milestone

The next hardening milestone is:

```text
MCP contract tests + MCP E2E tests
```

Manual ChatGPT testing already exposed an important product-boundary risk: chat rendering can corrupt model output, especially PDCP delimiters. The next move is not more manual ChatGPT testing. The next move is automated validation of the MCP tool path, because MCP is the product surface for upload, context, PDCP submission, rejection diagnostics, regeneration, SAVE, replay, and export.

This milestone tests the existing internal MCP tool registry/wrapper layer first. Real external MCP SDK/server adapter wiring is intentionally deferred until the MCP contract and E2E tests exist.

## Boundaries

PatchDIFF deterministic core may:

- parse `.pdcp` files
- validate PDCP structure and protocol invariants
- apply exact `MATCH/REPLACE` transactions in memory
- reject invalid PDCP without target mutation
- return deterministic result objects for persistence

PatchDIFF deterministic core must not:

- call an LLM
- call MCP tools
- construct prompts
- choose a model
- execute model-generated code
- silently repair malformed PDCP
- perform fuzzy, semantic, AST, or language-aware matching
- partially commit failed transactions

MCP orchestration may:

- receive upload events
- initialize canonical targets
- build prompt context
- receive model-emitted `.pdcp` content
- submit PDCP to the deterministic service path
- return accepted/rejected results
- build regeneration context/prompt
- submit regenerated PDCP as a new attempt
- trigger SAVE/replay/export services

MCP orchestration must not:

- mutate `cloud_target_files.current_content` directly
- bypass `patchdiff_submit_pdcp`
- execute PDCP content
- mark rejected attempts as accepted
- delete append-only history
- apply regenerated PDCP without full validation

## Testing Roadmap

```text
DONE / mostly done:
- Phase 1: local runtime confidence
- Phase 2: PDCP format robustness baseline
- unit tests
- integration tests
- manual PDCP smoke test

NEXT:
- Phase 3: internal MCP tool contract tests
- Phase 4: MCP E2E happy/reject/regenerate flows
- Phase 5: model-output robustness through MCP
- Phase 6: SAVE/replay/export through MCP
- Phase 7: real external MCP adapter wiring
- Phase 8: benchmark/evaluation suite
```

## MVP Invariants

- PDCP files use `.pdcp`.
- PDCP is declarative and non-executable.
- Every PDCP is untrusted until validated by PatchDIFF.
- Target mutation comes only from accepted `.pdcp` transactions.
- Rejected PDCP attempts are logged and do not mutate targets.
- Manifest ledger rows are accepted-only.
- Regenerated PDCP is a separate attempt and validates from scratch.
- SAVE creates snapshots and editing-cycle transitions but does not mutate target content.
- Replay reconstructs from the initial canonical target plus accepted PDCP logs.
- Postgres is the MVP persistence backend.
- SQLite must not be used to prove persistence, locking, SAVE, or replay correctness.
