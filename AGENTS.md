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
2. `docs/MODERNIZATION_ARCHITECTURE.md` (architecture decisions A1–A8, contracts C1–C6, and hypothesis reconciliation)
3. `docs/MODERNIZATION_CHANGE_DOC.md` (current product change record: formats, compatibility and verification scope)
4. `docs/MCP_TOOLS.md` (MCP tool schemas and request/response contracts)
5. `docs/PATCHDIFF_CORE_SPEC.md` (deterministic runtime, validation stages, replay profiles)
6. `docs/DATA_MODEL.md` (Postgres schema and migrations `0001`, `0002` and `0003`)
7. `docs/PDCP_FORMAT.md` (`patchdiff-tx/1` typed edits, `patchdiff-tx/2` guarded operations, `patchdiff-tx/3` sole replacement, and pointer to `docs/LEGACY_COMPATIBILITY.md`)
8. `docs/MCP_FIRST_MVP.md` (system boundaries and workflows)
9. `docs/HOST_INTEGRATION_GUIDE.md` (host-owned loop and usage guide)
10. `docs/LEGACY_COMPATIBILITY.md` (frozen `.pdcp` v0.2.3 syntax, `patchdiff_submit_pdcp`, deprecated regeneration wrappers, and historical replay profiles)
11. `docs/PatchDIFF-Concept-Paper-6.md` (modernized conceptual whitepaper: theoretical model, edit-method comparison, design rationale, tradeoffs, and research hypotheses)
12. `docs/TEST_MATRIX.md`, `docs/CODEX_BUILD_PLAN.md` & `backend/tests/verification/README.md` (verification matrix and offline evaluation methodology)

Concept Paper v6 (`docs/PatchDIFF-Concept-Paper-6.md`) is the current explanation of PatchDIFF's theoretical model, design rationale, tradeoffs, and research claims. For executable API schemas, persistence behavior, runtime profiles, and exact limits, use the current normative specifications and implementation (`AGENTS.md` and items 2–10 above). Concept Paper v5 (`docs/PatchDIFF-Concept-Paper-5.md`) remains an unchanged historical record.

Historical design records (`docs/PatchDIFF-Concept-Paper-5.md`, `docs/PatchDIFF-Protocol-Spec-v0.2.3.md`, `docs/PatchDIFF-Implementation-Spec-v0.2.3.md`, `docs/PatchDIFF-Snapshot.md`, `docs/phase_prompts/`, `docs/Archive/`) are preserved untouched for historical context. Goal F decision records, accepted plans, verification captures and the earlier as-built reconciliation record (`docs/usability/`, including `docs/usability/internal/MODERNIZATION_CHANGE_DOC-973ba79.md`) and review reports (`docs/reviews/`) are likewise preserved at their recorded revisions.

If ambiguity remains, preserve PatchDIFF’s locked invariants and choose the simplest deterministic behavior.

## Transaction Input Formats (`patchdiff-tx/1` Edits, `patchdiff-tx/2` Operations, `patchdiff-tx/3` Replacement, Frozen Legacy `.pdcp`)

PatchDIFF supports four declarative, non-executable transaction input formats that lower into the same `ParsedPDCP` representation and execute through the same `apply_pdcp_transaction` applier:

1. **Typed transaction (`patchdiff_submit_edits` / `protocol_version = "patchdiff-tx/1"`, preferred)**:
   - Structured JSON arguments (`target_file_id`, required `expected_target_version` and/or `expected_current_hash`, required transaction `intent`, ordered `edits[]` with `{match, replace, change_id?, rationale?, risk?, occurrence_index?, anchor_before?, anchor_after?}`, optional `client_request_id`, `parent_pdcp_log_id`, `attempt`).
   - Eliminates delimiter-collision failures and reduces mandatory prose overhead to top-level `intent`.
   - Persisted in `append_only_pdcp_logs.pdcp_content` as deterministic canonical JSON (`patchdiff-tx/1`).
2. **Guarded operations (`patchdiff_submit_operations` / `patchdiff-tx/2`)**: ordered explicit match/span operations with intent and mandatory hash/version guard; sequential code-point spans require exact `expected_text`. Zero-length insertion is explicit span behavior, never empty `MATCH`. Shared applier and immutable `0.3.0` profile; `tx/1` and legacy histories/profiles remain unchanged. No `replace_all` operation in `0.3.0`. Optional span `expected_before`/`expected_after` adjacency guards record immutable `0.5.0`; records without them keep `0.3.0`.
3. **Sole replacement (`patchdiff_submit_replacement` / `patchdiff-tx/3`)**: explicit guarded `replace_all` through the shared applier and immutable `0.4.0` profile, with bounded fresh admission (`1,000,000` code points and `1,048,576` UTF-8 bytes, raw and canonical) and one full-span ledger fact. Replay does not reapply fresh admission limits.
4. **Legacy PDCP file (`patchdiff_submit_pdcp` / `protocol_version = "0.2.3"`, frozen legacy/import in `docs/LEGACY_COMPATIBILITY.md`)**:
   - Raw `.pdcp` text with `PDCP 0.2.3` header, 7 required `# MANIFEST` fields per change block, and `<<<<<<< MATCH` / `=======` / `>>>>>>> REPLACE` delimiters.
   - Retained for backward compatibility and replay of historical logs.

