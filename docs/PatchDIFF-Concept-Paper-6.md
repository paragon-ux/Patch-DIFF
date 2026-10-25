# PatchDIFF: Transaction-Enveloped State Transitions for Auditable, Low-Decoding-Cost LLM Document Editing

> **Edition & Authority Note (Concept Paper v6):** This paper is the current conceptual and research edition for PatchDIFF, superseding the historical v0.2.3 paper ([PatchDIFF-Concept-Paper-5.md](PatchDIFF-Concept-Paper-5.md), which is preserved untouched as a historical design record). Concept Paper v6 explains PatchDIFF's theoretical model, design rationale, edit-method comparisons, generalized formal transaction model (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`, and legacy `.pdcp` v0.2.3), operational efficiency analysis, and research hypotheses (`H1`–`H7`). For executable MCP tool schemas, persistence behavior, runtime profiles, and exact byte/code-point limits, the normative specifications ([MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md), [MCP_TOOLS.md](MCP_TOOLS.md), [PATCHDIFF_CORE_SPEC.md](PATCHDIFF_CORE_SPEC.md), [DATA_MODEL.md](DATA_MODEL.md), [PDCP_FORMAT.md](PDCP_FORMAT.md), and [LEGACY_COMPATIBILITY.md](LEGACY_COMPATIBILITY.md)) govern.

---

## Abstract

Large language models (LLMs) and coding agents are increasingly used to edit long-lived textual artifacts such as source files, Markdown specifications, configuration files, structured documents, and knowledge bases (Chen et al., 2021; Yao et al., 2023; Schick et al., 2023; Jimenez et al., 2024). Across contemporary systems, two interaction patterns dominate: full-document regeneration, where the model decodes an entire replacement artifact even when the requested change is local, and ad-hoc local editing tools (such as unique-string `str_replace` or line-oriented unified diffs), which reduce output size but typically leave optimistic concurrency locking, multi-edit rollback, repeated-string disambiguation, retry idempotence, and rejected-attempt auditing to custom host glue code.

PatchDIFF addresses this systems gap by treating model-generated edits as **transaction-enveloped textual state transitions** over an authoritative target document managed in PostgreSQL and exposed through the Model Context Protocol (MCP). Instead of rewriting a file unguarded or applying unverified local patches, an MCP host reads bounded canonical slices from PatchDIFF and submits declarative JSON transactions: localized exact-match edits (`patchdiff-tx/1`), guarded match and code-point span operations including zero-length insertions (`patchdiff-tx/2`), or explicitly authorized whole-target replacements (`patchdiff-tx/3`). A pure, deterministic runtime validates the transaction envelope, checks required target version and/or SHA-256 hash preconditions under PostgreSQL `SELECT ... FOR UPDATE`, simulates operations sequentially in memory, and either commits all changes atomically per target or rejects the transaction without mutating target state. Both accepted and rejected attempts are recorded in an append-only log with request-key idempotence (`client_request_id`) and retry lineage (`parent_pdcp_log_id`), while accepted changes populate an append-only manifest ledger pairing model-claimed intent with runtime-derived span and hash facts.

The central claim of PatchDIFF is not that textual diffs are new (Hunt and Szymanski, 1977; Myers, 1986; Chacon and Straub, 2014). Rather, PatchDIFF defines the **transactional runtime and lifecycle semantics** required to make model-generated textual deltas safe to apply, reject, recover, audit, checkpoint (`SAVE`), and deterministically replay across protocol evolution. PatchDIFF deliberately avoids AST rewriting, fuzzy auto-mutation, silent merge, and executable model-generated protocol logic. Strict precondition matching enforces transaction applicability and selection constraints rather than semantic or task correctness (`task_correct: "not_evaluated"`, `semantic: "not_evaluated"`), while bounded rejection diagnostics (`failure_context`, `exact_candidates`, and post-commit Levenshtein `near_misses`) convert uncertain model context into structured feedback for host-driven recovery.

---

## 1. Introduction

Large language models are now routinely deployed inside interactive coding and document-editing loops over long-lived artifacts: source code, configuration files, Markdown specifications, YAML/JSON manifests, and technical prose (Chen et al., 2021; Jimenez et al., 2024). In these workflows, reliability depends not only on whether a model can propose a plausible edit, but on how the surrounding system validates, applies, records, and recovers from faulty or stale proposals.

Historically, the simplest editing abstraction has been **full-state regeneration**: the host supplies a document, requests a modification, and the model emits a complete rewritten artifact. Full-state regeneration is both computationally expensive and operationally fragile. Even when a user requests a one-line change, the model must decode the entire file, unchanged regions may silently drift or be truncated, and an edit generated from stale context can overwrite newer state without detection. Retrieval-augmented generation reduces input context pressure by selecting relevant passages (Lewis et al., 2020), but retrieval alone does not make the retrieved view transactionally authoritative at write time.

To avoid full-file decoding, modern agent harnesses commonly adopt localized edit tools—most notably **unique-match string replacement** (`str_replace`, e.g., Anthropic, 2025) and **structured diff/patch tools** (`apply_patch`, e.g., OpenAI, 2025), alongside classical unified diffs and line-range splicers. These interfaces substantially reduce output tokens for small edits, but they expose a second layer of systems challenges during multi-turn agent loops:

1. **Disambiguation vs. context bloat:** In a unique-match `str_replace` interface, editing a repeated line (such as `"enabled: true"` in a configuration file) requires expanding `old_str` and `new_str` with enough surrounding lines to force global uniqueness.
2. **Hunk formatting and coordinate drift:** In unified diff or line-range interfaces, miscounted line headers (`@@ -l,s +l,s @@`) or stale line offsets after earlier edits cause hunk rejections or misplaced edits.
3. **Host-delegated transaction lifecycle:** Standard tool schemas define how a model formats an edit request, but leave optimistic concurrency control, all-or-nothing multi-edit rollback, lost-response retry idempotence, rejected-attempt logging, and deterministic replay to the host harness.
4. **Strict matching vs. blind recovery:** Strict exact matching prevents silent misplacement, but when a model quotes slightly wrong whitespace or encounters duplicate matches, a bare error string forces extra search/read turns to recover.

PatchDIFF resolves these problems by elevating document editing from a stateless string-replacement helper into a **server-side, PostgreSQL-backed deterministic transaction service** exposed over MCP (Anthropic, 2024). The canonical target resides in PostgreSQL. The host reads bounded slices or searches exact occurrences, submits a guarded declarative transaction (`patchdiff-tx/1`, `patchdiff-tx/2`, or `patchdiff-tx/3`), and receives either an atomic per-target commit with runtime-derived span/hash evidence or a structured rejection enriched with bounded recovery candidates.

### 1.1 Status of the Thesis, Implemented Mechanisms, Verified Properties, and Open Hypotheses

To maintain strict scientific and engineering clarity, this paper separates four layers of status across the PatchDIFF project:

| Layer | Status in Current System (`PR #14`, Runtime Profiles `0.1.0`–`0.5.0`) |
| --- | --- |
| **1. Core Architectural Thesis** | **Preserved from v0.2.3:** Model-generated edits are untrusted declarative proposals validated against canonical UTF-8 target state under optimistic concurrency guards, applied sequentially and atomically per target, logged in append-only accepted/rejected tables, compacted via `SAVE` cycles, and verified by deterministic replay. |
| **2. Modernized Runtime & Protocol Mechanisms** | **Implemented:** Typed JSON transaction formats (`patchdiff-tx/1` exact match edits, `patchdiff-tx/2` guarded `[start, end)` spans and zero-length insertions with optional `expected_before`/`expected_after` adjacency checks, `patchdiff-tx/3` guarded whole-target replacement) alongside frozen legacy `.pdcp` v0.2.3; MCP stdio JSON-RPC adapter and 20-tool surface; `(target_file_id, client_request_id)` idempotent outcome recovery; read-only `patchdiff_preview`; bounded rejection enrichment (`failure_context`, `exact_candidates`, and post-commit pigeonhole + Landau–Vishkin Levenshtein `near_misses`); line-ending preservation (`migration 0003`); and immutable replay profiles `patchdiff-mvp-0.1.0` through `0.5.0`. |
| **3. Deterministically Verified & Locally Benchmarked Properties** | **Verified:** **1,226 automated tests** (`816` pure unit tests + `410` live PostgreSQL 16.3 and real stdio MCP subprocess integration tests, including populated Alembic `upgrade -> downgrade -> upgrade` checks) and **235/235** live stdio friction checks; deterministic UTF-8 payload byte and verdict equivalence accounting (`evaluation/offline_eval.py`); and local fixture benchmarks for `SVC-001` near-miss scans (`1.7 ms` prose / `41.9 ms` repetitive log 5-run medians) and `MCP-001` PostgreSQL 16+ `LATERAL` history reads (`14.68 ms` ledger / `22.85 ms` log 7-run medians on 20 MB `tx/3` history). |
| **4. Open Empirical Research Hypotheses (`H1`–`H7`)** | **Designed, Not Yet Executed (`NOT RUN` for live-model / human studies):** While deterministic guarantees (`H2` locality for local operations, `H3` stale-guard rejection, `H5` profile-dispatched replay) and payload byte scaling (`H1` byte accounting) are established in software, controlled live-LLM comparative trials measuring actual token usage, task-level unintended edit rates, multi-turn recovery rates (`H1`–`H4`, `H7`), and human review studies (`H6`) have not been run (Decision A8). |

---

## 2. From Full-State Regeneration to Transaction-Enveloped Editing

In full-state regeneration, the model acts as an unverified state generator:

`T_new = LLM(T_old, instruction)`

Even when `T_new` differs from `T_old` by only a few characters, the model must re-emit the entire artifact, and the host must either overwrite `T_old` blindly or compute a post-hoc diff to infer what changed. Post-hoc diffing can show what the model altered after the fact, but it cannot distinguish an intentional edit from accidental drift in an unrelated paragraph, nor can it prevent a stale model turn from overwriting a concurrent update.

In PatchDIFF, the model does not emit a new target state. Instead, the model emits a **declarative transaction** $\tau$ containing a state guard $g$, transaction intent $I$, and ordered operations $\langle o_1, \dots, o_n \rangle$:

`T_new = Apply(T_current, τ)`

The runtime evaluates $\tau$ against the current authoritative target $T_{\text{current}}$. If the state guard $g$ or any operation precondition fails, `Apply` leaves $T_{\text{current}}$ unchanged and records a rejected transaction attempt.

