# Phase 5 Prompt — Exact Matcher And Disambiguation

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


Phase 4 protocol validator should be complete before this phase.

Now implement Phase 5: exact matching and disambiguation.

Focus on pure deterministic, storage-agnostic functions.

Phase 5 scope:

1. Implement exact occurrence detection.
2. Implement disambiguation resolution.
3. Add unit tests.

Matching semantics:

- exact
- case-sensitive
- whitespace-sensitive after canonicalization
- multiline
- left-to-right over Unicode codepoint positions
- full current in-memory buffer search
- no fuzzy matching
- no semantic matching
- no token matching
- no AST/language-aware matching
- no fallback/repair

Occurrence detection:

- return all non-overlapping exact full-span occurrences in left-to-right order
- count all candidates before selecting
- zero candidates -> match_absent
- multiple candidates without disambiguation -> match_ambiguous

Disambiguation fields:

- anchor_before
- anchor_after
- occurrence_index
- region_hint
- target_hash

Resolution algorithm:

1. Find all exact full-span MATCH occurrences.
2. If zero, reject match_absent.
3. If one, select it.
4. If multiple, apply disambiguation.
5. occurrence_index is 1-based over the global exact occurrence list.
6. anchor_before retains candidates where anchor text appears before candidate span.
7. anchor_after retains candidates where anchor text appears after candidate span.
8. region_hint is advisory only and must never select by itself.
9. exactly one candidate must remain.
10. zero or multiple remaining candidates -> disambiguation_invalid.

Suggested files:

- backend/app/pdcp/matcher.py
- backend/app/pdcp/disambiguation.py
- backend/tests/unit/test_matcher.py
- backend/tests/unit/test_disambiguation.py

Testing requirements:

- exact single match succeeds
- zero match returns match_absent
- duplicate match returns match_ambiguous when no disambiguation
- occurrence_index selects correct candidate
- invalid occurrence_index rejects
- anchor_before selects candidate
- anchor_after selects candidate
- combined occurrence and anchors select candidate
- anchors leaving zero candidates reject
- anchors leaving multiple candidates reject
- region_hint alone does not select candidate
- case mismatch rejects
- whitespace mismatch rejects
- multiline match succeeds
- CRLF canonicalization supports matching
- Unicode-equivalent but codepoint-different strings do not match silently

Run:

- pytest backend/tests/unit
