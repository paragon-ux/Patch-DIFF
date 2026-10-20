# Comprehensive Second PR Review: PR [#1](https://github.com/paragon-ux/Patch-DIFF/pull/1) (`feature/modernization-argon-remediation` -> `main`)

**Verdict: REQUEST CHANGES.**  
**Review standard:** [v1.1.0](https://github.com/paragon-ux/Patch-DIFF/blob/4563a49ed4c46e8687b6fd5079649d5f0304918c/docs/PR_REVIEW_STANDARD.md), with independent P1/P2/P3 triage in every category.  
**Review date:** 2026-10-20.  
**Base:** 0c75c4054b5da01eb56c53ce5579c74014270f3a.  
**Head reviewed:** b31d73da0e41862f77e31cb518f8a88dabf1559b.  
**Revision:** 2; supersedes the earlier partial category review at head 39dcb4b; this review includes the later documentation-only merge. Stable finding IDs are retained.

## Coverage and evidence limits

All 55 changed files were included in this source/diff review, mapped to a primary category below. Relevant unchanged dependencies, the concept paper and selected frozen-spec sections were also inspected. Source review is complete for the listed change scope; execution coverage is limited to inspected existing CI. It is not a claim of exhaustive correctness or readiness to merge.

No local execution or new reproduction was possible because the execution environment was unavailable. Every newly described failure/interleaving is source-derived, not reported as a locally reproduced result. The attached transcript was not accessible; its contents are not used as evidence. The initial review posted on the PR was read and its claims independently checked.

During review, head advanced from 39dcb4b to b31d73da0e41862f77e31cb518f8a88dabf1559b when PR #2 merged. The compared delta changes only AGENTS.md, the review standard, the PR template and the earlier partial report. Their contents match the format changes reviewed here; no runtime behavior changed. All findings were revalidated against that delta and source links repinned. The earlier report remains a historical snapshot rather than being overwritten.

Existing [CI run 39480768393](https://github.com/paragon-ux/Patch-DIFF/actions/runs/39480768393), job 118828411176, is associated with the reviewed head. Its log checks out generated merge commit **7b8a3a737462349ef833776d3da6d5a151aa0c44**, combining this head with the recorded base. It records **174 unit tests passed**, **89 integration tests passed**, and offline verdict equivalence **OK**. This is real CI evidence for that tested revision; it does not execute the new counterexamples below.

Priority reflects impact, not whether a failure was reproduced locally. P1 requires resolution before merge; P2 identifies actionable correctness/contract problems; P3 identifies lower-impact repairs. Empty buckets mean none identified in the specified reviewed scope, not universal clearance. Verification gaps are kept separate from defect counts.

## Architecture-first assessment and provenance

The concept paper's central contribution is the deterministic transaction lifecycle over authoritative text: exact preconditions, all-or-nothing commits, rejected-attempt audit, accepted-only advisory memory and replay. Its section 9 distinguishes protocol/transaction validity from task/semantic correctness; sections 19–20 ground history and state consistency. Section 26 explicitly leaves empirical performance claims unvalidated.

The modernization's direction is supportable:
- Typed JSON addresses the paper's delimiter limitation without changing target-native payloads or introducing AST/fuzzy semantics; both formats lower into the shared deterministic applier.
- Authoritative reads and host-owned proposal/retry preserve the model-proposes/runtime-validates boundary.
- Runtime-derived facts appropriately distinguish operational evidence from model-authored prose.
- Recorded matcher profiles preserve historical replay while fixing overlapping occurrence enumeration.
- SAVE continues to rotate active manifest context and preserve history; it is not host conversation compaction.

Current primary sources were opened to check the architecture's external rationale. [Claude text editing](https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool) documents structured exact replacement, range reads and caller-handled errors. [OpenAI apply_patch](https://developers.openai.com/api/docs/guides/tools-apply-patch) leaves actual application and all-or-nothing policy to the harness. [Claude checkpointing](https://code.claude.com/docs/en/checkpointing), [memory](https://code.claude.com/docs/en/memory), and [hooks](https://code.claude.com/docs/en/hooks) support the distinction between host convenience/instructions and authoritative pre-write enforcement. [Antigravity MCP](https://antigravity.google/docs/mcp) documents local stdio configuration; the [review page](https://antigravity.google/docs/ide/review-changes-editor) was also opened. [MCP Python SDK v2.3.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0) resolves the release identity cited in E8; the API /releases/latest endpoint was inaccessible through the browsing tool, so the official release page was used. These checks support the boundary decisions; they do not independently prove every incidental vendor/UI/version claim in E1–E8 or a measured PatchDIFF performance advantage.

The principal remediation is therefore to make the selected guarantees true and evidenced. It is not necessary to replace the deterministic core, add semantic matching, or adopt a new SDK merely because it exists.

| Contract | Implementation / review consequence |
| --- | --- |
| A4/A6 — authoritative guarded commit | DB-002: locked ORM reads must refresh authoritative state |
| C1 — complete typed contract | MCP-001, MCP-002: discovery/parser/public grammar agreement |
| C2 — stage accuracy and safe rejection/lineage | RUN-001–003, SVC-001–002, SKILL-001 |
| C3 — replay integrity | DB-001: define and implement a coherent observation boundary |
| C4 — outcome recovery | DOC-001: request identity is distinct from version/hash guards |
| C5 — ledger/schema fidelity | SKILL-002; populated migration proof remains missing |
| C6/A5 — bounded reads/history | ARCH-001–002 |
| A8 — honest evaluation | SCRIPT-001; no live-model comparative claim established |

## Category coverage and triage index

| Category | P1 | P2 | P3 | Source coverage / disposition |
| --- | --- | --- | --- | --- |
| ARCH | None identified | ARCH-001, ARCH-002 | None identified | Reviewed changed scope; see category verdict |
| DOC | None identified | DOC-001, DOC-002 | DOC-003 | Reviewed changed scope; see category verdict |
| SKILL | None identified | None identified | SKILL-001, SKILL-002 | Reviewed changed scope; see category verdict |
| MCP | None identified | MCP-001, MCP-002 | None identified | Reviewed changed scope; see category verdict |
| RUN | None identified | RUN-001, RUN-002, RUN-003 | None identified | Reviewed changed scope; see category verdict |
| SVC | None identified | SVC-001 | SVC-002 | Reviewed changed scope; see category verdict |
| DB | DB-002 | DB-001 | None identified | Reviewed changed scope; see category verdict |
| SCRIPT | None identified | SCRIPT-001 | None identified | Reviewed changed scope; see category verdict |
| TEST | None identified | None identified | None identified | Reviewed changed scope; verification gaps remain |
| DEP | None identified | None identified | None identified | Reviewed changed scope; no independent finding |

## ARCH — Architecture and contracts

**Scope / coverage:** 3 changed architecture/specification files; original concept paper and relevant frozen-spec sections. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Trace the paper's authoritative-target, structural-validity and lifecycle thesis to A1–A8/C1–C6. Typed lowering and host-owned planning preserve the boundary; resource contracts remain inconsistent.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority


#### ARCH-001 — The bounded-read implementation contradicts the locked C6 contract

- **Provenance:** [docs/MODERNIZATION_ARCHITECTURE.md:159–162](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/MODERNIZATION_ARCHITECTURE.md#L159-L162) specifies default 4,000 characters and maximum 8,000. AGENTS.md places this architecture above implementation descriptions.
- **Evidence and trigger:** [backend/app/services/read_service.py:19–46](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/read_service.py#L19-L46) uses MAX_READ_CHARS = 20,000 and defaults an omitted length to that maximum. Read a target longer than 20,000 characters with length omitted; the implementation selects 20,000, rather than the specified 4,000. A request for 20,000 also exceeds the specified 8,000 cap.
- **Impact:** hosts cannot rely on the documented context budget. The claimed locked contract and as-built behavior disagree.
- **Required remediation:** honor C6's 4,000 default and 8,000 cap, with separate default/max constants. If those limits are intentionally being revised, record and justify that contract change before changing runtime; do not silently treat the existing implementation as the decision.
- **Acceptance evidence:** a sufficiently long target returns 4,000 characters by default; an oversized request returns at most 8,000; end, truncated, and next_start match the actual slice. Reconcile active docs and tests against the selected contract.
- **Reasoning:** this is a measurable contract mismatch, not a preference for smaller responses. No claim is made that 8,000 is universally optimal.
- **Status:** open; source-derived.

#### ARCH-002 — A5's bounded manifest history is unimplemented on the default path

- **Provenance:** A5 [MODERNIZATION_ARCHITECTURE.md:87](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/MODERNIZATION_ARCHITECTURE.md#L87) promises bounded pagination for both history tools; the initial review explicitly claimed both are capped at 200.
- **Source / trigger:** [tools.py:307–337](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/mcp/tools.py#L307-L337) defaults limit to null and executes unrestricted all() in that branch. With more than 200 selected ledger rows, omit limit; include_previous_cycles=true can expand this to every cycle.
- **Expected / actual / impact:** a bounded default is promised, but the entire selected ledger is returned. Clamping only a supplied limit does not bound the default. There is also no ledger continuation argument/sequence in the response, so a cap alone would prevent complete traversal.
- **Required remediation:** define the modern history contract in A5 as default 50 / maximum 200, reusing the existing history constants, plus before_sequence over ledger_sequence and a usable continuation field. Implement schema, query, response and docs together. If legacy callers need the whole active ledger, preserve that through an explicit compatibility path rather than claiming it is bounded.
- **Acceptance evidence:** with at least 201 entries, default returns at most 50, oversized limit at most 200, and continuation traverses all selected rows without gaps or duplicates; verify cycle filtering and compatibility behavior.
- **Root cause:** the presence of clamp_limit was used to sign off a guarantee without checking every branch.
- **Origin / status:** open, source-derived. Existing unbounded behavior retained under a newly asserted architecture guarantee; not characterized as a newly introduced legacy regression.

### P3 — Low priority

None identified within the reviewed scope.

**Verification:** relevant source and existing test assertions were inspected; the listed regression acceptance cases have not been newly executed in this review.

**Category verdict:** Changes required.

## DOC — Documentation and change records

**Scope / coverage:** 13 changed guides, format/data-model specifications, change/review records, review standard and PR template; linked configuration and runtime consumers. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Check examples, configuration names, recovery instructions and as-built claims against code. Historical records are distinguished from active requirements.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority


#### DOC-001 — Manual lost-response recovery overstates the protection of an old guard

- **Provenance and evidence:** [docs/HOST_INTEGRATION_GUIDE.md:97–113](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/HOST_INTEGRATION_GUIDE.md#L97-L113) says a verbatim retry with the old guard cannot apply twice. The typed contract permits a hash-only guard; legacy guards are optional. C4 separately provides request-ID deduplication.
- **Trigger / actual:** omit client_request_id, use only expected_current_hash, and submit a no-op replacement such as match="a", replace="a" against target "a". The accepted transaction increments version but preserves the hash. The same hash-only request can be accepted again. An ABA history also restores a previously used hash.
- **Impact:** host authors may mistake a state precondition for request identity, creating duplicate accepted history or repeating an edit after an ABA transition.
- **Required remediation:** qualify the old-guard claim to a monotonically advancing version guard. Explain that a hash-only guard is not request deduplication; recommend preserving the same client_request_id for transport retries. State the separate legacy behavior. Do not describe a one-version advance or a newest-five-log sample as proof of request identity.
- **Acceptance evidence:** the guide distinguishes request IDs, version guards, and hash guards, including no-op/ABA cases. Retain the existing keyed recovery tests; add or explicitly cite the unkeyed counterexample when verifying the claim.
- **Reasoning:** the implementation's keyed mechanism can be correct while the fallback instructions remain unsafe.
- **Status:** open; source-derived. Corresponds to earlier second-review finding 5.

#### DOC-002 — Test instructions select a database using a variable the application never reads

- **Provenance:** verification commands must select the database they claim to exercise. The application's configuration contract is PATCHDIFF_DATABASE_URL.
- **Evidence:** [README.md:141–143](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/README.md#L141-L143), [TEST_MATRIX.md:42–44](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/TEST_MATRIX.md#L42-L44), evaluation/README.md and the testing skill set DATABASE_URL. [config.py:9–12](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/core/config.py#L9-L12) only reads PATCHDIFF_DATABASE_URL. CI uses the correct name.
- **Trigger / actual / impact:** set DATABASE_URL to a nondefault database as instructed while PATCHDIFF_DATABASE_URL is unset or points elsewhere. Tests use the configured/default database instead, so the claimed environment is not verified.
- **Required remediation:** use PATCHDIFF_DATABASE_URL consistently in all active setup/test commands and skills. Correct the subprocess test's explicit override at [test_external_mcp_e2e.py:203–207](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/tests/integration/test_external_mcp_e2e.py#L203-L207) too; inherited os.environ currently masks this error in CI.
- **Acceptance evidence:** with a nondefault database/port, parent tests and stdio child use the requested PATCHDIFF_DATABASE_URL. Source reconciliation is sufficient for prose-only edits; do not add a test that merely repeats the documentation string.
- **Root cause:** copied configuration instructions were not traced to their consumer.
- **Status:** open; newly confirmed through documentation/configuration review.

### P3 — Low priority


#### DOC-003 — The provenance chain points to frozen-spec filenames absent at this revision

- **Provenance:** architecture-first review requires resolvable original design references.
- **Evidence / trigger:** [AGENTS.md:37](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/AGENTS.md#L37) and [MODERNIZATION_ARCHITECTURE.md:176](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/MODERNIZATION_ARCHITECTURE.md#L176) reference PatchDIFF_Protocol_Specification_v0_2_3.md and PatchDIFF_Implementation_Specification_v0_2_3.md. Fetching those exact paths returns 404. The actual documents are docs/PatchDIFF-Protocol-Spec-v0.2.3.md and docs/PatchDIFF-Implementation-Spec-v0.2.3.md.
- **Impact:** following the declared historical provenance fails even though the original documents remain present. This is not evidence that historical content was removed.
- **Required remediation:** correct active references to the actual hyphenated filenames and preserve the historical files.
- **Acceptance evidence:** corrected paths resolve at the fix revision; no runtime test is needed.
- **Root cause / status:** source identities were not checked during reconciliation. Open, low-priority traceability defect.

**Verification / reconciliation:** update the as-built matrix after fixes, linking each VERIFIED claim to the actual assertion and tested SHA. Its named schema test only checks field keys; the migration guard's source/string check is not a populated live downgrade test. Correct stale tool/test counts and any claimed schema constraints not present in DDL during reconciliation. These are related evidence/documentation gaps, not extra counted runtime defects.

**Category verdict:** Changes required; update completion claims after the behavioral gaps are resolved.

## SKILL — Skills and agent instructions

**Scope / coverage:** AGENTS.md and all four changed skill files. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Check actual enum/API names, fields, storage types, disambiguation rules and review/completion instructions against controlling contracts.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority

None identified within the reviewed scope.

### P3 — Low priority


#### SKILL-001 — The core skill teaches validation stages absent from the contract and runtime

- **Provenance:** C2 names PRECONDITION_GUARD, PROTOCOL_VALIDATION, TRANSACTION_APPLICABILITY, COMMIT_GUARD, and ACCEPTED, with nullable unreached-stage validity.
- **Evidence:** [.agents/skills/patchdiff-core-runtime/SKILL.md:114–129](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/.agents/skills/patchdiff-core-runtime/SKILL.md#L114-L129) instead lists PROTOCOL_DECODE, TARGET_RESOLUTION, CONCURRENCY_GUARD, MATCH_RESOLUTION, and SEQUENTIAL_SIMULATION, and describes protocol_valid / transaction_valid only as booleans. Compare [backend/app/core/validity.py:33–40](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/core/validity.py#L33-L40) and its stage handling.
- **Trigger / impact:** an agent following the skill can reference nonexistent enum members or flatten unreached stages into false. This undermines architecture-first remediation.
- **Required remediation:** reconcile that skill section to C2's exact names and null/false/true meanings. Distinguish informal algorithm phases from the actual ValidationStage enum if both are retained.
- **Acceptance evidence:** source reconciliation against C2 and the enum. No extra test is necessary merely to check prose.
- **Reasoning:** instructions are an implementation input and deserve review independently from runtime.
- **Status:** open; lower-priority instruction defect, not a demonstrated production failure.

#### SKILL-002 — Skills publish incorrect fact names, storage types and matching instructions

- **Provenance:** C5 and the actual applier define derived facts; historical implementation section 8 governs retained disambiguation semantics.
- **Evidence:** [SKILL.md:75–84](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/.agents/skills/patchdiff-core-runtime/SKILL.md#L75-L84) describes immediately adjacent anchors and a selecting line-range hint; [disambiguation.py:40–76](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/pdcp/disambiguation.py#L40-L76) uses before/after substring presence and region_hint does not select. The core skill's lines 104–110 and persistence skill's lines 75–78 name match_length, replace_length, match_sha256, replace_sha256; [applier.py:82–92](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/pdcp/applier.py#L82-L92) emits matched_chars, replacement_chars, matched_sha256, replacement_sha256.
- **Additional storage evidence:** [SKILL.md:42–46](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/.agents/skills/patchdiff-persistence-replay-save/SKILL.md#L42-L46) calls client_request_id UUID and origin VARCHAR(16), while migration 0002 defines both as TEXT. The skill's sequence_id is log_sequence in the model.
- **Trigger / impact:** an agent following these contracts can address nonexistent keys, impose an unsupported UUID restriction, or change frozen matching behavior.
- **Required remediation:** reconcile those exact names/types with C5 and migration 0002, use log_sequence, and restore the historical nonadjacent before/after anchor constraints and advisory-only region_hint. Do not change runtime to fit the erroneous instructions.
- **Acceptance evidence:** compare skill examples to applier keys, migration/model fields and historical disambiguation section 8; preserve request IDs such as req-001. Prose reconciliation suffices.
- **Root cause / status:** duplicated instruction contracts were not checked against canonical definitions. Open; lower-priority guidance defect.

**Verification / workflow:** source reconciliation is the appropriate acceptance method for the prose repairs. The testing skill's concise completion-report example does not establish PR review coverage; PR #2 has merged the separate v1.1.0 category/P1–P3 standard into this branch through AGENTS.md. That workflow change does not close the product findings above.

**Category verdict:** Changes required in instructions; these do not justify changing the runtime to match incorrect prose.

## MCP — MCP schemas and public API

**Scope / coverage:** Both changed MCP modules, registry dependency and typed schema/parser. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Inspect all 16 registered tool signatures, discovery generation, transport dispatch and submit responses. Python annotations are not runtime/schema enforcement. Key-only schema tests are insufficient.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority


#### MCP-001 — tools/list excludes a null value explicitly accepted by the typed contract

- **Provenance:** C1 at [docs/MODERNIZATION_ARCHITECTURE.md:99–102](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/MODERNIZATION_ARCHITECTURE.md#L99-L102) and [docs/MCP_TOOLS.md:132–139](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/MCP_TOOLS.md#L132-L139) allow change_id=null, defaulting it to the indexed identifier.
- **Evidence:** [backend/app/pdcp/typed.py:74–78](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/pdcp/typed.py#L74-L78) advertises change_id as string only. The parser at [backend/app/pdcp/typed.py:283–286](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/pdcp/typed.py#L283-L286) accepts null. [backend/tests/unit/test_typed_transaction.py:281–283](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/tests/unit/test_typed_transaction.py#L281-L283) explicitly tests that acceptance. The adapter advertises this schema directly.
- **Trigger / impact:** a schema-validating host rejects a documented request containing change_id:null before it reaches a runtime that accepts it.
- **Additional structural evidence:** annotation-derived top-level discovery in external_adapter.py:135–159 omits C1's non-null guard alternative and nonblank intent; the rationale item schema also permits blanks that typed.py:305–307 rejects. These are checked structural-domain mismatches, not a claim that schemas can enforce every business rule.
- **Required remediation:** make change_id nullable in the advertised schema, preserving the documented indexed default. Also encode representable C1 constraints missing from top-level annotation-derived discovery: nonblank intent/rationale, nonnegative version, SHA-256 hash pattern, and an anyOf requiring a non-null valid version or hash. Retain service checks for business rules; Python annotations do not enforce runtime validation.
- **Acceptance evidence:** validate omitted, null, valid-string, invalid-string, and invalid-type cases against the actual tools/list item schema and parser. The existing schema test at lines 275–278 checks key sets, required keys, and additionalProperties, not value-domain agreement.
- **Reasoning:** this is an externally visible contract mismatch independently of parser error handling in RUN-001.
- **Status:** open; source-derived.

#### MCP-002 — A contract-valid colon in change_id is rejected by schema and parser

- **Provenance:** C1 [MODERNIZATION_ARCHITECTURE.md:101](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/MODERNIZATION_ARCHITECTURE.md#L101) and [PDCP_FORMAT.md:58](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/PDCP_FORMAT.md#L58) allow the character class [A-Za-z0-9_.:-].
- **Evidence / trigger:** [typed.py:55–76](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/pdcp/typed.py#L55-L76) omits colon from both regexes. Submit an otherwise valid guarded edit with change_id="section:1".
- **Expected / actual / impact:** the documented identifier should be accepted; discovery and runtime reject the otherwise valid edit. This is separate from MCP-001's schema-versus-parser nullability disagreement.
- **Required remediation:** add colon to the schema and parser classes according to C1, preserving length, uniqueness and default-ID rules. Narrowing that contract requires an explicit architecture decision rather than an as-built documentation rewrite.
- **Acceptance evidence:** section:1 passes discovery and submit; whitespace, unsupported punctuation, oversized IDs and duplicates still reject.
- **Root cause / status:** contract grammar was transcribed inconsistently. Open, source-derived.

### P3 — Low priority

None identified within the reviewed scope.

**Verification:** relevant source and existing test assertions were inspected; the listed regression acceptance cases have not been newly executed in this review.

**Category verdict:** Changes required.

## RUN — Core runtime, parsing and validation

**Scope / coverage:** All 7 changed core/PDCP modules plus parser, validator, canonicalizer and model dependencies. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Check exact canonical matching, overlap profiles, sequential simulation, lowering, derived facts, rejection paths and stage propagation. No new core DB/LLM dependency was identified in changed modules.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority


#### RUN-001 — Unhashable risk input escapes canonical rejection and attempt logging

- **Provenance:** untrusted transactions must be deterministically rejected, with durable rejected-attempt history for a known target.
- **Evidence:** [backend/app/pdcp/typed.py:305–311](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/pdcp/typed.py#L305-L311) performs risk membership in a frozenset without checking its type. [backend/app/services/pdcp_service.py:399–440](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L399-L440) catches only the domain parse/validation exceptions. The adapter at [backend/app/mcp/external_adapter.py:59–68](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/mcp/external_adapter.py#L59-L68) converts a leaked TypeError into a generic tool error; schema advertising does not validate tool arguments.
- **Trigger / actual:** submit otherwise valid guarded edits with risk:[] or risk:{}. Membership raises TypeError; the normal rejection persistence path is skipped.
- **Impact:** a malformed proposal disappears from the canonical attempt audit and loses format-specific diagnostics.
- **Required remediation:** type-check risk before enum membership and raise the same domain validation error used for invalid risk strings. Keep runtime validation even if transport schema validation is added.
- **Acceptance evidence:** both malformed values through the actual MCP call boundary yield a normal rejected result with a persisted rejected log, typed diagnostics, and unchanged target/version/ledger. The process remains usable.
- **Status:** open; source-derived. Corresponds to earlier finding 2.

#### RUN-002 — A hash error is treated as proof that all protocol validation completed

- **Provenance:** C2/A7 require validity derived from the actual completed stage.
- **Evidence:** [backend/app/services/pdcp_service.py:425–432](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L425-L432) assigns TRANSACTION_APPLICABILITY to every TARGET_HASH_MISMATCH exception. But [backend/app/pdcp/protocol_validator.py:128–145](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/pdcp/protocol_validator.py#L128-L145) raises that reason for conflicting header/manifest hashes inside validate_pdcp, which iterates changes in order.
- **Trigger / actual:** a two-change PDCP has conflicting valid-format hashes in change 1 and an invalid occurrence_index=0 in change 2. Validation aborts on change 1; change 2 is never validated, yet the service reports protocol_valid=true.
- **Impact:** a host receives false evidence that the entire input satisfied the structural contract.
- **Required remediation:** propagate the actual phase or split structural validation from target applicability checks. Treat header/manifest inconsistency as a protocol-validation failure; reserve applicability classification for the current-target hash check after full structural validation. Do not infer completion from a shared failure code.
- **Acceptance evidence:** multi-fault input reports protocol_valid=false and transaction_valid=null; a fully protocol-valid input whose header hash differs from the target still reports protocol_valid=true and transaction_valid=false. Neither mutates the target.
- **Status:** open; source-derived. Corresponds to earlier finding 3.

#### RUN-003 — Malformed-guard rejection writes the invalid value into a constrained DB column

- **Provenance:** C2 requires clean malformed-input rejection; known-target rejected attempts must remain auditable.
- **Evidence / trigger:** [pdcp_service.py:556–567](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L556-L567) detects a wrong-length expected_current_hash, but [pdcp_service.py:730–757](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L730-L757) inserts the original value into the log's VARCHAR(64) column ([models.py:185–187](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/storage/models.py#L185-L187)). Submit an otherwise valid request with a 65-character expected_current_hash.
- **Expected / actual / impact:** the intended context_invalid rejection reaches a flush that exceeds VARCHAR(64), producing a PostgreSQL data error and rollback instead of durable rejection. Adding a validator alone does not fix this persistence path.
- **Required remediation:** separate raw submitted guards from validated storage fields. Preserve invalid input in canonical input/diagnostic JSON and store null in the typed guard column when it is invalid; do not truncate audit input. Apply a storage-safe rule to wrong-type/out-of-range versions and malformed retry metadata.
- **Acceptance evidence:** the oversized hash through tools/call returns a durable context_invalid rejection, original invalid value remains inspectable, target/ledger are unchanged, and no raw DB error escapes. Include malformed version cases against live Postgres.
- **Root cause / status:** unvalidated request metadata is reused as typed persistence metadata. Open; source-derived failure in the shared malformed-input path.

### P3 — Low priority

None identified within the reviewed scope.

**Verification:** relevant source and existing test assertions were inspected; the listed regression acceptance cases have not been newly executed in this review.

**Category verdict:** Changes required.

## SVC — Services, orchestration and audit semantics

**Scope / coverage:** All 6 changed non-replay service modules plus relevant target service and MCP callers. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Inspect shared submit, request-ID lookup/fingerprinting/outcome reconstruction, retry lineage, advisory metadata, save/export/context paths and deprecated wrapper guard forwarding.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority


#### SVC-001 — Retry lineage accepts an accepted transaction as the rejected parent

- **Provenance:** [docs/MCP_TOOLS.md:143–145](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/docs/MCP_TOOLS.md#L143-L145) defines parent_pdcp_log_id as the rejected parent attempt when retrying.
- **Evidence:** [backend/app/services/pdcp_service.py:978–993](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L978-L993) checks UUID, existence, and target ownership, but not parent.status.
- **Trigger / actual:** use an accepted log from the same target as the parent of another valid submission. It passes parent validation and is recorded as retry lineage.
- **Impact:** consumers cannot interpret retry chains according to the published contract.
- **Required remediation:** enforce rejected status in the shared parent-validation path. Persist an ordinary context-invalid rejection with a null parent FK when the parent fails validation, matching the existing invalid-parent policy.
- **Acceptance evidence:** accepted same-target parent is rejected and logged; rejected same-target parent succeeds; existing malformed, nonexistent, and cross-target cases remain covered.
- **Status:** open; source-derived. Part of earlier finding 4.

### P3 — Low priority


#### SVC-002 — One-based retry attempt metadata has no value validation

- **Provenance:** MCP_TOOLS.md line 145 defines attempt as one-based.
- **Evidence:** [backend/app/services/pdcp_service.py:163–175](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L163-L175) forwards attempt to regeneration_attempt, and the shared submit path persists it. [backend/app/storage/models.py:170–181](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/storage/models.py#L170-L181) has an integer column without a positive-value constraint. An int annotation does not enforce a range at runtime.
- **Trigger / actual:** attempt=0 or -1 can be persisted for an otherwise valid request.
- **Impact:** audit metadata violates its own numbering contract; target edits can still be correct.
- **Required remediation:** validate optional attempt as a positive integer, explicitly rejecting booleans. Apply the rule at the shared submission boundary while preserving null as optional; define how malformed metadata is represented in a rejected attempt.
- **Acceptance evidence:** null and positive integers follow the contract; zero, negatives, booleans, and wrong types are cleanly rejected without mutation or raw DB errors.
- **Status:** open; lower-priority metadata issue. Part of earlier finding 4, split because it has a distinct fix.

**Verification:** relevant source and existing test assertions were inspected; the listed regression acceptance cases have not been newly executed in this review.

**Category verdict:** Changes required; no separate new regression asserted for the UUID hardening or deprecated guard forwarding.

## DB — Database, migrations, replay and concurrency

**Scope / coverage:** 4 changed DB/migration/replay files; engine, lock repository, target service and initial migration dependencies. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Review transaction/ORM boundaries, accepted-history dispatch/checks, schema alignment, unique request index, downgrade guard and DB evidence.

### P1 — High priority


#### DB-002 — A retained ORM target can bypass stale guards and overwrite a newer committed edit

- **Provenance:** paper sections 10/20 and A4/A6 require authoritative state checks and stale-proposal rejection. Locking is a mechanism for that guarantee.
- **Source:** [pdcp_service.py:203–223](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L203-L223) locks/loads through [repositories.py:8–14](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/storage/repositories.py#L8-L14) without refreshing an existing ORM instance. SessionLocal uses expire_on_commit=false. The final guard [pdcp_service.py:465–470](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L465-L470) compares that same in-memory object, and [pdcp_service.py:684–687](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/pdcp_service.py#L684-L687) writes content/version derived from it.
- **Authoritative ORM evidence:** SQLAlchemy documents that a later query normally does not repopulate an already-loaded object: https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html#populate-existing .
- **Concrete interleaving:** under default READ COMMITTED, A loads and retains target v0 with content "old"; B submits "old" -> "B" and commits v1; A calls submit_edits with expected_target_version=0 and "old" -> "A", then commits its outer transaction.
- **Expected / actual / impact:** A must reject against current v1. Instead, the lock query can return A's already-loaded v0 object. Stale guards and the in-memory final guard pass; A can overwrite "B" and append a second 0->1 log, breaking current state and replay continuity.
- **Required remediation:** refresh authoritative target state from the locked row before capturing before_* or checking guards, using populate_existing or an equivalent explicit locked refresh. Define how pending local target mutations are rejected so refresh cannot conceal unauthorized writes. Apply the boundary rule to other mutating services using the helper while preserving per-target atomicity.
- **Acceptance evidence:** a synchronized live two-session test retains A's object, commits B's edit, then verifies A's v0 request rejects target_version_mismatch, B/v1 remains intact, and rejection is recorded against current state. A subsequent valid v1 request produces v2 with a contiguous replay chain. Use synchronization rather than sleeps.
- **Origin and scope:** this shared-service weakness is present in the base and inherited by the new typed path; it is a modernization guarantee blocker, not a newly introduced regression. It affects callers reusing a Session with a retained target; it is not asserted for every fresh-session MCP call.
- **Root cause / status:** database locking was assumed to refresh the ORM identity map. Open, P1 due to potential lost updates; source-derived, not locally reproduced.

### P2 — Medium priority


#### DB-001 — Replay health compares database states from different read instants

- **Provenance:** C3 describes materialized_state_matches as integrity evidence for authoritative current state.
- **Evidence:** [backend/app/services/replay_service.py:62–75](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/replay_service.py#L62-L75) loads the target before [backend/app/services/replay_service.py:116–123](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/replay_service.py#L116-L123) separately loads accepted history. [backend/app/services/replay_service.py:212–230](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/services/replay_service.py#L212-L230) compares the reconstructed history with the previously loaded target. [backend/app/storage/db.py:11–12](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/backend/app/storage/db.py#L11-L12) specifies no stronger isolation.
- **Trigger / actual:** under PostgreSQL's default READ COMMITTED, session A loads target version N; session B commits N+1; session A reads accepted history including N+1. Its comparison uses the retained N target, producing a false unhealthy result for consistent committed data. PostgreSQL explicitly documents statement-level snapshots and differing successive SELECT results: https://www.postgresql.org/docs/16/transaction-iso.html#XACT-READ-COMMITTED .
- **Impact:** normal concurrent editing can be reported as materialized-state corruption.
- **Required remediation:** first define the replay observation boundary in C3, then ensure target, initial snapshot, and accepted-history reads share that boundary. A dedicated coherent read snapshot or a correctly scoped target lock can implement it; account for SQLAlchemy's identity map and callers with preloaded targets. Do not rely on the existence of a transaction alone.
- **Acceptance evidence:** a live Postgres two-session regression with controlled synchronization commits an edit between the target and history read positions. Replay must report a coherent version/hash/content cut. Separate actual tampering tests must still detect unhealthy state.
- **Reasoning:** write atomicity does not by itself make a multi-query diagnostic read coherent.
- **Status:** open; source-derived, not locally reproduced. Corresponds to earlier finding 1.

### P3 — Low priority

None identified within the reviewed scope.

**Migration evidence gap, separate from findings:** CI upgrades, downgrades and upgrades before any tests populate the database. test_migrations_reachable.py inspects metadata; test_migration_0002_offline.py renders SQL and checks strings. Neither executes a populated legacy roundtrip or typed-history downgrade refusal. Migration source contains the refusal guard, but the change document's reported local check is not independently reproduced here. Supply an isolated live Postgres test that seeds valid legacy history, verifies preservation through upgrade/downgrade/upgrade, then seeds typed accepted history and verifies refused downgrade leaves schema revision and rows intact. This does not assert that the migration is broken.

**Category verdict:** Changes required; DB-002 is the P1 merge blocker. Populated migration execution remains an evidence gap.

## SCRIPT — Scripts, evaluation and developer tooling

**Scope / coverage:** evaluation/offline_eval.py and evaluation/README.md. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Inspect byte accounting, matched/minimal proposals, scenario definitions and exit-status oracle. The script correctly limits performance claims to bytes; its failure gate is too permissive.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority


#### SCRIPT-001 — The equivalence gate excuses an unexpected parser failure in any scenario

- **Provenance:** A8 requires honest deterministic verdict accounting; only the named delimiter-collision case intentionally differs between formats.
- **Evidence:** [evaluation/offline_eval.py:143–161](https://github.com/paragon-ux/Patch-DIFF/blob/b31d73da0e41862f77e31cb518f8a88dabf1559b/evaluation/offline_eval.py#L143-L161) sets expressible_gap whenever PDCP rejects with block_malformed and both typed variants accept. It does not check that the current scenario is the delimiter-collision case.
- **Trigger / actual:** a regression makes the ordinary "1 tiny edit" PDCP path return rejected:block_malformed while both typed variants still accept. The predicate labels it an expressibility gap and all_equivalent can remain true.
- **Impact:** CI can report equivalence OK while an ordinary legacy proposal has regressed.
- **Required remediation:** encode explicit per-scenario expected results and allow a format difference only in the named delimiter case. For accepted cases, verify expected output/hash as well as agreement between implementations.
- **Acceptance evidence:** inject an unexpected block_malformed outcome into a non-delimiter scenario and require nonzero exit; require the intended delimiter case to pass only with its expected outcomes and output. An unexpected rejection shared by all formats must also fail.
- **Reasoning:** a comparison needs an independent oracle; shared failure or a broad exception is insufficient.
- **Status:** open; source-derived. Current CI output is not claimed to contain that regression.

### P3 — Low priority

None identified within the reviewed scope.

**Verification:** relevant source and existing test assertions were inspected; the listed regression acceptance cases have not been newly executed in this review.

**Category verdict:** Changes required.

## TEST — Tests and CI

**Scope / coverage:** All 11 changed test/workflow files, relevant unchanged helpers and inspected CI logs. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Read assertions and subprocess wiring, not only test names. Confirm real subprocess E2E exists; distinguish empty schema migration execution from populated safety tests.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority

None identified within the reviewed scope.

### P3 — Low priority

None identified within the reviewed scope.

**Verification gaps (not duplicate defect findings):**

1. DB-002: retain a target object across two live sessions and prove stale commit rejection after another writer commits.
2. DB-001: synchronize a concurrent commit between replay's target/history reads and prove a coherent observation cut.
3. MCP-001–002: validate documented value domains and cross-field guard requirements against actual tools/list schemas and submission. Current tests assert key sets/schema equality, not behavioral conformance.
4. RUN-001/RUN-003: exercise malformed risk containers and oversized/wrong-type guard metadata through the MCP boundary, asserting durable rejection and unchanged target/ledger.
5. RUN-002: use a multi-fault legacy transaction to establish actual stage completion.
6. SVC-001–002: cover an accepted same-target parent and invalid retry attempt values, beyond malformed/missing/cross-target parent cases.
7. ARCH-001–002: verify the selected default/cap and full bounded history continuation, beyond tests with small explicit page sizes.
8. SCRIPT-001: inject wrong verdicts/outputs and require the evaluation process to fail.
9. Migration: execute populated preservation/refusal cases described in DB verification.

The version-guard retry test proves its narrower stale-version case; it does not establish the guide's hash-only claim. The real stdio integration workflow is acknowledged as present and executed by CI; no stale finding claiming it is absent is carried forward. Parent/child DB configuration must be checked using the actual PATCHDIFF_DATABASE_URL variable (DOC-002).

**Category verdict:** No extra product defect counted here; verification remains incomplete for the newly identified cases.

## DEP — Dependencies, packaging and configuration

**Scope / coverage:** pyproject.toml, requirements.lock, configuration reader, Alembic environment/path setup, Docker configuration and installation instructions. Changed-file source/diff coverage completed; runtime reproduction limits apply.

**Review checks:** Compare declared direct dependency ranges with pinned versions, changed import paths and CI installation. CI demonstrates installation/use in Linux Python 3.11. No independently actionable packaging defect established in the changed files.

### P1 — High priority

None identified within the reviewed scope.

### P2 — Medium priority

None identified within the reviewed scope.

### P3 — Low priority

None identified within the reviewed scope.

**Verification:** the pinned direct dependency versions inspected fall within the declared project ranges. Existing CI installed requirements.lock and the editable project with --no-deps on Python 3.11, then exercised the suite. This supports that environment. A new local clean install, other Python versions and a Desktop host run were unavailable; compatibility outside that evidence is not certified. Configuration-command drift is owned by DOC-002, not counted twice here.

**Category verdict:** No findings identified within reviewed source/CI scope; a new local clean install or Desktop compatibility run was unavailable.

## Cross-category root causes and remediation order

1. **Authoritative state must be defined at the transaction boundary.** Resolve DB-002's retained-object write hazard first, then define C3's read observation boundary for DB-001. A row-lock token and a transaction wrapper are insufficient evidence of fresh/coherent application state.
2. **Reconcile contract definitions before changing behavior.** ARCH-001–002 and MCP-001–002 require an explicit decision on limits, continuation and accepted values; then align runtime, schema, guides and skills. Do not rewrite high-priority contracts merely to describe existing code.
3. **Validate audit metadata as carefully as edits.** RUN-001/RUN-003 and SVC-001–002 expose different ways untrusted data escapes or corrupts the rejection/lineage contract. Separate raw request evidence from typed persistence fields.
4. **Track actual phase completion.** RUN-002 requires stage provenance instead of inference from a shared failure reason.
5. **Require independent verification oracles.** SCRIPT-001 and key-only schema checks illustrate why matching names or agreeing outputs do not prove the advertised behavior.
6. **Make verification claims reviewable.** Correct DOC/SKILL drift, execute the relevant regressions on live Postgres, and update the as-built evidence matrix at the fix revision. Aggregate green counts remain evidence, not a merge decision.

The initial review's approval is not carried forward. Its shared-applier, overlap-profile, keyed recovery and real-subprocess observations are supported within the inspected scope. Its blanket contract/coherence sign-off is contradicted by the findings above; its strict manifest bound claim is false on the omitted-limit path. Its populated downgrade safety claim remains unverified by inspected CI/tests.

## Finding closure record

Every finding remains open. Closure requires the fix commit, relevant acceptance evidence at that revision, and category re-review; a new commit or green suite alone is not closure. P3 items are lower priority and can be explicitly deferred with a recorded rationale.

| ID | Priority | Status | Fix commit | Acceptance evidence / recheck |
| --- | --- | --- | --- | --- |
| ARCH-001 | P2 | Open | — | Required / not yet supplied |
| ARCH-002 | P2 | Open | — | Required / not yet supplied |
| DB-002 | P1 | Open | — | Required / not yet supplied |
| DB-001 | P2 | Open | — | Required / not yet supplied |
| DOC-001 | P2 | Open | — | Required / not yet supplied |
| DOC-002 | P2 | Open | — | Required / not yet supplied |
| DOC-003 | P3 | Open | — | Required / not yet supplied |
| MCP-001 | P2 | Open | — | Required / not yet supplied |
| MCP-002 | P2 | Open | — | Required / not yet supplied |
| RUN-001 | P2 | Open | — | Required / not yet supplied |
| RUN-002 | P2 | Open | — | Required / not yet supplied |
| RUN-003 | P2 | Open | — | Required / not yet supplied |
| SCRIPT-001 | P2 | Open | — | Required / not yet supplied |
| SKILL-001 | P3 | Open | — | Required / not yet supplied |
| SKILL-002 | P3 | Open | — | Required / not yet supplied |
| SVC-001 | P2 | Open | — | Required / not yet supplied |
| SVC-002 | P3 | Open | — | Required / not yet supplied |

## Changed-file inventory

All paths below refer to head b31d73da0e41862f77e31cb518f8a88dabf1559b; each changed file has one primary category. “Reviewed” identifies source/diff inspection, not new execution or absolute correctness. Cross-category dependencies were considered in the corresponding sections.

| Category | Changed file | Coverage |
| --- | --- | --- |
| SKILL | .agents/skills/patchdiff-core-runtime/SKILL.md | Reviewed |
| SKILL | .agents/skills/patchdiff-mcp-orchestration/SKILL.md | Reviewed |
| SKILL | .agents/skills/patchdiff-persistence-replay-save/SKILL.md | Reviewed |
| SKILL | .agents/skills/patchdiff-testing-review/SKILL.md | Reviewed |
| DOC | .github/PULL_REQUEST_TEMPLATE.md | Reviewed |
| TEST | .github/workflows/ci.yml | Reviewed |
| SKILL | AGENTS.md | Reviewed |
| DOC | README.md | Reviewed |
| DOC | README_INTERNAL_MCP.md | Reviewed |
| RUN | backend/app/core/result.py | Reviewed |
| RUN | backend/app/core/validity.py | Reviewed |
| RUN | backend/app/core/versions.py | Reviewed |
| MCP | backend/app/mcp/external_adapter.py | Reviewed |
| MCP | backend/app/mcp/tools.py | Reviewed |
| DB | backend/app/migrations/alembic.ini | Reviewed |
| DB | backend/app/migrations/versions/20261020_0002_typed_ledger.py | Reviewed |
| RUN | backend/app/pdcp/applier.py | Reviewed |
| RUN | backend/app/pdcp/disambiguation.py | Reviewed |
| RUN | backend/app/pdcp/matcher.py | Reviewed |
| RUN | backend/app/pdcp/typed.py | Reviewed |
| SVC | backend/app/services/export_service.py | Reviewed |
| SVC | backend/app/services/pdcp_service.py | Reviewed |
| SVC | backend/app/services/prompt_context_service.py | Reviewed |
| SVC | backend/app/services/read_service.py | Reviewed |
| SVC | backend/app/services/regeneration_service.py | Reviewed |
| DB | backend/app/services/replay_service.py | Reviewed |
| SVC | backend/app/services/save_service.py | Reviewed |
| DB | backend/app/storage/models.py | Reviewed |
| TEST | backend/tests/integration/test_external_mcp_e2e.py | Reviewed |
| TEST | backend/tests/integration/test_mcp_tools.py | Reviewed |
| TEST | backend/tests/integration/test_migrations_reachable.py | Reviewed |
| TEST | backend/tests/integration/test_typed_submit_flow.py | Reviewed |
| TEST | backend/tests/unit/test_matcher.py | Reviewed |
| TEST | backend/tests/unit/test_migration_0002_offline.py | Reviewed |
| TEST | backend/tests/unit/test_modernization_contracts.py | Reviewed |
| TEST | backend/tests/unit/test_mutation_boundary.py | Reviewed |
| TEST | backend/tests/unit/test_stdio_adapter_subprocess.py | Reviewed |
| TEST | backend/tests/unit/test_typed_transaction.py | Reviewed |
| DOC | docs/CLAUDE_DESKTOP_SETUP.md | Reviewed |
| DOC | docs/CODEX_BUILD_PLAN.md | Reviewed |
| DOC | docs/DATA_MODEL.md | Reviewed |
| DOC | docs/HOST_INTEGRATION_GUIDE.md | Reviewed |
| ARCH | docs/MCP_FIRST_MVP.md | Reviewed |
| DOC | docs/MCP_TOOLS.md | Reviewed |
| ARCH | docs/MODERNIZATION_ARCHITECTURE.md | Reviewed |
| DOC | docs/MODERNIZATION_CHANGE_DOC.md | Reviewed |
| ARCH | docs/PATCHDIFF_CORE_SPEC.md | Reviewed |
| DOC | docs/PDCP_FORMAT.md | Reviewed |
| DOC | docs/PR_REVIEW_STANDARD.md | Reviewed |
| DOC | docs/TEST_MATRIX.md | Reviewed |
| DOC | docs/reviews/PR-1-39dcb4b-category-review.md | Reviewed |
| SCRIPT | evaluation/README.md | Reviewed |
| SCRIPT | evaluation/offline_eval.py | Reviewed |
| DEP | pyproject.toml | Reviewed |
| DEP | requirements.lock | Reviewed |

**Additional unchanged dependencies examined:** storage/db.py and repositories.py; core/config.py and canonicalization.py; pdcp/parser.py, protocol_validator.py and models.py; services/target_service.py; mcp/server.py; migration env.py and 0001; test helpers/conftest; docker-compose.yml. The concept paper was read, and relevant frozen implementation sections on matching, disambiguation and transaction consistency were checked. Bibliography claims and every historical-spec section were not independently audited.

**Overall disposition:** request changes. Changed-file source coverage is complete; acceptance execution for the new findings and populated migration safety is incomplete. Re-review affected categories at the fix SHA before claiming completion or recommending merge.
