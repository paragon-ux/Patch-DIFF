# Structural batch editing and MCP profiles

Waymark discovers exact structural identities. PatchDIFF observes disjoint scopes
on one canonical target snapshot, evaluates each operation group inside its own
original slice, and commits the assembled target once. The host owns selection,
intent, proposal generation and retry decisions. A batch never spans targets.

## Trusted startup profiles

Set `PATCHDIFF_MCP_PROFILE` before starting `python -m app.mcp.external_adapter`.
An unset variable selects `editor`; an unknown value prevents startup. Restart
the MCP session to change its profile. Trusted embeddings may construct
`ExternalMCPAdapter(profile="observed")`. Agents cannot override it in a request.
The same immutable profile controls both `tools/list` and `tools/call`.

| Profile | Count | Advertised and callable tools |
| --- | ---: | --- |
| `editor` (default) | 7 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_edits`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay` |
| `unobserved` | 5 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_submit_edits`, `patchdiff_save`, `patchdiff_replay` |
| `observed` | 6 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_observed_operations`, `patchdiff_save`, `patchdiff_replay` |
| `observed_editor` (delegated role) | 4 | `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_observed_operations` |
| `full` (explicit compatibility) | 22 | All registered tools, including initialization, export, history and legacy submissions |

Older integrations and trusted lifecycle operators that initialize/export targets
must explicitly select `full`. The internal registry retains all 22 handlers.
Delegated editors use
`observed_editor` when the host owns SAVE/replay; these lifecycle tools are
uncallable on that editor connection. Existing profile defaults/counts are
unchanged; use a separate full session for trusted finalization.
`PATCHDIFF_STRICT_OBSERVATION_MODE=1` independently rejects unobserved writes at
the service layer, including writes through `full` or the internal registry.

## Observation contract

The public `tools/list` schemas include task-independent examples for filtered
candidate discovery, direct single selection, batch selection, observation paging,
and separate single/batch submissions. Bind illustrative IDs, both guards and
returned cursors to actual receipts. Candidate discovery issues no observation;
known exact identities can be selected directly. Preserve returned Markdown names
including punctuation; ambiguous identities reject. Exact match strings can
include literal newlines. `find_occurrences` indexes the whole current target;
batch groups instead count overlapping matches from one inside their own
scope-local sequential buffer after earlier operations. A preceding catalog is
not mandatory, and single/batch fields cannot be mixed.


