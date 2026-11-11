# PR #27 live swarm — Trial 3

Trial 3 repeated the two-wave, three-worker protocol on the third fixture root
with fresh workers in every wave, all on
`deepseek/deepseek-v4.1-flash-1017`. Unlike trial 2, both waves exercised the
stale-snapshot path: wave 1 produced two `BUNDLE_VERSION_MISMATCH` rejections
before reaching version 3, and wave 2 produced two more before version 6. The
coordinator published once with SAVE.

## Environment

| Item | Value |
| --- | --- |
| Installed runtime commit | `52f19e213759e2664e3fa8f0c70f3930ca2a0ff6` |
| PostgreSQL | 16.3 container `patchdiff-init-verify`, database `patchdiff_swarm_52f19e2`, revision `20261111_0007` |
| Fixture root | `/home/paragon-ux/patchdiff-external/workspace-init-verification/swarm-live.FEbQ59/trial-3` |
| Root identity | `2096:20714` |
| Target | `05cb629b-7099-45b7-ba02-69f31570fb72` |
| Profile | `observed_workspace`, strict observation, resident Waymark 4.1.0 |
| Baseline disk SHA-256 | `a233713f22ccab19a7473e84696f1fe94205a9aca04239ea3c52bf694c8dd6a1` |

## Wave 1 — create and reach v3

| Worker | Initialize interval | `created` | Version | Snapshot bundle | Scope observation |
| --- | --- | --- | --- | --- | --- |
| T3-W1 | 22:46:41.076, 76.29 ms | false | 0 | `05a458ed-1b9f-4aa8-bff5-1cb51f703a19` | `2671a579-6929-4aaf-92e3-011a60473aed` |
| T3-W2 | 22:46:40.912, 155.02 ms | **true** | 0 | `8a835c18-da5c-4896-bdfe-3131afb16352` | `82b1ca1f-87f0-41cd-a80f-c11847726622` |
| T3-W3 | 22:46:42.200, 46.95 ms | false | 0 | `df42eae0-bebd-4419-9915-838e7da94709` | `921502d7-babe-40ab-9f45-b782b4d9e3d6` |

Exactly one `created:true` (T3-W2), all three at version 0, hash `a233713f…`,
cycle `ff8a71b2-d1ba-4749-8b53-ac913dc3cb8e`, zero `workspace_busy`.

All three attempt-1 commits were pinned to their own phase-1 v0 snapshots:

| Key | Guard | Interval | Outcome | Log |
| --- | --- | --- | --- | --- |
| `t3-w3-a1` | v0 | 22:47:06.114, 137.31 ms | **Accepted v1** | `18c6a3ea-6430-4c4a-86e2-2227323352cd` |
| `t3-w1-a1` | v0 | 22:47:07.792, 78.73 ms | `BUNDLE_VERSION_MISMATCH`, current v1 | `f2fb4b7b-3523-4b3f-9065-75c3ebb80f42` |
| `t3-w1-a2` | v1, parent `f2fb4b7b…` | 22:47:07.933, 112.53 ms | **Accepted v2** | `54ebf23e-f00c-4361-bdf6-e0db182bd525` |
| `t3-w2-a1` | v0 | 22:47:09.047, 59.76 ms | `BUNDLE_VERSION_MISMATCH`, current v2 | `800ad87d-0af4-4df7-9b1f-bbb2dfa9ba95` |
| `t3-w2-a2` | v2, parent `800ad87d…` | 22:47:09.146, 109.98 ms | **Accepted v3** | `988a68b3-adb2-4c6d-a3aa-dfdaf02c1587` |

One acceptance and two stale rejections on first attempts, each recovered by
re-observing, rebuilding from current text, a fresh key, and parent lineage.
Reopen barrier: all three same target, `created:false`, v3, hash `0149f73a…`,
original disk digest.

## Wave 2 — rediscover, contend, reach v6

Wave 2 used fresh workers `t3w4`, `t3w5`, `t3w6`. Before their first calls the
host's detached bridge processes exited; all three workers reported
`ECONNREFUSED`. The coordinator relaunched the three bridges as persistent
processes (same seats, same root, new `patchdiff-mcp` children). No target,
log, or disk state changed while the bridges were down, and the workers
completed phase 1 after the relaunch. This is recorded as a harness incident,
not a PatchDIFF outcome.

