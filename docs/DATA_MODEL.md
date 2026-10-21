# DATA_MODEL.md

## Scope

This document defines the authoritative Postgres data model for PatchDIFF, incorporating Alembic migrations `20260510_0001_initial_schema` and `20261020_0002_typed_ledger`.

The schema supports:
- canonical target storage in Postgres (`cloud_target_files`)
- row-locked per-target atomic transactions under `SELECT ... FOR UPDATE`
- append-only attempt logs (`append_only_pdcp_logs`) recording both accepted and rejected submissions, retry lineage (`parent_pdcp_log_id`), and request deduplication (`client_request_id`)
- accepted-only manifest ledger (`append_only_manifest_ledger`) tracking origin (`origin = 'typed'` vs `'pdcp_manifest'`) and runtime-derived span/hash facts (`derived_json`)
- SAVE checkpoints and editing cycle advancement (`editing_cycles`, `target_snapshots`)
- deterministic replay across recorded `(protocol_version, runtime_version)` profiles

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built record and verification evidence: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

## Design Rules

- Postgres (`postgres:16.3-alpine`) is the required working substrate. SQLite is out of scope for persistence, row-locking, migrations, SAVE, or replay.
- `cloud_target_files` is the single authoritative current-state table.
- `append_only_pdcp_logs`, `append_only_manifest_ledger`, and `target_snapshots` are strictly append-only.
- `editing_cycles` is history-preserving; the only mutation is a one-time terminal `closed_at` and `save_snapshot_id` stamp when SAVE advances the cycle.
- `current_pdcp_files` is mutable display/session state for the most recent submission and is not authoritative history.
- Target mutation occurs exclusively through accepted commits executed by `submit_edits` or `submit_pdcp`.

## Tables

### `users`
Minimal identity table for project ownership and audit metadata.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `user_id` | UUID | PK | Stable user identifier |
| `external_subject` | TEXT | UNIQUE NULLABLE | Upstream auth provider identity |
| `display_name` | TEXT | NOT NULL | Human-readable audit label |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Profile update timestamp |

### `projects`
Logical grouping for targets and memberships.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `project_id` | UUID | PK | Stable project identifier |
| `name` | TEXT | NOT NULL | Project label |
| `created_by_user_id` | UUID | FK -> `users.user_id` NULLABLE | Creator identity |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Metadata update timestamp |

### `project_memberships`
Role assignments per project (`UNIQUE (project_id, user_id)`).

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `project_membership_id` | UUID | PK | Stable membership identifier |
| `project_id` | UUID | FK -> `projects.project_id` NOT NULL | Parent project |
| `user_id` | UUID | FK -> `users.user_id` NOT NULL | Member identity |
| `role` | TEXT | NOT NULL | `owner`, `editor`, or `viewer` |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

### `editing_cycles`
Tracks SAVE boundaries and the active manifest context.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `editing_cycle_id` | UUID | PK | Stable cycle identifier |
| `target_file_id` | UUID | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `cycle_index` | BIGINT | NOT NULL | Monotonic cycle number per target |
| `status` | TEXT | NOT NULL | `active` or `closed` |
| `started_at` | TIMESTAMPTZ | NOT NULL | Cycle start timestamp |
| `closed_at` | TIMESTAMPTZ | NULLABLE | Timestamp when SAVE closed the cycle |
| `opened_by_user_id` | UUID | FK -> `users.user_id` NULLABLE | Initiator |
| `closed_by_user_id` | UUID | FK -> `users.user_id` NULLABLE | Closer |
| `save_snapshot_id` | UUID | FK -> `target_snapshots.snapshot_id` NULLABLE | Snapshot that closed this cycle |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

Constraints:
- `CHECK (status IN ('active', 'closed'))`
- `UNIQUE (target_file_id, cycle_index)`
- Partial unique index: `uq_editing_cycles_one_active_per_target ON editing_cycles(target_file_id) WHERE status = 'active'`

