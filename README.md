# PatchDIFF

**Server-side deterministic document transaction service for MCP hosts and coding agents.**

PatchDIFF turns model-generated document edits from best-effort file rewrites into **guarded, atomic, auditable, and deterministically replayable PostgreSQL transactions** exposed over the Model Context Protocol (MCP).

Instead of trusting an LLM to regenerate an entire file or apply unverified local patches, the MCP host reads authoritative document slices from PatchDIFF, submits compact typed JSON transactions (`patchdiff-tx/1`, `patchdiff-tx/2`, or `patchdiff-tx/3`) guarded by version/hash preconditions and `client_request_id` idempotency keys, and receives either an **atomic per-target commit** (with runtime-derived span/hash facts and advisory warnings) or a **structured rejection** (with stage-accurate validity, exact ambiguity candidates, and sub-50 ms exact Levenshtein near-miss diagnostics).

```text
PatchDIFF server = deterministic transaction runtime + authoritative read/commit service
MCP              = transport/interface (stdio JSON-RPC / internal registry)
Host / Model     = planning, context selection, proposal generator, retry owner
PostgreSQL 16+   = canonical working substrate (SELECT ... FOR UPDATE)
```

PatchDIFF is not a chat UI, rich document editor, semantic patch language, AST rewrite engine, fuzzy matcher, automatic merge system, or full-document regeneration workflow. See the [release notes](CHANGELOG.md), [release checklist](docs/RELEASE_READINESS.md), and [security policy](SECURITY.md).

---

## How the Transactional Loop Works

```mermaid
sequenceDiagram
    participant Host as MCP Host / Agent
    participant PD as PatchDIFF MCP Server
    participant PG as PostgreSQL 16 (Authoritative State)

    Host->>PD: 1. patchdiff_read_target / patchdiff_find_occurrences
    PD->>PG: Read committed canonical LF slice
    PG-->>PD: content slice + version + current_hash
    PD-->>Host: Bounded slice / exact spans + version=3

    Host->>PD: 2. patchdiff_submit_edits (expected_target_version=3, client_request_id="req-01", edits=[...])
    PD->>PG: SELECT ... FOR UPDATE (row lock)
    alt All edits match & guards hold
        PD->>PG: Atomic commit (target v4 + append_only_pdcp_logs + append_only_manifest_ledger)
        PD-->>Host: status="accepted", version=4, evidence.changes[], warnings[], validity
    else Stale guard, missing match, or ambiguity
        PD->>PG: Log rejected attempt in append_only_pdcp_logs (zero target mutation)
        PD-->>Host: status="rejected", failure_reason, failure_context, exact_candidates / near_misses
        Host->>PD: 3. Re-read fresh slice & retry with parent_pdcp_log_id
    end
```

---

## Why PatchDIFF: Measured Benefits & Guarantees

All measurements below are reproducible locally via `evaluation/offline_eval.py` and the live PostgreSQL benchmark suite (`Python 3.11.9`, `postgres:16.3-alpine` on Windows 11).

### 1. Compact $O(\text{delta})$ Typed JSON Payloads & Zero Delimiter Collisions
Unlike full-document regeneration ($O(\text{document size})$) or text-delimited patch envelopes that break when target files contain conflict markers (`<<<<<<<`), PatchDIFF's typed JSON formats scale strictly with the edited span:

| Scenario (`evaluation/offline_eval.py`) | `patchdiff-tx/1` Minimal (`typed_min`, Wire / Stored) | `patchdiff-tx/1` with Prose (`typed_match`, Wire / Stored) | `patchdiff-tx/3` Whole-Target Rewrite (Wire / Stored) | Verdict & Delimiter Safety |
| --- | --- | --- | --- | --- |
| **1 tiny edit** | **`151 B`** / **`206 B`** | `327 B` / `382 B` | `341 B` / `290 B` | `accepted` |
| **5 small edits in 1 transaction** | **`259 B`** / **`314 B`** | `1,139 B` / `1,194 B` | — | `accepted` (atomic all-or-nothing) |
| **1 edit, 2 KB span** | **`4,441 B`** / **`4,496 B`** | `4,617 B` / `4,672 B` | `2,486 B` / `2,435 B` | `accepted` |
| **Quotes + backslashes + Unicode (`🌍`, `中`)** | **`172 B`** / **`227 B`** | `348 B` / `403 B` | `359 B` / `308 B` | `accepted` |
| **Payload contains `<<<<<<< MATCH` delimiter** | **`162 B`** / **`217 B`** | `338 B` / `393 B` | — | **`accepted` (100% collision-free)** |

