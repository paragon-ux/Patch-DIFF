# CODEX_BUILD_PLAN.md

## Scope

This document defines the implementation order for a later coding pass.

This pass is documentation-only.

Do not implement runtime source code, package files, Docker files, migrations, tests, or source modules yet.

## Planning Rules

- follow `docs/AGENTS.md`, `docs/MCP_FIRST_MVP.md`, `docs/PATCHDIFF_CORE_SPEC.md`, and `docs/MCP_TOOLS.md` first
- keep MCP orchestration separate from the deterministic core runtime
- keep Postgres as the MVP persistence backend
- keep frontend or debug-console work deferred
- do not introduce executable PDCP, fuzzy matching, semantic matching, AST parsing, automatic merge, or partial commit paths

## Phase 1. Repo/Backend Scaffold

Goal:

- establish the backend-oriented project layout for MCP orchestration, service coordination, deterministic core modules, persistence, and tests

Acceptance criteria:

- repo structure clearly separates orchestration, service, deterministic core, and persistence layers
- no frontend-first architecture is introduced
- no chat UI or standalone PatchDIFF web app is introduced
- docs remain the source of truth for the implementation layout

## Phase 2. Docker Compose Postgres

Goal:

- add deterministic local Postgres development infrastructure through Docker Compose

Acceptance criteria:

- local Postgres version is pinned and reproducible
- local environment supports row-level locking and transactional integration testing
- SQLite is not used as the MVP persistence backend

## Phase 3. Alembic/Postgres Schema

Goal:

- implement the schema defined in `DATA_MODEL.md`

Acceptance criteria:

- migrations create `users`, `projects`, `project_memberships`, `cloud_target_files`, `current_pdcp_files`, `append_only_pdcp_logs`, `append_only_manifest_ledger`, `target_snapshots`, and `editing_cycles`
- append-only history tables are modeled correctly
- one active editing cycle per target is enforced
- foreign keys and indexes support SAVE, replay, and regeneration lineage

## Phase 4. Core Canonicalization And Hashing

Goal:

- implement shared canonicalization and SHA-256 hashing helpers for targets and PDCP payloads

Acceptance criteria:

- UTF-8, LF normalization, tab preservation, space preservation, trailing whitespace preservation, final newline preservation, and no Unicode normalization are implemented once
- one shared hash helper computes SHA-256 over canonical UTF-8 bytes
- helpers are storage-agnostic and transport-agnostic

## Phase 5. PDCP Parser

Goal:

- parse the protocol-native `.pdcp` format defined in `PDCP_FORMAT.md`

Acceptance criteria:

- parser recognizes `PDCP 0.2.3`, `target_file_id`, `target_type`, optional `target_hash`, manifest blocks, optional disambiguation fields, and `MATCH/REPLACE` blocks
- parser rejects archival `C = ...` headers for the MCP-first MVP
- parser surfaces canonical structural failures without executing payload text

## Phase 6. Protocol Validator

Goal:

- validate parsed PDCP structure and protocol invariants before target application

Acceptance criteria:

- required header and manifest fields are enforced
- invalid `risk`, duplicate manifest fields, duplicate `change_id`, malformed blocks, and delimiter collision are rejected deterministically
- executable logic outside payloads is rejected with canonical failure labels

## Phase 7. Exact Matcher And Disambiguation

Goal:

- implement exact `MATCH` resolution and disambiguation without semantic fallback

Acceptance criteria:

- matching is exact, case-sensitive, whitespace-sensitive after canonicalization, and multiline
- `anchor_before`, `anchor_after`, `occurrence_index`, `region_hint`, and `target_hash` behave per spec
- ambiguous matches reject unless disambiguation isolates exactly one candidate
- no fuzzy, semantic, AST, or language-aware matching is introduced

## Phase 8. Transaction Applier

Goal:

- apply ordered PDCP changes sequentially in memory

Acceptance criteria:

- later changes see the progressively updated buffer
- deletion and anchored insertion behave per `PDCP_FORMAT.md`
- transaction fails atomically on the first invalid change
- no mutation occurs outside the selected exact `MATCH` spans

## Phase 9. Postgres Atomic Commit Flow

Goal:

- connect deterministic core results to a Postgres-backed commit path

Acceptance criteria:

- accepted flow locks the target row with `FOR UPDATE`
- request-level `expected_target_version` precondition failures map to `target_version_mismatch` before validation begins
- request-level `expected_current_hash` and PDCP `target_hash` precondition failures map to `target_hash_mismatch` before validation begins
- target row changes after validation/simulation but before the final commit guard inside the same transaction attempt map to `target_diverged`
- same-target writes do not interleave
- rejected transactions leave target content, hash, and version unchanged

