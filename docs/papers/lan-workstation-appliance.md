# PatchDIFF Shared LAN Hub Reference Architecture

**Status:** Proposed LAN v1 architecture; decision draft, not an as-built declaration  
**Target location:** `docs/papers/lan-workstation-appliance.md` (replaces the earlier workstation/LAN reference)  
**Reviewed source baseline:** PatchDIFF PR [#27](https://github.com/paragon-ux/Patch-DIFF/pull/27), commit `7fef376e440adf5e3fd40723f02c1c68848d20f1`, 2026-11-12  
**Companions:** [Operator-Managed Editing Run Lifecycle](../plans/operator-managed-editing-run-lifecycle.md) · [LAN Hub and Editing Run Invariants](../spec/lan-hub-and-run-lifecycle-invariants.md)

> **Architecture decision.** PatchDIFF exposes ordinary project files to AI agents through a shared, deterministic MCP editing service. A team LAN uses **one centrally operated remote MCP endpoint and one dedicated PostgreSQL database per operator-managed editing run**. Workers do not provision, migrate, back up, or retire the server. Workspace placement, the MCP profile, publication authority, run duration, and archive/discard policy are operator/host choices. **Only an explicit operator close can retire a run database.**

## 1. Purpose and architectural boundaries

PatchDIFF addresses concurrent editing, not virtual filesystem management. Agents continue to find text or symbols, read or observe scopes, propose guarded edits, and (when their profile permits) SAVE to real files. PostgreSQL holds the **canonical in-flight state of initialized targets**, versions, snapshots, and transaction evidence while a run is active. It is not a separate navigable copy of the entire project directory. Imported target content is stored in PostgreSQL; this design does **not** claim zero data duplication.

The three boundaries are independent:

| Boundary | Defined by | Not implied by |
| --- | --- | --- |
| **Deployment / transport** | Local workstation stdio or centrally operated remote MCP service | Physical location of workspace files |
| **Editing and lifecycle permissions** | Selected MCP profile, host workflow, and service-side authorization | Whether a connection uses LAN or stdio |
| **Editing-run retention** | Explicit operator lifecycle and whole-database policy | SAVE count, MCP disconnection, crash, or server restart |

**LAN defines the service boundary, not the workspace boundary.** Centralizing PatchDIFF does not require placing all checkouts on the server. However, the currently implemented `observed_workspace` import and disk-publication tools operate on a workspace accessible to the **server process**. A client-side checkout is not writable merely because its client can connect over MCP; a host-owned publication workflow is a different, explicit arrangement.

## 2. Primary topology — LAN v1

```text
        Independently connected MCP clients / AI workers
          A                 B                 C ... H
          |                 |                    |
          +-----------------+--------------------+
                            | authorized remote MCP
                            v
            +---------------------------------------+
            | ONE operator-managed remote endpoint  |
            | authn, access policy, profile binding |
            | admission control / active-run gate   |
            +------------------+--------------------+
                               |
                        PatchDIFF runtime
                      (Waymark when selected)
                               |
                  guarded edits, row-lock OCC,
                  canonical reads, durable logs
                               |
                +--------------v-----------------+
                | Dedicated PostgreSQL database  |
                | for ONE operator-managed run   |
                +--------------+-----------------+
                               |
              authorized initialization / SAVE
                      or trusted host workflow
                               v
                 Ordinary operator-defined files
             (location independent of LAN topology)
```

“One endpoint” means **one logical shared editing authority for the active project and run**. LAN v1 uses one operator-supervised service host, one operator-registered writable workspace, one active editing run, one dedicated database, and one shared worker endpoint. The workspace can live anywhere the service can access it. The operator's exclusive workspace lease covers every PatchDIFF writer, including trusted lifecycle paths, across independently provisioned databases. Cross-host failover requires an enforced fence before moving authority. The [lifecycle plan](../plans/operator-managed-editing-run-lifecycle.md#p0--freeze-run-identity-authority-and-failure-policy) defines acquisition and release.

The central operator owns endpoint configuration, PostgreSQL, migrations, health, authentication, access policy, backup/retention, the workspace integration, and close/retire. The project host/orchestrator owns planning, task distribution, worker coordination, validation, and any host-held lifecycle operations. Workers own their normal editing calls and host-directed retry decisions—not infrastructure.

**Transport implementation gap:** at the inspected PR revision, `patchdiff-mcp` runs an external **stdio** adapter; the FastAPI application has health routes but is not a demonstrated remote MCP endpoint. LAN v1 requires implementing and testing an authenticated network transport (Streamable HTTP is the proposed choice) that reuses existing profile-filtered MCP dispatch. Do not label LAN verification complete based on stdio tests.

## 3. Secondary topology — workstation swarm

```text
      Project orchestrator: provision and eventually stop local runtime
            |             |                  |
         Worker A       Worker B           Worker C
            |             |                  |
       stdio adapter  stdio adapter     stdio adapter
            +-------------+------------------+
                          |
                Shared PostgreSQL state
                          |
                Configured local workspace
```

Workstation orchestration may own server startup and shutdown. All worker stdio connections share the same authoritative database; they are not separate editing engines. Workstation controls establish shared-state/OCC behavior, but do **not** establish remote MCP connectivity. Local runs may also use the operator-managed database lifecycle if configured for it.

## 4. Profiles govern workspace operations

These are **existing profile catalogs**, not new LAN-specific tools:

| Profile | Worker-visible editing capabilities | Initialization and SAVE ownership |
| --- | --- | --- |
| `observed_workspace` (7 tools) | `patchdiff_initialize_target`, `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`, `patchdiff_save` | An **authorized** agent can initialize and request SAVE; workspace publication still requires the server's workspace permissions and publication checks. |
| `workspace` (5 tools) | Initialize, read, exact search, typed submit, SAVE | Same lifecycle option without structural observation. |
| `observed_v2` (5 tools) | Read, find, list scopes, observe scopes, commit bundle | Host/trusted lifecycle path initializes and performs SAVE/publication; the worker has neither tool. |
| `editor` (7 tools) | Read/find, observed or exact editing, `patchdiff_save`, replay | Host supplies an existing target. **The editor does expose SAVE**, so host-exclusive SAVE is *not* guaranteed by this profile alone. |
| `observed_editor` (4 tools) | Existing-target read/find, observe, submit observed operations | Trusted host supplies target and owns SAVE/publication. |
| `full` (18 tools) | Full lifecycle, inspection, and audit tools | Privileged host/operator role; do not automatically expose to general workers. |

The [profile catalog](../spec/profiles/index.md) defines the exact tool surface. Authenticate every supported remote MCP route and keep separate adapter negotiation state for each session. Bind that session to its authenticated principal, active run, and operator-approved profile. Reject attempts to reuse it under a different principal or run or to elevate its profile. Trusted lifecycle access uses a separately authorized path against the same database.

**`SAVE` is not server shutdown.** `patchdiff_save` checkpoints a target's database editing cycle; `sync_workspace: true` may also publish its bytes. It never, by itself, closes an operator-managed editing run, archives, prunes, or drops the database.

## 5. Normal editing sequence and file semantics

1. **Select or initialize a target.** An authorized `observed_workspace` worker may open a server-accessible path; for `observed_v2` or delegated profiles, a trusted host supplies the target ID after a separate initialization step. Reopening a bound workspace path resumes its one active target when the recorded disk baseline matches.
2. **Inspect normally.** The agent reads or searches the canonical working text and, for a structural profile, discovers and observes source scopes.
3. **Submit guarded changes.** PatchDIFF evaluates typed or observed operations against authoritative target version/hash and PostgreSQL row locks. Edits in one target submission are ordered, and the submission is atomic **per target**. A stale writer rejects and the host decides whether/how to retry with lineage.
4. **Collaborate before publication.** A peer with access to that target can observe accepted **unpublished** edits in PostgreSQL without first editing the physical file.
5. **Finalize through the authorized lifecycle.** SAVE closes the target's current editing cycle and creates a checkpoint. Set `sync_workspace: true` to request publication or `false` for a database-only checkpoint. An omitted value follows the service configuration. A host can order per-file SAVEs across a multi-file task. Each target can complete independently.
6. **Verify.** The host checks acceptance/rejection evidence and runs semantic tests, linters, Git checks, and file-byte verification as appropriate. PatchDIFF validates transaction applicability, not whether the agent's code change is correct.

PatchDIFF does not expose an alternate directory tree or require a FUSE/NFS mount. Normal source files remain ordinary files. Current managed workspace operations require a server-side POSIX-compatible root, path confinement, and drift/ownership safeguards; non-cooperating filesystem writers remain a deployment concern.

## 6. Operator-managed editing runs and whole-database retirement

An **editing run** is the operator-controlled lifetime of one dedicated PatchDIFF database and its attached active worker service. It may contain 100 edits or 1,000. It is **not** an MCP connection/session, a target editing cycle, a SAVE, or an agent's task.

A successful close fences all writers and releases the workspace lease. A successor can then use the workspace even if the old database was retained. A retained or restored run must reacquire the lease before writable reopen.

```text
OPEN (acquire workspace lease, start the dedicated DB and service)
  -> ACTIVE
  -> explicit operator CLOSE
  -> QUIESCE (gate admission, drain, fence every writer)
  -> CLOSED_PRESERVED (record the fence and publication evidence)
       -> RETAINED (live DB remains fenced)
       -> ARCHIVED_VERIFIED (verified archive and fenced live DB)
            -> RETIRED (remove live DB after recording authorization)
       -> RETIRED (acknowledge discard and record removal authorization)
```

**No in-run pruning:** the v1 design does not delete completed cycles every N SAVEs; it introduces no replay anchors, receipt stubs, archive providers, retention migrations, or changes to the transaction applier. Full replay and same-key recovery remain governed by the existing in-run contracts while the database exists. Retiring/discarding that entire database intentionally ends access to its history unless an archive is restored.

**Publication is independent of retention.** A database archive preserves durable working state, including unpublished edits. The external closure report records available SAVE receipts, disk evidence, and unknown outcomes. PostgreSQL dumps exclude ordinary files and cluster-global roles. Restoring to a different checkout can require guarded workspace reconciliation before publication. The operator must acknowledge any unpublished or unknown state before discard. Worker disconnects, unclean stops, and ordinary restarts preserve the run database. If the controller stops after an authorized database drop, recovery reconciles the recorded removal intent against the exact database identity.

See the [operator lifecycle plan](../plans/operator-managed-editing-run-lifecycle.md) for the state machine, archive verification, stop/drain behavior, and proof obligations.

## 7. LAN security and availability boundary

- Require authenticated, encrypted remote transport and enforce the Streamable HTTP Origin and protocol-version rules. Workers have only their authorized tool routes. Keep PostgreSQL, administrative, and archive credentials private.
- Authorize the principal for the run at the endpoint and enforce its fixed profile at dispatch. Treat target IDs as identifiers. Any separately authorized trusted route uses the same run database and participates in close.
- Acquire an exclusive workspace lease through the service supervisor. Register physical workspace identity, reject conflicting aliases and overlapping writable roots, and prevent stale writers from restarting after lease transfer. Existing database-local bindings do not provide cross-database fencing.
- Atomically gate admission and count admitted work through execution completion, including after client disconnect. On a drain timeout, preserve the database and prevent replacement activation until fencing succeeds.
- Keep archives encrypted/access-controlled under organizational policy. Never put database credentials or complete private transaction contents into routine benchmark summaries or public CI logs.

## 8. Verification and release claims

**Remote correctness canary.** Run **24 scored trials with eight live Antigravity workers per trial**. Trials 01–08 are workstation controls, 09–16 are remote repetition A, and 17–24 are remote repetition B. Each block uses a distinct retained run database and workspace with separate fixtures per trial. Remote workers use independent authenticated MCP sessions through the centrally operated endpoint, with the same pinned configuration for both repetitions. Record physical client placement. Each worker must perform scenario-relevant operations.

Use a coordinator barrier and record actual overlap at the hub. Verify target identity and versions, accepted and rejected attempts, retry lineage, SAVE checkpoints, raw disk bytes, and reconnect behavior against independent evidence. Keep trusted conformance checks separate from worker calls and label checks on a local verifier route as local contract evidence. The [canary plan](../plans/operator-managed-editing-run-lifecycle.md#a-lan-shared-editing-canary--24-scored-trials) assigns workers and maps the S1–S8 scenarios to the A1–A8 architecture decisions.

**Operator lifecycle verification (separate suite):** prove successful close/drain, archive and isolated restore, explicit discard with outstanding-work acknowledgement, and crash/restart recovery. Both suites are required for a production v1 claim; completing the remote canary does not require live pruning or an already implemented archive/delete helper.

Record the agreed 24-trial matrix in the canary handoff before scoring. It supersedes the earlier 32-trial proposal. Remote evidence requires actual network MCP traffic, and ordered per-target SAVEs establish per-target publication outcomes.

## 9. Implementation status and references

| Capability | Status at inspected PR head |
| --- | --- |
| Stdio MCP adapter and immutable profiles | Implemented |
| Shared PostgreSQL target authority, OCC, append-only attempts, SAVE and replay | Implemented |
| PR #27 active workspace binding, path reopen and guarded recovery | Implemented in inspected PR code; release/cutover requires its own verification |
| Authenticated remote MCP endpoint with safe admission/drain | **To implement and verify** |
| Per-editing-run database provisioning and close/archive/discard automation | **To implement and verify**; can live outside PatchDIFF runtime |
| In-run history pruning / SAVE-count compaction | **Not part of LAN v1** |
| General multi-project authorization and dynamic database routing | **Deferred** |

Sources: [MCP profiles](../spec/profiles/index.md), [workspace profile](../spec/profiles/workspace-profile.md), [trusted lifecycle](../spec/profiles/delegation-and-lifecycle.md), [MCP tools and SAVE](../spec/mcp-tools.md), [architecture decisions A1–A8](modernization-architecture.md#summary-of-decisions-a1-to-a8), [workspace quickstart](../guides/workspace-quickstart.md), [MCP Streamable HTTP specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [PostgreSQL pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html), and [pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html).
