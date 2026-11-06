# MCP profiles

Profiles select the tools available on one external MCP connection.

## Choose a profile

- Start with a project file using [workspace or observed_workspace](workspace-profile.md), which can import,
  edit and publish through one connection. Choose `workspace` for 5-tool exact text editing, or
  `observed_workspace` for 7-tool structural AST observation and atomic multi-edit bundling.
- Work with a target ID using [editor, unobserved or observed](existing-target-editing.md).
  These profiles combine editing with checkpointing and replay.
- Separate editing from lifecycle work using
  [delegated editors and full](delegation-and-lifecycle.md). Choose how much
  context the delegate can read and which edit form it can submit.
- Use [observed editor v2](observed-editor-v2.md) for structural delegation
  with an explicit snapshot envelope and compact commit receipts.
- Consult the [Profile Compatibility & Deployment Matrix](profile-compatibility.md) for OS,
  Docker configurations, and runtime dependency support across all profiles.

The [shared tool specification](../mcp-tools.md) defines the underlying
arguments, receipts and errors. Strict observation is a service setting.
When it is enabled, unobserved writes are rejected even if the selected
profile exposes a submission tool. The workspace profile also refuses
startup with strict observation enabled.

## Startup selection

Set `PATCHDIFF_MCP_PROFILE` before starting `python -m app.mcp.external_adapter`.
An unset variable selects `observed_workspace`. An unknown value prevents startup. Restart
the MCP session to change its profile. Trusted embeddings may construct
`ExternalMCPAdapter(profile="observed")`. Agents cannot override it in a request.
The same immutable profile controls both `tools/list` and `tools/call`.

## Tool catalog

| Profile | Count | Advertised and callable tools |
| --- | ---: | --- |
| `editor` | 7 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_edits`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay` |
| `unobserved` | 5 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_edits`, `patchdiff_save`, `patchdiff_replay` |
| `observed` | 6 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay` |
| `observed_editor` (delegated role) | 4 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_observed_operations` |
| `unobserved_editor` | 3 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_edits` |
| `hybrid_editor` | 1 | `patchdiff_submit_edits` |
| `observed_v2` | 5 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle` |
| `workspace` | 5 | `patchdiff_initialize_target`, `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_edits`, `patchdiff_save` |
| `observed_workspace` (default) | 7 | `patchdiff_initialize_target`, `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle`, `patchdiff_save` |
| `full` (trusted lifecycle) | 18 | Complete registry, including initialization, SAVE, export, audit and replay |
