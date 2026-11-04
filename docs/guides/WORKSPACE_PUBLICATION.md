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

Start or refresh the MCP connection and check that it exposes these five tools.

| Tool | When to use it |
| --- | --- |
| `patchdiff_initialize_target` | Start here if you have a filename but no `target_file_id`. |
| `patchdiff_read_target` | Read bounded working text and obtain its version and hash. |
| `patchdiff_find_occurrences` | Locate known exact text or disambiguate repeated matches. |
| `patchdiff_submit_edits` | Commit guarded replacements to the PostgreSQL working copy. |
| `patchdiff_save` | Checkpoint the working copy and publish to the workspace when requested. |

The server prepares these declarations and checks the absolute workspace
directory, explicit database URL and installed migration revision before the
MCP handshake. Startup errors go to stderr. Apply migrations separately.
This profile starts without Node or Waymark. Strict observation mode is
incompatible with this exact-text profile.

Set the MCP server's workspace root to the same project directory the host
opens, so server-relative paths and client-rendered links refer to the same
file. If the host prompts for MCP write approval, authorize the server for
that workspace before asking it to edit.

The root must already exist. Sync defaults off; use `sync_workspace=true` on an
individual SAVE, or deliberately set `PATCHDIFF_WORKSPACE_SYNC_ON_SAVE=1` for
that server. Explicit false disables publication even when the default is on.
Installation does not choose a project root. Configure each server process for
its intended workspace; targets imported from disk retain the root's device/
inode identity and reject a different root, even if relative names/bytes match.
Relocating the same directory preserves that identity; using another copy
requires explicit initialization of a new target.

## Ownership and paths

The server owns managed file operations. Workspace imports and publications obtain
an advisory exclusive lease on the pinned physical destination directory.
This serializes the same destination across processes, target IDs, overlapping
configured roots and path aliases. Different destination directories can run
independently. A conflicting operation rejects
`workspace_busy` without publication. Reinitialize duplicate targets when their
baseline diverges; do not publish both from a stale shared baseline.

Path validation rejects escapes, reserved/ambiguous path components and static
symlinks. IO walks directories using non-following handles, then reads/replaces
relative to the opened parent. Replacing an ancestor pathname with a symlink
cannot redirect that opened handle to another tree. The trusted configured root
and opened directories must remain owned/stable: a hostile process moving an
opened directory out of the workspace is outside this cooperative ownership
contract. This mode is not a filesystem sandbox against another process with
the same filesystem privileges.

The source byte hash is checked under the lease and checked again after staging.
Unmanaged edits found at either check reject as `external_disk_drift` and remain
intact. Non-cooperating writers can still race after the final check: pathname
replacement is not hash compare-and-swap. Quiesce such writers during
publication. Creation uses an atomic no-clobber link, so a newly appeared file
is preserved. These limits apply regardless of whether the file writer is
native or an external managed adapter.

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

SAVE publication rejects caller-owned database transactions before IO. Plain
SAVE (`sync_workspace=false`) retains existing caller-transaction behavior.
`original_eol` is the default; mixed original endings require an explicit
`canonical_lf` or `crlf` choice. POSIX file modes are retained. Newly created
files use private mode 0600. New parent directories can remain after a rejected
publication; file installation and directory creation are not a transaction.

## Partial outcomes

Before installation, a failure returns `rejected`, leaves destination bytes
unchanged and creates no checkpoint. After installation, a filesystem durability
failure returns `partial` with `workspace_durability_uncertain` and
`workspace_sync.durability=uncertain`. A later database flush/commit error returns
`partial` with `workspace_checkpoint_uncertain` and the installed-file digest;
a commit acknowledgement error may mean the database actually committed.
A directory-handle teardown error after installation returns `partial` with
`workspace_post_install_error`; its receipt retains the observed durability.
Checkpoint/cycle IDs are not asserted on a partial result. No filesystem
rollback is attempted and no automatic retry is safe. A killed process/lost
response can also leave an unknown outcome. Inspect the file, target, cycles
and snapshots, then explicitly reconcile or initialize a new target.

This implementation establishes a source-transfer path with no full-text relay
in initialization arguments or the successful SAVE receipt. It does not claim a
measured whole-host token saving, latency improvement, Windows support or an
atomic file/database commit. Live PostgreSQL and installed-host acceptance
remain separate gates for the patch candidate.
