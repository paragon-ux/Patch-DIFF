# Phase 7 Prompt — Postgres Atomic Commit And Services

You are working in the PatchDIFF MVP repository.

The repo is MCP-first.

Architecture:

PatchDIFF server = MCP orchestration + deterministic runtime
MCP = transport/interface
Chatbot/model = PDCP generator
Postgres = canonical working substrate

The user interacts through the chatbot, not through a PatchDIFF frontend.

The build docs take precedence over the older PatchDIFF papers/specs because the product architecture is now MCP-first.

Source-of-truth order:

1. /docs/AGENTS.md
2. /docs/MCP_FIRST_MVP.md
3. /docs/PATCHDIFF_CORE_SPEC.md
4. /docs/MCP_TOOLS.md
5. /docs/DATA_MODEL.md
6. /docs/PDCP_FORMAT.md
7. /docs/TEST_MATRIX.md
8. /docs/CODEX_BUILD_PLAN.md
9. /.agents/skills/patchdiff-core-runtime.md
10. /.agents/skills/patchdiff-mcp-orchestration.md
11. /.agents/skills/patchdiff-persistence-replay-save.md
12. /.agents/skills/patchdiff-testing-review.md

Older papers/specs are background only. If they conflict with the MCP-first build docs, follow the build docs.

Global invariants:

- PDCP files use `.pdcp`.
- PDCP is declarative, not executable.
- Do not implement generated `applyPDCP` functions.
- Do not execute model-generated code.
- Do not implement fuzzy matching, semantic matching, AST parsing, automatic merge, or partial commit paths.
- Do not implement a frontend or chat UI.
- Do not use SQLite as the MVP persistence backend.
- Postgres is the MVP persistence backend.
- Docker Compose must provide deterministic local Postgres.
- MCP orchestration must not bypass the deterministic core runtime.
- A regenerated `.pdcp` must return through `patchdiff_submit_pdcp` and be validated from scratch.
- Target content mutation must come only from accepted `.pdcp` transactions.
- SAVE may create snapshots and advance editing cycles but must not alter target content.

If there are existing files, inspect them first and preserve user work.

Use `rg` / `rg --files` for exploration.

Do not use destructive git commands.

Final response format:

Implemented:
- short summary

Changed:
- list files created/edited

Verified:
- commands actually run and results

Notes:
- assumptions
- anything intentionally deferred to later phases


Phase 6 deterministic in-memory applier should be complete before this phase.

Now implement Phase 7: service-layer Postgres-backed submit flow.

This phase connects deterministic core results to Postgres persistence.

Phase 7 scope:

1. Implement target initialization service if not complete.
2. Implement submit PDCP service.
3. Lock target row with Postgres `FOR UPDATE`.
4. Enforce expected_target_version and/or expected_current_hash guards.
5. Call parser, protocol validator, and transaction applier.
6. Commit accepted transactions atomically.
7. Log rejected transactions without target mutation.
8. Update `current_pdcp_files` status.
9. Add Postgres integration tests.

Accepted flow:

1. Begin transaction.
2. Lock `cloud_target_files` row with `FOR UPDATE`.
3. Verify expected version/hash preconditions.
4. Parse/validate/apply PDCP against locked canonical target.
5. Insert accepted PDCP log row.
6. Insert accepted manifest ledger rows.
7. Update target content/hash/version/latest accepted log.
8. Update current_pdcp_file status.
9. Commit.

Rejected flow:

1. Begin transaction.
2. Lock target row if target exists.
3. Compute before_hash when possible.
4. Insert rejected PDCP log row when possible.
5. Do not update target content/hash/version.
6. Do not insert manifest ledger rows.
7. Update current_pdcp_file status.
8. Commit.

Failure mapping:

- request expected_target_version mismatch -> target_version_mismatch
- request expected_current_hash mismatch -> target_hash_mismatch
- row changes after validation/simulation but before final commit guard -> target_diverged
- target not found -> target_not_found

Suggested files:

- backend/app/services/target_service.py
- backend/app/services/pdcp_service.py
- backend/app/storage/repositories.py
- backend/tests/integration/test_pdcp_submit_flow.py
- backend/tests/integration/test_atomic_commit.py

Testing requirements:

- initialize target creates target, initial snapshot, active cycle
- accepted PDCP updates target and logs accepted row
- accepted PDCP appends manifest ledger entries
- rejected PDCP logs rejected row and does not mutate target
- failed multi-change transaction does not partially mutate
- stale expected_target_version rejects
- stale expected_current_hash rejects
- same-target row lock behavior tested against Postgres
- different targets are independent
- current_pdcp_files is updated but not authoritative history
- diagnostic_json stored for rejected attempts if implemented

Run:

- pytest backend/tests/unit
- pytest backend/tests/integration
