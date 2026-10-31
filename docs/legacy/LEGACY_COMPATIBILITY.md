# Legacy Compatibility Reference (`PDCP 0.2.3`, Deprecated Wrappers & Historical Profiles)

## Scope

This document is the single canonical reference for PatchDIFF's frozen legacy interfaces and historical replay profiles:
1. **Frozen `.pdcp` v0.2.3 text format** (`protocol_version = "0.2.3"`)
2. **Legacy MCP submission tool** (`patchdiff_submit_pdcp`)
3. **Deprecated server-mediated regeneration wrappers** (`patchdiff_get_regeneration_context`, `patchdiff_build_regeneration_prompt`, `patchdiff_request_regeneration`) and legacy prompt-prefix helper (`patchdiff_build_prompt_context`)
4. **Historical runtime replay profiles** (`patchdiff-mvp-0.1.0`, `patchdiff-mvp-0.2.0`, `patchdiff-mvp-0.2.1`)
5. **Measured wire and storage comparison** between legacy `.pdcp` v0.2.3 and active typed JSON transactions (`patchdiff-tx/1`)

For all new integrations and host workflows, use the active typed JSON formats documented in [PDCP_FORMAT.md](../spec/PDCP_FORMAT.md), [MCP_TOOLS.md](../spec/MCP_TOOLS.md), and [HOST_INTEGRATION_GUIDE.md](../guides/HOST_INTEGRATION_GUIDE.md):
- `patchdiff_submit_edits` (`patchdiff-tx/1`) for exact `MATCH/REPLACE` transactions
- `patchdiff_submit_operations` (`patchdiff-tx/2`) for guarded sequential match/span edits and verified insertions
- `patchdiff_submit_replacement` (`patchdiff-tx/3`) for guarded whole-target replacement

Historical design specifications (`docs/legacy/PatchDIFF-Concept-Paper-5.md`, `docs/legacy/PatchDIFF-Protocol-Spec-v0.2.3.md`, `docs/legacy/PatchDIFF-Implementation-Spec-v0.2.3.md`) remain preserved untouched as historical design artifacts.

---

## 1. Frozen `.pdcp` v0.2.3 Wire Format

Legacy `.pdcp` v0.2.3 is a declarative text format lowered into the shared `ParsedPDCP` representation and executed through `apply_pdcp_transaction`. It is retained for backward compatibility and deterministic replay of historical logs.

### Wire Representation
```text
PDCP 0.2.3
target_file_id: 11111111-1111-4111-8111-111111111111
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

### Header Rules
- First line must be `PDCP 0.2.3`.
- Required header field: `target_file_id` (UUID).
- Optional header fields: `target_type`, `target_hash` (64-hex SHA-256 precondition).

### 7 Required `# MANIFEST` Fields
Every `MATCH/REPLACE` block in `.pdcp` v0.2.3 must be preceded immediately by a `# MANIFEST` block containing all 7 non-empty prose fields:
1. `change_id`
2. `intent`
3. `input_state`
4. `output_state`
5. `affected_region`
6. `user_visible_change`
7. `risk` (`low`, `medium`, or `high`)

Optional manifest fields in v0.2.3:
- `occurrence_index` (1-based integer selector)
- `anchor_before` (exact preceding substring selector)
- `anchor_after` (exact succeeding substring selector)
- `region_hint` (advisory-only metadata; never selects an ambiguous span by itself and is rejected on typed formats)
- `target_hash` (block-level hash precondition)

