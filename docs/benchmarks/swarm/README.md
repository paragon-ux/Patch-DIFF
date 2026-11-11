# Live swarm test handoff

[PR #27](https://github.com/paragon-ux/Patch-DIFF/pull/27) makes workspace initialization reuse the active PostgreSQL target. This test checks that independent agents opening one path share its unpublished edits, contend on the same version, and recover from stale snapshots. Workers use strict `observed_workspace` with individual MCP calls and manual barriers.

[Trial 1, wave 1 results](results/pr27-trial-1-wave-1.md) · [Read-only PostgreSQL audit](results/pr27-trial-1-wave-1-audit.txt)

## Resume trial 1 with DeepSeek

Wave 1 used three live Sol 6.1 Extra High workers. All three opened one target and committed their edits. Trial 1 is paused before wave 2 and before SAVE.

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

Resume the existing test container with `docker unpause patchdiff-init-verify` (use `docker.exe` if connecting to Windows Docker Desktop from WSL). Point the DeepSeek host's MCP connections at the installed PatchDIFF launcher and the same database on loopback port 55437. Set `PATCHDIFF_WORKSPACE_ROOT` to the original `trial-1` directory. Its directory identity is part of the binding, so keep that directory and fixture in place. Keep the existing database and installed runtime. Set `PATCHDIFF_MCP_PROFILE=observed_workspace`, `PATCHDIFF_STRICT_OBSERVATION_MODE=1`, and `PATCHDIFF_WAYMARK_MODE=resident`, with pinned Node and Waymark available. The host must support launching one separate MCP process per worker.

Give three workers only the relative path `system_settings.py`, their own assignment, and the phase instructions below. Keep the target ID and version-3 evidence in the coordinator's notes until each worker has opened the path independently.

| Worker | Scope | Exact replacement |
| --- | --- | --- |
| T1-W4 | `setting_4` | `return 104` → `return 204` |
| T1-W5 | `setting_5` | `return 105` → `return 205` |
| T1-W6 | `setting_6` | `return 106` → `return 206` |

## Manual worker phases

1. **Open.** Start three separate strict `observed_workspace` connections. Verify the seven advertised tools. Wait until all workers are ready, then release them to call `patchdiff_initialize_target` with the relative filename and `from_workspace: true`. Record request intervals and all receipts. Retry `workspace_busy` at most five times within 60 seconds. For trial 1's second wave, all three must receive the same existing target at version 3 with `created: false`. Use `patchdiff_read_target` to verify the first wave's three unpublished values.
2. **Observe and commit.** Each worker uses `patchdiff_observe_scopes` for its assigned function and reports the snapshot to the coordinator. Release commits after all three snapshots agree on target, version, and canonical hash. Each worker uses its own returned snapshot and observation ID with `patchdiff_commit_bundle`, one exact match replacement, and a unique request key such as `t1-w4-a1`. Expect one acceptance and two `BUNDLE_VERSION_MISMATCH` rejections.
3. **Retry.** For a definitive stale rejection, re-observe the function, build a fresh guarded proposal, use a new key, and link the rejected log as the parent. Allow at most five commit attempts per worker. If the response is lost, resend the identical proposal and key to recover its recorded outcome before preparing a new proposal.
4. **Reopen.** Once all three edits have committed, each worker opens the path again and reads its change. Require the original target, `created: false`, and version 6 for this wave. Confirm the disk digest is still the original one. Close worker sessions.
5. **Publish.** The coordinator opens and reads the same target. Verify all six expected values, then call `patchdiff_save` once with the verified version and hash and `sync_workspace: true`. Compare the exact file bytes against the run directory's `expected.py` and verify the SAVE receipt's raw disk SHA-256. A fresh open must return the same target at version 6 with the new cycle. If SAVE reports a partial outcome or the response is lost, inspect disk and checkpoint evidence before another call.

Use PatchDIFF for the workers' edits. Stop the affected trial if ordinary open reports external drift, a target ID differs, or disk bytes change before the coordinator publishes. Keep the evidence for diagnosis.

## Remaining trials and reporting

The existing `trial-2` and `trial-3` roots have baseline fixtures and have yet to be opened. After trial 1 passes, run two waves of three workers per root. Start each trial with the six baseline functions in `initial.py` from the run directory. The first wave changes functions 1–3 from 101–103 to 201–203. Require exactly one `created: true` receipt at version 0. Each first wave ends at version 3 with the disk baseline intact. Each second wave rediscovering the path must see the first wave's edits, change functions 4–6, and reach version 6 before the single coordinator SAVE.

The final LF fixture must match `expected.py`. Its SHA-256 is `1d188dfc94c659b568211e599f0f1e64029bc7d8c86525781b484c820d5120fd`. For each completed trial, use a read-only PostgreSQL transaction to verify one binding and target for the root/path, one `initial_upload` snapshot, six accepted edit transactions and ledger rows, and one `save_checkpoint` snapshot. Match the stale rejection IDs to the append-only attempt log.

Add each wave's evidence under `results/`. Record the runtime commit, host and actual model, root and database label, worker and connection IDs, request intervals, creation and reopen receipts, snapshot guards, request keys and log IDs, retries, and the SAVE outcome. Track the number of active workers and overlapping request intervals. Report Sol and DeepSeek results by wave and label trial 1 as a mixed-model handoff. The target workload is 18 worker turns across six waves, with three active workers per wave.
