# DEV-DB-001 independent review

Date: 2026-10-21.
Repository: paragon-ux/Patch-DIFF.
Branch: fix/devin-replay-integrity.
Review standard: PR_REVIEW_STANDARD.md version 1.1.0.
Base: fda5adba8c1912e207443ad4cdd964f7c0c5bc60.
Contract-first commit: 9de0a64cb7c8630b59e58606d17e7068d8683252.
Reviewed material head: cd1b91f19054ac7dc31bf5e2416f2e9f3547394e.
Reviewer: independent inherited-default-model selector_independent_review agent.
Workstream PR: not yet opened at review time.

## Scope, authority and evidence limits

DEV-DB-001 is independently classified fixed within this scope. No remaining actionable P1/P2/P3 findings were identified. This is not whole-PR #1 approval or merge authorization.

The contract change was inspected at 9de0a64 before the implementation appeared. It deliberately replaces the former core formula that normalized stored content before comparison. Existing canonical hashing, accepted-history execution and response shape remain unchanged.

The reviewer inspected the pinned source/contract delta, all six corruption/healthy regression bodies, relevant replay dependencies, stored full-suite output and manual evidence. The parent executed the full test suite and outside-pytest live cases. The reviewer independently queried the actual PostgreSQL manual target and verified protected-file hashes, but did not execute a second corruption matrix or independently launch the stdio process.

The user prohibits changes under docs/reviews/. This requested review artifact is therefore stored under docs/remediation/. No production file, original review, branch or database row was modified by this reviewer.

## File inventory and primary categories

Paths are repository-relative. Each changed file has one primary category.

| Category | Files |
| --- | --- |
| ARCH | docs/MODERNIZATION_ARCHITECTURE.md; docs/PATCHDIFF_CORE_SPEC.md |
| DOC | docs/HOST_INTEGRATION_GUIDE.md; docs/MODERNIZATION_CHANGE_DOC.md; docs/remediation/WORKFLOW.md |
| SKILL | .agents/skills/patchdiff-persistence-replay-save/SKILL.md |
| MCP | docs/MCP_TOOLS.md |
| RUN | No changed files |
| SVC | No changed files |
| DB | backend/app/services/replay_service.py |
| SCRIPT | No changed files |
| TEST | backend/tests/integration/test_replay_materialized_integrity_live.py; docs/TEST_MATRIX.md; docs/remediation/DEV-SVC-001-CI.json |
| DEP | No changed files |

Additional pending execution evidence inspected: docs/remediation/DEV-DB-001-live.json and DEV-DB-001-pytest.txt. Relevant unchanged dependencies include canonical_sha256/canonicalize_text, target lock/refresh, initial-snapshot and accepted-log replay, profile dispatch and the replay MCP wrapper.

## Contract-to-source-to-test trace

The locked canonical-LF storage invariant and amended C3/core formula now require:

- content_matches: raw target.current_content equals reconstructed canonical buffer.
- stored_hash_matches: stored current_hash equals reconstructed_hash.
- recomputed_hash_matches: canonical_sha256(stored current_content) equals reconstructed_hash.
- version_matches: stored and reconstructed versions agree.

