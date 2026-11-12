# Profile Compatibility & Deployment Matrix

This document provides a comprehensive compatibility matrix and reproducible setup instructions for running PatchDIFF profiles across operating systems and Docker environments.

---

## 1. Compatibility Overview

PatchDIFF profiles fall into two operational classes:

1. **Workspace Synchronizer Profiles (`observed_workspace`, `workspace`):**
   - Manage real filesystem directories (`PATCHDIFF_WORKSPACE_ROOT`).
   - **POSIX Requirement:** Directory writebacks use descriptor-relative operations (`openat`, `O_NOFOLLOW`, `O_DIRECTORY`, and `fcntl.flock`) to guard against symlinks, path traversal, and race conditions.
   - Requires a POSIX environment: **Linux, WSL2, macOS, or Docker**. Bare Windows cmd/PowerShell lacks `fcntl.flock`.
2. **Inline Ledger Profiles (`observed_v2`, `editor`, `unobserved_editor`, `hybrid_editor`, `full`, etc.):**
   - Inline workflows operate on PostgreSQL targets. They run on native Windows, WSL2, Linux and macOS without workspace filesystem locks.
   - The trusted `full` profile can also initialize and publish workspace files on supported POSIX filesystems.

---

## 2. OS & Docker Configuration Compatibility Matrix

| Profile | Tools | Bare Windows | WSL2 (Ubuntu/Debian) | Native Linux | macOS | Docker Desktop (WSL2) | Docker Engine (Linux) | Docker Desktop (macOS) | Fully Containerized |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`observed_workspace`** *(default)* | 7 | ❌ Incompatible¹ | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`workspace`** | 5 | ❌ Incompatible¹ | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`observed_v2`** | 5 | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`observed_editor`** | 4 | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`unobserved_editor`**| 3 | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`hybrid_editor`** | 1 | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`editor`** | 7 | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`observed`** | 6 | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`unobserved`** | 5 | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |
| **`full`** | 18 | ⚠️ Inline only¹| ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported | ✅ Supported |

> ¹ *Note for Bare Windows:* Although inline-content `patchdiff_initialize_target` has no POSIX filesystem dependency, the workspace startup preflight check (`_check_workspace_startup`) executes before the MCP handshake and requires POSIX descriptor-relative operations and directory locks (`fcntl.flock`). Because bare Windows cmd/PowerShell lacks these primitives, the server refuses to start in `workspace` or `observed_workspace` profiles even for inline-only use. On Windows, run PatchDIFF inside WSL2 or Docker to use workspace profiles, or specify `--profile observed_v2` or `--profile editor` for native bare Windows inline editing.

---

## 3. Dependency Requirements per Profile

| Profile | Python 3.11+ | PostgreSQL 16+ | Node.js 22+ (Waymark) | `PATCHDIFF_WORKSPACE_ROOT` | POSIX `flock` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`observed_workspace`** *(default)* | ✅ Required | ✅ Required | ✅ Required | ✅ Mandatory | ✅ Required |
| **`workspace`** | ✅ Required | ✅ Required | ❌ Pure Python | ✅ Mandatory | ✅ Required |
| **`observed_v2`** | ✅ Required | ✅ Required | ✅ Required | ❌ Not used | ❌ Not needed |
| **`observed_editor`** | ✅ Required | ✅ Required | ✅ Required | ❌ Not used | ❌ Not needed |
| **`unobserved_editor`**| ✅ Required | ✅ Required | ❌ Pure Python | ❌ Not used | ❌ Not needed |
| **`hybrid_editor`** | ✅ Required | ✅ Required | ❌ Pure Python | ❌ Not used | ❌ Not needed |
| **`editor`** | ✅ Required | ✅ Required | ✅ Required | ❌ Not used | ❌ Not needed |
| **`observed`** | ✅ Required | ✅ Required | ✅ Required | ❌ Not used | ❌ Not needed |
| **`unobserved`** | ✅ Required | ✅ Required | ❌ Pure Python | ❌ Not used | ❌ Not needed |
| **`full`** | ✅ Required | ✅ Required | ✅ Required | ⚠️ Optional | ⚠️ If sync |

---

## 4. Reproducible Setup Instructions by Environment

