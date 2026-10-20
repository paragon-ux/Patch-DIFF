# PatchDIFF Modernization Change Document

Status: **remaining review corrections implemented; 313 tests pass against live Postgres, including stdio and isolated populated migrations (2026-10-20). Independent closure review pending.**

Architecture decisions and primary external evidence (E1–E8): [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).

## 1. Coherent Change Set Summary

PatchDIFF is modernized into a guarded transaction service with a typed primary input (`patchdiff_submit_edits` / `patchdiff-tx/1`), authoritative target read/search tools (`patchdiff_read_target`, `patchdiff_find_occurrences`), request idempotency (`client_request_id`), stage-accurate validity reporting (`ValidationStage`), explicit replay profile dispatch (`protocol_version` + `runtime_version`), and component-level materialized-state verification (`materialized_state_checks`), while preserving frozen PDCP v0.2.3 compatibility and deterministic replay of all historical logs.

| # | Area | Decisions / Contracts | Summary of Implementation |
| --- | --- | --- | --- |
| 1 | Typed transaction input & schema | A2, A3, A6, **C1** | `patchdiff_submit_edits` accepts `intent`, `edits[]`, required guard (`expected_target_version` and/or `expected_current_hash`), optional `client_request_id`, `parent_pdcp_log_id`, `attempt`. Full item JSON Schema (`TYPED_EDIT_JSON_SCHEMA`) advertised in MCP `tools/list`. Persisted as canonical JSON with `protocol_version = "patchdiff-tx/1"`. |
| 2 | Stage-based validity & format-specific diagnostics | A7, **C2** | `ValidationStage` (`PRECONDITION_GUARD`, `PROTOCOL_VALIDATION`, `TRANSACTION_APPLICABILITY`, `COMMIT_GUARD`, `ACCEPTED`) drives `validity_levels(...)`. Typed rejections report `format: "patchdiff-tx/1"`, `requires_new_submission: true`, and `allowed_edit_fields` / `required_edit_fields` without leaking PDCP manifest keys. |
| 3 | Safe UUID & parent-lineage handling | **C2** | Malformed `target_file_id` returns `CONTEXT_INVALID`; nonexistent `target_file_id` returns `TARGET_NOT_FOUND`. Malformed, missing, or cross-target `parent_pdcp_log_id` logs a `CONTEXT_INVALID` rejection on the target with `parent_pdcp_log_id = null`. |
| 4 | Matcher overlap fix & explicit replay profiles | A2, **C3** | `find_exact_occurrences` counts all exact spans (`overlapping=True`). `SUPPORTED_RUNTIME_PROFILES` maps `"patchdiff-mvp-0.1.0" -> False` and `"patchdiff-mvp-0.2.0" -> True`; unknown runtime/protocol versions fail replay with `REPLAY_PROTOCOL_INVALID`. |
| 5 | Replay integrity & materialized-state checks | **C3** | `replay_target` verifies initial snapshot ownership & hash, per-log target ownership, version contiguity, `before_hash`, `pdcp_content_hash`, and `after_hash`, and reports `materialized_state_checks` (`content_matches`, `stored_hash_matches`, `recomputed_hash_matches`, `version_matches`). |
| 6 | Request idempotency & lost-response recovery | A6, **C4** | `client_request_id` + `request_fingerprint` on `append_only_pdcp_logs` (`uq_pdcp_logs_target_client_request_id`). Duplicate requests recover the recorded terminal outcome (`deduplicated: true`) prior to stale-guard checks; conflicting reuse with a different payload rejects with `CONTEXT_INVALID`. |
| 7 | Ledger schema & derived facts | A3, **C5** | Migration `20261020_0002` adds `origin` (`'pdcp_manifest'` or `'typed'`) and `derived_json` to `append_only_manifest_ledger`, relaxes legacy prose columns to nullable, and populates `derived_json` on both PDCP and typed acceptances. |
| 8 | Authoritative reads, search & history pagination | A1, A5, **C6** | `patchdiff_read_target` (`next_start`), `patchdiff_find_occurrences` (`start_occurrence`, `max_results`, `next_occurrence_index`, `returned_count`), and `patchdiff_get_pdcp_log` (`before_sequence`, `status`, `content_hash`, `client_request_id`). |
| 9 | Offline payload & verdict accounting | A8 | `evaluation/offline_eval.py` separates framing overhead (`typed_match` vs `pdcp`) from reduced-manifest prose savings (`typed_min` vs `typed_match`) across both persisted records and MCP request payloads. |
| 10 | Coherent active documentation & skills | R3, Section 5 | Active docs and all four `.agents/skills/patchdiff-*/SKILL.md` rewritten coherently without contradictory amendment footers. |

