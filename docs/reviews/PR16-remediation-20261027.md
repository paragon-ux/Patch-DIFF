# PR #16 remediation implementation record - 2026-10-27

Implementation handoff for independent re-review. This report grants no merge or Gate 2 approval. Findings are implementation-complete only where stated; independent closure remains with the reviewer.

- Repository: `paragon-ux/Patch-DIFF`; PR: https://github.com/paragon-ux/Patch-DIFF/pull/16.
- Base: `f5cc6742f94e080d2eda7486265e79eebf55c8ad`; reviewed/remediation baseline: `581ee35476171f27a714ed890606b2b525dd13f3`.
- Branch: `feat/waymark-structural-observation`. GitHub and local baseline heads were compared before edits and reconfirmed during work.
- Original review: https://github.com/paragon-ux/Patch-DIFF/pull/16#pullrequestreview-5662171047.
- Evidence: repository instructions and four local skills, original PR diff/affected callers, independent review, supplied continuity handoff, live PostgreSQL regressions, real Node children and real stdio. The separately referenced preceding prompt was not recovered: the supplied file repeats the handoff, and the connected discussion returns a content-reference marker for the earlier response.
- Existing Desktop checkout and its untracked review directories were preserved. Work occurred in an isolated clone of the exact PR branch with the same origin remote. No Waymark release/package changes, schema redesign, model calls, comparative runs or merge occurred.

## Finding ledger and independent implementation triage

| Finding | Priority | Changed surfaces | Acceptance evidence | Implementation status |
| --- | --- | --- | --- | --- |
| A-1 | P2 | Waymark adapter and output-limit tests | Real stdout/stderr floods, inclusive caps, simultaneous pipes, timeout/reaping, pipe and parent-owned temporary-tree cleanup | Fixed; independent recheck pending |
| B-1 | P2 | Observation paging and live regressions | SAVE then page rejects closed cycle despite unchanged version/hash | Fixed; independent recheck pending |
| B-2 | P2 | Exact-selection candidates and live regressions | 205 ambiguous methods return 200 plus exact total/truncation, no observation | Fixed; independent recheck pending |
| C-1 | P1 | Shared scoped applier and unit/live/stdio regressions | Both boundaries, JSON/Python neighbors, missing guards, nonadjacent guards, guard extent, sequential scope growth/shrink, positive insertion, whole-scope replacement, unobserved compatibility | Fixed; independent recheck pending |
| D-1 | P1 | Replay and live integrity regressions | Pristine replay after SAVE; deleted/unlinked/wrong-ID/target/cycle/version/preimage/bounds/hash evidence rejects; database unique linkage enforced | Fixed; independent recheck pending |
| E-2 | P2 | MCP schema, core/tool/data/host contracts, stdio | Observed-only insertion conditional schema; real negative and positive stdio calls; unobserved schema/profile unchanged | Fixed; independent recheck pending |
| F-1 | P2 | Dedicated unit, PostgreSQL and real subprocess tests | Focused negative cases plus full suites and migration/stdin-stdout checks; final counts in verification record below | Added; independent recheck pending |
| G-1 | P1 | Study plan and manifest | Original primary replication reinstated; supplemental explicitly 45 targets / 20 scopes / five files; three studies separate | Original primary task restored and authenticated; execution remains gated |
| G-2 | P2 | Separate hash-pinned primary/supplemental fixtures, exact prompts, original oracles, staging and evaluation CLI | Original scratch hashes verified; identical common task across arms; hash/path tamper tests; fresh staging without evaluator; original external checks reject unedited fixtures | Original artifacts recovered and prepared; host/telemetry/full-byte oracle still require review |
| G-3 | P2 | Preregistration and manifest | Same frozen Gemini 3.8 Flash High and paired conditions/budgets, actual tokens/tool bytes/time, isolation and reporting rules | Preregistered; provider/host/model configuration unverified |

No listed finding was dismissed, merged as a duplicate or silently deferred by priority. Original task/fixture/oracle recovery is complete; host execution and full-byte collateral verification remain Gate 2 blockers.

## Architecture and compatibility trace

AGENTS.md purity/authority/atomicity invariants -> current architecture A4/A6/A8 and core/tool/data contracts -> shared scoped applier, observation service, replay and MCP discovery -> dedicated negative regressions. Additional admission is selected only by authoritative scope bounds; unobserved historical profiles/versions/record grammar are unchanged. Replay never rediscovers through Waymark and never substitutes diagnostic offsets for missing observation authority. Node output is bounded while running, with both pipes drained concurrently.

## Complete PR changed-file inventory

