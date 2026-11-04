# Workspace editing with the installed package

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
[five workspace tools](../spec/profiles/WORKSPACE.md). Startup errors appear
on stderr.

Set the MCP server's workspace root to the same project directory the host
opens, so server-relative paths and client-rendered links refer to the same
file. If the host prompts for MCP write approval, authorize the server for
that workspace before asking it to edit.

Use `sync_workspace=true` when you want SAVE to write the file. The
[workspace profile contract](../spec/profiles/WORKSPACE.md) describes
startup requirements and the server-wide sync default.

## Edit and publish a file

A normal user request can name the file, describe the edit and ask to save it
to the workspace. The client can discover the sequence from the tools.

1. Start with `patchdiff_initialize_target` and arguments
   `{"filename":"handbook/on-call.md","from_workspace":true}`. Omit `content`.
   The response gives you `target_file_id`, version and hash without returning
   the source text. Use that ID in the following calls.
2. Read the working copy with `patchdiff_read_target`, or search with
   `patchdiff_find_occurrences` when you know the exact text. Submit one
   `patchdiff_submit_edits` call with the target ID, observed version and/or
   hash, a nonblank `intent` describing the change, and ordered `edits` with
   exact `match` and `replace` strings. Acceptance updates PostgreSQL.
3. Call `patchdiff_save` with the target ID, the accepted version as
   `expected_target_version`, and `sync_workspace: true`.
4. On `saved`, use `workspace_sync.synced_path` relative to the configured root.
   The receipt gives the raw byte digest in `disk_sha256`, plus `bytes_written`,
   `content_eol`, `publication: "installed"` and `durability: "confirmed"`.
   The optional `export_after_save` flag also returns the document body.
5. If SAVE reports external drift, inspect the workspace file and initialize a
   new working target from it. If SAVE reports partial or the response is lost,
   inspect both disk and PostgreSQL before reconciling.

`original_eol` is the default. For a file with mixed original line endings,
set `workspace_eol_format` to `canonical_lf` or `crlf`. See the
[shared SAVE contract](../spec/MCP_TOOLS.md#patchdiff_save) for publication
errors, partial receipts and filesystem requirements.
