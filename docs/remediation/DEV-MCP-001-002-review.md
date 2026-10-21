# DEV-MCP-001/002 independent review

Date: 2026-10-21.
Repository: paragon-ux/Patch-DIFF.
Branch: fix/devin-mcp-history.
Reviewer: independent inherited-default-model selector_independent_review agent.
Standard: PR_REVIEW_STANDARD.md v1.1.0.
Base: dd5877de5d50ccae19faca12a6fb8463a291ec60.
Contract-first: 46841ecfa027c24bd6458a98e3675274f03793fd.
Production fix: 3b122dfa3d22e9e5d62c381131292417506d9bd0.
Reviewed final material/test head: 69f6a646270ab74aba54eca635e2a6ea9cca968a.
Workstream PR: not yet opened at review time; stacked on PR #7.

## Scope and evidence limits

DEV-MCP-001 and DEV-MCP-002 are independently classified fixed within this scope. No actionable P1/P2/P3 candidate remains. This is a scoped approval recommendation, not whole-PR #1 approval or authorization to merge.

The reviewer inspected contracts, the complete production delta, both new test modules, affected active documentation and connected unchanged read/registry/storage dependencies. The original concept paper's abstract and opening sections were examined for the authoritative-target/advisory-context thesis. No new external ecosystem claim is needed for these local contract corrections.

Execution provenance is separate:
- Reviewer executed the initial new pure unit module: 107 cases passed. The final two omitted-limit cases and default-content assertion were source-rechecked at 69f6a64; they were included in the parent's final execution.
- Parent's isolated final run executed 69f6a64: 834 passed, 9 existing warnings, 37.52 seconds; 613 unit and 221 live PostgreSQL integration cases. Exact stdout: docs/remediation/DEV-MCP-001-002-pytest.txt. Offline verdict equivalence was reported OK.
- Outside-pytest manual PostgreSQL and real stdio execution used production pin 3b122df. The subsequent two commits change tests only. Inspected evidence: docs/remediation/DEV-MCP-001-002-live.json.
- Reviewer independently read the manual target through direct PostgreSQL SELECTs and both public history handlers; no database row was modified. The reviewer did not independently launch a second stdio subprocess or rerun the full DB suite.
- Prior PR #7 CI evidence names generated merge 20c66c530cbaebf199828fed804e046f1e0e841e, not this workstream. No current-workstream remote CI result was available at review time.
- OCR's deterministic preview launcher failed because its installed npm module was missing. Git inventory, direct source inspection and independent execution supplied review evidence; no OCR-generated verdict is claimed.

The user forbids modifying docs/reviews/. This owned report is written under docs/remediation/ as authorized. All twelve protected review hashes were independently checked unchanged. Only this report was written by the reviewer.

## Changed-file inventory and coverage matrix

Inventory is the base-to-69f6a64 comparison, thirteen files. Each has exactly one primary category. Closure/evidence files subsequently committed require a documentation/evidence delta check.

| Category | Primary changed files | Coverage |
| --- | --- | --- |
| ARCH | docs/MODERNIZATION_ARCHITECTURE.md | Complete for C6 changes |
| DOC | docs/HOST_INTEGRATION_GUIDE.md; docs/MODERNIZATION_CHANGE_DOC.md; docs/remediation/WORKFLOW.md | Complete for affected active guidance |
| SKILL | .agents/skills/patchdiff-mcp-orchestration/SKILL.md | Complete for changed guidance |
| MCP | backend/app/mcp/external_adapter.py; backend/app/mcp/tools.py; docs/MCP_TOOLS.md | Complete for affected API/schema/routing |
| RUN | No changed files | Connected matcher/canonicalization/input-text dependency review |
| SVC | backend/app/services/read_service.py | Complete for context validation and read path |
| DB | No changed files | Connected models, query ordering/filtering and cycle semantics |
| SCRIPT | No changed files | Connected adapter entry point and evaluator scope |
| TEST | backend/tests/unit/test_mcp_arguments_paging.py; backend/tests/integration/test_mcp_history_paging_live.py; docs/TEST_MATRIX.md; docs/remediation/DEV-DB-001-CI.json | Complete for changed tests/evidence provenance |
| DEP | No changed files | Connected packaging/configuration and CI startup |