| File | Primary review category |
| --- | --- |
| `.gitattributes` | DEP |
| `.github/workflows/ci.yml` | DEP |
| `.gitignore` | DEP |
| `README_DEV.md` | DOC |
| `backend/app/core/config.py` | DEP |
| `backend/app/mcp/external_adapter.py` | MCP |
| `backend/app/mcp/tools.py` | MCP |
| `backend/app/migrations/versions/20261026_0004_target_scope_observations.py` | DB |
| `backend/app/pdcp/applier.py` | RUN |
| `backend/app/services/pdcp_service.py` | SVC |
| `backend/app/services/replay_service.py` | DB |
| `backend/app/services/scope_observation_service.py` | SVC |
| `backend/app/services/waymark_adapter.py` | SVC |
| `backend/app/storage/models.py` | DB |
| `backend/tests/integration/test_mcp_tools.py` | TEST |
| `backend/tests/integration/test_migrations_reachable.py` | TEST |
| `backend/tests/integration/test_observation_remediation.py` | TEST |
| `backend/tests/integration/test_observed_submission.py` | TEST |
| `backend/tests/integration/test_scope_observation.py` | TEST |
| `backend/tests/unit/test_migration_0002_offline.py` | TEST |
| `backend/tests/unit/test_migration_0004_offline.py` | TEST |
| `backend/tests/unit/test_observed_insertions.py` | TEST |
| `backend/tests/unit/test_retest_preparation.py` | TEST |
| `backend/tests/unit/test_waymark_adapter.py` | TEST |
| `backend/tests/unit/test_waymark_output_limits.py` | TEST |
| `docs/DATA_MODEL.md` | DOC |
| `docs/HOST_INTEGRATION_GUIDE.md` | DOC |
| `docs/MCP_TOOLS.md` | DOC |
| `docs/PATCHDIFF_CORE_SPEC.md` | ARCH |
| `docs/WAYMARK_STRUCTURAL_OBSERVATION_RETEST_PLAN.md` | DOC |
| `docs/reviews/PR16-remediation-20261027.md` | DOC |
| `evaluation/structural_retest/evaluate.py` | SCRIPT |
| `evaluation/structural_retest/manifest.json` | SCRIPT |
| `evaluation/structural_retest/prepare.py` | SCRIPT |
| `evaluation/structural_retest/primary/evaluator/original_A_prompt.md` | SCRIPT |
| `evaluation/structural_retest/primary/evaluator/original_B_prompt.md` | SCRIPT |
| `evaluation/structural_retest/primary/evaluator/prompt_provenance.json` | SCRIPT |
| `evaluation/structural_retest/primary/evaluator/setup_hard_suite.py` | SCRIPT |
| `evaluation/structural_retest/primary/evaluator/targets_manifest.json` | SCRIPT |
| `evaluation/structural_retest/primary/evaluator/verify_hard_suite.py` | SCRIPT |
| `evaluation/structural_retest/primary/fixtures/MIGRATION_RUNBOOK.md` | SCRIPT |
| `evaluation/structural_retest/primary/fixtures/matrix_kernel.py` | SCRIPT |
| `evaluation/structural_retest/primary/fixtures/routing_manifest.json` | SCRIPT |
| `evaluation/structural_retest/primary/fixtures/schema_defs.py` | SCRIPT |
| `evaluation/structural_retest/primary/fixtures/validator_engine.py` | SCRIPT |
| `evaluation/structural_retest/primary/prompts/TASK.md` | SCRIPT |
| `evaluation/structural_retest/primary/prompts/tools_A.md` | SCRIPT |
| `evaluation/structural_retest/primary/prompts/tools_B.md` | SCRIPT |
| `evaluation/structural_retest/primary/prompts/tools_C.md` | SCRIPT |
| `evaluation/structural_retest/supplemental/edit_specs.json` | SCRIPT |
| `evaluation/structural_retest/supplemental/evaluator/REPORT.md` | SCRIPT |
| `evaluation/structural_retest/supplemental/evaluator/benchmark_results.json` | SCRIPT |
| `evaluation/structural_retest/supplemental/evaluator/original_harness.py` | SCRIPT |
| `evaluation/structural_retest/supplemental/evaluator/verify_hard_suite.py` | SCRIPT |
| `evaluation/structural_retest/supplemental/fixtures/MIGRATION_RUNBOOK.md` | SCRIPT |
| `evaluation/structural_retest/supplemental/fixtures/matrix_kernel.py` | SCRIPT |
| `evaluation/structural_retest/supplemental/fixtures/routing_manifest.json` | SCRIPT |
| `evaluation/structural_retest/supplemental/fixtures/schema_defs.py` | SCRIPT |
| `evaluation/structural_retest/supplemental/fixtures/validator_engine.py` | SCRIPT |
| `integrations/waymark/discover.mjs` | DEP |
| `integrations/waymark/package-lock.json` | DEP |
| `integrations/waymark/package.json` | DEP |

