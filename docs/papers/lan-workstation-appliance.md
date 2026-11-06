# Workstation and LAN Hub Reference Architecture

This document specifies the deployment architecture for running PatchDIFF as a shared concurrency hub across multiple autonomous agents operating on a single developer workstation or local area network (LAN).

---

## 1. Context and Problem Statement

Autonomous coding agents frequently operate in multi-agent swarms: a planner outlines tasks, multiple worker agents draft edits in parallel, and a reviewer validates changes.

When these agents interact directly with the local filesystem:
1. **Concurrent writes collide**: Simultaneous file modifications cause lost updates, race conditions, and corrupted files.
2. **Git indexes dirty prematurely**: In-flight drafts trigger linters, language servers, and git merge conflicts before code is ready for review.
3. **Deployment friction stalls adoption**: Agents spend excessive turns installing system dependencies, configuring relational databases, and debugging daemon startup instead of writing code.

PatchDIFF solves this by running as a **shared transaction hub**: a single PostgreSQL instance and PatchDIFF service manage canonical in-flight state for all agents on a workstation or team network.

---

## 2. System Topology

In this architecture, one machine (the developer workstation or a shared team host) runs the PatchDIFF engine and PostgreSQL. Client agents connect as standard MCP clients without local database or parser dependencies.

```text
[Developer Workstation or Team LAN Host]
┌─────────────────────────────────────────────────────────────┐
│ Docker / Podman or Local System Daemons                     │
│                                                             │
│  ┌─────────────────────────┐     ┌───────────────────────┐  │
│  │ PostgreSQL 16+          │◄────┤ PatchDIFF MCP Server  │  │
│  │ (MVCC Row-Level Locks)  │     │ + Resident Waymark    │  │
│  └─────────────────────────┘     └──────────▲────────────┘  │
│                                             │               │
│                                  ┌──────────┴────────────┐  │
│                                  │ Local Stdio or        │  │
│                                  │ Network MCP Gateway   │  │
│                                  └──────────▲────────────┘  │
└─────────────────────────────────────────────┼───────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      │                                               │
             [Agent Client A]                                [Agent Client B]
     Planning / Coder Subagent                         Reviewer / Auditor Subagent
     Connection: Stdio or Network MCP                  Connection: Stdio or Network MCP
     Client Dependencies: 0                            Client Dependencies: 0
```

### Key Architectural Properties

- **Zero client footprint**: Client agents require no PostgreSQL, no Alembic migrations, and no Node.js runtime. To the agent, PatchDIFF is simply an MCP toolset configured in its host settings.
- **Physical working tree isolation**: The physical Git repository remains clean during multi-agent drafting. Edits live entirely within PostgreSQL working copies until an authorized agent executes `patchdiff_save`.
- **Granular row-level OCC**: PostgreSQL locks only the specific row of the file being committed (`SELECT ... FOR UPDATE`). Agents working on disjoint files commit simultaneously with zero contention. If two agents touch the same file, the second transaction fails immediately with an OCC version guard error and retry lineage.

---

## 3. Agent-Driven CLI Deployment

Agents prefer explicit, deterministic command-line operations over interactive wizards or manual configuration files. The CLI serves as the authoritative interface for automated startup, migrations, and health checks.

### 3.1 One-Step Migration and Startup

An agent provisioning or inspecting the hub runs two commands:

```bash
# 1. Apply database migrations to the latest head
patchdiff-mcp --migrate

# 2. Launch the server with explicit profile and response mode
patchdiff-mcp --profile observed_workspace --response-mode compact
```

### 3.2 Machine-Readable Error Exits

The CLI enforces strict exit codes for automated agent recovery:
- `0`: Clean execution or graceful shutdown.
- `1`: Database connection failure, unapplied migrations, or invalid workspace root. The error stream outputs actionable guidance (for example, suggesting `--profile observed_v2` if POSIX file locking is absent).
- `2`: Missing CLI flag arguments or unrecognized options.

---

## 4. Storage Compaction and Log Pruning on N SAVEs

PatchDIFF records every accepted and rejected transaction in `append_only_pdcp_logs` and `manifest_ledger`. During active multi-agent drafting, retry loops and exploratory edits can produce high log volumes.

To keep PostgreSQL storage bounded and query latencies predictable, the hub uses epoch-based compaction tied to the publication lifecycle.

### 4.1 Publication Epochs

Every call to `patchdiff_save` with `sync_workspace=true` writes canonical text to disk and rotates the target editing cycle. This rotation establishes a clean epoch boundary.

### 4.2 Compaction Policy

```text
[Active Cycle 1..N in Postgres]
  │
  ├─► Agent drafting, retries, and OCC evaluation
  │
[Cycle N+1 SAVE Executed]
  │
  ├─► 1. Verify target hash matches latest manifest fact
  ├─► 2. Stream historical logs for cycles < N into compressed JSONL archive
  ├─► 3. Prune archived rows from append_only_pdcp_logs
  │
[PostgreSQL Retains Bounded Hot Working Set]
```

1. **Hot working set**: PostgreSQL retains only the active cycle and the most recent $N$ completed cycles (default: 3). This preserves sufficient retry lineage and diff context for active agents.
2. **Cold archive**: Older attempt logs and intermediate span facts are streamed to compressed append-only files (`.patchdiff/archive/cycle-<id>.jsonl.gz`) before deletion from PostgreSQL.
3. **Database health**: Indexes and table working sets fit entirely inside database shared memory, keeping OCC row-lock evaluation fast regardless of project age.

---

## 5. Division of Responsibilities

A common confusion in transactional editing is whether the transaction service should also validate AST grammar and code semantics. The architecture maintains a strict boundary between parser scoping and transaction arbitration:

| Responsibility | Owner | Mechanism |
| :--- | :--- | :--- |
| **Syntactic boundary scoping** | Waymark Engine (AST Parser) | Resolves function, class, and method bounds with code-point spans. Prevents the model from corrupting surrounding file syntax. |
| **Transaction atomicity & OCC** | PatchDIFF Server | Evaluates version guards, SHA-256 hashes, row locks (`SELECT ... FOR UPDATE`), and atomic rollback across multiple targets. |
| **Lineage & Idempotency** | PatchDIFF Storage | Deduplicates client request keys and tracks parent-to-child retry attempt chains. |
| **Physical File Publication** | Workspace Synchronizer | Writes canonical LF bytes to disk upon explicit `patchdiff_save` with drift detection. |
| **Task & Semantic Logic** | Autonomous Agent (Host) | Plans code changes, interprets diagnostics, and chooses retry strategies. |

---

## 6. Security and Network Isolation

When exposing PatchDIFF across a local area network:
1. **Network binding**: Bind the MCP service and PostgreSQL exclusively to local interfaces (`127.0.0.1` for workstation-local, or private LAN subnets with pre-shared tokens).
2. **Filesystem path confinement**: The workspace synchronizer resolves canonical paths before opening file descriptors, rejecting directory traversal attempts and symbolic link escapes outside `PATCHDIFF_WORKSPACE_ROOT`.
