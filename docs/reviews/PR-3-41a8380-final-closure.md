# PR #3 — Final remediation review and closure

## 1. Metadata, scope and evidence limits

**Disposition: approve PR #3 for merge into PR #1's feature branch.** No open actionable findings remain within this remediation scope. This is not a new blanket approval of PR #1 into main.

- Repository / PR: [paragon-ux/Patch-DIFF #3](https://github.com/paragon-ux/Patch-DIFF/pull/3).
- Review date: 2026-10-20, America/New_York.
- Standard: PR_REVIEW_STANDARD.md v1.1.0.
- Base: 60fa01fc92bdeff16929b68f6f0d3c838da3d394.
- Material code revision reviewed and executed: 41a83806519eb556fbef3f8a98803cc79a937347.
- Integration target: feature/modernization-argon-remediation, the head branch of PR #1. Main is not the merge target.
- Predecessor: [existing-finding recheck](PR-1-60fa01f-findings-recheck.md). Historical reports remain unchanged.
- Independent subagent examined the first correction revision (68b9c54 / evidence-only 1b57f6c), reproduced DB-003 and SVC-003 against live Postgres and returned their triggers. It did not deliver a completed approval report before exhausting usage. At the user's explicit request, the primary agent took over final review and rechecked the corrections, affected contracts, tests and live evidence. Final closure is attributed to the primary agent, not an unissued subagent approval.
- A final documentation/test-fixture-only delta restores the original Unicode fixture bytes and the correct non-empty MATCH description, records the evidence and closes finding statuses. The affected typed parser tests were rerun: 56 passed. No runtime behavior changed after 41a8380.

Source review covered the complete PR #3 change scope and relevant unchanged dependencies. Whole-PR #1 behavior outside the remediation remains governed by the earlier review and its limits. The design paper's transaction thesis was examined in the predecessor review and re-used here; vendor ecosystem claims and a live-model/desktop-host benchmark were not newly audited. Approval is based on source/contract inspection, concrete acceptance checks and exact revision evidence, not pass percentages.

## 2. Changed-file inventory and category coverage

Every changed path has one primary category. Inventory includes the final report/evidence files. Reviewed means source/diff or recorded-evidence inspection for this PR's scope, not certification of every possible behavior.

| Category | Changed file | Coverage |
| --- | --- | --- |
| SKILL | .agents/skills/patchdiff-core-runtime/SKILL.md | Reviewed |
| SKILL | .agents/skills/patchdiff-mcp-orchestration/SKILL.md | Reviewed |
| SKILL | .agents/skills/patchdiff-persistence-replay-save/SKILL.md | Reviewed |
| SKILL | .agents/skills/patchdiff-testing-review/SKILL.md | Reviewed |
| SKILL | AGENTS.md | Reviewed |
| RUN | backend/app/core/versions.py | Reviewed |
| MCP | backend/app/mcp/external_adapter.py | Reviewed |
| DB | backend/app/migrations/env.py | Reviewed |
| RUN | backend/app/pdcp/typed.py | Reviewed |
| SVC | backend/app/services/pdcp_service.py | Reviewed |
| DB | backend/app/services/replay_service.py | Reviewed |
| TEST | backend/tests/integration/test_external_mcp_e2e.py | Reviewed |
| TEST | backend/tests/integration/test_migrations_reachable.py | Reviewed |
| TEST | backend/tests/integration/test_submission_schema_domains.py | Reviewed |
| TEST | backend/tests/integration/test_validation_profile_compatibility.py | Reviewed |
| TEST | backend/tests/unit/test_typed_transaction.py | Reviewed |
| DOC | docs/CODEX_BUILD_PLAN.md | Reviewed |
| DOC | docs/DATA_MODEL.md | Reviewed |
| DOC | docs/HOST_INTEGRATION_GUIDE.md | Reviewed |
| ARCH | docs/MCP_FIRST_MVP.md | Reviewed |
| ARCH | docs/MODERNIZATION_ARCHITECTURE.md | Reviewed |
| DOC | docs/MODERNIZATION_CHANGE_DOC.md | Reviewed |
| ARCH | docs/PATCHDIFF_CORE_SPEC.md | Reviewed |
| DOC | docs/PDCP_FORMAT.md | Reviewed |
| DOC | docs/TEST_MATRIX.md | Reviewed |
| DOC | docs/reviews/PR-1-60fa01f-findings-recheck.md | Reviewed |
| DOC | docs/reviews/PR-3-41a8380-final-closure.md | Reviewed |
| TEST | docs/reviews/PR-3-final-stdio-live.json | Reviewed |
| TEST | docs/reviews/PR-3-live-verification.json | Reviewed |
| TEST | docs/reviews/PR-3-replay-compatibility-live.json | Reviewed |
| SCRIPT | evaluation/README.md | Reviewed |
| DEP | pyproject.toml | Reviewed |
| DEP | requirements.lock | Reviewed |

Relevant unchanged dependencies examined: MCP registry/tool wrappers; typed/legacy applier and disambiguator; core validity, hashing and canonicalization; target/SAVE services; storage models, db/session factory and locked repository query; original and typed-ledger migrations; integration helpers; CI configuration and pinned installation path.

| Category | Coverage within PR #3 | Verdict |
| --- | --- | --- |
| ARCH | Complete: preserved contracts, strict/current versus historical decoding and request recovery | No findings within reviewed scope |
| DOC | Complete: changed active records, recovery guide and preserved historical reports | No findings within reviewed scope |
| SKILL | Complete: four changed skills and relevant instructions | No findings within reviewed scope |
| MCP | Complete: changed discovery/domain boundary and its service path | No findings within reviewed scope |
| RUN | Complete: strict parsing, metadata sanitizer and recorded profiles | No findings within reviewed scope |
| SVC | Complete: changed exact-key recovery and durable rejection path | No findings within reviewed scope |
| DB | Complete: affected replay and migration-isolation mechanism | No findings within reviewed scope |
| SCRIPT | Complete: changed evaluation guidance; unchanged oracle checked by prior review | No findings within reviewed scope |
| TEST | Complete: new/modified regression assertions, manual records and inspected CI | No findings within reviewed scope |
| DEP | Complete: test-only dependency declaration/lock additions and existing CI install | No findings within reviewed scope |

## 3. Architecture-to-implementation trace

| Invariant / decision | Contract and implementation | Acceptance evidence |
| --- | --- | --- |
| Deterministic, exact, sequential, atomic target updates | Core/applier boundary preserved; no fuzzy repair or model execution introduced | Full runtime/integration suite and live target/ledger inspection |
| Audit every representable known-target domain rejection | C2/D4: strict hash fullmatch; malformed metadata becomes null in constrained fields while raw evidence remains | Typed and legacy newline guards produce durable rejected rows, unchanged target/version and no accepted ledger |
| Discovery agrees on representable structural domains | C1: non-null guard anyOf, nonblank prose, integer bounds and full ID/hash patterns; service retains business validation | Actual tools/list schema evaluated with jsonschema, then corresponding live submission and persisted effects |
| Preserve all recorded history | C3 / DB-003: 0.2.1 strict submit; explicit 0.2.0 and 0.1.0 historical decoding and matcher profiles | Exact base parser produced durable old newline-ID acceptance; current replay and mixed-profile replay remain healthy without rewriting bytes |
| Preserve recorded request outcomes | C4 / SVC-003: exact existing key lookup under target lock precedes new-key validation; unchanged fingerprints distinguish retry/conflict | Accepted/rejected legacy keys recover same log; conflict creates no replacement row; fresh invalid key on another target rejects |
| Migration safety | Caller-supplied Alembic connection lets tests own schema/transaction scope | Populated legacy upgrade/downgrade/upgrade preservation; typed-history refusal preserves rows/revision and replay |
| Host owns recovery decisions | Guide distinguishes request IDs, guards, paged evidence and unknown in-flight outcomes | Source reconciliation against actual response keys and live recovery |
| Meaningful validity | Skills use actual stage provenance and null/unreached semantics, including simulation validity at commit failure | Enum/mapping/source reconciliation; existing multi-fault assertions preserved |

## 4. Required category records

### ARCH — Architecture and contracts

**Scope / coverage:** Complete for changed active specifications and the C1/C2/C3/C4 consequences. Historical design thesis and original boundaries remain intact. DB-003 and SVC-003 are owned below, not counted twice.

#### P1 — High priority

None identified within reviewed scope.

#### P2 — Medium priority

None identified within reviewed scope.

#### P3 — Low priority

None identified within reviewed scope.

**Verification:** Inspected strict/current versus recorded-profile decisions and caller ownership; source and live mixed-profile checks establish selected compatibility. **Gaps:** arbitrary SQL writers bypassing the target-lock discipline and whole-PR #1 areas outside this delta are not certified. **Verdict:** no findings within reviewed scope.

### DOC — Documentation and change records

**Scope / coverage:** Complete for changed active docs and historical-report preservation.

#### P1 — High priority

None identified within reviewed scope.

#### P2 — Medium priority

DOC-001 **closed** by 68b9c54: recovery guide distinguishes version/hash checks from request identity, does not infer non-arrival from a five-row page, requires paged inspection and treats an in-flight or ambiguous outcome as unknown. It states optional legacy guards, actual context_invalid/conflict metadata and printable-ASCII keys.

#### P3 — Low priority

None identified within reviewed scope. Final source reconciliation corrected an inadvertently overstrict prose description: MATCH is non-empty, including whitespace, whereas intent/rationale are nonblank.

**Verification:** Source reconciliation against the actual API and persistence; active finding subjects/priorities restored to their original IDs; old reports preserved. **Gaps:** external vendor claims and historical bibliography not newly audited. **Verdict:** no open findings within reviewed scope.

### SKILL — Skills and agent instructions

**Scope / coverage:** Complete for four skills and AGENTS delta.

#### P1 — High priority

None identified within reviewed scope.

#### P2 — Medium priority

None identified within reviewed scope.

#### P3 — Low priority

SKILL-001 **closed** by 68b9c54 and final reconciliation: exact five enums, null unreached stages, precondition versus protocol/applicability and commit-stage simulation validity are described correctly.

SKILL-002 **closed** by 68b9c54 / 41a8380: real matcher signature/tuple result, one-based occurrence indices, advisory-only region_hint, actual facts/types/sequence names, optional UUID choice, supplied typed risk behavior, canonical replay hash-failure labels and explicit historical profile/recovery notes.

**Verification:** Instructions compared with implementation, schema and storage definitions; no runtime alteration was made merely to satisfy incorrect guidance. **Gaps:** no claim that every future agent will follow the instructions. **Verdict:** no open findings within reviewed scope.

### MCP — MCP schemas and public API

**Scope / coverage:** Complete for discovery changes and submission boundaries.

#### P1 — High priority

None identified within reviewed scope.

#### P2 — Medium priority

MCP-001 **closed** by 68b9c54: actual discovery requires a valid non-null guard alternative and advertises nullable bounded metadata, nonblank intent/rationale and exact patterns. Existing service validation remains authoritative; missing guards now reach durable rejection instead of an early unaudited tool error.

MCP-002 **closed** by 68b9c54 with DB-003 compatibility correction in 41a8380: new change IDs use full-string grammar, allow colon/null/default IDs and retain uniqueness checks. Trailing newline rejects; historical decoder behavior is explicitly versioned.

#### P3 — Low priority

None identified within reviewed scope.

**Verification:** Actual tools/list schemas, JSON Schema validator, domain matrix, in-process live audit checks and real stdio calls. **Gaps:** database existence, uniqueness across edits and idempotency identity remain service/business rules, not JSON Schema assertions. Fresh calls with obsolete invalid keys reject, while exact stored-key recovery is the documented compatibility exception. **Verdict:** no open findings within reviewed scope.

### RUN — Core runtime, parsing and validation

**Scope / coverage:** Complete for changed typed parser, hash sanitizer and runtime profiles; unchanged applier/canonicalization inspected as dependencies.

#### P1 — High priority

None identified within reviewed scope. DB-003 owns the resolved replay regression.

#### P2 — Medium priority

RUN-003 **closed** by 68b9c54: fullmatch prevents newline-suffixed SHA-256 metadata from entering VARCHAR(64). Both formats retain normal rejected outcomes, raw invalid evidence, null constrained hash values and healthy subsequent submissions.

#### P3 — Low priority

None identified within reviewed scope.

**Verification:** Unit/domain tests, live typed/legacy audit rows, actual stdio requests and final-profile check. The original Unicode round-trip fixture bytes were restored in the final test-only reconciliation and all 56 typed parser tests passed. **Gaps:** no model task-correctness/semantic claim. **Verdict:** no open findings within reviewed scope.

### SVC — Services, orchestration and audit semantics

**Scope / coverage:** Complete for changed locked request-key lookup, validation and cached-outcome/conflict paths.

#### P1 — High priority

None identified within reviewed scope.

#### P2 — Medium priority

**SVC-003 — Stricter request-key syntax broke recovery of a stored legacy key. CLOSED at 41a8380.**
- Provenance: C4 requires identical requests to recover their recorded outcome, independent of later target state.
- Independent subagent trigger at first correction: base code accepted an ID ending in newline; the corrected syntax ran before lookup and rejected the identical retry with a new rejection row.
- Expected versus observed before fix: recover original accepted/rejected log; instead context_invalid, no deduplication. Live reproduction was rolled back.
- Root cause: applying new-key syntax before determining whether an exact historical key already exists.
- Fix: exact string lookup under the target lock; only an existing key bypasses new-key syntax. Existing request fingerprint still governs same versus conflicting proposal. Fresh invalid keys, including the same raw value on another target, reject normally.
- Acceptance: both recorded statuses recover the same log without additional rows; conflicting reuse rejects without replacing history; final direct live Postgres check used the exact old validator, committed fixtures and then restored current code. See live compatibility JSON.
- Residual limit: no normalization/aliasing of key text; matching is exact.

#### P3 — Low priority

None identified within reviewed scope.

**Verification:** New accepted/rejected legacy-key regressions, direct base-code live experiment and current-profile stdio deduplication. Original SVC-001/SVC-002 lineage/attempt checks remain passing. **Gaps:** arbitrary SQL corruption and external transport guarantees are outside this scope. **Verdict:** no open findings within reviewed scope.

### DB — Database, migrations, replay and concurrency

**Scope / coverage:** Complete for changed replay profile dispatch and supplied Alembic connection; unchanged lock, model and migration definitions inspected.

#### P1 — High priority

**DB-003 — Stricter current parsing invalidated accepted historical typed history. CLOSED at 41a8380.**
- Provenance: locked invariants and C3 require replay under recorded protocol/runtime behavior.
- Independent subagent trigger: exact base typed parser accepted a newline-suffixed change ID under runtime 0.2.0. Restored initial-correction decoder failed replay_protocol_invalid.
- Expected versus observed before fix: replay accepted immutable history; instead current fullmatch reinterpreted the old record while runtime version remained unchanged.
- Impact: historical replay failure despite valid original acceptance.
- Fix: new submissions record 0.2.1; decode_record receives and validates the recorded runtime. Only explicit supported historical profiles retain the original ID grammar and matcher semantics. New submissions are always strict; unknown versions fail.
- Acceptance: historical acceptance/current rejection and mixed-profile replay regressions; exact base-code live acceptance followed by current replay produced healthy gamma/version 2, preserved old record bytes, and wrote new history under 0.2.1.
- Residual limit: no historical row is rewritten or silently trimmed.

#### P2 — Medium priority

None identified within reviewed scope.

#### P3 — Low priority

None identified within reviewed scope.

**Verification:** Full live-backed integration suite, standalone isolated migration checks, direct base/current compatibility experiment and existing synchronized row-lock checks retained. Populated legacy accepted/rejected history, snapshots, cycle and target rows survive upgrade/downgrade/upgrade. Refused typed downgrade leaves revision and full row snapshot unchanged and still replayable. **Gaps:** migration evidence uses owned schemas on live Postgres, not arbitrary production datasets; no protection against writers bypassing target locking. **Verdict:** no open findings within reviewed scope.

### SCRIPT — Scripts, evaluation and developer tooling

**Scope / coverage:** Changed evaluation guidance and the unchanged oracle assertions from the predecessor review. No runtime evaluation script change.

#### P1 — High priority

None identified within reviewed scope.

#### P2 — Medium priority

None identified within reviewed scope. SCRIPT-001 remains closed; independent expected verdicts/hashes and named delimiter exemption are preserved.

#### P3 — Low priority

None identified within reviewed scope.

**Verification:** Offline evaluation rerun after runtime-profile changes, result OK. **Gaps:** bytes/deterministic outcomes only; no token/latency/model or task-success benchmark. **Verdict:** no findings within reviewed scope.

### TEST — Tests and CI

**Scope / coverage:** Complete for modified/new tests, migration fixtures, manual evidence and actual CI checkout logs.

#### P1 — High priority

None identified within reviewed scope.

#### P2 — Medium priority

TEST-001 **closed** by 68b9c54: test-owned random schemas remove prior-history/order dependence. Actual initializer/session/initial version zero is used; a fresh fixture must create and assert typed acceptance before refusal. The original TypeError branch no longer exists. Refusal asserts both revision and preserved data, then replay; a separate populated legacy roundtrip compares preserved fields and rows.

#### P3 — Low priority

None identified within reviewed scope.

**Verification:** 319 tests passed (181 unit / 138 live Postgres integration); isolated migration module separately passed; actual new schemas and stdio child exercised. Manual checks outside pytest are separately pinned below. CI confirms 181/138 at the generated merge revision. **Gaps:** no OS/Python matrix or exhaustive adversarial input space; a green count alone did not establish closure. **Verdict:** no open findings within reviewed scope.

### DEP — Dependencies, packaging and configuration

**Scope / coverage:** Complete for test-only jsonschema direct dependency, pinned transitive additions and existing installation/CI configuration.

#### P1 — High priority

None identified within reviewed scope.

#### P2 — Medium priority

None identified within reviewed scope.

#### P3 — Low priority

None identified within reviewed scope.

**Verification:** jsonschema >=4,<5 is in the test extra; requirements.lock pins the actual tested version and dependencies. Production code does not import it or introduce transport auto-rejection. Existing CI installs the lockfile and editable package successfully. **Gaps:** no new clean-install matrix, dependency security audit or other Python-version certification. **Verdict:** no findings within reviewed scope.

## 5. Cross-category root causes and remediation order

1. New-domain tightening required separating current validation from immutable accepted history (DB-003).
2. Exact request identity must remain recoverable before applying new-key admission syntax (SVC-003).
3. Full-string validation, safe metadata persistence and schema advertising needed joint checks (MCP-001/002, RUN-003).
4. Self-contained live migration fixtures were necessary to prove preservation/refusal (TEST-001).
5. Guidance now reflects actual stage, matching, identity and recovery semantics; historical review claims remain preserved as historical evidence.

No confirmed defect was dropped because of lower priority. All nine findings handled by this PR (six original open findings, TEST-001 and the two independent-review compatibility findings) have explicit closure evidence. Eleven original findings remain closed as established in the predecessor recheck.

## 6. Verification record

| Evidence | Exact revision / environment | Result |
| --- | --- | --- |
| Full pytest suite after compatibility fix | Material code at 41a8380, local Windows / live Postgres16.3 | 319 passed: 181 unit + 138 integration |
| Typed parser suite after restoring original Unicode fixture | Final fixture-only delta over 41a8380 | 56 passed |
| Offline evaluation | Compatibility code at 41a8380 | OK |
| Standalone migration module | Same migration code, owned temporary Postgres schemas | 6 passed; populated legacy roundtrip and typed refusal preservation |
| Final actual stdio + independent DB inspection outside pytest | 41a8380 | PASS, server0.2.1; newline hash and missing guard durably rejected, current edit/dedup/replay healthy |
| Exact base parser/validator + current persistent service, outside pytest | 41a8380; fixture parser/validator bytes from base60fa01f | PASS, immutable historical record replays and accepted/rejected keys recover; mixed0.2.0/0.2.1 history healthy |
| Earlier manual stdio restart experiment | 68b9c54, explicitly superseded for compatibility behavior | PASS, ten durable rejections, no target/ledger mutation, dedup after restart/later commit |
| Inspected PR CI [run39501529225](https://github.com/paragon-ux/Patch-DIFF/actions/runs/39501529225) / job118899951720 | Generated merge6449114b6270684279e81cf2121f8c0092ec9488, combining code41a8380 with base60fa01f; Linux/Python3.11/Postgres16.3 | Logs:181 unit +138 integration passed, offlineOK |

Manual records:
- [Final stdio live evidence](PR-3-final-stdio-live.json).
- [Historical compatibility live evidence](PR-3-replay-compatibility-live.json).
- [Earlier restart/audit live evidence](PR-3-live-verification.json).

The independent subagent's DB-003/SVC-003 reproductions and final primary-agent recheck are distinct evidence stages. No final independent subagent approval is claimed after its usage exhaustion. No deployment, live-model benchmark or broad main-branch approval is implied.

## 7. Finding closure table and disposition

| ID | Priority | Status | Fix / acceptance evidence |
| --- | --- | --- | --- |
| ARCH-001 | P2 | Closed, carried forward | 30dd14f; bounded read/Unicode continuation rechecked in predecessor |
| ARCH-002 | P2 | Closed, carried forward | 30dd14f; 230-entry/two-cycle pagination rechecked |
| DB-002 | P1 | Closed, carried forward | c1df5b9; authoritative retained-state and caller-transaction checks |
| DB-001 | P2 | Closed, carried forward | c1df5b9; fresh locked coherent replay and live synchronization |
| DOC-001 | P2 | Closed | 68b9c54; current guide reconciled with recovery/runtime |
| DOC-002 | P2 | Closed, carried forward | 68dce30; actual database-setting consumer chain verified |
| DOC-003 | P3 | Closed, carried forward | 44fc6e1; existing historical reference paths |
| MCP-001 | P2 | Closed | 68b9c54; actual schema/live domain+audit matrix |
| MCP-002 | P2 | Closed | 68b9c54 +41a8380; strict current grammar and historical-profile preservation |
| RUN-001 | P2 | Closed, carried forward | b5a54f3; unhashable risk rejection/audit retained |
| RUN-002 | P2 | Closed, carried forward | b5a54f3; actual stage provenance retained |
| RUN-003 | P2 | Closed | 68b9c54; both-format live newline hash rejection, null metadata and raw evidence |
| SVC-001 | P2 | Closed, carried forward | abeb58e; rejected-parent lineage retained |
| SVC-002 | P3 | Closed, carried forward | abeb58e; strict attempt metadata retained |
| SCRIPT-001 | P2 | Closed, carried forward | 78b16e6; independent oracle preserved and offline evaluation rerun |
| SKILL-001 | P3 | Closed | 68b9c54; actual enum/stage/null mapping |
| SKILL-002 | P3 | Closed | 68b9c54 +41a8380; matcher/index/ID/storage/sequence/failure/profile reconciliation |
| TEST-001 | P2 | Closed | 68b9c54; isolated fresh/populated migration preservation/refusal assertions |
| DB-003 | P1 | Closed | 41a8380; exact historical acceptance/current replay and mixed profiles |
| SVC-003 | P2 | Closed | 41a8380; accepted/rejected legacy-key recovery, conflict and fresh-key rejection |

Final recommendation: merge PR #3 into feature/modernization-argon-remediation once final-head CI succeeds. Preserve the PR #1 review history and leave PR #1 open against main.

## Immutable source evidence index

- MCP-001: [backend/app/mcp/external_adapter.py:150-185](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/app/mcp/external_adapter.py#L150-L185)
- MCP-002 / DB-003: [backend/app/pdcp/typed.py:179-203](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/app/pdcp/typed.py#L179-L203)
- MCP-002 / DB-003: [backend/app/pdcp/typed.py:298-314](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/app/pdcp/typed.py#L298-L314)
- RUN-003: [backend/app/services/pdcp_service.py:67-72](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/app/services/pdcp_service.py#L67-L72)
- SVC-003: [backend/app/services/pdcp_service.py:280-379](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/app/services/pdcp_service.py#L280-L379)
- DB-003: [backend/app/core/versions.py:9-23](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/app/core/versions.py#L9-L23)
- DB-003: [backend/app/services/replay_service.py:253-261](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/app/services/replay_service.py#L253-L261)
- TEST-001: [backend/tests/integration/test_migrations_reachable.py:105-207](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/tests/integration/test_migrations_reachable.py#L105-L207)
- DB-003 / SVC-003 assertions: [backend/tests/integration/test_validation_profile_compatibility.py:18-66](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/backend/tests/integration/test_validation_profile_compatibility.py#L18-L66)
- DOC-001: [docs/HOST_INTEGRATION_GUIDE.md:97-119](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/docs/HOST_INTEGRATION_GUIDE.md#L97-L119)
- SKILL-001: [.agents/skills/patchdiff-core-runtime/SKILL.md:114-130](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/.agents/skills/patchdiff-core-runtime/SKILL.md#L114-L130)
- SKILL-002: [.agents/skills/patchdiff-persistence-replay-save/SKILL.md:40-121](https://github.com/paragon-ux/Patch-DIFF/blob/41a83806519eb556fbef3f8a98803cc79a937347/.agents/skills/patchdiff-persistence-replay-save/SKILL.md#L40-L121)