## Phase 10. Logs And Manifest Ledger

Goal:

- persist accepted and rejected PDCP attempts plus accepted-only manifest entries

Acceptance criteria:

- accepted submissions append one PDCP log row and their manifest ledger rows atomically
- rejected submissions append one rejected PDCP log row and zero manifest ledger rows
- regeneration lineage fields are persisted where applicable
- append-only guarantees are enforced by application behavior

## Phase 11. SAVE And Replay

Goal:

- implement checkpointing and deterministic reconstruction

Acceptance criteria:

- SAVE creates a snapshot, closes the active editing cycle, and opens a new active cycle atomically
- SAVE preserves PDCP log and manifest ledger history
- replay reconstructs target state from the initial canonical target plus accepted PDCP log rows
- replay shares parser, canonicalizer, matcher, disambiguator, and applier behavior with live runtime

## Phase 12. MCP Server/Tools

Goal:

- expose the MVP MCP interface defined in `MCP_TOOLS.md`

Acceptance criteria:

- MCP tool surface includes upload, initialize target, build prompt context, submit PDCP, regeneration context, request regeneration, get target, export target, save, replay, PDCP log, and manifest ledger operations
- orchestration and deterministic core remain separate layers
- MCP tools cannot mutate targets directly outside accepted core transactions

## Phase 13. Upload-To-Target Flow

Goal:

- handle uploaded document content and initialize canonical cloud targets

Acceptance criteria:

- UTF-8 validation, canonicalization, initial hashing, initial snapshot creation, and initial editing-cycle creation are wired together
- upload returns target metadata needed for later MCP flows
- no frontend dependency is introduced

## Phase 14. Prompt-Context Builder

Goal:

- build deterministic prompt context packages for the model host

Acceptance criteria:

- context includes target metadata, relevant target spans, active manifest summary, user request, current hash/version, and PDCP rules
- context builder reads canonical state from Postgres-backed services rather than a frontend cache
- context builder stays outside the deterministic core runtime

## Phase 15. PDCP Response Submission Flow

Goal:

- receive model-emitted `.pdcp` content and submit it through the deterministic validation path

Acceptance criteria:

- submission stores current pending PDCP state before validation
- accepted results update target state atomically and return structured success payloads
- rejected results return structured diagnostics and preserve the target unchanged
- no model-generated executable logic is ever executed

## Phase 16. Rejection-To-Regeneration Orchestration

Goal:

- orchestrate fresh regeneration requests after deterministic rejection

Acceptance criteria:

- rejection diagnostics can be converted into regeneration context for MCP
- regenerated PDCP content is submitted as a new attempt with its own lineage metadata
- regenerated PDCP is validated from scratch through the same `patchdiff_submit_pdcp` path
- MCP orchestration never applies regenerated content directly

## Phase 17. Export/Download Current Target

Goal:

- return current canonical target content through MCP

Acceptance criteria:

- export returns current content, content type, version, and hash from canonical Postgres state
- export does not mutate target state
- SAVE can optionally chain into export without bypassing canonical persistence

## Phase 18. Unit And Integration Tests

Goal:

- implement the test suite described in `TEST_MATRIX.md`

Acceptance criteria:

- runtime unit tests cover parser, canonicalization, exact matching, disambiguation, sequential mutation, and failure mapping
- Postgres integration tests cover migrations, atomic commit, row-level locking, SAVE, replay, and append-only history guarantees
- MCP contract tests cover upload, prompt context, submit, rejection diagnostics, regeneration, export, SAVE, replay, and no-bypass guarantees
- tests explicitly prove regenerated PDCP attempts are separate attempts validated from scratch

## Deferred Work

Keep deferred unless explicitly reprioritized:

- frontend or debug console as a primary user surface
- standalone PatchDIFF web app
- semantic validation
- AST parsing
- fuzzy matching
- automatic merge
- restore-to-version UX
- stream-intercepted partial PDCP application
- binary or rich document target handling

## Exit Condition For The Later Coding Pass

The implementation pass should be considered MVP-complete only when:

- upload initializes canonical targets
- prompt context can be built for the model host
- valid `.pdcp` submissions apply atomically
- invalid `.pdcp` submissions reject without mutation
- accepted and rejected attempts are logged append-only
- accepted manifest entries ledger only on success
- SAVE advances editing cycles while preserving history
- replay reconstructs accepted target state deterministically
- MCP orchestration cannot bypass deterministic core validation
