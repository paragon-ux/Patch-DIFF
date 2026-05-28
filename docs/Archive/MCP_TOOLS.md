# MCP_TOOLS.md

## Purpose

This document defines the MCP-first interface for PatchDIFF MVP.

MCP is the transport/interface layer between the chat session, the model, and the PatchDIFF server. The PatchDIFF server owns orchestration and deterministic runtime execution.

The deterministic core runtime remains separate from MCP transport.

## Core Principle

```text
MCP layer orchestrates.
Core runtime validates and applies.
Model generates declarative .pdcp.
```

MCP tools must never bypass core runtime validation.

## Tool Naming

Use explicit names with a `patchdiff_` prefix.

Recommended MVP tools:

- `patchdiff_handle_upload`
- `patchdiff_initialize_target`
- `patchdiff_build_prompt_context`
- `patchdiff_submit_pdcp`
- `patchdiff_get_regeneration_context`
- `patchdiff_request_regeneration`
- `patchdiff_get_target`
- `patchdiff_export_target`
- `patchdiff_save`
- `patchdiff_replay`
- `patchdiff_get_pdcp_log`
- `patchdiff_get_manifest_ledger`

## patchdiff_handle_upload

Purpose:

Receive a document-upload event from the chat session and initialize or stage a PatchDIFF target.

Input:

```json
{
  "filename": "example.md",
  "content": "...",
  "content_type": "text/markdown",
  "project_id": "optional_project_id"
}
```

Behavior:

- validate UTF-8
- canonicalize content
- create target if requested
- initialize editing cycle
- create initial snapshot
- return target metadata

Output:

```json
{
  "target_file_id": "target_123",
  "filename": "example.md",
  "target_type": "text/markdown",
  "version": 0,
  "current_hash": "...",
  "active_editing_cycle_id": "cycle_001"
}
```

## patchdiff_initialize_target

Purpose:

Initialize a canonical cloud target from provided text content.

This may be called directly or by `patchdiff_handle_upload`.

Input:

```json
{
  "filename": "example.md",
  "content": "...",
  "content_type": "text/markdown",
  "project_id": "optional_project_id"
}
```

Output:

```json
{
  "target_file_id": "target_123",
  "version": 0,
  "current_hash": "...",
  "active_editing_cycle_id": "cycle_001"
}
```

## patchdiff_build_prompt_context

Purpose:

Build prompt context for the chatbot/model to generate a `.pdcp` transaction.

Input:

```json
{
  "target_file_id": "target_123",
  "user_request": "Clarify the SAVE section.",
  "context_policy": "relevant_spans"
}
```

Behavior:

- load target metadata
- load active manifest ledger
- retrieve relevant target spans if needed
- include PDCP output rules
- include current version/hash
- include user request

Output:

```json
{
  "target_file_id": "target_123",
  "target_type": "text/markdown",
  "current_hash": "...",
  "version": 3,
  "manifest_summary": [
    {
      "change_id": "chg_001",
      "intent": "...",
      "output_state": "..."
    }
  ],
  "target_context": "...",
  "pdcp_rules": "...",
  "user_request": "Clarify the SAVE section."
}
```

The output may be rendered or forwarded by the MCP host to the model.

## patchdiff_submit_pdcp

Purpose:

Submit model-emitted `.pdcp` text for deterministic validation and application.

Input:

```json
{
  "target_file_id": "target_123",
  "pdcp_content": "PDCP 0.2.3\ntarget_file_id: target_123\n...",
  "expected_target_version": 3,
  "expected_current_hash": "...",
  "source": "model_response"
}
```

Behavior:

- store current PDCP as pending validation
- parse PDCP
- validate protocol
- validate transaction against canonical target
- apply atomically if valid
- reject without mutation if invalid
- append accepted/rejected log
- append manifest ledger only on success
- return structured result

Accepted output:

```json
{
  "status": "accepted",
  "target_file_id": "target_123",
  "pdcp_log_id": "log_123",
  "before_hash": "...",
  "after_hash": "...",
  "version": 4,
  "manifest_entries_added": 1
}
```

Rejected output:

```json
{
  "status": "rejected",
  "target_file_id": "target_123",
  "pdcp_log_id": "log_124",
  "failure_reason": "match_absent",
  "failure_detail": "MATCH text was not found in the current canonical target.",
  "failed_change_id": "chg_002",
  "before_hash": "...",
  "after_hash": null,
  "current_version": 3,
  "current_hash": "...",
  "diagnostic": {
    "retryable": true,
    "requires_new_pdcp": true,
    "context_refresh_recommended": true,
    "recommended_action": "refresh_context_and_resubmit"
  }
}
```

## patchdiff_get_regeneration_context

Purpose:

Return deterministic context needed for regeneration after rejection.

Input:

```json
{
  "pdcp_log_id": "log_124"
}
```

Behavior:

- load rejected PDCP log
- load current target metadata
- load active manifest ledger
- retrieve fresh relevant target context when possible
- include failure diagnostics
- include PDCP rules

