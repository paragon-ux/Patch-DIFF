# PR #11 friction review: agentic host lifecycle at `d68c77d`

## 1. Metadata

| Item | Value |
| --- | --- |
| Repository / PR | `paragon-ux/Patch-DIFF` PR #11 |
| Head under test | `d68c77d5709399ad0d1dc3b95db60a0054edcfba` (worktree `pr11-fix`, branch `fix/pr11-review-findings`, identical to `origin/feature/goal-f-rejection-context`) |
| Merge base with `origin/main` | `2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10` |
| Date | 2026-10-22 |
| Review type | Friction review run as an agentic host. It is not a PR Review Standard category review and does not replace one. |
| Runtime | Windows 11, Python 3.11.9 venv (lockfile deps plus an editable install of the worktree), pytest 9.0.3 |
| Database | `patchdiff_pr11_friction` on Docker `patchdiff-postgres` (postgres:16.3-alpine, 127.0.0.1:5432). Alembic `upgrade head` applied `20260510_0001` and `20261020_0002`. The database is kept for inspection: 45+ attempt rows and 33 ledger rows. |
| MCP server | Real stdio subprocess `python -m app.mcp.external_adapter` (serverInfo `patchdiff-mvp` 0.2.2, 20 tools). `PYTHONIOENCODING` was removed from the server environment to exercise the strict-UTF-8 path. Requests were sent as literal UTF-8, not ASCII-escaped. |
| Scratch repo | `…\scratchpad\friction-repo\` with commits `749b480` (initial) and `9502f1e` (PatchDIFF edits written back). Repo-local `core.autocrlf=false` keeps bytes exact; the global setting is `true`. |
| Evidence | `…\scratchpad\friction-tools\transcript.jsonl`: 213 JSON-RPC records with request/response bytes, timings and task labels. Bodies over 200 KB are clipped to a SHA-256 plus a 2 KB head. Also in that folder: `metrics.json` (per-task aggregates), `tools_list.json` (the `tools/list` result), `t6_typo_responses.json`, `exports.json`, `state.json` (target IDs), and the scripts `pdclient.py`, `make_repo.py`, `t11_glue.py`, `t12_audit.py`, `metrics.py`, `ctxstats.py`. Scripts not saved as files were piped through stdin, and every request they sent is in the transcript. |

`…\scratchpad\` = `C:\Users\USER\AppData\Local\Temp\claude\C--Users-USER-Desktop-Frameworks-Patch-DIFF\699fb695-9b16-439f-bd31-35399e6b8eba\scratchpad\`

Totals: 179 `tools/call` requests, of which 31 were rejected, 5 returned `invalid_argument` and 2 returned an `isError` tool error. Excluding the deliberate size probes, the host sent 43,011 request bytes and received 224,397 response bytes. Including them, about 19 MB went up.

Targets: README `82bd8504…`, `src/calc.py` `73ecfce5…`, `config.yaml` `756981a9…`, CHANGELOG `634e2370…`, `docs/i18n.md` `984df178…`, `tests/test_calc.py` `756a016b…`. Demo targets: `75b64299…` (index trap), `424858e0…` (UTF-16 insert), `a7c9298e…` (2.08M code-point performance doc).

## 2. Lifecycle

### 2.1 Task outcomes

| # | Task | Tools used | Calls | Rejections | Outcome |
| --- | --- | --- | --- | --- | --- |
| 1 | Initialize one target per file | `initialize_target`×6, `get_target`×8 | 14 | 0 | Six targets at v0. The CRLF/no-final-newline `docs/i18n.md` was silently LF-normalized (178 → 168 code points). Its `current_hash` ≠ SHA-256 of the file bytes, and the response gives no signal of either (FR-3). 7 of the `get_target` calls were spent recovering IDs after my own client crashed on a console-encoding error. That crash is not product friction. |
| 2 | Fix the `mean()`/`clamp()` bug | `read_lines`, `find_occurrences`, `submit_edits` | 3 | 0 | Accepted v1: two edits, with `occurrence_index: 2` on `return low`. The scratch tests went from 2 failed to 4 passed after export. |
| 3 | Rename `Calcly` → `Numerix` in README (keep `CalclyCore`) | `submit_edits`, `find_occurrences`×2, `preview`×2, `submit_operations` | 6 (+4 demo) | 3 (1 `match_ambiguous`, 2 previewed `disambiguation_invalid`) | Accepted v1 using six tx/2 spans in descending offset order, with `parent_pdcp_log_id` and `attempt: 2`. `exact_candidates` showed 5 of 7 occurrences, so a `find_occurrences` call was still needed. In the demo, indexes copied from `find_occurrences` produced an **accepted wrong edit** (FR-1). |
| 4 | Insert a section by line, then a multi-op tx/2 with emoji | `read_lines`×5, `preview`, `submit_operations`×2 | 8 (+5 demo) | 0 | README: a `## Testing` section was inserted at offset 380. It took two `read_lines` calls to turn line 25 into an offset. `i18n.md`: a 4-op tx/2 was accepted, with sequential spans 23..24, 84..84, 177..182 plus a match op. In the demo, an insertion at a UTF-16-derived offset and one inside a flag grapheme were both **accepted** (FR-2). |
| 5 | Concurrent writer on `config.yaml` | `read_target`×2, `submit_edits` (second client), `submit_operations`×2, `get_pdcp_log` | 6 | 1 `target_version_mismatch` | Recovered on attempt 2 (the span moved 33 → 50) with a parent link. `current_context` held the whole 151-code-point file, so recovery was possible without a re-read. I did the re-read anyway. |
| 6 | Typo recovery | `read_target`, `submit_edits`×6, `find_occurrences` | 8 | 5 `match_absent` | Short typo and 50-code-point typo: `near_misses[0]` was exact at distance 1. Typo at offset 392 (beyond 256): `candidates: []` with `status: "computed"`, so I fell back to `find_occurrences` (FR-6). 77-code-point multi-line indentation typo: `match_too_large`, no hints. Accepted v3 with a parent link. |
| 7 | Idempotency | `submit_edits`×7 | 7 | 3 `context_invalid` | Two `deduplicated: true` responses with the same `pdcp_log_id`. A resend after the target advanced still reports `version: 2` while the target is at 3 (FR-9). Key reuse with reworded intent produced a conflict with `existing_pdcp_log_id`. A key containing whitespace, and `rationale: null` vs an omitted field, also produced `context_invalid` (FR-10). |
| 8 | Preview vs submission | `preview` (×8 overall), `submit_*` | 4 (+ previews in tasks 3, 4, 9, 10) | 3 (expected) | 3 compared pairs (2 accepted, 1 rejected): verdict, `failure_reason`, `failed_change_id`, `after_hash` and change facts matched exactly. A preview with a stale guard rejects at `precondition_guard`. Preview omits `near_misses` and uses a different response shape (FR-14). |
| 9 | Rewrite CHANGELOG with tx/3; oversized replacements | `read_target`, `preview`, `submit_replacement`×4, `get_target`, `get_pdcp_log` | 3 + 5 | 0 rejected, 3 `invalid_argument` | Accepted `replace_all` (60 → 328 code points). The 1,000,001-code-point, 1,200,000-byte and raw-CRLF 1,020,000-code-point probes (680,000 canonical) all returned `replacement_too_large`, with no attempt row and the version unchanged. The same 2.08M-code-point rewrite succeeds through tx/1 and tx/2 (FR-12). |
| 10 | `include_correlation_id` | `submit_edits`×3, `preview`, `read_target`, `save` | 6 | 1 (`save` with a non-UUID ID) | A fresh UUID on every submission, including dedup. `"true"` (string) → `invalid_argument`, no row. Passing the flag to `preview`/`read_target` returns an `isError` Python `TypeError` text (FR-14). |
| 11 | SAVE → replay → export → write back → test → commit | `get_target`, `save`×7, `replay`×6, `export_target`×11, `initialize_target` | 31 | 0 | All six replays `success` with `materialized_state_matches: true`. A naive write-back passed pytest (4/4) but turned an 11-line `i18n.md` file into a full rewrite (CRLF → LF). A 20-line host glue restored CRLF from git HEAD. Committed `9502f1e`. `export_target(format="docx")` echoes `"docx"` back with LF text (FR-3). |
| 12 | Audit summary | `get_pdcp_log`×14, `get_manifest_ledger`×19 (limit 2) | 33 | 0 | Rebuilt 22 attempts and 22 ledger rows across six targets. After SAVE, the default ledger call returned 0 rows. Ledger rows could only be joined to attempts by matching intent text (FR-11). |
| – | Extra probes: schema edges, `read_lines` paging, large-doc performance | mixed | 36 | 15 | See FR-4, FR-5, FR-7, FR-12, FR-13 and FR-14. |

