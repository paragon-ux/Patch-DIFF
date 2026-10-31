# Compact MCP / host finalization: incremental implementation review

Date: 2026-10-28. Standard: PR_REVIEW_STANDARD v1.1.0.
Repository: paragon-ux/Patch-DIFF. Intended stacked PR: #17, dependent on #16.
Base: `4b18e36355ca02e642023d86996b5b75063ed9ad`.
Reviewed implementation head: `23b9f24d859b7e8787fd1ddd6a79b3a80b9ffd82`.
Reviewer: primary implementation agent; this is a source/test self-assessment,
not independent code approval. One fresh Astra High agent reviewed the plan only;
the implementation agent independently triaged its F1/F2 findings. No further
agent review or benchmark qualification was introduced.

This report is a documentation-only follow-up to the reviewed implementation
commit. Its own primary category is DOC. Exact pushed-head Linux CI remains a
separate delivery receipt; it was not yet available when this report was written.

## Inventory and provenance

| Changed file | Primary category |
| --- | --- |
| .github/workflows/ci.yml | TEST |
| backend/app/mcp/external_adapter.py | MCP |
| backend/tests/integration/test_compact_host_workflow.py | TEST |
| backend/tests/unit/test_host_finalize.py | TEST |
| backend/tests/unit/test_mcp_response_modes.py | TEST |
| backend/tests/verification/README.md | DOC |
| backend/tests/verification/structural_batch/verify.py | SCRIPT |
| docs/HOST_INTEGRATION_GUIDE.md | DOC |
| docs/MCP_TOOLS.md | MCP |
| docs/MODERNIZATION_ARCHITECTURE.md | ARCH |
| docs/MODERNIZATION_CHANGE_DOC.md | DOC |
| docs/OBSERVED_EDITOR_WORKFLOW.md | SKILL |
| docs/PatchDIFF-Concept-Paper-6.md | ARCH |
| docs/STRUCTURAL_BATCH_EDITING.md | ARCH |
| docs/TEST_MATRIX.md | TEST |
| examples/host_finalize.py | SCRIPT |
| docs/reviews/PR17-implementation-review.md (report follow-up) | DOC |

Sources examined: locked AGENTS.md boundaries; original Concept Paper 5 abstract/
thesis; current architecture A1/A3/A5/A6/A7; structural batch contract; MCP schemas
and adapter; scope observation/page construction; SAVE, replay and export services;
storage cycle/snapshot fields; all changed implementation/test/documentation files.
The review covers the incremental change, not a fresh audit of PR16's worker or
historical runtime implementations. Existing user Docker/README edits and internal
evaluation artifacts are excluded and were not copied into this branch.

Architecture trace: deterministic transaction/persistence authority -> host-owned
planning/lifecycle -> opt-in external representation -> post-registry projection
and scalar host recipe -> unit, live PG/stdio and independent five-file oracles.
Detailed defaults, profile names/counts, schemas, request fingerprints, guards,
replay profiles, and stored facts remain unchanged. The host does not rebase
guards, infer task correctness from acceptance, or retry an uncertain SAVE.

## ARCH — Architecture and contracts

Scope/coverage: complete for the incremental boundaries and three architecture
documents. Projection follows registry evaluation; the example remains outside
server/core layers. The observed profile still permits six tools; role lifecycle
ownership is not misrepresented as an enforced new capability boundary.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification/gaps: inspected adapter, example and workflow against current contracts;
live workflow and preserved-file comparison support unchanged authority. No host
latency or universal spill-size claim is established. Verdict: no findings within
reviewed scope.

## DOC — Documentation and change records

Scope/coverage: complete for changed guides, change record, verification README
and this report. Active prose distinguishes default detailed from compact results,
server SAVE from host compaction, and replay integrity from task correctness.
Historical documents/fixtures remain unchanged.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification/gaps: source reconciliation and whitespace checks; actual Antigravity
schema preloading/output-limit support remains unverified and is explicitly
conditional. Verdict: no findings within reviewed scope.

## SKILL — Skills and agent instructions

Scope/coverage: complete for new task-independent workflow v1; no skills changed.
Instructions permit required tool-help/spill lookup, preserve original task and
archived arm prompts, prohibit oracle/solution access, retain exact proposal keys,
and assign bounded completion reporting to the editor.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification/gaps: compared all named tools/fields/routes with source. The owner
must configure/restart the real editing process; no model run was launched.
Verdict: no findings within reviewed scope.

## MCP — Schemas and public API

Scope/coverage: complete for adapter/representation contract and unchanged inputs.
Default and unrelated/error serialization are preserved. Projection removes only
reviewed fields, announces actual omissions, preserves future envelope/warning
fields and does not mutate registry results. Scope pages remain unchanged.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification/gaps: mode/schema/profile/Unicode unit cases and real stdio acceptance,
warning/recovery, stale rejection and paging. No missing proof identified within
this local scope. Verdict: no findings within reviewed scope.

## RUN — Core runtime, parsing and validation

