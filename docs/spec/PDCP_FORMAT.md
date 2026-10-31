# PDCP_FORMAT.md

## Scope

This document defines the active declarative JSON transaction formats supported by PatchDIFF:
1. **`patchdiff-tx/1` (Primary Typed Match Transaction)**: A structured JSON format passed directly through MCP tool arguments (`patchdiff_submit_edits`), stored as canonical JSON in `append_only_pdcp_logs.pdcp_content` under runtime profile `patchdiff-mvp-0.2.2`. Delimiter-collision free, with minimal mandatory prose overhead (`151 B` wire / `206 B` persisted for a 1-edit transaction; `259 B` wire / `314 B` persisted for 5 edits).
2. **`patchdiff-tx/2` (Guarded Match & Span Operations)**: Canonical JSON passed through `patchdiff_submit_operations` with required `intent`, required state guard, and ordered `operations[]` carrying explicit `op: "match"` or `op: "span"`. Span records require `start`, `end`, `expected_text`, and `replace`, use sequential canonical Unicode code-point coordinates, and allow explicit empty-span insertion (`start == end`, `expected_text: ""`). Optional `expected_before` / `expected_after` verify exact adjacent text; records using them execute under immutable runtime profile `patchdiff-mvp-0.5.0` (otherwise `patchdiff-mvp-0.3.0`).
3. **`patchdiff-tx/3` (Guarded Sole Whole-Target Replacement)**: Canonical JSON passed through `patchdiff_submit_replacement` with required `intent`, required state guard, and a single `{"op": "replace_all", "replace": "..."}` operation under immutable runtime profile `patchdiff-mvp-0.4.0` (`232 B` MCP `arguments` JSON / `290 B` persisted record / `341 B` compact `tools/call` line for a 3-byte whole-target replacement).

> **Legacy Compatibility**: Frozen `.pdcp` v0.2.3 text transactions (`patchdiff_submit_pdcp`), deprecated regeneration wrappers, and historical runtime profiles (`0.1.0`–`0.2.1`) remain supported for backward compatibility and deterministic replay. See [LEGACY_COMPATIBILITY.md](../legacy/LEGACY_COMPATIBILITY.md) for their specification.

None of these formats is executable code. All lower into the same internal `ParsedPDCP` representation and execute through the same deterministic applier (`apply_pdcp_transaction`).

Architecture decisions: [MODERNIZATION_ARCHITECTURE.md](../papers/MODERNIZATION_ARCHITECTURE.md).
As-built record: [MODERNIZATION_CHANGE_DOC.md](../papers/MODERNIZATION_CHANGE_DOC.md).

---

## 1. Typed Match Transaction (`patchdiff-tx/1`, Primary)