### 2.2 Per-task measurements

Bytes are request/response wire bytes for the task label in `transcript.jsonl`. Server process start-up (`initialize`, median 1,585 ms) is excluded from latency.

| # | Retries | Bytes (req / resp) | Information the host had to compute | Messages that did not say what to do next |
| --- | --- | --- | --- | --- |
| 1 | – | 4,588 / 8,938 | Whether the server normalized line endings, by comparing my own hash of the LF text with `current_hash`. | Initialize gave no message at all about the CRLF normalization. |
| 2 | – | 1,218 / 3,482 | A match long enough to be unique, or the `occurrence_index` from search. | – |
| 3 | 1 (attempt 2) | 2,997 / 15,746 (+1,681 / 3,694 demo) | The set of occurrences to keep (`CalclyCore` is a substring hit), and offsets reordered descending so the sequential coordinates stayed valid. | `disambiguation_invalid`: "occurrence_index is outside the exact occurrence list." It does not mention that indexes are renumbered after earlier edits. |
| 4 | – | 3,214 / 9,898 | Line → absolute offset (an extra `read_lines` call, or summing line lengths), code-point offsets around emoji, and the cumulative delta for later ops (+1 then +13). | – |
| 5 | 1 | 2,199 / 9,690 | The new span offset after the other writer's change. There is no "changes since version N" to rebase with. | – |
| 6 | 1 | 3,381 / 18,781 | Which near miss to use, and that an empty list means "outside the scanned 256 code points". | "MATCH text was not found." with `candidates: []` and `omission_reason: null`. |
| 7 | – | 2,727 / 11,877 | That `context_invalid` here means a key conflict, not malformed input. Also had to track the current version separately from the dedup response. | The conflict detail is clear, but the failure label collides with the "fix the request shape" row of the guide's table. |
| 8 | – | 1,471 / 8,250 | Mapping preview fields (`change_facts`, top-level `validation_stage`) onto submission fields (`evidence.changes`, `diagnostic.validation_stage`). | – |
| 9 | – | 1,593 / 2,975 (+4.03 MB / 3,144 oversize) | Actual sizes versus limits, and that the canonical CRLF text would have fit. | `replacement_too_large` with `limit_exceeded: "raw_code_points"` but no actual or limit values. |
| 10 | – | 1,828 / 3,429 | – | `"Invalid arguments for patchdiff_preview: patchdiff_preview() got an unexpected keyword argument 'include_correlation_id'"` |
| 11 | – | 4,649 / 19,329 (+1,239 / 4,395) | Original EOL style per file (recovered from git HEAD), and re-encoding plus hash verification before writing. | – |
| 12 | – | 6,904 / 62,486 | Joining ledger rows to attempts, parsing double-encoded `pdcp_content` JSON for intents, and reversing ledger pages. | – |

