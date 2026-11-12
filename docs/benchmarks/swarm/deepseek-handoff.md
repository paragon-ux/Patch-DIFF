# Archived DeepSeek handoff for the PatchDIFF swarm test

This is the original coordinator handoff for trial 1, wave 2 on runtime
`52f19e213759e2664e3fa8f0c70f3930ca2a0ff6`. All trials are complete.
The instructions below refer to the historical version-3 state. See the
[completed results](README.md#completed-trials-and-reporting). Use a fresh
isolated database and fixture for any new run.

Resume trial 1 at wave 2 using the existing test installation, PostgreSQL
database, and fixture directory. Wave 1 has already passed. Your task is to
coordinate three live workers through manual barriers, prove that they
rediscover one shared working copy, and publish the verified result once.
Use the installed PatchDIFF server and individual MCP tool calls.

## How PatchDIFF works

PatchDIFF is a document transaction server. DeepSeek and its host decide
what to edit. PatchDIFF reads the file, checks each proposed change, and
commits accepted edits atomically.

| Term | Meaning in this test |
| --- | --- |
| Workspace root | The server's configured directory. Workers pass paths relative to it. |
| Target | The PostgreSQL working copy, identified by `target_file_id`. First workspace open imports the disk file. Subsequent opens resolve the same root and path to the active target, including unpublished edits. |
| Version and canonical hash | The version advances once per accepted edit transaction. The hash covers the canonical UTF-8 text with LF line endings. Both guard a proposed commit. |
| Observed scope | A Python function selected through Waymark. Observation returns exact scope text, its ID, and a snapshot of the whole target. |
| Bundle | One or more edits submitted against that snapshot. Every operation in an accepted bundle commits together. This test uses one exact match replacement per bundle. |
| SAVE | A PostgreSQL checkpoint that rotates the editing cycle. With `sync_workspace: true`, SAVE also publishes the working bytes to disk. The result reports publication separately. SAVE keeps the target version. |

The shared version belongs to the **file target**. Three workers can edit
different functions and still receive stale-version rejections when they
submit against the same starting version. This is expected. Re-observing
gives the rejected worker current scope text and a fresh snapshot.

## Original connection instructions

1. Open the [swarm runbook](README.md) and [wave 1 evidence](results/pr27-trial-1-wave-1.md). The repository worktree contains the instructions. The original `trial-1` directory under the run directory contains the fixture.
2. Resume the existing PostgreSQL 16.3 test container. Use the isolated database `patchdiff_swarm_52f19e2` on loopback port 55437 and the original `trial-1` root. The stored binding includes the root directory's identity, so copying the file to a new directory would start a different test.
3. In the host, start the installed `patchdiff-mcp` launcher with `PATCHDIFF_DATABASE_URL` pointing to that database and `PATCHDIFF_WORKSPACE_ROOT` pointing to the original root. Set `PATCHDIFF_MCP_PROFILE=observed_workspace`, `PATCHDIFF_STRICT_OBSERVATION_MODE=1`, and `PATCHDIFF_WAYMARK_MODE=resident`. Make the pinned Node binary available to the server and keep the installed package import path.
4. Give each worker a separate MCP connection to the same root and database. The host normally handles MCP negotiation. Check `tools/list` on each connection. The advertised tools should be `patchdiff_initialize_target`, `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`, and `patchdiff_save`. Read the logical result from `structuredContent` when present or parse the JSON in the MCP text result.

The coordinator knows that the target should be at version 3, with functions
1–3 returning 201, 202, and 203. Disk still contains all six original values.
Keep the known target ID and hash from the runbook out of the worker briefs.

## Run wave 2

The coordinator assigns `setting_4`, `setting_5`, and `setting_6` to T1-W4,
T1-W5, and T1-W6 respectively. Each worker changes only the return value in
its own function, from 104–106 to 204–206.

### 1. Open by path

Wait until all three connections are ready. Release the workers to call
`patchdiff_initialize_target` with these arguments.

```json
{"filename":"system_settings.py","from_workspace":true}
```

Each receipt should contain the same `target_file_id`, `created: false`,
version 3, and the original raw `disk_sha256`. Record each call's interval and
receipt. A `workspace_busy` result permits up to five retries of the same
open within 60 seconds. Check the returned identity against the runbook
after all workers report. Have each worker call `patchdiff_read_target` with
its returned ID and confirm that it sees the three unpublished changes.

### 2. Observe and wait

The following are example arguments for T1-W4. Replace the target placeholder
with the ID returned by this worker's open.

```json
{
  "target_file_id": "<ID from initialize>",
  "selections": [{"symbol_name": "setting_4"}]
}
```

Send these to `patchdiff_observe_scopes`. Read the selected scope text and
check that it contains the expected original return. Keep the response's
complete `snapshot` object and the selected scope's `observation_id`. The
three snapshots must agree on target ID, version 3, and canonical hash.
Their observation bundle and scope IDs will differ.

Hold the commit barrier until all three workers report these snapshots.
Release the three first attempts together. A worker must submit the
snapshot it just reported so the first round tests stale-version rejection.

### 3. Submit and recover

Example `patchdiff_commit_bundle` arguments for T1-W4 follow. Replace the
entire example snapshot with the exact object from this worker's
`patchdiff_observe_scopes` response. Copy its scope ID separately.

```json
{
  "snapshot": {
    "target_file_id": "<from observation>",
    "expected_target_version": 3,
    "expected_current_hash": "<from observation>",
    "observation_bundle_id": "<from observation>"
  },
  "intent": "Change setting_4 to return 204",
  "client_request_id": "t1-w4-a1",
  "groups": [
    {
      "observation_id": "<from the setting_4 scope>",
      "operations": [{"op": "match", "match": "return 104", "replace": "return 204"}]
    }
  ]
}
```

Expect one first-round acceptance at version 4 and two
`BUNDLE_VERSION_MISMATCH` rejections. Record every response, including
`transaction.pdcp_log_id`, before and after versions, and the current
version. For a definitive stale rejection, observe again, rebuild the
proposal from current text, use a new key such as `t1-w4-a2`, and set
`parent_pdcp_log_id` to the rejected log ID. Allow five attempts per worker.
For a lost or unknown response, resend the identical proposal and key to
recover the outcome before preparing another proposal.

Once all three are accepted, release the reopen barrier. Each worker opens
by path again, expects the original ID and version 6 with `created: false`,
and verifies its own result by reading the target. The raw disk digest
should still equal the version-0 baseline. Close the three worker
connections.

### 4. Publish and verify

The coordinator opens and reads the target through its own connection.
Check version 6 and that the six functions return 201–206. Send
`patchdiff_save` once with the returned `target_file_id`,
`expected_target_version: 6`, the version-6 `expected_current_hash`, and
`sync_workspace: true`. Check `status: saved`, a snapshot ID, and the
`workspace_sync` publication receipt. Compare the file on disk against
`expected.py` in the run directory. Verify the receipt's SHA-256 against
the exact disk bytes.

Open again on a fresh connection and verify the same target ID and
version 6 with the new cycle from SAVE. Use read-only PostgreSQL
inspection to confirm one binding and target for trial 1, one initial
snapshot, six accepted transactions and ledger entries, and one SAVE
checkpoint. Match rejected log IDs to the attempt log.

If an open returns external drift, a different target, or unexpected disk
bytes, pause the trial and preserve the evidence. If SAVE returns a partial
outcome or its response is lost, inspect the actual file and database
checkpoint before issuing another SAVE.

## Original coordinator brief

> Resume trial 1, wave 2 of the PatchDIFF swarm test. Read the swarm runbook
> and this handoff. Keep the existing runtime, database, and original fixture
> root. Start three live workers with independent strict observed_workspace
> connections. Assign setting_4, setting_5, and setting_6 and withhold the
> target ID. Use the open, commit, and reopen barriers. Collect real tool
> receipts and reconcile all three target identities and versions before
> proceeding. Keep edits in PostgreSQL until all six function results are
> verified at version 6. Publish once as coordinator and check the file
> bytes, digest, cycle, and database evidence. Record the actual DeepSeek
> model and results under results/. Label trial 1 as a mixed-model handoff.
> Use individual MCP calls for the test and keep the workers' edits inside
> PatchDIFF. Start trials 2 and 3 only after trial 1 passes.

The [workspace lifecycle contract](../../spec/profiles/workspace-profile.md)
and [observed editing contract](../../spec/profiles/observed-editor-v2.md)
document the tool arguments and receipts used here.
