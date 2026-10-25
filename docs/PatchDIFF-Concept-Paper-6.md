# PatchDIFF: Transactional Document Editing for AI Agents

> **Scope & Authority Note:** This paper presents the conceptual foundation, formal transaction model, architectural tradeoffs, and research hypotheses of PatchDIFF. For executable API schemas, persistence contracts, and exact runtime limits, refer to the normative specifications ([AGENTS.md](../AGENTS.md), [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md), [MCP_TOOLS.md](MCP_TOOLS.md), [PATCHDIFF_CORE_SPEC.md](PATCHDIFF_CORE_SPEC.md), [DATA_MODEL.md](DATA_MODEL.md), and [PDCP_FORMAT.md](PDCP_FORMAT.md)).

---

## Abstract

Large language models (LLMs) and coding agents frequently modify existing documents, source files, and structured configurations across multi-turn sessions. Prevailing editing interfaces force an uncomfortable tradeoff: full-document regeneration scales in output cost with total file length and exposes unmodified regions to silent drift, whereas ad-hoc local patching (`str_replace` substring replacement, unified diffs, or unguarded line-range splices) relies on fragile context-copying or line-number arithmetic and typically lacks server-enforced optimistic concurrency, all-or-nothing multi-edit rollback, idempotent retry recovery, and durable auditability.

PatchDIFF reframes agent-driven document editing as a **deterministic, preconditioned relational transaction** exposed over the Model Context Protocol (MCP). Rather than trusting an agent to rewrite a file or directly mutate a workspace buffer, PatchDIFF maintains the canonical document state inside PostgreSQL and requires agents to submit declarative JSON transactions: **`patchdiff-tx/1`** (exact substring match/replace with explicit disambiguation), **`patchdiff-tx/2`** (mixed exact-match and guarded `[start, end)` Unicode code-point span operations with exact `expected_text` and optional `expected_before` / `expected_after` adjacency checks), and **`patchdiff-tx/3`** (explicitly guarded whole-document replacement). Every submission must carry an explicit state precondition (`expected_target_version` and/or `expected_current_hash`). Under a per-target PostgreSQL row lock (`SELECT ... FOR UPDATE`), the pure core runtime validates preconditions, simulates all operations sequentially in memory, derives exact span and cryptographic hash facts, and either commits the entire transaction atomically or rejects it without target mutation while returning bounded recovery diagnostics (`failure_context`, `exact_candidates`, and post-commit Levenshtein `near_misses`). Every attempt admitted into the locked target-submission path (whether accepted or rejected) is recorded in an append-only audit log with `client_request_id` idempotence and retry lineage (`parent_pdcp_log_id`), while accepted changes populate an append-only manifest ledger that supports `SAVE` cycle compaction and deterministic replay across versioned execution profiles.

---

## 1. Introduction: Why Agent Document Editing Needs Transactions

When an AI agent edits an authoritative artifact—such as a technical specification, legal contract, configuration manifest, or source module—the core systems challenge is not merely *how to represent a text delta*. The deeper challenge is **how to make untrusted, probabilistic model proposals safe to apply repeatedly to a shared, evolving document**.

In typical agent harnesses, editing is treated as an unguarded side effect of tool execution:
1. The agent reads part or all of a file into its prompt context.
2. The model decodes either a complete replacement file or a local patch (such as a `str_replace` call or unified diff).
3. The host writes the result directly to disk or memory, often with no version lock, no transactional rollback if the third edit in a five-edit sequence fails, no durable record of rejected attempts, and no idempotence key if the transport times out after commit.

PatchDIFF separates **probabilistic proposal generation** (owned by the MCP host and model) from **deterministic state transition authority** (owned by the PatchDIFF transaction server and PostgreSQL substrate).

### 1.1 Architectural Layers and Claim Boundaries

To keep conceptual claims, software guarantees, and empirical questions distinct, this paper separates four layers throughout:

| Layer | Scope & Evidentiary Status |
| :--- | :--- |
| **1. Core Architectural Thesis** | Model-generated edits are untrusted declarative proposals that must be validated against explicit document version/hash preconditions and applied atomically (`all-or-nothing`) by a deterministic server-side runtime over a canonical relational substrate. |
| **2. Formal Transaction & Lifecycle Mechanisms** | Structured JSON transaction formats (`patchdiff-tx/1` exact match, `patchdiff-tx/2` guarded match/span operations with optional adjacency guards, `patchdiff-tx/3` guarded whole-document replacement), MCP read/search/preview tools, per-target PostgreSQL `SELECT ... FOR UPDATE` serialization, `client_request_id` idempotency, bounded rejection diagnostics (`failure_context`, `exact_candidates`, post-commit `near_misses`), `SAVE` cycle rotation, and profile-dispatched deterministic replay. |
| **3. Deterministically Enforced & Reference-Measured Properties** | Automated unit and live PostgreSQL/stdio integration verification, deterministic payload byte accounting (`evaluation/offline_eval.py`: `151 B` compact MCP `arguments` for 1 minimal edit, `259 B` for 5 edits), hard response byte/code-point caps, and local reference implementation latency profiles. |
| **4. Open Empirical Hypotheses (`H1`–`H7`)** | Live-model comparative trials across model families (`H1`–`H4`, `H7`) and human reviewer usability studies (`H6`) are **designed in §23.2–§23.3 (`NOT RUN`)**. Strict precondition matching enforces **applicability and selection constraints**; it does **not** guarantee semantic correctness (`task_correct: "not_evaluated"`, `semantic: "not_evaluated"`) or automatic agent recovery. |

---

## 2. Failure Modes of Full-Document Regeneration

When an LLM is asked to revise an existing document by regenerating the entire artifact, four structural problems arise:

1. **$O(|T|)$ Output Cost for $O(|\Delta|)$ Edits:** Modifying a single clause or configuration value in a 64 KB document requires decoding all 64 KB of unchanged text. Output token cost, latency, and truncation risk scale with document length $|T|$ rather than edit magnitude $|\Delta|$.
2. **Unintended Drift Outside Target Regions:** Because autoregressive decoding samples every token afresh, unmodified sections remain exposed to silent rewording, formatting normalization, dropped comments, or accidental omissions.
3. **Opaque Review Surface:** Without a post-hoc diff step, a human reviewer or supervising agent cannot tell whether the model changed only the requested paragraph or subtly altered three other sections.
4. **Silent Overwrite Under Concurrent or Stale Context:** If the document advances between the turn when the agent read it and the turn when it finishes decoding a full rewrite, naive file replacement silently overwrites the intervening changes.

---

## 3. Why Cached State Alone Is Insufficient

Modern LLM APIs support prompt caching and stateful conversation threads, reducing the *input* cost of re-reading a stable document prefix. However, caching input context does not solve the *output* and *state-transition* problems:

- **Input caching does not bound output decoding:** Even if a 64 KB document is cached in the model's KV cache, asking the model to emit the updated document still decodes 64 KB of output tokens.
- **Prompt state is not authoritative storage:** A model's context window is a lossy, truncated projection of workspace state. If an agent reads lines 1–100 in turn 1 and proposes an edit in turn 4, only an external authoritative store can verify whether the target document is still at the version the agent observed.
- **Multi-turn editing requires explicit compaction boundaries:** Over dozens of edits, accumulating raw patch attempts and error traces in the conversation history bloats the prompt window unless the storage layer supports explicit checkpoints (`SAVE`) and bounded metadata queries.

---

## 4. Comparative Analysis of Agent Editing Paradigms

Existing agent harnesses typically rely on one of five editing paradigms. While a host application can always build custom locking, rollback, retry deduplication, and audit tables around any patch syntax, those guarantees are external to the edit primitive itself. PatchDIFF integrates them into the transaction protocol and persistence service:

| Capability / Guarantee | Full-File Rewrite | Unique Substring (`str_replace`) | Line Diffs (`diff -u` / V4A `apply_patch`) | Line-Range Splice | AST / RFC 6902 JSON Patch | **PatchDIFF (`patchdiff-tx/1..3`)** |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Output payload scaling** | $O(\text{file size})$ | $O(\text{edit} + \text{uniqueness padding})$ | $O(\text{edit} + \text{context lines})$ | $O(\text{edit})$ | $O(\text{edit})$ | **$O(\text{edit})$** (`tx/1`, `tx/2`); explicit $O(\text{file})$ only on `tx/3` |
| **Works across prose, code, configs & logs** | Yes | Yes | Yes | Yes | Only with grammar/JSON parser | **Yes (UTF-8 format-agnostic)** |
| **Stale-state / concurrent-write guard** | Host-dependent | Host-dependent | Implicit via context lines (host-dependent) | None (corrupts on line shift) | Via `test` op (RFC 6902) | **Required (`expected_target_version` and/or `expected_current_hash`)** |
| **Repeated-string disambiguation** | N/A | Expand `old_str` context until unique | Line numbers (`diff -u`) or context headers (`@@`) | Line numbers (fragile) | Structural path | **`occurrence_index`, `anchor_before`/`after` (`tx/1`), or guarded `[start, end)` span (`tx/2`)** |
| **Zero-length insertion at exact offset** | Re-emit full text | Must match & re-emit adjacent text | Context hunk | Line insertion (fragile) | Path insertion | **`tx/2` empty span (`start == end`, `expected_text: ""`) + optional adjacency guards** |
| **Multi-edit all-or-nothing atomicity** | Single write | Host-dependent (often per-call) | Implementation-dependent | Host-dependent | Atomic per patch document | **Server-enforced per target (`SELECT ... FOR UPDATE` + in-memory simulation)** |
| **Idempotent retry on lost transport response** | Overwrites | Fails if edit already applied | Fails if hunk already applied | Corrupts / duplicates | Fails if `test` no longer holds | **Built-in (`client_request_id` returns recorded outcome with `deduplicated: true`)** |
| **Structured recovery on mismatch** | None | Error string (`0` or `>1` matches) | Patch reject message | None | Path/test error | **Bounded `failure_context`, `exact_candidates` (up to 5), and post-commit `near_misses` (up to 3)** |
| **Durable attempt & accepted-fact ledger** | Host-dependent | Host-dependent | Host-dependent | Host-dependent | Host-dependent | **PostgreSQL `append_only_pdcp_logs` (accepted + rejected) & `append_only_manifest_ledger`** |

### 4.1 Where Line-Oriented Diffs (`diff -u` and `apply_patch`) Break Down for LLMs

