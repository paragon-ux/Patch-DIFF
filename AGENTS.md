# AGENTS.md

## Project

PatchDIFF MVP is an MCP-first, server-side document editing system.

PatchDIFF server receives document-upload and edit-request events over MCP, manages canonical target state in Postgres, constructs prompt context for the chatbot/model, receives declarative PDCP transaction files, validates them deterministically, applies accepted edits atomically, logs accepted and rejected attempts, and supports SAVE/export/replay.

Core architecture:

```text
PatchDIFF server = orchestration + deterministic runtime
MCP = transport/interface
Chatbot/model = PDCP generator
Postgres = canonical working substrate
```

The user interacts with the chatbot, not with a PatchDIFF frontend.

PatchDIFF is not a chat UI, rich document editor, semantic patch language, AST rewrite engine, fuzzy matcher, merge system, or full-document regeneration workflow.

## Source Of Truth

Read project artifacts in this order:

1. `AGENTS.md`
2. `docs/MCP_FIRST_MVP.md`
3. `docs/PATCHDIFF_CORE_SPEC.md`
4. `docs/MCP_TOOLS.md`
5. `docs/DATA_MODEL.md`
6. `docs/PDCP_FORMAT.md`
7. `docs/TEST_MATRIX.md`
8. `docs/CODEX_BUILD_PLAN.md`

If files conflict, follow `MCP_FIRST_MVP.md`.

If deterministic runtime behavior is unclear, follow `PATCHDIFF_CORE_SPEC.md`.

If MCP tool behavior is unclear, follow `MCP_TOOLS.md`.

If ambiguity remains, preserve PatchDIFF’s locked invariants and choose the simplest deterministic behavior.

## PDCP File Boundary

PDCP files use the `.pdcp` extension.

PDCP is a declarative PatchDIFF transaction format, not Python, JavaScript, C, JSON, YAML, or any target language.

The trusted runtime may be implemented in Python, for example as `changeOperator.py`.

The PDCP file itself must never be executable.

Keep this boundary:

```text
.pdcp file = declarative transaction artifact
.py file = trusted runtime implementation
target file = Markdown/Python/YAML/JSON/prose/etc.
```

Do not treat PDCP as Python just because the runtime is written in Python.

Do not use Python-style target declarations as the primary PDCP header.

Use protocol-native PDCP headers defined in `PDCP_FORMAT.md`.


## Core Runtime Boundary

PatchDIFF core runtime is deterministic.

It may:

- parse `.pdcp` files
- validate protocol structure
- validate transaction applicability
- apply accepted transactions atomically
- reject invalid transactions without target mutation
- log accepted and rejected attempts
- return structured rejection diagnostics
- support SAVE and deterministic replay

It must not:

- call an LLM
- call an MCP tool
- construct prompts
- choose a model
- hold model credentials
- run an agent loop
- silently repair submitted PDCP
- perform fuzzy matching
- perform semantic matching
- perform automatic merge
- partially commit a failed transaction
- execute model-generated code

Every PDCP, however produced, is untrusted until validated by PatchDIFF core.

## MCP Orchestration Boundary

MCP orchestration is in scope for the MVP.

The PatchDIFF server may:

- receive document-upload events over MCP
- initialize a canonical target from uploaded content
- build prompt context for the chatbot/model
- route prompt context through MCP
- receive model-emitted `.pdcp` content
- store the submitted PDCP as the current pending transaction
- submit PDCP content to the deterministic core runtime
- receive accepted/rejected results
- construct regeneration prompts after rejection
- request regenerated PDCP through MCP orchestration
- submit regenerated PDCP as a new attempt
- export or return the current target through MCP

The MCP orchestration layer may interact with stochastic systems.

The deterministic core runtime must remain separate from MCP orchestration.

A regenerated PDCP is never applied directly by the MCP layer. It must be submitted through the same validation path and validated from scratch.

## User Interaction Model

The MVP user surface is the chatbot session.

The expected flow is:

