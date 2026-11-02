# Trusted MCP host setup on Linux and WSL2

PatchDIFF has two MCP capabilities: the five-tool default `observed_v2` editor and the operator's 24-tool `full` connection. The model interacts through the host. A profile filters tool discovery and calls; it is not authentication.

## Prerequisites and identities

The supported isolation claim requires Linux/WSL2 POSIX permissions, Python 3.11+ with venv/pip, Node 22, Docker Compose v2 and PostgreSQL 16.3 Alpine. An administrator explicitly creates two unprivileged nonlogin users:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin patchdiff-mcp-agent
sudo useradd --system --no-create-home --shell /usr/sbin/nologin patchdiff-model
```

The third identity is the trusted operator. Neither service nor model belongs to sudo, Docker or another privileged group. Neither can traverse operator-private directories or access the Docker socket. The model cannot read service configuration or secrets, nor impersonate the service. Setup and default editor startup fail closed when the three identities are missing. Running the model under the operator or editor-service UID is unsupported.

Install the Python runtime under an operator-controlled absolute path readable/executable by the service, without putting secrets there. The host configuration stays private to the operator. Only the operator may use the trusted launcher:

```bash
sudo -n -u patchdiff-mcp-agent -- /absolute/installed/bin/patchdiff-mcp
```

The administrator configures sudo for this exact operator, account and installed executable; do not give the model permission to run this command. The host starts the service and hands the model only its MCP transport. A model shell runs as `patchdiff-model`.

## Database setup

As operator, run:

```bash
patchdiff-mcp-setup
patchdiff-mcp-daemon status
```

The sole managed database is a checkout-scoped PostgreSQL 16.3 Alpine Compose service on `127.0.0.1:5433`. Use `--port` or `PATCHDIFF_POSTGRES_PORT` to change the port. `start`, `stop`, `restart` and `status` manage only this verified project. Stop preserves its container and named volume; foreign or ambiguous labels fail before mutation. Status neither creates credentials nor starts containers. Obsolete route/native flags have been removed and argparse rejects them normally.

Setup generates three distinct secrets once, never silently rotating them:

| SQL role | Secret file and owner | Capability |
| --- | --- | --- |
| `patchdiff_bootstrap` | operator `<runtime_dir>/db_bootstrap_credentials.json` | Superuser for setup/migrations only; never MCP |
| `patchdiff_host` | operator `<runtime_dir>/db_host_credentials.json` | Nonsuperuser trusted `full` service |
| `patchdiff_agent` | service `/var/lib/patchdiff-mcp-agent/db_agent_credentials.json` | Allowlisted editor DML only |

Each file is `0600`, in a respective owner-controlled `0700` directory. Installation of the service secret requires an explicit privileged ownership operation; failure aborts. Symlinks, hardlinks, unexpected owners/modes and known passwords are rejected. Do not put bootstrap or host secrets in an editor environment or model-visible MCP config. Never run a full MCP process as a database superuser.

Setup upgrades through `20261101_0008`, applies explicit table/column grants, verifies both database roles and tests both MCP interfaces. An intentional credential reset is a separate operator maintenance operation: stop the affected connection, preserve the private old credential for recovery, explicitly change that role's password through the bootstrap connection, atomically install a newly validated owner-correct single-role file, restart and verify `current_user`. Never delete a credential to trigger an unexplained rotation against an existing volume.

For an already-running external PostgreSQL 16+ database, privately supply all three same-endpoint URLs, using the three roles above:

```bash
patchdiff-mcp-setup --external-database
```

The required variables are `PATCHDIFF_BOOTSTRAP_DATABASE_URL`, `PATCHDIFF_HOST_DATABASE_URL` and `PATCHDIFF_AGENT_DATABASE_URL`. This path migrates under bootstrap and validates roles; it invokes no Docker, `initdb` or `pg_ctl`. It never owns the external server's stop/restart. A trusted launcher may explicitly supply `PATCHDIFF_DATABASE_URL` for its single process; startup checks its exact profile role and live PostgreSQL `current_user`. No default DSN/password fallback exists.

Existing native clusters and PGDATA stay untouched. Follow [the non-destructive migration guide](NATIVE_POSTGRES_MIGRATION.md) for an operator-led logical backup, restore into a new empty database and integrity/replay comparison before cutover.

## Host/editor lifecycle

The operator starts its separate connection with `PATCHDIFF_MCP_PROFILE=full` and operator-controlled host credentials. It initializes a target and supplies the resulting target ID to the editor. The service's default connection advertises exactly:

- `patchdiff_read_target`
- `patchdiff_find_occurrences`
- `patchdiff_list_scopes`
- `patchdiff_observe_scopes`
- `patchdiff_commit_bundle`

Initialization, SAVE, replay, finalization and export paging are denied on the editor transport. After editing, the operator calls `patchdiff_finalize_target` with a request key and version/hash guard. The database commits verified SAVE, receipt and immutable export chunks atomically. Retry the same key after response loss; it does not create another checkpoint.

Host disk installation is a separate operation. Use an explicit trusted target-to-path mapping and operator-private authorized root, permanent shared flock marker, expected preimage and verified receipt hash. Report `durability_uncertain` after a successful rename whose directory fsync fails. A same-UID writer ignoring the lock is outside the supported cooperative contract. See [the host guide](HOST_INTEGRATION_GUIDE.md).

## Installation and release boundary

The candidate distribution is exactly `patchdiff-mcp`, version `0.1.0`; console scripts include `patchdiff`, `patchdiff-mcp`, `patchdiff-mcp-setup` and `patchdiff-mcp-daemon`. A prepublication check uses `uvx --from /absolute/path/to/local.whl patchdiff` in a fresh cache. This does not establish availability of a PyPI-hosted release.

No PR test publishes. Name ownership on PyPI/TestPyPI, independent protected-environment approval and matching Trusted Publisher settings require actual owner evidence. Live Glama claim/reindex verification occurs only after a separately authorized merge. See [release readiness](../standards/RELEASE_READINESS.md).
