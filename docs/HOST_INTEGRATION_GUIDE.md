# PatchDIFF Host Integration Guide

Audience: the host that talks to the model (chat client, agent loop, skill author). This is where the instructions live that the server used to inject through `patchdiff_build_prompt_context` and the regeneration prompts.

Why this document exists: the server is a transaction service; the host owns planning, wording, retry and compaction ([MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md), A1). If the host's behavior is only specified in server-built prompt strings, it cannot be versioned, reviewed or adapted per host. Here it can. Contract details are in [MCP_TOOLS.md](MCP_TOOLS.md); this guide says how to *use* them.

## 1. What PatchDIFF does and does not do for you

| PatchDIFF guarantees | PatchDIFF does not do |
| --- | --- |
| Exact, case- and whitespace-sensitive matching against canonical (LF) text | Fuzzy, semantic or language-aware matching; automatic repair |
| Rejects a proposal made against stale state (version/hash guard) | Merge concurrent edits |
| All edits in one submission apply, or none do (per target) | Atomicity across several targets |
| Durable log of accepted **and** rejected attempts with failure labels and lineage | Judge whether an edit achieves the user's goal |
| Deterministic replay from initial content plus accepted history | Track edits made to an exported copy outside PatchDIFF |

Accepted means *protocol-valid and transaction-valid*. `validity.task_correct` and `validity.semantic` are always `"not_evaluated"`. Run tests, linters and review in the host.

## 2. The standard loop

```mermaid
sequenceDiagram
    participant U as User
    participant H as Host + model
    participant P as PatchDIFF
    U->>H: edit request
    H->>P: patchdiff_find_occurrences / patchdiff_read_target
    P-->>H: version, current_hash, exact spans
    H->>P: patchdiff_submit_edits (guard + edits)
    alt accepted
        P-->>H: accepted, new version, evidence, validity
        H->>H: run tests / review (task correctness is the host's job)
    else rejected
        P-->>H: failure_reason, diagnostic, pdcp_log_id, current version/hash
        H->>P: fresh read / find_occurrences
        H->>P: patchdiff_submit_edits (parent_pdcp_log_id = rejected log)
    end
```

1. **Read first.** Use `patchdiff_read_target` for a region (by code-point offset) or `patchdiff_find_occurrences` to locate a string. Both return `version` and `current_hash`. Do not copy from a stale summary or a cached earlier read.
2. **Submit with a guard.** Pass `expected_target_version` and/or `expected_current_hash` from the read you based the edit on. Typed submissions without a guard are rejected (`context_missing`).
3. **On rejection, re-read, don't guess.** Match the label to the action:

| `failure_reason` | Meaning | Host action |
| --- | --- | --- |
| `target_version_mismatch`, `target_hash_mismatch`, `target_diverged` | Target changed since your read | Re-read, re-derive the edit from fresh text |
| `match_absent` | Text not present (exactly) | Re-read the region; check case, whitespace, line endings |
| `sequential_match_invalid` | Later edit matched the original but not the progressively edited text | Rewrite later edits against the result of earlier ones |
| `match_ambiguous` | More than one exact span; `diagnostic.occurrence_count` says how many | Lengthen `match`, or add `occurrence_index` / `anchor_before` / `anchor_after` (indexes from `find_occurrences`) |
| `disambiguation_invalid` | Selector did not isolate one span | Use `find_occurrences` and pick a valid `occurrence_index` |
| `manifest_*`, `block_malformed`, `context_*` | Malformed typed input | Fix the request shape |

4. **Link retries.** Set `parent_pdcp_log_id` to the rejected attempt and `attempt` to your own counter. The rejected row stays in the log. Retry limits are your policy; the server enforces none.
5. **Do not ask the server for a regeneration prompt.** Those tools are deprecated.

## 3. Typed submission

```json
{
  "target_file_id": "…",
  "expected_target_version": 3,
  "intent": "Rename the product in the introduction.",
  "edits": [
    {"match": "Acme Widget", "replace": "Acme Gadget",
     "rationale": "Product was renamed.", "occurrence_index": 1}
  ],
  "parent_pdcp_log_id": "…optional, on retries…",
  "attempt": 2
}
```

