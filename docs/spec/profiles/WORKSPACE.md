# Workspace profile

Set `PATCHDIFF_MCP_PROFILE=workspace` for one project directory. The
[installed workspace guide](../../guides/WORKSPACE_PUBLICATION.md) covers
client configuration and the edit sequence.

| Tool | Purpose |
| --- | --- |
| `patchdiff_initialize_target` | Start from a workspace file and return its working target ID. |
| `patchdiff_read_target` | Read bounded canonical working text and get its version and hash. |
| `patchdiff_find_occurrences` | Find exact text and disambiguate repeated matches. |
| `patchdiff_submit_edits` | Apply guarded replacements to the PostgreSQL working copy. |
| `patchdiff_save` | Checkpoint the working copy and publish the file when requested. |

## Startup requirements

The stdio process prepares the five tool declarations and checks the absolute
`PATCHDIFF_WORKSPACE_ROOT`, explicit `PATCHDIFF_DATABASE_URL` and database
migration revision before answering the MCP handshake. The database must
already be at the installed Alembic head. The server uses POSIX
descriptor-relative IO and directory locking. It starts without Node or
Waymark and refuses startup when strict observation mode is enabled.

## Publication settings

SAVE follows `PATCHDIFF_WORKSPACE_SYNC_ON_SAVE` when `sync_workspace` is
omitted or null. The default is off. Explicit true requests publication,
and explicit false selects a database-only checkpoint.

The [initializer](../MCP_TOOLS.md#1-target-lifecycle-tools)
and [SAVE](../MCP_TOOLS.md#patchdiff_save) use the shared MCP contracts, including
the workspace binding, path rules and partial publication receipts.
