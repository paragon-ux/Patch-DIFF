# PatchDIFF: Transactional Document Editing for AI Agents

This paper explains PatchDIFF's transaction model, tradeoffs, and research
hypotheses. For the mathematical state space, operational transition algebra,
and invariant proofs, see the companion paper:
[Formal Transaction Model](formal-transaction-model.md).
For implementation details, start with the
[architecture](modernization-architecture.md),
[MCP tools](../spec/mcp-tools.md), [core runtime](../spec/core-runtime.md),
[data model](../spec/data-model.md), and [transaction formats](../spec/transaction-formats.md).
[Repository invariants](https://github.com/paragon-ux/Patch-DIFF/blob/main/AGENTS.md)
govern the implementation.

---

## Abstract

Large language models and coding agents frequently modify documents, source files, and structured configurations across multi-turn sessions. Conventional editing interfaces force an uncomfortable tradeoff: full-document regeneration scales in output cost with total file length and exposes unmodified regions to silent drift, whereas local patching approaches (such as substring replacement, unified diffs, or unguarded line-range splices) rely on fragile context copying or line-number arithmetic. Crucially, these interfaces typically lack server-enforced optimistic concurrency, all-or-nothing multi-edit rollback, idempotent retry recovery, and durable audit logs.

PatchDIFF reframes agent-driven document editing as a **deterministic, preconditioned relational transaction** exposed over the Model Context Protocol (MCP). Rather than trusting an agent to rewrite a file or directly mutate a workspace buffer, PatchDIFF maintains canonical document state inside PostgreSQL and requires agents to submit declarative JSON transactions: exact substring replacement with explicit disambiguation under `patchdiff-tx/1`, guarded code-point span operations with adjacency predicates under `patchdiff-tx/2`, and guarded whole-document replacement under `patchdiff-tx/3`. Every submission must carry an explicit state precondition specifying an expected target version, content hash, or both. Under a per-target PostgreSQL row lock using `SELECT ... FOR UPDATE`, the service verifies preconditions, coordinates idempotent deduplication, and commits atomic transactions. Meanwhile, a pure deterministic runtime simulates all operations sequentially in memory, enumerates exact matches, and derives span and cryptographic hash facts, rejecting invalid proposals without target mutation while returning bounded diagnostics, candidate locations, and near-miss suggestions. Every attempt admitted into the locked submission path is durably recorded in an append-only audit log with request-key idempotence and retry lineage, while accepted changes populate an append-only manifest ledger that supports cycle compaction and deterministic replay across versioned execution profiles.

---

## 1. Introduction: Why Agent Document Editing Needs Transactions

When an AI agent edits an authoritative artifact (such as a technical specification, legal contract, configuration manifest, or source module), the core systems challenge is not merely how to represent a text delta. The deeper challenge is **how to make untrusted, probabilistic model proposals safe to apply repeatedly to a shared, evolving document**.

In typical agent harnesses, editing is treated as an unguarded side effect of tool execution:
1. The agent reads part or all of a file into its prompt context.
2. The model decodes either a complete replacement file or a local patch (such as a substring replacement call or unified diff).
3. The host writes the result directly to disk or memory, often with no version lock, no transactional rollback if the third edit in a five-edit sequence fails, no durable record of rejected attempts, and no idempotence key if the transport times out after commit.

PatchDIFF separates **probabilistic proposal generation** (owned by the MCP host and model) from **deterministic state transition authority** (owned by the PatchDIFF transaction server and PostgreSQL substrate). The foundation of this architecture is strict determinism: exact code-point matching guarantees that an edit applies strictly to the intended text and fails closed if even a single character has shifted. Every subsequent capability (optimistic row locks, in-memory multi-edit rollback, AST structural discovery, append-only durability, and staged workspace publication) builds directly on top of that exact-match foundation.

### 1.1 Architectural Layers and Claim Boundaries

To keep conceptual claims, software guarantees, and empirical questions distinct, this paper separates four layers throughout:

| Layer | Scope & Evidentiary Status |
| :--- | :--- |
| **1. Core Architectural Thesis** | Model-generated edits are untrusted declarative proposals that must be validated against explicit document version/hash preconditions and applied atomically (all or nothing) by a deterministic server-side runtime over a canonical relational substrate. |
| **2. Formal Transaction & Lifecycle Mechanisms** | Structured JSON transaction formats across `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`, MCP read, search, and preview tools, per-target PostgreSQL `SELECT ... FOR UPDATE` serialization, `client_request_id` idempotency, bounded rejection diagnostics, cycle rotation, and profile-dispatched deterministic replay. |
| **3. Deterministically Enforced & Reference-Measured Properties** | Automated unit and live PostgreSQL/stdio integration verification, deterministic payload byte accounting (151 bytes of compact arguments for 1 minimal edit and 259 bytes for 5 edits in offline evaluation), hard response byte and code-point caps, and local reference implementation latency profiles. |
| **4. Empirical Validation & Open Hypotheses (H1 to H7)** | The [current Workspace benchmark](../benchmarks/workspace-e2e-benchmark.md) evaluates three editing workflows across 18 trials ($n=3$ per arm across 6 Git and non-Git conditions): Native file edits, host-orchestrated structural edits (observed_v2), and autonomous agent-owned workspace edits (workspace and observed_workspace). Workspace averaged 16.2% less timed execution and verification time and 42.7% fewer editor calls, with agent-owned import and publication. All 90 files matched byte-for-byte and all 360 behavior checks passed. Preparation and owner handoffs are separate setup measurements. Model choice is operator-attested. Broader workloads, multi-agent concurrency, long-horizon sessions, and human-review studies remain open. |

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
- **Prompt state is not authoritative storage:** A model's context window is a lossy, truncated projection of workspace state. If an agent reads lines 1 to 100 in turn 1 and proposes an edit in turn 4, only an external authoritative store can verify whether the target document is still at the version the agent observed.
- **Multi-turn editing requires explicit compaction boundaries:** Over dozens of edits, accumulating raw patch attempts and error traces in conversation history bloats the prompt window unless the storage layer supports explicit checkpoint saves via `patchdiff_save` and bounded metadata queries.

---

## 4. Comparative Analysis of Agent Editing Paradigms

Existing agent harnesses typically rely on one of five editing paradigms: full-file rewriting, unique substring replacement such as `str_replace`, line-oriented diffs such as `diff -u` and `apply_patch`, line-range splices, or structural AST patches. While a host application can build custom locking, rollback, retry deduplication, and audit logging around an external tool, those guarantees remain separate from the editing primitive itself.

PatchDIFF organizes these capabilities into a coherent determinism hierarchy. At the bedrock, exact code-point matching guarantees that an edit applies strictly to the intended text and fails closed if even a single character has shifted. Around this deterministic core, PatchDIFF layers transactional controls that conventional tools leave to ad-hoc host orchestration: optimistic row-level locking, in-memory multi-edit rollback, AST structural discovery, append-only durability, and staged workspace publication:

| Capability / Guarantee | Full-File Rewrite | Unique Substring (str_replace) | Line Diffs (diff -u / apply_patch) | Line-Range Splice | AST / RFC 6902 JSON Patch | **PatchDIFF (patchdiff-tx/1 to tx/3)** |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Output payload scaling** | $O(\text{file size})$ | $O(\text{edit} + \text{uniqueness padding})$ | $O(\text{edit} + \text{context lines})$ | $O(\text{edit})$ | $O(\text{edit})$ | **$O(\text{edit})$** on tx/1 and tx/2; explicit $O(\text{file})$ only on tx/3 |
| **Works across prose, code, configs & logs** | Yes | Yes | Yes | Yes | Only with grammar/JSON parser | **Yes (UTF-8 format-agnostic)** |
| **Stale-state / concurrent-write guard** | Host-dependent | Host-dependent | Implicit via context lines (host-dependent) | None (corrupts on line shift) | Via test op (RFC 6902) | **Required (expected_target_version and/or expected_current_hash)** |
| **Repeated-string disambiguation** | N/A | Expand old_str context until unique | Line numbers (diff -u) or context headers (@@) | Line numbers (fragile) | Structural path | **occurrence_index, anchor_before/after (tx/1), or guarded span (tx/2)** |
| **Zero-length insertion at exact offset** | Re-emit full text | Must match & re-emit adjacent text | Context hunk | Line insertion (fragile) | Path insertion | **tx/2 empty span (start == end) with optional adjacency guards** |
| **Multi-edit all-or-nothing atomicity** | Single write | Host-dependent (often per-call) | Implementation-dependent | Host-dependent | Atomic per patch document | **Server-enforced per target (SELECT ... FOR UPDATE with in-memory simulation)** |
| **Idempotent retry on lost transport response** | Overwrites | Fails if edit already applied | Fails if hunk already applied | Corrupts / duplicates | Fails if test no longer holds | **Built-in (client_request_id returns deduplicated outcome)** |
| **Structured recovery on mismatch** | None | Error string (zero or multiple matches) | Patch reject message | None | Path or test error | **Bounded failure context, up to 5 exact candidates, and up to 3 near misses** |
| **Durable attempt & accepted-fact ledger** | Host-dependent | Host-dependent | Host-dependent | Host-dependent | Host-dependent | **PostgreSQL audit log (accepted and rejected attempts) and manifest ledger** |

### 4.1 Where Line-Oriented Diffs (diff -u and apply_patch) Break Down for LLMs

Line-oriented patch tools fall into two grammar families: traditional unified diffs (using diff -u with numeric line-count headers) and headerless context diffs (such as OpenAI's V4A apply_patch format, which uses text update envelopes and context markers without numeric line counts). Each carries distinct failure modes:
1. **Hunk header arithmetic in diff -u:** Standard unified diffs require exact line numbers and line counts; language models frequently miscount hunk lengths, causing strict patch parsers to reject otherwise valid edits.
2. **Envelope and prefix sensitivity:** While standard unified diffs prefix every hunk line with a space, plus, or minus character (preventing raw payload lines from colliding with hunk headers), text-delimited patch envelopes and conflict-marker formats fail with syntax collisions whenever the target text itself contains standalone delimiter lines. Even in prefixed V4A apply_patch hunks, omitting a single leading space on an unchanged context line invalidates the hunk grammar.
3. **Fuzzy offset application risks:** When diff appliers or context matchers fall back to fuzzy offset search to mask line shifts or imprecise context, a hunk can silently bind to the wrong repeated block in a file.

### 4.2 Where Naive Substring Replacement Breaks Down

Substring replacement functions like `str_replace(old_str, new_str)` avoid line-number arithmetic by requiring the target string to appear exactly once in the file. However, this creates three operational bottlenecks:
1. **Context padding on repeated text:** When the target line occurs multiple times (such as a configuration line like retry: false in a multi-service manifest or a repeated closing block in source code), substring replacement forces the model to copy surrounding unchanged lines into both old and new arguments until the block is unique. For example, replacing a 12-byte retry: false setting with an 11-byte retry: true in a file where the setting repeats typically requires copying roughly 180 bytes of surrounding lines. A conventional tool must emit 360 bytes of raw text across both arguments. By contrast, a `patchdiff-tx/1` edit carries only the 23 bytes of target and replacement text, adding an occurrence index such as `occurrence_index: 2` to resolve ambiguity. The entire edit serializes to 69 bytes as a compact JSON object. This eliminates context-padding bloat and removes the risk of spurious failures caused by whitespace discrepancies in unchanged surrounding lines.
2. **Lack of explicit cursor insertion:** Because the target string must be non-empty and unique, inserting new content at an exact boundary requires duplicating an existing anchor block into both old and new parameters.
3. **Multi-call partial state on batch edits:** When an agent issues five separate tool calls and the fourth call fails, the first three mutations remain written to disk unless the host harness has implemented an external rollback wrapper.

### 4.3 How PatchDIFF Resolves Both Failure Modes

PatchDIFF combines three complementary transaction primitives under a single guarded execution model:
- **Exact-match editing under `patchdiff-tx/1`:** Submitted via `patchdiff_submit_edits`, this primitive handles standard string replacements without line numbers. When target text repeats, the agent resolves ambiguity using an occurrence index or short prefix and suffix anchors, avoiding multi-line context padding.
- **Guarded span editing under `patchdiff-tx/2`:** Submitted via `patchdiff_submit_operations`, this primitive adds Unicode code-point span replacements and zero-length insertions. Unlike unguarded line or byte splices, every span requires the text at that position to match `expected_text` exactly, with optional checks on immediately adjacent text before and after the span.
- **Guarded document replacement under `patchdiff-tx/3`:** Submitted via `patchdiff_submit_replacement`, this primitive provides an explicit, bounded whole-document replacement path when a complete rewrite is genuinely intended, guarded by explicit version and hash preconditions.

---

## 5. Design Principles

PatchDIFF is governed by eight architectural invariants:

1. **Authoritative Relational State:** Canonical document text, version counters, and SHA-256 content hashes live in PostgreSQL inside `cloud_target_files`, never in prompt memory or unversioned scratch files.
2. **Declarative, Non-Executable Transactions:** Transaction payloads across `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3` are pure data structures. The runtime never evaluates model-submitted code, regular expressions, or template scripts.
3. **Mandatory Optimistic Preconditions:** Every write submission must supply `expected_target_version` and/or `expected_current_hash`, checked under a per-target `SELECT ... FOR UPDATE` row lock.
4. **Exact Deterministic Matching & Sequential Simulation:** All operations in a transaction are simulated sequentially in memory against LF-normalized canonical text. No fuzzy matching, heuristic offset guessing, or partial commit is permitted.
5. **Separated Asserted Intent and Runtime-Derived Facts:** The model asserts high-level intent (with optional rationale and risk classifications), while the runtime independently computes and records exact code-point spans, character counts, and SHA-256 digests in `derived_json`.
6. **Complete Append-Only Auditability:** Both accepted and rejected attempts are durably logged in `append_only_pdcp_logs` with retry lineage and idempotent request keys. Accepted edits also append to `append_only_manifest_ledger`.
7. **Stage-Aware Validity & Bounded Diagnostics:** Every submission returns explicit stage validity (protocol and transaction validity, with task and semantic correctness labeled as not evaluated) and strictly bounded recovery context on rejection.
8. **Profile-Dispatched Deterministic Replay:** Re-applying the ordered sequence of accepted transactions from the initial upload snapshot under each log entry's recorded execution profile deterministically reconstructs the exact canonical content, SHA-256 hash, and version number.

---

## 6. System Architecture and Runtime Boundary

PatchDIFF enforces a strict operational separation between the external MCP host or coding agent and the internal transaction server:

1. **MCP Host and Coding Agent (External Client)**: Owns planning, prompt assembly, probabilistic model invocation, retry policies, and domain verification (including linters, test suites, and human review). The agent interacts with PatchDIFF exclusively through standardized Model Context Protocol (MCP) tool invocations over standard input and output (stdio JSON-RPC) or an internal service registry.
2. **Layer 1: MCP Transport and Tool Interface**: Advertises typed JSON tool schemas and discovery examples, validates input arguments against strict structural constraints, and enforces response byte budgets.
3. **Layer 2: Transaction and Read Service Layer**: Coordinates per-target concurrency by acquiring row-level `SELECT ... FOR UPDATE` locks on `cloud_target_files`. It verifies `client_request_id` idempotency, enforces target version and hash guards, applies fresh admission limits, and computes post-commit Levenshtein near-miss diagnostics when an exact match is absent.
4. **Layer 3: Declarative Transaction Decoders and Validators**: Parses and validates typed JSON transaction payloads across `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`, lowering them into a uniform internal representation.
5. **Layer 4: Pure Deterministic Core Applier**: Executes sequential in-memory simulation against canonical LF text. It handles exact match enumeration, disambiguation, Unicode code-point span verification, change-fact derivation, and deterministic replay.
6. **Layer 5: Relational Persistence Substrate (PostgreSQL)**: Serves as the authoritative source of truth, persisting target files in `cloud_target_files`, immutable attempt logs in `append_only_pdcp_logs`, accepted change facts in `append_only_manifest_ledger`, durable snapshots in `target_snapshots`, and editing cycle boundaries in `editing_cycles`.

The core runtime (Layers 3 and 4) is a pure function of the target text, target version, target hash, transaction payload, and runtime profile. It never calls an LLM, never performs network or database I/O, and never mutates state outside memory.

### 6.1 Workspace File Lifecycle and Authority Boundary

In agent-owned Workspace editing workflows, the boundary between the physical filesystem and the relational transaction authority operates across three phases:

1. **Physical Import:** When `patchdiff_initialize_target` is called with workspace import enabled, the service imports physical workspace bytes into PostgreSQL, retaining source line endings and recording the initial file digest in `cloud_target_files`.
2. **Authoritative Relational Working Copy:** During multi-turn editing sessions, PostgreSQL serves as the authoritative working copy. All reads via `patchdiff_read_target`, searches via `patchdiff_find_occurrences`, AST scope observations via `patchdiff_observe_scopes`, and guarded mutations via `patchdiff_submit_edits` and `patchdiff_commit_bundle` operate strictly against locked database rows.
3. **Guarded Workspace Publication:** When editing concludes, `patchdiff_save` writes canonical bytes to disk with workspace synchronization enabled. The service validates target version and hash guards, verifies that the physical file has not experienced external disk drift from its last observed digest, writes the updated content to disk, and commits a checkpoint snapshot. If physical disk installation succeeds but database checkpointing fails, `patchdiff_save` returns a partial status with publication evidence, signaling that the disk reflects the edit while the database checkpoint remains unconfirmed.

---

## 7. Why Validation, Audit Logging, Idempotency, and Replay Share One Transactional Substrate

A natural architectural question is whether PatchDIFF's capabilities could be decomposed into separate, loosely coupled utilities (for example, a stateless local patch validator paired with a filesystem workspace and an external logging sink). PatchDIFF combines validation, state mutation, append-only attempt logging, request idempotence, and replay inside a single PostgreSQL transactional boundary because separating them introduces four classic distributed-state hazards:

1. **Check-then-act races between validation and commit:** If a patch is validated against a file snapshot outside a database row lock, another agent or background process can modify the file before the write completes. Acquiring a row-level `SELECT ... FOR UPDATE` lock on `cloud_target_files` before checking `expected_target_version` and `expected_current_hash` serializes guarded writes per managed target row.
2. **Lost rejection history on ephemeral tool errors:** When a stateless patch tool fails, the rejected payload and exact failure state vanish into transient chat logs. By persisting rejected attempts in `append_only_pdcp_logs` with `parent_pdcp_log_id` lineage, PatchDIFF preserves a complete, queryable record of *why* an edit failed and *how* the agent recovered.
3. **Non-idempotent retries and the ABA problem:** If a stdio or HTTP transport connection drops after the server commits an edit but before the agent receives the response, a naive retry either fails with a version mismatch (leaving the agent unsure whether its edit or another writer's edit won) or, under a hash-only guard after an $A \rightarrow B \rightarrow A$ cycle, re-applies the transaction a second time. Persisting the request key `client_request_id` alongside the terminal response payload inside the same database commit allows the server to return the exact recorded outcome with `deduplicated: true` on retry.
4. **Long-term replay across runtime evolution:** As an editing protocol evolves (such as adding guarded code-point span operations or span adjacency predicates), historical audit logs cannot be re-verified unless every committed transaction records both its protocol version and its immutable runtime profile alongside the initial snapshot in the same durable store.

---

## 8. The PatchDIFF Transaction Protocol Family

PatchDIFF provides four declarative JSON transaction formats that lower into a unified transactional execution pipeline and execute through the deterministic applier:

| Protocol Version | MCP Submission Tool | Execution Profile | Primary Use Case & Operation Types |
| :--- | :--- | :--- | :--- |
| **`patchdiff-tx/1`** (Exact Match) | `patchdiff_submit_edits` | Exact-match profile | Ordered edit list with exact `match` and `replace` strings, plus optional `occurrence_index`, `anchor_before`, and `anchor_after` disambiguators. Recommended primary path for localized code and prose edits. |
| **`patchdiff-tx/2`** (Guarded Operations) | `patchdiff_submit_operations` | Match and span profile (with optional adjacency guards) | Ordered operations mixing exact match and guarded `[start, end)` span operations, including zero-length insertions when `start == end`, with optional `expected_before` and `expected_after` adjacency checks. |
| **`patchdiff-tx/3`** (Whole Replacement) | `patchdiff_submit_replacement` | Whole-target replacement profile | Submitted via MCP argument `replacement` and persisted canonically as a single whole-replacement operation under mandatory version and hash guards, subject to admission limits of 1,000,000 code points and 1,048,576 bytes. |
| **`patchdiff-observed-batch/1`** (Structural Batch) | `patchdiff_commit_bundle` | Structural batch profile `patchdiff-observed-batch-r1` | Atomic bundle committing 1 to 32 disjoint scope groups discovered via AST Waymark coordinates, evaluated per group with descending assembly. |

Because all transaction formats are native typed JSON objects validated by MCP tool schemas, they eliminate the delimiter-line collisions and escaping ambiguities that affect text-delimited patch envelopes: arbitrary code, syntax markers, or symbols inside target text require no escaping beyond standard JSON string serialization.

---

## 9. Separating Asserted Intent from Runtime-Derived Change Facts

When an autonomous agent proposes a document modification, two fundamentally different kinds of metadata exist:
- **Asserted metadata (what the proposer *claims* it is doing):** Why the change is being made, how risky the proposer believes it is, and what logical identifier the proposer assigns to the step.
- **Derived metadata (what the transaction *actually* changes):** Which exact code-point interval $[s_i, e_i)$ was matched, how many characters were removed and inserted, and the cryptographic hashes of the before and after substrings.

If a protocol forces the LLM to compute character counts, byte offsets, or SHA-256 digests in its output, the model wastes output tokens on fragile arithmetic that the server cannot trust anyway. Conversely, if a protocol records only raw patch strings without intent metadata, human reviewers and downstream agents must reverse-engineer the purpose of a 50-edit session by re-reading every diff payload.

PatchDIFF separates these two concerns cleanly:
1. **Minimal asserted metadata on input:** Every transaction requires a non-blank `intent` string describing the purpose of the change. Individual edits may optionally supply a `change_id` (assigned sequentially when omitted), an explanatory `rationale`, and a `risk` classification of low, medium, or high.
2. **Authoritative runtime-derived facts on commit:** As the applier executes each operation, it computes and persists exact change facts in `derived_json` within `append_only_manifest_ledger`:
   - The zero-based code-point span `[span_start, span_end)` in the buffer state immediately preceding the operation,
   - The exact character lengths of matched and replacement text recorded in `matched_chars` and `replacement_chars`,
   - Lowercase hexadecimal SHA-256 digests of the UTF-8 encoded matched and replacement text,
   - The resolved operation type (match, span, or full replacement).

This separation allows `patchdiff_get_manifest_ledger` and `patchdiff_get_pdcp_log` to return compact, trustworthy summaries of an editing session. Queries project bounded intent strings (up to 256 characters) and rationale fields (up to 128 characters) alongside verified span and hash facts, without loading multi-megabyte payload contents into the agent prompt window.

---

## 10. Conceptual Transaction Model and Core Invariants

PatchDIFF models document editing as a deterministic state machine operating over canonical text. Rather than treating an edit as an imperative disk write, the system evaluates declarative proposals against explicit preconditions, simulating changes in memory before committing.

> [!NOTE] Formal Mathematical Treatment
> For the complete algebraic formalization, including metric spaces over Unicode scalar sequences, operational transition functions, and formal proofs of all theorems, see the companion paper: [Formal Transaction Model and System Invariants](formal-transaction-model.md).

### 10.1 Authoritative Document State

An authoritative target document at rest within PostgreSQL is defined by three elements:
1. **Canonical content ($T_0$)**: An LF-normalized Unicode scalar string.
2. **Version counter ($v_0$)**: A strictly monotonic non-negative integer, initialized to 0 upon target creation.
3. **Content digest ($h_0$)**: The SHA-256 cryptographic hash of the UTF-8 encoded canonical content.

Every transaction submission must declare an explicit state precondition: an expected target version, an expected content hash, or both. Before any edit operation is evaluated, the service verifies these preconditions under a per-target row lock using `SELECT ... FOR UPDATE`. If the target has advanced or diverged, the transaction fails closed immediately with zero document mutation.

### 10.2 Sequential In-Memory Simulation

When preconditions are satisfied, the deterministic core applier initializes an in-memory buffer sequence:
$$T_0 \xrightarrow{o_1} T_1 \xrightarrow{o_2} \dots \xrightarrow{o_k} T_k$$

Edits within a transaction execute strictly sequentially in array order against the evolving buffer. If an edit targets a repeated string, disambiguation occurs deterministically:
- **Global occurrence index**: Selects the exact occurrence from the original unedited candidate list.
- **Contextual anchors**: Evaluates prefix `anchor_before` and suffix `anchor_after` constraints anywhere in the document outside the candidate span, avoiding the brittle requirement of immediate adjacency.

When operations specify explicit code-point spans under `patchdiff-tx/2`, the applier requires an exact match on `expected_text` before replacing the span. If any operation fails, the entire transaction aborts without mutating the database row or filesystem.

### 10.3 Core System Invariants

Four formal invariants govern every PatchDIFF transaction:

1. **Invariant 1: Localized Unmatched-Content Preservation**
   For all localized operations under `patchdiff-tx/1` exact match and `patchdiff-tx/2` guarded span, all code points outside the resolved target spans are guaranteed to remain invariant. Unlike whole-file rewrites, localized transactions make it impossible for unmentioned paragraphs, functions, or comments to undergo silent model drift.

2. **Invariant 2: All-or-Nothing Per-Target Atomicity**
   A multi-edit transaction succeeds completely or not at all. If the fifth edit in a five-edit batch fails (for example, due to a missing match or out-of-bounds offset), the preceding four in-memory edits are discarded, the document remains at its original version and hash, and a detailed diagnostic payload is returned.

3. **Invariant 3: Deterministic Replay Equivalence**
   Given an initial snapshot and an ordered sequence of accepted audit records, replaying transactions under each record's immutable execution profile deterministically reconstructs the exact committed document, version counter, and SHA-256 hash. Replay verifies that historical logs remain authoritative over time without depending on external parser versions.

4. **Invariant 4: Request-Key Idempotency**
   Every submission may carry a unique `client_request_id`. If a transport disconnect occurs after a commit and the client resends the payload, the server detects the recorded request key and returns the identical accepted outcome with `deduplicated: true`, preventing accidental duplicate applications.

---

## 11. Canonicalization, Unicode Semantics, and Source Line-Ending Preservation

Cross-platform editing fails silently when tools disagree on line endings (CRLF versus LF), character indexing (UTF-8 bytes versus UTF-16 code units versus Unicode scalar values), or invalid Unicode sequences. PatchDIFF enforces three rules:

| Boundary | Canonical Rule |
| :--- | :--- |
| **Canonical storage and matching** | All target documents, `match` and `replace` strings, `expected_text`, and anchors are canonicalized to LF before hashing into `current_hash` or matching. |
| **Unicode scalar indexing** | All offset coordinates (`start`, `end`, `span_start`, `span_end`, and `length`) are zero-based Unicode code-point indices over the LF-canonical string, matching Python `str` indexing. |
| **UTF-8 & PostgreSQL text safety** | Strings containing UTF-16 surrogates (code points U+D800 through U+DFFF) or NUL bytes (code point U+0000) are rejected during protocol validation with failure reason `target_encoding_invalid`. Known-target invalid-text attempts are durably logged using reversible ASCII-escaped evidence under schema `patchdiff-invalid-input/1` without corrupting PostgreSQL text or JSONB columns. |
| **Source line-ending preservation** | Upload records `source_line_endings` with lowercase `style` in `{"lf", "crlf", "cr", "mixed", "none"}` and raw upload digest `source_sha256`. While canonical storage and `current_hash` always use LF, `patchdiff_export_target` supports `format = "original_text" | "canonical_lf" | "crlf" | "original_eol"` so uniform original line endings can be restored on export. |
| **Advisory grapheme-split warning** | If a matched or span boundary splits a multi-code-point Unicode extended grapheme cluster (UAX #29, such as an emoji ZWJ sequence or base character + combining mark), the applier emits an advisory `grapheme_boundary_split` warning on acceptance without rejecting the edit. |

---

## 12. Exact Matching, Overlapping Occurrences, and Disambiguation

A subtle defect in many string-replacement tools is how they count occurrences when a pattern overlaps itself. Consider the target string $T = \texttt{"ababa"}$ and pattern $m = \texttt{"aba"}$.
- A naive non-overlapping scanner that advances by pattern length finds only index 0 and falsely concludes that `"aba"` is unique in `"ababa"`.
- In fact, `"aba"` occurs at two exact spans: $[0, 3)$ and $[2, 5)$.

PatchDIFF's matcher enumerates **all** exact occurrences by advancing the search start by one code point after each match:
- In `"ababa"`, searching for `"aba"` finds two occurrences ($[0, 3)$ and $[2, 5)$) and rejects an un-disambiguated `patchdiff-tx/1` edit with `match_ambiguous` where `match_count = 2`, returning both spans in `diagnostic.exact_candidates`.
- Furthermore, under the singleton selector rule `enforce_singleton_selectors`, if a pattern occurs only once in $T_{i-1}$ with `match_count = 1`, the runtime still validates any supplied `occurrence_index`, `anchor_before`, or `anchor_after`. A stale selector, such as specifying `occurrence_index: 2` when only one occurrence remains, is caught and rejected as `disambiguation_invalid` rather than silently ignored.

---

## 13. Sequential In-Memory Application and Coordinate Semantics

Within a multi-operation transaction across `patchdiff-tx/1` or `patchdiff-tx/2`, operations execute **sequentially in array order** against the evolving in-memory buffer:
$$T_0 \xrightarrow{o_1} T_1 \xrightarrow{o_2} T_2 \xrightarrow{\dots} T_k.$$

This sequential model has two important consequences that host integrations must respect:
1. **Later operations observe earlier replacements:** If $o_1$ changes `"version = 1"` to `"version = 2"`, or shifts character offsets in $T_1$, operation $o_2$ is evaluated against $T_1$, not $T_0$.
   - If $o_1$ and $o_2$ target the same repeated string and $o_1$ replaces occurrence 1, then in $T_1$ the remaining occurrence is now occurrence 1, not 2. When an accepted transaction's later `occurrence_index` selects a span whose index shifted due to an earlier edit in the same transaction, the runtime records an advisory `occurrence_index_basis_shift` warning so the host can inspect it.
   - When submitting multiple `tx/2` code-point span edits in a single transaction where each span changes the length of the document ($|r_i| \neq e_i - s_i$), submitting spans in **descending offset order** (from the bottom of the file toward the top) keeps earlier code-point offsets invariant.
2. **Intermediate-buffer rejection coordinates:** If operations $o_1, \dots, o_{i-1}$ succeed in memory and operation $o_i$ ($i > 1$) fails, no changes are committed to PostgreSQL ($\mathcal{S}' = \mathcal{S}$). However, `diagnostic.failure_context`, `exact_candidates`, and `near_misses` for the failing operation $o_i$ are computed against the **intermediate in-memory buffer $T_{i-1}$** with `buffer_stage = "intermediate_buffer"` and `prior_changes = i - 1`, whereas `current_context` reflects the committed target $T_0$.

---

## 14. Operational Primitives: Replacement, Insertion, Deletion, and Guarded Rewrite

All common document editing actions map cleanly onto `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`:

- **Modification (in-place replacement):** Replace matched text directly using `match` and `replace` under `patchdiff-tx/1` or `patchdiff-tx/2`, or provide `[start, end)` with `expected_text` and `replace` using span operations in `patchdiff-tx/2`.
- **Deletion:** Set `replace: ""` on a non-empty match under `patchdiff-tx/1` or a non-empty code-point span under `patchdiff-tx/2`.
- **Insertion:**
  - In `patchdiff-tx/1`, `match` must be non-empty. An empty match string is rejected by schema validation or during protocol validation with code `block_malformed`. Insertion is therefore expressed by matching an adjacent anchor substring and including that anchor alongside the new content in `replace`.
  - In `patchdiff-tx/2`, zero-length insertion is expressed directly without duplicating anchor text into `replace`: configure `op: "span"` with `start == end` and `expected_text: ""`, with optional adjacency guards via `expected_before` and `expected_after`.
- **Whole-Document Replacement:** Submit a full replacement payload through `patchdiff_submit_replacement` under `patchdiff-tx/3` with mandatory version or hash preconditions.

---

## 15. Stage-Aware Validity and Failure Taxonomy

A central flaw in naive patch tools is collapsing all failures into an unstructured error string, or conversely treating a syntactically applied patch as proof that the user's task succeeded. PatchDIFF tracks the exact `ValidationStage` reached by each submission in the execution path and reports a four-part `validity` object on every response:

1. `precondition_guard`: Target lookup, UUID and lineage validation, pre-parse version and hash guards, and request-key verification.
2. `protocol_validation`: Structural schema decoding, UTF-8 and NUL text safety checks, non-empty match validation, and selector syntax verification.
3. `transaction_applicability`: Sequential in-memory simulation against intermediate buffers, evaluating exact match resolution, span boundary bounds, expected text verification, and optional adjacency predicates.
4. `commit_guard`: Post-simulation target version and hash verification under the held row lock prior to database commit.
5. `accepted`: Atomic database commit, durable attempt and manifest ledger recording, and generation of non-blocking advisory warnings.

Every response returns a structured four-part validity object reflecting the outcome at these stages:

| Validity Dimension | `precondition_guard` Rejection | `protocol_validation` Rejection | `transaction_applicability` Rejection | `commit_guard` Rejection | `accepted` | Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `protocol_valid` | `null` | `false` | `true` | `true` | `true` | Did the transaction satisfy structural and protocol validation (null if rejected before protocol evaluation)? |
| `transaction_valid` | `null` | `null` | `false` | `true` | `true` | Did sequential in-memory simulation succeed against the evaluated buffer (null if not reached)? |
| `task_correct` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | Did the edit fulfill the user's high-level instruction? *(Host-evaluated)* |
| `semantic` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | `"not_evaluated"` | Does the resulting code/document compile, pass tests, or preserve domain meaning? *(Host-evaluated)* |

Always returning `"not_evaluated"` for `task_correct` and `semantic` enforces a vital epistemic boundary: **PatchDIFF certifies that the state transition was authorized, exact, and atomic, never that the resulting code passes unit tests or satisfies domain logic.**

---

## 16. Host-Owned Recovery Loop and Bounded Rejection Diagnostics

Instead of embedding a hidden LLM inside the database server to silently rewrite failed patches, PatchDIFF keeps the retry loop in the **MCP host** and equips rejection responses with bounded, deterministic recovery evidence (without guaranteeing that additional read/search calls or retries will always succeed):

1. **Committed state coordinates:** Rejections for known targets return the committed `current_version` and `current_hash` at the top level, allowing the host to update its context immediately.
2. **Bounded failure window:** Diagnostics provide up to 256 Unicode code points around the failure location via `failure_context` and `current_context` (capped at 4,096 bytes each, and 8,192 bytes combined). When the committed buffer matches the intermediate simulation state, redundant context is omitted.
3. **Ambiguity candidates:** When an exact match is ambiguous or disambiguation fails, `exact_candidates` returns up to five exact occurrences (capped at 8,192 bytes). Each candidate includes its occurrence index, offsets, a match preview up to 64 code points, and 20-code-point side contexts.
4. **Post-commit near-miss suggestions:** When an exact match is absent, the server releases the row lock and scans an in-memory copy of the failing buffer (up to 65,536 code points) for patterns between 1 and 64 code points. Using an exact positional pigeonhole prefilter and an Ukkonen-banded Landau-Vishkin edit-distance algorithm under a 1,000,000-cell cap, the response returns up to three non-overlapping near-miss candidates ordered by distance, each with surrounding context. Near-miss calculation is skipped if an earlier edit in the same batch consumed the pattern, or if the transaction executed inside a caller-owned outer transaction.
5. **Advisory dry-run preview:** The `patchdiff_preview` tool allows hosts to simulate transactions against read-only target observations under a 32 KB response budget without acquiring row locks, writing audit logs, or advancing target versions.

---

## 17. Structural Safety and the Non-Executable Boundary

PatchDIFF treats every transaction submission as untrusted declarative data rather than executable code. The system enforces strict boundaries between three distinct roles:

- **Untrusted Transaction Payloads:** Pure declarative data structures across `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3` specifying matches, offsets, and replacement text without executable logic.
- **Trusted Transaction Server and Pure Core Applier**: Deterministic software components responsible for validating preconditions, executing exact string operations, and managing relational persistence.
- **Authoritative Target Document**: The static target file at rest, whether formatted as Python, YAML, JSON, Markdown, or plain prose.

The operational boundaries include:
- **No `eval`, shell, regex, or AST execution:** The runtime performs only deterministic Unicode string slicing, exact substring search, SHA-256 hashing, and parameterized SQL queries via SQLAlchemy.
- **Typed JSON validation vs. prose freedom:** In `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`, proposals arrive as structured JSON objects validated against strict schemas that reject additional properties, enforce type bounds, and ensure UTF-8 text safety. Because JSON keys and string values are structurally separated, `intent` and `rationale` strings in typed transactions may freely mention code symbols like `import`, `def`, `class`, SQL keywords, or diff markers without triggering false-positive rejections.

---

## 18. Locality Controls: Runtime-Enforced Bounds vs. Host Policies

Structural observation provides an explicit locality contract for agent edits. Read-only Waymark discovery identifies code structures, after which PatchDIFF issues observations over a locked PostgreSQL snapshot. A bundle selects 1 to 32 disjoint scopes from a single target document. Each operation group executes sequentially against its original scope-local buffer through the exact deterministic applier, followed by descending assembly and a single guarded per-target commit. This model guarantees strict boundary isolation without requiring full AST code generation or cross-target distributed transactions. Strict observed admission rechecks issued identity, editing cycle, version and hash guards, original scope bounds, and unused state under the target row lock. Accepted durable batches use `patchdiff-observed-batch/1` under the `patchdiff-observed-batch-r1` profile, and deterministic replay validates every recorded scope independently of the AST parser. See [the batch contract](../spec/structural-batch-editing.md).

To prevent unintended wide-area rewrites while still supporting legitimate whole-file updates, it is important to distinguish **controls enforced directly by the PatchDIFF runtime** from **optional policies that an MCP host or enterprise harness may layer on top**:

| Control Mechanism | Enforced by PatchDIFF Runtime? | Actual Runtime / Host Behavior |
| :--- | :--- | :--- |
| **Non-empty `match` in exact-match operations** | **Yes (Runtime-enforced)** | Empty match strings are rejected at schema validation or protocol validation. |
| **Separation of localized edits from whole-target replacement** | **Yes (Runtime-enforced)** | Full replacement operations are forbidden in localized transaction types; whole-document replacement requires calling `patchdiff_submit_replacement`. |
| **Fresh admission size cap on whole-target replacement** | **Yes (Service-enforced on fresh submissions)** | Fresh whole-replacement submissions exceeding 1,000,000 Unicode code points or 1,048,576 bytes return an error before entering the applier; replay never re-applies fresh admission caps. |
| **Runtime-derived character lengths per edit** | **Yes (Runtime-computed)** | Computed and returned in change evidence and stored in `append_only_manifest_ledger.derived_json`. |
| **Advisory warnings (such as no-op edits or grapheme splits)** | **Yes (Runtime-computed, non-blocking)** | Returned on accepted transactions and persisted in diagnostics; never convert an accepted edit into a rejection. |
| **Heuristic replacement-ratio limits or human approval gates** | **No (Host-owned policy)** | The runtime does not reject edits based on replacement ratios or asserted high risk. Hosts can inspect previews or change evidence to enforce custom approval policies. |

---

## 19. Persistence Architecture, Audit Logs, and Deterministic Replay

The principal persistence entities include:

1. **`cloud_target_files`**: Canonical `current_content` (LF-normalized), `current_hash` (SHA-256), integer `version` counter starting at 0, and `source_line_endings`.
2. **`append_only_pdcp_logs`**: Immutable admitted accepted/rejected attempts, ordered by `log_sequence`, recording protocol/runtime, original transaction content and `pdcp_content_hash`, `before_version`/`after_version`, `before_hash`/`after_hash`, failure diagnostics, retry parent and request key/fingerprint. Submitted guards are retained in applicable canonical transaction records, not separate expected-version/hash columns. Pre-admission MCP argument errors do not create an attempt row.
3. **`append_only_manifest_ledger`**: Immutable ledger of **accepted** changes only, ordered by `ledger_sequence`, recording `origin`, `editing_cycle_id`, `change_id`, `intent`, `risk`, and derived facts including code-point spans, character counts, and SHA-256 digests.
4. **`target_snapshots`**: Immutable snapshots for initial uploads and save checkpoints, storing full canonical content, hash, and version.
5. **`editing_cycles`**: Active/closed cycles, identified by `cycle_index`, with `closed_at` and `save_snapshot_id` on closure.
6. **`target_scope_observations`**: Server-issued target/cycle/snapshot/scope evidence, including bundle identity/order and accepted-log linkage. Observations are consumed on acceptance; their authoritative facts are retained in accepted history.

### 19.1 Versioned Execution Profiles and 4-Component Replay Verification

Every accepted row in `append_only_pdcp_logs` records both its `protocol_version` and an immutable `runtime_version` profile capturing the exact semantic rule flags active when the transaction was committed, such as `overlap_aware_matching`, `enforce_singleton_selectors`, `allow_span_operations`, `allow_replace_all_operations`, and `allow_span_adjacency_guards`.

When `patchdiff_replay(target_file_id)` is invoked, the replay engine loads the `initial_upload` snapshot, replays every accepted log entry in `log_sequence` order by dispatching on `(protocol_version, runtime_version)`, and verifies four independent `materialized_state_checks` against `cloud_target_files`:
1. `content_matches`: Replayed canonical LF text exactly matches `cloud_target_files.current_content`. Raw text comparison under this check detects out-of-band CRLF or bare-CR byte corruption even when canonical LF hashes would agree.
2. `stored_hash_matches`: Replayed SHA-256 equals `cloud_target_files.current_hash`.
3. `recomputed_hash_matches`: `SHA256(canonical(cloud_target_files.current_content))` equals `cloud_target_files.current_hash` (verifying persisted hash integrity).
4. `version_matches`: Replayed version equals `cloud_target_files.version`.

---

## 20. Concurrency Model: Serialized Per-Target Commits Under Optimistic Guards

Multiple MCP hosts, background workers, or subagents may connect to the same PatchDIFF server and read or target the same document concurrently:

- **Per-target serialization under `SELECT ... FOR UPDATE`:** Every write submission across `patchdiff_submit_edits`, `patchdiff_submit_operations`, and `patchdiff_submit_replacement`, as well as `patchdiff_save`, acquires a PostgreSQL row-level lock using `SELECT ... FOR UPDATE` on the `cloud_target_files` row before checking `client_request_id` idempotency or evaluating version and hash guards.
- **Optimistic concurrency rejection on conflict:** If two agents read version 4 concurrently and submit edits carrying `expected_target_version: 4`, the first transaction to acquire the row lock commits and advances the target to version 5. The second transaction then acquires the lock, observes that the target version has advanced, logs a deterministic `target_version_mismatch` rejection returning `current_version: 5` and bounded `current_context`, and leaves version 5 intact.
- **Single-target atomicity scope:** Atomicity is strictly **per `target_file_id`**. PatchDIFF does not provide multi-file distributed transactions across different `target_file_id` rows; hosts editing multiple files coordinate multi-file workflows at the host layer.

---

## 21. MCP Tool Surface and Operational Profiles

PatchDIFF structures its Model Context Protocol (MCP) tool exposure around three core operational profiles, corresponding directly to the experimental arms of empirical verification:

1. **Observed Workspace Profile (`observed_workspace`):** The primary 7-tool structural editing profile enabling autonomous agents to manage the complete file lifecycle from physical import to disk publication:
   - `patchdiff_initialize_target`: Imports a workspace file into the PostgreSQL working copy.
   - `patchdiff_read_target`: Bounded Unicode code-point slice reads.
   - `patchdiff_find_occurrences`: Exact substring search with surrounding context.
   - `patchdiff_list_scopes`: Structural symbol candidate discovery via AST Waymark coordinates.
   - `patchdiff_observe_scopes`: Observes 1 to 32 disjoint scopes on a locked snapshot.
   - `patchdiff_commit_bundle`: Atomically commits ordered operations across scope groups.
   - `patchdiff_save`: Publishes canonical content to disk with drift detection and checkpoints the cycle.

2. **Workspace Profile (`workspace`):** The 5-tool exact text editing profile for autonomous agents operating without AST structural parsing:
   - `patchdiff_initialize_target`: Imports a workspace file into the PostgreSQL working copy.
   - `patchdiff_read_target`: Bounded Unicode code-point slice reads.
   - `patchdiff_find_occurrences`: Exact substring search with surrounding context.
   - `patchdiff_submit_edits`: Submits ordered exact-match transactions under protocol `patchdiff-tx/1`.
   - `patchdiff_save`: Publishes canonical content to disk with drift detection and checkpoints the cycle.

3. **Observed Editor Profile (`observed_v2`):** The 5-tool structural editing profile designed for host-managed lifecycle environments, where the host harness manages pre-edit setup and post-edit publication out-of-band:
   - `patchdiff_read_target`: Bounded Unicode code-point slice reads.
   - `patchdiff_find_occurrences`: Exact substring search with surrounding context.
   - `patchdiff_list_scopes`: Structural symbol candidate discovery via AST Waymark coordinates.
   - `patchdiff_observe_scopes`: Observes 1 to 32 disjoint scopes on a locked snapshot.
   - `patchdiff_commit_bundle`: Atomically commits ordered operations across scope groups.

Each profile enforces identical advertisement and dispatch filtering: tools outside the active profile are neither exposed during discovery nor callable over the transport.

---

## 22. Save Compaction, Physical Publication, and Context Hygiene

During an extended editing session (for example, 40 sequential edits to a specification or module), two distinct histories grow:
1. The **server-side manifest ledger** in `append_only_manifest_ledger`, and
2. The **host's LLM conversation history** (past tool calls, responses, and reasoning turns).

### 22.1 Cycle Checkpointing and Publication Semantics

`patchdiff_save` provides an explicit **cycle boundary** in the persistence substrate and, in workspace mode, publishes edited bytes to disk:

1. **State Guards & Lock Acquisition:** Under `SELECT ... FOR UPDATE`, `patchdiff_save` verifies target version and hash guards for `expected_target_version` and `expected_current_hash`.
2. **Physical Workspace Synchronization:** When workspace synchronization is enabled,
   - The service reads the current bytes on disk and verifies that the physical file has not experienced external disk drift from its last recorded digest.
   - If drift is detected, `patchdiff_save` aborts without writing to disk or advancing the cycle, returning a rejection error.
   - If the disk digest matches, the canonical LF content is formatted using the target's recorded `source_line_endings` and written to disk.
3. **Database Checkpoint Snapshot:** An immutable `save_checkpoint` row is recorded in `target_snapshots` capturing the committed content, hash, and version.
4. **Cycle Rotation:** The current editing cycle is closed with its timestamp and snapshot reference, and a new active cycle is opened with an incremented cycle index.
5. **Partial SAVE Handling:** If the physical disk write succeeds but the subsequent database transaction fails to commit, `patchdiff_save` returns `status: "partial"` accompanied by physical publication details and an unconfirmed database checkpoint receipt.
6. **Active-Cycle Ledger Reset:** Because `patchdiff_get_manifest_ledger` defaults to excluding previous cycles, querying the ledger immediately after `patchdiff_save` returns an empty entry list for the new cycle. Setting `include_previous_cycles = True` continues to expose all prior cycles, and `patchdiff_replay` still verifies complete history from the initial upload snapshot.

**Scope boundary:** `patchdiff_save` rotates the server-side active cycle view and records a durable checkpoint snapshot; it does **not** automatically summarize or truncate the host's in-memory LLM chat transcript. Instead, hosts use `patchdiff_save` as a safe synchronization point at which the host can discard prior edit-turn messages from its prompt window and retain only the new `current_version` / `current_hash` and active slices read via `patchdiff_read_target`.

---

## 23. Operational Efficiency, Reference Measurements, and Research Hypotheses (H1 to H7)

All quantitative and comparative claims in this paper follow a four-tier classification:
1. **Enforced Contract / Hard Cap:** Deterministic byte, code-point, or row-count bounds enforced in software.
2. **Measured (PatchDIFF-only):** Deterministic byte counts from `backend/tests/verification/offline_eval.py` and local reference workload medians.
3. **Analytical Comparison:** Structural complexity and round-trip comparisons under stated workflow assumptions.
4. **Empirical Evidence / Open Hypotheses:** The [Workspace benchmark](../benchmarks/workspace-e2e-benchmark.md) is the current empirical comparison of Native, host-orchestrated structural editing, and agent-owned Workspace editing across 18 verified trials. Multi-agent contention, long-horizon sessions, and human-review outcomes remain open empirical investigations.

### 23.1 Deterministic Payload Byte Scaling & Reference Runtime Characteristics (Measured)

Reproducible via `PYTHONPATH=backend python backend/tests/verification/offline_eval.py`:

| Scenario (offline evaluation benchmark) | Raw Replacement | Minimal tx/1 Arguments / Persisted Record | Rationale-Annotated tx/1 Arguments / Persisted Record | tx/3 Whole-Target Rewrite Arguments / Persisted Record / Line |
| :--- | :--- | :--- | :--- | :--- |
| **1 tiny edit ("old" -> "new")** | 3 bytes | **151 B** / 206 B | 327 B / 382 B | **232 B** / 290 B / 341 B |
| **5 small edits in 1 transaction (5 x 1 byte)** | 5 bytes | **259 B** / 314 B | 1,139 B / 1,194 B | N/A |
| **1 edit, 2 KB span (2,053 bytes match/replace)** | 2,053 bytes | **4,441 B** / 4,496 B | 4,617 B / 4,672 B | **2,377 B** / 2,435 B / 2,486 B |
| **Quotes + backslashes + Unicode** | 16 bytes | **172 B** / 227 B | 348 B / 403 B | **250 B** / 308 B / 359 B |
| **Payload containing delimiter-like syntax line** | 14 bytes | **162 B** / 217 B | 338 B / 393 B | N/A |

- **Marginal wire cost per additional edit:** Each additional minimal edit item in a `patchdiff-tx/1` transaction adds exactly 26 bytes of JSON structure (25 bytes of object keys and punctuation plus a 1-byte comma) plus the JSON-escaped UTF-8 lengths of `match` and `replace` (28 bytes total for two 1-byte ASCII strings).
- **Hard context-protection caps (Enforced Contract):**
  - Target reads via `patchdiff_read_target` and `patchdiff_read_lines`: 4,000 code points default, 8,000 code points maximum per page.
  - Occurrence search via `patchdiff_find_occurrences`: 40 code points side context default (400 maximum), returning up to 200 results.
  - Rejection context via `failure_context` and `current_context`: Up to 256 code points (at most 4,096 bytes each, and 8,192 bytes combined).
  - Ambiguity and near-miss enrichment: Up to 5 exact candidates and up to 3 near misses (at most 8,192 bytes each, within an 18,432-byte ceiling).
  - Advisory preview via `patchdiff_preview`: 32 KB total budget (16 KB facts and 16 KB diagnostics).
  - History and ledger pagination: 50 rows default, 200 maximum per page; ledger queries project bounded intent (up to 256 characters) and rationale (up to 128 characters), while history queries enforce a 1 MiB cumulative content budget per page.
  - MCP tool discovery: At most 64 KB total across all registered tool schemas.
- **Reference implementation latency characteristics (Measured single-machine medians):**
  - **Post-commit near-miss scan:** On 65,536-code-point buffers with needle length 45 and threshold 4, scanning a varied prose buffer takes 1.7 ms, while a dense repetitive log buffer takes 41.9 ms under the 1,000,000-cell cap.
  - **Bounded SQL history and ledger reads:** Using PostgreSQL 16+ JSON validation and lateral projections, reading 50 rows over a 20 MB history takes 14.68 ms for ledger entries and 22.85 ms for attempt logs on whole-target replacements; on exact-match transactions, reading 50 rows takes 136.72 ms for attempt logs and 221.59 ms for ledger entries.

### 23.2 Status of the Seven Core Research Hypotheses (H1 to H7)

The table below states each of PatchDIFF's seven core research hypotheses (H1 to H7) and distinguishes what is **established in software and offline measurements**, what has been **empirically validated on live models**, and what remains an **open empirical investigation**:

| Research Hypothesis | Established Today (Deterministic Runtime & Offline Measurements) | Empirical Status & Evaluation Protocol |
| :--- | :--- | :--- |
| **H1: PatchDIFF reduces full-document decoding cost** | **Deterministic payload byte accounting:** Localized `patchdiff-tx/1` payloads scale with edit magnitude $O(|\Delta|)$ rather than document size $|T|$ (151 bytes for 1 minimal edit, 259 bytes for 5 edits, and 28 bytes per additional 1-byte edit). | The [current 18-trial benchmark](../benchmarks/workspace-e2e-benchmark.md) measures cumulative exported token fields and editor activity on one task. Workspace used 42.7% fewer editor calls and a 16.2% lower timed interval than Native. These observations support workflow efficiency on that workload. They do not isolate decoding cost or unique context growth. |
| **H2: PatchDIFF reduces unintended mutation** | **Deterministic locality for localized operations (Invariant 1):** For every accepted transaction in `patchdiff-tx/1` and `tx/2`, code points outside the resolved spans are provably invariant. If an agent selects an over-broad match, text within that span can change, but unintended whole-file rewrites cannot occur via localized primitives. | **End-to-end agent edit-fidelity study (open):** Measure how often live models select an unintended span or over-broad match string compared to silent drift in full-file rewrites or misapplied fuzzy diffs. |
| **H3: PatchDIFF improves stale-context detection** | **Enforced optimistic concurrency guards:** Typed submission tools require `expected_target_version` and/or `expected_current_hash` evaluated under `SELECT ... FOR UPDATE`, while observed bundles strictly require both guards. Any version or hash divergence deterministically rejects with `target_version_mismatch`, `target_hash_mismatch`, or `target_diverged` with zero target mutation. | **Multi-agent contention and recovery study (open):** Measure conflict recovery success rates and wasted turns when multiple live agents concurrently edit shared documents under optimistic locking. |
| **H4: PatchDIFF supports multi-edit cached-document workflows** | **Multi-edit batching, cycle checkpoints, and bounded SQL history:** Localized primitives execute ordered multi-edit batches atomically in memory; `patchdiff_save` rotates active editing cycles, immediately resetting the active-cycle manifest ledger to empty while retaining prior cycles on request; SQL lateral projections bound 50-row history reads over 20 MB logs to 14.68 to 221.59 ms. | **Long-horizon session study (open):** Measure cumulative prompt token growth and task completion over 20 to 100 sequential edits with periodic `patchdiff_save` compaction compared to uncompacted agent loops. |
| **H5: PatchDIFF preserves deterministic replay** | **Verified by implementation tests across supported execution profiles:** `patchdiff_replay` reconstructs canonical state from the initial snapshot plus ordered accepted logs, verifying all four materialized state checks for content, stored hash, recomputed hash, and version matches, including detection of out-of-band line-ending corruption. | **Supported replay behavior verified in the reference implementation test suite.** *(Cross-implementation conformance and longitudinal archive benchmarks remain future work.)* |
| **H6: PatchDIFF improves reviewability** | **Separation of asserted intent from derived facts:** `append_only_manifest_ledger` stores model-claimed intent and rationale alongside runtime-computed change facts (span bounds, character counts, and SHA-256 digests), and `patchdiff_preview` exposes those exact facts prior to commit. | **Human reviewer and auditing study (open):** Measure human review time and defect-detection accuracy when inspecting PatchDIFF manifest ledgers and derived span facts compared to raw unified diffs or full-file rewrites. |
| **H7: LLMs can reliably generate valid PatchDIFF transactions** | **JSON-native schema and delimiter-collision elimination:** Transaction formats and observed bundles use standard JSON tool arguments advertised with executable discovery examples (under 8,192 bytes), eliminating text-envelope collisions and escaping ambiguities. | In the [current benchmark](../benchmarks/workspace-e2e-benchmark.md), all 60 guarded commits across the 12 PatchDIFF trials were accepted and independently reconstructed. Both PatchDIFF arms produced 60/60 exact files and passed 240/240 behavior checks. Including Native, all 18 trials passed 90 file comparisons and 360 checks. The requested Gemini setting is operator-attested, with provider identity and exact host build unavailable. |

### 23.3 Experimental Design for Live-Model & Human Benchmarks (H1 to H4, H6, H7)

To evaluate the open empirical hypotheses (H1 to H4, H6, H7) rigorously without conflating Edit Format with Host Harness policy, future live-model trials should hold the model, temperature (set to 0.0), target corpus (files ranging from 4 KB to 256 KB across Python, TypeScript, Markdown, JSON, and YAML), and read budget constant while comparing four conditions:
1. **Condition A:** Full-document rewrite using `write_file`.
2. **Condition B:** Unique substring replacement using `str_replace`.
3. **Condition C:** Unified diff using `apply_patch`.
4. **Condition D:** PatchDIFF exact-match and guarded operations with bounded diagnostic feedback on rejection.

Primary dependent variables: (a) first-attempt `protocol_valid` and `transaction_valid` rates (H7), (b) post-rejection recovery rate within 2 retries and total tool round trips (H7), (c) total input and output tokens billed (H1 and H4), (d) unintended out-of-span character mutations (H2), (e) stale-write prevention under injected concurrent modifications (H3), and (f) human review time and error-identification accuracy (H6).

---

## 24. Verification Methodology: Unit, Relational, and Transport Conformance

Because PatchDIFF acts as an authoritative transaction monitor, its deterministic guarantees must be verified across three distinct testing layers:

| Verification Category | Required Invariant Coverage |
| :--- | :--- |
| **Canonicalization & Unicode safety** | CRLF/CR $\rightarrow$ LF normalization; rejection of UTF-16 surrogates and NUL bytes with code `target_encoding_invalid` and reversible ASCII-escaped audit evidence; preservation of lowercase line-ending styles (LF, CRLF, CR, mixed, or none) on export across original, canonical, and exported text representations. |
| **Exact & overlapping match enumeration** | Single match succeeds; zero matches reject with `match_absent`; duplicate matches reject with `match_ambiguous` unless uniquely resolved by global `occurrence_index` selection followed by non-adjacent `anchor_before` and `anchor_after` filtering; overlapping occurrences such as `"aba"` in `"ababa"` are enumerated accurately; invalid singleton selectors reject with `disambiguation_invalid`. |
| **Guarded span and replacement semantics** | Exact `expected_text` verification on `[start, end)` spans under `patchdiff-tx/2`; zero-length insertions when start equals end with empty expected text; immediate-adjacency checks rejecting mismatched boundaries with `span_expected_text_mismatch`; whole-document replacements under `patchdiff-tx/3` subject to admission limits of 1,000,000 code points and 1,048,576 bytes. |
| **Sequential simulation & atomicity** | Multi-operation transactions evaluate against intermediate in-memory buffers $T_{i-1}$; failure at operation $i > 1$, including `sequential_match_invalid` when an earlier operation consumed the match, leaves PostgreSQL target state completely unchanged and labels diagnostics with `buffer_stage = "intermediate_buffer"` and `prior_changes = i - 1`. |
| **Bounded diagnostics & preview** | Diagnostic context fields `failure_context` and `current_context` capped at 256 code points (at most 4,096 bytes each); exact candidates (up to 5) and post-commit near misses (up to 3) capped at 8,192 bytes each within an 18,432-byte combined ceiling; dry-run preview via `patchdiff_preview` capped at 32 KB with zero database locks or writes. |
| **Concurrency, idempotency & lineage** | Per-target `SELECT ... FOR UPDATE` row locking; stale version or hash rejection; idempotent recovery returning `deduplicated: true` on matching request keys, while payload-mismatch conflicts reject with code `request_key_conflict`; retry lineage tracking via `parent_pdcp_log_id`. |
| **Checkpointing, profile replay & stdio transport** | Tested schema migration upgrade, downgrade, and upgrade conformance (with downgrade safety guards that refuse destructive data loss when newer feature rows exist); `patchdiff_save` snapshot creation and cycle rotation; 4-component replay verification across execution profiles; end-to-end JSON-RPC execution over standard I/O subprocess pipes. |

---

## 25. End-to-End Transactional Walkthrough

Consider a target configuration document `config.yaml` initialized at `current_version = 0` and content hash `8f4a...`. The document defines two services: an `auth-api` service and a `background-sync` worker, each configured with `timeout_ms: 1000` and `retry: false`.

1. **Bounded Read and Occurrence Discovery**:
   The agent calls `patchdiff_find_occurrences(target_file_id, text="retry: false")`. PatchDIFF returns `occurrence_count: 2`, reporting occurrence 1 at code-point offset `[47, 59)` under `auth-api` and occurrence 2 at offset `[113, 125)` under `worker`, together with `current_version: 0`.

2. **Guarded Multi-Edit Submission under `patchdiff-tx/1`:**
   To increase the `auth-api` timeout to 2,500 ms and enable retries only on the worker, the agent submits a single atomic transaction carrying `expected_target_version: 0`, a client request key `req-worker-retry-01`, and two sequential edits:
   - Edit 1 matches `name: auth-api\n  timeout_ms: 1000` and replaces it with `name: auth-api\n  timeout_ms: 2500`.
   - Edit 2 matches `retry: false` with `occurrence_index: 2` and replaces it with `retry: true`, using explicit index disambiguation instead of padding the payload with dozens of lines of surrounding context.

3. **Deterministic Validation and Atomic Commit**:
   Under a row-level `SELECT ... FOR UPDATE` lock, PatchDIFF verifies that the target version is still 0. The runtime applies edit 1 in memory ($T_0 \rightarrow T_1$), resolves occurrence 2 of `retry: false` in $T_1$ ($T_1 \rightarrow T_2$), increments `current_version` to 1, records the accepted transaction in `append_only_pdcp_logs`, appends two derived change records to `append_only_manifest_ledger`, and returns `status: "accepted"`.

4. **Idempotent Retry Recovery**:
   If a network or transport disconnect drops the response and the host resends the submission with request key `req-worker-retry-01`, PatchDIFF recognizes the recorded key, skips applier re-execution, and returns the recorded accepted outcome with `deduplicated: true`.

---

## 26. Architectural Limitations and Operational Tradeoffs

PatchDIFF deliberately trades heuristic permissiveness for deterministic safety. Integrators and researchers should account for the following boundaries and operational limitations:

1. **Exact matching can still reject and cost extra turns when near-miss bounds are exceeded:**
   - Because PatchDIFF never performs fuzzy auto-application, a single-character typo in `match` or `expected_text` always rejects the transaction and requires a host retry turn.
   - Furthermore, post-commit `near_misses` are bounded: they run **only** on eligible `match_absent` rejections when the failing needle has length 1 to 64 code points, scan at most 65,536 code points of the failing buffer copy under a 1,000,000-comparison-cell cap (flagging `scope_truncated: true` if capped), are omitted on `sequential_match_invalid` rejections with omission reason `sequential_match_consumed`, and are skipped when submission tools are called inside a caller-owned outer SQLAlchemy transaction with omission reason `caller_transaction`. When `near_misses` are unavailable or truncated, the host can issue an explicit `patchdiff_read_target` or `patchdiff_find_occurrences` call.
2. **Intermediate-buffer coordinates on multi-edit failures:**
   - When operation $i > 1$ fails in a multi-operation transaction, `failure_context`, `exact_candidates`, and `near_misses` reflect the uncommitted intermediate buffer $T_{i-1}$ with `buffer_stage = "intermediate_buffer"`, not the committed target $T_0$. Hosts must either adjust operation $i$ relative to the preceding operations $1 \dots i-1$ in the same batch or inspect `current_context` ($T_0$).
3. **Single-target atomicity only:**
   - Transactions are atomic per `target_file_id`. Cross-file refactorings spanning multiple documents are not committed in a single multi-target transaction.
4. **Conservative Unicode grapheme-cluster warning:**
   - The `grapheme_boundary_split` check inspects immediate boundary code points around $[s_i, e_i)$ (catching combining marks, ZWJ sequences, variation selectors, and regional indicator pairs) as an advisory warning; it is not a full locale-sensitive linguistic segmentation engine.
5. **No semantic or task-level correctness guarantee:**
   - An accepted PatchDIFF transaction guarantees that precondition guards held and exact text or span operations succeeded (marking `protocol_valid` and `transaction_valid` as true). It never guarantees that the resulting code compiles, passes tests, or satisfies the user's intent (marking `task_correct` and `semantic` as `"not_evaluated"`).
6. **Empirically measured efficiency and remaining open questions (Decision A8):**
   - The [current Workspace benchmark](../benchmarks/workspace-e2e-benchmark.md) records timed execution, setup delays, calls, tokens and exact task outcomes across 18 runs. It supports the agent-owned guarded editing/publication workflow for this task. Multi-agent contention, long-horizon sessions and human review remain open investigations.
7. **Single-file workspace publication & cooperative writer limits:**
   - Workspace publication via `patchdiff_save(sync_workspace=True)` synchronizes individual files to disk and guards against external disk drift. It does not provide cross-file filesystem transactions, and assumes a cooperative POSIX writer environment where external processes do not concurrently overwrite target files outside PatchDIFF.

---

## 27. Security, Trust Boundaries, and Deployment Scope

- **Trust boundary:** Model outputs and MCP tool arguments are untrusted inputs validated at the protocol and service layers. The PostgreSQL database and PatchDIFF Python runtime are trusted infrastructure components.
- **Resource & DoS bounds:** Read and search tools enforce hard caps of 8,000 code points and 200 occurrences; `patchdiff-tx/3` enforces a 1 MiB (1,048,576 bytes) and 1,000,000-code-point fresh admission cap; near-miss calculations execute after releasing the target row lock under a hard 1,000,000-cell budget; and history paging with `include_content=True` enforces a 1 MiB cumulative page budget (after the first non-empty entry on a page).
- **Filesystem concurrency & operational scope:** Filesystem synchronization operates strictly on individual target files within a designated workspace root. The server does not manage distributed filesystem locks or intercept OS write syscalls; it relies on per-target optimistic concurrency in PostgreSQL, pre-write disk drift validation, and cooperative POSIX writer environments.
- **Authentication & multi-tenant isolation:** PatchDIFF is designed as a local or private-network MCP transaction service running over standard I/O subprocess pipes or an internal FastAPI registry. Multi-tenant authentication, role-based access control, and network TLS termination are deployment-layer responsibilities outside the core transaction engine.

---

## 28. Future Research and Architectural Extensions

1. **Executing the Live-Model & Human Comparative Benchmark Suite (H1 to H4, H6, H7):** Running the controlled multi-model evaluation defined in §23.3 across frontier and open-weight coding models to quantify first-pass validity, retry convergence with `near_misses`/`exact_candidates`, and net session token cost.
2. **Multi-Target Coordinated Transactions:** Extending `SELECT ... FOR UPDATE` lock ordering across sorted target UUID arrays to support all-or-nothing multi-file refactoring transactions while preserving per-target replayable ledgers.
3. **Client/Server Protocol Capability Handshake:** While PatchDIFF already dispatches replay across recorded protocol and runtime version pairs, adding an explicit MCP capability negotiation handshake would allow hosts and servers at different versions to negotiate supported transaction formats dynamically at connection startup.
4. **Optional Host-Side Semantic Verification Hooks:** Providing standardized post-preview / pre-commit callback patterns so hosts can run syntax checkers, typecheckers, or unit tests against `patchdiff_preview` outputs before committing.

---

## 29. Conclusion

As AI agents transition from single-turn code completions to long-horizon, multi-turn collaborators over persistent documents, the editing interface can no longer treat file mutation as an unguarded side effect. Full-document regeneration wastes output bandwidth and risks silent drift across untouched regions, while unguarded local patch tools (such as substring replacements, unified diffs, and line-range splices) leave concurrency control, multi-edit rollback, retry idempotence, and auditability to ad-hoc host wrappers.

PatchDIFF demonstrates that agent document editing is naturally modeled as a **deterministic, preconditioned database transaction**. By combining structured JSON transaction primitives across exact match under `patchdiff-tx/1`, guarded code-point spans under `patchdiff-tx/2`, and whole-document replacement under `patchdiff-tx/3` with per-target PostgreSQL `SELECT ... FOR UPDATE` serialization, `client_request_id` idempotency, stage-accurate validity reporting, bounded recovery diagnostics, save cycle compaction, and profile-dispatched deterministic replay, PatchDIFF gives MCP hosts a rigorous, auditable foundation for iterative document state transitions.

---

## References

1. **Model Context Protocol (MCP) Specification:** Anthropic, *Model Context Protocol Specification (JSON-RPC 2.0 Transport & Tool Calling)*, `https://modelcontextprotocol.io/`.
2. **IETF RFC 6902:** P. Bryan and M. Nottingham, *JavaScript Object Notation (JSON) Patch*, RFC 6902, April 2013.
3. **Unicode Standard Annex #29 (UAX #29):** M. Davis, *Unicode Text Segmentation (Extended Grapheme Clusters)*, Unicode Consortium.
4. **Approximate String Matching & Banded Edit Distance:**
   - E. Ukkonen, *"Algorithms for Approximate String Matching,"* Information and Control, 64(1-3):100-118, 1985.
   - G. M. Landau and U. Vishkin, *"Fast Parallel and Serial Approximate String Matching,"* Journal of Algorithms, 10(2):157-169, 1989.
5. **Optimistic Concurrency Control:** H. T. Kung and J. T. Robinson, *"On Optimistic Methods for Concurrency Control,"* ACM Transactions on Database Systems (TODS), 6(2):213-226, 1981.
6. **Agent Editing Tool Interfaces (Primary Vendor Specifications):**
   - Anthropic, *Text Editor Tool* (`str_replace_based_edit_tool` and `str_replace`), Claude API Documentation, https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/text-editor-tool.
   - OpenAI, *Apply Patch Tool* (`apply_patch` V4A diff format), OpenAI Platform Documentation & Cookbook, https://platform.openai.com/docs/guides/tools.
7. **PatchDIFF Normative Specifications:**
   - [AGENTS.md](https://github.com/paragon-ux/Patch-DIFF/blob/main/AGENTS.md): Locked architectural invariants and runtime boundaries.
   - [formal transaction model](formal-transaction-model.md): Mathematical state space, operational transition algebra, and invariant proofs.
   - [modernization architecture](modernization-architecture.md): Architecture decisions A1 to A8, contracts C1 to C6, and historical design reconciliation.
   - [MCP tool contracts](../spec/mcp-tools.md): Normative MCP tool contracts, schemas, and byte budgets.
   - [core runtime](../spec/core-runtime.md): Deterministic core runtime specification and validation stages.
   - [PostgreSQL data model](../spec/data-model.md): PostgreSQL schema and constraints.
   - [transaction formats](../spec/transaction-formats.md): Transaction formats across `patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`.
   - [backend/tests/verification/README.md](https://github.com/paragon-ux/Patch-DIFF/blob/main/backend/tests/verification/README.md): Offline payload byte accounting and evaluation methodology.
