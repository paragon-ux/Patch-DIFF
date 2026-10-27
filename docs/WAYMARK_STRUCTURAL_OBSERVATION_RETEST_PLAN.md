# Native vs. Patch-DIFF three-arm replication preregistration

Gate 2 is CLOSED. Preparation and deterministic tests are authorized. No measured
agents, comparative study, performance conclusions, merge, or self-approval are
authorized. The independent reviewer must approve an exact remediation commit
and a complete manifest before execution.

## Three separate studies

1. **Primary replication:** the original native-vs-Patch-DIFF subagent workflow,
   extended with a Waymark-backed third arm. Preserve the original task prompt,
   source bytes, task sequence and independent oracle. Authenticate them before
   execution. No substitute task or reconstructed gold label is accepted.
2. **Supplemental structural benchmark:** **45 edit targets, 20 scopes, five source
   files**: three Python modules, one JSON configuration and one Markdown runbook.
   Exact original fixtures, simulation harness, external verifier and expanded
   original edit specifications from `Editing-Toolbench/10-26-26` are hash-pinned in
   `evaluation/structural_retest/manifest.json`. The old harness is simulation
   evidence, never a live Patch-DIFF runner. TS/JS cases require a separate study.
3. **Transactional stress suite:** ordinary deterministic tests for ambiguity,
   stale observations, insertion boundaries/adjacency, atomic rejection, concurrent
   submissions, SAVE and authoritative replay. These are product correctness tests,
   not measured-model observations.

Report each study separately. Never combine denominators or success rates. For the
supplemental study report 45-target and five-file accuracy; 20 is a scope count.
The historical verifier has its own named checks, distinct from the 45 edit targets.

## Artifact availability and preparation

The manifest records SHA-256 hashes of exact bytes and labels fixtures, task
specifications and hidden evaluators. Input changes require a new manifest revision
and independent review. Keep evaluator/gold files outside agent mounts and context,
including repository searches.

The user identified `Editing-Toolbench/10-26-26` as the primary recovery source.
Its five current fixtures, 45-edit specification and standalone verifier have been
recovered and hash-pinned. Current source hashes agree with `benchmark_results.json`,
but all five conflict with the older fixture hashes in `REPORT.md`; line counts
and byte lengths differ too. These are content differences, not EOL normalization.
Both original evidence files are archived unchanged. The manifest lists every
conflict and references recovered primary candidate artifacts without promoting
them to authenticated original-run inputs. No measured-agent prompt, exact per-arm
tool instructions, original task sequence or model settings were found there.
Original-run provenance and independent full-byte collateral checks remain blockers.
Historical W1-W12 files are separate candidate evidence and are not substituted.

The supplied `10-27-26/Remediation-Prompt.md` repeats the continuity handoff and still
refers to a separate preceding prompt. The connected discussion exposes that
response as a content-reference marker, not its complete text. Record this gap.

Preparation commands (no model calls):

```powershell
python evaluation/structural_retest/prepare.py --check-inputs
python evaluation/structural_retest/prepare.py
python evaluation/structural_retest/prepare.py --stage supplemental --destination <new-directory>
```

The hash check returns zero. The default readiness check returns 2 while blockers
remain. Staging creates three byte-identical fixture directories and MCP
initialization JSONL requests for B/C. It never starts models, edits targets or
copies evaluators. Existing destinations are refused. Primary staging fails until
its authenticated originals are available.

Install `requirements.lock`, then `pip install --no-deps -e .` and
`npm --prefix integrations/waymark ci`. Pin Python 3.11, Node 22, PostgreSQL 16.3,
migration `20261026_0004` and `waymark-engine@4.1.0`. Record exact runtime/OS/host
builds and repository/manifest hashes. B/C need independent disposable databases,
migrations and real MCP `patchdiff_initialize_target` calls returning fresh target
IDs at version 0. Capture initial hashes, canonical text and upload EOL metadata.

## Frozen model and allowed tools

