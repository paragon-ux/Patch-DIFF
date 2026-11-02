# PatchDIFF Modernization Roadmap

**Status**: Forward-looking architectural roadmap  
**Baseline**: PR #22 (Repository standardization & docs cleanup) $\to$ PR #23 (MCP profile consolidation, atomic finalization, packaging, and roadmap)  
**Governing Standard**: [`docs/standards/PR_REVIEW_STANDARD.md`](standards/PR_REVIEW_STANDARD.md) v1.1.0 and [`AGENTS.md`](https://github.com/paragon-ux/Patch-DIFF/blob/main/AGENTS.md)

---

## 1. Multi-Agent Concurrency Architecture

PatchDIFF decouples document editing from the host filesystem, providing an authoritative transaction runtime backed by PostgreSQL. In multi-agent environments, this architecture fundamentally eliminates the primary bottleneck of autonomous coding: **working tree disk collisions**.

```text
Host Filesystem (Untouched during editing)
  |
  +---> [Agent A] ---> patchdiff_observe_scopes ---> patchdiff_commit_bundle ---+
  |                                                                             |--> [PostgreSQL Substrate]
  +---> [Agent B] ---> patchdiff_observe_scopes ---> patchdiff_commit_bundle ---+    (SELECT ... FOR UPDATE)
  |
  +---> [Host Finalization] ---> patchdiff_finalize_target ---> Host-Owned Verified Disk Write-Back
```

### 1.1 In-Flight Git Conflict Elimination

When multiple agents edit files concurrently on a traditional workspace:
1. File modifications trigger IDE file watchers, background linters, and compiler re-indexes.
2. Concurrent edits dirty the Git index, creating intermediate merge conflicts, stash collisions, and corrupted working states.

Under PatchDIFF:
- **In-flight working-tree isolation**: Agents submit declarative transactions (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`, or observed batches) directly against the PostgreSQL substrate. The physical working tree on disk remains untouched during drafting and review until trusted host finalization.
- **Optimistic Concurrency Control (OCC)**: Every edit transaction requires explicit `expected_target_version` and/or `expected_current_hash` guards evaluated under atomic row locking (`SELECT ... FOR UPDATE`). This guarantees no lost updates within the PatchDIFF database substrate.
- **Deterministic Linear Retries**: If Agent B commits version $V+1$ while Agent A was observing version $V$, Agent A's transaction is deterministically rejected (`target_version_mismatch`) with zero database mutation and zero disk mutation. Agent A reads the authoritative current state via `patchdiff_read_target` or `patchdiff_find_occurrences`, resolves the change, and resubmits with `parent_pdcp_log_id` lineage.
- **Explicit System Boundaries**: PatchDIFF guarantees OCC per target within PostgreSQL. It does not provide cross-target atomicity, physical filesystem transactions, external non-PatchDIFF writer synchronization, Git branch merges, or automatic semantic conflict resolution. Final disk installation is host-owned and must use preimage verification (`examples/host_finalize.py`).

### 1.2 Boundary of Transactional Guarantees

In accordance with [PR Review Standard v1.1.0](standards/PR_REVIEW_STANDARD.md):
- **Database transaction atomicity**: Guaranteed. PostgreSQL enforces per-target ACID state transitions, append-only logs, and manifest ledgers.
- **In-flight working-tree isolation**: Guaranteed within the PostgreSQL substrate. Unfinalized PatchDIFF transactions do not touch disk or Git working trees.
- **Semantic / Task correctness**: Host-owned. PatchDIFF validates exact match/span bounds and transaction consistency; it does not synthesize agent intents or guarantee that two independently valid edits achieve an overall business goal.
- **Physical disk write-back**: Host-owned. The host installs exported bytes onto physical media using atomic file replacement protocols.

---

## 2. Release & Packaging Roadmap

### 2.1 Distribution (`patchdiff-mcp`)

- **PyPI Package Name**: `patchdiff-mcp` (differentiating from unrelated third-party package `patchdiff`).
- **Console Scripts**: `patchdiff-mcp` (primary; prepublication acceptance uses `uvx --from <absolute-local-wheel> patchdiff`), `patchdiff-mcp-setup`, and `patchdiff-mcp-daemon` (with `patchdiff`, `patchdiff-setup`, and `patchdiff-daemon` retained as compatibility aliases).
- **Docker-only PostgreSQL Runtime CLI**: `patchdiff-mcp-setup` and `patchdiff-mcp-daemon start|stop|restart|status` manage a checkout-scoped PostgreSQL 16.3 Alpine Compose service on loopback port `5433`. Explicit external PostgreSQL 16+ URLs connect to an already-running service without lifecycle management. Existing native PGDATA stays untouched.
- **Process and database boundaries**: operator, editor-service and model UIDs remain separate; bootstrap is migration-only, host is a nonsuperuser, and editor DML is allowlisted. Migration `20261101_0008` adds database-owned history revision, immutable audit guards and persisted 256-KiB export chunks.
- **Supported Runtime**: Python >=3.11 with `psycopg[binary]>=3.2,<4.0`.
- **Packaging Security**: publication is separate from PR completion. Manual dispatch from `main` must verify an existing tag equals `origin/main` and package metadata, re-test the exact artifact, and obtain independent protected `pypi` environment approval before OIDC publishing. PyPI/TestPyPI name control and Trusted Publisher settings need owner evidence; live Glama ingestion remains post-merge. Version `0.1.0` is not publication authorization.

### 2.2 Profile Evolution

- **Default Profile (`observed_v2`)**: Streamlined 5-tool external editing surface for autonomous agents (`patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`).
- **Lifecycle & Administrative Profile (`full`)**: Comprehensive 24-tool surface for trusted host harnesses, including document ingestion, export, SAVE checkpointing, deterministic replay, single-roundtrip `patchdiff_finalize_target`, and immutable paginated `patchdiff_read_finalized_export`.
- **Legacy Profiles Transition**: Historical profiles (`editor`, `unobserved`, `unobserved_editor`, `hybrid_editor`, `observed`, `observed_editor`) retain their catalogs with advisory notices on stderr. Trusted lifecycle actions use a separate operator-owned `full` session; the delegated SQL role cannot perform lifecycle writes.

### 2.3 Independent Version Domains (`PR23-PLAN-DEP-005`)

PatchDIFF explicitly distinguishes independent version domains:
1. **PyPI Distribution Version (`0.1.0`)**: Python package release version for `patchdiff-mcp` in `pyproject.toml`.
2. **MCP Wire Protocol & Server (`2024-11-05` / `patchdiff-mvp 0.2.2`)**: The external JSON-RPC MCP protocol version and advertised server identity.
3. **Transaction Format Revisions (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`, `0.2.3`, `patchdiff-observed-batch/1`)**: Declarative transaction input schemas and lowerings.
4. **Deterministic Replay Profiles (`patchdiff-mvp-0.1.0`, `0.2.0`, `0.2.1`, `0.2.2`, `0.3.0`, `0.4.0`, `0.5.0`, and `patchdiff-observed-batch-r1`)**: Immutable historical replay runtimes stored in Postgres logs. Distribution version increments never retroactively alter or rename durable protocol/runtime identifiers.

