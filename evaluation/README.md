# Evaluation & Benchmarks

The separate [structural batch capability check](../docs/STRUCTURAL_BATCH_EDITING.md#deterministic-capability-evidence)
uses `structural_batch/verify.py` with live PostgreSQL and real stdio. It keeps the
original five-file fixtures, task, gold oracle, exploratory transcripts and frozen
Gate 2 controller unchanged. It checks five bundled observations/five atomic
submissions, exact output bytes and 20 behavioral assertions; it invokes no model
and makes no comparative performance claim. Evidence is stored in its own run
directory. Existing host integrations requiring administrative tools opt into
`PATCHDIFF_MCP_PROFILE=full` before launch.

Four evaluation layers, kept strictly separate (`docs/MODERNIZATION_ARCHITECTURE.md` Decision A8).

---

## 1. Deterministic Guarantee & Persistence Suite

Run against live Postgres (`postgres:16.3-alpine` on `127.0.0.1:5432`):

```powershell
$env:PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
.\.venv\Scripts\python.exe -m pytest -q
```

- **Current verified scale (`PR #14`)**: **1,226 passed** (`816` pure core unit tests in `backend/tests/unit/` + `410` live PostgreSQL & real stdio MCP subprocess integration tests in `backend/tests/integration/`), plus **235/235** live stdio friction harness checks.
- Covers typed (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`) and legacy equivalence, delimiter-collision safety, overlapping-match enumeration, explicit replay profile dispatch (`0.1.0` through `0.5.0`), component-level `materialized_state_checks`, `client_request_id` idempotency and lost-response outcome recovery, stage-aware `validity`, populated Alembic migration `upgrade -> downgrade -> upgrade` checks, and full stdio MCP workflows.

Results and counts identify the executed revision; historical suite totals do not certify later source changes.

---

## 2. Offline Payload & Verdict Accounting (`evaluation/offline_eval.py`)

```powershell
$env:PYTHONPATH="backend"; .\.venv\Scripts\python.exe evaluation/offline_eval.py
```

Deterministic UTF-8 byte accounting and shared-applier verdict equivalence across 5 scenarios:
1. `typed_min`: minimal typed `patchdiff-tx/1` (`intent` + `{match, replace}`).
2. `typed_match`: typed `patchdiff-tx/1` with matched advisory prose (`intent` + per-edit `change_id`, `rationale`, `risk="low"`).
3. *(Legacy baseline `pdcp` v0.2.3 is also verified by the script; see [docs/LEGACY_COMPATIBILITY.md](../docs/LEGACY_COMPATIBILITY.md#5-measured-comparison-legacy-pdcp-v023-vs-typed-patchdiff-tx1) for the legacy `.pdcp` byte and delimiter-collision comparison.)*

Reports both MCP tool request wire JSON bytes (`tools/call` arguments) and persisted record bytes (`append_only_pdcp_logs.pdcp_content`). Bytes measure wire/storage size, not LLM token cost or model validity rates.

### Measured `patchdiff-tx/1` Payload Bytes (`evaluation/offline_eval.py`)

| Scenario (`patchdiff_submit_edits`) | Raw Match + Replace Strings (`UTF-8 B`) | `typed_min` Wire Bytes (`tools/call` `arguments`) | `typed_min` Persisted Bytes (`pdcp_content`) | `typed_match` Wire Bytes (`tools/call` `arguments`) | `typed_match` Persisted Bytes (`pdcp_content`) | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **1 tiny edit (`"old" -> "new"`)** | `6 B` (`3 B` + `3 B`) | **`151 B`** | **`206 B`** | `327 B` | `382 B` | `accepted` |
| **5 small edits (`5 × 1-byte edits`)** | `10 B` (`5 × 2 B`) | **`259 B`** | **`314 B`** | `1,139 B` | `1,194 B` | `accepted` |
| **1 edit, 2 KB span (`LONG_BODY`)** | `4,218 B` (`2,109 B` × 2) | **`4,441 B`** | **`4,496 B`** | `4,617 B` | `4,672 B` | `accepted` |
| **Quotes + backslashes + Unicode** | `23 B` (`10 B` + `13 B`) | **`172 B`** | **`227 B`** | `348 B` | `403 B` | `accepted` |
| **Payload has a delimiter line (`"a\n=======\nb"`)** | `14 B` (`11 B` + `3 B`) | **`162 B`** | **`217 B`** | `338 B` | `393 B` | `accepted` |

- **Marginal edit framing (`Derived`):** Each additional minimal edit item in `edits[]` adds **`25 B`** of JSON object keys/punctuation (`{"match":"","replace":""}`) + **`1 B`** array comma separator (`,`) + the UTF-8 JSON-escaped byte lengths of `match` and `replace`. For two 1-byte ASCII strings (`{"match":"a","replace":"1"}`), the controlled marginal cost is **`+28 B` per additional edit**. (Scenario 1 uses `"old"` + `"new"` = `6 B` of strings for `151 B` total; replacing that first edit with `"a"` + `"1"` = `2 B` of strings yields a `147 B` 1-edit baseline, and `147 B + 4 × 28 B = 259 B` for Scenario 2's five 1-byte edits.)
- **Delimiter collision immunity (`Measured`):** Scenario 5's match payload (`"a\n=======\nb"`) contains a standalone `=======` line that collides with the `.pdcp` v0.2.3 block separator (`rejected:block_malformed`), whereas `patchdiff-tx/1` encodes it as a standard JSON string (`162 B` `arguments`, `217 B` persisted) and commits cleanly. JSON string encoding eliminates `.pdcp` delimiter-line collisions while JSON syntax itself remains protocol-validated.

### Measured `patchdiff-tx/3` Guarded Replacement Bytes (`evaluation/offline_eval.py`)

Five `patchdiff-tx/3` (`patchdiff_submit_replacement`) cases separately check accepted content/hash oracles through immutable runtime `patchdiff-mvp-0.4.0`. The table below separates raw/canonical replacement text bytes, compact MCP `arguments` JSON bytes, canonical persisted record bytes (`pdcp_content`), and complete compact UTF-8 JSON-RPC `tools/call` request line bytes (fixed `id=1` plus one terminal LF):

| `patchdiff-tx/3` Case (`patchdiff_submit_replacement`) | Raw / Canonical Replacement (`UTF-8 B`) | MCP Tool `arguments` JSON (`UTF-8 B`) | Persisted Record Bytes (`pdcp_content`) | Complete JSON-RPC `tools/call` Line Bytes | Verdict |
| --- | --- | --- | --- | --- | --- |
| **Guarded whole-target rewrite (`"old" -> "new"`)** | `3 B` / `3 B` | `232 B` | `290 B` | `341 B` | `accepted` |
| **Empty target (`"" -> "new"`)** | `3 B` / `3 B` | `232 B` | `290 B` | `341 B` | `accepted` |
| **Empty replacement (`"old" -> ""`)** | `0 B` / `0 B` | `229 B` | `287 B` | `338 B` | `accepted` |
| **Unicode, quotes, CRLF (`'say "hi" \\\r\n🌟'`)** | `16 B` raw / `15 B` LF | `250 B` | `308 B` | `359 B` | `accepted` |
| **Whole-target 2 KB rewrite (40 lines, 39 `\n` chars)** | `2,109 B` / `2,109 B` | `2,377 B` | `2,435 B` | `2,486 B` | `accepted` |

- **Accounting separation:** The compact MCP `arguments` JSON framing around raw `replacement` text is **`229 B`** (including `target_file_id`, `intent: "Replace complete target."`, `expected_target_version: 0`, and 64-char `expected_current_hash`), plus JSON character escaping (`+39 B` for 39 newlines in the 40-line 2 KB fixture, yielding `2,109 + 39 + 229 = 2,377 B`). The outer JSON-RPC `tools/call` envelope (`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"patchdiff_submit_replacement","arguments":...}}\n`) adds **`109 B`** to `arguments` (`232 + 109 = 341 B`; `2,377 + 109 = 2,486 B`). Persisted `tx/3` records (`290 B` / `2,435 B`) are canonical storage representations and are not compared directly to `tools/call` wire lines.
- These are deterministic serialization measurements; they do not execute live transport or persistence, measure timing, or establish representative workload results. No cross-format replacement equivalence is claimed.

---

## 3. Service & Database Latency Benchmarks (`SVC-001` & `MCP-001`)

Measured on Windows 11 (`Python 3.11.9`, `postgres:16.3-alpine` on `127.0.0.1:5432`, isolated PostgreSQL database). These benchmarks measure **internal PatchDIFF server and database optimizations (`PR #13` baseline vs. `PR #14`)** on specified local fixtures; they are not cross-product benchmarks against external editing tools or end-to-end model turns.

