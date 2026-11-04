# Optional workspace publication

This mode reads and writes files in the server's workspace. PostgreSQL remains
the canonical working target for deterministic editing. SAVE's database
checkpoint and file installation are separate outcomes; neither can roll back
the other. No finalization tool, automatic retry or recovery service is added.

## Setup

Use a POSIX server supporting `openat`-style directory-relative IO, `O_NOFOLLOW`
and directory `flock` (Linux is the verified platform). Native Windows workspace
IO rejects with `workspace_platform_unsupported` before file IO. The ordinary
inline upload/edit/export workflow remains available there. A Linux/WSL server
can access a mounted project only if its filesystem supports these operations.

Use PostgreSQL 16 and apply the migrations shipped with the installed wheel.
In the same Python environment as PatchDIFF, set `PATCHDIFF_DATABASE_URL` to
the provisioned database, then run:

```bash
alembic_ini=$(python -c 'from pathlib import Path; import app; print(Path(app.__file__).with_name("migrations") / "alembic.ini")')
python -m alembic -c "$alembic_ini" upgrade head
```

Configure your MCP client to start that interpreter. For example:

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

The `workspace` profile exposes `patchdiff_initialize_target`,
`patchdiff_read_target`, `patchdiff_find_occurrences`,
`patchdiff_submit_edits` and `patchdiff_save`. It prepares these declarations
at startup and checks the absolute workspace directory and installed database
migration revision before answering MCP requests. Apply migrations separately.
This profile uses exact text edits and starts without Node or Waymark. A server
with strict observation enabled must use an observed editing profile.

The root must already exist. Sync defaults off; use `sync_workspace=true` on an
individual SAVE, or deliberately set `PATCHDIFF_WORKSPACE_SYNC_ON_SAVE=1` for
that server. Explicit false disables publication even when the default is on.
Installation does not choose a project root. Configure each server process for
its intended workspace; targets imported from disk retain the root's device/
inode identity and reject a different root, even if relative names/bytes match.
Relocating the same directory preserves that identity; using another copy
requires explicit initialization of a new target.

## Ownership and paths

The server owns managed file operations. All managed readers/publishers obtain
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

## Flow through existing tools

1. Call `patchdiff_initialize_target(filename="src/app.py", from_workspace=true)`
   with content omitted/null. The server imports valid UTF-8 bytes, records raw
   hash/EOL/root identity and returns target metadata, without returning source.
2. Use `patchdiff_read_target` for bounded canonical text and
   `patchdiff_find_occurrences` to verify exact matches. Call
   `patchdiff_submit_edits` with the observed version or hash and your ordered
   match/replace edits. Acceptance updates the PostgreSQL working copy.
3. Call `patchdiff_save(target_file_id=..., expected_target_version=...,
   sync_workspace=true)`. Do not enable `export_after_save` when a receipt suffices.
4. On `saved`, verify `workspace_sync.disk_sha256` and the file. The receipt also
   contains `synced_path`, `bytes_written`, `content_eol`, `publication=installed`
   and `durability=confirmed`; it contains no full target text.
5. On external divergence, stop and inspect/reinitialize from the file. On a
   partial/unknown outcome, inspect both disk and database before proceeding.

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
