# Native PostgreSQL to Docker Compose Migration Guide

## Overview

In PR #23, application-managed native PostgreSQL provisioning (`initdb`, `pg_ctl`, and `--route native` / `--route both`) was removed (`PR23-R5-ARCH-002`). PatchDIFF now manages only one bundled database runtime: **PostgreSQL 16.3 Alpine via Docker Compose** (or connects to an already-running external PostgreSQL 16+ instance via `patchdiff-mcp-setup --external-database`).

> [!IMPORTANT]
> **Safety Rules — Read Before Migrating**
> - **Do NOT delete `PGDATA`**: PatchDIFF never deletes, modifies, or automatically stops any preexisting native PostgreSQL cluster directory (such as `~/.local/share/patchdiff-runtime/pgdata`).
> - **Do NOT auto-stop existing native PostgreSQL**: Keep the existing native PostgreSQL server running and untouched until the restored Docker database has been migrated and verified against all integrity and replay checks.
> - **Do NOT move or bind-mount an existing native `PGDATA` directory onto Docker's volume directory**: Native host binaries and Alpine container PostgreSQL builds have incompatible OS collations and binary layouts. Always migrate logically using `pg_dump` and `pg_restore` into a **new empty database**.
> - **Sensitive Document Data**: Database dumps (`pg_dump` archives) contain full canonical document text, edit logs, and snapshots. Store backup files only in private operator-owned directories (`0700` directory, `0600` archive file) and never in world-readable `/tmp` or version control.

---

## Step 1: Read-Only Dry-Run Inventory (No Restore or Deletion)

Before exporting or modifying any service, run this read-only dry-run command path against the existing native PostgreSQL instance to record target counts, versions, hashes, and append-only log counts. This dry-run path cannot restore, mutate, or delete any data:

```bash
# Set the explicit read-only connection URL for your existing native PostgreSQL cluster
export SOURCE_NATIVE_DSN="postgresql://patchdiff_admin@127.0.0.1:5434/patchdiff"

# Dry-run inventory query (read-only transaction)
psql "$SOURCE_NATIVE_DSN" --no-psqlrc -v ON_ERROR_STOP=1 <<'SQL'
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT target_file_id, filename, version, current_hash
  FROM cloud_target_files
 ORDER BY target_file_id;
SELECT status, count(*) AS log_count
  FROM append_only_pdcp_logs
 GROUP BY status
 ORDER BY status;
SELECT count(*) AS snapshot_count FROM target_snapshots;
SELECT count(*) AS manifest_count FROM append_only_manifest_ledger;
ROLLBACK;
SQL
```

Also verify the dump archive table-of-contents in dry-run mode (after creating the dump in Step 2) without connecting to or restoring any target database:

```bash
pg_restore --list "$HOME/.local/share/patchdiff-Migration-Backup/patchdiff-native.dump"
```

---

## Step 2: Export Existing Native Database to Private Storage

Create a private `0700` operator directory and run `pg_dump --format=custom --no-owner --no-acl` against the explicit original native DSN:

```bash
BACKUP_DIR="$HOME/.local/share/patchdiff-Migration-Backup"
install -d -m 0700 "$BACKUP_DIR"
umask 0077

pg_dump \
  --format=custom \
  --no-owner \
  --no-acl \
  --file="$BACKUP_DIR/patchdiff-native.dump" \
  "$SOURCE_NATIVE_DSN"

chmod 0600 "$BACKUP_DIR/patchdiff-native.dump"
sha256sum "$BACKUP_DIR/patchdiff-native.dump" > "$BACKUP_DIR/patchdiff-native.dump.sha256"
```

---

## Step 3: Provision Fresh Docker Compose PostgreSQL and Restore into a New Empty DB

1. Provision the checkout-scoped Docker Compose PostgreSQL service on loopback `127.0.0.1:5433`:

```bash
patchdiff-mcp-setup
```

