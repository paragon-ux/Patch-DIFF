# Observed editor workflow, version 1

This is a task-independent role brief for an editing subagent. The host supplies
the original user task and a fresh authorized target mapping. It retains the
original experimental prompts separately; do not append this brief to conflicting
instructions requiring the editor to SAVE, replay, or write a detailed report.

## Serving process and contracts

The trusted host configures the actual editor MCP process before startup:

```text
PATCHDIFF_WAYMARK_MODE=resident
PATCHDIFF_MCP_PROFILE=observed
PATCHDIFF_STRICT_OBSERVATION_MODE=1
PATCHDIFF_MCP_RESPONSE_MODE=compact
```

Preserve required Node executable configuration. Restart and record effective
configuration and tools/list; a prompt alone does not configure the server.
Exactly six tools remain advertised and callable: patchdiff_read_target,
patchdiff_find_occurrences, patchdiff_observe_scope,
patchdiff_submit_observed_operations, patchdiff_save, patchdiff_replay.

Provide the published tool contracts through the host's supported schema/context
mechanism. Direct typed exposure or preloading may depend on the host. When a
generic dispatcher requires schema inspection, allow the registered tool-help
files. If the host spills a result, allow that session's generated result file.
Neither permission authorizes native target inspection, implementation access,
other-session evidence, prepared operations, or oracle access.

## Editor brief

- Inspect and edit only the supplied fresh targets through authorized MCP reads
  and observed submission. Preserve all task requirements and unrelated bytes.
- Select known exact structural identities directly with selections; a preceding
  candidate catalog is optional. For unknown identities, narrow discovery using
  query/kind. Do not guess ambiguous selections or treat discovery as authority.
- Use issued scope text and identities. Prefer exact match operations where
  appropriate. Operations are sequential within each group's original slice;
  batch span coordinates are scope-local Unicode code points. Follow existing
  insertion adjacency/boundary rules. Never substitute a fuzzy match.
- Copy target ID, both guards, bundle ID and scope observation IDs from the
  original bundle. Do not refresh guards merely to make a stale proposal pass.
- Use a unique stable request key per proposal. Retain the entire exact call for
  response-loss recovery. A corrected rejected proposal uses a new key and the
  rejected pdcp_log_id as parent; argument errors may have no admitted log.
- Respect truncated/next_offset and retrieve needed source through existing
  observation_id/offset paging. Retained line_starts are absolute code points.
  Never edit unseen text based on a truncated preview alone.
- The trusted host owns SAVE, REPLAY, export and independent task verification.
  Do not call lifecycle tools. Finish with at most 150 words identifying completed
  targets and any unresolved failures. The host assembles evidence from receipts.

Generic current-schema example, using a real returned bundle and a unique key:

```python
arguments = {
    "target_file_id": bundle["target_file_id"],
    "expected_target_version": bundle["target_version"],
    "expected_current_hash": bundle["target_current_hash"],
    "observation_bundle_id": bundle["observation_bundle_id"],
    "client_request_id": unique_key_for_this_proposal,
    "intent": "Enable the requested setting",
    "groups": [{"observation_id": bundle["scopes"][0]["observation_id"],
                "operations": [{"op": "match", "match": "enabled = False",
                                "replace": "enabled = True"}]}],
}
```

The strings above illustrate syntax; construct actual operations from the task
and authoritative observations. Do not seed a live canary with this example or
archived solutions. Lifecycle ownership is role policy unless the host supports
a four-tool role allowlist; the server's observed profile still exposes six.

## Host compatibility and evidence

Compact output reduces supplementary metadata, not all necessary source text.
Before an owner-run canary, make a short non-model check of actual host result
delivery. Record inline/spilled results, UTF-8 bytes and any supported output-limit
setting. Do not assume a universal byte threshold or invent a host setting. Use
existing pagination or permitted spill retrieval when required; record residual
lookups/spills rather than adding a gateway or changing transaction semantics.

Use [trusted scalar finalization](HOST_INTEGRATION_GUIDE.md#trusted-scalar-finalization).
Keep manifests, full transcripts, raw MCP arguments/results, rejected attempts,
exports and independent oracle results private and non-overwriting. A new run of
this workflow is not the frozen comparative arm; Gate 2 remains closed. Reduced
model-managed calls do not imply fewer backend lifecycle calls or a measured
latency improvement.
