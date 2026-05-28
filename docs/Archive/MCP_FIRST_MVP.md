# MCP_FIRST_MVP.md

## Purpose

This document defines the MCP-first PatchDIFF MVP.

The MVP is not a standalone frontend. The user interacts through a chatbot session. PatchDIFF runs server-side, receives document and edit events over MCP, manages canonical target state, routes prompt context, receives declarative `.pdcp` transaction files, validates them deterministically, applies accepted edits atomically, and returns status or exported target content.

Core architecture:

```text
PatchDIFF server = orchestration + deterministic runtime
MCP = transport/interface
Chatbot/model = PDCP generator
Postgres = canonical working substrate
```

## Product Goal

The MVP proves that PatchDIFF can support iterative document editing without full-document regeneration by using server-managed target state and declarative PDCP transactions.

The user should be able to:

1. Upload a document in the chat session.
2. Have PatchDIFF initialize that document as a canonical cloud target.
3. Request edits through the chatbot.
4. Have PatchDIFF build prompt context automatically.
5. Have the model emit a declarative `.pdcp` transaction.
6. Have PatchDIFF validate, apply, or reject the PDCP deterministically.
7. Have PatchDIFF request regeneration over MCP when validation fails.
8. Have PatchDIFF maintain accepted manifest summaries and full PDCP logs.
9. SAVE/export the current target back to the chat session.
10. Replay accepted transactions for audit and verification.

## Non-Goals

The MVP does not include:

- standalone PatchDIFF frontend
- chat UI implementation
- rich document editor
- semantic validation
- AST-based editing
- fuzzy repair
- automatic merge
- restore-to-version
- multi-writer collaboration
- CRDT or OT collaboration
- production auth
- billing
- delimiter escaping
- length-prefixed payloads
- binary/rich document targets

## User Flow

```text
1. User uploads document in chat.
2. PatchDIFF server receives upload event over MCP.
3. PatchDIFF initializes canonical cloud target.
4. User sends edit request in chat.
5. PatchDIFF constructs prompt context.
6. PatchDIFF sends prompt context through MCP to chatbot/model.
7. Model emits declarative .pdcp transaction.
8. PatchDIFF receives .pdcp response over MCP.
9. PatchDIFF stores it as current pending PDCP.
10. PatchDIFF validates it deterministically.
11. If rejected, PatchDIFF returns diagnostics and requests regeneration through MCP orchestration.
12. Regenerated PDCP is submitted as a new attempt.
13. If accepted, PatchDIFF applies exact MATCH/REPLACE transaction atomically.
14. PatchDIFF appends accepted manifest entries and full PDCP log.
15. PatchDIFF returns status to chat.
16. User may call SAVE/export.
```

## Server Responsibilities

PatchDIFF server owns:

- MCP tool/interface layer
- upload event handling
- target initialization
- canonical target storage
- prompt context construction
- model response ingestion
- current PDCP tracking
- deterministic PDCP validation
- atomic transaction application
- rejected/accepted PDCP logging
- manifest ledger updates
- regeneration orchestration
- SAVE checkpointing
- export/download target behavior
- deterministic replay

## Chatbot/Model Responsibilities

The chatbot/model owns:

- generating `.pdcp` transaction text from prompt context
- regenerating `.pdcp` text when PatchDIFF returns diagnostics

The model must not be treated as trusted.

Every model-emitted PDCP is untrusted until PatchDIFF validates it.

## PDCP Artifact Boundary

PDCP files use `.pdcp`.

PDCP is declarative and must not contain executable functions, recursion, imports, loops, shell commands, network calls, filesystem calls, or tool calls.

The trusted runtime applies PDCP through exact `MATCH/REPLACE` semantics.

Do not implement model-generated `applyPDCP` functions.

Do not execute model-generated code.

## Deterministic Core Runtime

The deterministic core runtime performs:

- `.pdcp` parsing
- protocol validation
- target lookup
- canonicalization
- hash/version precondition checks
- exact `MATCH` validation
- disambiguation
- sequential in-memory `REPLACE`
- atomic commit
- rejected/accepted logging
- manifest ledger append on accepted transactions only
- SAVE
- replay

The core runtime must not:

- call a model
- call MCP tools
- construct prompts
- repair submitted PDCP
- perform fuzzy matching
- perform semantic matching
- perform automatic merge
- partially commit failed transactions

## Regeneration Orchestration

Regeneration is in scope for the MCP/server orchestration layer.

When validation fails:

1. Core runtime rejects deterministically.
2. Rejected attempt is logged when possible.
3. Server receives structured diagnostics.
4. Server constructs regeneration prompt context.
5. Server routes the regeneration request through MCP.
6. Model emits a new `.pdcp`.
7. Server submits the new `.pdcp` as a new transaction attempt.
8. Core runtime validates from scratch.

A regenerated PDCP never bypasses validation.

## SAVE And Export

SAVE is checkpointing and active manifest context compaction.

On SAVE, PatchDIFF should:

- snapshot current canonical target
- close current editing cycle
- create a new active editing cycle
- clear active manifest context by moving to the new cycle
- preserve append-only PDCP log
- preserve manifest ledger history
- export or return current target content through MCP when requested

SAVE must not delete append-only history.

## Persistence

Use Postgres as the MVP persistence backend.

Use Docker Compose for deterministic local Postgres.

SQLite is not the MVP persistence backend.

Required table families:

- users
- projects
- project_memberships
- cloud_target_files
- current_pdcp_files
- append_only_pdcp_logs
- append_only_manifest_ledger
- target_snapshots
- editing_cycles

## Backend Stack

Use:

- Python 3.11+
- FastAPI or equivalent ASGI layer for server runtime
- MCP server tooling appropriate for Python
- Postgres
- SQLAlchemy or SQLModel
- Alembic
- pytest
- Docker Compose

The deterministic runtime core must stay independent of FastAPI, MCP transport, and SQL.

## MVP Acceptance Criteria

The MVP is acceptable when:

- upload event initializes a canonical target
- target content is canonicalized and hashed
- prompt context can be generated from target metadata, relevant spans, and manifest ledger
- model-emitted `.pdcp` can be received over MCP
- valid PDCP can be accepted and applied atomically
- invalid PDCP can be rejected without target mutation
- rejected PDCP produces structured diagnostics
- rejected PDCP can trigger MCP regeneration orchestration
- regenerated PDCP is submitted as a new attempt
- accepted/rejected attempts are logged append-only
- accepted manifest entries are ledgered only on success
- SAVE snapshots target and advances editing cycle
- export returns current canonical target
- replay reconstructs accepted target state and verifies hashes
- core runtime performs no model calls
- core runtime executes no model-generated code
