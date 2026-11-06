# Changelog

All notable features of `patchdiff-mcp` are documented in this file.

The format follows Keep a Changelog.

## [0.2.0] - 2026-11-06

### Added

- `patchdiff-mcp doctor`: System, database, schema migration, and Waymark dependency diagnostic CLI command.
- Default `observed_workspace` MCP profile: `patchdiff-mcp` defaults to the 7-tool observed workspace profile on startup.
- Default resident Waymark discovery: `WaymarkWorkerOwner` now defaults to `resident` mode, eliminating per-query Node.js process startup overhead while preserving `PATCHDIFF_WAYMARK_MODE=oneshot` as an opt-in fallback.
- Multi-target coordinated transactions: commit all-or-nothing changes across multiple target files with deadlock-free canonical UUID lock ordering via `patchdiff_commit_multi_target`.
- Client/server capability negotiation: explicit `capabilities.patchdiff` handshake during JSON-RPC initialize for negotiating supported transaction formats and features.
- Pre-commit semantic verification hooks: optional syntax and AST validation (Python, JSON, Markdown fence balance) during `patchdiff_preview`.
- Multi-agent contention benchmark: automated benchmark suite and empirical contention study covering disjoint and hotspot concurrency regimes.
- End-user troubleshooting guide: comprehensive operational guide (`docs/guides/troubleshooting.md`) covering WSL2 memory tuning, Docker visibility, port management, and test isolation boundaries.

### Security & Hardening

- Profile immutability: JSON-RPC wire handshake capability negotiation rejects/ignores client profile mutations, ensuring server profiles remain strictly fixed at process launch.

## [0.1.0] - 2026-11-05

### Added

- Workspace lifecycle tools: import workspace files into PostgreSQL canonical storage, edit the working copy, and write changes back to disk with `patchdiff_save`.
- Guarded multi-scope transactions: commit atomic modifications across multiple observed AST scopes in one target file with `patchdiff_commit_bundle`.
- Structural AST discovery: inspect syntax candidates such as functions, classes, and methods through resident Waymark parser workers via `patchdiff_list_scopes` and `patchdiff_observe_scopes`.
- Optimistic concurrency control: lock target rows, check version numbers, and verify SHA-256 content hashes before writing mutations to PostgreSQL.
- Append-only audit logging: store accepted and rejected transactions with client request keys for idempotent retries and deterministic historical replay.
- Command-line entry points: run the stdio MCP server (`patchdiff-mcp`) and apply Alembic migrations directly (`patchdiff-mcp --migrate`).
