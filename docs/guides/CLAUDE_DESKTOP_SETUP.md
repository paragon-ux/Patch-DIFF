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

### UTF-8 transport

The adapter entry point configures stdin/stdout as strict UTF-8, including Windows pipes and environments with a different PYTHONIOENCODING value. Hosts must send UTF-8 JSON-RPC bytes. ASCII Unicode escapes remain supported; malformed UTF-8 wire bytes are not silently repaired. Escaped invalid edit strings still follow the audited domain-validation contract.

When running an older revision without the UTF-8 transport fix, add `"PYTHONIOENCODING": "utf-8"` to the MCP server environment. Without it, literal Unicode requests can be accepted with incorrectly decoded text; this was reproduced as input corruption rather than a stdout crash. The workaround remains compatible with fixed revisions.

Restart or refresh the server through the host after command/environment changes, then verify the connection. Claude Desktop restart steps appear below; other hosts have their own refresh lifecycle.

## 1. Start Postgres And Run Migrations

From the Patch-DIFF repo root:

```powershell
docker compose up -d postgres
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

You do not need to run `uvicorn` for the Claude Desktop MCP tools. Claude Desktop launches `app.mcp.external_adapter` directly.

Apply migrations through `20261027_0005` so the typed ledger, request idempotency, source line endings and bundled scope evidence are available.

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

The default startup profile is `editor` (7 advertised and callable tools).
Use `PATCHDIFF_MCP_PROFILE=full` in the server environment for older integrations
or trusted upload/initialization/export workflows that need the complete 22-tool
catalog. `unobserved` (5), `observed` (6), and `observed_editor` (4) are also
available. The last is for delegated editors whose host owns SAVE/replay.
Unknown profiles fail startup, and requests cannot override the session's immutable selection.
[Exact tool lists and structural batches](STRUCTURAL_BATCH_EDITING.md).

Use the venv Python directly so Claude Desktop launches the interpreter that has PatchDIFF's dependencies installed.

Replace paths if your repo lives somewhere else:

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
- **Authoritative reads & exact search**: `patchdiff_read_target`, `patchdiff_read_lines`, `patchdiff_find_occurrences`
- **Guarded edit submission**: `patchdiff_submit_edits` (`patchdiff-tx/1`), `patchdiff_submit_operations` (match/span, `patchdiff-tx/2`), `patchdiff_submit_replacement` (sole replace_all, `patchdiff-tx/3`), `patchdiff_submit_pdcp` (legacy `.pdcp`)
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