Keep this boundary:

```text
patchdiff-tx/1, patchdiff-tx/2, patchdiff-tx/3 or .pdcp = declarative, non-executable transaction artifact
backend/app/*.py = trusted deterministic runtime and service implementation
target file = Markdown / Python / YAML / JSON / prose / etc.
```

None of `patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3` or `.pdcp` is executable code.

Submitted edit-string values and nested metadata must be valid UTF-8/PostgreSQL text before normal hashing/storage. Known-target invalid text is durably rejected through the shared locked path using reversible ASCII-escaped evidence in existing TEXT fields and safe JSONB markers. Never silently repair it or store decoded surrogate/NUL text. Valid hashes and historical fingerprints remain unchanged.

## Core Runtime Boundary

PatchDIFF core runtime (`backend/app/core/`, `backend/app/pdcp/`) is pure and deterministic.

It may:

- parse and validate `.pdcp` (`0.2.3`), typed edits (`patchdiff-tx/1`), guarded operations (`patchdiff-tx/2`) and sole replacements (`patchdiff-tx/3`)
- enumerate all exact `MATCH` occurrences (including overlapping spans in `patchdiff-mvp-0.2.2`)
- resolve explicit disambiguation (`occurrence_index`, `anchor_before`, `anchor_after`, or legacy `region_hint` in `0.2.3`)
- simulate sequential exact `MATCH/REPLACE` and guarded explicit span operations in memory and compute `change_facts` (`span_start`, `span_end`, char counts, SHA-256 digests)
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
- **Authoritative bounded reads & exact search**: `patchdiff_read_target` (`start`, `length`, `next_start`), `patchdiff_read_lines` (inclusive LF ranges and range-relative `next_offset`), `patchdiff_find_occurrences` (`text`, `context_chars`, `start_occurrence`, `max_results`, `next_occurrence_index`)
- **Guarded atomic transaction submission**: `patchdiff_submit_edits` (typed matches), `patchdiff_submit_operations` (guarded match/span), `patchdiff_submit_replacement` (sole explicit whole-target replacement) and `patchdiff_submit_pdcp` (legacy `.pdcp`), each supporting `client_request_id` idempotency and `parent_pdcp_log_id` retry lineage
- **Advisory evaluation**: `patchdiff_preview` uses a coherent observation and the shared read-only evaluator, with bounded facts/diagnostics and no audit, retry key or mutation; later submission rechecks its guards.
- **Checkpointing, replay, and bounded history**: `patchdiff_save`, `patchdiff_replay`, `patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`
- **Convenience / deprecated compatibility wrappers**: `patchdiff_build_prompt_context` (convenience bounded prefix), and deprecated `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`

## Expected Modernized Host Workflow

```text
1. User uploads or initializes document -> patchdiff_initialize_target.
2. Host reads relevant slices or searches occurrences -> patchdiff_read_target / patchdiff_read_lines / patchdiff_find_occurrences.
3. Host/model optionally previews, then submits guarded edits -> patchdiff_preview, then patchdiff_submit_edits / patchdiff_submit_operations (or patchdiff_submit_replacement for an explicit whole-document rewrite), with expected_target_version/expected_current_hash and optional client_request_id.
4. PatchDIFF validates deterministically and commits atomically (or logs rejection with format-specific diagnostics and stage validity).
5. On rejection, host inspects diagnostics, re-reads via patchdiff_read_target / patchdiff_find_occurrences, and resubmits with parent_pdcp_log_id.
6. Host checkpoints cycles with patchdiff_save, verifies integrity with patchdiff_replay, and exports via patchdiff_export_target.
```

## Goal F diagnostics, preview and admission

Recorded decisions: `docs/usability/F01-decision.md`, `docs/usability/PASS-A-decision.md`, `docs/usability/PASS-B-decision.md`. Normative contract: `docs/MCP_TOOLS.md` ("Guarded editing, reads, preview and diagnostics").