Use the server version that matches your migrations. For host installs, see the
[workspace setup](../../guides/workspace-quickstart.md#setup) and install
[pinned Waymark dependencies](../../guides/workspace-quickstart.md#seven-tool-structural-setup)
for profiles that use structural tools. Before running any migration command
on an existing database, follow the
[0007 cutover procedure](../../guides/workspace-quickstart.md#upgrade-an-existing-database-to-0007).
PatchDIFF serves MCP over stdio. Configure the host to launch the server
command shown in each recipe and exchange MCP messages over stdin/stdout.

### Configuration A: Windows with Docker Desktop (WSL2 Backend) (Recommended for Windows)

This configuration runs the PatchDIFF server inside WSL2 while PostgreSQL runs in Docker Desktop, with full support for the default `observed_workspace` profile.

#### Step 1: Enable Docker Desktop WSL Integration
1. Open Docker Desktop on Windows.
2. Go to **Settings > Resources > WSL Integration**.
3. Enable **Turn on integration with additional distros** and check your distribution (e.g. `Ubuntu`).
4. Click **Apply & Restart**.

#### Step 2: Start PostgreSQL Container
From PowerShell or inside your WSL terminal in the repository root:
```bash
docker compose up -d --wait postgres
```
Verify the container is healthy:
```bash
docker ps --filter "name=patchdiff-postgres"
```

#### Step 3: Configure Environment in WSL2
Inside your WSL distribution, export the required environment variables:
```bash
# Point to Docker PostgreSQL (accessible via localhost in WSL2)
export PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"

# Point to your repository or working directory
export PATCHDIFF_WORKSPACE_ROOT="$(pwd)"

# Profile defaults to observed_workspace automatically
export PATCHDIFF_MCP_PROFILE="observed_workspace"
```

#### Step 4: Run Database Migrations
```bash
patchdiff-mcp --migrate
```

#### Step 5: Start the MCP Server
```bash
patchdiff-mcp
```

---

### Configuration B: Bare Windows (No WSL2, Docker Desktop Host)

When running directly on Windows without WSL2, workspace filesystem sync is disabled due to missing POSIX descriptor locks. Use inline ledger profiles such as `observed_v2`, `editor`, or `full`.

#### Step 1: Start PostgreSQL via Docker Desktop
In PowerShell from the repository root:
```powershell
docker compose up -d --wait postgres
```

#### Step 2: Set Environment Variables in PowerShell
```powershell
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
# Select an inline profile (e.g. observed_v2 or editor)
$env:PATCHDIFF_MCP_PROFILE = "observed_v2"
```

#### Step 3: Run Migrations and Start Server
```powershell
patchdiff-mcp --migrate
patchdiff-mcp
```

---

### Configuration C: Native Linux with System Docker Engine

Full native Linux deployment with zero translation overhead.

#### Step 1: Start PostgreSQL
```bash
docker compose up -d --wait postgres
```

#### Step 2: Set Environment Variables
```bash
export PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
export PATCHDIFF_WORKSPACE_ROOT="/path/to/your/project"
export PATCHDIFF_MCP_PROFILE="observed_workspace"
```

#### Step 3: Apply Migrations and Launch
```bash
patchdiff-mcp --migrate
patchdiff-mcp
```

---

### Configuration D: macOS with Docker Desktop for Mac

macOS supports POSIX file locking natively, allowing `observed_workspace` to run directly on the host with Dockerized PostgreSQL.

#### Step 1: Start PostgreSQL
```bash
docker compose up -d --wait postgres
```

#### Step 2: Configure Environment
```bash
export PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
export PATCHDIFF_WORKSPACE_ROOT="$(pwd)"
export PATCHDIFF_MCP_PROFILE="observed_workspace"
```

#### Step 3: Apply Migrations and Launch
```bash
patchdiff-mcp --migrate
patchdiff-mcp
```

---

### Configuration E: Fully Containerized Deployment (Server + Database)

To run the PatchDIFF stdio server and PostgreSQL in containers, build the
server image from the matching source checkout. The MCP host launches an
attached server container for each connection.

#### `Dockerfile` for PatchDIFF MCP Server
```dockerfile
FROM python:3.11-slim

# Install Node.js 22 for Waymark AST discovery
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY backend/ ./backend/
COPY integrations/ ./integrations/

# Install Python dependencies and package
RUN pip install --no-cache-dir -e .

# Install pinned Waymark engine
RUN npm --prefix integrations/waymark ci --omit=dev

ENV PATCHDIFF_WAYMARK_MODE=resident
ENV PATCHDIFF_MCP_PROFILE=observed_workspace

ENTRYPOINT ["patchdiff-mcp"]
```

#### `docker-compose.server.yml`
```yaml
services:
  postgres:
    image: postgres:16.3-alpine
    container_name: patchdiff-postgres
    environment:
      POSTGRES_DB: patchdiff
      POSTGRES_USER: patchdiff
      POSTGRES_PASSWORD: patchdiff
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U patchdiff -d patchdiff"]
      interval: 5s
      timeout: 5s
      retries: 10
    volumes:
      - patchdiff_postgres_data:/var/lib/postgresql/data

  patchdiff:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PATCHDIFF_DATABASE_URL: "postgresql+psycopg://patchdiff:patchdiff@postgres:5432/patchdiff"
      PATCHDIFF_WORKSPACE_ROOT: "/workspace"
      PATCHDIFF_MCP_PROFILE: "observed_workspace"
    volumes:
      - ./target_project:/workspace:rw
    stdin_open: true
    tty: false

volumes:
  patchdiff_postgres_data:
```

Start PostgreSQL, build the server image, and apply migrations before the
client launches an MCP connection.

```bash
docker compose -f docker-compose.server.yml up -d --wait postgres
docker compose -f docker-compose.server.yml build patchdiff
docker compose -f docker-compose.server.yml run --rm -T patchdiff --migrate
```

Configure the MCP client to launch `docker compose -f /absolute/path/to/docker-compose.server.yml run --rm -T patchdiff`
with stdin and stdout attached.

---

## 5. Port Conflicts & Troubleshooting

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| `Bind for 0.0.0.0:5432 failed: port is already allocated` | Native PostgreSQL daemon already running on port 5432 | Stop native postgres (`sudo systemctl stop postgresql`) or map Docker to host port `5433:5432`. |
| `PatchDIFF workspace startup: PATCHDIFF_WORKSPACE_ROOT is not configured` | Server started with default `observed_workspace` without setting workspace directory | Export `PATCHDIFF_WORKSPACE_ROOT="$(pwd)"` or pass `--profile observed_v2` / `--profile editor` for inline editing. |
| Docker Desktop GUI shows `0 containers running` | Containers started under an isolated WSL distro without Docker Desktop integration | Enable **Settings > Resources > WSL Integration** for your specific distro in Docker Desktop. |
| `ModuleNotFoundError: No module named 'fcntl'` | Running `observed_workspace` or `workspace` directly on bare Windows | Switch to WSL2, Docker, or select an inline profile (`--profile observed_v2` / `--profile editor`). |

For host configuration, WSL2 resource compaction, and background process management, see the [Troubleshooting & Operations Guide](../../guides/troubleshooting.md).