## 2. Code Files Modified or Added

| File | Role |
| --- | --- |
| `backend/app/core/versions.py` | `RUNTIME_VERSION = "patchdiff-mvp-0.2.0"`, `LEGACY_RUNTIME_VERSION = "patchdiff-mvp-0.1.0"`, `SUPPORTED_RUNTIME_PROFILES`, `UnsupportedRuntimeVersionError`, `resolve_overlapping_matches`. |
| `backend/app/core/validity.py` | `ValidationStage` enum and stage-aware `validity_levels(status, failure_reason, stage=...)`. |
| `backend/app/core/result.py` | `AcceptedCoreResult.change_facts`. |
| `backend/app/pdcp/matcher.py` | `find_exact_occurrences(target_text, match_text, *, overlapping=True)`. |
| `backend/app/pdcp/disambiguation.py` | `resolve_match_span(..., *, overlapping=True)`. |
| `backend/app/pdcp/applier.py` | `apply_pdcp_transaction(..., *, overlapping_matches=True)` computing `change_facts` (`span_start`, `span_end`, `matched_chars`, `replacement_chars`, `matched_sha256`, `replacement_sha256`) and `requires_new_submission`. |
| `backend/app/pdcp/typed.py` | `TYPED_PROTOCOL_VERSION = "patchdiff-tx/1"`, `TYPED_EDIT_JSON_SCHEMA`, `REQUIRED_TYPED_EDIT_FIELDS`, `ALLOWED_TYPED_EDIT_FIELDS`, `validate_client_request_id`, `build_record`, `canonical_record_json`, `parse_typed_record`, `decode_record`, `to_parsed_transaction`, `require_guard`. |
| `backend/app/storage/models.py` | `AppendOnlyManifestLedger` (`origin`, `derived_json`, nullable prose columns) and `AppendOnlyPdcpLogs` (`client_request_id`, `request_fingerprint`). |
| `backend/app/migrations/versions/20261020_0002_typed_ledger.py` | Migration `20261020_0002` (down_revision `20260510_0001`) adding ledger and idempotency columns, partial unique index `uq_pdcp_logs_target_client_request_id`, and downgrade safety check. |
| `backend/app/services/pdcp_service.py` | Unified `_submit` pipeline supporting `submit_edits` and `submit_pdcp`, `client_request_id` deduplication/recovery, safe UUID and parent-lineage validation, stage tracking, format-specific diagnostics, and `derived_json` on all accepted ledger rows. |
| `backend/app/services/replay_service.py` | Explicit `(protocol_version, runtime_version)` dispatch, initial-snapshot and `pdcp_content_hash` verification, and `materialized_state_checks`. |
| `backend/app/services/read_service.py` | `slice_content` (`next_start`), `occurrence_report` (`start_occurrence`, `next_occurrence_index`, `returned_count`), `read_target`, `find_occurrences`, `clamp_limit`. |
| `backend/app/services/prompt_context_service.py` | `context_truncated`, `target_chars`, safe UUID handling, and `origin`/`derived` in `_active_manifest_summary`. |
| `backend/app/services/regeneration_service.py` | Deprecated compatibility wrappers passing version/hash guards through and safely handling missing/malformed IDs. |
| `backend/app/services/export_service.py` & `save_service.py` | Safe UUID validation on `get_target`, `export_target`, and `save_target`. |
| `backend/app/mcp/tools.py` | Tool registrations for `patchdiff_submit_edits`, `patchdiff_read_target`, `patchdiff_find_occurrences`, updated `patchdiff_submit_pdcp`, `patchdiff_replay`, `patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`. |
| `backend/app/mcp/external_adapter.py` | Full `TYPED_EDIT_JSON_SCHEMA` advertised in `tools/list`, JSON-RPC `params` validation (`-32602`). |
| `evaluation/offline_eval.py` | Three-way deterministic byte & verdict comparison (`pdcp_v023`, `typed_matched`, `typed_minimal`) across persisted records and MCP request payloads. |

