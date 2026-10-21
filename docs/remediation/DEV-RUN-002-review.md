# DEV-RUN-002 independent recheck and closure

Date:2026-10-21. Standard:PR_REVIEW_STANDARD1.1.0.
Branch:fix/devin-unicode. Base:2df23ed2e42a09f3bc77d6bad8a1d732bfbef6a4.
Reviewed material:893301ec13ca7ae3415aa26698677686581c6d15.
Independent reviewer: default-model selector_independent_review, distinct from implementation worker and primary agent. This record summarizes its returned ten-category report and separately attributed primary execution results. No writes under docs/reviews per explicit user direction.

## Inventory and trace

ARCH: MODERNIZATION_ARCHITECTURE, PATCHDIFF_CORE_SPEC, DEV-RUN-002-decision and V07-wrapper-decision.
DOC: DATA_MODEL, HOST_INTEGRATION_GUIDE, MODERNIZATION_CHANGE_DOC, PDCP_FORMAT, WORKFLOW and this closure record.
SKILL: AGENTS and core/MCP/persistence skills.
MCP: tools, export_service, prompt_context_service, read_service, MCP_TOOLS.
RUN: input_text, parser, typed.
SVC: pdcp_service, regeneration_service.
DB: replay_service safe invalid-ID echo.
TEST: new unit/test_invalid_input_unicode.py and integration/test_invalid_input_unicode_live.py, TEST_MATRIX and associated JSON/stdout evidence. SCRIPT/DEP:no changed product files.

Locked audit/atomicity/history -> pre-coding safe representation decision -> validate original nested strings/keys -> deterministic ASCII envelope in existing TEXT + safe JSONB previews -> shared locked domain rejection -> original/new keyed recovery -> direct/legacy ownership and actual persistence/stdio proof.

New input validation is separate from historical decoding. Recorded escaped-NUL accepted/rejected outcomes and invalid-parent fingerprints recover under the lock without admitting fresh invalid input or rewriting recorded hashes. The iterative walker removes per-level Python recursion. The wrapper no longer commits a caller's transaction. No new profile/table/migration/encoding framework/operation/catch-all handler.

## Findings independently raised during review

| Candidate | Priority | Recheck |
| --- | --- | --- |
| Historical NUL/invalid-parent retries became false conflicts | P2 | Fixed:lookup-only original fingerprint fallback and accepted/rejected recovery before/after later edits. |
| Depth500 JSON failed recursive validation before audit | P2 | Fixed:iterative DFS, deep pure/live cases and path-order assertion. |
| Deprecated wrapper committed caller-owned transaction | P2 / V07 | Fixed:ownership-before-read, actual caller commit/rollback and standalone MCP persistence. |
| Shortened path incorrectly reported no truncation | P3 | Fixed at893301e:expression, deep-case assertion and documented preview semantics. |

All four are independently rechecked; no remaining source/contract finding in this workstream.

## ARCH

Scope/coverage:Complete for selected existing-field representation, audit, compatibility, read boundaries and V07 ownership.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:Decision before coding -> input preflight -> existing locked reject path -> typed/legacy persistence and recovery tests.

Limits:No whole-project approval.

Verdict:no remaining findings within reviewed scope.

## DOC

Scope/coverage:Complete for changed contracts and recorded decisions.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:ASCII envelope, safe JSONB, invalid keys, lookup-only historical recovery, preview flag and unchanged valid identity reconciled.

Limits:Final evidence is committed after the reviewed material source.

Verdict:no remaining findings within reviewed scope.

## SKILL

Scope/coverage:Complete for affected instructions.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:Pure core, audited domain errors, safe read responses, immutable historical identity and live checks retained.

Limits:Unrelated skills not audited.

Verdict:no remaining findings within reviewed scope.

## MCP

Scope/coverage:Complete for changed read/search/filter/echo boundaries.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:No unsafe database binds/echoes; invalid_argument on reads without edit rows; actual escaped-JSON stdio evidence inspected.

Limits:Numeric context/paging remain later workstreams.

Verdict:no remaining findings within reviewed scope.

## RUN

Scope/coverage:Complete for text checks, iterative scanner, parser admission and decoder compatibility.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:Reviewer independently passed97 final pure cases including nested keys, metadata, depth500, path order, Unicode/NUL, supplementary text and identity assertions.

Limits:Arbitrary non-JSON object graphs are not a claimed wire format.

Verdict:no remaining findings within reviewed scope.

## SVC

Scope/coverage:Complete for envelope construction, historical fingerprint fallback and wrapper ownership.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:Original inputs safely compared under lock before stale guards. New invalid-only identity does not rewrite old keys. Wrapper establishes ownership before reads.

Limits:Conflict-audit branch remains DEV-SVC-001.

Verdict:no remaining findings within reviewed scope.

## DB

Scope/coverage:Complete for affected encoding persistence and transaction durability.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:Reviewer independently read manual target5c326553-7344-4135-ba12-9a125b6fca8f:three ASCII-evidence rejections,one acceptance,one NULL-key rejection,one ledger/version1, plus all four typed/wrapper commit/rollback outcomes.

Limits:Reviewer did not rerun entire live suite; stronger-isolation guarantee not claimed.

Verdict:no remaining findings within reviewed scope.

## SCRIPT

Scope/coverage:Complete delta assessment; evaluator unchanged.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:Valid serialization/hash APIs unchanged; primary agent reran evaluator with equivalence OK.

Limits:No usability/performance claim or independent evaluator rerun.

Verdict:no remaining findings within reviewed scope.

## TEST

Scope/coverage:Complete for added assertions and evidence linkage.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:97 reviewer-run pure cases; primary683 final full tests (500unit/183integration),actual stdio/directDB manual evidence,12 protected review hashes verified, diff check clean.

Limits:Remote workstream CI still needs inspection after publication.

Verdict:no remaining findings within reviewed scope.

## DEP

Scope/coverage:Complete delta assessment; no dependency/schema/config change.

### P1

None identified within reviewed scope.

### P2

None remaining within reviewed scope.

### P3

None remaining within reviewed scope.

Verification:Stdlib helper, no new migration/framework/profile/operation.

Limits:No clean-install rerun by reviewer.

Verdict:no remaining findings within reviewed scope.

## Verification and closure

DEV-RUN-002 independently classified fixed at893301e. The reviewer independently passed97 pure cases and corroborated the actual manual target and four ownership outcomes directly in PostgreSQL. Parent executed683 final tests, including183 live integration cases, real subprocess tests and isolated populated migrations; exact stdout in DEV-RUN-002-pytest.txt. Nine existing Alembic warnings remain unrelated. Offline evaluator OK.

Manual execution outside pytest at893301e:11 real stdio calls; three encoding rejections and one acceptance; reversible ASCII evidence; invalid key stored NULL; invalid read strings create no attempt; recovery after a later real edit; depth500 audited; replay healthy. Separate direct and wrapper outer commit/rollback retain ownership and durability, including unrelated outer project markers. Evidence:DEV-RUN-002-live.json and DEV-RUN-002-tests.json.

An earlier approval-capacity error prevented one manual command from executing. No pass was inferred. After capacity returned, the prepared script executed successfully at893301e. The default-model reviewer resumed and completed its final pinned review. No failed reviewer turn is represented as approval.

Commit final evidence, publish/attach the stacked PR and inspect actual remote CI. This is scoped closure, not approval of the remaining PR#1 findings. No merge is authorized.