Complete base-to-current PR inventory. This implementation self-review is not independent approval.

## ARCH

Coverage: affected remediation surfaces inspected: Observed admission vs immutable historical profiles and PostgreSQL authority. This is implementation self-review, not independent approval.

- P1: C-1: prescribed policy implemented; reviewer recheck pending.
- P2: None identified within remediation scope.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## DOC

Coverage: affected remediation surfaces inspected: Core/tool/host/data contracts and separate-study plan. This is implementation self-review, not independent approval.

- P1: G-1: corrected primary/supplemental distinction; original primary artifacts are recovered; future host configuration remains an execution blocker.
- P2: E-2 and G-2/G-3 contracts prepared; unresolved artifacts/settings are explicit.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## SKILL

Coverage: affected remediation surfaces inspected: AGENTS.md and four repository skills; no skill changes. This is implementation self-review, not independent approval.

- P1: None identified within remediation scope.
- P2: None identified within remediation scope.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## MCP

Coverage: affected remediation surfaces inspected: Observed schema copy, capabilities and real stdio negative/positive requests. This is implementation self-review, not independent approval.

- P1: None identified within remediation scope.
- P2: E-2 implemented; cross-field offsets/adjacency remain service checks.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## RUN

Coverage: affected remediation surfaces inspected: Shared scoped span admission and unobserved historical behavior. This is implementation self-review, not independent approval.

- P1: C-1 implemented; no runtime identifiers repurposed.
- P2: None identified within remediation scope.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## SVC

Coverage: affected remediation surfaces inspected: Bounded Node subprocess and observation lifecycle/candidate response. This is implementation self-review, not independent approval.

- P1: None identified within remediation scope.
- P2: A-1/B-1/B-2 implemented with direct regressions.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## DB

Coverage: affected remediation surfaces inspected: Authoritative replay linkage, row locks, unique constraint, SAVE and migration behavior. This is implementation self-review, not independent approval.

- P1: D-1 implemented; corrupted history fails closed.
- P2: No new migration needed for remediation.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## SCRIPT

Coverage: affected remediation surfaces inspected: Non-model manifest/hash/staging CLI; unchanged original supplemental source bytes. This is implementation self-review, not independent approval.

- P1: G-1 original primary task restored from authenticated scratch artifacts; execution remains gated.
- P2: G-2/G-3 original inputs and pure oracle preparation complete; provider identity, measured-run host/controller, telemetry and full-byte collateral oracle remain unverified.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## TEST

Coverage: affected remediation surfaces inspected: Focused and broad unit/live PostgreSQL/stdio/migration/offline verification. This is implementation self-review, not independent approval.

- P1: None identified within remediation scope.
- P2: F-1 negative regressions added; green aggregate totals alone are not used as proof.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## DEP

Coverage: affected remediation surfaces inspected: Existing exact npm pin/lock and Python lock; portable fixture byte preservation. This is implementation self-review, not independent approval.

- P1: None identified within remediation scope.
- P2: No dependency changes; gitattributes prevents hash drift across platforms.
- P3: None identified within remediation scope.
- Verification/gaps: see the finding ledger and verification record; independent reviewer recheck remains outstanding.
- Verdict: submit for independent re-review; Gate 2 remains closed.

## Verification record

