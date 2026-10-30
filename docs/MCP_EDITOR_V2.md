# Versioned observed editor interface

`PATCHDIFF_MCP_PROFILE=observed_v2` selects eight external tool purposes at process
startup. It is opt-in. The existing editor (7), unobserved (5), observed (6),
observed_editor (4) and full (22) profiles retain their tool sets, argument contracts
and response presentation. The internal registry still has22 handlers. These
external aliases dispatch to the existing observation and observed-submission
services; they introduce no transaction format, runtime, migration or replay path.

| Tool | Purpose | Existing service route |
| --- | --- | --- |
| `patchdiff_read_target` | Bounded target text | read_target |
| `patchdiff_find_occurrences` | Exact target-wide search | find_occurrences |
| `patchdiff_list_scopes` | Candidate identities without observation authority | observe_scope candidate mode |
| `patchdiff_observe_scopes` | Issue 1..32 disjoint scopes on one snapshot | observe_scope selections mode |
| `patchdiff_read_observation` | Page one issued scope | observe_scope observation_id mode |
| `patchdiff_commit_bundle` | Atomic scope-local grouped operations | submit_observed_operations batch mode |
| `patchdiff_observe_one` | Issue a single scope, including one above the batch size cap | observe_scope symbol_name mode |
| `patchdiff_commit_observation` | Single-scope operations with absolute sequential spans | submit_observed_operations single mode |

The first six are the common bundle workflow. The last two preserve single-scope
capabilities: batch issuance caps the combined selected text at 65,536 code points,
so replacing every single request with a one-group bundle would lose capability.
All eight remain available for the connection. The common six carry
`_meta: {"antigravity/alwaysLoad": true}` on modern connections. This is a host hint;
selective loading by a particular IDE has not been established. Budget for all
eight declarations unless actual host evidence shows otherwise.

## Explicit snapshots and route boundaries

Selection returns `snapshot` with exactly `target_file_id`,
`expected_target_version`, `expected_current_hash`, and `observation_bundle_id`
(or `observation_id` for observe_one). A commit accepts that same object without
renaming fields. Bundle commits also require `intent`, `client_request_id` and
`groups`; each group pairs a returned observation ID with its ordered operations.
Single commits require `intent` and `operations`; their request key is optional,
as in the existing single service. The schemas retain both match and span forms,
disambiguators, insertion guards, source, retry lineage and correlation options.

The model no longer chooses between top-level single/batch argument envelopes,
combines catalog/selection/page fields, or renames returned version/hash fields.
It still selects structures, writes exact operations and binds scope IDs. This
is an interface change, not an instruction to omit discovery or verification.

Normalization only selects the named route and unwraps supplied fields. It does
not refill guards, reinterpret coordinates, normalize UUID spelling, derive
operations, or infer authority. Unknown envelope fields and unrouteable snapshots
fail explicitly. Known-target malformed operational values still reach the
shared service's audited admission path. Missing/null single/page identities
cannot fall through to candidate discovery. Tools/list schemas guide construction;
they are not a prevalidation layer that bypasses service audit or keyed recovery.

The existing target lock, both explicit guards, current-cycle observation checks,
scope boundaries, ordered simulation, all-or-nothing commit, append-only audit,
request fingerprints and deterministic replay remain authoritative. Exact keyed
recovery precedes fresh guard and consumed-observation checks. The same normalized
legacy request can recover across facades; changing its raw values changes its
identity under the existing fingerprint rules.

## Commit receipts

New-profile commit results distinguish:

- `transaction.before` / `transaction.after`: original transaction versions/hashes,
  taken from the service result, including on recovery.
- `current`: target version/hash at this invocation. A recovered transaction's
  after version can be lower than current.
- `transaction.pdcp_log_id`, request key, deduplication flag and operation/group
  counts: existing durable result metadata.
- `warnings`: items plus total and truncated flags.
- `validity` and diagnostics: validation evidence, not task correctness. Task and
  semantic correctness remain `not_evaluated`.

Receipts omit per-change span/hash facts and group lists. An editor cannot check
offsets or digests, and the first v2 canary listed them per change (3-8 KB per
commit, 2 of 5 truncated) before 19 read-back searches, against 4-8 for the
~900-byte compact receipts of the PR18/PR19 runs. The facts remain unchanged in
the append-only log and manifest ledger for trusted full-profile clients.

