# DEV-RUN-001 independent recheck and evidence

Date: 2026-10-21. PR workstream targets feature/modernization-argon-remediation.
Standard: PR_REVIEW_STANDARD.md1.1.0. Base b33faaf332e269019747772602afff34f9829e5c.
Material implementation ecd0dfa4573b6f4284e5d102d23ff9dc1310e711; final material delta3d4daec2361c87615e3dc20bc5341a90cc0b75cf.
Independent reviewer: default-model subagent selector_independent_review, distinct from selector_implementation and primary agent. This record summarizes its returned ten-category report and the primary agent's separately attributed execution evidence.
Report location follows the user's explicit prohibition on writing under docs/reviews/. No standard version or required category was changed.

## Inventory and architecture trace

ARCH: MODERNIZATION_ARCHITECTURE and PATCHDIFF_CORE_SPEC.
DOC: CODEX_BUILD_PLAN, DATA_MODEL, HOST_INTEGRATION_GUIDE, MCP_FIRST_MVP, MODERNIZATION_CHANGE_DOC, PDCP_FORMAT and docs/remediation records.
SKILL: AGENTS and the three changed core/persistence/testing skills.
MCP: external_adapter and MCP_TOOLS.
RUN: core/versions, pdcp/disambiguation, pdcp/applier.
SVC: services/pdcp_service.
DB: services/replay_service.
TEST: unit/test_selector_profiles.py, integration/test_selector_profiles_live.py, TEST_MATRIX and test/live JSON evidence.
SCRIPT/DEP: no changed files. Relevant unchanged matcher, typed decoder, legacy validation, transaction/rejection helpers, locked repository query, evaluator and CI inspected.

Concept-paper/locked invariants -> selected explicit selector contract -> independent profile flags -> shared applier used by locked submission and versioned replay -> pure offsets/outcomes and actual persistence/stdio evidence. Historical permissive change-ID decoding remains limited to its original profiles; canonical hashes and history are untouched.

The reviewer raised two P3 documentation findings: advisory-only repeated-match errors were mislabeled, and test-matrix counts/module inventory were stale. Both were corrected and independently rechecked. Server metadata was also reconciled to0.2.2. No remaining runtime/profile blocker was found.

## ARCH

Scope/coverage: Complete for singleton constraints, replay profiles and atomicity boundary.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Architecture/core contracts -> RuntimeProfile -> explicit submit/replay dispatch -> matrix and live assertions. One new immutable0.2.2; all three old profiles preserved.

Limits: No whole-project architecture audit.

Verdict: no remaining findings within reviewed scope.

## DOC

Scope/coverage: Complete for changed active documentation and remediation records.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Independent reviewer rechecked advisory-only error wording and403/153 counts/module row. Root executed both host examples through actual stdio. All12 protected review-file hashes match.

Limits: Final documentation/evidence commit follows reviewed material code.

Verdict: no remaining findings within reviewed scope.

## SKILL

Scope/coverage: Complete for affected instructions and current/historical semantics.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Separate singleton flag, nonadjacent anchors, advisory region_hint and required live verification reconciled.

Limits: Unrelated skills not audited.

Verdict: no remaining findings within reviewed scope.

## MCP

Scope/coverage: Complete for selector descriptions, unchanged input shape and metadata.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Actual subprocess domain rejection; server0.2.2 metadata independently reconciled.

Limits: Other MCP defects remain separate workstreams.

Verdict: no remaining findings within reviewed scope.

## RUN

Scope/coverage: Complete for profile resolver, disambiguation and shared applier.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Independent255-case pure run passed. Explicit offsets/outcomes across typed/legacy/sequential and historical settings.

Limits: Unicode remains DEV-RUN-002.

Verdict: no remaining findings within reviewed scope.

## SVC

Scope/coverage: Complete for profile dispatch through existing locked submission.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Ordinary applicability rejection, no new engine, no caller-owned commit, no partial accepted materialization.

Limits: V01/V06/V07/V09 remain assigned to later owning streams.

Verdict: no remaining findings within reviewed scope.

## DB

Scope/coverage: Complete for changed replay dispatch and audited rejection effects.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Six typed/legacy historical live fixtures inspected. Reviewer independently queried manual target: three rejected logs, one accepted0->1, one ledger, goodbye/version1, all runtime0.2.2 and read committed.

Limits: Reviewer did not rerun historical live fixtures. Raw integrity remains DEV-DB-001.

Verdict: no remaining findings within reviewed scope.

## SCRIPT

Scope/coverage: Complete for affected unchanged offline-evaluator interface; no script delta.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Shared applier retained and claims remain bytes/verdicts. Root evaluation passed.

Limits: Reviewer did not rerun evaluator.

Verdict: no remaining findings within reviewed scope.

## TEST

Scope/coverage: Complete for new assertion coverage and relevant CI configuration.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Root556-case full run; reviewer255-case focused run; 222new pure and15new live tests. State/log/ledger/profile assertions and actual subprocess timeout inspected.

Limits: Remote CI not yet inspected at this record's creation.

Verdict: no remaining findings within reviewed scope.

## DEP

Scope/coverage: Complete delta assessment: no dependency/migration/packaging/config changes.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification: Frozen slotted dataclass supported by existing Python>=3.11 and CI Python3.11; no new dependency.

Limits: No fresh clean-environment install.

Verdict: no remaining findings within reviewed scope.

## Closure and residual limits

DEV-RUN-001: independently classified fixed at material3d4daec. The reviewer independently passed255 focused pure cases and corroborated the manual target directly in PostgreSQL. It inspected, rather than independently rerunning, the six old-profile live fixtures.

Root full suite:556 passed (403unit/153integration) at the implementation tree recorded in DEV-RUN-001-tests.json. This includes real stdio and isolated populated migration tests. Offline evaluator OK. Subsequent metadata-only delta:5focused actual subprocess unit cases passed. Separate manual real stdio/direct-DB evidence at3d4daec is in DEV-RUN-001-live.json: both actual host examples reject, three attempts persist without target/ledger change, valid edit commits once, keyed retry recovers, replay healthy. Actual isolation is read committed.

The earlier filename collision caused collection failure, was corrected by distinct module basenames, and the complete rerun then passed. The final documentation/evidence delta was inspected independently and is committed with this report. CI must still be checked against the published head/generated merge. No uninspected CI pass is claimed.

This closes only the selector candidate within this workstream. Unicode, conflict audit, raw replay integrity, context validation and history continuation remain open. No merge authorization is implied.
