# MCP_FIRST_MVP.md

## Guarded operations and diagnostics

`patchdiff_submit_operations` adds mandatory-guard `patchdiff-tx/2` explicit sequential match/span operations on frozen profile 0.3.0 (0.5.0 when spans use `expected_before`/`expected_after` adjacency guards) through the same locked submit/applier/ledger/replay path. Old typed/legacy records and identities remain unchanged. [MCP_TOOLS.md](MCP_TOOLS.md) defines exact span expected text/insertion, optional response correlation, bounded immutable exact candidates and response-only near misses after service-owned lock release (caller-owned transactions explicitly omit). Exact match/span operations do not allow `replace_all`; explicit whole-target replacement uses its separate `patchdiff_submit_replacement` tool, `patchdiff-tx/3` format and immutable 0.4.0 profile. Typed guards remain required and request identity rules remain unchanged.

`patchdiff_read_lines` provides one-based inclusive LF-only ranges with range-relative and absolute continuation (default 4,000/cap 8,000 code points) from one ordinary column observation under `no_autoflush`. `patchdiff_preview` uses the shared fresh read-only evaluator for all four explicit formats, rejects pending local target changes, and returns bounded advisory facts/hash without audit, locks, writes, commit or rollback. Submission always re-locks and rechecks. Preview payloads cap at 32,768 compact ASCII-escaped JSON bytes with explicit evidence omissions; see the tool reference for per-field limits. Accepted submissions and previews return advisory warnings, and `patchdiff_export_target` restores recorded upload line endings with `format: "original_eol"`.

## Purpose

PatchDIFF is an MCP-first, server-side deterministic document transaction service.

The user interacts through an MCP-enabled host or chatbot. PatchDIFF exposes MCP tools over stdio JSON-RPC (and an internal Python registry), stores canonical target state in Postgres, provides authoritative bounded reads and exact occurrence search, validates declarative edit transactions (`patchdiff-tx/1` typed matches, `patchdiff-tx/2` guarded match/span operations, `patchdiff-tx/3` sole replacement and `.pdcp` v0.2.3 frozen legacy) deterministically, applies accepted edits atomically per target, logs all accepted and rejected attempts in an append-only log with retry lineage and `client_request_id` idempotency, records accepted edits in an append-only manifest ledger with runtime-derived span/hash facts, supports SAVE checkpointing, export, and deterministic replay, and returns structured stage-aware validity and evidence to the caller.

