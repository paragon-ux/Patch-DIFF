# DATA_MODEL.md

## Guarded replacement, line reads and preview

New patchdiff_submit_replacement records guarded tx/3 sole replace_all on immutable0.4.0 through the existing locked pipeline; tx/2/0.3.0 remain unchanged. Fresh replacement raw/result limits are1,000,000 code points and1,048,576 UTF-8 bytes each (inclusive). Invalid Unicode keeps audited classification; existing-key recovery/conflict precedes fresh admission. Oversized valid fresh replacements return pre-admission invalid_argument/replacement_too_large without writes; replay bypasses admission limits. Empty replacement is valid; one typed ledger row records full original span and operation=replace_all.

patchdiff_read_lines uses one ordinary column observation under no_autoflush, one-based inclusive LF-only line ranges, trailing newline inclusion and final empty line, range-relative offset continuation, default4000/cap8000 code points. It never edits or flushes local state. patchdiff_preview uses the same fresh read-only guard/decode/apply evaluator as submit with coherent ordinary observation, explicit format and pending-local-target rejection. Preview has no request-key/audit/lineage parameter, writes/locks/commit/rollback; accepted previews return facts/hash, rejected previews no partial facts. It never invokes post-commit near misses. Submission always re-locks/rechecks.

Discovery publishes bounded schema-conforming examples, copied per result, at most65,536 compact ASCII-escaped JSON bytes overall and8192 for the complete examples map. Every advertised(tool,index) is bound to real returned IDs/guards/parents/cursors and executed over stdio/PostgreSQL, including exact dedup and complete attempt-descending/ledger-page-ascending traversal. No migration, optional typed guards, normalized identity, editing adapter, model-success or representative production-performance claim. Dataset and performance evidence is limited to local synthetic cases because no representative sanitized dataset or production benchmark threshold was supplied.


## Guarded operations and bounded diagnostics

`include_correlation_id=false` is a boolean response option on submissions; true emits a fresh UUIDv4 even on exact recovery. Invalid types return pre-admission invalid_argument with no attempt. Correlation never enters durable records, request keys or fingerprints.

New applicability ambiguity/selector failures retain at most five exact candidates (20 code points each side,64 match preview;8192 compact ASCII-escaped JSON bytes including wrapper), stage/prior-change/observed identity and explicit truncation; no cursor or selection. Absent/sequential failures retain at most 64 code points of immutable query evidence (1024 wrapper bytes). Response-only near misses compare only the original at-most-256-point failure prefix after actual successful service-owned commit/lock release; caller-owned transactions omit with caller_transaction. Work is at most 1,000,000 Levenshtein cells, windows query length±1, distance threshold min(4,max(1,length//4)), at most three candidates ranked distance/start/end,16-point context each side and8192 wrapper bytes. Exhaustion/oversize/historical inputs have explicit omission; unexpected post-commit errors propagate without claiming rollback. Original diagnostics stay immutable on recovery. New enrichment fields combined are at most18432 compact ASCII-escaped JSON bytes; this excludes preexisting arbitrary evidence.

`patchdiff_submit_operations` records `patchdiff-tx/2`: intent, mandatory guard and ordered explicit match/span operations. Span start/end are non-bool integers 0..2^63-1, end exclusive and end>=start; expected_text/replace are required strings. Coordinates describe each sequential canonical buffer; exact canonical expected text must equal that span. Empty-span insertion is allowed with empty expected text; selectors on span and unknown fields/operations reject. Mixed match/span edits are atomic. Applicability errors are span_out_of_bounds and span_expected_text_mismatch. Both forms use the existing locked submit/rejection/ledger path. New records use immutable patchdiff-mvp-0.3.0 enabling span operations; old forms keep 0.2.2 and unchanged records/fingerprints/profiles. Replay refuses unsupported profile/operation pairs. Span facts include operation=span and existing runtime-derived hashes/spans/counts; ledger origin remains typed. No migration or replace_all in 0.3.0. Discovery advertises operation schema and x-patchdiff-capabilities. Discovery also provides bounded argument examples.


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

#### Bounded rejected-buffer evidence

New rejected attempts store `failure_context` within existing `diagnostic_json`; no column or migration is added. It contains only the bounded original failure prefix, code-point counts, canonical/intermediate stage, prior simulated-change count and transaction-start observed target identity, using the representation and JSON-byte limits in MCP_TOOLS. This evidence is immutable. Exact recovery returns the stored diagnostic unchanged; pre-feature rows remain without failure context. Top-level fresh `current_context` is response-only and is never written into the recovered row. Unknown targets and pending local state have no target-linked durable attempt; their contexts explicitly report unavailable. Qualified audit and caller commit/rollback ownership are unchanged.

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

An admitted fingerprint conflict uses client_request_id=NULL so the original target/key unique row stays authoritative. Its request_fingerprint is the newly submitted fingerprint, not the original row's fingerprint. Repeated conflicts remain separate immutable audit rows, even when their submitted fingerprints are identical. Diagnostics link the original log and show the submitted key with a256-character preview/truncation flag; the original keyed row retains the complete key. The returned response still identifies the submitted key and returns the newly persisted rejection's log ID.

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
