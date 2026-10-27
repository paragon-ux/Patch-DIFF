# Native vs. Patch-DIFF primary replication preregistration

Gate 2 remains **CLOSED**. This revision supplies deterministic infrastructure for
independent review. The owner conducts Gemini sessions only after implementation
review, external host verification and explicit Gate 2 authorization. Sol's engineering
work is excluded from measured costs. No live or alternative model, measured arm,
merge or self-approval is authorized by this document.

## Separate studies and immutable inputs

The later structural batch remediation has its own deterministic capability
check, `evaluation/structural_batch/verify.py`, and [contract](STRUCTURAL_BATCH_EDITING.md).
It reuses authenticated original source/task/oracle bytes and declarative
exploratory C operations, issues five observation bundles and five atomic editing
submissions, then SAVE/replay per file. It invokes no model, does not modify this
frozen controller/manifest or approve Gate 2, and makes no comparative latency or
cost claim. Its outputs and request/response evidence live separately under
`evaluation/structural_batch/`. A new direct three-arm functionality test still
requires independent product review followed by owner authorization.

When running the older frozen controller for compatibility checks, its trusted
operator must set `PATCHDIFF_MCP_PROFILE=full` before launch. It retains its
original bytes and host-owned filters; the new service profiles are tested
separately through actual external MCP advertisement and dispatch.

The **primary** replication is the recovered original **21-edit-labeled, five-file
task**, extended with observed Arm C. Its exact TASK.md, five fixtures, setup,
verifier, old A/B prompts and provenance remain unchanged and SHA-256 pinned.
Source hashes match the original scratch target manifest. Historical B-specific
hints and UUIDs are hidden archival evidence. All arms receive identical TASK.md;
only the three pinned tool instruction files differ. One complete five-file task
uses one fresh context and budget.

The **supplemental** study has 45 edit targets, 20 scopes and five files. Its
historical REPORT.md hash table was stale; the primary scratch manifest authenticates
the preserved source bytes. It remains independently gated, including its missing
historical measured prompt/host binding. The primary controller never dispatches it.
The **stress suite** is ordinary transactional product testing. Never combine these
studies' denominators, accuracy measures or results.

`manifest.json` pins inputs, prompts, controller sources, host interface and hidden
reference hashes. Original bytes are protected by .gitattributes. `freeze.py` is
an engineering-only pin refresh: changes invalidate approval. Never refresh pins
to accept changed inputs or tolerance after seeing experimental outcomes.

## Complete-byte oracle and evaluator isolation

`primary/evaluator/full_byte_oracle.py` verifies every raw source hash and the
original task hash before reference construction. Explicit byte splices use original
Python AST symbol boundaries, unique JSON tenant identities and Markdown anchors.
Overlapping SYNC starts are enumerated advancing one byte; the second is selected
explicitly. Original-offset splices reject overlap and preserve every other byte.
No serializer, formatter or diff alignment constructs gold.

One representation is frozen: task literals with original surrounding indentation
and EOL. No post-result tolerance is permitted. The hidden `reference_hashes.json`
records expected complete-file hashes and lengths. Both exact-byte equality and
the original 20 behavioral checks must pass. The behavioral verifier imports Python;
it runs only after byte equality and with bytecode writing disabled. Mismatch reports
include filename, first differing byte, lengths/hashes and bounded hex context.
Extra, missing, renamed and nonregular entries fail.

Generate gold only in a hidden evaluator directory. Never mount the repository,
parent run directory, oracle or reference manifest in a measured context.
`prepare.py --stage` is an archival preparation utility, not the measured sandbox.
The controller gives A only five target files; B/C receive no native target files.
Prompts and fresh target mappings are supplied through the broker. The underlying
host must deny direct filesystem/network access and inherited tools/contexts.
Path, target and observation checks provide additional broker enforcement.

## Controller lifecycle and real tool routes

```text
PREPARED -> PREFLIGHT_VERIFIED -> INITIALIZED -> AGENT_RUNNING
 -> AGENT_FINISHED_OR_BUDGET_EXHAUSTED -> SAVE_AND_EXPORT
 -> REPLAY_VALIDATION -> HIDDEN_ORACLE_EVALUATION -> EVIDENCE_ARCHIVED
```

Failures retain the exact stage and terminal failure archive. Agent failures and
budget exhaustion still proceed to export/replay/evaluation where possible. No
automatic repair or model rerun occurs. A schedule is written before the first arm;
every scheduled run gets an append-only result, including failed preflight. Process
interruption retains the plan and partial evidence, which fails completeness checks.
Interrupted studies are not automatically resumed or rerun.

Each live scheduled run owns one new bridge process. Before opening its single
fresh context, the controller obtains a new `host/describe`, validates every frozen
host field against approved evidence, and verifies native/MCP bindings. Startup
and attestation overhead are recorded separately from the unchanged task budget.
The context is closed/cancelled and the process reaped before evidence archival
and the next process starts. Timeout/disconnect failures remain primary; bounded
cleanup errors are secondary evidence. The failed task is never retried.

