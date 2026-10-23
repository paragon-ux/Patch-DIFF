# PR #13 friction review: agentic host re-test at `de6e7c2`

## 1. Metadata

| Item | Value |
| --- | --- |
| Repository / PR | `paragon-ux/Patch-DIFF` PR #13, "Fix PR #11 friction findings FR-1..FR-20" |
| Head under test | `de6e7c29e1dbafe0caa915e490476a8c6ee5a5a0` (worktree `pd-fr-followup`, branch `fix/pr11-friction-followup`). Product code is identical to `0420dac`; `de6e7c2` only adds the author's review files. |
| Base used for comparison | `16ce338e0ed251a7bbfc372f29db916e966e1388` (`main`), extracted read-only with `git archive 16ce338 backend` into the scratch directory and run from there with the same venv |
| Date | 2026-10-22 |
| Review type | Independent friction review run as an agentic host. It is not a PR Review Standard category review and does not replace one. The author's [category review](PR-13-0420dac-category-review.md) was read but not relied on; every claim below was checked against live responses or SQL. |
| Runtime | Windows 11 Pro, Python 3.11.9 (worktree `.venv`), Git Bash. Locale preferred encoding `cp1252`. |
| Database | `patchdiff_pr13_friction` on Docker `patchdiff-postgres` (postgres:16.3-alpine). Created empty and upgraded to `20261022_0003`, then downgraded (empty) to `20261020_0002`. Pre-PR history was written with the base server, then upgraded `0002 → 0003` populated. At the end, `alembic downgrade -1` was refused ("Cannot downgrade 20261022_0003: recorded source line endings exist"; 24 targets had recorded facts). The database was dropped after this review. |
| MCP server | Real stdio subprocess `python -m app.mcp.external_adapter` (cwd = worktree, `PYTHONPATH=backend`, `PATCHDIFF_DATABASE_URL` = my DB, `PYTHONIOENCODING` removed). serverInfo `patchdiff-mvp` 0.2.2, protocol `2024-11-05`, 20 tools, `tools/list` 34,401 compact bytes. Requests were sent as literal UTF-8. Up to 8 concurrent server processes were used for the race test. |
| Scratch repo | `…\scratchpad\pr13-friction\repo\` with `core.autocrlf=true` and `.gitattributes` `*.bat -text`. Commits `0a2f8ff` (initial: 10 files, including a CRLF/no-final-newline emoji file, a CRLF-blob `.bat`, a mixed-EOL file and a 6,016-line, 409,016-code-point log) and `3e5ef53` (PatchDIFF edits written back with `format: "original_eol"`; `pytest` 4/4). |
| Evidence | `…\scratchpad\pr13-friction\`: `transcript.jsonl` (420 JSON-RPC records, 377 `tools/call`; bodies over 200 KB clipped to SHA-256 plus a 2 KB head), `tools_list.json`, `state.json`, `state_base.json`, `compat_history.json`, `exports.json`, `pdclient.py`, `make_repo.py` and task scripts `t00_*.py` … `t20_*.py`. The host-decoding probes (`t14b`, `t14c`, `t14d`) use raw `subprocess` pipes on purpose, so their requests are not in the transcript; the scripts reproduce them. |

`…\scratchpad\` = `C:\Users\USER\AppData\Local\Temp\claude\C--Users-USER-Desktop-Frameworks-Patch-DIFF\8e4d82a3-0e72-484d-9c0b-966b150ce1fd\scratchpad\`

Totals against the PR server: 352 `tools/call` requests, 66 rejected, 60 `invalid_argument` (44 of them came from one bug in my own export script, which passed a state object as `target_file_id`), about 29.7 MB up (mostly deliberate size probes and 20 × 1 M-code-point tx/3 rewrites) and 5.1 MB down. A further 25 calls went to the base server.

## 2. Lifecycle

### 2.1 Task outcomes

| # | Task | Tools used | Outcome |
| --- | --- | --- | --- |
| 0 | Record pre-PR history with the base server (10 keyed attempts across tx/1, tx/2, tx/3 and PDCP, including a tx/2 span that already carried `expected_before`) | base server, then `alembic upgrade` | Base behaviour confirmed (`format: "docx"` echoed; no `status` on initialize). The populated `0002 → 0003` upgrade succeeded and history was unchanged. |
| 0b | Compatibility of recorded history under PR code | `replay`, resend of all 10 keyed requests, `get_pdcp_log`, `get_manifest_ledger`, `export_target` | Replay `success`. All 10 resends returned `deduplicated: true` with the original `pdcp_log_id` and no new row. Stored `failure_detail` ("MATCH text was not found." for the old `sequential_match_invalid`) and stored `retryable: false` for the old `span_expected_text_mismatch` were preserved. The old tx/2 request with `expected_before` recovered its recorded `manifest_invalid`; it was not re-evaluated under `0.5.0`. `original_eol` on the old target returned `source_line_endings_unknown`. |
| 1 | Discover, then initialize one target per file | `tools/list`, `initialize_target`×10, `get_target` | All `status: "ok"`. For all 10 files, `source_line_endings.source_sha256` equalled the SHA-256 of the file bytes and `current_hash` equalled the hash of the LF-canonical text. Styles: `crlf` (i18n.md, build.bat), `mixed` (mixed.txt, lf 2 / crlf 1 / cr 1), `lf` for the rest. |
| 2 | Fix the `mean()`/`clamp()` bug | `find_occurrences`, `read_lines(include_line_starts)`, `submit_edits`, `export_target(original_eol)` | Accepted v1. Two edits, the second with `occurrence_index: 2`, produced no false basis-shift warning, because the first edit did not move the occurrences. Scratch tests went from failing to 4/4. |
| 3 | FR-1 rename traps on README copies, then the real rename | `find_occurrences`, `preview`, `submit_edits`, `submit_operations` | (a) Copied indexes `[1,2,3]`: accepted and flagged with two `occurrence_index_basis_shift` warnings, visible in preview before commit. (b) **Correct sequential indexes `[1,1,1]`: also flagged with two warnings (NF-1).** (c) `[1,2,3,5,6,7]`: rejected at `chg_005` with the new "after 4 earlier simulated change(s)" sentence. (d) Six descending tx/2 spans: accepted with no warnings, and preview `after_hash` equalled submission `after_hash`. |
| 4 | Insert a section by line number; UTF-16 offset mistake; grapheme probes | `read_lines`, `read_target`, `submit_operations`, `preview` | The line offset came from `line_starts` in one call, and the insertion with `expected_before`/`expected_after` was accepted under `0.5.0`. A UTF-16 offset (83 instead of 81) was rejected with `span_check: "expected_before"` and `actual_text: " "`; the linked retry was accepted. Grapheme warnings fired for 6 of 6 split probes (flag, both sides of ZWJ, combining mark, Hangul jamo, skin-tone modifier) and for 0 of 3 clean boundaries. |
| 5 | Concurrent writer on `config.yaml` (two server processes) | `find_occurrences`, `submit_edits`, `submit_operations` | Stale submission: `target_version_mismatch`, `retryable: true`. **`current_context` was the unavailable object (`same_as_failure_context`, `text: null`), so my host's rebase-from-`current_context` code crashed (NF-4).** After switching to `diagnostic.failure_context`, attempt 2 (span moved 39 → 55) was accepted with a parent link. B's lost-response resend returned `version: 1`, `current_version: 2`. |
| 6 | Typo recovery and span diagnostics | `submit_edits`, `submit_operations`, `find_occurrences` | Short typo near the top and a typo at offset 432: exact `near_misses[0]` at distance 1, `scan_source: "failing_buffer"`. Typo beyond 65,536 in the 409k log: empty list with `scope_truncated: true` and a `hint`. **Typo at offset 47,646 of the repetitive log: the scan stopped at the cell budget (`scanned_end: 20114`) after about 0.8 s and returned three distance-4 candidates on other log lines (NF-5).** A 95-code-point multi-line typo: `match_too_large`. `sequential_match_invalid` named the consuming change `retitle`. Span mismatch, out-of-bounds, `expected_after` and ambiguity failures beyond offset 192 got `selection: "failure_window"` around the location. |
| 7 | Idempotency and key conflicts | `submit_edits`, `submit_operations`, `submit_pdcp`, `get_pdcp_log` | Dedup returned the same log and `current_version`. Conflicts returned `diagnostic.code: "request_key_conflict"` with exact `differing_fields`: `intent`, `edits[0].rationale` for null vs omitted, `expected_target_version`, and `pdcp_content` for cross-format and PDCP. Keys with whitespace, 129 characters or non-ASCII: `invalid_client_request_id`. A repeated conflict appended a new row. |
| 8 | Preview vs submission, argument errors, wire | `preview`, `submit_*`, deliberate bad arguments | Three pairs (accepted, `match_absent`, no-op) matched on verdict, `after_hash`, warnings, near-miss texts and facts. Unknown or missing arguments (preview `include_correlation_id`, `expected_version`, read `offset`, export without target, save `version`) returned structured JSON with `isError: true`. Responses carry literal UTF-8. |
| 9 | tx/3 CHANGELOG rewrite; oversize; history content budget | `preview`, `submit_replacement`, `submit_edits`, `get_pdcp_log` | Accepted `replace_all`. 1,000,001 code points, 1.2 MB and raw-CRLF 1,020,000 code points were refused with `actual`/`limit`; the CRLF case had `canonical_would_fit: true`. No rows were written and preview diagnostics were identical. A page of three 600 KB rejected rows returned the first whole and the rest with `pdcp_content_omitted: "page_byte_budget"`; `limit: 1` fetched an omitted one. |
| 10 | Legacy PDCP from a Windows host; mixed-EOL edit; SAVE guards | `submit_pdcp`, `submit_operations`, `save` | CRLF-authored `.pdcp` accepted after a self-inflicted retry (my script doubled CRs). An `expected_after` with a raw `\r\n` matched canonical `\n`. SAVE: stale version → `target_version_mismatch`; -1, `true`, `"3"` → `context_invalid`; stale hash → `target_hash_mismatch`. SQL showed no snapshot row for any of these; a matching guard pair saved. |
| 11 | Audit after SAVE | `get_manifest_ledger`, `get_pdcp_log` | Default ledger after SAVE: 0 rows. With `include_previous_cycles` and `limit: 2`, five pages joined to attempts by `pdcp_log_id`, with versions. `rationale` and `transaction_intent` were separated correctly for `calc.py`. |
| 12 | Replay, export all formats, write back, commit | `replay`×14, `export_target`×44 | All replays `success`, `materialized_state_matches: true` (runtimes `0.2.2`, `0.3.0`, `0.4.0`, `0.5.0`). `original_eol` gave CRLF for i18n.md and build.bat, LF elsewhere, and was refused for mixed.txt. `content_sha256` was correct in every case. An unedited CRLF upload had `content_sha256 == source_sha256`. `git diff --stat` was minimal (build.bat 2 lines; an unedited file was byte-identical). The mixed file needed 10 lines of host glue to restore per-line endings from git HEAD. Committed `3e5ef53`. |
| 13 | Probes: wire decoding, framing, surrogates, warnings, race, history cost, migration | mixed | See NF-2, NF-3, NF-6, NF-7 and NF-8. Race: 8 processes at v0 → exactly 1 accepted, 7 `target_version_mismatch`, 1 ledger row, replay success. Lone-surrogate echoes fell back to ASCII escapes without a crash. |

### 2.2 Measurements

| Measure | PR (`de6e7c2`) | Base (`16ce338`) |
| --- | --- | --- |
| Median latency, most reads | 6–13 ms | – |
| Median latency, submissions | 28–31 ms (tx/1, tx/2, PDCP); 169 ms (tx/3, dominated by 1 M-code-point probes) | – |
| `match_absent` on the 409k repetitive log (`submit_edits` / `preview`, median of 3) | 790 ms / 819 ms | 99 ms / 15 ms |
| `match_absent` on 70k varied prose (typo at 50,027) | 137–142 ms, found at distance 1 | – |
| Median rejection response (tx/1, tx/2) | 2,396 bytes (n=22) | 2,171 bytes (n=4) |
| Ledger page of 20 accepted ~1 M-code-point tx/3 rows | 220 ms | 90 ms |
| Attempt page of the same rows | 234 ms | 201 ms |

### 2.3 Discovery from `tools/list` only

Every top-level parameter of all 20 tools has a description. Guard rules, code-point units and the sequential basis are repeated in prose. `x-patchdiff-capabilities` names `0.5.0` for span context, and the export `format` is an enum. From `tools/list` alone I could not work out:

- how to write a legacy `.pdcp` document. `pdcp_content` is described only as "Raw legacy PDCP 0.2.3 text.", with no format or example. This predates the PR and only matters for legacy clients.
- that accepted responses carry `warnings`, what each code means, or that `current_context` can be elided. `tools/list` has no output schema in this protocol version, so these live only in MCP_TOOLS.
- that `patchdiff_get_target` returns the full content, so a cheap version/hash probe is `read_target(length=1)`. This also predates the PR.

## 3. FR-1..FR-20 re-test

Disposition key: **Fixed**, **Partial**, **Not fixed**, **Declined**. "Declined sub-item" means the decision record declined part of the original remedy; I judged each one.

| FR | Original friction (PR #11) | Re-test performed | Verdict |
| --- | --- | --- | --- |
| FR-1 | Copied `occurrence_index` values committed a wrong rename silently | Task 3 (a)–(d), plus PDCP with `# occurrence_index` | **Fixed**: the basis is stated in the tool description, schema and guide; the rejection detail adds the sequential sentence; wrong edits are flagged in preview and submission (also for PDCP). Declined sub-item: `occurrence_basis` selector (reasonable). **New friction NF-1 (high): the warning also fires on correct sequential use, and the docs call it a wrong edit.** |
| FR-2 | Empty-span insertions unverified; UTF-16 and grapheme splits accepted | Task 4 | **Fixed**: the UTF-16 offset was caught by `expected_before`; grapheme warnings were 6/6 correct with 0/3 false alarms on clean boundaries; the code-point note is in the tool descriptions. Declined sub-item: mandatory insertion context (reasonable, for compatibility). |
| FR-3 | Silent EOL normalization; `format` ignored | Tasks 1 and 12 | **Fixed**: facts are recorded with a verifiable `source_sha256`; the enum is honoured; `original_eol` write-back gave minimal git diffs; unknown formats are refused. Declined sub-item: per-line restoration for mixed files (reasonable; refused explicitly with `original_eol_unrecoverable`). See doc mismatch DM-2. |
| FR-4 | `retryable: false` on span failures | Tasks 4, 5, 6 | **Fixed** for `span_*` and `target_version_mismatch`. `target_diverged` was not tested live. |
| FR-5 | Span failures did not show the text at the span | Task 6 (g1–g4) | **Fixed**: `span_check`, `buffer_length`, bounded `actual_text` (64 code points, truncation flag), and the char counts are present. |
| FR-6 | Near misses scanned 256 code points; empty result unexplained | Task 6 (a–d), Task 20 prose | **Fixed** for normal documents: the typo at offset 50,027 was found, and `scan_source`, `scanned_*`, `scope_truncated`, `candidates_truncated` and `hint` are present. On large repetitive files the cell cap limits the scope and adds latency (NF-5). |
| FR-7 | Duplicate windows; misleading hints for consumed matches | Task 6 (a, d, f) | **Fixed**: candidates are distinct locations; `sequential_match_invalid` names `consumed_by_change_id` and omits near misses. |
| FR-8 | Duplicate contexts; prefix-only | Tasks 5, 6, 8 | **Fixed**: `failure_window` around known locations and `same_as_failure_context` elision. Rejections are not smaller (median 2.4 KB vs 2.2 KB) because evidence was added. Compatibility side effect: NF-4. |
| FR-9 | Dedup reported a stale version | Task 5 | **Fixed** (`version: 1`, `current_version: 2`). |
| FR-10 | Key conflict looked like malformed input | Task 7 | **Fixed** (`diagnostic.code`, `differing_components`, exact `differing_fields`, guide rows). Declined sub-item: null/omitted fingerprint normalization (reasonable; `differing_fields` names the path). |
| FR-11 | Audit trail not joinable | Task 11 | **Fixed**. The read cost is measurable (NF-8, low). |
| FR-12 | tx/3 limit framing; unbounded `include_content` pages | Task 9 | **Fixed**: page budget and documentation. Declined sub-items: shared admission cap and bounded stored rejections (reasonable; the append-only contract stores every attempt). |
| FR-13 | `read_lines` mixed coordinate frames | Task 4 | **Fixed** (`next_start` continued correctly in `read_target`; `line_starts` is correct, including empty and final-empty-line cases). |
| FR-14 | Escaped wire, inconsistent envelopes, `TypeError` text | Tasks 8 and 13 | **Fixed** (literal UTF-8; structured unknown/missing arguments; `status: "ok"`; `current_*` on submissions). Shape residuals remain (NF-9, low). **New friction NF-2 (high) and NF-6 (low) come from the encoding change.** |
| FR-15 | Sparse schema descriptions | Discovery | **Fixed** (no undescribed parameter; guard rule in prose). `anyOf`/`allOf` remain, but are mirrored in prose. |
| FR-16 | Drifted examples | Live comparison | **Fixed**: the `match_ambiguous` example, evidence keys, ledger example and guide UUIDs match live output. Leftover: `PDCP_FORMAT.md` still uses `11111111-1111-1111-…` (DM-6). |
| FR-17 | No-op accepted silently | Tasks 8 and 13 | **Fixed**: `no_op_change` and `no_op_transaction` warnings, persisted and recovered by key. Persistence representation issue: NF-3. |
| FR-18 | Missing numbers | Tasks 6 and 9 | **Fixed** (`next_occurrence_index` continued correctly in `find_occurrences`; `actual`, `limit` and `canonical_would_fit` present). |
| FR-19 | Preview weaker than submission | Task 8 | **Fixed** (identical near misses; structured unknown-argument error). |
| FR-20 | SAVE had only a hash guard | Task 10 | **Fixed** (version guard and both-guard checks; no snapshot on any rejection, verified in SQL). |

