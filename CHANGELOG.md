# Changelog

All notable features of `patchdiff-mcp` are documented in this file.

The format follows Keep a Changelog.

## [0.1.0] - 2026-11-05

### Added

- Workspace lifecycle tools: import workspace files into PostgreSQL canonical storage, edit the working copy, and write changes back to disk with `patchdiff_save`.
- Guarded multi-scope transactions: commit atomic modifications across multiple observed AST scopes in one target file with `patchdiff_commit_bundle`.
- Structural AST discovery: inspect syntax candidates such as functions, classes, and methods through resident Waymark parser workers via `patchdiff_list_scopes` and `patchdiff_observe_scopes`.
- Optimistic concurrency control: lock target rows, check version numbers, and verify SHA-256 content hashes before writing mutations to PostgreSQL.
- Append-only audit logging: store accepted and rejected transactions with client request keys for idempotent retries and deterministic historical replay.
- Command-line entry points: run the stdio MCP server (`patchdiff-mcp`) and apply Alembic migrations directly (`patchdiff-mcp --migrate`).
