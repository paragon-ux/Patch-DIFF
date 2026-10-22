# Goal F Pass A independent review

Date: 2026-10-21. Reviewer: `/root/f01_independent_review`, inherited/default model; no role override, subagents or product edits. Standard: `docs/PR_REVIEW_STANDARD.md` v1.1.0. Repository: `paragon-ux/Patch-DIFF`; branch `feature/goal-f-rejection-context`; PR/CI: not yet available for this snapshot.

- Base: `2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10`.
- Initial reviewed source: `46bd2938977b3992e6009187370df36649655810`.
- Narrow correction recheck: taxonomy `afdd80bcf3ba3b16e0ce6538c4a04a02b3d76590`, then skill reconciliation `154ab7a97c74775e8f7ff205f00ecc1a5e5d7eab`.
- Reused foundation: F01 `128f59d869453b8044500f30a835dacb624afc84`, reviewed in [Goal-F-F01-128f59d-review.md](Goal-F-F01-128f59d-review.md), committed with records at b62c7af.

All ten material categories are covered. The two initially reported candidates and one related existing instruction qualifier are independently confirmed and closed by the narrow deltas below. No product correctness blocker remains within reviewed scope. This is a source/delta review with explicit execution limits; actual final-head/generated-merge CI and separate user merge approval remain required. The first full suite was not green, and is never represented as such.

Scope follows the user-authorized consolidated cadence: F01 foundation plus F03/F05/F06/F07; F02/F04 remain deferred. No Pass B or unrelated Goal G approval is implied. The parent expressly authorized this new unprotected review path; no supplied/protected review or other agent-owned file was edited. No commit/push/merge, implementation change, broad test rerun or subdelegation was performed by this reviewer.

## Evidence reuse and changed-file inventory

The 2ee7ce4→46bd293 comparison has 76 changed paths, with 43 paths changed since F01. All 33 foundation inventory paths not touched by that delta were compared by Git blob ID and are identical to 128f59d. Thus the F01 category review, source/evidence provenance and historical CI distinctions carry forward only for unchanged material; affected core/MCP/service/docs/skills/tests were independently reviewed anew. In particular `backend/app/core/result.py` remains blob `fd002ab76d7c4ea56a2dd35047abffa7eeb3acc7`. Historical logs were not redundantly reread as new feature evidence.

The exact initial-head inventory follows. Categories are primary ownership, with cross-category dependencies covered below. The narrow correction adds `backend/tests/unit/test_failures.py` (TEST) to the base comparison and re-edits the already-listed persistence skill (SKILL): 77 unique paths through 154ab7a. Root-generated PASS-A XML/text/manual artifacts were untracked supplemental TEST evidence when inspected, outside the initial 76-path tree.

