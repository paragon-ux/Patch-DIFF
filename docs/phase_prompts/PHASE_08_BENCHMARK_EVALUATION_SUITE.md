# Phase 8 Prompt - Benchmark Evaluation Suite

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
Phase 7 real external MCP adapter wiring should be complete before this phase.

Task:

Create a benchmark/evaluation suite for MCP product-surface reliability.

Benchmark scenarios:

- valid PDCP acceptance rate over representative text targets
- malformed-output rejection consistency
- regeneration recovery after `match_absent`
- regeneration recovery after delimiter corruption
- SAVE/replay/export consistency after accepted transaction sequences
- basic latency and log integrity for MCP E2E workflows

Requirements:

- use MCP tool paths rather than direct parser/applier calls
- keep results reproducible enough for later CI or release gating
- do not introduce semantic, fuzzy, AST, or model-repair behavior as benchmark logic
- do not add frontend code

Suggested files:

```text
backend/tests/evaluation/
backend/tests/integration/test_mcp_benchmark_smoke.py
```

Run:

```powershell
py -3 -m pytest backend\tests\unit
py -3 -m pytest backend\tests\integration
py -3 -m pytest
```