Summary: **20 fixed, 0 partial, 0 not fixed, 0 wholly declined.** Five sub-items were declined (FR-1, FR-2, FR-3, FR-10, FR-12); each decline is documented in the decision record and I judged each reasonable. Four fixes introduced new friction: FR-1 → NF-1, FR-14 → NF-2/NF-6, FR-8 → NF-4, FR-17 → NF-3.

## 4. Findings

Severity counts: **blocking 0, high 2, medium 3, low 5.** "NF" means new friction introduced by PR #13.

### Blocking

None. I found no data loss or corruption by PatchDIFF itself, no violation of a locked invariant, and no break of recorded history.

- Atomicity held under an 8-process race.
- Exact matching was unchanged.
- The attempt log stayed append-only, including repeated conflicts.
- The ledger stayed accepted-only.
- Replay succeeded for every target and profile.
- All 10 pre-PR keyed requests recovered unchanged.

NF-2 is the borderline case, and §4 explains why I rated it high rather than blocking.

### High

#### NF-1: `occurrence_index_basis_shift` fires on correct sequential indexes, and the docs tell hosts to treat it as a wrong edit.

- **Category:** usability / documentation (new in PR, D1/D11).
- **Reproduction (minimal):**
  - `patchdiff_initialize_target {filename:"cats.txt", content:"cat dog cat dog cat\n", content_type:"text/plain"}`
  - `patchdiff_submit_edits {target_file_id, expected_target_version:0, intent:"Rename the first two cats", edits:[{match:"cat", replace:"lion", occurrence_index:1}, {match:"cat", replace:"lion", occurrence_index:1}]}`

  The response is `status: "accepted"` with `warnings: ["occurrence_index_basis_shift: chg_002 occurrence_index 1 selected the occurrence that was index 2 at transaction start; indexes count the sequential buffer after earlier changes."]` and `warning_details[0]` `{occurrence_index:1, transaction_start_occurrence_index:2}`. The content is `'lion dog lion dog cat\n'`, exactly the intended result.

  The README version (task 3b, three `occurrence_index: 1` edits, "first three mentions") produced two warnings. The result renamed exactly the title, tagline and install line (offsets 2, 11, 99).
