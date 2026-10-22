# Release-readiness review

**Latest disposition:** All four release-readiness findings are fixed and independently rechecked through source 57dd7c4, with configuration/dependency/packaging fixes at 9473e8b. The patched environment's complete local suite passes 1,144 tests and the fresh installed artifact passes its separate live workflow. Original candidate findings and their later closure supplements remain below. Final current-head/generated-merge CI and separate owner merge/publication authorization remain required; this report authorizes no merge, tag or release.

## Review metadata and evidence limits

- Date: 2026-10-22; reviewer: independent release-facing reviewer, default model.
- Repository: https://github.com/paragon-ux/Patch-DIFF; PR11: https://github.com/paragon-ux/Patch-DIFF/pull/11; PR12: https://github.com/paragon-ux/Patch-DIFF/pull/12.
- Standard: docs/PR_REVIEW_STANDARD.md v1.1.0, required by AGENTS.md. Applied patchdiff-testing-review, pr-review-branch and ponytail review instructions.
- Integrated base: **2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10**.
- PR11 head / PR12 stacked base: **d27c1832a85efdb92e12d0b9fcf8acefb1c559f6**.
- PR12 candidate head: **973ba7901769871012f355f8443ffe05abd58878**.
- This is a separate release-readiness review, not a fresh engine review, complete security audit, merge authorization or publication. PR11 remains open under the user's instruction. No tag, release, commit, push or merge was performed by this reviewer.
- Source inspection and local read-only checks are reviewer evidence. Implementation-reported current GitHub, package-build, advisory and future fix evidence is explicitly separate and requires the implementation owner's final record.
- No full suite, live DB mutation or installed-host test was run here. Existing test evidence retains its own executed revision; this report does not claim candidate-head CI passed.

## File inventory and coverage matrix

The exact integrated-base-to-candidate inventory contains **119 paths**, generated with git diff --name-only at the pins above. The table below assigns every path one primary category; it is an inventory, not a claim of independently rereviewing every engine file. Unchanged release dependencies additionally inspected: README.md, README_DEV.md, README_INTERNAL_MCP.md, docs/CLAUDE_DESKTOP_SETUP.md, pyproject.toml, requirements.lock, docker-compose.yml, .env.example, .gitignore, .github/workflows/ci.yml, .github/PULL_REQUEST_TEMPLATE.md, backend/app/core/config.py, backend/app/storage/db.py, backend/app/main.py, backend/app/api/health.py and backend/app/migrations/alembic.ini.

