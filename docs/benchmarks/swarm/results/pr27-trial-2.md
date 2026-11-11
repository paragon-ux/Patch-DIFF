# PR #27 live swarm — Trial 2

Trial 2 used the same paused-then-resumed runtime, database, and manual
barriers as trial 1, with three fresh live workers per wave, all on
`deepseek/deepseek-v4.1-flash-1017`. Wave 1 created the target and reached
version 3; wave 2 rediscovered it by path, contended on version 3, recovered
from stale snapshots, and reached version 6; the coordinator published once
with SAVE.

## Environment

| Item | Value |
| --- | --- |
| Installed runtime commit | `52f19e213759e2664e3fa8f0c70f3930ca2a0ff6` |
| PostgreSQL | 16.3 container `patchdiff-init-verify`, database `patchdiff_swarm_52f19e2`, revision `20261111_0007` |
| Fixture root | `/home/paragon-ux/patchdiff-external/workspace-init-verification/swarm-live.FEbQ59/trial-2` |
| Root identity | `2096:20713` |
| Target | `b79ea267-3176-49ca-9292-88ea9edc2c01` |
| Profile | `observed_workspace`, strict observation, resident Waymark 4.1.0 |
| Baseline disk SHA-256 | `a233713f22ccab19a7473e84696f1fe94205a9aca04239ea3c52bf694c8dd6a1` |

## Wave 1 — create and reach v3

Open receipts (coordinator released the barrier at 22:42:50Z; opens began 22:43:00Z):

| Worker | Initialize interval | `created` | Version | Snapshot bundle | Scope observation |
| --- | --- | --- | --- | --- | --- |
| T2-W1 | 22:43:00.894, 73.82 ms | **true** | 0 | `fe4ffca8-1f9f-42a2-8a47-f0b9de5fa437` | `bf0e6c04-63c9-4d0a-95bf-06fd6c7d637a` |
| T2-W2 | 22:43:01.322, 58.30 ms | false | 0 | `ccd111ab-f054-47d5-b7ae-15befb68b002` | `a454b24a-bb35-45f6-a234-a6c6bc5372c5` |
| T2-W3 | 22:43:03.132, 45.70 ms | false | 0 | `657e131b-ed00-4aa0-9a10-3d56732c8574` | `87ec1c1d-dd32-4d1f-af5b-ded268d7ac93` |

Exactly one `created:true` receipt, all three at version 0 with canonical hash
`a233713f…`, cycle `632e0dad-a622-480b-abe4-6247aa8b52a7`. Zero
`workspace_busy` responses.

| Key | Guard | Interval | Outcome | Log |
| --- | --- | --- | --- | --- |
| `t2-w2-a1` | v0 | 22:43:22.432, 218.65 ms | **Accepted v1** | `989a22c5-b137-4998-b0ec-796ce7464274` |
| `t2-w3-a1` | v1 | 22:43:22.806, 123.23 ms | **Accepted v2** | `3dda948d-9e05-4ae2-a047-7d5a5116835a` |
| `t2-w1-a1` | v2 | 22:43:23.527, 207.95 ms | **Accepted v3** | `6baa1eab-2881-40ae-a185-0f13c84f7aa6` |

**Deviation, recorded deliberately:** wave 1 produced no stale rejections.
The host-side driver re-observed the target immediately before each commit
attempt, so each worker's guard matched the version current at submit time
(v0, v1, v2). The commits are genuine and sequential, but this wave did not
exercise the stale-snapshot path. Wave 2 below pins the phase-1 snapshot for
attempt 1 and does exercise it.

Reopen barrier: all three returned the same target, `created:false`, version 3,
canonical hash `0149f73a…`, cycle `632e0dad…`, and the original disk digest
`a233713f…`.

## Wave 2 — rediscover, contend, reach v6

Open receipts (barrier released 22:43:59Z; fresh workers opened from 22:44:08Z):

| Worker | Initialize interval | `created` | Version | Snapshot bundle | Scope observation |
| --- | --- | --- | --- | --- | --- |
| T2-W4 | 22:44:08.434, 67.98 ms | false | 3 | `946d8db7-cf8c-4a4d-9899-2ca55d5fea31` | `816372c5-50a7-46c8-bcba-d61612f6840f` |
| T2-W5 | 22:44:09.499, 49.84 ms | false | 3 | `96275552-1e1f-4247-90b4-920a9b3271bf` | `a3ed3660-918c-4926-b8a7-69d028d987b9` |
| T2-W6 | 22:44:08.447 (busy), 22:44:21.618, 54.19 ms | false | 3 | `da2617bd-1e19-4ca1-b672-d33badaafa76` | `52ebcb57-56cf-4c6e-8050-58bb886f68b0` |