## 3. Documentation Reconciliation Table

To resolve R3 (contradictory "Modernization amendment" footers), all active documentation and skills were rewritten coherently in their main body while historical design artifacts were left untouched:

| Document | Layer | Old Statement (Superseded) | New Coherent Statement |
| --- | --- | --- | --- |
| `AGENTS.md` | Layer 5 (Agent Rules) | Treated `.pdcp` as the only transaction format, required server-mediated regeneration, listed stale `skills/*.md` paths, and ended with a conflicting amendment footer. | States `patchdiff_submit_edits` (`patchdiff-tx/1`) as primary and `.pdcp` v0.2.3 as frozen legacy, host-owned retry via `patchdiff_read_target` / `patchdiff_find_occurrences`, stage-based validity, `client_request_id` idempotency, and exact `.agents/skills/patchdiff-*/SKILL.md` paths. |
| `docs/MCP_FIRST_MVP.md` | Layer 3 (Active Spec) | Defined MVP around server-built prompts, model-emitted raw `.pdcp` only, and server-side regeneration orchestration, with a conflicting footer. | Defines the modernized MCP-first transaction service: typed `patchdiff_submit_edits` primary, `.pdcp` v0.2.3 legacy, authoritative read/search tools, host-owned retry, `client_request_id` idempotency, SAVE, and multi-format replay. |
| `docs/PATCHDIFF_CORE_SPEC.md` | Layer 3 (Active Spec) | Described only `.pdcp` parsing, 7-field manifest requirement for all inputs, and `after_hash`-only replay, with a conflicting footer. | Specifies shared deterministic core semantics for both `patchdiff-tx/1` and `.pdcp` v0.2.3, overlapping-match enumeration (`patchdiff-mvp-0.2.0`) vs legacy replay profile (`patchdiff-mvp-0.1.0`), `ValidationStage`, `derived_json`, and component-level replay verification. |
| `docs/MCP_TOOLS.md` | Layer 3 (Active Spec) | Listed 11 original tools as active and tacked new tools onto a footer. | Specifies all 14 MCP tools coherently in the main body, grouped into Core Lifecycle, Authoritative Reads & Search, Transaction Submission (Typed Primary + Legacy PDCP), Checkpointing/Replay/Audit, and Convenience/Deprecated Compatibility Tools, with full request/response schemas. |
| `docs/DATA_MODEL.md` | Layer 3 (Active Spec) | Showed only migration `0001` columns (`append_only_manifest_ledger` all `NOT NULL`, no `origin`/`derived_json`, no `client_request_id`), with a footer. | Documents the full schema after migration `20261020_0002`, including `origin`, `derived_json`, nullable legacy prose columns, `client_request_id`, `request_fingerprint`, and `uq_pdcp_logs_target_client_request_id`. |
| `docs/PDCP_FORMAT.md` | Layer 3 (Active Spec) | Presented `.pdcp` v0.2.3 as the only transaction format, with a footer. | Documents both transaction formats coherently: `patchdiff-tx/1` (primary typed JSON record) and `.pdcp` v0.2.3 (frozen declarative text format), including field mapping and shared applier semantics. |
| `docs/TEST_MATRIX.md` | Layer 3 (Active Spec) | Listed only original v0.1 tests with a footer. | Integrates unit, Postgres integration (`0001` + `0002`), and real stdio MCP subprocess E2E test matrices covering C1–C6. |
| `docs/CODEX_BUILD_PLAN.md` | Layer 3 (Active Spec) | Described original 8-phase build plan with a footer. | Records phases 1–8 (initial MVP) plus Phase 9 (Modernization & Argon Remediation, completed and verified). |
| `docs/HOST_INTEGRATION_GUIDE.md` & `docs/CLAUDE_DESKTOP_SETUP.md` | Layer 4 (Host Guides) | Omitted `client_request_id`, pagination parameters, and stage validity details; `CLAUDE_DESKTOP_SETUP.md` used a footer. | Coherently documents the host-owned edit loop, `patchdiff_submit_edits` schema, `client_request_id` recovery, pagination (`next_start`, `start_occurrence`), stage-based `validity`, and stdio MCP setup. |
| `README.md` & `README_INTERNAL_MCP.md` | Layer 4 (Entry Guides) | Used `.pdcp`-only flow in main body with a footer. | Coherently presents the modernized architecture, tool table, Docker Postgres setup, migration commands, and verification commands. |
| `.agents/skills/patchdiff-*/SKILL.md` (all 4 skills) | Layer 5 (Skills) | `patchdiff-core-runtime` was untouched and taught obsolete rules; the other 3 had 3-line footers contradicting their bodies. | All 4 skills rewritten coherently to guide work on the modernized codebase. |

