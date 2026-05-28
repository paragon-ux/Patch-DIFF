# Phase 11 Prompt — Export, API Polish, And End-To-End Smoke Tests

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


Phase 10 orchestration should be complete before this phase.

Now implement Phase 11: export/download current target, API/tool polish, and end-to-end MVP smoke tests.

Phase 11 scope:

1. Ensure current target export works through MCP/service layer.
2. Ensure health and readiness endpoints are useful.
3. Add end-to-end smoke tests covering upload -> prompt context -> submit -> reject/regenerate -> accept -> SAVE -> replay -> export.
4. Clean up response schemas and docs where needed.
5. Do not build a frontend.

Export requirements:

- return current canonical content
- return filename/target_type/version/hash
- do not mutate target state
- may be chained after SAVE but must not bypass persistence

Smoke test scenarios:

1. Upload text target.
2. Build prompt context.
3. Submit invalid/stale PDCP and receive rejection diagnostics.
4. Build regeneration context/prompt.
5. Submit corrected PDCP as new attempt.
6. Confirm accepted target content.
7. Confirm rejected parent remains logged.
8. Confirm manifest ledger only includes accepted changes.
9. SAVE target.
10. Replay accepted logs and verify current hash.
11. Export current target.

Response-shape polish:

- accepted result includes status, target_file_id, before_hash, after_hash, version, pdcp_log_id, manifest_entries_added, warnings
- rejected result includes status, target_file_id, failure_reason, failure_detail, failed_change_id, before_hash, after_hash=null, current_version, current_hash, pdcp_log_id, diagnostic
- replay failure includes replay failure label and detail
- export result includes content, target_type, version, hash

Testing requirements:

- end-to-end smoke test passes against Postgres
- no frontend assumptions
- no SQLite
- no MCP bypass of deterministic core
- no generated code execution

Run:

- pytest backend/tests/unit
- pytest backend/tests/integration
- any app import/health checks
