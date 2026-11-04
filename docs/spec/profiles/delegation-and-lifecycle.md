# Delegated editing and trusted lifecycle

A host can give the editor a limited connection while retaining
initialization, SAVE, replay and export on its own connection. Supply the
editor with the target ID and enough task context to choose and verify an
edit. Treat profile selection as a tool boundary. The server checks every
call against the selected profile and applies the same service validation.

## Observed editor

Use `observed_editor` to delegate structural edits with the existing
observation and observed submission tools. The editor can read or search
text, obtain a scope receipt and submit guarded operations. The trusted
host consumes the accepted receipt and handles lifecycle calls on a separate
connection. See the [observed editor workflow](../../guides/observed-editor-workflow.md)
for the complete editor and host sequence. For an explicit snapshot
envelope and compact commit receipt, choose [observed editor v2](observed-editor-v2.md).

## Unobserved editor

Use `unobserved_editor` when the delegate should read, search and submit exact
text edits. For example, give it a target ID and a request to change a
heading. It reads the current version, disambiguates the heading if needed
and submits a guarded replacement. It returns the acceptance or rejection
to the host for the next lifecycle action.

The delegate has no structural observation, SAVE or replay. This is the
read/search/submit part of the [existing-target text workflow](existing-target-editing.md#unobserved).
Strict observation blocks its unobserved submissions.

## Hybrid editor

Use `hybrid_editor` when the host already supplies the exact source context
and current version or hash. The delegate can call only `patchdiff_submit_edits`.
For example, the host reads a target, then gives the delegate the target ID,
the relevant exact text and version, and the requested change. If the guard
fails or the match is ambiguous, the host obtains fresh context before the
delegate prepares another submission.

Use [unobserved editor](#unobserved-editor) if the delegate should read or search
for itself. Hybrid editing also depends on admission of unobserved writes.

## Full

Use `full` for a trusted operator who needs the complete 17-tool catalog.
It can initialize targets, read and edit them, SAVE, replay, export, inspect
audit history and support host-owned finalization. A typical trusted sequence
initializes a target and hands its ID to a restricted editor, then checks
the accepted version, checkpoints it, replays the target or exports it as
needed. See the [host lifecycle recipe](../../guides/host-integration-guide.md#trusted-scalar-finalization).

The full catalog includes the underlying structural tools. The
[observed v2 tool aliases](observed-editor-v2.md) are specific to that profile.
Strict observation still applies at the service boundary even on a full
connection. Consult the [shared tool contract](../mcp-tools.md) for the
complete catalog and argument rules.
