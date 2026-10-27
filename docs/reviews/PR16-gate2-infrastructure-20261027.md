# PR #16 Gate 2 infrastructure implementation evidence

Date: 2026-10-27. Standard: PR Review Standard 1.1.0. Author: Sol engineering
implementation agent. This is implementation/self-inspection evidence, **not an
independent Gate 2 authorization**. Prior independent review:
https://github.com/paragon-ux/Patch-DIFF/pull/16#pullrequestreview-5663108394.

Repository: https://github.com/paragon-ux/Patch-DIFF. Branch:
`feat/waymark-structural-observation`. Previous independently reviewed head/base of
this delta: `9e7f9614728ad5098d543c1f2f98774ae0f4fe6c`. PR base remains
`f5cc6742f94e080d2eda7486265e79eebf55c8ad`.
Implementation commit: **`51dec6d37b62484e74d43dc8ef55fc66a8604541`**.
This report is a subsequent documentation-only commit. The final PR comment records
its complete delivery SHA, CI run URLs, executed head/merge revisions and log counts.

Production A-F and original recovery G-1 are carried forward from the independent
review. There is no delta to production runtime, applier, services, DB schema,
Waymark dependency, original task/tool prompts, fixtures, historical prompts/setup/
verifier or supplemental study. Git path comparisons were empty and original input
hashes passed. No measured model, substitute model, measured arm or merge occurred.

## Required implementation matrix and finding triage

| Category | Priority | Implementation | Evidence | Verdict |
| --- | --- | --- | --- | --- |
| G2-1 Exact-byte oracle | P1 gate dependency | `full_byte_oracle.py:30` explicit original-offset transformations; `:149` whole-file comparison; `evaluate.py:31` both-oracle gate | Positive gold 20/20; 13 corruption scenarios; collateral comment passes behavior but fails byte oracle; source authentication | Ready for independent review |
| G2-2 Controller | P2 | `controller.py:47` lifecycle/broker, `:344` balanced schedule; `mcp_session.py:29` real stdio and `:74` disposable DBs | Nine archived synthetic lifecycles; real B/C accepted/rejected histories, committed-response loss/idempotency, SAVE/export/replay; zero model calls | Ready offline; host binding externally gated |
| G3-1 Host configuration | P2 | `host_adapter.py:28` protocol, `:83` bridge; `preflight.py:13` host parity, `:80` external approval; `controller.py:335` all-arm tool checks | Configuration mismatch/missing usage/permissions tests; actual stdio schemas; unresolved example preflight exits 2 | Interface ready; external verification pending |
| G3-2 Telemetry/budgets | P2 | `telemetry.py:33` append-only evidence, `:70` budgets; controller request/tool events and audit | Actual-usage contract tests; calls/deadline/timeout/retry tests; raw MCP frame bytes/hashes; truncated evidence rejected | Ready offline; provider enforcement pending real host proof |
| G3-3 Freeze | P2 | Manifest/controller source pins, reference manifest, LF source checkout rules, operator plan | Pin validation, unchanged historical inputs, balanced order and failure denominator tests | Ready for independent review |

**G2-1 findings:** P1: the requested complete-byte dependency is implemented; peer
recheck remains required. P2: evaluating arbitrary output Python before an exact-byte
gate would execute untrusted code; the primary CLI now gates imports on whole-byte
equality and suppresses bytecode writes. Regression checks assert the skip on all
corruptions and no added files after positive evaluation. P3: none identified in scope.

**G2-2 findings:** P1: none newly identified. P2: none unresolved in offline controller
scope. Failed stages, unauthorized requests and unsuccessful runs are archived; no
result repair or rerun is implemented. Underlying host isolation is an explicit
external dependency. P3: none identified. Databases are intentionally retained for
review and require explicit owner cleanup, documented in the operator plan.

**G3-1 findings:** P1: none newly identified. P2: a first implementation checked actual
bindings only when each arm initialized, permitting A to begin before discovering a
bad B/C binding. It now verifies all native/MCP bindings before any measured context;
the schema mismatch regression checks that boundary. Exact real model ID/High and
host evidence remain unresolved external requirements, not fabricated completion.
P3: none identified in scope.

**G3-2 findings:** P1: none newly identified. P2: no unresolved defect found in tested
budget/telemetry scope. Independent SQL/Waymark-internal durations cannot be obtained
through current public MCP; records explicitly flag these components unavailable
and report observable round trips only. Independent review must accept that
limitation or request a separate instrumentation amendment. P3: none identified.

**G3-3 findings:** P1/P2: none newly identified beyond the original review dependencies.
P3: Windows checkout conversion could invalidate code pins; execution sources now
have explicit LF checkout rules. Only the new reference manifest was normalized;
all historical bytes remain intact. No unresolved in-scope P3 remains.

These are implementation classifications/evidence, not independent closure of the
original ledger. The reviewer must recheck G2-1/G2-2/G3-1/G3-2/G3-3 at the delivered
revision; current Gate 2 approval remains null/closed.

## Changed-file inventory and architecture trace

All paths below are repository-relative for inventory purposes. No files outside
this list belong to this implementation delta (the last row is this evidence commit).