A bridge startup, reattestation or unreaped-process failure stops further live
execution. The failed preflight is archived as `blocked_by_host_preflight`;
remaining schedule rows are `not_started` with explicit blocking reasons, no
fabricated task/oracle outcomes and no model invocations. The study returns failure
requiring operator review. In-process synthetic tests may still reuse fake hosts;
real subprocess fixtures additionally verify cross-run failure isolation.

| Arm | Broker allowlist | Mode |
| --- | --- | --- |
| A | `run_command` restricted to `rtk read <one confined file>`; `edit_file(Path, Target, Replacement)` replaces every exact occurrence | No Patch-DIFF |
| B | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_edits`, `patchdiff_save`, `patchdiff_replay` | Strict observation off |
| C | `patchdiff_observe_scope`, `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay` | Strict observation on |

Unlisted requests are rejected and recorded before dispatch. A cannot run shell
expressions/scripts or inspect arbitrary paths. B cannot submit observed operations;
C cannot use older writes. Target IDs must belong to this arm/context. C submission
observations must have been acquired through this context's broker. Actual native
executable path/hash/version and MCP schemas must match reviewed host bindings.
Prompts and local permission booleans cannot establish underlying host isolation.

Each B/C arm/replicate gets a new randomly named PostgreSQL database migrated to
head and a real stdio MCP child. Only administrative DB creation uses SQL; target
initialization, edits, export and audit use real MCP. Before opening a context,
verify five fresh UUIDs at version zero, canonical LF content/hash and full original
EOL metadata. Historical IDs are never reused. Context IDs must be fresh across
all nine runs. Databases are retained, with names recorded for explicit owner
cleanup; the controller never automatically deletes them.

After closing the host context, guarded SAVE and `original_eol` export run for
every B/C target. The controller verifies export hashes, replay success and all
four materialized-state checks. It pages accepted/rejected attempts including
transaction content and previous-cycle ledger facts, checks transaction hashes
and accepted-log/ledger membership. C accepted logs need observation markers;
authoritative replay validates their one-to-one persisted scope links. Rejected
attempts retain request/diagnostic provenance and do not acquire accepted links.
Final oracle/evidence results are never sent to a measured context.

## Host interface and unresolved external verification

Every future arm uses **Gemini 3.8 Flash High**, with identical exact provider ID,
verified effective High, provider, host build, decoding and context/output limits.
No `inherit`, display-name guess or substitution is accepted.

`host_adapter.py` defines `patchdiff-retest-host/1`. The owner supplies a trusted
JSON-lines bridge implementing `host/describe`, `host/open`, `host/turn`, `host/close`.
This is an adapter interface, **not a supplied Gemini connector**. Real connectivity,
permissions, native bindings and actual provider usage remain unverified.

The bridge must report actual evidence for `provider`, `exact_provider_model_id`,
`effective_reasoning_setting`, `host_name`, `host_version`, `decoding_settings`,
`context_limit`, `output_limit`, `tool_permissions`, `model_configuration_timestamp`
for every arm. Preserve provider-response hashes, host-build/decoding evidence and
negative permission-probe hashes privately. A typed name or `verified: true` alone
is not verification; the owner and independent reviewer must inspect original proof.

The host must enforce fresh contexts, broker-only tools, no direct filesystem or
network, no inherited/other-arm/evaluator access, cancellation and zero transport
retries. `host/open` acknowledges fresh context and applied permissions. Each turn
returns provider/request ID, effective model/High, synthetic=false and actual usage.
Tools route through the controller and results return only to that context.

Actual input includes cached tokens; output includes reasoning. The host must enforce
the remaining **total** token allowance through hard reservation or cancellation.
A completion-only cap is insufficient. Current real host support is unresolved;
a provider without reliable actual input/output telemetry is blocked. No alternative
token estimator or exception is implemented or approved.

`host_config.example.json` has unresolved placeholders and execution disabled.
Do not put credentials in configuration or evidence. Supply the administrative DB
URL via `PATCHDIFF_RETEST_ADMIN_URL`; provider credentials stay in the trusted bridge.
The owner must implement/verify the bridge, actual native tool semantics, sandbox
negative probes, provider usage and hard-budget support before Gate 2 approval.

## Frozen budgets and append-only telemetry

Three replicates use balanced orders **ABC, BCA, CAB**. Each complete task permits
**600 seconds, 16,000 actual model tokens, 96 agent tool calls, 30 seconds per tool,
two rejected/lost-response editing retries, zero automatic transport retries**.
Setup/context creation is recorded separately from the task timer. No adaptive
stopping, cherry-picking, prompt tuning or omitted failures is permitted.

Calls are checked before dispatch; unauthorized requests count. Deadlines/timeouts
cancel in-flight work. Tokens use input+output totals, never character estimates
or double-counted breakdowns. Missing input/output blocks; cached/reasoning fields
can be unavailable only with explicit missing flags. A subsequent edit on a target
after rejection or loss consumes a retry regardless of a model's retry label.
Successful distinct edits are initial attempts. B/C rejection recovery needs parent
log and incremented attempt; lost-response recovery requires an explicit identical
arguments/same-key retry. Each broker invocation requires a new call ID.

`telemetry.py` writes append-only JSONL with sequence/hash linkage, UTC timestamps,
frozen config, provider metadata, actual usage/missing flags, tool arguments/results,
canonical broker UTF-8 sizes/hashes, starts/ends/durations, attempts/request keys,
outcomes/retries, initialization, cold startup, warm calls, SAVE/export/replay,
hidden oracle and artifact hashes. Real MCP frames also record exact wire sizes
and hashes. Sensitive keys, authorization values and credential URLs are redacted.

Native/MCP initialization/transaction and Waymark discovery **round-trip** times
are observable. Separate SQL execution and internal Waymark child timing are not
exposed by the public MCP contract and are explicitly flagged unavailable. Do not
relabel round trips as component CPU/DB times. Independent review must accept that
limitation or request a separately scoped protocol/instrumentation amendment.

All failures remain in the nine-run denominator. Per-run events/results/exports,
`runs.jsonl` and `summary.json` preserve unsuccessful outcomes. Chain verification
requires a terminal archive event. Synthetic usage is labeled synthetic and has
no experimental interpretation.

## Owner sequence after independent implementation review

1. Fetch the independently reviewed clean commit; record HEAD and raw manifest SHA.
2. Install pinned requirements/Python 3.11/Node 22/PostgreSQL 16.3, migration head
   and `waymark-engine@4.1.0`; verify all input/source pins.
3. Supply the real bridge and host configuration from actual provider/host evidence.
4. Run offline preflight and verify real `host/describe` evidence without task/model
   requests. Check the exact Gemini ID and effective High separately for A/B/C.
5. Verify native path/hash/version, MCP schema digest, negative permission probes,
   cancellation, actual usage and hard total-token support; archive private proof.
6. Obtain explicit independent Gate 2 approval bound to exact commit, raw manifest
   SHA and canonical host-evidence SHA. Supply its PR review permalink and digest.
7. Only then, the owner enables execution and deliberately uses the separate
   `--execute --config ... --approval ... --destination <new-private-directory>`.
   This schedules all three balanced replicates. Sol must never invoke it here.
8. Run hidden whole-byte and original behavioral oracles for every exported result
   (automatic in the controller); require both for task correctness.
9. Inspect histories, ledger, SAVE/export/replay, C authoritative links and telemetry;
   disclose missing evidence/host limitations without repairing any output.
10. Archive all runs, failures, exhausted budgets and partial/crashed evidence plus
    commit/manifest/prompt/host/approval/CI evidence. Keep gold private. Protocol
    changes or measured reruns require separate review.

Reviewer-authored JSON fenced block (placeholders are not approval):

```json
{
  "gate": "Gate 2",
  "decision": "approved",
  "study_id": "primary-original-21-five-file-v1",
  "commit": "<exact reviewed 40-character commit>",
  "manifest_sha256": "<SHA-256 of raw manifest.json>",
  "host_evidence_sha256": "<canonical compact UTF-8 JSON SHA-256 of host/describe>",
  "independent_review": true,
  "live_execution_authorized": true
}
```

The separate receipt contains `review_url` and `review_sha256`, the canonical JSON
digest of the full GitHub API review response. The controller resolves the PR #16
review afresh, checks submitted state, exact commit, bindings and digest. A local
`gate_2: approved` flag is insufficient. Reviewer independence/expertise remains
a human responsibility; GitHub identity alone cannot prove it. Any bound change
invalidates approval. This controller never manufactures an approval.

## Offline commands and evidence interpretation

```powershell
python evaluation/structural_retest/prepare.py --check-inputs
python evaluation/structural_retest/controller.py --check-inputs
python evaluation/structural_retest/controller.py --preflight-offline --config evaluation/structural_retest/host_config.example.json
python evaluation/structural_retest/controller.py --dry-run-synthetic --destination <new-private-directory>
python evaluation/structural_retest/primary/evaluator/full_byte_oracle.py --generate-reference <new-hidden-directory>
python evaluation/structural_retest/evaluate.py --study primary --workspace <hidden-reference-or-export-directory>
python -m pytest backend/tests/unit -q
python -m pytest backend/tests/integration -q
python evaluation/offline_eval.py
```

Input checks return zero for frozen bytes. Offline preflight uses real stdio
`tools/list` without a DB/model request; unresolved example host returns 2. The
synthetic dry-run uses a deterministic no-op host, independent real MCP databases
and zero model calls. Exit zero means all nine infrastructure records archived;
all no-op outputs intentionally fail correctness and remain in evidence. These
are not Gemini results. Focused real-MCP tests also cover rejection, committed
response loss, explicit idempotent retry, Waymark, strict mode, SAVE/export/replay
and original EOL.

Verified offline: authenticated inputs, reference/oracles, controller simulations
and local real-MCP tests (see exact-commit evidence report). Pending external:
actual Gemini model/High, host build, permissions, tool bindings and usage/hard
budget support. Not executed: any measured comparative session. Independent review,
host verification and explicit Gate 2 approval are still required.
