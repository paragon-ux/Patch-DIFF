# Phase 8 Prompt — SAVE And Replay

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


Phase 7 Postgres submit flow should be complete before this phase.

Now implement Phase 8: SAVE and deterministic replay.

Phase 8 scope:

1. Implement SAVE service.
2. Implement replay service.
3. Add integration tests for editing cycles, snapshots, append-only preservation, and replay.
4. Ensure replay shares parser/canonicalizer/matcher/disambiguator/applier behavior with live runtime.

SAVE rules:

- SAVE snapshots current target
- SAVE closes current editing cycle
- SAVE opens a new active editing cycle
- SAVE preserves PDCP logs
- SAVE preserves manifest ledger history
- SAVE does not mutate target content
- SAVE failure leaves old active cycle and target state intact

SAVE flow:

1. Begin transaction.
2. Lock target row FOR UPDATE.
3. Verify expected hash if supplied.
4. Insert snapshot of current canonical target.
5. Close active editing cycle.
6. Insert new active editing cycle.
7. Update cloud_target_files.active_editing_cycle_id.
8. Commit.

Replay rules:

- authoritative replay source is initial canonical target + accepted PDCP logs ordered by log_sequence
- replay must not depend on current_pdcp_files
- replay must not depend on manifest ledger
- replay must not depend on snapshots as authoritative history
- replay verifies computed after_hash equals logged after_hash after each accepted PDCP

Failure mapping:

- parse/protocol failure during replay -> replay_protocol_invalid
- transaction application failure during replay -> replay_transaction_invalid
- computed hash differs from logged after_hash -> replay_hash_mismatch

Suggested files:

- backend/app/services/save_service.py
- backend/app/services/replay_service.py
- backend/tests/integration/test_save.py
- backend/tests/integration/test_replay.py

Testing requirements:

- SAVE creates snapshot
- SAVE closes old cycle and opens exactly one new active cycle
- SAVE does not mutate target content/hash/version
- SAVE preserves logs and ledger history
- default active manifest query shifts to new cycle
- previous ledger remains queryable
- SAVE failure leaves old cycle active
- replay reconstructs current target from accepted logs
- replay ignores current_pdcp_files
- replay ignores manifest ledger and snapshots as authoritative
- corrupted accepted PDCP log fails replay
- corrupted logged after_hash fails replay_hash_mismatch

Run:

- pytest backend/tests/unit
- pytest backend/tests/integration
