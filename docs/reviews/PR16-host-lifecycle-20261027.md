# PR #16 bounded host-lifecycle remediation evidence

2026-10-27; PR Review Standard 1.1.0. Engineering implementation/self-inspection,
not independent Gate 2 approval. Repository: https://github.com/paragon-ux/Patch-DIFF;
branch `feat/waymark-structural-observation`; PR https://github.com/paragon-ux/Patch-DIFF/pull/16.

Reviewed baseline: `d16bb4cb314e6efb244f7595385e5c352882eb65`. Fetch before editing
confirmed that exact remote head, clean checkout and no intervening commits.
Independent review read in full:
https://github.com/paragon-ux/Patch-DIFF/pull/16#pullrequestreview-5663740447.
PR base remains `f5cc6742f94e080d2eda7486265e79eebf55c8ad`.

Implementation commit: **`36af615c39a31f9027f7b0aaf9fa59bdd9b828ad`**.
This report is a separate evidence-only follow-up. The final PR comment records
the complete delivery SHA, CI URLs, checkout revisions and inspected test counts.

## Finding ledger and result

| ID | Priority | Independent implementation triage | Evidence | Disposition |
| --- | --- | --- | --- | --- |
| G2-2-R1 | P1 | Confirmed: shared bridge cancellation killed the process later runs reused; failing context cleanup could obscure the original timeout | Baseline controller/provider wait, shared run loop and JsonLinePeer cancellation; corrected real-child tests below | Fixed in implementation commit; independent reviewer recheck required |

No additional in-scope P1, P2 or P3 findings were identified. G3 real Gemini identity,
permissions, usage/hard-token enforcement and independent approval remain external
prerequisites. G2-1 oracle and prior production A-F/G-1 findings are not reopened.
Gate 2 stays **CLOSED**; no live/alternative model, measured task, merge or approval
was performed. This fix cannot establish that an actual owner bridge is trustworthy.

## Architecture and lifecycle

Contract: fresh independent state per scheduled arm/replicate -> one supervised
bridge per run -> fresh describe and exact frozen host evidence -> existing
`validate_host`, all-arm `tool_binding_errors` and fresh context -> unchanged task
budgets -> bounded context cleanup/process reap -> existing export/replay/oracles
and one terminal archive -> next independently started/verified process.

`controller.py:424` accepts a factory for live execution and rejects a shared live
host instance. CLI creation is deferred to that factory. Synthetic in-process hosts
retain their existing reusable behavior. The same supervisor can be tested with
explicitly synthetic subprocess bridges without authorizing any live provider.

`Run.start_host` (`controller.py:105`) requires a new unstarted BridgeHost object,
starts it, obtains actual PID and fresh describe response, compares the complete
description to approved evidence, applies the existing host validator and verifies
tool bindings before opening a context. Failed start/attestation is archived as
`blocked_by_host_preflight`; later schedule rows remain `not_started` with the
original blocking reason and no fabricated task, usage or oracle outcomes. No
later bridge/context is opened. The study returns failure requiring operator review.

`Run.agent_loop` records timeout/disconnect events and propagates the original
exception. `Run.execute` (`controller.py:303`) records that primary failure and
catches bounded context cleanup errors separately in `cleanup_failures`, without
overwriting the root cause. Cleanup failures also prevent a successful run verdict.

`Run.reap_host` (`controller.py:89`) terminates/reaps the owned bridge before
archival/next scheduling, including preflight failures. If reaping itself fails,
further execution is blocked. Normal shutdown closes stdin and permits one second
for EOF exit, then kills if needed; cancellation kills immediately. Child waits are
bounded. EOF/dead-child/broken-pipe conditions are ConnectionError rather than a
misleading JSON parse failure. No task retry, context reuse or budget extension
is introduced. The subprocess EOF/kill fallback is shutdown, not a second recovery
scheme or provider transport retry.