| Category | Path |
| --- | --- |
| SKILL | `.agents/skills/patchdiff-core-runtime/SKILL.md` |
| SKILL | `.agents/skills/patchdiff-mcp-orchestration/SKILL.md` |
| SKILL | `.agents/skills/patchdiff-persistence-replay-save/SKILL.md` |
| SKILL | `.agents/skills/patchdiff-testing-review/SKILL.md` |
| ARCH | `AGENTS.md` |
| RUN | `backend/app/core/diagnostics.py` |
| RUN | `backend/app/core/failures.py` |
| RUN | `backend/app/core/result.py` |
| RUN | `backend/app/core/validity.py` |
| RUN | `backend/app/core/versions.py` |
| MCP | `backend/app/mcp/external_adapter.py` |
| MCP | `backend/app/mcp/tools.py` |
| RUN | `backend/app/pdcp/applier.py` |
| RUN | `backend/app/pdcp/models.py` |
| RUN | `backend/app/pdcp/operations.py` |
| SVC | `backend/app/services/near_miss_service.py` |
| SVC | `backend/app/services/pdcp_service.py` |
| SVC | `backend/app/services/rejection_context.py` |
| DB | `backend/app/services/replay_service.py` |
| TEST | `backend/tests/integration/test_conflict_audit_live.py` |
| TEST | `backend/tests/integration/test_invalid_input_unicode_live.py` |
| TEST | `backend/tests/integration/test_mcp_tools.py` |
| TEST | `backend/tests/integration/test_pass_a_flow.py` |
| TEST | `backend/tests/integration/test_rejection_context_flow.py` |
| TEST | `backend/tests/unit/test_invalid_input_unicode.py` |
| TEST | `backend/tests/unit/test_pass_a_diagnostics.py` |
| TEST | `backend/tests/unit/test_pass_a_operations.py` |
| TEST | `backend/tests/unit/test_rejection_context.py` |
| DOC | `docs/DATA_MODEL.md` |
| DOC | `docs/HOST_INTEGRATION_GUIDE.md` |
| DOC | `docs/MCP_FIRST_MVP.md` |
| DOC | `docs/MCP_TOOLS.md` |
| ARCH | `docs/MODERNIZATION_ARCHITECTURE.md` |
| DOC | `docs/MODERNIZATION_CHANGE_DOC.md` |
| DOC | `docs/PATCHDIFF_CORE_SPEC.md` |
| DOC | `docs/PDCP_FORMAT.md` |
| DOC | `docs/reviews/Goal-F-F01-128f59d-review.md` |
| DOC | `docs/usability/BASELINE-and-evidence-closures.md` |
| TEST | `docs/usability/BASELINE-junit.xml` |
| TEST | `docs/usability/BASELINE-live-results.json` |
| SCRIPT | `docs/usability/BASELINE-live-verify.py` |
| TEST | `docs/usability/BASELINE-manual.txt` |
| TEST | `docs/usability/BASELINE-offline.txt` |
| TEST | `docs/usability/BASELINE-suite.txt` |
| ARCH | `docs/usability/EXECUTION-PLAN.md` |
| ARCH | `docs/usability/F01-decision.md` |
| TEST | `docs/usability/F01-junit.xml` |
| TEST | `docs/usability/F01-live-results-development.json` |
| TEST | `docs/usability/F01-live-results.json` |
| SCRIPT | `docs/usability/F01-live-verify.py` |
| TEST | `docs/usability/F01-manual.txt` |
| TEST | `docs/usability/F01-offline.txt` |
| TEST | `docs/usability/F01-suite.txt` |
| DOC | `docs/usability/F01-verification.md` |
| DOC | `docs/usability/GEMINI-v1-v2-REVIEW.md` |
| TEST | `docs/usability/GEMINI-v2-evidence-check.json` |
| SCRIPT | `docs/usability/GEMINI-v2-evidence-check.py` |
| ARCH | `docs/usability/PASS-A-decision.md` |
| SCRIPT | `docs/usability/PASS-A-live-verify.py` |
| ARCH | `docs/usability/accepted/AUTHORITY.json` |
| ARCH | `docs/usability/accepted/DEVIN_CHANGE_PLAN-b33faaf-v2.md` |
| ARCH | `docs/usability/accepted/Devin-Goal-F.md` |
| DOC | `docs/usability/integration/CONSOLIDATION_RECHECK.md` |
| TEST | `docs/usability/integration/PR-1-CI-39663238218.txt` |
| TEST | `docs/usability/integration/PR-10-CI-39663057668.txt` |
| TEST | `docs/usability/integration/PR-5-CI-39661605566.txt` |
| TEST | `docs/usability/integration/PR-6-CI-39569958566.txt` |
| TEST | `docs/usability/integration/PR-6-CI-39662203586.txt` |
| TEST | `docs/usability/integration/PR-7-CI-39662500697.txt` |
| TEST | `docs/usability/integration/PR-8-CI-39662684583.txt` |
| TEST | `docs/usability/integration/PR-9-CI-39662879868.txt` |
| TEST | `docs/usability/integration/merge-ledger-attempt1.json` |
| TEST | `docs/usability/integration/merge-ledger-attempt2.json` |
| TEST | `docs/usability/integration/merge-ledger-attempt3.json` |
| TEST | `docs/usability/integration/merge-ledger.json` |
| SCRIPT | `docs/usability/integration/merge_stack.py` |