The entire logical commit/error JSON is capped at 8,192 UTF-8 bytes when serialized
compactly, including metadata, diagnostics and all collections.
`presentation.truncated` and `omitted_fields` disclose omissions; collection totals
remain available. Oversized invalid identity echoes become null with byte/hash
omission metadata, never a shortened string pretending to be an authentic ID.
This cap is a server presentation choice, not a measured host limit. Observation
and text/search results keep the existing service bounds and paging semantics.
`list_scopes` always applies the compact candidate projection (name, kind, parent
and line bounds, with `presentation.omitted: ["candidate_details"]`).

Receipts do not invent final-text snippets from intermediate spans or echo a
proposed replacement as independently verified text. Additional reads can resolve
task uncertainty; host-owned behavioral/full-byte verification remains separate.
Both detailed and compact startup response modes use this same v2 presentation.

Definitive tool failures set `isError: true`, retaining their domain/audit data.
Accepted transactions with advisory warnings remain successful. Infrastructure
exceptions return `status: outcome_unknown`; they do not certify rejection or
absence of a commit. Exact keyed retries use the original arguments and key.
Legacy profiles keep their previous error-envelope behavior.

## MCP negotiation and startup

The adapter supports 2024-11-05,2025-06-18 and2025-11-25. It honors a supported
requested revision; an unsupported revision offers 2025-11-25. Missing revision
retains2024 compatibility. Invalid initialization is rejected and a connection
cannot renegotiate to a different revision. This is not a 2026 protocol upgrade.

For modern negotiated connections, v2 declarations include outputSchema and
truthful annotations, and results contain the same logical JSON in text and
structuredContent. Text remains available for hosts with incomplete structured
result handling. On2024 connections the additional declarations/channel are
omitted. Wire bytes include envelope escaping and, for modern v2, both channels;
the 8 KiB logical cap is not a bound on that duplicated wire envelope.

Annotations are hints, not enforcement. Read/search/catalog/page are read-only;
issuing observations writes authority rows. Submissions are destructive and are
not unconditionally idempotent: request-key conflict retries can add audit rows.

Set these on the actual editing MCP process:

```text
PATCHDIFF_MCP_PROFILE=observed_v2
PATCHDIFF_STRICT_OBSERVATION_MODE=1
PATCHDIFF_WAYMARK_MODE=resident
```

Use the same executable/database/Node configuration as the tested deployment.
Trusted initialization, SAVE, replay and export use a separate full-profile
connection. The editor's8-tool allowlist denies lifecycle and all old mixed or
unobserved mutation routes. The host must keep its operator connection, oracle
and privileged data outside the editing agent's tool/context access.

For a live comparison, keep the ordinary task and target mapping; do not add
coaching to skip schema discovery, force a particular edit form, or stop checking.
Only the owner launches model canaries. Gate 2 and merge authorization are unchanged.

## Evidence and costs

More specific tools reduce within-tool route alternatives while increasing the
number of available tool names. Snapshot nesting adds bytes but removes field
translation. Output schemas and receipts also cost context/result bytes. No model
latency or correctness benefit is established by static catalog measurements or
backend tests. Report the full available catalog, actual host loading if known,
text/structured/wire sizes and ordinary-use correctness separately.

Relevant primary specifications: [MCP tools 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools),
[MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle),
[MCP annotations](https://modelcontextprotocol.io/specification/2025-11-25/schema#toolannotations),
and [Antigravity changelog](https://antigravity.google/docs/changelog).
These establish available interface mechanisms, not PatchDIFF performance gains
or the installed IDE's exact rendering of schemas and dual-channel results.

Deterministic regression (real stdio + live Postgres, zero model invocations):

```bash
python backend/tests/verification/structural_batch/verify.py --editor-v2 --host-finalize --output /tmp/five-file-v2-fresh
```

This authenticates the unchanged five fixtures and archived regression operations,
checks full-byte/behavioral equivalence and trusted scalar finalization. Archived
operations/oracle data must never be supplied to a live editing agent.
