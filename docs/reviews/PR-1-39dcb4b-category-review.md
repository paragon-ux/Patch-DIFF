# PR #1 — Category-separated second review

Review standard: 1.1.0  
Review date: 2026-10-20  
PR: https://github.com/paragon-ux/Patch-DIFF/pull/1  
Base: 0c75c4054b5da01eb56c53ce5579c74014270f3a  
Head reviewed: 39dcb4b049a030dc15b96b8672ee3236e4e99c7e  
Disposition: REQUEST CHANGES  
Coverage: PARTIAL; this report is not a whole-PR approval.

## Evidence and limits

This report reorganizes and rechecks the earlier second-review findings, then adds specific gaps found while inspecting the category contracts. It is not an endorsement of the initial approval.

Sources examined include the current architecture and change records, AGENTS.md, all four repository skill files, MCP schema/adapter/tool paths, submission/validation/replay paths, migration/model excerpts, evaluation code, selected tests, and CI logs. File-level coverage is recorded below. Referenced failure triggers are source-derived unless explicitly identified as executed CI.

No local reproduction or new product test execution was possible: the execution environment was unavailable. The attached transcript was not accessible in this pass. No conclusion here depends on its contents. The original paper and external-tool comparison were not independently re-reviewed in this pass; architecture claims about them remain outside this review's coverage. Normative current contracts are used as the implementation baseline, not as proof that every architectural choice was justified.

