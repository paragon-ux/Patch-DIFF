# AGENTS.md

## Project

PatchDIFF is an MCP-first, server-side deterministic document transaction service.

PatchDIFF server receives document-upload, read/search, and edit-submission requests over MCP, manages canonical target state in Postgres, validates untrusted edit transactions deterministically, applies accepted edits atomically per target, logs all accepted and rejected attempts in an append-only log with retry lineage and request idempotency, records accepted changes in an append-only manifest ledger with runtime-derived span/hash facts, and supports SAVE checkpointing, export, and deterministic replay.

Core architecture:

```text
PatchDIFF server = deterministic transaction runtime + authoritative read/commit service
MCP = transport/interface (stdio JSON-RPC / internal registry)
Host / Chatbot / Model = planning, context selection, proposal generator, retry owner
Postgres = canonical working substrate
```

The user interacts with the host/chatbot, not with a standalone PatchDIFF frontend.

PatchDIFF is not a chat UI, rich document editor, semantic patch language, AST rewrite engine, fuzzy matcher, automatic merge system, or full-document regeneration workflow.

## Source Of Truth & Precedence

Read project artifacts in this order:

1. `AGENTS.md` (locked invariants)
2. `docs/MODERNIZATION_ARCHITECTURE.md` (architecture decisions A1–A8 and contracts C1–C6)
3. `docs/MODERNIZATION_CHANGE_DOC.md` (as-built record, reconciliation table, verification evidence)
4. `docs/MCP_TOOLS.md` (MCP tool schemas and request/response contracts)
5. `docs/PATCHDIFF_CORE_SPEC.md` (deterministic runtime, validation stages, replay profiles)
6. `docs/DATA_MODEL.md` (Postgres schema and migrations `0001` + `0002`)
7. `docs/PDCP_FORMAT.md` (`patchdiff-tx/1` typed record and frozen PDCP v0.2.3 format)
8. `docs/MCP_FIRST_MVP.md` (system boundaries and workflows)
9. `docs/HOST_INTEGRATION_GUIDE.md` (host-owned loop and usage guide)
10. `docs/TEST_MATRIX.md` & `docs/CODEX_BUILD_PLAN.md`

Historical design records (`docs/PatchDIFF-Concept-Paper-5.md`, `docs/PatchDIFF-Protocol-Spec-v0.2.3.md`, `docs/PatchDIFF-Implementation-Spec-v0.2.3.md`, `docs/PatchDIFF-Snapshot.md`, `docs/phase_prompts/`, `docs/Archive/`) are preserved untouched for historical context.

If ambiguity remains, preserve PatchDIFF’s locked invariants and choose the simplest deterministic behavior.

## Transaction Input Formats (`patchdiff-tx/1` Primary, `.pdcp` v0.2.3 Frozen Legacy)

PatchDIFF supports two declarative, non-executable transaction input formats that lower into the same `ParsedPDCP` representation and execute through the same `apply_pdcp_transaction` applier:

1. **Typed transaction (`patchdiff_submit_edits` / `protocol_version = "patchdiff-tx/1"`, preferred)**:
   - Structured JSON arguments (`target_file_id`, required `expected_target_version` and/or `expected_current_hash`, required transaction `intent`, ordered `edits[]` with `{match, replace, change_id?, rationale?, risk?, occurrence_index?, anchor_before?, anchor_after?}`, optional `client_request_id`, `parent_pdcp_log_id`, `attempt`).
   - Eliminates delimiter-collision failures and reduces mandatory prose overhead to top-level `intent`.
   - Persisted in `append_only_pdcp_logs.pdcp_content` as deterministic canonical JSON (`patchdiff-tx/1`).
2. **Legacy PDCP file (`patchdiff_submit_pdcp` / `protocol_version = "0.2.3"`, frozen legacy/import)**:
   - Raw `.pdcp` text with `PDCP 0.2.3` header, 7 required `# MANIFEST` fields per change block, and `<<<<<<< MATCH` / `=======` / `>>>>>>> REPLACE` delimiters.
   - Retained for backward compatibility and replay of historical logs.

Keep this boundary:

```text
patchdiff-tx/1 or .pdcp = declarative, non-executable transaction artifact
backend/app/*.py = trusted deterministic runtime and service implementation
target file = Markdown / Python / YAML / JSON / prose / etc.
```

Neither `patchdiff-tx/1` nor `.pdcp` is executable code.

## Core Runtime Boundary

PatchDIFF core runtime (`backend/app/core/`, `backend/app/pdcp/`) is pure and deterministic.

It may:

- parse and validate `.pdcp` (`0.2.3`) and typed (`patchdiff-tx/1`) transactions
- enumerate all exact `MATCH` occurrences (including overlapping spans in `patchdiff-mvp-0.2.0`)
- resolve explicit disambiguation (`occurrence_index`, `anchor_before`, `anchor_after`, or legacy `region_hint` in `0.2.3`)
- simulate sequential `MATCH/REPLACE` operations in memory and compute `change_facts` (`span_start`, `span_end`, char counts, SHA-256 digests)
- reject invalid transactions without target mutation
- classify stage-aware validity (`ValidationStage` -> `protocol_valid`, `transaction_valid`, `task_correct: "not_evaluated"`, `semantic: "not_evaluated"`)
- support deterministic replay across recorded `(protocol_version, runtime_version)` profiles

It must not:

- call an LLM or hold model credentials
- call an MCP tool or depend on FastAPI / SQLAlchemy / Postgres
- construct prompts or run an agent loop
- silently repair submitted transactions
- perform fuzzy, semantic, or AST matching
- perform automatic merge or partial commits
- execute model-generated code