| Category | Changed path |
| --- | --- |
| SKILL | `.agents/skills/patchdiff-core-runtime/SKILL.md` |
| SKILL | `.agents/skills/patchdiff-mcp-orchestration/SKILL.md` |
| SKILL | `.agents/skills/patchdiff-persistence-replay-save/SKILL.md` |
| SKILL | `.agents/skills/patchdiff-testing-review/SKILL.md` |
| DEP | `.gitattributes` |
| ARCH | `AGENTS.md` |
| RUN | `backend/app/core/diagnostics.py` |
| RUN | `backend/app/core/failures.py` |
| RUN | `backend/app/core/result.py` |
| RUN | `backend/app/core/validity.py` |
| RUN | `backend/app/core/versions.py` |
| MCP | `backend/app/mcp/external_adapter.py` |
| MCP | `backend/app/mcp/tools.py` |
| RUN | `backend/app/pdcp/applier.py` |
| RUN | `backend/app/pdcp/models.py` |
| RUN | `backend/app/pdcp/operations.py` |
| RUN | `backend/app/pdcp/replacement.py` |
| SVC | `backend/app/services/near_miss_service.py` |
| SVC | `backend/app/services/pdcp_service.py` |
| SVC | `backend/app/services/preview_evidence.py` |
| SVC | `backend/app/services/read_service.py` |
| SVC | `backend/app/services/rejection_context.py` |
| DB | `backend/app/services/replay_service.py` |
| TEST | `backend/tests/integration/test_conflict_audit_live.py` |
| TEST | `backend/tests/integration/test_invalid_input_unicode_live.py` |
| TEST | `backend/tests/integration/test_mcp_tools.py` |
| TEST | `backend/tests/integration/test_pass_a_flow.py` |
| TEST | `backend/tests/integration/test_pass_b_discovery.py` |
| TEST | `backend/tests/integration/test_pass_b_reads.py` |
| TEST | `backend/tests/integration/test_pass_b_submission_preview.py` |
| TEST | `backend/tests/integration/test_preview_budget_live.py` |
| TEST | `backend/tests/integration/test_rejection_context_flow.py` |
| TEST | `backend/tests/unit/test_failures.py` |
| TEST | `backend/tests/unit/test_invalid_input_unicode.py` |
| TEST | `backend/tests/unit/test_pass_a_diagnostics.py` |
| TEST | `backend/tests/unit/test_pass_a_operations.py` |
| TEST | `backend/tests/unit/test_pass_b_reads_discovery.py` |
| TEST | `backend/tests/unit/test_pass_b_runtime.py` |
| TEST | `backend/tests/unit/test_preview_evidence.py` |
| TEST | `backend/tests/unit/test_rejection_context.py` |
| DOC | `docs/DATA_MODEL.md` |
| DOC | `docs/HOST_INTEGRATION_GUIDE.md` |
| DOC | `docs/MCP_FIRST_MVP.md` |
| DOC | `docs/MCP_TOOLS.md` |
| ARCH | `docs/MODERNIZATION_ARCHITECTURE.md` |
| DOC | `docs/MODERNIZATION_CHANGE_DOC.md` |
| DOC | `docs/PATCHDIFF_CORE_SPEC.md` |
| DOC | `docs/PDCP_FORMAT.md` |
| DOC | `docs/reviews/Goal-F-F01-128f59d-review.md` |
| DOC | `docs/reviews/Goal-F-PASS-A-46bd293-review.md` |
| DOC | `docs/reviews/Goal-F-PASS-B-84ec120-review.md` |
| DOC | `docs/reviews/Goal-F-PASS-B-budget-537937d-review.md` |
| DOC | `docs/usability/BASELINE-and-evidence-closures.md` |
| TEST | `docs/usability/BASELINE-junit.xml` |
| TEST | `docs/usability/BASELINE-live-results.json` |
| SCRIPT | `docs/usability/BASELINE-live-verify.py` |
| TEST | `docs/usability/BASELINE-manual.txt` |
| TEST | `docs/usability/BASELINE-offline.txt` |
| TEST | `docs/usability/BASELINE-suite.txt` |
| ARCH | `docs/usability/EXECUTION-PLAN.md` |
| ARCH | `docs/usability/F01-decision.md` |
| TEST | `docs/usability/F01-junit.xml` |
| TEST | `docs/usability/F01-live-results-development.json` |
| TEST | `docs/usability/F01-live-results.json` |
| SCRIPT | `docs/usability/F01-live-verify.py` |
| TEST | `docs/usability/F01-manual.txt` |
| TEST | `docs/usability/F01-offline.txt` |
| TEST | `docs/usability/F01-suite.txt` |
| DOC | `docs/usability/F01-verification.md` |
| DOC | `docs/usability/GEMINI-v1-v2-REVIEW.md` |
| TEST | `docs/usability/GEMINI-v2-evidence-check.json` |
| SCRIPT | `docs/usability/GEMINI-v2-evidence-check.py` |
| DOC | `docs/usability/GOAL-F-DELIVERY-LEDGER.md` |
| ARCH | `docs/usability/PASS-A-decision.md` |
| TEST | `docs/usability/PASS-A-junit.xml` |
| TEST | `docs/usability/PASS-A-live-results.json` |
| SCRIPT | `docs/usability/PASS-A-live-verify.py` |
| TEST | `docs/usability/PASS-A-manual.txt` |
| TEST | `docs/usability/PASS-A-offline.txt` |
| TEST | `docs/usability/PASS-A-recheck-junit.xml` |
| TEST | `docs/usability/PASS-A-recheck.txt` |
| TEST | `docs/usability/PASS-A-suite.txt` |
| DOC | `docs/usability/PASS-A-verification.md` |
| TEST | `docs/usability/PASS-B-budget-junit.xml` |
| TEST | `docs/usability/PASS-B-budget-live-results.json` |
| SCRIPT | `docs/usability/PASS-B-budget-live-verify.py` |
| TEST | `docs/usability/PASS-B-budget-manual.txt` |
| TEST | `docs/usability/PASS-B-budget-tests.txt` |
| ARCH | `docs/usability/PASS-B-decision.md` |
| TEST | `docs/usability/PASS-B-fixture-recheck-junit.xml` |
| TEST | `docs/usability/PASS-B-fixture-recheck.txt` |
| TEST | `docs/usability/PASS-B-junit.xml` |
| TEST | `docs/usability/PASS-B-live-results.json` |
| SCRIPT | `docs/usability/PASS-B-live-verify.py` |
| TEST | `docs/usability/PASS-B-manual-initial-failure.txt` |
| TEST | `docs/usability/PASS-B-manual.txt` |
| TEST | `docs/usability/PASS-B-offline.txt` |
| TEST | `docs/usability/PASS-B-recheck-junit.xml` |
| TEST | `docs/usability/PASS-B-recheck.txt` |
| TEST | `docs/usability/PASS-B-suite.txt` |
| DOC | `docs/usability/PASS-B-verification.md` |
| ARCH | `docs/usability/accepted/AUTHORITY.json` |
| ARCH | `docs/usability/accepted/DEVIN_CHANGE_PLAN-b33faaf-v2.md` |
| ARCH | `docs/usability/accepted/Devin-Goal-F.md` |
| DOC | `docs/usability/integration/CONSOLIDATION_RECHECK.md` |
| TEST | `docs/usability/integration/PR-1-CI-39663238218.txt` |
| TEST | `docs/usability/integration/PR-10-CI-39663057668.txt` |
| TEST | `docs/usability/integration/PR-5-CI-39661605566.txt` |
| TEST | `docs/usability/integration/PR-6-CI-39569958566.txt` |
| TEST | `docs/usability/integration/PR-6-CI-39662203586.txt` |
| TEST | `docs/usability/integration/PR-7-CI-39662500697.txt` |
| TEST | `docs/usability/integration/PR-8-CI-39662684583.txt` |
| TEST | `docs/usability/integration/PR-9-CI-39662879868.txt` |
| TEST | `docs/usability/integration/merge-ledger-attempt1.json` |
| TEST | `docs/usability/integration/merge-ledger-attempt2.json` |
| TEST | `docs/usability/integration/merge-ledger-attempt3.json` |
| TEST | `docs/usability/integration/merge-ledger.json` |
| SCRIPT | `docs/usability/integration/merge_stack.py` |
| SCRIPT | `evaluation/offline_eval.py` |

| Category | Release-review coverage |
| --- | --- |
| ARCH | Partial: boundaries and publication claims inspected; engine architecture inherited only where unchanged. |
| DOC | Complete for identified release/onboarding surfaces; source candidate REL-DOC-001. |
| SKILL | Partial: required review/testing instructions and prior corrected inventories inspected. |
| MCP | Partial: discoverability/version identity inspected; full schema review reused. |
| RUN | Partial: immutable version mapping inspected; engine deep review reused. |
| SVC | Partial: release-facing ownership/preview/admission guarantees inspected; service deep review reused. |
| DB | Partial: installation/migration prerequisites inspected; full DB review reused. |
| SCRIPT | Partial: install/start commands, offline scope, developer/release tooling inspected. |
| TEST | Partial: CI workflow and historical evidence boundaries inspected; fresh final CI owned by the implementation owner. |
| DEP | Complete source review for installation/config/packaging/version identity and independent recorded advisory triage; executable build/fresh advisory queries owned by the implementation owner. |

## Architecture-to-implementation trace and inherited evidence

AGENTS.md defines a deterministic MCP service with host-owned planning/retries and Postgres-owned canonical state. Guarded operations add tx/2 guarded spans and response-only diagnostic enrichment; Replacement and preview features add tx/3 guarded sole replacement, line reads, zero-audit advisory preview and bounded discovery examples. Current normative contracts and discovery descriptions preserve exact application, immutable profiles, fresh guarded admission and submit rechecking. Release text must retain these qualifications and deferred scope.