| Worker | Initialize interval | `created` | Version | Snapshot bundle | Scope observation |
| --- | --- | --- | --- | --- | --- |
| T3-W4 | 22:49:02.004, 88.20 ms | false | 3 | `2ef06745-72d8-4d72-9da7-72c57d28d8ad` | `b2477b57-8c59-43f3-a731-4dcced008dcc` |
| T3-W5 | 22:49:02.735, 76.62 ms | false | 3 | `b948ee89-6cdc-460b-aeea-8a9460236d1e` | `4ca90134-bfc5-451f-9870-bb23abb6ceee` |
| T3-W6 | 22:49:02.471, 68.51 ms | false | 3 | `486e642c-8f4e-47ad-b564-6ae0db7fa669` | `c52518c9-ce55-465c-9551-18f7c4738555` |

| Key | Guard | Interval | Outcome | Log |
| --- | --- | --- | --- | --- |
| `t3-w4-a1` | v3, pinned phase-1 snapshot | 22:49:30.780, 78.24 ms | **Accepted v4** | `606ebae9-2c78-45e4-aa09-cc6fc8b68d2f` |
| `t3-w5-a1` | v3, pinned phase-1 snapshot | 22:49:32.113, 43.67 ms | `BUNDLE_VERSION_MISMATCH`, current v4 | `38be40c1-b2a2-4b13-9615-9670f2fd736a` |
| `t3-w5-a2` | v4, parent `38be40c1…` | 22:49:32.190, 78.89 ms | **Accepted v5** | `e071e4c4-d9b6-4a60-aef4-71855d847b4d` |
| `t3-w6-a1` | v3, pinned phase-1 snapshot | 22:49:33.293, 64.00 ms | `BUNDLE_VERSION_MISMATCH`, current v5 | `a93ad2c0-5e5e-4ec1-a85c-969cb6d83a14` |
| `t3-w6-a2` | v5, parent `a93ad2c0…` | 22:49:33.408, 114.59 ms | **Accepted v6** | `815081a5-2c9d-4c50-b49b-f3814f9558ea` |

Version hashes: v4 `67369396…d4a9c9`, v5
`3c4321295a439afafa0b25b1606af9c20c961147aa0042eacce722be3ecf25c9`, v6
`1d188dfc94c659b568211e599f0f1e64029bc7d8c86525781b484c820d5120fd`.

Reopen barrier: all three returned the same target at `created:false`,
version 6, hash `1d188dfc…`, original disk digest, cycle `ff8a71b2…`; reads
showed 201–206. Connections closed.

## Publication

| Field | Value |
| --- | --- |
| Status / version | `saved`, version 6 |
| Snapshot | `5d0de1d8-e6a0-4ae3-91dd-8234394be835` |
| Cycles | closed `ff8a71b2-d1ba-4749-8b53-ac913dc3cb8e`, new `a8d63046-4594-4890-8254-63f6cacd0d9f` |
| Publication | `installed`, 197 bytes, `content_eol: lf`, `durability: confirmed` |
| Receipt digest | `1d188dfc94c659b568211e599f0f1e64029bc7d8c86525781b484c820d5120fd` |

The disk file is byte-identical to `expected.py` and the receipt digest equals
the exact disk bytes. A fresh connection after SAVE returned the same target,
version 6, the published disk digest, and the new cycle `a8d63046…`.

## Database evidence

Read-only audit in [pr27-trial-3-audit.txt](pr27-trial-3-audit.txt):

- 1 binding/target; 6 accepted transactions and 6 ledger rows; 4 rejected
  attempts (two per wave), each linked as a parent of its recovery.
- 1 `initial_upload` snapshot (v0 `a233713f…`) and 1 `save_checkpoint` snapshot
  (v6 `1d188dfc…`); 2 cycles, 1 active.
- Target v6 hash equals the recomputed SHA-256 of `current_content`.

## Notes

- The bridge relaunch described above is a host-side incident: the initially
  detached launch was not persistent. The relaunched seats were fresh
  `patchdiff-mcp` processes with the same database and root; transcripts retain
  only the phase-1 tool calls made after the relaunch, plus the earlier
  handshakes.
- Unlike trial 2 wave 1, both trial 3 waves pinned the phase-1 snapshot for
  attempt 1, so the stale-snapshot path is exercised four times in this trial.

Artifacts: [pr27-trial-3-calls.json](pr27-trial-3-calls.json),
[pr27-trial-3-publication.txt](pr27-trial-3-publication.txt).
