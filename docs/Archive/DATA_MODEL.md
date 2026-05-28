# DATA_MODEL.md

## Scope

This document defines the Postgres data model for the MCP-first PatchDIFF MVP.

The schema supports:

- canonical target storage in Postgres
- pending `.pdcp` display/state tracking
- append-only accepted and rejected PDCP attempt history
- accepted-only manifest ledger history
- SAVE snapshots and editing-cycle advancement
- deterministic replay from persisted accepted PDCP attempts

The user interacts with the chatbot session over MCP. This schema does not assume a frontend.

## Design Rules

- Postgres is the MVP persistence backend.
- SQLite is out of scope for MVP persistence, locking, SAVE, and replay.
- `cloud_target_files` is the authoritative current-state table.
- `current_pdcp_files` is mutable session state and is not authoritative history.
- `append_only_pdcp_logs`, `append_only_manifest_ledger`, and `target_snapshots` are append-only.
- `editing_cycles` is history-preserving and must never be deleted; the only allowed lifecycle mutation is a one-time close stamp on the previously active cycle.
- Target content mutation must come only from accepted `.pdcp` transactions.
- SAVE may create snapshots and advance editing cycles but must not alter target content.
- MCP orchestration must never write target content directly.
- MVP enforces append-only behavior in application/repository code.
- MVP+ may add database triggers or restricted roles to prevent UPDATE/DELETE on append-only tables.

## ID And Type Conventions

Recommended conventions for the later implementation pass:

- primary keys: UUID or ULID text keys
- hashes: lowercase hex SHA-256, length 64
- content columns: canonical UTF-8 text stored as Postgres `TEXT`
- versions: monotonically increasing `BIGINT`
- timestamps: `TIMESTAMPTZ`

## Tables

### `users`

Minimal user identity table for project ownership and audit metadata.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `user_id` | UUID/TEXT | PK | Stable user identifier |
| `external_subject` | TEXT | UNIQUE NULLABLE | Optional mapping to upstream auth/provider identity |
| `display_name` | TEXT | NOT NULL | Human-readable audit label |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Last profile metadata update |

### `projects`

Logical grouping for targets and memberships.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `project_id` | UUID/TEXT | PK | Stable project identifier |
| `name` | TEXT | NOT NULL | Project label |
| `created_by_user_id` | UUID/TEXT | FK -> `users.user_id` | Optional initial owner |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Metadata update timestamp |

### `project_memberships`

Minimal membership table for ownership and audit context.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `project_membership_id` | UUID/TEXT | PK | Stable membership identifier |
| `project_id` | UUID/TEXT | FK -> `projects.project_id` NOT NULL | Parent project |
| `user_id` | UUID/TEXT | FK -> `users.user_id` NOT NULL | Member |
| `role` | TEXT | NOT NULL | Recommended values: `owner`, `editor`, `viewer` |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

Required uniqueness:

- `UNIQUE (project_id, user_id)`

### `editing_cycles`

Tracks SAVE boundaries and the currently active manifest context.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `editing_cycle_id` | UUID/TEXT | PK | Stable cycle identifier |
| `target_file_id` | UUID/TEXT | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `cycle_index` | BIGINT | NOT NULL | Monotonic per target |
| `status` | TEXT | NOT NULL | `active` or `closed` |
| `started_at` | TIMESTAMPTZ | NOT NULL | Cycle start timestamp |
| `closed_at` | TIMESTAMPTZ | NULLABLE | Set once when SAVE closes the cycle |
| `opened_by_user_id` | UUID/TEXT | FK -> `users.user_id` NULLABLE | Audit metadata |
| `closed_by_user_id` | UUID/TEXT | FK -> `users.user_id` NULLABLE | SAVE initiator when applicable |
| `save_snapshot_id` | UUID/TEXT | FK -> `target_snapshots.snapshot_id` NULLABLE | Snapshot that closed this cycle |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

Constraints and indexes:

- `CHECK (status IN ('active', 'closed'))`
- `UNIQUE (target_file_id, cycle_index)`
- partial unique index for one active cycle per target:
  `UNIQUE (target_file_id) WHERE status = 'active'`

Lifecycle note:

- `editing_cycles` should be treated as append-only history with a single terminal close update on the row that was active before SAVE.

### `cloud_target_files`

