# Phase 3 Prompt - MCP Tool Contract Tests

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
Phases 1 and 2 of manual/local validation are complete enough:

- local setup works
- health checks work
- unit/integration tests pass
- manual valid PDCP submission works
- manual malformed ChatGPT-rendered PDCP exposed delimiter corruption risk

Now move testing to the MCP product surface.

Task:

Create MCP-focused contract tests using the existing internal MCP tool registry/wrapper layer.

Test categories:

1. upload / initialize target
2. build prompt context
3. submit PDCP
4. get regeneration context
5. SAVE
6. replay
7. export target
8. get PDCP log
9. get manifest ledger

Requirements:

- upload/initialize target goes through target service
- submit PDCP goes through deterministic submit service
- valid PDCP accepts and mutates target
- invalid PDCP rejects without mutation
- accepted submit appends accepted PDCP log
- rejected submit appends rejected PDCP log
- manifest ledger appends only for accepted PDCP
- SAVE tool calls SAVE service
- replay tool calls replay service
- export tool returns canonical target
- MCP wrapper/tool code does not directly update `cloud_target_files.current_content`

Suggested files:

```text
backend/tests/integration/test_mcp_tool_contract.py
```

Run:

```powershell
py -3 -m pytest backend\tests\unit
py -3 -m pytest backend\tests\integration
py -3 -m pytest
```