### `cloud_target_files`
Authoritative current canonical target state.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `target_file_id` | UUID | PK | Stable target identifier |
| `project_id` | UUID | FK -> `projects.project_id` NOT NULL | Parent project |
| `filename` | TEXT | NOT NULL | Filename (e.g. `doc.md`) |
| `target_type` | TEXT | NOT NULL | MIME / language type (e.g. `text/markdown`) |
| `current_content` | TEXT | NOT NULL | Canonical UTF-8 target text (LF normalized) |
| `current_hash` | CHAR(64) | NOT NULL | SHA-256 of canonical target text |
| `version` | BIGINT | NOT NULL | Monotonically increasing version (0 on init) |
| `active_editing_cycle_id` | UUID | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Current active cycle |
| `latest_accepted_pdcp_log_id` | UUID | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Last accepted attempt |
| `initial_snapshot_id` | UUID | FK -> `target_snapshots.snapshot_id` NULLABLE | Initial upload snapshot |
| `created_by_user_id` | UUID | FK -> `users.user_id` NULLABLE | Initiator |
| `created_at` | TIMESTAMPTZ | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Last mutation timestamp |

### `current_pdcp_files`
Mutable record of the most recent submission for a target (display/session state; not authoritative history).

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `pdcp_file_id` | UUID | PK | Row identifier |
| `target_file_id` | UUID | FK -> `cloud_target_files.target_file_id` UNIQUE NOT NULL | One row per target |
| `editing_cycle_id` | UUID | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Submission cycle |
| `protocol_version` | TEXT | NOT NULL | `patchdiff-tx/1` or `0.2.3` |
| `pdcp_content` | TEXT | NOT NULL | Raw text or canonical JSON |
| `pdcp_content_hash` | CHAR(64) | NOT NULL | SHA-256 of `pdcp_content` |
| `status` | TEXT | NOT NULL | `pending_validation`, `accepted`, `rejected`, `superseded` |
| `submission_source` | TEXT | NOT NULL | `model_response`, `regeneration`, `manual` |
| `parent_pdcp_log_id` | UUID | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Retry lineage |
| `regeneration_attempt` | INTEGER | NULLABLE | 1-based attempt number |
| `regeneration_source` | TEXT | NULLABLE | Host identifier |
| `last_pdcp_log_id` | UUID | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Resulting log row |
| `created_at` | TIMESTAMPTZ | NOT NULL | Initial insert timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Last overwrite timestamp |

### `append_only_pdcp_logs`
Authoritative append-only log of accepted and rejected transaction attempts.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `pdcp_log_id` | UUID | PK | Stable attempt identifier |
| `log_sequence` | BIGINT | UNIQUE NOT NULL | Monotonic replay sequence key |
| `target_file_id` | UUID | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `editing_cycle_id` | UUID | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Cycle active at submission time |
| `parent_pdcp_log_id` | UUID | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Prior rejected attempt prompting this retry |
| `regeneration_attempt` | INTEGER | NULLABLE | 1-based retry attempt |
| `regeneration_source` | TEXT | NULLABLE | Host or policy label |
| `submission_source` | TEXT | NOT NULL | `model_response`, `regeneration`, `manual` |
| `protocol_version` | TEXT | NOT NULL | `patchdiff-tx/1` or `0.2.3` |
| `runtime_version` | TEXT | NOT NULL | Runtime profile (e.g. `patchdiff-mvp-0.2.1`) |
| `pdcp_content` | TEXT | NOT NULL | Canonical JSON (`patchdiff-tx/1`) or raw `.pdcp` |
| `pdcp_content_hash` | CHAR(64) | NOT NULL | SHA-256 of `pdcp_content` |
| `status` | TEXT | NOT NULL | `accepted` or `rejected` |
| `failure_reason` | TEXT | NULLABLE | Canonical failure label on rejection |
| `failure_detail` | TEXT | NULLABLE | Diagnostic explanation |
| `failed_change_id` | TEXT | NULLABLE | Failing change ID when applicable |
| `diagnostic_json` | JSONB | NULLABLE | Structured diagnostics (`format`, `retryable`, `stage`, etc.) |
| `expected_target_version` | BIGINT | NULLABLE | Concurrency guard |
| `expected_current_hash` | CHAR(64) | NULLABLE | Concurrency guard |
| `before_version` | BIGINT | NULLABLE | Target version before transaction |
| `after_version` | BIGINT | NULLABLE | Target version after acceptance (`NULL` on rejection) |
| `before_hash` | CHAR(64) | NOT NULL | Target hash before transaction |
| `after_hash` | CHAR(64) | NULLABLE | Target hash after acceptance (`NULL` on rejection) |
| `change_count` | INTEGER | NOT NULL | Number of changes in the transaction |
| `client_request_id` | TEXT | NULLABLE | Idempotency request ID (Migration `0002`) |
| `request_fingerprint` | VARCHAR(64) | NULLABLE | SHA-256 envelope fingerprint (Migration `0002`) |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