### 2. Sub-50 ms Exact Near-Miss Diagnostics on 64K Buffers (`SVC-001`)
When an exact match fails (`match_absent`), PatchDIFF scans up to the first `65,536` code points of the failing buffer after lock release using an **exact positional pigeonhole filter ($k+1$ disjoint needle pieces) coupled with a Landau–Vishkin diagonal-wave banded dynamic program** under a `1,000,000`-cell cap. It returns up to 3 non-overlapping exact Levenshtein near-miss candidates without ever applying a fuzzy edit:

| 65,536-Code-Point Workload (`needle` len 45, `threshold=4`) | Baseline Banded DP (`PR #13`) | Pigeonhole + Landau–Vishkin (`PR #14`) | Speedup & Coverage Gain |
| --- | --- | --- | --- |
| **Varied technical prose (`65,536` chars)** | `100.2 ms` (`174,897` cells, `100%` scanned) | **`1.7 ms`** (`585` cells, `100%` scanned) | **58.9× faster** (`99.7%` fewer DP cells) |
| **Repetitive structured logs (`65,536` chars)** | `708.5 ms` (`1,000,000` cells, **truncated at `69%`**) | **`41.9 ms`** (`142,255` cells, **`100%` scanned**) | **16.9× faster** + **full 64K scan** (`scope_truncated=False`) |

### 3. Millisecond-Scale PostgreSQL 16+ `LATERAL` History & Ledger Reads (`MCP-001`)
Audit and manifest ledger tools (`patchdiff_get_manifest_ledger`, `patchdiff_get_pdcp_log`) project bounded `intent`, `transaction_intent`, and per-edit `rationale` directly in PostgreSQL 16+ (`pg_input_is_valid`) `LATERAL` subqueries and guarded 4 KB head/tail slices—avoiding Python-side TOAST transfer and JSON decoding of multi-megabyte transaction histories:

| 20 MB Historical Substrate (`postgres:16.3-alpine`) | Query Operation | Full-Record Python Decode (`PR #13`) | Guarded SQL `LATERAL` Projection (`PR #14`) | Speedup |
| --- | --- | --- | --- | --- |
| **`50 × 400 KB` (`20 MB`) `patchdiff-tx/3` history** | `patchdiff_get_manifest_ledger(limit=50)` | `279.6 ms` | **`14.68 ms`** (zero `pdcp_content` TOAST reads) | **19.0× faster** |
| **`50 × 400 KB` (`20 MB`) `patchdiff-tx/3` history** | `patchdiff_get_pdcp_log(limit=50)` | `372.4 ms` | **`22.85 ms`** (4 KB head slice fast path) | **16.3× faster** |
| **`20 × 1 MB` (`20 MB`) `patchdiff-tx/1` history** | `patchdiff_get_pdcp_log(limit=50)` | `305.6 ms` | **`136.72 ms`** (4 KB tail slice fast path) | **2.2× faster** |
| **`20 × 1 MB` (`20 MB`) `patchdiff-tx/1` history** | `patchdiff_get_manifest_ledger(limit=50)` | `305.6 ms` | **`221.59 ms`** (single-cast `LATERAL ... OFFSET 0`) | **1.38× faster** |

### 4. Hard Context Budgets & Verification Scale
Every MCP response is strictly bounded to protect host context windows, and every invariant is verified against live PostgreSQL 16 and real stdio MCP subprocesses:
- **Discovery (`tools/list`)**: `<= 65,536 B` total (`<= 8,192 B` for 13 executable examples across 9 tools).
- **Authoritative Reads (`patchdiff_read_target`, `patchdiff_read_lines`)**: `4,000` default / `8,000` max Unicode code points per call; `patchdiff_find_occurrences` caps `context_chars` at `400` and `max_results` at `200`.
- **Advisory Preview (`patchdiff_preview`)**: `<= 32,768 B` total (`<= 16,384 B` for up to 32 facts; `<= 16,384 B` for diagnostics).
- **Rejection Enrichment**: `<= 18,432 B` combined (`<= 8,192 B` for up to 5 exact ambiguity candidates; `<= 8,192 B` for up to 3 near misses; `<= 256` code points of persisted `failure_context`).
- **Verification Suite**: **1,226 automated tests** (`816` pure core unit tests + `410` live PostgreSQL & stdio MCP integration tests, including populated Alembic `upgrade -> downgrade -> upgrade` checks) and **235/235** live stdio agentic friction checks.