Events include `host_process_started`, `host_description_received`,
`host_attestation_verified`, `host_context_opened`, `host_turn_timeout` or
`host_turn_disconnected`, `host_context_cleanup_failed` and `host_process_reaped`.
PIDs/return codes come from real subprocess handles; startup, preflight, request
and cleanup durations use the actual monotonic clock. Startup/attestation are
separate overhead, outside the unchanged task timer. No credentials/environment
secrets or bridge command arguments are added to the evidence.

## Deterministic subprocess acceptance cases

`backend/tests/fixtures/retest_host_bridge.py` is a local JSON-lines child with no
network, SDK, model or solved output. Tests use actual BridgeHost subprocess
transport/supervision, synthetic provider responses and deterministic native/MCP
binding/target test doubles. Existing integration tests independently exercise real
MCP/PostgreSQL. Timeout tests simulate elapsed planning time in the Budget start
value to reach the real asyncio deadline quickly; production manifest budgets and
actual process/timing evidence are unchanged.

| Required case | Assertions observed |
| --- | --- |
| A Timeout isolation | First run processes a native no-op then blocks; actual child is cancelled/killed/reaped; TimeoutError remains first failure; one archive; next verified child has a different PID/provider session/context, empty initial tool results and fresh 600-second/16,000-token budget state |
| B Unexpected exit | Child exits during second provider request with code 23; ConnectionError belongs to first run; no task retry; new verified process completes next no-op flow; all nine schedule records retained |
| C Changed replacement identity | Five parametrizations change model ID, reasoning, host version, permissions or provider evidence; replacement gets no open request; it is archived blocked; seven later runs are not_started with reasons and no oracle/task results |
| Additional startup failure | Missing replacement executable stops execution before any new context; remaining schedule remains explicit and unsuccessful |
| D Cleanup preserves cause | Original timeout remains the only primary failure; dead-child context cleanup is secondary ConnectionError; process reaped, single archive, next independent run finishes |
| E Normal lifecycle | All nine healthy fake bridges have distinct actual PIDs/fresh contexts; identical attested contracts; close/EOF/exit zero; no subprocess leak; original order/budgets unchanged |
| F Existing behavior | Full old unit/live integration suites plus fresh nine-run synthetic dry-run pass; no-op outputs still fail the original task; real rejection/lost-response idempotency, strict C, SAVE/export/replay, oracle collateral and telemetry checks remain covered |

Focused lifecycle result: **10 passed**, no failures/skips. Test cleanup asserts no
live child handles before emergency cleanup, so a passing test cannot conceal leaks.

## Verification

Local: Windows, Python 3.11.9, Node 22.19.0, Docker PostgreSQL 16.3, pinned existing
dependencies. Integration database `patchdiff_pr16_host_lifecycle` was created fresh
and migrated to head; controller probes created separate disposable DBs. No suites
mutated target tables concurrently in the same DB.

Commands used the repository `.venv/Scripts/python.exe`:

| Command | Observed result |
| --- | --- |
| `python -m pytest backend/tests/unit/test_retest_host_lifecycle.py -q` | 10 passed; focused rerun with JUnit: 42.228 s |
| `python -m pytest backend/tests/unit -q` | 919 passed, 0 failed/skipped, 251.368 s |
| `python -m pytest backend/tests/integration -q` | 455 passed, 0 failed/skipped, 342.945 s; includes real stdio/Waymark/PostgreSQL regressions |
| `python evaluation/offline_eval.py` | Verdict-equivalence and content/hash oracles OK, unchanged named delimiter exception |
| `python evaluation/structural_retest/prepare.py --check-inputs` | Exit 0; Gate 2 closed |
| `python evaluation/structural_retest/controller.py --check-inputs` | Exit 0; frozen pins valid, zero model invocations |
| `python evaluation/structural_retest/controller.py --dry-run-synthetic --destination <new-private-directory>` | Exit 0; 9/9 archived, ABC/BCA/CAB, six fresh real MCP DBs, zero measured model invocations, comparative_results=false |
| `git diff --check` / staged check | Passed |

