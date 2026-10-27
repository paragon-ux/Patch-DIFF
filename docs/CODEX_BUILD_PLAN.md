# PatchDIFF Implementation Map

## Scope

This document maps product capabilities to their implementation and verification boundaries. Current contracts are in the architecture and tool specifications.

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built record and verification evidence: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

---

## Runtime and persistence foundations

- Structural batch implementation: `pdcp/observed_batch.py`, bundle issuance in
  `services/scope_observation_service.py`, existing locked submission path,
  explicit batch replay dispatch and additive migration `20261027_0005`.
- External MCP profiles: immutable startup selection, shared advertisement/call
  filtering and generated schemas for the two extended tool identities.
- [Contract, implementation trace and deterministic evidence](STRUCTURAL_BATCH_EDITING.md).

- Built pure deterministic core runtime (`backend/app/core/`, `backend/app/pdcp/`).
- Established Postgres persistence layer (`cloud_target_files`, `append_only_pdcp_logs`, `append_only_manifest_ledger`, `target_snapshots`, `editing_cycles`) under Alembic migration `20260510_0001_initial_schema`.
- Implemented MCP tool registry and stdio JSON-RPC adapter (`backend/app/mcp/external_adapter.py`).
- Added initial test suites for parser robustness, delimiter validation, SAVE checkpoints, and deterministic replay.

## Transaction, transport and history capabilities

1. **Primary External Evidence Grounding**:
   - Fetched and verified primary vendor documentation on 2026-10-20 for Claude Text Editor Tool (`text_editor_20250728`, E1), OpenAI Apply Patch tool (`apply_patch`, E2), Claude Checkpointing (E3), Claude Memory (E4), Claude Hooks (E5), Antigravity Review Changes Editor (E6), Antigravity MCP integration (E7), and MCP Python SDK (`v2.3.0`, E8).
2. **Typed Transactions Primary, Legacy PDCP Frozen**:
   - Implemented `patchdiff_submit_edits` accepting `intent`, `edits[]`, required state guard (`expected_target_version` / `expected_current_hash`), optional `client_request_id`, `parent_pdcp_log_id`, and `attempt`.
   - MCP `tools/list` advertises complete `TYPED_EDIT_JSON_SCHEMA` for `edits` items.
   - Preserved `.pdcp` v0.2.3 (`patchdiff_submit_pdcp`) as a frozen legacy format sharing the same deterministic applier.
3. **Stage-Based Validity & Format-Specific Diagnostics**:
   - Implemented `ValidationStage` enum and stage-driven `validity_levels(...)` reporting (`protocol_valid`, `transaction_valid`, `task_correct: "not_evaluated"`, `semantic: "not_evaluated"`).
   - Format-specific diagnostics: typed rejections report `format: "patchdiff-tx/1"`, `requires_new_submission: true`, `allowed_edit_fields`, and `required_edit_fields` without leaking PDCP manifest keys.
   - Robust UUID and lineage validation: malformed `target_file_id` returns `CONTEXT_INVALID`; missing target returns `TARGET_NOT_FOUND`; invalid parent log ID logs a `CONTEXT_INVALID` rejection on the target with `parent_pdcp_log_id = null`.
4. **Matcher Overlap Fix, Explicit Profile Dispatch & Component Checks**:
   - Fixed `matcher.py` to count all exact matches including overlaps (`overlapping=True`).
   - Implemented `SUPPORTED_RUNTIME_PROFILES` with explicit dispatch for `"patchdiff-mvp-0.2.2"` (new typed-match/legacy submissions), `"patchdiff-mvp-0.3.0"` (match/span operations), `"patchdiff-mvp-0.4.0"` (sole replacement) and `"patchdiff-mvp-0.5.0"` (match/span operations with span context guards). Historical `"patchdiff-mvp-0.2.1"` / `"patchdiff-mvp-0.2.0"` retain overlapping matching with ignored singleton selectors; `"patchdiff-mvp-0.1.0"` retains non-overlapping replay.
   - `patchdiff_replay` validates initial snapshot hash, contiguous version chains, before/after hashes, and reports component-level `materialized_state_checks` (`content_matches`, `stored_hash_matches`, `recomputed_hash_matches`, `version_matches`).
5. **Request Idempotency & Lost-Response Recovery**:
   - Migration `20261020_0002` added `client_request_id`, `request_fingerprint`, and partial unique index `uq_pdcp_logs_target_client_request_id`.
   - Deduplicated requests with identical fingerprints recover their terminal outcome (`deduplicated: true`) prior to evaluating stale guards.
   - Conflicting reuse with different payloads rejects with `CONTEXT_INVALID`.
6. **Ledger Schema & Derived Facts**:
   - Migration `20261020_0002` added `origin` and `derived_json` to `append_only_manifest_ledger`, relaxing legacy prose columns to nullable.
   - Populated `derived_json` (`span_start`, `span_end`, `matched_sha256`, char counts) on all accepted ledger rows across both typed and PDCP inputs.
7. **Authoritative Reads, Exact Search & Pagination**:
   - Implemented `patchdiff_read_target` with `next_start` continuation.
   - Implemented `patchdiff_find_occurrences` with `start_occurrence`, `max_results`, `next_occurrence_index`, and `returned_count`.
   - Added `client_request_id` filter and `limit` clamping to `patchdiff_get_pdcp_log`.
8. **Real Stdio Subprocess E2E Testing**:
   - Added `test_real_stdio_subprocess_mcp_full_modernized_workflow` executing all 8 steps of the product workflow over stdio JSON-RPC backed by live Postgres.
9. **Guarded Replacement and Advisory Tools**:
   - `patchdiff_submit_replacement` uses `patchdiff-tx/3` and immutable runtime 0.4.0 through the same locked transaction pipeline. Fresh raw and canonical results each allow at most 1,000,000 code points and 1,048,576 UTF-8 bytes, inclusively; replay bypasses fresh admission limits.
   - `patchdiff_read_lines` provides one-based inclusive LF-only ranges, range-relative and absolute continuation and 4,000/8,000-code-point default/maximum pages without flushing local state.
   - `patchdiff_preview` shares submission evaluation without audit, locks, writes, commit or rollback. Its complete payload is bounded to 32,768 compact ASCII-escaped JSON bytes; accepted evidence is a prefix of at most 32 complete facts, at most 2,048 bytes each and 16,384 wrapped bytes. Submissions re-lock and recheck.
   - Discovery examples are copied per result; discovery is capped at 65,536 compact ASCII-escaped JSON bytes and its complete examples map at 8,192 bytes.
10. **PR #11 Friction Follow-Up** ([decisions](usability/friction-followup-decision.md)):
   - Span context guards under immutable runtime 0.5.0, advisory accepted-transaction warnings and one shared retryable set.
   - Migration `20261022_0003` records upload line endings; export formats are an honoured enum.
   - Focused failure windows, consumed-match evidence, distinct near misses over a bounded failing-buffer copy, request-key conflict fields, joinable history, line-read offsets, literal tool-result text inside ASCII JSON-RPC lines and a SAVE version guard.

## Verification boundaries

Use [TEST_MATRIX.md](TEST_MATRIX.md) for unit, live PostgreSQL, real stdio, migration and offline verification coverage. Results must identify the executed revision. Historical totals do not certify current source or publication CI. Offline evaluation measures serialized bytes and deterministic outcomes; no live-model, representative dataset or production performance result is established.