| Editing Problem | Conventional Approach | What PatchDIFF Provides Directly |
| --- | --- | --- |
| **Small edit in a large file** | Full regeneration emits the complete replacement document on every turn | `patchdiff-tx/1` and `tx/2` emit only the matched/replaced spans plus compact transaction framing (`151 B` `arguments` JSON for 1 tiny edit) |
| **Repeated identical text** | Unique-match replacement (`str_replace`) requires expanding `old_str` with surrounding lines until unique | Explicit `occurrence_index`, `anchor_before` / `anchor_after` (`tx/1`), or guarded `[start, end)` spans (`tx/2`) without enlarging the match |
| **Unified diff formatting** | Agent must construct line-oriented hunks and maintain `@@ -l,s +l,s @@` header arithmetic | Structured JSON fields (`patchdiff_submit_edits` / `patchdiff_submit_operations`); zero hunk-header arithmetic or text-delimiter collision |
| **Coordinate & state drift** | Line-based edits depend on positions remaining unchanged since the agent last read the file | Required `expected_target_version` and/or `expected_current_hash` under `SELECT ... FOR UPDATE`, plus exact `expected_text` and optional `expected_before` / `expected_after` span checks |
| **Multiple changes in one target** | Single-replacement interfaces require $N$ separate tool calls (or leave multi-edit rollback to the host) | One `edits[]` / `operations[]` submission simulated sequentially in memory and committed all-or-nothing per target |
| **Missing or ambiguous match** | Basic interfaces return an error string, leaving the host to search for context in extra turns | Structured rejection with bounded `failure_context` (`<= 256` code points), up to 5 indexed `exact_candidates`, and up to 3 ranked Levenshtein `near_misses` |
| **Lost submission response** | Host must inspect current target state to guess whether a timed-out write succeeded before retrying | Retrying with the same `(target_file_id, client_request_id)` returns the exact recorded outcome (`deduplicated: true`) |
| **Long editing session & audit** | Host must maintain its own history, rejected-attempt logs, and state verification | Append-only attempt log (accepted + rejected), accepted manifest ledger with runtime-derived span/hash facts, `patchdiff_save` cycles, and profile-dispatched `patchdiff_replay` |

---

## 3. Authoritative Cached Target Editing Model

PatchDIFF separates **authoritative document storage** from **transient model context**. The canonical target document is stored in PostgreSQL (`cloud_target_files`) with its current integer `version`, canonical LF-normalized UTF-8 `content`, `current_hash` (SHA-256), and optional `source_line_endings` metadata (`"LF"`, `"CRLF"`, or `"MIXED"`).

Rather than loading an entire multi-thousand-line file into the prompt on every turn, the MCP host interacts with the cached target through bounded read and search primitives:

1. **Bounded code-point slice reads (`patchdiff_read_target`):** Reads `length` Unicode code points starting at 0-based code-point offset `start` (default `4,000`, maximum `8,000` code points), returning `content`, `version`, `current_hash`, `truncated`, and `next_start`.
2. **Bounded inclusive line reads (`patchdiff_read_lines`):** Reads 1-based inclusive line ranges (`start_line`..`end_line`) up to `8,000` Unicode code points (`max_chars`) with optional `line_offset`, returning line-numbered slices along with range-relative `next_offset` and absolute `next_start` cursors when truncated.
3. **Exact occurrence search (`patchdiff_find_occurrences`):** Enumerates all exact occurrences of a query string (including overlapping matches under runtime `patchdiff-mvp-0.2.2+`), returning 1-based `occurrence_index`, 0-based `[start, end)` code-point offsets, 1-based `line` and `column`, and bounded `context_before` / `context_after` snippets (default `40`, maximum `400` code points; up to `200` results per page with `next_occurrence_index`).

Because every read and search response returns the committed `version` and `current_hash` observed from PostgreSQL, the host can immediately bind its subsequent edit proposal to the exact target state it inspected.

---

## 4. Why Unified Diff and Host-Delegated Patch Tools Are Insufficient Alone

Unified diff (Myers, 1986) is a foundational representation for human code review and version control, and modern agent platforms expose structured patch tools such as OpenAI's `apply_patch` (OpenAI, 2025). However, using a diff syntax alone as an LLM editing protocol leaves three distinct gaps:

