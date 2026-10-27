# Structural Batch Editing Remediation Report — PR #16

Date: 2026-10-27. Standard: PR Review Standard v1.1.0. Author: Codex implementation evidence and source self-inspection. **Independent category review and product acceptance remain pending. This report is not a merge recommendation. Gate 2 remains CLOSED.**

- Repository / PR: [https://github.com/paragon-ux/Patch-DIFF/pull/16](https://github.com/paragon-ux/Patch-DIFF/pull/16).
- PR base: `f5cc6742f94e080d2eda7486265e79eebf55c8ad`. Remediation baseline: `76415946fa7f24eff6026102f901f3217a435780`.
- Final implementation source head: [`ae3e2f36ab22204601422c5cc06221e482e4cecd`](https://github.com/paragon-ux/Patch-DIFF/commit/ae3e2f36ab22204601422c5cc06221e482e4cecd). Initial implementation: `6c2353baba6bd6a711fa384767c274adf8dd863e`; final delta reserves the batch runtime exclusively for its protocol.
- Scope: 61 changed source/test/config/contract files relative to the corrective-review baseline. The complete PR comparison contains 157 paths; the 96 earlier paths were not independently re-reviewed in this implementation task. Their earlier review/evidence records are preserved.
- Evidence added after the source head is documentation, deterministic run artifacts and attributes preserving every recorded artifact byte. Exact final evidence-head identity is supplied by the PR report comment; source execution identities below are pinned separately.

## Result and architecture trace

Multiple exact Waymark selections now produce one snapshot-bound bundle; groups execute through the existing deterministic applier on independent original slices; descending assembly feeds one existing locked commit. Acceptance writes one log, all observation links and ledger facts, and increments the target once. Any failed group commits one rejection and no target or accepted-ledger changes. The external adapter defaults to seven advertised and callable tools.

| Invariant / contract | Implementation | Evidence |
| --- | --- | --- |
| Exact structural authority, one discovery per snapshot | [backend/app/services/scope_observation_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/services/scope_observation_service.py) — `_issue_bundle / validate_bundle_for_locked_target` | 2/5/20/32 selections and instrumented discovery counts |
| Sequential local operations, deterministic all-or-nothing assembly | [backend/app/pdcp/observed_batch.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/pdcp/observed_batch.py) — `validate_batch_envelope / apply_observed_batch` | local spans, occurrences, guarded interior inserts, late-group rejection |
| One locked atomic commit and keyed recovery | [backend/app/services/pdcp_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/services/pdcp_service.py) — `_submit / _evaluate_locked_batch / _persist_acceptance` | one version/log, real response loss, concurrent writer, injected failure and caller rollback |
| Durable many-to-one scope linkage | [backend/app/migrations/versions/20261027_0005_observation_bundles.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/migrations/versions/20261027_0005_observation_bundles.py) — `upgrade / downgrade` | populated historical roundtrip; bundle/accepted-evidence downgrade refusal |
| Immutable replay without discovery | [backend/app/services/replay_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/services/replay_service.py) — `replay_target / _replay_observed_batch` | missing/extra/duplicate/reordered/forged authority and altered record failures |
| Immutable advertised and callable capability profiles | [backend/app/mcp/external_adapter.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/mcp/external_adapter.py) — `ExternalMCPAdapter` | 7/5/6/22 catalogs; forbidden-call checks in process and real stdio |

Durable identifiers: **`patchdiff-observed-batch/1` / `patchdiff-observed-batch-r1`**. Original tx/2 operations and their order are retained inside each group. Canonical server evidence records scope identity, bundle ordinal, original bounds/hash, symbol coordinates and engine version. Request fingerprints identify the original submitted body before server evidence is attached. Replay requires the exact protocol/runtime pair and exact authoritative links. Single-scope absolute coordinates and all historical transaction profiles remain available.

## Public tools and catalog measurements

Default `editor`: `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_edits`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay`. No tool was added or deleted; all 22 internal handlers remain.

| Startup profile | Tools | Actual tools/list JSON-RPC line bytes | Result JSON bytes |
| --- | ---: | ---: | ---: |
| `editor` | 7 | 21,313 | 21,277 |
| `unobserved` | 5 | 7,751 | 7,715 |
| `observed` | 6 | 16,953 | 16,917 |
| `full` | 22 | 47,999 | 47,963 |

Measured over actual stdio responses, request ID 2, compact ASCII JSON-RPC envelope including trailing LF. Result-column sizes omit the JSON-RPC envelope. [Complete actual catalogs](../../evaluation/structural_batch/20261027-final/tool_catalogs.json). `PATCHDIFF_MCP_PROFILE` is read once at startup; unknown values fail closed. Both list and dispatch use the frozen profile; per-request overrides fail. Older/trusted administrative integrations opt into `full`. Strict observation remains separately enforced by services.

## Exact observation and submission example

[Unabridged real requests and responses](../../evaluation/structural_batch/20261027-final/exact_example.json) contain a separately initialized three-function example, its accepted batch, SAVE/replay and export. These example calls are excluded from the five-file workflow counts. Complete argument objects are reproduced below; response projections retain their real values and are explicitly labeled.

`patchdiff_observe_scope` — exact arguments:

```json
{
  "target_file_id": "54167943-1e55-4daf-9da3-151561ed8752",
  "selections": [
    {
      "symbol_name": "api_quota",
      "kind": "function"
    },
    {
      "symbol_name": "etl_quota",
      "kind": "function"
    },
    {
      "symbol_name": "ui_quota",
      "kind": "function"
    }
  ]
}
```

Actual response projection (the linked artifact retains every field):

```json
{
  "status": "observed_batch",
  "observation_bundle_id": "17aeb956-2b85-4ad5-aadd-2ae16a0e42c6",
  "target_file_id": "54167943-1e55-4daf-9da3-151561ed8752",
  "target_version": 0,
  "target_current_hash": "0909c475b747121cf8b13ffb01d29fa49629ede6dcf156b56e2f53154de977a8",
  "waymark_engine_version": "4.1.0",
  "language": "python",
  "scopes": [
    {
      "observation_id": "c6540ed8-1e4d-4774-ba4b-93ce38a40b97",
      "ordinal": 0,
      "symbol": {
        "kind": "function",
        "name": "api_quota",
        "parent": null
      },
      "scope_start": 0,
      "scope_end": 31,
      "observed_scope_hash": "4f5e528294bbed485d837e9c1e2e23a2dfe228320cb325a2122ea611d461defe",
      "text": "def api_quota():\n    return 100",
      "truncated": false,
      "next_offset": null
    },
    {
      "observation_id": "6f3c8ffa-35f0-4c26-81e9-1ecef3bb038d",
      "ordinal": 1,
      "symbol": {
        "kind": "function",
        "name": "etl_quota",
        "parent": null
      },
      "scope_start": 33,
      "scope_end": 64,
      "observed_scope_hash": "93b9e536dc0521912f0618801525d5a500f29a5e208ef5203c67ac86cbd3d77c",
      "text": "def etl_quota():\n    return 100",
      "truncated": false,
      "next_offset": null
    },
    {
      "observation_id": "24f467bf-f2cf-4f1f-85ab-04cff5f85f9b",
      "ordinal": 2,
      "symbol": {
        "kind": "function",
        "name": "ui_quota",
        "parent": null
      },
      "scope_start": 66,
      "scope_end": 96,
      "observed_scope_hash": "e957876ffaa3d8d8e2d5aad34eaae167c21d86bd15c56aee91bbada691c6d5ec",
      "text": "def ui_quota():\n    return 100",
      "truncated": false,
      "next_offset": null
    }
  ]
}
```

`patchdiff_submit_observed_operations` — exact arguments:

```json
{
  "target_file_id": "54167943-1e55-4daf-9da3-151561ed8752",
  "observation_bundle_id": "17aeb956-2b85-4ad5-aadd-2ae16a0e42c6",
  "expected_target_version": 0,
  "expected_current_hash": "0909c475b747121cf8b13ffb01d29fa49629ede6dcf156b56e2f53154de977a8",
  "client_request_id": "exact-batch-example",
  "intent": "Raise selected quotas to 200",
  "groups": [
    {
      "observation_id": "c6540ed8-1e4d-4774-ba4b-93ce38a40b97",
      "operations": [
        {
          "op": "match",
          "match": "return 100",
          "replace": "return 200"
        }
      ]
    },
    {
      "observation_id": "6f3c8ffa-35f0-4c26-81e9-1ecef3bb038d",
      "operations": [
        {
          "op": "match",
          "match": "return 100",
          "replace": "return 200"
        }
      ]
    },
    {
      "observation_id": "24f467bf-f2cf-4f1f-85ab-04cff5f85f9b",
      "operations": [
        {
          "op": "match",
          "match": "return 100",
          "replace": "return 200"
        }
      ]
    }
  ]
}
```

Actual response projection (the linked artifact retains every field):

```json
{
  "status": "accepted",
  "pdcp_log_id": "0570cb45-21cd-420e-8cbe-17acbf32bb3c",
  "before_version": 0,
  "after_version": 1,
  "before_hash": "0909c475b747121cf8b13ffb01d29fa49629ede6dcf156b56e2f53154de977a8",
  "after_hash": "4f83a4917150e6f2ec161647d1a639da79fa0377785737030a7e3b4fe5283431",
  "observation_bundle_id": "17aeb956-2b85-4ad5-aadd-2ae16a0e42c6",
  "group_count": 3,
  "change_count": 3,
  "client_request_id": "exact-batch-example",
  "groups": [
    {
      "change_count": 1,
      "group_index": 0,
      "observation_id": "c6540ed8-1e4d-4774-ba4b-93ce38a40b97"
    },
    {
      "change_count": 1,
      "group_index": 1,
      "observation_id": "6f3c8ffa-35f0-4c26-81e9-1ecef3bb038d"
    },
    {
      "change_count": 1,
      "group_index": 2,
      "observation_id": "24f467bf-f2cf-4f1f-85ab-04cff5f85f9b"
    }
  ]
}
```

## Verification record

Source inspection, local execution and CI are separate evidence classes. Local environment: Windows, Python 3.11.9, pytest 8.4.2, Node 22.19.0, Waymark 4.1.0, live PostgreSQL 16.3. CI installs the repository-pinned dependency lock on Linux, including its pinned pytest version.

The staged whitespace/conflict-marker check excludes only the five exact gold exports: the original task deliberately contains literal conflict markers and trailing empty lines. Their complete bytes are verified against the frozen oracle and are never reformatted to satisfy a source-code whitespace check. All source, contract and receipt paths pass the check.

| Execution | Result | Evidence / exact tree |
| --- | --- | --- |
| Local complete unit suite | 936 passed | [unit.txt](../../evaluation/structural_batch/20261027-final/unit.txt) |
| Local final focused live PostgreSQL / real stdio suite | 85 passed | [focused_integration.txt](../../evaluation/structural_batch/20261027-final/focused_integration.txt); includes the final batch behavior and documented examples |
| Local offline evaluator | Verdict equivalence and replacement content/hash oracles OK | [offline_eval.txt](../../evaluation/structural_batch/20261027-final/offline_eval.txt) |
| CI `push` | **936 unit + 540 integration passed**; migrations and offline evaluator passed | [run 40502991197](https://github.com/paragon-ux/Patch-DIFF/actions/runs/40502991197); executed `ae3e2f36ab22204601422c5cc06221e482e4cecd` |
| CI `pull_request` | **936 unit + 540 integration passed**; migrations and offline evaluator passed | [run 40502998837](https://github.com/paragon-ux/Patch-DIFF/actions/runs/40502998837); executed `e0e59136110894093159c4fd37095163ecbeb1b7` |

[CI excerpts](../../evaluation/structural_batch/20261027-final/ci-evidence.json) preserve actual checkout SHAs, migration steps and test totals. The PR job executes GitHub merge tree `e0e59136110894093159c4fd37095163ecbeb1b7`, merging source head `ae3e2f36ab22204601422c5cc06221e482e4cecd` into base `f5cc6742f94e080d2eda7486265e79eebf55c8ad`; the push job executes the source head directly. Passing CI is execution evidence, not independent product approval.

Migration evidence includes populated historical observation `0004 -> 0005 -> 0004 -> 0005` preservation and replay, empty live CI up/down/up, refusal for unconsumed bundles, accepted batches and accepted batch logs even after test-only authority deletion. Old single-observation uniqueness and all existing historical/unobserved replay tests pass. All-scope replay tamper cases include missing, duplicated, additional, reordered, cross-target, cross-cycle and altered scope/hash evidence, changed operations/record hashes, and incompatible runtime pairs.

Atomicity evidence checks target text/version, log/ledger counts and every observation link; rejected last groups, caller rollback and exceptions after acceptance persistence leave no partial acceptance. The response-loss test sends a real MCP request, deliberately does not receive its reply, observes its committed PostgreSQL log, closes that process, then recovers through a fresh stdio process with exactly one accepted log/version. A controlled two-session race observes actual PostgreSQL lock blocking before checking stale rejection.

## Five-file deterministic oracle and call accounting

[Results](../../evaluation/structural_batch/20261027-final/results.json) and [all real stdio request/response receipts](../../evaluation/structural_batch/20261027-final/requests_responses.json) retain the fresh target/log IDs. Every exported file matches its complete frozen gold bytes; the original behavioral verifier passes **20/20** after exact-byte equality. Zero out-of-scope output differences were found.

| File | Bundle scopes | Operations | Final target version | SAVE / replay |
| --- | ---: | ---: | ---: | --- |
| `matrix_kernel.py` | 5 | 9 | 1 | passed |
| `schema_defs.py` | 2 | 4 | 1 | passed |
| `validator_engine.py` | 5 | 21 | 1 | passed |
| `routing_manifest.json` | 4 | 16 | 1 | passed |
| `MIGRATION_RUNBOOK.md` | 4 | 4 | 1 | passed |

| Actual editing MCP tool calls | Original exploratory C | Deterministic batch capability path |
| --- | ---: | ---: |
| Candidate discovery | 5 | 0 |
| Selected / bundled observation | 20 | 5 |
| Editing submission | 20 | 5 |
| Search | 1 | 0 |
| SAVE | 5 | 5 |
| Replay | 5 | 5 |
| Total | 56 | 20 |

The new runner counts actual `tools/call` lines in its observed-profile session. Trusted lifecycle work adds 5 initialize, 5 export, 5 log and 5 ledger calls, reported separately; MCP initialize/tools-list handshakes and catalog/example captures are not editing calls. Known exact selectors and declarative operation payloads are extracted from the preserved exploratory C transcript, not generated by a new model. All 20 scopes / 54 operations are preserved. This demonstrates API capability, not elapsed-time, token, context, cost or model-success improvement. An agent may still choose additional discovery/reads.

Frozen primary prompts/fixtures/oracle, exploratory transcripts/outputs, controller source/manifest and existing Gate 2 approval state are unchanged. `prepare.validate_inputs(...)` returned an empty error list. The frozen controller is neither re-pinned nor weakened; compatibility tests set trusted `full` in their test environment. **No measured Gemini subagents executed, no comparative model run occurred, no new external bridge/framework was added, nothing was merged, and Gate 2 is not approved.**

## Changed-file inventory and coverage

[Machine-readable inventories](../../evaluation/structural_batch/20261027-final/changed_files.json) map every remediation path and every full-PR path to a primary category. The table below covers the 61-path remediation delta; the full-PR inventory additionally marks scope through its separate base comparison. Generated evidence paths are SCRIPT artifacts, and this implementation report is DOC. They do not change runtime behavior.

| Primary category | Changed path (source head pinned) |
| --- | --- |
| SKILL | [.agents/skills/patchdiff-core-runtime/SKILL.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/.agents/skills/patchdiff-core-runtime/SKILL.md) |
| SKILL | [.agents/skills/patchdiff-mcp-orchestration/SKILL.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/.agents/skills/patchdiff-mcp-orchestration/SKILL.md) |
| SKILL | [.agents/skills/patchdiff-persistence-replay-save/SKILL.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/.agents/skills/patchdiff-persistence-replay-save/SKILL.md) |
| SKILL | [.agents/skills/patchdiff-testing-review/SKILL.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/.agents/skills/patchdiff-testing-review/SKILL.md) |
| DEP | [.env.example](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/.env.example) |
| DEP | [.gitattributes](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/.gitattributes) |
| SKILL | [AGENTS.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/AGENTS.md) |
| DOC | [README.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/README.md) |
| DOC | [README_INTERNAL_MCP.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/README_INTERNAL_MCP.md) |
| RUN | [backend/app/core/versions.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/core/versions.py) |
| MCP | [backend/app/mcp/external_adapter.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/mcp/external_adapter.py) |
| MCP | [backend/app/mcp/tools.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/mcp/tools.py) |
| DB | [backend/app/migrations/versions/20261027_0005_observation_bundles.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/migrations/versions/20261027_0005_observation_bundles.py) |
| RUN | [backend/app/pdcp/observed_batch.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/pdcp/observed_batch.py) |
| SVC | [backend/app/services/pdcp_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/services/pdcp_service.py) |
| SVC | [backend/app/services/rejection_context.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/services/rejection_context.py) |
| DB | [backend/app/services/replay_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/services/replay_service.py) |
| SVC | [backend/app/services/scope_observation_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/services/scope_observation_service.py) |
| DB | [backend/app/storage/models.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/app/storage/models.py) |
| TEST | [backend/tests/conftest.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/conftest.py) |
| TEST | [backend/tests/integration/test_batch_documented_examples.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_batch_documented_examples.py) |
| TEST | [backend/tests/integration/test_batch_migrations.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_batch_migrations.py) |
| TEST | [backend/tests/integration/test_batch_stdio_profiles.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_batch_stdio_profiles.py) |
| TEST | [backend/tests/integration/test_conflict_audit_live.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_conflict_audit_live.py) |
| TEST | [backend/tests/integration/test_external_mcp_adapter.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_external_mcp_adapter.py) |
| TEST | [backend/tests/integration/test_external_mcp_e2e.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_external_mcp_e2e.py) |
| TEST | [backend/tests/integration/test_external_mcp_utf8.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_external_mcp_utf8.py) |
| TEST | [backend/tests/integration/test_friction_followup_stdio.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_friction_followup_stdio.py) |
| TEST | [backend/tests/integration/test_invalid_input_unicode_live.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_invalid_input_unicode_live.py) |
| TEST | [backend/tests/integration/test_mcp_history_paging_live.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_mcp_history_paging_live.py) |
| TEST | [backend/tests/integration/test_migrations_reachable.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_migrations_reachable.py) |
| TEST | [backend/tests/integration/test_observed_batch.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_observed_batch.py) |
| TEST | [backend/tests/integration/test_observed_submission.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_observed_submission.py) |
| TEST | [backend/tests/integration/test_pass_a_flow.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_pass_a_flow.py) |
| TEST | [backend/tests/integration/test_pass_b_discovery.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_pass_b_discovery.py) |
| TEST | [backend/tests/integration/test_rejection_context_flow.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_rejection_context_flow.py) |
| TEST | [backend/tests/integration/test_selector_profiles_live.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_selector_profiles_live.py) |
| TEST | [backend/tests/integration/test_structural_batch_oracle.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_structural_batch_oracle.py) |
| TEST | [backend/tests/integration/test_submission_schema_domains.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/integration/test_submission_schema_domains.py) |
| TEST | [backend/tests/unit/test_friction_followup.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/unit/test_friction_followup.py) |
| TEST | [backend/tests/unit/test_mcp_arguments_paging.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/unit/test_mcp_arguments_paging.py) |
| TEST | [backend/tests/unit/test_mcp_profiles.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/unit/test_mcp_profiles.py) |
| TEST | [backend/tests/unit/test_migration_0002_offline.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/unit/test_migration_0002_offline.py) |
| TEST | [backend/tests/unit/test_observed_batch_core.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/unit/test_observed_batch_core.py) |
| TEST | [backend/tests/unit/test_pass_b_reads_discovery.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/unit/test_pass_b_reads_discovery.py) |
| TEST | [backend/tests/unit/test_stdio_adapter_subprocess.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/backend/tests/unit/test_stdio_adapter_subprocess.py) |
| DOC | [docs/CLAUDE_DESKTOP_SETUP.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/CLAUDE_DESKTOP_SETUP.md) |
| DOC | [docs/CODEX_BUILD_PLAN.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/CODEX_BUILD_PLAN.md) |
| DB | [docs/DATA_MODEL.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/DATA_MODEL.md) |
| DOC | [docs/HOST_INTEGRATION_GUIDE.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/HOST_INTEGRATION_GUIDE.md) |
| DOC | [docs/MCP_FIRST_MVP.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/MCP_FIRST_MVP.md) |
| MCP | [docs/MCP_TOOLS.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/MCP_TOOLS.md) |
| ARCH | [docs/MODERNIZATION_ARCHITECTURE.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/MODERNIZATION_ARCHITECTURE.md) |
| DOC | [docs/MODERNIZATION_CHANGE_DOC.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/MODERNIZATION_CHANGE_DOC.md) |
| DOC | [docs/PATCHDIFF_CORE_SPEC.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/PATCHDIFF_CORE_SPEC.md) |
| DOC | [docs/PDCP_FORMAT.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/PDCP_FORMAT.md) |
| ARCH | [docs/STRUCTURAL_BATCH_EDITING.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/STRUCTURAL_BATCH_EDITING.md) |
| DOC | [docs/TEST_MATRIX.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/TEST_MATRIX.md) |
| DOC | [docs/WAYMARK_STRUCTURAL_OBSERVATION_RETEST_PLAN.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/docs/WAYMARK_STRUCTURAL_OBSERVATION_RETEST_PLAN.md) |
| DOC | [evaluation/README.md](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/evaluation/README.md) |
| SCRIPT | [evaluation/structural_batch/verify.py](https://github.com/paragon-ux/Patch-DIFF/blob/ae3e2f36ab22204601422c5cc06221e482e4cecd/evaluation/structural_batch/verify.py) |

## Category-separated implementation self-inspection

Coverage statements below concern the remediation delta and its relevant existing dependencies. They record implementation inspection and executed checks; they are not an independent review of the full PR. A prior approval or green CI does not close the two corrective findings. Independent reviewer recheck remains required.

### ARCH — Architecture and contracts

**Scope / coverage:** New batch contract, architecture decisions and invariants traced through scoped evaluation, one commit and exact replay. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- PR16-P1: batch capability regression implemented in the source head; five-file capability and atomicity evidence pass. **Independent closure pending.**

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** No new direct model comparison or product performance acceptance; owner authorization is still required.

**Verdict:** Implementation acceptance criteria evidenced; independent product review pending.

### DOC — Documentation and change records

**Scope / coverage:** MCP/host/core/data/format/setup/retest contracts reconciled; complete Python/JSON/Markdown recipes executed. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** Historical recorded reports are preserved, not rewritten as current evidence.

**Verdict:** No documentation mismatch identified in the changed contract scope.

### SKILL — Skills and agent instructions

**Scope / coverage:** AGENTS addition preserves locked invariants; four local skill notes describe current profiles, batch lifecycle and migration. All four quick validators pass. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** No independent skill behavior evaluation; edits are narrow contract reconciliation.

**Verdict:** No instruction defect identified in the changed scope.

### MCP — MCP schemas and public API

**Scope / coverage:** Generated selections/groups schemas, mutual exclusion, bounded operations and exact profile lists/call enforcement inspected in process and real stdio. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- PR16-P2: oversized default catalog implemented as enforced 7/5/6/22 profiles; exact catalogs and forbidden-call tests pass. **Independent closure pending.**

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** No third-party host selection/cost claim; existing hosts must opt into full for lifecycle tools.

**Verdict:** API and profile implementation evidenced; independent contract recheck pending.

### RUN — Core runtime, parsing and validation

**Scope / coverage:** Pure envelope/group parser and shared-applier assembly inspected; historical applier implementation unchanged. Local spans, occurrences, Unicode, strict insertions, stages and no-op warnings tested. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** Semantic/task correctness remains not_evaluated in service validity, as required.

**Verdict:** No deterministic-runtime defect identified within inspected scope.

### SVC — Services, orchestration and audit semantics

**Scope / coverage:** Bundle issuance, locked admission, idempotent raw-body identity, canonical durable UUIDs, lineage, one acceptance and scoped rejection context inspected. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** Caller-owned acceptance remains provisional until caller commit, preserving existing ownership.

**Verdict:** Atomicity/recovery/authority checks pass; external recheck pending.

### DB — Database, migrations, replay and concurrency

**Scope / coverage:** Additive 0005, historical partial uniqueness, many-to-one linkage, downgrade refusal and exact replay pair/evidence checked with populated schemas and adversarial rows. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** Direct privileged SQL can corrupt evidence; replay detects inconsistent history and never repairs it.

**Verdict:** Persistence/replay acceptance evidence passes; independent integrity review pending.

### SCRIPT — Scripts, evaluation and developer tooling

**Scope / coverage:** Deterministic real-stdio runner authenticates frozen sources and archived payloads, counts editing/lifecycle calls separately and gates behavioral imports on byte equality. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** No measured Gemini agents, timing/cost study or Gate 2 execution; these remain unauthorized.

**Verdict:** Capability and experiment-integrity evidence passes; no performance verdict.

### TEST — Tests and CI

**Scope / coverage:** Focused negative cases inspected; 936 local units, 85 final focused live tests and both 936/540 CI suites pass, including real subprocess/response loss and populated migrations. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** Local pytest differs from the lock; CI verifies pinned dependencies. Existing Alembic path-separator warnings remain non-failing.

**Verdict:** Required execution evidence passes at the pinned source/merge trees.

### DEP — Dependencies, packaging and configuration

**Scope / coverage:** Waymark remains pinned at 4.1.0; startup profile config and exact-byte export attributes added; no dependency/framework or external model bridge added. Coverage complete for the inspected delta; prior unchanged PR material is outside this self-inspection.

**P1 — high priority**

- None identified within inspected remediation scope.

**P2 — medium priority**

- None identified within inspected remediation scope.

**P3 — low priority**

- None identified within inspected remediation scope.

**Verification gaps:** Other host implementations are not certified by these stdio tests.

**Verdict:** Configuration/dependency constraints preserved in changed scope.

## Product-review category triage

These additional categories preserve the corrective request's separate questions. They map into the standard sections above; unresolved verification is recorded as a gap, not invented as a defect.

| Category | Coverage / evidence | P1 | P2 | P3 | Verdict / gap |
| --- | --- | --- | --- | --- | --- |
| MCP contracts | Generated schemas and actual dispatch | None identified | None identified | None identified | Independent contract recheck pending |
| Structural observation | Snapshot authority, unique exact selection, one discovery, size/geometry negatives | None identified | None identified | None identified | Independent authority recheck pending |
| Deterministic runtime | Scope-local sequential applier and descending assembly | None identified | None identified | None identified | Pure/runtime tests pass |
| Atomic transactions | Failed last group, caller rollback, post-persist exception, blocked writer | None identified | None identified | None identified | No partial acceptance observed |
| Database/migrations | Populated preservation/refusal and partial uniqueness | None identified | None identified | None identified | Independent migration review pending |
| Replay | Every scope link and canonical record checked, no Waymark | None identified | None identified | None identified | Fail-closed negatives and historical compatibility pass |
| Idempotency | Actual committed response loss through new MCP process, changed-body conflicts and lineage | None identified | None identified | None identified | One accepted outcome/version recovered |
| Tool profiles | Exact 7/5/6/22 lists and forbidden calls | None identified | PR16-P2 implementation delivered; independent closure pending | None identified | Host cost/selection benefit unmeasured |
| Testing | Local final checks and both exact-tree CI runs | None identified | None identified | None identified | No missing required deterministic case identified |
| Experiment integrity | Frozen input validator, unchanged historical paths and byte-gated oracle | None identified | None identified | None identified | No comparative agents or Gate 2 execution |
| Performance/ergonomics | Five bundled observations and five writes; exact call counts and schema bytes | PR16-P1 implementation delivered; independent closure pending | None identified | None identified | No causal timing/token/cost conclusion |

## Disposition and finding closure

| Finding | Implementation evidence | Status | Independent closure evidence |
| --- | --- | --- | --- |
| PR16-P1 — lost structural batching capability | `ae3e2f36ab22204601422c5cc06221e482e4cecd`, one log/version and 5 bundled observations / 5 submissions for all original files | Implemented and deterministically verified | Pending independent reviewer recheck and later owner-authorized direct functionality test |
| PR16-P2 — 22-tool default overhead | `ae3e2f36ab22204601422c5cc06221e482e4cecd`, enforced profiles and archived byte counts | Implemented and deterministically verified | Pending independent reviewer recheck |

No additional unresolved P1/P2/P3 defect was identified within the inspected implementation delta. The material remaining work is independent category review/product acceptance, not another unauthorized model run. The full PR is **not independently approved** by this implementation report. No merge or Gate 2 approval is requested or performed.