## 4. Requirement-to-Evidence Matrix (C1–C6 & R1–R4)

| Requirement | Implementation Location | Automated Test / Verification Evidence | Status |
| --- | --- | --- | --- |
| **R1**: Live Postgres & Alembic verification | `docker-compose.yml`, `20260510_0001`, `20261020_0002` | `alembic upgrade head -> downgrade 20260510_0001 -> upgrade head` on `postgres:16.3-alpine`; `test_migrations_reachable.py`; downgrade exception verified when typed rows exist. | **VERIFIED** |
| **R2**: Primary external evidence E1–E8 | `docs/MODERNIZATION_ARCHITECTURE.md` Section 3 | Direct HTTP fetches of primary vendor pages E1–E8 on `2026-10-20` with verified tool versions (`text_editor_20250728`, `apply_patch`, MCP Python SDK `v2.3.0`). | **VERIFIED** |
| **R3**: Coherent documentation & skills | All Layer 2–5 docs and `.agents/skills/patchdiff-*/SKILL.md` | Rewritten coherently; reconciliation table in Section 3 above; zero contradictory "Modernization amendment" footers remain. | **VERIFIED** |
| **R4 / C1**: Typed contract & MCP discovery schema | `backend/app/pdcp/typed.py`, `backend/app/mcp/external_adapter.py` | `test_typed_edit_schema_conforms_to_runtime_contract`, `test_subprocess_initialize_and_list_new_tools_with_complete_schema`, `test_real_stdio_subprocess_mcp_full_modernized_workflow`. | **VERIFIED** |
| **C2**: Stage-based `validity`, format-specific diagnostics, safe UUID/parent lineage | `backend/app/core/validity.py`, `backend/app/services/pdcp_service.py` | `test_stage_aware_validity_distinguishes_precondition_vs_applicability_and_commit_guard`, `test_format_specific_vs_format_neutral_diagnostics_and_no_pdcp_leakage_on_typed_rejection`, `test_validity_stages_across_typed_and_pdcp_paths_via_mcp_tools`, `test_malformed_uuid_and_invalid_parent_lineage_handling`. | **VERIFIED** |
| **C3**: Explicit replay profile dispatch & component `materialized_state_checks` | `backend/app/core/versions.py`, `backend/app/services/replay_service.py` | `test_explicit_runtime_profile_dispatch_and_unknown_version_rejection`, `test_replay_detects_tampered_before_hash_broken_version_chain_and_unknown_profiles`, `test_replay_success_is_distinct_from_materialized_state_health_and_reports_component_checks`, `test_legacy_runtime_log_with_overlap_acceptance_still_replays`. | **VERIFIED** |
| **C4**: `client_request_id` idempotency & lost-response outcome recovery | `backend/app/services/pdcp_service.py`, `20261020_0002_typed_ledger.py` | `test_client_request_id_idempotency_lost_response_recovery_and_conflict_rejection` (covers normal retry, ABA hash sequence, no-op hash edit, rejected retry, conflicting payload reuse, and `get_pdcp_log` lookup). | **VERIFIED** |
| **C5**: Ledger `origin` & `derived_json` on both typed and PDCP paths | `backend/app/services/pdcp_service.py`, `backend/app/storage/models.py` | `test_pdcp_and_typed_ledger_rows_both_carry_derived_facts_and_origin`, `test_live_postgres_schema_has_0002_columns_and_unique_index`. | **VERIFIED** |
| **C6**: Read/search continuation & history pagination | `backend/app/services/read_service.py`, `backend/app/mcp/tools.py` | `test_slice_content_is_bounded_and_reports_truncation_and_next_start`, `test_occurrence_report_is_bounded_and_paginates_via_start_occurrence`, `test_read_target_and_find_occurrences_pagination_and_argument_validation`. | **VERIFIED** |

