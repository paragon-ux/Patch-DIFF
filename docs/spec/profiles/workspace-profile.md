# Workspace profiles (`workspace` and `observed_workspace`)

Choose a workspace profile when the host should start with a file path and publish
the edited bytes back to one project directory. A target is the working
copy that PatchDIFF keeps in PostgreSQL. The file, the working copy and the
database checkpoint are separate.

### Workspace Profile Tool Catalogs

| Tool | Profile | Use |
| --- | --- | --- |
| `patchdiff_initialize_target` | Both | Open the active working target for a workspace file, importing on first use. |
| `patchdiff_read_target` | Both | Read a bounded slice of the working text and get its version and hash. |
| `patchdiff_find_occurrences` | Both | Find exact matches in the working copy and distinguish repeated text. |
| `patchdiff_submit_edits` | `workspace` only | Apply a guarded batch of exact replacements to the working copy. |
| `patchdiff_list_scopes` | `observed_workspace` only | List AST structural candidate symbols and scope outlines. |
| `patchdiff_observe_scopes` | `observed_workspace` only | Request bounded AST scope snapshots with observation IDs. |
| `patchdiff_commit_bundle` | `observed_workspace` only | Submit an atomic multi-edit transaction guarded by scope snapshots. |
| `patchdiff_save` | Both | Checkpoint that version in PostgreSQL and optionally publish its bytes with `sync_workspace: true`. |

The 5-tool `workspace` profile uses exact text, so it starts without Node or Waymark.
The 7-tool `observed_workspace` profile connects the Waymark structural parser to the workspace
lifecycle, enabling high-performance AST scoped observation and atomic commit bundling.
Unlike `workspace`, `observed_workspace` permits `PATCHDIFF_STRICT_OBSERVATION_MODE=1`.

## Startup requirements