Architecture decisions and primary external evidence (E1–E8): [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built implementation record: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

## Architecture

External MCP defaults to the seven-tool `editor` profile, with server-enforced
`unobserved` (5), `observed` (6) and opt-in compatibility `full` (22). Trusted
lifecycle work uses `full`; strict observed admission remains a separate service
guard. Multi-scope bundles reuse the existing observe/submit tool names and
shared applier, preserving one atomic target commit, audit, SAVE and replay.
[Profiles and scoped batch workflow](STRUCTURAL_BATCH_EDITING.md).

```text
PatchDIFF server = deterministic transaction runtime + authoritative read/commit service
MCP = transport/interface (stdio JSON-RPC adapter + internal registry)
Host / Chatbot / Model = planning, context selection, proposal generator, retry owner
Postgres = canonical working substrate
```

The host/model proposes edits through typed matches (`patchdiff_submit_edits`, `patchdiff-tx/1`, preferred), guarded match/span operations (`patchdiff_submit_operations`, `patchdiff-tx/2`), or explicit sole replacement (`patchdiff_submit_replacement`, `patchdiff-tx/3`). All formats lower into the same `ParsedPDCP` representation and execute through the same deterministic `apply_pdcp_transaction` applier. Frozen legacy `.pdcp` v0.2.3 (`patchdiff_submit_pdcp`) and deprecated regeneration wrappers are documented in [LEGACY_COMPATIBILITY.md](LEGACY_COMPATIBILITY.md).

The product surface is the MCP server, not a standalone frontend, web app, or rich editor.

## Measured System Characteristics (`PR #14`)

| Dimension | Measured Value | Source / Verification |
| --- | --- | --- |
| **Minimal Typed Transaction Wire Overhead (`patchdiff-tx/1`)** | **`151 B`** wire (`206 B` stored) for 1 edit; **`259 B`** wire (`314 B` stored) for 5 edits; **0%** delimiter collisions | `evaluation/offline_eval.py` |
| **Whole-Target Guarded Replacement (`patchdiff-tx/3`)** | **`341 B`** `tools/call` line (`290 B` stored) for small rewrite; fresh admission `<= 1 MB` / `1,000,000` code points | `evaluation/offline_eval.py` |
| **65,536-Code-Point Near-Miss Scan (`SVC-001`)** | **`1.7 ms`** median (`585` cells) on varied prose (**58.9× faster**); **`41.9 ms`** median (`142,255` cells, 100% scanned) on repetitive logs (**16.9× faster**) | `backend/tests/unit/test_friction_followup.py` |
| **20 MB History & Ledger Paging (`MCP-001`, PostgreSQL 16+ `LATERAL`)** | **`14.68 ms`** ledger / **`22.85 ms`** attempt log on `50 × 400 KB` `tx/3` (**16–19× faster**); **`136.72 ms`** log / **`221.59 ms`** ledger on `20 × 1 MB` `tx/1` | `backend/tests/integration/test_friction_followup_live.py` |
| **Hard Response & Context Caps** | `<= 65,536 B` discovery; `<= 8,000` code points per read; `<= 32,768 B` preview; `<= 18,432 B` rejection enrichment | [MCP_TOOLS.md](MCP_TOOLS.md) |

## System Boundaries

### PatchDIFF Deterministic Core (`backend/app/core/`, `backend/app/pdcp/`)

May:
- decode and validate all four transaction formats (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3` and `.pdcp` `0.2.3`)
- enumerate all exact `MATCH` occurrences (including overlapping spans in `patchdiff-mvp-0.2.2`)
- resolve explicit disambiguation (`occurrence_index`, `anchor_before`, `anchor_after`, and legacy `region_hint` in `0.2.3`)
- simulate sequential exact match/span operations or one explicit whole-target replacement in memory and compute `change_facts` (`span_start`, `span_end`, char counts, SHA-256 digests)
- reject invalid transactions without target mutation
- classify stage-aware validity (`ValidationStage` -> `protocol_valid`, `transaction_valid`, `task_correct: "not_evaluated"`, `semantic: "not_evaluated"`)

Must not:
- call an LLM or hold model credentials
- call MCP tools or import SQLAlchemy / FastAPI / Postgres drivers
- construct prompts or run the host retry loop
- execute model-generated code
- silently repair malformed inputs
- perform fuzzy, semantic, AST, or language-aware matching
- partially commit failed transactions

### PatchDIFF Service & MCP Layer (`backend/app/services/`, `backend/app/mcp/`)

May:
- receive upload/initialization events (`patchdiff_initialize_target`, `patchdiff_handle_upload`)
- serve authoritative bounded reads (`patchdiff_read_target`, `patchdiff_read_lines`) and exact occurrence search (`patchdiff_find_occurrences`)
- enforce state precondition guards (`expected_target_version` and/or `expected_current_hash`, required on all three typed submission tools)
- enforce `client_request_id` idempotency and lost-response outcome recovery under row-level `FOR UPDATE` locking
- submit typed or `.pdcp` transactions through the unified service commit path
- return accepted results (with `validity` and `evidence.changes`) or rejected results (with format-specific `diagnostic` and stage-aware `validity`)
- execute `patchdiff_save`, `patchdiff_replay`, `patchdiff_export_target`, `patchdiff_get_target`, `patchdiff_get_pdcp_log`, and `patchdiff_get_manifest_ledger`
- retain legacy compatibility wrappers (`patchdiff_submit_pdcp`, `patchdiff_build_prompt_context`, and deprecated regeneration wrappers) as documented in [LEGACY_COMPATIBILITY.md](LEGACY_COMPATIBILITY.md)

Must not:
- mutate `cloud_target_files.current_content` outside the single service commit path (`submit_edits`, `submit_operations`, `submit_replacement`, `submit_pdcp`)
- execute transaction payload content
- mark rejected attempts as accepted
- delete append-only history
- apply retried transactions without full validation from scratch

## Core Invariants

- Every transaction (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3` or `.pdcp` v0.2.3) is declarative, non-executable, and untrusted until validated.
- Atomicity is **per target**: all edits in a submission succeed together or zero edits are committed.
- Target mutation occurs only through accepted submission commits under `SELECT ... FOR UPDATE`.
- Admitted rejected attempts are logged in `append_only_pdcp_logs` and never mutate `cloud_target_files`.
- `append_only_manifest_ledger` is accepted-only and records `origin` (`'typed'` or `'pdcp_manifest'`) plus `derived_json` runtime facts.
- Retried submissions after rejection are independent attempts (`parent_pdcp_log_id`, `attempt`) validated from scratch.
- Retried submissions after a lost response using the same `(target_file_id, client_request_id)` and payload recover the recorded terminal outcome (`deduplicated: true`) without re-applying the edit.
- SAVE creates a `save_checkpoint` snapshot and advances the active editing cycle without mutating target content.
- Replay reconstructs state from the initial upload snapshot plus ordered accepted logs, dispatching on `(protocol_version, runtime_version)` and reporting component-level `materialized_state_checks`.
- Postgres is the required persistence backend; SQLite must never be used to claim persistence, locking, migration, SAVE, or replay correctness.
