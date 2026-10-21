# G-Series Friction Inventory: Live Agent Workflow Analysis

- **Review Date**: 2026-10-21
- **Reviewer**: Gemini in Antigravity (Pair Programming Agent)
- **Target Revision**: `b5caa40bd41848420c4323d22ab648847cdc6745` (Head of PR #9)
- **Evaluation Environment**: Windows 11 Pro, Python 3.12, PostgreSQL 16.3 on Docker, native stdio MCP transport
- **Workflows Tested**: W1–W12 across 5 realistic target fixtures (T1–T5)

---

## Overview

During the execution of the 12 real-agent workflows (W1–W12), the PatchDIFF deterministic transaction runtime, Postgres locking substrate, and append-only audit models functioned with 100% correctness. However, several operational friction points emerged at the boundary between the host agent and the MCP server interface. 

These findings are cataloged below under the **`G*` series**. They represent observed host frictions that are distinct from the Devin Goal F backlog (`F01`–`F14`), providing empirical data on where autonomous agents hesitate, waste round-trip calls, or encounter ambiguous errors.

---

## Finding Summary Matrix

| ID | Title | Category | Severity | Workflow Origin | Agent Cost / Impact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **G01** | Subprocess Caching on Host Config Change | `DEP` / `DOC` | P3 | Setup | Process deadlock on manual kill (`0xffffffff`); requires session cycle. |
| **G02** | Windows Stdio Codepage Crash (`DEFECT-001`) | `DEP` / `MCP` | P1 | Setup / W4 | Immediate adapter crash on emojis/CJK unless `PYTHONIOENCODING=utf-8` set. |
| **G03** | Unexpected Tool Kwargs Trigger Server `TypeError` | `MCP` | P1 | Discovery / W1 | Unhandled exception bubbles to host instead of structured `-32602` error. |
| **G04** | Backward-Only Cursor Pagination in Manifest Ledger | `MCP` / `DOC` | P3 | W9 | Agent loops or receives empty pages trying forward pagination (`after_sequence`). |
| **G05** | Ledger Omission of Applied Diff Text for Typed Edits | `DB` / `DOC` | P2 | W9 | Agent forced to make redundant calls to `get_pdcp_log` to discover textual changes. |
| **G06** | Progressive In-Memory Buffer Shifting Across Multi-Edits | `DOC` / `SKILL` | P3 | W3 | Subsequent edits fail if agent references original snapshot instead of intermediate state. |
| **G07** | Omission of Target Version/Hash from Search Results | `MCP` / `SVC` | P2 | W5 | Forced redundant read or metadata lookup after finding exact match span. |
| **G08** | Selector Exclusivity and Strict Disambiguation Clashes | `RUN` / `SVC` | P2 | W1 / W8 | Conjunctive index + anchor mismatches fail with opaque ambiguous rejection. |

---

## Detailed Friction Records

### G01: Subprocess Caching on Host Configuration Change
* **Category**: `DEP` (Dependencies & Runtime Environment) / `DOC` (Documentation)
* **Severity**: P3 (Host Integration Friction)
* **Observed Context**: Setup & Antigravity MCP Server Registration
* **Trigger**: Modifying `~/.gemini/config/mcp_config.json` while the host environment is active to switch database connection strings or add environment variables.
* **Expected Behavior**: The host cleanly restarts the stdio subprocess with the new configuration, or provides a clear lifecycle signal.
* **Actual Behavior**: The running Python stdio process remains active in the background, bound to the old database. If the process is terminated via taskkill/kill from the host shell, subsequent tool calls in that turn fail with `exit status 0xffffffff` until an interactive turn boundary completes.
* **Agent Hesitation & Cost**: The agent cannot reliably verify configuration changes in the same turn; requires diagnostic shell probing and manual process reconciliation.
* **Distinction from F01–F14**: F14 standardizes stdio external adapter protocol conformance; G01 identifies orchestrator-level process lifecycle and config-reloading expectations.
* **Remediation**: Add explicit process lifecycle and reconnection guidance in [`docs/HOST_INTEGRATION_GUIDE.md`](file:///c:/Users/USER/Desktop/Frameworks/Patch-DIFF/docs/HOST_INTEGRATION_GUIDE.md).

---

### G02: Windows Stdio Default Codepage Encoding Crash (`DEFECT-001`)
* **Category**: `DEP` / `MCP`
* **Severity**: P1 (High - Platform Reliability)
* **Observed Context**: W4 (Encoding-sensitive edit on T3 `notes.txt`)
* **Trigger**: Reading or receiving error diagnostics containing emojis (`🌟🚀`) or non-ANSI CJK glyphs over stdio on Windows without `PYTHONIOENCODING=utf-8` set.
* **Expected Behavior**: The stdio stream outputs valid UTF-8 JSON-RPC envelopes across all operating systems.
* **Actual Behavior**: Python fails with `UnicodeEncodeError: 'charmap' codec can't encode character...` in `external_adapter.py`, terminating the subprocess with exit code 1.
* **Agent Hesitation & Cost**: Complete loss of communication channel; agent experiences tool call drop without receiving a diagnostic error response.
* **Distinction from F01–F14**: F01–F14 address core validation, diagnostics, and formats; G02 is a platform-specific transport encoding defect in the stdio adapter.
* **Remediation**: Reconfigure `sys.stdin` and `sys.stdout` to UTF-8 on adapter startup (`backend/app/mcp/external_adapter.py`). See [DEFECT-001](file:///c:/Users/USER/Desktop/Frameworks/Patch-DIFF/docs/reviews/gemini/DEFECT-001-windows-stdio-utf8.md).

---

### G03: Unexpected Tool Kwargs Trigger Server `TypeError`
* **Category**: `MCP` (Schemas and Public API)
* **Severity**: P1 (Protocol Robustness)
* **Observed Context**: W1 & Discovery
* **Trigger**: Invoking an MCP tool with an extraneous parameter (e.g., passing `version: 1` or `expected_version` to `patchdiff_read_target`, intuitively passed by an agent expecting guard checks on reads).
* **Expected Behavior**: The server catches unexpected parameters and returns a structured JSON-RPC error `-32602` (Invalid params) or a schema validation diagnostic.
* **Actual Behavior**: The MCP adapter unpacks `**params` directly into the function call, raising Python `TypeError: patchdiff_read_target() got an unexpected keyword argument 'version'`. The exception bubbles up as an unhandled server error (`-32603`).
* **Agent Hesitation & Cost**: The agent assumes the server suffered an internal crash rather than a parameter mismatch, leading to unnecessary debugging cycles.
* **Distinction from F01–F14**: F12 provides discovery examples in `tools/list`; G03 addresses parameter parsing robustness in the dispatch adapter.
* **Remediation**: In `backend/app/mcp/external_adapter.py`, validate incoming tool arguments against declared tool signatures/schemas before invoking service functions, returning clean `-32602 Invalid params` envelopes.

---

### G04: Backward-Only Cursor Pagination in Manifest Ledger
* **Category**: `MCP` / `DOC`
* **Severity**: P3 (API Ergonomics)
* **Observed Context**: W9 (History Review on T2 `README.md`)
* **Trigger**: Paginating through transaction history using `patchdiff_get_manifest_ledger`.
* **Expected Behavior**: Conventional cursor pagination advances forward into the future or provides an explicit `next_cursor` token without directional ambiguity.
* **Actual Behavior**: Ledger entries are listed in ascending chronological order (`sequence: 1, 2, 3`), but the pagination cursor is strictly backward (`before_sequence = min_sequence - 1`). When the agent intuitively provided the highest observed sequence to fetch subsequent items, it received empty results.
* **Agent Hesitation & Cost**: 2 wasted recovery calls to deduce that `before_sequence` paginates backward toward history inception, and that pagination must start from the end of the chain.
* **Distinction from F01–F14**: F13 preserves display order within pages; G04 concerns the reverse cursor direction across paged history queries.
* **Remediation**: Explicitly document reverse-chronological pagination semantics in `tools/list` schema descriptions and consider adding an `after_sequence` cursor in a future profile.

---

### G05: Ledger Omission of Applied Diff Text for Typed Edits
* **Category**: `DB` (Database & Ledger Invariants) / `DOC` (Documentation)
* **Severity**: P2 (Auditability Gap)
* **Observed Context**: W9 (History Review on T2)
* **Trigger**: Querying `patchdiff_get_manifest_ledger` to answer: *"What text was changed in T2?"*
* **Expected Behavior**: The ledger entry provides a summary or diff excerpt of the textual change.
* **Actual Behavior**: For typed transactions (`origin="typed"`), ledger rows record derived span bounds and hashes (`span_start`, `span_end`, `before_hash`, `after_hash`), but leave prose fields as `null` and do not store `match` or `replace` strings.
* **Agent Hesitation & Cost**: The agent could not answer the question from the ledger alone; it had to execute an additional lookup via `patchdiff_get_pdcp_log(include_content=true)` to parse the raw JSON transaction payload, doubling call overhead and token consumption.
* **Distinction from F01–F14**: F07 and F09 introduce new transaction representations; G05 is a read-side auditability gap between the manifest ledger and the attempt log.
* **Remediation**: Preserve the locked `manifest_ledger` database schema (no migration). Document `patchdiff_get_pdcp_log(include_content=true)` as the authoritative diff retriever in `HOST_INTEGRATION_GUIDE.md`, and evaluate a read-side `include_diff_excerpt` parameter that hydrates snippets in memory without altering table storage.

---

### G06: Progressive In-Memory Buffer Shifting Across Multi-Edits
* **Category**: `DOC` / `SKILL` (Agent Instructions & Cognitive Model)
* **Severity**: P3 (Host Mental Model Friction)
* **Observed Context**: W3 (Atomic multi-edit transaction on T2)
* **Trigger**: Submitting a multi-edit array (`edits: [edit1, edit2, edit3]`) where edit 1 changes the length of a section, and edit 2 targets text below edit 1.
* **Expected Behavior**: LLMs intuitively construct matches and anchors against the static target content they just read via `patchdiff_read_target`.
* **Actual Behavior**: In PatchDIFF, edits apply sequentially to an immediate in-memory buffer. Edit 2 must match against the *post-edit-1 buffer*, meaning any anchors or matches overlapping or immediately adjacent to edit 1's boundary must account for edit 1's replacement text.
* **Agent Hesitation & Cost**: Multi-edit transactions fail on edit 2 if the agent does not manually simulate intermediate buffer shifts.
* **Distinction from F01–F14**: F08 standardizes selector semantics; G06 represents host-side cognitive friction with sequential buffer mutation invariants.
* **Remediation**: Add explicit multi-edit progressive buffer examples in `tools/list` schema descriptions and [`docs/MCP_TOOLS.md`](file:///c:/Users/USER/Desktop/Frameworks/Patch-DIFF/docs/MCP_TOOLS.md) (aligned with **F12**).

---

### G07: Omission of Target Version/Hash from Search Results
* **Category**: `MCP` / `SVC` (Service Orchestration)
* **Severity**: P2 (Tool Ergonomics & Redundant Calls)
* **Observed Context**: W5 (Large file editing on T4 `large.md`)
* **Trigger**: Calling `patchdiff_find_occurrences` to locate an exact match string in a large target without reading the entire document.
* **Expected Behavior**: The search response returns the target version and hash alongside matched spans, enabling immediate guarded transaction construction.
* **Actual Behavior**: `patchdiff_find_occurrences` returns occurrences, spans, and snippets, but omits `target_version` and `target_current_hash`.
* **Agent Hesitation & Cost**: The agent cannot construct a guarded transaction (`expected_target_version`, `expected_current_hash`) from search results alone; it must make a redundant call to `patchdiff_get_target` or `patchdiff_read_target` solely to retrieve the version/hash header.
* **Distinction from F01–F14**: F10 proposes a read-only line/range helper; G07 addresses metadata parity between search and read tool responses.
* **Remediation**: Enrich `patchdiff_find_occurrences` response to include `target_version` and `target_current_hash` (zero schema migration required).

---

### G08: Selector Exclusivity and Strict Disambiguation Clashes
* **Category**: `RUN` (Core Runtime) / `SVC` (Service Diagnostics)
* **Severity**: P2 (Diagnostic Clarity)
* **Observed Context**: W1 & W8
* **Trigger**: An agent provides both `occurrence_index` AND `anchor_before`/`anchor_after` to be defensively specific, but the anchor matches a different span than the index.
* **Expected Behavior**: The server returns an actionable diagnostic identifying that `occurrence_index` and `anchor` matched conflicting spans.
* **Actual Behavior**: The transaction is rejected as `ambiguous_match` or `anchor_failed` without explaining that the two selectors clashed with each other.
* **Agent Hesitation & Cost**: The agent attempts to fix whitespace in the anchor rather than realizing the index and anchor were mutually exclusive, increasing retry cycles.
* **Distinction from F01–F14**: F06 addresses ambiguity candidates; G08 specifically targets diagnostic visibility for conjunctive selector conflicts.
* **Remediation**: Fold into Goal F Phase B (**F05/F06**): augment rejection diagnostics to report selector clash details when both index and anchors are supplied.
