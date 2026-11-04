# Editing an existing target

These profiles start from a target ID that a trusted host already obtained.
They expose read, search, SAVE and replay. They differ in how an edit earns
authority. A trusted host can initialize or export targets through
[full](delegation-and-lifecycle.md#full). Choose [workspace](workspace-profile.md)
when the editing connection itself should start from a file path and
publish the result.

## Editor

Use `editor`, the default profile, when one connection needs both exact text
edits and structural edits on an existing target. Read or search the working
text and submit guarded `patchdiff_submit_edits` for an exact replacement.
For a structural edit, call `patchdiff_observe_scope` to obtain a scope receipt
and submit `patchdiff_submit_observed_operations` against that observation.
After acceptance, checkpoint or replay on the same connection as needed.

If strict observation is enabled, use the observed path for writes. The
catalog still shows typed submission, and service admission rejects its
unobserved writes. See the [host's guarded edit loop](../../guides/host-integration-guide.md#the-standard-loop)
and the [structural observation contract](../structural-batch-editing.md).

## Unobserved

Use `unobserved` when exact text and version or hash guards are sufficient
and the connection should also SAVE or replay. For example, read the current
text, replace one uniquely matching sentence in a single typed submission,
and SAVE the accepted version. Exact search can supply context when the
host already knows the string to replace.

This profile has no structural observation or observed submission tool.
A strict-observation deployment rejects unobserved writes. Use the
[read, edit and SAVE example](workspace-profile.md#2-read-the-text-and-prepare-the-edit)
with the host's existing target ID. For a database-only checkpoint, pass
`sync_workspace: false`.

## Observed

Use `observed` when structural authority should precede edits and the same
connection should also SAVE or replay. Use the scope observation tool to
select the relevant scope or batch. Submit guarded observed operations using
the returned IDs and required guards, then checkpoint the accepted version.
This profile omits typed submission.

The same tool supports discovery, selection and paging. Follow the
[structural batch contract](../structural-batch-editing.md#observation-contract)
for its request shapes. Choose [observed editor v2](observed-editor-v2.md)
when the host wants separate tools for listing, selecting and committing.
