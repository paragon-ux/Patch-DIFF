# PatchDIFF Architecture & Product Roadmap

**Status:** Forward-looking architectural roadmap  
**Baseline:** PR #24 (`observed_workspace` profile, agent-owned publication, and 18-trial benchmark)  
**Governing Standard:** [`docs/standards/pr-review-standard.md`](standards/pr-review-standard.md) v1.1.0 and [`AGENTS.md`](https://github.com/paragon-ux/Patch-DIFF/blob/main/AGENTS.md)

---

## 1. Multi-Agent Concurrency Architecture

PatchDIFF decouples document editing from the host filesystem, providing an authoritative transaction runtime backed by PostgreSQL. In multi-agent environments, this architecture fundamentally eliminates the primary bottleneck of autonomous coding: **working-tree disk collisions**.

```text
Physical Filesystem (Untouched during drafting)
  │
  ├─► [Agent A] ──► patchdiff_observe_scopes ──► patchdiff_commit_bundle ──┐
  │                                                                        ├─► [PostgreSQL Substrate]
  ├─► [Agent B] ──► patchdiff_observe_scopes ──► patchdiff_commit_bundle ──┘    (SELECT ... FOR UPDATE)
  │
  └─► [Explicit SAVE] ──► patchdiff_save(sync_workspace=true) ──► Published Working File
```

### 1.1 In-Flight Git Conflict Elimination

When multiple agents edit files concurrently on a traditional filesystem:
1. File modifications trigger IDE file watchers, background linters, and compiler re-indexes.
2. Concurrent edits dirty the Git index, creating intermediate merge conflicts, stash collisions, and corrupted working states.

Under PatchDIFF:
- **In-flight working-tree isolation**: Agents submit declarative transactions (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`, or observed scope bundles) directly against the PostgreSQL substrate. The physical working tree on disk remains untouched during drafting and review until explicit publication.
- **Optimistic Concurrency Control (OCC)**: Every edit transaction requires explicit `expected_target_version` and/or `expected_current_hash` guards evaluated under atomic row locking (`SELECT ... FOR UPDATE`). This guarantees no lost updates within the PatchDIFF database substrate.
- **Deterministic Linear Retries**: If Agent B commits version $V+1$ while Agent A was observing version $V$, Agent A's transaction is deterministically rejected (`target_version_mismatch`) with zero database mutation and zero disk mutation. Agent A reads the authoritative current state via `patchdiff_read_target` or `patchdiff_find_occurrences`, resolves the change, and resubmits with `parent_pdcp_log_id` lineage.
- **Explicit System Boundaries**: PatchDIFF guarantees OCC per target within PostgreSQL. It does not provide cross-target atomicity, physical filesystem transactions, external non-PatchDIFF writer synchronization, Git branch merges, or automatic semantic conflict resolution. Publication to disk requires explicit SAVE.

### 1.2 Boundary of Transactional Guarantees

In accordance with [PR Review Standard v1.1.0](standards/pr-review-standard.md):
- **Database transaction atomicity**: Guaranteed. PostgreSQL enforces per-target ACID state transitions, append-only logs, and manifest ledgers.
- **In-flight working-tree isolation**: Guaranteed within the PostgreSQL substrate. Unfinalized PatchDIFF transactions do not touch disk or Git working trees.
- **Semantic / Task correctness**: Host-owned. PatchDIFF validates exact match/span bounds and transaction consistency; it does not synthesize agent intents or guarantee that two independently valid edits achieve an overall business goal.
- **Physical disk write-back**: Explicitly published. In Workspace mode, `patchdiff_save` (`sync_workspace: true`) writes canonical bytes to disk with drift verification against the initial observed digest.

---

## 2. Profile Surface and Packaging

### 2.1 Distribution (`patchdiff-mcp`)

- **PyPI Package Name**: `patchdiff-mcp`.
- **Runtime Environment**: Python >= 3.11 with PostgreSQL 16+ as the backing relational substrate.
- **Waymark AST Parser Bridge**: Packaged with the wheel; requires Node.js 22+ for resident structural AST scope observation.

### 2.2 Core Benchmark Arm Profiles

PatchDIFF documentation and public interfaces focus on three core profiles aligned with the empirical benchmark:

1. **`observed_workspace` (Primary & Recommended)**: The comprehensive 7-tool structural editing profile that enables autonomous agents to own the complete editing lifecycle from file import to publication:
   - `patchdiff_initialize_target` (with `from_workspace: true`)
   - `patchdiff_read_target`
   - `patchdiff_find_occurrences`
   - `patchdiff_list_scopes`
   - `patchdiff_observe_scopes`
   - `patchdiff_commit_bundle`
   - `patchdiff_save` (with `sync_workspace: true`)
2. **`workspace`**: The streamlined 5-tool exact text editing profile for file-based workflows without Node.js dependencies (`initialize_target`, `read_target`, `find_occurrences`, `submit_edits`, `save`).
3. **`observed_v2`**: The 5-tool structural editing profile for host-managed lifecycle environments (`read_target`, `find_occurrences`, `list_scopes`, `observe_scopes`, `commit_bundle`), where the host manages target setup, SAVE checkpointing, replay, and file writes out-of-band.

---

## 3. Forward-Looking Research and Architectural Extensions

1. **Multi-Target Coordinated Transactions** (Implemented):
   - Deadlock-free `SELECT ... FOR UPDATE` lock ordering across canonical UUID sort order (`target_file_id[]`) supporting all-or-nothing multi-file refactoring transactions via `patchdiff_commit_multi_target` while preserving per-target replayable ledgers.
2. **Client/Server Protocol Capability Negotiation** (Implemented):
   - Explicit MCP capability-negotiation handshake (`capabilities.patchdiff`) allowing hosts and servers across versions to negotiate supported transaction formats (`tx/1..3`), runtime profiles, and observation features dynamically at connection startup.
3. **Pre-Commit Semantic Verification Hooks** (Implemented):
   - Standardized advisory verification hooks via `verify_syntax` and `verification_hooks` in `patchdiff_preview` allowing hosts to evaluate simulated buffer AST syntax (Python, JSON, Markdown fence balance) before committing transactions, reporting `validity.semantic`.
4. **Long-Horizon Multi-Agent Contention Studies** (Implemented):
   - Empirical evaluation across concurrent disjoint workloads, hotspot file contention with lineage retries, and circular multi-target refactorings, proving 100% recovery rates, zero deadlocks, and verified cryptographic replay ([docs/benchmarks/multi-agent-contention.md](benchmarks/multi-agent-contention.md)).
