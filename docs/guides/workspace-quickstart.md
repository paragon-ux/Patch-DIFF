# Workspace editing quickstart

Use the `workspace` MCP profile when a host needs to edit an existing file in
one project directory. PatchDIFF imports the file into a PostgreSQL working
target, applies guarded edits there, then publishes the file on explicit SAVE.
File publication and the database checkpoint have separate outcomes.

## Setup

Use a POSIX server supporting `openat`-style directory-relative IO, `O_NOFOLLOW`
and directory `flock`. Linux is the verified platform. The `workspace` profile
fails startup on native Windows, where inline upload, edit and export remain
available through `full`. A Linux/WSL server
can access a mounted project only if its filesystem supports these operations.

Create a Python 3.11 virtual environment and install `patchdiff-mcp`.
Provision a PostgreSQL 16 database and set `PATCHDIFF_DATABASE_URL` to its
connection URL before applying the migrations shipped with the package.

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install patchdiff-mcp
export PATCHDIFF_DATABASE_URL='postgresql+psycopg://patchdiff@localhost:5432/patchdiff'
patchdiff-mcp --migrate
```

### Seven-tool structural setup

The five-tool `workspace` profile needs no Node.js installation. For the
seven-tool `observed_workspace` profile, install Node.js 22+ on the server,
then install the pinned npm dependencies beside the bridge shipped with the
package. Run this with the same virtual environment activated:

```bash
node --version
waymark_dir=$(python -c 'from app.services.waymark_adapter import WAYMARK_INTEGRATION_DIR; print(WAYMARK_INTEGRATION_DIR)')
npm --prefix "$waymark_dir" ci --omit=dev
```

The shipped `package-lock.json` pins Waymark Engine 4.1.0 and its dependencies.
Repeat this npm command after upgrading the Python package. In the MCP
configuration below, select `PATCHDIFF_MCP_PROFILE=observed_workspace` and
add `PATCHDIFF_WAYMARK_MODE=resident`. Set
`PATCHDIFF_STRICT_OBSERVATION_MODE=1` to require observed writes. That profile
imports files and publishes SAVE through the same connection, using
`patchdiff_list_scopes`, `patchdiff_observe_scopes` and
`patchdiff_commit_bundle` for guarded structural editing.

## Connect the MCP client

Configure your MCP client to start that interpreter. Replace the paths and
database URL with the values for your environment.

```json
{
  "mcpServers": {
    "patchdiff-workspace": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "app.mcp.external_adapter"],
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

Start or refresh the MCP connection and verify that it exposes the
[selected workspace catalog](../spec/profiles/workspace-profile.md): five tools
for `workspace` or seven for `observed_workspace`. Startup errors appear on stderr.

Set the MCP server's workspace root to the same project directory the host
opens, so server-relative paths and client-rendered links refer to the same
file. If the host prompts for MCP write approval, authorize the server for
that workspace before asking it to edit.

Use `sync_workspace=true` when you want SAVE to write the file. The
[workspace profile contract](../spec/profiles/workspace-profile.md) describes
startup requirements and the server-wide sync default.

## Edit and publish a file

The following example uses the five-tool `workspace` profile.

Give the host a request with the file path, the desired edit and whether
to write the result to disk. For example, ask it to move the maintenance
window in `ops/schedule.txt` to 10:00 and save the file.

| Step | Tool | Arguments to supply |
| --- | --- | --- |
| Start with the file | `patchdiff_initialize_target` | Workspace-relative `filename` and `from_workspace: true`. Keep the returned `target_file_id`. |
| Read the working copy | `patchdiff_read_target` | `target_file_id`. Use `start` and `length` to read more. Keep the version or hash for the submission guard. |
| Disambiguate if needed | `patchdiff_find_occurrences` | `target_file_id` and exact `text`. Use the occurrence index or anchors for repeated matches. |
| Apply the edit | `patchdiff_submit_edits` | `target_file_id`, nonblank `intent`, `edits` with exact `match` and desired `replace`, and `expected_target_version` or `expected_current_hash`. Keep the accepted version. |
| Publish and checkpoint | `patchdiff_save` | `target_file_id`, `expected_target_version` set to the accepted version, and `sync_workspace: true`. |

The [worked example](../spec/profiles/workspace-profile.md#import-edit-and-publish)
shows the calls and receipts. After SAVE, check for `status: "saved"`, a
`snapshot_id` and a `workspace_sync` receipt. Resolve its `synced_path`
relative to the configured server root. Open that file to confirm the
requested edit, or compare the SHA-256 of its raw bytes with the receipt's
`disk_sha256`.

For a rejection, partial result or missing response, follow the
[workspace recovery steps](../spec/profiles/workspace-profile.md#decide-what-to-do-after-a-failure).
