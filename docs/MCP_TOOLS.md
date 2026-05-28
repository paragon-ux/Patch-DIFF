# MCP_TOOLS.md

## Purpose

This document defines the MCP-first tool surface for PatchDIFF MVP and the active MCP testing milestone.

The current implementation validates the internal MCP tool registry/wrapper layer. Real external MCP SDK/server adapter wiring is deferred to Phase 7, after contract and E2E tests lock the product behavior.

## Core Principle

```text
MCP layer orchestrates.
Core runtime validates and applies.
Model generates declarative .pdcp.
Postgres stores canonical target state and append-only history.
```

MCP tools must never bypass deterministic parser, validator, matcher, applier, or service-layer commit paths.

## Required MVP Tool Surface

- `patchdiff_handle_upload`
- `patchdiff_initialize_target`
- `patchdiff_build_prompt_context`
- `patchdiff_submit_pdcp`
- `patchdiff_get_regeneration_context`
- `patchdiff_build_regeneration_prompt`
- `patchdiff_request_regeneration`
- `patchdiff_get_target`
- `patchdiff_export_target`
- `patchdiff_save`
- `patchdiff_replay`
- `patchdiff_get_pdcp_log`
- `patchdiff_get_manifest_ledger`

## Tool Contracts

### Upload / Initialize Target

Inputs include filename, UTF-8 text content, content type, and optional project ID.

Expected behavior:

- canonicalize target text
- compute current hash
- create target row
- create initial editing cycle
- create initial snapshot
- return target metadata with version `0`

### Build Prompt Context

Inputs include target ID, user request, and optional context policy.

Expected behavior:

- load canonical target metadata from Postgres-backed services
- include current version/hash
- include active manifest summary
- include target context spans
- include PDCP rules
- include literal replacement scope guidance for quoted strings
- include post-submit audit guidance for literal replacements
- remain outside deterministic core runtime

For quoted literal replacement requests, prompt context should tell the model that matching is case-sensitive by default unless the user explicitly asks for case-insensitive replacement or capitalization variants. If capitalization variants are changed, the manifest must say so. Prefer one change block per actual occurrence; if one block changes multiple occurrences inside the same `MATCH` payload, the manifest must state that multiple occurrences are changed.

After an accepted literal replacement, MCP-facing guidance should verify the final target against the requested literal, report the actual number of changed occurrences, report whether capitalization variants were changed, and avoid summarizing manifest entry count as occurrence count.

### Submit PDCP

Inputs include target ID, raw `.pdcp` content, optional expected version/hash, source, and optional regeneration lineage.

Expected behavior:

- store submitted PDCP as current pending/display state
- submit through deterministic service path
- parse and validate PDCP
- apply only accepted transactions atomically
- append accepted or rejected PDCP log rows
- append manifest ledger rows only for accepted PDCP
- return structured accepted or rejected payload

Accepted response includes status, target ID, before hash, after hash, new version, PDCP log ID, manifest entries added, and warnings.

Rejected response includes status, target ID, failure reason/detail, failed change ID when applicable, before hash, `after_hash = null`, current version/hash, PDCP log ID, and advisory diagnostics.

### Regeneration Context / Prompt / Request

Regeneration tools operate in MCP orchestration, not deterministic core.

Expected behavior:

- load rejected parent log
- include current canonical target metadata
- include diagnostics and failed change ID
- include fresh target context and PDCP rules
- submit regenerated PDCP as a new attempt through `patchdiff_submit_pdcp`
- preserve rejected parent log

### SAVE / Replay / Export

Expected behavior:

- SAVE creates snapshot and editing-cycle transition without mutating content/hash/version
- replay reconstructs from initial canonical target plus accepted logs
- replay ignores `current_pdcp_files` and manifest ledger as operational truth
- export returns current canonical content, target type, version, and hash

### Log And Ledger Reads

Expected behavior:

- PDCP log returns accepted and rejected attempts
- manifest ledger returns accepted manifest entries only
- default manifest reads focus on active editing cycle unless previous cycles are requested

## Tool Safety Rules

MCP wrappers/tools must not:

- directly update `cloud_target_files.current_content`
- call transaction applier directly instead of submit service
- execute PDCP content
- apply regenerated content directly
- mutate target outside accepted core transactions
- mark rejected rows as accepted
- delete append-only history
- hide rejected attempts
- treat model output as trusted
- silently repair malformed PDCP

## Current Milestone Tests

MCP contract and E2E tests must prove:

- upload initializes canonical target state
- prompt context includes expected metadata and rules
- valid PDCP accepts and mutates target through service path
- invalid PDCP rejects without mutation
- accepted/rejected log rows are written correctly
- manifest ledger appends only for accepted PDCP
- regeneration uses separate attempts and parent lineage
- SAVE/replay/export work through MCP tools
- malformed model outputs reject safely
- MCP wrapper source does not directly mutate target content

## Deferred Transport Work

Phase 7 wires the real external MCP adapter. That phase must reuse the same behavior and rerun the MCP E2E suite through the real transport. It must not redefine tool semantics.
