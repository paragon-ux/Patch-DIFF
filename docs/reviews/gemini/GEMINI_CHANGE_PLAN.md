# Gemini review: item-by-item accepted change plan

Date: 2026-10-21
Plan revision: 1 — accepted by the user after live reproduction; supersedes the three original Gemini reports as the work inventory.
Repository: paragon-ux/Patch-DIFF
Related PR: #1 modernization and its existing remediation stack; no merge is authorized by this plan.
Inspected/reproduced head: b5caa40bd41848420c4323d22ab648847cdc6745
Review standard: docs/PR_REVIEW_STANDARD.md, version 1.1.0
Execution goal: [Gemini-Goal-G.md](Gemini-Goal-G.md)

## Scope and conclusions

This plan mirrors the Devin change-plan structure: item-by-item dispositions, necessary changes, preserved capabilities, verification gaps, delivery order, category mapping, and closure evidence. It is an accepted work inventory, not a whole-PR approval.

The user authorized creating this plan and Goal G, archiving superseded Gemini reports, and beginning Goal G. That authorization permits the bounded transport fix and its contracts/tests/review. It does not authorize merging existing PRs or starting the independent Goal F feature implementations.

Evidence: [live reproduction report](archive/2026-10-21-reproduction/REPRODUCTION_REPORT.md), [80 native calls](archive/2026-10-21-reproduction/native-events-final.json), [transport byte controls](archive/2026-10-21-reproduction/transport-results.json), and [independent SQL verification](archive/2026-10-21-reproduction/independent-verification.json). All W1–W12 workflows, supplemental exact 40-line replacement, final target equality checks, and five final replays passed with the configured UTF-8 workaround. Scripts were limited to setup, allowed interference/response loss, transport diagnostics, and independent verification. This was an informed reproduction, not a blinded usability study. The old 834-test/28-step totals were not rerun for that report.

One confirmed product defect is accepted: G02, default Windows stdio input decoding. Its reported stdout crash is replaced by the measured failure: valid raw UTF-8 was accepted and stored as mojibake. G03’s unhandled-error and G07’s missing-metadata claims are rejected. The remaining G items are intended behavior, bounded documentation/evidence corrections, Goal F overlaps, or a host-specific verification gap.

## 1. Confirmed defect

### G02 / DEFECT-001 — P1: enforce UTF-8 at the stdio process boundary

Categories: MCP, DEP, TEST, DOC; ARCH/SVC/DB are compatibility verification surfaces.
Source: backend/app/mcp/external_adapter.py, serve_stdio/main; default streams inherit the Windows pipe code page.

Trigger/actual: with PYTHONIOENCODING and PYTHONUTF8 absent on Windows Python 3.11.9, stdin was cp1252. A tools/call carrying literal UTF-8 star bytes as the replacement of ASCII hello was accepted at version 1, but the stored/exported text was ðŸŒŸ instead of 🌟. Native export and independent SQL confirmed persistence. ASCII-escaped Unicode worked. Both raw and escaped JSON worked with PYTHONIOENCODING=utf-8. Every process exited 0 and stdout remained ASCII; the claimed UnicodeEncodeError stdout crash did not reproduce.

Necessary changes:

1. Establish explicit UTF-8 stdin/stdout encoding and strict text errors at the external process entry point, using the smallest standard-library change. Keep serve_stdio’s injectable test-stream interface usable. Do not add a codec framework or dependency.
2. Never use errors=replace/ignore or silently reinterpret malformed wire bytes. Separate invalid UTF-8 wire encoding from valid JSON Unicode escapes: escaped surrogate/NUL edit data still reaches the existing audited domain boundary and must retain its current rejection/evidence behavior.
3. Preserve ASCII JSON response escaping, JSON-RPC framing, tool schemas, request fingerprints, transaction ownership, runtime profile 0.2.2, and stored replay history. No migration, runtime-profile bump, tool alias fields, or G03 dispatch rewrite.
4. Update current MCP setup/host transport documentation and the modernization change record to describe the actual defect and the resulting UTF-8 guarantee. PYTHONIOENCODING=utf-8 remains compatible and is the interim workaround for older revisions.
5. Add raw-byte subprocess regressions: literal and escaped Unicode with ambient UTF-8 settings absent or explicitly non-UTF-8; verify exact upload/read/search/edit/export content against live PostgreSQL. Include emoji/non-BMP, accents and CJK, structured argument-error survival, and escaped invalid-domain-input preservation.

