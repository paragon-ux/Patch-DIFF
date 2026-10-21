# Goal F: PatchDIFF usability extensions — revision 2

Date: 2026-10-21.
Repository: paragon-ux/Patch-DIFF.
Disposition source: Devin-Goal-F-Disposition.md, reviewed against the preceding Goal F proposal and the source-backed plan review.

## Status and authorization

This revision incorporates the disposition into the proposed goal. The current user request authorizes updating this goal file. It does not itself authorize merges, feature implementation, commits or publication. Execution begins after the user approves proceeding and the merge preconditions below are satisfied.

Scope is nine planned feature implementations, three closures with existing evidence, and two deferred decision items. Do not describe all fourteen as accepted implementations or claim deferred items are implemented. The optional F10 editing adapter is also deferred; its read-only helper is included.

## Authority and preservation

Follow AGENTS.md, docs/MODERNIZATION_ARCHITECTURE.md, docs/PATCHDIFF_CORE_SPEC.md and docs/PR_REVIEW_STANDARD.md. Use change plan revision 2, its D01 decision and docs/remediation/DELIVERY.md for provenance. Amend the applicable highest-priority contracts explicitly before introducing new transaction forms; do not silently treat new code as overriding them.

Preserve the original Devin reports, disposition file, earlier change plans and remediation evidence. The current explicit goal-file edit is the sole exception to the earlier prohibition on editing docs/reviews/. For future implementation, put new decision/evidence/review records outside that protected directory, with the location exception stated in each report. Do not update old remediation records to make new features appear previously implemented.

## Merge sequence and execution preconditions

Once merge execution is authorized:

1. Verify the current heads, reviews, CI and dependencies of the existing PRs. PRs #2/#3 were already merged when this revision was prepared; verify their incorporated changes rather than attempting to merge them again.
2. Merge remediation PRs #4–#9 into feature/modernization-argon-remediation (PR #1), in dependency order. Retarget successors to the PR #1 branch as appropriate, inspect each resulting diff and rerun required CI against the actual new base. Merging a child into an already-merged feature branch does not automatically update PR #1.
3. Verify the consolidated PR #1 head, then merge PR #1 into main after the required approval and green checks. Do not bypass review requirements, force-push, or delete branches as an implied part of this plan.
4. Start usability work from the resulting main head on a new non-protected branch. Record the exact base SHA and merge evidence. Do not stack this effort on an unmerged PR #1.
5. Confirm runtime profile patchdiff-mvp-0.2.2 is frozen and the PR #9 D01/DEV-SVC-002 documentation is present. Run the required baseline verification, including live PostgreSQL, real stdio and offline evaluation.

If a precondition fails, report the concrete gap before dependent work. Do not infer merge approval from this document.

## Feature disposition and delivery order

| ID | Disposition for this goal | Phase |
| --- | --- | --- |
| F01 | Implement bounded rejection context, preserving original outcome evidence | A |
| F02 | Deferred; require a demonstrated host need and a separate adoption decision | Decision register |
| F03 | Implement explicitly opt-in correlation IDs only; keep caller-generated retry keys | C |
| F04 | Deferred to a separate identity-strategy proposal/PR | Decision register |
| F05 | Implement bounded diagnostic-only near misses after lock release, or omit explicitly | B |
| F06 | Implement bounded ambiguity candidates with truncation and buffer-stage identity | B |
| F07 | Implement guarded span edits with a versioned durable representation | D1 |
| F08 | Close with DEV-RUN-001 evidence; no new selector semantics | A |
| F09 | Implement guarded whole-target replacement as the sole operation in its transaction | D2 |
| F10 | Implement a read-only line/range helper; editing adapter deferred | A, or B if A grows |
| F11 | Implement advisory preview with no audit and no request-key parameter | E |
| F12 | Implement bounded, executable discovery examples; maintain across phases | A and subsequent phases |
| F13 | Close with DEV-MCP-002 evidence; preserve both display orders | A |
| F14 | Close with DEV-MCP-001 evidence | A |

The nine implementations are F01/F03/F05/F06/F07/F09/F10/F11/F12. The three closures are F08/F13/F14. F02/F04 remain explicitly deferred.