- **Why it matters:** the tool description, the schema and the guide all define `occurrence_index` as sequential, and `[1,1]` is the documented-correct way to rename the first two. Yet the guide says "Treat that warning as a wrong edit and fix it with a follow-up proposal" (§3), and the checklist says "treat accepted-edit `warnings` as probable mistakes" (§10). MCP_TOOLS says such a host "most likely edited the wrong occurrences". By construction, the warning fires on every sequential index that differs from its transaction-start index, so every correct multi-edit use of sequential indexes is flagged. A host that follows the guide either "fixes" a correct edit or learns to ignore the warning, which defeats FR-1.
- **Why not blocking:** the committed edit is correct, and the warning text and its `transaction_start_occurrence_index` are accurate. A host that compares `transaction_start_occurrence_index` with its intended original index can tell the two cases apart. The harm needs a further host action.
- **Remedy:** reword the guide, checklist and MCP_TOOLS. The warning means "the sequential index differs from the transaction-start index"; compare `transaction_start_occurrence_index` with the occurrence you meant. It is a wrong edit only if you meant transaction-start indexes. Optionally rename the code or add `"interpretation": "sequential_index_differs_from_transaction_start"`. Add a test pinning the correct-sequential case.

#### NF-2: The literal-UTF-8 wire (FR-14) silently corrupts text for hosts that decode server stdout with a non-UTF-8 locale codec. Such hosts worked with every earlier revision.