### Delimiters & Delimiter Collisions
- `<<<<<<< MATCH` marks the start of the exact match payload.
- `=======` separates the match payload from the replacement payload.
- `>>>>>>> REPLACE` marks the end of the replacement payload.
- **Delimiter collision limitation**: If target or replacement payload text contains a line identical to `<<<<<<< MATCH`, `=======`, or `>>>>>>> REPLACE`, `.pdcp` v0.2.3 parsing fails with `FailureReason.BLOCK_MALFORMED`. Typed JSON formats (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`) carry payloads as JSON string values and eliminate delimiter collisions completely.

### Line-Ending & Identity Rules
- Raw `.pdcp` records are persisted in `append_only_pdcp_logs.pdcp_content` with `protocol_version = "0.2.3"` and `pdcp_content_hash = canonical_sha256(pdcp_content)` (which normalizes line endings before hashing).
- Accepted `.pdcp` changes write `append_only_manifest_ledger` rows with `origin = 'pdcp_manifest'`, populating all 7 prose columns plus runtime-derived `derived_json` facts.

---

## 2. Legacy MCP Submission Tool (`patchdiff_submit_pdcp`)

`patchdiff_submit_pdcp` submits a raw `.pdcp` v0.2.3 document through the same row-locked `SELECT ... FOR UPDATE` service commit path, stage-aware `validity` model, and diagnostic structure as `patchdiff_submit_edits`.

- **Arguments**:
  - `target_file_id` (`string`, required): target UUID.
  - `pdcp_content` (`string`, required): raw `.pdcp` v0.2.3 text.
  - `expected_target_version` (`integer | null`, optional): version guard (optional on legacy path for backward compatibility; required on typed tools).
  - `expected_current_hash` (`string | null`, optional): 64-hex SHA-256 hash guard.
  - `client_request_id` (`string | null`, optional): 1..128 printable ASCII request key for idempotent outcome recovery.
  - `parent_pdcp_log_id` (`string | null`, optional): rejected parent attempt UUID.
  - `regeneration_attempt` (`integer | null`, optional), `regeneration_source` (`string | null`, optional), `source` (`string | null`, optional), `include_correlation_id` (`boolean`, optional).

### Singleton-Selector Enforcement under Current Runtime (`patchdiff-mvp-0.2.2`)
New `.pdcp` v0.2.3 submissions execute under runtime profile `patchdiff-mvp-0.2.2`, which enforces all supplied selectors even when a match occurs only once. For example, against target text `hello`, the following legacy request rejects with `disambiguation_invalid`:

```json
{
  "target_file_id": "11111111-1111-4111-8111-111111111111",
  "expected_target_version": 0,
  "pdcp_content": "PDCP 0.2.3\ntarget_file_id: 11111111-1111-4111-8111-111111111111\ntarget_type: text/plain\n\n# MANIFEST\n# change_id: greeting\n# intent: Replace greeting.\n# input_state: hello exists.\n# output_state: goodbye should exist.\n# affected_region: greeting\n# user_visible_change: Greeting changes.\n# risk: low\n# occurrence_index: 2\n\n<<<<<<< MATCH\nhello\n=======\ngoodbye\n>>>>>>> REPLACE"
}
```

### Internal Registry Example (`testest.pdcp`)
```powershell
.\.venv\Scripts\python.exe -c "import json; from pathlib import Path; from app.mcp import tools; from app.mcp.server import registry; pdcp = Path('testest.pdcp').read_text(encoding='utf-8'); target_id = next(line.split(':', 1)[1].strip() for line in pdcp.splitlines() if line.startswith('target_file_id:')); print(json.dumps(registry.call('patchdiff_submit_pdcp', target_file_id=target_id, pdcp_content=pdcp, expected_target_version=0), indent=2))"
```

---

## 3. Deprecated Regeneration & Prompt-Prefix Wrappers

Early pre-MCP-first iterations included server-built prompt templates and server-mediated retry helpers. In the modernized architecture (Decision A1), the host owns planning, context gathering, prompt construction, and retry orchestration.

| Tool | Status | Behavior & Modern Replacement |
| --- | --- | --- |
| `patchdiff_build_prompt_context` | **Legacy Convenience** | Returns a bounded 4,000-character prefix (`content[:4000]`) with `context_truncated: bool`, active manifest summary, and `.pdcp` formatting instructions. Not an authoritative retrieval engine; use `patchdiff_read_target`, `patchdiff_read_lines`, and `patchdiff_find_occurrences`. |
| `patchdiff_get_regeneration_context` | **Deprecated** | Returns rejection metadata and bounded target context for a rejected log ID. Replaced by inspecting the structured `diagnostic` (`failure_context`, `exact_candidates`, `near_misses`) returned directly by `patchdiff_submit_edits` / `patchdiff_submit_operations` and reading fresh slices. |
| `patchdiff_build_regeneration_prompt` | **Deprecated** | Builds a static text prompt asking a model to emit a corrected `.pdcp` v0.2.3 document. Replaced by the host-owned retry loop in [HOST_INTEGRATION_GUIDE.md](../guides/HOST_INTEGRATION_GUIDE.md). |
| `patchdiff_request_regeneration` | **Deprecated** | Wrapper combining regeneration context lookup and prompt formatting, or submitting a provided `candidate_pdcp` while preserving caller-owned transaction semantics. Replaced by `patchdiff_submit_edits(..., parent_pdcp_log_id=...)`. |

---

## 4. Historical Runtime Replay Profiles

`patchdiff_replay` reconstructs canonical target state from the `initial_upload` snapshot plus ordered accepted log rows, dispatching on each row's recorded `(protocol_version, runtime_version)` pair:

| Runtime Profile | Protocol Versions | Matching & Selector Semantics | Status |
| --- | --- | --- | --- |
| `patchdiff-mvp-0.1.0` | `0.2.3` | Non-overlapping match enumeration (advances search index by `len(match)`); singleton matches ignore out-of-range selectors. | **Historical replay only** |
| `patchdiff-mvp-0.2.0` | `0.2.3`, `patchdiff-tx/1` | Overlapping match enumeration (advances search index by 1 code point); permissive historical typed `change_id` grammar; singleton matches ignore out-of-range selectors. | **Historical replay only** |
| `patchdiff-mvp-0.2.1` | `0.2.3`, `patchdiff-tx/1` | Overlapping match enumeration; strict ASCII `change_id` grammar (`1..64` chars); singleton matches ignore out-of-range selectors. | **Historical replay only** |
| `patchdiff-mvp-0.2.2` | `0.2.3`, `patchdiff-tx/1` | Overlapping match enumeration; strict `change_id` grammar; **all supplied selectors enforced as conjunctive constraints even on singletons**. | **Active (`tx/1` & `0.2.3`)** |
| `patchdiff-mvp-0.3.0` | `patchdiff-tx/2` | Enables sequential `op: "match"` and `op: "span"` (`start`, `end`, `expected_text`, `replace`). | **Active (`tx/2`)** |
| `patchdiff-mvp-0.4.0` | `patchdiff-tx/3` | Enables sole guarded whole-target replacement (`op: "replace_all"`). | **Active (`tx/3`)** |
| `patchdiff-mvp-0.5.0` | `patchdiff-tx/2` | Extends `0.3.0` with exact span adjacency guards (`expected_before`, `expected_after`). | **Active (`tx/2` + context)** |

Unknown or missing `(protocol_version, runtime_version)` pairs fail closed (`replay_protocol_invalid` / `replay_transaction_invalid`). Historical accepted rows are never rewritten.

---

## 5. Measured Comparison: Legacy `.pdcp` v0.2.3 vs. Typed `patchdiff-tx/1`

Deterministic UTF-8 byte and verdict accounting from `evaluation/offline_eval.py` across 5 representative editing scenarios demonstrates why `patchdiff-tx/1` superseded `.pdcp` v0.2.3 as the primary transaction format:

| Scenario | Legacy `.pdcp` v0.2.3 (Wire / Persisted) | `patchdiff-tx/1` Matched Prose (`typed_match`, Wire / Persisted) | `patchdiff-tx/1` Minimal (`typed_min`, Wire / Persisted) | Wire Overhead Reduction (`typed_min` vs. `.pdcp`) | Verdict Equivalence |
| --- | --- | --- | --- | --- | --- |
| **1 tiny edit** | `451 B` / `331 B` | `327 B` / `382 B` | **`151 B` / `206 B`** | **-66.5% wire** (`-37.8%` stored) | `accepted` (identical hash) |
| **5 small edits** | `1,467 B` / `1,287 B` | `1,139 B` / `1,194 B` | **`259 B` / `314 B`** | **-82.3% wire** (`-75.6%` stored) | `accepted` (identical hash) |
| **1 edit, 2 KB span** | `4,741 B` / `4,543 B` | `4,617 B` / `4,672 B` | **`4,441 B` / `4,496 B`** | **-6.3% wire** (payload-dominated) | `accepted` (identical hash) |
| **Quotes + backslashes + Unicode** | `472 B` / `345 B` | `348 B` / `403 B` | **`172 B` / `227 B`** | **-63.6% wire** (`-34.2%` stored) | `accepted` (identical hash) |
| **Payload has a delimiter line (`=======`)** | `462 B` / `339 B` (**`rejected: block_malformed`**) | `338 B` / `393 B` (**`accepted`**) | **`162 B` / `217 B`** (**`accepted`**) | **100% collision elimination** | Named legacy expressibility exception |