## Architecture-to-implementation trace

The original paper distinguishes authoritative canonical state, advisory context and uncommitted sequential simulation. Current AGENTS/A1–A8/C1–C6 preserve trusted deterministic validation, host-owned retries, exact evidence, immutable audit/replay and transaction ownership. Accepted Goal F revision 2 plus EXECUTION-PLAN/PASS-A-decision authorize the explicit span extension with a new durable format/profile, not a reinterpretation of old coordinates or old records.

F07 builds tx/2 records, validates/lower both explicit operations into ParsedPDCP and uses the existing applier/lock/persist/ledger route. Span expected_text is compared exactly against its sequential canonical slice; guards remain mandatory. 0.3.0 enables spans while 0.2.2 and older profiles keep frozen semantics. Replay dispatches on stored format/profile and fails closed for incompatible tx/2 history. F03 wraps terminal results with invocation metadata outside identity. F06 captures bounded original exact candidates before losing the failing buffer. F05 persists bounded original query/prefix then compares only after actual owned commit/lock release, or omits for the caller-owned lifetime. The tests/manual assertions exercise those connected guarantees and exact identity rather than merely checking response-field presence.

## Candidate finding ledger and independent closure

| ID | Priority / category | Evidence, trigger and required behavior | Independent triage and closure |
| --- | --- | --- | --- |
| TEST-A1 | P2 / TEST; closed | At 46bd293, `backend/tests/unit/test_failures.py:9` omitted the two newly required span rejection values from its exact inventory. Core failures/validity/contracts intentionally add them. Full-suite XML observed this sole failure, blocking the required green check. Keep complete taxonomy coverage and add the two expected labels. | Root independently confirmed. afdd80b changes only those two expected values; reviewer inspected the exact delta. PASS-A-recheck XML/text shows all three taxonomy tests passed in 0.08s at that fix. Existing new live cases assert both actual span failure reasons/stages. Closed without broad local repeat; final CI remains required. |
| SKILL-A1 | P3 / SKILL; closed | At 46bd293, `.agents/skills/patchdiff-persistence-replay-save/SKILL.md:61` listed only current 0.2.2/historical 0.1.0 despite adding tx/2 to the adjacent protocol list. This could guide an implementer to record/replay the wrong profile. State tx/2→0.3.0, current old tools→0.2.2 and retained historical profiles; reconcile content representation. | Root independently confirmed. 154ab7a now names every supported profile/format pairing and tx/2/invalid-text content representation. Reviewer reconciled with `_runtime_version`, decode dispatch and versions.py. Source-only correction; no product test required. |
| SKILL-A2 | P3 / SKILL; closed; related qualifier | The adjacent existing “Every submission … creates an append-only row” guidance was unqualified, contradicting C1/C4, explicit pre-admission flag errors, unlinked targets, keyed recovery and caller rollback/infrastructure ownership. Qualify admitted known-target terminal rows and actual durability boundaries. | Root identified and independently changed this in 154ab7a; reviewer separately confirmed against decorator admission, shared submit early returns, keyed reconstruction and `_transaction` ownership. The new wording covers these boundaries accurately. This is an existing instruction defect reconciled in affected scope, not a newly introduced runtime bug. |