Additional pending evidence inspected: DEV-MCP-001-002-live.json and DEV-MCP-001-002-pytest.txt. Relevant unchanged dependencies examined include app/mcp/server.py, app/core/input_text.py, exact occurrence matching, read_service occurrence_report/clamp_limit, app/storage/db.py and models.py, SAVE/cycle regression coverage, adapter JSON-RPC routing, pyproject.toml, requirements.lock, evaluation/offline_eval.py and .github/workflows/ci.yml.

## Contract to implementation to verification

The locked authoritative-target boundary keeps reads advisory and mutation confined to guarded submissions. C6 was reconciled first, then implemented without a runtime-profile, history-format, schema-migration or operation change.

| Contract | Implementation | Verification inspected |
| --- | --- | --- |
| Context is a non-bool integer >=0; default40, cap400 | read_service.find_occurrences rejects before querying; occurrence_report retains bounded exact snippets | Unit invalid-type matrix, zero/default/cap cases and routing; manual stdio zero and boolean cases |
| Both histories accept omitted/null limit50 and positive non-bool integers, cap200; positive exclusive cursor | tools validates before DB binding, then clamp_limit | Both-handler unit matrix, omitted/null/cap assertions and schema checks |
| Attempt continuation is determined after every filter | get_pdcp_log applies target/status/hash/key/cursor then DESC limit+1 | Actual PG mixed accepted/rejected rows, sequence gaps, combined filters and terminal lookahead |
| Safe exact historical keys remain queryable | History schema removes submission-only pattern; handler accepts safe strings | Legacy newline key persisted through narrowly bypassed old validator and queried exactly; new submission schema still constrained |
| Attempt pages DESC; ledger newest selected page displayed ASC | Attempt page unchanged order; ledger reverses only selected newest rows | Independent expected sequence lists, real stdio pages and SQL readback |
| Every history result carries entries/has_more/next_sequence | Success and _history_error; ledger existing errors plus flag validation | Empty, malformed, unknown, filtered terminal and multi-page cases |