## 3. Friction findings

Severity counts: **blocking 0, high 3, medium 11, low 6.** "New in PR" means the code or document path was added or changed between `2ee7ce4` and `d68c77d`. "Pre-existing" findings still affect any host adopting this PR.

### High

#### FR-1: `occurrence_index` is counted in the sequential buffer, but the docs tell hosts to copy it from `find_occurrences`/`exact_candidates`. Multi-edit renames are accepted while editing the wrong occurrences.

- **Category:** usability / documentation (pre-existing semantics; the new PR guidance repeats them).
- **Evidence:** On demo target `75b64299…`, `find_occurrences("Calcly", max_results=3)` returned `[(1,2),(2,10),(3,100)]`. The host intent was "Rename the first three Calcly mentions (title, tagline, install line)", sent as `edits: [{match:"Calcly", replace:"Numerix", occurrence_index:1|2|3}]`, and the submission was accepted:

  ```text
  evidence spans: chg_001 2..8, chg_002 101..107, chg_003 295..301
  Numerix at 2   '# '                  '\n\nCalcly is a '        <- tagline still Calcly
  Numerix at 101 'tion\n\nInstall '    ' from a checko'
  Numerix at 295 'etic helpers. '      ' keeps no glob'          <- Architecture section edited
  ```

  On the real README, the preview with indexes `[1,2,3,5,6,7]` was rejected at `chg_004` with "occurrence_index is outside the exact occurrence list." Its `exact_candidates` (`buffer_stage: "intermediate_buffer"`, `prior_changes: 3`) show that originals 1, 3 and 5 had already been renamed.