Authoritative current canonical target state.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `target_file_id` | UUID/TEXT | PK | Stable target identifier |
| `project_id` | UUID/TEXT | FK -> `projects.project_id` NOT NULL | Parent project |
| `filename` | TEXT | NOT NULL | Original or exported filename |
| `target_type` | TEXT | NOT NULL | Target content type such as `text/markdown` |
| `current_content` | TEXT | NOT NULL | Canonical UTF-8 target text |
| `current_hash` | CHAR(64) | NOT NULL | SHA-256 of canonical target text |
| `version` | BIGINT | NOT NULL | Monotonic target version |
| `active_editing_cycle_id` | UUID/TEXT | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Current cycle |
| `latest_accepted_pdcp_log_id` | UUID/TEXT | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Last accepted attempt |
| `initial_snapshot_id` | UUID/TEXT | FK -> `target_snapshots.snapshot_id` NULLABLE | Initial upload snapshot |
| `created_by_user_id` | UUID/TEXT | FK -> `users.user_id` NULLABLE | Audit metadata |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Target mutation timestamp |

Indexes:

- `INDEX (project_id)`
- `INDEX (active_editing_cycle_id)`
- `INDEX (current_hash)`

### `current_pdcp_files`

Mutable record of the most recent submitted `.pdcp` content for a target.

This table is not authoritative history and may be overwritten by later submissions.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `pdcp_file_id` | UUID/TEXT | PK | Current PDCP row identifier |
| `target_file_id` | UUID/TEXT | FK -> `cloud_target_files.target_file_id` NOT NULL | One active current row per target |
| `editing_cycle_id` | UUID/TEXT | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Cycle in which the PDCP was submitted |
| `protocol_version` | TEXT | NOT NULL | Expected MVP value: `0.2.3` |
| `pdcp_content` | TEXT | NOT NULL | Raw `.pdcp` text as submitted |
| `pdcp_content_hash` | CHAR(64) | NOT NULL | SHA-256 of submitted PDCP bytes after UTF-8 validation |
| `status` | TEXT | NOT NULL | Recommended values: `pending_validation`, `accepted`, `rejected`, `superseded` |
| `submission_source` | TEXT | NOT NULL | Recommended values: `model_response`, `regeneration`, `manual_submission` |
| `parent_pdcp_log_id` | UUID/TEXT | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Prior rejected attempt that led to regeneration |
| `regeneration_attempt` | INTEGER | NULLABLE | 1-based retry number for regenerated submissions |
| `regeneration_source` | TEXT | NULLABLE | MCP host or policy label for regeneration |
| `last_pdcp_log_id` | UUID/TEXT | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Resulting accepted/rejected log row once validation finishes |
| `submitted_by_user_id` | UUID/TEXT | FK -> `users.user_id` NULLABLE | Audit metadata |
| `created_at` | TIMESTAMPTZ | NOT NULL | First creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Last overwrite/status change timestamp |

Required uniqueness:

- `UNIQUE (target_file_id)`

### `append_only_pdcp_logs`

Authoritative append-only log of accepted and rejected PDCP attempts.

Replay reads accepted rows from this table in deterministic order.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `pdcp_log_id` | UUID/TEXT | PK | Stable PDCP attempt identifier |
| `log_sequence` | BIGINT | UNIQUE NOT NULL | Monotonic replay ordering key |
| `target_file_id` | UUID/TEXT | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `editing_cycle_id` | UUID/TEXT | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Cycle active at submission time |
| `parent_pdcp_log_id` | UUID/TEXT | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Prior rejected attempt that prompted regeneration |
| `regeneration_attempt` | INTEGER | NULLABLE | 1-based retry number when regenerated |
| `regeneration_source` | TEXT | NULLABLE | Host or policy label for regeneration |
| `submission_source` | TEXT | NOT NULL | Recommended values: `model_response`, `regeneration`, `manual_submission` |
| `protocol_version` | TEXT | NOT NULL | MVP protocol version used to parse the file |
| `runtime_version` | TEXT | NOT NULL | Trusted runtime build/version string |
| `pdcp_content` | TEXT | NOT NULL | Full submitted `.pdcp` text |
| `pdcp_content_hash` | CHAR(64) | NOT NULL | SHA-256 of submitted PDCP bytes |
| `status` | TEXT | NOT NULL | `accepted` or `rejected` |
| `failure_reason` | TEXT | NULLABLE | Canonical rejection label for rejected rows |
| `failure_detail` | TEXT | NULLABLE | Human-readable rejection detail |
| `failed_change_id` | TEXT | NULLABLE | Change that failed, when applicable |
| `diagnostic_json` | JSONB | NULLABLE | Advisory structured diagnostics for rejected attempts and regeneration context; does not affect transaction semantics |
| `expected_target_version` | BIGINT | NULLABLE | Request-level optimistic concurrency guard |
| `expected_current_hash` | CHAR(64) | NULLABLE | Request-level optimistic concurrency guard |
| `before_version` | BIGINT | NULLABLE | Target version seen during validation |
| `after_version` | BIGINT | NULLABLE | New target version for accepted rows |
| `before_hash` | CHAR(64) | NOT NULL | Current target hash at validation time |
| `after_hash` | CHAR(64) | NULLABLE | New target hash for accepted rows, `NULL` on rejection |
| `change_count` | INTEGER | NOT NULL | Number of manifest/MATCH blocks in the PDCP |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

