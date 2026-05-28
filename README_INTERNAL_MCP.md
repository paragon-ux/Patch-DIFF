# PatchDIFF Internal MCP Registry

This README is for local debugging and test-harness use of the internal MCP registry.

Most users should connect through the external MCP adapter documented in [README.md](README.md). The internal registry is still useful for quick local checks because it calls the same service-layer functions without starting an external MCP host.

## Boundary

The internal registry is not a separate product path.

It must keep the same invariants as the external adapter:

- PDCP content is untrusted until submitted through `patchdiff_submit_pdcp`.
- Target content mutation must come only from accepted `.pdcp` transactions.
- The registry must not bypass parser, validator, matcher, applier, or service-layer commit paths.
- SAVE may create snapshots and advance editing cycles, but must not alter target content.
- Rejected PDCP attempts remain logged and must not append manifest ledger rows.

## Prerequisites

From the repo root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
docker compose up -d postgres
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

## Submit `testest.pdcp`

`testest.pdcp` is a sample declarative PatchDIFF transaction in the repo root.

It is pointed at this demo target:

```text
target_file_id: aae935dd-1427-4801-ad60-b8ec95040234
target_hash: d53e81b191e91d26570cc6883ada57b4b255d47468111059435c34e265f8f25f
```

Submit the file through the internal MCP tool registry:

```powershell
.\.venv\Scripts\python.exe -c "import json; from pathlib import Path; from app.mcp import tools; from app.mcp.server import registry; pdcp = Path('testest.pdcp').read_text(encoding='utf-8'); target_id = next(line.split(':', 1)[1].strip() for line in pdcp.splitlines() if line.startswith('target_file_id:')); print(json.dumps(registry.call('patchdiff_submit_pdcp', target_file_id=target_id, pdcp_content=pdcp, expected_target_version=0), indent=2))"
```

Export the current target after a successful submit:

```powershell
.\.venv\Scripts\python.exe -c "import json; from app.mcp import tools; from app.mcp.server import registry; print(json.dumps(registry.call('patchdiff_export_target', target_file_id='aae935dd-1427-4801-ad60-b8ec95040234'), indent=2))"
```

This PDCP is intended to be submitted once against target version `0`. If it has already been accepted, submitting the same file again will reject because the original `MATCH` text no longer exists and the header `target_hash` is stale.

## List Internal Tools

```powershell
.\.venv\Scripts\python.exe -c "from app.mcp import tools; from app.mcp.server import registry; print('\n'.join(registry.names()))"
```

Expected tool surface:

```text
patchdiff_build_prompt_context
patchdiff_build_regeneration_prompt
patchdiff_export_target
patchdiff_get_manifest_ledger
patchdiff_get_pdcp_log
patchdiff_get_regeneration_context
patchdiff_get_target
patchdiff_handle_upload
patchdiff_initialize_target
patchdiff_replay
patchdiff_request_regeneration
patchdiff_save
patchdiff_submit_pdcp
```