- **Impact:** The guide's failure table says "add `occurrence_index` … (indexes from `find_occurrences`)", and the new text says "Ambiguity failures list up to five exact candidates: choose one with `occurrence_index`". A host that follows either for more than one same-string edit in one transaction gets either a confusing rejection or, as shown above, a committed wrong edit that no guard can detect.
- **Remedy:** In the guide and the tool descriptions, state that indexes are resolved against the buffer after earlier edits, and recommend tx/2 spans in descending order for multi-occurrence edits. Add the renumbering explanation to the `disambiguation_invalid` detail when `prior_changes > 0`. Consider an explicit `occurrence_basis: "transaction_start"` selector or a multi-occurrence selector in a future profile.

#### FR-2: Empty-span insertions carry no positional check, so host offset mistakes are accepted silently, including grapheme splits.

- **Category:** defect-risk / usability (new in PR, tx/2).
- **Evidence:** On demo target `424858e0…` (the CRLF emoji file), the code-point offset of `- Developer` is 83, but a UTF-16 host computes 85.

  ```text
  submit_operations [{op:"span", start:85, end:85, expected_text:"", replace:"- 한국어: 계산기 🔢\n"}] -> accepted
  submit_operations insertion between U+1F1EF and U+1F1F5 -> accepted
  read_lines -> '- 日本語: 電卓 🧮\n- - 한국어: 계산기 🔢\nDeveloper: 👨\u200d💻 …\n- Flag: 🇯X🇵 Japan\n'
  ```

  The wire format makes this mistake natural: `content[0].text` is ASCII-escaped JSON (`Internationalisation \\ud83c\\udf0d`), so JavaScript and TypeScript hosts, which include most MCP clients, receive UTF-16 strings, while offsets are code points.
- **Impact:** Replacement spans are protected by `expected_text`, but insertions, the documented way to add a section, have no verification. Off-by-N errors from UTF-16 units, CRLF counting or line arithmetic commit corrupted text with `status: "accepted"` and `warnings: []`.
- **Remedy:** Add optional `expected_before`/`expected_after` context to span ops (or require it for `start == end`). Emit a warning when a span boundary splits a grapheme cluster or a CRLF pair. Put "offsets are Unicode code points; convert from UTF-16 in JS" in the `submit_operations` and `find_occurrences` tool descriptions, not only in MCP_TOOLS.

#### FR-3: Line endings are normalized silently, and `export_target(format=…)` ignores its argument while labelling LF text `original_text`.

- **Category:** usability / documentation (pre-existing; `export_service.py`, `canonicalization.py` and `target_service.py` are unchanged in this PR).
- **Evidence:** `initialize_target` for `docs/i18n.md` (CRLF, 178 code points) returns only `{active_editing_cycle_id, current_hash, filename, target_file_id, target_type, version}`. The stored text has 168 code points and no CR. `export_target` with `format` set to `"original_text"`, `"crlf"`, `"docx"` or `""` echoed each value back and returned LF text every time. A mixed-EOL file `"line1\r\nline2\nline3\rline4"` exports as `"line1\nline2\nline3\nline4"`, and the original form cannot be recovered. Writing the naive export back to the repo produced:

  ```text
   docs/i18n.md | 23 ++++++++++++-----------   (4 real edits; every line rewritten)
  ```

  After `t11_glue.py` restored CRLF from git HEAD, the diff was 7 lines.