Scope/coverage: complete for preservation in this incremental diff; no core/parser
changes. Exact sequential application and recorded runtime dispatch remain owned
by existing implementation. This is not an independent re-audit of those modules.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification/gaps: unit/integration and offline equivalence passed; preserved paths
were compared with the parent. Verdict: no findings within reviewed scope.

## SVC — Orchestration and audit

Scope/coverage: complete for new host orchestration and unchanged service entry
points. Finalization copies original accepted guards, calls scalar services once,
keeps per-target outcomes, and stops after infrastructure/evidence failure.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification/gaps: explicit rejection, response loss, malformed receipt, component
replay failure and export mismatch tests; no automatic retries/resume. Verdict:
no findings within reviewed scope.

## DB — Persistence, replay and concurrency

Scope/coverage: complete for the changed caller's assumptions, no DB/runtime
changes. SAVE rotates a cycle without changing target content/hash/version;
replay must match all four components and expected hashes/versions. Cross-target
atomicity is neither implemented nor claimed.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification/gaps: live tests verify two independent projects, one save snapshot/
cycle rotation each, unchanged materialized state, and exact exported bytes. Full
integration includes existing migration/concurrency coverage. Verdict: no findings
within reviewed scope.

## SCRIPT — Operator and verification tooling

Scope/coverage: complete for host_finalize and modified verification client/runner.
Finite RPC deadlines include write/read; failed startup/timeout reaps the peer.
No unbounded stderr read, automatic resend, model controller or benchmark exists.

### P1
None identified within reviewed scope.
### P2
- F1 — fixed. Plan allowed target/control artifact filename collisions. Trigger:
  a valid target named results.json. Independent triage confirmed the collision
  risk. The implementation separates exports/ from control files and preflights
  case-insensitive duplicates and Windows/POSIX names. Acceptance:
  test_success_separates_export_names_from_control_artifacts_and_refuses_rerun,
  unsafe-name and duplicate-name cases. Fix/recheck: reviewed head above.
- F2 — fixed. Plan required a stored report even after persistence failure.
  Independent triage confirmed that guarantee was unachievable. Successful bytes/
  receipts are flushed/fsynced; failures stop calls and return explicit incomplete
  state, with results.json best-effort. SAVE receipt failures remain uncertain.
  Acceptance: failed_save_receipt_fsync and evidence_failure unit cases.
  Fix/recheck: reviewed head above.
### P3
None identified within reviewed scope.

Source evidence for both closures:
[host recipe at reviewed commit](https://github.com/paragon-ux/Patch-DIFF/blob/23b9f24d859b7e8787fd1ddd6a79b3a80b9ffd82/examples/host_finalize.py),
[regressions](https://github.com/paragon-ux/Patch-DIFF/blob/23b9f24d859b7e8787fd1ddd6a79b3a80b9ffd82/backend/tests/unit/test_host_finalize.py).
Verdict: no unresolved findings within reviewed scope; filesystem checks do not
claim universal power-loss durability.

## TEST — Tests and CI

Scope/coverage: complete for new tests, existing suite integration and the single
additional compact-host five-file CI step. Existing Linux worker/migration checks
are retained. Inputs/oracle/prepared operations retain parent bytes.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Local evidence: Windows x64, Python 3.11.9, Node 22.19.0, PostgreSQL 16.3, locked
dependencies and a fresh isolated test database. Unit: 957 passed, zero skipped.
Integration: 542 passed, zero skipped, resident mode, including real stdio and
migrations. Offline verdict/replacement oracle equivalence passed. Both detailed
and compact-host five-file runs passed five full-byte oracles and 20/20 behavior
checks; model invocations zero. Compact-host editor made ten editing calls and
zero SAVE/REPLAY calls; lifecycle calls still occur through the trusted operator.

Local runs exercised the implementation working tree; final verifier-only byte
receipt/assertion additions were exercised by both subsequent five-file runs.
Exact final pushed-head CI is required separately and was pending at authoring.
Verdict: no findings within reviewed local scope; remote platform proof pending.

## DEP — Dependencies, packaging and configuration

Scope/coverage: complete for the new frozen startup mode and checkout-only operator
example. No dependencies/lockfiles changed. Production packaging does not import
the test helper or example; the guide explicitly scopes the operator recipe to a
checkout. Resident remains opt-in and oneshot remains the compatibility default.

### P1
None identified within reviewed scope.
### P2
None identified within reviewed scope.
### P3
None identified within reviewed scope.

Verification/gaps: pinned dependencies installed offline in an isolated venv;
unit packaging/config checks passed. Actual Antigravity deployment remains an
owner integration step. Verdict: no findings within reviewed scope.

## Disposition and remaining evidence

F1/F2 share a host-evidence failure boundary, not a database/runtime defect. Both
were resolved before delivery without redesigning SAVE or adding another review
round. No other candidate was deferred by priority.

No unresolved source finding identified in this incremental implementation.
This self-assessment does not grant merge approval. Inspect exact pushed-head
Linux CI before delivery; retain the actual-host spill/schema check as an owner
pre-canary task. No synthetic performance qualification, live model canary,
comparative study, Gate 2 approval or merge was performed.
