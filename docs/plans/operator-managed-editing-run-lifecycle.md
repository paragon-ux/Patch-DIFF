# Operator-Managed Editing Run Lifecycle — LAN v1 Implementation Plan

**Status:** Proposed implementation plan (not implemented)  
**Target location:** `docs/plans/operator-managed-editing-run-lifecycle.md`  
**Scope:** One team/project, one centrally operated remote MCP endpoint, one dedicated PostgreSQL database per editing run  
**Related:** [LAN Reference Architecture](../papers/lan-workstation-appliance.md) · [LAN Hub and Editing Run Invariants](../spec/lan-hub-and-run-lifecycle-invariants.md)  
**Source baseline:** [PR #27](https://github.com/paragon-ux/Patch-DIFF/pull/27) at `7fef376e440adf5e3fd40723f02c1c68848d20f1`

## 1. Decision and rationale

An **editing run** is a shared, operator-owned deployment lifetime. It is not an individual MCP protocol session, a `SAVE` editing cycle, or a worker task. The operator decides when a run ends, regardless of number of edits or SAVEs. A dedicated PostgreSQL database is the authoritative in-flight working state for all workers in that run.

This plan replaces the previous SAVE-triggered pruning / checkpoint-replay-anchor proposal. **LAN v1 never prunes history while a run is active.** The operator closes a run, quiesces all writers, then chooses to retain, archive and optionally remove, or discard the whole database. This reuses standard PostgreSQL utilities and leaves PatchDIFF's schema, replay path, OCC, request-key identity, and retry lineage unchanged during the run.

**Implementation priority:** remote MCP transport and authentication are the principal new product engineering tasks; database retirement is a smaller **operator-side workflow**. The 24-trial remote correctness canary may run when the real endpoint is ready, with the database retained; the lifecycle suite is a separate production gate.

### Explicit non-goals

- No delete/prune trigger from `patchdiff_save`, N SAVEs, worker disconnect, MCP session termination, ordinary shutdown, or crashes.
- No partial-history deletion, replay anchors, replacement of the initial upload snapshot, compact request receipts, cycle-level archival, storage-schema migration, or new worker-facing retention tools.
- No simultaneous project tenancy in a shared database, no per-request database routing, no per-file cross-target atomic SAVE, no guarantee that database restoration reproduces external workspace files.
- No operator policy imposed on archive retention duration, backup schedule, encryption vendor, or the physical location of workspace data.

## 2. Concrete ownership model

| Actor | Responsibility | Prohibited action |
| --- | --- | --- |
| **Central operator** | Provision/run/stop endpoint and DB, choose profile/workspace, migrate DB, authorize users, inspect end state, archive/discard | Hand database-retirement rights to workers |
| **Project host/orchestrator** | Coordinate agents, verify edits, invoke trusted initialization/SAVE if required by profile | Retire database without explicit operator authorization |
| **Worker / MCP client** | Authorized read/search/scope/commit; initialize and SAVE only if selected profile permits | Install, migrate, terminate, archive, or drop shared database |
| **PatchDIFF core** | Guarded target edits, OCC, durable attempts, SAVE/checkpoints, replay, workspace bindings | Infer operator close from an editing action |
| **Run controller (proposed)** | Operator-authenticated open/close, admission gate, drain, archive verification and metadata | Modify transaction outcomes or prune active history |

One operator-supervised service host owns the registered writable workspace. The worker endpoint binds one active run database to one operator-approved worker profile. Trusted lifecycle access uses a separately authorized path to the same database and participates in the same admission and shutdown controls. Use a run-scoped application role with independently revocable connection access. The operator archive role is separate.

## 3. State machine and allowed transitions

| State | Worker admission | Database and writer authority | Allowed next state |
| --- | --- | --- | --- |
| `PREPARING` | Closed | Provision or check the dedicated DB after acquiring the workspace lease | `ACTIVE` or `FAILED_PRESERVED` |
| `ACTIVE` | Open to authorized sessions | Current run holds the writer lease | `QUIESCING` on explicit operator close, `INTERRUPTED` on crash |
| `QUIESCING` | Closed | Keep the lease while draining and fencing all writers | `CLOSED_PRESERVED` after recording the fence, or `FAILED_PRESERVED` |
| `CLOSED_PRESERVED` | Closed | Fenced live DB, workspace lease released | `RETAINED`, `ARCHIVING`, or `REMOVAL_AUTHORIZED` after discard acknowledgement |
| `RETAINED` | Closed | Fenced live DB | Operator-authorized reopen through `PREPARING` and lease reacquisition, or a later disposition |
| `ARCHIVING` | Closed | Fenced live DB | `ARCHIVED_VERIFIED` or `FAILED_PRESERVED` |
| `ARCHIVED_VERIFIED` | Closed | Verified archive and fenced live DB | Retain both, or `REMOVAL_AUTHORIZED` with operator approval |
| `REMOVAL_AUTHORIZED` | Closed | Exact removal intent persisted. The original DB may exist or already be gone after interruption. | `RETIRED` after verified removal, or stop for operator retry or investigation |
| `INTERRUPTED` / `FAILED_PRESERVED` | Closed | Preserve any original DB. Hold the workspace lease if the writer fence is unproven. | Operator recovery through `PREPARING` or explicit close retry |
| `RETIRED` | Closed | Original live DB absent. A verified archive remains if selected. | Historical access through a separately restored DB if an archive exists |

These are operator states. Keep the run registry outside the database being retired. Durably record the run ID, exact database identity, endpoint, workspace identity, runtime revision, lease owner, fence, close decision, artifact locations, and removal intent and outcome.

A successor may acquire the workspace lease as soon as the previous writer fence is durable and the lease is released, independent of data disposition. A retained or restored run needs the same lease and current writer authority before accepting writes. Recovery must fail while another run owns it. Only an explicit authenticated operator close begins retirement. A crash, worker disconnect, or restart preserves the database before any authorized drop.

## 4. Implementation phases

### P0 — Freeze run identity, authority and failure policy

- Give each run a unique ID and dedicated database name. Record the PostgreSQL deployment and database identity used for destructive checks. Record the endpoint, profile, and workspace registration without secrets.
- Register one physical writable workspace per supervised LAN v1 service host. Check the canonical resolved root and physical identity before provisioning. Reject a second registration for an alias or overlapping writable root. Use the registered identity to acquire an exclusive writer lease outside the run DB. Only the current owner may start a writer. Fence the prior runtime and invalidate its owner identity before handing over the lease. Cross-host failover requires a proven fence before transfer.
- Use an operator CLI or supervisor. Use a run-scoped application credential with revocable access to its dedicated database, separate from operator archive privileges. The example commands are illustrative.

### P1 — Provision and activate one editing run

1. Validate the registered physical workspace and acquire its exclusive writer lease, including for writable reopen or restore. Bind writer startup and restart to the current lease owner.
2. Provision a uniquely named, dedicated PostgreSQL database using operator credentials, or explicitly reopen the recorded original run DB after checking its identity. Give the runtime only the run-scoped credentials it needs.
3. Apply the matching migrations before enabling admission, with old writers drained for upgrades. PR #27 migration `0007` has a cutover requirement.
4. Start the endpoint with existing profile-filtered dispatch. Require authentication on every supported route. Check the Streamable HTTP Origin and protocol-version rules. Maintain separate negotiation state per MCP session and bind it to the authenticated principal, active run, and fixed profile. Reject mismatched principal/run, stale session, or profile elevation. Keep any trusted access separately authorized.
5. Confirm the intended run, database identity, runtime revision and workspace lease owner. Persist `ACTIVE` before opening admission.

Proposed operator workflow (names intentionally **not** implemented):

```text
patchdiff-run open --project PROJECT --workspace WORKSPACE --profile observed_workspace
# → run_id, database identity, endpoint identity, ACTIVE
```

### P2 — Build the safe close/admission barrier

On **explicit** operator close:

1. Persist authenticated close intent. Gate new admissions and register in-flight work under the same synchronization boundary. The admission gate must close even if the listener remains up for status.
2. Drain previously admitted calls and transactions, including through trusted lifecycle paths. Count a disconnected client's call until it actually completes. Stop all writer paths, including alternative stdio adapters and sidecars.
3. If drain times out or fencing fails, enter `FAILED_PRESERVED`. Preserve the database and workspace lease, block replacement activation, and require operator recovery.
4. Stop the supervised runtime and dispose its pools. Revoke run-specific application connection access independently of archive access and verify existing writer sessions have ended. Also verify that stale processes cannot restart or publish files under the old lease.
5. While the lease is held, generate the external finalization report from the quiescent DB and filesystem. Persist the fence and `CLOSED_PRESERVED` before releasing the workspace lease. A later archive or removal concerns only this fenced database.

A `pg_dump` snapshot alone does **not** substitute for the admission/drain barrier: PostgreSQL can create consistent dumps while the application is still operating, but the run would not be demonstrably final.

### P3 — Review publication independently of retirement

- Record each target as **confirmed published**, **unpublished**, **unknown**, or **host-owned**. Use accepted version/hash, checkpoint and cycle state, captured SAVE receipts, and raw disk digests when available. Keep disk and checkpoint outcomes distinct. Missing receipts and unresolved publication state stay unknown.
- Use the [workspace reconciliation procedure](../spec/profiles/workspace-profile.md#decide-what-to-do-after-a-failure) for a partial SAVE or lost reply. Record the evidence and uncertainty outside the run database. A dump preserves durable DB state and can contain unpublished working bytes. It cannot reconstruct a lost response or publish those bytes.
- Preserve or archive unpublished and unknown state when the operator chooses. Before discard, show the finalization report and require explicit acknowledgement of the possible loss. Close does not publish targets automatically. Host-managed targets may use an external publication workflow.
- The report records publication evidence. The host remains responsible for repository and semantic validation.

### P4 — Archive the whole database, verify restore, optionally retire

1. With the original DB fenced, record its schema and migration revision. For each durable PatchDIFF application table, record the row count and SHA-256 over canonically encoded rows in primary-key order. Capture replay expectations for every target and representative keyed outcomes. Produce a complete custom-format archive outside the workspace and live DB.
2. Record the archive hash, run and database identities, runtime revision, PostgreSQL version, migration revision, workspace reference, and external finalization report. Store the archive and its verification records under operator access controls.
3. Restore into an isolated, empty verification database using compatible PostgreSQL roles, extensions and runtime. Use `pg_restore --exit-on-error` and keep the worker endpoint disconnected from the verification DB.
4. Compare schema and migration revision, all application-table row counts and content digests, replay results for every target, and representative exact-key recovery. Run recovery probes after the equivalence checks against the isolated restore. Verify historical DB state independently of writable workspace reconciliation.
5. Preserve the original on any archive, restore, or equivalence failure. Enter `ARCHIVED_VERIFIED` only after all checks pass.
6. Before removal, persist `REMOVAL_AUTHORIZED` outside the run database with the exact PostgreSQL deployment and database identity, run ID, disposition, operator authorization, and verified archive identity and hash. Recheck the original identity, closed writer fence and current authorization before drop. Record `RETIRED` after confirming the original is gone.

Illustrative PostgreSQL primitives (operator chooses secure DSNs and storage; **not** a production-ready script):

```bash
pg_dump --format=custom --file="$ARCHIVE" --dbname="$RUN_DSN"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
createdb --template=template0 "$VERIFY_DB"                   # separate admin connection
pg_restore --exit-on-error --dbname="$VERIFY_DB" "$ARCHIVE"  # isolated restore
# Compare all durable table digests, replay every target, and check keyed recovery.
# Persist exact removal intent before an authorized drop.
```

`pg_dump` excludes cluster-wide role/tablespace definitions and does **not** capture the external workspace. Organization backup processes must supply required globals and real-file backups. A restored DB contains recorded workspace identities and disk baselines; resuming against a different checkout/device may require the current guarded recovery and workspace path reconciliation rather than immediate `SAVE`.

### P5 — Discard and retain policies

- **Retain.** Preserve the fenced DB. A new run may use the workspace after lease release. A retained run can reopen for writes only after operator approval and lease reacquisition.
- **Discard.** Show the external finalization report and require explicit acknowledgement of the loss of DB-only history, unpublished edits, and unknown publication state. Apply the same drain/fence checks and durable removal-intent record as archival. Bind the acknowledgement to the exact run and database.
- **Archive and retire.** Apply P4. The operator may also keep the fenced live copy after verifying the archive.

Proposed operator interface:

```text
patchdiff-run close RUN_ID --policy retain
patchdiff-run close RUN_ID --policy archive-and-retire
patchdiff-run close RUN_ID --policy discard --acknowledge-data-loss
```

These examples sketch the interface. Either removal policy needs explicit operator authorization for the exact run and database.

### P6 — Crash, interruption and restore behavior

- Worker disconnect leaves peers active and does not authorize retirement. Track admitted calls until they finish.
- A gateway/runtime crash or host restart leaves the database intact. An operator can recover the same run after checking its identity, compatible runtime, workspace state and lease ownership.
- Before the destructive boundary, interruption or uncertainty preserves the original database. During recovery, consult the durable removal intent and inspect the recorded database identity. If an authorized drop succeeded, record `RETIRED` without issuing another drop. If the original still exists, preserve it pending explicit operator retry and recheck the fence. Missing intent, uncertain identity, or a replacement at the recorded name requires operator investigation. Never touch the replacement.
- Restore into a separate database. Keep historical read, replay and export available under authorized access. Writable recovery requires the workspace lease and existing path, binding and baseline guards. A changed root, device or checkout may require the documented reconciliation or export to a separate destination.

### P7 — Independent tests, production rollout and observability

Test all state transitions, error paths, permissions, and failure points before production release. Record operational durations and archive sizes but do **not** make unrelated token or performance claims from the correctness canary.

## 5. Verification plan: two independent evidence groups

### A. LAN shared-editing canary — 24 scored trials

Use 01–08 for workstation controls, 09–16 for remote repetition A, and 17–24 for remote repetition B. Each block gets one retained run database and a fresh workspace. Use independent fixtures per row. Fence remote run A before starting B. Both remote repetitions use the same pinned configuration and eight independent authenticated sessions through the real network MCP endpoint. Record client placement and actual model/build. Eight live Antigravity workers perform scenario-relevant calls in every row. The coordinator and independent verifier are separate.

| Scenario | Eight-worker allocation and required outcome |
| --- | --- |
| S1 Disjoint CRUD | Eight workers on eight paths open, read, update and remove content through guarded edits. Verify overlapping work, exact bytes and independent target/version chains. Attribute physical file removal, if tested, to a trusted fixture actor. |
| S2 Contended CRUD | Two groups of four, each with three same-version writers and one reader. Race updates and guarded content removal. Verify one applicable winner per round, stale rejections, coherent reads and a host-selected retry using fresh guards and lineage. Capture row-lock wait or equivalent transaction ordering. |
| S3 Concurrent and repeated open | Two groups of four race first open on two paths, then reopen after an unpublished edit. Verify one binding and initial snapshot per path, peer visibility and unchanged disk before publication. |
| S4 Interrupted initialization and lost reply | One group of four exercises ordinary open interrupted before commit and a lost reply after commit. Reopen by path and verify one active target. The other group exercises lost response from guarded workspace recovery and retries the same key to verify one successor. Independently verify each commit boundary. |
| S5 Path identity | Four pairs test separator aliases, a migrated spelling or supported case alias, distinct case-sensitive entries, and hard links. Verify the documented reuse, ownership conflict, or distinct history. Test overlapping roots separately through a trusted verifier with the same authority. Record unsupported filesystem cases. |
| S6 Dirty worktrees | Two groups of four edit real tracked and untracked fixtures with pre-existing changes and controlled disk drift. Verify canonical bytes, explicit drift outcomes, final publication bytes and exact unrelated Git and file deltas. |
| S7 SAVE and publication race | Two groups of four exercise a real destination change and the file-installed/checkpoint-uncertain boundary. Verify no clobber and reconcile raw bytes, receipt, checkpoint and cycle independently. Set `sync_workspace` explicitly in test calls. |
| S8 Disconnect and recovery | Four pairs exercise disconnect with peer progress, a stale guard, denied access, and disk drift. Use a profile-denied tool call for the workstation negative control and unauthenticated or stale-run access for the remote negative control. Reconnect to the same pending canonical state and recover a lost mutation reply by exact key with one terminal outcome. |

Freeze the fixtures, worker assignments, allowed outcomes, barriers and fault points before scoring. Use hub-side request intervals to prove overlap. Verify target IDs, versions, canonical hashes, bindings, attempt rows, retry keys and lineage, checkpoints and cycles, raw disk bytes and Git state independently. Report each row as pass, fail, blocked or invalid. A missing worker, absent required overlap, or remote transport fallback cannot pass. Keep internal evidence out of GitHub. The agreed 24 trials supersede the earlier 32-trial proposal.

Map S1–S8 to A1–A8 per the [invariants](../spec/lan-hub-and-run-lifecycle-invariants.md#architecture-decision-traceability-source-a1a8-not-workload-names). In every block, use a separately attributed trusted conformance check for tx/1–3, derived ledger facts, history pagination, and stage-based validity. For remote blocks, use a separately authorized trusted network path if provided. Otherwise use an authorized local verifier at the same pinned runtime and label it local contract evidence. Worker credentials cannot access the trusted profile.

### B. Operator run-lifecycle suite — separately scored

| Test | Expected evidence |
| --- | --- |
| Open and denied worker administration | Dedicated DB, migration head, recorded run and endpoint identity, authorized worker profile, rejected admin access |
| Close/admission race | Hold a previously admitted call, close admission, reject new calls and drain the admitted call before the fence |
| Disconnected in-flight request | Observe a request continue after client disconnect. Close waits for its actual completion, and peers progress before close. |
| Unfenced trusted writer or surviving DB session | Attempt reconnect from the old service identity. Preserve the DB and block replacement activation until the process, connection and workspace authority are fenced. |
| Unclean stop and recovery | Original run DB remains. Restart under authorized recovery without implicit close. |
| Archive and isolated restore | Preserve unpublished work. Compare archive hash, schema, all durable table digests, replay for every target and representative keyed recovery. |
| Archive or restore failure | Corrupt the archive or force restore failure. Verify source retention and explicit failure state. |
| Partial or uncertain SAVE at close | Inspect DB and actual disk bytes separately. Report unresolved evidence and reject discard without acknowledgement. |
| Discard and interrupted removal | Reject missing acknowledgement. Interrupt immediately before and after drop, before final receipt. Verify original identity, disposition, external receipt and that a replacement DB is untouched. |
| Retain, reopen and replacement | Confirm keyed recovery after authorized reopen. Start a successor only after the old fence, then deny the retained run's writable reopen. |
| Changed workspace after restore | Verify historical read/replay/export and enforced workspace identity, binding and baseline guards before writable use. |

**Production evidence gate:** both A and B pass at pinned revisions, with failures, timeouts, negative cases and independent verifier attribution preserved. **Concurrency evidence may proceed before B is complete**, but do not claim full production lifecycle readiness until B passes. No claims about in-run pruning or multi-project tenancy are part of this gate.

## 6. Completion checklist and deliverables

- [ ] Operator-owned run registry, dedicated-DB naming and exclusive workspace writer lease
- [ ] Authenticated remote MCP service, configured worker profile and fail-closed admission gate
- [ ] Provision/migrate/ready flow with matching run ID and DB identity
- [ ] Close, drain and fence flow with durable authorized removal intent and restart reconciliation
- [ ] Publication reconciliation report and explicit operator policy selection
- [ ] Whole-DB archive and isolated restore verified by complete durable table digests, every-target replay and representative keyed recovery
- [ ] Approved retain, archive-and-retire, and discard paths with recorded external receipts
- [ ] Evidence for all 24 remote/workstation canary trials and independent lifecycle tests
- [ ] Release docs, restore runbook, security controls, known limitations and rollback plan

## 7. Primary source contracts

- [PatchDIFF PR #27](https://github.com/paragon-ux/Patch-DIFF/pull/27); [MCP profiles](../spec/profiles/index.md); [workspace profile and partial SAVE reconciliation](../spec/profiles/workspace-profile.md); [SAVE tool contract](../spec/mcp-tools.md#patchdiff_save); [workspace quickstart/cutover](../guides/workspace-quickstart.md); [test matrix](../benchmarks/test-matrix.md).
- [PostgreSQL 16 pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html); [pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html); [database drop](https://www.postgresql.org/docs/16/sql-dropdatabase.html); [cluster-wide backups](https://www.postgresql.org/docs/16/app-pg-dumpall.html).
- [MCP Streamable HTTP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports). Version selection and future protocol compatibility are operator implementation decisions; do not assume that an MCP network gateway already ships.
