# Goal F Pass B bounded-preview corrective review

Date: 2026-10-22. Reviewer: `/root/pass_a_ci_recheck`, inherited/default model, no role override/subagents. Repository: `paragon-ux/Patch-DIFF`, branch `feature/goal-f-pass-b`, [PR12](https://github.com/paragon-ux/Patch-DIFF/pull/12). Standard: PR_REVIEW_STANDARD v1.1.0. This is a new corrective review; prior protected reports are unchanged.

- Prior reviewed/green snapshot: `1e0b80028f041d52456a5ef8b521bd1a34e3f701`.
- Pre-code corrective policy: `24eccefeaf36383e163e2f1fb5c2d075f3834d57`.
- Reviewed implementation: `537937d7c3a23e67350ba758d18252275e16e9c7`.
- Prior category/source review: `Goal-F-PASS-B-84ec120-review.md`, corrections through9854e1b; subsequent evidence-only451eecd and preservation1e0b800 delta/CI rechecks retain their own actual checkout pins. They do not establish green CI for this new production correction.
- Scope: independently triaged BUDGET-B1 preview-output bounds and affected contracts/skills/tests/manual helper. No new runtime profile, submission limit, migration, audit, fingerprint, recovery or core-fact behavior. Parent/root independently confirmed the candidate before implementation. Reviewer ran no product workflow or test suite and made no product/Git changes; only this new report was written. Reviewer execution consists of read-only Git/source/artifact checks, captured-wire assertions and fresh read-only SQL.

## Changed-file inventory and inherited coverage

The exact1e0b800-to537937d delta contains11 files,425 additions, zero deletions. Every changed file has one primary category:

| Category | Path |
| --- | --- |
| SKILL | `.agents/skills/patchdiff-mcp-orchestration/SKILL.md` |
| SVC | `backend/app/services/pdcp_service.py` |
| SVC | `backend/app/services/preview_evidence.py` |
| TEST | `backend/tests/integration/test_preview_budget_live.py` |
| TEST | `backend/tests/unit/test_preview_evidence.py` |
| DOC | `docs/HOST_INTEGRATION_GUIDE.md` |
| DOC | `docs/MCP_TOOLS.md` |
| ARCH | `docs/MODERNIZATION_ARCHITECTURE.md` |
| DOC | `docs/PATCHDIFF_CORE_SPEC.md` |
| SCRIPT | `docs/usability/PASS-B-budget-live-verify.py` |
| ARCH | `docs/usability/PASS-B-decision.md` |

All affected categories below have complete source coverage. Unchanged material inherits the prior completed B source review and explicit execution limits; no unreviewed material category is represented as finding-free. Git comparison confirms no core/parser/profile/replay, database/migration, submit/recovery/history, external adapter/schema, dependency/configuration or accepted-archive change. The six-line service delta imports the projection and wraps every preview result; the previous preview evaluator body is only renamed `_preview`.

## Contract and implementation trace

Accepted Goal F revision2 global contract5 requires numeric per-field/whole-output bounds and explicit truncation behavior for every new feature. BUDGET-B1 established that preview's accepted facts, raw invalid guards, legacy failed IDs and invalid-target echo lacked those bounds. Existing full submit evidence is not an exemption for a new advisory API. Pre-code policy24eccefe defines a preview-only projection before implementation537937d.

The service wrapper projects every accepted, rejected and invalid-argument preview response after the same observation/evaluator. The projector copies the payload, constructs a new deterministic prefix fact list and leaves full core/submit evidence untouched. It retains verdict/stage/validity, valid UUID and observed hashes/versions/accepted hash. Whole facts and failed identities are never shortened to resemble another identity; omitted optional evidence has explicit reasons/counts. This is response presentation, not replay semantics or a new profile. Root's existing zero-audit/ownership assertions remain relevant because no persistence or transaction path is added.

## Candidate ledger and independent closure

| ID | Priority/category | Contract, trigger, evidence and remediation | Independent disposition |
| --- | --- | --- | --- |
| BUDGET-B1 | P2 / SVC | Accepted Goal F global contract5 requires bounded new output. At1e0b800, the [preview returns](https://github.com/paragon-ux/Patch-DIFF/blob/1e0b80028f041d52456a5ef8b521bd1a34e3f701/backend/app/services/pdcp_service.py#L306-L418) exposed an arbitrary-length facts list, raw invalid guard diagnostic, unrestricted legacy failed ID or invalid target echo. Root and runtime worker independently confirmed. Required behavior is the numeric preview-only contract recorded before code at24eccefe. [preview_evidence.py](https://github.com/paragon-ux/Patch-DIFF/blob/537937d7c3a23e67350ba758d18252275e16e9c7/backend/app/services/preview_evidence.py#L1-L95) and the public service wrapper implement whole-payload/fact/text/diagnostic bounds while preserving terminal verdict and coherent identity. | **fixed** at537937d. Reviewer inspected actual projection/wrapper, all new test assertions, affected contracts/skill and manual helper; independently checked captured public responses, actual JSON byte sizes, source/helper digests and fresh read-only SQL.88 focused cases and separate three-group manual execution pass. Final corrected-head/generated-merge CI remains required. |

No additional actionable candidate was identified. Earlier B findings retain their independently rechecked closures; none is reopened or silently dropped. Preservation closure is explicitly checked below.

## ARCH — Architecture and contracts

**Scope/Coverage:** Complete for accepted global bounds, pre-code policy and architecture amendment; unchanged host/runtime/ownership boundaries inherit prior review.

### P1

None identified within reviewed scope.
### P2

BUDGET-B1 is closed in its primary SVC category; no separate architecture defect.
### P3

None identified within reviewed scope.

**Verification:** Policy precedes code and distinguishes complete payload32768 ASCII-escaped JSON bytes from transport envelopes; accepted prefix32/perfact2048/wrapper16384, text1024 code points/8192 wrapper, diagnostic16384 and safe context bounds. Explicit omission never changes shared semantic results. **Gaps:** Final corrected CI pending; representative V02/V04 limits remain. **Verdict:** No unresolved findings within reviewed scope.

## DOC — Documentation and change records

**Scope/Coverage:** Complete for MCP/host/core corrective prose and referenced decision; prior B/preservation reports remain historical evidence.

### P1

None identified within reviewed scope.
### P2

None separately identified within reviewed scope.
### P3

None identified within reviewed scope.

**Verification:** Bounds, units, counts, non-exhaustive facts and omission semantics agree with actual response fields and code. Full submit/history evidence remains distinct from preview projection. **Gaps:** Root final verification append/final CI are subsequent evidence deltas. **Verdict:** No unresolved findings within reviewed scope.

## SKILL — Skills and agent instructions

**Scope/Coverage:** Complete for MCP skill's corrective instruction; unchanged skills inherit prior review.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

**Verification:** Numeric limits and identity/submit preservation guidance match actual projection and policy. **Gaps:** None specific to source guidance. **Verdict:** No findings within reviewed scope.

## MCP — MCP schemas and public API

**Scope/Coverage:** Complete for affected public preview response projection and captured stdio behavior. Adapter, schemas, other tools and discovery examples are unchanged and inherit prior review.

### P1

None identified within reviewed scope.
### P2

None separately identified within reviewed scope; public output defect belongs to BUDGET-B1.
### P3

None identified within reviewed scope.

**Verification:** Actual wire confirms accepted count/truncation fields and whole fact prefix, explicit raw-guard/legacy-ID/invalid-target omissions, retained status/stage/observed state, no log ID and rejected-preview absence of facts. Existing F12 real stdio workflow passes the affected run. **Gaps:** Corrected final head/merge CI not yet inspected. **Verdict:** No unresolved findings within reviewed scope.

## RUN — Core runtime, parsing and validation

**Scope/Coverage:** Complete inherited source coverage plus exact unchanged core/parser/profile comparison; affected projection is post-evaluation service code.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

**Verification:** No core result, profile or decoder is modified. The live test compares projected32-fact prefix against an actual40-fact full submission, preserving existing fact identity/order. Existing four-format accepted/rejected parity runs remain green for small complete evidence. **Gaps:** No reviewer core execution or full-suite rerun. **Verdict:** No findings within reviewed scope.

## SVC — Services, orchestration and audit semantics

**Scope/Coverage:** Complete for new projector and all preview return paths, shared evaluator dependency and original result ownership.

### P1

None identified within reviewed scope.
### P2

BUDGET-B1 fixed/rechecked at537937d.
### P3

None identified within reviewed scope.

**Verification:** All early returns pass through the wrapper. Fact selection stops at the first count/whole-fact/wrapper limit; it does not skip oversized identities or mutate the original list. Text remains whole or becomes null with explicit reason. Oversized diagnostic falls back to bounded failure_context when available. Actual total serialization is checked in deterministic diagnostic/text/invalid-echo/context order, then whole trailing facts if needed. Valid UUID is retained canonically, including a long accepted UUID spelling; known hashes/versions/stages/reason remain untouched. Fixed-shape essential fields are bounded by service/database contracts; arbitrary user evidence is optional/projected. **Gaps:** Final CI pending. **Verdict:** No unresolved findings within reviewed scope.

## DB — Database, migrations, replay and concurrency

**Scope/Coverage:** Complete inherited unchanged persistence/replay coverage and affected no-audit/caller-ownership assertions; fresh manual target SQL inspected.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

**Verification:** No SQL/lock/transaction/persistence call is added by projection. Live tests retain caller transaction identity/pending unrelated object, assert one SELECT without FOR UPDATE and compare every managed table's contents before/after preview. Manual helper also asserts all-table digest/count equality. Fresh reviewer read-only SQL confirms content/hash/version unchanged and zero attempts/facts. **Gaps:** Whole-table pre/post equality is the executed helper/test assertion; reviewer fresh SQL independently verifies the manual target, not a reconstruction of all pre-call database rows. No representative performance claim. **Verdict:** No findings within reviewed scope.

## SCRIPT — Scripts, evaluation and developer tooling

**Scope/Coverage:** Complete for new budget manual helper and reused raw-stdio/SQL helper; offline evaluator is unchanged.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

**Verification:** Real child stdio exercises40 accepted no-op spans, giant invalid guard, giant legacy failed ID and invalid target echo. Actual serialized payloads and per-fact/wrapper limits are asserted; every managed table is compared; final target state is independently queried. The record pins executed head, all48 production digests and both helper digests and captures all raw requests/responses. Reuse of helper utilities is explicit; no new installed-host/model/performance claim. **Gaps:** No reviewer rerun of script; source and actual recorded execution were independently checked. **Verdict:** No findings within reviewed scope.

## TEST — Tests and CI

**Scope/Coverage:** Complete for21 new pure cases and six live cases, plus inspected reuse of existing60 replacement/preview and one real F12 stdio case in the affected run.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

**Verification:** Tests assert actual JSON bytes, inclusive fact/diagnostic limits, ASCII-escaped non-BMP bytes, first oversized-fact stop, count cap, wrapper cap, original payload nonmutation, valid long UUID preservation and combined-field fallback retaining verdict/identity. Live cases exercise accepted/rejected giant legacy IDs, full-submit evidence preservation, invalid target no transaction, caller ownership, one observation and all-table nonmutation. Focused XML independently counts88 passed, zero failures/errors/skips,52.217s. **Gaps:** No local full-suite repeat or reviewer tests; actual final head/generated-merge CI is required. Prior green1e0b800 CI is preserved at that revision. **Verdict:** Source/focused evidence clear; final full CI pending.

## DEP — Dependencies, packaging and configuration

**Scope/Coverage:** Complete inherited unchanged dependencies/configuration plus new projector imports.

### P1

None identified within reviewed scope.
### P2

None identified within reviewed scope.
### P3

None identified within reviewed scope.

**Verification:** Projector adds only standard-library json/uuid and existing service import; no package, lockfile, environment, workflow or schema change. Prior exact archive .gitattributes preservation paths remain unchanged. **Gaps:** No new installation/platform test was required or run. **Verdict:** No findings within reviewed scope.

## Independent execution-evidence recheck

Root execution at537937d is separate from reviewer checks. PASS-B-budget-junit.xml contains **88 cases:21 unit,67 integration; zero failures/errors/skips;52.217s**. Class counts are21 projector pure cases, six budget live cases,60 existing replacement/preview cases and one F12 real stdio case. PASS-B-budget-tests.txt preserves its successful run. No claim of a new complete local suite is made.

Separate outside-pytest manual run: **three groups passed** at537937d. Reviewer independently decoded all **six raw JSON-RPC events**, including four preview tool responses, checked matching request/response IDs and every raw request byte count/SHA-256, and recomputed actual compact ASCII-escaped payload sizes as **10,331 /1,331 /1,502 /1,149 bytes**. All are below32768. The accepted40-change preview returns exactly32 complete sequential chg_001–chg_032 facts with exact empty-span/empty-replacement hashes/counts and operation=span; each fact fits2048 bytes and wrapped facts fit16384. Its after_hash equals SHA-256 of x. Rejected raw-guard/legacy-ID/invalid-target responses preserve their actual classification and expose explicit omission reasons, with no staged facts/log ID. Diagnostic wrapper sizes independently fit16384.

All **48 production Python source digests and both helper digests** independently match current files. Captured source/helper/head pins establish what was executed; file names alone are not passing evidence.

Fresh reviewer SQL used **default_transaction_read_only=on**, verified that transaction setting, and queried manual target **5b1f2abb-1734-4b2b-81dc-2a30d83f121e** in patchdiff_goal_f_pass_b_manual_20261022. Stored content x, version0, SHA-256 **2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881**, zero attempt rows and zero ledger rows match the captured final state. This fresh read-only observation is distinct from root's all-table pre/post execution assertions.

## Preservation closure and final disposition

PRESERVE-B1 remains **fixed at1e0b800**. Prior independent checks established both archive HEAD/worktree/original hashes match the unchanged authority manifest, exact193 CR restoration without normalized-text changes, exact two -text paths, unchanged product trees and56 preexisting review/remediation blobs. Root's fresh checkout with core.autocrlf=true audit agrees. Correction1e0b800→537937d changes neither .gitattributes nor accepted archives/manifest or prior review/remediation files. The earlier head/merge CI remains valid evidence for that snapshot; no historical review was rewritten.

**Overall:** All ten material categories are covered by affected review plus explicit unchanged inheritance. BUDGET-B1 is independently fixed/rechecked; no new source candidate remains at537937d. No approval is inferred from focused tests alone. Final published documentation/evidence delta and actual green corrected-head/generated-merge CI must be checked at their real checkout SHAs; this report alone does not approve merging. Existing representative V02/V04 limitations and separate user merge authorization remain unchanged.