Line-oriented patch tools fall into two grammar families—traditional unified diffs (`diff -u` with numeric `@@ -l,s +l,s @@` hunk headers) and headerless context diffs (such as OpenAI's V4A `apply_patch` format, which uses `*** Update File:` envelopes and `@@` context markers without numeric line counts)—each carrying distinct failure modes:
1. **Hunk header arithmetic in `diff -u`:** Standard unified diffs require exact line numbers and line counts (`@@ -l,s +l,s @@`); LLMs frequently miscount hunk lengths, causing strict `patch` parsers to reject otherwise valid edits.
2. **Envelope and prefix sensitivity:** While standard unified diffs prefix every hunk line with `' '`, `'+'`, or `'-'` (preventing raw payload lines from colliding with hunk headers), unprefixed delimiter-bounded envelopes—such as conflict-marker search/replace blocks (`<<<<<<<` / `=======` / `>>>>>>>`) or custom text-delimited patch blocks—fail with syntax collisions whenever the target text itself contains a standalone delimiter line (e.g., `"a\n=======\nb"`). Even in prefixed V4A `apply_patch` hunks, omitting a single leading space on an unchanged context line invalidates the hunk grammar.
3. **Fuzzy offset application risks:** When diff appliers or `@@` context matchers fall back to fuzzy offset search to mask line shifts or imprecise context, a hunk can silently bind to the wrong repeated block in a file.

### 4.2 Where Naive `str_replace` Breaks Down

Anthropic-style `str_replace(old_str, new_str)` avoids line-number arithmetic by requiring `old_str` to appear exactly once in the target file. However, this creates three operational bottlenecks:
1. **Context padding on repeated text:** When the target line occurs multiple times (for example, `"retry: false"` in a multi-service YAML file or a repeated closing block in source code), `str_replace` forces the model to copy surrounding unchanged lines into **both** `old_str` and `new_str` until the block is unique. In an illustrative example where disambiguating a `12 B` `"retry: false"` line (`11 B` replacement `"retry: true"`) requires an assumed `180 B` block of surrounding context (e.g., 6 lines), `str_replace` must emit `360 B` of raw `old_str` + `new_str` value text (`180 B` + `180 B`, before JSON key/call framing), whereas the corresponding `patchdiff-tx/1` edit carries `23 B` of raw match/replacement text (`"retry: false"` + `"retry: true"`) and serializes to `69 B` as a complete compact UTF-8 JSON edit object including the selector (`{"match":"retry: false","replace":"retry: true","occurrence_index":2}`: `22 B` + `23 B` + `20 B` + `4 B` braces/commas, excluding the top-level transaction envelope and MCP `tools/call` framing)—avoiding context-padding bloat that expands the surface area for single-character whitespace mismatches.
2. **Lack of explicit cursor insertion:** Because `old_str` must be non-empty and unique, inserting new content at a specific boundary requires duplicating an existing anchor block into `old_str` and `new_str`.
3. **Multi-call partial state on batch edits:** When an agent issues five separate `str_replace` tool calls and the fourth call fails, the first three mutations remain applied on disk unless the host builds an external transaction wrapper.

### 4.3 How PatchDIFF Resolves Both Failure Modes

PatchDIFF combines three complementary transaction primitives under a single guarded execution model:
- **`patchdiff-tx/1` (`patchdiff_submit_edits`)** handles standard exact-match edits without line numbers. When a target string repeats, the agent does **not** need to pad `match` with 20 lines of surrounding text; it can specify `"occurrence_index": 2` or short `"anchor_before"` / `"anchor_after"` strings.
- **`patchdiff-tx/2` (`patchdiff_submit_operations`)** adds `[start, end)` Unicode code-point span replacements and zero-length insertions (`start == end`, `expected_text: ""`). Unlike unguarded line/offset splices, every `tx/2` span requires `expected_text` to match `T[start:end]` exactly and supports optional `expected_before` and `expected_after` adjacency checks.
- **`patchdiff-tx/3` (`patchdiff_submit_replacement`)** provides an explicit, bounded whole-document replacement path when a complete rewrite is genuinely intended, still guarded by `expected_target_version` and/or `expected_current_hash`.

---

## 5. Design Principles

PatchDIFF is governed by eight architectural invariants:

1. **Authoritative Relational State:** Canonical document text, version counters, and SHA-256 content hashes live in PostgreSQL (`cloud_target_files`), never in prompt memory or unversioned scratch files.
2. **Declarative, Non-Executable Transactions:** Transaction payloads (`patchdiff-tx/1`, `tx/2`, `tx/3`) are pure data structures. The runtime never evaluates model-submitted code, regular expressions, or template scripts.
3. **Mandatory Optimistic Preconditions:** Every write submission must supply `expected_target_version` and/or `expected_current_hash`, checked under a per-target `SELECT ... FOR UPDATE` row lock.
4. **Exact Deterministic Matching & Sequential Simulation:** All operations in a transaction are simulated sequentially in memory against LF-normalized canonical text. No fuzzy matching, heuristic offset guessing, or partial commit is permitted.
5. **Separated Asserted Intent and Runtime-Derived Facts:** The model asserts high-level `intent` (and optional per-edit `rationale` and `risk`), while the runtime independently computes and records exact `span_start`, `span_end`, character counts, and SHA-256 digests (`derived_json`).
6. **Complete Append-Only Auditability:** Both accepted and rejected attempts are durably logged in `append_only_pdcp_logs` with retry lineage (`parent_pdcp_log_id`) and idempotent request keys (`client_request_id`). Accepted edits also append to `append_only_manifest_ledger`.
7. **Stage-Aware Validity & Bounded Diagnostics:** Every submission returns explicit stage validity (`protocol_valid`, `transaction_valid`, `task_correct: "not_evaluated"`, `semantic: "not_evaluated"`) and strictly bounded recovery context on rejection.
8. **Profile-Dispatched Deterministic Replay:** Re-applying the ordered sequence of accepted transactions from the initial upload snapshot under each log entry's recorded `(protocol_version, runtime_version)` profile deterministically reconstructs the exact canonical content, SHA-256 hash, and version number.

---

## 6. System Architecture and Runtime Boundary

PatchDIFF enforces a strict separation between the **MCP host/agent** (which plans edits, selects context slices, calls the model, and decides when to retry) and the **PatchDIFF transaction server** (which owns authoritative reads, validation, atomic commits, history, and replay):

```text
+-------------------------------------------------------------------------+
|                        MCP Host / Coding Agent                          |
|  - Planning, prompt construction, model invocation, retry decisions     |
|  - Semantic & task-level verification (tests, linters, human review)    |
+------------------------------------+------------------------------------+
                                     |
                                     | Model Context Protocol (MCP)
                                     | (stdio JSON-RPC / internal registry)
                                     v
+-------------------------------------------------------------------------+
|                      PatchDIFF Transaction Server                       |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  | Layer 1: MCP Transport & Tool Interface                           |  |
|  |   Advertises JSON schemas & examples; enforces response byte caps |  |
|  +---------------------------------+---------------------------------+  |
|                                    v                                    |
|  +-------------------------------------------------------------------+  |
|  | Layer 2: Transaction & Read Service Layer                         |  |
|  |   Acquires SELECT ... FOR UPDATE; checks client_request_id        |  |
|  |   idempotency, version/hash guards, and tx/3 admission caps;      |  |
|  |   computes post-commit Levenshtein near_misses on rejection.      |  |
|  +---------------------------------+---------------------------------+  |
|                                    v                                    |
|  +-------------------------------------------------------------------+  |
|  | Layer 3: Declarative Transaction Decoders & Validators            |  |
|  |   Typed JSON decoders (patchdiff-tx/1, tx/2, tx/3) lowering       |  |
|  |   into the shared internal transaction representation.            |  |
|  +---------------------------------+---------------------------------+  |
|                                    v                                    |
|  +-------------------------------------------------------------------+  |
|  | Layer 4: Pure Deterministic Core Applier                          |  |
|  |   LF canonicalization, exact match enumeration, disambiguation,   |  |
|  |   span verification, sequential simulation, change_facts, replay. |  |
|  +---------------------------------+---------------------------------+  |
|                                    v                                    |
|  +-------------------------------------------------------------------+  |
|  | Layer 5: Relational Persistence Substrate (PostgreSQL)            |  |
|  |   cloud_target_files, append_only_pdcp_logs,                      |  |
|  |   append_only_manifest_ledger, target_snapshots, editing_cycles   |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
```

The core runtime (Layers 3 and 4) is a pure function of `(target_text, target_version, target_hash, transaction_payload, runtime_profile)`. It never calls an LLM, never performs network or database I/O, and never mutates state outside memory.

---

## 7. Why Validation, Audit Logging, Idempotency, and Replay Share One Transactional Substrate

A natural architectural question is whether PatchDIFF's capabilities could be decomposed into separate, loosely coupled utilities—for example, a stateless local patch validator paired with a filesystem workspace and an external logging sink. PatchDIFF combines validation, state mutation, append-only attempt logging, request idempotence, and replay inside a single PostgreSQL transactional boundary because separating them introduces four classic distributed-state hazards:

1. **Check-then-act races between validation and commit:** If a patch is validated against a file snapshot outside a database row lock, another agent or background process can modify the file before the write completes. Acquiring a row-level `SELECT ... FOR UPDATE` lock on `cloud_target_files` before checking `expected_target_version` and `expected_current_hash` serializes guarded writes per managed target row.
2. **Lost rejection history on ephemeral tool errors:** When a stateless patch tool fails, the rejected payload and exact failure state vanish into transient chat logs. By persisting rejected attempts in `append_only_pdcp_logs` with `parent_pdcp_log_id` lineage, PatchDIFF preserves a complete, queryable record of *why* an edit failed and *how* the agent recovered.
3. **Non-idempotent retries and the ABA problem:** If a stdio or HTTP transport connection drops after the server commits an edit but before the agent receives the response, a naive retry either fails with a version mismatch (leaving the agent unsure whether its edit or another writer's edit won) or—under a hash-only guard after an $A \rightarrow B \rightarrow A$ cycle—re-applies the transaction a second time. Persisting `(target_file_id, client_request_id)` alongside the terminal response payload inside the same database commit allows the server to return the exact recorded outcome (`deduplicated: true`) on retry.
4. **Long-term replay across runtime evolution:** As an editing protocol evolves (for example, adding guarded code-point span operations or span adjacency predicates), historical audit logs cannot be re-verified unless every committed transaction records both its `protocol_version` and its immutable `runtime_version` profile alongside the initial snapshot in the same durable store.

---

## 8. The PatchDIFF Transaction Protocol Family (`patchdiff-tx/1`, `tx/2`, and `tx/3`)

PatchDIFF provides three declarative JSON transaction formats that lower into a single internal representation and execute through the same deterministic applier:

| Protocol Version | MCP Submission Tool | Execution Profile | Primary Use Case & Operation Types |
| :--- | :--- | :--- | :--- |
| **`patchdiff-tx/1`** (Primary) | `patchdiff_submit_edits` | Exact-match profile | Ordered `edits[]` with exact `match` and `replace` strings, plus optional `occurrence_index`, `anchor_before`, and `anchor_after` disambiguators. Recommended primary path for localized code and prose edits. |
| **`patchdiff-tx/2`** (Guarded Operations) | `patchdiff_submit_operations` | Match + span profile (with optional adjacency guard profile) | Ordered `operations[]` mixing `{"op": "match", ...}` and `{"op": "span", "start": s, "end": e, "expected_text": ..., "replace": ...}` (including zero-length insertion when `start == end` and `expected_text == ""`, plus optional `expected_before` / `expected_after` adjacency checks). |
| **`patchdiff-tx/3`** (Whole Replacement) | `patchdiff_submit_replacement` | Whole-target replacement profile | Submitted via MCP argument `replacement: "<new content>"` and persisted canonically as a single `{"op": "replace_all", "replace": "<new content>"}` operation under mandatory version/hash guards and fresh admission caps (`1,000,000` code points and `1,048,576` UTF-8 bytes). |

Because all three formats are native JSON objects validated by MCP tool schemas, they eliminate the delimiter-line collisions that affect text-delimited patch envelopes: target text containing standalone `<<<<<<<`, `=======`, `>>>>>>>`, or `@@` lines requires no special escaping beyond standard JSON string serialization.

---

## 9. Separating Asserted Intent from Runtime-Derived Change Facts

When an autonomous agent proposes a document modification, two fundamentally different kinds of metadata exist:
- **Asserted metadata (what the proposer *claims* it is doing):** Why the change is being made, how risky the proposer believes it is, and what logical identifier the proposer assigns to the step.
- **Derived metadata (what the transaction *actually* changes):** Which exact code-point interval $[s_i, e_i)$ was matched, how many characters were removed and inserted, and the cryptographic hashes of the before and after substrings.

If a protocol forces the LLM to compute character counts, byte offsets, or SHA-256 digests in its output, the model wastes output tokens on fragile arithmetic that the server cannot trust anyway. Conversely, if a protocol records only raw patch strings without intent metadata, human reviewers and downstream agents must reverse-engineer the purpose of a 50-edit session by re-reading every diff payload.

PatchDIFF separates these two concerns cleanly:
1. **Minimal asserted metadata on input:** Every transaction requires a single non-blank top-level `intent` string (e.g., `"Enable TLS and increase pool timeout"`). Individual edits may optionally supply `change_id` (auto-assigned as `chg_001`, `chg_002`, ... when omitted), `rationale`, and `risk` (`"low" | "medium" | "high"`).
2. **Authoritative runtime-derived facts on commit (`derived_json`):** As the applier executes each operation $i$, it computes and persists in `append_only_manifest_ledger`:
   - `span_start` and `span_end` (0-based code-point interval $[s_i, e_i)$ in the buffer state immediately preceding operation $i$),
   - `matched_chars` and `replacement_chars` (exact code-point lengths),
   - `matched_sha256` and `replacement_sha256` (lowercase hex SHA-256 digests of the UTF-8 encoded matched and replacement text),
   - `operation` (`"match"`, `"span"`, or `"replace_all"`).

This separation allows `patchdiff_get_manifest_ledger` (which defaults to `include_previous_cycles=False` for the active editing cycle) and `patchdiff_get_pdcp_log(include_content=False)` to return compact, trustworthy summaries of an editing session—projecting bounded `intent` (`<= 256` chars), `rationale` (`<= 128` chars), and runtime-derived span/hash facts—without loading multi-megabyte `pdcp_content` payloads into the agent's context window.

---

## 10. Formal Transaction Model and Core Invariants

Let $\Sigma^*$ denote the set of valid, LF-normalized UTF-8 strings (sequences of Unicode scalar values containing no UTF-16 surrogates `\uD800`–`\uDFFF` and no `NUL` code point `\u0000`, with `\r\n` and `\r` normalized to `\n`). For any string $T \in \Sigma^*$, let $|T|$ denote its length in Unicode code points, let $T[a:b]$ ($0 \le a \le b \le |T|$) denote the half-open code-point slice from index $a$ to $b$, and let $H(T) = \text{SHA256}_{\text{hex}}(\text{UTF8}(T))$.

### 10.1 Target State and Transaction Structure

An authoritative target document at rest is a tuple:
$$\mathcal{S} = (T_0, v_0, h_0) \quad \text{where } T_0 \in \Sigma^*,\; v_0 \in \mathbb{N}_0,\; h_0 = H(T_0).$$

A PatchDIFF transaction submission $\mathcal{X}$ evaluated under a server-selected immutable execution profile $\pi$ is a tuple:
$$\mathcal{X} = \bigl(\tau,\; \pi,\; g_v,\; g_h,\; \text{intent},\; \langle o_1, o_2, \dots, o_k \rangle\bigr)$$
where:
- $\tau \in \{\texttt{patchdiff-tx/1},\; \texttt{patchdiff-tx/2},\; \texttt{patchdiff-tx/3}\}$ is the protocol version,
- $\pi$ is the server-selected immutable execution profile determined from $\tau$ and the submitted operation capabilities (`overlap_aware_matching`, `enforce_singleton_selectors`, `allow_span_operations`, `allow_replace_all_operations`, `allow_span_context`) and recorded on the audit row for replay (clients never supply arbitrary runtime flags),
- $(g_v, g_h) \in (\mathbb{N}_0 \cup \{\bot\}) \times (\Sigma^{64} \cup \{\bot\})$ is the state precondition guard, with the requirement that $(g_v, g_h) \neq (\bot, \bot)$,
- $\text{intent} \in \Sigma^+$ is the non-blank transaction intent, and
- $\langle o_1, \dots, o_k \rangle$ ($k \ge 1$) is an ordered non-empty sequence of declarative operations.

### 10.2 Precondition Verification

Before any operation $o_i$ is evaluated, the state guard is checked against $(T_0, v_0, h_0)$:
$$\text{GuardOK}(\mathcal{S}, g_v, g_h) \iff (g_v = \bot \lor g_v = v_0) \;\land\; (g_h = \bot \lor g_h = h_0).$$
When both $g_v$ and $g_h$ are supplied, the version precondition $g_v = v_0$ is checked first. If $\neg\text{GuardOK}(\mathcal{S}, g_v, g_h)$, the transaction is rejected at stage `precondition_guard`—with `target_version_mismatch` when $g_v \neq \bot \land g_v \neq v_0$, or `target_hash_mismatch` when $g_h \neq \bot \land g_h \neq h_0$—reporting `protocol_valid: null` and `transaction_valid: null`, and $\mathcal{S}$ remains unchanged. Separately, if a post-simulation commit verification detects that the locked target state diverged from $(v_0, h_0)$ before commit, the transaction is rejected with `target_diverged` at stage `commit_guard` (`protocol_valid: true`, `transaction_valid: true`).

### 10.3 Sequential Operation Semantics Across All Three Operation Classes

When $\text{GuardOK}(\mathcal{S}, g_v, g_h)$ holds, the applier initializes $T^{(0)} = T_0$ and evaluates $o_1, \dots, o_k$ sequentially. Each operation $o_i$ ($1 \le i \le k$) maps intermediate buffer $T_{i-1}$ to either a unique resolved span $[s_i, e_i)$ ($0 \le s_i \le e_i \le |T_{i-1}|$) with canonical replacement string $r_i \in \Sigma^*$, or to a deterministic rejection $\bot$:

1. **Localized Exact-Match Operation (`tx/1` and `tx/2` `op="match"`):**
   $$o_i = \text{Match}(m_i, r_i, \text{occ}_i, \alpha_i, \beta_i), \quad m_i \in \Sigma^+,\; r_i \in \Sigma^*$$
   Let $\text{Occ}_\pi(T_{i-1}, m_i)$ be the ordered sequence of all exact code-point spans $[s, e)$ in $T_{i-1}$ such that $T_{i-1}[s:e] = m_i$ (enumerating every start index $s$ where $T_{i-1}[s:s+|m_i|] = m_i$, including overlapping occurrences under current profiles).
   - **Absence & sequential consumption:** If $|\text{Occ}_\pi(T_{i-1}, m_i)| = 0$, $o_i$ rejects with `match_absent` (or `sequential_match_invalid` when $i > 1$ and $m_i$ occurred in $T_0$ at a span overlapped/consumed by an earlier operation $o_j$, $j < i$, in which case post-commit `near_misses` are omitted with `omission_reason: "sequential_match_consumed"`).
   - **Un-disambiguated multiplicity:** If $|\text{Occ}_\pi(T_{i-1}, m_i)| > 1$ and no selector ($\text{occ}_i, \alpha_i, \beta_i$) is supplied, $o_i$ rejects with `match_ambiguous`.
   - **Step 1 — Global `occurrence_index` selection (before anchor filtering):** Initialize candidate list $C_0 = \text{Occ}_\pi(T_{i-1}, m_i)$ (when `enforce_singleton_selectors` is active, selectors are validated even when $|C_0| = 1$). If $\text{occ}_i \neq \bot$, it indexes directly into the **original global exact-occurrence list** $C_0$: if $1 \le \text{occ}_i \le |C_0|$, set $C_1 = [C_0[\text{occ}_i - 1]]$; otherwise reject with `disambiguation_invalid`. If $\text{occ}_i = \bot$, set $C_1 = C_0$.
   - **Step 2 — Conjunctive non-adjacent `anchor_before` and `anchor_after` filtering:** Filter $[s, e) \in C_1$ by requiring that $\alpha_i$ (when $\alpha_i \neq \bot$) occurs **anywhere in the prefix** $T_{i-1}[0 : s]$ (`anchor_before in target[:span.start]`), and $\beta_i$ (when $\beta_i \neq \bot$) occurs **anywhere in the suffix** $T_{i-1}[e : |T_{i-1}|]$ (`anchor_after in target[span.end:]`). Unlike `tx/2` span adjacency guards, match anchors need not be immediately adjacent to $[s, e)$. Operation $o_i$ succeeds iff exactly one span $[s_i, e_i)$ remains after Step 1 and Step 2 (otherwise rejecting with `disambiguation_invalid`).

2. **Localized Guarded Code-Point Span Operation (`tx/2` `op="span"`):**
   $$o_i = \text{Span}(s_i, e_i, x_i, r_i, b_i, a_i), \quad 0 \le s_i \le e_i,\; x_i, r_i \in \Sigma^*,\; |x_i| = e_i - s_i$$
   Operation $o_i$ succeeds on intermediate buffer $T_{i-1}$ iff:
   - Bounds hold: $0 \le s_i \le e_i \le |T_{i-1}|$ (otherwise `span_out_of_bounds`),
   - Substring precondition holds: $T_{i-1}[s_i:e_i] = x_i$ (otherwise `span_expected_text_mismatch` with `span_check: "expected_text"`; when $s_i = e_i$ and $x_i = \varepsilon$, this defines an exact **zero-length insertion** at code-point offset $s_i$), and
   - Immediate-adjacency preconditions hold when supplied ($b_i \neq \bot$ or $a_i \neq \bot$): $s_i \ge |b_i| \land T_{i-1}[s_i - |b_i| : s_i] = b_i$, and $e_i + |a_i| \le |T_{i-1}| \land T_{i-1}[e_i : e_i + |a_i|] = a_i$ (otherwise `span_expected_text_mismatch` with `span_check: "expected_before"` or `"expected_after"`).

3. **Guarded Whole-Target Replacement Operation (`tx/3` `op="replace_all"`):**
   $$k = 1,\quad o_1 = \text{ReplaceAll}(r_1), \quad r_1 \in \Sigma^*$$
   Subject to service-level fresh admission bounds on raw and canonical content ($|r_1| \le 1{,}000{,}000$ code points and $|\text{UTF8}(r_1)| \le 1{,}048{,}576$ bytes; fresh submissions exceeding these bounds return `invalid_argument` with `code: "replacement_too_large"` before entering the applier, whereas replay never re-applies fresh admission bounds), $o_1$ selects the full target span $[s_1, e_1) = [0, |T_0|)$ and replaces $T_0$ with $r_1$.

When operation $o_i$ resolves to $[s_i, e_i)$, the next buffer state is:
$$T_i = T_{i-1}[0 : s_i] \,\|\, r_i \,\|\, T_{i-1}[e_i : |T_{i-1}|].$$

### 10.4 Four Core Formal Invariants

#### Invariant 1: Localized Unmatched-Content Preservation (`tx/1` and `tx/2`)
For every individual localized operation $o_i \in \{\text{Match}, \text{Span}\}$ that resolves to span $[s_i, e_i)$ in $T_{i-1}$, the prefix and suffix outside $[s_i, e_i)$ are preserved code-point-for-code-point:
$$T_i[0 : s_i] = T_{i-1}[0 : s_i] \quad \text{and} \quad T_i\bigl[s_i + |r_i| : |T_i|\bigr] = T_{i-1}\bigl[e_i : |T_{i-1}|\bigr].$$
*(Note: Whole-target replacement `tx/3` is intentionally excluded from localized preservation because its explicit contract is to replace the full span $[0, |T_0|)$ under mandatory version/hash guards.)*

#### Invariant 2: All-or-Nothing Per-Target Atomic State Transition
If any precondition fails or any operation $o_i$ ($1 \le i \le k$) yields $\bot$, the committed target state remains identically $\mathcal{S}' = \mathcal{S} = (T_0, v_0, h_0)$. Only if all $k$ operations succeed does the target advance atomically to:
$$\mathcal{S}' = \bigl(T_k,\; v_0 + 1,\; H(T_k)\bigr).$$

#### Invariant 3: Deterministic Execution and Profile-Dispatched Replay Equivalence
For any fixed initial snapshot $T_{\text{init}}$ and ordered sequence of accepted log records $\langle (\mathcal{X}_1, \pi_1), \dots, (\mathcal{X}_m, \pi_m) \rangle$, sequential evaluation of $\mathcal{X}_j$ under its recorded profile $\pi_j$ is a pure deterministic function that yields the exact materialized state $(T_m, m, H(T_m))$.

#### Invariant 4: Request-Key Idempotency
For any target $F$ and non-null `client_request_id` $q$, at most one transaction submission with key $(F, q)$ is ever executed. Any subsequent submission carrying $(F, q)$ with an identical request fingerprint returns the recorded terminal response (`deduplicated: true`) without re-executing the applier or mutating $\mathcal{S}$. Any submission carrying $(F, q)$ with a different request fingerprint is rejected without mutating $\mathcal{S}$, returning `failure_reason: "context_invalid"` and `diagnostic.code: "request_key_conflict"` (logged as a separate rejected attempt with `client_request_id = NULL` so the original key binding remains intact).

---

## 11. Canonicalization, Unicode Semantics, and Source Line-Ending Preservation

Cross-platform editing fails silently when tools disagree on line endings (`\r\n` vs. `\n`), character indexing (UTF-8 bytes vs. UTF-16 code units vs. Unicode scalar values), or invalid Unicode sequences. PatchDIFF enforces three rules:

| Boundary | Canonical Rule |
| :--- | :--- |
| **Canonical storage & matching (`\n`)** | All target documents, `match`/`replace` strings, `expected_text`, and anchors are canonicalized to LF (`\r\n` $\rightarrow$ `\n`, standalone `\r` $\rightarrow$ `\n`) before hashing (`current_hash`) or matching. |
| **Unicode scalar indexing** | All offsets (`start`, `end`, `span_start`, `span_end`, `length`) are 0-based Unicode code-point (scalar value) indices over the LF-canonical string—identical to Python `str` indexing. |
| **UTF-8 & PostgreSQL text safety** | Strings containing UTF-16 surrogates (`\uD800`–`\uDFFF`) or `NUL` (`\u0000`) are rejected at stage `protocol_validation` with `failure_reason: "target_encoding_invalid"`. Known-target invalid-text attempts are durably logged using reversible ASCII-escaped evidence (`patchdiff-invalid-input/1`) without corrupting PostgreSQL `TEXT`/`JSONB` columns. |
| **Source line-ending preservation** | Upload records `source_line_endings` with lowercase `style` in `{"lf", "crlf", "cr", "mixed", "none"}` and raw upload digest `source_sha256`. While canonical storage and `current_hash` always use LF, `patchdiff_export_target` supports `format = "original_text" | "canonical_lf" | "crlf" | "original_eol"` so uniform original line endings can be restored on export. |
| **Advisory grapheme-split warning** | If a matched or span boundary splits a multi-code-point Unicode extended grapheme cluster (UAX #29, such as an emoji ZWJ sequence or base character + combining mark), the applier emits an advisory `grapheme_boundary_split` warning on acceptance without rejecting the edit. |

---

## 12. Exact Matching, Overlapping Occurrences, and Disambiguation

A subtle defect in many string-replacement tools is how they count occurrences when a pattern overlaps itself. Consider the target string $T = \texttt{"ababa"}$ and pattern $m = \texttt{"aba"}$.
- A naive non-overlapping scanner (`str.find` stepping by `len(m)`) finds only index `0` and falsely concludes that `"aba"` is unique in `"ababa"`.
- In fact, `"aba"` occurs at two exact spans: $[0, 3)$ and $[2, 5)$.

PatchDIFF's matcher enumerates **all** exact occurrences by advancing the search start by $1$ code point (`pos + 1`) after each match:
- In `"ababa"`, searching for `"aba"` finds two occurrences ($[0, 3)$ and $[2, 5)$) and rejects an un-disambiguated `tx/1` edit with `match_ambiguous` (`match_count = 2`), returning both spans in `diagnostic.exact_candidates`.
- Furthermore, under the singleton-selector rule (`enforce_singleton_selectors`), if a pattern occurs only **once** in $T_{i-1}$ (`match_count = 1`), the runtime still validates any supplied `occurrence_index`, `anchor_before`, or `anchor_after` so that a stale selector (e.g., `occurrence_index = 2` when only 1 occurrence remains) is caught and rejected as `disambiguation_invalid` rather than silently ignored.

---

## 13. Sequential In-Memory Application and Coordinate Semantics

Within a multi-operation transaction (`patchdiff-tx/1` or `patchdiff-tx/2`), operations execute **sequentially in array order** against the evolving in-memory buffer:
$$T_0 \xrightarrow{o_1} T_1 \xrightarrow{o_2} T_2 \xrightarrow{\dots} T_k.$$

This sequential model has two important consequences that host integrations must respect:
1. **Later operations observe earlier replacements:** If $o_1$ changes `"version = 1"` to `"version = 2"`, or shifts character offsets in $T_1$, operation $o_2$ is evaluated against $T_1$, not $T_0$.
   - If $o_1$ and $o_2$ target the same repeated string and $o_1$ replaces occurrence `1`, then in $T_1$ the remaining occurrence is now occurrence `1` (not `2`). When an accepted transaction's later `occurrence_index` selects a span whose index shifted due to an earlier edit in the same transaction, the runtime records an advisory `occurrence_index_basis_shift` warning so the host can inspect it.
   - When submitting multiple `tx/2` code-point span edits in a single transaction where each span changes the length of the document ($|r_i| \neq e_i - s_i$), submitting spans in **descending offset order** (from the bottom of the file toward the top) keeps earlier code-point offsets invariant.
2. **Intermediate-buffer rejection coordinates (`prior_changes > 0`):** If operations $o_1, \dots, o_{i-1}$ succeed in memory and operation $o_i$ ($i > 1$) fails, no changes are committed to PostgreSQL ($\mathcal{S}' = \mathcal{S}$). However, `diagnostic.failure_context`, `exact_candidates`, and `near_misses` for the failing operation $o_i$ are computed against the **intermediate in-memory buffer $T_{i-1}$** (`buffer_stage = "intermediate_buffer"`, `prior_changes = i - 1`), whereas `current_context` reflects the committed target $T_0$.

---

## 14. Operational Primitives: Replacement, Insertion, Deletion, and Guarded Rewrite

All common document editing actions map cleanly onto `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`:

- **Modification (in-place replacement):** `match` $\rightarrow$ `replace` (`tx/1` or `tx/2` `op="match"`), or `[start, end)` + `expected_text` $\rightarrow$ `replace` (`tx/2` `op="span"`).
- **Deletion:** Set `replace: ""` on a non-empty `match` (`tx/1` / `tx/2`) or non-empty `[start, end)` span (`tx/2`).
- **Insertion:**
  - In `patchdiff-tx/1`, `match` must be non-empty (an empty `match: ""` is rejected by schema validation or at `protocol_validation` with `block_malformed`), so insertion is expressed by matching an adjacent anchor substring and including it in `replace`.
  - In `patchdiff-tx/2`, zero-length insertion is expressed directly without duplicating anchor text into `replace`: set `op: "span"`, `start == end`, `expected_text: ""`, and optionally guard the insertion point with `expected_before` and/or `expected_after`.
- **Whole-Document Replacement:** Use `patchdiff_submit_replacement` (`patchdiff-tx/3`, `op: "replace_all"`) with mandatory `expected_target_version` and/or `expected_current_hash`.

---

## 15. Stage-Aware Validity and Failure Taxonomy

A central flaw in naive patch tools is collapsing all failures into an unstructured error string, or conversely treating a syntactically applied patch as proof that the user's task succeeded. PatchDIFF tracks the exact `ValidationStage` reached by each submission in the execution path and reports a four-part `validity` object on every response:

```text
1. precondition_guard        (target lookup, UUID/lineage checks, pre-parse version/hash & request-key guards)
   |
   v
2. protocol_validation       (structural/schema decoding, UTF-8/NUL text safety, non-empty match, selector syntax)
   |
   v
3. transaction_applicability (sequential in-memory simulation: match resolution, span bounds, expected_text & adjacency)
   |
   v
4. commit_guard              (post-simulation target version/hash verification before commit)
   |
   v
5. accepted                  (atomic database commit; non-blocking advisory warnings attached if present)
```

| Validity Dimension | `precondition_guard` Rejection | `protocol_validation` Rejection | `transaction_applicability` Rejection | `commit_guard` Rejection | `accepted` | Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `protocol_valid` | `null` | `false` | `true` | `true` | `true` | Did the transaction satisfy structural and protocol validation? (`null` if rejected before protocol evaluation.) |
| `transaction_valid` | `null` | `null` | `false` | `true` | `true` | Did sequential in-memory simulation succeed against the evaluated buffer? (`null` if not reached.) |
| `task_correct` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | Did the edit fulfill the user's high-level instruction? *(Host-evaluated)* |
| `semantic` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | Does the resulting code/document compile, pass tests, or preserve domain meaning? *(Host-evaluated)* |

Always returning `"not_evaluated"` for `task_correct` and `semantic` enforces a vital epistemic boundary: **PatchDIFF certifies that the state transition was authorized, exact, and atomic—never that the resulting code passes unit tests or satisfies domain logic.**

---

## 16. Host-Owned Recovery Loop and Bounded Rejection Diagnostics

Instead of embedding a hidden LLM inside the database server to silently rewrite failed patches, PatchDIFF keeps the retry loop in the **MCP host** and equips rejection responses with bounded, deterministic recovery evidence (without guaranteeing that additional read/search calls or retries will always succeed):

1. **Up-to-date state coordinates:** Known-target rejections return the target's committed `current_version` and `current_hash` at the top level.
2. **Bounded failure window (`failure_context` and `current_context`):** Persisted `diagnostic.failure_context` and response-only `current_context` each provide up to `256` Unicode code points (`<= 4,096` compact ASCII-escaped JSON bytes each; `<= 8,192 B` combined, with `current_context` omitted when identical to `failure_context`) around the failure location.
3. **Ambiguity candidates (`exact_candidates` on `match_ambiguous` / `disambiguation_invalid`):** Persisted `diagnostic.exact_candidates` returns `occurrence_count` and up to `5` exact occurrences (`<= 8,192 B`), each with its 1-based `occurrence_index`, `start`, `end`, `match_preview` (`<= 64` code points), `match_truncated`, and 20-code-point `before`/`after` context snippets.
4. **Post-commit Levenshtein near-misses (`near_misses` on eligible `match_absent` rejections):** After a service-owned transaction commits the rejection log and releases the target row lock (`sequential_match_invalid` omits near-misses with `omission_reason: "sequential_match_consumed"`, and caller-owned transactions omit them with `omission_reason: "caller_transaction"`), PatchDIFF scans up to the first `65,536` code points of an in-memory copy of the failing buffer (for needles `1..64` code points under a `1,000,000`-comparison-cell cap) using an exact positional pigeonhole prefilter and Ukkonen-banded Landau–Vishkin diagonal-wave edit-distance program with threshold `min(4, max(1, len(needle) // 4))`. Response-only top-level `near_misses` returns up to `3` non-overlapping candidate substrings ordered by `(distance, start, end)`, each exposing `distance`, `start`, `end`, `text`, `before`, and `after` (`<= 8,192 B`), subject to a combined `<= 18,432 B` ceiling across newly added diagnostic enrichment fields.
5. **Advisory dry-run preview (`patchdiff_preview`):** Allows a host to test a `tx/1`, `tx/2`, or `tx/3` payload against a read-only observation (`<= 32,768 B` response budget) without acquiring a row lock, writing an audit log, or reserving a version.

---

## 17. Structural Safety and the Non-Executable Boundary

PatchDIFF treats every transaction submission as **untrusted data**, never executable code:

```text
patchdiff-tx/1, patchdiff-tx/2, or patchdiff-tx/3 = declarative, non-executable transaction data
PatchDIFF core runtime & service layers           = trusted deterministic validator and applier
target document                                   = Markdown / Python / YAML / JSON / prose / etc.
```

- **No `eval`, shell, regex, or AST execution:** The runtime performs only deterministic Unicode string slicing, exact substring search, SHA-256 hashing, and parameterized SQL queries via SQLAlchemy.
- **Typed JSON validation vs. prose freedom:** In `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`, proposals arrive as structured JSON objects validated against strict schemas (`additionalProperties: false`, type and bound checks, and UTF-8/PostgreSQL text validation). Because JSON keys and string values are structurally separated, `intent` and `rationale` strings in typed transactions may freely mention code symbols (`import`, `def`, `class`, SQL keywords, or diff markers) without triggering false-positive rejections.

---

## 18. Locality Controls: Runtime-Enforced Bounds vs. Host Policies

To prevent unintended wide-area rewrites while still supporting legitimate whole-file updates, it is important to distinguish **controls enforced directly by the PatchDIFF runtime** from **optional policies that an MCP host or enterprise harness may layer on top**:

| Control Mechanism | Enforced by PatchDIFF Runtime? | Actual Runtime / Host Behavior |
| :--- | :--- | :--- |
| **Non-empty `match` in `tx/1` and `tx/2` match ops** | **Yes (Runtime-enforced)** | Empty `match: ""` is rejected (`invalid_argument` at MCP tool schema validation or `block_malformed` at `protocol_validation`). |
| **Separation of localized edits (`tx/1`, `tx/2`) from whole-target rewrite (`tx/3`)** | **Yes (Runtime-enforced)** | `replace_all` is forbidden in `tx/1` and `tx/2`; whole-document replacement requires calling `patchdiff_submit_replacement` (`tx/3`). |
| **Fresh admission size cap on `tx/3` (`replace_all`)** | **Yes (Service-enforced on fresh submissions)** | Fresh `tx/3` submissions exceeding `1,000,000` Unicode code points or `1,048,576` UTF-8 bytes (raw or canonical, evaluated after `client_request_id` recovery/conflict checks) return `invalid_argument` with `code: "replacement_too_large"` before entering the applier or creating an audit row; replay never re-applies fresh admission caps. |
| **Runtime-derived `matched_chars` & `replacement_chars` per edit** | **Yes (Runtime-computed)** | Computed and returned in `evidence.changes` (and `patchdiff_preview`) and stored in `append_only_manifest_ledger.derived_json`. |
| **Advisory warnings (`no_op_change`, `no_op_transaction`, `occurrence_index_basis_shift`, `grapheme_boundary_split`)** | **Yes (Runtime-computed, non-blocking)** | Returned in `warnings[]` on accepted transactions and persisted in `diagnostic_json.warnings`; never convert an accepted edit into a rejection. |
| **Heuristic replacement-ratio limits or mandatory human approval on `risk: "high"`** | **No (Host-owned policy)** | The runtime does **not** reject a localized edit because `replacement_chars / matched_chars` is large or because `risk == "high"`. Hosts can inspect `patchdiff_preview` or `evidence.changes` to enforce custom approval gates. |

---

## 19. Persistence Architecture, Audit Logs, and Deterministic Replay

PatchDIFF's PostgreSQL persistence substrate maintains five core tables:

1. **`cloud_target_files`**: Canonical `current_content` (LF-normalized), `current_hash` (SHA-256), `current_version` (monotonic integer starting at `0`), and `source_line_endings`.
2. **`append_only_pdcp_logs`**: Immutable log of every submission attempt admitted into the audited target-submission path (`status = 'accepted' | 'rejected'`; pre-admission MCP argument errors such as `invalid_argument` / `replacement_too_large` return before creating a log row), ordered by `log_sequence`, recording `protocol_version`, `runtime_version`, `pdcp_content` (canonical JSON), `pdcp_hash`, `expected_target_version`, `expected_current_hash`, `base_version`, `resulting_version`, `failure_reason`, `diagnostic_json`, `parent_pdcp_log_id`, and `client_request_id` + `request_fingerprint`.
3. **`append_only_manifest_ledger`**: Immutable ledger of **accepted** changes only, ordered by `ledger_sequence`, recording `origin`, `editing_cycle_id`, `change_id`, `intent`, `risk`, and `derived_json` (`span_start`, `span_end`, char counts, SHA-256 digests).
4. **`target_snapshots`**: Immutable snapshots (`snapshot_type = 'initial_upload' | 'save_checkpoint'`), storing the full canonical content, hash, and version at creation and at each `SAVE` boundary.
5. **`editing_cycles`**: Tracks active and completed editing cycles (`status = 'active' | 'saved'`) rotated by `patchdiff_save`.

### 19.1 Versioned Execution Profiles and 4-Component Replay Verification

Every accepted row in `append_only_pdcp_logs` records both its `protocol_version` and an immutable `runtime_version` profile capturing the exact semantic rule flags active when the transaction was committed (`overlap_aware_matching`, `enforce_singleton_selectors`, `allow_span_operations`, `allow_replace_all_operations`, `allow_span_adjacency_guards`).

When `patchdiff_replay(target_file_id)` is invoked, the replay engine loads the `initial_upload` snapshot, replays every accepted log entry in `log_sequence` order by dispatching on `(protocol_version, runtime_version)`, and verifies four independent `materialized_state_checks` against `cloud_target_files`:
1. `content_matches`: Replayed canonical text equals `cloud_target_files.current_content`.
2. `stored_hash_matches`: Replayed SHA-256 hash equals `cloud_target_files.current_hash`.
3. `recomputed_hash_matches`: `SHA256(cloud_target_files.current_content)` equals `cloud_target_files.current_hash` (detecting raw out-of-band database corruption such as injected CRLF bytes).
4. `version_matches`: Replayed version equals `cloud_target_files.current_version`.

---

## 20. Concurrency Model: Serialized Per-Target Commits Under Optimistic Guards

Multiple MCP hosts, background workers, or subagents may connect to the same PatchDIFF server and read or target the same document concurrently:

- **Per-target serialization under `SELECT ... FOR UPDATE`:** Every write submission (`patchdiff_submit_edits`, `patchdiff_submit_operations`, `patchdiff_submit_replacement`) and `patchdiff_save` acquires a PostgreSQL row-level lock (`SELECT ... FOR UPDATE` with `populate_existing=True`) on the `cloud_target_files` row before checking `client_request_id` idempotency or evaluating `expected_target_version` / `expected_current_hash`.
- **Optimistic concurrency rejection on conflict:** If two agents read version `v = 4` concurrently and submit edits carrying `expected_target_version = 4`, the first transaction to acquire the row lock commits and advances the target to `v = 5`. The second transaction then acquires the lock, sees `current_version = 5 != 4`, logs a deterministic `target_version_mismatch` rejection (with `current_version: 5` and bounded `current_context`), and leaves `v = 5` intact.
- **Single-target atomicity scope:** Atomicity is strictly **per `target_file_id`**. PatchDIFF does not provide multi-file distributed transactions across different `target_file_id` rows; hosts editing multiple files coordinate multi-file workflows at the host layer.

---

## 21. MCP Tool Surface and Host Integration Workflow

PatchDIFF exposes its transaction and inspection lifecycle over MCP (`tools/list` and `tools/call`) across five functional tool groups:

1. **Target Initialization & Export (`4` tools):** `patchdiff_handle_upload`, `patchdiff_initialize_target`, `patchdiff_get_target`, `patchdiff_export_target`.
2. **Authoritative Bounded Reads & Search (`4` tools):** `patchdiff_read_target` (code-point slices, `4,000` default / `8,000` max, returning `next_start`), `patchdiff_read_lines` (1-based inclusive `start_line` / `end_line` ranges with `offset`, `max_chars`, and `include_line_starts`, capped at `4,000` default / `8,000` max Unicode code points per page and returning range-relative `next_offset` and absolute `next_start`), `patchdiff_find_occurrences` (exact substring search with `40` default / `400` max side context, up to `200` results), and `patchdiff_build_prompt_context` (labelled convenience prefix wrapper).
3. **Guarded Transaction Submission (`3` tools):** `patchdiff_submit_edits` (`tx/1`), `patchdiff_submit_operations` (`tx/2`), and `patchdiff_submit_replacement` (`tx/3`).
4. **Advisory Dry-Run Preview (`1` tool):** `patchdiff_preview` (`<= 32,768 B` response budget).
5. **Checkpointing, Replay & Bounded History (`4` tools):** `patchdiff_save`, `patchdiff_replay`, `patchdiff_get_pdcp_log`, and `patchdiff_get_manifest_ledger`.

---

## 22. `SAVE` Compaction and Long-Session Context Hygiene

During a long editing session (for example, 40 sequential edits to a specification or module), two distinct histories grow:
1. The **server-side manifest ledger** (`append_only_manifest_ledger`), and
2. The **host's LLM conversation history** (past tool calls, responses, and reasoning turns).

`patchdiff_save(target_file_id)` provides an explicit **cycle boundary** in the persistence substrate:
1. Under `SELECT ... FOR UPDATE`, it records an immutable `save_checkpoint` row in `target_snapshots` capturing `(current_content, current_hash, current_version)`.
2. It marks the current row in `editing_cycles` as `status = 'saved'` (`ended_version = current_version`) and opens a fresh `active` editing cycle (`cycle_number + 1`, `started_version = current_version`).
3. Because `patchdiff_get_manifest_ledger` defaults to `include_previous_cycles = False`, querying the ledger immediately after `patchdiff_save` returns an **empty active-cycle ledger (`entries: []`)** for the new cycle, while setting `include_previous_cycles = True` still exposes the complete historical ledger across prior cycles, and `patchdiff_replay` still verifies the full history from `initial_upload`.

**Scope boundary:** `patchdiff_save` rotates the server-side active cycle view and records a durable checkpoint snapshot; it does **not** automatically summarize or truncate the host's in-memory LLM chat transcript. Instead, hosts use `patchdiff_save` as a safe synchronization point at which the host can discard prior edit-turn messages from its prompt window and retain only the new `current_version` / `current_hash` and active slices read via `patchdiff_read_target`.

---

## 23. Operational Efficiency, Reference Measurements, and Research Hypotheses (`H1`–`H7`)

All quantitative and comparative claims in this paper follow a four-tier classification:
1. **`Enforced Contract / Hard Cap`**: Deterministic byte, code-point, or row-count bounds enforced in software.
2. **`Measured (PatchDIFF-only)`**: Deterministic byte counts from `evaluation/offline_eval.py` and local reference workload medians.
3. **`Analytical Comparison`**: Structural complexity and round-trip comparisons under stated workflow assumptions.
4. **`Comparative Hypothesis (Not Yet Measured)`**: Live-model token/success trials (`H1`–`H4`, `H7`) and human review studies (`H6`) (`NOT RUN`).

### 23.1 Deterministic Payload Byte Scaling & Reference Runtime Characteristics (`Measured`)

Reproducible via `PYTHONPATH=backend python evaluation/offline_eval.py`:

| Scenario (`evaluation/offline_eval.py`) | Raw Replacement Text (`B`) | Minimal `patchdiff-tx/1` (`arguments` `B` / Persisted Record `B`) | Rationale-Annotated `patchdiff-tx/1` (`arguments` `B` / Persisted Record `B`) | `patchdiff-tx/3` Whole-Target Rewrite (`arguments` `B` / Persisted Record `B` / JSON-RPC Line `B`) |
| :--- | :--- | :--- | :--- | :--- |
| **1 tiny edit (`"old" -> "new"`)** | `3 B` | **`151 B`** / **`206 B`** | `327 B` / `382 B` | **`232 B`** / **`290 B`** / **`341 B`** |
| **5 small edits in 1 transaction (`5 × 1 B`)** | `5 B` | **`259 B`** / **`314 B`** | `1,139 B` / `1,194 B` | — |
| **1 edit, 2 KB span (`2,053 B` match/replace)** | `2,053 B` (`2,109 B` full body) | **`4,441 B`** / **`4,496 B`** | `4,617 B` / `4,672 B` | **`2,377 B`** / **`2,435 B`** / **`2,486 B`** |
| **Quotes + backslashes + Unicode (`🌍`, `中`)** | `16 B` | **`172 B`** / **`227 B`** | `348 B` / `403 B` | **`250 B`** / **`308 B`** / **`359 B`** |
| **Payload containing a standalone `=======` line** | `14 B` | **`162 B`** / **`217 B`** | `338 B` / `393 B` | — |

- **Marginal wire cost per additional `patchdiff-tx/1` edit:** Each additional minimal edit item `{"match":"...","replace":"..."}` in `edits[]` adds exactly **`26 B` of JSON structure** (`25 B` object keys/punctuation + `1 B` comma) plus the JSON-escaped UTF-8 lengths of `match` and `replace` (`28 B` total for two 1-byte ASCII strings).
- **Hard context-protection caps (`Enforced Contract`):**
  - Target reads (`patchdiff_read_target`, `patchdiff_read_lines`): **`4,000` code points default / `8,000` code points max per page** (with `start_line`, `end_line`, `offset`, `max_chars`, `include_line_starts`, and `next_offset` / `next_start` continuation on `patchdiff_read_lines`).
  - Occurrence search (`patchdiff_find_occurrences`): **`40` code points side context default (`400` max)**, up to **`200` results**.
  - Rejection context (`failure_context`, `current_context`): **`<= 256` code points (`<= 4,096 B`) each** (`<= 8,192 B` combined).
  - Ambiguity & near-miss enrichment (`exact_candidates` up to 5, `near_misses` up to 3): **`<= 8,192 B` each**, **`<= 18,432 B` combined enrichment cap**.
  - Advisory preview (`patchdiff_preview`): **`<= 32,768 B` total** (`<= 16,384 B` facts + `<= 16,384 B` diagnostics).
  - History & ledger pagination (`patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`): **`50` rows default / `200` max**; `patchdiff_get_manifest_ledger` defaults to `include_previous_cycles=False` and projects bounded `transaction_intent` (`<= 256` chars) and `rationale` (`<= 128` chars); on `patchdiff_get_pdcp_log`, default `include_content=False` omits raw payloads and projects bounded `intent` (`<= 256` chars), while `include_content=True` enforces a **`1,048,576 B` (`1 MiB`)** cumulative `pdcp_content` page budget (always returning the first non-empty entry on a page whole and marking subsequent over-budget entries with `pdcp_content_omitted: "page_byte_budget"`).
  - MCP tool discovery (`tools/list`): **`<= 65,536 B` total** across all registered tools (`<= 8,192 B` for 13 worked examples across 9 tools).
- **Reference implementation latency characteristics (`Measured` — local single-machine medians on Windows 11, `Python 3.11.9`, `postgres:16.3-alpine`):**
  - **Post-Commit Near-Miss Levenshtein Scan (`65,536`-code-point buffers, needle length `45`, threshold `4`, 5-run medians):** Using exact positional pigeonhole prefiltering plus an Ukkonen-banded Landau–Vishkin edit-distance DP under the `1,000,000`-cell cap, scanning a 65,536-code-point varied prose buffer takes **`1.7 ms`** (`scanned_end = 65,493`, `scope_truncated = False`), and scanning a dense repetitive log buffer takes **`41.9 ms`** (`scanned_end = 65,493`, `142,255` cells, `scope_truncated = False`).
  - **Bounded SQL History & Ledger Reads (`20 MB` total history, 7-run medians after warmup):** Using PostgreSQL 16+ `pg_input_is_valid(..., 'jsonb')` and `LATERAL` JSON projections so `patchdiff_get_pdcp_log(include_content=False)` and `patchdiff_get_manifest_ledger` queries do not transfer multi-megabyte `pdcp_content` blobs to Python, reading 50 rows over a `20 MB` `tx/3` history (`50 × 400 KB`) takes **`14.68 ms`** (ledger) and **`22.85 ms`** (attempt log); over a `20 MB` `tx/1` history (`20 × 1 MB`), reading 50 rows takes **`136.72 ms`** (attempt log) and **`221.59 ms`** (ledger, or **`445.33 ms`** at `limit=100`).

### 23.2 Status of the Seven Core Research Hypotheses (`H1`–`H7`)

The table below states each of PatchDIFF's seven core research hypotheses (`H1`–`H7`) and separates what is **established in software and offline measurements today** from what **requires live-model or human empirical validation (`NOT RUN`)**:

| Research Hypothesis | Established Today (Deterministic Runtime & Offline Measurements) | Open Empirical Evaluation (`NOT RUN` — Experimental Protocol in §23.3) |
| :--- | :--- | :--- |
| **H1: PatchDIFF reduces full-document decoding cost** | **Deterministic payload byte accounting (`evaluation/offline_eval.py`):** Localized `patchdiff-tx/1` payloads scale with $O(|\Delta|)$ rather than document size $|T|$ (`151 B` MCP `arguments` for 1 minimal edit, `259 B` for 5 edits, `+28 B` per additional 1-byte edit). | **Live-model token & latency study (`NOT RUN`):** Measure total input + output tokens, wall-clock latency, and API cost across live LLM families when performing single-turn and multi-turn edits via PatchDIFF vs. full-document rewrite, `str_replace`, and `apply_patch`. |
| **H2: PatchDIFF reduces unintended mutation** | **Deterministic locality for localized operations (Invariant 1):** For every accepted `tx/1` and `tx/2` transaction, code points outside the resolved $[s_i, e_i)$ spans are provably invariant (`T_i[0:s_i] == T_{i-1}[0:s_i]` and `T_i[s_i+|r_i|:] == T_{i-1}[e_i:]`). Unintended whole-file rewrites cannot occur via `tx/1` or `tx/2`. | **End-to-end agent edit-fidelity study (`NOT RUN`):** Measure how often live models select an unintended span or over-broad `match` string compared to silent drift in full-file rewrites or misapplied fuzzy diffs. |
| **H3: PatchDIFF improves stale-context detection** | **Enforced optimistic concurrency guards:** Every submission requires `expected_target_version` and/or `expected_current_hash` evaluated under `SELECT ... FOR UPDATE`. Any version or hash divergence deterministically rejects (`target_version_mismatch`, `target_hash_mismatch`, `target_diverged`) with zero target mutation. | **Multi-agent contention & recovery study (`NOT RUN`):** Measure conflict recovery success rates and wasted turns when multiple live agents concurrently edit shared documents under optimistic locking. |
| **H4: PatchDIFF supports multi-edit cached-document workflows** | **Multi-edit batching, `SAVE` cycles, and bounded SQL history:** `tx/1` and `tx/2` execute ordered multi-edit batches atomically in memory; `patchdiff_save` rotates active editing cycles (`include_previous_cycles=False` returns an empty active-cycle ledger `entries: []`); SQL `LATERAL` projection bounds 50-row history reads over `20 MB` logs to `14.68–221.59 ms`. | **Long-horizon session study (`NOT RUN`):** Measure cumulative prompt token growth and task completion over 20–100 sequential edits with periodic `patchdiff_save` compaction vs. uncompacted agent loops. |
| **H5: PatchDIFF preserves deterministic replay** | **Verified by implementation tests across supported execution profiles:** `patchdiff_replay` reconstructs canonical state from `initial_upload` + ordered accepted logs and verifies all four `materialized_state_checks` (`content_matches`, `stored_hash_matches`, `recomputed_hash_matches`, `version_matches`), including detection of out-of-band raw CRLF injection. | **Supported replay behavior verified in the reference implementation test suite.** *(Cross-implementation conformance and multi-million-row longitudinal archive benchmarks remain future work.)* |
| **H6: PatchDIFF improves reviewability** | **Separation of asserted intent from derived facts:** `append_only_manifest_ledger` stores model-claimed `intent` / `rationale` alongside runtime-computed `derived_json` (`span_start`, `span_end`, char counts, SHA-256 hashes), and `patchdiff_preview` exposes those exact facts prior to commit. | **Human reviewer & auditing study (`NOT RUN`):** Measure human review time and defect-detection accuracy when inspecting PatchDIFF manifest ledgers + derived span facts vs. raw unified diffs or full-file rewrites. |
| **H7: LLMs can reliably generate valid PatchDIFF transactions** | **JSON-native schema & delimiter-collision elimination:** `patchdiff-tx/1..3` use standard JSON tool arguments (`TYPED_EDIT_JSON_SCHEMA`, `TYPED_OPERATIONS_JSON_SCHEMA`, `TYPED_REPLACEMENT_JSON_SCHEMA`) advertised with 13 executable discovery examples (`<= 8,192 B`), eliminating line-delimiter collisions (`"a\n=======\nb"` is accepted at `162 B`). | **Live-model first-pass validity & retry-convergence study (`NOT RUN`):** Measure first-turn `protocol_valid` and `transaction_valid` rates, plus 1-retry convergence rates using `exact_candidates` and `near_misses`, across frontier and smaller open-weight models. |

### 23.3 Experimental Design for Live-Model & Human Benchmarks (`H1`–`H4`, `H6`, `H7`)

To evaluate the open empirical hypotheses (`H1`–`H4`, `H6`, `H7`) rigorously without conflating Edit Format with Host Harness policy, future live-model trials should hold the model, temperature (`0.0`), target corpus (`4 KB`, `32 KB`, `64 KB`, and `256 KB` files across Python, TypeScript, Markdown, JSON, and YAML), and read budget constant while comparing four conditions:
1. **Condition A:** Full-document rewrite (`write_file`).
2. **Condition B:** Unique substring replacement (`str_replace`).
3. **Condition C:** Unified diff (`apply_patch`).
4. **Condition D:** PatchDIFF (`patchdiff_read_target` / `patchdiff_find_occurrences` $\rightarrow$ `patchdiff_submit_edits` / `patchdiff_submit_operations`, with bounded diagnostic feedback on rejection).

Primary dependent variables: (a) first-attempt `protocol_valid` and `transaction_valid` rates (`H7`), (b) post-rejection recovery rate within $\le 2$ retries and total tool round-trips (`H7`), (c) total input and output tokens billed (`H1`, `H4`), (d) unintended out-of-span character mutations (`H2`), (e) stale-write prevention under injected concurrent modifications (`H3`), and (f) human review time and error-identification accuracy (`H6`).

---

## 24. Verification Methodology: Unit, Relational, and Transport Conformance

Because PatchDIFF acts as an authoritative transaction monitor, its deterministic guarantees must be verified across three distinct testing layers:

| Verification Category | Required Invariant Coverage |
| :--- | :--- |
| **Canonicalization & Unicode safety** | CRLF/CR $\rightarrow$ LF normalization; rejection of UTF-16 surrogates and `NUL` (`target_encoding_invalid`) with reversible ASCII-escaped audit evidence; preservation of lowercase `source_line_endings.style` (`lf`, `crlf`, `cr`, `mixed`, `none`) on export (`original_text`, `canonical_lf`, `crlf`, `original_eol`). |
| **Exact & overlapping match enumeration** | Single match succeeds; zero match rejects (`match_absent`); duplicate match rejects (`match_ambiguous`) unless uniquely resolved by global `occurrence_index` selection followed by non-adjacent `anchor_before`/`anchor_after` filtering; overlapping occurrences (`"aba"` in `"ababa"`) enumerated accurately; invalid singleton selectors rejected (`disambiguation_invalid`). |
| **Guarded span (`tx/2`) & replacement (`tx/3`) semantics** | Exact `expected_text` verification on `[start, end)`; zero-length insertion (`start == end`, `expected_text: ""`); immediate-adjacency `expected_before` / `expected_after` checks (`span_expected_text_mismatch`); `tx/3` fresh admission size caps (`1,000,000` code points, `1,048,576` bytes, returning `invalid_argument` / `replacement_too_large`). |
| **Sequential simulation & atomicity** | Multi-operation transactions evaluate against intermediate in-memory buffers $T_{i-1}$; failure at operation $i > 1$ (including `sequential_match_invalid` when an earlier operation consumed the match) leaves PostgreSQL target state completely unchanged (`v_0`, `h_0`) and labels diagnostics with `buffer_stage = "intermediate_buffer"` and `prior_changes = i - 1`. |
| **Bounded diagnostics & preview** | `failure_context` / `current_context` capped at `256` code points (`<= 4,096 B` each); `exact_candidates` (max 5) and post-commit `near_misses` (max 3) capped at `<= 8,192 B` each (`<= 18,432 B` combined enrichment); `patchdiff_preview` capped at `<= 32,768 B` with zero DB locks or writes. |
| **Concurrency, idempotency & lineage** | Per-target `SELECT ... FOR UPDATE` row locking; stale version/hash rejection; `(target_file_id, client_request_id)` idempotent recovery (`deduplicated: true`) and payload-mismatch conflict rejection (`context_invalid` with `diagnostic.code: "request_key_conflict"`); `parent_pdcp_log_id` retry lineage validation. |
| **Checkpointing, profile replay & stdio transport** | Tested schema migration `upgrade -> downgrade -> upgrade` conformance (with downgrade safety guards that refuse destructive data loss when newer feature rows exist); `patchdiff_save` snapshot creation and cycle rotation; 4-component replay verification across execution profiles; end-to-end JSON-RPC execution over real `stdio` subprocess pipes. |

---

## 25. End-to-End Transactional Walkthrough

Consider a target file `config.yaml` initialized at `current_version = 0`, `current_hash = "8f4a..."`:

```yaml
service:
  name: auth-api
  timeout_ms: 1000
  retry: false
worker:
  name: background-sync
  timeout_ms: 1000
  retry: false
```

1. **Bounded Read / Search:** The agent calls `patchdiff_find_occurrences(target_file_id, text="retry: false")`. PatchDIFF returns `occurrence_count: 2` (`occurrence_index: 1` at `[47, 59)` under `service`, and `occurrence_index: 2` at `[113, 125)` under `worker`), along with `current_version: 0`.
2. **Guarded Multi-Edit Submission (`patchdiff-tx/1`):** To update `service.timeout_ms` to `2500` and enable `retry: true` only on `worker`, the agent submits a single atomic transaction:
   ```json
   {
     "target_file_id": "2c6f9c9c-6e9e-4f15-9a25-88c5b6e2f101",
     "expected_target_version": 0,
     "client_request_id": "req-worker-retry-01",
     "intent": "Increase service timeout to 2500ms and enable worker retries",
     "edits": [
       {
         "match": "  name: auth-api\n  timeout_ms: 1000",
         "replace": "  name: auth-api\n  timeout_ms: 2500"
       },
       {
         "match": "retry: false",
         "replace": "retry: true",
         "occurrence_index": 2
       }
     ]
   }
   ```
3. **Deterministic Validation & Atomic Commit:** Under `SELECT ... FOR UPDATE`, PatchDIFF verifies `current_version == 0`, applies edit 1 in memory ($T_0 \rightarrow T_1$), resolves occurrence `2` of `"retry: false"` in $T_1$ ($T_1 \rightarrow T_2$), increments `current_version` to `1`, records the accepted attempt in `append_only_pdcp_logs` and two derived change rows in `append_only_manifest_ledger`, and returns `status: "accepted"`, `current_version: 1`.
4. **Idempotent Retry Recovery:** If a network glitch drops the response and the host resends the identical payload with `"client_request_id": "req-worker-retry-01"`, PatchDIFF sees the recorded key, skips re-execution, and returns the exact `status: "accepted"`, `current_version: 1` response with `"deduplicated": true`.

---

## 26. Architectural Limitations and Operational Tradeoffs

PatchDIFF deliberately trades heuristic permissiveness for deterministic safety. Integrators and researchers should account for the following boundaries and operational limitations:

1. **Exact matching can still reject and cost extra turns when near-miss bounds are exceeded:**
   - Because PatchDIFF never performs fuzzy auto-application, a single-character typo in `match` or `expected_text` always rejects the transaction and requires a host retry turn.
   - Furthermore, post-commit `near_misses` are bounded: they run **only** on eligible `match_absent` rejections when the failing needle has length `1..64` code points, scan at most `65,536` code points of the failing buffer copy under a `1,000,000`-comparison-cell cap (`scope_truncated: true` if capped), are omitted on `sequential_match_invalid` rejections (`omission_reason: "sequential_match_consumed"`), and are skipped when `submit_*` is called inside a caller-owned outer SQLAlchemy transaction (`omission_reason: "caller_transaction"`). When `near_misses` are unavailable or truncated, the host must issue an explicit `patchdiff_read_target` or `patchdiff_find_occurrences` call.
2. **Intermediate-buffer coordinates on multi-edit failures (`prior_changes > 0`):**
   - When operation $i > 1$ fails in a multi-operation transaction, `failure_context`, `exact_candidates`, and `near_misses` reflect the uncommitted intermediate buffer $T_{i-1}$ (`buffer_stage = "intermediate_buffer"`), not the committed target $T_0$. Hosts must either adjust operation $i$ relative to the preceding operations $1 \dots i-1$ in the same batch or inspect `current_context` ($T_0$).
3. **Single-target atomicity only:**
   - Transactions are atomic per `target_file_id`. Cross-file refactorings spanning multiple documents are not committed in a single multi-target transaction.
4. **Conservative Unicode grapheme-cluster warning:**
   - The `grapheme_boundary_split` check inspects immediate boundary code points around $[s_i, e_i)$ (catching combining marks, ZWJ sequences, variation selectors, and regional indicator pairs) as an advisory warning; it is not a full locale-sensitive linguistic segmentation engine.
5. **No semantic or task-level correctness guarantee:**
   - An accepted PatchDIFF transaction guarantees that precondition guards held and exact text/span operations succeeded (`protocol_valid: true`, `transaction_valid: true`). It never guarantees that the resulting code compiles, passes tests, or satisfies the user's intent (`task_correct: "not_evaluated"`, `semantic: "not_evaluated"`).
6. **Live-model comparative efficiency remains an open empirical question (`Decision A8`):**
   - While deterministic byte counts and local PostgreSQL/runtime latencies are measured, end-to-end token savings and retry-convergence rates across live LLM families remain unexecuted (`NOT RUN`).

---

## 27. Security, Trust Boundaries, and Deployment Scope

- **Trust boundary:** Model outputs and MCP tool arguments are untrusted inputs validated at the protocol and service layers. The PostgreSQL database and PatchDIFF Python runtime are trusted infrastructure components.
- **Resource & DoS bounds:** Read/search tools enforce hard code-point and result caps (`8,000` code points, `200` occurrences); `tx/3` enforces a `1 MiB` (`1,048,576 B`) / `1,000,000`-code-point fresh admission cap; `near_misses` execute *after* releasing the target row lock under a hard `1,000,000`-cell budget; and `include_content=True` history paging enforces a `1 MiB` cumulative page budget (after the first non-empty entry on a page).
- **Authentication & multi-tenant isolation:** PatchDIFF is designed as a local or private-network MCP transaction service (`stdio` subprocess or internal FastAPI/MCP registry). Multi-tenant authentication, RBAC, and network TLS termination are deployment-layer responsibilities outside the core transaction engine.

---

## 28. Future Research and Architectural Extensions

1. **Executing the Live-Model & Human Comparative Benchmark Suite (`H1`–`H4`, `H6`, `H7`):** Running the controlled multi-model evaluation defined in §23.3 across frontier and open-weight coding models to quantify first-pass validity, retry convergence with `near_misses`/`exact_candidates`, and net session token cost.
2. **Multi-Target Coordinated Transactions:** Extending `SELECT ... FOR UPDATE` lock ordering (e.g., canonical UUID sort order across `target_file_id[]`) to support all-or-nothing multi-file refactoring transactions while preserving per-target replayable ledgers.
3. **Client/Server Protocol Capability Handshake:** While PatchDIFF already dispatches replay across recorded `(protocol_version, runtime_version)` tuples, adding an explicit MCP capability-negotiation handshake would allow hosts and servers at different minor versions to negotiate supported transaction versions (`tx/1..3`) dynamically at connection startup.
4. **Optional Host-Side Semantic Verification Hooks:** Providing standardized post-preview / pre-commit callback patterns so hosts can run syntax checkers, typecheckers, or unit tests against `patchdiff_preview` outputs before committing.

---

## 29. Conclusion

As AI agents transition from single-turn code completions to long-horizon, multi-turn collaborators over persistent documents, the editing interface can no longer treat file mutation as an unguarded side effect. Full-document regeneration wastes output bandwidth and risks silent drift across untouched regions, while unguarded local patch tools (`str_replace`, unified diffs, line-range splices) leave concurrency control, multi-edit rollback, retry idempotence, and auditability to ad-hoc host wrappers.

PatchDIFF demonstrates that agent document editing is naturally modeled as a **deterministic, preconditioned database transaction**. By combining structured JSON transaction primitives—localized exact-match edits (`patchdiff-tx/1`), localized guarded code-point span operations (`patchdiff-tx/2`), and explicitly guarded whole-target replacement (`patchdiff-tx/3`)—with per-target PostgreSQL `SELECT ... FOR UPDATE` serialization, `client_request_id` idempotency, stage-accurate validity reporting, bounded recovery diagnostics (`failure_context`, `exact_candidates`, and post-commit Levenshtein `near_misses`), `SAVE` cycle compaction, and profile-dispatched deterministic replay, PatchDIFF gives MCP hosts a rigorous, auditable foundation for iterative document state transitions.

---

## References

1. **Model Context Protocol (MCP) Specification:** Anthropic, *Model Context Protocol Specification (JSON-RPC 2.0 Transport & Tool Calling)*, `https://modelcontextprotocol.io/`.
2. **IETF RFC 6902:** P. Bryan and M. Nottingham, *JavaScript Object Notation (JSON) Patch*, RFC 6902, April 2013.
3. **Unicode Standard Annex #29 (UAX #29):** M. Davis, *Unicode Text Segmentation (Extended Grapheme Clusters)*, Unicode Consortium.
4. **Approximate String Matching & Banded Edit Distance:**
   - E. Ukkonen, *"Algorithms for Approximate String Matching,"* Information and Control, 64(1–3):100–118, 1985.
   - G. M. Landau and U. Vishkin, *"Fast Parallel and Serial Approximate String Matching,"* Journal of Algorithms, 10(2):157–169, 1989.
5. **Optimistic Concurrency Control:** H. T. Kung and J. T. Robinson, *"On Optimistic Methods for Concurrency Control,"* ACM Transactions on Database Systems (TODS), 6(2):213–226, 1981.
6. **Agent Editing Tool Interfaces (Primary Vendor Specifications):**
   - Anthropic, *Text Editor Tool (`str_replace_based_edit_tool` / `str_replace`)*, Claude API Documentation, `https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/text-editor-tool`.
   - OpenAI, *Apply Patch Tool (`apply_patch` V4A Diff Format)*, OpenAI Platform Documentation & Cookbook, `https://platform.openai.com/docs/guides/tools`.
7. **PatchDIFF Normative Specifications:**
   - [AGENTS.md](../AGENTS.md) — Locked architectural invariants and runtime boundaries.
   - [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md) — Architecture decisions (`A1`–`A8`), contracts (`C1`–`C6`), and historical design reconciliation.
   - [MCP_TOOLS.md](MCP_TOOLS.md) — Normative MCP tool contracts, schemas, and byte budgets.
   - [PATCHDIFF_CORE_SPEC.md](PATCHDIFF_CORE_SPEC.md) — Deterministic core runtime specification and validation stages.
   - [DATA_MODEL.md](DATA_MODEL.md) — PostgreSQL schema and constraints.
   - [PDCP_FORMAT.md](PDCP_FORMAT.md) — Transaction formats (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`).
   - [evaluation/README.md](../evaluation/README.md) — Offline payload byte accounting and evaluation methodology.
