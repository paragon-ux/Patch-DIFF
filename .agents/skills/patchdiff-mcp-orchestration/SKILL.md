---
name: patchdiff-mcp-orchestration
description: Use when implementing or reviewing the MCP-first PatchDIFF server layer: upload events, prompt context construction, model PDCP response handling, rejection diagnostics, regeneration orchestration, and target export.
---

# PatchDIFF MCP Orchestration Skill

## Architecture

PatchDIFF MVP is MCP-first and server-side.

Core architecture:

```text
PatchDIFF server = orchestration + deterministic runtime
MCP = transport/interface
Chatbot/model = PDCP generator
Postgres = canonical working substrate
```

The user interacts with the chatbot, not a PatchDIFF frontend.

The PatchDIFF server receives events over MCP, manages target state, constructs prompt context, receives `.pdcp` transaction files, submits them to the deterministic core runtime, orchestrates regeneration when needed, and exports target state.

## Runtime Separation

MCP orchestration is in scope for the MVP.

The deterministic core runtime must remain separate from MCP orchestration.

The MCP layer may:

- receive document-upload events over MCP
- initialize a canonical target from uploaded content
- build prompt context for the chatbot/model
- route prompt context through MCP
- receive model-emitted `.pdcp` content
- store submitted PDCP as current pending transaction
- submit PDCP content to the deterministic core runtime
- receive accepted/rejected results
- construct regeneration prompts after rejection
- request regenerated PDCP over MCP
- submit regenerated PDCP as a new attempt
- export or return the current target through MCP

The MCP layer must not bypass the deterministic core runtime.

A regenerated PDCP is never applied directly by MCP orchestration. It must be submitted through the same validation path and validated from scratch.

## User Interaction Flow

Expected MVP flow:

```text
1. User uploads document in chat.
2. PatchDIFF server receives upload event over MCP.
3. PatchDIFF initializes canonical cloud target.
4. User requests an edit in chat.
5. PatchDIFF constructs prompt context.
6. Chatbot/model emits declarative .pdcp transaction.
7. PatchDIFF receives .pdcp response.
8. PatchDIFF validates .pdcp deterministically.
9. PatchDIFF applies accepted edits atomically.
10. PatchDIFF requests regeneration on rejection when appropriate.
11. PatchDIFF returns status and exports target when requested.
```

Do not build a frontend as the primary MVP interface.

A debug console, audit viewer, or replay inspector may be added later, but is not the MVP user surface.

## Upload Event Handling

On document upload event, the PatchDIFF server should:

- receive uploaded content and metadata over MCP
- validate the content is a supported UTF-8 text-like target
- initialize `cloud_target_file`
- canonicalize uploaded content
- compute initial hash
- create initial editing cycle
- create initial snapshot
- return `target_file_id`, `target_type`, `version`, and `current_hash`

The chatbot UI must not perform PatchDIFF logic.

## Prompt Context Construction

PatchDIFF server constructs prompt context automatically.

Prompt context may include:

- `target_file_id`
- `target_type`
- current target version/hash
- relevant target spans
- document structure summary when available
- current accepted manifest ledger
- user edit request
- PDCP output rules
- canonicalization and exact-match requirements
- previous rejection diagnostics when regenerating

The model's job is to generate valid declarative `.pdcp`.

PatchDIFF must not ask the model to generate executable apply functions.

## PDCP Response Handling

When the model emits a `.pdcp` response, the PatchDIFF server should:

- receive the `.pdcp` content over MCP
- store it as `current_pdcp_file` with status such as `pending_validation`
- submit it to the deterministic core runtime
- receive accepted/rejected result
- update persistence through the service/persistence layer
- return status to the chat session

Use PDCP terminology, not “program file” terminology.

Preferred terms:

- `current_pdcp_file`
- `append_only_pdcp_log`
- `.pdcp transaction file`

Avoid implying PDCP is executable.

## Rejection And Regeneration

Rejected PDCPs are normal transaction outcomes.

On rejection, the PatchDIFF server may:

- store rejected PDCP log entry
- return structured diagnostics
- construct regeneration prompt
- include fresh target context if needed
- include failed change ID and failure reason
- request a regenerated PDCP over MCP
- submit regenerated PDCP as a new transaction attempt

The regenerated PDCP must:

- be submitted explicitly
- receive its own log entry
- be validated from scratch
- use current canonical target state
- produce its own accepted or rejected result

Rejected attempts must remain append-only log entries.

Accepted attempts must not erase prior rejected attempts.

## Regeneration Prompt Requirements

Regeneration prompt should include:

- original user edit request
- rejection failure reason
- failure detail
- failed change ID when available
- current target version/hash
- current accepted manifest ledger
- fresh relevant target spans
- PDCP format rules
- instruction to regenerate a fresh `.pdcp` transaction from scratch

The regeneration prompt must not instruct the model to bypass validation or generate executable apply logic.

## MCP Tool Boundary

MCP tools should expose orchestration operations such as:

- initialize target from upload
- build prompt context
- submit PDCP response
- get target
- export target
- get PDCP log
- get manifest ledger
- save target
- replay target
- get regeneration context
- request regeneration, if the project owns that flow

MCP tools must not write directly to target content except through accepted core runtime transactions.

MCP tools must not mark rejected transactions as accepted.

MCP tools must not delete append-only logs.

## Export And SAVE

The PatchDIFF server should support:

- exporting current canonical target
- returning current target content to the chat session when requested
- SAVE checkpointing
- active editing-cycle compaction
- preserving full PDCP log for audit/replay

SAVE does not mean “write target changes.” Accepted PDCP transactions already update the canonical target.

## Stream Interception

Complete `.pdcp` submission is the MVP-safe path.

Stream interception of partial model output is MVP+ unless explicitly prioritized.

If stream interception is implemented later, it must not apply partial PDCPs or bypass validation.

## Forbidden MCP Behavior

Do not let MCP orchestration:

- apply generated text directly to targets
- mutate target content without the core runtime
- bypass exact `MATCH/REPLACE` validation
- delete rejected attempts
- overwrite append-only logs
- execute PDCP content
- treat model output as trusted
- silently repair malformed PDCP

The only mutation path is:

```text
submitted .pdcp -> deterministic core validation -> accepted transaction -> atomic commit
```
