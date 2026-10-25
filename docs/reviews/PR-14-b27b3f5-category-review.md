# PR #14 Category Review — Resolve PR #13 Deferred Near-Miss (SVC-001) and Ledger-Read (MCP-001) P3 Findings

## 1. Review metadata and evidence limits

| Field | Value |
| --- | --- |
| Repository | `paragon-ux/Patch-DIFF` |
| PR | [paragon-ux/Patch-DIFF#14](https://github.com/paragon-ux/Patch-DIFF/pull/14) |
| Review date | 2026-10-24 |
| Reviewer | Antigravity (self-review of the implementation session) |
| Standard | [PR Review Standard v1.1.0](../PR_REVIEW_STANDARD.md) |
| Predecessor reviews | [PR-13-0420dac-category-review.md](PR-13-0420dac-category-review.md) (`MCP-001`), [PR-13-ac842bb-delta-review.md](PR-13-ac842bb-delta-review.md) (`SVC-001`), [PR-13-de6e7c2-friction-review.md](PR-13-de6e7c2-friction-review.md) (`NF-5`, `NF-8`), [PR-13-aa88cd5-friction-recheck.md](PR-13-aa88cd5-friction-recheck.md) |
| Base SHA | `d09fbc8422bbc22543b0b209c2f689b3e341e3b2` (`origin/main`, PR #13 merge commit) |
| Head SHA | `b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0` (`perf/pr13-deferred-p3`) |
| Delta | 9 files changed, +470 / −89 |
| CI runs | Pending push and PR creation; local verification recorded below |

### Changed-file inventory (`d09fbc8..b27b3f5`)

1. `backend/app/mcp/tools.py` (+206 / −35) — Primary category: `MCP`
2. `backend/app/services/near_miss_service.py` (+238 / −49) — Primary category: `SVC`
3. `backend/tests/integration/test_friction_followup_live.py` (+86 / −0) — Primary category: `TEST`
4. `backend/tests/unit/test_friction_followup.py` (+17 / −0) — Primary category: `TEST`
5. `docs/MCP_TOOLS.md` (+2 / −2) — Primary category: `MCP`
6. `docs/MODERNIZATION_ARCHITECTURE.md` (+2 / −1) — Primary category: `ARCH`
7. `docs/MODERNIZATION_CHANGE_DOC.md` (+1 / −1) — Primary category: `DOC`
8. `docs/TEST_MATRIX.md` (+2 / −2) — Primary category: `DOC`
9. `docs/usability/friction-followup-decision.md` (+6 / −0) — Primary category: `ARCH`

### Unchanged dependencies examined

- `docs/PatchDIFF-Concept-Paper-5.md` (design thesis: exact deterministic matching, non-fuzzy core runtime, PostgreSQL canonical authority, append-only audit trail)
- `AGENTS.md`, `docs/PATCHDIFF_CORE_SPEC.md`, `docs/DATA_MODEL.md`, `docs/PDCP_FORMAT.md`
- `backend/app/services/pdcp_service.py` (caller of `near_misses_from_rejected_result` and `near_misses`)
- `backend/app/storage/models.py` (`AppendOnlyPdcpLogs`, `AppendOnlyManifestLedger`)
- `backend/tests/unit/test_pass_a_diagnostics.py`, `backend/tests/unit/test_mcp_arguments_paging.py`, `backend/tests/integration/test_mcp_history_paging_live.py`, `backend/tests/integration/test_friction_followup_stdio.py`

### Evidence available and limits

- **Source inspection:** Full diff `d09fbc8..b27b3f5` and all referenced unchanged callers, models, and contracts.
- **Local execution:**
  - Full unit and live-PostgreSQL integration suite (`pytest backend/tests -q`, 1,223 passed: 813 unit + 410 integration) against isolated database `patchdiff_perf_p3_20261024` on `postgres:16.3-alpine` (`127.0.0.1:5432`), dropped upon completion.
  - Offline byte and verdict equivalence evaluation (`evaluation/offline_eval.py`, exit 0).
  - Controlled before/after latency benchmarks on 65,536-code-point repetitive and varied-prose buffers (`SVC-001`) and 20 × 1,000,000-code-point `patchdiff-tx/3` history pages (`MCP-001`).
  - Exhaustive 2,000-trial randomized equivalence check comparing the new `_candidate_starts` + `_window_distances` implementation against an unpruned, unbanded Levenshtein reference across varied and repetitive alphabets and lengths `1..64`.
- **Limits:** Self-review by the authoring agent; no live third-party MCP host/model trial was run; measurements are local single-machine timings on Windows 11 / Python 3.11.9 / PostgreSQL 16.3.

---

## 2. File-to-category inventory and coverage matrix

| ID | Category | Primary changed files | Cross-referenced files / unchanged dependencies | Coverage | Verdict |
| --- | --- | --- | --- | --- | --- |
| ARCH | Architecture and contracts | `docs/MODERNIZATION_ARCHITECTURE.md`, `docs/usability/friction-followup-decision.md` | `AGENTS.md`, `docs/PatchDIFF-Concept-Paper-5.md` | Complete | Pass (no findings) |
| DOC | Documentation and change records | `docs/MODERNIZATION_CHANGE_DOC.md`, `docs/TEST_MATRIX.md` | `docs/MCP_TOOLS.md`, `docs/usability/friction-followup-decision.md` | Complete | Pass (no findings) |
| SKILL | Skills and agent instructions | None | `.agents/skills/patchdiff-core-runtime/SKILL.md`, `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`, `.agents/skills/patchdiff-persistence-replay-save/SKILL.md`, `.agents/skills/patchdiff-testing-review/SKILL.md` | Complete (unchanged verification) | Pass (no findings) |
| MCP | MCP schemas and public API | `backend/app/mcp/tools.py`, `docs/MCP_TOOLS.md` | `backend/app/mcp/external_adapter.py` | Complete | Pass (`MCP-001` closed) |
| RUN | Core runtime, parsing, and validation | None | `backend/app/core/`, `backend/app/pdcp/` | Not modified; boundary verified | Pass (no findings) |
| SVC | Services, orchestration, and audit semantics | `backend/app/services/near_miss_service.py` | `backend/app/services/pdcp_service.py` | Complete | Pass (`SVC-001` closed) |
| DB | Database, migrations, replay, and concurrency | None | `backend/app/mcp/tools.py` (read-only SQL projections), `backend/app/storage/models.py` | Complete for read-query semantics | Pass (no findings) |
| SCRIPT | Scripts, evaluation, and developer tooling | None | `evaluation/offline_eval.py` | Complete (executed) | Pass (no findings) |
| TEST | Tests and CI | `backend/tests/unit/test_friction_followup.py`, `backend/tests/integration/test_friction_followup_live.py` | `backend/tests/unit/test_pass_a_diagnostics.py`, `backend/tests/unit/test_mcp_arguments_paging.py`, `backend/tests/integration/test_mcp_history_paging_live.py`, `backend/tests/integration/test_friction_followup_stdio.py` | Complete locally | Pass (no findings) |
| DEP | Dependencies, packaging, and configuration | None | `backend/requirements.txt`, `docker-compose.yml` | Not applicable (no changes) | Not applicable |

---

## 3. Architecture-to-implementation trace

### 3.1 Trace matrix

| Finding / Decision | Design thesis & invariant | Architecture decision & contract | Implementation (`b27b3f5`) | Verification |
| --- | --- | --- | --- | --- |
| `SVC-001` / `NF-5` (D6 follow-up: near-miss scan cost on repetitive text) | Core matching remains 100% exact (`backend/app/pdcp/matcher.py`); near-miss suggestions are strictly advisory, response-only, post-commit, and never auto-applied (`docs/PatchDIFF-Concept-Paper-5.md`, `AGENTS.md`). | `docs/usability/friction-followup-decision.md` (D6 & follow-up), `docs/MCP_TOOLS.md`: scan up to `MAX_SCAN_BUFFER_CHARS = 65_536` code points under `MAX_COMPARISON_CELLS = 1_000_000` with exact Levenshtein ranking `(distance, start, end)`, non-overlapping location selection, and exact `scanned_*` / `scope_truncated` reporting. | `backend/app/services/near_miss_service.py`: (1) `_candidate_starts` partitions `needle` into `threshold + 1` disjoint pieces (plus contiguous unedited run merging and exhaustive 1-edit checks on 3-code-point pieces when `len(needle) >= 3 * (threshold + 1)`), guaranteeing by the pigeonhole principle that every window within edit distance `<= threshold` is enumerated; (2) `_window_distances` computes exact distances for window widths `len(needle) + {-1, 0, +1}` via an Ukkonen-banded Landau–Vishkin diagonal-wave DP (`band_radius = (threshold + 1) // 2`), charging `reached_row * (2 * band_radius + 1)` cells. | Existing reference-equality tests in `test_pass_a_diagnostics.py` and `test_friction_followup.py` pass; new `test_repetitive_64k_buffer_scans_to_end_within_work_bound` proves a 65,536-code-point repetitive log scans to completion (`scanned_end == 65493`, `scope_truncated is False`) within `142,255 <= 200,000` cells with exact ranking `[(1, 47646, 47692), (3, 27193, 27238), (3, 27808, 27854)]`. |
| `MCP-001` / `NF-8` (FR-11 follow-up: ledger and attempt history read cost) | `append_only_pdcp_logs` stores full canonical transaction records (`pdcp_content`) and `append_only_manifest_ledger` stores accepted change facts (`AGENTS.md`, `docs/DATA_MODEL.md`). Persisted records, hashes, and fingerprints are immutable. | `docs/usability/friction-followup-decision.md` (D11 & follow-up), `docs/MCP_TOOLS.md`: `patchdiff_get_manifest_ledger` returns `transaction_intent` and per-edit `rationale`; `patchdiff_get_pdcp_log` returns bounded `intent` (`<= 256` code points) and `intent_truncated`, omitting `pdcp_content` unless `include_content=true`. | `backend/app/mcp/tools.py`: (1) `patchdiff_get_manifest_ledger` skips JSON extraction entirely when all typed rows on the page are `patchdiff-tx/3` (`derived_json.operation == "replace_all"`, where `transaction_intent == row.intent` and `rationale is None`) or legacy `0.2.3`; when `tx/1` or `tx/2` rows are present, `_sql_transaction_intent()` and `_sql_rationales()` extract only those fields in SQL under `protocol_version` and `pg_input_is_valid(..., 'jsonb')` guards that skip `0.2.3` and `patchdiff-invalid-input/1` evidence envelopes; (2) `patchdiff_get_pdcp_log` defers `AppendOnlyPdcpLogs.pdcp_content` and queries `_sql_bounded_intent()` and `_sql_intent_truncated()` in SQL (using a 4 KB prefix slice before `,"operations":[` on `> 64 KB` canonical records). | `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` in `test_friction_followup_live.py` hooks SQLAlchemy `after_cursor_execute` to prove `pdcp_content` never appears in `cursor.description` or executed ledger SQL across mixed `tx/1`, `tx/2`, `tx/3`, `0.2.3`, and `patchdiff-invalid-input/1` rows while returning identical fields. |

### 3.2 Measured before/after benchmarks

#### SVC-001: 65,536-code-point near-miss scan (`MAX_COMPARISON_CELLS = 1_000_000`)

| Workload (65,536-code-point buffer) | Base `d09fbc8` in-process | Base `d09fbc8` stdio | Head `b27b3f5` in-process | Head `b27b3f5` tool call | Base `comparison_cells` (`scanned_end`, `scope_truncated`) | Head `comparison_cells` (`scanned_end`, `scope_truncated`) | Candidate ranking `(distance, start, end)` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Repetitive `ops-log.md`, typo at `47,646` (45 cp needle) | 708.5 ms | 931.0 ms | **41.9 ms** (16.9× faster) | **85.0 ms** (11.0× faster) | `999,892` (`45,404`, `True` — missed typo at `47,646`) | **`142,255`** (`65,493`, `False` — full buffer scanned) | `[(1, 47646, 47692), (3, 27193, 27238), (3, 27808, 27854)]` (matches unpruned 64K reference) |
| Repetitive `ops-log.md`, typo at `2,672` (45 cp needle) | 705.0 ms | 956.0 ms | **38.5 ms** (18.3× faster) | **81.2 ms** (11.8× faster) | `999,804` (`45,608`, `True`) | **`123,435`** (`65,493`, `False` — full buffer scanned) | `[(1, 2672, 2718), (3, 623, 669), (3, 1306, 1352)]` (matches unpruned 64K reference) |
| Varied prose, typo at `50,027` (38 cp needle) | 100.2 ms | 117.0 ms | **1.7 ms** (58.9× faster) | **24.1 ms** (4.9× faster) | `2,727` (`65,500`, `False`) | **`950`** (`65,500`, `False`) | `[(1, 50027, 50065)]` (identical) |
| Varied prose, typo at `50,027` (53 cp needle) | 98.4 ms | 98.0 ms | **2.2 ms** (44.7× faster) | **23.3 ms** (4.2× faster) | `4,131` (`65,485`, `False`) | **`1,325`** (`65,485`, `False`) | `[(2, 50027, 50080)]` (identical) |
| Varied prose, absent needle (`45` cp) | 110.1 ms | 116.0 ms | **1.6 ms** (68.8× faster) | **22.3 ms** (5.2× faster) | `0` (`65,492`, `False`) | **`0`** (`65,492`, `False`) | `[]` (identical) |

#### MCP-001: History page (`limit=50`) over 20 × 1,000,000-code-point (`~20 MB`) `patchdiff-tx/3` records

| Operation | Base `d09fbc8` total (in-process) | Head `b27b3f5` SQL execution | Head `b27b3f5` total (including new session setup) | `pdcp_content` selected in `cursor.description`? |
| --- | --- | --- | --- | --- |
| `patchdiff_get_manifest_ledger(limit=50)` | 230–263 ms | **1.4 ms** | **21.1–23.6 ms** (~10× faster) | Base: Yes (20 × 1 MB transferred & `json.loads`-parsed) → Head: **No** (`pdcp_content` never referenced) |
| `patchdiff_get_pdcp_log(limit=50, include_content=False)` | 234–260 ms | **9.5 ms** | **68.1–76.3 ms** (~3.4× faster) | Base: Yes (full ORM column loaded & `json.loads`-parsed) → Head: **No** (`defer(AppendOnlyPdcpLogs.pdcp_content)` + 4 KB prefix slice in SQL) |

---

## 4. Category sections

### ARCH — Architecture and contracts

- **Scope:** `docs/MODERNIZATION_ARCHITECTURE.md`, `docs/usability/friction-followup-decision.md`, and preservation of locked invariants in `AGENTS.md` and `docs/PatchDIFF-Concept-Paper-5.md`.
- **Coverage:** Complete.
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification & reasoning:**
  - `MAX_COMPARISON_CELLS = 1_000_000` and `MAX_SCAN_BUFFER_CHARS = 65_536` are kept unchanged; no contract or resource cap was weakened.
  - Core matching in `backend/app/pdcp/` remains pure and exact; near-miss ranking stays in `backend/app/services/near_miss_service.py` as a post-commit advisory enrichment.
  - No persisted record format, hash, request fingerprint, runtime profile, or failure reason changed.
- **Verification gaps:** None.
- **Verdict:** Pass (no findings).

### DOC — Documentation and change records

- **Scope:** `docs/MODERNIZATION_CHANGE_DOC.md`, `docs/TEST_MATRIX.md`, plus cross-checked descriptions in `docs/MCP_TOOLS.md` and `docs/usability/friction-followup-decision.md`.
- **Coverage:** Complete.
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification & reasoning:**
  - `docs/MCP_TOOLS.md` accurately describes the exact Ukkonen-banded Landau–Vishkin diagonal-wave DP (`band_radius = (threshold + 1) // 2`), the exact positional pigeonhole filter over disjoint needle pieces, cell counting (`reached_row * (2 * band_radius + 1)`), and latency characteristics (both varied prose and structured repetitive logs scan the full 65,536-code-point buffer in tens of milliseconds; only homogeneous inputs where every needle piece repeats across the buffer hit the cell cap early).
  - `docs/MCP_TOOLS.md` also documents that `patchdiff_get_manifest_ledger` extracts `transaction_intent` and `rationale` in SQL without transferring or decoding full `pdcp_content` payloads (and uses `intent` directly for `patchdiff-tx/3` rows).
  - `docs/MODERNIZATION_ARCHITECTURE.md`, `docs/MODERNIZATION_CHANGE_DOC.md`, `docs/TEST_MATRIX.md`, and `docs/usability/friction-followup-decision.md` agree with the implementation.
- **Verification gaps:** None.
- **Verdict:** Pass (no findings).

### SKILL — Skills and agent instructions

- **Scope:** `.agents/skills/patchdiff-core-runtime/SKILL.md`, `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`, `.agents/skills/patchdiff-persistence-replay-save/SKILL.md`, `.agents/skills/patchdiff-testing-review/SKILL.md`.
- **Coverage:** Complete (inspected for compatibility with `SVC-001` and `MCP-001` changes).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification & reasoning:** None of the four workspace skill files hardcode the old bag-distance filter or Python-side `_decoded_record` loop on ledger pages; their invariants (`RejectedCoreResult.near_miss_buffer` capped at 65,536 code points, `patchdiff_get_manifest_ledger` join fields, `patchdiff_get_pdcp_log` byte budget) remain 100% accurate.
- **Verification gaps:** None.
- **Verdict:** Pass (no findings).

### MCP — MCP schemas and public API

- **Scope:** [tools.py:340-613](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/app/mcp/tools.py#L340-L613), [tools.py:729-802](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/app/mcp/tools.py#L729-L802), and [MCP_TOOLS.md:137-142](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/docs/MCP_TOOLS.md#L137-L142).
- **Coverage:** Complete.
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:**
  - **MCP-001 (Closed) — Ledger and attempt-log pages loaded and JSON-decoded full `pdcp_content` records.**
    - **Provenance:** Opened as advisory P3 in [PR-13-0420dac-category-review.md](PR-13-0420dac-category-review.md) (`MCP-001`) and [PR-13-de6e7c2-friction-review.md](PR-13-de6e7c2-friction-review.md) (`NF-8`).
    - **Source evidence:** [tools.py:340-466](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/app/mcp/tools.py#L340-L466) (`patchdiff_get_pdcp_log`), [tools.py:469-613](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/app/mcp/tools.py#L469-L613) (`patchdiff_get_manifest_ledger`), and [tools.py:729-802](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/app/mcp/tools.py#L729-L802) (`_SAFE_DOC_SQL`, `_SAFE_TX12_DOC_SQL`, `_sql_bounded_intent`, `_sql_intent_truncated`, `_sql_transaction_intent`, `_sql_rationales`).
    - **Trigger:** Calling `patchdiff_get_manifest_ledger` or `patchdiff_get_pdcp_log(include_content=False)` over a target with large stored `pdcp_content` payloads (such as 1,000,000-code-point `patchdiff-tx/3` whole-document replacements).
    - **Expected / actual (before fix):** Only bounded summary fields (`transaction_intent`, `rationale`, or 256-char `intent` + `intent_truncated`) are returned, but the server selected `AppendOnlyPdcpLogs.pdcp_content` and ran `json.loads` on every full record on the page (~230–263 ms for 20 × 1 MB rows).
    - **Remediation implemented (`b27b3f5`):**
      1. In `patchdiff_get_manifest_ledger`, `needs_json` checks whether any row on the page has `row.origin == "typed" and (row.derived_json or {}).get("operation") != "replace_all"`. When `needs_json` is `False` (e.g., pages of `patchdiff-tx/3` `replace_all` rows or legacy `0.2.3` rows), `AppendOnlyPdcpLogs` is queried only for `(pdcp_log_id, log_sequence, before_version, after_version, protocol_version)` without touching `pdcp_content` at all; `transaction_intent` is read from `row.intent` for typed rows (`tx/3` ledger rows store the transaction intent in `intent`) and `rationale` is `None`.
      2. When `needs_json` is `True` (`tx/1` or `tx/2` rows on the page), `_sql_transaction_intent()` and `_sql_rationales()` extract `intent` and the array of per-edit `rationale` values directly in PostgreSQL using `_SAFE_DOC_SQL` and `_SAFE_TX12_DOC_SQL`, which guard casts with `protocol_version IN (...)`, `pg_input_is_valid(..., 'jsonb')`, `jsonb_typeof(...) = 'object'`, and `NOT (doc ? 'evidence_format')` so legacy `0.2.3` text and `patchdiff-invalid-input/1` envelopes never fail or leak.
      3. In `patchdiff_get_pdcp_log`, `defer(AppendOnlyPdcpLogs.pdcp_content)` omits `pdcp_content` from the ORM query, and a secondary metadata query fetches `_sql_bounded_intent()` and `_sql_intent_truncated()` (plus `func.octet_length(AppendOnlyPdcpLogs.pdcp_content)` only when `include_content=True` to select in-budget IDs before fetching their `pdcp_content`). For canonical records `> 64 KB` containing `,"operations":[`, `_SAFE_DOC_SQL` slices only the first 4,096 chars before `,"operations":[` and closes the JSON object (`|| '}'`) so PostgreSQL extracts top-level `intent` without parsing a multi-megabyte `operations` array.
    - **Acceptance & closure evidence:** `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` in [test_friction_followup_live.py:636-720](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/tests/integration/test_friction_followup_live.py#L636-L720) verifies via SQLAlchemy's `after_cursor_execute` event that `pdcp_content` is absent from every executed SQL statement on the `tx/3` ledger page and absent from `cursor.description` across both `patchdiff_get_manifest_ledger` and `patchdiff_get_pdcp_log(include_content=False)` over a mixed history of `tx/1`, `tx/2`, `tx/3`, `0.2.3`, and `patchdiff-invalid-input/1` rows, while returning identical response payloads. All 133 tests in `test_mcp_arguments_paging.py`, `test_friction_followup_live.py`, and `test_mcp_history_paging_live.py` pass.
- **Verification gaps:** None.
- **Verdict:** Pass (`MCP-001` closed; no open findings).

### RUN — Core runtime, parsing, and validation

- **Scope:** `backend/app/core/`, `backend/app/pdcp/`.
- **Coverage:** Complete (verified unchanged and isolated from service/MCP changes).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification & reasoning:** `git diff d09fbc8..b27b3f5 -- backend/app/core backend/app/pdcp` is empty. All core runtime unit tests and `evaluation/offline_eval.py` pass without modification.
- **Verification gaps:** None.
- **Verdict:** Pass (no findings).

### SVC — Services, orchestration, and audit semantics

- **Scope:** [near_miss_service.py:1-396](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/app/services/near_miss_service.py#L1-L396).
- **Coverage:** Complete.
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:**
  - **SVC-001 (Closed) — Near misses on highly repetitive text cost up to ~1 s of CPU per rejection and stopped before the end of 65,536-code-point buffers.**
    - **Provenance:** Opened as advisory P3 in [PR-13-ac842bb-delta-review.md](PR-13-ac842bb-delta-review.md) (`SVC-001`) and [PR-13-de6e7c2-friction-review.md](PR-13-de6e7c2-friction-review.md) (`NF-5`).
    - **Source evidence:** [near_miss_service.py:140-396](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/app/services/near_miss_service.py#L140-L396) (`near_misses`, `_candidate_starts`, `_piece_within_one_edit`, `_window_distances`, `_slide`).
    - **Trigger:** A `match_absent` rejection or preview on a 65,536-code-point repetitive buffer (such as `ops-log.md`, where every line shares the same characters and prefix structure as the needle).
    - **Expected / actual (before fix):** The sliding character-count lower bound (`Counter` bag distance) rarely pruned windows on repetitive logs because almost every window had a similar character multiset, and the Python row-by-row banded DP allocated lists per row, consuming ~708 ms in-process (~931 ms over stdio) and exhausting `MAX_COMPARISON_CELLS = 1_000_000` at offset `45,404` (`scope_truncated: True`), missing the distance-1 typo at offset `47,646`.
    - **Remediation implemented (`b27b3f5`):**
      1. **Exact positional pigeonhole filter (`_candidate_starts`):** Splits `needle` into `k + 1` (`threshold + 1`) disjoint pieces. By the pigeonhole principle, any window within edit distance `<= k` of `needle` must contain at least one piece with 0 edits, shifted by at most `[-k, +k]` from its piece offset `pos_i`. Using C-level `str.find` for each piece enumerates all candidate starts. Furthermore, when `len(needle) >= 3 * (k + 1)`:
         - If a window start `s` is discovered only via the last piece (`pieces[k]`, having missed the `k` rarest pieces `pieces[:k]`), it must spend 1 edit in each of `pieces[:k]` and 0 edits in all remaining pieces `pieces[k:]`. Merging adjacent pieces in `pieces[k:]` into contiguous unedited runs (and anchoring `pos_k == 0` at exact offset `s = at` since no edits precede index 0) eliminates false starts from shared suffixes.
         - Each 3-code-point piece `c0 c1 c2` in `pieces[:k]` must appear within `haystack[s + pos_i - k : s + pos_i + 3 + k]` within edit distance 1 (`c0 c1`, `c1 c2`, `c0 c2`, or `c0 _ c2`), checked via `_piece_within_one_edit`.
      2. **Exact Ukkonen-banded Landau–Vishkin diagonal-wave DP (`_window_distances`):** Evaluates edit distances `0..threshold` across diagonals `diag in [-band_radius, +band_radius]` where `band_radius = (threshold + 1) // 2` (exact Ukkonen band for width differences `{-1, 0, +1}` and distance `<= threshold`). By Ukkonen's diagonal monotonicity property (edit distance along any diagonal is non-decreasing with row index), the set of reachable rows on diagonal `d` at distance `<= dist` is always the contiguous interval `[max(0, -d), R_dist[d]]`, allowing `r_max = min(prev, needle_len - 1, window_len - 1 - diag)` for substitution/deletion transitions and C-level prefix slides (`_slide`) without dropping multi-width branches. Work is charged as `reached_row * (2 * band_radius + 1)` cells.
    - **Acceptance & closure evidence:**
      - Existing reference-equality tests in `backend/tests/unit/test_pass_a_diagnostics.py` and `backend/tests/unit/test_friction_followup.py` (`test_pruned_search_matches_unpruned_reference`, `test_banded_ranking_equals_unbanded_reference`, `test_early_row_abandon_keeps_ranking_and_cuts_cells`) pass.
      - New timing-independent test `test_repetitive_64k_buffer_scans_to_end_within_work_bound` in [test_friction_followup.py:467-482](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/tests/unit/test_friction_followup.py#L467-L482) verifies that the 65,536-code-point repetitive `ops-log` buffer scans to completion (`scope_truncated is False`, `scanned_end == 65493`) within `142,255 <= 200,000` comparison cells and returns exact ranking `[(1, 47646, 47692), (3, 27193, 27238), (3, 27808, 27854)]`.
      - In-process latency drops from **708.5 ms → 41.9 ms** on 65,536-code-point repetitive text and from **100.2 ms → 1.7 ms** on 65,536-code-point varied prose.
- **Verification gaps:** None.
- **Verdict:** Pass (`SVC-001` closed; no open findings).

### DB — Database, migrations, replay, and concurrency

- **Scope:** Read-only SQL queries in `backend/app/mcp/tools.py` (`patchdiff_get_pdcp_log` and `patchdiff_get_manifest_ledger`); schema, migrations `0001`..`0003`, and replay engine are unchanged.
- **Coverage:** Complete for read-query semantics and schema compatibility.
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification & reasoning:**
  - PostgreSQL 16 built-in `pg_input_is_valid(text, 'jsonb')` guards every `::jsonb` cast in `_SAFE_DOC_SQL` and `_SAFE_TX12_DOC_SQL`, ensuring malformed JSON or legacy `.pdcp` text (`0.2.3`) never raises a PostgreSQL cast error even if a row had an unexpected `protocol_version`.
  - `NOT ((...::jsonb) ? 'evidence_format')` ensures `patchdiff-invalid-input/1` ASCII evidence envelopes stored in `pdcp_content` on rejected invalid-Unicode attempts return `NULL` for `intent` / `transaction_intent` / `rationales`, matching `_decoded_record`.
  - Live migration tests (`test_migrations_reachable.py`) and replay tests (`test_selector_profiles_live.py`, `test_typed_submit_flow.py`, `test_friction_followup_live.py`) pass on PostgreSQL 16.3.
- **Verification gaps:** None.
- **Verdict:** Pass (no findings).

### SCRIPT — Scripts, evaluation, and developer tooling

- **Scope:** `evaluation/offline_eval.py`.
- **Coverage:** Complete (executed against `b27b3f5`).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification & reasoning:** `evaluation/offline_eval.py` exits 0 with all persisted byte counts, wire byte counts, shared-applier verdict equivalence checks, and `tx/3` content/hash oracles passing unchanged.
- **Verification gaps:** None.
- **Verdict:** Pass (no findings).

### TEST — Tests and CI

- **Scope:** [test_friction_followup.py:467-482](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/tests/unit/test_friction_followup.py#L467-L482), [test_friction_followup_live.py:636-720](https://github.com/paragon-ux/Patch-DIFF/blob/b27b3f54c2a8194f9bcb41650faac2fb5ccf30f0/backend/tests/integration/test_friction_followup_live.py#L636-L720), and the full 1,223-test suite.
- **Coverage:** Complete locally; GitHub Actions CI will run upon PR creation.
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification & reasoning:**
  - `test_repetitive_64k_buffer_scans_to_end_within_work_bound` is timing-independent: it asserts exact candidate ranking `[(1, 47646, 47692), (3, 27193, 27238), (3, 27808, 27854)]`, full-buffer reach (`scanned_end == 65493`, `scope_truncated is False`), and `0 < comparison_cells <= 200_000`.
  - `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` inspects actual PostgreSQL cursor column descriptions (`cursor.description`) via SQLAlchemy's `after_cursor_execute` hook across `tx/3`-only and mixed (`tx/1`, `tx/2`, `tx/3`, `0.2.3`, `patchdiff-invalid-input/1`) pages, proving `pdcp_content` is never selected while verifying that `include_content=True` still enforces the 1 MB page budget.
- **Verification gaps:** GitHub Actions CI on the pushed branch head and merge commit is pending PR creation.
- **Verdict:** Pass (no findings).

### DEP — Dependencies, packaging, and configuration

- **Scope:** None.
- **Coverage:** Not applicable (no dependency, lockfile, Docker, or configuration files changed).
- **P1 findings:** None identified within reviewed scope.
- **P2 findings:** None identified within reviewed scope.
- **P3 findings:** None identified within reviewed scope.
- **Verification gaps:** None.
- **Verdict:** Not applicable.

---

## 5. Cross-category root causes and rationale for remediation order

1. **SVC-001 root cause:** Bag-distance pruning (`Counter` multiset difference) ignores character order and position, so on structured logs where every line contains the same vocabulary (timestamps, level tags, field names), almost no window start is filtered out; evaluating every surviving window with a Python list-per-row DP then dominated CPU and exhausted the 1,000,000-cell cap before reaching the end of the 65,536-code-point buffer. Replacing the multiset filter with an exact positional pigeonhole filter (`str.find` on disjoint needle pieces + contiguous unedited run merging + 3-char 1-edit checks) and replacing the row-by-row DP with an Ukkonen-banded Landau–Vishkin diagonal-wave DP eliminates both bottlenecks while preserving 100% mathematical exactness.
2. **MCP-001 root cause:** `patchdiff_get_manifest_ledger` and `patchdiff_get_pdcp_log` loaded full `AppendOnlyPdcpLogs.pdcp_content` TEXT columns into Python and ran `json.loads` on the entire document solely to read top-level `intent` and per-edit `rationale`. Moving that projection into guarded SQL expressions (and skipping `AppendOnlyPdcpLogs.pdcp_content` altogether on `tx/3` / `0.2.3` ledger pages) eliminates multi-megabyte TOAST transfers and Python JSON parsing on history reads.

---

## 6. Verification record and remaining gaps

| Check | Revision | Environment | Result |
| --- | --- | --- | --- |
| Full pytest suite (`pytest backend/tests -q`) | `b27b3f5` | Windows 11, Python 3.11.9, PostgreSQL 16.3 (`patchdiff-postgres`), isolated DB `patchdiff_perf_p3_20261024` (dropped after run) | **1,223 passed** (813 unit + 410 live-PostgreSQL integration), 0 failed, 0 skipped |
| Offline evaluation (`evaluation/offline_eval.py`) | `b27b3f5` | Windows 11, Python 3.11.9 | **Exit 0** (`Verdict equivalence on the shared applier: OK`, `Accepted guarded replacement content/hash oracles: OK`) |
| Randomized exactness fuzzing (2,000 trials vs unpruned/unbanded Levenshtein reference) | `b27b3f5` | Windows 11, Python 3.11.9 | **2,000 / 2,000 exact matches** across varied and repetitive strings (`len 1..64`) |
| Isolated DB cleanup check | `b27b3f5` | `patchdiff-postgres` (`127.0.0.1:5432`) | Verified `patchdiff_perf_p3_20261024` dropped; default `patchdiff` DB untouched |
| GitHub Actions CI | Pending push | `ubuntu-latest` + `postgres:16.3-alpine` | To be verified after `gh pr create` |

---

## 7. Overall disposition and finding closure table

**Overall disposition:** **Approve** (all material categories reviewed; zero open P0/P1/P2/P3 findings; both deferred P3 findings `SVC-001` and `MCP-001` closed with unit tests, live-PostgreSQL integration tests, and before/after latency measurements).

| Finding ID | Friction ID | Category | Priority | Status | Fix commit | Verification evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `SVC-001` | `NF-5` | `SVC` | P3 (advisory) | **Closed** | `b27b3f5` | `test_repetitive_64k_buffer_scans_to_end_within_work_bound` (`test_friction_followup.py`), `test_pass_a_diagnostics.py`; 65,536-cp repetitive buffer: 708.5 ms (`scanned_end=45404`, `scope_truncated=True`) → **41.9 ms** (`scanned_end=65493`, `scope_truncated=False`, `142,255` cells); 65,536-cp varied prose: 100.2 ms → **1.7 ms** |
| `MCP-001` | `NF-8` | `MCP` | P3 (advisory) | **Closed** | `b27b3f5` | `test_mcp001_large_tx3_ledger_and_attempt_pages_do_not_select_pdcp_content` (`test_friction_followup_live.py`), `test_mcp_history_paging_live.py`, `test_mcp_arguments_paging.py`; 20 × 1 MB `tx/3` ledger page: 230–263 ms → **21.1–23.6 ms** (1.4 ms SQL, zero `pdcp_content` selected); attempt log page: 234–260 ms → **68.1–76.3 ms** (9.5 ms SQL, `pdcp_content` deferred) |
