# Phase 9 Prompt — MCP Server And Tool Surface

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


Phase 8 SAVE/replay should be complete before this phase.

Now implement Phase 9: MCP server/tool surface.

This phase exposes existing services through MCP orchestration. It must not duplicate deterministic core logic.

Read `/docs/MCP_TOOLS.md` and `/.agents/skills/patchdiff-mcp-orchestration.md` first.

Phase 9 scope:

1. Add MCP server setup appropriate for the selected Python stack.
2. Implement MCP tool wrappers for core workflows.
3. Keep MCP orchestration separate from deterministic core.
4. Add MCP contract tests where possible.

Required MVP MCP tool surface, subject to names in `/docs/MCP_TOOLS.md`:

- patchdiff_handle_upload or initialize target from upload
- patchdiff_build_prompt_context
- patchdiff_submit_pdcp
- patchdiff_get_regeneration_context
- patchdiff_build_regeneration_prompt, if specified
- patchdiff_get_target
- patchdiff_export_target
- patchdiff_save
- patchdiff_replay
- patchdiff_get_pdcp_log
- patchdiff_get_manifest_ledger

MCP rules:

- MCP tools call service-layer methods.
- MCP tools must not mutate target content directly.
- MCP tools must not mark rejected attempts as accepted.
- MCP tools must not bypass parser/validator/applier.
- MCP tools must not execute PDCP content.
- MCP tools must not treat model output as trusted.

Do not implement frontend or chat UI.

Suggested files:

- backend/app/mcp/server.py
- backend/app/mcp/tools.py
- backend/tests/integration/test_mcp_tools.py
- backend/tests/unit/test_prompt_context.py, if prompt building is pure

Testing requirements:

- upload initializes target through services
- submit valid PDCP returns accepted result
- submit invalid PDCP returns rejected diagnostics
- MCP submit stores pending current_pdcp_file
- MCP export returns canonical target
- MCP save calls SAVE service
- MCP replay calls replay service
- MCP tool cannot bypass core validation
- MCP tool does not directly update cloud_target_files.current_content

Run:

- pytest backend/tests/unit
- pytest backend/tests/integration