- **Category:** compatibility / defect-risk (new in PR, D14).
- **Reproduction (`t14d_mojibake.py`):** a Python host starts the server with `subprocess.Popen(..., text=True)` and no `encoding`, so it uses the Windows locale codec, `cp1252`.
  - `patchdiff_read_target {target_file_id}` on a copy of `settings.json`. The host receives `"greeting": "Bonjour, cafÃ© â˜•"` with no error, because every byte maps in cp1252.
  - The host bumps the version in that text and sends `patchdiff_submit_replacement {target_file_id, expected_target_version:0, intent:"Bump version to 1.3.0", replacement:<that text>}`. The response is `status: "accepted"`, `warnings: []`.
  - The stored line is `'  "greeting": "Bonjour, caf\xc3\xa9 \xe2\u02dc\u2022",'`.
  - The identical host against the base server stores `'  "greeting": "Bonjour, caf\xe9 \u2615",'`, which is correct.
  - With other characters the same host crashes instead: reading `docs/i18n.md` raised `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d` in the reader thread. Against base it worked (`t14c_base_wire.py`).
- **Why it matters:** before this PR, ASCII-escaped output made every ASCII-compatible decoder correct, so these hosts were safe by accident. Now they mis-decode, and the mojibake round-trips into committed content with no warning. The CHANGELOG lists the change under "Changed" but not under "Compatibility and operations". No doc tells hosts to decode responses as UTF-8; the setup guide only says "Hosts must send UTF-8", and there is no opt-out.
- **Why high and not blocking:** RFC 8259 and MCP stdio require UTF-8 JSON, the base docs never promised ASCII output, mainstream SDK hosts (TypeScript and Python MCP SDKs, Node-based hosts) decode UTF-8, and this was the remedy requested in FR-14. If maintainers consider hand-rolled hosts that decode with the locale codec to be supported, this becomes blocking.
- **Remedy:**
  - Add a compatibility note: hosts must decode stdout as strict UTF-8, for example Python `encoding="utf-8", errors="strict"`.
  - Consider an opt-in ASCII wire, for example `PATCHDIFF_WIRE_ASCII=1`, for hosts that cannot.
  - Mention it in `CLAUDE_DESKTOP_SETUP.md` §UTF-8 transport and guide §0.