All nine synthetic no-op outputs remain failed task-oracle results, preserved in
evidence. This is infrastructure verification, not measured comparison data.
Local JUnit, lifecycle child traces/run archives (10 canonical cases), validation
JSON and real-MCP dry-run evidence are retained outside the checkout under the
task workspace's `pr16-evidence/bounded-lifecycle-20261027/`. Source tests reproduce
the assertions. Known existing FastAPI/httpx and Alembic deprecation warnings remain.

Raw final manifest SHA-256:
`58ebe0b392a246e0fa3ada1ee075330b830e8e3067a353c655ca4e039f3ccbbd`.
The only manifest changes are `controller.py` and `host_adapter.py` source pins.
All model, arms, conditions, artifact/prompt and oracle fields compare equal to
baseline. The hidden reference-manifest hash remains
`d43bdf7a9586bec87e47961035938e63ef9f3504f3c1a33a7ebab1e1c0886ef6`.
Production runtime, npm dependency, original primary bytes and supplemental paths
have an empty Git delta. No primary oracle or fixture was rewritten.

## Changed-file inventory and category coverage

| File | Primary review category |
| --- | --- |
| `evaluation/structural_retest/controller.py` | SCRIPT |
| `evaluation/structural_retest/host_adapter.py` | SCRIPT |
| `evaluation/structural_retest/manifest.json` | SCRIPT |
| `backend/tests/fixtures/retest_host_bridge.py` | TEST |
| `backend/tests/unit/test_retest_host_lifecycle.py` | TEST |
| `docs/WAYMARK_STRUCTURAL_OBSERVATION_RETEST_PLAN.md` | DOC |
| `docs/reviews/PR16-host-lifecycle-20261027.md` | DOC (this evidence-only follow-up) |

Category records below apply only to the bounded delta. Prior independent production
review is retained, not replaced by self-inspection or green CI.

| Category | Scope / coverage | P1 | P2 | P3 | Verification / verdict |
| --- | --- | --- | --- | --- | --- |
| ARCH | Complete: per-run host ownership and existing host/MCP boundary | G2-2-R1 root cause addressed under SCRIPT | None newly identified in scope | None identified in scope | New process/attestation/context lifecycle verified; independent recheck pending |
| DOC | Complete: lifecycle paragraph and this implementation record | None identified in scope | None identified in scope | None identified in scope | Statements match observed tests; no execution approval |
| SKILL | No instruction or skill edits | Not assessed as skill changes | Not assessed | Not assessed | Applicable instructions read; no independent skill audit requested |
| MCP | No production schema/API change; child EOF handling exercised | None identified in changed interaction scope | None identified in scope | None identified in scope | Existing real MCP integration suite passed |
| RUN | No core runtime/parser change | Not assessed as runtime changes | Not assessed | Not assessed | Unit/integration regressions pass; prior independent verdict retained |
| SVC | Complete for host supervisor/cleanup; services unchanged | Same G2-2-R1, not a second finding | None newly identified in scope | None identified in scope | Primary/secondary failures and no task rerun verified |
| DB | No DB/migration/replay implementation change | Not assessed as implementation changes | Not assessed | Not assessed | Fresh DB and existing migration/replay/audit tests passed |
| SCRIPT | Complete: controller, adapter and pin delta | G2-2-R1 fixed in implementation; peer recheck pending | None additional identified in scope | None identified in scope | Ten real-child tests and all existing suites; offline ready for re-review |
| TEST | Complete for new fixture/assertions and required regression execution | None additional identified | None identified in scope | None identified in scope | 919/455 plus focused 10 and dry-run; final CI in PR comment |
| DEP | No dependency/config semantics change; two source pins updated | None identified in bounded scope | None identified in scope | None identified in scope | Pin check and unchanged manifest contracts verified |

## Remaining Gate 2 requirements

Independent re-review of G2-2-R1 at the corrected exact head; actual owner-provided
Gemini 3.8 Flash High identity/effective High, host build, native/MCP bindings,
sandbox permissions, cancellation and actual usage/hard-total-token proof; external
Gate 2 authorization bound to corrected commit/manifest/verified host evidence.
Internal SQL/Waymark timing limitations and supplemental-study gating remain as
previously documented. The owner alone conducts the later comparison after approval.
No `--execute` invocation occurred during this assignment.
