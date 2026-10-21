# Goal G: PatchDIFF Gemini transport remediation and evidence reconciliation — revision 1

Date: 2026-10-21.
Repository: paragon-ux/Patch-DIFF.
Accepted inventory: [GEMINI_CHANGE_PLAN.md](GEMINI_CHANGE_PLAN.md).
Reproduced base: b5caa40bd41848420c4323d22ab648847cdc6745.

## Status and authorization

The user approved the live-reproduction conclusions and explicitly authorized this accepted goal, the corresponding change plan, archival of superseded Gemini reports, and beginning Goal G. Execute within the scope below without another planning approval. PR merges remain separately authorized actions.

Scope is one corrected product fix (G02), evidence-backed dispositions for G03/G04/G05/G06/G07, bounded host guidance, and explicit deferrals for G01’s affected-host test and diagnostic features already owned by Goal F. Do not describe eight findings as eight implementation features.

## Authority and preservation

Follow AGENTS.md, MODERNIZATION_ARCHITECTURE.md, PATCHDIFF_CORE_SPEC.md and PR_REVIEW_STANDARD.md v1.1.0. Existing valid-input fingerprints, immutable runtime profiles including 0.2.2, audit ownership and protected review hashes remain unchanged.

The user’s file/archival request is the explicit location exception for docs/reviews/gemini. Preserve original bytes and a hash manifest; preserve Devin records and the existing four skill description edits. Put subsequent implementation decisions, live evidence and independent reviews under docs/gemini-remediation. An accepted plan is not a retroactive fix or review closure.

## Execution preconditions and branch policy

1. Pin current branch/head and dirty-tree ownership. Create a non-protected fix/gemini-stdio-utf8 branch from the reproduced stack material, preserving unrelated changes.
2. Establish the two accepted documents first; then archive original Gemini reports with hash verification and copy the live reproduction evidence. Do not rewrite archived claims to match later conclusions.
3. Begin the bounded transport fix on that branch. Goal G is a compatibility repair and may be prepared against b5caa40 before the stack is merged. This does not relax Goal F’s separately defined consolidated-main prerequisites.
4. Use an isolated PostgreSQL database for tests/manual work. Keep the installed reproduction server’s existing database/encoding configuration intact unless a later explicit deployment step changes it.
5. No merge, force-push, branch deletion, database deletion or publication claim is implied. Record actual commits, PRs and CI only when they exist.

## Item disposition and delivery order

| ID | Goal G disposition | Phase |
| --- | --- | --- |
| G02 | Implement explicit UTF-8 stdio entry point and compatibility regressions | A |
| G03 | Close the unhandled/P1 premise as contradicted; no dispatch rewrite | B evidence disposition |
| G04 | Preserve cursor behavior; correct historical recommendation in accepted guidance | B evidence disposition |
| G05 | Document existing attempt-log text retrieval; defer optional enrichment | B / decision register |
| G06 | Preserve sequential semantics; leave new worked examples to F12 | B / Goal F overlap |
| G07 | Close missing-metadata premise as falsified; no alias fields | B evidence disposition |
| G08 | Preserve conjunctive selectors; retain diagnostic work under F06 | Goal F overlap |
| G01 | Record host-specific uncertainty; defer Antigravity lifecycle experiment | Decision register |

## Global contracts

1. The wire transport is UTF-8 independent of locale, Windows pipe code page or PYTHONIOENCODING overrides. Use strict decoding/encoding; never repair malformed bytes.
2. Valid JSON escape sequences remain protocol data: escaped lone surrogates/NUL must reach the existing safe domain policy, including audited known-target rejection. Do not conflate invalid wire encoding with invalid decoded edit strings.
3. Keep injectable serve_stdio streams and existing tools usable. Preserve response escaping/framing and existing handled invalid-argument behavior.
4. Make no protocol, replay-profile, fingerprint, database-schema, matcher/selector, transaction-ownership or audit-guarantee changes. No new dependency.
5. Separate native host execution, raw stdio diagnostics, SQL verification, local suites and inspected CI. Only measured quantities receive numeric claims.
6. Independent triage and recheck use inherited/default-model subagents. Each material category gets its own P1/P2/P3 lists, gaps and verdict. A confirmed new defect found during implementation is triaged rather than silently deferred.

## Phase A: G02 transport correctness

### Decision and implementation