External response presentation is independently selected at startup with
`PATCHDIFF_MCP_RESPONSE_MODE=detailed|compact` (default `detailed`). Input schemas,
guards, profiles, stored evidence and recovery semantics are unchanged. In compact
mode candidate entries retain name/kind/parent/start_line/end_line. Batch scopes
omit duplicate start/end/max_chars/next_start/start_line/end_line fields but retain
exact text, original bounds/hash, offset/next_offset, truncation and requested
absolute code-point line_starts. Single observations/pages and failures are
unchanged. Accepted observed submissions omit evidence/groups; counts, identities,
all guards/version aliases, validity, request key, deduplication and all existing
warning fields remain. A presentation object lists actual omissions. Detailed
sessions and durable logs/ledger retain full evidence. See
[the response contract](MCP_TOOLS.md#external-response-representations) and
[editor workflow v1](OBSERVED_EDITOR_WORKFLOW.md).

Extend `patchdiff_observe_scope` with `selections`: 1–32 objects containing required
nonempty `symbol_name` and optional nonempty `kind`. Exact names and existing
qualified `parent.name` identities use the existing Waymark selector logic.
`selections` is exclusive with `symbol_name`, `query`, `observation_id`, top-level
`kind`, and a nonzero `offset`. No new MCP tool is registered.

The server reads one coherent target row, runs Waymark once, and resolves all
selectors from that discovery. Every selected scope must be unique, nonempty and
disjoint; adjacency is allowed, nesting/overlap is rejected. No partial bundle is
persisted. A selection failure includes `selection_index` (zero based) and its
code. An engine discovery failure retains the engine code.

`status: "observed_batch"` returns `observation_bundle_id`, `target_file_id`,
`target_version`, `target_current_hash`, `waymark_engine_version`, `language`, and
ordered `scopes`. Each scope contains `observation_id`, `ordinal`, `symbol`
(`name`, `kind`, `parent`), real `scope_start`/`scope_end`, `observed_scope_hash`,
`text`, `truncated`, and `next_offset`. Positions are canonical LF Unicode code
points, converted from Waymark's authoritative UTF-16 coordinates.

Selection contents total at most **65,536 code points**. Initial returned text
totals at most **32,768 code points**; exceeding it returns
`BUNDLE_RESPONSE_TOO_LARGE`, so the host can divide the selection. Each individual
page retains the existing default 4,000 / maximum 8,000 code points. Page larger
scopes through the existing `observation_id` + `offset` route. Paging is another
observation of current state; a stale, consumed or closed-cycle receipt rejects.

## Atomic submission contract

The existing `patchdiff_submit_observed_operations` accepts either:

- Single form: `observation_id`, `operations`, `intent`, both target guards and
  optional request key. Its existing absolute sequential span semantics remain.
- Batch form: `observation_bundle_id`, nonempty `groups`, `intent`, both
  `expected_target_version` and `expected_current_hash`, and `client_request_id`.
  Single and batch fields cannot be mixed, including explicit null fields.

Each group has exactly `observation_id` and nonempty `operations`, using the
existing typed `match`/`span` operation schema. A request allows 1–32 groups and
at most 128 operations in total. Groups may be a nonempty subset of the issued
bundle, in caller-specified order, with each observation used once.

Under the canonical target's `SELECT ... FOR UPDATE` lock, request-key recovery
or conflict auditing precedes fresh guard checks. Fresh admission verifies the
entire target preimage hash, all participating observation rows, bundle, target,
cycle, version/hash, unused state, original scope hashes, and structural identity
and bounds using **one** Waymark discovery for the locked snapshot.

Each group evaluates against its own original scope slice. `match`, anchors and
`occurrence_index` inspect that group's sequential buffer. Batch `span` offsets
are **scope-local**, beginning at zero and reflecting earlier operations in the
same group. A group cannot access a neighbor's original slice. Zero-width spans
must be strictly interior and carry both nonempty `expected_before` and
`expected_after`, matching exact adjacent text entirely inside that scope.

All groups use `apply_pdcp_transaction`; the global target hash is checked before
the local applier receives the actual slice hash. Successful slices are assembled
in descending original `scope_start` order. One accepted attempt, all accepted
observation links, all ledger rows, target content/hash and exactly one version
increment commit together. A failed group writes one rejected attempt, changes
no target/ledger state, consumes no observations, and reports `group_index`,
`observation_id` where valid, and `underlying_code` without unrelated target text.
Infrastructure exceptions and caller-owned rollback leave no partial acceptance.

Failure context uses `scope_local_original` or `scope_local_intermediate_buffer`
for evaluated groups. Admission failures report `batch_scope_not_evaluated`
without a target-text slice. A no-op warning for the entire transaction is emitted
only when the complete assembled target is unchanged.

Success returns `status`, one `pdcp_log_id`, `before_version`, `after_version`,
`before_hash`, `after_hash`, `observation_bundle_id`, `group_count`, `change_count`,
`client_request_id`, and bounded `groups` summaries. Complete per-operation
runtime facts remain in `evidence.changes` and the accepted-only ledger.

An exact keyed retry returns the original outcome with `deduplicated: true`, even
after a committed response was lost or the target advanced. A changed bundle,
group order/identity, operation, intent or guard with the same key produces
`request_key_conflict` and a separate NULL-key rejection row. Use a new key and
`parent_pdcp_log_id` to explicitly retry a corrected rejected proposal. Accepted
observations are consumed once. Unused members remain unconsumed but become stale
after the version increment. SAVE closes their original editing cycle.

## Durable evidence and replay

The canonical internal record uses `protocol_version = patchdiff-observed-batch/1`
and `runtime_version = patchdiff-observed-batch-r1`. It retains ordered original
tx/2 operations and expected global guards, target and bundle IDs, intent,
editing-cycle identity and authoritative `scope_evidence`: observation identities,
bundle ordinals, group and operation indices, original bounds/hashes, symbol
identities, engine/language and original coordinate facts. The content hash uses
the existing canonical SHA-256 convention. The request fingerprint identifies
the original request before server evidence is attached, including the existing
parent identity rules. Existing transaction records/fingerprints are unchanged.
Durable UUID fields use canonical spelling while the original submitted spelling
remains part of request identity; an exact retry still recovers the same outcome.

Ledger metadata adds `group_index`, `bundle_ordinal`, `operation_index`,
`observation_id`, original `scope_start`/`scope_end`, and
`scope_local_start`/`scope_local_end`. `span_start`/`span_end` are local to that
operation's sequential group buffer; global `change_index` follows group and
operation order. Internal change IDs are prefixed `g<group_index>:` to keep them
unique across groups; original client IDs remain in the canonical operation list.

Migration `20261027_0005` adds nullable paired `observation_bundle_id` and
`bundle_ordinal`, unique bundle/ordinal, bundle and accepted-log indexes. A partial
unique index retains historical one-observation-per-log uniqueness for rows
without bundles. Bundled rows can link many observations to one accepted log.
Downgrade refuses any bundled rows, many-to-one links or accepted batch records;
otherwise it restores the old uniqueness and drops only the new schema fields.

Replay explicitly dispatches the batch pair, checks canonical JSON and its hash,
requires exactly the recorded authoritative links, verifies target/cycle/preimage,
bundle, order, scope coordinates and hashes, reuses the pure local applier and
descending assembly, and verifies output hash/version/count. It never calls
Waymark or changes canonical state. Tampering returns
`BATCH_REPLAY_INTEGRITY_FAILURE`. Historical single-scope and unobserved branches
retain their prior formats and behavior.

## Batch errors

Observation/admission codes are `INVALID_BATCH_REQUEST`, `BATCH_LIMIT_EXCEEDED`,
`BUNDLE_RESPONSE_TOO_LARGE`, `BUNDLE_SELECTION_NOT_FOUND`,
`BUNDLE_SELECTION_AMBIGUOUS`, `BUNDLE_SCOPE_OVERLAP`, `BUNDLE_SCOPE_DUPLICATE`,
`BUNDLE_NOT_FOUND`, `BUNDLE_TARGET_MISMATCH`, `BUNDLE_CYCLE_MISMATCH`,
`BUNDLE_VERSION_MISMATCH`, `BUNDLE_HASH_MISMATCH`, `BUNDLE_ALREADY_CONSUMED`,
`BATCH_GROUP_INVALID`, `BATCH_OPERATION_OUTSIDE_SCOPE`,
`BATCH_OPERATION_REJECTED`, and `BATCH_REPLAY_INTEGRITY_FAILURE`.
Existing request-key, encoding, lineage and single-scope codes remain unchanged.

## Complete Python, JSON and Markdown examples

The following executable example uses the public tool names and actual generated
schemas. The trusted operator creates targets with `full`; the editing client
uses `observed`. In a host, send these same tool names/argument objects through
`tools/call` in separately configured sessions. Both returned guards are passed
unchanged. Replacements deliberately change only the selected scopes.

```python
import json
import uuid
from app.mcp.external_adapter import ExternalMCPAdapter

operator = ExternalMCPAdapter(profile="full")
editor = ExternalMCPAdapter(profile="observed")

def call(adapter, name, **arguments):
    reply = adapter.call_tool(name, arguments)
    assert not reply.get("isError"), reply
    return json.loads(reply["content"][0]["text"])

def edit_example(filename, content, content_type, selections, operations):
    target = call(operator, "patchdiff_initialize_target", filename=filename,
                  content=content, content_type=content_type)
    tid = target["target_file_id"]
    bundle = call(editor, "patchdiff_observe_scope", target_file_id=tid,
                  selections=selections)
    assert bundle["status"] == "observed_batch", bundle
    result = call(editor, "patchdiff_submit_observed_operations", target_file_id=tid,
        observation_bundle_id=bundle["observation_bundle_id"],
        expected_target_version=bundle["target_version"],
        expected_current_hash=bundle["target_current_hash"],
        client_request_id=f"example-{uuid.uuid4()}", intent="Update selected structures",
        groups=[{"observation_id": scope["observation_id"], "operations": ops}
                for scope, ops in zip(bundle["scopes"], operations)])
    assert result["status"] == "accepted" and result["after_version"] == 1, result
    assert call(editor, "patchdiff_save", target_file_id=tid)["status"] == "saved"
    assert call(editor, "patchdiff_replay", target_file_id=tid)["materialized_state_matches"]
    return call(operator, "patchdiff_export_target", target_file_id=tid)["content"]

python_output = edit_example("quotas.py",
    "def api_quota():\n    return 100\n\ndef etl_quota():\n    return 100\n\ndef ui_quota():\n    return 100\n",
    "text/x-python",
    [{"symbol_name": name, "kind": "function"} for name in ("api_quota", "etl_quota", "ui_quota")],
    [[{"op": "match", "match": "return 100", "replace": "return 200"}] for _ in range(3)])
assert python_output.count("return 200") == 3

json_output = edit_example("quotas.json",
    json.dumps({"tenants": [{"id": name, "quota": 100} for name in ("api", "etl", "ui")]}, indent=2) + "\n",
    "application/json", [{"symbol_name": f"tenants[{name}]"} for name in ("api", "etl", "ui")],
    [[{"op": "match", "match": '"quota": 100', "replace": '"quota": 200'}] for _ in range(3)])
assert all(tenant["quota"] == 200 for tenant in json.loads(json_output)["tenants"])

markdown_output = edit_example("release.md",
    "# Release\n\n## Deploy\nstate: old\n\n## Rollback\nstate: old\n\n## Verification\nstate: old\n",
    "text/markdown", [{"symbol_name": name} for name in ("## Deploy", "## Rollback", "## Verification")],
    [[{"op": "match", "match": "state: old", "replace": "state: ready"}] for _ in range(3)])
assert markdown_output.count("state: ready") == 3
```

## Deterministic capability evidence

Discovery can use the internal [resident Waymark worker](WAYMARK_WORKER.md) through trusted startup configuration. It retains fresh locked verification and the existing transaction schemas, catalogs and replay profiles.

Run `python backend/tests/verification/structural_batch/verify.py --output <new-directory>` with
live Postgres and pinned Waymark dependencies. The runner issues real stdio MCP
requests and counts `tools/call` lines separately for trusted lifecycle and
editing clients. Its pinned declarative operation fixture was extracted from the
archived exploratory transcript. CI retains only the required original five-file
inputs and independent oracle under `backend/tests/verification/`; internal
transcripts, controllers, captures and the Gate 2 manifest remain unchanged in the
ignored local `evaluation/` directory. Full-byte equality precedes the 20 behavioral checks.

The original exploratory C recorded 25 observations (5 discovery + 20 selected),
20 editing submissions, 1 search, 5 SAVE and 5 replay: 56 MCP calls. With known
selectors, the deterministic batch path requires 5 bundled observations, 5
submissions, 5 SAVE and 5 replay: 20 editing calls. Initialization, export and
audit inspection are counted separately as trusted lifecycle work. API-call
reduction establishes capability; it establishes no model latency, context,
token-cost or comparative performance result. Gate 2 remains closed, and a new
direct three-arm run still requires owner authorization.

## Versioned external view

Opt-in `observed_v2` separates candidate listing, selection, paging and bundle commit into five external purpose-specific tools. It lowers unchanged values into the structural batch services described here. See [the v2 contract](MCP_EDITOR_V2.md); existing profile catalogs and durable formats remain unchanged.