```text
User uploads document in chat.
PatchDIFF server receives upload event over MCP.
PatchDIFF initializes canonical cloud target.
User requests an edit in chat.
PatchDIFF constructs prompt context.
Chatbot/model emits declarative .pdcp transaction.
PatchDIFF validates the PDCP deterministically.
PatchDIFF applies accepted edits atomically.
PatchDIFF requests regeneration on rejection when appropriate.
PatchDIFF returns status and exports target when requested.
```

Do not build a frontend as the primary MVP interface.

A debug console, audit viewer, or replay inspector may be added later, but is not the MVP user surface.

## Non-Negotiable Boundaries

Do not introduce into the deterministic core runtime:

- fuzzy matching
- semantic matching
- AST parsing
- language-specific rewrite behavior
- token-coordinate editing
- line-number editing as authority
- automatic repair
- automatic merge
- partial commits
- model-generated executable protocol logic
- hidden mutation outside selected `MATCH` spans
- full-document regeneration as the commit mechanism
- deletion of append-only history
- SQLite as the MVP persistence backend
- semantic validation as core transaction validity

Do not introduce into PDCP files:

- executable recursion functions
- generated `applyPDCP` functions
- imports
- loops
- conditionals
- runtime logic
- tool calls
- shell commands
- network calls
- filesystem calls

PDCP is declarative.

PatchDIFF trusted runtime applies exact `MATCH/REPLACE` transactions.

## MVP Boundary

The MCP-first MVP includes:

- MCP server interface
- upload-event handling
- target initialization from uploaded document content
- prompt-context construction
- model PDCP response handling
- `.pdcp` parsing
- protocol validation
- transaction validation
- exact `MATCH/REPLACE` application
- atomic Postgres commit
- accepted/rejected PDCP logging
- accepted-only manifest ledger
- structured rejection diagnostics
- regeneration orchestration through MCP
- regenerated PDCP validation from scratch
- target retrieval/export
- SAVE snapshot and editing-cycle advancement
- deterministic replay

The MVP excludes:

- standalone frontend as primary interface
- rich document editor
- chat UI implementation
- restore-to-version
- multi-writer merge
- CRDT or OT collaboration
- semantic validation
- code execution from PDCP
- production auth
- billing
- delimiter escaping
- length-prefixed payloads
- rich or binary document support

Project-level adapters may be built later, but they must preserve the core runtime boundary.

## Backend Requirements

The MVP backend is cloud-shaped from day one.

Use:

- FastAPI
- Postgres
- SQLAlchemy or SQLModel
- Alembic migrations
- pytest
- Docker Compose
- MCP server tooling appropriate for the selected Python stack

Postgres is the MVP persistence backend.

SQLite is not the MVP persistence backend. SQLite may be used only for isolated experiments or pure runtime tests that do not exercise persistence, locking, migrations, SAVE, or replay.

Docker Compose must provide deterministic local Postgres.

The PatchDIFF runtime core must remain storage-abstracted. Parser, canonicalizer, matcher, disambiguator, applier, and replay logic must not depend directly on SQL, FastAPI, Postgres, Docker, MCP transport, or a specific deployment provider.

## Runtime Layers

Keep these layers separate:

1. MCP orchestration layer
2. Service layer
3. PDCP parser
4. Protocol validator
5. Transaction validator
6. Transaction applier
7. Append-only persistence layer

The MCP layer handles transport and orchestration.

The service layer coordinates workflows.

The parser extracts PDCP structure.

The protocol validator checks structural validity.

The transaction validator checks applicability against the current canonical target.

The applier simulates replacements in memory and commits only after all changes succeed.

The persistence layer stores targets, logs, ledgers, snapshots, and editing cycles atomically.

Do not collapse these layers in a way that makes replay, testing, or validation unclear.

## Canonical Runtime Contract

PatchDIFF MVP is successful only if it preserves:

```text
canonical UTF-8 target text
+ declarative .pdcp transaction files
+ exact deterministic MATCH
+ immediate sequential REPLACE
+ atomic Postgres commit
+ append-only PDCP log
+ accepted-only manifest ledger
+ structured rejection diagnostics
+ MCP orchestration outside deterministic core
+ SAVE checkpointing
+ deterministic replay
```

Do not trade away determinism for convenience.

Do not trade away exactness for helpfulness.

Do not trade away atomicity for partial success.

## Testing Rule

Do not claim completion unless relevant tests pass.

Use pure runtime unit tests for:

- PDCP header parsing
- manifest parsing
- canonicalization
- hashing
- exact matching
- disambiguation
- sequential in-memory application
- failure classification
- rejection diagnostic mapping

Use Postgres integration tests for:

- atomic commit
- row-level locking
- target version/hash guards
- `target_diverged`
- append-only PDCP logs
- accepted-only manifest ledger
- rejected PDCP logging
- SAVE editing-cycle behavior
- snapshots
- deterministic replay from persisted logs
- Alembic migration validity

Use MCP contract tests for:

- upload event initializes target
- prompt context is constructed from target metadata, manifest ledger, and relevant spans
- model PDCP response is stored as pending current PDCP
- accepted PDCP returns success status
- rejected PDCP returns diagnostics
- regeneration prompt is constructed after rejection
- regenerated PDCP is submitted as a new attempt
- export returns current canonical target

Do not rely on SQLite to prove persistence correctness.

## Code Organization

Before adding a helper, search for existing implementations.

Do not duplicate logic for:

- canonicalization
- SHA-256 hashing
- failure reason labels
- PDCP header parsing
- manifest parsing
- `MATCH` occurrence detection
- disambiguation resolution
- transaction application
- replay application
- SAVE cycle handling
- MCP tool response shapes

Prefer one shared implementation used by runtime and tests.

If runtime and replay behavior differ, treat that as a bug unless a controlling artifact explicitly says otherwise.

## Final Response Style

When reporting work, be concise.

Prefer:

```text
Implemented X.

Changed:
- path/to/file.py
- tests/test_file.py

Verified:
- pytest ...

Notes:
- ...
```

List tests run.

List tests not run.

Do not paste large files unless requested.

Do not claim completion without verification.

## Skills

This repo uses MCP-first PatchDIFF skill files to keep implementation guidance focused and avoid loading stale architecture assumptions.

Use only the MCP-first skills listed here.

Do not use older PatchDIFF skills unless the user explicitly asks for archival comparison.

Required skills:

- `skills/patchdiff-core-runtime.md`
  - Use for deterministic core runtime work.
  - Covers `.pdcp` parsing, protocol validation, canonicalization, hashing, exact `MATCH/REPLACE`, disambiguation, sequential mutation, atomic application, and failure labels.

- `skills/patchdiff-mcp-orchestration.md`
  - Use for MCP-first server orchestration work.
  - Covers upload events, target initialization, prompt-context construction, model PDCP response handling, rejection diagnostics, regeneration orchestration, and export.

- `skills/patchdiff-persistence-replay-save.md`
  - Use for persistence, SAVE, and replay work.
  - Covers Postgres, Docker Compose, Alembic migrations, append-only logs, row-level locking, editing cycles, snapshots, SAVE, and deterministic replay.

- `skills/patchdiff-testing-review.md`
  - Use for tests, reviews, and completion checks.
  - Covers core runtime tests, Postgres integration tests, MCP contract tests, regeneration-flow tests, protocol-drift review, and code-quality checks.

When a task touches multiple areas, read all relevant skills before editing.

Examples:

```text
PDCP parser change -> patchdiff-core-runtime.md
MCP upload flow -> patchdiff-mcp-orchestration.md
SAVE or replay -> patchdiff-persistence-replay-save.md
Review or test planning -> patchdiff-testing-review.md
```

If a skill conflicts with MCP_FIRST_MVP.md, PATCHDIFF_CORE_SPEC.md, or MCP_TOOLS.md, follow the build docs first.

The skill files are implementation aids, not the source of truth.