## 5. Verification Executed

### 5.1 Commands and Results

| Command | Result |
| --- | --- |
| `docker compose up -d` (`postgres:16.3-alpine` on `127.0.0.1:5432`) | Container `patchdiff-postgres` healthy |
| `alembic -c backend/app/migrations/alembic.ini upgrade head -> downgrade 20260510_0001 -> upgrade head` | Full migration cycle succeeded cleanly on empty/legacy DB; downgrade guard raised `Cannot downgrade 20261020_0002: typed ledger rows exist` when typed rows were present |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/unit -q` | **178 passed** |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/integration -q` | **135 passed** (against live Postgres `127.0.0.1:5432/patchdiff`, including real stdio subprocess E2E test) |
| `.\.venv\Scripts\python.exe -m pytest -q` | **313 passed** |
| `$env:PYTHONPATH="backend"; .\.venv\Scripts\python.exe evaluation/offline_eval.py` | **OK** (verdict equivalence across all 5 scenarios and 3 proposal variants) |

### 5.2 Offline Payload Accounting Output (`evaluation/offline_eval.py`)

```text
=== 1. Persisted Record UTF-8 Bytes (append_only_pdcp_logs.pdcp_content) ===
scenario                         pdcp B  typed_match B  typed_min B  match/pdcp  min/pdcp  verdict (pdcp / matched / minimal)
-----------------------------------------------------------------------------------------------------------------------------
1 tiny edit                         331            382          206        1.15      0.62  accepted / accepted / accepted
5 small edits                      1287           1194          314        0.93      0.24  accepted / accepted / accepted
1 edit, 2 KB span                  4543           4672         4496        1.03      0.99  accepted / accepted / accepted
quotes+backslashes+unicode          345            403          227        1.17      0.66  accepted / accepted / accepted
payload has a delimiter line        339            393          217        1.16      0.64  rejected:block_malformed / accepted / accepted [PDCP delimiter collision]

=== 2. MCP Tool Request Payload UTF-8 Bytes (wire arguments JSON) ===
scenario                        submit_pdcp B  edits_match B  edits_min B  match/pdcp  min/pdcp
-----------------------------------------------------------------------------------------------
1 tiny edit                               451            327          151        0.73      0.33
5 small edits                            1467           1139          259        0.78      0.18
1 edit, 2 KB span                        4741           4617         4441        0.97      0.94
quotes+backslashes+unicode                472            348          172        0.74      0.36
payload has a delimiter line              462            338          162        0.73      0.35
```


## 6. PR #3 — Remaining-finding remediation

