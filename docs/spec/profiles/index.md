# MCP profiles

Profiles select the tools available on one external MCP connection.

## Startup selection

Set `PATCHDIFF_MCP_PROFILE` before starting `python -m app.mcp.external_adapter`.
An unset variable selects `editor`; an unknown value prevents startup. Restart
the MCP session to change its profile. Trusted embeddings may construct
`ExternalMCPAdapter(profile="observed")`. Agents cannot override it in a request.
The same immutable profile controls both `tools/list` and `tools/call`.

## Tool catalog

| Profile | Count | Advertised and callable tools |
| --- | ---: | --- |
| `editor` (default) | 7 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_edits`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay` |
| `unobserved` | 5 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_edits`, `patchdiff_save`, `patchdiff_replay` |
| `observed` | 6 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay` |
| `observed_editor` (delegated role) | 4 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_observed_operations` |
| `unobserved_editor` | 3 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_edits` |
| `hybrid_editor` | 1 | `patchdiff_submit_edits` |
| `observed_v2` | 5 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_list_scopes`, `patchdiff_observe_scopes`, `patchdiff_commit_bundle` |
| `workspace` | 5 | `patchdiff_initialize_target`, `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_edits`, `patchdiff_save` |
| `full` (explicit compatibility) | 22 | All registered tools, including initialization, export, history and legacy submissions |

Use [`workspace`](WORKSPACE.md) to import and publish a
workspace file. Use `full` for export, administrative audit calls and legacy
submissions. Delegated editors can use `observed_editor` while the trusted host
handles SAVE/replay in a separate session. The internal registry retains all
22 handlers. `PATCHDIFF_STRICT_OBSERVATION_MODE=1` independently rejects
unobserved writes at the service layer and prevents `workspace` startup.

See the [workspace profile](WORKSPACE.md) and [observed editor v2](MCP_EDITOR_V2.md)
for their profile-specific contracts. The [shared tool specification](../MCP_TOOLS.md)
defines the arguments, receipts and errors of the underlying tools.