---

## How PatchDIFF Compares

| Capability | Full-Document Rewrite | Built-In Agent `str_replace` / `apply_patch` | Local Filesystem Diff MCPs | **PatchDIFF (`patchdiff-tx/1..3`)** |
| --- | --- | --- | --- | --- |
| **Wire Payload Scaling** | $O(\text{full file})$ | $O(\text{delta})$ | $O(\text{delta})$ | **$O(\text{delta})$ (`151 B` for 1 edit)** |
| **Optimistic Concurrency Guard** | None (last write wins) | None or mtime check | None | **Required `expected_target_version` and/or `expected_current_hash` under `SELECT ... FOR UPDATE`** |
| **Multi-Edit Atomicity** | Whole file replaced | Often partial on multi-hunk failure | Varies | **Strict all-or-nothing per target** |
| **Lost-Response Idempotency** | Re-runs overwrite | Re-runs fail or duplicate | None | **`client_request_id` recovers exact recorded outcome (`deduplicated: true`)** |
| **Overlapping Match Safety** | N/A | Silent first-match or non-overlapping | Silent or fuzzy | **Counts all overlapping occurrences; requires explicit selector (`occurrence_index`, `anchor_before`/`after`)** |
| **Verified Insertion Context** | N/A | Fragile line numbers | Fragile line numbers | **`tx/2` spans with `expected_before` / `expected_after` adjacency guards + UAX #29 grapheme split warnings** |
| **Rejected Attempt Audit** | Ephemeral chat | Ephemeral tool error | Ephemeral | **Durable `append_only_pdcp_logs` + retry lineage (`parent_pdcp_log_id`)** |
| **Deterministic Replay** | None | Git commits only | None | **Profile-dispatched replay (`0.1.0`..`0.5.0`) + 4-part `materialized_state_checks`** |

---

## Choosing a Transaction Format & 3-Step Walkthrough

### Typed Transaction Formats

| Format | MCP Tool | When to Use | Guard Requirement |
| --- | --- | --- | --- |
| **`patchdiff-tx/1`** (Primary) | `patchdiff_submit_edits` | Default exact `MATCH/REPLACE` edits with optional `occurrence_index`, `anchor_before`, or `anchor_after` selectors. | `expected_target_version` and/or `expected_current_hash` |
| **`patchdiff-tx/2`** | `patchdiff_submit_operations` | Coordinate-known `span` edits (`start`, `end`, `expected_text`, `replace`), descending multi-span edits from a single read, or verified insertions (`expected_before` / `expected_after`). | `expected_target_version` and/or `expected_current_hash` |
| **`patchdiff-tx/3`** | `patchdiff_submit_replacement` | Explicit whole-document replacement (`{"op": "replace_all", "replace": "..."}`, up to 1 MB / 1M code points). | `expected_target_version` and/or `expected_current_hash` |

*(For the frozen `.pdcp` v0.2.3 text format and `patchdiff_submit_pdcp`, see [docs/LEGACY_COMPATIBILITY.md](docs/LEGACY_COMPATIBILITY.md).)*

### 3-Step Host Walkthrough

**Step 1 — Read authoritative state (`patchdiff_read_target` or `patchdiff_find_occurrences`):**
```json
{
  "name": "patchdiff_read_target",
  "arguments": {
    "target_file_id": "11111111-1111-4111-8111-111111111111",
    "start": 0,
    "length": 4000
  }
}
```
Response returns `content`, `version: 0`, and `current_hash: "8f434346..."`.

**Step 2 — Submit guarded typed edits (`patchdiff_submit_edits`):**
```json
{
  "name": "patchdiff_submit_edits",
  "arguments": {
    "target_file_id": "11111111-1111-4111-8111-111111111111",
    "expected_target_version": 0,
    "intent": "Enable system theme by default.",
    "client_request_id": "req-theme-001",
    "edits": [
      {
        "match": "theme: dark",
        "replace": "theme: system",
        "rationale": "Default to OS theme preference."
      }
    ]
  }
}
```

