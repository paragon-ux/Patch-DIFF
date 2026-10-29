# PatchDIFF

**Transactional document-editing service for MCP-connected agents.**

PatchDIFF turns model-generated document edits from unguarded file rewrites or ad-hoc local patches into **explicitly preconditioned, atomic, auditable, and deterministically replayable PostgreSQL transactions** exposed over the Model Context Protocol (MCP).

Agents propose structured text edits (`patchdiff-tx/1`, `patchdiff-tx/2`, or `patchdiff-tx/3`) against a canonical target document managed in PostgreSQL. PatchDIFF validates the proposal deterministically against exact text/span preconditions and required target version/hash guards, simulates all edits sequentially in memory, and either **commits the entire transaction atomically per target** (`SELECT ... FOR UPDATE`) or **rejects it without mutating target state** while returning bounded recovery diagnostics (`failure_context`, `exact_candidates`, and post-commit Levenshtein `near_misses`).

```text
PatchDIFF server = deterministic transaction runtime + authoritative read/commit service
MCP              = transport/interface (stdio JSON-RPC / internal registry)
Host / Model     = planning, context selection, proposal generator, retry owner
PostgreSQL 16+   = canonical working substrate (SELECT ... FOR UPDATE)
```

PatchDIFF is not a chat UI, rich document editor, semantic patch language, AST rewrite engine, fuzzy matcher, automatic merge system, or full-document regeneration workflow. The MCP host remains responsible for planning, generating proposals, and evaluating whether accepted edits accomplish the user's goal. See the [Concept Paper](docs/PatchDIFF-Concept-Paper-6.md), [release notes](CHANGELOG.md), [release checklist](docs/RELEASE_READINESS.md), and [security policy](SECURITY.md).

---

## 1. Why PatchDIFF Instead of Existing Edit Methods?

Coding agents and document workflows typically edit text through full-file rewrites, unique-string replacement (`str_replace`), line-oriented diffs (`diff -u` or V4A `apply_patch`), or line-range splices. While a host harness can build custom concurrency locks, rollback logic, retry deduplication, and audit tables around those formats, PatchDIFF provides those capabilities directly in its transaction protocol and PostgreSQL runtime:

| Editing Problem | Conventional Approach | What PatchDIFF Provides Directly |
| --- | --- | --- |
| **Small edit in a large file** | Full regeneration emits the complete replacement document on every turn | `patchdiff-tx/1` and `tx/2` emit only the matched/replaced spans plus compact transaction framing |
| **Repeated identical text** | Unique-match replacement (`str_replace`) requires expanding `old_str` with surrounding lines until unique | Explicit `occurrence_index`, `anchor_before` / `anchor_after` (`tx/1`), or guarded `[start, end)` spans (`tx/2`) without enlarging the match |
| **Line-oriented diff grammars (`diff -u` / V4A `apply_patch`)** | Traditional `diff -u` requires numeric `@@ -l,s +l,s @@` hunk header counts; OpenAI-style V4A `apply_patch` avoids numeric hunk counts via file-operation envelopes (`*** Update File:`) and contextual `@@` markers, but still requires line-prefixed diff grammar and context matching | Structured JSON fields (`patchdiff_submit_edits` / `patchdiff_submit_operations`); no numeric hunk-header arithmetic (`diff -u`), line-prefix diff grammar, or text-delimiter collision |
| **Coordinate & state drift** | Line-based edits depend on positions remaining unchanged since the agent last read the file | Required `expected_target_version` and/or `expected_current_hash` under `SELECT ... FOR UPDATE`, plus exact `expected_text` and optional `expected_before` / `expected_after` span checks |
| **Multiple changes in one target** | Single-replacement interfaces require $N$ separate tool calls (or leave multi-edit rollback to the host) | One `edits[]` / `operations[]` submission simulated sequentially in memory and committed all-or-nothing per target |
| **Missing or ambiguous match** | Basic interfaces return an error string, leaving the host to search for context in extra turns | Structured rejection with bounded `failure_context` (`<= 256` code points), up to 5 indexed `exact_candidates`, and up to 3 ranked Levenshtein `near_misses` |
| **Lost submission response** | Host must inspect current target state to guess whether a timed-out write succeeded before retrying | Retrying with the same `(target_file_id, client_request_id)` returns the exact recorded outcome (`deduplicated: true`) |
| **Long editing session & audit** | Host must maintain its own history, rejected-attempt logs, and state verification | Append-only attempt log (accepted + rejected), accepted manifest ledger with runtime-derived span/hash facts, `patchdiff_save` cycles, and profile-dispatched `patchdiff_replay` |

