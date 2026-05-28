# Phase 2 Prompt — Deterministic Core Primitives

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


Phase 1 is complete. The repo has backend foundation, FastAPI app, Postgres-only SQLAlchemy setup, Alembic configuration, initial schema migration, Docker Compose Postgres config, health checks, and first import/migration reachability tests.

Now implement Phase 2: deterministic core primitives.

Focus only on storage-agnostic deterministic core helpers.

Phase 2 scope:

1. Implement shared canonicalization helper.
2. Implement shared SHA-256 hashing helper.
3. Implement canonical failure labels / enums.
4. Implement basic core result types for accepted/rejected outcomes if useful.
5. Add unit tests for canonicalization, hashing, and failure labels.
6. Do not implement full PDCP parser/applier yet unless small type definitions are useful scaffolding.

Canonicalization requirements:

- applies to target content, MATCH payload, and REPLACE payload
- input must be valid UTF-8 text
- normalize CRLF and CR to LF
- preserve tabs exactly
- preserve spaces exactly
- preserve trailing whitespace exactly
- preserve final newline exactly
- apply no Unicode normalization
- do not trim
- do not collapse whitespace
- do not alter manifest text except later parser line handling

Hashing requirements:

- SHA-256 over UTF-8 bytes of canonicalized target text
- lowercase hex digest
- one shared helper used by tests and future runtime code
- do not duplicate hashing logic

Failure labels:

Define ordinary PDCP rejection labels:

- context_missing
- context_invalid
- target_not_found
- target_encoding_invalid
- manifest_missing
- manifest_invalid
- block_malformed
- match_absent
- match_ambiguous
- disambiguation_invalid
- target_hash_mismatch
- target_version_mismatch
- target_diverged
- executable_logic_detected
- sequential_match_invalid
- transaction_internal_error

Define replay-only labels:

- replay_hash_mismatch
- replay_protocol_invalid
- replay_transaction_invalid

Do not invent new labels.

Suggested files, adjust to existing structure:

- backend/app/core/canonicalization.py
- backend/app/core/hashing.py
- backend/app/core/failures.py
- backend/app/core/result.py
- backend/tests/unit/test_canonicalization.py
- backend/tests/unit/test_hashing.py
- backend/tests/unit/test_failures.py

Testing requirements:

- LF input stays unchanged
- CRLF normalizes to LF
- CR normalizes to LF
- mixed CRLF/CR normalizes to LF
- tabs are preserved
- spaces are preserved
- trailing spaces are preserved
- final newline is preserved
- missing final newline is preserved as missing
- no Unicode normalization is applied
- hash helper hashes canonicalized text consistently
- CRLF and LF variants hash the same after canonicalization
- Unicode-equivalent but codepoint-different strings hash differently if canonicalized text differs
- all canonical failure labels are present
- replay-only labels are separate from ordinary PDCP rejection labels

Run the narrowest useful verification commands, likely:

- pytest backend/tests/unit
- existing import/health/migration tests if quick
