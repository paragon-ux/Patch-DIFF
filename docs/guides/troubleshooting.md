# PatchDIFF Troubleshooting & Operations Guide

This guide provides operational troubleshooting, environment diagnostics, and configuration best practices for running PatchDIFF across Windows, WSL2, macOS, and Linux environments.

For operating system support matrices and reproducible Docker setup instructions, see the [Profile Compatibility & Deployment Matrix](../spec/profiles/profile-compatibility.md).

---

## 1. WSL2 Setup, Memory Limits & Resource Reclamation

When running PatchDIFF on Windows via WSL2, default WSL configurations can lead to memory exhaustion, high virtual disk (`ext4.vhdx`) growth, or lingering loop-device file locks.

### A. Recommended `.wslconfig` Tuning

Create or edit `%USERPROFILE%\.wslconfig` in Windows (e.g. `C:\Users\<YourUsername>\.wslconfig`):

```ini
[wsl2]
# Restrict WSL2 RAM usage so it does not starve Windows host processes
memory=8GB

# Allocate CPU cores (typically half of host physical cores)
processors=4

# WSL 2.0+: Automatically reclaim cached memory back to the Windows OS
autoMemoryReclaim=gradual

# Enable automatic sparse virtual disk compaction
sparseVhd=true

# Set swap storage limit
swap=4GB
```

After modifying `.wslconfig`, restart WSL from a Windows PowerShell or Command Prompt:

```powershell
wsl --shutdown
```

### B. Clearing Loop Devices & Hanging Processes

If you encounter `No space left on device`, unkillable background worker threads, or locked SQLite/Postgres temp files:

1. Terminate all WSL instances cleanly:
   ```powershell
   wsl --shutdown
   ```
2. Verify all distributions have stopped:
   ```powershell
   wsl --list --verbose
   ```
3. Restart your distribution:
   ```powershell
   wsl -d Ubuntu
   ```

### C. Reclaiming Disk Space from `ext4.vhdx`

WSL2 virtual disks grow dynamically as files are created, but deleting files inside Linux does not automatically shrink the `.vhdx` on Windows unless sparse VHD is enabled.

To reclaim disk space manually:
1. Shut down WSL: `wsl --shutdown`
2. Run `diskpart` in Windows PowerShell (Admin):
   ```cmd
   diskpart
   select vdisk file="C:\Users\<YourUsername>\AppData\Local\Packages\<DistroPackage>\LocalState\ext4.vhdx"
   compact vdisk
   exit
   ```

---

## 2. PostgreSQL Database & Docker Container Visibility

PatchDIFF requires PostgreSQL 16+ with ACID transaction isolation. Depending on your environment, you may run PostgreSQL as a native host service or inside a container.

### A. Why Docker Desktop May Not Show Your Containers

If you start PostgreSQL or inspect containers and Docker Desktop shows "0 containers running", this usually occurs because:

- **Native Linux Service:** If PostgreSQL was installed via `apt install postgresql`, it runs directly under Linux `systemd`, completely independent of Docker.
- **Standalone Docker inside WSL2:** If you installed Docker Engine directly inside an Ubuntu WSL distro rather than using Docker Desktop's WSL Integration, containers run in that distro's isolated daemon and will not appear in the Windows Docker Desktop GUI.
- **Enabling Docker Desktop WSL Integration:**
  1. Open Docker Desktop Settings on Windows.
  2. Navigate to **Resources > WSL Integration**.
  3. Toggle **Enable integration with additional distros** and select your active distribution (e.g., `Ubuntu`).
  4. Now `docker ps` inside WSL and the Docker Desktop GUI will observe the same containers.

### B. Resolving Port 5432 Conflicts

If you attempt to run `docker compose up -d` and see:
```text
Error response from daemon: driver failed programming external connectivity on endpoint ...: Bind for 0.0.0.0:5432 failed: port is already allocated
```

This indicates a native PostgreSQL service is already listening on port 5432.

**Solution 1: Use the existing native PostgreSQL**
Check if the native service is running:
```bash
sudo systemctl status postgresql
```
If running, ensure the `patchdiff` database and user exist, then run migrations:
```bash
patchdiff-mcp --migrate
```

**Solution 2: Stop the native PostgreSQL and use Docker**
```bash
sudo systemctl stop postgresql
sudo systemctl disable postgresql
docker compose up -d
patchdiff-mcp --migrate
```

**Solution 3: Remap the Docker port**
In `docker-compose.yml`, map the host port to `5433:5432`:
```yaml
ports:
  - "5433:5432"
```
Then configure your database URL accordingly:
```bash
export PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@localhost:5433/patchdiff"
```

---

## 3. Platform Differences & Workspace I/O Semantics

PatchDIFF supports two editing paradigms:

1. **Workspace Profiles (`observed_workspace` / `workspace`):**
   - Reads files directly from `PATCHDIFF_WORKSPACE_ROOT`, commits atomic AST-scoped edits to PostgreSQL, and flushes canonical checkpoint bytes back to disk during `patchdiff_save`.
   - **POSIX Requirement:** To prevent symlink attacks, directory traversal, and race conditions, the workspace synchronizer requires POSIX descriptor-relative operations (`openat`, `O_NOFOLLOW`, `O_DIRECTORY`, and `flock`).
   - On Windows, run the PatchDIFF server inside **WSL2** or a **Docker container** when using workspace synchronization.

2. **Inline Profiles (`observed_v2`, `editor`, `full`):**
   - Edit targets are initialized via direct content submission or upload, and changes are tracked entirely in the PostgreSQL append-only ledger without touching the host filesystem.
   - Compatible natively across Windows, macOS, and Linux without requiring POSIX file descriptor locks.

---

## 4. Security Architecture: Test Isolation Boundary

### Critical Safety Advisory: Do Not Run Internal Tests in Production

> [!CAUTION]
> **Never run repository test suites (`pytest backend/tests/...`) on user or production machines.**
> 
> The internal integration tests (`backend/tests/integration/`) are designed strictly for isolated development and CI environments. During test execution, the test harness automatically connects to the configured PostgreSQL instance, creates ephemeral test databases (e.g. `patchdiff_test_*`), executes schema drops, and performs high-frequency concurrent writes.
> 
> Running tests on production databases or end-user workstations may lead to accidental schema rollbacks, database bloat, or lock contention.