**Step 3a — Accepted Commit Response:**
```json
{
  "status": "accepted",
  "target_file_id": "11111111-1111-4111-8111-111111111111",
  "pdcp_log_id": "22222222-2222-4222-8222-222222222222",
  "version": 1,
  "current_version": 1,
  "before_hash": "8f434346...",
  "after_hash": "c3ab8ff1...",
  "current_hash": "c3ab8ff1...",
  "deduplicated": false,
  "warnings": [],
  "validity": {
    "protocol_valid": true,
    "transaction_valid": true,
    "task_correct": "not_evaluated",
    "semantic": "not_evaluated"
  }
}
```

**Step 3b — Or Structured Rejection with Exact Near-Miss Diagnostics (`match_absent`):**
If the target actually contained `"theme: drak"`, the target is untouched (`version: 0`) and PatchDIFF returns:
```json
{
  "status": "rejected",
  "failure_reason": "match_absent",
  "pdcp_log_id": "33333333-3333-4333-8333-333333333333",
  "current_version": 0,
  "diagnostic": {
    "stage": "TRANSACTION_APPLICABILITY",
    "retryable": true,
    "failed_change_id": "chg_001",
    "near_misses": {
      "available": true,
      "candidates": [
        {
          "distance": 2,
          "start": 14,
          "end": 25,
          "matched_text": "theme: drak",
          "context_before": "# Settings\n",
          "context_after": "\nnotifications: true"
        }
      ],
      "scanned_start": 0,
      "scanned_end": 46,
      "scope_truncated": false
    }
  }
}
```

---

## Prerequisites

- Python 3.11+
- Docker Desktop with Docker Compose
- PowerShell on Windows (or bash on Linux/macOS)

## Quick Setup

From the repo root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
docker compose up -d postgres
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```

The FastAPI server runs at `http://127.0.0.1:8000` (used for health checks and HTTP APIs). The primary interface for external MCP clients (such as Claude Desktop) is the stdio MCP adapter.

For MCP-only use, stop after migrations and configure the host below; Uvicorn is optional. Compose publishes PostgreSQL on `127.0.0.1:5432` only. The example database password is for isolated local development; see [SECURITY.md](SECURITY.md) before using real data or another deployment.

## Configuration

By default, the app connects to the local Docker Compose Postgres instance:

```text
postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff
```

Override it with:

```powershell
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff"
```

## Database Migrations

Start Postgres:

```powershell
docker compose up -d postgres
```

Run migrations (`20260510_0001`, `20261020_0002`, and `20261022_0003`):

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

## Health Checks

With FastAPI running:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

- `/health/live` verifies the FastAPI app process is responsive.
- `/health/ready` verifies Postgres is reachable and responsive.

## External MCP Adapter Setup (Claude Desktop)

PatchDIFF exposes a stdio JSON-RPC MCP adapter for external MCP hosts such as Claude Desktop.

