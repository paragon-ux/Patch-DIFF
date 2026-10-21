# MCP_FIRST_MVP.md

## Guarded operations and diagnostics (Pass A)

`patchdiff_submit_operations` adds mandatory-guard `patchdiff-tx/2` explicit sequential match/span operations on frozen profile 0.3.0 through the same locked submit/applier/ledger/replay path. Old typed/legacy records and identities remain unchanged. MCP_TOOLS and usability/PASS-A-decision.md define exact span expected text/insertion, optional response correlation, bounded immutable exact candidates and response-only near misses after service-owned lock release (caller-owned transactions explicitly omit). No fuzzy application, replace_all, optional typed guards or normalized request identity is added.

## Purpose

PatchDIFF is an MCP-first, server-side deterministic document transaction service.

The user interacts through an MCP-enabled host or chatbot. PatchDIFF exposes MCP tools over stdio JSON-RPC (and an internal Python registry), stores canonical target state in Postgres, provides authoritative bounded reads and exact occurrence search, validates declarative edit transactions (`patchdiff-tx/1` typed primary and `.pdcp` v0.2.3 frozen legacy) deterministically, applies accepted edits atomically per target, logs all accepted and rejected attempts in an append-only log with retry lineage and `client_request_id` idempotency, records accepted edits in an append-only manifest ledger with runtime-derived span/hash facts, supports SAVE checkpointing, export, and deterministic replay, and returns structured stage-aware validity and evidence to the caller.

Architecture decisions and primary external evidence (E1–E8): [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built implementation record: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

## Architecture

```text
PatchDIFF server = deterministic transaction runtime + authoritative read/commit service
MCP = transport/interface (stdio JSON-RPC adapter + internal registry)
Host / Chatbot / Model = planning, context selection, proposal generator, retry owner
Postgres = canonical working substrate
```

The host/model proposes edits either as a **typed transaction** (`patchdiff_submit_edits`, preferred) or as a legacy `.pdcp` v0.2.3 document (`patchdiff_submit_pdcp`). Both paths lower into the same `ParsedPDCP` representation and execute through the same deterministic `apply_pdcp_transaction` applier.

The product surface is the MCP server, not a standalone frontend, web app, or rich editor.

## System Boundaries

### PatchDIFF Deterministic Core (`backend/app/core/`, `backend/app/pdcp/`)

May:
- decode and validate `patchdiff-tx/1` typed transaction records and `.pdcp` (`0.2.3`) files
- enumerate all exact `MATCH` occurrences (including overlapping spans in `patchdiff-mvp-0.2.2`)
- resolve explicit disambiguation (`occurrence_index`, `anchor_before`, `anchor_after`, and legacy `region_hint` in `0.2.3`)
- simulate sequential `MATCH/REPLACE` operations in memory and compute `change_facts` (`span_start`, `span_end`, char counts, SHA-256 digests)
- reject invalid transactions without target mutation
- classify stage-aware validity (`ValidationStage` -> `protocol_valid`, `transaction_valid`, `task_correct: "not_evaluated"`, `semantic: "not_evaluated"`)

Must not:
- call an LLM or hold model credentials
- call MCP tools or import SQLAlchemy / FastAPI / Postgres drivers
- construct prompts or run an agent loop
- execute model-generated code
- silently repair malformed inputs
- perform fuzzy, semantic, AST, or language-aware matching
- partially commit failed transactions

### PatchDIFF Service & MCP Layer (`backend/app/services/`, `backend/app/mcp/`)

May:
- receive upload/initialization events (`patchdiff_initialize_target`, `patchdiff_handle_upload`)
- serve authoritative bounded reads (`patchdiff_read_target`) and exact occurrence search (`patchdiff_find_occurrences`)
- enforce state precondition guards (`expected_target_version` and/or `expected_current_hash`, required on `patchdiff_submit_edits`)
- enforce `client_request_id` idempotency and lost-response outcome recovery under row-level `FOR UPDATE` locking
- submit typed or `.pdcp` transactions through the unified service commit path
- return accepted results (with `validity` and `evidence.changes`) or rejected results (with format-specific `diagnostic` and stage-aware `validity`)
- execute `patchdiff_save`, `patchdiff_replay`, `patchdiff_export_target`, `patchdiff_get_target`, `patchdiff_get_pdcp_log`, and `patchdiff_get_manifest_ledger`
- expose `patchdiff_build_prompt_context` as a labelled convenience prefix (`context_truncated`) and `patchdiff_get_regeneration_context` / `patchdiff_build_regeneration_prompt` / `patchdiff_request_regeneration` as deprecated compatibility wrappers

Must not:
- mutate `cloud_target_files.current_content` outside the single service commit path (`submit_edits` / `submit_pdcp`)
- execute transaction payload content
- mark rejected attempts as accepted
- delete append-only history
- apply retried transactions without full validation from scratch

## Core Invariants

- Every transaction (`patchdiff-tx/1` or `.pdcp` v0.2.3) is declarative, non-executable, and untrusted until validated.
- Atomicity is **per target**: all edits in a submission succeed together or zero edits are committed.
- Target mutation occurs only through accepted `submit_edits` or `submit_pdcp` commits under `SELECT ... FOR UPDATE`.
- Rejected attempts are logged in `append_only_pdcp_logs` and never mutate `cloud_target_files`.
- `append_only_manifest_ledger` is accepted-only and records `origin` (`'typed'` or `'pdcp_manifest'`) plus `derived_json` runtime facts.
- Retried submissions after rejection are independent attempts (`parent_pdcp_log_id`, `attempt`) validated from scratch.
- Retried submissions after a lost response using the same `(target_file_id, client_request_id)` and payload recover the recorded terminal outcome (`deduplicated: true`) without re-applying the edit.
- SAVE creates a `save_checkpoint` snapshot and advances the active editing cycle without mutating target content.
- Replay reconstructs state from the initial upload snapshot plus ordered accepted logs, dispatching on `(protocol_version, runtime_version)` and reporting component-level `materialized_state_checks`.
- Postgres is the required persistence backend; SQLite must never be used to claim persistence, locking, migration, SAVE, or replay correctness.
