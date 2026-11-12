# PR #27 live swarm evidence

These three completed trials used runtime `52f19e213759e2664e3fa8f0c70f3930ca2a0ff6`.
The recorded host handoff below describes the original test. Use a fresh
isolated database and fixture for a new run.

[PR #27](https://github.com/paragon-ux/Patch-DIFF/pull/27) makes workspace initialization reuse the active PostgreSQL target. This test checks that independent agents opening one path share its unpublished edits, contend on the same version, and recover from stale snapshots. Workers use strict `observed_workspace` with individual MCP calls and manual barriers.

[Trial 3 results and publication](results/pr27-trial-3.md) · [Trial 2 results and publication](results/pr27-trial-2.md)

[Trial 1, wave 2 results and publication](results/pr27-trial-1-wave-2.md) · [Wave 2 tool-call evidence](results/pr27-trial-1-wave-2-calls.json) · [Wave 2 read-only PostgreSQL audit](results/pr27-trial-1-wave-2-audit.txt)

[Trial 1, wave 1 results](results/pr27-trial-1-wave-1.md) · [Read-only PostgreSQL audit](results/pr27-trial-1-wave-1-audit.txt)
[Archived DeepSeek handoff and tool-call walkthrough](deepseek-handoff.md)

## Trial 1: wave 2 resumed with DeepSeek

Wave 1 used three live Sol 6.1 Extra High workers. All three opened one target and committed their edits. Wave 2 resumed the paused container, database, and fixture root with three live DeepSeek workers, reached version 6, and published once with SAVE. Trial 1 is complete and labelled a mixed-model handoff; see the [wave 2 results](results/pr27-trial-1-wave-2.md). The recorded values below are the pre-wave-2 resume state.

| State | Recorded value |
| --- | --- |
| Installed runtime commit | `52f19e213759e2664e3fa8f0c70f3930ca2a0ff6` |
| PostgreSQL database and revision | `patchdiff_swarm_52f19e2`, `20261111_0007` |
| File | `trial-1/system_settings.py` in the existing run directory |
| Active target and version | `df0887b3-c6ca-4ad3-9279-1136f5afe26d`, version 3 |
| Active editing cycle | `7d75be39-878d-42f0-94aa-27d2aa3b7b0d` |
| Canonical version 3 SHA-256 | `0149f73a9b82d9408a78ee09d8cb0c2aaccb25294a0218e11f57e857f04a4e7e` |
| Unpublished working values | `setting_1` through `setting_3` return 201, 202, and 203 |
| Raw disk SHA-256 | `a233713f22ccab19a7473e84696f1fe94205a9aca04239ea3c52bf694c8dd6a1` |

The original coordinator resumed the paused container and connected to the
same database on loopback port 55437. The runtime used the original `trial-1`
directory, strict `observed_workspace`, resident Waymark, and one MCP process
per worker.

Workers received the relative path `system_settings.py` and their own
assignments. The coordinator withheld the target ID and version-3 evidence
until each worker had opened the path independently.

| Worker | Scope | Exact replacement |
| --- | --- | --- |
| T1-W4 | `setting_4` | `return 104` → `return 204` |
| T1-W5 | `setting_5` | `return 105` → `return 205` |
| T1-W6 | `setting_6` | `return 106` → `return 206` |

## Original wave 2 protocol

1. **Open.** Start three separate strict `observed_workspace` connections. Verify the seven advertised tools. Wait until all workers are ready, then release them to call `patchdiff_initialize_target` with the relative filename and `from_workspace: true`. Record request intervals and all receipts. Retry `workspace_busy` at most five times within 60 seconds. For trial 1's second wave, all three must receive the same existing target at version 3 with `created: false`. Use `patchdiff_read_target` to verify the first wave's three unpublished values.
2. **Observe and commit.** Each worker uses `patchdiff_observe_scopes` for its assigned function and reports the snapshot to the coordinator. Release commits after all three snapshots agree on target, version, and canonical hash. Each worker uses its own returned snapshot and observation ID with `patchdiff_commit_bundle`, one exact match replacement, and a unique request key such as `t1-w4-a1`. Expect one acceptance and two `BUNDLE_VERSION_MISMATCH` rejections.
3. **Retry.** For a definitive stale rejection, re-observe the function, build a fresh guarded proposal, use a new key, and link the rejected log as the parent. Allow at most five commit attempts per worker. If the response is lost, resend the identical proposal and key to recover its recorded outcome before preparing a new proposal.
4. **Reopen.** Once all three edits have committed, each worker opens the path again and reads its change. Require the original target, `created: false`, and version 6 for this wave. Confirm the disk digest is still the original one. Close worker sessions.
5. **Publish.** The coordinator opens and reads the same target. Verify all six expected values, then call `patchdiff_save` once with the verified version and hash and `sync_workspace: true`. Compare the exact file bytes against the run directory's `expected.py` and verify the SAVE receipt's raw disk SHA-256. A fresh open must return the same target at version 6 with the new cycle. If SAVE reports a partial outcome or the response is lost, inspect disk and checkpoint evidence before another call.

Use PatchDIFF for the workers' edits. Stop the affected trial if ordinary open reports external drift, a target ID differs, or disk bytes change before the coordinator publishes. Keep the evidence for diagnosis.

## Completed trials and reporting

Trials 2 and 3 ran on 2026-11-11 with fresh DeepSeek workers in every wave. Each root opened once, reached version 3 in wave 1 with exactly one `created: true` receipt at version 0, rediscovered the unpublished target by path in wave 2, reached version 6, and published once with SAVE.

- [Trial 2](results/pr27-trial-2.md): wave 1 committed sequentially without stale rejections because the host driver re-observed before every attempt; wave 2 produced the expected two `BUNDLE_VERSION_MISMATCH` rejections with parent lineage. One genuine `workspace_busy` open retry occurred.
- [Trial 3](results/pr27-trial-3.md): both waves produced two stale rejections with parent lineage. A host-side bridge relaunch was required before wave 2 phase 1; no target or disk state changed.

At the end of the run, all three trial fixtures matched `expected.py` with SHA-256 `1d188dfc94c659b568211e599f0f1e64029bc7d8c86525781b484c820d5120fd`. Each trial's read-only audit verifies one binding and target for its root/path, one `initial_upload` snapshot, six accepted edit transactions and ledger rows, one `save_checkpoint` snapshot, and the rejected attempt IDs. Per-call evidence (intervals, guards, keys, log IDs, parents) is in `results/pr27-trial-2-calls.json` and `results/pr27-trial-3-calls.json`.
