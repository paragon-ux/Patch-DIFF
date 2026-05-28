# CODEX_BUILD_PLAN.md

## Scope

This document defines the next implementation/testing roadmap for PatchDIFF MVP.

The current pass is documentation-only. Do not implement runtime source code, tests, migrations, Docker files, package files, frontend code, or real external MCP adapter wiring in this pass.

## Planning Rules

- Follow `AGENTS.md`, `docs/MCP_FIRST_MVP.md`, `docs/MCP_TOOLS.md`, `docs/PATCHDIFF_CORE_SPEC.md`, `docs/PDCP_FORMAT.md`, `docs/DATA_MODEL.md`, and `docs/TEST_MATRIX.md` first.
- Preserve MCP-first architecture.
- Use the existing internal MCP tool registry/wrapper layer until Phase 7.
- Do not bypass deterministic parser, validator, matcher, applier, or service paths.
- Do not add frontend or chat UI code.
- Do not use SQLite for MVP persistence testing.
- Keep real external MCP adapter wiring deferred until contract/E2E tests exist.

## Done / Mostly Done

- Phase 1: local runtime confidence
- Phase 2: PDCP format robustness baseline
- unit tests
- integration tests
- manual PDCP smoke test

Manual ChatGPT testing exposed model-output rendering risk. That finding now moves into automated MCP product-surface tests.

## Phase 3. Internal MCP Tool Contract Tests

Goal:

- prove every internal MCP tool wrapper calls service-layer workflows and cannot bypass deterministic validation

Acceptance criteria:

- upload/initialize creates canonical target state
- prompt context includes target metadata, current hash/version, user request, relevant target context, manifest summary, and PDCP rules
- valid PDCP accepts through MCP and mutates target
- invalid PDCP rejects through MCP without target mutation
- accepted and rejected PDCP log rows are written
- manifest ledger appends only for accepted PDCP
- SAVE, replay, export, PDCP log, and manifest ledger tools return service-backed payloads
- wrapper code does not directly update `cloud_target_files.current_content`

## Phase 4. MCP E2E Happy / Reject / Regenerate Flows

Goal:

- test the product workflow through MCP/internal tool wrappers without a frontend

Acceptance criteria:

- happy path covers upload, prompt context, valid submit, target read, log read, ledger read, and export
- rejection path covers bad MATCH, `match_absent`, unchanged target, rejected log, and no accepted ledger entry
- regeneration path covers rejected parent, regeneration context, corrected regenerated PDCP, separate accepted child log, and exactly one target mutation

## Phase 5. Model Output Robustness Through MCP

Goal:

- convert manual ChatGPT-rendering failures into automated MCP regression tests

Acceptance criteria:

- corrupted separator delimiters reject
- corrupted REPLACE terminators reject
- extra prose before or after PDCP rejects if unsupported
- blockquote-rendered delimiters reject
- full rewritten document instead of PDCP rejects
- executable apply function outside payload rejects
- malformed manifest rejects
- all corrupted outputs leave target unchanged and log rejected attempts
- regeneration context can be produced for rejected malformed outputs
- raw code-block contents PDCP submits successfully

## Phase 6. SAVE / Replay / Export Through MCP

Goal:

- prove durable workflow operations work through the actual MCP-facing interface

Acceptance criteria:

- MCP SAVE creates snapshot and editing-cycle transition
- MCP SAVE does not mutate target content/hash/version
- MCP replay reconstructs current hash
- MCP replay ignores `current_pdcp_files`
- MCP replay ignores manifest ledger as operational truth
- MCP export returns current content, target type, version, and hash

## Phase 7. Real External MCP Adapter Wiring

Goal:

- wire the real external MCP SDK/server adapter after internal contract tests exist

Acceptance criteria:

- external MCP adapter exposes the same tool names and payload semantics
- Phase 3-6 E2E tests or equivalent transport tests pass through real MCP transport
- adapter calls the same service layer as internal wrappers
- adapter does not bypass `patchdiff_submit_pdcp`
- no frontend, model UI, or chat UI is added

## Phase 8. Benchmark / Evaluation Suite

Goal:

- measure product reliability and regression behavior over representative MCP workflows

Acceptance criteria:

- benchmark suite includes valid PDCP acceptance, malformed-output rejection, regeneration recovery, SAVE/replay/export consistency, and basic latency/log-integrity measurements
- benchmark scenarios use MCP tool paths rather than direct parser/applier calls
- benchmark outputs are reproducible enough for later CI or release gating

## Deferred Work

Keep deferred unless explicitly reprioritized:

- frontend/debug console
- chat UI implementation
- stream-intercepted partial PDCP handling
- restore-to-version
- rich/binary document targets
- semantic validation
- AST parsing
- fuzzy repair
- production auth/billing
- external MCP adapter before Phase 7

## Exit Condition For This Milestone

The milestone is complete when MCP contract and E2E tests prove:

- upload initializes canonical targets
- prompt context can be built through MCP
- valid `.pdcp` applies atomically through MCP submit
- invalid or malformed `.pdcp` rejects without mutation through MCP submit
- accepted and rejected attempts are append-only logged
- accepted manifest entries ledger only on success
- regeneration creates separate attempts validated from scratch
- SAVE/replay/export work through MCP
- MCP orchestration cannot bypass deterministic core validation