- **Impact:** Every Windows or CRLF repo round-trip needs host-side EOL bookkeeping that PatchDIFF neither records nor reports. A host cannot verify its local file against `current_hash` without canonicalizing first. Mixed-EOL and bare-CR files lose information irreversibly. The `original_text` label suggests the opposite.
- **Remedy:** Return `normalization: {crlf: n, cr: n}` (and the dominant EOL) from initialize and store it. Make `format` an enum (`canonical_lf`, `original_eol`) that is honoured, or reject unknown values. Rename or redocument the `original_text` default. Add a "round-tripping to files" section to the host guide.

### Medium

#### FR-4: `diagnostic.retryable` is `false` for the new span failures, even though the guide says to re-read and retry.

- **Category:** defect (new in PR).
- **Evidence:** `span_expected_text_mismatch` returns `{"format":"patchdiff-tx/2","requires_new_submission":true,"retryable":false,…}`, and `span_out_of_bounds` behaves the same way. The guide table says "Re-read, recompute offsets … copy `expected_text` exactly". The PR added both reasons to `PDCP_REJECTION_REASONS` and `TRANSACTION_FAILURE_REASONS` but not to the retryable sets in `backend/app/pdcp/applier.py:152` and `backend/app/services/pdcp_service.py:1352`. The two sets also differ from each other: only the service set contains `target_version_mismatch`.
- **Impact:** A host that gates automatic retry on `retryable` gives up on the most common tx/2 failure, a stale offset after a concurrent edit.
- **Remedy:** Add both reasons to one shared retryable set, define `retryable` in MCP_TOOLS, and add a test.

#### FR-5: Span failures do not show what is actually at the span.

- **Category:** usability (new in PR).
- **Evidence:** The `span_expected_text_mismatch` diagnostic keys are `['failure_context','format','requires_new_submission','retryable','validation_stage']`. The detail reads "Span expected_text does not match the sequential buffer." `span_out_of_bounds` does not report the buffer length. `failure_context` is the document prefix, not the span.
- **Impact:** Every span mismatch costs another read round-trip, even though the server already holds the text at `[start, end)`.
- **Remedy:** Add a bounded `actual_text` (≤64 code points, failing-buffer coordinates) and `buffer_length` to these diagnostics.

#### FR-6: Near misses only scan the first 256 code points, and an empty result does not say that the scope was the cause.

- **Category:** usability / documentation (new in PR).
- **Evidence:** A typo at offset 392 of a 487-code-point README returned:

  ```json
  {"candidates": [], "status": "computed", "omission_reason": null, "truncated": true, "returned_count": 0}
  ```

  `truncated: true` here means the prefix was cut. In the successful short-typo case it means the candidate list was cut. The field means both.
  - In `src/calc.py`, everything after `add()` lies beyond offset 256.
  - A 77-code-point multi-line indentation typo returned `omission_reason: "match_too_large"`.
- **Impact:** Near misses help mainly with short typos near the top of a file. An agent can read `status: "computed"` with an empty list as "no similar text exists".
- **Remedy:** Add `scanned_start`/`scanned_end` and separate `scope_truncated` from `candidates_truncated`. Name `find_occurrences` on a fragment as the next step in `failure_detail`. Consider scanning the whole buffer under the existing work cap.

#### FR-7: Near-miss candidates repeat one location and can point at the wrong text.

- **Category:** usability (new in PR).
- **Evidence:**
  - For short typos, all three candidates are overlapping windows of one spot: `Numerix is a` (d=1), `Numerix is ` (d=2) and `umerix is a` (d=2).
  - For `sequential_match_invalid` (query `# Numerix`, consumed by the earlier edit), the candidates were `l Numerix` and ` Numerix` in "Install Numerix", which is unrelated text.
  - The `failure_detail` for `sequential_match_invalid` is the same "MATCH text was not found." used for `match_absent`.
- **Impact:** Duplicate windows crowd out other locations. For sequential failures the hints steer the agent towards editing the wrong line, and nothing names the earlier change that consumed the text.
- **Remedy:** Keep the best window per location. For `sequential_match_invalid`, report the original-buffer occurrence and the earlier `change_id` whose span overlapped it, and suppress near misses.