### Wire Representation (MCP Tool Arguments)
Submitted over MCP via `patchdiff_submit_edits`:
```json
{
  "target_file_id": "11111111-1111-4111-8111-111111111111",
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
- `expected_current_hash` (`string | null`): Exactly 64 lowercase hex SHA-256 target hash precondition guard.
- *Guard requirement*: At least one of `expected_target_version` or `expected_current_hash` must be non-null.
- `client_request_id` (`string | null`, optional): 1..128 printable ASCII characters without whitespace for request deduplication.
- `parent_pdcp_log_id` (`string | null`, optional): UUID of rejected parent attempt when retrying.
- `attempt` (`integer 1..2^31-1 | null`, optional): Retry attempt counter.

### Edit Item Schema (`TYPED_EDIT_JSON_SCHEMA`)
- `match` (`string`, required non-empty): Exact target text to match.
- `replace` (`string`, required): Replacement text. Empty string `""` denotes deletion.
- `change_id` (`string | null`, optional): A complete 1–64-character identifier containing only ASCII letters, digits, underscore, period, colon, or hyphen; trailing newlines reject. Defaults to `chg_001`, `chg_002`, ... by 1-based index if omitted or `null`. Duplicate IDs reject with `FailureReason.MANIFEST_INVALID`.
- `rationale` (`string | null`, optional): Nonblank per-edit explanation when supplied.
- `risk` (`"low" | "medium" | "high" | null`, optional): Advisory risk classification.
- `occurrence_index` (`integer >= 1 | null`, optional): 1-based index over exact matches in the sequential buffer.
- `anchor_before` (`string | null`, optional): Exact substring that must precede candidate span.
- `anchor_after` (`string | null`, optional): Exact substring that must succeed candidate span.
- Selectors are conjunctive constraints even when there is only one match (`patchdiff-mvp-0.2.2`). An index beyond the occurrence count or an excluding anchor rejects (`disambiguation_invalid`); combined selectors must all hold. Anchors need not be adjacent.
- `additionalProperties: false`: Unknown fields reject with `FailureReason.MANIFEST_INVALID`.

### Canonical Persisted Record
Stored in `append_only_pdcp_logs.pdcp_content` with `protocol_version = "patchdiff-tx/1"` and `runtime_version = "patchdiff-mvp-0.2.2"`, normalized via `json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)`.

Known-target invalid Unicode (unpaired surrogates or NUL) is rejected before normal hashing/storage with `target_encoding_invalid` at `PROTOCOL_VALIDATION`. Its log uses a reversible ASCII-escaped `patchdiff-invalid-input/1` evidence envelope in the same `TEXT` column with a safe JSONB diagnostic marker; that rejected envelope is never applied or decoded as accepted history.

---

## 2. Guarded Match & Span Operations (`patchdiff-tx/2`)

### Wire Representation (MCP Tool Arguments)
Submitted over MCP via `patchdiff_submit_operations` when the caller holds exact Unicode code-point offsets from `patchdiff_read_target`, `patchdiff_read_lines`, or `patchdiff_find_occurrences`:
```json
{
  "target_file_id": "11111111-1111-4111-8111-111111111111",
  "expected_target_version": 2,
  "expected_current_hash": null,
  "intent": "Insert header note and rename setting.",
  "operations": [
    {
      "op": "span",
      "start": 0,
      "end": 0,
      "expected_text": "",
      "expected_after": "# Settings\n",
      "replace": "Note: Managed by PatchDIFF\n"
    },
    {
      "op": "match",
      "match": "alpha",
      "replace": "beta"
    }
  ],
  "client_request_id": "req-ops-v2"
}
```

### Operation Rules & Runtime Profiles
- Requires top-level `intent` and at least one state guard (`expected_target_version` and/or `expected_current_hash`).
- `op: "match"` carries the same fields and selector rules as `patchdiff-tx/1` edit items.
- `op: "span"` requires non-boolean integer `start` and `end` (`0 <= start <= end <= len(buffer)` in sequential canonical LF code points), exact `expected_text` (`buffer[start:end] == canonicalize_text(expected_text)`), and `replace`.
  - Empty-span insertion uses `start == end` with `expected_text: ""`.
  - Optional `expected_before` and `expected_after` verify exact adjacent text (`buffer[start-len(expected_before):start]` and `buffer[end:end+len(expected_after)]`) so off-by-N insertion offsets reject deterministically (`span_expected_text_mismatch`).
- **Runtime profile selection**:
  - `patchdiff-mvp-0.3.0` when no span carries `expected_before` or `expected_after`.
  - `patchdiff-mvp-0.5.0` when any span carries `expected_before` or `expected_after`.
- See [MCP_TOOLS.md](MCP_TOOLS.md#patchdiff_submit_operations-patchdiff-tx2) for complete field schemas.

---

## 3. Guarded Sole Whole-Target Replacement (`patchdiff-tx/3`)

### Wire Representation & Canonical Record
Submitted over MCP via `patchdiff_submit_replacement` for explicit whole-document replacement under mandatory state guards. Stored as canonical JSON under immutable runtime profile `patchdiff-mvp-0.4.0`:
```json
{
  "expected_current_hash": null,
  "expected_target_version": 0,
  "format": "patchdiff-tx/3",
  "intent": "Explicit whole-target replacement",
  "operations": [
    {
      "op": "replace_all",
      "replace": "new text\n"
    }
  ],
  "target_file_id": "11111111-1111-4111-8111-111111111111"
}
```

### Rules & Service Admission Boundary
- Exactly one operation with `{"op": "replace_all", "replace": "..."}` is permitted. No `match`, `span`, selectors, or mixed operations are allowed in `patchdiff-tx/3` (and `patchdiff-tx/2` continues to refuse `replace_all`).
- At least one valid state guard (`expected_target_version` and/or `expected_current_hash`) is required; both top-level guard keys are persisted with raw values (including `null`) through the same canonical JSON identity rule.
- Default `change_id` is `chg_001`; default `risk` is `"low"`; one typed ledger row (`operation: "replace_all"`) covers the full original span `[0, len(buffer))`.
- **Fresh service admission limit**: Fresh `patchdiff-tx/3` replacement submissions are bounded to `<= 1,000,000` Unicode code points and `<= 1,048,576` UTF-8 bytes (both raw input and canonical LF result). Replay bypasses fresh admission limits so historical accepted logs always replay.

---

## 4. Typed Format Decision Matrix & Measured Payload Overhead

### Choosing the Right Typed Format

| Format | MCP Tool | Runtime Profile | Primary Use Case | Guard Requirement | Typical Wire Overhead (Excluding Payload) |
| --- | --- | --- | --- | --- | --- |
| **`patchdiff-tx/1`** | `patchdiff_submit_edits` | `patchdiff-mvp-0.2.2` | Default exact `MATCH/REPLACE` edits with optional selectors (`occurrence_index`, `anchor_before`, `anchor_after`) | Required (`version` and/or `hash`) | **`~140 B`** (`151 B` total for 1 tiny edit; `259 B` for 5 small edits) |
| **`patchdiff-tx/2`** | `patchdiff_submit_operations` | `patchdiff-mvp-0.3.0` (`0.5.0` with span context) | Coordinate-known `span` replacements, descending multi-span edits from a single read, and verified insertions (`expected_before`/`expected_after`) | Required (`version` and/or `hash`) | **`~165 B`** |
| **`patchdiff-tx/3`** | `patchdiff_submit_replacement` | `patchdiff-mvp-0.4.0` | Explicit guarded whole-document replacement (`replace_all`, up to 1,048,576 UTF-8 bytes / 1,000,000 code points, raw and canonical) | Required (`version` and/or `hash`) | **`229 B` MCP `arguments` JSON framing** (`232 B` `arguments` / `290 B` persisted record / `341 B` complete `tools/call` line for a 3-byte replacement) |

### Deterministic Byte Accounting (`backend/tests/verification/offline_eval.py`)

Measured UTF-8 byte sizes across standard typed editing scenarios (`PYTHONPATH=backend python backend/tests/verification/offline_eval.py`):

| Scenario | `patchdiff-tx/1` Minimal (`typed_min`, Wire / Persisted) | `patchdiff-tx/1` Matched Prose (`typed_match`, Wire / Persisted) | Verdict & Delimiter Safety |
| --- | --- | --- | --- | --- | --- |
| **1 tiny edit** | **`151 B`** / **`206 B`** | `327 B` / `382 B` | `accepted` |
| **5 small edits** | **`259 B`** / **`314 B`** | `1,139 B` / `1,194 B` | `accepted` |
| **1 edit, 2 KB span** | **`4,441 B`** / **`4,496 B`** | `4,617 B` / `4,672 B` | `accepted` |
| **Quotes + backslashes + Unicode** | **`172 B`** / **`227 B`** | `348 B` / `403 B` | `accepted` |
| **Payload has a delimiter line (`=======`)** | **`162 B`** / **`217 B`** | `338 B` / `393 B` | `accepted` (eliminates `.pdcp` delimiter-line collisions; JSON syntax remains protocol-validated) |

Measured `patchdiff-tx/3` (`patchdiff_submit_replacement`) UTF-8 byte sizes:

| `patchdiff-tx/3` Case | Raw / Canonical Replacement (`UTF-8 B`) | MCP Tool `arguments` JSON (`UTF-8 B`) | Persisted Record Bytes (`pdcp_content`) | Complete JSON-RPC `tools/call` Line Bytes | Verdict |
| --- | --- | --- | --- | --- | --- |
| **Guarded whole-target rewrite (`"old" -> "new"`)** | `3 B` / `3 B` | `232 B` | `290 B` | `341 B` | `accepted` |
| **Empty target replacement (`"" -> "new"`)** | `3 B` / `3 B` | `232 B` | `290 B` | `341 B` | `accepted` |
| **Empty replacement (clear target, `"old" -> ""`)** | `0 B` / `0 B` | `229 B` | `287 B` | `338 B` | `accepted` |
| **Unicode, quotes, CRLF normalization (`'say "hi" \\\r\n🌟'`)** | `16 B` raw / `15 B` LF | `250 B` | `308 B` | `359 B` | `accepted` |
| **Whole-target 2 KB rewrite (40 lines, 39 `\n` chars)** | `2,109 B` / `2,109 B` | `2,377 B` | `2,435 B` | `2,486 B` | `accepted` |

*(For the baseline comparison against frozen `.pdcp` v0.2.3, see [LEGACY_COMPATIBILITY.md](../legacy/LEGACY_COMPATIBILITY.md#5-measured-comparison-legacy-pdcp-v023-vs-typed-patchdiff-tx1).)*

---

## 5. Shared Lowering and Applier Semantics

The structural batch tool mode wraps ordered tx/2 operation groups in the internal
durable format `patchdiff-observed-batch/1`, runtime `patchdiff-observed-batch-r1`.
It is not another public tool or operation type. Each group lowers through the
same tx/2 parser and `ParsedPDCP` and executes the existing applier against its
own original slice. The canonical envelope additionally records target/bundle,
both guards, intent, editing cycle and immutable authoritative scope evidence.
Original operation order, group/operation indices, scope hashes/bounds and IDs
support deterministic replay without discovery. [Complete batch specification](STRUCTURAL_BATCH_EDITING.md).

All supported transaction formats lower into `ParsedPDCP`:
```python
@dataclass(frozen=True, slots=True)
class ParsedPDCP:
    header: PDCPHeader
    changes: tuple[PDCPChangeBlock, ...]
```

The applier `apply_pdcp_transaction(target_content, parsed)`:
1. Normalizes target content and payloads to LF.
2. Checks header preconditions (if present).
3. Simulates each change sequentially against the in-memory buffer:
   - For `match` operations: locates all exact spans (overlapping spans counted in `patchdiff-mvp-0.2.2`), resolves disambiguation to exactly one span, slices the buffer, and splices `replace` immediately.
   - For `tx/2` `span` operations: verifies `0 <= start <= end <= len(buffer)`, `buffer[start:end] == expected_text`, and optional `expected_before` / `expected_after` adjacency guards before splicing `replace`.
   - For the `tx/3` sole `replace_all` operation: replaces `[0, len(buffer))` in one step.
   - Computes authoritative `change_facts` (`span_start`, `span_end`, char counts, SHA-256 digests).
4. Computes final `after_hash`.
5. Emits `AcceptedCoreResult` on full success or `RejectedCoreResult` on any failure without mutating the target.