### How PatchDIFF Compares Across Editing Paradigms

- **Against Full-Document Regeneration:** Localized `patchdiff-tx/1` and `patchdiff-tx/2` transactions scale with the edited delta rather than target file length, and restrict mutations strictly to the matched or span-guarded regions. When a whole-document rewrite is intentionally desired, `patchdiff-tx/3` (`patchdiff_submit_replacement`) provides an explicit, version/hash-guarded replacement path (`<= 1,000,000` code points and `<= 1,048,576` UTF-8 bytes).
- **Against Line-Oriented Diffs (`diff -u` and V4A `apply_patch`):** Traditional `diff -u` unified diffs require numeric `@@ -l,s +l,s @@` hunk-header arithmetic, while OpenAI-style V4A `apply_patch` eliminates mandatory numeric hunk counts in favor of file-operation envelopes (`*** Begin Patch` / `*** Update File:`) and contextual `@@` markers. Both require models to emit line-prefixed diff syntax and surrounding context lines, CLI `patch` appliers may shift hunks when fuzz is enabled, and `apply_patch` delegates patch application, concurrency locking, and atomicity policy to the host harness; PatchDIFF uses structured JSON fields and enforces exact version/hash guards, per-target PostgreSQL transactional atomicity, and durable audit/retry semantics directly in the server.
- **Against Unique-Match `str_replace` (e.g., Anthropic Text Editor Tool):** Documented `str_replace` tools require `old_str` to match exactly once and reject zero or multiple matches, which is safe against silent first-match corruption but forces the model to copy surrounding context lines whenever a target line repeats (such as `"enabled: true"`). PatchDIFF preserves exact matching while allowing the model to disambiguate repeated strings via `occurrence_index`, `anchor_before` / `anchor_after`, or `tx/2` spans, and batches multiple edits in a single atomic call.
- **Against Unguarded Line-Range Editing:** Splicing by raw line numbers can silently corrupt text if earlier edits shift line offsets. PatchDIFF's `patchdiff-tx/2` (`patchdiff_submit_operations`) requires `expected_text` on every `[start, end)` code-point span, supports optional `expected_before` and `expected_after` adjacency guards (runtime profile `patchdiff-mvp-0.5.0`), and emits conservative UAX #29 `grapheme_boundary_split` advisory warnings without silently guessing boundaries.
- **Alternatives for Different Problem Domains:** AST / RFC 6902 JSON Patch tools are purpose-built for structural tree mutations on parsed JSON/code ASTs, and OT / CRDT systems (Yjs, Automerge) are designed for concurrent lock-free multi-user merging. PatchDIFF targets arbitrary canonical UTF-8 documents (Markdown, Python, YAML, JSON, prose) where stale or conflicting agent edits must be deterministically rejected rather than auto-merged.

---

## 2. How PatchDIFF Resolves Common Agent-Editing Failures (Strict Matching Without Blind Recovery)

```mermaid
sequenceDiagram
    participant Host as MCP Host / Agent
    participant PD as PatchDIFF MCP Server
    participant PG as PostgreSQL 16 (Authoritative State)

    Host->>PD: 1. patchdiff_read_target / patchdiff_read_lines / patchdiff_find_occurrences
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
        PD-->>Host: status="rejected", failure_reason, diagnostic.failure_context, exact_candidates / near_misses
        Host->>PD: 3. Inspect diagnostics & resubmit with parent_pdcp_log_id
    end
```