| Primary category | Files |
| --- | --- |
| DEP | `.gitattributes` |
| TEST | `backend/tests/integration/test_retest_controller_mcp.py`; `backend/tests/unit/test_retest_controller.py`; `backend/tests/unit/test_retest_host_telemetry.py`; `backend/tests/unit/test_retest_oracle.py`; `backend/tests/unit/test_retest_preparation.py` |
| DOC | `docs/WAYMARK_STRUCTURAL_OBSERVATION_RETEST_PLAN.md` |
| SCRIPT | `evaluation/structural_retest/controller.py`; `evaluate.py`; `freeze.py`; `host_adapter.py`; `host_config.example.json`; `manifest.json`; `mcp_session.py`; `native.py`; `preflight.py`; `prepare.py`; `synthetic.py`; `telemetry.py`; `primary/evaluator/full_byte_oracle.py`; `primary/evaluator/reference_hashes.json` (all under the same structural_retest directory) |
| DOC | `docs/reviews/PR16-gate2-infrastructure-20261027.md` |

Trace: original task and pinned bytes -> permitted explicit reference splices ->
complete exported bytes -> original behavior. Preregistered conditions -> host
configuration parity and external approval -> broker permissions/budgets -> real
MCP transactional runtime -> SAVE/export/authoritative replay -> private evaluation.
The evaluator never edits runtime/DB target state. Administrative SQL only creates
fresh DBs; target operations use MCP. Native replace-all semantics are confined to
A's five files. No new dependency or production API was introduced.

## Required category coverage

### ARCH — Architecture and contracts

Coverage: complete for experiment delta; read AGENTS, orchestration/testing skills,
current MCP/EOL/replay contracts and prior review. The host owns model behavior and
permissions; production runtime owns deterministic commits/replay. P1: none newly
identified. P2: all-arm preflight issue fixed under G3-1. P3: none identified.
Verification: broker, pin, host, isolation and live MCP tests. Gap: actual external
host behavior. Verdict: offline boundaries ready for independent review.

### DOC — Documentation and change records

Coverage: complete for revised operator plan and manifest claims. P1: none identified.
P2: none identified. P3: none identified. Verification: commands exercised, current
limits and external gaps reconciled with code; historical reports left untouched.
Verdict: no remaining finding within reviewed documentation scope.

### SKILL — Skills and agent instructions

Coverage: applicable existing instructions read; no skill changes. P1/P2/P3: not
assessed as a skill revision; none was requested. Verification: repository and user
scope followed. Verdict: not applicable to skill changes; no independent skill audit.

### MCP — MCP schemas and public API

Coverage: controller interaction with unchanged real schemas/tools inspected.
P1: none identified in integration scope. P2: none identified. P3: none identified.
Verification: real stdio tools/list/call, schema digest, strict C, read/init/write/
SAVE/export/history/replay. Gap: owner host's actual Gemini tool binding. Verdict:
existing public API preserved; controller integration verified offline/local.

### RUN — Core runtime, parsing and validation

Coverage: no implementation changes; prior A-F review carried forward. P1/P2/P3:
not assessed as new runtime changes. Verification: complete unit regression and
integration suites; no production delta. Verdict: outside this targeted re-review;
no claim to replace the previous independent production review.

### SVC — Services, orchestration and audit

Coverage: complete for experiment broker orchestration; production services unchanged.
P1: none newly identified. P2: none unresolved in scope. P3: none identified.
Verification: real rejected/accepted attempts, explicit response loss after commit,
same-key retry with no duplicate transaction, lineage and ledger membership.
Gap: external host cancellation/usage enforcement. Verdict: offline controller ready.

### DB — Database, migrations, replay and concurrency

Coverage: disposable initialization and controller use of existing replay inspected;
no migration/replay/concurrency redesign. P1: none identified in changed scope.
P2: none identified. P3: none identified. Verification: new DBs, canonical version-zero
hash/EOL checks, existing migration cycle/full regression, all four replay components,
C observation markers and authoritative replay. Rejected attempts have request/
diagnostic evidence; accepted scope links are verified by existing replay. Verdict:
integration verified; production independent review retained.

### SCRIPT — Scripts, evaluation and tooling

Coverage: complete for 14 experiment files. P1: G2-1 dependency implemented.
P2: G2-1 import gate and G3-1 global-binding issue fixed. P3: LF pin stability fixed.
Verification: both oracles, negative corruption cases, synthetic lifecycle/failures,
real MCP probes, source pins. Gaps: exact external host and internal component timing.
Verdict: ready for independent infrastructure review, not execution approval.

### TEST — Tests and CI

Coverage: new tests inspected and executed; existing suites executed. P1: none identified.
P2: no unresolved test finding. The C probe initially omitted the hash guard and was
corrected to supply both required guards; rerun passed. P3: none identified.
Verification: local counts/commands below. Final CI head and merge evidence belongs
in the PR completion comment. Verdict: local verification passed; independent recheck
and final CI confirmation required before any Gate 2 decision.

### DEP — Dependencies, packaging and configuration