Pinned source: [read service](https://github.com/paragon-ux/Patch-DIFF/blob/69f6a646270ab74aba54eca635e2a6ea9cca968a/backend/app/services/read_service.py#L147), [history handlers](https://github.com/paragon-ux/Patch-DIFF/blob/69f6a646270ab74aba54eca635e2a6ea9cca968a/backend/app/mcp/tools.py#L238), [discovery schema](https://github.com/paragon-ux/Patch-DIFF/blob/69f6a646270ab74aba54eca635e2a6ea9cca968a/backend/app/mcp/external_adapter.py#L136).

## ARCH

Scope/coverage: complete for amended C6, locked read/write boundaries and compatibility decisions. Original thesis review is limited to the relevant authoritative-target/advisory-context passages.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: contract-first history establishes argument domains, intentional display-order difference and legacy lookup compatibility before source implementation.
Gaps: unrelated architecture is outside this scoped review.
Verdict: no findings within reviewed scope.

## DOC

Scope/coverage: complete for changed host, change-record and workflow guidance; cross-checked against C6 and MCP contract.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: examples correctly give attempts [10,9,8], ledger [8,9,10], cursor8, then ledger [5,6,7]. Active-cycle traversal restart after SAVE remains explicit. Newer inserts remain outside continuation below the existing cursor.
Gaps: final publication/CI metadata requires a later evidence-only delta check.
Verdict: no findings within reviewed scope.

## SKILL

Scope/coverage: complete for affected MCP orchestration instructions; relevant testing and persistence skills also examined.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: instructions agree with strict integer/boolean handling, bounded context, nullable history limits, filtered lookahead and safe historical exact-key lookup.
Gaps: no unrelated skill audit.
Verdict: no findings within reviewed scope.

## MCP

Scope/coverage: complete for changed tools, schema generation and public documentation; connected registry/adapter transport examined.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: schemas advertise minima/defaults/nullability/status enum and boolean flags. No maximum is advertised for values intentionally accepted and capped. History key lookup drops the only inherited new-submission restriction; submission schemas retain theirs. Invalid domain values return domain payloads instead of generic transport failures. Content inclusion remains opt-in.
Gaps: current remote CI unavailable; reviewer inspected parent real-stdio evidence rather than independently launching it.
Verdict: no findings within reviewed scope.

## RUN

Scope/coverage: complete for connected exact matching and canonical snippet behavior; no core runtime/profile change.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: zero context yields empty surrounding strings with unchanged exact spans; >400 caps each side. Input-text safety remains shared. Parsing, sequential application, hashes and historical dispatch are unchanged.
Gaps: no fresh whole-core audit; existing full regression execution is parent evidence.
Verdict: no findings within reviewed scope.

## SVC

Scope/coverage: complete for find_occurrences and its tool wrapper; input checks precede target reads.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: negative, bool, null, string, float and containers reject deterministically; valid zero/default/capped context preserves target version/content. Read calls create no attempt rows; these changes introduce no service write path or ownership change.
Gaps: service-level adversarial matrices are appropriate for DEV-MCP-001; no separate live DB case for every malformed context value.
Verdict: no findings within reviewed scope.

## DB

Scope/coverage: complete for affected read-query semantics and connected sequence/cycle models; schema/mutations unchanged.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: filters precede lookahead; globally allocated sequence gaps are supported. Exclusive cursor uses smallest selected sequence, including the ASC ledger display. Live cases insert newer accepted history between pages and prove original traversal coverage. Independent readback matched all current pages with direct SQL.
Gaps: traversal is not a snapshot transaction across calls; active-cycle SAVE restart is documented. No new migration/concurrency guarantee is claimed.
Verdict: no findings within reviewed scope.

## SCRIPT

Scope/coverage: complete for connected unchanged stdio entry point and offline evaluator relevance.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: real subprocess tests inspect response count, domain payloads, both page orders and continuation. Offline evaluator retains explicit scenario verdict comparisons; no benchmark/model-performance claim is introduced.
Gaps: OCR preview unavailable as recorded; no scripts changed and no tool installation audit.
Verdict: no findings within reviewed scope.

## TEST

Scope/coverage: complete for new test bodies, matrix entries, stored final output and inherited CI provenance.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: final new unit module has109 cases and live module6. Bodies assert concrete argument domains, expected sequences, SQL limit+1, caps, optional content, all-filter lookahead, exact old keys, empty/error continuation and actual subprocess behavior. Parent final isolated834-case run passed at69f6a64. Reviewer initial107-case execution and independent DB readback are separately identified.
Gaps: no remote CI result for this workstream yet; no independently repeated full suite.
Verdict: no findings within reviewed scope.

## DEP

Scope/coverage: complete for affected unchanged Python packaging, PostgreSQL configuration and CI startup assumptions.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification: no dependency, lockfile, transport version, runtime profile, database schema or configuration key changes. Existing pinned stack supports schema validation and actual subprocess/PG execution.
Gaps: no fresh install or wider dependency/security audit; OCR launcher failure is a separate local tool limitation.
Verdict: no findings within reviewed scope.

## Independent live readback and remaining gaps

Target128afcf1-bdcb-4436-9676-ea9e3132b20f contains13 attempts,11 ledger rows and version11. Reviewer compared each complete current history traversal with direct ordered SQL; both contained exactly their respective rows without duplication. Status subsets and exact stored-key lookup matched SQL. Parent's four original pages per tool each contain the expected oldest ten rows, excluding newer inserted history. All twelve protected review files retain baseline SHA256 values.

Parent manual evidence records four pages per tool, filtered status/hash/key cases and six actual stdio calls (two pages per history tool plus context0 and invalid boolean context). Production pin3b122df is unchanged at final test head69f6a64. The full-suite evidence names that final test head; no earlier or overlapping test invocation is used as final proof.

Remaining gaps are publication/remote CI and evidence-only closure metadata, not established production defects. No durable history was repaired or rewritten by this workstream.

## Root causes, disposition and closure

Both findings came from incomplete boundary contract enforcement: context validation fell through to coercive clamping, and attempt history returned only entries while ledger already exposed continuation. C6 reconciliation, small shared error construction and existing limit helper resolve these without introducing a pagination framework. Review found no additional candidate requiring implementation-agent triage.

| Finding | Independent classification | Fix/evidence | Recheck |
| --- | --- | --- | --- |
| DEV-MCP-001 | Fixed within scope | 3b122df strict context validation;109-case unit module includes domain/cap/routing cases; manual real stdio | Source, test assertions and execution provenance reconciled at69f6a64 |
| DEV-MCP-002 | Fixed within scope | 3b122df filtered limit+1 continuation/error shape;6 actual PG cases and manual traversals/stdio | Final source/test review plus independent SQL/public-handler readback |

Recommend scoped approval after normal publication checks. No unresolved actionable P1/P2/P3 finding remains. Current-workstream CI and the final evidence-only delta still need review before any eventual merge decision; user merge authorization is separate.
