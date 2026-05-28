# Phase 5 Prompt - Model Output Robustness Through MCP

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
Phase 4 MCP E2E flow tests should be complete before this phase.

Task:

Convert manual ChatGPT delimiter/rendering failures into automated MCP submit regression tests.

Malformed model-output cases:

- reject delimiter separator corrupted as `=================================================`
- reject REPLACE terminator corrupted as `> > > > > > > REPLACE`
- reject extra prose before PDCP if unsupported
- reject extra prose after PDCP if unsupported
- reject Markdown blockquote-rendered delimiters
- reject full rewritten document instead of PDCP
- reject executable apply function outside payload
- reject malformed manifest with missing fields

Acceptance criteria:

- all corrupted outputs reject
- failure labels are useful and canonical
- target remains unchanged
- rejected attempts are logged
- regeneration context can be produced

Positive test:

- raw code-block contents PDCP submits successfully through MCP

Suggested files:

```text
backend/tests/integration/test_mcp_model_output_regressions.py
```

Run:

```powershell
py -3 -m pytest backend\tests\unit
py -3 -m pytest backend\tests\integration
py -3 -m pytest
```
