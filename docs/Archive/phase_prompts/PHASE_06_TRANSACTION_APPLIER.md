# Phase 6 Prompt — Transaction Applier

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


Phase 5 matcher/disambiguation should be complete before this phase.

Now implement Phase 6: deterministic in-memory transaction application.

This phase does not commit to Postgres yet. It should simulate applying accepted changes and return an accepted/rejected result object suitable for the service/persistence layer.

Phase 6 scope:

1. Implement transaction validation/application over canonical target text and parsed+validated PDCP.
2. Apply ordered changes sequentially against the progressively updated in-memory buffer.
3. Enforce non-empty MATCH.
4. Implement deletion and anchored insertion behavior naturally through MATCH/REPLACE.
5. Detect sequential_match_invalid vs match_absent.
6. Compute before_hash and after_hash.
7. Return deterministic accepted/rejected results.
8. Add unit tests.

Application rules:

- a PDCP file is one atomic transaction
- no target mutation outside this in-memory function
- changes apply in file order
- each MATCH evaluates against current in-memory buffer
- after each selected MATCH span, replace immediately in memory
- next change sees the mutated buffer
- if any change fails, return rejection and no final target content should be committed by caller
- no fuzzy/semantic repair
- no generated code execution

sequential_match_invalid rule:

If change N where N > 1 fails to match the current in-memory buffer, and the same MATCH text would have matched the original transaction-start buffer, return sequential_match_invalid. Otherwise return match_absent.

Suggested files:

- backend/app/pdcp/applier.py
- backend/tests/unit/test_transaction_applier.py

Testing requirements:

- single replacement accepted
- deletion accepted
- whitespace-only replacement accepted
- anchored insertion accepted
- zero-length MATCH rejects
- multi-change sequential success
- second change sees first replacement
- second change against original state returns sequential_match_invalid
- overlapping valid sequential edits accepted
- overlapping invalid sequential edits reject atomically
- one failed change does not return partially applied final content
- before_hash and after_hash correct
- after_hash absent/null on rejection
- no mutation outside selected span

Run:

- pytest backend/tests/unit
