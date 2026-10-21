# Goal G independent review

## Metadata and evidence limits

- Repository: `paragon-ux/Patch-DIFF`.
- Date: 2026-10-21.
- Reviewer: `/root/goal_g_independent_review`, inherited/default model; independent of implementation.
- Standard: `docs/PR_REVIEW_STANDARD.md` v1.1.0.
- Base: `b5caa40bd41848420c4323d22ab648847cdc6745`.
- Reviewed/fixed head: `f19c97f50f241b8af764539e818c6e9762de3c1b`.
- Branch: `fix/gemini-stdio-utf8`.
- Scope: accepted Gemini plan/archive and bounded G02 transport fix. This is not a new approval of PR #1 or the existing remediation stack.
- No new PR or CI evidence was available. The installed native MCP remains on the recorded playground baseline; fixed-code verification used actual subprocesses from the reviewed checkout.
- Four pre-existing skill-description edits and untracked Devin files were excluded.

No actionable P1, P2, or P3 defect remains within this change’s reviewed scope.

## Changed-file inventory and coverage

Each of the 26 changed files has one primary category:

| Primary category | Changed files |
| --- | --- |
| MCP | `backend/app/mcp/external_adapter.py` |
| TEST | `backend/tests/integration/test_external_mcp_utf8.py`; `backend/tests/unit/test_stdio_utf8.py` |
| DOC | `README.md`; `docs/CLAUDE_DESKTOP_SETUP.md`; `docs/HOST_INTEGRATION_GUIDE.md`; `docs/MODERNIZATION_CHANGE_DOC.md` |
| ARCH | `docs/gemini-remediation/G02-decision.md` |
| SCRIPT | `docs/gemini-remediation/G02-live-verify.py` |
| DOC | `docs/reviews/gemini/GEMINI_CHANGE_PLAN.md`; `docs/reviews/gemini/Gemini-Goal-G.md` |
| DOC | `docs/reviews/gemini/archive/2026-10-21-reproduction/REPRODUCTION_REPORT.md` |
| SCRIPT | `docs/reviews/gemini/archive/2026-10-21-reproduction/evidence-sha256.json`; `independent-verification.json`; `installation-preflight.json`; `native-events-final.json`; `scripted-steps.json`; `transport-results.json`; `workflow-metrics.json` — all under that same directory |
| SCRIPT | `docs/reviews/gemini/archive/2026-10-21-reproduction/transport_probe.py`; `docs/reviews/gemini/archive/2026-10-21-reproduction/verify_results.py` |
| DOC | `docs/reviews/gemini/archive/2026-10-21-superseded/DEFECT-001-windows-stdio-utf8.md`; `G-SERIES-FRICTION-INVENTORY.md`; `GEMINI_FRICTION_AND_DEFECT_DISPOSITION.md` — all under that same directory |
| DOC | `docs/reviews/gemini/archive/ARCHIVE_MANIFEST.json`; `docs/reviews/gemini/archive/README.md` |

All ten required categories were assessed for this change. Unchanged service/core/schema dependencies were considered for compatibility; this review does not constitute a fresh whole-repository audit.

## Architecture-to-implementation trace

The original concept-paper abstract/introduction establishes explicit target-native edits, deterministic validation, and no hidden repair. Current `AGENTS.md` and architecture Unicode contracts preserve exact decoded proposal text and distinguish safe audited invalid-domain input.

G02 violated this boundary before domain validation: ambient cp1252 could reinterpret valid raw UTF-8 as different, storable text. The recorded decision selects explicit strict UTF-8 at process startup.

