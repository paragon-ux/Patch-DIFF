# Visual Architecture & Transaction Lifecycle

Follow an edit from the host's initial read through validation, commit, publication, and replay. See the [profile catalog](spec/profiles/index.md) to choose which tools the host can call.

---

## 1. End-to-End Transaction Sequence

The workspace file supplies the starting bytes and receives an explicit publication. PostgreSQL holds the canonical LF working copy, version, and audit history. The host owns edit intent, context selection, and retries.

The sequence below illustrates the 5-tool `workspace` text-editing workflow:

`initialize_target` → `read_target` / `find_occurrences` → `submit_edits` → `save`

In the primary 7-tool `observed_workspace` profile, the agent also discovers structural candidates with `patchdiff_list_scopes`, observes snapshots with `patchdiff_observe_scopes`, and commits multi-scope bundles with `patchdiff_commit_bundle` between import and SAVE publication.

![End-to-End Transaction Sequence](assets/diagrams/end-to-end-transaction-sequence.svg)

With `sync_workspace: false`, SAVE checkpoints the database without publishing a file. When SAVE returns `partial`, inspect the file and checkpoint separately. See the [workspace contract](spec/profiles/workspace-profile.md).

---

## 2. Core Validation Stages & State Transition Flowchart

PatchDIFF evaluates each proposal through five validation stages. The target is not mutated unless the transaction passes the guards, protocol validation, sequential simulation, and commit checks.

![Core Validation Stages and State Transitions](assets/diagrams/core-validation-stages.svg)

The stages serve different purposes: Stage 3 simulates the proposed edits against the evolving in-memory buffer; Stage 4 verifies the commit guard before persistence. Rejections leave the target document unchanged. Pre-admission failures such as a missing target do not create an attempt row.

---

## 3. Four-Tier Architecture

PatchDIFF separates the external agent, MCP transport, transaction orchestration, and persistent state. The deterministic core is shown as a component called by the transaction service, rather than as a separate operational tier, because it performs pure in-memory evaluation without database or network I/O.

![Four-Tier Architecture](assets/diagrams/four-tier-architecture.svg)

**Execution boundary:** The transaction service coordinates persistence and workspace I/O. The pure deterministic core receives the target text, transaction payload, and execution profile; it returns a simulated result and derived facts without calling an LLM, database, or network service.

---

## 4. Deterministic Profile-Dispatched Replay Flowchart

Replay reconstructs the target by starting from the initial upload snapshot and applying accepted log entries in `log_sequence` order. Each entry is executed using its recorded `(protocol_version, runtime_version)` profile.

![Deterministic Profile-Dispatched Replay Flowchart](assets/diagrams/replay-verification.svg)

The four materialized-state checks are independent: `content_matches`, `stored_hash_matches`, `recomputed_hash_matches`, and `version_matches`. The content comparison also detects raw line-ending divergence, such as out-of-band CRLF or bare-CR changes, even when canonical LF hashes agree.
