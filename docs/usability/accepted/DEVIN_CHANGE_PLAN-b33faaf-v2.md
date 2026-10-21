# Devin review: item-by-item change plan

Date: 2026-10-20
Plan revision: 2 — incorporates the user's supplied Devin critique; supersedes the initial plan for future work. The initial file and original reports remain preserved.
Repository: paragon-ux/Patch-DIFF
PR: [#1](https://github.com/paragon-ux/Patch-DIFF/pull/1)
Branch: feature/modernization-argon-remediation
Inspected head: b33faaf332e269019747772602afff34f9829e5c
Review-standard reference: docs/PR_REVIEW_STANDARD.md, version 1.1.0

## Scope and conclusions

This is a remediation and feature-change inventory for all three supplied Devin reports, not a new whole-PR approval or an implementation. The original reports remain unchanged:

- [The good](devin_review-the_good.md): existing capabilities, limitations, and 14 feature suggestions.
- [The bad](devin_review-the_bad.md): verification risks, four idempotency concerns, five unverified questions, and ten preventive actions.
- [Bugs and flags](devin_review-bugs-and-flags.md): three bugs and three flags.

Repeated items share one plan ID below. Six concrete fixes are warranted: DEV-RUN-001, DEV-RUN-002, DEV-DB-001, DEV-MCP-001, DEV-MCP-002, and DEV-SVC-001. DEV-SVC-002 is a narrower parent-ID consistency issue than Devin describes and needs a compatibility decision. The LF/CRLF fingerprint difference follows the current full-record identity contract; changing it is a feature/contract decision, not an automatic bug fix. Most usability suggestions are optional extensions.

Evidence: current source and contracts were inspected; an independent default-model subagent triaged the candidate defects and ran focused pure-function/fake-session reproductions. These confirmed singleton selector acceptance, pre-database surrogate failure, negative-context acceptance, and the distinction between valid and invalid parent lineage. Other conclusions below are source-derived. No new successful live-PostgreSQL reproduction, full-suite run, CI recheck, or production-data migration rehearsal is claimed in this inventory. An attempted rollback-only live probe was interrupted without a result and is not acceptance evidence. Earlier test/review records are historical evidence at their recorded revisions.

All items remain open as implementation work or decisions unless expressly classified as already implemented or no change required. Nothing is closed merely because a plan or regression case exists.

## Revision 2: disposition of Devin's six adjustments

The accepted corrections to Devin's original review still stand: valid parent UUIDs are canonicalized, full-record request identity is specified by C4, the response uses deduplicated:true, and request IDs need not be UUIDs. This revision directly rechecked the response field and request-ID regex as well as both history implementations. It does not claim new runtime or live-database execution.

| Adjustment | Disposition | Resulting scope |
| --- | --- | --- |
| 1. Bump the runtime profile once | Accept with a release boundary | Group selected replay-affecting semantics into one new profile before it writes durable history. Do not bump per finding, delay the selector fix for optional features, or redefine a profile after it has written logs. Service errors, paging and health reporting do not automatically need execution-profile bumps. Fingerprint versioning is a separate identity concern. |
| 2. Unicode escape hatch and read/search scope | Revise | First choose the smallest safe, reversible audit representation in the existing rejected-attempt storage. Keep audited known-target rejection as the default. An unaudited structured error is a possible explicit change to the locked audit guarantee, not equivalent to deduplication and not implicitly authorized by this plan. Include UTF-8 validation policy for search text and other read/search string inputs; reads return invalid_argument without becoming edit-attempt logs. |
| 3. Rate-limit conflict rows | Revise | Keep one immutable row for each admitted conflicting submission. Do not silently collapse/cap audited attempts or mutate counters on append-only rows. Specify admission/resource controls separately, before the audited submit path, and explicitly describe any pre-admission rate-limit exception. A per-key cap alone is bypassable with new keys and also risks suppressing evidence. Rate limiting is not a prerequisite for correcting the existing missing audit row. |
| 4. Fix history ordering | Reject the behavior change; accept clarification | Current architecture C6 and MCP_TOOLS explicitly specify newest-first attempts and oldest-first presentation within a newest-selected ledger page. Preserve compatibility and document both; standardize continuation fields and exclusive cursor semantics, not display order. |
| 5. Tier acceptance criteria | Accept with retained DB checks | Exhaustive edge matrices run at the pure/service layer. Use representative live PostgreSQL/real stdio cases for the high-risk fixes; V01 requires real concurrent connections. Raw stored-content integrity and SQL pagination also need representative PostgreSQL verification. DEV-MCP-001 does not need a separate DB/subprocess case for every invalid value. Existing live-suite requirements remain in force. |
| 6. Keep delivery small | Accept | Each defect workstream gets its own coherent PR with contracts, implementation, tests and evidence. Share utilities only where actually needed. Preserve an evidence-backed independent recheck for each PR. This plan revision does not open or merge PRs. |

F01 and F12 remain the first optional usability candidates. Their acceptance criteria do not expand into F07's new span protocol or F11's preview API.

## 1. Confirmed defects and the parent-ID edge case

### DEV-RUN-001 — P1: enforce selectors on singleton matches

Source: [disambiguation.py at inspected head, lines 33–38](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/pdcp/disambiguation.py#L33-L38).
Categories: RUN, DB, ARCH, TEST.
Devin references: Bug 1; repeated severe finding; “Reject contradictory selectors”; preventive action 1.

Trigger/actual: target “hello”, match “hello”, occurrence_index 2 still selects the only occurrence. Nonmatching before/after anchors are likewise bypassed by the singleton early return. This can apply a proposal that explicitly excludes the selected location.

Necessary changes:

1. In resolve_match_span, apply supplied selection constraints for zero, one, and multiple occurrences. Preserve the ordinary singleton/no-selector success case. A valid index plus an excluding anchor must reject; selectors combine as constraints, not alternatives.
2. Keep the documented anchor semantics: anchor_before searches before the match and anchor_after after it. Do not silently change these to adjacency while fixing the early return.
3. Extend the execution profile in backend/app/core/versions.py and its dispatch through applier/submission/replay. Record one new profile for the selected replay-affecting changes in the release, rather than one version per finding. Freeze its behavior once it writes durable history; later semantic changes then require another profile. Do not hold this P1 fix for optional features merely to save a version. Old accepted logs may contain selectors the old runtime ignored; replay those with their recorded behavior. The existing overlap-only profile flag is insufficient to express this additional semantic difference. Paging, audit-error handling and materialized health checks do not themselves alter historical edit execution.
4. Update the core spec, architecture/profile table, typed/legacy host examples, and change record. Do not edit historical review evidence to claim the old behavior was fixed then.

Acceptance: a matrix of absent/single/multiple/overlapping matches with no selector, valid/invalid index, each anchor, and combined contradictory selectors; typed and legacy submissions; sequential edits where the relevant buffer has already changed. Live known-target rejection must append one rejected attempt, with no target/version/ledger change. Add an old-profile fixture containing an accepted ignored selector and prove unchanged replay; prove the new profile rejects it. Unknown profiles must still fail closed.

### DEV-RUN-002 — P2: reject invalid Unicode with durable audit evidence

Sources: [typed.py canonical serialization](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/pdcp/typed.py#L170-L176), [pdcp_service.py pretransaction hashing](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/services/pdcp_service.py#L217-L239).
Categories: RUN, SVC, DB, MCP, TEST.
Devin references: Bug 2; idempotency issue 4; preventive actions 3 and 8.

Trigger/actual: a JSON string containing a lone surrogate reaches ensure_ascii=False serialization, then UTF-8 hashing raises before target resolution/locking and audit persistence.

Necessary changes:

1. Validate Unicode scalar/UTF-8 encodability before normal hashing/storage, including match, replace, anchors, intent, rationale and other user strings, not just replacement text. Cover equivalent legacy inputs where applicable.
2. Before implementation, choose and document the smallest deterministic, reversible invalid-input representation that can itself be hashed and stored safely. Prefer an ASCII-escaped evidence string and small explicit diagnostic marker in existing rejected-attempt fields if that satisfies the contracts; do not assume a new transaction protocol, table or general encoding framework is necessary. Escaped textual evidence or an explicitly encoded diagnostic envelope must preserve the offending escape/code point without placing a surrogate in PostgreSQL text/JSONB. JSONB also rejects an escaped unpaired surrogate interpreted as a JSON string; ensure_ascii=True alone is not a complete persistence fix.
3. Route a proposal for a resolvable target to the ordinary audited domain rejection under the established transaction ownership rules. Select/document the existing appropriate failure reason and stage, or explicitly extend the public failure contract. Preserve raw evidence without replacement encoding or silent correction.
4. Specify request identity/retry behavior for invalid input and compatibility with existing stored fingerprints. Keep valid-input hashes unchanged unless deliberately introducing a versioned identity scheme.
5. Catch anticipated validation/encoding failures at the appropriate service boundary. Moving every operation inside a transaction or converting every exception to rejection is insufficient and would mask infrastructure failures.
6. Define the same valid-Unicode input boundary for read/search strings, particularly find_occurrences.text, with an invalid_argument result and safe transport serialization. Reads are not edit submissions and do not require rejected-attempt rows. Test the service and adapter behavior; this extension is boundary hardening, not a claim that search currently has the same hashing crash.

Escape-hatch decision: retain durable rejection for a known target as the baseline. If a safe small representation proves unsuitable, propose a separately documented pre-validation/no-log exception with an explicit error code and evidence that no target/log/ledger mutation occurred. That alternative must explicitly amend AGENTS.md's locked audit invariant and affected architecture/data-model/host contracts before adoption; merely documenting it in this plan would not reconcile the guarantee. Exact dedup recovery already has a durable original attempt, whereas dropping an invalid first submission loses its only attempt evidence.

Acceptance: unit coverage for isolated high/low surrogates in each relevant field and nested input, normal non-ASCII and supplementary characters, and decoding of escaped JSON. Representative live PostgreSQL and real stdio submissions must return a domain rejection rather than a generic tool error, persist readable safe evidence, and leave target/version/ledger unchanged; the complete field matrix can remain at the pure/service layer. Verify request-key retries and caller-owned commit/rollback. Do not declare closure from pure Python tests alone.

### DEV-DB-001 — P2: expose noncanonical materialized storage during replay

Source: [replay_service.py, lines 216–221](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/services/replay_service.py#L216-L221).
Categories: ARCH, DB, DOC, TEST.
Devin references: Bug 3; normalization postmortem.

Trigger/actual: materialized current_content changes from LF to CRLF while canonical hash/version remain unchanged. Replay canonicalizes the stored text before comparison, so its component checks can all pass.

Contract qualification: PATCHDIFF_CORE_SPEC.md currently explicitly defines content_matches using canonicalize(target.current_content), so the implementation follows that local formula. The stronger canonical-LF storage invariant calls for reconciling the specification and implementation together; this is not solely a coding mismatch.

Necessary changes:

1. Record the integrity decision in architecture C3 and amend the core replay formula. Compare raw stored current_content with the canonical reconstructed buffer for content_matches.
2. Make noncanonical storage observable through that check or a separately specified canonicality check. If adding a response field, update every documented/schema/test consumer.
3. Keep canonical target hashing unchanged for normal content and all historical logs. Do not replace the shared canonical_sha256 function with a raw-byte hash. A separate raw-byte integrity metric, if desired, needs a distinct name and purpose.
4. Preserve the distinction between successful history reconstruction and materialized_state_matches=false. Corrupt materialized state need not make reconstruction itself fail; replay must not silently repair storage.

Acceptance: live rollback-isolated corruption cases for CRLF and bare CR, ordinary Unicode content corruption, hash-only and version-only corruption, plus a healthy canonical target. Assert individual component checks and aggregate health, original historical hashes, and no replay mutation.

### DEV-MCP-001 — P3: reject invalid context_chars explicitly

Source: [read_service.py find_occurrences](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/services/read_service.py#L143-L190).
Categories: MCP, RUN, DOC, TEST.
Devin references: Flag 1; “Reject bad arguments clearly”; preventive action 1.

Necessary changes: validate context_chars as a non-boolean integer >= 0 before querying/report generation. Return the established invalid_argument response for negatives and invalid types. Retain the intentional upper context cap of 400; do not confuse resource capping with accepting negative values. Align tools/list schema minimum/type, Python/MCP entry points, and C6/MCP documentation.

Acceptance: service-level negative, bool, string, float, zero, normal and above-cap cases, plus the read/search Unicode policy introduced under DEV-RUN-002. Verify direct tool routing and schema minimum/type statically or with focused adapter tests. Zero remains valid and above-cap behavior stays documented. Read failures must not mutate target or history. No separate live PostgreSQL or real stdio run is required for every argument value; retain the normal repository live/stdio workflow checks for the integrated release.

### DEV-MCP-002 — P2: complete attempt-log continuation metadata

Source: [tools.py attempt history](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/mcp/tools.py#L237-L310).
Categories: MCP, ARCH, DOC, TEST.
Devin references: Flag 2; “Consistent pagination”; preventive action 7.

Contract: architecture A5 explicitly promises has_more and next_sequence for both history tools. The attempt-log response and the narrower C6/tool description omit them. Reconcile these surfaces to A5. Ordering is already intentional in C6 and MCP_TOOLS: attempts display newest-first; the ledger selects the newest eligible page and reverses that page for oldest-first display. Preserve both existing orders. Consistent metadata does not require identical presentation order. Source: [ledger page reversal and cursor calculation at inspected head](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/mcp/tools.py#L377-L405); architecture C6 and MCP_TOOLS history sections agree.

Necessary changes: fetch effective_limit + 1 after applying existing target/status/cursor filters; return at most effective_limit rows newest first. has_more reports an additional matching row. next_sequence is the smallest returned log_sequence only when another page exists; otherwise null. For the ledger, continue using the smallest selected ledger_sequence regardless of display position. Example for limit 3 over sequences 1..10: attempts return [10,9,8], ledger returns [8,9,10], and both next_sequence values are 8. Passing before_sequence=8 selects the next older page; ledger then displays [5,6,7]. Pages traverse backward even though the ledger displays each individual page ascending. Use the exclusive before_sequence cursor. Include consistent empty continuation fields on empty/not-found/invalid responses as defined for the sibling ledger tool. Preserve default 50, cap 200, and bounded content behavior. Align docs and response contracts; a small helper is optional, a generic pagination framework is unnecessary.

Acceptance: cover no rows, one row, exact limit, limit+1, several pages, filtered pages, sequence gaps, invalid limit/cursor types, and inserted newer rows between requests with focused service/response tests. Run representative actual PostgreSQL multi-page queries for both tools; assert display order and traverse using the smallest-sequence cursor with no duplicates/skips. Include a shared real stdio history smoke scenario rather than duplicating the complete matrix through the subprocess.

### DEV-SVC-001 — P2: audit fingerprint-conflict rejections

Source: [pdcp_service.py conflict return, lines 364–388](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/services/pdcp_service.py#L364-L388).
Categories: SVC, DB, ARCH, DOC, TEST.
Devin reference: idempotency issue 1; preventive action 4.

Trigger/actual: reuse a target/request key with a different fingerprint. The service rejects with pdcp_log_id=None and writes no attempt. C4 prohibits overwriting the original row; that does not prohibit a separate null-key rejection. The general rejected-attempt audit invariant warrants closing this gap.

Necessary changes: append a normal rejected attempt with client_request_id=NULL, retain submitted_client_request_id and existing_pdcp_log_id as safe diagnostic evidence, and return that rejection's log ID. Keep the original keyed row and fingerprint untouched; it must remain the outcome recovered by its original request. Reuse the locked rejected-attempt persistence path, with no target/accepted-ledger mutation. Specify repeated-conflict audit behavior and the null-key row's fingerprint policy. Baseline: every separately admitted conflict creates its own immutable null-key rejection; no per-key collapse/cap and no update/delete of prior rows. Bound diagnostic previews and enforce any approved proposal-size limit before admission while preserving the complete admitted audit payload. Separately document deployment admission/rate controls for submissions as a whole (using available trusted caller identity, target/global limits as appropriate), not a bypassable conflict-key-only rule. If throttled requests receive no attempt row, make that a precise pre-admission exception with a structured response, documented counting/window policy and operational telemetry; do not silently weaken the existing audit rule inside this fix. Such controls are a separate bounded operational work item, not a blocker for restoring conflict audit.

Update architecture C4, data model/audit documentation and host guidance. Existing tests that explicitly expect no extra conflict row must change along with the recorded decision; do not relabel those prior passing tests as proof of the new policy. Leave historical reports immutable.

Acceptance: live original acceptance, conflicting reuse, recovery of original payload after conflict, and conflicts against originally rejected requests. Assert row delta, null-key uniqueness compatibility, diagnostic linkage, complete response fields, unchanged target/version/ledger, concurrent conflict ordering, repeated identical conflicts producing distinct null-key attempts, and rollback semantics. Use service tests for the exhaustive field matrix and representative live PostgreSQL/real stdio cases for durability and transport. Exact deduplicated recovery of the original request remains the documented no-new-row exception.

### DEV-SVC-002 — P3 advisory/decision: normalize syntactically valid parent UUIDs consistently

Source: [fingerprint parent selection](https://github.com/paragon-ux/Patch-DIFF/blob/b33faaf332e269019747772602afff34f9829e5c/backend/app/services/pdcp_service.py#L340-L350); _resolve_parent_log in the same module.
Categories: SVC, DB, ARCH, TEST.
Devin reference: idempotency issue 3; preventive action 8.

Correction: a valid same-target rejected parent already resolves to canonical str(UUID), so uppercase/lowercase valid-parent submissions do not establish Devin's general claim. A syntactically valid UUID that fails lineage validation (missing, accepted, cross-target) falls back to raw input for fingerprinting, allowing casing to change the identity of a rejected request.

If adopting consistent identifier identity, parse/canonicalize syntactically valid parent UUIDs before fingerprinting, separately from checking lineage eligibility. Preserve the raw submitted value in safe diagnostics, invalid-parent null FK behavior, and rejection semantics. Do not normalize malformed arbitrary text or accidentally accept an ineligible parent. Design lookup compatibility for already-stored rejected-request fingerprints before changing new fingerprints.

Acceptance: upper/lower spellings for valid, missing, accepted and cross-target parents; malformed IDs; fresh/retried keys; legacy stored rejected fingerprints. A retry must recover the correct original rejection rather than becoming a false conflict. Treat this as narrower lower-impact work, not evidence the normal parent path is broken.

## 2. All 14 usability suggestions from “the good”

These are design choices, not a directive to implement all extensions in PR #1. Existing correctness fixes above should not depend on approving new protocol features.

| ID | Devin suggestion | Classification and necessary changes | Acceptance / limits |
| --- | --- | --- | --- |
| F01 | Fresh state on rejection | Partly available: submission results already carry current hash/version. Expose those consistently in public responses/examples; optionally add bounded current-target snippets through pdcp_service.py and tools.py. Specify response fields in C1/C6/MCP_TOOLS and host guide. | A coherent version/hash/snippet from the locked state; strict size cap. A missing match has no exact failed span. A failure after earlier staged edits concerns an intermediate buffer: label it clearly, never present it as committed current content. No unbounded full-target rejection payload. |
| F02 | Optional guards / hash-only strict mode | Hash-only or version-only guards are already supported. Omitting both would change C1's required optimistic concurrency guarantee. If explicitly selected, define a separate mode/contract, schema, failure behavior and host guidance before altering typed validation/service guards. Retaining at least one guard is the recommended baseline. | Demonstrate stale/ABA/concurrent cases and explicit weakened guarantees. Exact text alone does not establish that the host observed the current target. Preserve stricter existing clients and historical decoding. |
| F03 | Server-generated request ID | UUID generation is unnecessary: current IDs accept 1–128 printable non-whitespace ASCII characters. Optional server correlation IDs are feasible, but cannot recover a lost first response if the caller never learned the generated key. Prefer host/SDK generation before first send for recoverable retries. | If added, specify optionality/schema, return key, collision handling and retry limits. No claim of first-response-loss idempotency without a caller-known key. Preserve per-target uniqueness and old-key recovery. |
| F04 | Normalize line endings for matching and fingerprints | Matching already canonicalizes LF/CRLF. Fingerprint normalization is an optional identity change; see D01 below. Do not add redundant matching normalization or call the current identity a proven bug. | Existing CRLF/LF matching coverage; explicit versioned fingerprint policy and old-key lookup compatibility if identity changes. No historical hash rewrite. |
| F05 | Near-miss diagnostics | Optional diagnostic feature, separate from deterministic exact application. Add a bounded diagnostic helper/service response for MATCH_ABSENT and document deterministic tie breaking, maximum input/work/candidate size, and diagnostic-only status. Keep fuzzy selection out of the applier. | Whitespace-only/nearby/distant cases, no near candidate, large target limits. A diagnostic must never authorize application or imply an exact match. No host/model loop inside the runtime. |
| F06 | Ambiguity candidates in rejection | Search already returns paged exact occurrences. Optionally attach bounded occurrence_report-style candidates to ambiguous submission diagnostics, including occurrence index, code-point span and context. Specify a continuation/search route instead of “every occurrence” unbounded. | Cap candidates (reuse the search bound of 200 or an explicitly smaller response bound). Include truncation/cursor and buffer-stage identity. Later edits may fail against an intermediate sequential buffer; indices from the original target cannot be reused blindly. |
| F07 | Span-based edits | New typed protocol capability, not merely an alias for occurrence_index. Define start/end as code points, end exclusive, exact expected_text, guards, and whether spans refer to the original or sequential buffer. Define mixed span/match/selector rejection. Extend schema, parser/lowering, pure applier, derived facts, ledger/replay profiles and docs. | Emoji/non-BMP, normalized newlines, boundaries, empty/insertion semantics if supported, stale guards, overlapping edits and sequential shifts. Never trust a stale search span without expected-text and target-state validation. Preserve old format decoding. |
| F08 | Reject contradictory selectors | Required fix DEV-RUN-001, not optional enhancement. | Singleton and historical-profile acceptance criteria above. |
| F09 | Whole-target replace / full write | Optional architecture extension beyond the current targeted-edit boundary. A full nonempty MATCH can already express a whole-content replacement at high payload cost. A dedicated guarded operation needs an explicit decision and versioned transaction representation, not an empty-MATCH hack. Update schema, pure application, derived facts, audit, replay and host docs. | Explicit hash/version protection, empty target, resource limits, atomicity, request retries, full replacement replay and payload measurement. Keep regeneration/orchestration with the host. Do not assume a new service can bypass the shared locked submission path. |
| F10 | Range/line helpers | Optional adapter to an approved span operation (F07), or a helper returning exact text/spans for existing edits. Specify line numbering, inclusive/exclusive end, newline inclusion, final empty line/EOF, code points versus bytes/UTF-16, and canonical LF behavior. | CRLF input, Unicode, empty lines/targets, EOF and out-of-range cases. Convert against the guarded target state and revalidate exact expected text; no unchecked line offsets. |
| F11 | Dry run / validate_only | New advisory validation API. Factor/reuse pure validation and application; return verdict/facts and the observed target identity without updating target/version or writing accepted logs/ledger. Define whether separate audit is desired and how it is distinguished. Do not consume a real submission request key. | No persistent mutation, no commit of a caller-owned transaction, invalid and accepted previews, derived-fact equivalence. A later real submit must reacquire state and recheck guards; preview does not reserve a version or promise later acceptance. Avoid “execute then rollback” as the public abstraction. |
| F12 | Worked examples in tools/list | Low-risk discoverability improvement. Add short actual accepted JSON and representative rejection/retry examples to external_adapter.py schemas/descriptions; reconcile MCP_TOOLS and HOST_INTEGRATION_GUIDE. Show one guard, selectors, valid request IDs, pagination and exact retries. | Parse/execute representative examples through real stdio; assert actual fields and outcomes, not just example-string presence. Examples must follow schema nullability and bounds and remain short enough for discovery. Do not claim measured model success from adding examples. |
| F13 | Consistent history pagination | Required fix DEV-MCP-002. | Continuation, filtering and bounded live traversal above. |
| F14 | Clear errors for negative context | Required fix DEV-MCP-001. | Invalid-type and boundary checks above. |

### D01 — Fingerprint identity decision (Flag 3 and idempotency issue 2)

Current architecture C4 specifies a fingerprint including protocol, target, the complete canonical-record content hash, guards and parent identity. Intent/rationale and raw field values therefore matter. A changed intent or changed LF/CRLF inside a string is a changed request record even when the resulting edit would be the same. JSON key order and insignificant serialization whitespace are canonicalized, so “the wire bytes must be identical” is too broad.

Necessary baseline change: make this contract easy to find in DATA_MODEL and HOST_INTEGRATION_GUIDE, link to authoritative C4, and demonstrate preserving the original record, guards and key on recovery. Correct the report's characterization of request identity as unspecified.

Optional alternative: deliberately define normalized identity for selected edit-text fields and introduce a versioned fingerprint strategy with old-row recovery. Preserve raw audit evidence and original recorded intent. Do not normalize IDs/prose/entire serialized JSON indiscriminately or drop intent solely because it does not change target bytes: that could recover one proposal under another proposal's audit narrative. If adopting the alternative, test same-key LF/CRLF, changed intent, key ordering, guards, selectors and historical fingerprints. This decision is independent of raw-storage integrity in DEV-DB-001.

## 3. Existing “good” features: preserve, verify, and correct descriptions

No replacement implementation is necessary for these existing capabilities. New changes must preserve them.

| Existing feature described by Devin | Required handling |
| --- | --- |
| Typed patchdiff-tx/1 plus frozen legacy PDCP | Preserve shared ParsedPDCP/applier behavior, typed origin and legacy parsing. Extend through a versioned profile when semantics change; do not fork independent submit engines. |
| Overlapping matches; old nonoverlapping replay | Current submissions count overlaps. Runtime 0.1 history retains nonoverlap; supported 0.2 history retains overlap. See V03 for caller compatibility. |
| Server-derived spans/lengths/hashes and staged validity | Preserve computed facts and failed stage/change IDs across accepted, rejected and recovered outcomes. F07/F09/F11 must reuse this mechanism. |
| Target locking; atomic target/log/ledger write | Preserve one locked service path, transaction ownership and rollback. Verify V01/V06/V07 rather than adding speculative catch-all database handling. |
| Idempotent recovery before guards | Preserve original terminal outcome after subsequent edits, ABA and no-op edits. The actual response field is deduplicated:true, not idempotent_replay. Only exact recovery is a no-new-attempt exception. |
| Typed ledger migration, origin/derived JSON, nullable prose, partial unique key, downgrade refusal | Already implemented. Preserve typed-row downgrade refusal and existing indexes/FKs. Extend tests only for an actual schema change; V02 covers release rehearsal. |
| Bounded target reads and exact occurrence search | Already implemented with code-point offsets, context and paging; search responses are bounded, not all matches in one unbounded response. F05/F06 are optional diagnostics; DEV-MCP-001 is the input fix. |
| Bounded log/ledger reads | Limits exist. Complete attempt-log continuation with DEV-MCP-002; do not imply both currently have identical metadata. |
| stdio tool discovery and non-object parameter rejection | Preserve typed input schema and JSON-RPC -32602 behavior. Domain failures remain distinguished from malformed RPC parameters. |
| Versioned replay and materialized checks | Preserve unknown-profile refusal and historical decoding. DEV-DB-001 strengthens raw-storage health; DEV-RUN-001 requires a new semantic profile. |
| SAVE/export UUID checks and deprecated guarded regeneration wrappers | Already implemented; keep host ownership of regeneration and wrappers forwarding guards through the shared path. No separate regeneration engine is needed. |
| Unit/live DB/migration/stdio tests, locked CI dependencies | Preserve these layers. Existing tests are not proof of the newly identified edge cases; add focused live regressions and pin evidence to the future fix SHA. |
| Offline payload-size/verdict evaluator | Preserve reproducibility and bounded claims. It measures bytes/verdicts, not agent usability, reliability superiority or token/latency savings. Agent comparisons need a separate controlled evaluation if wanted. |
| Architecture, skills and host documentation | Reconcile only affected active contracts/instructions with implemented decisions. Preserve historical reports; do not let polished summaries substitute for execution evidence. |

Additional wording corrections: version and/or hash is required, not both simultaneously; request IDs need not be UUIDs; exact matching remains case/whitespace sensitive but target-text line endings are canonicalized. Historical runtime 0.2.0 accepts its recorded permissive key rules while current 0.2.1 is stricter. Do not extrapolate those key-validation rules to all replay profiles.

Devin's claim that nobody performed a full review is not a reliable inventory of the repository's existing category reviews. Those reports still do not establish absence of these particular defects. Likewise, comparative claims about other diff tools and model training/usability were not verified by this task and should not become release claims without evidence.

## 4. Risks and unverified idempotency questions from “the bad”

These are verification work, not automatically additional production bugs.

| ID | Source item | Necessary work and acceptance |
| --- | --- | --- |
| V01 | Concurrent duplicate requests; practical merge bar; preventive action 6 | Add a deterministic real-PostgreSQL test with two independent connections/sessions submitting the same target/key/payload concurrently. Synchronize so the second waits while the first owns the lock, then commit the first. Assert one target/version transition, one keyed attempt, one ledger entry and recovery of the same original outcome with deduplicated=true. Exercise accepted and rejected original outcomes and a conflicting-payload case. Set bounded timeouts; no sleeps as the only evidence of overlap. Include a real adapter path where practical. Existing sequential retry/lock tests do not prove this exact interleaving. |
| V02 | Migration on representative data | Existing populated legacy upgrade/downgrade round trips and typed-row refusal tests already cover more than empty fixtures. If representative data is available, rehearse on an isolated sanitized copy and compare IDs, counts, hashes, lineage, cycles, snapshots and sequences, with replay after supported transitions. Test legacy-only downgrade then re-upgrade; typed data must refuse downgrade. Never use an active application/shared database for a destructive rehearsal. No production copy was supplied, so this remains an environment/data-dependent release check, not a proven migration defect. |
| V03 | Changed overlapping semantics | Keep overlap semantics explicit in release notes, MCP/host examples and real legacy-caller fixtures. Test a repeated string with overlapping occurrences so the changed index is visible. Replay recorded 0.1 with nonoverlap and supported 0.2 with overlap. Do not revert the current matcher or apply new semantics to old logs. The singleton selector fix needs a distinct semantic setting in the selected new profile, not reuse of the overlap flag; it need not get a separate version from other changes selected before that profile writes durable history. |
| V04 | Replay blocks writers for long histories | The lock is an intentional consistency decision, not a demonstrated performance defect. Benchmark realistic content size, accepted-log count and proposal size, plus writer wait/timeout and cancellation. Record acceptable bounds before optimizing. Any checkpoint/snapshot/range optimization must preserve a coherent input cut and detect relevant corruption; simply removing the lock is not a safe fix. |
| V05 | PR size, author-produced evidence, green CI | Check exact-head or generated-merge SHA for live DB and stdio CI after fixes; retain immutable regression output and independent recheck. Use coherent bounded follow-up PRs or stacked changes with explicit dependencies. Runtime/contract/migration/docs for one behavior must remain mutually valid; splitting solely by file type can produce broken intermediate states. Author JSON reports are evidence claims to verify, not independent approval. |
| V06 | Isolation level unverified | DB engine setup has no explicit isolation override; the actual deployment/session isolation was not verified here. Establish/document supported isolation and test the real configuration. READ COMMITTED supports the intended lock-then-read recovery design; stronger isolation can require transaction-level retry/error handling. Define SQLSTATE 40001/40P01 handling at the transaction-owner boundary if supported; do not retry an arbitrary caller-owned transaction or assume every IntegrityError means duplicate recovery. |
| V07 | Caller-owned outer transactions | The service intentionally does not commit the caller's transaction; this is already documented/tested, not a new bug. Verify visibility, commit, rollback, lock lifetime and duplicate behavior using two connections. Explain that a returned service acceptance is provisional until the outer owner commits, and the owner must end transactions promptly. Do not “fix” this by committing someone else's transaction. |
| V08 | Other insert paths / no IntegrityError catch | Current production accepted/rejected AppendOnlyPdcpLogs insertion sites are in the shared locked service path; no unlocked production writer was established. Preserve this invariant and inspect future entry points/direct database permissions. A speculative blanket IntegrityError catch with rollback could hide real failures or corrupt caller-owned transaction handling; it is not required from the evidence. |
| V09 | Reconstructed response completeness | The recovery path already restores accepted ledger-derived facts and rejected diagnostic/stage data. Add targeted field assertions for the original before/after versions, hashes, validity, facts, failed change, diagnostic and log ID across later target changes. Current-state metadata may legitimately refresh while the original outcome remains fixed; do not require literal whole-response equality. No missing-derived-facts defect was demonstrated. |

The four practical success criteria in Devin's report map to V05 (CI), all defect acceptance cases (regressions), V01 (simultaneous duplicates), and V02 (representative migration rehearsal). They are a useful bar, not a guarantee of no remaining issues or a substitute for the repository's ten-category review.

## 5. All ten postmortem preventive actions, corrected for current contracts

| Action | Necessary change |
| --- | --- |
| 1. “Reject, never coerce”; selector/match-count matrix | Add explicit contradictory-selector and invalid-argument rules to the core/public contracts and implement DEV-RUN-001/DEV-MCP-001. Keep intentional resource caps, target normalization, and historical replay behavior. A universal ban on all coercion/normalization would contradict existing valid behavior. |
| 2. One canonicalize function everywhere | Retain the shared target-text LF helper. Document distinct domains: canonical target text, raw audit evidence, full-record request identity and UUID identity. Use D01/DEV-SVC-002 for deliberate identity changes and DEV-DB-001 for raw-storage integrity. Do not canonicalize all inputs into one representation and conceal corruption or erase proposal identity. |
| 3. All hashing/serialization in transaction; catch any exception | Implement DEV-RUN-002's safe prevalidation and auditable rejection path. Catch anticipated input failures; propagate/handle database and infrastructure errors honestly at the owning boundary. Define safe evidence storage first. Merely moving the existing unsafe hash under a lock does not make an unpaired surrogate persistable. |
| 4. Audit-invariant property test | Add parameterized/property-style live coverage for known-target accepted/rejected calls and documented exceptions. Assert one attempt for normal submissions/rejections and zero for exact outcome recovery; conflicts gain an attempt under DEV-SVC-001. Distinguish unresolvable target, inability to reach DB, and outer rollback from durable audit success. A caller-owned transaction's durability follows commit, not function return. |
| 5. Specify fingerprint inputs in DATA_MODEL | Link/copy the authoritative C4 definition, clarify canonical JSON versus wire bytes, include intent/guards/selectors/parent identity and recovery-before-guards examples. Identity already has a contract; the problem includes visibility and consistency of explanations. Record a new decision only if adopting D01's alternative. |
| 6. Concurrent same-key test | Implement V01 using real sessions and controlled lock/commit ordering, including rollback/failure branches. Do not replace it with mocks or sequential retries. |
| 7. Shared pagination type and response-shape test | Fix DEV-MCP-002 and add public response contract tests for both tools. Introduce a tiny shared result/helper only if it reduces real duplication; a new abstraction is not itself an acceptance criterion. |
| 8. Fuzz Unicode, line endings, UUID casing | Add focused boundary matrices/property cases for surrogate fields, valid Unicode, LF/CR/CRLF, parent/key validation, boolean-as-integer, selectors, caps and storage constraints. Reuse existing pytest tooling where sufficient; no new fuzzing dependency is required solely for this list. Pair pure cases with actual PostgreSQL/stdio failure cases. |
| 9. Split oversized PRs | Add a brief PR-template prompt for coherent scope, dependent/stacked changes, migration/replay implications and exact evidence SHA. Prefer vertical behavior slices with their tests/contracts rather than independent runtime/docs PRs that disagree while deployed. This is future workflow guidance, not a reason to rewrite existing Git history. |
| 10. Add edge-case/invariant review checklist | The existing review standard already requires architecture traceability, adversarial tests, independent triage and ten categories. Add only missing concrete prompts for Unicode persistence, selector contradictions, identity normalization, raw-storage checks, concurrency and old-profile replay. A normative standard change requires a version bump (for example 1.1.0 to 1.2.0), rationale, and corresponding template/instruction references; do not silently rewrite review requirements. |

## 6. Acceptance tiers, delivery order, review mapping, and closure

### Acceptance tiers

Use the lowest test layer that proves each assertion. Do not repeat every edge input through a live DB and subprocess. The user's requirement to test actual live behavior remains: existing tests alone do not close the high-risk changes.

| Work | Exhaustive focused evidence | Representative live evidence required |
| --- | --- | --- |
| DEV-RUN-001 | Pure selector/profile/sequential matrix for typed and legacy | Actual PostgreSQL accepted/rejected state and audit assertions; real stdio contradictory-selector rejection plus compatible historical replay. |
| DEV-RUN-002 | Pure/service Unicode-field matrix, reversible safe evidence and encoding | Actual PostgreSQL persistence/recovery/rollback; real stdio escaped-surrogate rejection with safe response and stored evidence. Read/search string policy can have focused service/adapter tests. |
| DEV-SVC-001 | Service/response matrix for conflict identity and diagnostics | Actual PostgreSQL original/conflict/recovery/repeated-conflict rows and rollback; representative real stdio conflict and original recovery. |
| V01 | Deterministic synchronization/timeout assertions | Two real PostgreSQL connections demonstrating lock wait, commit/rollback, one original outcome and duplicate recovery. Concurrent subprocesses are optional; one existing/added real stdio recovery smoke can be shared with the fix cases. |
| DEV-DB-001 | Replay component/contract cases | Actual rollback-isolated PostgreSQL corruption and health checks. Reuse the release stdio replay workflow; a subprocess per corruption variant adds no necessary proof. |
| DEV-MCP-001 | Service argument matrix and focused routing/schema checks | No additional DB/subprocess case per invalid argument. Preserve integrated repository live/stdio checks. |
| DEV-MCP-002 | Response/boundary/filter/cursor matrix | Representative real PostgreSQL page selection and both display orders, plus one real stdio history traversal smoke. |
| DOC-only plan revisions | Source/contract reconciliation and complete-item coverage | No live DB rerun required to revise this plan; no runtime-fix closure is claimed. |

Shared end-to-end scenarios may cover multiple assertions when evidence names the exact IDs and executed SHA. Each implementation PR still runs the relevant repository-required unit/live DB/stdio/offline checks and records actual results. The tier table does not waive AGENTS.md's live-verification completion rule.

### Bounded PRs and release profiles

1. Selector/profile PR: DEV-RUN-001, its compatibility contract, fixtures and live proof. Choose the new profile once for selected release semantics; do not delay the P1 fix for optional work.
2. Unicode PR: DEV-RUN-002 and read/search string-boundary policy, a minimal evidence-storage decision, contracts and tests. No new general encoding framework or schema migration without demonstrated need.
3. Conflict-audit PR: DEV-SVC-001 and repeated-conflict policy, keyed recovery tests and documentation. Reuse existing/small shared rejection persistence where appropriate. Document operational admission controls separately; do not bundle a general rate limiter into this bug fix.
4. Replay-integrity PR: DEV-DB-001 with the specification decision, raw-storage checks and actual corruption evidence.
5. Public-arguments/paging PR: DEV-MCP-001/002 with both documented display orders, bounded metadata and focused tests. Split these two if the delta warrants it.
6. Identity decision: DEV-SVC-002 and D01 separately; preserve historical-key recovery and implement only deliberately selected identity changes. Service identity strategies need their own compatibility treatment, not an automatic edit-runtime profile bump.
7. Cross-cutting verification: place V01/V06/V07/V09 cases in the owning coherent PRs, then check final integrated-head CI. Keep V02/V04 data/benchmark limitations visible where unavailable.
8. Optional usability: F01/F12 first if selected, then diagnostic/new-operation features in separate PRs. A span-based F10 depends on F07. No optional feature is necessary to close the confirmed defects.

Each PR includes its own contracts, implementation, tests, evidence and independent recheck; avoid splitting those into incompatible file-type PRs. A common new profile is possible only if all its semantics are settled before durable logs are written with it. Once a profile has written history, never redefine it to save another version. Keep this plan and its revisions as documentation artifacts; this scope adjustment authorizes no PR creation or merge by itself.

For future implementation, assign ownership by coherent behavior, provide the IDs, pinned source/contract evidence, required edits, and acceptance cases above to any provider-neutral agent. Use the inherited/default model for subagents. Require independent recheck of each candidate and each fix; do not treat a previous model's confidence as acceptance.

Review-category mapping for the follow-up full PR review:

| Category | Relevant work in this inventory |
| --- | --- |
| ARCH | Replay/storage spec decision, selector runtime profiles, identity/guard/new-operation decisions. |
| DOC | Active contracts, host/data-model examples, corrected claims and change record. |
| SKILL | Reconcile repo skill/API instructions only where changed fields/profiles/workflow affect them. |
| MCP | Context validation, history response, examples and any approved extension schema. |
| RUN | Singleton selection, Unicode validation, exact/sequential application and new profiles. |
| SVC | Conflict audit, parent identity, recovery completeness and transaction ownership. |
| DB | Replay integrity, historical compatibility, locking/isolation, live persistence and migrations. |
| SCRIPT | Keep evaluator claims limited to measured bytes/verdicts; record any new benchmark methods. |
| TEST | Edge-case matrices, real stdio/PostgreSQL regressions, concurrent duplicate test and pinned CI. |
| DEP | No dependency change is required by this inventory; assess actual future packaging/config changes. |

This mapping is not a ten-category approval: unrelated surfaces remain unassessed here. A follow-up review must provide the standard's separate P1/P2/P3 buckets, coverage, verification and verdict for every category.

Close each implementation item only with: fix commit; exact executed revision; contract/schema/doc reconciliation; regression assertions and actual results; independent recheck; and any remaining limitation. Preserve original Devin files and previous review records. A new plan, a passing old test suite, or an unexecuted regression case is not closure.