Constraints and indexes:

- `CHECK (status IN ('accepted', 'rejected'))`
- `INDEX (target_file_id, log_sequence)`
- `INDEX (target_file_id, created_at)`
- `INDEX (parent_pdcp_log_id)`
- `INDEX (status, failure_reason)`

Append-only rule:

- no `UPDATE`
- no `DELETE`
- corrections are represented by new attempts, not rewritten rows

### `append_only_manifest_ledger`

Append-only ledger of accepted manifest entries only.

Rejected attempts never write to this table.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `manifest_entry_id` | UUID/TEXT | PK | Stable manifest ledger identifier |
| `ledger_sequence` | BIGINT | UNIQUE NOT NULL | Monotonic read ordering key |
| `target_file_id` | UUID/TEXT | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `editing_cycle_id` | UUID/TEXT | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Cycle active when accepted |
| `pdcp_log_id` | UUID/TEXT | FK -> `append_only_pdcp_logs.pdcp_log_id` NOT NULL | Accepted PDCP row that emitted this entry |
| `change_index` | INTEGER | NOT NULL | 1-based order of the change inside the PDCP |
| `change_id` | TEXT | NOT NULL | Manifest change identifier |
| `intent` | TEXT | NOT NULL | Required manifest field |
| `input_state` | TEXT | NOT NULL | Required manifest field |
| `output_state` | TEXT | NOT NULL | Required manifest field |
| `affected_region` | TEXT | NOT NULL | Required manifest field |
| `user_visible_change` | TEXT | NOT NULL | Required manifest field |
| `risk` | TEXT | NOT NULL | `low`, `medium`, or `high` |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

Constraints and indexes:

- `CHECK (risk IN ('low', 'medium', 'high'))`
- `UNIQUE (pdcp_log_id, change_index)`
- `UNIQUE (pdcp_log_id, change_id)`
- `INDEX (target_file_id, editing_cycle_id, ledger_sequence)`

Append-only rule:

- no `UPDATE`
- no `DELETE`

### `target_snapshots`

Append-only snapshot table for initial target state and SAVE checkpoints.

Snapshots may accelerate later reads or replay startup, but they are not authoritative transaction history.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `snapshot_id` | UUID/TEXT | PK | Stable snapshot identifier |
| `target_file_id` | UUID/TEXT | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `editing_cycle_id` | UUID/TEXT | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Cycle being snapshotted |
| `content` | TEXT | NOT NULL | Canonical target text at snapshot time |
| `content_hash` | CHAR(64) | NOT NULL | SHA-256 of snapshotted canonical content |
| `version` | BIGINT | NOT NULL | Target version at snapshot time |
| `snapshot_reason` | TEXT | NOT NULL | Recommended values: `initial_upload`, `save_checkpoint` |
| `base_pdcp_log_id` | UUID/TEXT | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Last accepted PDCP included in the snapshot |
| `created_by_user_id` | UUID/TEXT | FK -> `users.user_id` NULLABLE | Audit metadata |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

Constraints and indexes:

- `CHECK (snapshot_reason IN ('initial_upload', 'save_checkpoint'))`
- `INDEX (target_file_id, created_at)`

Append-only rule:

- no `UPDATE`
- no `DELETE`

## Authoritative State And Replay Inputs

Authoritative current state:

- `cloud_target_files.current_content`
- `cloud_target_files.current_hash`
- `cloud_target_files.version`

Authoritative operational history:

- accepted rows from `append_only_pdcp_logs`, ordered by `log_sequence`

