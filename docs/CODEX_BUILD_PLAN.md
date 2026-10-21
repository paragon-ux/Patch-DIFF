# CODEX_BUILD_PLAN.md

## Scope

This document records the architectural build phases of PatchDIFF, from initial MVP foundations through Phase 9 (Modernization & Remediation, completed and verified).

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built record and verification evidence: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

---

## Build Phases Summary

```text
Phase 1: Local runtime confidence & pure core (COMPLETED)
Phase 2: PDCP format robustness baseline & delimiters (COMPLETED)
Phase 3: Internal MCP tool contract tests (COMPLETED)
Phase 4: MCP E2E happy / reject / lineage flows (COMPLETED)
Phase 5: Model output robustness through MCP (COMPLETED)
Phase 6: SAVE / Replay / Export through MCP (COMPLETED)
Phase 7: Real external MCP stdio adapter wiring (COMPLETED)
Phase 8: Offline evaluation foundation (COMPLETED)
Phase 9: Modernization & Argon Remediation (COMPLETED & VERIFIED 2026-10-20)
```

---

## Completed Phases

### Phase 1–8: Initial MVP Baseline
- Built pure deterministic core runtime (`backend/app/core/`, `backend/app/pdcp/`).
- Established Postgres persistence layer (`cloud_target_files`, `append_only_pdcp_logs`, `append_only_manifest_ledger`, `target_snapshots`, `editing_cycles`) under Alembic migration `20260510_0001_initial_schema`.
- Implemented MCP tool registry and stdio JSON-RPC adapter (`backend/app/mcp/external_adapter.py`).
- Added initial test suites for parser robustness, delimiter validation, SAVE checkpoints, and deterministic replay.

### Phase 9: Modernization & Remediation (Completed 2026-10-20)
Remediated the incomplete prototype left by Claude Sonnet, aligned PatchDIFF with primary vendor evidence (E1–E8), and verified all contracts (C1–C6) against live Postgres and a real stdio MCP subprocess:

1. **Primary External Evidence Grounding (R2)**:
   - Fetched and verified primary vendor documentation on 2026-10-20 for Claude Text Editor Tool (`text_editor_20250728`, E1), OpenAI Apply Patch tool (`apply_patch`, E2), Claude Checkpointing (E3), Claude Memory (E4), Claude Hooks (E5), Antigravity Review Changes Editor (E6), Antigravity MCP integration (E7), and MCP Python SDK (`v2.3.0`, E8).
2. **C1 (Typed Transactions Primary, Legacy PDCP Frozen)**:
   - Implemented `patchdiff_submit_edits` accepting `intent`, `edits[]`, required state guard (`expected_target_version` / `expected_current_hash`), optional `client_request_id`, `parent_pdcp_log_id`, and `attempt`.
   - MCP `tools/list` advertises complete `TYPED_EDIT_JSON_SCHEMA` for `edits` items.
   - Preserved `.pdcp` v0.2.3 (`patchdiff_submit_pdcp`) as a frozen legacy format sharing the same deterministic applier.
3. **C2 (Stage-Based Validity & Format-Specific Diagnostics)**:
   - Implemented `ValidationStage` enum and stage-driven `validity_levels(...)` reporting (`protocol_valid`, `transaction_valid`, `task_correct: "not_evaluated"`, `semantic: "not_evaluated"`).
   - Format-specific diagnostics: typed rejections report `format: "patchdiff-tx/1"`, `requires_new_submission: true`, `allowed_edit_fields`, and `required_edit_fields` without leaking PDCP manifest keys.
   - Robust UUID and lineage validation: malformed `target_file_id` returns `CONTEXT_INVALID`; missing target returns `TARGET_NOT_FOUND`; invalid parent log ID logs a `CONTEXT_INVALID` rejection on the target with `parent_pdcp_log_id = null`.
4. **C3 (Matcher Overlap Fix, Explicit Profile Dispatch & Component Checks)**:
   - Fixed `matcher.py` to count all exact matches including overlaps (`overlapping=True`).
   - Implemented `SUPPORTED_RUNTIME_PROFILES` with explicit dispatch for `"patchdiff-mvp-0.2.2"` (current) and historical profiles `"patchdiff-mvp-0.2.1"` / `"patchdiff-mvp-0.2.0"` (overlapping, singleton selectors ignored) and `"patchdiff-mvp-0.1.0"` (legacy non-overlapping replay).
   - `patchdiff_replay` validates initial snapshot hash, contiguous version chains, before/after hashes, and reports component-level `materialized_state_checks` (`content_matches`, `stored_hash_matches`, `recomputed_hash_matches`, `version_matches`).
5. **C4 (Request Idempotency & Lost-Response Recovery)**:
   - Migration `20261020_0002` added `client_request_id`, `request_fingerprint`, and partial unique index `uq_pdcp_logs_target_client_request_id`.
   - Deduplicated requests with identical fingerprints recover their terminal outcome (`deduplicated: true`) prior to evaluating stale guards.
   - Conflicting reuse with different payloads rejects with `CONTEXT_INVALID`.
6. **C5 (Ledger Schema & Derived Facts)**:
   - Migration `20261020_0002` added `origin` and `derived_json` to `append_only_manifest_ledger`, relaxing legacy prose columns to nullable.
   - Populated `derived_json` (`span_start`, `span_end`, `matched_sha256`, char counts) on all accepted ledger rows across both typed and PDCP inputs.
7. **C6 (Authoritative Reads, Exact Search & Pagination)**:
   - Implemented `patchdiff_read_target` with `next_start` continuation.
   - Implemented `patchdiff_find_occurrences` with `start_occurrence`, `max_results`, `next_occurrence_index`, and `returned_count`.
   - Added `client_request_id` filter and `limit` clamping to `patchdiff_get_pdcp_log`.
8. **Real Stdio Subprocess E2E Testing**:
   - Added `test_real_stdio_subprocess_mcp_full_modernized_workflow` executing all 8 steps of the product workflow over stdio JSON-RPC backed by live Postgres.
9. **Documentation & Skills Coherence (R3)**:
   - Rewrote all active documentation files and workspace skills coherently, eliminating contradictory amendment footers.

---

## Verification Summary (2026-10-20)

- Live Postgres (`postgres:16.3-alpine` on Docker `127.0.0.1:5432`): verified.
- Alembic migration `upgrade -> downgrade -> upgrade` cycle: verified.
- Pure core unit tests: **174 / 174 passed**.
- Postgres integration & stdio subprocess tests: **87 / 87 passed** (Total: **261 passed**).
- Offline payload and verdict accounting: **OK** across all 5 scenarios and 3 proposal variants.