- Rejection evidence is bounded: immutable `diagnostic.failure_context` (at most 256 code points of the actual failing buffer, as a prefix or a window around a known failure location), bounded exact candidates and the near-miss query. `current_context` and near misses are response-only; near misses run after a service-owned commit releases the lock and are omitted for caller-owned transactions. No fuzzy application or automatic choice is permitted.
- Submission correlation is opt-in UUID invocation metadata, never request identity.
- `patchdiff_preview` and `patchdiff_read_lines` are advisory, read-only observations; submission always re-locks and rechecks guards.
- tx/3 fresh admission (1,000,000 code points and 1,048,576 UTF-8 bytes, raw and canonical) runs after request-key recovery/conflict and never during replay.
- PR #11 friction follow-up (`docs/usability/friction-followup-decision.md`): one shared `retryable` definition; advisory accepted-transaction warnings (no-op, `occurrence_index` basis shift, grapheme split) that never change a verdict and that replay ignores; source line endings recorded at upload (migration `0003`) with honoured export formats, while canonical LF storage and hashes stay unchanged.
- PR #14 performance follow-up (`SVC-001` & `MCP-001`): post-commit near-miss diagnostics use exact positional pigeonhole prefiltering plus an Ukkonen-banded Landau–Vishkin Levenshtein DP (`backend/app/services/near_miss_service.py`) while preserving identical bounded scan caps (`<= 64` query code points, `65,536` buffer code points, `1,000,000` DP cells) and tie-break order; `patchdiff_get_pdcp_log` (default `include_content=False`) and `patchdiff_get_manifest_ledger` (default `include_previous_cycles=False`) project bounded `intent` / `transaction_intent` and `rationale` in SQL via PostgreSQL 16+ `pg_input_is_valid(..., 'jsonb')` and `LATERAL` without loading multi-megabyte `pdcp_content` blobs.

## Non-Negotiable Invariants

Structural batch extension: the existing `patchdiff_observe_scope` accepts
bounded `selections` and the existing `patchdiff_submit_observed_operations`
accepts guarded `groups`. Each group uses its original scope-local sequential
buffer through the shared applier; descending assembly commits one target
version, accepted log and complete observation linkage atomically. The internal
durable pair is `patchdiff-observed-batch/1` / `patchdiff-observed-batch-r1`;
replay verifies every authoritative scope without Waymark. Additive migration
`20261027_0005` follows `20261026_0004`, preserving historical single linkage and
refusing destructive downgrade. See [the batch contract](docs/STRUCTURAL_BATCH_EDITING.md).

External MCP uses immutable startup `PATCHDIFF_MCP_PROFILE`: default `editor`
advertises and permits exactly 7 tools; `unobserved` 5, `observed` 6 and explicit
compatibility `full` all 22. Trusted lifecycle/legacy clients opt into `full`;
the internal registry retains all handlers. Strict observed service admission
remains independent. The frozen comparative Gate 2 stays closed.

PatchDIFF must always preserve:

```text
canonical UTF-8 target text (LF normalized)
+ declarative non-executable transactions (patchdiff-tx/1, patchdiff-tx/2, patchdiff-tx/3 and PDCP 0.2.3)
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
- Alembic migrations (`20260510_0001`, `20261020_0002` and `20261022_0003`)
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
- Offline payload and verdict equivalence evaluation (`backend/tests/verification/offline_eval.py`)

## PR Review Standard

All PR reviews must follow [PR Review Standard v1.1.0](docs/PR_REVIEW_STANDARD.md). Record the base and head SHAs, map every changed file to a primary category, and give each required category its own coverage statement, separate P1/P2/P3 finding lists, verification gaps, and verdict. Empty reviewed buckets must say so; unreviewed buckets must say not assessed.

Trace architecture and contracts before recommending runtime changes. Keep source inspection, local execution, and CI evidence separate. Passing tests or a prior approval cannot replace category review. Do not recommend approval with unreviewed material categories or unresolved blocking findings.

Store review reports in `docs/reviews/`. Close findings only with a fix commit, relevant evidence, and reviewer recheck. The concise implementation completion report in the testing skill does not replace the required PR review.

Changes to the review format require a versioned change to `docs/PR_REVIEW_STANDARD.md`; reviewers must not silently omit categories or weaken evidence requirements.

## Skills

Use the workspace skills in `.agents/skills/`:

- `.agents/skills/patchdiff-core-runtime/SKILL.md`: Deterministic core runtime (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`, and `.pdcp` v0.2.3 parsing, protocol validation, overlapping match enumeration, disambiguation, sequential application, `ValidationStage`, and `change_facts`).
- `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`: MCP tool surface, stdio JSON-RPC adapter, `TYPED_EDIT_JSON_SCHEMA`, authoritative reads/search, host-owned retry, and deprecated wrapper maintenance.
- `.agents/skills/patchdiff-persistence-replay-save/SKILL.md`: Postgres persistence, migrations `0001`, `0002` and `0003`, row locking, `client_request_id` idempotency, SAVE cycles, and profile-dispatched deterministic replay.
- `.agents/skills/patchdiff-testing-review/SKILL.md`: Unit, live Postgres integration, stdio subprocess E2E testing, and documentation consistency review.
