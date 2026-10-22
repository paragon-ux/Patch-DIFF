# PatchDIFF Internal MCP Registry

This README is for local debugging and test-harness use of the internal MCP registry.

Most users should connect through the external MCP adapter documented in [README.md](README.md) and [docs/CLAUDE_DESKTOP_SETUP.md](docs/CLAUDE_DESKTOP_SETUP.md). The internal registry is still useful for quick local checks because it calls the same service-layer functions without starting an external MCP host.

## Boundary

The internal registry is not a separate product path.

It must keep the same invariants as the external adapter:

- Transactions are untrusted until submitted through `patchdiff_submit_edits` (`patchdiff-tx/1`), `patchdiff_submit_operations` (`patchdiff-tx/2`), `patchdiff_submit_replacement` (`patchdiff-tx/3`) or `patchdiff_submit_pdcp` (legacy `0.2.3`). All use the shared locked commit path.
- Target content mutation must come only from accepted transactions validated by the deterministic core runtime.
- The registry must not bypass parser, validator, matcher, applier, or service-layer commit paths.
- SAVE may create snapshots and advance editing cycles, but must not alter target content.
- Admitted known-target rejections append attempt rows within the owner transaction and no ledger rows. Exact recovery, reads, preview and documented pre-admission failures add no attempt; caller rollback/infrastructure failure does not promise durability.

## Prerequisites

From the repo root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
docker compose up -d postgres
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

## Submit Typed Edits (Primary `patchdiff-tx/1`)

Submit guarded typed edits through the internal MCP tool registry:

```powershell
.\.venv\Scripts\python.exe -c "import json; from app.mcp import tools; from app.mcp.server import registry; print(json.dumps(registry.call('patchdiff_submit_edits', target_file_id='aae935dd-1427-4801-ad60-b8ec95040234', expected_target_version=0, intent='Update title', edits=[{'match': '# Sample Title', 'replace': '# Modernized Title'}]), indent=2))"
```

Export the current target after a successful submit:

```powershell
.\.venv\Scripts\python.exe -c "import json; from app.mcp import tools; from app.mcp.server import registry; print(json.dumps(registry.call('patchdiff_export_target', target_file_id='aae935dd-1427-4801-ad60-b8ec95040234'), indent=2))"
```

## Legacy `.pdcp` Submission

`testest.pdcp` is a sample legacy declarative PatchDIFF transaction in the repo root.

Submit the file through the internal registry:

```powershell
.\.venv\Scripts\python.exe -c "import json; from pathlib import Path; from app.mcp import tools; from app.mcp.server import registry; pdcp = Path('testest.pdcp').read_text(encoding='utf-8'); target_id = next(line.split(':', 1)[1].strip() for line in pdcp.splitlines() if line.startswith('target_file_id:')); print(json.dumps(registry.call('patchdiff_submit_pdcp', target_file_id=target_id, pdcp_content=pdcp, expected_target_version=0), indent=2))"
```

## List Internal Tools

```powershell
.\.venv\Scripts\python.exe -c "from app.mcp import tools; from app.mcp.server import registry; print('\n'.join(registry.names()))"
```

Expected tool surface (20 tools):

```text
patchdiff_build_prompt_context
patchdiff_build_regeneration_prompt
patchdiff_export_target
patchdiff_find_occurrences
patchdiff_get_manifest_ledger
patchdiff_get_pdcp_log
patchdiff_get_regeneration_context
patchdiff_get_target
patchdiff_handle_upload
patchdiff_initialize_target
patchdiff_preview
patchdiff_read_lines
patchdiff_read_target
patchdiff_replay
patchdiff_request_regeneration
patchdiff_save
patchdiff_submit_edits
patchdiff_submit_operations
patchdiff_submit_pdcp
patchdiff_submit_replacement
```

The three regeneration tools (`patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`) are deprecated compatibility wrappers. Modern host workflows use `patchdiff_read_target` / `patchdiff_find_occurrences` and host-owned retries.
