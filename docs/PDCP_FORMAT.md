# PDCP_FORMAT.md

## Scope

This document defines the transaction formats supported by PatchDIFF:
1. **`patchdiff-tx/1` (Primary Typed Transaction)**: A structured JSON format passed directly through MCP tool arguments (`patchdiff_submit_edits`), stored as canonical JSON in `append_only_pdcp_logs.pdcp_content`. Delimiter-collision free, with reduced mandatory prose overhead.
2. **`patchdiff-tx/2` (Guarded Operations)**: canonical JSON with required intent and guard plus ordered `operations` carrying explicit `op:match` or `op:span`. Span records require start/end/expected_text/replace, use sequential canonical code-point coordinates and allow empty-span insertion. Optional `expected_before`/`expected_after` check the exact adjacent text; a record that contains them is recorded under immutable runtime `patchdiff-mvp-0.5.0` instead of `0.3.0`. See [MCP_TOOLS.md](MCP_TOOLS.md#patchdiff_submit_operations-patchdiff-tx2) for complete fields and immutable profile `patchdiff-mvp-0.3.0`. Example canonical record: `{"expected_current_hash":null,"expected_target_version":2,"format":"patchdiff-tx/2","intent":"Insert a note","operations":[{"end":0,"expected_text":"","op":"span","replace":"Note: ","start":0},{"match":"alpha","op":"match","replace":"beta"}],"target_file_id":"<UUID>"}`.

3. **`patchdiff-tx/3` (Sole Replacement)**: A separate sole replacement record: `{"format":"patchdiff-tx/3","target_file_id":"<UUID>","intent":"explicit replacement","operations":[{"op":"replace_all","replace":"new text"}],"expected_target_version":0,"expected_current_hash":null}`. Exactly one operation with exactly `op,replace` is permitted. No match/span/selectors or mixed transaction in tx/3; tx/2 continues refusing replace_all. Both top-level guard keys are persisted with raw values, including null, through the same canonical JSON identity rule. At least one valid guard is required. Default change ID is chg_001; risk is low. Profile 0.4.0 enables replacement without modifying 0.3.0. Fresh size admission is a service rule, not decoding/replay grammar.
4. **`.pdcp` v0.2.3 (Frozen Legacy Text Format)**: The declarative text format with `PDCP 0.2.3` header, 7 required manifest fields per change, and `MATCH/REPLACE` delimiters, retained for backward compatibility and historical replay.

None of these formats is executable code. All lower into the same internal `ParsedPDCP` representation and execute through the same deterministic applier (`apply_pdcp_transaction`).

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](MODERNIZATION_ARCHITECTURE.md).
As-built record: [MODERNIZATION_CHANGE_DOC.md](MODERNIZATION_CHANGE_DOC.md).

---

## 1. Typed Transaction Format (`patchdiff-tx/1`, Primary)

### Wire Representation (MCP Tool Arguments)
Submitted over MCP via `patchdiff_submit_edits`:
```json
{
  "target_file_id": "11111111-1111-1111-1111-111111111111",
  "expected_target_version": 0,
  "expected_current_hash": null,
  "intent": "Update user settings label and default value.",
  "edits": [
    {
      "match": "theme: dark",
      "replace": "theme: system",
      "change_id": "chg_001",
      "rationale": "Align default theme with OS preferences.",
      "risk": "low"
    },
    {
      "match": "notifications: true",
      "replace": "notifications: false",
      "occurrence_index": 2
    }
  ],
  "client_request_id": "req-settings-v1"
}
```

### Top-Level Properties
- `target_file_id` (`string`, required): UUID of target document.
- `intent` (`string`, required nonblank): High-level transaction intent for audit logs and ledger.
- `edits` (`array`, required, `minItems: 1`): Ordered list of edits executed sequentially.
- `expected_target_version` (`integer 0..2^63-1 | null`): Version precondition guard.
- `expected_current_hash` (`string | null`): exactly 64 lowercase hex SHA-256 target hash precondition guard.
- *Guard requirement*: At least one of `expected_target_version` or `expected_current_hash` must be non-null.
- `client_request_id` (`string | null`, optional): 1..128 printable ASCII characters without whitespace for request deduplication.
- `parent_pdcp_log_id` (`string | null`, optional): UUID of rejected parent attempt when retrying.
- `attempt` (`integer 1..2^31-1 | null`, optional): Retry attempt counter.