## MCP Service & Host Boundary

The host/agent owns planning, context gathering, proposal generation, and retry decisions.

The PatchDIFF MCP service provides:

- **Target initialization & retrieval**: `patchdiff_handle_upload`, `patchdiff_initialize_target`, `patchdiff_get_target`, `patchdiff_export_target`
- **Authoritative bounded reads & exact search**: `patchdiff_read_target` (`start`, `length`, `next_start`), `patchdiff_find_occurrences` (`text`, `context_chars`, `start_occurrence`, `max_results`, `next_occurrence_index`)
- **Guarded atomic transaction submission**: `patchdiff_submit_edits` (primary typed input) and `patchdiff_submit_pdcp` (legacy `.pdcp`), both supporting `client_request_id` idempotency and `parent_pdcp_log_id` retry lineage
- **Checkpointing, replay, and bounded history**: `patchdiff_save`, `patchdiff_replay`, `patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`
- **Convenience / deprecated compatibility wrappers**: `patchdiff_build_prompt_context` (convenience bounded prefix), and deprecated `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`

## Expected Modernized Host Workflow

```text
1. User uploads or initializes document -> patchdiff_initialize_target.
2. Host reads relevant slices or searches occurrences -> patchdiff_read_target / patchdiff_find_occurrences.
3. Host/model submits guarded edits -> patchdiff_submit_edits (with expected_target_version/expected_current_hash and optional client_request_id).
4. PatchDIFF validates deterministically and commits atomically (or logs rejection with format-specific diagnostics and stage validity).
5. On rejection, host inspects diagnostics, re-reads via patchdiff_read_target / patchdiff_find_occurrences, and resubmits with parent_pdcp_log_id.
6. Host checkpoints cycles with patchdiff_save, verifies integrity with patchdiff_replay, and exports via patchdiff_export_target.
```

## Non-Negotiable Invariants

PatchDIFF must always preserve:

```text
canonical UTF-8 target text (LF normalized)
+ declarative non-executable transactions (patchdiff-tx/1 and PDCP 0.2.3)
+ exact deterministic MATCH (all exact occurrences counted)
+ immediate sequential in-memory REPLACE simulation
+ per-target atomic Postgres commit under SELECT ... FOR UPDATE
+ append-only attempt log (accepted and rejected, with lineage and client_request_id idempotency)
+ accepted-only manifest ledger (with origin and runtime-derived span/hash facts)
+ stage-accurate validity reporting and format-specific diagnostics
+ SAVE checkpointing and editing-cycle rotation
+ deterministic replay dispatching on (protocol_version, runtime_version) with component-level materialized_state_checks
```

## Backend Requirements & Runtime Layers

Use:

- FastAPI
- Postgres (`postgres:16.3-alpine` via Docker Compose)
- SQLAlchemy 2.x
- Alembic migrations (`20260510_0001` and `20261020_0002`)
- pytest
- Stdio MCP JSON-RPC adapter (`backend/app/mcp/external_adapter.py`)

Keep runtime layers separate:

1. MCP transport & tool layer (`backend/app/mcp/`)
2. Service layer (`backend/app/services/`)
3. Typed & PDCP parsers/validators (`backend/app/pdcp/`)
4. Deterministic matcher, disambiguator, and applier (`backend/app/pdcp/`, `backend/app/core/`)
5. Postgres persistence layer (`backend/app/storage/`, `backend/app/migrations/`)

## Testing Rule

Do not claim completion unless relevant tests pass against live Postgres:

- Pure runtime unit tests (`backend/tests/unit/`)
- Postgres integration tests (`backend/tests/integration/`), including live Alembic `upgrade -> downgrade -> upgrade` and real stdio MCP subprocess E2E workflow
- Offline payload and verdict equivalence evaluation (`evaluation/offline_eval.py`)

## PR Review Standard

All PR reviews must follow [PR Review Standard v1.1.0](docs/PR_REVIEW_STANDARD.md). Record the base and head SHAs, map every changed file to a primary category, and give each required category its own coverage statement, separate P1/P2/P3 finding lists, verification gaps, and verdict. Empty reviewed buckets must say so; unreviewed buckets must say not assessed.

Trace architecture and contracts before recommending runtime changes. Keep source inspection, local execution, and CI evidence separate. Passing tests or a prior approval cannot replace category review. Do not recommend approval with unreviewed material categories or unresolved blocking findings.

Store review reports in `docs/reviews/`. Close findings only with a fix commit, relevant evidence, and reviewer recheck. The concise implementation completion report in the testing skill does not replace the required PR review.

Changes to the review format require a versioned change to `docs/PR_REVIEW_STANDARD.md`; reviewers must not silently omit categories or weaken evidence requirements.

## Skills

Use the workspace skills in `.agents/skills/`:

- `.agents/skills/patchdiff-core-runtime/SKILL.md`: Deterministic core runtime (`patchdiff-tx/1` and `.pdcp` v0.2.3 parsing, protocol validation, overlapping match enumeration, disambiguation, sequential application, `ValidationStage`, and `change_facts`).
- `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`: MCP tool surface, stdio JSON-RPC adapter, `TYPED_EDIT_JSON_SCHEMA`, authoritative reads/search, host-owned retry, and deprecated wrapper maintenance.
- `.agents/skills/patchdiff-persistence-replay-save/SKILL.md`: Postgres persistence, migrations `0001` and `0002`, row locking, `client_request_id` idempotency, SAVE cycles, and profile-dispatched deterministic replay.
- `.agents/skills/patchdiff-testing-review/SKILL.md`: Unit, live Postgres integration, stdio subprocess E2E testing, and documentation consistency review.