The [pinned replay implementation](https://github.com/paragon-ux/Patch-DIFF/blob/cd1b91f19054ac7dc31bf5e2416f2e9f3547394e/backend/app/services/replay_service.py) changes only the content_matches comparison. The preexisting canonical recomputed-hash calculation remains intact. Reconstruction can still succeed while aggregate materialized health is false; replay does not repair storage.

The [six-case regression](https://github.com/paragon-ux/Patch-DIFF/blob/cd1b91f19054ac7dc31bf5e2416f2e9f3547394e/backend/tests/integration/test_replay_materialized_integrity_live.py) asserts exact component values:

| Case | content | stored hash | recomputed hash | version |
| --- | --- | --- | --- | --- |
| Healthy | true | true | true | true |
| CRLF | false | true | true | true |
| Bare CR | false | true | true | true |
| Unicode content corruption | false | true | false | true |
| Hash-only corruption | true | false | true | true |
| Version-only corruption | true | true | true | false |

It snapshots complete rows across six target-owned tables before/after replay, checks the caller transaction remains open, rolls back the intentional corruption, then checks a fresh healthy observer and unchanged rows.

## ARCH

Coverage: complete for the intentional materialized-health contract change and unchanged history invariants.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

Verification: contract-first history and final implementation reconcile the higher canonical-storage invariant with the former local formula. No new runtime profile, hash definition or repair behavior.
Limits: unrelated architecture remains outside this scoped review.
Verdict: no findings within reviewed scope.

## DOC

Coverage: complete for changed host/change-record/workflow descriptions and coverage placement.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None remaining within reviewed scope.

Verification: successful reconstruction is distinguished from healthy storage. The test-matrix row was moved into the actual integration table; the current remediation section was moved alongside current workstreams rather than after historical closure.
Limits: final evidence/closure records still need publication metadata.
Verdict: no remaining findings within reviewed scope.

## SKILL

Coverage: complete for the affected persistence/replay skill.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None remaining within reviewed scope.

Verification: raw stored-content comparison and recomputed_hash_matches formula now agree with C3 and source. The formerly misleading recomputed-hash description was corrected; hash-only corruption now has the documented distinct component meaning.
Limits: no unrelated skill audit.
Verdict: no remaining findings within reviewed scope.

## MCP

Coverage: complete for the affected replay response contract and wrapper boundary.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

Verification: response fields and operation shape are unchanged. Documentation tells hosts to inspect aggregate/component health independently of reconstruction status. Parent manual evidence includes a real stdio replay after rollback.
Limits: reviewer did not independently launch that subprocess; paging/argument fixes remain separate.
Verdict: no findings within reviewed scope.

## RUN

Coverage: complete delta assessment and affected canonicalization/replay inputs.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

Verification: no applier, parser, profile or canonical_sha256 change. Reconstructed canonical buffer and logged hash validation remain unchanged.
Limits: no new whole-core audit.
Verdict: no findings within reviewed scope.

## SVC

Coverage: complete for the affected read-only replay service boundary.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

Verification: existing transaction ownership and coherent locked snapshot are retained. No write/repair path, hidden retry or new catch is introduced.
Limits: no unrelated submit-service review.
Verdict: no findings within reviewed scope.

## DB

Coverage: complete for raw materialized comparison, history preservation and nonmutation assertions.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

Verification: independently queried manual target 90f7b637-931d-4573-964a-42fd58cc010c. It is restored to canonical LF content/version1. Its canonical current hash, accepted after_hash and stdio reconstructed_hash agree. Accepted pdcp_content hashes correctly. All six target-owned tables retain exactly one row. Source and regression snapshots establish no repair or history rewrite.
Limits: transient rollback-isolated corruption outcomes are supported by the parent's executed cases and inspected assertions, not independently recreated by this reviewer. No schema/migration change.
Verdict: DEV-DB-001 independently fixed within reviewed scope.

## SCRIPT

Coverage: complete delta assessment; no script behavior changed.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

Verification: parent reports offline equivalence passed; no new performance/model claim.
Limits: reviewer did not rerun the evaluator.
Verdict: no findings within reviewed scope.

## TEST

Coverage: complete for six new case bodies, source mapping and execution evidence.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None remaining within reviewed scope.

Verification: focused14 and full719 passing cases reported by parent; stored output confirms719 passed,9 warnings in41.87s. Parent identifies504 unit/215 live integration cases at the pinned source. Manual artifact records all six actual PostgreSQL rollback-isolated outcomes, successful reconstruction, nonmutation, restored state and actual stdio healthy replay. Reviewer independently corroborated restored database/history state and all12 protected review-file hashes. git diff --check passed.
Limits: reviewer did not rerun the full DB suite; remote workstream CI was not yet available.
Verdict: no remaining findings within reviewed scope; preserve final CI evidence when published.

## DEP

Coverage: complete delta assessment; no dependency, packaging or configuration change.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

Verification: existing runtime and PostgreSQL dependencies suffice; no migration or additional profile.
Limits: no separate clean-install run by reviewer.
Verdict: no findings within reviewed scope.

## Closure and disposition

| Item | Priority | Independent disposition |
| --- | --- | --- |
| DEV-DB-001 | P2 | Fixed at cd1b91f: raw storage divergence visible, canonical hashes/history unchanged, no repair. |
| Recomputed-hash skill description | P3 | Corrected and rechecked at cd1b91f against actual formula/hash-only case. |
| Test-matrix/current-change record placement | P3 | Corrected and rechecked at cd1b91f. |

The scoped change is ready for its stacked PR and remote CI. Commit the pending execution evidence and this review, then record the actual CI head/generated-merge revision. Other remediation streams remain open. No merge is authorized.

Formatting-only follow-up: P1/P2/P3 paragraphs are now Markdown headings to match standard1.1.0. Review findings, evidence and source pin are unchanged; original report remains in Git atdd5877d.
