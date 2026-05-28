# Phase 7 Prompt - Real External MCP Adapter Wiring

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
Phase 3-6 internal MCP contract and E2E tests should be complete before this phase.

Task:

Wire the real external MCP adapter and rerun the same MCP E2E tests through the real transport.

Scope:

- implement only external MCP SDK/server adapter wiring needed to expose the existing tool surface
- keep internal registry/wrapper behavior as the semantic source of truth
- route external MCP calls to the same service-layer methods
- preserve existing response shapes
- rerun or adapt Phase 3-6 MCP tests against real transport where feasible

Do not:

- add frontend code
- add chat UI code
- change PDCP format
- change deterministic parser/validator/matcher/applier semantics
- let transport call the applier or persistence directly
- bypass `patchdiff_submit_pdcp`
- call a model from deterministic core

Suggested files depend on the selected MCP SDK. If SDK/API is uncertain, stop and report the integration decision needed instead of guessing a broken adapter.

Run:

```powershell
py -3 -m pytest backend\tests\unit
py -3 -m pytest backend\tests\integration
py -3 -m pytest
```
