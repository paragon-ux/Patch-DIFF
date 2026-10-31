# TEST_MATRIX.md

## Scope

This document defines the comprehensive test matrix for PatchDIFF, covering pure-core unit tests, Postgres integration tests, real stdio MCP subprocess workflows, and offline evaluation.

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](../papers/MODERNIZATION_ARCHITECTURE.md).
As-built record and verification evidence: [MODERNIZATION_CHANGE_DOC.md](../papers/MODERNIZATION_CHANGE_DOC.md).

## Global Test Invariants

Compact presentation is covered by `test_mcp_response_modes.py`,
`test_host_finalize.py` and `test_compact_host_workflow.py`: immutable mode/default
compatibility, preserved schemas/profiles/guards/warnings/source/paging, rich
keyed recovery, exact per-target lifecycle effects, artifact-name isolation,
SAVE uncertainty, evidence failures and bounded stdio failure cleanup. CI also
runs the existing five-file oracle with compact editing and trusted scalar
finalization. These checks do not invoke a model or establish host spill limits.

Structural batch coverage additionally lives in `test_observed_batch_core.py`,
`test_mcp_profiles.py`, `test_observed_batch.py`, `test_batch_stdio_profiles.py`,
`test_batch_migrations.py`, `test_batch_documented_examples.py` and
`test_structural_batch_oracle.py`. They cover 2/5/20/32 scopes, one discovery per
snapshot, selection limits/geometry/paging, scope-local sequential operations,
atomic rejection and rollback, concurrent writers, request recovery/conflicts,
corrupted replay authority, populated 0004/0005 preservation/refusal, enforced
7/5/6/22 catalogs, real response-loss recovery, Python/JSON/Markdown examples and
the frozen five-file full-byte/20-check oracle. [Capability evidence](../spec/STRUCTURAL_BATCH_EDITING.md#deterministic-capability-evidence).

- Postgres (`postgres:16.3-alpine`) is the required working substrate. SQLite must never be used to claim persistence, locking, migration, SAVE, or replay correctness.
- The deterministic core runtime is pure and language-neutral; it must never import DB/ORM drivers, call MCP tools, or execute transaction payloads.
- Atomicity is strictly per target: multi-edit transactions commit completely or leave target state untouched.
- All transaction attempts (accepted and rejected) are logged append-only with lineage (`parent_pdcp_log_id`) and idempotency (`client_request_id`).
- Manifest ledger entries are accepted-only and carry `origin` (`'typed'` or `'pdcp_manifest'`) and `derived_json` facts.
- Replay verifies history from initial snapshots independently of current materialized targets, dispatching explicitly on `(protocol_version, runtime_version)`.

---

Test counts are recorded with each exact executed revision in verification evidence; the matrix below describes coverage rather than a permanent total.

## 1. Pure Unit Test Matrix (`backend/tests/unit/`)

Run with: `pytest backend/tests/unit -q`

| Module | Requirements / Capabilities Tested |
| --- | --- |
| `test_canonicalization.py` | LF line-ending normalization; preservation of exact whitespace, tabs, and trailing newlines; no Unicode normalization. |
| `test_hashing.py` | Canonical SHA-256 computation over UTF-8 bytes. |
| `test_failures.py` | Enum definitions and frozen failure reason sets. |
| `test_matcher.py` | Exact matching; overlapping-match enumeration (`patchdiff-mvp-0.2.2`, advancing by 1 code point); legacy non-overlapping mode (`patchdiff-mvp-0.1.0`). |
| `test_parser.py` | Protocol header parsing; manifest line format; delimiter enforcement (`<<<<<<< MATCH`, `=======`, `>>>>>>> REPLACE`); delimiter collision rejection (`FailureReason.BLOCK_MALFORMED`). |
| `test_protocol_validator.py` | 7 required manifest fields (v0.2.3); risk value validation; structural purity (rejection of executable logic outside payloads). |
| `test_mcp_arguments_paging.py` | service context type/bounds, discovery/routing, filtered limit+1 continuation, defaults/caps, error shapes and invalid argument types. |
| `test_conflict_audit.py` | bounded submitted-key diagnostic, NULL persisted key versus response echo, submitted fingerprint policy. |
| `test_invalid_input_unicode.py` | all nested text/metadata fields, high/low surrogate and NUL, safe DB-bound diagnostics/read errors, valid-input hash identity and invalid-evidence domain separation. |
| `test_selector_profiles.py` | singleton/multiple/overlapping/absent selectors across typed, legacy and sequential buffers; historical profile compatibility. |
| `test_disambiguation.py` | Resolution via `occurrence_index`, `anchor_before`, `anchor_after`, and `region_hint`. |
| `test_applier.py` | Sequential in-memory simulation; immediate buffer replacement; deletion (`replace=""`); sequential match invalidation; calculation of runtime-derived `change_facts`. |
| `test_typed_transaction.py` | **C1, C4**: `patchdiff-tx/1` parsing; `build_record` and `canonical_record_json` determinism; default `change_id` generation; `validate_client_request_id` (ASCII printable, no whitespace, 1..128 chars); `TYPED_EDIT_JSON_SCHEMA` conformance; delimiter collision immunity; verdict equivalence with PDCP across test corpus. |
| `test_modernization_contracts.py` | **C2, C3, C6**: Stage-aware `validity_levels` (`ValidationStage`); explicit runtime profile dispatch (`SUPPORTED_RUNTIME_PROFILES`); `slice_content` (`next_start`); `occurrence_report` (`start_occurrence`, `max_results`, `next_occurrence_index`, `returned_count`); host-loop inspect/revise simulation without server regeneration prompts. |
| `test_stdio_adapter_subprocess.py` | **C1**: MCP `initialize` and `tools/list`; full `edits` item schema advertised in `patchdiff_submit_edits`; JSON-RPC `-32602` error response on non-object `params` of every JSON type; process survival. |
| `test_friction_followup.py` | FR-1..FR-20 pure behavior: `occurrence_index` basis-shift warnings and selector details, grapheme boundary cases, span context guards and 0.3.0/0.5.0 profile selection, line-ending facts and export mapping, the shared retryable set, span evidence, near-miss scope and pruned-versus-unpruned equivalence over buffers beyond 256 code points, exact abandoning and pigeonhole/Landau-Vishkin work bounds on 65,536-code-point repetitive buffers, consumed sequential matches, failure windows and context elision, no-op warnings, candidate cursors and replacement numbers, `line_starts`, UTF-8 serialization fallback, structured argument errors and parameter descriptions. |
| `test_migration_0003_offline.py` | **C5b**: SQL rendering of nullable `source_line_endings` without backfill; downgrade refusal precedes the column drop. |
| `test_migration_0002_offline.py` | **C5**: 0002 sits between 0001 and head `20261022_0003`; SQL rendering of `origin`, `derived_json`, `client_request_id`, `request_fingerprint`, and partial unique index; downgrade safety check rendering. |

---

## 2. Postgres Integration Test Matrix (`backend/tests/integration/`)

Run with: `$env:PATCHDIFF_DATABASE_URL="..."; pytest backend/tests/integration -q`

| Module | Requirements / Capabilities Tested |
| --- | --- |
| `test_conflict_audit_live.py` | distinct repeated conflict attempts; controlled real lock waits at READ COMMITTED; commit/rollback visibility; original full terminal recovery after later edits; actual stdio. |
| `test_invalid_input_unicode_live.py` | actual PostgreSQL persistence/recovery, old accepted/rejected fingerprint compatibility, outer commit/rollback and deprecated wrapper ownership, real stdio readable evidence. |
| `test_selector_profiles_live.py` | durable rejection without materialization, all supported historical selector profiles in typed/legacy mixed history, actual stdio rejection and replay. |
| `test_friction_followup_live.py` | FR-1..FR-20 against live PostgreSQL: persisted and recovered warnings (SQL NULL when there are none), 0.5.0 rows replaying beside 0.3.0 history, recorded line endings and every export format, persisted retryable/span evidence and failure windows, near misses beyond 256 code points, consumed-match evidence, context elision, current state on recovery, key-conflict fields, ledger/attempt joins after SAVE (including pdcp_content-free SQL cursor verification over large tx/3 records), content page budget, line continuation, invalid-argument codes, replacement numbers, preview near misses and SAVE version guards. |
| `test_friction_followup_stdio.py` | Real stdio subprocess: literal tool text inside pure-ASCII JSON-RPC lines (including U+2028/U+2029/U+0085), described schemas and new domains, CRLF upload and `original_eol` export, `line_starts`, span context rejection and 0.5.0 acceptance, warnings, preview near misses, structured unknown-argument errors, ledger joins, SAVE version guard and replay. |
| `test_migrations_reachable.py` | **C5, C5b**: Alembic config presence; schema verification for migrations `0001`, `0002` and `0003`; populated `0002 -> 0003 -> 0002 -> 0003` preservation; 0003 downgrade refusal with recorded line endings; live Postgres column nullability and partial unique index `uq_pdcp_logs_target_client_request_id` verification. |
| `test_typed_submit_flow.py` | **C1–C6**: Typed accept writes `append_only_pdcp_logs` (`protocol_version="patchdiff-tx/1"`) and `append_only_manifest_ledger` (`origin="typed"`, `derived_json`); format-specific diagnostics (no PDCP manifest leakage on typed rejections); stage-based validity across all 5 stages; safe UUID and parent-lineage error handling; `client_request_id` idempotency, lost-response outcome recovery, ABA sequence recovery, no-op edit recovery, and conflicting reuse rejection; mixed PDCP/typed replay; component-level `materialized_state_checks`; unknown profile rejection; read/search pagination. |
| `test_pdcp_submit_flow.py` | Legacy `.pdcp` submission; atomic rollback on applicability failure; optimistic concurrency guards (`expected_target_version`, `expected_current_hash`); row locking independence across targets. |
| `test_save.py` | `patchdiff_save` creates snapshots and cycle rotation without mutating target content; ledger reads filter to active cycle. |
| `test_mcp_history_paging_live.py` | actual PostgreSQL multi-page attempt/ledger traversal, filters/gaps, inserted newer rows, empty/not-found targets and real stdio history. |
| `test_replay.py` | Reconstructs state from initial upload snapshot + accepted logs; detects tampered logs and broken version chains. |
| `integration/test_replay_materialized_integrity_live.py` | healthy,CRLF,bareCR,Unicode,hash-only,version-only storage; exact four checks/aggregate; reconstruction success; no target/history mutation; caller rollback and fresh healthy observer. |
| `test_mcp_tool_contract.py` & `test_mcp_tools.py` | Tool wrappers route exclusively through services; tools do not mutate storage directly. |
| `test_mcp_e2e_flows.py` | End-to-end upload -> context -> submit -> get -> save -> replay -> export workflows. |
| `test_external_mcp_adapter.py` | External MCP stdio adapter JSON-RPC handling; tool discovery; argument routing. |
| `test_external_mcp_e2e.py` | In-process adapter flows AND **`test_real_stdio_subprocess_mcp_full_modernized_workflow`**: real child-process `python -m app.mcp.external_adapter` communicating over stdin/stdout backed by live Postgres executing the full 8-step product workflow (initialize, upload, read/search, ambiguous reject, disambiguated accept with lineage & idempotency, SAVE, replay, and export). |

---

## 3. Offline Payload & Verdict Accounting Matrix (`backend/tests/verification/offline_eval.py`)

Run with: `$env:PYTHONPATH="backend"; python backend/tests/verification/offline_eval.py`

The original comparison evaluates 5 scenarios across 3 proposal variants:
1. `pdcp`: PDCP v0.2.3 with 7 mandatory manifest fields per edit.
2. `typed_match`: typed `patchdiff-tx/1` with matched advisory prose (`intent` + per-edit `change_id`, `rationale`, `risk`).
3. `typed_min`: minimal typed `patchdiff-tx/1` (`intent` + `{match, replace}`).

Checks:
- Exact verdict and `after_hash` equivalence across representations through the shared applier (except where PDCP fails on delimiter lines).
- Persisted record UTF-8 byte accounting (`append_only_pdcp_logs.pdcp_content`).
- MCP tool request JSON wire byte accounting (`tools/call` arguments).
- Strict separation of serialization framing overhead from reduced-manifest prose savings.

Five additional guarded `patchdiff-tx/3` scenarios measure canonical record bytes and complete UTF-8 JSON-RPC request lines (fixed id=1 and one LF): whole-target rewrite, empty target, empty replacement, Unicode/quotes/CRLF and 2 KB rewrite. Accepted content/hash oracles use immutable 0.4.0; no cross-format replacement equivalence, live transport, persistence, timing or representative workload is measured. Only the named `payload has a delimiter line` scenario permits the legacy `block_malformed` versus typed acceptance exception.

## Guarded replacement and advisory tool coverage

Unit and live PostgreSQL/stdio coverage includes inclusive raw/result byte/code-point limits, invalid Unicode precedence, existing-key recovery before fresh admission, empty replacement, immutable profiles/replay, coherent LF line observations and continuation, pending local-state rejection, preview/submit parity and nonmutation of every managed table/caller transaction. Discovery executes every advertised example using returned IDs/guards/parents/cursors, including deduplication and complete history traversal. Preview evidence tests cover serialized per-field/whole-response budgets and complete identity retention or explicit omission.

## Schema and migration regression coverage

The submission schema domain tests validate actual tools/list schemas against live service results and durable audit rows, including null guards, whitespace prose, integer boundaries and newline-suffixed IDs/hashes. The migration tests independently create owned schemas for populated legacy preservation and typed-history downgrade refusal, including unchanged rows/revision and replay after refusal.
