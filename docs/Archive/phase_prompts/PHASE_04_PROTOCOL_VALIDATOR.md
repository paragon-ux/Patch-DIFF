# Phase 4 Prompt — Protocol Validator

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


Phase 3 parser should be complete before this phase.

Now implement Phase 4: protocol validation for parsed `.pdcp` objects.

The parser extracts structure. The protocol validator enforces structural validity and purity. It must not inspect target applicability beyond hash fields and structural rules.

Phase 4 scope:

1. Implement protocol validator over parsed PDCP objects.
2. Validate required fields and supported values.
3. Validate change ID uniqueness.
4. Validate optional disambiguation field shapes.
5. Validate structural purity outside payloads.
6. Ensure validation returns canonical failure labels.
7. Add unit tests.

Protocol validator responsibilities:

- required header exists
- protocol version is supported
- target_file_id and target_type exist and are non-empty
- optional target_hash is valid SHA-256 hex if present
- each change has one manifest and one MATCH/REPLACE block
- required manifest fields exist and are non-empty
- risk is one of low, medium, high
- duplicate manifest fields are invalid
- duplicate change_id values are invalid
- occurrence_index, if present, is a positive integer
- manifest-level target_hash is valid SHA-256 hex if present
- header-level and manifest-level target_hash conflict rejects with target_hash_mismatch before MATCH evaluation
- executable logic outside payloads rejects
- payloads remain opaque and are never executed

Do not implement target matching or transaction application in this phase.

Suggested files:

- backend/app/pdcp/protocol_validator.py
- backend/tests/unit/test_protocol_validator.py

Testing requirements:

- valid parsed PDCP validates
- invalid protocol version rejects
- invalid hash shape rejects
- header/manifest target_hash conflict rejects target_hash_mismatch
- invalid occurrence_index rejects
- invalid risk rejects
- duplicate change IDs reject
- executable structural content rejects
- code-like payload content remains allowed
- validator does not call storage, MCP, or model code

Run:

- pytest backend/tests/unit