2. Create a **new empty database** (for example, `patchdiff_restored`) inside the Docker PostgreSQL instance using the operator bootstrap credentials from `~/.local/share/patchdiff-runtime/db_bootstrap_credentials.json`, and restore the custom dump with `pg_restore --no-owner --no-acl`:

```bash
# Construct target bootstrap DSN pointing to the new empty database
psql "$TARGET_DOCKER_POSTGRES_DSN" -v ON_ERROR_STOP=1 -c "CREATE DATABASE patchdiff_restored OWNER patchdiff_bootstrap;"

pg_restore \
  --no-owner \
  --no-acl \
  --exit-on-error \
  --dbname="$TARGET_DOCKER_RESTORED_DSN" \
  "$BACKUP_DIR/patchdiff-native.dump"
```

3. Run Alembic upgrade and enforce least-privilege role grants (`patchdiff_bootstrap`, `patchdiff_host`, `patchdiff_agent`) on the restored database:

```bash
# All three URLs target the restored database, with distinct private role secrets.
PATCHDIFF_BOOTSTRAP_DATABASE_URL="$TARGET_DOCKER_RESTORED_SQLALCHEMY_URL" \
PATCHDIFF_HOST_DATABASE_URL="$TARGET_DOCKER_RESTORED_HOST_URL" \
PATCHDIFF_AGENT_DATABASE_URL="$TARGET_DOCKER_RESTORED_AGENT_URL" \
  patchdiff-mcp-setup --external-database
```

---

## Step 4: Verify Target IDs, Versions, Hashes, Log Counts, and Replay Before Cutover

Compare the restored Docker database against the original native database before switching any client configuration:

1. **Compare target IDs, versions, and SHA-256 hashes:**

```bash
psql "$SOURCE_NATIVE_DSN" --tuples-only --no-align -c \
  "SELECT target_file_id, version, current_hash FROM cloud_target_files ORDER BY target_file_id;" \
  > "$BACKUP_DIR/source_targets.txt"

psql "$TARGET_DOCKER_RESTORED_DSN" --tuples-only --no-align -c \
  "SELECT target_file_id, version, current_hash FROM cloud_target_files ORDER BY target_file_id;" \
  > "$BACKUP_DIR/restored_targets.txt"

diff -u "$BACKUP_DIR/source_targets.txt" "$BACKUP_DIR/restored_targets.txt"
```

2. **Compare append-only log, manifest, and snapshot counts:**

```bash
psql "$SOURCE_NATIVE_DSN" --tuples-only --no-align -c \
  "SELECT (SELECT count(*) FROM append_only_pdcp_logs), (SELECT count(*) FROM append_only_manifest_ledger), (SELECT count(*) FROM target_snapshots);" \
  > "$BACKUP_DIR/source_counts.txt"

psql "$TARGET_DOCKER_RESTORED_DSN" --tuples-only --no-align -c \
  "SELECT (SELECT count(*) FROM append_only_pdcp_logs), (SELECT count(*) FROM append_only_manifest_ledger), (SELECT count(*) FROM target_snapshots);" \
  > "$BACKUP_DIR/restored_counts.txt"

diff -u "$BACKUP_DIR/source_counts.txt" "$BACKUP_DIR/restored_counts.txt"
```

3. **Run deterministic replay verification (`patchdiff_replay`) across every target:**
   Verify that `status == "success"`, `materialized_state_matches == true`, and all four `materialized_state_checks` (`content_matches`, `stored_hash_matches`, `recomputed_hash_matches`, `version_matches`) return `true` for every target in the restored Docker database.

> [!CAUTION]
> **On Any Mismatch: Stop Immediately**
> If `diff` reports any discrepancy or `patchdiff_replay` fails on any target, **abort the cutover immediately**. Leave the original native PostgreSQL instance and its `PGDATA` directory completely untouched and investigate the discrepancy before attempting cutover.
