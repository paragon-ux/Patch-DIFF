# PatchDIFF PR Review Standard

Version: 1.0.0
Status: required by AGENTS.md when this change is adopted
Established: 2026-10-20

## Purpose and authority

A review must make its coverage, reasoning, findings, and evidence inspectable by category. Passing tests, a polished change document, and a previous approval are inputs; none establishes that the implementation satisfies its architecture.

This standard governs PR reviews. The testing skill's concise completion-report example remains appropriate for implementation status updates; it does not replace a PR review.

Changes to this standard require a version bump, a rationale, and a PR that identifies which review requirements change. A reviewer cannot silently omit or weaken a category. This is a repository workflow contract, not a claim that GitHub branch protection or an automated merge gate has been installed.

## 1. Pin the review

Record:

- Repository, PR URL, review date, reviewer, standard version, base SHA, and head SHA.
- Exact commit or tree executed by each cited CI run. Distinguish a PR head from GitHub's generated merge commit.
- Changed-file inventory from the base/head comparison, plus unchanged dependencies examined.
- Evidence actually available: repository sources, original design paper, prior review, transcript, local reproduction, and CI logs. State when an attachment or environment was unavailable.
- Scope and exclusions. Fetching a file is not the same as reviewing it.

A new head invalidates claims about changed behavior until the delta and affected categories are re-reviewed. Retain the previous review and record which findings carry forward.

## 2. Review architecture before runtime

For every behavior change, trace:

design thesis / invariant -> current architecture decision -> public contract -> implementation -> verification.

Read the original design paper when assessing preservation or modification of its thesis. Separate historical design records, normative current contracts, as-built descriptions, and external evidence. Existing implementation does not automatically override a higher-priority contract.

When modernization relies on a current ecosystem norm, cite a primary source, its version or date, the exact capability, the demonstrated gap, and why closing that gap benefits PatchDIFF. Unsupported generalizations such as "modern agents expect this" are not evidence.

For each intentional departure from a contract, require a recorded decision, compatibility implications, and acceptance criteria before recommending runtime changes. Do not resolve a mismatch by silently rewriting documentation to match code.

## 3. Required categories

Each category has its own coverage statement, finding list, verification gaps, and verdict.

| ID | Category | Required review questions |
| --- | --- | --- |
| ARCH | Architecture and contracts | Are boundaries, guarantees, ownership, compatibility, and resource limits explicit? Does implementation satisfy the selected decisions? |
| DOC | Documentation and change records | Do active docs agree with normative contracts and actual behavior? Are historical records distinguished? Are completion and benchmark claims supported? |
| SKILL | Skills and agent instructions | Are referenced APIs, enums, fields, commands, and guarantees real and current? Do instructions guide correct implementation and review? |
| MCP | MCP schemas and public API | Do discovery schemas, runtime acceptance, errors, defaults, nullability, bounds, and documented responses agree? |
| RUN | Core runtime, parsing, and validation | Are inputs untrusted, failures deterministic, matching exact, application sequential and atomic, and stage reporting accurate? |
| SVC | Services, orchestration, and audit semantics | Are retries, lineage, request identity, recovery, and shared entry points consistent with the contracts? |
| DB | Database, migrations, replay, and concurrency | Are reads and writes transactionally coherent? Is history preserved? Are populated upgrades, downgrade refusal, and replay profiles verified? |
| SCRIPT | Scripts, evaluation, and developer tooling | Do scripts fail on unexpected results? Are exceptions scenario-specific? Are measurement claims limited to what was measured? |
| TEST | Tests and CI | Do tests prove the guarantees, including adversarial cases? What ran, where, against which revision and database, and what remains unverified? |
| DEP | Dependencies, packaging, and configuration | Are installation paths, lockfiles, supported versions, configuration names, and startup assumptions coherent? |

Map every changed file to one primary category. Cross-reference affected categories without counting the same defect twice. Split a category into named subsections when necessary; additions cannot replace the required categories. A documentation file defining architecture can belong primarily to ARCH.

"No findings" is permitted. A finding quota is prohibited.

## 4. Required category record

For each category include:

1. **Scope:** changed files and relevant unchanged dependencies examined.
2. **Coverage:** complete, partial, or not reviewed; specify what remains.
3. **Finding list:** independent findings with category-prefixed stable IDs, or "No findings identified within the reviewed scope."
4. **Verification:** tests inspected, tests executed, CI evidence inspected, and missing proof.
5. **Verdict:** changes required, no findings within reviewed scope, incomplete, or not applicable with a reason.