Indexes:
- `INDEX (target_file_id, log_sequence)`
- `INDEX (target_file_id, created_at)`
- `INDEX (parent_pdcp_log_id)`
- `INDEX (status, failure_reason)`
- Partial unique index: `uq_pdcp_logs_target_client_request_id ON append_only_pdcp_logs(target_file_id, client_request_id) WHERE client_request_id IS NOT NULL`

### `append_only_manifest_ledger`
Append-only ledger of accepted changes only. Rejections never write to this table.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `manifest_entry_id` | UUID | PK | Ledger row identifier |
| `ledger_sequence` | BIGINT | UNIQUE NOT NULL | Monotonic read sequence key |
| `target_file_id` | UUID | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `editing_cycle_id` | UUID | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Active cycle when accepted |
| `pdcp_log_id` | UUID | FK -> `append_only_pdcp_logs.pdcp_log_id` NOT NULL | Accepted attempt that created this entry |
| `change_index` | INTEGER | NOT NULL | 1-based index within the transaction |
| `change_id` | TEXT | NOT NULL | Change identifier (e.g. `chg_001`) |
| `origin` | TEXT | NOT NULL DEFAULT `'pdcp_manifest'` | `'typed'` or `'pdcp_manifest'` (Migration `0002`) |
| `intent` | TEXT | NOT NULL | Change intent (or `rationale` on typed path) |
| `input_state` | TEXT | NULLABLE | Prose description (nullable after Migration `0002`) |
| `output_state` | TEXT | NULLABLE | Prose description (nullable after Migration `0002`) |
| `affected_region` | TEXT | NULLABLE | Prose description (nullable after Migration `0002`) |
| `user_visible_change` | TEXT | NULLABLE | Prose description (nullable after Migration `0002`) |
| `risk` | TEXT | NULLABLE | `low`, `medium`, `high`, or `NULL` (nullable after Migration `0002`) |
| `derived_json` | JSONB | NULLABLE | Runtime-derived facts (`span_start`, `span_end`, char lengths, hashes) |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

Constraints:
- `CHECK (risk IS NULL OR risk IN ('low', 'medium', 'high'))`
- `CHECK (origin IN ('pdcp_manifest', 'typed'))`
- `UNIQUE (pdcp_log_id, change_index)`
- `INDEX (target_file_id, editing_cycle_id, ledger_sequence)`

### `target_snapshots`
Append-only snapshots for initial uploads and SAVE checkpoints.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `snapshot_id` | UUID | PK | Snapshot identifier |
| `target_file_id` | UUID | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `editing_cycle_id` | UUID | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Cycle being snapshotted |
| `content` | TEXT | NOT NULL | Canonical target text at snapshot time |
| `content_hash` | CHAR(64) | NOT NULL | SHA-256 of canonical text |
| `version` | BIGINT | NOT NULL | Target version at snapshot time |
| `snapshot_reason` | TEXT | NOT NULL | `initial_upload` or `save_checkpoint` |
| `base_pdcp_log_id` | UUID | FK -> `append_only_pdcp_logs.pdcp_log_id` NULLABLE | Last accepted log included in snapshot |
| `created_by_user_id` | UUID | FK -> `users.user_id` NULLABLE | Initiator |
| `created_at` | TIMESTAMPTZ | NOT NULL | Insert timestamp |

## Atomic Commit Workflow (`SELECT ... FOR UPDATE`)

For both `patchdiff_submit_edits` and `patchdiff_submit_pdcp`, execution proceeds inside a single database transaction:
1. `SELECT * FROM cloud_target_files WHERE target_file_id = :id FOR UPDATE;`
2. Check `client_request_id`: if already recorded for this target with the identical `request_fingerprint`, return the reconstructed terminal result (`deduplicated: true`) without re-applying. If recorded with a different fingerprint, reject with `CONTEXT_INVALID`.
3. Verify optimistic guards (`expected_target_version`, `expected_current_hash`).
4. Validate format and sequential in-memory applicability; compute `change_facts`.
5. Post-simulation commit guard: verify target version and hash have not diverged.
6. Commit: update `cloud_target_files`, insert `append_only_pdcp_logs`, insert `append_only_manifest_ledger` rows (with `origin` and `derived_json`), update `current_pdcp_files`.
7. On any rejection: target is not mutated; a rejected row is inserted into `append_only_pdcp_logs`; zero rows are inserted into `append_only_manifest_ledger`.