The adapter process uses strict UTF-8 for stdin/stdout, including Windows pipes, independently of the locale or `PYTHONIOENCODING` setting. Older revisions require `PYTHONIOENCODING=utf-8` in the server environment to avoid misdecoding literal Unicode requests. See [the setup guide](docs/CLAUDE_DESKTOP_SETUP.md) for transport and restart guidance.

Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "patchdiff": {
      "type": "stdio",
      "command": "C:\\path\\to\\Patch-DIFF\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp.external_adapter"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\Patch-DIFF\\backend",
        "PATCHDIFF_DATABASE_URL": "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff"
      }
    }
  }
}
```

Quick stdio smoke check from the repo root:

```powershell
$env:PYTHONPATH = "backend"
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | .\.venv\Scripts\python.exe -m app.mcp.external_adapter
```

Expected response includes:

```json
{
  "serverInfo": {
    "name": "patchdiff-mvp"
  }
}
```

See [docs/CLAUDE_DESKTOP_SETUP.md](docs/CLAUDE_DESKTOP_SETUP.md) for full setup guidance.

## MCP Tool Surface

- **Document Lifecycle**: `patchdiff_handle_upload`, `patchdiff_initialize_target`, `patchdiff_get_target`, `patchdiff_export_target`
- **Authoritative Reads & Exact Search**: `patchdiff_read_target` (bounded slices with `next_start`), `patchdiff_read_lines` (inclusive LF ranges with `next_offset` / `next_start`), `patchdiff_find_occurrences` (exact spans with context and pagination)
- **Guarded Submission**: `patchdiff_submit_edits` (`patchdiff-tx/1`), `patchdiff_submit_operations` (sequential match/span edits, `patchdiff-tx/2`), `patchdiff_submit_replacement` (sole explicit whole-target replacement, `patchdiff-tx/3`)
- **Advisory Preview**: `patchdiff_preview` (bounded verdict/facts without audit rows, keys, or target mutation)
- **Checkpoints, Replay & History**: `patchdiff_save` (editing cycle rotation), `patchdiff_replay` (deterministic profile-dispatched reconstruction), `patchdiff_get_pdcp_log` (bounded attempt log), `patchdiff_get_manifest_ledger` (accepted changes with runtime facts)
- **Legacy Compatibility**: Frozen `.pdcp` v0.2.3 submission (`patchdiff_submit_pdcp`) and compatibility wrappers (`patchdiff_build_prompt_context`, `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`) are documented in [docs/LEGACY_COMPATIBILITY.md](docs/LEGACY_COMPATIBILITY.md).

See [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) and [docs/HOST_INTEGRATION_GUIDE.md](docs/HOST_INTEGRATION_GUIDE.md).

Discovery advertises 20 tools and 13 executable examples across nine tools. Bind examples to actual target IDs, guards, rejection parents, and returned cursors. A preview does not reserve state: subsequent submission must recheck a version or hash guard. Span and whole-target replacement always require a guard; a version guard also detects intervening no-op/ABA edits. Correlation IDs are opt-in invocation metadata, separate from caller-known retry keys.

## Testing & Offline Evaluation

Run unit and integration tests against live Postgres:

```powershell
# Unit tests (pure runtime, 816 tests)
.\.venv\Scripts\python.exe -m pytest backend/tests/unit -q

# Integration tests (live Postgres & real stdio subprocess, 410 tests)
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
.\.venv\Scripts\python.exe -m pytest backend/tests/integration -q

# Offline evaluation (payload bytes and applier verdict equivalence)
.\.venv\Scripts\python.exe evaluation/offline_eval.py
```

See [evaluation/README.md](evaluation/README.md) for full benchmark tables and reproduction instructions.

## Project Layout

```text
backend/app/api          FastAPI health and HTTP API routes
backend/app/core         Pure deterministic runtime primitives, version profiles, validity stages
backend/app/pdcp         Declarative typed and PDCP parsers, matcher, disambiguator, applier
backend/app/services     Authoritative services (submit, read, search, near-miss, save, replay, export)
backend/app/storage      SQLAlchemy models, database session management, migrations
backend/app/mcp          MCP tool definitions, internal registry, and external stdio adapter
backend/app/migrations   Alembic migration versions (0001 initial, 0002 typed ledger, 0003 source line endings)
backend/tests            Unit tests and live Postgres integration tests
evaluation               Offline payload and verdict equivalence evaluation harness
docs                     Modernized architecture, core spec, data model, tool contracts, guides
```

## Reference Documentation

Read in order of precedence:

1. `AGENTS.md` (locked architectural invariants)
2. `docs/MODERNIZATION_ARCHITECTURE.md` (architectural decisions A1–A8, contracts C1–C6, and whitepaper hypothesis reconciliation)
3. `docs/MODERNIZATION_CHANGE_DOC.md` (current product change record: formats, compatibility, and verification scope)
4. `docs/MCP_TOOLS.md` (MCP tool contracts, byte budgets, and schemas)
5. `docs/PATCHDIFF_CORE_SPEC.md` (deterministic core runtime specification)
6. `docs/DATA_MODEL.md` (Postgres schema and migrations `0001`, `0002`, and `0003`)
7. `docs/PDCP_FORMAT.md` (`patchdiff-tx/1`, guarded operations `patchdiff-tx/2`, sole replacement `patchdiff-tx/3`)
8. `docs/HOST_INTEGRATION_GUIDE.md` (host-owned loop, reads, guards, retries, and failure handling)
9. `docs/LEGACY_COMPATIBILITY.md` (frozen `.pdcp` v0.2.3 format, `patchdiff_submit_pdcp`, deprecated wrappers, and historical replay profiles)
10. `docs/TEST_MATRIX.md` & `docs/CODEX_BUILD_PLAN.md`

## License

[MIT](LICENSE), selected by the repository owner. Third-party packages retain their own licenses; the release checklist records dependency and security review limits.
