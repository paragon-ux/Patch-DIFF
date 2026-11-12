# PR #27 live swarm — Trial 1, wave 2 (DeepSeek) and publication

Wave 2 of trial 1 resumed the paused runtime, database, and original fixture
root. Three live DeepSeek worker agents with separate strict
`observed_workspace` MCP connections rediscovered the unpublished wave-1
working copy by path, contended on its single target version, recovered from
stale rejections, and reached version 6. The coordinator then published once
with SAVE and verified the file, digest, cycle, and database evidence.

Trial 1 is a **mixed-model handoff**: wave 1 used three Sol 6.1 Extra High
workers; wave 2 used the DeepSeek Harness model reported here as
`deepseek/deepseek-v4.1-flash-1017` (coordinator and all three workers).

## Environment

| Item | Value |
| --- | --- |
| Installed runtime commit | `52f19e213759e2664e3fa8f0c70f3930ca2a0ff6` |
| PostgreSQL | 16.3 container `patchdiff-init-verify`, resumed once with `docker.exe unpause` |
| Database and migration | `patchdiff_swarm_52f19e2`, `20261111_0007` |
| Fixture root (kept in place) | `/home/paragon-ux/patchdiff-external/workspace-init-verification/swarm-live.FEbQ59/trial-1` |
| File | `system_settings.py`, root identity `2096:20710` |
| Profile and modes | `observed_workspace`, strict observation, resident Waymark (`4.1.0`) |
| Advertised tools | exactly the seven expected names on every connection |

Each worker seat had its own MCP stdio process: the host launched one
`patchdiff-mcp` child per seat and each seat drove only its own connection
through a private bridge socket (connection IDs `w4`, `w5`, `w6`; the bridge
harness was removed after the run). The coordinator used separate connections
for pre-SAVE checks, the SAVE, and the post-SAVE reopen. Full call records,
arguments, and intervals are in
[pr27-trial-1-wave-2-calls.json](pr27-trial-1-wave-2-calls.json).

## Open barrier

All timestamps are UTC on 2026-11-11. The coordinator released the open
barrier at 22:36:30.660 after all three connections advertised the seven tools.

| Worker | Connection | Initialize interval | Receipt | Snapshot bundle | Scope observation |
| --- | --- | --- | --- | --- | --- |
| T1-W4 | `run/w4.sock` | 22:36:43.311, 68.74 ms | OK, `created:false`, v3 | `4bf08239-f792-4e73-bfc2-5f933d8f89e9` | `a89b5a56-f59f-4a24-9dd9-2371ba06a8bd` |
| T1-W5 | `run/w5.sock` | 22:36:38.203, 52.63 ms | OK, `created:false`, v3 | `18fc60e3-5d9a-4678-bbbc-ca2b8f14de1d` | `e2b979c8-ce2a-47d6-83ef-4f3127976e84` |
| T1-W6 | `run/w6.sock` | 22:36:41.877, 120.66 ms | OK, `created:false`, v3 | `92793bb1-c531-411b-8ea0-aee7336440fb` | `53419f29-7788-4f42-9922-adce004ef4d3` |

All three receipts named target `df0887b3-c6ca-4ad3-9279-1136f5afe26d`,
version 3, canonical hash
`0149f73a9b82d9408a78ee09d8cb0c2aaccb25294a0218e11f57e857f04a4e7e`, editing
cycle `7d75be39-878d-42f0-94aa-27d2aa3b7b0d`, and the original raw disk digest
`a233713f22ccab19a7473e84696f1fe94205a9aca04239ea3c52bf694c8dd6a1`. Each read
returned the wave-1 working copy (`setting_1`–`setting_3` = 201, 202, 203)
with `setting_4`–`setting_6` still at 104–106. The three snapshots agreed on
target, version, and hash; their bundle and observation IDs differed as
expected. Zero `workspace_busy` responses occurred.

## Commit barrier and recovery