### Edit Item Schema (`TYPED_EDIT_JSON_SCHEMA`)
- `match` (`string`, required non-empty): Exact target text to match.
- `replace` (`string`, required): Replacement text. Empty string `""` denotes deletion.
- `change_id` (`string | null`, optional): A complete 1–64-character identifier containing only ASCII letters, digits, underscore, period, colon or hyphen; trailing newlines reject. Defaults to `chg_001`, `chg_002`, ... by 1-based index if omitted or `null`. Duplicate IDs reject with `FailureReason.MANIFEST_INVALID`.
- `rationale` (`string | null`, optional): Nonblank per-edit explanation when supplied.
- `risk` (`"low" | "medium" | "high" | null`, optional): Advisory risk classification.
- `occurrence_index` (`integer >= 1 | null`, optional): 1-based index over exact matches.
- `anchor_before` (`string | null`, optional): Exact substring that must precede candidate span.
- `anchor_after` (`string | null`, optional): Exact substring that must succeed candidate span.
- Selectors are constraints even when there is only one match. An index beyond the occurrence count or an excluding anchor rejects; combined selectors must all hold. Anchors need not be adjacent.
- `additionalProperties: false`: Unknown fields (such as `region_hint`) reject with `FailureReason.MANIFEST_INVALID`.

### Canonical Persisted Record

Known-target invalid Unicode is rejected before normal hashing/storage. Its log uses a reversible ASCII-escaped patchdiff-invalid-input/1 evidence envelope in the same TEXT column, with a diagnostic marker; that rejected envelope is not this transaction format and must not be applied or decoded as accepted history. Valid record serialization below is unchanged.

Stored in `append_only_pdcp_logs.pdcp_content` with `protocol_version = "patchdiff-tx/1"`. Normalized via `json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)`.

---

## 2. Legacy PDCP Format (v0.2.3, Frozen)

Submitted over MCP via `patchdiff_submit_pdcp`:
```text
PDCP 0.2.3
target_file_id: 11111111-1111-1111-1111-111111111111
target_type: text/markdown
target_hash: b8711cb73b5f382538f71019da43211d7e191622d0a865a8c1e5bf63ea1b58f2

# MANIFEST
# change_id: chg_001
# intent: Update user settings label.
# input_state: theme is set to dark.
# output_state: theme is set to system.
# affected_region: settings section
# user_visible_change: Theme default changes.
# risk: low

<<<<<<< MATCH
theme: dark
=======
theme: system
>>>>>>> REPLACE
```

### Delimiters & Delimiter Collisions
- `<<<<<<< MATCH`: Marks start of exact match payload.
- `=======`: Separates match payload from replace payload.
- `>>>>>>> REPLACE`: Marks end of replace payload.
- If payload text contains lines identical to `<<<<<<< MATCH`, `=======`, or `>>>>>>> REPLACE`, PDCP v0.2.3 parsing fails with `FailureReason.BLOCK_MALFORMED`. The typed format (`patchdiff-tx/1`) eliminates delimiter collision.

### 7 Required Manifest Fields (v0.2.3)
Each change block must include all 7 non-empty manifest fields:
1. `change_id`
2. `intent`
3. `input_state`
4. `output_state`
5. `affected_region`
6. `user_visible_change`
7. `risk` (`low`, `medium`, or `high`)

Optional disambiguation fields in v0.2.3: `anchor_before`, `anchor_after`, `occurrence_index`, `region_hint` (advisory), `target_hash`.

---

## 3. Shared Lowering and Applier Semantics

All four formats lower into `ParsedPDCP`:
```python
@dataclass(frozen=True, slots=True)
class ParsedPDCP:
    header: PDCPHeader
    changes: tuple[PDCPChangeBlock, ...]
```

The applier `apply_pdcp_transaction(target_content, parsed)`:
1. Normalizes target content and payloads to LF.
2. Checks header preconditions (if present).
3. Simulates each change sequentially against the buffer:
   - Locates all exact spans (overlapping spans counted in `patchdiff-mvp-0.2.2`).
   - Resolves disambiguation to exactly one span.
   - Slices buffer and splices `replace` immediately.
   - For a tx/2 span, checks `0 <= start <= end <= len(buffer)` and `buffer[start:end] == expected_text` instead of matching; for the tx/3 sole `replace_all`, the span is the whole buffer.
   - Computes `change_facts` (`span_start`, `span_end`, char counts, SHA-256 digests).
4. Computes final `after_hash`.
5. Emits `AcceptedCoreResult` on full success or `RejectedCoreResult` on any failure.