Install the package and migrate the database with the
[workspace quickstart](../../guides/workspace-quickstart.md). Set these
values in the environment of the MCP server process. For `observed_workspace`,
also follow the [seven-tool structural setup](../../guides/workspace-quickstart.md#seven-tool-structural-setup)
to install Node.js 22+ and the pinned Waymark npm dependencies before startup.

| Variable | Setting |
| --- | --- |
| `PATCHDIFF_MCP_PROFILE` | `workspace` or `observed_workspace` |
| `PATCHDIFF_WORKSPACE_ROOT` | An absolute path to the project directory on the server. Use the same project in the host so links resolve to the edited files. |
| `PATCHDIFF_DATABASE_URL` | Explicit connection URL for PostgreSQL. The database must be at the installed Alembic head. |
| `PATCHDIFF_WORKSPACE_SYNC_ON_SAVE` | Defaults to off. Set `sync_workspace` on the SAVE call to choose explicitly. |

The stdio server prepares the declarations and checks the root, database
connection and migration revision before the MCP handshake. The profile
requires POSIX descriptor-relative file access and directory locking.
Linux is the verified platform. The `workspace` profile refuses startup with
strict observation enabled; `observed_workspace` permits it. A startup failure
appears on stderr. Restart the process after
changing its configuration.

## Import, edit and publish

This walkthrough uses `workspace` and `patchdiff_submit_edits`. With
`observed_workspace`, use the same open and SAVE calls and follow the
[structural observation and commit contract](observed-editor-v2.md) for edits.

This example moves a maintenance window in `ops/schedule.txt` from 09:00
to 10:00. The file starts as a UTF-8 line ending in CRLF. Each request below
shows the tool arguments and each receipt shows the fields needed for the
next step. Use the IDs, versions and hashes from your own receipts.
For the stdio adapter, parse the JSON in the MCP tool result's text content
and check its `status` before proceeding.

### 1. Open the file

Call `patchdiff_initialize_target` with a path relative to the configured
root. Leave out `content` when `from_workspace` is true.

```json
{"filename":"ops/schedule.txt","from_workspace":true}
```

```json
{
  "status": "ok",
  "target_file_id": "11111111-1111-4111-8111-111111111111",
  "filename": "ops/schedule.txt",
  "created": true,
  "version": 0,
  "current_hash": "2d399ba08bf8d535404f7618328297dcec2e8cb4f5745a9c9668ae2678c90dee"
}
```

The first open creates the working target and records the source line endings
and raw-byte digest. When the recorded disk baseline matches, subsequent
opens return the same target ID with `created: false` and its current database
version, including unpublished edits.
The receipt does not include the document body.

### 2. Read the text and prepare the edit

Call `patchdiff_read_target` with the returned ID. In this short example
the first slice contains the whole line. For a longer file, continue at
`next_start` when it is present, or use `patchdiff_find_occurrences` to
locate known exact text.

```json
{"target_file_id":"11111111-1111-4111-8111-111111111111","start":0,"length":80}
```

```json
{
  "status": "ok",
  "text": "Maintenance starts at 09:00.\n",
  "version": 0,
  "current_hash": "2d399ba08bf8d535404f7618328297dcec2e8cb4f5745a9c9668ae2678c90dee"
}
```

The read returns canonical LF text. Its version and hash describe the same
working copy. If exact search finds several matches, use the documented
[selectors](../mcp-tools.md#patchdiff_submit_edits-primary-typed-transaction)
to identify the intended one. Use the text and guard from the same observation.

### 3. Submit the guarded edit

Call `patchdiff_submit_edits` with the target ID, a nonblank `intent`, the
ordered exact replacements, and the observed version and/or hash. The
example supplies both guards.

```json
{
  "target_file_id": "11111111-1111-4111-8111-111111111111",
  "expected_target_version": 0,
  "expected_current_hash": "2d399ba08bf8d535404f7618328297dcec2e8cb4f5745a9c9668ae2678c90dee",
  "intent": "Move the maintenance window to 10:00",
  "edits": [{"match":"09:00","replace":"10:00"}]
}
```

```json
{
  "status": "accepted",
  "version": 1,
  "current_hash": "37bf0bd0c020c2d980883158293584113d123943a00a8300580872536ef40020",
  "manifest_entries_added": 1
}
```

Acceptance updates PostgreSQL and records the accepted transaction. At this
point the on-disk file still contains 09:00.

### 4. Checkpoint and publish

Call `patchdiff_save` with the accepted version as a guard and request
workspace publication explicitly.

```json
{
  "target_file_id": "11111111-1111-4111-8111-111111111111",
  "expected_target_version": 1,
  "sync_workspace": true
}
```

```json
{
  "status": "saved",
  "version": 1,
  "current_hash": "37bf0bd0c020c2d980883158293584113d123943a00a8300580872536ef40020",
  "snapshot_id": "22222222-2222-4222-8222-222222222222",
  "workspace_sync": {
    "synced_path": "ops/schedule.txt",
    "disk_sha256": "b00d23d7e3d42ca47d350d13c4d3b0a6f2ef998f5e184df173454769230a446f",
    "bytes_written": 30,
    "content_eol": "crlf",
    "publication": "installed",
    "durability": "confirmed"
  }
}
```

### Publication settings

Use `synced_path` relative to the configured server root. The receipt pairs
the canonical working hash with a separate digest of the published bytes.
SAVE preserves uniform original line endings by default. For mixed or
unknown original endings, choose `canonical_lf` or `crlf` explicitly in
`workspace_eol_format`. With `sync_workspace: false`, SAVE only checkpoints
the database. If you omit the field or pass null, the process default applies.

## Decide what to do after a failure

| Result | Meaning and next step |
| --- | --- |
| Initialization rejects the path or file | Use a valid relative path to a regular UTF-8 file. Check the root and file type. Paths that escape the root or traverse symlinks are rejected. |
| An edit is rejected or a guard no longer matches | Read or search again. Rebuild the proposal from the current working version and verify that the user's requested change still applies. |
| Initialization or SAVE returns `workspace_busy` | Another managed operation owns the destination. Wait for it to settle, then reopen and verify the working version before proceeding. |
| Initialization or SAVE returns `external_disk_drift` | Restore the recorded bytes at the pinned destination to resume the existing target. If present disk bytes should start a successor, use guarded `workspace_recovery` with action `reimport`. Restore a missing file before fresh recovery. |
| Initialization returns `workspace_binding_ambiguous` | Inspect the listed members of this binding and use guarded `select_existing` to choose the active history. |
| Initialization or SAVE returns `workspace_binding_mismatch` | Check the configured root, parent directory and exact listed spelling. The destination can resolve to a different recorded path. |
| SAVE returns `partial` | The file was installed. Use the included `workspace_sync` receipt to inspect the actual file and check the database snapshot and cycle. The response leaves checkpoint and cycle IDs empty. |
| The SAVE response is lost | Treat both outcomes as unknown. Compare the file bytes and the database checkpoint before choosing what to do next. |

If the destination parent directory was replaced, restore the original
directory at the recorded path before retrying. Guarded reimport recovers disk
content within the pinned destination. If the original directory is unavailable,
read, replay or export the retained history by target ID. Choose a separate
workspace path or root to start another history explicitly.

If exactly one recorded binding conflicts with the listed spelling, inspect
its target by ID first. Coordinate with other writers and restore the
recorded spelling if the filesystem permits it, then reopen. If multiple
legacy bindings resolve to the same entry, restoring either spelling still
leaves an ownership conflict. Access the retained histories by target ID.
Choose a separate destination if an operator needs to start a new history.

A SAVE can install file bytes before the database checkpoint succeeds.
On a partial result, inspect whether the checkpoint actually committed
before attempting another SAVE. Reopen the path for the active target and
disk evidence. If a new history is appropriate, follow the
[guarded recovery contract](../mcp-tools.md#workspace-initialization-and-recovery). Use a trusted
[full-profile](delegation-and-lifecycle.md#full) connection when the host
needs to inspect audit or replay evidence.

See the [shared SAVE contract](../mcp-tools.md#patchdiff_save) for exact
error codes, the destination lease, and the limits of file publication
in the presence of other writers.

## Comparative workflow evidence

The [PR #24 Workspace benchmark](../../benchmarks/workspace-e2e-benchmark.md)
compares `observed_workspace` with Native and standalone `observed_v2` across
18 trials. Workspace's editing agent imported files, submitted guarded scope
bundles and published through SAVE. Standalone `observed_v2` used separate
host initialization and finalization. Both apply guarded atomic transactions
per target. Timings, preparation costs, accuracy and model/build attribution
limits are recorded in the report.