A category with findings and partial coverage records both facts. "Not applicable" means the category has no relevant change or dependency, not that it was skipped.

## 5. Required finding record

Use one ID per independently remediable problem, e.g. MCP-001. Preserve IDs across revisions.

- **Title, priority, status.**
- **Contract provenance:** exact invariant, architecture decision, public contract, or evidenced external norm.
- **Source evidence:** immutable commit-pinned file links and relevant line ranges, plus the affected symbol.
- **Trigger:** concrete input, state, interleaving, or document instruction that exposes the issue.
- **Expected / actual:** explain the mismatch and distinguish observed execution from source-derived inference.
- **Impact:** concrete consequence and affected scope.
- **Required remediation:** precise behavior to restore, compatibility constraints, and affected contract surfaces.
- **Acceptance evidence:** regression case and assertions; use source reconciliation for low-impact prose changes where a test would add no value.
- **Root cause / related IDs:** connect cross-layer defects without duplicating the finding.
- **Closure:** fix commit, evidence at that revision, reviewer recheck, and residual limitations.

Priorities:

- P0: immediate critical failure requiring emergency handling.
- P1: high-impact correctness, data loss, security, or reliability failure.
- P2: actionable correctness or contract problem that should be fixed.
- P3: lower-impact issue or improvement; identify whether it is advisory.

A verification gap alone is not proof of a production defect. Label it as a gap. Do not inflate severity or finding counts to fill categories.

## 6. Evidence rules

- Separate source inspection, attempted reproduction, local execution, and inspected CI logs.
- Give reproduction steps even when execution is unavailable; label the expected failure as source-derived.
- Test names, comments, string-presence assertions, and a green summary do not prove the named guarantee. Inspect what is asserted.
- Never inherit a previous review's verdict. Revalidate its findings and explicitly accept, revise, or reject them.
- Identify assumptions, unresolved questions, and unverified external claims.
- Do not claim that a transcript, attachment, or design paper was read unless its contents were accessible and examined.

PatchDIFF-specific verification:

- Schema: exercise documented omitted/null/valid/invalid values through actual tools/list schemas and the runtime boundary. Enforce representable structural constraints; retain service checks for cross-field and business rules.
- Validation: include multi-fault inputs to prove that reported validity follows completed stages.
- Audit: check target state and accepted/rejected log/ledger effects, not only returned status.
- Idempotency: distinguish request-ID deduplication, monotonic version guards, hash-only guards, no-op edits, and ABA transitions.
- Concurrency: use two sessions and controlled synchronization for snapshot/locking claims.
- Migrations: use an isolated live Postgres database with populated legacy data; check preservation through upgrade/downgrade/upgrade and refusal to downgrade typed history. An empty schema roundtrip establishes only the empty case.
- Evaluation: use explicit expected outcomes and outputs; permit format differences only in named cases.
- External MCP: distinguish an in-process adapter call from a real stdio subprocess.

Run checks appropriate to the change. A documentation-only review-standard change does not require rerunning the product suite.

## 7. Verdict and closure

Keep coverage and merge disposition separate.

- Request changes when blocking correctness or contract findings remain.
- Mark the review incomplete when a material category is unreviewed; this can coexist with request changes.
- Recommend approval only after all material categories are covered, blocking findings are resolved and rechecked, and required verification has evidence.
- Never calculate approval from a pass percentage, number of findings, test count, or absence of findings in an unreviewed category.

Re-review each fix in its primary category and all affected categories. A fix commit is not closure by itself. Every closed finding needs the relevant evidence and reviewer recheck.

## 8. Required report structure

1. Review metadata and evidence limits.
2. File-to-category inventory and coverage matrix.
3. Architecture-to-implementation trace.
4. Ten category sections, each with its own finding list and verdict.
5. Cross-category root causes and rationale for remediation order.
6. Verification record and remaining gaps.
7. Overall disposition and finding closure table.

Reports are stored under docs/reviews/. Preserve reports at their reviewed revisions; a later review gets a new revision or dated document with a link to its predecessor.

## Change history

| Version | Date | Change |
| --- | --- | --- |
| 1.0.0 | 2026-10-20 | Establish category-separated review, provenance, explicit coverage, evidence distinctions, and finding closure. |