The implementation changes only [the two stream reconfiguration calls](https://github.com/paragon-ux/Patch-DIFF/blob/f19c97f50f241b8af764539e818c6e9762de3c1b/backend/app/mcp/external_adapter.py#L132-L135). Reconfiguration mutates the existing wrappers, preserving the references already bound in `serve_stdio` defaults. It does not change selectors, application order, transaction ownership, fingerprints, replay profiles, schema, or dependencies.

## ARCH — Architecture and contracts

Coverage: complete for the transport change. Inspected the accepted decision, goal, architecture Unicode boundary, relevant concept-paper thesis, and implementation.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: the chosen process-boundary fix preserves domain validation and avoids replacement/ignore decoding. No new runtime profile or migration is warranted.

Gaps: the complete historical design paper was not re-audited; its thesis is not modified.

Verdict: no findings within reviewed scope.

## DOC — Documentation and change records

Coverage: complete for active additions, accepted scope, archival provenance, and compatibility claims.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: active guides describe UTF-8, the older-revision workaround, strict malformed-wire handling, and host-specific refresh. Accepted documents distinguish corrected claims from historical reports and retain Goal F ownership. Independently verified hashes for all three archived original reports, ten copied reproduction files, and twelve protected historical files.

Gaps: historical absolute links can retain their original locations; the archive README explicitly explains this and supplies the manifest mapping.

Verdict: no findings within reviewed scope.

## SKILL — Skills and agent instructions

Coverage: complete for this change’s relevant instructions and exclusions. No skill file belongs to the committed diff.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: repository instructions require live PostgreSQL, real subprocess verification, and independent category review. The four existing description edits remain outside this change.

Gaps: no new Antigravity skill-loader run; accepted documents correctly limit the earlier result to YAML parsing.

Verdict: no findings within reviewed scope.

## MCP — Schemas and public API

Coverage: complete for the modified entry point and its unchanged dispatch/framing dependencies.

### P1
None identified within reviewed scope; corrected G02 is closed below.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: independently executed a literal UTF-8 star request under `PYTHONIOENCODING=cp1252:surrogateescape`. The fixed subprocess returned the exact star and exited normally. Inspected raw-byte regression and live workflow assertions. `serve_stdio` injection, ASCII response escaping, tool schemas, and handled keyword errors remain unchanged.

Gaps: no fixed-code native-host reload was performed; subprocess execution is explicitly distinguished.

Verdict: no findings within reviewed scope.

## RUN — Parsing and deterministic runtime

Coverage: complete for the affected Unicode boundary and compatibility delta; matcher/applier code is unchanged.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: strict wire decoding rejects invalid bytes before dispatch. Valid JSON escapes still reach existing surrogate/NUL domain rejection. The new live assertions check `target_encoding_invalid` at `protocol_validation`; safe evidence retains `evidence_format=patchdiff-invalid-input/1`.

Gaps: no new guarantee of recovery within a malformed-byte connection. The decision does not promise one.

Verdict: no findings within reviewed scope.

## SVC — Services, recovery, and audit

Coverage: complete for the unchanged service behavior reached by the new transport tests.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: live tests inspect same-log keyed recovery and independent accepted/rejected row counts. Reviewer SQL readback independently matched all four manual target states: version 1, one accepted attempt, two rejected attempts, and one ledger row.

Gaps: this change does not extend concurrency or isolation guarantees; no service implementation changes are present.

Verdict: no findings within reviewed scope.

## DB — Persistence, migrations, and replay

Coverage: complete for this change’s persisted Unicode and audit/replay effects; no schema delta exists.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: reviewer independently queried the four manual targets and confirmed exact Unicode content and recorded row counts. Manual evidence reports all four materialized replay checks true for each profile. Suite output includes existing populated migration and downgrade-refusal tests.

Gaps: no new production-data migration rehearsal; no migration is introduced.

Verdict: no findings within reviewed scope.

## SCRIPT — Evidence and developer tooling

Coverage: complete for the manual helper and the archived evidence’s relevant semantics/provenance.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: inspected the helper’s actual assertions, strict subprocess timeouts, source hashes, decoded proposals, SQL readback, and explicit malformed-wire nonmutation check. Independently parsed all twelve manual raw-run records and verified the two recorded source-file hashes. Archived scripts are historical reproduction records rather than claimed portable deployment tools.

Gaps: the manual helper intentionally names a dedicated local database; it assumes that database has been prepared.

Verdict: no findings within reviewed scope.

## TEST — Tests and execution evidence

Coverage: complete for the added assertions and available local verification.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification:

- Inspected unit assertions for actual raw-byte decoding, stream reconfiguration, injected streams, and malformed-byte failure.
- Inspected four parameterized live profiles: absent/cp1252 environment × literal/escaped JSON.
- Inspected parent-executed suite output: **842 passed, nine Alembic deprecation warnings, 102.13 seconds**.
- Inspected offline output: **shared-applier verdict equivalence OK**.
- Independently reran the write-free cp1252/raw-UTF-8 probe.
- Independently rechecked source-pinned manual evidence and four targets with SQL.

Gaps: no new remote CI run was inspected; local Windows results do not establish separate Linux-host execution.

Verdict: no findings within reviewed scope.

## DEP — Dependencies, packaging, and startup configuration

Coverage: complete for the startup delta and documented invocation.

### P1
None identified within reviewed scope.

### P2
None identified within reviewed scope.

### P3
None identified within reviewed scope.

Verification: standard-library `TextIOWrapper.reconfigure` is applied before serving. No dependency or lockfile change. Absent and explicitly cp1252 environment profiles passed. The older `PYTHONIOENCODING=utf-8` workaround remains compatible.

Gaps: embedded callers replacing `sys.stdin`/`sys.stdout` before invoking `main()` are not a newly supported hosting interface; injectable `serve_stdio` remains available.

Verdict: no findings within reviewed scope.

## Root cause and disposition reconciliation

The single product defect belongs to transport decoding, before trusted domain processing. Fixing the entry point avoids changing persistence or identity to compensate for already-corrupted text.

Raw preserved evidence independently supports the accepted distinctions:

| Item | Recheck disposition |
| --- | --- |
| G01 | Affected Antigravity lifecycle claim remains unverified; explicitly deferred. |
| G02 | Corrected input-corruption defect fixed and independently rechecked. |
| G03 | Unhandled/P1 premise contradicted by `isError:true` and subsequent success; no dispatch rewrite. |
| G04 | Returned exclusive cursor works; `min−1` recommendation skips an eligible row. Preserve behavior. |
| G05 | Literal diff text absent from ledger; supplied rationale/intent and risk present. Optional enrichment remains deferred. |
| G06 | Sequential semantics intentional; original-buffer dependency rejects atomically. |
| G07 | Missing-metadata premise falsified: search contains `version` and `current_hash`. |
| G08 | Diagnostic limitation retained as Goal F/F06 work; conjunctive selector semantics preserved. |

## Closure and overall disposition

| Finding | Fix | Recheck evidence | Status |
| --- | --- | --- | --- |
| G02 / DEFECT-001, corrected P1 input corruption | `f19c97f50f241b8af764539e818c6e9762de3c1b` | Independent raw-byte cp1252 probe; reviewed regression assertions; inspected 842-test/offline outputs; source-hash validation; independent SQL readback of all four manual profiles | Closed within Goal G scope |

Recommend acceptance of this bounded Goal G change. No blocking or advisory implementation findings remain in the reviewed diff.

This recommendation does not authorize merges, approve PR #1 as a whole, claim remote CI success, or close the deferred Antigravity-host and Goal F work.

## Evidence-only delta recheck

This section reviews the subsequently prepared evidence records separately from the source review pinned above. Their future commit is not presented as a newly executed product revision.

| Primary category | Additional evidence files |
| --- | --- |
| SCRIPT | `docs/gemini-remediation/G02-suite.txt`; `G02-offline.txt`; `G02-manual.txt`; `G02-live-results.json` — all in the same directory |
| DOC | `docs/gemini-remediation/G02-verification.md`; this `G02-independent-review.md` |

The verification summary faithfully distinguishes worker-focused testing, parent suite/manual execution, reviewer readback, historical reproduction, and unavailable CI/native deployment. Its 842-test result, offline equivalence result, four manual profiles, exact executed SHA, SQL counts, and source hashes agree with inspected artifacts. Both Devin template hashes remain unchanged.

The adapter, both new test files, and manual helper match the reviewed f19c97f committed material after normal Git CRLF normalization; the manual record's raw working-file hashes for the adapter/helper also match current bytes. No product/test/helper edit was found in the evidence-only delta.

Category delta: DOC, SCRIPT and TEST evidence reconciled; ARCH, SKILL, MCP, RUN, SVC, DB and DEP source conclusions unchanged. P1: none identified within reviewed scope. P2: none identified within reviewed scope. P3: none identified within reviewed scope. Gap: the evidence-only commit hash does not exist at this review's preparation time; remote CI and fixed native-host deployment remain unclaimed. Verdict: no findings within the reviewed evidence-only delta.