Immutable source references: [initial test](https://github.com/paragon-ux/Patch-DIFF/blob/46bd2938977b3992e6009187370df36649655810/backend/tests/unit/test_failures.py#L9), [initial skill](https://github.com/paragon-ux/Patch-DIFF/blob/46bd2938977b3992e6009187370df36649655810/.agents/skills/patchdiff-persistence-replay-save/SKILL.md#L57), [taxonomy correction](https://github.com/paragon-ux/Patch-DIFF/commit/afdd80bcf3ba3b16e0ce6538c4a04a02b3d76590), [skill correction](https://github.com/paragon-ux/Patch-DIFF/commit/154ab7a97c74775e8f7ff205f00ecc1a5e5d7eab). These are local verified Git revisions; this report does not claim the commits have been published remotely.

The findings have distinct causes: exact test-inventory maintenance and incomplete instruction reconciliation. No duplicate runtime finding was created. No P1 was identified and no quota was applied. Root triage and reviewer recheck are separate; final source conclusions include the two-file correction delta rather than assuming a fix commit closes itself.

## ARCH — Architecture and contracts

**Scope/Coverage:** Complete: AGENTS, architecture, accepted authority, both decisions and execution cadence; original design thesis and C1–C6 carried forward from the F01 review. Traced explicit spans against the original paper’s stale-coordinate concern: mandatory guard plus exact canonical expected_text makes the new operation a guarded sequential state transition. F02/F04 stay deferred; F09/replace_all and discovery examples remain Pass B.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

**Verification:** Profile 0.3.0 is explicit and immutable; old submit tools still select 0.2.2. Span grammar, mixed sequencing, insertion/deletion, diagnostics budgets, post-commit timing and caller ownership are recorded before production changes. No current external ecosystem assertion is needed.

**Gaps/limits:** No unreviewed architecture category remains. Future Pass B and any later product delta need their own review.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## DOC — Documentation and change records

**Scope/Coverage:** Complete: all changed active data/core/format/MCP/host/MVP/as-built documents, new F01 verification record, execution plan and decisions. Original F01/historical evidence is carried forward only where blob-identical. Reconciled new tool, fields, profile/format names, bounds, omission reasons and qualified evidence claims with code.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

**Verification:** F01 verification accurately pins its earlier source rather than claiming a later execution. The initial Pass A full run is recorded below as failing, not green; the subsequent correction is isolated. No native-host, token, model-success or comparative timing claim is accepted.

**Gaps/limits:** Final published verification/as-built status and actual head/generated-merge CI remain root-owned follow-up evidence.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## SKILL — Skills and agent instructions

**Scope/Coverage:** Complete: four repository skills and connected AGENTS changes. Verified real APIs/enums, shared pipeline, current and historical profiles, response-only correlation, byte/work budgets and transaction ownership. Reviewed final 154ab7a persistence-skill delta in addition to the 46bd293 baseline.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
SKILL-A1/SKILL-A2 closed as recorded in the ledger; none unresolved.

**Verification:** SKILL-A1 and related SKILL-A2 are independently confirmed and closed with source reconciliation below. Final guidance explicitly maps tx/2 to 0.3.0, old tools to 0.2.2, historical profiles, tx/2 canonical content and invalid-text evidence, plus qualified admission/recovery/rollback semantics.

**Gaps/limits:** No installed third-party skill-loader test was rerun; no loader deployment was changed or claimed.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## MCP — MCP schemas and public API

**Scope/Coverage:** Complete: both changed MCP modules, three submit handlers, response serializer, discovery/schema generation, and existing registry/transport dependencies. Inspected required guards, op-discriminated item schema, integer ranges, nullability, invalid response-option boundary and x-patchdiff-capabilities.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

**Verification:** Boolean correlation is optional/default false and UUIDv4 metadata is absent when disabled. It never enters the durable record/fingerprint/key. Actual subprocess test/manual assertions exercise discovery, guarded operations, correlation, errors, immutable rejection recovery, SAVE/replay/export and SQL effects. Reviewer independently decoded the captured wire and asserted semantics and budgets.

**Gaps/limits:** End-before-start is correctly a service cross-field rule. No new executable tools/list examples or native-host/model trial is claimed; F12 remains Pass B.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## RUN — Core runtime, parsing and validation

**Scope/Coverage:** Complete: diagnostics, failure/validity/profile tables, applier, models and tx/2 parser/lowering; connected typed/legacy validators, exact matching and disambiguation. Checked strict span fields/types/bounds, expected text, newline/code-point semantics, mixed sequential application, zero-length insertion and no partial rejected facts.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

**Verification:** New 0.3.0 enables spans explicitly; older profiles retain original overlap/selector behavior and refuse tx/2 decoding. Default legacy/v1 application remains match-only. Exact candidates capture first five existing enumerated occurrences without selector auto-choice; near query is raw-length bounded and canonicalized. Pure tests assert Unicode, empty/EOF insertion, deletion, shifted/overlapping sequential spans, structural/applicability stages and frozen-profile refusal.

**Gaps/limits:** No reviewer broad runtime-test rerun. Inspected focused/live and root final-run evidence rather than infer correctness from test names.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## SVC — Services, orchestration and audit semantics

**Scope/Coverage:** Complete: decorator/three entry points, shared submit/persist/recover path, bound builders and near-miss service. Reviewed actual commit-return boundary, owner detection, original diagnostic preservation, request identity, lineage, safe Unicode, final guard and acceptance/ledger path.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

**Verification:** Near comparison follows successful owned transaction exit; caller-owned sessions return caller_transaction before comparison and keep locks/commit ownership. Query/prefix are immutable original evidence; historical omissions are explicit. DP cells cap at 1,000,000, widths are bounded, ties sort deterministically, partial rankings are discarded on exhaustion, and output truncation only removes trailing candidates. Unexpected post-commit exceptions propagate without another persistence attempt. Correlation stays outside identity.

**Gaps/limits:** Public live tests still call decorated APIs for Unicode persistence/recovery, including nested unsafe keys and legacy metadata; __wrapped__ is limited to white-box tests whose mocked persistence returns kwargs rather than SubmitPDCPResult. No functional protection was removed by that adaptation.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## DB — Database, migrations, replay and concurrency

**Scope/Coverage:** Complete: changed replay dispatch and connected row-lock repository, models, append-only persistence and existing migration boundaries. No migration/schema change; accepted tx/2 uses typed ledger origin and span facts. Replay dispatch validates the durable protocol/profile pair before applier execution.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

**Verification:** Mixed legacy/v1/v2 replay, tx/2 old/unknown-profile refusal, persisted identities/facts, one-attempt rejections and owner commit/rollback are semantically asserted by live tests. Manual probe checks a second connection can acquire the target lock and see committed rejection at actual near-comparison entry, and NOWAIT fails while caller ownership remains. Reviewer independently read fresh SQL for the captured public scenario.

**Gaps/limits:** No reviewer migration or two-session probe rerun and no representative production-data rehearsal. Existing populated migration/refusal tests ran in the root full run; there is no new migration requiring one.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## SCRIPT — Scripts, evaluation and developer tooling

**Scope/Coverage:** Complete for new PASS-A-live-verify.py and carried-forward helper provenance. Reviewed persistent raw-UTF8 client, bounded response wait, source hashes, independent SQL, combined enrichment serialization, staged workflow assertions and scoped diagnostic-entry lock probe.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

**Verification:** Captured manual record pins 46bd293 and all 47 product/helper source hashes match. The probe restores the production function and calls its real comparison; committed visibility and lock availability are asserted before it. Caller omission is checked with a separate locking connection and rollback. Offline output at afdd80b reports shared-applier equivalence OK with the named legacy delimiter exception.

**Gaps/limits:** Historical merge/Gemini/baseline helpers and CI were not rerun. Their hashes and prior review applicability were checked instead; no unrelated Goal G review was reopened.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## TEST — Tests and CI

**Scope/Coverage:** Complete: three new test files, affected existing helper/mock/tool-inventory tests, exact source artifacts, root suite results and narrow taxonomy fix. Inspected all 103 new cases (50 pure, 53 PG/stdio) for assertions rather than relying on names/counts. Terminal helper comparisons exclude near_misses/correlation only as response metadata; original diagnostic equality remains.

### P1
None identified within reviewed scope.

### P2
TEST-A1 closed as recorded in the ledger; none unresolved.

### P3
None identified within reviewed scope.

**Verification:** TEST-A1 is independently confirmed from both source and the full-run XML, then closed at afdd80b with the exact expected-label fix and three passing taxonomy tests. Root full run at 46bd293 collected 1005 = 685 unit + 320 integration: 1004 passed, one taxonomy failure, nine warnings, 120.14s. No green full-run claim is made. The narrow correction changes only the test expectation; final CI must still establish the required green full suite.

**Gaps/limits:** Reviewer did not rerun the broad suite or already-proved matrices. No Pass A final-head/generated-merge CI was available at this review snapshot; merge approval is not recommended from this report alone.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck. Required final CI evidence is pending.

## DEP — Dependencies, packaging and configuration

**Scope/Coverage:** Complete for affected scope: no dependency/lockfile/startup/configuration change. Existing Python >=3.11 packaging, CI, Postgres transaction assumptions, service imports and external adapter configuration remain applicable. Additions use existing standard-library/dataclasses/json facilities.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

**Verification:** 47-product/helper source hashes in manual execution match reviewed sources; 46bd293→154ab7a contains no backend/app change, so manual product execution remains directly applicable. Parent/root owns Git/CI and no review operation changed installation or configuration.

**Gaps/limits:** No new installation or cross-platform deployment test was run or claimed; unchanged packaging has no newly introduced verification requirement.

**Verdict:** No unresolved findings within reviewed scope after narrow correction recheck.

## Verification record and overall disposition

Reviewer-executed checks were read-only: exact source/base and path/blob comparison; manual product/helper SHA-256 comparison (all 47 match); independent assertions over the 19 captured JSON-RPC events, including 17 public tool calls; fresh read-only SQL for manual target `798df186-1578-471d-8314-6f2fbb8192a9`; source/record comparison for the two correction commits. No product workflow, broad pytest matrix or lock probe was rerun by the reviewer.

The independent captured-wire assertions verified actual exact-candidate spans, original diagnostic and near-miss recovery equality, fresh observed version 1→2, UUIDv4 values and disabled omission, and the 18,432-byte combined enrichment bound. Fresh SQL exactly matched final content/hash/version 2, seven attempts and four accepted ledger facts, including the immutable original missing-match diagnostic. The stored original versus fresh response observations remain distinct. The manual helper's separate probe asserts actual committed visibility and NOWAIT acquisition at comparison entry, then caller lock retention, omission and rollback; its two observations are recorded explicitly.

Inspected root execution:

- F01 foundation: 902 pass at 128f59d, preserved as its own evidence.
- Pass A focused development: 391 distinct cases reported, including 103 new cases; these are not inflated by summing overlapping reruns.
- Pass A complete suite at 46bd293: **1004 passed, 1 failed, nine warnings, 120.14s**; XML has 1005 cases, 685 unit/320 integration, sole TEST-A1 failure, no skip/error. This is not a green final suite.
- Taxonomy-only correction at afdd80b: **3 passed, 0.08s**; offline evaluator reports shared-applier equivalence OK, retaining its named legacy delimiter exception and bytes-only limits.
- Actual persistent raw-UTF8 public-stdio/manual run at 46bd293: seven assertion groups, independent SQL and scoped separate-connection lock proof. All 47 recorded product/helper digests match. The 46bd293→154ab7a delta changes only test expectations and skill prose, with no `backend/app` change.

Source inspection, reviewer read-only checks, root local execution and historical CI are intentionally distinct. At this snapshot no actual Pass A head/generated-merge CI was inspected. The report therefore recommends no merge/CI approval yet, even though all material source categories are reviewed and all candidate findings are closed. Root should retain the initial failed suite and narrow passing correction as an honest evidence chain, then attach actual green CI for the final head/merge tree. Later product changes require affected source review/testing; test/prose-only corrections do not justify repeating already-proved product scenarios locally.