### 3.1 Near-Miss Levenshtein Scan Latency (`SVC-001`, `backend/app/services/near_miss_service.py`)

Scans up to `65,536` Unicode code points (`MAX_SCAN_CODE_POINTS`) of the failing buffer after lock release for a `45`-code-point absent query (`threshold = min(4, max(1, len(query) // 4)) = 4`) under the `1,000,000`-cell cap (`MAX_COMPARISON_CELLS`).

`PR #14` pairs an exact positional pigeonhole filter ($k + 1 = 5$ disjoint needle pieces) with an Ukkonen-banded Landau–Vishkin diagonal-wave dynamic program, guaranteeing identical `(distance, start, end)` candidates and tie-breaking (`backend/tests/unit/test_friction_followup.py`: verified by `test_candidate_starts_strict_path_and_loop2_and_leading_insertion_exactness` over **120 seeded trials** (`random.Random(12345)`) covering strict-path, Loop-2-only, and leading-insertion windows, and by `test_bag_pruned_full_buffer_scan_equals_unpruned_reference` over **150 randomized cases** against the unpruned reference scan):

| 65,536-Code-Point Buffer Workload | Baseline (`PR #13` Ukkonen Row DP, 5-run median) | Optimized (`PR #14` Pigeonhole + Landau–Vishkin, 5-run median) | Speedup & Scan Completeness |
| --- | --- | --- | --- |
| **Varied technical prose (`65,536` chars)** | `100.2 ms` (`174,897` cells, `scanned_end=65,493`, `scope_truncated=False`) | **`1.7 ms`** (`585` cells, `scanned_end=65,493`, `scope_truncated=False`) | **58.9× faster** (`99.7%` fewer DP cells) |
| **Repetitive structured logs (`65,536` chars)** | `708.5 ms` (`1,000,000` cells, `scanned_end=45,404`, **`scope_truncated=True`**) | **`41.9 ms`** (`142,255` cells, `scanned_end=65,493`, **`scope_truncated=False`**) | **16.9× faster** + **scans 100% of buffer** (vs. `69%` before) |

