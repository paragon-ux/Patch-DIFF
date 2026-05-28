# TEST_MATRIX.md

## Scope

This document defines the active test matrix for the next PatchDIFF MVP hardening milestone:

```text
MCP contract tests + MCP E2E tests
```

Earlier local/runtime validation is done or mostly done: local setup, health checks, parser/protocol/unit coverage, Postgres integration coverage, and manual PDCP smoke testing. Manual ChatGPT testing exposed renderer corruption risk. Automated MCP tests now own the product boundary.

This matrix assumes the internal MCP tool registry/wrapper layer is the current product-surface test harness. Real external MCP transport validation is Phase 7.

## Global Test Invariants

- Do not add frontend or chat UI assumptions.
- Do not use SQLite for persistence correctness.
- Do not bypass deterministic parser, validator, matcher, applier, or service paths.
- Do not execute PDCP content.
- Do not silently repair malformed model output.
- Target content mutation must come only from accepted `.pdcp` transactions.
- Rejected attempts must remain logged and leave targets unchanged.
- Regenerated PDCP must be a separate attempt validated from scratch.

## Phase 3. MCP Tool Contract Tests

Goal: prove every MCP wrapper calls the service layer and cannot bypass deterministic validation.

Tool categories:

- upload / initialize target
- build prompt context
- submit PDCP
- get regeneration context
- SAVE
- replay
- export target
- get PDCP log
- get manifest ledger

Required assertions:

- MCP upload creates canonical target.
- MCP upload creates initial snapshot and editing cycle.
- MCP prompt context includes target metadata, version/hash, user request, target context, manifest summary, and PDCP rules.
- MCP submit stores current PDCP display state before/around validation.
- Valid MCP submit accepts and mutates target.
- Invalid MCP submit rejects without mutation.
- Accepted submit appends accepted PDCP log.
- Rejected submit appends rejected PDCP log.
- Manifest ledger appends only for accepted PDCP.
- SAVE tool calls SAVE service and returns SAVE result shape.
- Replay tool calls replay service and returns replay result shape.
- Export tool returns current canonical content/type/hash/version.
- MCP wrapper/tool code does not directly update `cloud_target_files.current_content`.

Expected files:

```text
backend/tests/integration/test_mcp_tool_contract.py
```

## Phase 4. MCP E2E Flow Tests

Goal: test the actual product workflow without a frontend.

Happy path:

```text
upload target through MCP
build prompt context
submit valid PDCP through MCP
assert accepted
get target
assert content changed
get PDCP log
assert accepted log exists
get manifest ledger
assert accepted manifest exists
export target
assert exported content matches current target
```

Rejection path:

```text
upload target
submit invalid PDCP with wrong MATCH
assert rejected
assert failure_reason = match_absent
assert after_hash is null
assert target content/hash/version unchanged
assert rejected log exists
assert manifest ledger did not append accepted entry
```

Regeneration path:

```text
upload target
submit bad PDCP
get regeneration context
submit corrected regenerated PDCP
assert corrected PDCP accepted
assert rejected parent remains logged
assert accepted regenerated attempt is a separate log entry
assert target mutates exactly once
```

Expected files:

```text
backend/tests/integration/test_mcp_e2e_flows.py
```

## Phase 5. Model Output Robustness Through MCP

Goal: convert manual ChatGPT delimiter/rendering failures into automated MCP regression tests.

Malformed outputs to reject:

- separator delimiter corrupted as `=================================================`
- terminator delimiter corrupted as `> > > > > > > REPLACE`
- extra prose before `PDCP 0.2.3`
- extra prose after the final PDCP block
- Markdown blockquote-rendered delimiters
- full rewritten document instead of PDCP
- executable apply function outside payload
- malformed manifest with missing fields

Required assertions for each corrupted output:

- MCP submit returns rejected.
- Failure label is useful and canonical.
- `after_hash` is null.
- Target content/hash/version remain unchanged.
- Rejected attempt is logged.
- Regeneration context can be produced from the rejection.

Positive regression:

- correctly copied raw code-block contents PDCP submits successfully through MCP.

Expected files:

```text
backend/tests/integration/test_mcp_model_output_regressions.py
```

## Phase 6. SAVE / Replay / Export Through MCP

Goal: prove the durable workflow works through the actual MCP-facing interface.

Required assertions:

- MCP SAVE creates snapshot/editing-cycle transition.
- MCP SAVE does not mutate target content/hash/version.
- MCP replay reconstructs current hash.
- MCP replay ignores `current_pdcp_files`.
- MCP replay ignores manifest ledger as operational truth.
- MCP export returns current canonical content, target type, version, and hash.

Expected files:

```text
backend/tests/integration/test_mcp_save_replay_export.py
```

## Phase 7. Real External MCP Adapter Tests

Goal: wire real external MCP transport after the internal contract is locked.

Required assertions:

- External transport exposes the same tool names and payload shapes.
- The Phase 3-6 E2E behaviors pass through real transport.
- External adapter does not redefine service semantics.
- External adapter does not bypass `patchdiff_submit_pdcp`.

## Phase 8. Benchmark / Evaluation Suite

Goal: measure reliability and regression behavior after transport is wired.

Required scenarios:

- valid PDCP acceptance rate over representative text targets
- malformed-output rejection consistency
- regeneration recovery rate after `match_absent` and delimiter corruption
- SAVE/replay/export consistency after accepted transaction sequences
- latency and log integrity for MCP E2E workflows

## Failure Labels To Assert

Use existing canonical labels from `PATCHDIFF_CORE_SPEC.md`, especially:

```text
context_missing
context_invalid
manifest_missing
manifest_invalid
block_malformed
match_absent
match_ambiguous
disambiguation_invalid
target_hash_mismatch
target_version_mismatch
target_diverged
executable_logic_detected
sequential_match_invalid
replay_hash_mismatch
replay_protocol_invalid
replay_transaction_invalid
```

Do not introduce new labels for chat-rendering corruption unless the controlling docs and implementation are explicitly updated. Renderer-corrupted PDCP should map to existing parse/protocol failure labels.

## Verification Commands For Implementation Passes

```powershell
py -3 -m pytest backend\tests\unit
py -3 -m pytest backend\tests\integration
py -3 -m pytest
```

If dependencies or Docker are unavailable, report the exact blocker and the next command to run. Do not claim test success unless the command actually ran.