The [head-pinned recheck](reviews/PR-1-60fa01f-findings-recheck.md) closed 11 original findings, retained six, and identified TEST-001. It supersedes the earlier blanket closure claim. Historical review reports are preserved; original finding identities and priorities below are retained.

| Finding ID | Priority | Implementation / acceptance evidence | Status |
| --- | --- | --- | --- |
| DB-002 | P1 | c1df5b9; locked refresh, pending mutation rejection, retained-state/caller transaction and synchronized live recheck | Closed at prior recheck |
| DB-001 | P2 | c1df5b9; fresh locked replay inputs and synchronized writer-blocking recheck | Closed at prior recheck |
| ARCH-001 | P2 | 30dd14f; 4,000/8,000 bounds with Unicode continuation | Closed at prior recheck |
| ARCH-002 | P2 | 30dd14f; bounded 230-entry/two-cycle traversal | Closed at prior recheck |
| DOC-002 | P2 | 68dce30; actual configuration variable and parent/child chain | Closed at prior recheck |
| DOC-003 | P3 | 44fc6e1; historical reference paths resolve | Closed at prior recheck |
| RUN-001 | P2 | b5a54f3; unhashable risk rejection and durable audit verified | Closed at prior recheck |
| RUN-002 | P2 | b5a54f3; multi-fault stage provenance verified | Closed at prior recheck |
| SVC-001 | P2 | abeb58e; only rejected parents support retry lineage | Closed at prior recheck |
| SVC-002 | P3 | abeb58e; strict attempt metadata validation | Closed at prior recheck |
| SCRIPT-001 | P2 | 78b16e6; independent verdict/hash oracle fault-injected | Closed at prior recheck |
| MCP-001 | P2 | Discovery advertises non-null guard alternatives, nonblank prose, storage integer bounds and exact hash/ID domains. Actual schema validated with a test-only jsonschema validator against live submission and persisted outcomes. Unguarded known-target calls reach durable service rejection. | Implemented; independent recheck pending |
| MCP-002 | P2 | Full-string change-ID validation rejects trailing newline, preserves colon/null/default/uniqueness behavior; schema and live boundary cases covered. | Implemented; independent recheck pending |
| RUN-003 | P2 | Strict hash fullmatch before persistence; typed and legacy newline-hash calls reject normally, preserve raw evidence, leave constrained metadata null and retain durable rejection. | Implemented; independent recheck pending |
| DOC-001 | P2 | Recovery guide distinguishes paged history, unknown outcomes and still-running requests, optional legacy guards, actual conflict payload and printable-ASCII request IDs. | Implemented; independent recheck pending |
| SKILL-001 | P3 | Exact validity enum/phase table, null unreached stages and true simulation validity at commit failure. | Implemented; independent recheck pending |
| SKILL-002 | P3 | One-based indices, real matcher signature, advisory region hint, actual ID/storage/sequence names and typed risk behavior. | Implemented; independent recheck pending |
| TEST-001 (new) | P2 | Unique owned schemas and actual sessions/version zero; populated legacy accepted/rejected history survives upgrade/downgrade/upgrade; typed downgrade refusal preserves rows and revision and remains replayable. | Implemented; independent recheck pending |

### Verification scope

- Complete local suite: **313 passed** (178 unit, 135 live Postgres integration), including real stdio subprocess rejection/audit workflow.
- Focused schema/audit + typed unit checks: **86 passed**.
- Migration module independently: **6 passed**, including populated legacy preservation and typed-history refusal in isolated schemas.
- Offline evaluation: **OK**. Results measure bytes and deterministic outcomes, not model performance.
- Alembic accepts an explicitly supplied connection so migration tests control isolation and transaction scope without downgrading shared data. Ordinary CLI migration setup is unchanged.
- jsonschema is a test-only direct dependency, pinned with its transitive dependencies in requirements.lock; no production schema-validation dependency or transport rejection layer was added.
- A separate live stdio/Postgres session and independent review will be recorded with their actual revision before merge. No new CI or review approval is claimed here.