### The Strict-Matching Tradeoff: Enforcing Applicability Without Fuzzy Auto-Mutation

Strict exact matching prevents the runtime from silently applying an edit at the wrong location, but it creates a well-known agent usability challenge: models occasionally quote slightly stale whitespace/characters (`match_absent`) or target a string that appears multiple times (`match_ambiguous`).

> **Scope of Strict Matching:** Strict matching and state guards enforce **transaction applicability and selection constraints**—guaranteeing that an edit applies only to the exact target state and text span specified. They do **not** guarantee semantic or task correctness (`task_correct: "not_evaluated"`, `semantic: "not_evaluated"`), nor do they guarantee that an agent will successfully repair a rejected proposal.

Instead of weakening exact matching with fuzzy auto-application, PatchDIFF returns **bounded, machine-actionable recovery diagnostics** on rejection so the host/agent can formulate an exact retry:

1. **Ambiguous Match (`match_ambiguous` / `anchor_ambiguous`):** Returns `diagnostic.exact_candidates` containing `occurrence_count` and up to **5 indexed exact occurrences** (`occurrence_index`, `start`, `end`, `before`, `match_preview`, `match_truncated`, `after`, capped at `<= 8,192` compact ASCII JSON bytes) so the agent can resubmit immediately with `"occurrence_index": k` or a `[start, end)` span.
2. **Missing Match (`match_absent`):** After releasing the database lock on a service-owned transaction, PatchDIFF scans up to the first `65,536` Unicode code points of the failing buffer (when `len(match) <= 64` code points, under a `1,000,000` comparison-cell budget) and returns top-level `near_misses` with up to **3 ranked exact Levenshtein candidates** (`distance`, `start`, `end`, `text`, `before`, `after`, capped at `<= 8,192` compact ASCII JSON bytes).
3. **Consumed Sequential Match (`sequential_match_invalid`):** If edit $i$ fails because earlier edit $j < i$ in the same transaction already modified or consumed its match span, PatchDIFF reports `consumed_by_change_id` and up to 5 transaction-start `original_occurrences` (and omits `near_misses` with `omission_reason: "sequential_match_consumed"`).
4. **Read-Only Dry-Run (`patchdiff_preview`):** Hosts can validate and simulate any `tx/1`, `tx/2`, or `tx/3` proposal in memory (`<= 32,768` compact ASCII JSON bytes) without acquiring row locks, writing audit rows, or advancing target state.

---

## 3. Operational Efficiency: Payload, Context, Tool Calls, and Latency

Claims below use four explicit evidence labels (`docs/MODERNIZATION_ARCHITECTURE.md` Decision A8):
- **`Measured`**: Deterministic UTF-8 serialization byte counts from `backend/tests/verification/offline_eval.py` or local benchmark medians on specified workloads.
- **`Derived`**: Exact arithmetic or tool-call counts for an explicitly specified interface workflow.
- **`Illustrative`**: Clearly labeled token or decoding-time illustrations stating their conversion assumptions (not tokenizer measurements).
- **`Not yet measured`**: Live-model comparative accuracy, retry-turn distributions, and end-to-end agent turn latency (`NOT RUN`).

### 3.1 Output Payload Size & Scaling (`Measured` + `Derived`)

Reproducible via `PYTHONPATH=backend python backend/tests/verification/offline_eval.py` (using a fixed 36-char `target_file_id`, concise `intent`, `expected_target_version: 0`, and compact UTF-8 JSON):

