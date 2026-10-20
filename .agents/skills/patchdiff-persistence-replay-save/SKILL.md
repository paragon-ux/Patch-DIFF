---
name: patchdiff-persistence-replay-save
description: Use when implementing, reviewing, or testing Postgres persistence, Docker Compose setup, Alembic migrations, append-only logs, row-locking concurrency guards, editing cycles, SAVE snapshots, and profile-dispatched deterministic replay.
---

# PatchDIFF Persistence, Replay, and SAVE Skill

## Persistence Architecture

Postgres is PatchDIFF's single source of truth for managed target content, transaction attempts, manifest history, and snapshots.

Target mutations require row-level locking:

```text
Incoming submit
  -> BEGIN TRANSACTION
  -> SELECT ... FROM cloud_target_files WHERE target_file_id = :id FOR UPDATE
  -> Check client_request_id idempotency in append_only_pdcp_logs
  -> Check version / hash concurrency guards
  -> Apply transaction deterministically in memory
  -> If accepted:
       UPDATE cloud_target_files (current_content, current_version, current_hash)
       INSERT INTO append_only_pdcp_logs (status='accepted')
       INSERT INTO append_only_manifest_ledger (with origin and derived_json)
     If rejected:
       INSERT INTO append_only_pdcp_logs (status='rejected', failure_reason)
  -> COMMIT
```

Target mutation is strictly atomic: all edits succeed or none do. Rejected attempts are durably logged.

## Database Migrations

Schema migrations are managed by Alembic in `backend/app/migrations/`:

1. `20260510_0001_initial_schema.py`:
   - `cloud_target_files` (managed targets)
   - `append_only_pdcp_logs`
   - `append_only_manifest_ledger`
   - `editing_cycles`
   - `target_snapshots`
2. `20261020_0002_typed_ledger.py`:
   - Adds `client_request_id` TEXT NULL (UUID format) and `request_fingerprint` (CHAR(64)) to `append_only_pdcp_logs`.
   - Adds partial unique index `uq_pdcp_logs_target_client_request_id` where `client_request_id IS NOT NULL`.
   - Makes `manifest_ledger` legacy prose columns nullable (`input_state`, `output_state`, `affected_region`, `user_visible_change`, `risk`).
   - Adds `origin` TEXT NOT NULL (default `'pdcp_manifest'`) and `derived_json` JSONB NULL to `append_only_manifest_ledger`.
   - Guarded downgrade: refuses to downgrade to `0001` if typed ledger rows exist (`origin = 'typed'`).

Migrations must always run cleanly on live Postgres:
```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

## Append-Only Attempt Log (`append_only_pdcp_logs`)

Every submission (accepted or rejected) creates an append-only row:
- `log_sequence`: strictly ascending BigInteger sequence number (`BIGSERIAL`).
- `target_file_id`: foreign key to `cloud_target_files`.
- `protocol_version`: `'patchdiff-tx/1'` or `'0.2.3'`.
- `runtime_version`: `'patchdiff-mvp-0.2.0'` (or historical `'patchdiff-mvp-0.1.0'`).
- `status`: `'accepted'` or `'rejected'`.
- `failure_reason`: canonical failure string if rejected; `None` if accepted.
- `client_request_id`: client-supplied UUID string (TEXT) for idempotency.
- `request_fingerprint`: SHA-256 hash of submission parameters.
- `parent_pdcp_log_id`: link to predecessor log in retry lineage.
- `before_version`, `after_version`: target version progression.
- `before_hash`, `after_hash`: target SHA-256 progression.
- `pdcp_content`: canonical JSON string for `patchdiff-tx/1`; raw text for `0.2.3`.
- `pdcp_content_hash`: SHA-256 of `pdcp_content`.

## Accepted-Only Manifest Ledger (`append_only_manifest_ledger`)

Only accepted transactions record rows in the manifest ledger:
- `ledger_sequence`: strictly ascending BigInteger sequence number (`BIGSERIAL`).
- `origin`: `'typed'` for `patchdiff_submit_edits`, `'pdcp_manifest'` for `patchdiff_submit_pdcp` (TEXT).
- `derived_json`: JSONB object containing exact runtime facts computed by the applier:
  - `span_start`, `span_end`, `matched_chars`, `replacement_chars`, `matched_sha256`, `replacement_sha256`.
- For typed rows, legacy prose fields (`input_state`, `output_state`, `affected_region`, `user_visible_change`, `risk`) are `NULL`.

## SAVE Checkpoints & Editing Cycles

- `patchdiff_save` creates a snapshot row in `target_snapshots` and advances the active cycle in `editing_cycles`.
- SAVE does **not** mutate target text, change target version, change target hash, or alter manifest history.
- SAVE does not compact host context; context compaction is host-managed.

## Deterministic Replay Algorithm

Replay reconstructs target state strictly from initial target content plus accepted transaction history:

```mermaid
flowchart TD
    A[Start Replay] --> B[Fetch target & initial snapshot]
    B --> C{Initial snapshot hash matches?}
    C -- No --> F1[Return initial_snapshot_corrupted]
    C -- Yes --> D[Initialize replay buffer = snapshot content]
    D --> E[Fetch accepted logs in sequence_id order]
    E --> G{Has next log?}
    G -- No --> H[Replay complete: verify final buffer against target]
    G -- Yes --> I[Dispatch parser on protocol_version]
    I --> J[Check log.pdcp_content_hash]
    J -- Mismatch --> F2[Return pdcp_content_tampered]
    J -- Match --> K[Resolve overlapping matches via runtime_version]
    K --> L[Simulate transaction on replay buffer]
    L --> M{Computed hash == log.after_hash?}
    M -- No --> F3[Return replay_hash_mismatch]
    M -- Yes --> G
    H --> N[Report status='success', materialized_state_matches, checks]
```

### Component-Level Materialized State Checks
The replay result provides detailed boolean verification:
- `content_matches`: replay buffer matches current database content.
- `stored_hash_matches`: logged `after_hash` of final log matches current database `current_hash`.
- `recomputed_hash_matches`: recomputed hash of final replay buffer matches current database `current_hash`.
- `version_matches`: final log `after_version` matches current database `current_version`.
- `materialized_state_matches`: `true` only when all four component checks pass.

Replay uses the exact `(protocol_version, runtime_version)` recorded on each log row via `SUPPORTED_RUNTIME_PROFILES` in `backend/app/core/versions.py`. Legacy logs recorded with `patchdiff-mvp-0.1.0` replay with non-overlapping match enumeration; modern logs recorded with `patchdiff-mvp-0.2.0` replay with overlapping enumeration.