The CI run associated with the reviewed head is [run 39472831144](https://github.com/paragon-ux/Patch-DIFF/actions/runs/39472831144), job 118801047553. Its checkout log identifies GitHub's generated merge commit cb33b18d4c0ae4be665c198b46e129d08ee166af, combining this head with the recorded base. It is not direct execution of the head SHA. The log records 174 unit tests passed, 89 integration tests passed, and offline verdict equivalence OK. Those results are real evidence for those checks and that tested revision; they do not establish the missing cases below.

## Coverage and category verdicts

| Category | Coverage | Own findings | Verdict |
| --- | --- | --- | --- |
| ARCH — Architecture and contracts | Current contract excerpts inspected; original-paper and external-norm provenance not re-reviewed | ARCH-001 | Changes required; partial |
| DOC — Documentation | Host recovery and relevant active contract/change-record excerpts inspected; entry/setup docs not all re-reviewed | DOC-001 | Changes required; partial |
| SKILL — Skills and instructions | All four skills and AGENTS.md inspected for contract coherence | SKILL-001 | Changes required within inspected scope |
| MCP — Schemas and public API | Typed item schema, schema advertising, dispatch, and relevant tool paths inspected | MCP-001 | Changes required; other tool schemas not exhaustively checked |
| RUN — Runtime, parsing, validation | Typed edit parsing and legacy protocol/stage paths inspected | RUN-001, RUN-002 | Changes required; partial |
| SVC — Services and audit semantics | Submission, lineage, attempt propagation, and guard paths inspected | SVC-001, SVC-002 | Changes required; other services not exhaustively checked |
| DB — DB, migrations, replay, concurrency | Replay read/check boundary, engine configuration, model and migration paths inspected | DB-001 | Changes required; populated migration execution unverified |
| SCRIPT — Scripts and evaluation | Offline evaluation and its README inspected | SCRIPT-001 | Changes required |
| TEST — Tests and CI | CI source/logs and selected relevant assertions inspected | No additional production defect asserted; explicit gaps below | Incomplete verification |
| DEP — Dependencies, packaging, configuration | Changed-file inventory only for packaging and lockfile | No findings asserted | Not reviewed; cannot approve |

## Architecture-to-implementation trace

| Architecture obligation | Implementation boundary | Review result |
| --- | --- | --- |
| C1 — typed schema and runtime agreement | typed.py and MCP tools/list | MCP-001; RUN-001 |
| C2 — stage accuracy and safe lineage | protocol validator, submit service, instruction skill | RUN-002; SVC-001; SVC-002; SKILL-001 |
| C3 — replay and materialized-state health | replay service and DB read boundary | DB-001 |
| C4 — request identity and outcome recovery | client_request_id versus version/hash guards | DOC-001 |
| C5 — migration and history preservation | migration 0002 and live DB checks | Source inspected; populated migration evidence gap |
| C6 — bounded authoritative reads | read service defaults and cap | ARCH-001 |
| A8 — honest offline evaluation | verdict-equivalence oracle | SCRIPT-001 |

The findings below concern distinct broken or inconsistent obligations. They are not evidence that the deterministic-service / host-owned-planning boundary should be discarded.

## ARCH — Architecture and contracts

**Scope:** MODERNIZATION_ARCHITECTURE.md, relevant service contracts and current bounded-read implementation. **Coverage:** partial.

### P1 — High priority

None identified within reviewed scope.

### P2 — Medium priority

### ARCH-001 — P2 — The bounded-read implementation contradicts the locked C6 contract

- **Provenance:** [docs/MODERNIZATION_ARCHITECTURE.md:159–162](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/MODERNIZATION_ARCHITECTURE.md#L159-L162) specifies default 4,000 characters and maximum 8,000. AGENTS.md places this architecture above implementation descriptions.
- **Evidence and trigger:** [backend/app/services/read_service.py:19–46](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/read_service.py#L19-L46) uses MAX_READ_CHARS = 20,000 and defaults an omitted length to that maximum. Read a target longer than 20,000 characters with length omitted; the implementation selects 20,000, rather than the specified 4,000. A request for 20,000 also exceeds the specified 8,000 cap.
- **Impact:** hosts cannot rely on the documented context budget. The claimed locked contract and as-built behavior disagree.
- **Required remediation:** honor C6's 4,000 default and 8,000 cap, with separate default/max constants. If those limits are intentionally being revised, record and justify that contract change before changing runtime; do not silently treat the existing implementation as the decision.
- **Acceptance evidence:** a sufficiently long target returns 4,000 characters by default; an oversized request returns at most 8,000; end, truncated, and next_start match the actual slice. Reconcile active docs and tests against the selected contract.
- **Reasoning:** this is a measurable contract mismatch, not a preference for smaller responses. No claim is made that 8,000 is universally optimal.
- **Status:** open; source-derived.

### P3 — Low priority

None identified within reviewed scope.

**Category verdict:** changes required. The paper-to-modernization rationale and vendor claims still need a separate provenance audit before whole-category sign-off.

## DOC — Documentation and change records

**Scope:** host recovery guidance and linked C4/submission behavior. **Coverage:** partial.

### P1 — High priority

None identified within reviewed scope.

### P2 — Medium priority

### DOC-001 — P2 — Manual lost-response recovery overstates the protection of an old guard

- **Provenance and evidence:** [docs/HOST_INTEGRATION_GUIDE.md:97–113](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/HOST_INTEGRATION_GUIDE.md#L97-L113) says a verbatim retry with the old guard cannot apply twice. The typed contract permits a hash-only guard; legacy guards are optional. C4 separately provides request-ID deduplication.
- **Trigger / actual:** omit client_request_id, use only expected_current_hash, and submit a no-op replacement such as match="a", replace="a" against target "a". The accepted transaction increments version but preserves the hash. The same hash-only request can be accepted again. An ABA history also restores a previously used hash.
- **Impact:** host authors may mistake a state precondition for request identity, creating duplicate accepted history or repeating an edit after an ABA transition.
- **Required remediation:** qualify the old-guard claim to a monotonically advancing version guard. Explain that a hash-only guard is not request deduplication; recommend preserving the same client_request_id for transport retries. State the separate legacy behavior. Do not describe a one-version advance or a newest-five-log sample as proof of request identity.
- **Acceptance evidence:** the guide distinguishes request IDs, version guards, and hash guards, including no-op/ABA cases. Retain the existing keyed recovery tests; add or explicitly cite the unkeyed counterexample when verifying the claim.
- **Reasoning:** the implementation's keyed mechanism can be correct while the fallback instructions remain unsafe.
- **Status:** open; source-derived. Corresponds to earlier second-review finding 5.

### P3 — Low priority

None identified within reviewed scope.

**Category verdict:** changes required. This is not a sign-off on every active guide.

## SKILL — Skills and agent instructions

**Scope:** AGENTS.md and all four .agents/skills/patchdiff-*/SKILL.md files. **Coverage:** source review of their current instructions; commands not executed.

### P1 — High priority

None identified within reviewed scope.

### P2 — Medium priority

None identified within reviewed scope.

### P3 — Low priority

### SKILL-001 — P3 — The core skill teaches validation stages absent from the contract and runtime

- **Provenance:** C2 names PRECONDITION_GUARD, PROTOCOL_VALIDATION, TRANSACTION_APPLICABILITY, COMMIT_GUARD, and ACCEPTED, with nullable unreached-stage validity.
- **Evidence:** [.agents/skills/patchdiff-core-runtime/SKILL.md:114–129](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/.agents/skills/patchdiff-core-runtime/SKILL.md#L114-L129) instead lists PROTOCOL_DECODE, TARGET_RESOLUTION, CONCURRENCY_GUARD, MATCH_RESOLUTION, and SEQUENTIAL_SIMULATION, and describes protocol_valid / transaction_valid only as booleans. Compare [backend/app/core/validity.py:33–40](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/core/validity.py#L33-L40) and its stage handling.
- **Trigger / impact:** an agent following the skill can reference nonexistent enum members or flatten unreached stages into false. This undermines architecture-first remediation.
- **Required remediation:** reconcile that skill section to C2's exact names and null/false/true meanings. Distinguish informal algorithm phases from the actual ValidationStage enum if both are retained.
- **Acceptance evidence:** source reconciliation against C2 and the enum. No extra test is necessary merely to check prose.
- **Reasoning:** instructions are an implementation input and deserve review independently from runtime.
- **Status:** open; lower-priority instruction defect, not a demonstrated production failure.

**Process gap addressed by the proposed standard:** the testing skill's current completion example at lines 75–91 reports paths and aggregate test counts. It does not provide category coverage, finding provenance, or closure evidence. That example is useful for implementation updates; AGENTS.md must explicitly require the separate PR review standard. This is a newly requested workflow requirement, not an additional counted product bug.

**Category verdict:** reconcile the inaccurate core skill. Other findings do not become skill findings merely because a skill mentions the affected subsystem.

## MCP — Schemas and public API

**Scope:** typed item schema, schema publication, relevant submission API. **Coverage:** partial.

### P1 — High priority

None identified within reviewed scope.

### P2 — Medium priority

### MCP-001 — P2 — tools/list excludes a null value explicitly accepted by the typed contract

- **Provenance:** C1 at [docs/MODERNIZATION_ARCHITECTURE.md:99–102](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/MODERNIZATION_ARCHITECTURE.md#L99-L102) and [docs/MCP_TOOLS.md:132–139](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/MCP_TOOLS.md#L132-L139) allow change_id=null, defaulting it to the indexed identifier.
- **Evidence:** [backend/app/pdcp/typed.py:74–78](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/pdcp/typed.py#L74-L78) advertises change_id as string only. The parser at [backend/app/pdcp/typed.py:283–286](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/pdcp/typed.py#L283-L286) accepts null. [backend/tests/unit/test_typed_transaction.py:281–283](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/unit/test_typed_transaction.py#L281-L283) explicitly tests that acceptance. The adapter advertises this schema directly.
- **Trigger / impact:** a schema-validating host rejects a documented request containing change_id:null before it reaches a runtime that accepts it.
- **Required remediation:** make change_id nullable in the advertised schema, preserving the documented indexed default. Audit the remaining representable structural constraints for the same schema/runtime drift; do not claim business rules are automatically enforced by Python annotations.
- **Acceptance evidence:** validate omitted, null, valid-string, invalid-string, and invalid-type cases against the actual tools/list item schema and parser. The existing schema test at lines 275–278 checks key sets, required keys, and additionalProperties, not value-domain agreement.
- **Reasoning:** this is an externally visible contract mismatch independently of parser error handling in RUN-001.
- **Status:** open; source-derived.

### P3 — Low priority

None identified within reviewed scope.

**Category verdict:** changes required; other tools' discovery contracts still need coverage.

## RUN — Core runtime, parsing, and validation

**Scope:** typed optional-field parsing and legacy validation/stage propagation. **Coverage:** partial.

### P1 — High priority

None identified within reviewed scope.

### P2 — Medium priority

### RUN-001 — P2 — Unhashable risk input escapes canonical rejection and attempt logging

- **Provenance:** untrusted transactions must be deterministically rejected, with durable rejected-attempt history for a known target.
- **Evidence:** [backend/app/pdcp/typed.py:305–311](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/pdcp/typed.py#L305-L311) performs risk membership in a frozenset without checking its type. [backend/app/services/pdcp_service.py:399–440](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/pdcp_service.py#L399-L440) catches only the domain parse/validation exceptions. The adapter at [backend/app/mcp/external_adapter.py:59–68](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/mcp/external_adapter.py#L59-L68) converts a leaked TypeError into a generic tool error; schema advertising does not validate tool arguments.
- **Trigger / actual:** submit otherwise valid guarded edits with risk:[] or risk:{}. Membership raises TypeError; the normal rejection persistence path is skipped.
- **Impact:** a malformed proposal disappears from the canonical attempt audit and loses format-specific diagnostics.
- **Required remediation:** type-check risk before enum membership and raise the same domain validation error used for invalid risk strings. Keep runtime validation even if transport schema validation is added.
- **Acceptance evidence:** both malformed values through the actual MCP call boundary yield a normal rejected result with a persisted rejected log, typed diagnostics, and unchanged target/version/ledger. The process remains usable.
- **Status:** open; source-derived. Corresponds to earlier finding 2.

### RUN-002 — P2 — A hash error is treated as proof that all protocol validation completed

- **Provenance:** C2/A7 require validity derived from the actual completed stage.
- **Evidence:** [backend/app/services/pdcp_service.py:425–432](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/pdcp_service.py#L425-L432) assigns TRANSACTION_APPLICABILITY to every TARGET_HASH_MISMATCH exception. But [backend/app/pdcp/protocol_validator.py:128–145](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/pdcp/protocol_validator.py#L128-L145) raises that reason for conflicting header/manifest hashes inside validate_pdcp, which iterates changes in order.
- **Trigger / actual:** a two-change PDCP has conflicting valid-format hashes in change 1 and an invalid occurrence_index=0 in change 2. Validation aborts on change 1; change 2 is never validated, yet the service reports protocol_valid=true.
- **Impact:** a host receives false evidence that the entire input satisfied the structural contract.
- **Required remediation:** propagate the actual phase or split structural validation from target applicability checks. Treat header/manifest inconsistency as a protocol-validation failure; reserve applicability classification for the current-target hash check after full structural validation. Do not infer completion from a shared failure code.
- **Acceptance evidence:** multi-fault input reports protocol_valid=false and transaction_valid=null; a fully protocol-valid input whose header hash differs from the target still reports protocol_valid=true and transaction_valid=false. Neither mutates the target.
- **Status:** open; source-derived. Corresponds to earlier finding 3.

### P3 — Low priority

None identified within reviewed scope.

**Category verdict:** changes required.

## SVC — Services, orchestration, and audit semantics

**Scope:** parent validation, retry attempt propagation, and persisted metadata. **Coverage:** partial.

### P1 — High priority

None identified within reviewed scope.

### P2 — Medium priority

### SVC-001 — P2 — Retry lineage accepts an accepted transaction as the rejected parent

- **Provenance:** [docs/MCP_TOOLS.md:143–145](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/MCP_TOOLS.md#L143-L145) defines parent_pdcp_log_id as the rejected parent attempt when retrying.
- **Evidence:** [backend/app/services/pdcp_service.py:978–993](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/pdcp_service.py#L978-L993) checks UUID, existence, and target ownership, but not parent.status.
- **Trigger / actual:** use an accepted log from the same target as the parent of another valid submission. It passes parent validation and is recorded as retry lineage.
- **Impact:** consumers cannot interpret retry chains according to the published contract.
- **Required remediation:** enforce rejected status in the shared parent-validation path. Persist an ordinary context-invalid rejection with a null parent FK when the parent fails validation, matching the existing invalid-parent policy.
- **Acceptance evidence:** accepted same-target parent is rejected and logged; rejected same-target parent succeeds; existing malformed, nonexistent, and cross-target cases remain covered.
- **Status:** open; source-derived. Part of earlier finding 4.

### P3 — Low priority

### SVC-002 — P3 — One-based retry attempt metadata has no value validation

- **Provenance:** MCP_TOOLS.md line 145 defines attempt as one-based.
- **Evidence:** [backend/app/services/pdcp_service.py:163–175](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/pdcp_service.py#L163-L175) forwards attempt to regeneration_attempt, and the shared submit path persists it. [backend/app/storage/models.py:170–181](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/storage/models.py#L170-L181) has an integer column without a positive-value constraint. An int annotation does not enforce a range at runtime.
- **Trigger / actual:** attempt=0 or -1 can be persisted for an otherwise valid request.
- **Impact:** audit metadata violates its own numbering contract; target edits can still be correct.
- **Required remediation:** validate optional attempt as a positive integer, explicitly rejecting booleans. Apply the rule at the shared submission boundary while preserving null as optional; define how malformed metadata is represented in a rejected attempt.
- **Acceptance evidence:** null and positive integers follow the contract; zero, negatives, booleans, and wrong types are cleanly rejected without mutation or raw DB errors.
- **Status:** open; lower-priority metadata issue. Part of earlier finding 4, split because it has a distinct fix.

**Category verdict:** changes required.

## DB — Database, migrations, replay, and concurrency

**Scope:** replay reads/checks, engine configuration, migration 0002 and model excerpts. **Coverage:** partial; no local DB execution.

### P1 — High priority

None identified within reviewed scope.

### P2 — Medium priority

### DB-001 — P2 — Replay health compares database states from different read instants

- **Provenance:** C3 describes materialized_state_matches as integrity evidence for authoritative current state.
- **Evidence:** [backend/app/services/replay_service.py:62–75](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/replay_service.py#L62-L75) loads the target before [backend/app/services/replay_service.py:116–123](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/replay_service.py#L116-L123) separately loads accepted history. [backend/app/services/replay_service.py:212–230](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/replay_service.py#L212-L230) compares the reconstructed history with the previously loaded target. [backend/app/storage/db.py:11–12](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/storage/db.py#L11-L12) specifies no stronger isolation.
- **Trigger / actual:** under PostgreSQL's default READ COMMITTED, session A loads target version N; session B commits N+1; session A reads accepted history including N+1. Its comparison uses the retained N target, producing a false unhealthy result for consistent committed data. PostgreSQL explicitly documents statement-level snapshots and differing successive SELECT results: https://www.postgresql.org/docs/16/transaction-iso.html#XACT-READ-COMMITTED .
- **Impact:** normal concurrent editing can be reported as materialized-state corruption.
- **Required remediation:** first define the replay observation boundary in C3, then ensure target, initial snapshot, and accepted-history reads share that boundary. A dedicated coherent read snapshot or a correctly scoped target lock can implement it; account for SQLAlchemy's identity map and callers with preloaded targets. Do not rely on the existence of a transaction alone.
- **Acceptance evidence:** a live Postgres two-session regression with controlled synchronization commits an edit between the target and history read positions. Replay must report a coherent version/hash/content cut. Separate actual tampering tests must still detect unhealthy state.
- **Reasoning:** write atomicity does not by itself make a multi-query diagnostic read coherent.
- **Status:** open; source-derived, not locally reproduced. Corresponds to earlier finding 1.

**Migration verification gap:** CI performs upgrade/downgrade/upgrade before tests populate the schema. That proves the empty-schema roundtrip. The inspected migration test checks schema metadata; it does not execute a populated downgrade or its refusal path. The change document claims populated/typed-row guard verification, but an as-built statement is not independently executable proof. Add or supply reproducible isolated-Postgres evidence for populated legacy preservation and typed-history refusal. This is a missing-evidence statement, not an assertion that the migration is broken.

### P3 — Low priority

None identified within reviewed scope.

**Category verdict:** changes required; populated migration safety remains unverified in this review.

## SCRIPT — Scripts, evaluation, and developer tooling

**Scope:** evaluation/offline_eval.py and evaluation/README.md. **Coverage:** source reviewed; existing CI execution inspected.

### P1 — High priority

None identified within reviewed scope.

### P2 — Medium priority

### SCRIPT-001 — P2 — The equivalence gate excuses an unexpected parser failure in any scenario

- **Provenance:** A8 requires honest deterministic verdict accounting; only the named delimiter-collision case intentionally differs between formats.
- **Evidence:** [evaluation/offline_eval.py:143–161](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/evaluation/offline_eval.py#L143-L161) sets expressible_gap whenever PDCP rejects with block_malformed and both typed variants accept. It does not check that the current scenario is the delimiter-collision case.
- **Trigger / actual:** a regression makes the ordinary "1 tiny edit" PDCP path return rejected:block_malformed while both typed variants still accept. The predicate labels it an expressibility gap and all_equivalent can remain true.
- **Impact:** CI can report equivalence OK while an ordinary legacy proposal has regressed.
- **Required remediation:** encode explicit per-scenario expected results and allow a format difference only in the named delimiter case. For accepted cases, verify expected output/hash as well as agreement between implementations.
- **Acceptance evidence:** inject an unexpected block_malformed outcome into a non-delimiter scenario and require nonzero exit; require the intended delimiter case to pass only with its expected outcomes and output. An unexpected rejection shared by all formats must also fail.
- **Reasoning:** a comparison needs an independent oracle; shared failure or a broad exception is insufficient.
- **Status:** open; source-derived. Current CI output is not claimed to contain that regression.

### P3 — Low priority

None identified within reviewed scope.

**Category verdict:** changes required.

## TEST — Tests and CI

**Scope:** CI workflow and logs; schema assertions, lineage/guard test excerpts, migration metadata tests. **Coverage:** partial.

### P1 — High priority

No additional defect established in the inspected tests/CI scope.

### P2 — Medium priority

No additional defect established; verification gaps follow separately.

### P3 — Low priority

None identified within reviewed scope.

No additional production defect is asserted in this category. The tests supply evidence and expose verification gaps associated with the findings above; those are not counted twice.

### Required verification gaps

1. MCP-001: compare value domains using the actual advertised schema; the current key-set test cannot detect nullability drift.
2. RUN-001: exercise malformed risk containers through the real tool boundary and assert durable rejection, not just process survival.
3. RUN-002: use multi-fault legacy inputs to distinguish completed protocol validation from an early failure.
4. SVC-001/SVC-002: cover accepted same-target parent and invalid attempt values in addition to current malformed/missing/cross-target parent tests.
5. DB-001: synchronize two real DB sessions across replay's read boundary.
6. DB migration gap: use populated data and assert preservation/refusal, beyond the pre-test empty roundtrip.
7. SCRIPT-001: prove the evaluation process fails on deliberately wrong verdicts and outputs.
8. ARCH-001: assert the chosen default/cap against the authoritative contract, rather than mirroring runtime constants.

The unkeyed retry test at [backend/tests/integration/test_typed_submit_flow.py:309–324](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/integration/test_typed_submit_flow.py#L309-L324) proves a version-guard retry is rejected; it does not prove the host guide's broader claim for a hash-only guard.

**Category verdict:** incomplete verification. Green CI is acknowledged; it does not close the above findings.

## DEP — Dependencies, packaging, and configuration

**Scope:** pyproject.toml and requirements.lock are changed, but were not substantively reviewed here. **Coverage:** not reviewed.

### P1 — High priority

Not assessed.

### P2 — Medium priority

Not assessed.

### P3 — Low priority

Not assessed.

No findings asserted. This does not establish compatibility, dependency safety, or reproducible installation.

### Required review

Inspect declared constraints versus the lockfile, Python support, editable-install behavior, configuration variable names used by setup instructions, and a clean installation/startup path. Separate current source agreement from any dependency advisory checks, which need dated evidence.

**Category verdict:** incomplete; no approval.

## Cross-category root causes and remediation order

1. **Contracts are copied without behavioral reconciliation.** ARCH-001, MCP-001, and SKILL-001 show independently drifting definitions. Start by confirming the normative decision, then reconcile schema, instructions, runtime, docs, and boundary assertions. Do not promote code to authority simply because it exists.
2. **A failure label substitutes for lifecycle evidence.** RUN-002 infers completed validation from an error enum. Preserve actual phase completion through the service boundary.
3. **The audit contract is not applied to every input path.** RUN-001 bypasses rejected-attempt persistence; SVC-001/SVC-002 accept invalid lineage metadata. Review common boundaries across entry points.
4. **The replay observation instant is unspecified.** DB-001 needs an architectural read-consistency rule before a locking/isolation implementation is selected.
5. **Verification compares outputs without fully constraining expected behavior.** SCRIPT-001 and the schema key-set test can be green while their advertised guarantees fail.

Recommended order: settle C3's observation boundary and C6's resource contract; reconcile typed schema and stage semantics; repair shared validation/audit boundaries; correct recovery guidance and skills; close the corresponding regression and migration evidence gaps. This ordering follows the dependency between decisions and implementation, rather than minimizing changed lines.

## Finding closure record

| ID | Priority | Status | Fix commit | Acceptance evidence / reviewer recheck |
| --- | --- | --- | --- | --- |
| ARCH-001 | P2 | Open | — | Required |
| DOC-001 | P2 | Open | — | Required |
| SKILL-001 | P3 | Open | — | Required |
| MCP-001 | P2 | Open | — | Required |
| RUN-001 | P2 | Open | — | Required |
| RUN-002 | P2 | Open | — | Required |
| SVC-001 | P2 | Open | — | Required |
| SVC-002 | P3 | Open | — | Required |
| DB-001 | P2 | Open | — | Required |
| SCRIPT-001 | P2 | Open | — | Required |

The migration proof gap and dependency review are open coverage items, not extra counted defects. The category identifiers above replace the earlier flat numbering; the correspondence is recorded in each carried-forward finding.

## Changed-file inventory

Every one of the PR's 52 changed files is mapped below. "Inspected" means relevant source or contract excerpts were examined for this report; it is not a claim of exhaustive line-by-line review. "Inventory only" means no substantive finding or clearance is claimed from this pass.

| Category | Changed file | Coverage in this pass |
| --- | --- | --- |
| SKILL | [.agents/skills/patchdiff-core-runtime/SKILL.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/.agents/skills/patchdiff-core-runtime/SKILL.md) | Inspected relevant source/contract |
| SKILL | [.agents/skills/patchdiff-mcp-orchestration/SKILL.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/.agents/skills/patchdiff-mcp-orchestration/SKILL.md) | Inspected relevant source/contract |
| SKILL | [.agents/skills/patchdiff-persistence-replay-save/SKILL.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/.agents/skills/patchdiff-persistence-replay-save/SKILL.md) | Inspected relevant source/contract |
| SKILL | [.agents/skills/patchdiff-testing-review/SKILL.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/.agents/skills/patchdiff-testing-review/SKILL.md) | Inspected relevant source/contract |
| TEST | [.github/workflows/ci.yml](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/.github/workflows/ci.yml) | Inspected relevant source/contract |
| SKILL | [AGENTS.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/AGENTS.md) | Inspected relevant source/contract |
| DOC | [README.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/README.md) | Inventory only |
| DOC | [README_INTERNAL_MCP.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/README_INTERNAL_MCP.md) | Inventory only |
| RUN | [backend/app/core/result.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/core/result.py) | Inventory only |
| RUN | [backend/app/core/validity.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/core/validity.py) | Inspected relevant source/contract |
| RUN | [backend/app/core/versions.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/core/versions.py) | Inspected relevant source/contract |
| MCP | [backend/app/mcp/external_adapter.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/mcp/external_adapter.py) | Inspected relevant source/contract |
| MCP | [backend/app/mcp/tools.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/mcp/tools.py) | Inspected relevant source/contract |
| DB | [backend/app/migrations/alembic.ini](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/migrations/alembic.ini) | Inventory only |
| DB | [backend/app/migrations/versions/20261020_0002_typed_ledger.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/migrations/versions/20261020_0002_typed_ledger.py) | Inspected relevant source/contract |
| RUN | [backend/app/pdcp/applier.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/pdcp/applier.py) | Inventory only |
| RUN | [backend/app/pdcp/disambiguation.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/pdcp/disambiguation.py) | Inventory only |
| RUN | [backend/app/pdcp/matcher.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/pdcp/matcher.py) | Inventory only |
| RUN | [backend/app/pdcp/typed.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/pdcp/typed.py) | Inspected relevant source/contract |
| SVC | [backend/app/services/export_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/export_service.py) | Inventory only |
| SVC | [backend/app/services/pdcp_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/pdcp_service.py) | Inspected relevant source/contract |
| SVC | [backend/app/services/prompt_context_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/prompt_context_service.py) | Inventory only |
| SVC | [backend/app/services/read_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/read_service.py) | Inspected relevant source/contract |
| SVC | [backend/app/services/regeneration_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/regeneration_service.py) | Inventory only |
| DB | [backend/app/services/replay_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/replay_service.py) | Inspected relevant source/contract |
| SVC | [backend/app/services/save_service.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/services/save_service.py) | Inventory only |
| DB | [backend/app/storage/models.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/app/storage/models.py) | Inspected relevant source/contract |
| TEST | [backend/tests/integration/test_external_mcp_e2e.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/integration/test_external_mcp_e2e.py) | Inventory only |
| TEST | [backend/tests/integration/test_mcp_tools.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/integration/test_mcp_tools.py) | Inventory only |
| TEST | [backend/tests/integration/test_migrations_reachable.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/integration/test_migrations_reachable.py) | Inspected relevant source/contract |
| TEST | [backend/tests/integration/test_typed_submit_flow.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/integration/test_typed_submit_flow.py) | Inspected relevant source/contract |
| TEST | [backend/tests/unit/test_matcher.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/unit/test_matcher.py) | Inventory only |
| TEST | [backend/tests/unit/test_migration_0002_offline.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/unit/test_migration_0002_offline.py) | Inventory only |
| TEST | [backend/tests/unit/test_modernization_contracts.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/unit/test_modernization_contracts.py) | Inventory only |
| TEST | [backend/tests/unit/test_mutation_boundary.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/unit/test_mutation_boundary.py) | Inventory only |
| TEST | [backend/tests/unit/test_stdio_adapter_subprocess.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/unit/test_stdio_adapter_subprocess.py) | Inventory only |
| TEST | [backend/tests/unit/test_typed_transaction.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/backend/tests/unit/test_typed_transaction.py) | Inspected relevant source/contract |
| DOC | [docs/CLAUDE_DESKTOP_SETUP.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/CLAUDE_DESKTOP_SETUP.md) | Inventory only |
| DOC | [docs/CODEX_BUILD_PLAN.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/CODEX_BUILD_PLAN.md) | Inventory only |
| DOC | [docs/DATA_MODEL.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/DATA_MODEL.md) | Inventory only |
| DOC | [docs/HOST_INTEGRATION_GUIDE.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/HOST_INTEGRATION_GUIDE.md) | Inspected relevant source/contract |
| ARCH | [docs/MCP_FIRST_MVP.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/MCP_FIRST_MVP.md) | Inventory only |
| DOC | [docs/MCP_TOOLS.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/MCP_TOOLS.md) | Inspected relevant source/contract |
| ARCH | [docs/MODERNIZATION_ARCHITECTURE.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/MODERNIZATION_ARCHITECTURE.md) | Inspected relevant source/contract |
| DOC | [docs/MODERNIZATION_CHANGE_DOC.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/MODERNIZATION_CHANGE_DOC.md) | Inspected relevant source/contract |
| ARCH | [docs/PATCHDIFF_CORE_SPEC.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/PATCHDIFF_CORE_SPEC.md) | Inventory only |
| DOC | [docs/PDCP_FORMAT.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/PDCP_FORMAT.md) | Inventory only |
| DOC | [docs/TEST_MATRIX.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/docs/TEST_MATRIX.md) | Inspected relevant source/contract |
| SCRIPT | [evaluation/README.md](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/evaluation/README.md) | Inspected relevant source/contract |
| SCRIPT | [evaluation/offline_eval.py](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/evaluation/offline_eval.py) | Inspected relevant source/contract |
| DEP | [pyproject.toml](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/pyproject.toml) | Inventory only |
| DEP | [requirements.lock](https://github.com/paragon-ux/Patch-DIFF/blob/39dcb4b049a030dc15b96b8672ee3236e4e99c7e/requirements.lock) | Inventory only |

Unchanged dependencies examined: backend/app/storage/db.py, backend/app/pdcp/protocol_validator.py, and backend/app/pdcp/models.py. Their findings concern changed behavior that relies on these paths.
