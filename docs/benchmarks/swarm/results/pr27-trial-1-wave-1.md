# PR #27 live swarm — Trial 1, wave 1

The coordinator stopped after the first wave at the user's direction. Three Sol
6.1 Extra High worker turns used independent strict `observed_workspace` stdio
connections and manual barriers. The third seat reused an existing Sol agent
thread after the chat reached its thread limit. Workers discovered the target
by path and made individual MCP requests.

- Installed PR head `52f19e213759e2664e3fa8f0c70f3930ca2a0ff6`.
- PostgreSQL 16.3 database `patchdiff_swarm_52f19e2`, migration `20261111_0007`.
- Fixture `trial-1/system_settings.py`.
- Target `df0887b3-c6ca-4ad3-9279-1136f5afe26d`, editing cycle `7d75be39-878d-42f0-94aa-27d2aa3b7b0d`.
- Initial and final disk SHA-256 `a233713f22ccab19a7473e84696f1fe94205a9aca04239ea3c52bf694c8dd6a1`.
- Expected and recomputed version-3 SHA-256 `0149f73a9b82d9408a78ee09d8cb0c2aaccb25294a0218e11f57e857f04a4e7e`.

## Open and observation barrier

All timestamps are UTC on 2026-11-11. Intervals measure the client tool call
and include transport and tool wait time.

| Worker | Session | First-open interval | Receipt | Version-0 observation bundle |
| --- | --- | --- | --- | --- |
| T1-W1 | 39005 | 21:29:22.859–21:29:28.929 | OK, created true, v0 | `18341889-cb7f-48de-b0eb-92b9eb5e4eab` |
| T1-W2 | 16773 | 21:29:28.546–21:29:32.614 | OK, created false, v0 | `8377b19f-cfb4-462b-aff5-93aa4b70a9df` |
| T1-W3 | 32242 | 21:29:32.953–21:29:38.574 | OK, created false, v0 | `b4ea5694-ad94-4353-ad1d-263ecf34a7c7` |

All three opens and snapshots named the same target and the same initial
hash. Three workers were active. Two measured first-open intervals overlapped
by 383 ms. There were zero `workspace_busy` responses.

## Commit barrier and retries

| Request key | Client interval (UTC) | Guard version | Outcome | Log ID |
| --- | --- | --- | --- | --- |
| `t1-w1-a1` | 21:30:17.650–21:30:37.777 (send plus response poll) | 0 | Accepted v1 | `4cbbde44-c57e-4497-bc3d-618e42dd6af2` |
| `t1-w2-a1` | 21:30:48.965–21:30:54.072 | 0 | `BUNDLE_VERSION_MISMATCH`, current v1 | `28df579c-8b53-424f-8447-acf82ca86737` |
| `t1-w3-a1` | 21:30:52.203–21:30:57.922 | 0 | `BUNDLE_VERSION_MISMATCH`, current v1 | `98c30100-7513-4576-b153-b911c8ba4f26` |
| `t1-w2-a2` | 21:31:38.254–21:31:42.547 | 1 | Accepted v2 | `0191f503-c251-48b6-90f6-c655a5798503` |
| `t1-w3-a2` | 21:31:42.931–21:31:51.076 | 1 | `BUNDLE_VERSION_MISMATCH`, current v2 | `ec142e62-1af1-4530-b819-53e12e16e8b5` |
| `t1-w3-a3` | 21:32:25.389–21:32:29.614 | 2 | Accepted v3 | `5335f880-3833-4a1d-9a12-9ecf27c16321` |

Retries used newly observed snapshots, fresh keys, and the prior rejection
as their parent. Version 1 hash was
`822817b404a0b510519135a94c0b2d84395eb3dc95a07159c5cc89e16db8eb4c`.
Version 2 hash was
`b5e2b71ccbaa58e724dfbe73bc2db1d5ac1119b23f741b4bb2918d0339097866`.

## Reopen and disposition

| Worker | Reopen interval | Working-copy read |
| --- | --- | --- |
| T1-W1 | 21:32:48.266–21:32:53.706 | `setting_1` returns 201 |
| T1-W2 | 21:32:53.002–21:32:56.397 | `setting_2` returns 202 |
| T1-W3 | 21:32:55.829–21:33:00.012 | `setting_3` returns 203 |

Every reopen returned `created: false`, the same target and cycle, version 3,
the expected working-copy hash, and the original disk hash. Read-only
PostgreSQL evidence in [pr27-trial-1-wave-1-audit.txt](pr27-trial-1-wave-1-audit.txt) shows one binding,
one member, one target, one project, one initial snapshot, one active cycle,
three ledger entries, and zero SAVE checkpoints. It also confirms three
accepted edits and all three stale rejections.

The first wave passed its checks. The five remaining waves and the SAVE phase
were left pending. The three changes are durable in PostgreSQL. The file on
disk still matches the original bytes. All worker MCP sessions closed.