### Medium

#### NF-3: Accepted rows without warnings now store JSONB `null`, not SQL NULL, contradicting the documented persisted contract. The author's evidence cannot detect this.

- **Category:** persistence / documentation (new in PR, D11).
- **Reproduction:** make any warning-free acceptance, for example task 2's `patchdiff_submit_edits` on `src/calc.py`. Then run `select diagnostic_json is null, jsonb_typeof(diagnostic_json) from append_only_pdcp_logs where status='accepted' group by 1,2`. In my DB: 37 PR-written rows were `false | null` (JSON literal), 6 were warning objects, and only the 7 base-written rows were SQL NULL. Attribution was checked by target: `legacy.md` and `moji-base.json` were written by the base server.
- **Cause:** `pdcp_service.py:1102` passes `diagnostic_json=envelope if accepted.warnings else None` explicitly. The column is `JSONB` with `none_as_null=False` (checked in-process), so SQLAlchemy writes JSON `null`. Base code never set the column for accepted rows, so it stayed SQL NULL.
- **Contract contradicted:**
  - `DATA_MODEL.md:10` and `:156`: "Accepted rows keep `diagnostic_json = NULL` unless…"
  - MCP_TOOLS: "other accepted rows keep `diagnostic_json = NULL`"
  - Decision D11: "keep `diagnostic_json = NULL`, as today"
  - The code comment says "as before".
