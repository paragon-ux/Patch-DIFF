# DATA_MODEL.md

## Storage effects of guarded operations, replacement and diagnostics

Only migration `20261022_0003` adds storage (below); everything else uses existing columns. The normative tool contract is [MCP_TOOLS.md](MCP_TOOLS.md#guarded-editing-reads-preview-and-diagnostics).

- New submissions record these `append_only_pdcp_logs.protocol_version` / `runtime_version` pairs: `patchdiff-tx/1` and `0.2.3` with `patchdiff-mvp-0.2.2`; `patchdiff-tx/2` with `patchdiff-mvp-0.3.0`, or `patchdiff-mvp-0.5.0` when a span operation contains `expected_before`/`expected_after`; `patchdiff-tx/3` with `patchdiff-mvp-0.4.0`. `pdcp_content` stores the canonical JSON record for every typed format.
- Accepted tx/2 and tx/3 transactions write `origin = 'typed'` ledger rows whose `derived_json` adds `operation` (`"span"` or `"replace_all"`). A tx/3 transaction writes exactly one row covering the full original span.
- Rejected rows persist `diagnostic_json.failure_context` (at most 256 code points of the failing buffer, as a prefix or a window around a known failure location) and, when applicable, `exact_candidates`, span evidence (`span_check`, `buffer_length`, `actual_text`), `original_occurrences` for consumed sequential matches, `near_miss_query` for absent matches, and `code` for request-key conflicts and invalid keys. Response-only `current_context`, `near_misses`, the near-miss scan buffer and `correlation_id` are never stored.
- Accepted rows keep `diagnostic_json = NULL` unless the applier reported warnings; then it holds `{warnings, warning_count, warnings_truncated}` with at most 16 warning objects. Replay never reads it.
- Migration `20261022_0003` adds nullable JSONB `cloud_target_files.source_line_endings`, written once at upload and read only by export. Existing targets keep NULL (unknown). Downgrade refuses while any target has recorded facts.
- A valid oversized fresh tx/3 replacement writes no attempt or `current_pdcp_files` row. A key-conflict attempt is audited before fresh admission, so its row stores the complete submitted record even when it exceeds the fresh limits, the same as any tx/1 or tx/2 attempt.
- `patchdiff_read_lines` and `patchdiff_preview` only read one committed `cloud_target_files` row; they write nothing and take no locks.

## Scope

This document defines the authoritative Postgres data model for PatchDIFF, incorporating Alembic migrations `20260510_0001_initial_schema`, `20261020_0002_typed_ledger` and `20261022_0003_source_line_endings`.

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
| `source_line_endings` | JSONB | NULLABLE | Raw upload line-ending facts `{style, lf, crlf, cr, normalized, source_code_points, source_utf8_bytes, source_sha256}` recorded before LF canonicalization; NULL for targets created before Migration `0003` |
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
| `protocol_version` | TEXT | NOT NULL | `patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3` or `0.2.3` |
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
| `protocol_version` | TEXT | NOT NULL | `patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3` or `0.2.3` |
| `runtime_version` | TEXT | NOT NULL | Runtime profile (e.g. `patchdiff-mvp-0.2.2`) |
| `pdcp_content` | TEXT | NOT NULL | Canonical JSON or raw PDCP for ordinary input; reversible ASCII JSON evidence for rejected invalid text |
| `pdcp_content_hash` | CHAR(64) | NOT NULL | SHA-256 of `pdcp_content` |
| `status` | TEXT | NOT NULL | `accepted` or `rejected` |
| `failure_reason` | TEXT | NULLABLE | Canonical failure label on rejection |
| `failure_detail` | TEXT | NULLABLE | Diagnostic explanation |
| `failed_change_id` | TEXT | NULLABLE | Failing change ID when applicable |
| `diagnostic_json` | JSONB | NULLABLE | Rejected rows: structured diagnostics (`format`, `retryable`, `stage`, etc.). Accepted rows: advisory warnings when present, otherwise NULL |
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

#### Bounded rejected-buffer evidence

New rejected attempts store `failure_context` within existing `diagnostic_json`; no column or migration is added. It contains only the bounded original failure prefix or failure window, code-point counts, canonical/intermediate stage, prior simulated-change count and transaction-start observed target identity, using the representation and JSON-byte limits in MCP_TOOLS. This evidence is immutable. Exact recovery returns the stored diagnostic unchanged; pre-feature rows remain without failure context. Top-level fresh `current_context` is response-only and is never written into the recovered row. Unknown targets and pending local state have no target-linked durable attempt; their contexts explicitly report unavailable. Qualified audit and caller commit/rollback ownership are unchanged.

#### Request identity

For ordinary inputs, request_fingerprint hashes a canonical JSON envelope containing protocol_version, canonical target_file_id, pdcp_content_hash, expected_target_version, expected_current_hash and parent_pdcp_log_id. The client_request_id selects the per-target keyed row; it is not itself part of this envelope. Submission source and attempt metadata are not part of ordinary request identity. The separate invalid-input evidence domain described below covers its evidence envelope instead.

For typed input, pdcp_content is canonical JSON of the complete submitted record: format, canonical target UUID, both guard fields, intent and the ordered raw edits array. Object keys are sorted and JSON separators are compact; decoded string values and supplied edit fields are preserved. JSON wire whitespace, object-key order and equivalent Unicode escape spelling do not affect identity. This is not a hash of the original JSON-RPC wire bytes, nor a fingerprint of only the resulting edit operation.

Changing intent, rationale, risk, selectors, edit order or a guard changes the record and therefore request identity. LF versus CRLF inside a typed string is represented by different JSON escapes and also changes identity, even when the applier would normalize both to the same matching text. No Unicode normalization is performed. An omitted optional edit field differs from an explicitly null field; an omitted change_id differs from an explicitly supplied runtime-default ID. Top-level omitted/null guards both become null in build_record. Runtime parsing defaults do not rewrite the persisted raw edit array before fingerprinting.

Legacy PDCP uses canonical_sha256 over its complete text, so LF/CRLF/bare-CR line endings normalize for that content hash. Do not extend that legacy equivalence to escaped line endings inside typed JSON values. Valid hashing and all stored fingerprints remain unchanged.

#### Parent identity

Do not adopt broader parent UUID canonicalization in this release. _resolve_parent_log canonicalizes only a UUID that resolves to a rejected attempt on the same target. If the parent is missing, accepted, cross-target or malformed, lineage rejects and the fingerprint retains its supplied string spelling (for a truthy value); no invalid foreign key is stored. Changing case or spelling in such a rejected request can therefore conflict with an existing key. Exact original retries preserve their prior identity and outcome, including the lookup-only historical compatibility path.

Canonicalizing syntactically valid but ineligible UUIDs before lineage would change rejected-request identity and require its own historical fingerprint compatibility strategy. Retaining the current contract is the requested adoption decision, not a claim that broader normalization was implemented. Conditional adoption tests are not applicable; the implementation remains unchanged.

#### Rejected invalid-text evidence

An encoding-invalid proposal uses existing pdcp_content TEXT for an ASCII-escaped JSON envelope: evidence_format is patchdiff-invalid-input/1; inputs retain the original submitted record and metadata. The stored characters are ASCII and safe for PostgreSQL, while JSON decoding can recover the offending code points for inspection outside database JSONB. Do not insert decoded unpaired surrogates or NUL into TEXT/JSONB.

The diagnostic marks this representation and safely identifies offending paths. Existing non-evidence rows retain lookup-only legacy fingerprint recovery for representable original records, even where today's Unicode boundary would reject that input. No old row/fingerprint is rewritten and no fresh invalid proposal is admitted. Domain-separated invalid-input fingerprints cover the complete evidence; safe original keys recover the original rejection. Invalid keys are retained only in evidence with client_request_id=NULL. Normal valid-input hashes/fingerprints and accepted-only ledger behavior are unchanged. Rejected evidence is excluded from accepted-history replay.

#### Conflicting-key audit policy

An admitted fingerprint conflict uses client_request_id=NULL so the original target/key unique row stays authoritative. Its request_fingerprint is the newly submitted fingerprint, not the original row's fingerprint. Repeated conflicts remain separate immutable audit rows, even when their submitted fingerprints are identical. Diagnostics link the original log and show the submitted key with a 256-character preview/truncation flag; the original keyed row retains the complete key. The returned response still identifies the submitted key and returns the newly persisted rejection's log ID.

No target/version/accepted-ledger change is made. Exact outcome recovery remains the no-new-attempt exception. Rate/admission controls are separate operational work and are not implemented by dropping, capping or mutating audit rows here.

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
2. Check `client_request_id`: if already recorded for this target with the identical `request_fingerprint`, return the reconstructed terminal result (`deduplicated: true`) without re-applying. If recorded with a different fingerprint, reject with CONTEXT_INVALID and append a separate NULL-key rejected attempt under the same target lock. Retain the submitted fingerprint on that attempt, with existing_pdcp_log_id and bounded submitted-key diagnostic evidence. The original keyed row/fingerprint is never overwritten; repeated conflicts create distinct rows.
3. Verify optimistic guards (`expected_target_version`, `expected_current_hash`).
4. Validate format and sequential in-memory applicability; compute `change_facts`.
5. Post-simulation commit guard: verify target version and hash have not diverged.
6. Commit: update `cloud_target_files`, insert `append_only_pdcp_logs`, insert `append_only_manifest_ledger` rows (with `origin` and `derived_json`), update `current_pdcp_files`.
7. On any rejection: target is not mutated; a rejected row is inserted into `append_only_pdcp_logs`; zero rows are inserted into `append_only_manifest_ledger`.


### `target_scope_observations` (Migration `20261026_0004`)
Server-issued structural scope observations produced by `patchdiff_observe_scope` over the pinned `waymark-engine@4.1.0` package.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `observation_id` | UUID | PK | Server-issued opaque observation reference |
| `target_file_id` | UUID | FK -> `cloud_target_files.target_file_id` NOT NULL | Owning target |
| `editing_cycle_id` | UUID | FK -> `editing_cycles.editing_cycle_id` NOT NULL | Active editing cycle when observed |
| `target_version` | BIGINT | NOT NULL | Canonical target version observed |
| `target_current_hash` | VARCHAR(64) | NOT NULL | SHA-256 of canonical LF target content observed |
| `waymark_engine_version` | TEXT | NOT NULL | Pinned Waymark release (`4.1.0`) |
| `language` | TEXT | NOT NULL | Waymark language identifier (`python`, `json`, `markdown`, etc.) |
| `symbol_name` | TEXT | NOT NULL | Exact Waymark symbol identity (`FRAME_SYNC_STREAM`, `tenants[ten_013]`, `row:CHK-14-C`, `fence:L7`) |
| `symbol_kind` | TEXT | NOT NULL | Waymark symbol kind |
| `symbol_parent` | TEXT | NULLABLE | Parent symbol name when nested |
| `start_line` | INTEGER | NOT NULL | 1-based inclusive start line |
| `start_column` | INTEGER | NOT NULL | 0-based UTF-16 code-unit start column |
| `end_line` | INTEGER | NOT NULL | 1-based inclusive end line |
| `end_column` | INTEGER | NOT NULL | 0-based UTF-16 code-unit end column |
| `scope_start` | BIGINT | NOT NULL | Inclusive canonical LF Unicode code-point start offset |
| `scope_end` | BIGINT | NOT NULL | Exclusive canonical LF Unicode code-point end offset |
| `observed_scope_hash` | VARCHAR(64) | NOT NULL | SHA-256 of `current_content[scope_start:scope_end]` |
| `observation_bundle_id` | UUID | NULLABLE, indexed | Migration 0005 bundle identity; NULL for historical singles |
| `bundle_ordinal` | INTEGER | NULLABLE, 0..31, unique with bundle | Paired nullability with bundle ID; selection order |
| `accepted_pdcp_log_id` | UUID | FK, indexed, NULLABLE | Singles retain partial uniqueness; bundled observations can share one accepted log |
| `created_at` | TIMESTAMPTZ | NOT NULL | Observation timestamp |

Retention and lifecycle semantics:
- Observations are append-only server-issued records.
- SAVE closes their editing cycle; paging and fresh admission both reject closed-cycle observations even if target version/hash are unchanged.
- Replay requires the exact authoritative observation for every accepted log recording `observation_id`, with one-to-one accepted-log linkage and matching target, cycle, preimage version/hash, scope bounds and scope hash against the sequential replay buffer. Missing or altered rows fail closed; diagnostic scope offsets are never fallback authority. Historical unobserved transactions retain their original replay path.
- Under `SELECT ... FOR UPDATE` on `cloud_target_files`, `patchdiff_submit_observed_operations` locks the `target_scope_observations` row, verifies `target_file_id`, `editing_cycle_id`, `target_version`, `target_current_hash`, `waymark_engine_version`, `observed_scope_hash`, and re-verifies Waymark symbol coordinates before restricting `patchdiff-tx/2` operations to `[scope_start, scope_end)`.
- Downgrading migration `20261026_0004` refuses while any rows exist in `target_scope_observations`.

Migration `20261027_0005_observation_bundles.py` follows 0004 without altering it.
It replaces `uq_target_scope_observations_accepted_log` with partial unique index
`uq_scope_single_accepted_log` (`observation_bundle_id IS NULL AND
accepted_pdcp_log_id IS NOT NULL`), and adds `uq_scope_bundle_ordinal`,
`ix_scope_bundle`, `ix_scope_accepted_log` and paired-nullability/range check
`ck_scope_bundle_pair`. Downgrade refuses bundled rows, many-to-one accepted links
or accepted `patchdiff-observed-batch/1` records before altering schema.
Historical rows, logs and snapshots remain unchanged.

Accepted batches retain ordered operations and authoritative scope evidence in
canonical JSON, hash it, and link every participating observation to one log in
the same transaction as all ledger entries and one target increment. The request
fingerprint identifies the submitted envelope before server evidence is attached.
Replay independently verifies canonical record/hash, exact links, bundle, group
order, target/cycle/version/preimage and all original scope hashes. Ledger facts
carry group/operation ordinals, observation IDs, original scope bounds and local
sequential operation coordinates. [Full durable contract](STRUCTURAL_BATCH_EDITING.md#durable-evidence-and-replay).
