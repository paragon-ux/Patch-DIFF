# Workstation and LAN Hub Reference Architecture

This reference architecture describes a workstation deployment and proposed
extensions for a shared LAN hub. The current MCP adapter uses stdio. A LAN
gateway would be supplied and operated separately.

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
- **Granular row-level OCC**: PostgreSQL locks only the specific row of the file being committed (`SELECT ... FOR UPDATE`). Agents working on disjoint files can commit independently. Same-target writers serialize on the row lock. A later writer with a stale version guard is rejected after it acquires the lock.

---

## 3. Agent-Driven CLI Deployment

Agents prefer explicit, deterministic command-line operations over interactive wizards or manual configuration files. The CLI serves as the authoritative interface for automated startup, migrations, and health checks.

### 3.1 Migration and startup

Apply migrations before the MCP host starts its stdio connection. For an
existing database, follow the [0007 cutover procedure](../guides/workspace-quickstart.md#upgrade-an-existing-database-to-0007).

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

## 4. SAVE retention and proposed archival

The current service retains admitted attempts in `append_only_pdcp_logs` and
accepted changes in `append_only_manifest_ledger`. A successful SAVE records
a checkpoint and rotates the editing cycle. With `sync_workspace: true`,
it can also publish file bytes. The service retains prior attempts and ledger
rows for audit and replay.

### Proposed archival policy

The following design is exploratory and has no current runtime or storage
contract. Any future pruning proposal must preserve audit and replay guarantees.

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

1. **Hot working set**. The proposal would retain the active cycle and the
   most recent $N$ completed cycles in PostgreSQL.
2. **Cold archive**. The proposal would archive older attempts and span facts
   before removing their database rows.
3. **Verification**. Storage and query costs, archive durability and replay
   from archived history would need independent validation.

---

## 5. Division of Responsibilities

A common confusion in transactional editing is whether the transaction service should also validate AST grammar and code semantics. The architecture maintains a strict boundary between parser scoping and transaction arbitration:

| Responsibility | Owner | Mechanism |
| :--- | :--- | :--- |
| **Syntactic boundary scoping** | Waymark Engine (AST Parser) | Resolves function, class, and method bounds with code-point spans. Observed edits are constrained to their selected scopes. |
| **Transaction atomicity & OCC** | PatchDIFF Server | Evaluates version guards, SHA-256 hashes, row locks (`SELECT ... FOR UPDATE`), and atomic application per target. |
| **Lineage & Idempotency** | PatchDIFF Storage | Deduplicates client request keys and tracks parent-to-child retry attempt chains. |
| **Physical File Publication** | Workspace Synchronizer | Publishes on explicit workspace SAVE with drift detection and the selected line-ending format. |
| **Task & Semantic Logic** | Autonomous Agent (Host) | Plans code changes, interprets diagnostics, and chooses retry strategies. |

---

## 6. Security and Network Isolation

When exposing PatchDIFF across a local area network:
1. **Network binding**. Keep PostgreSQL on a private interface. If a separate LAN gateway is deployed, configure its network exposure and access controls independently of the PatchDIFF stdio adapter.
2. **Filesystem path confinement**: The workspace synchronizer resolves canonical paths before opening file descriptors, rejecting directory traversal attempts and symbolic link escapes outside `PATCHDIFF_WORKSPACE_ROOT`.
