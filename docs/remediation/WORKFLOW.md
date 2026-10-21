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
| DEV-SVC-001 | Null-key immutable rejection for every admitted conflict; submitted/existing IDs and bounded diagnostics; null-key fingerprint policy; unchanged original recovery; accepted/rejected/repeated/concurrent/rollback live cases; stdio; contracts, independent review and stacked PR | Implemented at3a7ddb0;713tests/manuallive/independentten-categoryrecheck pass;PR#6open,stacked on #5;CIpending |
| DEV-DB-001 | C3/core raw-storage formula first; canonical hashes unchanged; no repair; separate reconstruction and health; rollback-isolated CRLF/CR/Unicode/hash/version/healthy live matrix; stdio replay; independent review and stacked PR | Contracts reconciled before implementation on fix/devin-replay-integrity |
| DEV-MCP-001/002 | Non-bool integer context >=0 with cap400; schemas/routing; limit+1 filtered attempt pages, continuation on every response, default50/cap200; preserve display orders; service matrix, actual DB traversal and stdio smoke; docs, independent review and stacked PR | Not started |
| DEV-SVC-002 / D01 | Recorded parent-identity adoption decision; conditional compatibility tests if adopted; document existing full-record identity including canonical JSON vs wire bytes, intent, guards and selectors | Decision: do not adopt parent-identity changes in this release; documentation not started |
| V01 / V06 / V07 / V09 | Real synchronized duplicate sessions; actual supported isolation; caller-owned visibility/commit/rollback/lock lifetime; complete accepted/rejected recovered facts after later edits | To place in owning Unicode/conflict workstreams and final integrated verification |

## Decisions

- DEV-SVC-002: retain current parent fingerprint behavior for this release. Eligible rejected-parent UUIDs already canonicalize. Ineligible/missing/cross-target lineage remains a rejection; its raw supplied value remains part of identity. Changing stored rejected-outcome identity would need a separate compatibility strategy and is not necessary for the six required fixes. D01 will document this without changing hashes. This is the explicitly requested adoption decision, not a claim the edge case was fixed.
- Exactly one new runtime profile, patchdiff-mvp-0.2.2, is reserved for selector constraints. Freeze after its first durable log. Other required changes do not change historical edit execution.
- Unicode evidence representation must be recorded before its implementation. No no-log exception, new operation, normalized-identity alternative, migration/framework, or general rate limiter is authorized.
- F01-F14 usability extensions are excluded; the separately named defect IDs remain required where they overlap those suggestions.
- Each PR is a coherent workstream with active contracts, implementation, tests and independent recheck. No reviews/ files are committed or modified.
- The supplied objective file ends mid-sentence in D01 after “intent, guards, sel”. Revision 2 and the complete earlier conversation supply the intended documentation scope; the truncated tail is not treated as authorization for extra features.

## Environment

Initial live PostgreSQL container existed but was paused. It was unpaused to run authorized live verification; pg_isready reported accepting connections. No live result is inferred from that readiness check.
