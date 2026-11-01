# Claude Desktop MCP Setup

PatchDIFF's Claude Desktop adapter is a local stdio MCP server, not a localhost HTTP MCP server.

Claude Desktop launches the Python process directly and talks to it over stdin/stdout:

```text
Claude Desktop / MCP Host
  -> launches
backend/app/mcp/external_adapter.py (or `patchdiff-mcp` console script)
  -> uses either independent PostgreSQL route:
     - `native` route: user-space PostgreSQL cluster on 127.0.0.1:5434
     - `docker` route: Docker Compose `patchdiff-postgres` container on 127.0.0.1:5433
```

Do not connect Claude Desktop to `http://127.0.0.1:8000` for this setup. The FastAPI server is useful for health checks and future HTTP API work, but the current Claude Desktop MCP path is the stdio adapter.

### UTF-8 transport

The adapter entry point configures stdin/stdout as strict UTF-8, including Windows pipes and environments with a different PYTHONIOENCODING value. Hosts must send UTF-8 JSON-RPC bytes. ASCII Unicode escapes remain supported; malformed UTF-8 wire bytes are not silently repaired. Escaped invalid edit strings still follow the audited domain-validation contract.

When running an older revision without the UTF-8 transport fix, add `"PYTHONIOENCODING": "utf-8"` to the MCP server environment. Without it, literal Unicode requests can be accepted with incorrectly decoded text; this was reproduced as input corruption rather than a stdout crash. The workaround remains compatible with fixed revisions.

Restart or refresh the server through the host after command/environment changes, then verify the connection. Claude Desktop restart steps appear below; other hosts have their own refresh lifecycle.

## 1. Provision Postgres & Run Migrations (`native`, `docker`, or `both`)

PatchDIFF provides a unified setup and daemon lifecycle CLI (`patchdiff-mcp setup` / `patchdiff-mcp daemon`) supporting two independent, non-conflicting PostgreSQL routes:

- **`native` (`127.0.0.1:5434`)**: User-space PostgreSQL cluster managed via `initdb` / `pg_ctl` in `~/.local/share/patchdiff-runtime/pgdata` (ideal for WSL/Linux without requiring Docker Desktop).
- **`docker` (`127.0.0.1:5433`)**: Docker Compose `patchdiff-postgres` (`postgres:16.3-alpine`) container mapped to `127.0.0.1:5433:5432`.

From the Patch-DIFF repo root (or with the `patchdiff-mcp` package installed):

```bash
# Provision both routes, run Alembic migrations through head (20261031_0007),
# bootstrap/verify the Waymark JS bridge, and smoke-test the MCP stdio adapter:
patchdiff-mcp setup --route both

# Or provision a single route:
patchdiff-mcp setup --route native
patchdiff-mcp setup --route docker
```

Both routes support identical daemon lifecycle commands:

```bash
patchdiff-mcp daemon start   --route <native|docker|both>
patchdiff-mcp daemon stop    --route <native|docker|both>
patchdiff-mcp daemon restart --route <native|docker|both>
patchdiff-mcp daemon status  --route <native|docker|both>
```

You can also run Docker Compose and Alembic manually if preferred (supplying a high-entropy `POSTGRES_PASSWORD` in `.env` or environment):

```powershell
$env:POSTGRES_USER = "patchdiff_admin"
$env:POSTGRES_PASSWORD = "<your-high-entropy-admin-secret>"
docker compose up -d postgres
$env:PYTHONPATH = "backend"
$env:PATCHDIFF_DATABASE_URL = "postgresql+psycopg://patchdiff_admin:<your-high-entropy-admin-secret>@127.0.0.1:5433/patchdiff"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

You do not need to run `uvicorn` for the Claude Desktop MCP tools. Claude Desktop launches `app.mcp.external_adapter` (or the `patchdiff-mcp` console script) directly.

Apply migrations through `20261031_0007` so the typed ledger, request idempotency, source line endings, bundled scope evidence, and durable target finalizations (`target_finalizations`) are available.

## 2. Smoke Test The Adapter

From the repo root:

```powershell
$env:PYTHONPATH = "backend"
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | .\.venv\Scripts\python.exe -m app.mcp.external_adapter
```

Expected response includes:

```json
{
  "serverInfo": {
    "name": "patchdiff-mvp"
  }
}
```

If this works, Claude Desktop should be able to launch the adapter with the same Python executable and environment.

## 3. Open Claude Desktop Config

In Claude Desktop:

```text
Settings -> Developer -> Edit Config
```

On Windows, the config is usually:

```text
%APPDATA%\Claude\claude_desktop_config.json
```

Anthropic documents local Claude Desktop MCP servers separately from remote connectors. Local servers run on your machine, while remote connectors are configured through the Claude connector flow and must be reachable from Anthropic's infrastructure.

References:

- [Getting Started with Local MCP Servers on Claude Desktop](https://support.anthropic.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
- [Get started with custom connectors using remote MCP](https://support.anthropic.com/en/articles/11175166-getting-started-with-custom-integrations-using-remote-mcp)

## 4. Add PatchDIFF

The default startup profile is `observed_v2` (5 advertised and callable tools: `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, and `patchdiff_commit_bundle`).
Use `PATCHDIFF_MCP_PROFILE=full` in the server environment for trusted upload/initialization/export/finalization workflows that need the complete 24-tool catalog. Legacy compatibility profiles (`editor` [7], `observed` [6], `unobserved` [5], `observed_editor` [4], `unobserved_editor` [3], and `hybrid_editor` [1]) remain available with a once-per-process stderr migration notice.
Unknown profiles fail startup, and requests cannot override the session's immutable selection.
[Exact tool lists and structural batches](../spec/STRUCTURAL_BATCH_EDITING.md).