The coordinator released the three first attempts together at 22:36:58. All
three carried the same version-3 guard.

| Request key | Guard | Interval | Outcome | Log ID |
| --- | --- | --- | --- | --- |
| `t1-w5-a1` | v3 | 22:37:04.066, 84.59 ms | **Accepted v4** | `72279a90-50be-4ebb-aae6-33110ab4331b` |
| `t1-w6-a1` | v3 | 22:37:08.035, 76.24 ms | `BUNDLE_VERSION_MISMATCH`, current v4 | `976b51f6-6d80-47c8-8de0-63068f75b83e` |
| `t1-w4-a1` | v3 | 22:37:08.738, 69.15 ms | `BUNDLE_VERSION_MISMATCH`, current v4 | `ac779d36-9866-4879-8eb7-0dbbb22ec2e7` |
| `t1-w6-a2` | v4, parent `976b51f6…` | 22:37:28.863, 95.91 ms | **Accepted v5** | `7e271dee-0700-4262-a300-62fd60a55bf6` |
| `t1-w4-a2` | v4, parent `ac779d36…` | 22:37:31.371, 29.52 ms | `BUNDLE_VERSION_MISMATCH`, current v5 | `127aad2a-068c-475e-8712-d28fe86d5bf9` |
| `t1-w4-a3` | v5, parent `127aad2a…` | 22:37:49.410, 80.40 ms | **Accepted v6** | `6cf030e8-9515-45f4-904d-f220d7e51916` |

Exactly one first-round acceptance and two stale rejections occurred, as
designed. Rejected workers re-observed their own scope, rebuilt the proposal
from current text, used a fresh key, and linked the rejection as
`parent_pdcp_log_id` with `attempt` 2 or 3. Re-observations were issued at
v4 (`d89cce8a…` for W4, `225211ad…` for W6) and v5 (`14025a78…` for W4). Each
observed scope still contained its original `return 10x` text and its
`observed_scope_hash` was unchanged, because intervening commits were outside
that scope.

Independent recomputation of the per-version hashes matches every receipt:

| Version | Canonical SHA-256 |
| --- | --- |
| 3 | `0149f73a9b82d9408a78ee09d8cb0c2aaccb25294a0218e11f57e857f04a4e7e` |
| 4 (setting_5) | `ef0e906311f23b64931286f0eeb6cb0d77b2bd9b67b1088d9db4a68ce3ba3110` |
| 5 (setting_6) | `563667c9c9ca03c8f49c78abbfbc9c4f8d7f7c0c20b15e48ada7b1b8af3b6f87` |
| 6 (setting_4) | `1d188dfc94c659b568211e599f0f1e64029bc7d8c86525781b484c820d5120fd` |

## Reopen barrier

Released at 22:38:00.701 after all three edits were accepted.

| Worker | Reopen interval | Receipt | Own result |
| --- | --- | --- | --- |
| T1-W4 | 22:38:05.826, 44.52 ms | same target, `created:false`, v6, disk `a233713f…` | `setting_4` = 204 |
| T1-W5 | 22:38:04.862, 30.01 ms | same target, `created:false`, v6, disk `a233713f…` | `setting_5` = 205 |
| T1-W6 | 22:38:05.779, 30.34 ms | same target, `created:false`, v6, disk `a233713f…` | `setting_6` = 206 |

All three reopens returned the original target ID, cycle
`7d75be39-878d-42f0-94aa-27d2aa3b7b0d`, version 6, canonical hash
`1d188dfc…`, and the original raw disk digest — the disk had not changed
before publication. Each read showed all six functions at 201–206. The three
worker connections then closed.

## Publication and verification

The coordinator opened and read through its own connection: v6, all six
functions 201–206. The SAVE with the verified guards and
`sync_workspace: true` succeeded on its second attempt; the first attempt was
rejected before publication, as recorded below.