T2-W6's first open returned `workspace_busy` while T2-W4's open owned the
destination; the intervals overlapped by 7.7 ms. It retried once and succeeded.
All three snapshots agreed on target, version 3, and hash `0149f73a…`.

| Key | Guard | Interval | Outcome | Log |
| --- | --- | --- | --- | --- |
| `t2-w4-a1` | v3, pinned phase-1 snapshot | 22:44:48.541, 82.12 ms | **Accepted v4** | `db26b1b4-b6c9-433b-ba64-5e9e2c7b21bb` |
| `t2-w6-a1` | v3, pinned phase-1 snapshot | 22:44:51.429, 45.78 ms | `BUNDLE_VERSION_MISMATCH`, current v4 | `9a4ff429-161f-446e-bb64-ecf249d73832` |
| `t2-w6-a2` | v4, parent `9a4ff429…` | 22:44:51.525, 72.75 ms | **Accepted v5** | `512d15d5-8ab0-4aed-8f58-cce33a7654f2` |
| `t2-w5-a1` | v3, pinned phase-1 snapshot | 22:44:56.551, 43.97 ms | `BUNDLE_VERSION_MISMATCH`, current v5 | `5f97f41e-3409-4ec1-9ce5-524455e7c509` |
| `t2-w5-a2` | v5, parent `5f97f41e…` | 22:44:56.631, 97.86 ms | **Accepted v6** | `b14bc3ac-bf92-4aa0-8d29-de1622a7eaec` |

Version hashes: v4 `673693966e05c94b20fd643ac5e6a7d13d0d184c29d79f10c1b457dc70d4a9c9`,
v5 `b5874afd6eec6cd455b616b1baa9d99d2d8598d7499ead519b0476a80af5c4ad`,
v6 `1d188dfc94c659b568211e599f0f1e64029bc7d8c86525781b484c820d5120fd`.

Reopen barrier: all three returned the same target at `created:false`,
version 6, hash `1d188dfc…`, original disk digest, and cycle `632e0dad…`;
each read showed 201–206. Connections closed.

## Publication

Coordinator open/read confirmed v6 and 201–206, then one SAVE was issued on a
connection with write access to the fixture root:

| Field | Value |
| --- | --- |
| Status / version | `saved`, version 6 |
| Snapshot | `47da6fe7-5d5c-4255-a4f2-26251c4d12e7` |
| Cycles | closed `632e0dad-a622-480b-abe4-6247aa8b52a7`, new `958dbedb-37f4-464f-abe1-c0583ae1e504` |
| Publication | `installed`, 197 bytes, `content_eol: lf`, `durability: confirmed` |
| Receipt digest | `1d188dfc94c659b568211e599f0f1e64029bc7d8c86525781b484c820d5120fd` |

The disk file is byte-identical to `expected.py` and the receipt digest equals
the exact disk bytes. A fresh connection after SAVE returned the same target,
version 6, the published disk digest, and the new cycle `958dbedb…`.

## Database evidence

Read-only audit in [pr27-trial-2-audit.txt](pr27-trial-2-audit.txt):

- 1 binding/target for the root and path; 6 accepted transactions and 6 ledger
  rows; 2 rejected attempts (both wave 2, both linked as parents).
- 1 `initial_upload` snapshot (v0 `a233713f…`) and 1 `save_checkpoint` snapshot
  (v6 `1d188dfc…`); 2 cycles, 1 active.
- Target v6 hash equals the recomputed SHA-256 of `current_content`.

## Notes

- `worker_commit.py` temporarily lacked its `--outdir` CLI flag; the wave-2
  workers invoked it through a thin shim that injected the default and left the
  driver logic unchanged. The flag was fixed before trial 3.
- Wave 1 (above) did not exercise stale rejection because the driver
  re-observed before every attempt; wave 2 did, with two rejections and full
  parent lineage.

Artifacts: [pr27-trial-2-calls.json](pr27-trial-2-calls.json),
[pr27-trial-2-publication.txt](pr27-trial-2-publication.txt).