Every measured arm uses **Gemini 3.8 Flash High**. Sol 6.1 Extra High is the
implementation role; engineering costs are excluded from measured runs. Never
use `Model="inherit"` without verifying the effective setting. No silent model,
effort, provider, host or tool substitution is allowed.

| Arm | Reads and discovery | Editing and final verification | Configuration |
| --- | --- | --- | --- |
| A | Native file read/search | Native edits; external final-state oracle | No Patch-DIFF |
| B | Patch-DIFF read/search | Real unobserved MCP transactions; SAVE/export/replay | Strict mode off |
| C | Same reads plus `patchdiff_observe_scope` | Real observed MCP transactions; SAVE/export/replay | Strict mode on |

B/C cannot directly edit files or use Python string-slicing simulation. The
external evaluator is read-only and cannot repair outputs. C cannot bypass scope
checks. Observed insertions must be strictly interior with both nonempty adjacent
guards inside the sequential scope; either boundary rejects. Record exact allowed
tool names, permissions and host/tool differences as remaining confounds.

The exact provider model identifier, effective High setting, host build, decoding
settings and output/context limits are unverified. This chat's subagent catalog
does not offer the requested Gemini model. Unknown fields stay null in the
manifest and block Gate 2; availability elsewhere requires evidence before approval.

## Paired conditions, budgets and isolation

After original recovery, freeze identical task text and original step order across
A/B/C. Only tool-use instructions may differ; exact per-arm prompt hashes require
review. No arm receives hidden labels, solved examples, earlier-arm traces or extra
hints. Use three fresh replicates per task/arm with balanced orders ABC, BCA, CAB.
No adaptive stopping, cherry-picking, post-result tuning or task rewriting.

Preregistered per-task budgets for every arm: three editing attempts, 600 seconds,
16,000 actual model tokens, 30-second tool timeouts and zero automatic transport
retries. Every failed call/retry/rejection counts. Lost-response recovery consumes
an explicit retry; B/C resend identical arguments and idempotency key. No hidden
harness repair. Reconcile any conflict with original conditions before approval.

Use fresh contexts and independently initialized state for each task/replicate/arm.
Preserve intentional multi-step task dependencies and original interference timing.
Pin interference/lost-response controllers independently of agents. Verify seed and
temperature support; when unsupported record that fact and use identical verified
provider defaults. Record host configuration and tool permissions before execution.

## Metrics, independent evaluation and reporting

Capture actual provider input/output/cached/reasoning token counts, tool count,
exact argument/result UTF-8 bytes, attempts, retries, rejections, timeouts, errors
and failures. Explicitly flag unavailable token fields; never estimate from chars.
Capture wall-clock start/end and separate planning/tool time, cold startup, warm
discovery, initialization and database/migration overhead from measured editing.

B/C must retain real JSON-RPC traces, target IDs, accepted/rejected attempt IDs,
ledger facts and C's authoritative one-to-one observation links. Require SAVE,
export (`original_eol` when restoring upload bytes), replay success and all four
materialized-state checks for every target. Synthetic receipts do not count.

Evaluate each arm externally with the hidden original oracle, full-content equality
and collateral-change checks. The recovered supplemental behavioral verifier may
miss unrelated byte edits. An independently approved full-byte oracle remains a
supplemental readiness blocker; its checks do not authenticate primary correctness.
Report all paired per-task results and failures, then study-specific aggregates
with denominators and replicate variation. Missing artifacts, telemetry, model
settings or exhausted budgets must remain visible, never silently excluded.

## Gate 2 checklist

- Independent re-review of the exact remediation commit and its CI evidence.
- Authenticated original primary prompt, fixtures, oracle, task sequence and hashes.
- Reviewed exact per-arm prompts, hidden-oracle isolation, fresh-state setup and
  genuine MCP execution harness (the preparation script is not that harness).
- Verified Gemini 3.8 Flash High provider/host settings and identical budgets.
- Full-byte collateral oracle and telemetry bindings, or explicit independently
  approved supplemental limitations.
- Explicit independent approval. This document and preparation script grant none.
