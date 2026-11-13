# PatchDIFF LAN Hub and Editing Run Lifecycle Invariants

**Status:** Proposed LAN v1 normative invariants / acceptance contract  
**Target location:** `docs/spec/lan-hub-and-run-lifecycle-invariants.md`  
**Companions:** [LAN Reference Architecture](../papers/lan-workstation-appliance.md) · [Operator-Managed Editing Run Lifecycle](../plans/operator-managed-editing-run-lifecycle.md)  
**Source baseline:** PR [#27](https://github.com/paragon-ux/Patch-DIFF/pull/27) at `7fef376e440adf5e3fd40723f02c1c68848d20f1`

## 1. Scope and interpretation

This specification defines **what must remain true** for the proposed one-project LAN v1. It is not a statement that the remote endpoint or operator-run controller already exists. **MUST**, **MUST NOT**, and **SHOULD** express requirements; the **status** column distinguishes established PatchDIFF behavior from proposed LAN/run requirements.

Definitions:

- **Hub:** one operator-managed network MCP endpoint exposing PatchDIFF against one active run authority.
- **Editing run:** operator-controlled lifetime of one **dedicated PostgreSQL database** and its associated shared service, possibly covering many workers, MCP connections, target editing cycles and SAVEs.
- **MCP session:** an individual transport/client interaction; never a database-retirement boundary.
- **Target / working copy:** an initialized file's canonical in-flight content in PostgreSQL, with version/hash and history; not a second navigable filesystem tree.
- **Workspace publication:** the configured, authorized act of making selected working bytes available as ordinary files; when managed by PatchDIFF it is a distinct effect of `patchdiff_save(sync_workspace=true)`.
- **Retirement:** operator-authorized removal of the entire dedicated run database after safe closure. **No in-run row pruning** is defined for v1.
- **Evidence category:** **Existing** (reviewed PR contract; reverify at implementation head), **New** (required implementation), or **Operational** (must be enforced by the operator/control plane).

## 2. Topology, authority and security

| ID | Requirement | Status | Verification |
| --- | --- | --- | --- |
| **HUB-01** | For one active project/run, every authorized worker MUST access the **same logical PatchDIFF editing authority** and database through the one remote endpoint. Internal process scaling MUST NOT fork canonical target state. | New | Two or more independent sessions observe the same target ID/version/hash and shared pending accepted edits. |
| **HUB-02** | LAN deployment MUST NOT dictate workspace physical location. Server-managed workspace import/SAVE MUST only operate on an explicitly configured root accessible to the service; a client's local disk is not implicitly reachable. | Existing + Operational | Server-root and remote-client-only negative tests. |
| **HUB-03** | Each editing run MUST own a dedicated database; a new run MUST NOT silently reuse an older run's DB or request-key namespace. | New | Create/close/new-run DB identity assertions. |
| **HUB-04** | LAN v1 MUST use one operator-supervised service host and one registered writable workspace. A supervisor-controlled exclusive lease outside the run DB MUST cover all writers, reject conflicting aliases and overlapping roots, and prevent stale owner startup after handoff. | New + Operational | Competing run with a separate database and overlapping-root/alias attempts are denied. Cross-host authority transfer requires a proven old-writer fence. |
| **HUB-05** | Worker connections MUST NOT administer migrations, databases, service processes, backup/retirement or workspace configuration through their normal editing profile. | New + Operational | Permission/negative route tests. |
| **HUB-06** | Every supported remote MCP route MUST authenticate and authorize the principal for the active run. Each MCP session MUST have independent negotiation state bound to that principal, run and fixed profile. The gateway MUST enforce Streamable HTTP Origin and protocol-version rules. Worker access excludes administrative and archive credentials. | New | Reject invalid Origin or protocol-version, wrong principal, stale session/run, unauthorized targets and profile escalation. |
| **HUB-07** | A centrally operated LAN endpoint MUST NOT be claimed as implemented or benchmarked from stdio-only trials. | Evidence rule | Remote endpoint and network call traces from the actual implementation. |

## 3. Editing, profiles and ordinary-file behavior

| ID | Requirement | Status | Verification |
| --- | --- | --- | --- |
| **EDIT-01** | Agents MUST be able to use the published PatchDIFF tools to read/search and, when profile permits, observe scopes and submit guarded edits against ordinary project content without mounting a DB-backed virtual filesystem. | Existing | Actual tool catalog and file-editing workflow. |
| **EDIT-02** | Initializing a workspace path MUST reuse the active binding and its unpublished edits when the recorded disk baseline matches. Aliases of the same destination MUST reuse it or return the documented ownership conflict. Distinct directory entries, including distinct hard links, retain their documented separate identity. | Existing (PR #27) | Concurrent first-open/reopen and path identity cases. |
| **EDIT-03** | A target submission MUST validate version/hash guards against PostgreSQL authority under the documented locking rules. Same-target contenders MUST serialize; stale submissions MUST fail without altering the accepted target content. | Existing | Measured overlapping calls and target/version/rejection rows. |
| **EDIT-04** | Operations inside one accepted target transaction MUST apply in deterministic sequence and atomically **per target**. The service MUST NOT claim cross-target atomic commits or atomic multi-file publication from ordered per-file SAVEs. | Existing | Acceptance/rollback and multi-target failure tests. |
| **EDIT-05** | Within an active database, already-admitted target-linked attempts MUST retain their currently documented audit, retry-lineage, keyed-recovery and replay behavior. No retention feature may weaken those contracts while the run is active. | Existing | Lost-result retry; rejected parent lineage; historical replay. |
| **EDIT-06** | `observed_workspace` MUST expose authorized initialize/SAVE tools in addition to structural read/search/observe/commit. `observed_v2` MUST NOT expose those lifecycle tools; it depends on trusted host initialization/publication. | Existing | Immutable per-profile `tools/list` and unauthorized call rejection. |
| **EDIT-07** | The `editor` profile **does expose `patchdiff_save`** and MUST NOT be described as host-exclusive SAVE. If host-exclusive SAVE is required, deployment MUST select/enforce an appropriate narrower profile or authorization path. | Existing + Operational | Catalog and attempted SAVE tests. |
| **EDIT-08** | Model/task correctness is a host verification responsibility. An accepted transaction MUST NOT be represented as proof of semantic correctness. | Existing | Receipt validity and independent test attribution. |

## 4. SAVE, publication and file identity

| ID | Requirement | Status | Verification |
| --- | --- | --- | --- |
| **PUB-01** | SAVE MUST checkpoint the target editing cycle. `sync_workspace: true` can also publish under existing ownership and drift rules. `false` requests a DB-only checkpoint, and omission uses the configured default. SAVE never closes an editing run. | Existing + New exclusion | Test explicit publish and checkpoint-only calls and verify run history is preserved. |
| **PUB-02** | Accepted in-flight edits MUST be visible to authorized readers of the shared canonical target **before** any disk publication. | Existing | Peer read after accept, before SAVE; disk unchanged. |
| **PUB-03** | Workspace publication and PostgreSQL checkpoint outcomes MUST be reported separately; `partial`, lost response or disk drift MUST NOT be silently converted into `saved`. | Existing | Fault injection before/after file install and DB commit. |
| **PUB-04** | Close MUST preserve captured SAVE receipts, disk evidence and uncertainty in the external closure report. An archive may contain unpublished durable working state. Archive and restore alone leave ordinary files unchanged. | Operational | Close and restore an unpublished target, inspect the report and compare disk. |
| **PUB-05** | Before discard, the operator MUST see confirmed published, unpublished, unknown and host-owned classifications as applicable and explicitly acknowledge loss of unpublished or uncertain state. A missing receipt or unresolved disk/checkpoint outcome MUST remain unknown. | New | Discard without acknowledgement is denied. Test a partial SAVE and a lost reply. |
| **PUB-06** | After restore on a different filesystem/checkout, operations MUST honor existing workspace-root, binding, path identity, disk baseline and guarded recovery rules rather than silently rebinding. | Existing + Operational | Changed root/device and disk drift restore tests. |

## 5. Run closure, archive and database retirement

| ID | Requirement | Status | Verification |
| --- | --- | --- | --- |
| **RUN-01** | **Only an explicit, authenticated operator close** MAY begin a run's retirement workflow. Worker disconnects, MCP termination, SAVE, number of edits, normal process exit, crash and machine restart MUST NOT authorize retirement. | New + Operational | Crash/restart, disconnect, repeated SAVE negative tests. |
| **RUN-02** | Close MUST atomically gate admission and track already-admitted work until completion, even across disconnect. Close MUST drain and fence all writers, including trusted paths, and revoke run-scoped application access independently of archive access. An unproven fence MUST preserve the DB and block replacement activation. | New | Admission race, disconnected in-flight request, surviving connection and bypassing writer. |
| **RUN-03** | Replacement activation MUST wait for a durable writer fence and lease release. A fenced retained DB can coexist with a successor. Writable reopen or restore MUST reacquire the lease and fail while a successor owns it. | New + Operational | Block dual activation before close, allow successor after fenced retain, deny stale-run reopen. |
| **RUN-04** | An interrupted close MUST preserve the original DB before the authorized drop. If interrupted after drop, reconcile the original's absence against the durable removal intent. If the original still exists, require explicit operator retry and recheck the fence. Never infer authorization or delete a replacement DB. | New | Kill controller before and after drop, before the outcome receipt. Test unexpected DB identity. |
| **RUN-05** | Retain MUST preserve replay and keyed recovery when a compatible run is reopened with operator approval and the current writer lease. | Operational | Reopen, replay and recover saved request keys. |
| **RUN-06** | Archive-and-retire MUST verify a complete run dump through isolated restore before source removal. Verify the archive hash, schema/migration revision, all durable application-table row counts and primary-key-ordered content digests, replay for every target, and representative exact-key recovery. Failure or uncertainty MUST preserve the original. | New | Restore unpublished state, compare all evidence, and verify source survives damage or restore failure. |
| **RUN-07** | `discard` MUST require explicit operator approval and acknowledgement that unpublished edits and DB-only history become inaccessible, and MUST use the same safe drain/fence as archival. | New | Reject discard without acknowledgement; no active writers remain. |
| **RUN-08** | Before drop, persist an operator-authorized removal intent outside the DB. It MUST identify the run, exact PostgreSQL deployment and DB identity, disposition, and verified archive identity/hash or discard acknowledgement. Persist the observed outcome without secrets. | New | Inspect authorization and final receipt around the destructive boundary. |
| **RUN-09** | A new run MUST start with a new DB/history. Previously published ordinary files MAY be opened as new targets; an old run's unpublished edits/keyed outcomes MUST NOT be assumed to exist in the new run. | Operational | New run import versus old archived/retained history. |
| **RUN-10** | Database archival MUST NOT be represented as backup of external workspaces, PostgreSQL cluster globals, deployed code, or platform dependencies. Their preservation remains under operator policy. | Operational | Archive-manifest inspection and restore prerequisites. |
| **RUN-11** | Operators MAY choose archive retention duration, encrypted storage, ordinary `pg_dump`/backup integration and final DB disposition; PatchDIFF MUST NOT hardcode a SAVE threshold or force archival when the operator elects discard. | New scope rule | Policy variants work without editing-runtime changes. |

### State survival matrix

| Event / outcome | Database working state and in-run history | Published ordinary files | Future recovery |
| --- | --- | --- | --- |
| Worker disconnect / MCP session close | **Preserved** | Unchanged by disconnect | Reconnect to same active run |
| Unexpected service stop / restart | **Preserved** (subject to normal DB durability) | May have a partial/unknown SAVE requiring reconciliation | Operator restarts and inspects same DB |
| Normal target `SAVE` | **Preserved**; target checkpoint/cycle rotate | Only if separately requested/authorized | Normal in-run replay and keyed recovery |
| Operator close → retain or archive with live DB kept | **Preserved** in a fenced live DB, with archive if verified | Unchanged by retention action | Writable reopen requires lease reacquisition and no current successor owner. |
| Operator close → verified archive and DB retire | **Preserved in archive**, live DB removed | **Not included in DB dump** | Restore DB, then reconcile workspace as needed |
| Operator close → acknowledged discard | **Lost with discarded DB** | Existing published bytes remain | Fresh run can reinitialize from existing files, not recover discarded history |
| Failed close before authorized removal, or failed archive verification | **Original DB preserved** | Unchanged by retirement attempt | Inspect failure and retry under operator control. Hold the workspace lease if the fence is unproven. |
| Interrupted removal with durable authorization | Original exists or was already dropped | Unchanged by retirement attempt | Reconcile the exact DB identity and removal intent. Preserve an existing original pending explicit retry. |

## 6. Evidence boundaries and acceptance gates

| ID | Requirement | Status | Verification |
| --- | --- | --- | --- |
| **EVD-01** | Report **24 scored trials** with eight live Antigravity workers performing relevant calls per trial. Use eight workstation controls and two independent eight-trial remote blocks, each with a distinct retained run DB/workspace and independent trial fixtures. Record actual placement and model/build. | Planned | Frozen trial manifest, worker activity and actual run logs. |
| **EVD-02** | Remote trials MUST establish actual authenticated network MCP sessions and hub-side request overlap. Verify target authority, retries, publication and reconnect behavior independently. Missing workers, absent required overlap or transport fallback cannot pass. | Planned | Request intervals, receipts, DB and byte oracles, and pass/fail/blocked/invalid rows. |
| **EVD-03** | Operator close/drain, archive/restore, retain/reopen, discard and unclean-stop recovery MUST be verified in a **separate operator test suite**, not silently counted as worker trials. | Planned | Independent operator lifecycle test reports. |
| **EVD-04** | Map S1–S8 workloads to A1–A8 decisions. Attribute trusted checks separately from the eight workers. Use a separately authorized trusted remote route if provided. Label authorized local verification as local contract evidence. | Planned | Traceability matrix, trusted interface and negative worker access checks. |
| **EVD-05** | The concurrency canary MAY proceed with the database retained as soon as the real gateway is ready. A **production LAN v1** claim requires passing both the concurrency suite and lifecycle suite. No test may claim live pruning, multi-project authorization, or atomic multi-file SAVE without implementing and verifying them. | Planned | Release evidence and explicit limitations. |

### Architecture decision traceability (source A1–A8, not workload names)

| Decision | Evidence obligation in this architecture |
| --- | --- |
| **A1** Server authority/host-owned retry | S2/S3/S8 trace authoritative reads and a host-selected retry. |
| **A2** Typed transactions | Trusted conformance exercises tx/1, tx/2 and tx/3. Worker-profile bundle calls establish observed-bundle behavior. |
| **A3** Asserted/derived metadata | Trusted conformance checks intent attribution and derived accepted ledger facts. |
| **A4** PostgreSQL authority | S2/S3/S8 show one canonical chain, row-lock/OCC behavior, and shared state after reconnect. |
| **A5** SAVE/checkpoints/history APIs | S6/S7 show checkpoint/cycle semantics and independent publication outcomes. Trusted conformance checks bounded history pagination. |
| **A6** Required guards/idempotency | S2/S4/S8 cover stale guards, keyed recovery and parent-linked retries. Ordinary workspace open resumes by path. |
| **A7** Stage-based validity | Trusted conformance checks the reached validation stage. The host owns semantic correctness. |
| **A8** Honest evaluation | Record pinned revisions and report live-worker, trusted local/remote, and operator evidence separately. |

## 7. Compatibility and status notes

- The **stdio** MCP adapter, existing profile catalogs, per-target transaction processing, SAVE, replay, and PR #27 workspace binding/recovery are source-grounded at the inspected revision. They must be retested against the final implementation commit.
- An authenticated **remote** MCP gateway, operator run registry, quiescence gate, exclusive cross-run workspace writer lease, archive-verify-retire commands, and lifecycle evidence are **not yet verified as implemented**.
- The prior SAVE-count pruning proposal is superseded for LAN v1. This contract defines **no pruning before operator close and no pruning within an active database**.
- For details see [existing target/host profiles](profiles/index.md), [workspace profile/reconciliation](profiles/workspace-profile.md), [MCP tools and SAVE](mcp-tools.md#patchdiff_save), [modernization architecture A1–A8](../papers/modernization-architecture.md#summary-of-decisions-a1-to-a8), [PostgreSQL archive/restore](https://www.postgresql.org/docs/16/app-pgdump.html), and [MCP remote transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).
