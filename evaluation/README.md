# Evaluation

Three layers, kept strictly separate (`docs/MODERNIZATION_ARCHITECTURE.md` Decision A8).

## 1. Deterministic Guarantee & Persistence Suite (VERIFIED)

Run against live Postgres (`postgres:16.3-alpine` on `127.0.0.1:5432`):

```powershell
$env:DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
.\.venv\Scripts\python.exe -m pytest -q
```

Covers pure core unit tests (`backend/tests/unit/`, 174 tests) and live Postgres + real stdio MCP subprocess integration tests (`backend/tests/integration/`, 87 tests): typed vs. PDCP equivalence, delimiter collision, overlapping-match enumeration, explicit replay profile dispatch (`0.2.3` vs `patchdiff-tx/1`, `patchdiff-mvp-0.1.0` vs `patchdiff-mvp-0.2.0`), component-level `materialized_state_checks`, `client_request_id` idempotency and lost-response outcome recovery, stage-aware `validity`, and full stdio MCP workflow.

## 2. Offline Payload & Verdict Accounting (VERIFIED)

```powershell
$env:PYTHONPATH="backend"; .\.venv\Scripts\python.exe evaluation/offline_eval.py
```

Deterministic UTF-8 byte accounting and shared-applier verdict equivalence across 5 scenarios and 3 proposal variants:
1. `pdcp`: PDCP v0.2.3 with its required 7 prose manifest fields per edit;
2. `typed_match`: typed `patchdiff-tx/1` with matched advisory prose (`intent` + per-edit `change_id`, `rationale`, `risk="low"`);
3. `typed_min`: minimal typed `patchdiff-tx/1` (`intent` + `{match, replace}`).

Reports both persisted record bytes (`append_only_pdcp_logs.pdcp_content`) and MCP tool request wire JSON bytes (`tools/call` arguments). Bytes measure wire/storage size, not LLM token cost or model validity rates.

## 3. Live-Model, Host-Integrated Study (NOT RUN)

Designed, not executed; no empirical model-performance claims are made.

To run a live-model study in the future, compare with identical model, retry budget, and target corpus:
- native exact-edit tool loop (`str_replace`) vs. PatchDIFF `patchdiff_submit_edits`;
- native patch tool loop (`apply_patch`) vs. PatchDIFF `patchdiff_submit_edits`;
- full-document regeneration as a secondary baseline on large documents.

Measure: first-attempt validity, task success, recovery turns, input/output tokens, latency, rejected-attempt auditability, lost-response recovery, and deterministic replay.