| Scenario (`backend/tests/verification/offline_eval.py`) | `patchdiff-tx/1` Minimal (`typed_min`, MCP `arguments` / Stored) | `patchdiff-tx/1` with Prose (`typed_match`, MCP `arguments` / Stored) | `patchdiff-tx/3` Whole-Target Replacement (`arguments` / Stored / `tools/call` Line) | Verdict & Delimiter Safety |
| --- | --- | --- | --- | --- |
| **1 tiny edit (`"old" -> "new"`)** | **`151 B`** / **`206 B`** | `327 B` / `382 B` | `232 B` / `290 B` / `341 B` | `accepted` |
| **5 small edits (`5 × 1-byte edits`)** | **`259 B`** / **`314 B`** | `1,139 B` / `1,194 B` | — | `accepted` (atomic all-or-nothing) |
| **1 edit, 2 KB span (`2,109 B` text)** | **`4,441 B`** / **`4,496 B`** | `4,617 B` / `4,672 B` | `2,377 B` / `2,435 B` / `2,486 B` | `accepted` |
| **Quotes + backslashes + Unicode (`🌟`, `中`)** | **`172 B`** / **`227 B`** | `348 B` / `403 B` | `250 B` / `308 B` / `359 B` | `accepted` |
| **Payload has a delimiter line (`"a\n=======\nb"`)** | **`162 B`** / **`217 B`** | `338 B` / `393 B` | — | **`accepted`** (eliminates `.pdcp` `=======` collision) |

- **Marginal edit cost (`Derived`):** Each additional minimal edit item in `edits[]` adds **`25 B`** of JSON keys/punctuation (`{"match":"","replace":""}`) + **`1 B`** comma separator + the JSON-escaped UTF-8 lengths of `match` and `replace` (**`+28 B` per additional edit** with two 1-byte ASCII strings).
- **Scaling comparison (`Derived` / `Illustrative`):** On a 64 KB (`65,536 B`) file, a full-document rewrite must emit all `65,536 B` of content (`~16,384` tokens under an illustrative `~4 UTF-8 bytes ≈ 1 token` code/English rule of thumb), whereas a 1-edit `patchdiff-tx/1` `arguments` payload is **`151 B`** (>99.7% fewer output bytes). When editing a repeated short line (e.g., `"enabled: true"`), a unique-match `str_replace` call must duplicate enough surrounding lines in both `old_str` and `new_str` to make the block unique, whereas `patchdiff-tx/1` adds `"occurrence_index": 2` (**`+21 B`**) to the short match.

### 3.2 Input Context Window Protection (`Measured` Runtime Caps)

Every PatchDIFF read, search, preview, rejection, and history response enforces deterministic bounds so large targets or high-volume edit logs do not flood the agent's context window:

| Surface | Enforced Bound & Unit | Operational Effect |
| --- | --- | --- |
| **Authoritative Reads (`patchdiff_read_target`, `patchdiff_read_lines`)** | **`4,000` default / `8,000` max Unicode code points** per call | Returns bounded slice with `truncated` flag and `next_start` (or `next_offset` / `next_start` on line reads) |
| **Exact Search (`patchdiff_find_occurrences`)** | `context_chars` default **`40`** / cap **`400`** code points; `max_results` default/cap **`200`** | Locates all exact occurrences (including overlapping matches) with compact surrounding snippets |
| **Rejection Enrichment (`failure_context`, `current_context`, `exact_candidates`, `near_misses`)** | **`<= 18,432 B` compact ASCII-escaped JSON** across newly added enrichment fields (`<= 4,096 B` per context window; `<= 8,192 B` per candidate block; `<= 256` code points in `FailureBufferContext`) | Provides immediate recovery context without dumping the full document into the error payload |
| **Advisory Preview (`patchdiff_preview`)** | **`<= 32,768 B` compact ASCII-escaped JSON** (`<= 16,384 B` for up to 32 `change_facts` at `<= 2,048 B` each; `<= 16,384 B` diagnostics) | Bounds dry-run output on multi-edit transactions |
| **History & Ledger Paging (`patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`)** | `limit` default **`50`** / cap **`200`**; `intent` bounded to **`<= 256` chars**, `rationale` to **`<= 128` chars**; `include_content=True` on `patchdiff_get_pdcp_log` uses a **`1,048,576 B` UTF-8 page budget** (first entry with content returned whole; later entries over budget set `pdcp_content_omitted: "page_byte_budget"`) | Inspects audit history in SQL without transferring multi-megabyte `pdcp_content` blobs into the prompt |