Out of scope: a general rate limiter; fuzzy application or automatic selection; host/model orchestration in the runtime; historical hash/fingerprint/profile rewrites; broader DEV-SVC-002 parent normalization; F02/F04 implementation; and the F10 editing adapter without a later decision.

## Global contracts

1. **One commit path.** Use the existing locked submit/rejection path in backend/app/services/pdcp_service.py and the shared deterministic applier. No alternative submit engine. Preserve caller-owned transactions; never commit or release their locks on the caller's behalf.
2. **Immutable replay profiles.** Keep 0.2.2 unchanged. F07 and F09 may have separate new runtime profiles so each can ship independently. Define and test each profile's complete semantics before its first durable history; never redefine it afterward. Later profiles must retain supported earlier operations. Add profiles only for actual replay-affecting semantics, not diagnostics, correlation IDs, examples or preview. Record chosen IDs in their decision records and profile table; unknown profiles fail closed.
3. **Identity compatibility.** F04 is deferred: do not introduce normalized fingerprints, a fingerprint-version migration, or a new identity strategy here. Preserve serialization and valid-input fingerprints for existing transaction forms, including omitted-field behavior. New forms must durably identify their operation/version and identity-bearing fields without retroactively changing old requests. Correlation IDs and response-only diagnostics never enter request identity. Preserve invalid-Unicode evidence and historical lookup-only recovery.
4. **Qualified audit guarantee.** Each admitted new submission to a known target creates exactly one immutable attempt within its transaction; durability follows successful owner commit. Exact keyed recovery creates none. Caller rollback and infrastructure failure do not promise a durable row. Reads and preview create none. If an oversized request is rejected before admission, document that separate no-attempt boundary and its structured error; do not call it an audited domain rejection or introduce an unrelated no-log exception.
5. **Bounded evidence.** Define numeric per-field and total-output budgets, units and truncation behavior before coding each feature. Bound candidate count and computation work as well as snippets. Label canonical target versus intermediate buffer, failed change/stage and observed version/hash. Never imply intermediate content was committed.
6. **Strict defaults.** At least one typed state guard remains required. Span and whole-target operations require a hash or version guard without exception. Check every supplied guard. Preserve client_request_id semantics; correlation is a separate opt-in response facility.
7. **Errors.** Catch only anticipated input failures. No blanket except or blanket IntegrityError catch. Infrastructure failures propagate to the transaction owner. New string inputs retain safe Unicode validation before hashing/storage.
8. **Verification.** Exhaustive matrices belong at pure/service level. Each phase also needs representative actual PostgreSQL and real stdio coverage, including manual live verification beyond existing tests. Run the repository-required suite/offline checks appropriate to the change. Do not substitute in-process routing for an actual subprocess.
9. **Small coherent PRs.** Deliver one PR per feature, or a small coherent phase when appropriate; stack only for real dependencies. Each includes contracts, decision records, implementation, tests, evidence and an independent ten-category recheck with separate P1/P2/P3 headings. Use default-model subagents. Never split solely by file type or merge without approval.

## Phase A: closures, rejection context, examples and read helpers

### F08 / F13 / F14: close with evidence

Confirm the fixes on the merged base and cite their actual fix/test/CI pins:

- F08: DEV-RUN-001 selector fix, including 0.2.2 singleton constraints and historical-profile behavior (material ecd0dfa/3d4daec; PR #4).
- F13: DEV-MCP-002 filtered limit+1 paging, exclusive cursor and preserved attempt-descending versus newest-ledger-page-ascending presentation (production 3b122df, final tests 69f6a64; PR #8).
- F14: DEV-MCP-001 invalid context types/bounds, including negative and boolean values (same MCP material; PR #8).

Recheck on the consolidated base. Fill missing host examples only; do not recode the fixes or reopen immutable profiles. An evidence closure is not a newly implemented feature.

### F01: fresh state and bounded rejection context

Public rejection payloads already expose current_version/current_hash; preserve them and address actual consistency gaps instead of treating both fields as entirely missing.

- Keep fresh locked target state separate from the original terminal failure evidence. Unknown/malformed target identity returns explicit unavailable/null state and snippet fields; do not fabricate freshness.
- Define a bounded failure-context representation and deterministic snippet-selection policy. A missing match has no exact failed span. Record whether context describes transaction-start or an intermediate sequential buffer.
- On keyed recovery after later edits, return the original terminal outcome/evidence unchanged. Any fresh state context is a separate response field with its own observed identity; never overwrite the stored diagnostic or relabel old failure context as current.
- Capture only cheap, bounded failure context while holding the target lock; it can support the later diagnostic features. Never return an unbounded target payload.
- Reconcile C1/C6, public schemas, MCP_TOOLS and the host guide.
- Test stale guards, missing/ambiguous matches, sequential-stage failure, cap boundaries, unknown targets and recovered rejections after later edits. Verify PostgreSQL nonmutation and one real stdio case.

### F12: worked examples in tools/list

Add short schema-conforming examples for a one-guard acceptance, selectors, a valid caller request key, rejection/read/retry, exact deduplication, and both history display orders. Reconcile MCP_TOOLS and the host guide.

Set and test a total discovery-payload budget. Avoid repeating full workflows in every tool description; put longer walkthroughs in the host guide. Test every published example over real stdio/PostgreSQL using actual initialized target IDs, returned guards, failure IDs and cursors. Fixed illustrative IDs/sequences are not assumed to exist. Assert actual results, not example-string presence. Update examples as later features land, with no model-success claims.

### F10: read-only line/range helper

Ship the helper in A, or move it to B if needed to keep the PR small. It returns bounded exact canonical text, code-point spans and the observed target version/hash. It performs no edits, creates no attempts and does not depend on F07.

Before coding, define line numbering, inclusive/exclusive endpoints, newline inclusion, EOF/final-empty-line behavior, empty targets, invalid types/ranges and output bounds. Distinguish code points from UTF-8 bytes and UTF-16 offsets. Returned text/spans/state identity must describe one coherent observation. Test CRLF initialization, Unicode/non-BMP text, empty lines/targets, EOF, out-of-range input and truncation/bounds.

A future editing adapter requires F07, a demonstrated need and a separate decision. It must convert against guarded target state and revalidate exact expected text; do not include it silently in this goal.

## Phase B: diagnostic-only candidates

### F06: ambiguity candidates

On ambiguity rejection, attach bounded occurrence-style candidates: occurrence index, end-exclusive code-point span and context. Use at most the search bound of 200, or a smaller explicit limit, plus a total output cap.

Initially return a truncation flag, not a continuation cursor. Include failed change and buffer-stage/observed-state identity. Explain that intermediate-buffer indices cannot be paged through a search of committed content or reused blindly for later sequential edits. Cover repeated/overlapping matches, selector failures where applicable, sequential buffers and output bounds. Diagnostics never choose or apply an edit.

### F05: near-miss diagnostics

Define deterministic tie-breaking, maximum input/window size, comparison work, candidate count and total output. Results must say they are near misses rather than exact matches; budget exhaustion has an explicit omission/truncation reason and never changes the core verdict.

Correct lock boundary: computing after the core verdict is not enough, because the submit transaction may still hold the target lock. For service-owned transactions, persist the normal rejection and release the lock on successful commit before expensive diagnostic work. Compute only from a captured bounded immutable failure context, labeled with its original stage/state identity; do not silently reread a newer target. Return supplemental response diagnostics without rewriting terminal audit evidence.

For caller-owned transactions, do not commit, release locks or run expensive near-miss comparisons while that lock remains held. Omit the expensive enrichment with an explicit reason. This does not schedule a background job or promise later delivery. Small bounded exact context/candidate capture remains governed by F01/F06.

Test whitespace-only, nearby/distant and no-candidate cases, deterministic ties, large-input/work limits, sequential context and caller ownership. Verify that expensive work starts after service-owned lock release and is skipped for caller-owned lock lifetime. Expected enrichment failures return the original committed verdict with an explicit diagnostic-omission reason; never retry persistence or create a second attempt. Do not swallow unexpected exceptions or imply rollback of an already committed outcome.

## Phase C: F03 correlation IDs only

Record the decision before code. Add an explicit opt-in flag (name/schema to be settled in the decision record) for per-call correlation IDs on submission responses. Default behavior is unchanged, whether or not client_request_id is supplied.

- correlation_id is distinct from client_request_id and pdcp_log_id. Define its format, generation and collision assumptions, scope and any existing-log integration without building a new durable lookup service.
- Never generate or substitute a retry key, claim keyed recovery from a correlation ID, consume the request-key namespace, add a persistence column, or include correlation in fingerprint identity.
- An opted-in dedup call can receive a fresh invocation correlation ID while retaining its original terminal outcome/log ID. Correlation remains response/trace metadata, not a rewrite of historical evidence.
- A lost first response still requires a caller-known client_request_id for recovery. Correlation does not make an unkeyed retry idempotent.
- Test opt-in omission/false/true and invalid types, generation, caller-supplied and absent retry keys, accepted/rejected/dedup responses, no additional audit rows, and real stdio routing.

## Phase D1: F07 guarded span edits

Write the architecture decision and amend AGENTS.md/current contracts before code. Define a versioned durable transaction representation and capability discovery, parser/lowering, pure application, derived facts, ledger and replay dispatch. Keep old typed/legacy records and existing fingerprints unchanged.

Require non-bool integer code-point start/end, end exclusive, exact expected_text, and at least one hash/version guard. F02 never bypasses span guards. Decide original versus sequential coordinates explicitly; sequential-buffer coordinates are the preferred fit with the existing applier. Define mixed match/span transaction rules and reject selectors on a span operation. Decide whether zero-length insertion is supported; keep legacy empty MATCH invalid.

Use a new frozen runtime profile if required by the selected semantics, independent of F09's later rollout. Test emoji/non-BMP, canonical newline offsets, type/range boundaries, expected-text mismatch, stale guards, overlaps, sequential shifts, insertion policy, atomic rejection and old/new/unknown profile decoding. Verify live persistence, retry recovery, replay and real stdio.

## Phase D2: F09 guarded whole-target replacement

Record the architecture extension and amend AGENTS.md/current contracts. Regeneration/proposal generation stays with the host; this is an explicit low-level replacement operation through the same locked submit path and pure applier.

- Use a versioned explicit operation such as replace_all, never an empty-MATCH workaround.
- Require a hash or version guard; no match_only exception.
- It is the sole operation in its transaction. Reject mixing with match/span/another replacement operation before mutation.
- Define real replacement-input UTF-8 byte/code-point and resulting-target limits, boundary behavior and the admission point. Read/search output caps are not these limits. Any proposed transport-wide cap also needs an explicit old-request recovery compatibility policy; do not silently broaden admission changes.
- Valid admitted operations produce the normal runtime facts and one accepted ledger entry. Invalid Unicode and admitted rejections retain the shared audited behavior. Document pre-admission oversized-request errors separately.
- A separate immutable replay profile is allowed. Preserve all earlier profiles and supported operations; do not retrofit replacement semantics into an already-used F07 profile.
- Test empty target/replacement, size boundaries, mixed-operation rejection, atomicity/caller rollback, keyed recovery, replay and actual stdio. Extend offline_eval.py with payload bytes only, without usability claims.

## Phase E: F11 advisory preview

Record the decision before code: zero preview audit, no request-key parameter or consumption, and no persistent mutation of any managed table. Do not expose a dormant preview-audit option.

Reuse pure validation/application and shared read-only preflight rules without building a second submit engine. Return verdict, reached stage, failed change if any, accepted-preview derived facts and the coherently observed target version/hash. Preserve existing rejection-fact semantics: no new partial staged facts on rejected previews unless that public contract is separately approved for both submit and preview.

Never implement preview as submit-then-rollback, commit a caller transaction, reserve a version or create target/current-PDCP/log/ledger/cycle/snapshot state. A subsequent submit takes its usual lock and rechecks all guards. Define the observation boundary and avoid unnecessary writer blocking.

Parity means the same observed state, operation/profile and fresh submission, not the cached outcome of an old keyed request. Test accepted and rejected parity, all relevant table row/content deltas on PostgreSQL, caller ownership, unknown/invalid input, and one actual stdio case. Use a monotonic version guard for the change-between-preview-and-submit stale-rejection test; hash-only ABA retains its existing limitations.

## Deferred decision register

### F02: guard-optional textual edits

Do not implement in this goal. Reopen only for a concrete host need and explicit adoption decision. If adopted later: explicit match_only opt-in for textual match edits only; strict default remains; persist the mode and include it in request identity; check every supplied guard; amend AGENTS.md/C1/schema/host guidance; preserve historical decoding; verify stale/ABA/concurrency cases. Span and whole-target edits always require guards.

### F04: normalized fingerprint identity

Do not implement or add its migration now. PR #9 documents the current identity and remains valid. A separate future PR must define a durable fingerprint-strategy discriminator, old-row dispatch, unknown-version refusal, new normalized identity hash distinct from the unchanged raw audit-content hash, and selected-field normalization. Keep intent/advisory prose/guards/selectors/parent identity unchanged and retain raw evidence. Old rows recover under their original strategy without rewrite; LF/CRLF equivalence would apply only to the explicitly adopted strategy. Require compatibility and migration/downgrade tests if a schema change is chosen.

F10 editing adapter is similarly deferred beyond its accepted read-only helper. Record all deferrals as decisions, never as implemented features or evidence closures.

## Cross-cutting documentation and release verification

Update relevant architecture decisions, tools/list schemas/examples, MCP_TOOLS, HOST_INTEGRATION_GUIDE, DATA_MODEL where changed, skills and MODERNIZATION_CHANGE_DOC with each feature. Maintain the format/profile compatibility matrix and replay fixtures for 0.2.2 and every introduced profile. No speculative fingerprint-version table or migration while F04 is deferred.

V02 (representative migration rehearsal) and V04 (replay lock/content/history/writer-wait benchmark, including F09) remain named checks. Before relevant work, establish whether representative sanitized data or a suitable benchmark environment and meaningful acceptance criteria are available. If so, record scope/baseline/thresholds and make the check required before the relevant release. Otherwise document the limitation and available synthetic evidence without claiming a pass. Environment availability alone is not a pass criterion. Automated populated migration tests remain mandatory for any actual migration, even if V02 representative data is unavailable; no F04 migration is part of this goal.

## Completion and report

- Nine accepted feature implementations verified, and F08/F13/F14 closed with actual remediation evidence on the consolidated base.
- F02/F04 explicitly deferred with rationale/reopening criteria; F10's optional editing adapter also deferred. No false claim of fourteen implemented features.
- Each PR carries its decisions, contracts, code, appropriate tests, separate manual live evidence and an independent ten-category review with P1/P2/P3 headings.
- Record green head and generated-merge CI, actual executed SHAs/run IDs, and the final integrated base/release result. Never infer executed code solely from a green badge.
- Keep 0.2.2, old valid-input hashes/fingerprints/profiles, parent-identity policy and protected review hashes unchanged. Preserve exact historical recovery and transaction ownership.
- Report each F-ID as implemented, closed-with-evidence or deferred, with PR/fix/executed SHAs, decisions, introduced protocol/profile IDs, changed files, tests/results and remaining limits. List no new fingerprint strategy because F04 is deferred.
- Implementation choices within the approved scope are settled in pre-code decision records. Report scope/invariant changes for resolution instead of silently broadening the goal. Merge approval remains a separate prerequisite.

## Disposition reconciliation

Kept: F01 fresh-versus-original evidence; F02 textual-only decision gate; F03 opt-in correlation-only scope; F04 deferral; F06 truncation without cursor; mandatory span guards; sole-operation F09; read-only F10 early delivery; zero-audit/keyless F11; executable bounded F12 examples; evidence closure for F08/F13/F14; separate immutable profiles; explicit authority amendments; and merging remediation/PR #1 before starting from main once authorized.

Revised: the disposition's feature count to nine implementations/three closures/two deferred items; F05's timing to actual lock release rather than merely after the core verdict, with explicit omission for caller-owned transactions; and V02/V04 gating to require defined representative inputs and acceptance criteria. This replaces conflicting instructions in the previous Goal F proposal. The disposition itself remains unchanged.