### 3.2 PostgreSQL 16+ `LATERAL` History & Ledger Read Latency (`MCP-001`, `backend/app/mcp/tools.py`)

`patchdiff_get_manifest_ledger` and `patchdiff_get_pdcp_log` extract bounded `intent`, `intent_truncated`, `transaction_intent`, and per-edit `rationale` inside PostgreSQL 16+ (`pg_input_is_valid`) `LATERAL` SQL subqueries and guarded 4 KB head/tail slices rather than selecting and JSON-decoding full `pdcp_content` records in Python (`backend/tests/integration/test_friction_followup_live.py`):

| Historical Substrate (`20 MB` total `pdcp_content`) | Tool & Page Size | Baseline Python Decode (`PR #13`, 7-run median) | Guarded SQL `LATERAL` (`PR #14`, 7-run median) | Speedup & I/O Behavior |
| --- | --- | --- | --- | --- |
| **`50 × 400 KB` (`20 MB`) `patchdiff-tx/3` history** | `patchdiff_get_manifest_ledger(limit=50)` | `279.6 ms` | **`14.68 ms`** | **19.0× faster** (`pdcp_content` never read) |
| **`50 × 400 KB` (`20 MB`) `patchdiff-tx/3` history** | `patchdiff_get_pdcp_log(limit=50)` | `372.4 ms` | **`22.85 ms`** | **16.3× faster** (`left(pdcp_content, 4096)` fast path) |
| **`20 × 1 MB` (`20 MB`) `patchdiff-tx/1` history (5 edits × 200 KB)** | `patchdiff_get_pdcp_log(limit=50)` | `305.55 ms` | **`136.72 ms`** | **2.2× faster** (`right(pdcp_content, 4096)` tail slice fast path) |
| **`20 × 1 MB` (`20 MB`) `patchdiff-tx/1` history (5 edits × 200 KB)** | `patchdiff_get_manifest_ledger(limit=50)` (10 logs) | `305.55 ms` | **`221.59 ms`** | **1.38× faster** (single-cast `LATERAL ... OFFSET 0`) |
| **`20 × 1 MB` (`20 MB`) `patchdiff-tx/1` history (5 edits × 200 KB)** | `patchdiff_get_manifest_ledger(limit=100)` (20 logs) | `449.92 ms` | **`445.33 ms`** | **1.01×** (at par; zero Python `pdcp_content` transfer) |

---

## 4. Live-Model, Host-Integrated Study (NOT RUN)

Designed, not executed; no empirical model-performance claims are made.

To run a live-model study in the future, compare with identical model, retry budget, and target corpus:
- native exact-edit tool loop (`str_replace`) vs. PatchDIFF `patchdiff_submit_edits`;
- native patch tool loop (`apply_patch`) vs. PatchDIFF `patchdiff_submit_edits`;
- full-document regeneration as a secondary baseline on large documents.

Measure: first-attempt validity, task success, recovery turns, input/output tokens, latency, rejected-attempt auditability, lost-response recovery, and deterministic replay.
