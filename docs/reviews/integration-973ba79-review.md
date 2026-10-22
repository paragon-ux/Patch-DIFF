# Integration review

Date: 2026-10-22. Reviewer: `/root/integration_review`, inherited/default model; no special review role, model override or subdelegation. Repository: `paragon-ux/Patch-DIFF`. Standard: `docs/PR_REVIEW_STANDARD.md` v1.1.0. Branch: `feature/goal-f-pass-b`.

- [PR11](https://github.com/paragon-ux/Patch-DIFF/pull/11): base `2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10`, head `d27c1832a85efdb92e12d0b9fcf8acefb1c559f6`.
- [PR12](https://github.com/paragon-ux/Patch-DIFF/pull/12): stacked base `d27c1832a85efdb92e12d0b9fcf8acefb1c559f6`, reviewed candidate `973ba7901769871012f355f8443ffe05abd58878`.
- Candidate tree: `cf718a2e26f68a11819810de9a48228ef64f9bc4`.
- Combined review comparison: main `2ee7ce4` to candidate `973ba79`, 119 changed paths, inventoried below.

What this change does: the stack adds bounded rejection evidence and invocation correlation, guarded sequential span operations, guarded sole replacement, coherent line reads, advisory preview and executable discovery examples. All four proposal formats converge on the deterministic applier and the existing authoritative submit/persistence path.

**Disposition: no new integration defect identified in the reviewed source and evidence. All ten material categories have source coverage, through independently inspected seams plus explicit reuse of prior category reviews. This is not merge approval. Final candidate head/generated-merge CI and the user's separate merge authorization remain required; PR11 is to remain open for review.**

## Scope, evidence and reuse

This distinct review assesses the connected PR11+PR12 result, rather than repeating their implementation reviews. The reviewer owns only this new report. No production changes, commit, push, merge, test suite or product-workflow rerun was performed. No current CI logs or fresh database state were independently fetched here; those are parent-owned checks. Read-only Git/source inspection, captured-wire decoding, artifact XML counting and SHA-256 comparisons were executed locally.

Prior ten-category source reviews reused for unchanged material:

1. `Goal-F-PASS-A-46bd293-review.md`, corrections through `154ab7a`, published at PR11 head `d27c183`. Git comparison confirms `154ab7a..d27c183` has no product/skill/workflow delta.
2. `Goal-F-PASS-B-84ec120-review.md`, corrections through `9854e1b` and its final documentation delta. The subsequent product delta is confined to `pdcp_service.py` and new `preview_evidence.py`; the only subsequent skill delta is the MCP projection guidance.
3. `Goal-F-PASS-B-budget-537937d-review.md`, covering the bounded-preview correction. Git comparison confirms `537937d..973ba79` changes no production Python, workflow, packaging or lockfile.

These reports' source conclusions and explicit evidence limitations are accepted after checking their affected seams; their historical approval/CI status is not inherited. The unchanged rejection-context foundation and original-paper thesis trace are reused through the guarded-operations review. Historical original design records, old remediation scripts and full old test matrices were not individually re-reviewed. The accepted change plan revision 2, its authority manifest, EXECUTION-PLAN, preimplementation decisions, active contracts, repository skills, relevant source, actual test assertions, manual helpers and captured records were examined. No new external ecosystem or model-success claim is made.

## Coverage matrix and architecture trace

| Category | Coverage | Integration focus |
| --- | --- | --- |
| ARCH | Complete for affected scope; prior unchanged trace reused | Authority, format/profile boundaries, advisory versus authoritative state, limits and deferrals |
| DOC | Complete for affected scope; historical evidence reused | Active contracts, delivery/verification claims and evidence revision boundaries |
| SKILL | Complete for affected scope | Real entry points, four formats, 20 tools, ownership and projection instructions |
| MCP | Complete for affected scope | Registry, actual stdio adapter, schemas, sentinel/null distinctions, serializer, all 13 example pairs |
| RUN | Complete for affected scope; prior unchanged parser matrices reused | Four-format lowering, shared applier, immutable profiles and full-span replacement facts |
| SVC | Complete for affected scope | Shared evaluator, locked key recovery/admission, zero-write preview, projection, coherent line reads |
| DB | Complete for affected scope; prior migration review reused | Lock refresh, atomic log/ledger updates, caller ownership, replay, SAVE/export |
| SCRIPT | Complete for affected scope; old unrelated helpers reused | Manual assertion quality, actual pair binding/traversal and byte-only offline oracles |
| TEST | Complete source/evidence review; final execution gate pending | Actual assertions/XML/wire evidence, ownership/concurrency and final CI distinction |
| DEP | Complete for affected scope | Unchanged dependencies/CI startup; exact accepted-snapshot byte preservation |

The accepted change plan's exact deterministic transition thesis leads to AGENTS/current architecture, then the public format/schema contracts, then strict parsers lowering into ParsedPDCP and one applier. tx/1 and legacy continue recording 0.2.2; tx/2 records 0.3.0; tx/3 records 0.4.0. Earlier 0.1.0/0.2.0/0.2.1 profiles retain their recorded flags. Replacement is an explicit authorized extension, never an empty-MATCH workaround or an implicit editing adapter.

Public registry calls create the service session; submit takes the refreshed target row lock and checks an existing key before fresh size admission. Successful simulation yields full accepted facts, exactly one replacement ledger row and monotonic version advancement. SAVE uses the same target lock and snapshots that authoritative state; replay decodes recorded formats/profiles and verifies hash/version/materialized state; export returns canonical current text. Preview observes scalar columns once under no_autoflush, rejects pending local target changes, runs the shared fresh evaluator, then projects only its advisory response. A later submit independently locks and checks guards. Optional typed guards, normalized identity and a line-based editing adapter remain deferred; no migration, identity normalization, optional typed guard or fuzzy application was introduced.

## Candidate-finding ledger and prior closure

No new candidate defect was identified. There are no new IDs requiring implementation-agent triage, and no reviewer-deferred candidates.

| Earlier IDs | Integration recheck | Status |
| --- | --- | --- |
| TEST-A1; SKILL-A1/A2 | Current failure enum expectations and persistence guidance agree with actual labels, profiles and qualified admitted-attempt ownership. | Prior fixes retained; no regression found |
| MCP-B1; TEST-B1/B2 | Admission serializer retains diagnostic/null log/correlation; public helper expects match_absent; fixture supplies current identity fields. Captured oversized response and passing narrow evidence support closure. | Prior fixes retained; no regression found |
| ARCH-B1; SKILL-B1; SCRIPT-B1 | Four-format/profile/tool lists and replacement byte/oracle section agree with source and explicit accepted scope. | Prior fixes retained; no regression found |
| PRESERVE-B1 | Both worktree and candidate Git blob SHA-256 values exactly equal AUTHORITY.json; exact two accepted paths have -text attributes. | Prior fix retained; independently hash-rechecked |
| BUDGET-B1 | Every public preview return passes through the projection; current 48 production and two helper hashes match the actual 537937d manual record. Whole-prefix/omission/wire assertions inspected and sizes independently recomputed. | Fixed at 537937d; integration recheck clear |

## ARCH — Architecture and contracts

**Scope/coverage:** Complete for connected authority/decisions, AGENTS, current format/profile and preview/resource contracts. Unchanged original-paper interpretation inherits the explicit prior architecture trace.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** Traced host-owned proposals to deterministic guarded transition, audit/replay and read-only advisory projection. Confirmed numeric fresh admission versus replay semantics and preview bounds are separate contracts. **Gaps:** Representative migration datasets and performance thresholds remain unavailable.

**Verdict:** No findings within reviewed scope.

## DOC — Documentation and change records

**Scope/coverage:** Complete for affected active contracts, decisions, PASS-A/PASS-B verification, delivery ledger and new projection evidence; unchanged historical records reused.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** Records correctly retain failed initial suites and narrow corrections. Nine implementations, three evidence closures and two deferred feature IDs are distinct. Initial 1e0b800 green CI is labeled historical; 537937d execution is not relabeled 973ba79. **Gaps:** Final CI/main release evidence is subsequent parent-owned work.

**Verdict:** No findings within reviewed scope.

## SKILL — Skills and agent instructions

**Scope/coverage:** Complete for four repository skills and AGENTS guidance, with unchanged material reused after source reconciliation.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** Tool inventory, four declarative formats, profile pairing, shared evaluator, zero-audit/keyless preview, caller ownership and numeric projection instructions match actual implementation. Qualified audit exceptions survive the stack. **Gaps:** No installed skill-loader deployment was exercised.

**Verdict:** No findings within reviewed scope.

## MCP — MCP schemas and public API

**Scope/coverage:** Complete for actual server registry, external_adapter.py, tools.py, schema construction, result serialization and 13 examples over nine tools.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** Registry signatures and public wrappers route to real services. Typed guard alternatives, format-conditioned required fields/irrelevant-field rejection, item schemas and omitted/null sentinel handling agree. Examples are deep-copied. Admission details survive serializer; preview is directly returned through its bounded wrapper. Manual helper validates each actual bound example against discovered schemas and requires pair-set equality, exact keyed resend and complete cursor traversal. **Gaps:** No reviewer tool call or current installed-host test; captured real subprocess evidence is distinguished below.

**Verdict:** No findings within reviewed scope.

## RUN — Core runtime, parsing and validation

**Scope/coverage:** Complete for connected versions/applier/replacement and typed/operations/legacy interfaces; unchanged parser/profile matrices inherit prior reviews.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** Explicit sole replace_all lowers into one full original span, permits empty replacement, normalizes LF and emits complete hashes/counts/operation facts. Sequential match/span still use canonical code-point coordinates and exact expected text. New operations default disabled and old replay flags unchanged. Shared stage-aware evaluator classifies encoding before guards and separates structural from applicability failures. **Gaps:** No runtime rerun by reviewer; exhaustive unchanged cases reused.

**Verdict:** No findings within reviewed scope.

## SVC — Services, orchestration and audit semantics

**Scope/coverage:** Complete for submit entry points, decorator, evaluator, recovery/admission/persistence handoffs, read observation/line slicing and all preview projection returns.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** Existing-key recovery/conflict precede stricter fresh replacement limits; invalid Unicode still enters audited rejection. Fresh valid oversize exits before current-PDCP upsert. Correlation stays outside identity; near misses run only after owned commit or explicitly omit for caller ownership; preview never invokes them. Preview copies response evidence, returns a whole ordered prefix of at most 32 facts, and omits arbitrary oversized evidence explicitly without modifying core/submit/history facts. Line ranges preserve LF/final-empty-line semantics and bounded range-relative continuation. **Gaps:** No new service execution; recorded evidence/assertions inspected.

**Verdict:** No findings within reviewed scope.

## DB — Database, migrations, replay and concurrency

**Scope/coverage:** Complete for connected repository/model/persist/recover/replay/SAVE/export paths; unchanged populated migration review/evidence reused. No new migration.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** FOR UPDATE uses populate_existing; full accepted log/ledger/target updates share the transaction owner. Replay dispatch selects recorded profiles, validates chains and bypasses fresh admission. Test assertions cover real pg_blocking_pids writer wait followed by stale rejection, caller commit/rollback visibility, one ordinary preview/line SELECT, stale/dirty ORM preservation, unchanged caller transaction and all-managed-table row-content equality. SAVE/replay/export in captured B workflow agree with mixed-profile final state. **Gaps:** No reviewer fresh SQL or two-session probe; prior reviewers performed separate read-only SQL rechecks. Representative production performance is unproved.

**Verdict:** No findings within reviewed scope.

## SCRIPT — Scripts, evaluation and developer tooling

**Scope/coverage:** Complete for A/B/budget manual helpers and offline replacement accounting; older baseline/consolidation helpers inherit prior scope.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** Helpers launch real raw-UTF8 stdio children, bind actual IDs/guards/parents/cursors and check expected outcomes. B history traversal is nonvacuous and unique sequence sets equal SQL; pair-set equality covers every advertised example. Budget helper asserts whole fact count/bytes, giant guard/legacy identity/invalid target omissions, whole payload bytes and all-table nonmutation. Offline evaluation retains named delimiter exception and explicit tx/3 content/hash/fact oracles with bytes-only claims. **Gaps:** No script rerun by reviewer; baseline/old merge utilities not newly executed.

**Verdict:** No findings within reviewed scope.

## TEST — Tests and CI

**Scope/coverage:** Complete for integration-relevant assertions and recorded artifacts, reusing unchanged exhaustive matrices. Inspected four-format/eight-case parity, boundaries, recovery, ownership, concurrency, sequential rejection, ABA, discovery, line reads and projection tests.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** Tests assert actual before/after table contents, transaction identity, SQL statement count/lock absence, expected hashes and fact equality; coverage is not inferred from names. Independently counted artifact cases: A 1005/one failure, B 1116/one failure, budget 88/zero failures. Budget actual wire/source/helper checks detailed below. CI source still requires pinned install, migration cycle, unit, live PostgreSQL integration and offline checks. **Gaps:** Final `973ba79` head/generated-merge CI pending at review; no suite rerun by reviewer.

**Verdict:** No source finding; final execution gate remains open.

## DEP — Dependencies, packaging and configuration

**Scope/coverage:** Complete for unchanged pyproject/lockfile/CI, standard-library projector imports, adapter startup and .gitattributes preservation change.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification:** No new dependency, package/version/configuration name or schema migration. Existing Python>=3.11/SQLAlchemy/Postgres assumptions remain. Exact accepted archive path attributes retain authoritative bytes; both current/Git hashes verified. **Gaps:** No new installation/platform test; fresh autocrlf checkout verification inherits preservation review.

**Verdict:** No findings within reviewed scope.

## Independent artifact and stack recheck

- Read-only Git checks establish main `2ee7ce4` is ancestor of PR11 `d27c183`, and `d27c183` is ancestor/exact merge-base of candidate `973ba79`. Existing integration merge `5ac2e77` has parents `f263f2e`/`d27c183`. PR12 is dependent on PR11; the candidate already includes that exact PR11 head. Review does not assert an independently executed merge into future main.
- A `git merge-tree --write-tree d27c183 973ba79` attempt failed because the common Git object database is read-only under reviewer sandbox. No escalation/retry/mutation was performed. Read-only ancestry/tree inspection supplies the stack evidence; actual merge/apply and final generated-merge CI remain parent-owned.
- PASS-A manual record pins `46bd293`, 47 production hashes, 19 events/seven groups. PASS-B record pins `c34a7e5`, 47 hashes, 27 events/four groups/all 13 pairs. Their helper assertions and prior independent wire/SQL rechecks are reused, with source changes since those runs explicitly delimited.
- PASS-B-budget record pins `537937d`, 48 production hashes, six events/three groups. Independently recomputed every current production source hash and both helper hashes: all match. Candidate production/workflow/packaging/lockfile tree is unchanged from `537937d`.
- Independently decoded budget responses, recomputed request lengths/SHA-256/response-ID correlation for captured raw requests, and recomputed compact ASCII-escaped payload bytes: **10331/1331/1502/1149**, all below 32768. Accepted response returns 32 complete facts of 40; rejection/invalid identity evidence is explicitly omitted. The executed helper asserts all-table equality and final version 0/content `x`/no logs/no ledger; this reviewer does not present that captured SQL as a new live query.
- Independently parsed JUnit cases rather than accepting run summaries: A 1005/one failure, B 1116/one failure, budget 88/zero failures. Narrow fixes and current assertion bodies agree with retained prior closure records. No green initial-local-suite claim is made.
- Reported historical PR11 CI `39725819914`/`39725850799` executed `d27c183`/generated merge `cba7396`; reported historical PR12 preservation CI `39727987137`/`39727991970` executed `1e0b800`/generated merge `c3f4b16`. These pins come from retained verification/delivery records, not fresh CI-log inspection in this review. They establish no green result for `973ba79`. Parent owns current logs and actual checkout SHA verification.

## Cross-category conclusion and handoff

No new cross-category root cause or implementation candidate remains. Prior corrective findings have source fixes plus independent rechecks; this integration review found no reason to reopen them. Coverage and execution disposition remain separate: affected source coverage is complete, while final candidate CI and separate user merge approval remain open. Representative migration/performance evidence and installed-host/model/performance claims remain outside the supplied evidence.

Parent handoff: retain this review at its pinned candidate, finish exact-head/generated-merge CI inspection and final stack/release verification within existing authorization. If either exposes a candidate, independently triage it on the feature branch, preserve all prior evidence and obtain an affected-category recheck. Do not merge PR11 or PR12 from this report alone.

## Appendix: machine-generated primary-category inventory

The following inventory is generated from `git diff --name-only 2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10 973ba7901769871012f355f8443ffe05abd58878`. Each path appears once. This report itself is outside that pinned comparison.

| Category | Path |
| --- | --- |
| SKILL | <code>.agents/skills/patchdiff-core-runtime/SKILL.md</code> |
| SKILL | <code>.agents/skills/patchdiff-mcp-orchestration/SKILL.md</code> |
| SKILL | <code>.agents/skills/patchdiff-persistence-replay-save/SKILL.md</code> |
| SKILL | <code>.agents/skills/patchdiff-testing-review/SKILL.md</code> |
| DEP | <code>.gitattributes</code> |
| ARCH | <code>AGENTS.md</code> |
| RUN | <code>backend/app/core/diagnostics.py</code> |
| RUN | <code>backend/app/core/failures.py</code> |
| RUN | <code>backend/app/core/result.py</code> |
| RUN | <code>backend/app/core/validity.py</code> |
| RUN | <code>backend/app/core/versions.py</code> |
| MCP | <code>backend/app/mcp/external_adapter.py</code> |
| MCP | <code>backend/app/mcp/tools.py</code> |
| RUN | <code>backend/app/pdcp/applier.py</code> |
| RUN | <code>backend/app/pdcp/models.py</code> |
| RUN | <code>backend/app/pdcp/operations.py</code> |
| RUN | <code>backend/app/pdcp/replacement.py</code> |
| SVC | <code>backend/app/services/near_miss_service.py</code> |
| SVC | <code>backend/app/services/pdcp_service.py</code> |
| SVC | <code>backend/app/services/preview_evidence.py</code> |
| SVC | <code>backend/app/services/read_service.py</code> |
| SVC | <code>backend/app/services/rejection_context.py</code> |
| DB | <code>backend/app/services/replay_service.py</code> |
| TEST | <code>backend/tests/integration/test_conflict_audit_live.py</code> |
| TEST | <code>backend/tests/integration/test_invalid_input_unicode_live.py</code> |
| TEST | <code>backend/tests/integration/test_mcp_tools.py</code> |
| TEST | <code>backend/tests/integration/test_pass_a_flow.py</code> |
| TEST | <code>backend/tests/integration/test_pass_b_discovery.py</code> |
| TEST | <code>backend/tests/integration/test_pass_b_reads.py</code> |
| TEST | <code>backend/tests/integration/test_pass_b_submission_preview.py</code> |
| TEST | <code>backend/tests/integration/test_preview_budget_live.py</code> |
| TEST | <code>backend/tests/integration/test_rejection_context_flow.py</code> |
| TEST | <code>backend/tests/unit/test_failures.py</code> |
| TEST | <code>backend/tests/unit/test_invalid_input_unicode.py</code> |
| TEST | <code>backend/tests/unit/test_pass_a_diagnostics.py</code> |
| TEST | <code>backend/tests/unit/test_pass_a_operations.py</code> |
| TEST | <code>backend/tests/unit/test_pass_b_reads_discovery.py</code> |
| TEST | <code>backend/tests/unit/test_pass_b_runtime.py</code> |
| TEST | <code>backend/tests/unit/test_preview_evidence.py</code> |
| TEST | <code>backend/tests/unit/test_rejection_context.py</code> |
| DOC | <code>docs/DATA_MODEL.md</code> |
| DOC | <code>docs/HOST_INTEGRATION_GUIDE.md</code> |
| DOC | <code>docs/MCP_FIRST_MVP.md</code> |
| DOC | <code>docs/MCP_TOOLS.md</code> |
| ARCH | <code>docs/MODERNIZATION_ARCHITECTURE.md</code> |
| DOC | <code>docs/MODERNIZATION_CHANGE_DOC.md</code> |
| DOC | <code>docs/PATCHDIFF_CORE_SPEC.md</code> |
| DOC | <code>docs/PDCP_FORMAT.md</code> |
| DOC | <code>docs/reviews/Goal-F-F01-128f59d-review.md</code> |
| DOC | <code>docs/reviews/Goal-F-PASS-A-46bd293-review.md</code> |
| DOC | <code>docs/reviews/Goal-F-PASS-B-84ec120-review.md</code> |
| DOC | <code>docs/reviews/Goal-F-PASS-B-budget-537937d-review.md</code> |
| DOC | <code>docs/usability/BASELINE-and-evidence-closures.md</code> |
| TEST | <code>docs/usability/BASELINE-junit.xml</code> |
| TEST | <code>docs/usability/BASELINE-live-results.json</code> |
| SCRIPT | <code>docs/usability/BASELINE-live-verify.py</code> |
| TEST | <code>docs/usability/BASELINE-manual.txt</code> |
| TEST | <code>docs/usability/BASELINE-offline.txt</code> |
| TEST | <code>docs/usability/BASELINE-suite.txt</code> |
| ARCH | <code>docs/usability/EXECUTION-PLAN.md</code> |
| ARCH | <code>docs/usability/F01-decision.md</code> |
| TEST | <code>docs/usability/F01-junit.xml</code> |
| TEST | <code>docs/usability/F01-live-results-development.json</code> |
| TEST | <code>docs/usability/F01-live-results.json</code> |
| SCRIPT | <code>docs/usability/F01-live-verify.py</code> |
| TEST | <code>docs/usability/F01-manual.txt</code> |
| TEST | <code>docs/usability/F01-offline.txt</code> |
| TEST | <code>docs/usability/F01-suite.txt</code> |
| DOC | <code>docs/usability/F01-verification.md</code> |
| DOC | <code>docs/usability/GEMINI-v1-v2-REVIEW.md</code> |
| TEST | <code>docs/usability/GEMINI-v2-evidence-check.json</code> |
| SCRIPT | <code>docs/usability/GEMINI-v2-evidence-check.py</code> |
| DOC | <code>docs/usability/GOAL-F-DELIVERY-LEDGER.md</code> |
| ARCH | <code>docs/usability/PASS-A-decision.md</code> |
| TEST | <code>docs/usability/PASS-A-junit.xml</code> |
| TEST | <code>docs/usability/PASS-A-live-results.json</code> |
| SCRIPT | <code>docs/usability/PASS-A-live-verify.py</code> |
| TEST | <code>docs/usability/PASS-A-manual.txt</code> |
| TEST | <code>docs/usability/PASS-A-offline.txt</code> |
| TEST | <code>docs/usability/PASS-A-recheck-junit.xml</code> |
| TEST | <code>docs/usability/PASS-A-recheck.txt</code> |
| TEST | <code>docs/usability/PASS-A-suite.txt</code> |
| DOC | <code>docs/usability/PASS-A-verification.md</code> |
| TEST | <code>docs/usability/PASS-B-budget-junit.xml</code> |
| TEST | <code>docs/usability/PASS-B-budget-live-results.json</code> |
| SCRIPT | <code>docs/usability/PASS-B-budget-live-verify.py</code> |
| TEST | <code>docs/usability/PASS-B-budget-manual.txt</code> |
| TEST | <code>docs/usability/PASS-B-budget-tests.txt</code> |
| ARCH | <code>docs/usability/PASS-B-decision.md</code> |
| TEST | <code>docs/usability/PASS-B-fixture-recheck-junit.xml</code> |
| TEST | <code>docs/usability/PASS-B-fixture-recheck.txt</code> |
| TEST | <code>docs/usability/PASS-B-junit.xml</code> |
| TEST | <code>docs/usability/PASS-B-live-results.json</code> |
| SCRIPT | <code>docs/usability/PASS-B-live-verify.py</code> |
| TEST | <code>docs/usability/PASS-B-manual-initial-failure.txt</code> |
| TEST | <code>docs/usability/PASS-B-manual.txt</code> |
| TEST | <code>docs/usability/PASS-B-offline.txt</code> |
| TEST | <code>docs/usability/PASS-B-recheck-junit.xml</code> |
| TEST | <code>docs/usability/PASS-B-recheck.txt</code> |
| TEST | <code>docs/usability/PASS-B-suite.txt</code> |
| DOC | <code>docs/usability/PASS-B-verification.md</code> |
| ARCH | <code>docs/usability/accepted/AUTHORITY.json</code> |
| ARCH | <code>docs/usability/accepted/DEVIN_CHANGE_PLAN-b33faaf-v2.md</code> |
| ARCH | <code>docs/usability/accepted/Devin-Goal-F.md</code> |
| DOC | <code>docs/usability/integration/CONSOLIDATION_RECHECK.md</code> |
| TEST | <code>docs/usability/integration/PR-1-CI-39663238218.txt</code> |
| TEST | <code>docs/usability/integration/PR-10-CI-39663057668.txt</code> |
| TEST | <code>docs/usability/integration/PR-5-CI-39661605566.txt</code> |
| TEST | <code>docs/usability/integration/PR-6-CI-39569958566.txt</code> |
| TEST | <code>docs/usability/integration/PR-6-CI-39662203586.txt</code> |
| TEST | <code>docs/usability/integration/PR-7-CI-39662500697.txt</code> |
| TEST | <code>docs/usability/integration/PR-8-CI-39662684583.txt</code> |
| TEST | <code>docs/usability/integration/PR-9-CI-39662879868.txt</code> |
| TEST | <code>docs/usability/integration/merge-ledger-attempt1.json</code> |
| TEST | <code>docs/usability/integration/merge-ledger-attempt2.json</code> |
| TEST | <code>docs/usability/integration/merge-ledger-attempt3.json</code> |
| TEST | <code>docs/usability/integration/merge-ledger.json</code> |
| SCRIPT | <code>docs/usability/integration/merge_stack.py</code> |
| SCRIPT | <code>evaluation/offline_eval.py</code> |

Inventory total: 119 paths. Counts: ARCH=9, DB=1, DEP=1, DOC=18, MCP=2, RUN=9, SCRIPT=8, SKILL=4, SVC=5, TEST=62.

## Narrow public-documentation and package recheck — 9473e8b

Recheck date: 2026-10-22. Base `973ba7901769871012f355f8443ffe05abd58878`; initial head `9473e8bdfc64ae2c2630146af53e2c3428f1ca55`; correction rechecks `60b16da336cd1c9678f561fca985d9a824a95184` and `57dd7c44b7fbd2e421abaa087591526f0de7037c`. This addendum preserves the preceding candidate review. The parent requested contract/behavior consistency and package-integration review; another independent reviewer owns license choice/security-advisory proof. No reviewer product execution, suite, install, commit or merge was performed. The parent owns fresh-environment complete tests, built-wheel/installed stdio smoke and final CI.

The exact 26-file delta has no backend/app, backend/tests, repository skill or review-standard change. The app tree is identical at both commits: `08467cf1c81e86ac8ab9828a774a9f901d51ea40`. Public documents replace internal workflow labels with capability names, retain numeric bounds/ownership/compatibility and remove stale totals. The new product change record restates actual format/profile, request identity, admission, projection, replay and evidence limits. AGENTS' tool groups now explicitly include replacement/line reads/preview.

| Primary category | Delta paths |
| --- | --- |
| ARCH | `AGENTS.md`; `docs/MODERNIZATION_ARCHITECTURE.md` |
| DOC | `CHANGELOG.md`; `README.md`; `README_DEV.md`; `README_INTERNAL_MCP.md`; `SECURITY.md`; `docs/CLAUDE_DESKTOP_SETUP.md`; `docs/CODEX_BUILD_PLAN.md`; `docs/DATA_MODEL.md`; `docs/HOST_INTEGRATION_GUIDE.md`; `docs/MCP_FIRST_MVP.md`; `docs/MCP_TOOLS.md`; `docs/MODERNIZATION_CHANGE_DOC.md`; `docs/PATCHDIFF_CORE_SPEC.md`; `docs/PDCP_FORMAT.md`; `docs/RELEASE_READINESS.md`; `docs/TEST_MATRIX.md`; `docs/usability/internal/MODERNIZATION_CHANGE_DOC-973ba79.md`; `evaluation/README.md` |
| DEP | `.gitattributes`; `.gitignore`; `LICENSE`; `docker-compose.yml`; `pyproject.toml`; `requirements.lock` |

The archive preserves the previous Windows worktree's exact CRLF bytes, not the old LF-normalized Git blob: SHA-256 `461008e70dc3b7da815ee503b3ea9ae39ad8208efdd574c12649f8b6394dff51`. Independently verified the archive equals the old blob converted to its CRLF worktree form, and the new archive Git blob equals those exact worktree bytes under its explicit `-text` attribute. Prior reviews, accepted authority and historical evidence remain untouched.

### Addendum candidate ledger

| ID | Priority / category | Evidence, trigger, expected/actual and direction | Independent status |
| --- | --- | --- | --- |
| INT-DOC-001 | P2 / ARCH | At [9473e8b architecture:180](https://github.com/paragon-ux/Patch-DIFF/blob/9473e8bdfc64ae2c2630146af53e2c3428f1ca55/docs/MODERNIZATION_ARCHITECTURE.md#L180), the revised typed-decoder bullet explicitly applies strict full-string IDs to both typed-match and legacy submissions. Actual legacy [protocol_validator.py:40-73](https://github.com/paragon-ux/Patch-DIFF/blob/9473e8bdfc64ae2c2630146af53e2c3428f1ca55/backend/app/pdcp/protocol_validator.py#L40-L73) checks nonempty values/uniqueness without the typed regex/64-character bound. Trigger: a valid legacy edit with `change_id = identity_` plus 2,000 stars; the inspected live preview test asserts acceptance and whole-ID fact omission, while the public bullet implies structural rejection. This is a source/test-derived mismatch, not a new reviewer execution. Separate runtime pairing (legacy/tx1 record 0.2.2) from typed ID grammar; retain frozen legacy grammar and all stored identities. Reconcile the related unqualified strict-ID summary in the new product change record. Source reconciliation suffices; do not change runtime grammar to match the prose. | **fixed** after parent independently confirmed source grammar. Architecture fix `60b16da` explicitly separates pairing from typed-only validation and preserves legacy nonempty/unique grammar; related product summary fix `57dd7c4` qualifies historical/current strict IDs as typed. Reviewer independently inspected both exact deltas against typed.py/protocol_validator.py and the giant-ID assertion. No runtime change or test rerun needed for prose closure. |

### ARCH recheck

**Scope/coverage:** Complete for changed authority/tool lists and public contract text; original architecture/source trace retained.

#### P1

None identified within reviewed scope.

#### P2

INT-DOC-001 fixed and independently rechecked through `57dd7c4`; none unresolved.

#### P3

None identified within reviewed scope.

**Verification/gaps:** Source/test comparison establishes the narrow grammar wording mismatch; no runtime change.

**Verdict:** No unresolved findings after source-only correction recheck.

### DOC recheck

**Scope/coverage:** Complete for the listed public cleanup/change-record/setup/evaluation texts; archive byte domain checked.

#### P1

None identified within reviewed scope.

#### P2

No separate candidate; related strict-ID summary belongs to INT-DOC-001.

#### P3

None identified within reviewed scope.

**Verification/gaps:** Guard/admission/recovery limits, line and preview bounds, profile freeze, host ownership and synthetic-only evidence qualifications retained. Fresh run results are intentionally not inferred from new prose.

**Verdict:** No unresolved findings after ARCH correction recheck.

### SKILL recheck

**Scope/coverage:** Complete unchanged inheritance; repository skills unchanged and AGENTS public tool inventory checked.

#### P1

None identified within reviewed scope.

#### P2

None identified within reviewed scope.

#### P3

None identified within reviewed scope.

**Verification/gaps:** Existing guidance remains aligned; no skill deployment execution.

**Verdict:** No findings within reviewed scope.

### MCP recheck

**Scope/coverage:** Complete unchanged adapter/schema/source inheritance plus changed public setup/tool inventory.

#### P1

None identified within reviewed scope.

#### P2

None separately identified within reviewed scope.

#### P3

None identified within reviewed scope.

**Verification/gaps:** Twenty tools, four formats, 13 examples and keyless preview remain accurate. Installed-artifact discovery pending parent smoke.

**Verdict:** No findings within reviewed scope.

### RUN recheck

**Scope/coverage:** Complete unchanged app-tree inheritance plus new public grammar/profile summary.

#### P1

None identified within reviewed scope.

#### P2

No runtime candidate; prose mismatch owned by INT-DOC-001.

#### P3

None identified within reviewed scope.

**Verification/gaps:** Immutable profiles and parser/applier bytes unchanged; no reviewer execution.

**Verdict:** No runtime finding.

### SVC recheck

**Scope/coverage:** Complete unchanged service inheritance and new public semantic summaries.

#### P1

None identified within reviewed scope.

#### P2

None identified within reviewed scope.

#### P3

None identified within reviewed scope.

**Verification/gaps:** Locked recovery/admission, audit/ownership, projection and read observation semantics retained. Fresh lock dependency-stack validation pending parent tests.

**Verdict:** No findings within reviewed scope.

### DB recheck

**Scope/coverage:** Complete unchanged migration/storage/service inheritance plus local Compose integration.

#### P1

None identified within reviewed scope.

#### P2

None identified within reviewed scope.

#### P3

None identified within reviewed scope.

**Verification/gaps:** Loopback publishing agrees with localhost development URLs and does not alter volumes/schema. Alembic configuration uses `%(here)s`; Python migration modules remain within the app namespace. Fresh migration/live tests pending parent.

**Verdict:** No findings within reviewed scope.

### SCRIPT recheck

**Scope/coverage:** Complete unchanged executable evaluation/manual inheritance plus updated command/evaluation prose.

#### P1

None identified within reviewed scope.

#### P2

None identified within reviewed scope.

#### P3

None identified within reviewed scope.

**Verification/gaps:** Exact lock install followed by no-deps editable install is coherent; replacement accounting still carries explicit deterministic oracles and named delimiter exception. No scripts rerun by reviewer.

**Verdict:** No findings within reviewed scope.

### TEST recheck

**Scope/coverage:** Complete source review for changed test dependency range and unchanged test/CI bodies.

#### P1

None identified within reviewed scope.

#### P2

None identified within reviewed scope.

#### P3

None identified within reviewed scope.

**Verification/gaps:** pytest minimum/lock consistently select 9.0.3; CI installs the exact lock. Complete new-environment suite and exact final CI checkout validation remain pending; historical green results are not substituted.

**Verdict:** No source finding; execution gate open.

### DEP recheck

**Scope/coverage:** Complete integration inspection of package metadata/discovery/data, five lock changes and Compose binding; license/advisory merits delegated to release reviewer.

#### P1

None identified within this integration scope.

#### P2

None identified within this integration scope.

#### P3

None identified within this integration scope.

**Verification/gaps:** Package discovery limits distribution to app/app.* and excludes tests; existing namespace discovery covers migrations/env.py and versions modules. Explicit app data includes both non-Python runtime assets found under backend/app: migrations/alembic.ini and migrations/script.py.mako. Runtime code has no other filesystem-resource dependency. Metadata adds readme/license/URLs without altering durable version domains. Installed-wheel contents/imports/stdio/health and dependency consistency remain parent-owned execution checks.

**Verdict:** Integration source clear; artifact execution pending.

**Addendum disposition:** INT-DOC-001 is independently fixed/rechecked through `57dd7c4`. The related release-review correction in `60b16da` now enumerates all current/historical runtime pairings in the build map; reviewer compared it with versions.py and service dispatch. These two correction commits change only documentation paths already inventoried above. Read-only Git comparison confirms `9473e8b..57dd7c4` changes no app, metadata, lock, README, LICENSE or Compose bytes. No unresolved integration source finding remains. Package/lock changes still require the fresh verification already assigned to the parent, and exact final head/generated-merge CI remains pending. No merge or publication approval is implied.

## Installed-artifact execution evidence recheck

The parent subsequently executed a separate installed-package smoke workflow, outside the source checkout, from `reproduction/2026-10-22/release/installed-package-smoke.py`. Its JSON and console record are in `installed-package-smoke.json`/`.txt` in the same directory. This reviewer inspected the actual helper assertions and decoded every captured request/response; no product workflow or suite was rerun. The two reviews remain separate and PR11 remains open for review.

**Artifact/source identity:** The wheel is `wheels-9473e8b/patchdiff_mvp-0.1.0-py3-none-any.whl`, built from source revision `9473e8bdfc64ae2c2630146af53e2c3428f1ca55`; independently recomputed SHA-256 is `5b132265d6243a77faec627727b26a71ca20bb90394fcf4040f84ac3ac12fcca`, exactly the captured value. The helper SHA-256 independently matches its recorded digest. All 48 installed app Python files exactly equal their corresponding wheel members. All 48 wheel source files equal the pinned Git source after LF/CRLF conversion; the wheel uses Windows checkout CRLF. Two current worktree modules use LF while their wheel equivalents use CRLF; normalized source is identical. Both migration assets exactly equal current worktree files. No test package appears in the wheel. The two subsequent source corrections through `57dd7c4` change documentation only, so the wheel is not relabeled as a later build.

**Package boundary exercised:** The helper removes PYTHONPATH/PYTHONIOENCODING/PYTHONUTF8, resolves app from `.venv-release/Lib/site-packages`, checks wheel members against installed files and launches children with the same interpreter from the reproduction directory. It invokes packaged `migrations/alembic.ini` via importlib.resources, with `script.py.mako` present, and successfully upgrades a newly created database through both real migration revisions. This establishes installed package discovery/resource integration rather than relying on an editable source import. Built metadata contains the readme/license information; substantive licensing/advisory review remains the release reviewer's responsibility.

**Captured public behavior:** All 13 raw JSON-RPC request/response pairs have matching IDs and no RPC errors; all 11 tool results have isError=false. Independently decoded discovery advertises 20 tools and 13 examples; this particular smoke checks their inventory, not execution of every example. The earlier schema-bound 13-example workflow remains its separately pinned evidence. This installed workflow previews tx/3, accepts replacement, accepts a span insertion, accepts typed match and accepts legacy PDCP, advancing version 0→4. Repeating the original replacement arguments after those later edits is byte-for-byte the same decoded argument object, recovers the original log/version-1 outcome and complete original facts, and creates no fifth attempt. Line read/export return `!ready 中\n`; SAVE succeeds; replay reconstructs four accepted transactions and all four materialized checks are true. The helper also starts real installed Uvicorn and asserts HTTP 200 for both liveness and readiness, capturing status=ok.

**Fresh reviewer SQL:** A separate connection to `patchdiff_release_package_20261022` used `default_transaction_read_only=on` and verified `SHOW transaction_read_only` returned `on`. Target `ca1cefbd-9fd6-41ff-9b24-2f2093370973` independently matches content `!ready 中\n`, version 4 and SHA-256 `1549dda3c53251a0403169fb7e789cc74e7eb5cc3ba91553cf1989bba4ddaab4`. Exactly four accepted attempt rows retain tx/3→0.4.0, tx/2→0.3.0, tx/1→0.2.2 and legacy→0.2.2, with four ledger rows. This is a new read-only observation, distinguished from the parent's executed workflow and captured SQL.

**Affected category evidence update:** MCP, RUN, SVC, DB and DEP source conclusions remain clear; the installed artifact now supplies the previously missing import/resource/migration/stdio/health evidence. TEST evidence remains distinct from this manual workflow and is pinned in the following completion record. No new candidate defect was identified and no merge/publication approval is implied.

## Final local verification provenance — 57dd7c4

The parent completed the source suite at `57dd7c44b7fbd2e421abaa087591526f0de7037c`, using the worktree's `.venv-release/Scripts/python.exe` (Python 3.11.9, Windows/MSC v.1938 AMD64), pytest 9.0.3 and all 40 exact corrected lock dependencies. `PYTHONPATH=.;backend` selects checkout sources for this suite despite the corrected noneditable wheel also being installed. The newly created `patchdiff_release_suite_20261022` database was migrated to head before execution. This source-suite execution is separate from the earlier installed-wheel smoke pinned to `9473e8b`.

Reviewer independently parsed `reproduction/2026-10-22/release/final-suite-junit.xml`: **1,144 cases = 755 unit + 389 live integration; zero failures, errors or skips; 131.020 seconds**. `final-suite.txt` reaches 100% and preserves ten warnings: nine Alembic path_separator deprecations plus one Starlette TestClient/httpx deprecation. Populated migration preservation/refusal and actual stdio cases are included in the suite; no warning is represented as a failed case or hidden result. No reviewer suite rerun occurred.

Reviewer inspected `offline-final.txt`: historical shared-applier verdict equivalence passes with only its named legacy delimiter-collision exception, and all five accepted tx/3 content/hash oracles pass. Replacement record/full-request byte pairs remain 290/341, 290/341, 287/338, 308/359 and 2435/2486. These measurements do not establish transport timing, model success or representative workloads.

A narrow reviewer dependency consistency check against the actual `.venv-release` interpreter reports **No broken requirements found**. Independently compared all 40 installed locked distributions to requirements.lock: no version mismatch. The current lock's exact Windows worktree SHA-256 is `58ad0b6ba179bf7e810227dfedd8aaf55f0e7d7a7dbdbf8438c0052c2b79a029`; Python 3.11.9 and pytest 9.0.3 were independently queried. This check evaluates installed dependency consistency, not security-advisory completeness, which remains the release reviewer's evidence domain.

**Current integration disposition:** All ten categories retain reviewed source coverage; INT-DOC-001 is fixed and independently rechecked. Complete fresh-lock source verification, offline oracles and separate installed-package/manual/SQL evidence are now available at their actual pins. No unresolved integration candidate remains. The evidence/report commit will create a later head, so exact published head/generated-merge CI checkout validation remains pending and is not inferred from this green local run. PR11 remains open; user merge authorization and publication authorization remain separate.