- Windows, Python 3.11.9, Node 22.19.0, live PostgreSQL 16.3 in isolated `patchdiff_pr16_remediation` and final acceptance database `patchdiff_pr16_final`; pinned requirements installed in the isolated checkout.
- `python -m pytest backend/tests/unit -q`: 853 passed in the final artifact-complete run; earlier runtime runs passed 852 before the original-oracle negative test was added.
- `python -m pytest backend/tests/integration -q`: 452 passed on the final code in fresh isolated patchdiff_pr16_final, with no competing test writer; a separate final 36-test authority/scoped suite passed. The earlier 450-test run also passed. A shared-database concurrent attempt had 12 global snapshot assertion failures and is excluded from acceptance evidence; its details are retained below.
- Explicit Alembic upgrade head -> downgrade one revision -> upgrade head passed against the empty isolated database; populated migration/downgrade-refusal coverage is in the integration suite.
- Real stdio observed/strict-mode negative and positive workflow passed in the focused 37-test integration run. Real stdout/stderr over-limit and timeout subprocess cases passed.
- `PYTHONPATH=.;backend python evaluation/offline_eval.py`: verdict equivalence and guarded replacement oracles OK, with the documented legacy delimiter-collision exception. First attempt without PYTHONPATH failed at import and did not evaluate cases.
- `python evaluation/structural_retest/prepare.py --check-inputs`: succeeds. Default readiness check intentionally exits 2 with explicit blockers. No measured model invoked.
- `git diff --cached --check -- . ":(exclude)evaluation/structural_retest/supplemental" ":(exclude)evaluation/structural_retest/primary"`: passed for code, contracts, manifest and preparation script. Archived fixture/evaluator bytes intentionally retain original CRLF/EOF whitespace and literal conflict-marker task content; their exact SHA-256 checks pass. Full unfiltered diff checking reports those preserved data bytes, which were not rewritten to satisfy whitespace checks. GitHub CI has not yet run on the remediation commit; its exact SHA, URLs and completed results will be pinned in the PR remediation comment.
- Initial focused failures: paging/candidate tests reproduced B-1/B-2 before the fixes. The boolean diagnostic tamper initially did not persist because ORM equality treats false like zero; flag_modified now forces the intended corruption, and replay rejects it. These are resolved, not remaining test failures.
- Non-failing existing warnings: FastAPI/Starlette TestClient deprecation and Alembic path_separator deprecation.

## Remaining blockers and execution boundary

Original primary artifacts were recovered from the user-identified Antigravity scratch/hard_suite: exact native/PatchDIFF prompt payloads, initial source files, target manifest, setup and original external verifier. Every fixture hash matches the original target manifest and transcript initial hash, resolving the stale supplemental REPORT.md table. The common primary task preserves the original 21-edit label and differs from the supplemental 45-target task. Per-arm tool instructions are separate from identical TASK.md and require host verification. Supplemental exact prompt/host binding, independent full-byte collateral oracle, measured-run MCP controller and telemetry binding still require review. Gemini 3.8 Flash High is frozen across future measured arms; provider identity/effective setting/host availability is unverified and the current subagent catalog lacks it. No substitution is permitted.

No comparative subagents were launched, no study executed, no comparative performance conclusions published, no merge performed, and Gate 2 remains CLOSED. Independent review decides closure/approval.

### Interrupted acceptance attempt: shared-database test interference

The concurrent full-suite attempt ran 452 tests with 12 failures. Failures were global snapshot/nonmutation assertions in existing discovery/preview tests while the focused authority suite created and changed other targets in that database. Target-local verdicts were unchanged. No product workaround was added. The acceptance rerun used its own fresh `patchdiff_pr16_final` database with no competing test process and passed all 452 tests; no product workaround was needed.

- `test_every_published_example_real_stdio_postgres`
- `test_real_postgres_inclusive_raw_chars_and_bytes_admission[chars-over]`
- `test_real_postgres_inclusive_raw_chars_and_bytes_admission[bytes-over]`
- `test_real_postgres_inclusive_raw_chars_and_bytes_admission[raw-crlf-over]`
- `test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change[accepted-0.2.3]`
- `test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change[accepted-patchdiff-tx/1]`
- `test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change[accepted-patchdiff-tx/2]`
- `test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change[accepted-patchdiff-tx/3]`
- `test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change[absent-0.2.3]`
- `test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change[absent-patchdiff-tx/1]`
- `test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change[absent-patchdiff-tx/2]`
- `test_preview_matches_fresh_submit_verdict_stages_facts_without_any_managed_table_change[absent-patchdiff-tx/3]`

### Original primary artifacts recovered and authenticated

The final source is Antigravity scratch/hard_suite, supplied by the user. Its five source files match the recorded targets_manifest.json and original prompt hashes. Exact Step 00 prompt payloads were extracted without rewriting text/newlines; transcript hashes and extraction provenance are recorded. Original oracle and setup remain unchanged. TASK.md is the verbatim native task section copied identically to all arms; historical UUIDs and extra B-only hints remain archival evidence. Validator default changes and total_clips distinguish the original 21-edit task from the supplemental 45-target task.

The preparation CLI stages primary fixtures, identical TASK.md and separate per-arm TOOLS.md without copying evaluator/gold/transcript evidence. The external evaluator compiles only the original oracle's two pure check functions, never imports PatchDIFF or runs historical entry points. Both original verifiers reject untouched fixtures in a deterministic negative test. Check totals vary after early section exceptions and are never equated to edit-target counts. No measured agent was launched.
