# 3-Arm Native vs. Patch-DIFF + Waymark Structural Observation Retest Plan

> **Gate 2 Status:** **PREPARED ONLY — DO NOT EXECUTE YET.**
> Per project governance, the comparative subagent study described in this document must **not** be executed until the Patch-DIFF Waymark structural observation integration PR and these experimental controls are reviewed and approved.

---

## 1. Objective

Evaluate whether integrating pinned **`waymark-engine@4.1.0`** structural symbol discovery (`patchdiff_observe_scope`) with server-enforced scoped transaction admission (`patchdiff_submit_observed_operations` under `PATCHDIFF_STRICT_OBSERVATION_MODE=1`) resolves the structural discovery and repeated-substring disambiguation bottlenecks observed in prior Patch-DIFF benchmarks while preserving Patch-DIFF's transactional, concurrency, and replay guarantees.

---

## 2. Three Experimental Arms

| Arm | Name | Allowed Read / Discovery Tools | Allowed Write Tools | Server Configuration |
| --- | --- | --- | --- | --- |
| **Arm A** | **Native Editing Baseline** | Native file read / search tools (`read_file` / `Get-Content` / `grep`) | Native file edit tools (`edit_file` / `write_file`) | No Patch-DIFF server |
| **Arm B** | **Patch-DIFF (Unobserved / Text-Selector Mode)** | `patchdiff_read_target`, `patchdiff_read_lines`, `patchdiff_find_occurrences`, `patchdiff_get_target` | `patchdiff_submit_edits`, `patchdiff_submit_operations`, `patchdiff_submit_replacement`, `patchdiff_preview`, `patchdiff_save`, `patchdiff_export_target` | `PATCHDIFF_STRICT_OBSERVATION_MODE=0` |
| **Arm C** | **Patch-DIFF + Waymark Structural Observation (Strict Mode)** | `patchdiff_observe_scope` (`waymark-engine@4.1.0`), `patchdiff_read_target`, `patchdiff_read_lines`, `patchdiff_find_occurrences`, `patchdiff_get_target` | `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_export_target` (all unobserved write tools fail closed with `OBSERVATION_REQUIRED`) | `PATCHDIFF_STRICT_OBSERVATION_MODE=1` |

---

## 3. Benchmark Corpus & Task Oracle

### 3.1 Primary Hard-Suite Corpus (`Editing-Toolbench/10-26-26`)
- **45 structural edit targets** across **20 files** spanning:
  1. **Python modules**: module-level constants/assignments (`FRAME_SYNC_STREAM`, `VALID_SCOPES`), classes, functions, and methods with repeated body literals.
  2. **JSON configuration files**: large multi-tenant and policy arrays (`tenants[ten_006]`, `tenants[ten_013]`, `tenants[ten_018]`, nested escaped keys) where identical field/value pairs (`"tier": "standard"`, `"quota": 100`) repeat across dozens of sibling array objects.
  3. **Markdown operational runbooks**: ATX headings (`# ...`), GFM pipe-table rows (`row:CHK-14-C`), and fenced code blocks (`fence:L...`).
  4. **TypeScript / JavaScript modules**: exported functions, classes, and methods.

### 3.2 Transactional & Concurrency Stress Suite
- **S1 — Repeated-field JSON array update:** Update a single tenant (`tenants[ten_013]`) without mutating identical `"quota": 100` fields in `tenants[ten_006]` or `tenants[ten_018]`.
- **S2 — Concurrent two-worker race:** Two subagents observe the same target at `version = 0` and submit concurrent scoped edits; verify `SELECT ... FOR UPDATE` serializes admission so the second writer fails closed (`STALE_OBSERVATION_VERSION`) instead of silently overwriting the first writer's changes.
- **S3 — ABA & no-op version progression:** Verify stale observations are rejected after `A -> B -> A` content restoration and after no-op version increments.
- **S4 — Out-of-scope collateral write attempt:** Verify edits targeting lines or matches outside the observed symbol's `[scope_start, scope_end)` fail closed (`OPERATION_OUTSIDE_OBSERVED_SCOPE`) with zero target mutation.

---

## 4. Experimental Controls

1. **Model & Decoding Parity:** All three arms use the exact same subagent model (`Model="inherit"`), temperature, and system tool timeout settings.
2. **Isolated Workspaces:** Each arm runs in a clean, isolated copy of the initial benchmark corpus (`ws_arm_a_native`, `ws_arm_b_patchdiff_unobserved`, `ws_arm_c_patchdiff_waymark_strict`).
3. **Database Isolation (Arms B & C):** Each Patch-DIFF arm initializes fresh target rows in PostgreSQL at `version = 0`, exports final contents via `patchdiff_save(export_after_save=True)` using `format="original_eol"`, and runs `patchdiff_replay` on every target file before running the external file-level oracle.
4. **Strict Enforcement in Arm C:** Arm C runs the Patch-DIFF MCP server with `PATCHDIFF_STRICT_OBSERVATION_MODE=1`. Any attempt by the subagent to call `patchdiff_submit_edits`, `patchdiff_submit_operations`, `patchdiff_submit_replacement`, `patchdiff_submit_pdcp`, or `patchdiff_request_regeneration` is rejected by the server and recorded in `append_only_pdcp_logs` with `code="OBSERVATION_REQUIRED"`.

---

## 5. Pre-Registered Evaluation Metrics

1. **Workspace Verification Pass Rate:** `x / 20` files passing `run_all_benchmarks.py` verification checks.
2. **Edit Target Resolution Rate:** `x / 45` individual edit targets resolved and applied accurately.
3. **Collateral Damage Rate:** Number of files where bytes outside the intended symbol/object/row/fence scope were modified or corrupted.
4. **First-Submission Acceptance Rate & Retry Count:** Ratio of accepted transactions on the first submission attempt vs. rejected attempts logged in `append_only_pdcp_logs`.
5. **Replay & Audit Integrity (Arms B & C):**
   - `patchdiff_replay` pass rate (`status == "success"` and `materialized_state_matches is True` across all 20 targets).
   - `target_scope_observations.accepted_pdcp_log_id` 1-to-1 linkage completeness for every accepted transaction in Arm C.
6. **Efficiency Metrics:** Total MCP tool calls, total input/output characters transferred in tool payloads, and wall-clock time per task.

---

## 6. Execution Gate (Gate 2)

Do **not** launch subagents or execute Arms A, B, or C until:
1. The Patch-DIFF PR introducing `waymark-engine@4.1.0`, `patchdiff_observe_scope`, `patchdiff_submit_observed_operations`, and `PATCHDIFF_STRICT_OBSERVATION_MODE` is reviewed.
2. Reviewer sign-off is granted on the 3-arm experimental controls and metrics above.
