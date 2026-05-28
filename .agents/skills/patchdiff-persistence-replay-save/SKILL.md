---
name: patchdiff-persistence-replay-save
description: Use when implementing or reviewing Postgres persistence, Docker Compose development, Alembic migrations, append-only logs, commit guards, editing cycles, SAVE, snapshots, and deterministic replay.
---

# PatchDIFF Persistence, Replay, And SAVE Skill

## Storage Backend

The MVP uses Postgres.

Do not use SQLite as the MVP persistence backend.

SQLite may be used only for isolated pure runtime experiments that do not exercise persistence, locking, migrations, SAVE, or replay.

Local development must use Docker Compose with a pinned Postgres version.

Persistence must preserve cloud-equivalent semantics:

- atomic commit
- row-level locking
- target version/hash guards
- append-only PDCP log
- accepted-only manifest ledger
- append-only snapshots
- deterministic replay
- editing-cycle support for SAVE

## Required Tables

Required Postgres tables:

- `users`
- `projects`
- `project_memberships`
- `cloud_target_files`
- `current_pdcp_files`
- `append_only_pdcp_logs`
- `append_only_manifest_ledger`
- `target_snapshots`
- `editing_cycles`

Use PDCP terminology.

Avoid “program file” terminology unless explicitly aliasing it to declarative PDCP transaction files.

## cloud_target_files

Stores current canonical target state.

Required fields include:

- `target_file_id`
- `project_id`
- `filename`
- `content_type`
- `current_content`
- `current_hash`
- `version`
- `active_editing_cycle_id`
- `created_at`
- `updated_at`

The target row is the authoritative current state.

## current_pdcp_files

Stores active-session pending/display PDCP state.

Required fields include:

- `pdcp_file_id`
- `target_file_id`
- `content`
- `status`
- `created_at`
- `updated_at`

This table is not authoritative protocol history.

It may be overwritten.

Replay must never depend on `current_pdcp_files`.

## append_only_pdcp_logs

Stores accepted and rejected PDCP attempts.

Required fields include:

- `pdcp_log_id`
- `target_file_id`
- `editing_cycle_id`
- `pdcp_content`
- `protocol_version`
- `runtime_version`
- `status`
- `failure_reason`
- `failure_detail`
- `failed_change_id`
- `before_hash`
- `after_hash`
- `created_at`

Optional regeneration-linkage fields:

- `parent_pdcp_log_id`
- `regeneration_attempt`
- `regeneration_source`

This table is append-only.

Rejected attempts must remain visible.

Accepted attempts must not erase rejected attempts.

## append_only_manifest_ledger

Stores accepted semantic manifest entries only.

Required fields include:

- `manifest_entry_id`
- `target_file_id`
- `editing_cycle_id`
- `pdcp_log_id`
- `change_id`
- `intent`
- `input_state`
- `output_state`
- `affected_region`
- `user_visible_change`
- `risk`
- `created_at`

This table is append-only.

Only accepted PDCP transactions append manifest ledger entries.

Rejected PDCP manifests must not be appended to the accepted manifest ledger.

## target_snapshots

Stores initial snapshots and SAVE checkpoints.

Required fields include:

- `snapshot_id`
- `target_file_id`
- `editing_cycle_id`
- `content_hash`
- `content`
- `version`
- `reason`
- `created_at`

This table is append-only.

Snapshots may accelerate replay later, but the accepted PDCP log remains the authoritative operational history.

## editing_cycles

Stores active and closed editing cycles.

Required fields include:

- `editing_cycle_id`
- `target_file_id`
- `status`
- `started_at`
- `closed_at`
- `save_snapshot_id`

Allowed status values:

- `active`
- `closed`

Each target must have exactly one active editing cycle.

## Atomic Accepted Commit

Accepted PDCP commit must be one Postgres transaction.

Required accepted flow:

```text
BEGIN
lock target row FOR UPDATE
verify expected version/hash
simulate PDCP in memory
update target content/hash/version
insert accepted PDCP log
insert accepted manifest ledger entries
COMMIT
```

No committed target state may exist without a corresponding accepted PDCP log entry.

No accepted manifest ledger entry may exist without a corresponding accepted PDCP log entry.

## Rejected Transaction Persistence

Rejected PDCP flow:

```text
BEGIN
lock target row if target exists
insert rejected PDCP log if possible
do not update target
do not insert manifest ledger entries
COMMIT
```

Every rejected PDCP should record:

- `status = rejected`
- `failure_reason`
- `failure_detail`
- `failed_change_id` when applicable
- `before_hash`
- `after_hash = null`

Rejected PDCPs must not mutate the target.

Rejected manifests must not be appended to the accepted manifest ledger.

## Row-Level Locking

Use Postgres row-level locking for same-target isolation.

Recommended lock behavior:

```sql
SELECT *
FROM cloud_target_files
WHERE target_file_id = :target_file_id
FOR UPDATE;
```

Do not allow two commits to the same target to interleave.

Different targets should be able to commit concurrently.

## Commit Guard

Submit requests should include at least one of:

- `expected_target_version`
- `expected_current_hash`

Inside the database transaction, verify that the stored target still matches the version or hash used during validation.

Failure behavior:

```text
request expected_target_version mismatch -> target_version_mismatch
request expected_current_hash mismatch -> target_hash_mismatch
stored target changes between validation and commit -> target_diverged
```

## Append-Only Rules

The following are append-only:

- PDCP log
- manifest ledger
- target snapshots
- editing cycles

Corrections must be represented by new transactions, new attempts, or new cycles, not by mutating history.

Do not delete manifest ledger rows during SAVE.

Do not delete PDCP log rows during SAVE.

Do not make replay depend on mutable display state.

## SAVE Semantics

SAVE is checkpoint and active-context compaction.

SAVE does not mean “write target changes.” Accepted PDCP transactions already update the target.

SAVE must:

- snapshot current target
- preserve PDCP log
- preserve manifest ledger history
- close the current editing cycle
- create a new active editing cycle
- make future default manifest-ledger reads return only the new active cycle
- optionally export current target through MCP

SAVE must not delete append-only history.

## SAVE Failure

If SAVE fails:

- target remains canonical
- current editing cycle remains active
- manifest ledger remains intact
- PDCP log remains intact
- no new active cycle is created

Never clear active context before snapshot success.

## Replay Inputs

Replay reconstructs target state from:

```text
initial canonical target
+ ordered accepted PDCP log entries
```

Replay must not depend on:

- `current_pdcp_file`
- manifest ledger
- snapshots
- current materialized target

Snapshots may accelerate replay, but they are not authoritative protocol history.

## Replay Algorithm

```text
1. Load initial canonical target content.
2. For each accepted PDCP log entry in order:
   a. parse PDCP using its protocol_version
   b. protocol-validate PDCP
   c. apply transaction deterministically against replay buffer
   d. compute hash
   e. compare computed hash to logged after_hash
3. If all hashes match, output reconstructed target.
```

If computed hash differs from logged `after_hash`, return `replay_hash_mismatch`.

Runtime application and replay must share the same parser, canonicalizer, matcher, disambiguator, and applier behavior.

If runtime and replay behavior differ, treat that as a bug.

## Docker Compose And Migrations

The project should include Docker Compose for deterministic local Postgres.

Alembic migrations should define the schema.

Integration tests should run against Postgres, not SQLite.

Do not claim persistence correctness from SQLite tests.
