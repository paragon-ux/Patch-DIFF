# Claude Desktop setup

Claude Desktop connects to PatchDIFF over stdio. Use the five-tool
`workspace` profile to edit a project file through a Linux server. First
install `patchdiff-mcp` and migrate your PostgreSQL 16 database as shown in the
[workspace quickstart](workspace-quickstart.md).

## Configure the connection

Before modifying the configuration file, create a backup copy of your existing
`claude_desktop_config.json` (such as `claude_desktop_config.json.bak`).

Open Claude Desktop settings and choose **Developer > Edit Config**.
Add the `patchdiff-workspace` entry under `mcpServers`, preserving any existing
server entries to avoid overwriting current MCP tools.
Use the absolute path to the installed environment's `patchdiff-mcp` executable
(or its Python interpreter running `-m app.mcp.external_adapter`),
the PostgreSQL connection URL and the server's project root.

```json
{
  "mcpServers": {
    "patchdiff-workspace": {
      "command": "/absolute/path/to/venv/bin/patchdiff-mcp",
      "args": [],
      "env": {
        "PATCHDIFF_MCP_PROFILE": "workspace",
        "PATCHDIFF_DATABASE_URL": "postgresql+psycopg://patchdiff@localhost:5432/patchdiff",
        "PATCHDIFF_WORKSPACE_ROOT": "/absolute/project/root",
        "PATCHDIFF_WORKSPACE_SYNC_ON_SAVE": "0"
      }
    }
  }
}
```

The example assumes the command starts on Linux. On Windows the server can
run in WSL if Claude Desktop launches it through `wsl.exe` and the project
filesystem supports the [workspace profile requirements](../spec/profiles/workspace-profile.md).
Use Linux paths and a database URL reachable from WSL in that case.
For a native Windows server, use `full` for inline initialization, editing
and export.

Fully quit and reopen Claude Desktop after saving the configuration.
Check the connection lists the [five workspace tools](../spec/profiles/workspace-profile.md).
Startup diagnostics go to stderr. The interpreter must resolve the installed
package and the database must be at the packaged Alembic head.

## Edit and verify

Ask Claude to edit a specific path relative to the configured project root
and save it to disk. For example, ask it to move the maintenance window in
`ops/schedule.txt` to 10:00 and save the file. If Claude Desktop asks for
permission, approve the calls for that project.

The host starts with workspace initialization, reads or searches the returned
target ID, and submits guarded edits. On SAVE, check for a snapshot ID and the
`workspace_sync` receipt. Open the receipt's path relative to the server root
and confirm the edit. See the [quickstart](workspace-quickstart.md#edit-and-publish-a-file)
for the exact arguments and receipt checks.

## Other workflows

Use a separate [structural editing profile](observed-editor-workflow.md) for
scope-based editing. Use the [trusted lifecycle profile](../spec/profiles/delegation-and-lifecycle.md#full)
for export, audit or replay.
