# PR #1 remediation execution

Authority: user-provided goal objective, AGENTS.md, modernization architecture, core specification, PR review standard 1.1.0 and change plan revision 2.
Starting commit: b33faaf332e269019747772602afff34f9829e5c.
Date started: 2026-10-21.
Base branch: feature/modernization-argon-remediation.
Merging requires further user approval. No merge is authorized.

The user explicitly prohibits editing anything under docs/reviews/. New execution and independent-review records therefore live here, overriding the review standard's usual report directory for this workflow. Original review files are protected by a SHA-256 inventory. Historical hashes, accepted logs and request fingerprints remain untouched.

## Workstream requirements and evidence

| Stream | Required deliverables | Current state |
| --- | --- | --- |
| DEV-RUN-001 | All-match-count selector constraints; one new immutable profile; typed/legacy/sequential matrix; live audit/nonmutation; real stdio; old-profile replay; contracts and independent review; stacked PR | PR #4 open at2df23ed;556 tests, manual live and independent recheck pass; actual generated-merge CI3ee9105 green (403unit/153integration), no merge |
| DEV-RUN-002 | Record minimal reversible evidence decision before coding; all user-string Unicode validation; audited known-target rejection, safe storage and deterministic keyed recovery; read/search invalid_argument; caller-owned commit/rollback; pure/live/stdio; independent review and stacked PR | PR #5 open atd8c71fe,stacked on #4;683 tests/manual live/independent recheck pass; actual generated-merge4207996 CI green(500unit/183integration),no merge |
| DEV-SVC-001 | Null-key immutable rejection for every admitted conflict; submitted/existing IDs and bounded diagnostics; null-key fingerprint policy; unchanged original recovery; accepted/rejected/repeated/concurrent/rollback live cases; stdio; contracts, independent review and stacked PR | Implemented at3a7ddb0;713tests/manuallive/independentten-categoryrecheck pass;PR#6open atfda5adb,stacked on #5;generated-merge d404924 CIgreen(504unit/209integration),no merge |
| DEV-DB-001 | C3/core raw-storage formula first; canonical hashes unchanged; no repair; separate reconstruction and health; rollback-isolated CRLF/CR/Unicode/hash/version/healthy live matrix; stdio replay; independent review and stacked PR | Implemented at cd1b91f after contract-first 9de0a64; 719 tests and manual PostgreSQL/stdio pass; independent ten-category recheck passes; PR #7 open at dd5877d, stacked on #6; generated-merge20c66c5 CI green (504 unit/215 integration), no merge |
| DEV-MCP-001/002 | Non-bool integer context >=0 with cap400; schemas/routing; limit+1 filtered attempt pages, continuation on every response, default50/cap200; preserve display orders; service matrix, actual DB traversal and stdio smoke; docs, independent review and stacked PR | Implemented at69f6a64;834 tests/manual PostgreSQL/stdio pass, independent ten-category closure passes; PR #8 open at226ab22, stacked on #7; CI pending |
| DEV-SVC-002 / D01 | Recorded parent-identity adoption decision; conditional compatibility tests if adopted; document existing full-record identity including canonical JSON vs wire bytes, intent, guards and selectors | Decision retained and D01 source-derived documentation implemented; independent recheck pending on docs/devin-request-identity |
| V01 / V06 / V07 / V09 | Real synchronized duplicate sessions; actual supported isolation; caller-owned visibility/commit/rollback/lock lifetime; complete accepted/rejected recovered facts after later edits | Verified in PRs #5/#6: actual READ COMMITTED blocking, outer ownership and full terminal recovery; final integrated verification remains |

## Decisions

- DEV-SVC-002: retain current parent fingerprint behavior for this release. Eligible rejected-parent UUIDs already canonicalize. Ineligible/missing/cross-target lineage remains a rejection; its raw supplied value remains part of identity. Changing stored rejected-outcome identity would need a separate compatibility strategy and is not necessary for the six required fixes. D01 will document this without changing hashes. This is the explicitly requested adoption decision, not a claim the edge case was fixed.
- Exactly one new runtime profile, patchdiff-mvp-0.2.2, is reserved for selector constraints. Freeze after its first durable log. Other required changes do not change historical edit execution.
- Unicode evidence representation must be recorded before its implementation. No no-log exception, new operation, normalized-identity alternative, migration/framework, or general rate limiter is authorized.
- F01-F14 usability extensions are excluded; the separately named defect IDs remain required where they overlap those suggestions.
- Each PR is a coherent workstream with active contracts, implementation, tests and independent recheck. No reviews/ files are committed or modified.
- The supplied objective file ends mid-sentence in D01 after “intent, guards, sel”. Revision 2 and the complete earlier conversation supply the intended documentation scope; the truncated tail is not treated as authorization for extra features.

## Environment

Initial live PostgreSQL container existed but was paused. It was unpaused to run authorized live verification; pg_isready reported accepting connections. No live result is inferred from that readiness check.
