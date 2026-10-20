# Claude Desktop MCP Setup

PatchDIFF's Claude Desktop adapter is a local stdio MCP server, not a localhost HTTP MCP server.

Claude Desktop launches the Python process directly and talks to it over stdin/stdout:

```text
Claude Desktop
  -> launches
backend/app/mcp/external_adapter.py
  -> uses
Postgres Docker container on localhost:5432
```

Do not connect Claude Desktop to `http://127.0.0.1:8000` for this setup. The FastAPI server is useful for health checks and future HTTP API work, but the current Claude Desktop MCP path is the stdio adapter.

## 1. Start Postgres And Run Migrations

From the Patch-DIFF repo root:

```powershell
docker compose up -d postgres
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

You do not need to run `uvicorn` for the Claude Desktop MCP tools. Claude Desktop launches `app.mcp.external_adapter` directly.

Ensure migrations `20260510_0001` and `20261020_0002` are applied so the typed transaction ledger columns and request idempotency index exist.

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

Use the venv Python directly so Claude Desktop launches the interpreter that has PatchDIFF's dependencies installed.

Replace paths if your repo lives somewhere else:

```json
{
  "mcpServers": {
    "patchdiff": {
      "type": "stdio",
      "command": "C:\\Users\\USER\\Desktop\\Frameworks\\Patch-DIFF\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "app.mcp.external_adapter"
      ],
      "env": {
        "PYTHONPATH": "C:\\Users\\USER\\Desktop\\Frameworks\\Patch-DIFF\\backend",
        "PATCHDIFF_DATABASE_URL": "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff"
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

You should see `patchdiff` and the full modernized tool surface:

- **Target lifecycle**: `patchdiff_handle_upload`, `patchdiff_initialize_target`, `patchdiff_get_target`, `patchdiff_export_target`
- **Authoritative reads & exact search**: `patchdiff_read_target`, `patchdiff_find_occurrences`
- **Guarded edit submission**: `patchdiff_submit_edits` (primary typed transaction format, `patchdiff-tx/1`), `patchdiff_submit_pdcp` (legacy `.pdcp` format)
- **Checkpoints, replay & audit**: `patchdiff_save`, `patchdiff_replay`, `patchdiff_get_pdcp_log`, `patchdiff_get_manifest_ledger`
- **Context preview & legacy wrappers**: `patchdiff_build_prompt_context` (bounded prefix preview), and deprecated `patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`

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
"command": "C:\\Users\\USER\\Desktop\\Frameworks\\Patch-DIFF\\.venv\\Scripts\\python.exe",
"args": ["-m", "app.mcp.external_adapter"]
```

That avoids the common failure where Claude Desktop launches global Python but PatchDIFF dependencies only exist in the virtual environment.