Acceptance: a pre-fix regression must demonstrate the raw-byte failure. Fixed real subprocesses must preserve exact Unicode without the environment workaround, retain escaped JSON compatibility and audited invalid-text rejection, and demonstrate persisted state/audit/ledger effects. Run repository-required unit/live integration/offline checks and an additional manual public-MCP workflow outside pytest. Independent default-model recheck and a source-pinned fix commit are required before closure.

## 2. All eight G-series dispositions

| ID | Accepted disposition | Necessary work / limit |
| --- | --- | --- |
| G01 | Host-specific verification gap | Preserve the observed Codex refresh requirement as host guidance. Do not claim the Antigravity kill/0xffffffff issue reproduced. Reopen only with an affected-host run; no process supervisor/runtime change. |
| G02 | Implement corrected transport fix | See section 1. Priority reflects silently wrong accepted text under unconfigured Windows pipes, not the unreplicated crash. |
| G03 | Reject unhandled-exception/P1 premise | Native unexpected version argument returned isError:true with a clear keyword message; later calls worked. Preserve behavior. A possible -32602 versus tool-error contract change is a separate future decision, not an accepted fix here. |
| G04 | Preserve traversal; correct review guidance | Use exclusive before_sequence=next_sequence. Native pages covered all 18 rows; min−1 skipped a row. Existing descriptions/guide already explain ordering. No after_sequence API, ordering change, or profile bump. |
| G05 | Accept narrower audit-read limitation | Ledger lacks match/replace literals but retains intent/rationale and supplied risk. Attempt history with include_content:true already supplies text. Clarify the read workflow only where needed; bounded excerpt enrichment is deferred. Append-only history is not a permanent schema freeze. |
| G06 | Intended sequential semantics; example belongs to F12 | Original-buffer-dependent edits reject atomically; progressive-buffer edits pass. Descending occurrence indexes solved the rename workflow. Do not change application order or imply arbitrary earlier length changes invalidate later exact matches. |
| G07 | Falsified; no product change | Search already returns version/current_hash; W5 submitted directly from that hash. Do not add target_version/target_current_hash aliases. |
| G08 | Confirm diagnostic limitation; fold into F06 | Actual label was disambiguation_invalid, with occurrence_count but no constraint-clash explanation. Preserve conjunctive index/anchor semantics. Candidate/constraint diagnostics remain in Goal F; no fuzzy selection or fallback. |

## 3. Original FRIC items, setup, and optional features

| Original item | Result / accepted consequence |
| --- | --- |
| FRIC-01 | Same host-specific gap as G01; no duplicate defect. |
| FRIC-02 | Same corrected transport defect as G02. |
| FRIC-03 | Same handled-error correction as G03. |
| FRIC-04 | Ascending repeated-occurrence drift reproduced; descending indexes passed. Keep semantics and a concise example under F12. No inferred replace-all requirement. |
| FRIC-05 | Missing near-miss snippets confirmed. Preserve F05’s bounded diagnostic-only proposal and lock-release constraints; no implementation in G. |
| FRIC-06 | Stale guard returned current version/hash and required a fresh read for content. Preserve F01’s fresh-versus-original evidence separation; no implementation in G. |
| FRIC-07 | Same corrected cursor guidance as G04. |
| FRIC-08 | Legacy required seven manifest prose fields and rejected a literal delimiter collision; typed equivalent passed. Keep typed primary and legacy frozen. Measured sample submit arguments were 255 vs 592 UTF-8 JSON bytes; not a universal savings ratio. |
| FRIC-09 | Literal old/new section payload remains real. Original Benchmarks was 22 lines/843 characters; a separate exact 40-line case passed. F07 still requires expected_text, F09 is whole-target replacement, and F10 is read-only. Do not mislabel them as removing old-text payload automatically. |
| Skill frontmatter | Original core-runtime description failed YAML parsing at its unquoted internal colon; quoting fixed it in memory. The other three original headers parsed. Preserve the four existing local quote-only edits; do not claim four parser defects or rewrite user-owned changes. |
| Context/RTK and broad correctness claims | No independently captured evidence supports the transcript-wide context/token-savings estimates or universal 100% product correctness. Preserve raw records and scope claims to executed cases. |

## 4. Existing capabilities to preserve