### 3.3 Tool Invocations for Multi-Edit & Recovery Workflows (`Derived`)

*Note: Counts below compare deterministic **tool invocations** for a specified operation. Whether fewer tool calls or richer diagnostics reduce end-to-end **model turns** across diverse tasks requires a controlled live-model study (`Not yet measured`).*

| Workflow Scenario | Single-Replacement / Basic Tool Interface (`Derived` Calls) | PatchDIFF MCP Interface (`Derived` Calls) | Mechanism |
| --- | --- | --- | --- |
| **Apply 5 distinct edits to one target** | **`5` tool calls** (five separate single-replacement invocations, with partial state if call $k$ fails) | **`1` tool call** (`patchdiff_submit_edits` with 5 items in `edits[]`, or `2` with optional `patchdiff_preview`) | Sequential in-memory simulation and atomic per-target commit |
| **Recover from an ambiguous match (`match_ambiguous`, <= 5 occurrences)** | **`2+` calls** (rejection error → search/read call to locate occurrences → retry call) | **`1` retry call** (`exact_candidates` in the rejection response already supplies `occurrence_index` and `[start, end)` coordinates) | Built-in `exact_candidates` enrichment on rejection |
| **Recover from a minor typo (`match_absent`, needle <= 64 chars)** | **`2+` calls** (rejection error → read/search call around suspected region → retry call) | **`1` retry call** when the target string appears in the top 3 `near_misses` candidates (`text`, `start`, `end`) | Post-commit Levenshtein `near_misses` scan on the failing buffer |
| **Recover from a lost/timed-out submission response** | **`2` calls** (read target to inspect whether edit was applied → conditional retry) | **`1` call** (resubmit identical request with the same `client_request_id`; server returns recorded outcome with `deduplicated: true`) | Durable `(target_file_id, client_request_id)` idempotency table |

### 3.4 Latency: Model Generation Scaling vs. Internal Server Benchmarks (`Illustrative` vs. `Measured`)

End-to-end editing latency consists of **model output decoding time** (typically tens of milliseconds per output token), **MCP transport**, and **PatchDIFF server + PostgreSQL execution**:

