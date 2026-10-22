# Evaluation

Three layers, kept strictly separate (`docs/MODERNIZATION_ARCHITECTURE.md` Decision A8).

## 1. Deterministic Guarantee & Persistence Suite

Run against live Postgres (`postgres:16.3-alpine` on `127.0.0.1:5432`):

```powershell
$env:PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
.\.venv\Scripts\python.exe -m pytest -q
```

Covers pure core unit tests (`backend/tests/unit/`) and live Postgres + real stdio MCP subprocess integration tests (`backend/tests/integration/`): typed vs. PDCP equivalence, delimiter collision, overlapping-match enumeration, explicit replay profile dispatch (`0.2.3` vs `patchdiff-tx/1`, historical `patchdiff-mvp-0.1.0` through current immutable 0.2.2/0.3.0/0.4.0 profiles), component-level `materialized_state_checks`, `client_request_id` idempotency and lost-response outcome recovery, stage-aware `validity`, and full stdio MCP workflow.

Results and counts must identify the executed revision; historical suite totals do not certify current source or CI.

## 2. Offline Payload & Verdict Accounting

```powershell
$env:PYTHONPATH="backend"; .\.venv\Scripts\python.exe evaluation/offline_eval.py
```

Deterministic UTF-8 byte accounting and shared-applier verdict equivalence across 5 scenarios and 3 proposal variants:
1. `pdcp`: PDCP v0.2.3 with its required 7 prose manifest fields per edit;
2. `typed_match`: typed `patchdiff-tx/1` with matched advisory prose (`intent` + per-edit `change_id`, `rationale`, `risk="low"`);
3. `typed_min`: minimal typed `patchdiff-tx/1` (`intent` + `{match, replace}`).

The sole named legacy expressibility exception is `payload has a delimiter line`: PDCP must reject with `block_malformed`, while both typed variants must accept with the expected hash. Every scenario checks explicit verdict/hash oracles; arbitrary rejection differences do not count as equivalence.

Reports both persisted record bytes (`append_only_pdcp_logs.pdcp_content`) and MCP tool request wire JSON bytes (`tools/call` arguments). Bytes measure wire/storage size, not LLM token cost or model validity rates.

### Guarded replacement accounting

Five `patchdiff-tx/3` cases separately check accepted content/hash oracles through immutable runtime 0.4.0: guarded whole-target rewrite, empty target, empty replacement, Unicode/quotes/CRLF, and whole-target 2 KB rewrite. Each measures its canonical persisted record and complete compact UTF-8 JSON-RPC `tools/call` request with fixed `id=1` and one terminal LF. These are deterministic serialization measurements; they do not execute live transport or persistence, measure timing, or establish representative workload results. No cross-format replacement equivalence is claimed.

## 3. Live-Model, Host-Integrated Study (NOT RUN)

Designed, not executed; no empirical model-performance claims are made.

To run a live-model study in the future, compare with identical model, retry budget, and target corpus:
- native exact-edit tool loop (`str_replace`) vs. PatchDIFF `patchdiff_submit_edits`;
- native patch tool loop (`apply_patch`) vs. PatchDIFF `patchdiff_submit_edits`;
- full-document regeneration as a secondary baseline on large documents.

Measure: first-attempt validity, task success, recovery turns, input/output tokens, latency, rejected-attempt auditability, lost-response recovery, and deterministic replay.