| Capability | Preservation/verification |
| --- | --- |
| Canonical text and reads | LF-normalized target text; code-point offsets; exact Unicode upload/read/search/export. |
| Guarded atomic edits | Version/hash checks, all supplied selectors, progressive-buffer simulation, no partial commit. |
| Audit and identity | Accepted/rejected append-only attempts; exact keyed recovery; original fingerprints and invalid-text evidence unchanged. |
| History | Attempt pages descending; newest ledger page displayed ascending; exclusive returned cursor; text via raw attempt records. |
| SAVE/replay | Checkpoint rotation without content mutation; all historical profile dispatch; four materialized-state checks. |
| Host boundary | Planning/retry remain host-owned; raw stdio subprocess proof is distinguished from native host calls. |

## 5. Verification and decision register

| ID | Check / disposition |
| --- | --- |
| G-V01 | Raw UTF-8 subprocess bytes under absent/non-UTF-8 environment; original failure and corrected exact text, with independent SQL checks. Required for G02. |
| G-V02 | Escaped JSON, malformed UTF-8 wire input, escaped surrogate/NUL domain rejection, extra-keyword survival and unchanged tool surface. Required compatibility checks. |
| G-V03 | Host-specific Antigravity lifecycle reproduction remains unverified. Deferred until the affected host can be tested; no fake closure. |
| G-V04 | Preserve recovered fixtures, byte captures and measured boundary metrics. Do not call boundary JSON sizes captured native wire frames or elapsed deliberation transport latency. |
| G-D01 | Invalid-argument RPC envelope changes: deferred independent contract decision. No G03 implementation. |
| G-D02 | Optional bounded history excerpts: deferred read-side proposal. No migration/schema prohibition inferred. |
| G-D03 | F01/F05/F06/F12 implementation remains owned by Devin Goal F; Goal G neither duplicates it nor waives F’s merge preconditions. |

## 6. Acceptance tiers, delivery order, category mapping, and closure

1. Establish these two accepted documents and archive provenance with SHA-256 checks before product changes.
2. Deliver one coherent G02 transport fix with focused regressions, active documentation, manual live PostgreSQL/stdio evidence, and independent ten-category review. A new non-protected branch may start from the reproduced b5caa40 stack head; do not merge the stack as an implicit prerequisite.
3. Complete evidence-only dispositions and any genuinely missing host guidance. Leave Goal F features and the affected-host lifecycle gap explicitly deferred.

Focused/unit checks establish entry-point configuration and injectable-stream compatibility. Real raw-byte subprocess tests plus live PostgreSQL establish actual decoding and storage. Manual execution outside pytest proves the original failure is gone at the fixed material. Run the required repository suites/offline evaluation once the focused checks pass; do not multiply expensive live tests for every prose change.

| Category | Scope |
| --- | --- |
| ARCH | Preserve host/runtime boundary; no transaction/protocol/profile change. |
| DOC | Accepted plan/goal, archived provenance, setup/host transport guarantee and as-built record. |
| SKILL | Preserve existing user edits; only add guidance if an actual missing instruction is found. |
| MCP | Explicit stdio encoding, framing and argument-error compatibility. |
| RUN | No matcher/parser/profile semantic changes; regress existing escaped invalid-domain inputs. |
| SVC | Preserve guards, audited rejection and keyed recovery. |
| DB | Verify exact persisted Unicode and audit/ledger effects; no migration. |
| SCRIPT | Preserve raw-byte/manual evidence and honest metrics. |
| TEST | Focused regression, actual subprocess/live DB, required suite/offline checks. |
| DEP | Standard library only; override-compatible Windows transport setup. |

Closure requires a fix commit, exact executed material, contract/doc reconciliation, regression and manual results, independent recheck, and remaining limitations. A new plan, archived report, or passing pre-fix replay is not closure. Rejected/intentional/deferred items are dispositions, not implemented fixes. Keep CI evidence separate from local evidence; do not invent remote green checks or merge authority.

## Authority and archival preservation

Follow AGENTS.md, active architecture/core/MCP contracts and PR_REVIEW_STANDARD.md. The user explicitly authorized these new files and archival moves under docs/reviews/gemini; this is a limited exception to the historical review-directory preservation rule. Original report bytes and the protected twelve-file review manifest stay unchanged. Devin reports/plans/Goal F are not edited.

The three original Gemini reports are preserved under archive/2026-10-21-superseded, and the live reproduction evidence is copied to archive/2026-10-21-reproduction. archive/ARCHIVE_MANIFEST.json records original paths and hashes. Archived recommendations are historical claims; these accepted documents govern Goal G. New implementation/test/review evidence belongs under docs/gemini-remediation so historical records remain immutable.

