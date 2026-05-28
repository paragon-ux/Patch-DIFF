# Phase 10 Prompt — Upload, Prompt Context, And Regeneration Orchestration

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


Phase 9 MCP server/tools should be complete before this phase.

Now implement Phase 10: MCP-first orchestration flow around upload, prompt context, and regeneration.

This phase may build prompt/context packages and regeneration prompts. It must not put model-calling logic inside the deterministic core runtime.

Phase 10 scope:

1. Implement upload-to-target workflow through MCP service/tool.
2. Implement prompt context builder.
3. Implement regeneration context builder.
4. Implement regeneration prompt builder if the docs specify it.
5. Ensure regenerated PDCP returns through `patchdiff_submit_pdcp`.
6. Add MCP contract tests.

Prompt context should include:

- target_file_id
- target_type
- target version/hash
- relevant target spans or structure summary
- active manifest summary
- user request
- PDCP output rules
- exact MATCH/REPLACE requirements

Regeneration context should include:

- original user request
- rejection diagnostics
- failed_change_id when available
- current target version/hash
- current active manifest summary
- fresh relevant target context when needed
- PDCP format rules
- instruction to regenerate a fresh `.pdcp`

Rules:

- prompt/context construction belongs to MCP orchestration/service layer
- deterministic core runtime must not construct prompts
- deterministic core runtime must not call model/MCP
- generated or regenerated PDCP is untrusted until submitted and validated
- regenerated PDCP is a separate attempt with its own log row and lineage if configured

Suggested files:

- backend/app/services/prompt_context_service.py
- backend/app/services/regeneration_service.py
- backend/app/mcp/tools.py
- backend/tests/unit/test_prompt_context.py
- backend/tests/unit/test_regeneration_context.py
- backend/tests/integration/test_mcp_regeneration_flow.py

Testing requirements:

- upload returns target metadata
- prompt context includes target metadata, active manifest summary, user request, and PDCP rules
- prompt context reads from canonical services, not frontend cache
- rejected PDCP creates diagnostics
- regeneration context includes rejection diagnostics and fresh target metadata
- regeneration prompt does not request executable apply functions
- regenerated PDCP submitted through submit path creates new attempt
- accepted regenerated PDCP does not erase rejected parent
- rejected regenerated PDCP remains logged
- parent_pdcp_log_id/regeneration_attempt/regeneration_source are populated when supplied

Run:

- pytest backend/tests/unit
- pytest backend/tests/integration