- **Why tests missed it:** the author's harness check "FR-17 accepted row without warnings keeps diagnostic_json NULL" uses `coalesce(diagnostic_json::text,'null')` followed by `json.loads`, and the integration test uses ORM `.diagnostic_json is None`. Both map JSON `null` and SQL NULL to Python `None`.
- **Impact:** invisible over MCP (`diagnostic: null` either way) and to service code. It splits SQL consumers: `WHERE diagnostic_json IS NULL` now misses every new plain acceptance, and history now has two representations.
- **Remedy:** omit the column when there are no warnings, or write `sqlalchemy.null()`. Add a SQL-level assertion (`diagnostic_json IS NULL` and `jsonb_typeof IS NULL`). The 37 rows written in this database are moot because it was dropped. Any database that already ran this head would keep JSON `null` rows; document that or normalize them in a migration.

#### NF-4: The FR-8 elision makes `current_context` unavailable in the most common rejection, which breaks hosts that rebase from it.

- **Category:** compatibility (new in PR, D8; a documented exception).
- **Reproduction (task 5):**
  - Client B accepts `patchdiff_submit_edits {match:"port: 8080", …}` on `config.yaml`, which moves it to v1.
  - Client A sends `patchdiff_submit_operations {target_file_id, expected_target_version:0, intent:"Double workers", operations:[{op:"span", start:39, end:49, expected_text:"workers: 4", replace:"workers: 8", expected_after:"\n"}]}`.
  - The response is `failure_reason: "target_version_mismatch"`, `current_context: {available:false, unavailable_reason:"same_as_failure_context", text:null, …}`.
  - My host, written to the base contract and to the PR #11 review's recovery pattern ("current_context held the whole file, so recovery was possible without a re-read"), raised `AttributeError: 'NoneType' object has no attribute 'index'`.
- **Impact:** the data is still in `diagnostic.failure_context`, which is identical key for key. Under the base contract, `available: false` occurred only for an invalid ID, an unknown target or unlocked local state, none of which apply to a known target. Hosts that treat unavailable as "re-read" lose the saved round trip. Hosts that index `text` crash. No wrong edit results.
- **Remedy:** list it under CHANGELOG "Compatibility". Consider returning the elided object with `available: true` and a `same_as: "diagnostic.failure_context"` marker but `text` omitted, or keep a full copy for one release.

#### NF-5: On large repetitive files the wider near-miss scan costs about 0.8 s per `match_absent` (submission and preview), stops near 20–29k code points, and can rank only wrong locations.

- **Category:** performance / usability (new in PR, D6).
- **Reproduction:** `patchdiff_submit_edits {target_file_id:<docs/ops-log.md, 409,016 code points>, expected_target_version:0, intent:"Fix one log line", edits:[{match:"entry 00700: service calcly processd batch 21", replace:…}]}`.
  - Median 790 ms (base: 99 ms).
  - `patchdiff_preview` with the same proposal: 819 ms (base: 15 ms).
  - `near_misses` returned `status: "computed"`, `comparison_cells: 999730`, `scanned_end: 20114`, `scope_truncated: true` and three distance-4 candidates at 20, 87 and 623 (entries 00001, 00002 and 00010). The real line is at offset 47,646, inside the documented "first 65,536 code points".
  - On 70k code points of varied prose, the same kind of typo at 50,027 was found in about 140 ms. The bag-distance pruning works there; it is ineffective on log, CSV or generated text where every window has similar character counts.