Output:

```json
{
  "target_file_id": "target_123",
  "failure_reason": "match_absent",
  "failure_detail": "...",
  "failed_change_id": "chg_002",
  "current_version": 3,
  "current_hash": "...",
  "manifest_summary": [],
  "fresh_target_context": "...",
  "rejected_pdcp_content": "...",
  "pdcp_rules": "..."
}
```

## patchdiff_request_regeneration

Purpose:

Orchestrate regeneration outside the deterministic core runtime.

This is an MCP/server orchestration tool, not a core runtime operation.

Input:

```json
{
  "pdcp_log_id": "log_124",
  "user_request": "Clarify the SAVE section.",
  "regeneration_policy": "from_scratch"
}
```

Behavior:

- retrieve regeneration context
- construct regeneration prompt/context package
- route the request through MCP/model host
- receive regenerated `.pdcp` text
- submit regenerated PDCP as a new attempt through `patchdiff_submit_pdcp`

Restrictions:

- must not mutate target directly
- must not mark rejected attempt as accepted
- must not bypass core validation
- must not apply generated text directly

Output:

```json
{
  "status": "accepted_or_rejected",
  "new_pdcp_log_id": "log_125",
  "parent_pdcp_log_id": "log_124",
  "result": {}
}
```

If the MCP host, not PatchDIFF, owns model calls, this tool may instead return the regeneration context package for the host to use.

## patchdiff_get_target

Purpose:

Return current canonical target state.

Input:

```json
{
  "target_file_id": "target_123"
}
```

Output:

```json
{
  "target_file_id": "target_123",
  "filename": "example.md",
  "target_type": "text/markdown",
  "current_content": "...",
  "current_hash": "...",
  "version": 4,
  "active_editing_cycle_id": "cycle_001"
}
```

## patchdiff_export_target

Purpose:

Export current canonical target back to the chat session.

Input:

```json
{
  "target_file_id": "target_123",
  "format": "original_text"
}
```

Output:

```json
{
  "filename": "example.md",
  "content_type": "text/markdown",
  "content": "...",
  "version": 4,
  "current_hash": "..."
}
```

## patchdiff_save

Purpose:

Create SAVE checkpoint and advance editing cycle.

Input:

```json
{
  "target_file_id": "target_123",
  "expected_current_hash": "...",
  "export_after_save": true
}
```

Behavior:

- verify target hash
- create snapshot
- close current editing cycle
- create new active editing cycle
- preserve logs and ledger history
- optionally export target

Output:

```json
{
  "status": "saved",
  "target_file_id": "target_123",
  "snapshot_id": "snap_001",
  "closed_editing_cycle_id": "cycle_001",
  "new_editing_cycle_id": "cycle_002",
  "current_hash": "...",
  "version": 4,
  "export": {
    "filename": "example.md",
    "content": "..."
  }
}
```

## patchdiff_replay

Purpose:

Verify deterministic reconstruction from initial target plus accepted PDCP log entries.

Input:

```json
{
  "target_file_id": "target_123"
}
```

Output:

```json
{
  "status": "success",
  "target_file_id": "target_123",
  "reconstructed_hash": "...",
  "current_hash": "...",
  "accepted_transactions_replayed": 4
}
```

Failure output:

```json
{
  "status": "failed",
  "failure_reason": "replay_hash_mismatch",
  "failure_detail": "...",
  "pdcp_log_id": "log_003"
}
```

## patchdiff_get_pdcp_log

Purpose:

Return accepted and rejected PDCP history.

Input:

```json
{
  "target_file_id": "target_123",
  "limit": 50
}
```

Output:

```json
{
  "entries": [
    {
      "pdcp_log_id": "log_001",
      "status": "accepted",
      "failure_reason": null,
      "before_hash": "...",
      "after_hash": "...",
      "created_at": "..."
    }
  ]
}
```

## patchdiff_get_manifest_ledger

Purpose:

Return accepted manifest summaries.

Input:

```json
{
  "target_file_id": "target_123",
  "include_previous_cycles": false
}
```

Output:

```json
{
  "entries": [
    {
      "change_id": "chg_001",
      "intent": "...",
      "input_state": "...",
      "output_state": "...",
      "affected_region": "...",
      "user_visible_change": "...",
      "risk": "low",
      "created_at": "..."
    }
  ]
}
```

## Tool Safety Rules

MCP tools must not:

- bypass core runtime validation
- execute PDCP content
- apply regenerated text directly
- mutate target outside accepted PDCP commit
- delete append-only logs
- hide rejected attempts
- treat model output as trusted

Every target mutation must pass through deterministic core transaction application.

## Tool Test Requirements

Test at least:

- upload initializes target
- prompt context contains target metadata and manifest ledger
- PDCP submission accepts valid transaction
- PDCP submission rejects invalid transaction
- rejection diagnostics are returned
- regeneration context can be produced
- regenerated PDCP creates a new log entry
- export returns current canonical target
- SAVE advances editing cycle
- replay verifies hashes
