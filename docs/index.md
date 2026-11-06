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
- [Troubleshoot environment setup](guides/troubleshooting.md) for port conflicts,
  WSL2 memory tuning, and Docker Desktop configurations.

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

PatchDIFF exposes focused tool profiles aligned with its editing workflows:

- [Profile Catalog](spec/profiles/index.md): Summary of all 10 operational profiles and startup configuration.
- [Profile Compatibility Matrix](spec/profiles/profile-compatibility.md): OS support (Bare Windows, WSL2, Linux, macOS) and Docker deployment recipes.
- [Observed Workspace](spec/profiles/workspace-profile.md) (Default): 7-tool structural AST editing enabling autonomous agents to own the complete lifecycle from file import to SAVE publication.
- [Workspace](spec/profiles/workspace-profile.md): 5-tool exact text editing from file import to SAVE publication.
- [Observed Editor v2](spec/profiles/observed-editor-v2.md): 5-tool structural editing for host-managed lifecycle environments.

## Architecture and evidence

- [Architecture diagrams](architecture.md) trace an edit through validation,
  commit and replay.
- [Modernization architecture](papers/modernization-architecture.md) records
  design decisions A1 to A8, contracts C1 to C6 and evidence E1 to E8.
- [Product change record](papers/product-change-record.md) tracks product behavior
  and verification scope.
- [Concept paper v6](papers/concept-paper-v6.md) explains the transaction model,
  tradeoffs and research hypotheses.
- [Formal transaction model](papers/formal-transaction-model.md) provides the
  formal mathematical specification, state space, and invariant proofs.
- [Workspace benchmark](benchmarks/workspace-e2e-benchmark.md) compares Native,
  host-orchestrated structural editing and agent-owned Workspace editing through
  publication and independent verification.
- [Test matrix](benchmarks/test-matrix.md) maps unit, PostgreSQL, migration and
  stdio tests to their contracts.
- [Roadmap](ROADMAP.md) outlines multi-agent concurrency, workspace publication, and forward-looking research.

## Review and release

- [PR review standard](standards/pr-review-standard.md) defines category
  coverage, finding severity and evidence requirements.
- [Release readiness](standards/release-readiness.md) covers versioning,
  verification and dependency audits.