#### FR-8: `failure_context` and `current_context` duplicate each other and are mostly irrelevant.

- **Category:** performance / usability (new in PR).
- **Evidence:** In 25 of 28 rejections the two objects were byte-identical, and together they made up 42% of rejection response bytes (median 45% per response). Rejections are 2.1 to 3.6 KB, against 1.0 to 2.8 KB for acceptances. Both always show the document prefix, even when the failing location is known (ambiguous candidates, span start, key conflicts).
- **Impact:** Every rejection costs the model context tokens and rarely shows the failing text.
- **Remedy:** When the observed version and hash are equal, replace `current_context` with `{same_as_failure_context: true}`. Centre the context window on the failing span or the first candidate when one is known.

#### FR-9: Deduplicated responses report the old version with no current state.

- **Category:** usability (pre-existing response shape; it matters more now that recovery is documented).
- **Evidence:** The first submission returned `accepted v 2`. Another write moved the target to `v 3`. Resending the first request returned `accepted v 2 dedup True`, with keys `[after_hash, before_hash, client_request_id, deduplicated, evidence, manifest_entries_added, pdcp_log_id, status, target_file_id, validity, version, warnings]` and no current version or hash.
- **Impact:** A host that tracks the version from responses goes stale and spends a rejection plus a read to recover.
- **Remedy:** Add `current_version`/`current_hash` to accepted and deduplicated responses.

#### FR-10: Request-key conflicts are reported as `context_invalid`, and request identity depends on serialization details.

- **Category:** usability / documentation (pre-existing labels; the guide table was edited in this PR).
- **Evidence:**
  - Reusing a key returned `failure_reason: "context_invalid"` with "client_request_id was already used for a different proposal on this target." and `retryable: false`.
  - Resending the same request with `rationale: null` in place of an omitted field also returned `context_invalid`, and was not deduplicated.
  - A key with spaces returned `context_invalid` as well, and wrote a durable row.
  - The guide's §2 table maps `context_*` to "Malformed typed input → Fix the request shape".
- **Impact:** An agent following the table misdiagnoses the conflict. A host SDK that normalizes optional fields to `null` on retry turns lost-response recovery into a conflict, which is safe but loses the recovery.
- **Remedy:** Use a distinct label (or `diagnostic.code: "request_key_conflict"`) and add a table row. Return a hint naming the differing fingerprint component. Recommend recovering through `get_pdcp_log(client_request_id=…)`.

#### FR-11: The audit trail cannot be joined through MCP.

- **Category:** usability (pre-existing).
- **Evidence:**
  - `get_manifest_ledger` entries omit `pdcp_log_id`, even though `append_only_manifest_ledger.pdcp_log_id` is NOT NULL in the model. They also omit the version.
  - The ledger `intent` holds the per-edit rationale when one is present, for example "Mean divides by the element count, not count + 1.", so the transaction intent is lost from that row.
  - After SAVE, the default call returned 0 rows. The guide §6 does not mention `include_previous_cycles`.
  - Attempt intents are only visible with `include_content=true`, as double-encoded JSON.
  - `log_sequence` is global across targets (1..31 interleaved), and `attempt` shows up as `regeneration_attempt` with `regeneration_source: "host"`.
- **Impact:** The 6-target audit took 33 calls plus a heuristic join on intent text.
- **Remedy:** Expose `pdcp_log_id`, before/after version and the transaction intent on ledger rows. Add a short intent or summary to attempt rows. Document the post-SAVE cycle behaviour and the per-target sequence gaps.

#### FR-12: tx/3 limits are not a document or request limit, and rejected payloads are stored and returned without bound.

- **Category:** performance / design / documentation (new in PR).
- **Evidence:**
  - On demo `a7c9298e…` (2,079,997 code points), a tx/2 span replacing `0..len` was accepted in 762 ms, and a tx/1 whole-document match in 692 ms. Each request was 4.29 MB. tx/3 rejects anything over 1,000,000 code points, and the guide's remedy is "Split the change into operations instead".
  - A rejected 4.29 MB span proposal is stored permanently.
  - `get_pdcp_log(include_content=true, limit=50)` returned a single 5,076,692-byte line.