The inherited engine reviews are [guarded-operation review](Goal-F-PASS-A-46bd293-review.md), [replacement-and-preview review](Goal-F-PASS-B-84ec120-review.md) and [bounded-preview correction](Goal-F-PASS-B-budget-537937d-review.md). Git diff 537937d..973ba79 contains only docs/MCP_TOOLS.md, docs/MODERNIZATION_CHANGE_DOC.md, the budget review and budget evidence/delivery/verification records: **no backend, skill, dependency, configuration or evaluator delta**. Thus this report relies on those reviews for unchanged runtime categories without assigning itself a fresh engine approval. The original concept paper was not reread; no alteration of its thesis is recommended here.

## Candidate-finding ledger

| ID | Priority / owner | Candidate, evidence and trigger | Required direction / acceptance |
| --- | --- | --- | --- |
| REL-DOC-001 | P2 / DOC; open at candidate | The release-facing tool inventories omit submit_operations, submit_replacement, read_lines and preview. [README:126-133](https://github.com/paragon-ux/Patch-DIFF/blob/973ba7901769871012f355f8443ffe05abd58878/README.md#L126-L133), [internal README:63-82](https://github.com/paragon-ux/Patch-DIFF/blob/973ba7901769871012f355f8443ffe05abd58878/README_INTERNAL_MCP.md#L63-L82) explicitly claims 16 tools, [Claude guide:120-126](https://github.com/paragon-ux/Patch-DIFF/blob/973ba7901769871012f355f8443ffe05abd58878/docs/CLAUDE_DESKTOP_SETUP.md#L120-L126) calls that older inventory full, and [AGENTS:105-110](https://github.com/paragon-ux/Patch-DIFF/blob/973ba7901769871012f355f8443ffe05abd58878/AGENTS.md#L105-L110) omits replacement/line reads/preview from its service summary. HOST_INTEGRATION_GUIDE:116 also says current submissions use 0.2.2 without qualifying tx/1 and legacy scope. A user following onboarding cannot discover the advertised guarded editing update capabilities or gets an incomplete version claim. This violates the review standard DOC coherence requirement; source-derived, not an observed installed-host failure. | Reconcile active inventories to actual 20-tool registry, distinguish prefix-context helper from advisory transaction preview, qualify runtime identity by format, preserve historical records. Source/discovery comparison is sufficient for prose. The implementation owner independently confirmed this candidate and reported intent to fix; fix SHA/reviewer recheck are not yet available here. |
| REL-DEP-001 | P2 / DEP; open at candidate; pre-existing | [docker-compose.yml:10-11](https://github.com/paragon-ux/Patch-DIFF/blob/973ba7901769871012f355f8443ffe05abd58878/docker-compose.yml#L10-L11) publishes 5432 on all host interfaces while lines6-8 ship known patchdiff credentials. README describes local Docker Postgres and .env.example repeats that local credential. Trigger: run documented docker compose up -d postgres on a host where inbound 5432 is reachable; Docker publication exceeds the described local boundary and exposes canonical documents/logs to anyone able to use that credential. Source-derived configuration issue, not an observed remote compromise; host firewall may restrict reachability. | Bind the development publication to 127.0.0.1:5432:5432, explain local-only assumptions and deliberate remote configuration. Validate docker compose config; do not recreate or delete an existing DB for this review. The implementation owner independently confirmed and reported intent to fix. This predates guarded editing update, but belongs to explicitly requested release readiness. |
| REL-SEC-001 | P2 / DEP; open at candidate; pre-existing pins | Candidate lock installs five packages with ten exact affected-version advisory matches. See the independent source/range/reachability record immediately below. | Resolve the five compatible fixed pins and pytest constraint; verify fresh audit, actual installation/build and regression evidence at fix SHA. |
| REL-PKG-001 | P2 / DEP; open at candidate; pre-existing discovery/data rules | Independently inspected unpublished wheel contains a top-level tests namespace with59 Python files and omits two migration support assets. See artifact/source/trigger record below. | Restrict discovery to app/app.*; include explicit migration config/template data; build from a fresh source archive and smoke actual installed artifact outside checkout. |

## Supplemental candidate REL-SEC-001 (DEP, P2; open at candidate)

The exact pinned requirements.lock contains five packages with ten published affected-version matches in the implementation owner's 2026-10-22 OSV result. This reviewer independently read the recorded query/advisory bodies, compared all 40 queried package/version pairs to the candidate Git blob, checked that every old pin appears in its advisory's affected-version list and inspected each remediation boundary. The raw recorded lock SHA-256 6a6ffe3f91cfd62a106c8abffc8abe98e3ddc99c85ca29a3e04a48cdada7d081 matches the candidate Git blob after normal checkout CRLF conversion; the Git LF blob hash is bfab70e5b52460ffdd8a954107bb8dd050a8ece4ed8e16b5f88e523d75bc68fe. This guards against accidentally triaging the implementation owner's simultaneously corrected working lock as the old snapshot.

Contract provenance: PR_REVIEW_STANDARD DEP requires supported dependency/configuration coherence; the user expressly requested security/release readiness. Trigger: installing the pinned candidate lock supplies the affected code/trust bundle. Expected: release preparation resolves confirmed affected pins compatibly and verifies the updated environment. Actual: old lock retains the ten matches and pyproject test constraint <9 prevents selecting the pytest fixed version. Impact: known vulnerable components are installed, with exploitability dependent on the feature/environment described below; no remotely reachable PatchDIFF exploit is demonstrated.

| Package / candidate pin | Advisory | Fixed boundary | PatchDIFF reachability assessment |
| --- | --- | --- | --- |
| Mako 1.3.12 | GHSA-5639-2j2p-m4mx | 1.4.2 | Windows user-controlled TemplateLookup names are prerequisite; no app template lookup found; migration/tooling dependency. |
| anyio 4.13.0 | GHSA-5p39-cfhj-2xmp | 4.14.2 | Worker-process stderr deadlock requires process-pool use; no app process-pool call found. |
| anyio 4.13.0 | GHSA-82r6-8w77-94w6 | 4.14.2 | TLS IDNA hostname spoofing requires relevant outbound TLS and redirected connection; no outbound app TLS call found. |
| certifi 2026.4.22 | GHSA-6q48-6c7w-9gw2 | 2026.10.19 | Compromised CA chain affects environments using this trust bundle with an on-path attacker; not an observed exploit. |
| pytest 8.4.2 | GHSA-6w46-j5rx-g56g | 9.0.3 | Test/developer environment; advisory concerns shared UNIX temporary directories and local users. |
| starlette 1.0.0 | GHSA-82w8-qh3p-5jfq | 1.3.1 | URL-encoded form-limit bypass; no application form endpoint found. |
| starlette 1.0.0 | GHSA-86qp-5c8j-p5mr | 1.0.1 | Host-derived URL/path security-check prerequisite; no such app check found. |
| starlette 1.0.0 | GHSA-jp82-jpqv-5vv3 | 1.3.0 | Malformed-path reconstructed hostname trust prerequisite; no such app trust use found. |
| starlette 1.0.0 | GHSA-wqp7-x3pw-xc5r | 1.1.0 | Windows StaticFiles UNC/SMB prerequisite; no static mount found. |
| starlette 1.0.0 | GHSA-x746-7m8f-x49c | 1.1.0 | Unconstrained HTTPEndpoint subclass prerequisite; health routes are explicit GET functions. |

Evidence bodies: reproduction/2026-10-22/release/dependency-osv.json and dependency-advisories.json in the parent chat workspace, outside the reviewed Git tree. Primary upstream advisory references are retained in those records. No redundant live advisory query was made by this reviewer.

Required remediation/acceptance: update the five affected lock pins to compatible fixed versions, reconcile pytest metadata to admit 9.0.3, resolve/install consistently, rerun all lock pins against the advisory service, inspect the resulting exact environment and execute the authorized suite/build smoke. The implementation owner independently identified/confirmed the issue and has begun the narrow dependency correction. Fixed working-tree versions alone are not closure: fix SHA, current audit, package checks and regression evidence remain required. The library severity ratings are not copied as PatchDIFF P1 findings because the app source does not establish the exploit prerequisites. Related IDs: none; single dependency correction the implementation owner cause.

## Supplemental candidate REL-PKG-001 (DEP, P2; open at candidate)

The implementation owner's first unpublished build succeeds but exposes a concrete distribution defect. This reviewer independently opened reproduction/2026-10-22/release/wheels-initial/patchdiff_mvp-0.1.0-py3-none-any.whl (SHA-256 **49df2671fc460ada5da4efa976934a795e780ca66b9b5dbd689ab7fe91bc858d**): top-level members are app, tests and dist-info; **59 tests/*.py** files are installed, while app/migrations contains only env.py and the two version Python modules. The wheel includes LICENSE but lacks **app/migrations/alembic.ini** and **app/migrations/script.py.mako**.

Provenance/source: PR_REVIEW_STANDARD DEP installation/packaging coherence and the requested release readiness. [Candidate pyproject:26-27](https://github.com/paragon-ux/Patch-DIFF/blob/973ba7901769871012f355f8443ffe05abd58878/pyproject.toml#L26-L27) discovers backend without an app filter or explicit package data. The implementation build adds license/readme metadata but still uses the candidate's package-discovery/data rules, so these omissions are traceable to unchanged original packaging.

Trigger: install the built wheel outside the checkout. Actual: the generic tests namespace is shipped, increasing unnecessary installed surface/conflict risk, and the package lacks the config/template needed for self-contained packaged migration operations. Expected: the distribution includes only the service package plus license/metadata and required migration assets. Impact is package/release completeness; the documented source-checkout migration path still has its files, and this does not prove existing source-run MCP is broken.

Required remediation/acceptance: restrict package discovery to app and app.*, include migrations/alembic.ini and migrations/script.py.mako explicitly, then build from a fresh archive to avoid stale build/lib contents. Inspect the new ZIP, license and metadata; install it into an isolated environment and verify MCP initialize/discovery, health and packaged Alembic from outside the checkout. The implementation owner independently identified and confirmed this candidate and is implementing that narrow fix. Fix SHA/actual corrected artifact identity and execution evidence remain pending; no wheel was published.

## ARCH — Architecture and contracts

**Scope / coverage:** Partial; release-facing MCP/host/Postgres separation, deferred features, no model/performance claims and profile boundaries inspected. Existing runtime trace reused as described above.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification / gaps:** Source-only. No original-paper reread or new full architecture review. Current ledger correctly limits representative migration/performance to local synthetic evidence and defers optional typed guards, normalized identity and the editing adapter.  
**Verdict:** No findings within reviewed release scope; engine assessment relies on cited reports and integration review.

## DOC — Documentation and change records

**Scope / coverage:** Complete for READMEs, Claude setup, host guide version statement, as-built/delivery/replacement-and-preview records and release-file presence.

### P1
None identified within reviewed scope.
### P2
REL-DOC-001; source candidate remains open at 973ba79.
### P3
None identified within reviewed scope.

**Verification / gaps:** Active docs inspected against real registry declarations and frozen profile constants. There is no tracked CHANGELOG/release-note artifact at the candidate; implementation/evidence records are useful but do not replace a reader-facing release summary. The implementation owner is preparing an Unreleased reader-facing note/version matrix. Its final contents, package identity and status must be reviewed at the fix revision. The implementation owner reports PR descriptions are also being refreshed; this reviewer did not inspect live PR bodies. A later explicit user constraint extends REL-DOC-001 acceptance: remove internal agent terminology (internal planning labels and identifiers) from README and active public documentation/new release/security notes and PR presentation, while preserving internal instructions, accepted records, review/evidence archives. This is a publication/presentation requirement and must not silently change normative behavior or rewrite protected history.  
**Verdict:** Changes required for REL-DOC-001. Publication notes are a separate release gap, not proof the engine is defective.

## SKILL — Skills and agent instructions

**Scope / coverage:** Partial; AGENTS and required testing/review instructions read; prior skill-inventory correction reused only because the skill tree has no delta since 537937d.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification / gaps:** AGENTS summary drift belongs to REL-DOC-001. No independent complete audit of every instruction/API was repeated.  
**Verdict:** No distinct findings within reviewed scope; inherited skill review remains bounded to unchanged material.

## MCP — MCP schemas and public API

**Scope / coverage:** Partial; adapter identity, advertised new tools/descriptions and discovery examples' publication claims inspected. Schema and stdio/PG behavior rely on prior reviews.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification / gaps:** PROTOCOL_VERSION is 2024-11-05 and SERVER_VERSION is 0.2.2 at the pin. These are separate from distribution, transaction and runtime IDs. No claim of latest MCP conformance or installed Claude certification is established here.  
**Verdict:** No findings within reviewed release identity/discovery scope; no fresh full-schema approval.

## RUN — Core runtime, parsing, and validation

**Scope / coverage:** Partial; versions.py and relevant format declarations inspected; existing runtime review reused without rerunning engine tests.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification / gaps:** Distribution 0.1.0, server 0.2.2 and tx/3 execution profile patchdiff-mvp-0.4.0 are not interchangeable. Immutable historical runtime constants must not be bumped to match a future tag. New tx/2 and tx/3 do not change legacy/tx1 history.  
**Verdict:** No findings within reviewed release-version scope; full runtime assessment inherited.

## SVC — Services, orchestration, and audit semantics

**Scope / coverage:** Partial; public read-only preview/admission/recovery/host-ownership descriptions checked against existing review and contract summaries.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification / gaps:** Release claims must preserve zero-audit advisory preview, re-lock/recheck on submit, limits on fresh replacement and existing-key recovery precedence. No new service execution, transaction/lock check or performance benchmark here.  
**Verdict:** No findings within reviewed publication-claim scope; service implementation review inherited.

## DB — Database, migrations, replay, and concurrency

**Scope / coverage:** Partial; documented migrations 20260510_0001 and 20261020_0002, Alembic import configuration and local canonical storage assumptions inspected.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification / gaps:** No guarded editing update migration is claimed or required by the reviewed decisions. No representative-data migration rehearsal, production replay/writer benchmark or fresh live DB run performed here. Exposed local DB configuration is owned once by DEP.  
**Verdict:** No distinct findings within reviewed release prerequisites; runtime DB review inherited.

## SCRIPT — Scripts, evaluation, and developer tooling

**Scope / coverage:** Partial; source-checkout installation/start commands, Alembic config, evaluator claim boundaries and absence of dedicated release automation inspected.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification / gaps:** README_DEV lacks an explicit PYTHONPATH assignment, but editable installation plus Alembic prepend_sys_path support its import path; this is not retained as a defect. Current README installs unconstrained compatible dependencies whereas CI uses requirements.lock: both are intentional supported mechanisms, but an exact release reproduction must name the locked path. Offline evidence measures bytes and explicit verdict/hash oracles; no token savings or model-success claim follows. Wheel/build/install execution is assigned to the implementation owner.  
**Verdict:** No findings within source-reviewed developer tooling; package execution gap remains separate.

## TEST — Tests and CI

**Scope / coverage:** Partial; CI workflow and pinned historical review/evidence boundaries inspected, no full suite rerun.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

**Verification / gaps:** CI pins Python3.11 and requirements.lock, installs editable package with no dependency re-resolution, performs migrations/unit/live PG/offline evaluation. It has no tag/release publishing job, distribution smoke job, secret scanner or dependency audit step. Their absence is not automatically a guarded editing update defect, and a green test workflow would not establish those release properties. Exact final-head/generated-merge CI verification belongs to the implementation owner. Python>=3.11 metadata is broader than one CI interpreter; no universal platform/version certification follows.  
**Verdict:** Incomplete for final integration evidence; no newly established CI defect.

## DEP — Dependencies, packaging, and configuration

**Scope / coverage:** Complete source review for pyproject/lock/Compose/env/defaults/start path and release identity. Executable build and current dependency advice intentionally owned by the implementation owner.

### P1
None identified within reviewed scope.
### P2
REL-DEP-001; source candidate remains open at 973ba79.
REL-SEC-001; affected exact pins independently confirmed against recorded advisories; corrected lock audit and regression evidence pending.
REL-PKG-001; first built wheel independently confirms test namespace inclusion and missing migration support assets; corrected artifact evidence pending.
### P3
None identified within reviewed scope.

**Verification / gaps:** pyproject names patchdiff-mvp version0.1.0, setuptools backend, backend package discovery and Python>=3.11; no console entry point, license metadata or README metadata. Documented source checkout uses python -m app.mcp.external_adapter and migrations, so missing a console script is not a defect. No LICENSE or SECURITY.md exists at the candidate. User subsequently chose MIT, per parent message; the implementation owner is adding canonical LICENSE plus metadata. This resolves the owner-choice question, but no later artifact is reviewed here. No security-contact address, key or tag/version is invented. .env is ignored; tracked .env.example holds explicitly local credentials. Local stdio is the tool transport; FastAPI includes only health routes, so no unauthenticated remote editing HTTP API is inferred. Secrets/advisory/build limits follow below.  
**Verdict:** Changes required for local bind, confirmed affected dependency pins and distribution contents; publication remains gated on final license/build/security evidence.

## Version and publication facts at the candidate

| Identifier | Actual source value / meaning |
| --- | --- |
| Python distribution | patchdiff-mvp 0.1.0; pyproject.toml |
| MCP serverInfo.version | 0.2.2; external_adapter.py |
| MCP transport protocol | 2024-11-05; external_adapter.py |
| Legacy artifact protocol | 0.2.3 |
| Typed match protocol | patchdiff-tx/1 |
| Guarded match/span protocol | patchdiff-tx/2 |
| Sole replacement protocol | patchdiff-tx/3 |
| Current legacy/tx1 execution profile | patchdiff-mvp-0.2.2 |
| tx2 execution profile | patchdiff-mvp-0.3.0 |
| tx3 execution profile | patchdiff-mvp-0.4.0 |
| Existing older execution profiles | 0.1.0, 0.2.0, 0.2.1 remain replay identities |
| Release tag | None selected or created by reviewer; git tag --list returned no local tags |
| Published release | Not established by reviewer; the implementation owner reports GitHub release API returned an empty list |

A future release tag is a publication decision, not proof that any of these independent IDs must change. The implementation owner reports actual public GitHub repository license metadata was null and LICENSE endpoint404 before the MIT addition; that is the implementation owner evidence, not a reviewer connector observation. This reviewer's git ls-remote --tags attempt failed because GitHub:443 was unreachable. The implementation owner subsequently reports authoritative GitHub tags and releases API lists were both empty; the final the implementation owner record must retain that external evidence rather than treating the failed local fetch as proof of no remote tags.

## Security, license/provenance and publication gaps

- The local Compose boundary issue is REL-DEP-001. No deployed exploit or credential compromise is claimed.
- A local stdlib scan read **298 tracked UTF-8 files** in the clean candidate worktree and found **zero matches** for four signatures: PEM private keys, GitHub tokens, AWS access IDs and OpenAI-style tokens. It printed only signature/path/line metadata. This is not a complete secret audit: no Git history, entropy, arbitrary credentials, PII/provenance or ignored/untracked file scan. No advisory queries were duplicated; the implementation owner owns current lockfile advisory evidence.
- Existing archived/accepted source and review material is preserved history, not a fresh license attestation of all contributed material. MIT owner authorization is reported by the implementation owner; the implementation owner must verify canonical text and package license contents before claiming completed release licensing. Third-party dependency licenses and redistribution obligations were not exhaustively audited.
- No security reporting contact or supported-version policy exists in the candidate. The implementation owner reports GitHub private vulnerability reporting is disabled. A future policy must state the real reporting gap or reference a verified channel, not an invented email.
- Candidate has no release notes, selected tag, publishing workflow, signed artifact or signing key. These are publication/evidence gaps, not automatic blockers to a source-only merge; the requested release preparation should leave concrete Unreleased notes and clearly label outstanding publication choices.
- Installation/build smoke, authoritative remote tag/release state, current advisories and final head/generated-merge CI remain implementation-owned checks. Production deployment, operational backups, auth for a future remote transport and representative representative migration/performance evidence are not certified.

## Verification record and remediation order

Reviewer executed: pinned git status/HEAD/branch/remotes/inventory/delta checks; local tag query; tracked release-file search; direct source reads listed above; bounded four-signature tracked-text scan. git ls-remote --tags failed network. No tests, wheel build, migrations, DB writes, full scanner or external advisory lookup were executed by this reviewer.

Fix source/documentation candidates first, add already-authorized MIT/release artifacts, validate Compose and package installation/build, then recheck the changed release surfaces and exact final CI. Do not publish or merge as a side effect of this review.

## Overall disposition and closure table

**Merge disposition:** Request narrow changes for REL-DOC-001, REL-DEP-001, REL-SEC-001 and REL-PKG-001; no new engine correctness blocker established here. Final integration approval requires the implementation owner's separate category/integration assessment and exact CI evidence.  
**Publication disposition:** Not ready to call a release published. License/release/security/build/version/tag evidence must be reconciled at the later actual fix SHA. Existing absence of a public release is accurately reported, not a failure.  
**Coverage disposition:** Release-facing source scope reviewed; full engine/security/production certification intentionally not claimed.

| ID / gate | State at 973ba79 | Independent triage / closure evidence |
| --- | --- | --- |
| REL-DOC-001 | Open P2 | The implementation owner independently confirmed and is preparing correction; no fix SHA/recheck yet. |
| REL-DEP-001 | Open P2, pre-existing | The implementation owner independently confirmed and is preparing loopback bind; no fix SHA/config evidence yet. |
| REL-SEC-001 | Open P2, pre-existing pins | Reviewer independently matched all 40 query pins and ten affected advisory records to candidate; the implementation owner fixing five pins plus pytest constraint. Corrected audit/build/suite/fix SHA still pending. |
| REL-PKG-001 | Open P2, pre-existing packaging rules | Reviewer independently inspected actual wheel ZIP/digest and source rules; the implementation owner fixing discovery/data rules. Corrected artifact/installed smoke/fix SHA pending. |
| MIT license publication | Missing at candidate | User chose MIT per the implementation owner; later LICENSE/metadata contents need recheck. |
| Release notes/version matrix | Missing at candidate | The implementation owner preparing Unreleased record, with no invented tag/version. |
| Security reporting / advisories | Evidence gap | Implementation-owned live checks; no fabricated contact or clean-advisory claim. |
| Build / package smoke | Evidence gap | Implementation-owned execution; no successful distribution build claimed here. |
| Final CI / remote refs | Evidence gap | Implementation-owned exact checkout/head/base checks. |
| Merge permission | Not granted | PR11 remains open; this report authorizes no merge. |

Implementation handoff: On the existing non-protected feature branch, independently classify every ledger ID as fixed, not-reproducible, duplicate, intentional-behavior or out-of-scope; preserve every ID in the final report/PR notes. For confirmed in-scope candidates, make the smallest correction and attach source recheck/config evidence at the real fix SHA. Re-review any later release artifact delta; retain this report at its original pin.

## Correction source recheck at 9473e8b

The implementation owner's correction is pinned at **9473e8bdfc64ae2c2630146af53e2c3428f1ca55**. The 973ba79-to-correction delta contains exactly 26 paths below and no backend application/test/evaluator source changes. This supplement preserves the original review's open-at-candidate states; it is a separate source recheck, pending final artifact/regression evidence.

| Category | Correction path |
| --- | --- |
| DEP | `.gitattributes` |
| DEP | `.gitignore` |
| ARCH | `AGENTS.md` |
| DOC | `CHANGELOG.md` |
| DEP | `LICENSE` |
| DOC | `README.md` |
| DOC | `README_DEV.md` |
| DOC | `README_INTERNAL_MCP.md` |
| DOC | `SECURITY.md` |
| DEP | `docker-compose.yml` |
| DOC | `docs/CLAUDE_DESKTOP_SETUP.md` |
| DOC | `docs/CODEX_BUILD_PLAN.md` |
| DOC | `docs/DATA_MODEL.md` |
| DOC | `docs/HOST_INTEGRATION_GUIDE.md` |
| DOC | `docs/MCP_FIRST_MVP.md` |
| DOC | `docs/MCP_TOOLS.md` |
| DOC | `docs/MODERNIZATION_ARCHITECTURE.md` |
| DOC | `docs/MODERNIZATION_CHANGE_DOC.md` |
| DOC | `docs/PATCHDIFF_CORE_SPEC.md` |
| DOC | `docs/PDCP_FORMAT.md` |
| DOC | `docs/RELEASE_READINESS.md` |
| DOC | `docs/TEST_MATRIX.md` |
| DOC | `docs/usability/internal/MODERNIZATION_CHANGE_DOC-973ba79.md` |
| DOC | `evaluation/README.md` |
| DEP | `pyproject.toml` |
| DEP | `requirements.lock` |

- **REL-DOC-001: partly corrected, residual sent to the implementation owner.** Actual 20-tool inventory and all four additions are present in main/internal/Claude onboarding. Host guide116 now qualifies 0.2.2 to tx1/legacy, names tx2/0.3.0 and tx3/0.4.0. A lexical scan of 18 active public documentation/release surfaces found no internal internal planning and agent labels; two ordinary phrases ('user's goal', 'always pass a guard') are valid product text. However CODEX_BUILD_PLAN33 still labels 0.2.2 current and gives an incomplete exhaustive profile list. The implementation owner was asked to qualify/reference the normative table before final closure.
- **REL-DEP-001: fixed and independently rechecked at 9473e8b.** Reviewer executed docker compose config --format json and inspected parsed publication: host_ip 127.0.0.1, published5432, target5432, tcp. No container or volume was recreated. SECURITY accurately says existing running containers retain old mappings until deliberately recreated.
- **REL-SEC-001: source/range correction rechecked; regression pending.** The five fixed pins and pytest>=9.0.3,<10.0 are present. Independently matched all 40 fixed-commit lock pins to dependency-osv-corrected.json, whose query SHA matches working-tree lock SHA58ad0b6ba179bf7e810227dfedd8aaf55f0e7d7a7dbdbf8438c0052c2b79a029. Recorded response has 40 empty result objects, findings[]. This establishes no advisory match for those pins at the recorded2026-10-22 query time, not enduring safety or exploit absence. The implementation owner's install log records the five corrected versions; coherent final environment/suite checks remain pending.
- **REL-PKG-001: source fix rechecked; artifact pending.** Discovery now includes app/app.* only and app package data explicitly includes migrations/alembic.ini and migrations/script.py.mako. Fresh-archive build/ZIP/license/migration/installed smoke evidence is still required; source metadata alone is not closure.
- **MIT/release presentation: source rechecked.** LICENSE is canonical MIT text with 2026 PatchDIFF contributors attribution, selected by the human user per parent authority; README links it and pyproject references the license file and README. CHANGELOG is explicitly Unreleased; security/version/release notes preserve limits and independent version domains. Proposed v0.1.0 is derived from existing distribution 0.1.0 and explicitly uncreated/unapproved. Disabled private reporting and intended container assessment remain publication prerequisites; no contact, key or published release is invented.
- **Historical record preservation:** New internal archive SHA-256 **461008e70dc3b7da815ee503b3ea9ae39ad8208efdd574c12649f8b6394dff51** exactly matches the old document's Windows checkout bytes. Its214 CRLFs explain the difference from the old LF Git blob SHA91fdb2d392c6c809be07f1f55da1fdf94c04e3b0bf09e3c46a128cb3b5f5f4b8; normalized bytes are equal. New exact-path -text keeps those archived bytes stable. This explicitly does not claim the differently normalized Git blobs have identical SHA-256. Protected existing review/accepted records have no correction delta.

No final approval or publication disposition is inferred from this source-only supplement. The implementation owner is executing the authorized fresh build, installed smoke, full suite and separate manual workflow.

### Fresh artifact content recheck

Reviewer independently inspected the fresh 9473e8b archive build's wheel at reproduction/2026-10-22/release/wheels-9473e8b/patchdiff_mvp-0.1.0-py3-none-any.whl: **83,108 bytes**, SHA-256 **5b132265d6243a77faec627727b26a71ca20bb90394fcf4040f84ac3ac12fcca**. The implementation owner's build log records the same size/hash. Top-level ZIP members are only app and dist-info; there are **zero tests/** files. Both migration assets and the license file are present and normalize to the exact checkout text. Metadata Name/Version are patchdiff-mvp/0.1.0, License-File is LICENSE, README content type is text/markdown and Python requirement is >=3.11. UTF-8 decoded metadata description exactly equals the 9072-character README. This corrects REL-PKG-001's observed distribution-content defect; installed outside-checkout execution still requires its own evidence before full closure.

## Finding closure recheck through 57dd7c4

This supplement supersedes the original candidate's open states for the three findings closed below. Correction 9473e8b contains the source/package/configuration changes; **60b16da336cd1c9678f561fca985d9a824a95184** and **57dd7c44b7fbd2e421abaa087591526f0de7037c** add only three documentation-path corrections: CODEX_BUILD_PLAN (DOC), MODERNIZATION_ARCHITECTURE (ARCH), and MODERNIZATION_CHANGE_DOC (DOC). Git comparison confirms no application, packaging input, lockfile or README delta from the built 9473e8b artifact.

### REL-DOC-001 — fixed, source independently rechecked

The implementation-map profile list now names current tx1/legacy 0.2.2, tx2/0.3.0 and tx3/0.4.0 separately. Architecture and public change record correctly qualify strict typed change IDs separately from frozen nonempty/unique legacy IDs. Combined with the 9473e8b onboarding/tool inventory and terminology changes, the original finding's source acceptance is satisfied. Public notes remain Unreleased, MIT is explicit, the tag is only a proposal, and publication/security limits are visible. No runtime behavior or protected historical record was rewritten to achieve this correction.

### REL-PKG-001 — fixed at 9473e8b, artifact and execution independently rechecked

The implementation owner's fresh outside-checkout installed-wheel helper is reproduction/2026-10-22/release/installed-package-smoke.py; SHA-256 **13e973389ff4efe8996896d9c0fcb5e4daeea450cd85a6e46a56430e08524aeb** matches its recorded digest. Reviewer inspected the helper's assertions and decoded every request/response in installed-package-smoke.json. The artifact remains the fresh 83,108-byte wheel SHA-256 **5b132265d6243a77faec627727b26a71ca20bb90394fcf4040f84ac3ac12fcca**.

The helper removes PYTHONPATH and locale overrides, launches children with an outside-checkout working directory, asserts the app loads from site-packages, and compares all **48 installed app Python files** byte-for-byte to the wheel. Packaged Alembic configuration successfully upgrades a new isolated database through the two required migrations. Both HTTP health routes return 200 through a real Uvicorn process using that installed package.

Reviewer independently decoded all **13 raw JSON-RPC request/response pairs**, checked matching IDs/no RPC errors and public isError=false, counted 20 tools/13 examples, recomputed all four accepted result hashes, and verified accepted preview/submit hash parity. The sequence executes tx3 replacement, tx2 span, tx1 match and legacy PDCP, reaching versions 1..4. Recovery arguments exactly equal the original replacement arguments after later edits; recovery returns the same original log/version 1 with deduplicated=true. Later line read/export show current version 4 text **!ready 中\n**. SAVE succeeds and replay independently checked all four materialized-state booleans true.

Reviewer also executed a **fresh independent SQL query** with default_transaction_read_only=on, verified that setting, and confirmed target **ca1cefbd-9fd6-41ff-9b24-2f2093370973** has text !ready 中 plus LF, version 4 and SHA-256 **1549dda3c53251a0403169fb7e789cc74e7eb5cc3ba91553cf1989bba4ddaab4**. It has exactly four accepted attempts in protocol/runtime order tx3/0.4.0, tx2/0.3.0, tx1/0.2.2 and legacy0.2.3/0.2.2, plus four ledger rows. This fresh observation matches the captured SQL and supports no extra preview/recovery attempt.

The initial installed-smoke run failed before product assertions because PostgreSQL was paused and the connection timed out. Its log is preserved separately; it is not represented as a passing run or a package defect. The later successful manual run, wheel/source/helper identities and read-only SQL close the actual packaging finding without claiming a published distribution.

### Current closure table

| Finding | Independent status | Evidence |
| --- | --- | --- |
| REL-DOC-001 | fixed | 9473e8b source inventory/terminology plus 60b16da/57dd7c4 version/typed-ID qualifications rechecked. |
| REL-DEP-001 | fixed | 9473e8b source and reviewer-executed parsed Compose host_ip 127.0.0.1/tcp 5432; no existing container/volume recreation. |
| REL-PKG-001 | fixed | 9473e8b fresh archive wheel ZIP/metadata/assets/license and actual installed outside-checkout stdio/migration/HTTP/manual proof, independently decoded and freshly read-only SQL checked. |
| REL-SEC-001 | source/advisory correction rechecked; full regression evidence pending | All40 corrected pins equal recorded clean advisory query; actual corrected installation recorded. Await the authorized full suite in the patched environment before final closure. |

Release-facing source and the installed package show no remaining candidate defect in the rechecked scope except the pending dependency-regression gate. Final current-head/generated-merge CI, private security-reporting setup, container/deployment assessment and explicit tag/publication authorization retain their stated boundaries. This review grants no merge, tag or release permission.

## Final dependency regression and disposition

**REL-SEC-001 is fixed at 9473e8b and independently closed with regression evidence at 57dd7c44b7fbd2e421abaa087591526f0de7037c.** Reviewer parsed final-suite-junit.xml: **1,144 cases = 755 unit + 389 integration, zero failures/errors/skips, 131.020 seconds**. The successful log and XML agree. Tests include live populated migration preservation/refusal and actual stdio; inspected prior assertions and unchanged engine review are reused, not replaced by the count.

The implementation owner reports this single final full run executed source 57dd7c4 with Python 3.11.9 in the isolated patched 40-pin environment and fresh patchdiff_release_suite_20261022 database. The five source pins/pytest constraint, actual installation record and exact 40-query zero-match OSV result were independently rechecked above. Implementation-reported pip check is green. The XML/log inspection is reviewer evidence; environment/source invocation is implementation execution provenance, not a second reviewer suite rerun.

Reviewer inspected offline-final.txt: the existing format matrix and explicitly named legacy delimiter exception pass, and all five replacement content/hash oracles report OK. Ten deprecation warnings are visible: nine Alembic prepend-path-splitting warnings and one supported Starlette/httpx test-client warning. No failure was converted to a skip or suppressed to obtain this result. The earlier paused-database setup failed before pytest and is preserved separately from the successful execution.

| Finding | Final independent classification | Fix and closure evidence |
| --- | --- | --- |
| REL-DOC-001 | fixed | Source 9473e8b tool/terminology corrections plus 60b16da336cd1c9678f561fca985d9a824a95184 and 57dd7c44b7fbd2e421abaa087591526f0de7037c profile/typed-ID qualification rechecks. |
| REL-DEP-001 | fixed | Source 9473e8b loopback bind; reviewer-executed parsed Compose configuration; no existing container/volume recreation. |
| REL-SEC-001 | fixed | Source 9473e8b five corrected lock pins and pytest constraint; exact 40-pin clean OSV result, installation evidence and successful 1,144-case patched-environment full suite at 57dd7c4. |
| REL-PKG-001 | fixed | Source 9473e8b restricted discovery/explicit assets; fresh wheel identity/ZIP/metadata/license inspection; installed 48-file equality and outside-checkout migration/stdIO/HTTP manual evidence; independent raw-event/hash/dedup decoding and fresh read-only SQL. |

**Final source/release-readiness recommendation:** No unresolved finding remains in this reviewed scope. Local package, dependency, documentation, license and configuration prerequisites are satisfied at the stated revisions. This is not complete engine/security/production certification; the separate integration review and exact final published-head/generated-merge CI remain necessary for a merge recommendation. PR11 remains open under the owner's hold. Publication still requires a verified private reporting channel, intended-container/deployment assessment, a final merged revision/artifact identity, and explicit tag/version/release approval. The proposed v0.1.0 remains uncreated and unapproved. Protected historical review/accepted records were not edited; this newly authored report alone was renamed to a plain product filename at the user's request.



