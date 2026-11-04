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

Create a Python 3.11 virtual environment and install the PatchDIFF wheel.
Provision a PostgreSQL 16 database and set `PATCHDIFF_DATABASE_URL` to its
connection URL before applying the migrations shipped with the wheel.

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install /absolute/path/to/patchdiff_mvp-0.1.0-py3-none-any.whl
export PATCHDIFF_DATABASE_URL='postgresql+psycopg://patchdiff@localhost:5432/patchdiff'
alembic_ini=$(python -c 'from pathlib import Path; import app; print(Path(app.__file__).with_name("migrations") / "alembic.ini")')
python -m alembic -c "$alembic_ini" upgrade head
```

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
[five workspace tools](../spec/profiles/workspace-profile.md). Startup errors appear
on stderr.

Set the MCP server's workspace root to the same project directory the host
opens, so server-relative paths and client-rendered links refer to the same
file. If the host prompts for MCP write approval, authorize the server for
that workspace before asking it to edit.

Use `sync_workspace=true` when you want SAVE to write the file. The
[workspace profile contract](../spec/profiles/workspace-profile.md) describes
startup requirements and the server-wide sync default.

## Edit and publish a file

Give the host a request with the file path, the desired edit and whether
to write the result to disk. For example, ask it to move the maintenance
window in `ops/schedule.txt` to 10:00 and save the file.

The host imports the file with `patchdiff_initialize_target` and
`from_workspace: true`. It reads or searches the returned target ID,
submits a guarded edit with a nonblank `intent`, then calls
`patchdiff_save` with the accepted version and `sync_workspace: true`.
The [worked example](../spec/profiles/workspace-profile.md#import-edit-and-publish)
shows each call and the corresponding receipt.

A successful publication reports `status: "saved"` with a `workspace_sync`
receipt. Resolve its `synced_path` relative to the configured server root.
For a rejection, partial result or missing response, follow the
[workspace recovery steps](../spec/profiles/workspace-profile.md#decide-what-to-do-after-a-failure).