Record a concise pre-code decision under docs/gemini-remediation naming the exact cp1252 input-corruption reproduction and the non-reproduced crash. Configure real process stdin/stdout to UTF-8 at main, with strict errors and no replacement/ignore fallback. Keep the pure/injectable serve_stdio path intact. Prefer direct standard-library stream reconfiguration over abstractions or wrappers.

Update active setup/host documentation and MODERNIZATION_CHANGE_DOC. Document the environment workaround for old versions and the fact that the fixed entry point no longer relies on it. Do not silently change the installed host’s configuration or rewrite historical DEFECT-001.

### Verification

- Demonstrate a pre-fix raw-byte failure using an explicitly non-UTF-8 child configuration, not just a mocked stream.
- Run fixed real subprocess cases with UTF-8 override absent and explicit cp1252 override, each using raw and escaped Unicode JSON.
- Exercise public initialize/upload, bounded read, exact search, typed submit, export, SAVE/replay and keyed recovery against live PostgreSQL. Verify exact stored Unicode, version, immutable attempt count and accepted ledger effects.
- Include emoji/non-BMP, accents, CJK, canonical CRLF input; escaped surrogate/NUL audited rejections; unexpected kwargs followed by a successful call; and malformed UTF-8 wire bytes that cannot produce accepted mutation.
- Run focused tests, the repository unit and integration suites, and offline equivalence. Add manual real subprocess/live DB verification outside existing pytest tests with raw stdin bytes and independent SQL assertions.
- Preserve existing stream-injection unit tests. Record Windows-specific and cross-platform limits; CI is not claimed until actually inspected.

## Phase B: reconcile accepted guidance and evidence

Record G03’s isError:true result and survival; G07’s existing version/current_hash; G04’s returned-cursor traversal and the min−1 skip; G05’s retained intent/rationale/risk and attempt-log literal content; G06’s atomic rejection/retry; and G08’s actual disambiguation_invalid diagnostic. Reference archived raw evidence rather than duplicating backend work.

Only change current user guidance where it is missing or incorrect. Current guide already describes search metadata, both history display orders, returned cursors and sequential edits. Do not add prose merely to make an evidence disposition look implemented.

Preserve the original frontmatter diagnosis: one failing core-runtime description; other original headers parsed. Existing local quote-only edits are user-owned. Keep the recovered 22-line benchmark section distinct from the supplemental 40-line case.

## Deferred decision register

- G01 / G-V03: affected Antigravity process lifecycle requires an actual affected-host run. Codex’s refresh experience is not equivalent proof.
- G-D01: changing unexpected tool arguments to JSON-RPC -32602 requires a separate contract decision. No unhandled-crash fix is accepted.
- G-D02: optional bounded history diff excerpts need a demonstrated read-side requirement. No permanent no-migration rule is adopted.
- F01/F05/F06/F12: fresh rejection context, near misses, candidate/constraint diagnostics and examples remain in Goal F with its existing limits. G08 is evidence for F06, not a second implementation.
- F07/F09/F10 and other Goal F extensions retain their exact contracts and authorization gates. No automatic replace-all, span optimization, line-edit adapter or runtime profile is introduced by G.

## Cross-cutting documentation and release verification

Keep one coherent transport change with its docs/tests/evidence. Preserve twelve protected historical file hashes and archived original report hashes. An independent review covers all ten categories required by the review standard, explicitly marking unchanged categories as inspected/not materially changed rather than skipping them.

Record base/fix/executed SHAs, commands/results, raw-byte manual proof, PostgreSQL state/audit assertions, suite/offline outcomes, reviewer identity and remaining host-specific limits. Prepare a reviewable branch/PR; merges require separate approval. Any later CI claims must identify the actually executed head or generated-merge SHA.

## Completion and report

- Accepted plan and goal exist at the requested paths; superseded reports and raw evidence are discoverable via an immutable hash-checked archive.
- G02 has a minimal fix, exact Unicode storage proof without the workaround, compatibility tests, manual live evidence, a fix commit and independent recheck.
- G03/G04/G05/G06/G07 have explicit evidence dispositions; G08 remains a Goal F diagnostic overlap; G01 and optional decisions are explicitly deferred.
- No false eight-feature completion, universal correctness claim, inherited CI pass, historical rewrite or unauthorized merge.
- Report actual changed files, commits/PRs, verification, disposition per G ID and remaining limitations.