- **Impact:** every miss on such files adds about 0.7 s of single-threaded server time. Preview loses its "cheap" property. The docs promise "up to the first 65,536 code points", but the effective scope is unpredictable, and the candidates look plausible. The ranking is honest (`scope_truncated`, `scanned_end`) and base gave similarly wrong candidates.
- **Remedy:**
  - Lower the cell budget for preview.
  - Prefer a cheap exact-substring pre-filter, for example on the longest token of the needle, before the dynamic program.
  - Document that repetitive text shortens the effective scope.
  - Consider returning `omission_reason` instead of candidates when every candidate is at the threshold distance.

### Low

#### NF-6: Raw U+2028, U+2029 and U+0085 now reach the wire, which breaks hosts that frame with `str.splitlines()`.

- **Reproduction (`t14c_base_wire.py`):** a target with content `"a\u2028b\x85c\n"`, then `patchdiff_read_target`. Splitting stdout on `\n` gives 2 frames. `str.splitlines()` gives 4 frames and `JSONDecodeError`. Base gave 2 frames either way, because these characters were escaped.
- **Remedy:** escape U+2028, U+2029 and U+0085 even with `ensure_ascii=False`, as many JSON-over-lines servers do, or document LF-only framing.

#### NF-7: `grapheme_boundary_split` warns on deliberate modifier and mark edits.

- **Reproduction:** `patchdiff_preview` (tx/2) span `[m, m+1)` with `expected_text:"\U0001F3FD"` and `replace:"\U0001F3FF"` (a skin-tone change) returns `grapheme_boundary_split:start`. This is advisory and documented as conservative, but it is noise for intentional edits of combining marks or modifiers.
- **Remedy:** skip the check when the replaced text and its replacement are both extend-class characters.

#### NF-8 (confirms the author's MCP-001): ledger and attempt pages decode full stored records.

- **Measurement:** 20 × ~1 M-code-point tx/3 rows. `get_manifest_ledger(limit 50)` took 220 ms (base 90 ms); `get_pdcp_log(limit 50)` took 234 ms (base 201 ms). This scales linearly to a 200-row page. Responses stay small.

#### NF-9: Response-shape residuals after FR-14.

- Preview uses `change_facts`, top-level `validation_stage` and `before_version`, while submission uses `evidence.changes` and `version`.
- Read, initialize, get and export use `version` only, not `current_version`.
- The export payload has no `target_file_id`.
- Unknown or missing argument errors are `isError: true`, while every other `invalid_argument` is `isError: false`.
- A SAVE `context_invalid` returns `version: null` and `current_hash: null`, so the host has no current state from it.
- All of this is documented; it is per-tool glue, not a defect.

#### NF-10 (pre-existing): `tools/list` cannot teach the legacy `.pdcp` format.

- Only legacy clients are affected.

## 5. Regressions

Behaviour that worked before PR #13 and does not now:

| # | Behaviour | Status |
| --- | --- | --- |
| R-1 | Hosts decoding stdout with a locale codec got correct text | Broken: silent mojibake or crash (NF-2) |
| R-2 | Hosts framing with `str.splitlines()` | Broken for U+2028, U+2029 or U+0085 in content (NF-6) |
| R-3 | `current_context.text` available on known-target rejections | Now `null` when identical to `failure_context` (NF-4; documented exception) |
| R-4 | `export_target` with any `format` string (for example `"docx"`, `"markdown"`, `""`) or `null` returned LF content | Now `invalid_argument` `unsupported_export_format` with `allowed_formats`. Intentional, documented in D3, and requested by FR-3. A host passing a descriptive format must change. |
| R-5 | `match_absent` latency on large repetitive targets (submission and preview) | About 8× slower for submission and 55× for preview (NF-5) |
| R-6 | Accepted rows without diagnostics are SQL NULL | Now JSONB `null` for new rows (NF-3) |

Verified unchanged:

- Recorded history: 10/10 keyed recoveries returned identical log IDs, stored detail and stored `retryable`; replay success across `0.2.2`, `0.3.0` and `0.4.0`.
- Fingerprints: unchanged, so cross-version dedup works.
- tx/2 without context keys stays `0.3.0`.
- `failure_detail` with `prior_changes == 0` (`"MATCH text appears multiple times without disambiguation."`) is unchanged.
- Default export output is unchanged, apart from added keys.
- Deprecated wrappers (`get_regeneration_context`, `build_regeneration_prompt`, `request_regeneration`) and `build_prompt_context` work on new rows.
- Migration: populated `0002 → 0003` upgrade, and downgrade refusal with recorded rows.