- **Impact:** The limit does not bound resource use, and the remedy guidance bypasses it. History paging is bounded only by row count.
- **Remedy:** Either document the tx/3 limit as tool-specific and say why, or apply one shared admission cap. Add a byte budget (with omission markers) to `include_content` pages.

#### FR-13: `read_lines` mixes coordinate frames.

- **Category:** usability (new in PR).
- **Evidence:** `read_lines(20..24, max_chars=40)` returned `{range_start:228, start:228, end:268, next_offset:40}`, and the next page returned `{start:268, end:308, next_offset:80}`. `start`/`end` are absolute while `offset`/`next_offset` are relative to the range. Passing `next_offset` (40) as `read_target.start` read `' library used to exercise PatchDIFF.'` instead of the continuation. There are no per-line offsets, so turning a line number into an offset needed a second call.
- **Impact:** A generic "continue with next_*" loop reads the wrong region. Offsets derived from it feed FR-2.
- **Remedy:** Also return an absolute `next_start`. Optionally return `line_starts` for the selected range.

#### FR-14: Tool results are double-escaped and response shapes are inconsistent.

- **Category:** usability / performance (pre-existing escaping; new preview shape).
- **Evidence:**
  - `_tool_result` uses `json.dumps(payload)` with the default `ensure_ascii`, so the model sees `\ud83c\udf0d` and `\u4e2d` instead of literal characters. On the wire each emoji costs 14 bytes (`\\ud83c\\udf0d`) and each CJK character 7, against 4 and 3 bytes in UTF-8.
  - Field names differ by outcome: accepted responses use `version`/`after_hash`; rejected ones use `current_version`/`current_hash`; previews use `before_version`/`current_version`, a top-level `validation_stage` and `change_facts` (instead of `evidence.changes`).
  - `status` is absent on success for `initialize_target`/`get_target`/`export_target`.
  - There are three error envelopes:
    - `status:"invalid_argument"` + `failure_detail`
    - preview's `code`/`detail`
    - `isError` plain text leaking Python signatures
- **Impact:** The model must reproduce exact non-ASCII text from escaped input, CJK/emoji text costs about 2 to 3.5 times the wire bytes, and the host needs per-tool glue to track version and hash.
- **Remedy:** Use `ensure_ascii=False` (the stdio path is now strict UTF-8). Converge on common `current_version`/`current_hash` fields and a single error envelope. Return a structured `invalid_argument` for unknown parameters.

### Low

#### FR-15: Schema descriptions are sparse.

- **Category:** documentation (mostly new tools).
- **Evidence:** Edit-item fields are described. At the top level, only `include_correlation_id`, `find_occurrences.context_chars` and the history `limit`/`before_sequence`/`client_request_id` fields carry descriptions. The span `start`/`end`/`expected_text`, both guards, `parent_pdcp_log_id`, `attempt`, `source`, every `read_lines` parameter and the export `format` have none. The submit and preview schemas use a top-level `anyOf` and `allOf`/`if`/`then`/`not`, which some function-calling schema dialects reject. I did not verify that against a live host.
- **Remedy:** Add one-line descriptions (coordinate frame, units, guard semantics). Mirror the conditional rules in prose for hosts that strip schemas.

#### FR-16: MCP_TOOLS examples have drifted.

- **Category:** documentation.
- **Evidence:**
  - The `match_ambiguous` example detail is "match matched 2 exact occurrences in the current buffer." The actual detail is "MATCH text appears multiple times without disambiguation."
  - Evidence examples lack `change_index` and `operation`.
  - "All submission tools accept `include_correlation_id`", but deprecated `patchdiff_request_regeneration` does not.
  - The guide uses UUID `11111111-1111-1111-…` while the schema examples use `11111111-1111-4111-…`.
  - The guide's "Executable discovery example sequence" paragraph packs a 10-step script into prose and is hard to follow.
- **Remedy:** Regenerate the examples from live output and turn the discovery sequence into a numbered list.

#### FR-17: No-op edits are accepted silently.