1. **Model Generation Cost (`Illustrative`):** Because autoregressive decoding time scales linearly with output tokens, emitting a **`151 B`** (`~38`-token illustrative) `patchdiff-tx/1` request instead of regenerating a **`65,536 B`** (`~16,384`-token illustrative) document avoids generating thousands of unchanged tokens.
2. **Internal PatchDIFF Server & PostgreSQL Benchmarks (`Measured` — `PR #13` vs. `PR #14`):**
   The measurements below compare **internal PatchDIFF runtime optimizations (`PR #13` baseline vs. `PR #14`)** on Windows 11 (`Python 3.11.9`, `postgres:16.3-alpine` on `127.0.0.1:5432`). They are local fixture medians, not universal latency ceilings or cross-product benchmarks against external editors:
   - **Near-Miss Levenshtein Scan (`SVC-001`, 5-run local medians on `65,536`-code-point buffers, needle length `45`, threshold `4`):**
     Pairing an exact positional pigeonhole filter ($k+1=5$ disjoint pieces) with a Landau–Vishkin diagonal-wave banded DP reduced scan time on varied prose from `100.2 ms` (`174,897` cells) to **`1.7 ms`** (`585` cells, **58.9× faster** vs. PR #13), and on repetitive structured logs from `708.5 ms` (`1,000,000` cells, truncated at 69% of buffer) to **`41.9 ms`** (`142,255` cells, **16.9× faster** while scanning **100%** of the eligible buffer).
   - **PostgreSQL 16+ `LATERAL` History & Ledger Projection (`MCP-001`, 7-run local medians after warmup):**
     Extracting bounded `intent` and per-edit `rationale` in SQL (`pg_input_is_valid` + 4 KB head/tail slices + single-cast `LATERAL ... OFFSET 0`) rather than transferring full `pdcp_content` blobs to Python reduced `50 × 400 KB` (`20 MB`) `tx/3` history reads from `279.6 ms` to **`14.68 ms`** (**19.0× faster** on `patchdiff_get_manifest_ledger(limit=50)`) and from `372.4 ms` to **`22.85 ms`** (**16.3× faster** on `patchdiff_get_pdcp_log(limit=50)`). On a `20 × 1 MB` (`20 MB`) `tx/1` history (5 edits × 200 KB per row), `patchdiff_get_pdcp_log(limit=50)` runs in **`136.72 ms`** (`305.55 ms` baseline, **2.2× faster**), `patchdiff_get_manifest_ledger(limit=50)` runs in **`221.59 ms`** (`305.55 ms` baseline, **1.38× faster**), and `patchdiff_get_manifest_ledger(limit=100)` runs in **`445.33 ms`** vs. `449.92 ms` baseline (**1.01×**, at par while eliminating Python `pdcp_content` transfer).

See [backend verification](backend/tests/verification/README.md) for reproduction commands and the public CI input boundary. Internal experiment captures remain local in the ignored `evaluation/` directory.

---

## 4. Choosing a Transaction Format & 3-Step Walkthrough

### Typed Transaction Formats

| Format | MCP Tool | Runtime Profile | When to Use | Guard Requirement |
| --- | --- | --- | --- | --- |
| **`patchdiff-tx/1`** (Primary) | `patchdiff_submit_edits` | `patchdiff-mvp-0.2.2` | Default exact `MATCH/REPLACE` edits with optional `occurrence_index`, `anchor_before`, or `anchor_after` selectors. | `expected_target_version` and/or `expected_current_hash` |
| **`patchdiff-tx/2`** | `patchdiff_submit_operations` | `patchdiff-mvp-0.3.0` (`0.5.0` with `expected_before`/`after`) | Ordered `match` and `[start, end)` code-point `span` operations (`expected_text`, `replace`), descending multi-span edits from a single read, or verified insertions. | `expected_target_version` and/or `expected_current_hash` |
| **`patchdiff-tx/3`** | `patchdiff_submit_replacement` | `patchdiff-mvp-0.4.0` | Explicit whole-document replacement (`replacement` up to `1,000,000` code points and `1,048,576` UTF-8 bytes, raw and canonical). | `expected_target_version` and/or `expected_current_hash` |

*(For the frozen `.pdcp` v0.2.3 text format and `patchdiff_submit_pdcp`, see [docs/LEGACY_COMPATIBILITY.md](docs/LEGACY_COMPATIBILITY.md).)*

### 3-Step Host Walkthrough

**Step 1 — Read authoritative state (`patchdiff_read_target`, `patchdiff_read_lines`, or `patchdiff_find_occurrences`):**
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
Response returns `content`, `version: 0`, `current_hash: "8f434346..."`, `truncated: false`, and `next_start: null`.

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
  "manifest_entries_added": 1,
  "warnings": [],
  "warning_details": [],
  "warning_count": 0,
  "warnings_truncated": false,
  "validity": {
    "protocol_valid": true,
    "transaction_valid": true,
    "task_correct": "not_evaluated",
    "semantic": "not_evaluated"
  },
  "evidence": {
    "changes": [
      {
        "change_id": "edit_1",
        "change_index": 1,
        "op": "match",
        "span_start": 14,
        "span_end": 25,
        "matched_chars": 11,
        "replacement_chars": 13
      }
    ]
  },
  "deduplicated": false,
  "client_request_id": "req-theme-001"
}
```

**Step 3b — Or Structured Rejection with Top-Level Near-Miss Diagnostics (`match_absent`):**
If the target actually contained `"theme: drak"`, the target is untouched (`current_version: 0`) and PatchDIFF returns:
```json
{
  "status": "rejected",
  "target_file_id": "11111111-1111-4111-8111-111111111111",
  "failure_reason": "match_absent",
  "failure_detail": "edit_1 MATCH text was not found in the target.",
  "failed_change_id": "edit_1",
  "current_version": 0,
  "pdcp_log_id": "33333333-3333-4333-8333-333333333333",
  "near_misses": {
    "kind": "near_miss",
    "status": "computed",
    "omission_reason": null,
    "candidates": [
      {
        "distance": 2,
        "start": 14,
        "end": 25,
        "text": "theme: drak",
        "before": "# Settings\n",
        "after": "\nnotifications: "
      }
    ],
    "returned_count": 1,
    "truncated": false,
    "scope_truncated": false,
    "candidates_truncated": false,
    "scan_source": "failing_buffer",
    "scanned_start": 0,
    "scanned_end": 36,
    "buffer_stage": "canonical_target",
    "prior_changes": 0
  },
  "diagnostic": {
    "retryable": true,
    "requires_new_submission": true,
    "requires_new_pdcp": true,
    "failure_context": {
      "available": true,
      "selection": "prefix",
      "buffer_stage": "canonical_target",
      "prior_changes": 0,
      "start": 0,
      "end": 46,
      "total_chars": 46,
      "text": "# Settings\n\ntheme: drak\nnotifications: true\n",
      "truncated": false
    }
  }
}
```

---

## 5. Guarantees, Operational Bounds, and Limitations

- **Managed PostgreSQL Authority & Per-Target Scope:** PatchDIFF manages canonical target state in PostgreSQL under `SELECT ... FOR UPDATE`. Atomicity is guaranteed **per `target_file_id`**, not across multiple targets or arbitrary unindexed filesystem paths. Exporting (`patchdiff_export_target`) writes a snapshot; external edits to exported files on disk are not tracked unless uploaded/initialized.
- **No Automatic Merge or Semantic Validation:** Concurrent conflicting edits are deterministically rejected (`target_version_mismatch`, `target_hash_mismatch`, `target_diverged`). PatchDIFF never evaluates syntax, type safety, or task correctness (`task_correct: "not_evaluated"`, `semantic: "not_evaluated"`).
- **Canonical LF Normalization & Unicode Code-Point Indexing:** All target content and edit payloads are canonicalized (`\r\n` and `\r` normalized to `\n`), and all read/span coordinates (`start`, `end`, `length`) are 0-based **Unicode code-point** offsets (JavaScript/TypeScript hosts must convert UTF-16 string indices). Migration `20261022_0003` records upload line-ending style so `patchdiff_export_target(format="original_eol")` can restore uniform CRLF on export.
- **Intermediate-Buffer Coordinate Rule (`prior_changes > 0`):** Because multi-edit transactions execute sequentially in memory, if edit $k > 1$ fails, `failure_context`, `exact_candidates`, and `near_misses` report `buffer_stage: "intermediate_buffer"` and `prior_changes: k - 1`. Their offsets and `occurrence_index` values refer to the **in-memory buffer after the earlier simulated changes**, not the persisted canonical target.
- **Advisory Preview & Unreserved State:** `patchdiff_preview` acquires no row lock, writes no audit rows, and does not reserve a version or hash; subsequent submission re-locks and re-validates all preconditions.
- **Conditional Near-Miss Scanning:** `near_misses` runs only after a service-owned transaction commits and releases its lock. It is omitted with explicit `omission_reason` when `len(match) > 64` code points (`"match_too_large"`), when called inside a caller-owned transaction (`"caller_transaction"`), when an earlier edit in the same transaction consumed the match (`"sequential_match_consumed"`), when historical context is unavailable (`"historical_context_unavailable"`), or when the first window exceeds `MAX_COMPARISON_CELLS = 1,000,000` (`"work_budget_exhausted"`).
- **Conservative Grapheme Warning:** `grapheme_boundary_split` is an advisory, conservative approximation of UAX #29 rules (combining marks, ZWJ, regional indicators, emoji modifiers/variation selectors); it never alters transaction verdicts or replay.

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

Run migrations through `20261027_0005` (bundled scope observations):

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

External MCP defaults to the **7-tool `editor` profile**: `patchdiff_read_target`,
`patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_edits`,
`patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay`.
Set trusted startup `PATCHDIFF_MCP_PROFILE=unobserved` (5), `observed` (6),
`observed_editor` (4), or `full` (22). Use `observed_editor` for delegated editing
when the host owns SAVE/replay; excluded tools are not advertised or callable.
Older integrations and trusted initialization/export operators must
explicitly select `full`. Both discovery and dispatch enforce the same immutable
profile. The internal registry retains every handler listed below.

Select multiple structures with `patchdiff_observe_scope(selections=...)` and
submit their scope-local operation `groups` in one guarded atomic transaction
through `patchdiff_submit_observed_operations`. A successful batch advances the
target once and links every scope for deterministic replay.
[Exact contracts and executable examples](docs/STRUCTURAL_BATCH_EDITING.md).

- **Document Lifecycle**: `patchdiff_handle_upload`, `patchdiff_initialize_target`, `patchdiff_get_target`, `patchdiff_export_target`
- **Authoritative Reads & Exact Search**: `patchdiff_read_target` (bounded slices with `next_start`), `patchdiff_read_lines` (inclusive LF ranges with `next_offset` / `next_start`), `patchdiff_find_occurrences` (exact spans with context and pagination)
- **Guarded Submission**: `patchdiff_submit_edits` (`patchdiff-tx/1`), `patchdiff_submit_operations` (sequential match/span edits, `patchdiff-tx/2`), `patchdiff_submit_replacement` (sole explicit whole-target replacement, `patchdiff-tx/3`)
- **Advisory Preview**: `patchdiff_preview` (bounded verdict/facts without audit rows, keys, or target mutation)
- **Checkpoints, Replay & History**: `patchdiff_save` (editing cycle rotation), `patchdiff_replay` (deterministic profile-dispatched reconstruction), `patchdiff_get_pdcp_log` (bounded attempt log), `patchdiff_get_manifest_ledger` (accepted changes with runtime facts)
- **Legacy Compatibility**: Frozen `.pdcp` v0.2.3 submission (`patchdiff_submit_pdcp`) and compatibility wrappers (`patchdiff_build_prompt_context`, `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`) are documented in [docs/LEGACY_COMPATIBILITY.md](docs/LEGACY_COMPATIBILITY.md).

See [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) and [docs/HOST_INTEGRATION_GUIDE.md](docs/HOST_INTEGRATION_GUIDE.md).

The explicit `full` catalog retains all 22 tools and the existing executable discovery examples. Bind examples to actual target IDs, guards, rejection parents, and returned cursors. A preview does not reserve state: subsequent submission must recheck a version or hash guard. Span and whole-target replacement always require a guard; a version guard also detects intervening no-op/ABA edits. Correlation IDs are opt-in invocation metadata, separate from caller-known retry keys.

## Testing & Offline Evaluation

Run unit and integration tests against live Postgres:

```powershell
# Unit tests (pure runtime, 816 tests)
.\.venv\Scripts\python.exe -m pytest backend/tests/unit -q

# Integration tests (live Postgres & real stdio subprocess, 410 tests)
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
.\.venv\Scripts\python.exe -m pytest backend/tests/integration -q

# Offline evaluation (payload bytes and applier verdict equivalence)
.\.venv\Scripts\python.exe backend/tests/verification/offline_eval.py
```

See [backend verification](backend/tests/verification/README.md) for reproduction instructions.

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
10. `docs/PatchDIFF-Concept-Paper-6.md` (modernized conceptual whitepaper: theoretical model, edit-method comparison, operational efficiency bounds, and research hypotheses; supersedes historical `docs/PatchDIFF-Concept-Paper-5.md`)
11. `docs/TEST_MATRIX.md`, `docs/CODEX_BUILD_PLAN.md` & `backend/tests/verification/README.md`

## License

[MIT](LICENSE), selected by the repository owner. Third-party packages retain their own licenses; the release checklist records dependency and security review limits.