## 6. Documentation mismatches

| # | Location | Claim | Observed |
| --- | --- | --- | --- |
| DM-1 | `HOST_INTEGRATION_GUIDE.md:9` | "the model sees `🌍` and `中`, not `🌍` escapes" | The escape example was replaced by a literal emoji (bytes `F0 9F 8C 8D`), so the sentence contradicts itself. It should read `\ud83c\udf0d`. |
| DM-2 | `HOST_INTEGRATION_GUIDE.md:234` | "`core.autocrlf=true` … writing LF back produces a whole-file diff even when only one line changed" | It is only true for files whose blob holds CRLF (`build.bat`: 8-line diff for 1 change). For LF-normalized blobs, the normal `autocrlf=true` case, a naive LF write gave a 1-line diff (`docs/i18n.md`). The remedy (`original_eol`) is still correct. |
| DM-3 | `DATA_MODEL.md:10`, `:156`; MCP_TOOLS "Accepted responses…"; decision D11; author review §3 "NULL for a plain row" | Accepted rows without warnings keep `diagnostic_json = NULL` | They store JSONB `null` (NF-3). |
| DM-4 | Guide §3 ("Treat that warning as a wrong edit"), §10 checklist; MCP_TOOLS `occurrence_index_basis_shift` | The warning implies a wrong edit | It also fires on correct sequential use (NF-1). |
| DM-5 | Guide §3 Diagnostics; MCP_TOOLS near misses | "scanned over up to the first 65,536 code points" | It is an upper bound only. Repetitive text stopped at 20,114–28,764 code points (NF-5). The cell cap is documented, but hosts cannot predict the scope. |
| DM-6 | `PDCP_FORMAT.md:25`, `:83` | — | Still uses `11111111-1111-1111-1111-111111111111`, the form FR-16 asked to replace. |
| DM-7 | `CHANGELOG.md` "Compatibility and operations" | Lists migration and identity rules | It omits the host-visible wire requirement (NF-2) and the `current_context` elision effect (NF-4). Both appear only under "Changed". |

## 7. What worked well

- The FR fixes are real and observable on the wire. In particular:
  - `expected_before`/`expected_after` caught the UTF-16 offset mistake, with the actual adjacent text in the rejection.
  - `line_starts` removed the extra read.
  - `original_eol` produced byte-exact round trips (`content_sha256 == source_sha256`) and minimal git diffs.
  - `differing_fields` named the exact null-vs-omitted path.
  - Consumed-match evidence named the consuming change.
  - SAVE guards wrote nothing on rejection.
- Compatibility discipline held where it matters most:
  - Recorded history recovers byte for byte.
  - `0.3.0` stays `0.3.0` when no context keys are present.
  - Context-guarded rows record `0.5.0` even when rejected (verified in SQL: 5 accepted, 7 rejected).
  - Replay ignores warnings.
- Invariants held under stress: the 8-way race committed exactly one writer, no near-miss data or `current_context` was persisted (SQL), and the history content budget worked without breaking paging.
- Preview and submission agreed on verdict, `after_hash`, warnings, near misses and facts in every compared pair.

## 8. What I could not test

- `target_diverged` retryability: it cannot be triggered through MCP without corrupting storage. Source shows it in `RETRYABLE_FAILURE_REASONS`.
- A real external MCP host (Claude Desktop, Gemini CLI, or a JavaScript/TypeScript client with native UTF-16 strings). The UTF-16 offset error was simulated in Python.
- Caller-owned transaction paths (`near_misses` `caller_transaction` omission), which are in-process only.
- The full pytest suite and CI. Neither was run; this is a friction review. The author reports 1,220 passed.
- Production-scale load, memory use of 200-row ledger pages over 1 MB records, and Linux/macOS hosts.

## 9. Verdict

No finding shows PatchDIFF violating a locked invariant, losing data on its own, or breaking recorded history, and all 20 FR items are fixed.

Two high findings should be addressed before hosts adopt this release:

- **NF-1** is a documentation and semantics problem: the FR-1 warning, as documented, mislabels correct sequential edits as wrong edits.
- **NF-2** is a host-compatibility hazard: literal-UTF-8 output silently corrupts text for hosts that decode with a locale codec. The CHANGELOG's compatibility section does not flag it.

NF-3 is a persisted-representation bug that contradicts DATA_MODEL and the decision record, and it slipped past the author's SQL evidence. It is cheap to fix now and messier after rows exist in real databases.

I recommend fixing NF-1's wording, NF-2's compatibility note (and optionally an ASCII opt-in) and NF-3 before merge. They are not merge-blocking under the stated criteria.

Merge-blocking findings: no