| Attempt | Connection | Result |
| --- | --- | --- |
| 1 | `run/coord.sock` | `rejected`, `workspace_io_error`, “Workspace staging failed; no file was published.” |
| 2 | `run/coord2.sock` | `saved`, snapshot `f0091f05-e117-46d9-b4ba-97d3ef9531aa` |

Attempt 1 failed for environmental reasons: that coordinator process ran
inside the session's write sandbox, whose only writable bind mount was the
repository worktree, so creating the staging file in the fixture root was
denied before any publication. Disk bytes, checkpoint, version, and cycles
were verified unchanged before the retry. Attempt 2 ran on a connection with
write access to the fixture root and succeeded on the first call; no further
SAVE was issued.

SAVE outcome:

| Field | Value |
| --- | --- |
| Status / version | `saved`, version 6 |
| Snapshot | `f0091f05-e117-46d9-b4ba-97d3ef9531aa` |
| Cycles | closed `7d75be39-878d-42f0-94aa-27d2aa3b7b0d`, new `f13e7c33-edec-4770-8923-b3811f702619` |
| Publication | `installed`, `synced_path: system_settings.py`, `bytes_written: 197`, `content_eol: lf`, `durability: confirmed` |
| Receipt digest | `1d188dfc94c659b568211e599f0f1e64029bc7d8c86525781b484c820d5120fd` |

The file on disk is byte-identical to `expected.py` (197 bytes, LF only) with
SHA-256 `1d188dfc…`; the receipt digest and byte count match the exact disk
bytes. A fresh connection opened afterwards returned the same target,
`created:false`, version 6, canonical hash `1d188dfc…`, the published disk
digest, and the new active cycle `f13e7c33…`.

## Database evidence

Read-only PostgreSQL audit in
[pr27-trial-1-wave-2-audit.txt](pr27-trial-1-wave-2-audit.txt):

- 1 binding, 1 member, 1 target, 1 project for this root and path.
- 1 `initial_upload` snapshot (v0, `a233713f…`) and 1 `save_checkpoint`
  snapshot (v6, `1d188dfc…`).
- 2 editing cycles: cycle 0 closed by the SAVE, cycle 1 active.
- 6 accepted transactions with 6 manifest ledger rows; 6 rejected attempts.
- Target v6 hash equals the recomputed SHA-256 of `current_content`.
- Attempt rows 7–12 are wave 2 with the keys, log IDs, parents, and
  `regeneration_attempt` values above; rows 1–6 are wave 1.

Ledger facts are scope-local: every entry records `scope_start: 0`,
`scope_end: 31`, `scope_local_start: 21`, matching the identical 31-code-point
function scopes.

## Concurrency note

The host released each barrier to all three seats at once, and all three
first attempts used the identical version-3 guard. Because the host executes
the workers' agent turns sequentially, no two client call intervals overlapped
at the transport level (the machine-readable overlap list is empty), yet the
version contention was real: the two later version-3 submissions were logged
against the already-advanced version 4. Likewise both v4 retries were guarded
at v4; the second one was logged against v5. T1-W4 also noted, correctly, that
simultaneous releases mean a loser always has to burn a fresh observation and
key — that is the intended recovery path, and it terminated at attempt 3 of 5.

## Disposition

Wave 2 passed every check. Trial 1 now has six accepted transactions, six
ledger entries, one SAVE checkpoint, and a published file matching
`expected.py`. At this checkpoint, trials 2 and 3 had yet to start. See their
[completed results](../README.md#completed-trials-and-reporting).

Artifacts: [pr27-trial-1-wave-2-calls.json](pr27-trial-1-wave-2-calls.json)
(all 32 tool calls with intervals, guards, keys, log IDs, and full rejection
fields), [pr27-trial-1-wave-2-audit.txt](pr27-trial-1-wave-2-audit.txt) (raw
read-only PostgreSQL output), and
[pr27-trial-1-wave-2-publication.txt](pr27-trial-1-wave-2-publication.txt)
(byte, digest, and SAVE receipt comparison).
