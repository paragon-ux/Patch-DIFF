# Phase 3 Prompt — PDCP Parser

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


Phase 2 should be complete before this phase.

Now implement Phase 3: the protocol-native `.pdcp` parser.

Focus only on parsing and structural extraction. Do not apply changes to targets yet.

Read `/docs/PDCP_FORMAT.md` and `/.agents/skills/patchdiff-core-runtime.md` carefully before editing.

Phase 3 scope:

1. Parse the protocol-native `.pdcp` header.
2. Parse one or more manifest-plus-MATCH/REPLACE change blocks.
3. Extract optional disambiguation fields.
4. Return typed parsed objects suitable for validators/applier.
5. Reject malformed structure with canonical failure labels.
6. Add unit tests for parser behavior.

Required header format:

```text
PDCP 0.2.3
target_file_id: <target id>
target_type: <target content type>
target_hash: <optional sha256>
```

Rules:

- first line must be exactly `PDCP 0.2.3`
- `target_file_id` is required
- `target_type` is required
- file-level `target_hash` is optional
- unknown header fields are invalid
- archival Python-style `C = ...` headers are invalid

Manifest requirements:

- each change has `# MANIFEST`
- required fields: change_id, intent, input_state, output_state, affected_region, user_visible_change, risk
- optional disambiguation fields: anchor_before, anchor_after, occurrence_index, region_hint, target_hash
- first colon separates key/value
- additional colons remain part of value
- duplicate manifest fields are invalid
- multiline manifest values are unsupported
- duplicate `change_id` values within a file are invalid

Block requirements:

```text
<<<<<<< MATCH
...
=======
...
>>>>>>> REPLACE
```

Rules:

- MATCH payload required and non-empty after canonicalization
- REPLACE payload may be empty
- delimiter collision inside payload rejects deterministically
- payloads are opaque target-native text
- parser must never execute payload text

Failure mapping:

- missing/malformed header -> context_invalid
- missing target_file_id or target_type -> context_missing
- missing manifest -> manifest_missing
- invalid manifest -> manifest_invalid
- malformed block or delimiter collision -> block_malformed
- executable logic outside payload -> executable_logic_detected

Suggested files:

- backend/app/pdcp/models.py
- backend/app/pdcp/parser.py
- backend/tests/unit/test_pdcp_parser.py

Testing requirements:

- minimal valid .pdcp parses
- valid multiple-change .pdcp parses
- header-level target_hash parses
- manifest-level target_hash parses
- optional disambiguation fields parse
- Python-style C header rejects
- unknown header field rejects
- missing target_file_id rejects
- missing target_type rejects
- missing manifest rejects
- missing required manifest field rejects
- duplicate field rejects
- empty manifest value rejects
- invalid risk rejects
- duplicate change_id rejects
- malformed delimiters reject
- empty MATCH rejects
- delimiter collision rejects
- executable logic outside payload rejects
- code-like text inside payload is allowed

Run:

- pytest backend/tests/unit
