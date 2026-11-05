# PatchDIFF documentation

PatchDIFF turns proposed text edits into guarded PostgreSQL transactions
over MCP. Start with the workflow that fits your host.

- [Edit a workspace file](guides/workspace-quickstart.md) with the installed
  package and publish the edited bytes on SAVE.
- [Connect Claude Desktop](guides/claude-desktop-setup.md) to the stdio server.
- [Integrate a host](guides/host-integration-guide.md) to read targets, submit
  guarded edits, and handle rejections.
- [Delegate structural editing](guides/observed-editor-workflow.md) while
  retaining lifecycle tools on a trusted connection.

## Shared specifications

- [Core runtime](spec/core-runtime.md) covers exact matching, sequential
  simulation, validation and deterministic replay.
- [MCP tools](spec/mcp-tools.md) defines shared requests, receipts and errors.
- [Data model](spec/data-model.md) explains PostgreSQL storage, row locks and migrations.
- [Transaction formats](spec/transaction-formats.md) covers typed replacements,
  guarded match and span operations, and whole-target replacement.
- [Structural batch editing](spec/structural-batch-editing.md) explains scope
  observation and atomic multi-scope edits.
- [Waymark worker](spec/waymark-worker.md) describes resident discovery, IPC and cleanup.

## MCP profiles

[Choose a profile](spec/profiles/index.md) to see which tools a connection
can use. These pages explain who should use each profile and how to start.

- [Workspace](spec/profiles/workspace-profile.md) for file import, exact editing and publication.
- [Editing an existing target](spec/profiles/existing-target-editing.md) for
  `editor`, `unobserved` and `observed`.
- [Delegated editing and lifecycle](spec/profiles/delegation-and-lifecycle.md)
  for `observed_editor`, `unobserved_editor`, `hybrid_editor` and `full`.
- [Observed editor v2](spec/profiles/observed-editor-v2.md) for structural
  editing with explicit snapshots and bounded receipts.

## Architecture and evidence

- [Architecture diagrams](architecture.md) trace an edit through validation,
  commit and replay.
- [Modernization architecture](papers/modernization-architecture.md) records
  design decisions A1–A8, contracts C1–C6 and evidence E1–E8.
- [Product change record](papers/product-change-record.md) tracks product behavior
  and verification scope.
- [Concept paper v6](papers/concept-paper-v6.md) explains the transaction model,
  tradeoffs and research hypotheses.
- [Workspace benchmark](benchmarks/workspace-e2e-benchmark.md) compares Native,
  host-orchestrated structural editing and agent-owned Workspace editing through
  publication and independent verification. It is the current comparative report.
- [Test matrix](benchmarks/test-matrix.md) maps unit, PostgreSQL, migration and
  stdio tests to their contracts.

## Review and release

- [PR review standard](standards/pr-review-standard.md) defines category
  coverage, finding severity and evidence requirements.
- [Release readiness](standards/release-readiness.md) covers versioning,
  verification and dependency audits.

## Earlier benchmarks

- [Modernization benchmark](benchmarks/modernized-benchmark-report.md) records
  the previous five-tool structural editing experiment.

- [Earlier baseline benchmark](https://github.com/paragon-ux/Patch-DIFF/blob/56d3545d9f4369bc1e57f593dbb71bbd37128b9e/docs/legacy/git_benchmark_report.md) records the original experiment.
