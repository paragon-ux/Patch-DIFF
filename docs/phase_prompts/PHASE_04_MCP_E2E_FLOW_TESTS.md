# Phase 4 Prompt - MCP E2E Flow Tests

You are working in the PatchDIFF MVP repository.

The repo is MCP-first.

Architecture:

```text
PatchDIFF server = MCP orchestration + deterministic runtime
MCP = transport/interface
Chatbot/model = PDCP generator
Postgres = canonical working substrate
```

The user interacts through the chatbot/MCP host, not through a PatchDIFF frontend.

Read first:

1. AGENTS.md
2. docs/MCP_FIRST_MVP.md
3. docs/MCP_TOOLS.md
4. docs/PATCHDIFF_CORE_SPEC.md
5. docs/PDCP_FORMAT.md
6. docs/DATA_MODEL.md
7. docs/TEST_MATRIX.md
8. docs/CODEX_BUILD_PLAN.md
9. .agents/skills/patchdiff-mcp-orchestration.md
10. .agents/skills/patchdiff-testing-review.md

Global invariants:

- Do not add frontend code.
- Do not implement chat UI code.
- Do not use SQLite for MVP persistence correctness.
- Use Postgres-backed integration behavior for persistence/SAVE/replay tests.
- Use the existing internal MCP registry unless this phase explicitly says external adapter.
- Do not bypass deterministic parser/validator/matcher/applier/service paths.
- Do not mutate target content directly from MCP tools.
- Do not execute PDCP content.
- Do not silently repair malformed model output.
- Regenerated PDCP must return through `patchdiff_submit_pdcp` and be validated from scratch.
- Target content mutation must come only from accepted `.pdcp` transactions.

If there are existing files, inspect them first and preserve user work.

Use `rg` / `rg --files` for exploration.

Do not use destructive git commands.

Final response format:

Implemented:
- short summary

Changed:
- files changed

Verified:
- commands run and results

Findings:
- any MCP gaps found

Deferred:
- real external MCP SDK/server adapter wiring, unless this phase is Phase 7
Phase 3 MCP tool contract tests should be complete before this phase.

Task:

Create MCP E2E tests for the actual product workflow without a frontend.

E2E test 1: happy path

```text
upload target through MCP
build prompt context
submit valid PDCP through MCP
assert accepted
get target
assert content changed
get PDCP log
assert accepted log exists
get manifest ledger
assert accepted manifest exists
export target
assert exported content matches current target
```

E2E test 2: rejection path

```text
upload target
submit invalid PDCP with wrong MATCH
assert rejected
assert failure_reason = match_absent
assert after_hash is null
assert target content/hash/version unchanged
assert rejected log exists
assert manifest ledger did not append accepted entry
```

E2E test 3: regeneration path

```text
upload target
submit bad PDCP
get regeneration context
submit corrected regenerated PDCP
assert corrected PDCP accepted
assert rejected parent remains logged
assert accepted regenerated attempt is a separate log entry
assert target mutates exactly once
```

Suggested files:

```text
backend/tests/integration/test_mcp_e2e_flows.py
```

Run:

```powershell
py -3 -m pytest backend\tests\unit
py -3 -m pytest backend\tests\integration
py -3 -m pytest
```