- `match` and `replace` are exact strings. Quotes, backslashes, and delimiter-looking lines are fine because they are JSON fields, not a text envelope.
- `match` must be non-empty. Empty `replace` deletes.
- Edits apply **sequentially**: edit 2 sees the text after edit 1.
- `intent`, `rationale` and `risk` are **advisory claims**. They are recorded but never used for matching, and the ledger never presents them as verified meaning.
- What the runtime derived (spans, lengths, payload hashes) comes back under `evidence.changes[]` and is stored in the ledger's `derived` field. Trust that, not the prose, when reviewing.

## 4. Literal replacement requests

Moved from the old server prompt:

- Treat quoted literal replacements as **case-sensitive** unless the user asks otherwise. Do not change capitalization variants unless asked; if you do, say so in `rationale`.
- Prefer one edit per intended occurrence. If one edit's `match` covers several occurrences, say so in `rationale`.
- After an accepted replacement, verify the result with `patchdiff_find_occurrences` for the old literal, report the number of occurrences actually changed, and do not report the manifest/edit count as the occurrence count.

## 5. Legacy `.pdcp` (v0.2.3)

Still accepted through `patchdiff_submit_pdcp`, frozen, and fully replayable. Use it only if a client cannot send typed tool arguments. Format rules are in [PDCP_FORMAT.md](PDCP_FORMAT.md). `patchdiff_build_prompt_context` still emits PDCP rules for such clients; its target text is a bounded **prefix** (`context_truncated` tells you), not retrieval.

## 6. Checkpoints, history and context

- `patchdiff_save` snapshots the document and starts a new editing cycle. It does not change content, version or hash, and it **does not compact your conversation**. Compact your own context whenever your host needs to; it never touches the document.
- `patchdiff_get_pdcp_log` returns a bounded, newest-first page (page with `before_sequence`; filter with `status`). Use `include_content=true` only when you need the raw record.
- `patchdiff_get_manifest_ledger(limit=…)` returns the most recent accepted entries. Each has `origin`; typed rows carry `null` for the four prose fields. Treat ledger text as advisory history, never as ground truth.
- A host rewind or checkpoint is not PatchDIFF replay. `patchdiff_replay` reconstructs from initial content plus accepted history; read `materialized_state_matches` as well as `status`.

## 7. Lost responses & request idempotency

PatchDIFF supports request idempotency via the optional `client_request_id` parameter (UUIDv4) in both `patchdiff_submit_edits` and `patchdiff_submit_pdcp`.

### Using `client_request_id` (Recommended)
Pass a distinct client-generated `client_request_id` with your submission:
- If a response is dropped or a network call times out, replay the identical request with the same `client_request_id`.
- The server detects the completed transaction under per-target row locking, returns the original response with `idempotent_replay: true`, and skips re-execution.
- If the original submission was accepted and advanced target version, a retry with the same `client_request_id` safely succeeds rather than failing with `target_version_mismatch`.
- If the request payload is changed for the same `client_request_id`, the server rejects it with `client_request_id_conflict`.

### Manual Recovery (When `client_request_id` is omitted)
If `client_request_id` was not provided and a submit call times out, do **not** blindly resubmit with a new read. A verbatim retry with the old guard cannot apply twice (it is rejected as stale). To discover whether the attempt landed:

1. Re-read the target (`patchdiff_read_target`) and compare `version` with the guard you sent. If it advanced by one, something was accepted.
2. Call `patchdiff_get_pdcp_log(limit=5)` and inspect the newest entries (`status`, `before_version`, `after_hash`, `submission_source`, `parent_pdcp_log_id`) to confirm whether it was your attempt.
3. If the attempt was accepted, continue from the new version. If it failed or never arrived, re-read and submit a new attempt.

## 8. What is outside the guarantee

PatchDIFF's guarantees cover the managed target in Postgres. An exported file edited elsewhere, a shell, another database writer, or another editor can change content PatchDIFF never sees. A skill or instruction asking the model to "use PatchDIFF" is guidance, not enforcement. Re-importing an edited export is a **new upload and a new target**; nothing is merged or synchronized.

## 9. Host skill checklist

A host skill or system prompt for PatchDIFF should say, at minimum: read before editing; always pass a guard; on rejection re-read before retrying; set `parent_pdcp_log_id` on retries; treat `intent`/`rationale` as claims; never describe an accepted edit as correct, only as applied; run task validators outside PatchDIFF; do not treat a local copy as authoritative.