1. **Hunk syntax and line-count fragility:** Classical unified diffs require the model to emit `---`/`+++` headers, `@@ -l,s +l,s @@` line counts, and prefix characters (` `, `-`, `+`) for every line in a hunk. When a model miscounts lines or omits a context line, standard `patch` parsers reject the hunk—or, if configured with line-offset/fuzz tolerances, may apply the hunk at an unintended location.
2. **Text-delimiter collision in custom envelopes:** Line-oriented patch envelopes (including V4A-style diff wrappers and PatchDIFF's own legacy `.pdcp` v0.2.3 format) reserve marker lines such as `<<<<<<< MATCH`, `=======`, or `*** End Patch`. When the target document itself discusses merge conflicts, Markdown dividers (`=======`), or patch examples, raw text delimiters collide with payload content unless represented inside a structured string encoding such as JSON.
3. **Format vs. transaction authority:** OpenAI's `apply_patch` specification defines a structured tool call (`create_file`, `update_file`, `delete_file`) and explicitly delegates patch application, path validation, and atomicity semantics to the caller's host harness (OpenAI, 2025). Thus, while `apply_patch` can express multi-file operations when backed by a capable host, the format itself does not provide an authoritative state database, required version/hash preconditions, durable rejected-attempt logs, or request-key idempotence. PatchDIFF provides those transactional guarantees directly inside the server per target.

---

## 5. Unique-Match `str_replace` and Unguarded Line-Range Editing

Two other local editing paradigms are widely used in agentic coding:

### 5.1 Unique-Match `str_replace` Interfaces

Anthropic's documented text-editor tool (`str_replace_based_edit_tool` / `text_editor_20250728`; Anthropic, 2025) replaces an exact `old_str` with `new_str` and rejects the call when `old_str` appears zero times or more than once. Requiring a unique exact match is a sound safety choice—it avoids the silent corruption of naive first-match `string.replace()` implementations.

However, a unique-match-only interface introduces three structural limitations that PatchDIFF directly addresses:

1. **Context padding on repeated text:** When the line to be edited occurs multiple times in a file (e.g., `"retry: false"`, `"version = \"0.1.0\""`, or a repeated closing block), the model cannot submit the short target line as `old_str`. It must copy 10–30 surrounding lines into both `old_str` and `new_str` solely to construct a globally unique string. In PatchDIFF, the model keeps `match` minimal and disambiguates via `occurrence_index: 2`, `anchor_before` / `anchor_after` (`patchdiff-tx/1`), or an explicit `[start, end)` span (`patchdiff-tx/2`).
2. **Single-replacement tool calls vs. atomic multi-edit batches:** A single-replacement `str_replace` call applies one edit per invocation. Making five related edits to a document requires five separate tool invocations, and if the fourth call fails, the first three edits remain applied unless the host implements an external rollback wrapper. PatchDIFF's `patchdiff_submit_edits` and `patchdiff_submit_operations` accept an ordered array of edits in a single call, simulate them sequentially in memory, and commit all five or none under a single PostgreSQL row lock.
3. **Unindexed ambiguity errors:** When `str_replace` rejects an ambiguous `old_str`, the agent typically receives an error message stating that multiple matches were found and must issue a separate view/search tool call to locate the occurrences. PatchDIFF's rejection response includes `diagnostic.exact_candidates` with the total `occurrence_count` and up to 5 indexed occurrences (`occurrence_index`, `start`, `end`, `before`, `match_preview`, `after`) so the host can disambiguate immediately.

### 5.2 Unguarded Line-Range and Coordinate Splicing

Line-number editing (`replace lines 40–45 with ...`) is compact, but raw coordinates are fragile across multi-edit turns: inserting three lines at line 20 shifts every subsequent line number by $+3$. If an agent submits a second edit using line numbers remembered from an earlier read, it splices into the wrong location without warning.

PatchDIFF's `patchdiff-tx/2` (`patchdiff_submit_operations`) supports coordinate-based editing (`op: "span"`) while eliminating silent coordinate drift through three mechanisms:
- **Mandatory target state guard:** Every `tx/2` transaction requires `expected_target_version` and/or `expected_current_hash`.
- **Mandatory `expected_text` precondition:** Every `[start, end)` code-point span must declare `expected_text`, which must match `buffer[start:end]` character-for-character (`FailureReason.SPAN_EXPECTED_TEXT_MISMATCH` otherwise).
- **Optional `expected_before` and `expected_after` adjacency guards (profile `patchdiff-mvp-0.5.0`):** Particularly for zero-length insertions (`start == end`, `expected_text: ""`), the transaction can assert the exact text immediately preceding `start` and following `end` (`FailureReason.SPAN_CONTEXT_MISMATCH` on mismatch).

---

## 6. System Model & Five-Layer Runtime Architecture

PatchDIFF is structured as a five-layer server architecture with strict separation of concerns:

```text
+-----------------------------------------------------------------------+
| Host / Agent Loop (External to PatchDIFF)                             |
|   Planning, context selection, proposal generation, retry decisions,  |
|   and semantic/task evaluation.                                       |
+-----------------------------------+-----------------------------------+
                                    | MCP (stdio JSON-RPC / registry)
                                    v
+-----------------------------------------------------------------------+
| Layer 1: MCP Transport & Tool Surface (backend/app/mcp/)              |
|   Stdio JSON-RPC adapter, full JSON Schema discovery (20 tools),      |
|   bounded response projection, and SQL LATERAL metadata paging.       |
+-----------------------------------+-----------------------------------+
                                    |
+-----------------------------------+-----------------------------------+
| Layer 2: Transaction & Read Service Layer (backend/app/services/)     |
|   Request-key idempotency (client_request_id), SELECT ... FOR UPDATE  |
|   row locking, precondition guards, tx/3 admission caps, post-commit  |
|   near-miss scanning, SAVE cycle rotation, and replay orchestration.  |
+-----------------------------------+-----------------------------------+
                                    |
+-----------------------------------+-----------------------------------+
| Layer 3: Declarative Parsers & Validators (backend/app/pdcp/)         |
|   Typed JSON decoders (patchdiff-tx/1, tx/2, tx/3) and frozen legacy  |
|   PDCP v0.2.3 parser/validator lowering into shared ParsedPDCP.       |
+-----------------------------------+-----------------------------------+
                                    |
+-----------------------------------+-----------------------------------+
| Layer 4: Pure Deterministic Core Applier (backend/app/core/, pdcp/)   |
|   Canonicalization, exact overlapping match enumeration, selector     |
|   disambiguation, sequential in-memory simulation, change_facts       |
|   computation, advisory warnings, and ValidationStage classification. |
+-----------------------------------+-----------------------------------+
                                    |
+-----------------------------------+-----------------------------------+
| Layer 5: PostgreSQL Persistence Substrate (backend/app/storage/)      |
|   cloud_target_files, append_only_pdcp_logs,                          |
|   append_only_manifest_ledger, target_snapshots, editing_cycles.      |
+-----------------------------------------------------------------------+
```

The core runtime (Layers 3 and 4) is pure and deterministic: it never calls an LLM, holds no model credentials, performs no network or database I/O, and never silently repairs a malformed or non-matching transaction.

---

## 7. Why Unified Validation, Audit, Idempotence, and Replay Belong in One Substrate

A natural architectural question is whether PatchDIFF's capabilities could be assembled loosely by a host using local files, an in-memory `str_replace` function, and git commits. Integrating validation, audit logging, idempotence, and replay inside a single PostgreSQL transaction boundary solves four coupled failure modes that loose host wrappers struggle to prevent:

1. **Check-then-act race conditions:** When concurrency checks (`stat()` / hash comparison) and file writes occur in separate host steps without a database row lock, two concurrent agent workers can both observe version $v$, pass their respective precondition checks, and overwrite each other. Acquiring `SELECT ... FOR UPDATE` on `cloud_target_files` before checking `expected_target_version` / `expected_current_hash` and holding that lock through target mutation and log insertion guarantees serializability per target.
2. **Auditability of rejected proposals:** Version-control systems record accepted commits, while rejected tool calls typically vanish into ephemeral chat logs. In agentic workflows, rejected edit attempts are high-signal operational data: they reveal whether failures stem from stale context (`target_version_mismatch`), ambiguous spans (`match_ambiguous`), or sequential self-conflict (`sequential_match_invalid`). Persisting rejected attempts in `append_only_pdcp_logs` with `parent_pdcp_log_id` lineage preserves the full retry tree.
3. **Crash-safe retry idempotence:** If an MCP transport connection drops after the server commits an edit from $v=3 \to v=4$—or if a later transaction subsequently advances the target to $v=5$ or reverts it back to the hash of $v=3$ (an ABA transition)—a naive host retry will either fail with `version_mismatch` or apply the edit a second time. Storing `(target_file_id, client_request_id, request_fingerprint)` atomically in the same PostgreSQL transaction as the attempt log allows the server to return the exact recorded terminal outcome (`deduplicated: true`) on retry, or reject payload reuse with `client_request_id_conflict`.
4. **Long-term replay across runtime evolution:** As an editing protocol evolves (for example, fixing non-overlapping match enumeration in `0.2.0`, enforcing singleton selectors in `0.2.2`, adding span operations in `0.3.0`, whole-target replacement in `0.4.0`, and span adjacency guards in `0.5.0`), re-running historical logs through the latest runtime rules could alter historical outcomes. Recording both `protocol_version` and `runtime_version` on every log row and dispatching replay through immutable `RuntimeProfile` definitions ensures that historical transactions replay under the exact semantics that accepted them.

---

## 8. The PatchDIFF Transaction Protocol Family (`patchdiff-tx/1`, `tx/2`, `tx/3`, and Legacy `.pdcp` v0.2.3)

PatchDIFF supports three active declarative JSON transaction formats and one frozen legacy text format. All four lower into the same internal `ParsedPDCP` structure and execute through the same deterministic applier (`apply_pdcp_transaction`):

| Format | MCP Tool | Default Runtime Profile | Operations Supported | Required Preconditions |
| --- | --- | --- | --- | --- |
| **`patchdiff-tx/1`** (Primary) | `patchdiff_submit_edits` | `patchdiff-mvp-0.2.2` | Ordered `edits[]` with exact `match` and `replace`, optional `occurrence_index`, `anchor_before`, `anchor_after` | `expected_target_version` and/or `expected_current_hash` |
| **`patchdiff-tx/2`** (Guarded Operations) | `patchdiff_submit_operations` | `patchdiff-mvp-0.3.0` (`0.5.0` when `expected_before`/`after` used) | Ordered `operations[]` mixing `op: "match"` and `op: "span"` (`start`, `end`, `expected_text`, `replace`, optional `expected_before`, `expected_after`) | `expected_target_version` and/or `expected_current_hash` |
| **`patchdiff-tx/3`** (Whole Replacement) | `patchdiff_submit_replacement` | `patchdiff-mvp-0.4.0` | Single `{"op": "replace_all", "replace": "..."}` (`<= 1,000,000` code points and `<= 1,048,576` UTF-8 bytes) | `expected_target_version` and/or `expected_current_hash` |
| **`.pdcp` v0.2.3** (Frozen Legacy) | `patchdiff_submit_pdcp` | `patchdiff-mvp-0.2.2` (historical `0.1.0`..`0.2.1` on replay) | Raw text blocks with 7 `# MANIFEST` fields and `<<<<<<< MATCH` / `=======` / `>>>>>>> REPLACE` delimiters | Optional `target_hash` / `expected_target_version` |

*(Full legacy `.pdcp` v0.2.3 grammar and deprecated regeneration wrappers are specified in [LEGACY_COMPATIBILITY.md](LEGACY_COMPATIBILITY.md).)*

### 8.1 Separation of Model-Claimed Intent (`origin`) and Runtime-Derived Facts (`derived_json`)

In the historical v0.2.3 `.pdcp` format, every change block required seven prose `# MANIFEST` lines (`change_id`, `intent`, `input_state`, `output_state`, `affected_region`, `user_visible_change`, `risk`). This imposed significant output overhead on multi-edit transactions and conflated model assertions with operational facts.

In the modernized `patchdiff-tx/1..3` architecture:
- Only a top-level transaction `intent` string is required from the proposer; per-edit `change_id`, `rationale`, and `risk` (`"low"`, `"medium"`, `"high"`) are optional.
- When a transaction is accepted, the runtime computes exact **`change_facts`** (`span_start`, `span_end`, `matched_chars`, `replacement_chars`, `match_sha256`, `replace_sha256`, and selector metadata) and stores them in `append_only_manifest_ledger.derived_json`, strictly separated from the proposer's `origin` metadata.

---

## 9. Validity Levels (`ValidationStage`)

PatchDIFF separates four levels of validity and reports them explicitly in every submission and preview response:

| Validity Field | Meaning | Enforced by PatchDIFF? |
| --- | --- | --- |
| `protocol_valid` | The transaction payload satisfies structural schema, type, UTF-8 text safety, and protocol grammar rules (`ValidationStage.PROTOCOL_PARSE` and `PROTOCOL_VALIDATION`) | **Yes (`true` / `false`)** |
| `transaction_valid` | State guards (`expected_target_version`, `expected_current_hash`) hold and all sequential operations resolve and apply cleanly (`PRECONDITION_GUARD`, `TRANSACTION_APPLICABILITY`, `COMMIT_GUARD`) | **Yes (`true` / `false`, or `null` when `protocol_valid` is `false`)** |
| `task_correct` | The accepted edit satisfies the user's high-level instruction | **No (`"not_evaluated"`)** |
| `semantic` | The resulting document compiles, passes tests, or preserves domain invariants | **No (`"not_evaluated"`)** |

This four-part distinction prevents overclaiming: **strict matching and precondition guards enforce transaction applicability and selection constraints, not semantic correctness or task success.**

---

## 10. Generalized Formal Transaction Model

Let $\Sigma$ be the set of valid Unicode scalar values (excluding UTF-16 surrogates $\text{U+D800}..\text{U+DFFF}$ and NUL $\text{U+0000}$), and let $\text{canon}: \Sigma^* \to \Sigma^*$ be the canonicalization function that normalizes $\text{CRLF}$ and $\text{CR}$ line endings to $\text{LF}$ (`\n`). Let $H: \Sigma^* \to \{0, \dots, 9, \text{a}, \dots, \text{f}\}^{64}$ denote the lowercase hexadecimal SHA-256 digest of the UTF-8 encoding of a canonical string.

At transaction start, the committed target row in PostgreSQL holds canonical text $T_0 \in \Sigma^*$, integer version $v_0 \in \mathbb{N}$, and digest $h_0 = H(T_0)$.

A transaction $\tau = (p, \pi, g, I, \langle o_1, \dots, o_n \rangle)$ consists of:
- Protocol version $p \in \{\text{"patchdiff-tx/1"}, \text{"patchdiff-tx/2"}, \text{"patchdiff-tx/3"}, \text{"0.2.3"}\}$,
- Immutable runtime profile $\pi \in \{\text{0.1.0}, \text{0.2.0}, \text{0.2.1}, \text{0.2.2}, \text{0.3.0}, \text{0.4.0}, \text{0.5.0}\}$,
- Precondition guard $g = (v_{\text{exp}}, h_{\text{exp}})$ where $v_{\text{exp}} \in \mathbb{N} \cup \{\bot\}$ and $h_{\text{exp}} \in \Sigma^{64} \cup \{\bot\}$,
- Transaction intent $I \in \Sigma^+$, and
- A non-empty ordered sequence of operations $\langle o_1, \dots, o_n \rangle$ ($n \ge 1$; for $p = \text{"patchdiff-tx/3"}$, $n = 1$).

### 10.1 Precondition Guard Evaluation

For all typed formats ($p \in \{\text{"patchdiff-tx/1"}, \text{"patchdiff-tx/2"}, \text{"patchdiff-tx/3"}\}$), at least one guard component must be non-null ($v_{\text{exp}} \neq \bot \lor h_{\text{exp}} \neq \bot$). Under a row lock on the target, guard evaluation $\text{Guard}(g, v_0, h_0)$ succeeds iff:

$$\bigl(v_{\text{exp}} = \bot \lor v_{\text{exp}} = v_0\bigr) \;\land\; \bigl(h_{\text{exp}} = \bot \lor h_{\text{exp}} = h_0\bigr)$$

If $\text{Guard}(g, v_0, h_0)$ fails, evaluation halts at `ValidationStage.PRECONDITION_GUARD` (`target_version_mismatch` or `target_hash_mismatch`) and the target remains $(T_0, v_0, h_0)$.

### 10.2 Sequential Operation Semantics ($T_0 \to T_1 \to \dots \to T_n$)

When the precondition guard holds, the applier evaluates $o_1, \dots, o_n$ sequentially over in-memory canonical buffers $T_0, T_1, \dots, T_n$. For step $i \in \{1, \dots, n\}$ against current buffer $T_{i-1}$:

1. **Localized Exact-Match Operation (`tx/1` and `tx/2` `op="match"`, plus `.pdcp` v0.2.3):**
   $o_i = (\text{match}, m_i, r_i, d_i)$ where $m_i = \text{canon}(m_i^{\text{raw}}) \in \Sigma^+$ ($|m_i| \ge 1$) and $r_i = \text{canon}(r_i^{\text{raw}}) \in \Sigma^*$.
   Let $\text{Occ}_\pi(T_{i-1}, m_i)$ be the ordered sequence of exact code-point spans $[s, e)$ in $T_{i-1}$ such that $T_{i-1}[s:e] = m_i$ (enumerated at every starting code point when $\pi.\text{overlapping\_matches} = \text{true}$, or non-overlapping left-to-right when $\pi = \text{0.1.0}$).
   - If $|\text{Occ}_\pi(T_{i-1}, m_i)| = 0$, $o_i$ fails with `match_absent` (or `sequential_match_invalid` if $i > 1$ and $|\text{Occ}_\pi(T_0, m_i)| > 0$).
   - Otherwise, selector resolution $\text{Resolve}_\pi(\text{Occ}_\pi(T_{i-1}, m_i), d_i)$ filters or indexes $\text{Occ}_\pi(T_{i-1}, m_i)$ using $d_i = (\text{occ\_idx}, a_{\text{before}}, a_{\text{after}})$. Under $\pi.\text{enforce\_singleton\_selectors} = \text{true}$ (`0.2.2+`), supplied anchors and `occurrence_index` are validated even when $|\text{Occ}_\pi(T_{i-1}, m_i)| = 1$.
   - If resolution yields a unique span $[s_i, e_i)$, the next buffer state is:
     $$T_i = T_{i-1}[0:s_i] \mathbin{\Vert} r_i \mathbin{\Vert} T_{i-1}[e_i:|T_{i-1}|]$$

2. **Localized Guarded Code-Point Span Operation (`tx/2` `op="span"`, profiles `0.3.0` and `0.5.0`):**
   $o_i = (\text{span}, s_i, e_i, x_i, b_i, f_i, r_i)$ with integer code-point offsets $s_i, e_i \in \mathbb{Z}$, expected slice $x_i = \text{canon}(x_i^{\text{raw}}) \in \Sigma^*$, optional adjacency guards $b_i, f_i \in \Sigma^* \cup \{\bot\}$ (requiring $\pi = \text{0.5.0}$ when non-null), and replacement $r_i = \text{canon}(r_i^{\text{raw}}) \in \Sigma^*$.
   - **Bounds precondition:** $0 \le s_i \le e_i \le |T_{i-1}|$ (failing with `span_out_of_bounds` otherwise). Note that $s_i = e_i$ with $x_i = \varepsilon$ represents an explicit zero-length insertion at code-point offset $s_i$.
   - **Expected-text precondition:** $T_{i-1}[s_i:e_i] = x_i$ (failing with `span_expected_text_mismatch` otherwise).
   - **Adjacency preconditions ($\pi = \text{0.5.0}$):** If $b_i \neq \bot$, then $s_i \ge |b_i|$ and $T_{i-1}[s_i - |b_i| : s_i] = b_i$; if $f_i \neq \bot$, then $e_i + |f_i| \le |T_{i-1}|$ and $T_{i-1}[e_i : e_i + |f_i|] = f_i$ (failing with `span_context_mismatch` otherwise).
   - When all preconditions hold, the selected span is $[s_i, e_i)$ and:
     $$T_i = T_{i-1}[0:s_i] \mathbin{\Vert} r_i \mathbin{\Vert} T_{i-1}[e_i:|T_{i-1}|]$$

3. **Guarded Whole-Target Replacement Operation (`tx/3` `op="replace_all"`, profile `0.4.0`):**
   A `tx/3` transaction contains exactly one operation ($n = 1$), $o_1 = (\text{replace\_all}, r_1)$ where $r_1 = \text{canon}(r_1^{\text{raw}})$. Fresh service submissions enforce admission caps $|r_1^{\text{raw}}|_{\text{cp}} \le 10^6$, $|r_1|_{\text{cp}} \le 10^6$, $|r_1^{\text{raw}}|_{\text{utf8}} \le 1{,}048{,}576$, and $|r_1|_{\text{utf8}} \le 1{,}048{,}576$ (`replacement_too_large`). The operation selects the full target span $[s_1, e_1) = [0, |T_0|)$ and produces:
   $$T_1 = r_1$$

### 10.3 Core Formal Invariants

#### Invariant 1: Localized Unmatched-Content Preservation (`tx/1`, `tx/2`, `.pdcp`)
For every individual localized operation $o_i \in \{\text{match}, \text{span}\}$ that selects span $[s_i, e_i)$ in $T_{i-1}$, the prefix $T_{i-1}[0:s_i]$ and suffix $T_{i-1}[e_i:|T_{i-1}|]$ are preserved code-point-for-code-point in $T_i = T_{i-1}[0:s_i] \mathbin{\Vert} r_i \mathbin{\Vert} T_{i-1}[e_i:|T_{i-1}|]$. Consequently, across any accepted localized transaction (`patchdiff-tx/1`, `patchdiff-tx/2`, or `.pdcp` v0.2.3), no code point outside the union of sequentially selected spans is modified. *(Whole-target replacement `patchdiff-tx/3` is an explicitly separated tool and format whose selected span is $[0, |T_0|)$ under mandatory version/hash guards.)*

#### Invariant 2: Per-Target All-or-Nothing Atomicity
If protocol validation, precondition guard evaluation $\text{Guard}(g, v_0, h_0)$, any sequential operation $o_i$ ($1 \le i \le n$), or the commit guard fails, the committed target state in PostgreSQL remains $(T_0, v_0, h_0)$, zero entries are appended to `append_only_manifest_ledger`, and a single rejected attempt row is committed to `append_only_pdcp_logs` with `before_hash` $= h_0$ and `after_hash` $= \text{NULL}$. If all steps succeed, the target advances atomically to $(T_n, v_0 + 1, H(T_n))$.

#### Invariant 3: Profile-Dispatched Replay Determinism
Let $T_{\text{init}}$ be a target's `initial_upload` snapshot and let $\langle (\tau_1, p_1, \pi_1, h_1^{\text{after}}), \dots, (\tau_m, p_m, \pi_m, h_m^{\text{after}}) \rangle$ be the ordered sequence of accepted log records for that target. Re-executing each $\tau_k$ from $T_{\text{init}}$ using the shared applier configured with $\text{resolve\_runtime\_profile}(\pi_k)$ deterministically reconstructs $T_{\text{final}}$ and verifies four independent checks (`materialized_state_checks`): `content_matches` ($T_{\text{final}} = T_{\text{stored}}$), `stored_hash_matches` ($H(T_{\text{final}}) = h_{\text{stored}}$), `recomputed_hash_matches` ($H(T_{\text{stored}}) = h_{\text{stored}}$), and `version_matches` ($m = v_{\text{stored}}$).

---

## 11. Canonicalization, Unicode Code-Point Indexing, and Line-Ending Preservation

PatchDIFF operates on canonical LF-normalized UTF-8 text:

| Property | Canonical Rule |
| --- | --- |
| Character encoding | Valid UTF-8 scalar values (surrogates and NUL rejected before normal hashing/storage) |
| Line endings in canonical storage | Normalize `\r\n` (CRLF) and `\r` (CR) to `\n` (LF) |
| Tabs, spaces, trailing whitespace, final newline | Preserved byte-for-byte |
| Unicode normalization (NFC/NFD/NFKC/NFKD) | None (exact code-point sequence identity required) |
| Coordinate system (`start`, `end`, `length`) | 0-based Unicode code-point offsets over canonical LF text |
| Source line-ending preservation (`migration 0003`) | Upload records `source_line_endings` (`"LF"`, `"CRLF"`, `"MIXED"`); `patchdiff_export_target(format="original_eol")` restores uniform `"CRLF"` on export without altering canonical LF storage or SHA-256 digests |

When a submission for a known target contains invalid UTF-8/PostgreSQL text (such as a NUL character `\u0000` or lone surrogate), PatchDIFF does not crash with an unhandled database driver error or silently strip the invalid code point. Instead, it durably logs the rejection through the locked commit path using a reversible ASCII-escaped `patchdiff-invalid-input/1` evidence envelope (`evidence_format: "ascii_escaped_json_v1"`).

---

## 12. Deterministic Matching and Overlapping Occurrence Enumeration

For every `match` operation, the runtime searches the current in-memory buffer for all exact occurrences of the canonical match string.

In historical runtime `patchdiff-mvp-0.1.0`, occurrence search used non-overlapping scan steps (`str.find(needle, pos + len(needle))`). Starting in `patchdiff-mvp-0.2.0` (and active in `0.2.2+`), `find_exact_occurrences` advances by 1 code point (`pos + 1`), enumerating **all** exact occurrences including overlapping spans (for example, `"aba"` inside `"ababa"` has two exact occurrences at $[0, 3)$ and $[2, 5)$).

In `patchdiff-mvp-0.2.2+` (`enforce_singleton_selectors = True`), if a proposer supplies `occurrence_index > 1`, `anchor_before`, or `anchor_after`, the runtime enforces those selectors even when only a single occurrence of `match` exists in the buffer—preventing a stale selector intended for a multi-occurrence file from silently matching the wrong survivor after earlier deletions.

---

## 13. Sequential In-Memory Mutation Semantics and Intermediate-Buffer Coordinates

Within a multi-operation transaction (`patchdiff-tx/1`, `patchdiff-tx/2`, or `.pdcp` v0.2.3), operations execute **sequentially in memory**:

- Operation 1 is evaluated against $T_0$.
- Operation 2 is evaluated against $T_1$ (the buffer resulting from Operation 1).
- Operation $i$ is evaluated against $T_{i-1}$ (the buffer after $i - 1$ earlier simulated changes).

This design supports dependent edits within a single atomic transaction, and makes descending-offset multi-span edits in `patchdiff-tx/2` straightforward. It also has two important diagnostic consequences implemented in the runtime:

1. **Consumed-match detection (`sequential_match_invalid`) and basis-shift warnings (`occurrence_index_basis_shift`):** If operation $i > 1$ fails with zero matches in $T_{i-1}$, the applier checks whether $m_i$ existed in $T_0$. If so, it classifies the failure as `sequential_match_invalid`, identifies which earlier operation (`consumed_by_change_id`) overlapped or consumed the original match, and omits unrelated near-miss scanning (`omission_reason: "sequential_match_consumed"`). Similarly, if an earlier edit shifts the occurrence count of a later edit's `occurrence_index` selector, an accepted transaction records an advisory `occurrence_index_basis_shift` warning.
2. **Intermediate-buffer coordinate reporting (`prior_changes > 0`):** When operation $i > 1$ fails, `failure_context`, `exact_candidates`, and `near_misses` report `buffer_stage: "intermediate_buffer"` and `prior_changes: i - 1`. Their `[start, end)` offsets and `occurrence_index` values refer to the **in-memory buffer $T_{i-1}$**, not the persisted canonical target $T_0$.

---

## 14. Deletion, Zero-Length Span Insertion, and Disambiguation

- **Deletion:** In `patchdiff-tx/1` and `patchdiff-tx/2`, replacing a non-empty match or `[start, end)` span with `replace: ""` deletes the selected text.
- **Insertion:** In `patchdiff-tx/1` (and legacy `.pdcp` v0.2.3), `match` must be non-empty, so insertion is expressed as anchored replacement of an existing non-empty substring. In `patchdiff-tx/2` (`patchdiff_submit_operations`), **zero-length insertion is supported directly** via an empty span (`start == end`, `expected_text: ""`), optionally guarded by `expected_before` and `expected_after` under runtime profile `patchdiff-mvp-0.5.0`.
- **Disambiguation:** Multiple exact matches of `m_i` are resolved deterministically by filtering candidates that are immediately preceded by `anchor_before` and/or immediately followed by `anchor_after`, and then selecting the 1-based `occurrence_index` among the surviving candidates. Advisory fields (`rationale`, `risk`, or legacy `region_hint`) never disambiguate a match.

---

## 15. Protocol Validity, Precondition Guards, and Transaction Applicability

Every rejection is classified by a deterministic `FailureReason` and `ValidationStage`:

| Validation Stage | Representative Failure Reasons | Target Mutated? |
| --- | --- | --- |
| `PROTOCOL_PARSE` / `PROTOCOL_VALIDATION` | `context_missing`, `context_invalid`, `manifest_missing`, `manifest_invalid`, `block_malformed`, `executable_logic_detected`, `target_encoding_invalid`, `replacement_too_large` | No (`protocol_valid: false`, `transaction_valid: null`) |
| `PRECONDITION_GUARD` | `target_not_found`, `target_version_mismatch`, `target_hash_mismatch` | No (`protocol_valid: true`, `transaction_valid: false`) |
| `TRANSACTION_APPLICABILITY` | `match_absent`, `match_ambiguous`, `anchor_absent`, `anchor_ambiguous`, `disambiguation_invalid`, `span_out_of_bounds`, `span_expected_text_mismatch`, `span_context_mismatch`, `sequential_match_invalid` | No (`protocol_valid: true`, `transaction_valid: false`) |
| `COMMIT_GUARD` | `target_diverged` (post-simulation guard verification before commit) | No (`protocol_valid: true`, `transaction_valid: false`) |

---

## 16. The Strict-Matching Tradeoff and Structured Diagnostic Recovery

Strict exact matching is essential for safety—it prevents the runtime from guessing which lines to overwrite when a model's context is slightly out of date. However, in an agent loop, strict matching creates a well-known usability tradeoff: if a rejection returns only a generic error code, the agent must spend extra tool calls and tokens reading slices of the file to discover why its match failed.

PatchDIFF resolves this tradeoff **without introducing fuzzy auto-mutation**. Application remains 100% exact, while rejection responses return bounded, structured recovery evidence (capped at **`<= 18,432` compact ASCII-escaped JSON bytes** across newly added enrichment fields):

1. **Bounded Failure and Current Contexts (`<= 4,096 B` each; `<= 256` code points):** Every rejection captures `diagnostic.failure_context` (`CONTEXT_CHARS = 256` code points—either a prefix of the failing buffer or a window centered around a known span failure offset `focus`) and response-only `current_context` (elided with `unavailable_reason: "same_as_failure_context"` when identical to `failure_context`).
2. **Indexed Ambiguity Candidates (`diagnostic.exact_candidates`, `<= 8,192 B`):** On `match_ambiguous` or `anchor_ambiguous`, PatchDIFF returns `occurrence_count` and up to **5 exact occurrences** (`occurrence_index`, `start`, `end`, `before` $\le 20$ chars, `match_preview` $\le 64$ chars, `match_truncated`, `after` $\le 20$ chars), allowing immediate disambiguation.
3. **Post-Commit Exact Levenshtein Near-Miss Discovery (`near_misses`, `<= 8,192 B`):** On `match_absent` when $|\text{match}| \le 64$ code points (`omission_reason: "match_too_large"` otherwise), after the service-owned rejection transaction commits and releases its PostgreSQL row lock, PatchDIFF scans at most the first `65,536` code points (`NEAR_MISS_SCAN_CHARS`) of the failing buffer under a `1,000,000` comparison-cell cap (`MAX_COMPARISON_CELLS`). Using an **exact positional pigeonhole filter ($k+1$ disjoint needle pieces) coupled with a Landau–Vishkin diagonal-wave banded dynamic program** (Landau and Vishkin, 1989) over candidate widths $|\text{needle}| + \{-1, 0, +1\}$ and threshold $k = \min(4, \max(1, \lfloor |\text{needle}| / 4 \rfloor))$, it returns up to **3 ranked non-overlapping near-miss candidates** (`distance`, `start`, `end`, `text`, `before`, `after`).
4. **Advisory Dry-Run Preview (`patchdiff_preview`, `<= 32,768 B`):** Evaluates any `tx/1`, `tx/2`, or `tx/3` proposal against a coherent read-only observation of the target without taking a row lock, writing audit rows, or reserving a version.
5. **Request-Key Outcome Recovery (`client_request_id`):** If a network timeout occurs during submission, retrying the identical payload with the same `(target_file_id, client_request_id)` returns the recorded accepted or rejected outcome (`deduplicated: true`).

---

## 17. Structural Safety Model

PatchDIFF enforces a strict boundary between **declarative transaction data** and **executable code**:

```text
patchdiff-tx/1, patchdiff-tx/2, patchdiff-tx/3, or .pdcp = declarative, non-executable transaction artifact
backend/app/*.py                                         = trusted deterministic runtime and service
target document                                          = arbitrary UTF-8 text (Python, Markdown, YAML, JSON, etc.)
```

The target document and the `match` / `replace` / `expected_text` strings frequently contain source code (such as Python `def` blocks, `import` statements, or shell commands). Those strings are treated strictly as passive UTF-8 character sequences and are never evaluated or executed.

It is important to distinguish how structural safety is enforced across input formats:
- **In legacy `.pdcp` v0.2.3 (`patchdiff_submit_pdcp`):** Because `.pdcp` is a custom line-oriented text format, `protocol_validator.py` scans structural lines outside `<<<<<<< MATCH ... >>>>>>> REPLACE` payloads for code-like constructs (`FailureReason.EXECUTABLE_LOGIC_DETECTED`).
- **In typed JSON formats (`patchdiff-tx/1`, `tx/2`, `tx/3`):** Proposals arrive as parsed JSON objects validated against strict key, type, and enum schemas (`typed.py`, `operations.py`, `replacement.py`). Metadata fields (`intent`, `rationale`, `change_id`) are validated as non-empty, UTF-8 / PostgreSQL-safe strings (no NUL or lone surrogates) and are **not** subject to legacy `.pdcp` keyword heuristics—allowing a developer or agent to freely name Python functions, SQL queries, or shell commands inside `intent` and `rationale` prose.

---

## 18. Locality Controls, Whole-Target Replacement Admission, and Host Policy Layering

The historical v0.2.3 concept paper discussed both runtime locality rules and potential deployment heuristics (such as flagging transactions whose replacement ratio exceeds a percentage of the file, or requiring human review when `risk: high` is declared). To prevent confusion between normative runtime behavior and optional host policy, Concept Paper v6 separates them explicitly:

| Control / Policy | Enforced by PatchDIFF Server Today? | Mechanism / Owner |
| --- | --- | --- |
| **Non-empty `match` in `tx/1`, `tx/2` match ops, and `.pdcp`** | **Yes (Runtime-enforced)** | Empty `match` is rejected at protocol validation (`block_malformed`). |
| **Separation of localized edits (`tx/1`, `tx/2`) from whole-file replacement (`tx/3`)** | **Yes (Runtime-enforced)** | `replace_all` is forbidden in `tx/1` and `tx/2` (`0.2.2`, `0.3.0`, `0.5.0`) and is only admitted through `patchdiff_submit_replacement` (`tx/3`, profile `0.4.0`). |
| **Fresh `tx/3` replacement size caps (`1,000,000` code points / `1,048,576` UTF-8 bytes)** | **Yes (Service-enforced)** | Checked on both raw and LF-canonical replacement strings during fresh `patchdiff_submit_replacement` calls (`replacement_too_large`); never re-applied during replay. |
| **Runtime-derived span and character-count evidence (`change_facts`)** | **Yes (Runtime-enforced)** | Every accepted change records exact `span_start`, `span_end`, `matched_chars`, and `replacement_chars` in `evidence.changes` and `append_only_manifest_ledger.derived_json`. |
| **Advisory warnings (`no_op_change`, `no_op_transaction`, `occurrence_index_basis_shift`, `grapheme_boundary_split`)** | **Yes (Runtime-computed, non-blocking)** | Returned on accepted submissions and previews; never alter the commit verdict or replay. |
| **Replacement-ratio thresholds or mandatory human approval on `risk: "high"`** | **No (Host-owned policy)** | PatchDIFF records `risk` and `change_facts` accurately, but does not block large localized `tx/1`/`tx/2` spans or `risk: "high"` edits; hosts may inspect `patchdiff_preview` facts to enforce custom approval policies before committing. |

---

## 19. Persistence, Append-Only Logs, and Profile-Dispatched Replay

PatchDIFF's PostgreSQL schema (`migrations 0001`, `0002`, and `0003`) maintains five core tables:

1. **`cloud_target_files`**: Authoritative current target state (`target_file_id`, `target_type`, `content`, `current_hash`, `version`, `active_cycle_id`, `source_line_endings`).
2. **`append_only_pdcp_logs`**: Immutable record of every accepted and rejected transaction attempt (`log_sequence`, `pdcp_content`, `protocol_version`, `runtime_version`, `status`, `before_hash`, `after_hash`, `failure_reason`, `diagnostic_json`, `parent_pdcp_log_id`, `client_request_id`, `request_fingerprint`).
3. **`append_only_manifest_ledger`**: Accepted-only ledger recording one row per applied change (`origin_json` for proposer metadata + `derived_json` for runtime-computed span/hash facts).
4. **`target_snapshots`**: Immutable content snapshots (`initial_upload` and `save_checkpoint` rows).
5. **`editing_cycles`**: Active and closed editing cycles tracking `start_version`, `end_version`, `start_hash`, `end_hash`, and `save_snapshot_id`.

### 19.1 Immutable Runtime Profiles (`0.1.0` through `0.5.0`)

Deterministic replay (`patchdiff_replay`) reconstructs target state from the `initial_upload` snapshot by applying all accepted `append_only_pdcp_logs` rows in ascending `log_sequence` order. Each log row is decoded according to its `protocol_version` and executed under its recorded `runtime_version` profile:

| Runtime Profile | `overlapping_matches` | `enforce_singleton_selectors` | `span_operations` | `replace_all_operations` | `span_context` | Primary Introduction |
| --- | --- | --- | --- | --- | --- | --- |
| `patchdiff-mvp-0.1.0` | `False` | `False` | `False` | `False` | `False` | Historical non-overlapping `.pdcp` baseline |
| `patchdiff-mvp-0.2.0` | `True` | `False` | `False` | `False` | `False` | Overlapping exact match enumeration |
| `patchdiff-mvp-0.2.1` | `True` | `False` | `False` | `False` | `False` | Pre-singleton-selector typed/PDCP profile |
| `patchdiff-mvp-0.2.2` | `True` | `True` | `False` | `False` | `False` | Active default for `patchdiff-tx/1` and `.pdcp` v0.2.3 |
| `patchdiff-mvp-0.3.0` | `True` | `True` | `True` | `False` | `False` | Active default for `patchdiff-tx/2` (`match` + `span`) |
| `patchdiff-mvp-0.4.0` | `True` | `True` | `True` | `True` | `False` | Active profile for `patchdiff-tx/3` (`replace_all`) |
| `patchdiff-mvp-0.5.0` | `True` | `True` | `True` | `False` | `True` | Active profile for `patchdiff-tx/2` spans with `expected_before`/`after` |

---

## 20. Concurrency Control and Serialized Per-Target Commits

In the historical v0.2.3 paper, concurrency was described informally as a "single-active-writer" assumption. In the modernized PostgreSQL service, concurrency is governed precisely by **per-target row-locked serialization combined with required optimistic state preconditions** (Kung and Robinson, 1981; Bernstein and Goodman, 1981):

- **Multiple connected hosts or agents are supported:** Any number of MCP clients or agent workers may read from and submit transactions to the service.
- **Per-target serialization under `SELECT ... FOR UPDATE`:** Every write submission (`patchdiff_submit_edits`, `patchdiff_submit_operations`, `patchdiff_submit_replacement`, `patchdiff_submit_pdcp`, and `patchdiff_save`) acquires a PostgreSQL row lock on `cloud_target_files` for the specified `target_file_id`.
- **Deterministic conflict rejection (no silent merge):** If Agent A and Agent B both read target version $v=3$ and submit concurrent edits with `expected_target_version: 3`, PostgreSQL serializes their row locks. The first transaction to acquire the lock validates $v=3$, commits $v=4$, and releases the lock. The second transaction then acquires the lock, observes committed version $v=4 \neq 3$, logs a rejected attempt (`target_version_mismatch`), and returns the rejection along with the fresh `current_version: 4` and `current_hash` without mutating the target.
- **Version vs. hash guards and ABA detection:** A hash-only guard (`expected_current_hash`) detects any net content change, whereas a version guard (`expected_target_version`) also detects intervening no-op commits or $A \to B \to A$ content cycles because `version` increments monotonically on every accepted transaction.

---

## 21. Authoritative MCP Service Interface

PatchDIFF exposes 20 MCP tools organized into five functional groups (normative schemas and byte budgets are specified in [MCP_TOOLS.md](MCP_TOOLS.md)):

1. **Target Lifecycle (`4` tools):** `patchdiff_handle_upload`, `patchdiff_initialize_target`, `patchdiff_get_target`, `patchdiff_export_target` (`"original_text"`, `"canonical_text"`, `"original_eol"`).
2. **Authoritative Bounded Reads & Search (`3` tools):** `patchdiff_read_target`, `patchdiff_read_lines`, `patchdiff_find_occurrences`.
3. **Guarded Transaction Submission (`3` active typed + `1` legacy):** `patchdiff_submit_edits` (`tx/1`), `patchdiff_submit_operations` (`tx/2`), `patchdiff_submit_replacement` (`tx/3`), and legacy `patchdiff_submit_pdcp` (`.pdcp` v0.2.3).
4. **Advisory Dry-Run Evaluation (`1` tool):** `patchdiff_preview`.
5. **Checkpointing, Replay, History & Compatibility (`4` core + `4` convenience/deprecated):** `patchdiff_save`, `patchdiff_replay`, `patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`, plus convenience prefix `patchdiff_build_prompt_context` and deprecated regeneration wrappers ([LEGACY_COMPATIBILITY.md](LEGACY_COMPATIBILITY.md)).

---

## 22. SAVE Checkpointing and Editing-Cycle Rotation

During long editing sessions, the manifest ledger accumulates accepted entries across many turns. `patchdiff_save` provides an explicit **editing-cycle checkpoint** without mutating target content or advancing the target `version`:

1. **Optional state guards:** `patchdiff_save` accepts optional `expected_target_version` and `expected_current_hash` preconditions checked under `SELECT ... FOR UPDATE`.
2. **Immutable snapshot creation:** Writes a `save_checkpoint` row in `target_snapshots` recording the current canonical `content`, `content_hash`, and `version`.
3. **Cycle rotation:** Marks the current `editing_cycles` row `"closed"` (recording `end_version`, `end_hash`, `save_snapshot_id`, and `closed_at`) and opens a new active `editing_cycles` row (`cycle_number + 1`).

**Boundary clarification vs. v0.2.3:** `patchdiff_save` rotates the server-side editing cycle and creates a durable database snapshot (`active_cycle_only: true` in `patchdiff_get_manifest_ledger` then scopes ledger reads to the new cycle). Unlike the illustrative heuristics discussed in v0.2.3, `patchdiff_save` does **not** automatically compact the host's LLM conversation history or enforce token-ratio thresholds ($0.30$ / $0.50$) inside the server; deciding when to invoke `patchdiff_save` or summarize chat history belongs to the MCP host.

---

## 23. Operational Efficiency & Research Evaluation Plan (`H1`–`H7`)

All quantitative and comparative claims in PatchDIFF documentation follow a four-tier evidence classification (`MODERNIZATION_ARCHITECTURE.md` Decision A8):
- **`Measured`**: Deterministic UTF-8 serialization byte counts from `evaluation/offline_eval.py` or locally executed benchmark medians on specified workloads.
- **`Derived`**: Exact arithmetic or deterministic tool-invocation counts for an explicitly specified interface workflow.
- **`Illustrative`**: Clearly labeled token or decoding-time illustrations stating their conversion assumptions (not tokenizer measurements).
- **`Not yet measured`**: Controlled live-model comparative accuracy, retry-turn distributions, end-to-end agent turn latency, and human review studies (`NOT RUN`).

### 23.1 Four User-Centric Operational Dimensions

#### 1. Output Payload Size & Scaling (`Measured` + `Derived`)

Reproducible via `PYTHONPATH=backend python evaluation/offline_eval.py` (fixed 36-char UUID, concise `intent`, `expected_target_version: 0`, compact UTF-8 JSON):

| Scenario (`evaluation/offline_eval.py`) | Raw Match + Replace (`UTF-8 B`) | `patchdiff-tx/1` Minimal (`typed_min`, MCP `arguments` / Stored) | `patchdiff-tx/1` with Prose (`typed_match`, MCP `arguments` / Stored) | `patchdiff-tx/3` Guarded Replacement (`arguments` / Stored / `tools/call` Line) | Verdict |
| --- | --- | --- | --- | --- | --- |
| **1 tiny edit (`"old" -> "new"`)** | `6 B` | **`151 B`** / **`206 B`** | `327 B` / `382 B` | `232 B` / `290 B` / `341 B` (`3 B` replacement) | `accepted` |
| **5 small edits (`5 × 1-byte edits`)** | `10 B` | **`259 B`** / **`314 B`** | `1,139 B` / `1,194 B` | — | `accepted` |
| **1 edit, 2 KB span (`2,109 B` text)** | `4,218 B` | **`4,441 B`** / **`4,496 B`** | `4,617 B` / `4,672 B` | `2,377 B` / `2,435 B` / `2,486 B` (`2,109 B` replacement) | `accepted` |
| **Quotes + backslashes + Unicode (`🌟`, `中`)** | `23 B` | **`172 B`** / **`227 B`** | `348 B` / `403 B` | `250 B` / `308 B` / `359 B` (`16 B` raw / `15 B` LF) | `accepted` |
| **Payload has a delimiter line (`"a\n=======\nb"`)** | `14 B` | **`162 B`** / **`217 B`** | `338 B` / `393 B` | — | **`accepted`** (`.pdcp` rejects with `block_malformed`) |

- **Marginal edit framing (`Derived`):** Each additional minimal edit item in `edits[]` adds **`25 B`** of JSON keys/punctuation (`{"match":"","replace":""}`) + **`1 B`** array comma separator + the UTF-8 JSON-escaped byte lengths of `match` and `replace` (**`+28 B` per additional edit** with two 1-byte ASCII strings: `151 B - 4 B = 147 B` base for one 1-byte edit, and `147 B + 4 × 28 B = 259 B` for five 1-byte edits).
- **Scaling vs. full-document regeneration and context-padded `str_replace` (`Derived` / `Illustrative`):** On a `65,536 B` (`~16,384`-token illustrative at `~4 UTF-8 B ≈ 1 token`) document, a 1-edit `patchdiff-tx/1` `arguments` payload is **`151 B`** (>99.7% smaller than re-emitting `65,536 B`). When editing a repeated short line, `patchdiff-tx/1` disambiguates via `"occurrence_index": 2` (**`+21 B`**) rather than duplicating surrounding context lines in `old_str` and `new_str`.

#### 2. Input Context Window Protection (`Measured` Runtime Caps)

- **Bounded reads:** `patchdiff_read_target` and `patchdiff_read_lines` default to **`4,000` Unicode code points** and cap at **`8,000` Unicode code points** per call.
- **Bounded occurrence search:** `patchdiff_find_occurrences` defaults `context_chars` to **`40`** (cap **`400`** code points) and caps `max_results` at **`200`**.
- **Bounded rejection enrichment:** Newly added enrichment fields (`failure_context`, `current_context`, `exact_candidates` / `near_misses`, `correlation_id`) are capped at **`<= 18,432` compact ASCII-escaped JSON bytes** (`<= 4,096 B` per context window; `<= 8,192 B` per candidate block).
- **Bounded history & ledger paging:** `patchdiff_get_pdcp_log` and `patchdiff_get_manifest_ledger` project bounded `intent` (`<= 256` chars) and `rationale` (`<= 128` chars) in SQL; when `include_content=True`, cumulative `pdcp_content` is governed by a **`1,048,576 B` UTF-8 page budget** (the first entry with content is returned whole even if $> 1\text{ MB}$; subsequent entries over budget omit content with `pdcp_content_omitted: "page_byte_budget"`).

#### 3. Tool Invocations for Multi-Edit & Recovery Workflows (`Derived`)

- **Multi-edit batching:** Applying 5 edits to one target requires **`1`** `patchdiff_submit_edits` call (or `2` with optional `patchdiff_preview`) versus **`5`** separate invocations of a single-replacement interface.
- **Recovery from ambiguity, minor typos, or lost responses:** Because rejection responses carry indexed `exact_candidates` ($\le 5$) or post-commit Levenshtein `near_misses` ($\le 3$), and `client_request_id` deduplicates timed-out retries, common recovery paths can avoid an intermediate read/search tool call (**`1` retry call** vs. **`2+` calls**). *(Whether this reduces total live-model turns across diverse tasks is a separate empirical question: `Not yet measured`.)*

#### 4. Latency: Model Generation Scaling vs. Internal Server Benchmarks (`Illustrative` vs. `Measured`)

- **Model generation scaling (`Illustrative`):** Because LLM decoding latency scales linearly with generated tokens, emitting compact `patchdiff-tx/1` deltas avoids decoding thousands of unchanged tokens on large files.
- **Internal PatchDIFF runtime & PostgreSQL benchmarks (`Measured` — `PR #13` baseline vs. `PR #14`, Windows 11, `Python 3.11.9`, `PostgreSQL 16.3`):**
  *(Note: These measure internal PatchDIFF server/database optimizations on specified local fixtures, not cross-product comparisons against external editing tools or end-to-end model turns.)*
  - **`SVC-001` Near-Miss Levenshtein Scan (`65,536`-code-point buffers, needle length `45`, threshold `4`, 5-run medians):** Exact positional pigeonhole filtering + Landau–Vishkin diagonal-wave DP reduced scan time on varied prose from `100.2 ms` (`174,897` cells) to **`1.7 ms`** (`585` cells, **58.9× faster**), and on repetitive logs from `708.5 ms` (`1,000,000` cells, truncated at 69% of buffer) to **`41.9 ms`** (`142,255` cells, **16.9× faster** while scanning **100%** of the eligible buffer).
  - **`MCP-001` PostgreSQL 16+ `LATERAL` History & Ledger Reads (`20 MB` total history, 7-run medians after warmup):** On `50 × 400 KB` `tx/3` history, `patchdiff_get_manifest_ledger(limit=50)` improved from `279.6 ms` to **`14.68 ms`** (**19.0× faster**) and `patchdiff_get_pdcp_log(limit=50)` from `372.4 ms` to **`22.85 ms`** (**16.3× faster**). On `20 × 1 MB` `tx/1` history (5 edits × 200 KB), `patchdiff_get_pdcp_log(limit=50)` runs in **`136.72 ms`** (vs. `305.55 ms`, **2.2× faster**), `patchdiff_get_manifest_ledger(limit=50)` in **`221.59 ms`** (vs. `305.55 ms`, **1.38× faster**), and `patchdiff_get_manifest_ledger(limit=100)` in **`445.33 ms`** (vs. `449.92 ms`, **1.01×**).

### 23.2 Research Hypotheses `H1`–`H7`: Original Meaning, Established Properties, and Unexecuted Empirical Trials

Preserving the exact hypothesis identities from §23 of the original concept paper, the table below distinguishes what is established today by deterministic verification and offline byte accounting from what requires a controlled live-model or human empirical study:

| Hypothesis (Original Identity Preserved) | What Is Established Today (`Measured` / `Derived` / Conformance Suite) | What Still Needs Empirical Validation (`Not yet measured` — Live-Model / Human Study `NOT RUN`) |
| --- | --- | --- |
| **H1: PatchDIFF reduces full-document decoding cost** | **Deterministic payload byte accounting (`evaluation/offline_eval.py`):** Localized `patchdiff-tx/1` and `tx/2` requests scale $O(\text{delta})$ (`151 B` `arguments` for 1 edit; `259 B` for 5 edits; `+28 B` per additional minimal 1-byte edit) rather than $O(|T|)$. Dropping `.pdcp` v0.2.3's 7 mandatory prose fields reduces 1-edit wire bytes by 66.5% (`451 B -> 151 B`) and 5-edit wire bytes by 82.3% (`1,467 B -> 259 B`). | **Actual model token consumption and end-to-end cost:** Measuring tokenizer-reported input + output tokens across multi-turn editing sessions (including any retry turns) against full regeneration, `str_replace`, and `apply_patch`. |
| **H2: PatchDIFF reduces unintended mutation** | **Deterministic locality for localized operations (Invariant 1):** Across all `816` unit and `410` integration tests, accepted `patchdiff-tx/1` and `tx/2` transactions preserve every code point outside selected match/span regions identically, and `tx/2` `expected_text` + `expected_before`/`after` guards prevent coordinate-drift splices. | **Task-level unintended edit rate:** Measuring how often an LLM using PatchDIFF introduces extraneous edits outside user-requested regions compared to full-document regeneration or unified diff tools on a benchmark task corpus. |
| **H3: PatchDIFF improves stale-context detection** | **Deterministic conflict rejection (Invariant 2):** Required `expected_target_version` and/or `expected_current_hash` under PostgreSQL `SELECT ... FOR UPDATE` plus post-simulation `target_diverged` checks guarantee a **0% silent overwrite rate** when target state diverges from the transaction's declared guard. | **Comparative agent recovery success:** Measuring how reliably agents refresh context and complete tasks after a `target_version_mismatch` / `target_hash_mismatch` rejection in multi-agent or concurrent workflows. |
| **H4: PatchDIFF supports multi-edit cached-document workflows** | **Multi-edit batching, `SAVE` cycles, and bounded SQL history (`MCP-001`):** Atomic sequential batching (`edits[]` / `operations[]`), `patchdiff_save` cycle rotation, bounded code-point reads (`4,000` / `8,000`), and SQL `LATERAL` history paging (`14.68 ms`–`221.59 ms` on 20 MB logs) are verified against live PostgreSQL. | **Multi-turn session throughput and total turn cost:** Measuring cumulative tokens, recovery overhead, and accepted edits per session over 20+ turn editing trajectories with and without `patchdiff_save`. |
| **H5: PatchDIFF preserves deterministic replay** | **Verified in software across all 7 runtime profiles (`0.1.0`..`0.5.0`) and 4 protocol versions (`0.2.3`, `tx/1`, `tx/2`, `tx/3`):** `patchdiff_replay` deterministically reconstructs target state from `initial_upload` + ordered accepted logs and verifies 4-part `materialized_state_checks`, including raw CRLF divergence detection (`evaluation/offline_eval.py` + live integration suite). | **Cross-language / independent-runtime interoperability:** Only needed if a second independent non-Python runtime implementation is introduced in the future. |
| **H6: PatchDIFF improves reviewability** | **Machine-verifiable provenance separation:** `append_only_manifest_ledger` and `patchdiff_preview` separate proposer-claimed `intent`/`rationale` (`origin`) from runtime-derived `span_start`, `span_end`, char counts, and SHA-256 digests (`derived_json`), plus advisory warnings (`no_op_change`, `grapheme_boundary_split`). | **Human reviewer speed and error-detection study:** Controlled human evaluation measuring review time, hidden-mutation detection rate, and reviewer accuracy across PatchDIFF manifests/facts vs. raw unified diffs and full-file diffs. |
| **H7: LLMs can reliably generate valid PatchDIFF transactions** | **JSON-native schema & delimiter-collision elimination:** `patchdiff-tx/1..3` replace custom text delimiters with standard tool-use JSON schemas (`TYPED_EDIT_JSON_SCHEMA`, 13 executable discovery examples), eliminating `.pdcp` delimiter collisions (`"a\n=======\nb"` accepted at `162 B` args) and providing structured `exact_candidates` and `near_misses` on rejection. | **Live-model first-attempt validity and recovery rates:** Measuring syntax-valid rate, protocol-valid rate, first-attempt `transaction_valid` rate, recovery rate after rejection diagnostics, and final task success across frontier and smaller models. |

---

## 24. Conformance & Runtime Verification Matrix

A PatchDIFF deployment is verified against an automated test matrix (**1,226 tests**: `816` unit + `410` live PostgreSQL & stdio MCP subprocess integration tests) and `evaluation/offline_eval.py`:

| Conformance Area | Verified Properties |
| --- | --- |
| **Exact & overlapping match tests** | Single match succeeds; zero match rejects (`match_absent`); duplicate match rejects (`match_ambiguous`) with `exact_candidates`; overlapping occurrences counted (`0.2.0+`); singleton selectors enforced (`0.2.2+`) |
| **Guarded span & insertion tests (`tx/2`)** | `[start, end)` bounds checked; `expected_text` verified; zero-length insertion (`start == end`, `expected_text: ""`) verified; `expected_before` / `expected_after` adjacency guards enforced under `0.5.0` |
| **Guarded replacement tests (`tx/3`)** | Required version/hash guard enforced; `1,000,000`-code-point and `1,048,576`-byte raw/canonical admission caps enforced on fresh submissions and bypassed on replay |
| **Sequential mutation & coordinates** | Later operation sees earlier replacement; consumed original match reports `sequential_match_invalid` and `consumed_by_change_id`; `prior_changes > 0` reports `buffer_stage: "intermediate_buffer"` |
| **Atomicity, locking & idempotency** | Failed operation $k$ rolls back operations $1..k-1$; `SELECT ... FOR UPDATE` serializes concurrent commits; `(target_file_id, client_request_id)` deduplicates identical retries and rejects conflicting payloads |
| **Diagnostics & near-miss exactness** | Seeded differential fuzzing (`1,000` trials) proves pigeonhole + Landau–Vishkin DP returns identical `(distance, start, end)` rankings to unpruned Levenshtein DP within `MAX_COMPARISON_CELLS = 1,000,000` |
| **Migrations, SAVE & profile replay** | Live Alembic `0001 -> 0002 -> 0003` upgrade/downgrade/upgrade with populated data; `patchdiff_save` cycle rotation; `patchdiff_replay` across `0.1.0`..`0.5.0` and `original_eol` export |

---

## 25. Related Work

PatchDIFF draws on classical textual differencing, version control, structured JSON patching, optimistic concurrency control, event sourcing, collaborative editing, semantic program transformation, edit-based neural generation, retrieval-augmented generation, and agentic software engineering.

### 25.1 Textual Differencing and Patch Systems
Classical longest-common-subsequence and shortest-edit-script algorithms established practical diff tools (Hunt and Szymanski, 1977; Myers, 1986), while Landau and Vishkin (1989) introduced efficient diagonal-wave $O(kn)$ approximate string matching (which PatchDIFF adapts in `near_miss_service.py` solely for post-rejection diagnostic discovery, never for fuzzy mutation). PatchDIFF inherits the principle of localized textual deltas while adding mandatory state preconditions, sequential transaction simulation, and append-only auditability.

### 25.2 Version Control and Commit Histories
Version-control systems such as Git record accepted repository states and content-addressed trees (Chacon and Straub, 2014). PatchDIFF operates one layer earlier, inside the agent edit-proposal loop: it records both accepted and rejected transaction attempts (`append_only_pdcp_logs`) with retry lineage (`parent_pdcp_log_id`) and separates operational replay logs from accepted manifest provenance (`append_only_manifest_ledger`).

### 25.3 JSON Patch and Structured Document Patching
RFC 6902 JSON Patch defines sequential atomic operations (`add`, `remove`, `replace`, `move`, `copy`, `test`) over JSON Pointers (Bryan and Nottingham, 2013). When paired with HTTP `PATCH` and `If-Match` ETags, JSON Patch provides preconditioned atomic updates for JSON documents. PatchDIFF applies the same preconditioned-transaction philosophy to **arbitrary UTF-8 text artifacts** (Markdown, Python, YAML, JSON, prose) where JSON Pointers do not exist, using exact text matches (`tx/1`) and text-guarded code-point spans (`tx/2`) as preconditions.

### 25.4 Optimistic Concurrency Control and MVCC
PatchDIFF's transaction lifecycle is a direct realization of optimistic concurrency control (Kung and Robinson, 1981; Bernstein and Goodman, 1981): an agent formulates a proposal against an observed `(version, current_hash)` read phase, and the server validates that precondition and every sequential text/span guard inside a serialized PostgreSQL `SELECT ... FOR UPDATE` validation/write phase.

### 25.5 Event Sourcing and Deterministic Replay
In event-sourced architectures, current state is a materialized projection of an immutable sequence of domain events (Fowler, 2005). PatchDIFF pairs an authoritative materialized target row (`cloud_target_files`) with an immutable event log (`target_snapshots` + `append_only_pdcp_logs`) and verifies their agreement via profile-dispatched `patchdiff_replay`.

### 25.6 Operational Transformation and CRDTs
Collaborative editing systems use Operational Transformation (Ellis and Gibbs, 1989; Sun et al., 1998) or Conflict-free Replicated Data Types (Shapiro et al., 2011) to merge concurrent edits automatically without rejection. Automatic convergence is desirable for concurrent human typing, but dangerous when an LLM agent acts on stale context: silently merging a stale model edit into a refactored function can produce syntactically broken or semantically contradictory text. PatchDIFF intentionally rejects stale or conflicting transactions so the agent must re-read current state.

### 25.7 Program Transformation and Semantic Patching
Semantic patching tools such as Coccinelle (Padioleau et al., 2008) express transformations over language-specific ASTs and control-flow graphs. PatchDIFF trades language-specific AST expressiveness for universal text-format neutrality and deterministic replay across code, configuration, and prose.

### 25.8 Edit-Based Neural Generation
Edit-based sequence models such as LaserTagger (Malmi et al., 2019) and Levenshtein Transformer (Gu et al., 2019) showed that predicting edit operations can be more compact than full sequence decoding. PatchDIFF applies this insight at the **protocol and transaction boundary** for general-purpose tool-use LLMs.

### 25.9 LLM-Assisted Editing and Agentic Tool Use
Reasoning-and-acting loops (Yao et al., 2023), tool-use models (Schick et al., 2023), software-engineering benchmarks such as SWE-bench (Jimenez et al., 2024), and commercial agent tools (`str_replace_based_edit_tool`, Anthropic, 2025; `apply_patch`, OpenAI, 2025) demonstrate both the power of localized model edits and the prevalence of patch-application failures, ambiguity errors, and multi-turn retry loops. PatchDIFF provides the server-side transactional substrate and structured diagnostic feedback needed to make those tool loops auditable and deterministic.

### 25.10 Context Management in Long-Horizon Agent Loops
Retrieval-augmented generation (Lewis et al., 2020) and bounded file-viewing tools mitigate prompt bloat on read, while PatchDIFF complements bounded reads (`patchdiff_read_target`, `patchdiff_read_lines`, `patchdiff_find_occurrences`) with hard byte budgets on preview (`<= 32,768 B`), rejection diagnostics (`<= 18,432 B`), and SQL `LATERAL` history paging (`<= 1,048,576 B` content budget).

---

## 26. Limitations and Operational Boundaries

### 26.1 Historical v0.2.3 Limitations Resolved in the Modernized Architecture

Several limitations identified in the v0.2.3 paper have been resolved in the current implementation:
- **Delimiter collisions:** Resolved by structured JSON string encoding in `patchdiff-tx/1`, `tx/2`, and `tx/3` (`.pdcp` v0.2.3 remains frozen for legacy compatibility).
- **Mandatory 7-field prose manifest overhead:** Reduced to a single required transaction `intent` plus optional per-edit `rationale`/`risk`, while moving span/length/hash accounting into runtime-derived `change_facts`.
- **Lack of zero-length cursor insertion:** Resolved by `patchdiff-tx/2` empty spans (`start == end`, `expected_text: ""`) with optional `expected_before` / `expected_after` adjacency guards (`patchdiff-mvp-0.5.0`).
- **Blind rejection errors on missing or duplicate matches:** Mitigated (without fuzzy auto-mutation) by `diagnostic.failure_context`, `diagnostic.exact_candidates` ($\le 5$), post-commit Levenshtein `near_misses` ($\le 3$), and `patchdiff_preview`.
- **Replay drift across protocol evolution:** Resolved by recording `(protocol_version, runtime_version)` on every log row and dispatching replay across immutable profiles `0.1.0`..`0.5.0`.

### 26.2 Active Architectural Limitations and Tradeoffs

1. **Exact matching can still reject and require extra agent turns:** While `exact_candidates` and `near_misses` assist recovery, PatchDIFF never auto-applies a near miss. When a model's assumed text differs by more than edit distance $k \le 4$, exceeds the `64`-code-point needle limit for near-miss scanning, or falls outside the first `65,536` code points / `1,000,000` comparison cells, the host must issue fresh read or search calls and resubmit.
2. **Conditional near-miss availability and intermediate-buffer coordinates:** `near_misses` is omitted inside caller-owned SQLAlchemy transactions (`"caller_transaction"`), when an earlier edit in the same transaction consumed the match (`"sequential_match_consumed"`), when `len(match) > 64` (`"match_too_large"`), or on historical recovery without context (`"historical_context_unavailable"`). On idempotent recovery (`deduplicated: true`), near-miss scanning sees only the stored 256-code-point `failure_context`. When `prior_changes > 0`, candidate coordinates refer to the sequential intermediate buffer $T_{i-1}$, not the committed target $T_0$.
3. **Per-target atomicity only (no cross-file transactions):** Atomicity is guaranteed for a single `target_file_id` under `SELECT ... FOR UPDATE`. PatchDIFF does not provide multi-target two-phase commit across multiple files simultaneously.
4. **No automatic concurrent merge:** Concurrent conflicting writes to the same target are rejected (`target_version_mismatch` / `target_hash_mismatch`), requiring the losing writer to re-read and re-propose.
5. **Semantic and task correctness are not evaluated:** An accepted transaction guarantees only that protocol rules and text/span/state preconditions held (`protocol_valid: true`, `transaction_valid: true`). It can still introduce syntax errors, type errors, or logic bugs (`task_correct: "not_evaluated"`, `semantic: "not_evaluated"`).
6. **Conservative UAX #29 grapheme approximation:** The `grapheme_boundary_split` warning checks common multi-scalar sequences (combining marks, ZWJ, regional indicators, emoji modifiers/variation selectors; Unicode Consortium, 2024), not full state-machine segmentation over every UAX #29 rule.
7. **Managed PostgreSQL state and untracked external disk edits:** Targets must be uploaded/initialized in PostgreSQL. Exporting a target writes a snapshot; external edits made directly to files on disk outside PatchDIFF are not tracked unless re-uploaded.
8. **Live-model and human comparative studies remain unexecuted (`NOT RUN`):** As detailed in Section 23.2, controlled live-LLM trials (`H1`–`H4`, `H7`) and human review trials (`H6`) are designed for future execution and are not claimed as completed measurements.

---

## 27. Discussion

PatchDIFF's central design choice is to shift trust away from unverified model-generated states and into **deterministic, stateful transaction validation** over canonical text.

In doing so, PatchDIFF changes the failure mode of agentic editing:
- A stale agent view becomes an explicit `target_version_mismatch` or `target_hash_mismatch` rejection rather than a silent overwrite.
- An ambiguous target string becomes either an explicit selector (`occurrence_index`, `anchor_before`/`after`, or `[start, end)` span) or a structured `match_ambiguous` rejection carrying `exact_candidates`.
- A multi-edit proposal becomes an all-or-nothing sequential transaction rather than a partial series of tool calls that leaves a document half-updated on error.
- A timed-out network call becomes an idempotent `client_request_id` lookup rather than a duplicate edit.

Crucially, these guarantees do not require the runtime to understand the programming language or domain semantics of the target artifact. By operating on canonical LF-normalized Unicode code points and separating `protocol_valid` and `transaction_valid` from `task_correct` and `semantic`, PatchDIFF provides a clean, verifiable substrate on top of which hosts can layer compilers, linters, test suites, and human review workflows.

---

## 28. Future Work

With typed JSON transactions (`patchdiff-tx/1..3`), bounded recovery diagnostics, request-key idempotency, and versioned replay profiles (`0.1.0`..`0.5.0`) now implemented, future work centers on five areas:

| Area | Open Research / Engineering Direction |
| --- | --- |
| **1. Controlled Live-Model Comparative Study (`H1`–`H4`, `H7`)** | Execute the Section 23.2 multi-model benchmark across prose, source code, and configuration corpora comparing full regeneration, native `str_replace`, native `apply_patch`, and PatchDIFF (`tx/1..3`) with identical models, prompts, and retry budgets, recording actual tokenizer counts, first-attempt validity, recovery turns, and decomposed latency. |
| **2. Controlled Human Review Study (`H6`)** | Evaluate human review speed, error detection, and confidence when inspecting PatchDIFF manifest provenance (`origin` + `derived_json` facts) versus raw unified diffs and full-document diffs. |
| **3. Optional Multi-Target Transaction Coordination** | Investigate grouped transactions across multiple `target_file_id` rows (e.g., ordered multi-row locking by UUID) for cross-file refactors while preserving per-target replay determinism. |
| **4. Explicit Client/Server Protocol-Version Handshake** | Add optional MCP capability negotiation for transaction format versions (distinct from the already-implemented per-record replay profile dispatch). |
| **5. Pluggable Post-Simulation Semantic Validation Hooks** | Allow hosts or server plugins to register deterministic syntax/schema validators (e.g., JSON/YAML parser, AST syntax check) between in-memory simulation ($T_n$) and PostgreSQL commit. |

---

## 29. Conclusion

PatchDIFF reframes LLM and agent document editing as **deterministic transaction control over authoritative state**.

Its primary contribution is not a new diff syntax in isolation, but an integrated transaction protocol and runtime lifecycle: required version/hash preconditions checked under PostgreSQL row locks, sequential in-memory simulation across localized exact-match edits (`patchdiff-tx/1`), guarded code-point span operations and insertions (`patchdiff-tx/2`), and explicitly bounded whole-target replacements (`patchdiff-tx/3`), paired with structured rejection diagnostics (`failure_context`, `exact_candidates`, and post-commit Levenshtein `near_misses`), idempotent retry recovery (`client_request_id`), append-only attempt and manifest ledgers, `SAVE` cycle checkpointing, and profile-dispatched deterministic replay.

For localized operations (`tx/1` and `tx/2`), accepted transactions guarantee that only matched or explicitly span-verified regions change while all unmatched content remains invariant; for explicit whole-target replacements (`tx/3`), the full-document transition is governed by the same mandatory state preconditions, atomic commit path, and audit trail. Rejected transactions never mutate the target and instead supply bounded, machine-actionable feedback for host-driven recovery.

PatchDIFF provides structural and transactional applicability guarantees rather than semantic correctness. By transforming model-generated edits from unverified rewrites or ad-hoc patches into preconditioned, auditable, and replayable state transitions, PatchDIFF provides a rigorous systems foundation for reliable agentic document editing.

---

## References

Anthropic (2024). _Model Context Protocol (MCP) Specification_. modelcontextprotocol.io.

Anthropic (2025). _Text Editor Tool (`str_replace_based_edit_tool` / `text_editor_20250728`) Documentation_. Claude Platform Documentation (`https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool`).

Bernstein, P. A., and Goodman, N. (1981). Concurrency control in distributed database systems. _ACM Computing Surveys_, 13(2), 185–221.

Bryan, P., and Nottingham, M. (2013). _RFC 6902: JavaScript Object Notation (JSON) Patch_. Internet Engineering Task Force.

Chacon, S., and Straub, B. (2014). _Pro Git_. Apress.

Chen, M., Tworek, J., Jun, H., Yuan, Q., Pinto, H. P. O., Kaplan, J., Edwards, H., Burda, Y., Joseph, N., Brockman, G., et al. (2021). Evaluating large language models trained on code. _arXiv:2107.03374_.

Ellis, C. A., and Gibbs, S. J. (1989). Concurrency control in groupware systems. _Proceedings of the ACM SIGMOD International Conference on Management of Data_, 399–407.

Fowler, M. (2005). Event Sourcing. martinfowler.com.

Gu, J., Wang, C., and Zhao, J. (2019). Levenshtein Transformer. _Advances in Neural Information Processing Systems_, 32.

Hunt, J. W., and Szymanski, T. G. (1977). A fast algorithm for computing longest common subsequences. _Communications of the ACM_, 20(5), 350–353.

Jimenez, C. E., Yang, J., Wettig, A., Yao, S., Pei, K., Press, O., and Narasimhan, K. (2024). SWE-bench: Can language models resolve real-world GitHub issues? _International Conference on Learning Representations_.

Kung, H. T., and Robinson, J. T. (1981). On optimistic methods for concurrency control. _ACM Transactions on Database Systems_, 6(2), 213–226.

Landau, G. M., and Vishkin, U. (1989). Fast parallel and serial approximate string matching. _Journal of Algorithms_, 10(2), 157–169.

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W., Rocktäschel, T., Riedel, S., and Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. _Advances in Neural Information Processing Systems_, 33.

Malmi, E., Krause, S., Rothe, S., Mirylenka, D., and Severyn, A. (2019). Encode, Tag, Realize: High-Precision Text Editing. _Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing_.

Myers, E. W. (1986). An O(ND) difference algorithm and its variations. _Algorithmica_, 1, 251–266.

OpenAI (2025). _Apply Patch Tool (`apply_patch`) Guide_. OpenAI Developer Documentation (`https://developers.openai.com/api/docs/guides/tools-apply-patch`).

Padioleau, Y., Lawall, J. L., Muller, G., and Hansen, R. R. (2008). Documenting and automating collateral evolutions in Linux device drivers. _Proceedings of the European Conference on Computer Systems_, 247–260.

Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Hambro, E., Zettlemoyer, L., Cancedda, N., and Scialom, T. (2023). Toolformer: Language models can teach themselves to use tools. _Advances in Neural Information Processing Systems_.

Shapiro, M., Preguiça, N., Baquero, C., and Zawirski, M. (2011). Conflict-free replicated data types. _International Symposium on Stabilization, Safety, and Security of Distributed Systems_, 386–400.

Sun, C., Jia, X., Zhang, Y., Yang, Y., and Chen, D. (1998). Achieving convergence, causality preservation, and intention preservation in real-time cooperative editing systems. _ACM Transactions on Computer-Human Interaction_, 5(1), 63–108.

Unicode Consortium (2024). _Unicode Standard Annex #29: Unicode Text Segmentation_. unicode.org/reports/tr29/.

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., and Cao, Y. (2023). ReAct: Synergizing reasoning and acting in language models. _International Conference on Learning Representations_.