Replay must not depend on:

- `current_pdcp_files`
- `append_only_manifest_ledger`
- `target_snapshots`
- a frontend cache

Snapshots are acceleration artifacts only.

## Atomic Commit Requirements

### Accepted PDCP transaction

One accepted `.pdcp` submission must commit in one Postgres transaction:

1. `SELECT ... FOR UPDATE` the `cloud_target_files` row for `target_file_id`.
2. Verify `expected_target_version` and/or `expected_current_hash`.
3. Verify the row still points to the expected active editing cycle.
4. Run deterministic parser, validator, matcher, disambiguator, and applier against the locked canonical target.
5. Update `cloud_target_files.current_content`, `current_hash`, `version`, `updated_at`, and `latest_accepted_pdcp_log_id`.
6. Insert one `append_only_pdcp_logs` row with `status = accepted`.
7. Insert one or more `append_only_manifest_ledger` rows for the accepted change manifests.
8. Update `current_pdcp_files` for the target to `status = accepted` and attach `last_pdcp_log_id`.
9. Commit.

Required invariants:

- no committed target mutation without a corresponding accepted PDCP log row
- no accepted manifest ledger rows without the corresponding accepted PDCP log row
- no partial commit of a multi-change PDCP

### Rejected PDCP transaction

One rejected `.pdcp` submission should persist in one Postgres transaction when the target exists:

1. `SELECT ... FOR UPDATE` the `cloud_target_files` row for `target_file_id`.
2. Verify current target state needed to produce deterministic diagnostics.
3. Insert one `append_only_pdcp_logs` row with `status = rejected`.
4. Do not modify `cloud_target_files.current_content`, `current_hash`, or `version`.
5. Do not insert manifest ledger rows.
6. Update `current_pdcp_files` for the target to `status = rejected` and attach `last_pdcp_log_id`.
7. Commit.

Required invariants:

- `before_hash` is the locked target hash seen during validation
- `after_hash` is `NULL`
- rejected attempts remain visible and append-only

### SAVE transaction

One SAVE operation must commit in one Postgres transaction:

1. `SELECT ... FOR UPDATE` the `cloud_target_files` row for `target_file_id`.
2. Verify `expected_current_hash` if supplied.
3. Insert a `target_snapshots` row for the current canonical target.
4. Close the currently active `editing_cycles` row by stamping `closed_at`, `closed_by_user_id`, `save_snapshot_id`, and `status = closed`.
5. Insert the new `editing_cycles` row with `status = active`.
6. Update `cloud_target_files.active_editing_cycle_id` to the new cycle.
7. Leave `append_only_pdcp_logs` and `append_only_manifest_ledger` unchanged.
8. Commit.

Required invariants:

- SAVE never deletes history
- SAVE never clears active manifest context before the snapshot insert succeeds
- SAVE does not alter `cloud_target_files.current_content`
- SAVE failure leaves the old active cycle and target state intact

## Row-Level Locking Expectations

Use same-target row-level locking on `cloud_target_files`:

```sql
SELECT *
FROM cloud_target_files
WHERE target_file_id = :target_file_id
FOR UPDATE;
```

Expectations:

- two writes to the same `target_file_id` must not interleave
- validation and commit for a target happen while that target row is locked
- different targets may commit concurrently
- application-level mutexes are not sufficient without the Postgres row lock

Expected failure mapping:

- request `expected_target_version` precondition fails before validation begins -> `target_version_mismatch`
- request `expected_current_hash` or PDCP `target_hash` precondition fails before validation begins -> `target_hash_mismatch`
- target row changes after validation/simulation but before the final commit guard inside the same transaction attempt -> `target_diverged`

## Read Patterns

Recommended default reads:

- current target view: `cloud_target_files`
- pending PDCP view: `current_pdcp_files`
- active manifest summary: `append_only_manifest_ledger` filtered to `cloud_target_files.active_editing_cycle_id`
- full audit log: `append_only_pdcp_logs`
- replay source: accepted `append_only_pdcp_logs` ordered by `log_sequence`

## Non-Negotiable Constraints

- Do not store executable PDCP runtime logic in the database as trusted code.
- Do not let MCP orchestration update `cloud_target_files.current_content` directly.
- Do not write accepted manifest rows for rejected attempts.
- Do not make replay depend on mutable current PDCP display state.
- Do not use SQLite to validate locking, migrations, SAVE, or replay behavior.
