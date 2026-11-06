# Changelog

All notable features of `patchdiff-mcp` are documented in this file.

The format follows Keep a Changelog.

## [Unreleased]

### Changed

- **Default MCP profile changed to `observed_workspace`**: `ExternalMCPAdapter` and `patchdiff-mcp` now default to the 7-tool `observed_workspace` profile (`patchdiff_initialize_target`, `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`, `patchdiff_save`) for the full autonomous agentic editing lifecycle. Existing hosts requiring the legacy inline editing toolset should set `PATCHDIFF_MCP_PROFILE=editor` or pass `--profile editor`.
- **Default Waymark discovery worker mode changed to `resident`**: `WaymarkWorkerOwner` now defaults to `resident` mode to reuse a single Node.js worker across queries, with selective prewarming restricted to profiles with structural discovery tools (`_WAYMARK_PROFILES`). Set `PATCHDIFF_WAYMARK_MODE=oneshot` for per-query worker processes.

### Added

- Added `--profile` / `-p` and `--response-mode` / `-m` CLI startup flags to `patchdiff-mcp` with strict option validation.
- Added end-user troubleshooting guide (`docs/guides/troubleshooting.md`) for WSL2 memory limits, Docker Desktop visibility, and test isolation.
- Added Profile Compatibility & Deployment Matrix (`docs/spec/profiles/profile-compatibility.md`) covering OS, Docker configurations, and reproducible recipes.

## [0.1.0] - 2026-11-05

### Added

- Workspace lifecycle tools: import workspace files into PostgreSQL canonical storage, edit the working copy, and write changes back to disk with `patchdiff_save`.
- Guarded multi-scope transactions: commit atomic modifications across multiple observed AST scopes in one target file with `patchdiff_commit_bundle`.
- Structural AST discovery: inspect syntax candidates such as functions, classes, and methods through resident Waymark parser workers via `patchdiff_list_scopes` and `patchdiff_observe_scopes`.
- Optimistic concurrency control: lock target rows, check version numbers, and verify SHA-256 content hashes before writing mutations to PostgreSQL.
- Append-only audit logging: store accepted and rejected transactions with client request keys for idempotent retries and deterministic historical replay.
- Command-line entry points: run the stdio MCP server (`patchdiff-mcp`) and apply Alembic migrations directly (`patchdiff-mcp --migrate`).