Coverage: no dependencies added; existing lockfiles/npm pin unchanged; new execution
source LF attributes and example config inspected. P1: none identified. P2: none
identified. P3: checkout pin stability fixed. Verification: local hashes plus CI Linux
hash checks in unit suite. Gap: actual owner host installation. Verdict: no remaining
offline packaging/configuration finding within scope.

## Verification record

Windows/Python 3.11.9, Node 22.19.0, local Docker PostgreSQL 16.3, pinned Python/npm
dependencies. Full integration used `patchdiff_pr16_gate2_validation`, isolated from
prior test databases. Controller probes used additional fresh `retest_<uuid>` DBs.
No two test suites wrote target tables in the same database concurrently.

| Command | Observed result |
| --- | --- |
| `python -m pytest backend/tests/unit -q` | 909 passed, 0 failed/skipped, 99.524 s |
| `python -m pytest backend/tests/integration -q` | 455 passed, 0 failed/skipped, 228.032 s |
| `python -m alembic -c backend/app/migrations/alembic.ini upgrade head`, `downgrade -1`, `upgrade head` | Live cycle passed; full suite also covers populated migration cases |
| `python evaluation/offline_eval.py` | Verdict equivalence and content/hash oracles OK; only existing named delimiter exception |
| `python evaluation/structural_retest/prepare.py --check-inputs` | Exit 0; immutable inputs valid; Gate 2 closed |
| `python evaluation/structural_retest/controller.py --check-inputs` | Exit 0; source pins valid; 0 model calls |
| `controller.py --preflight-offline --config evaluation/structural_retest/host_config.example.json` | Exit 2 (expected); real tools/list discovery, unresolved host blocked, 0 model calls |
| `controller.py --dry-run-synthetic --destination <new-private-directory>` | Exit 0; ABC/BCA/CAB, 9 scheduled/archived, 6 independent real DBs, 0 measured model calls, comparative_results=false |
| `full_byte_oracle.py --generate-reference <hidden-directory>` then `evaluate.py --study primary --workspace <hidden-directory>` | Complete bytes pass, original behavior 20/20, no evaluator files in agent staging |
| Four `test_retest_*.py` unit files | 59 passed after final LF/pin cleanup |
| `git diff --check` / staged check | Passed after normalizing only new reference JSON/preflight EOF |

The final two source changes after the full-suite run were all-arm binding preflight
(focused regression passed) and byte-only LF/EOF cleanup with refreshed source pins.
Final full-tree CI evidence is recorded in the PR comment. Local synthetic dry-run
was repeated after final pin cleanup. No experimental output was used to adjust gold.
Known pre-existing FastAPI/httpx and Alembic path-separator deprecation warnings remain.

Local raw evidence is outside the checkout in the task workspace's
`pr16-evidence/gate2-20261027/`: JUnit files, hidden gold and per-run synthetic
evidence. They are operator/evaluator evidence, never a measured-agent mount.
The repository tests reproduce the assertions; no synthetic result is a model result.

## Frozen reference evidence

Raw manifest SHA-256: `b31848bbe70f21e0b6267153fa23b64be23f6f295bb5c92e733c5a2fe77af41a`.
Hidden reference-manifest SHA-256: `d43bdf7a9586bec87e47961035938e63ef9f3504f3c1a33a7ebab1e1c0886ef6`.

| Expected file | Bytes | SHA-256 |
| --- | ---: | --- |
| matrix_kernel.py | 24312 | `36dba6340c0d47abcf6bbdc5e34788b8f800bbf0417254c7f791c40a926ab8f7` |
| schema_defs.py | 13498 | `da3e5504f40a5cb0d4da5638fb986e4c4c23af5185aa481d9737838fce3b9c4d` |
| validator_engine.py | 21847 | `90871b4658e10e960585abf05c27031179f7aab16b77d9e97a9a69ed604b1484` |
| routing_manifest.json | 6582 | `84ce22315b1665e9308ccad447267c64ba04c4c660ee66a2be2f4ce14612306e` |
| MIGRATION_RUNBOOK.md | 10104 | `95b08e130e92c0aeeada6d92518e48509f5dd131d4ff96cd6b51d5d0de3f5fbb` |

## Remaining Gate 2 checklist

- Independent review/recheck of this implementation and final commit/manifest/CI.
- Owner supplies real Gemini bridge and provider-backed exact model ID/effective
  High, host/build, decoding/defaults, context/output limits and timestamp for A/B/C.
- Verify actual native executable/semantics, MCP schemas, permissions and negative
  sandbox probes. Host must prevent direct filesystem/network/inherited tool access.
- Prove actual usage and hard total-token reservation/cancellation, no automatic
  transport retries, fresh contexts and enforced per-arm permissions. Missing proof
  blocks execution; no model substitute or estimated usage is allowed.
- Reviewer accepts explicitly missing SQL/internal Waymark timing or requests an
  independent instrumentation amendment. Round-trip metrics are already captured.
- External PR #16 review approval binds exact commit, raw manifest and canonical
  host evidence; owner supplies its receipt and separately invokes execution later.
- Supplemental remains separate and independently gated. Gate 2 stays CLOSED here.