- **Category:** usability.
- **Evidence:** `Numerix → Numerix` was accepted: version 3, `before_hash == after_hash`, `warnings: []`.
- **Impact:** The version bumps with no content change. Combined with a hash-only guard, this is the documented ABA hazard, and the host gets no signal of it.
- **Remedy:** Emit a `no_op_change` warning.

#### FR-18: Bounded diagnostics omit the numbers the host needs.

- **Category:** usability.
- **Evidence:**
  - `exact_candidates` returns 5 of 7 with no cursor, so a `find_occurrences` call is needed.
  - `replacement_too_large` gives `limit_exceeded` without actual or limit values.
  - A raw-CRLF replacement (1,020,000 code points) is rejected although the canonical result (680,000) would fit, and the response does not say so.
- **Remedy:** Add `actual` and `limit` values, and note when canonicalization would have fit.

#### FR-19: Preview is weaker than submission as a recovery tool.

- **Category:** usability (new in PR, documented).
- **Evidence:** Preview never returns `near_misses`. Preview rejects `include_correlation_id` with an `isError` `TypeError` instead of `invalid_argument`.
- **Remedy:** Allow near misses in preview. It holds no lock and could compute them inline under the same budget.

#### FR-20: `patchdiff_save` only accepts a hash guard.

- **Category:** usability (pre-existing).
- **Evidence:** The schema properties are `expected_current_hash`, `export_after_save` and `target_file_id`. The guide says "prefer a version guard" because hashes cannot detect ABA changes.
- **Remedy:** Accept `expected_target_version` on save.

## 4. What worked well

- **Guards and atomicity held everywhere.** I found no partial commit, lost update or phantom write. Version and hash guards rejected the concurrent-writer submission at `precondition_guard`, and the linked retry (`parent_pdcp_log_id`, `attempt: 2`) recorded correctly.
- **Replay and preview were consistent.** Replay succeeded with `materialized_state_matches: true` on all six real targets and on the 2M-code-point demo after tx/1, tx/2 and tx/3 history. Preview and submission agreed on verdict, reason, failed change, `after_hash` and change facts in every compared pair.
- **tx/2 spans worked well when offsets come from server reads.** `expected_text` caught every wrong replacement span (`span_expected_text_mismatch` with no side effects). Descending-order spans made a selective rename trivial. Mixed match/span transactions were atomic.
- **The new evidence is useful where it applies.** `exact_candidates` context (20 code points per side) made the `CalclyCore` substring hit obvious. Near misses gave the exact fix for short typos inside the scanned prefix. `current_context` alone was enough to rebase a small-file edit.
- **Idempotency is solid.** Identical resends returned the original `pdcp_log_id` with `deduplicated: true`, even after the target advanced, with no new row. Conflicts never overwrote the original, and they link it through `existing_pdcp_log_id`.
- **tx/3 admission is clean.** Oversized replacements were refused before any write, with no attempt row and no version change, in 36 to 116 ms even at 1.2 MB.
- **Latency is good.** The median per call is about 8 to 12 ms for most reads and 35 to 60 ms for submissions. `read_target` had a 93 ms median, mostly from first calls in a fresh process. On a 2.08M-code-point document, operations stayed under 0.8 s except the 1.9 s rejection of a 4.29 MB request.
- **The stdio path held up.** It handled literal UTF-8 (CJK, ZWJ emoji, flags, combining marks) correctly without `PYTHONIOENCODING`, and every invalid argument tested produced a clear, specific `failure_detail` (guard syntax, unknown fields, span ordering, key syntax).

## 5. Verdict

No finding shows PatchDIFF violating its documented contract, losing data or exposing a security problem.

- FR-1 and FR-2 produced accepted edits that were wrong relative to host intent. In both cases the server executed exactly the well-formed instruction its contract defines: sequential `occurrence_index`, and unverified empty-span insertion in code points. They are high-severity usability and documentation risks, not contract violations.
- FR-4 is a real defect introduced by this PR (a stale `retryable` set), but it affects only an advisory flag whose semantics are undocumented.

I recommend fixing FR-1/FR-2 guidance (or adding the insertion context guard) and FR-4 before hosts adopt tx/2 widely.

Merge-blocking findings: no