You can auto-populate your MCP configuration file using:

```bash
patchdiff-mcp setup --route both --update-mcp-config --mcp-route <native|docker> --mcp-config /path/to/mcp_config.json
```

Or add the configuration manually using your virtual environment Python (pointing `PATCHDIFF_DATABASE_URL` to port `5434` for `native` or port `5433` for `docker`):

```json
{
  "mcpServers": {
    "patchdiff": {
      "type": "stdio",
      "command": "C:\\path\\to\\Patch-DIFF\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "app.mcp.external_adapter"
      ],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\Patch-DIFF\\backend",
        "PATCHDIFF_DB_CREDENTIALS_FILE": "C:\\Users\\USER\\.local\\share\\patchdiff-runtime\\db_credentials.json",
        "PATCHDIFF_ACTIVE_ROUTE": "docker",
        "PATCHDIFF_MCP_PROFILE": "observed_v2",
        "PATCHDIFF_WAYMARK_MODE": "resident"
      }
    }
  }
}
```

The `"type": "stdio"` field makes the transport explicit. If an older Claude Desktop build rejects that field, remove only `"type": "stdio"` and keep `command`, `args`, and `env`.

## 5. Restart Claude Desktop

Fully quit Claude Desktop, then reopen it. On Windows, make sure Claude Desktop is not just minimized to the tray. Quit it completely before reopening.

## 6. Verify Tools In Claude Desktop

Open a new chat and check the MCP/connectors UI:

```text
+ button near the message box, labeled "+" -> Connectors
```

Under the default `observed_v2` profile, you will see the 5 streamlined editing tools:
- `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`

Under `PATCHDIFF_MCP_PROFILE=full`, you will see all 24 tools:

- **Target lifecycle & finalization**: `patchdiff_handle_upload`, `patchdiff_initialize_target`, `patchdiff_get_target`, `patchdiff_export_target`, `patchdiff_finalize_target`, `patchdiff_read_finalized_export`
- **Authoritative reads, structural scopes & exact search**: `patchdiff_read_target`, `patchdiff_read_lines`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`
- **Guarded edit submission**: `patchdiff_submit_edits` (`patchdiff-tx/1`), `patchdiff_submit_operations` (match/span, `patchdiff-tx/2`), `patchdiff_submit_observed_operations` (single/batch observed scopes), `patchdiff_submit_replacement` (sole replace_all, `patchdiff-tx/3`), `patchdiff_submit_pdcp` (legacy `.pdcp`)
- **Checkpoints, replay & audit**: `patchdiff_save`, `patchdiff_replay`, `patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`
- **Advisory preview & legacy wrappers**: `patchdiff_preview` (bounded keyless/no-audit evaluation), `patchdiff_build_prompt_context` (bounded prefix convenience), and deprecated `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`

For guidance on how the host/model interacts with these tools (reading before proposing, supplying guards, handling rejections with retry lineage, and client request idempotency), see [HOST_INTEGRATION_GUIDE.md](HOST_INTEGRATION_GUIDE.md).

## Important Gotcha

This can work:

```json
"command": "py",
"args": ["-3", "-m", "app.mcp.external_adapter"]
```

But only if the Python launched by `py -3` has all PatchDIFF dependencies installed.

For this repo, dependencies are normally installed into:

```text
.\.venv\Scripts\python.exe
```

The safer Claude Desktop config is:

```json
"command": "C:\\path\\to\\Patch-DIFF\\.venv\\Scripts\\python.exe",
"args": ["-m", "app.mcp.external_adapter"]
```

That avoids the common failure where Claude Desktop launches global Python but PatchDIFF dependencies only exist in the virtual environment.
