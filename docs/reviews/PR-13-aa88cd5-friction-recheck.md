# PR #13 friction recheck at `aa88cd5`

## 1. Metadata

| Item | Value |
| --- | --- |
| Repository / PR | `paragon-ux/Patch-DIFF` PR #13 |
| Head under test | `aa88cd56a8d627decd97a6d8b40f25948bb16fcf` (worktree `pd-fr-followup`, branch `fix/pr11-friction-followup`). The code fix is `ac842bb`; `aa88cd5` only adds review evidence. |
| Previous friction review | [PR-13-de6e7c2-friction-review.md](PR-13-de6e7c2-friction-review.md) (NF-1..NF-10, DM-1..DM-7) |
| Fix record | [friction-followup-decision.md](../usability/friction-followup-decision.md), section "Amendments after the PR #13 friction re-test", and the author's [delta review](PR-13-ac842bb-delta-review.md). Both were read; neither was relied on. |
| Comparison base | `16ce338` (`main`), extracted read-only with `git archive 16ce338 backend` and run from the scratch directory with the same venv |
| Date | 2026-10-22 |
| Review type | Independent friction recheck as an agentic host. It is not a PR Review Standard category review. |
| Runtime | Windows 11 Pro, Python 3.11.9 (worktree `.venv`), locale encoding `cp1252` |
| Database | `patchdiff_pr13_recheck` on Docker `patchdiff-postgres` (postgres:16.3-alpine). Sequence: created, upgraded to `20261020_0002`, given base-server history, upgraded populated to `20261022_0003`. At the end `downgrade -1` was refused ("Cannot downgrade 20261022_0003: recorded source line endings exist"). The database was dropped after this recheck. |
| MCP server | Real stdio subprocess `python -m app.mcp.external_adapter` (cwd = worktree, `PYTHONPATH=backend`, `PYTHONIOENCODING` removed), up to 8 concurrent processes |
| Scratch | `…\scratchpad\pr13-recheck\`: `pdclient.py`, task scripts `t00`–`t21` (copied from the previous review and pointed at the new database), `transcript.jsonl` (421 JSON-RPC records; 357 `tools/call` to the PR server, 25 to the base server), `nm_reference.json` and `state*.json`. The scratch repo `repo\` (`core.autocrlf=true`) has commits `11e582f` (initial) and `49051aa` (PatchDIFF edits written back with `original_eol`; `pytest` 4/4). |

`…\scratchpad\` = `C:\Users\USER\AppData\Local\Temp\claude\C--Users-USER-Desktop-Frameworks-Patch-DIFF\8e4d82a3-0e72-484d-9c0b-966b150ce1fd\scratchpad\`

## 2. NF re-test

| NF | Finding at `de6e7c2` | Claimed change | Recheck evidence | Verdict |
| --- | --- | --- | --- | --- |
| NF-1 (high) | `occurrence_index_basis_shift` fires on correct sequential indexes; docs said "treat as a wrong edit" | Guidance only; runtime unchanged | Runtime unchanged, as intended: the minimal case `cat dog cat dog cat` with two `occurrence_index: 1` edits is accepted as `lion dog lion dog cat`, with one warning `(occurrence_index 1, transaction_start_occurrence_index 2)`. Guide §3 now says the warning "reports the basis difference; it cannot know which basis you meant" and tells hosts to compare `transaction_start_occurrence_index`. The §10 checklist and MCP_TOOLS were reworded the same way. Residual: guide §1 still says warnings "flag accepted edits that are well formed but probably not what you meant" (RD-1). | **Fixed** (guidance), with one low residual sentence |
| NF-2 (high) | Literal JSON-RPC lines silently corrupted text for cp1252-decoding hosts | JSON-RPC lines ASCII-escaped again; tool text inside stays literal | `t14d_mojibake.py`: the cp1252 host's tx/3 rewrite now stores `"Bonjour, caf\xe9 \u2615"`, identical to base (previously `caf\xc3\xa9 \xe2\u02dc\u2022`). `t14c`: the cp1252 host reading `docs/i18n.md` no longer crashes. All 357 PR-server response lines contain 0 non-ASCII bytes. `content[0].text` still has a literal `🌍` and no `\ud83c` (FR-14 kept). The lone-surrogate echo stays safe. | **Fixed** |
| NF-3 (medium) | Warning-free accepted rows stored JSONB `null` | Column left unset | After the whole lifecycle: accepted rows are 43 SQL NULL and 7 warning objects; `jsonb_typeof(diagnostic_json)='null'` matches 0 rows anywhere. SQL NULL holds for every runtime (`0.2.2`, `0.3.0`, `0.4.0`, `0.5.0`). Warned rows still store `{warnings, warning_count, warnings_truncated}`, and keyed recovery returns them. | **Fixed** |
| NF-4 (medium) | Elided `current_context` breaks hosts that read `.text` | Kept by D8; CHANGELOG lists it | Behaviour unchanged (task 5: `same_as_failure_context`, `text: null`; the rebase works from `diagnostic.failure_context`). The CHANGELOG "Compatibility and operations" section now says hosts must check `available` before reading `text`. | **Kept by decision** (reasonable and documented) |
| NF-5 (medium) | About 0.8 s per `match_absent` on repetitive large files; reach about 20k code points; wrong-line candidates | Row-abandon bound (claimed exact); latency documented; rest deferred | **Exactness:** an independent unpruned banded reference (`t21_nm_reference.py`) equals the server ranking, including `candidates_truncated`, in 5 of 5 cases (2 repetitive, 3 prose). **Reach:** prose is scanned to the full buffer (`scanned_end` 65,500/65,485) with fewer cells (2,727 vs 4,890). On the repetitive log, reach rose from 20,114 to 45,404–45,608. **Latency:** on the repetitive log it is unchanged (median 979 ms submit and 939 ms preview, vs 113/20 ms on base); prose takes 98–145 ms. The typo at 47,646 is still not reached: the uncapped reference ranks it first at distance 1, while the server returns three distance-3 candidates on other lines with `scope_truncated: true`. MCP_TOOLS now documents the cap, the CPU cost and `scanned_end`. | **Partially fixed** (exact and better reach; latency and repetitive reach deferred, as stated) |
| NF-6 (low) | U+2028/U+2029/U+0085 broke `str.splitlines()` framing | Same as NF-2 | A target containing `a\u2028b\x85c` read through `read_target` gives 2 frames with `splitlines()` (previously 4 plus `JSONDecodeError`), identical to base. | **Fixed** |
| NF-7 (low) | `grapheme_boundary_split` warns on deliberate modifier/mark edits | Guidance only | Runtime unchanged: the skin-tone swap still warns `grapheme_boundary_split:start`. MCP_TOOLS now says "a deliberate edit of a modifier or combining mark triggers it too". The same §1 residual applies (RD-1). | **Fixed** (guidance) |
| NF-8 (low) | Ledger and attempt pages decode full records | Deferred | Unchanged: 233 ms ledger and 251 ms attempts for 20 × 1M records, vs 89/212 ms on base | **Deferred** (as stated) |
| NF-9 (low) | Response-shape residuals | Not addressed | Unchanged | **Not addressed** (as stated) |
| NF-10 (low, pre-existing) | `tools/list` cannot teach `.pdcp` | Not addressed | Unchanged | **Not addressed** (as stated) |

Documentation mismatches reported at `de6e7c2`:

| DM | Recheck | Verdict |
| --- | --- | --- |
| DM-1 guide §0 escape example | The line now ends "not `\ud83c\udf0d` escapes" (byte-checked) and describes the ASCII envelope accurately | Fixed |
| DM-2 guide §8 `autocrlf` | The new text says LF-stored files show only edited lines and CRLF-stored (`-text`) files show every line. Matches the re-run: naive LF write gives `i18n.md` a 1-line diff and `build.bat` an 8-line diff. | Fixed |
| DM-3 accepted `diagnostic_json` NULL | The code now matches the docs (NF-3) | Fixed |
| DM-4 warning framing | §3, §10 and MCP_TOOLS fixed; §1 residual (RD-1) | Fixed with residual |
| DM-5 near-miss reach | MCP_TOOLS now documents the cap's effect and `scanned_end` | Fixed |
| DM-6 PDCP_FORMAT UUIDs | Both examples now use `11111111-1111-4111-8111-111111111111`; no `1111-1111-1111-1111` left in active docs | Fixed |
| DM-7 CHANGELOG compatibility | A compatibility bullet now lists the `current_context` elision, export-format refusal and structured argument errors; "Changed" describes the ASCII envelope | Fixed |

## 3. Regression pass over the full lifecycle

Every task from the previous review was re-run on a fresh repo and database against `aa88cd5`. Outcomes were identical to `de6e7c2` except where a fix intended a change:

- **Formats.** All four submission formats were used: tx/1 in tasks 2, 3, 7 and 8; tx/2 with and without span context (`0.5.0`/`0.3.0`) in tasks 3, 4, 5 and 10; tx/3 including oversize probes in task 9; legacy PDCP including a CRLF-authored `.pdcp` and a key conflict in tasks 7 and 10.
- **Preview.** Preview/submit parity held on verdict, `after_hash`, warnings, near misses and facts.
- **Keys and guards.** Keyed dedup and conflicts returned the same `differing_fields`. SAVE with `expected_target_version`: stale, invalid, stale-hash and both-correct cases behaved as before, and no snapshot was written for any rejection.
- **History.** Audit paging and joins after SAVE, and the `include_content` page budget, were unchanged.
- **Replay.** All 14 targets replayed with `success` and `materialized_state_matches: true`.
- **Export and write-back.** All four export formats behaved as before (`original_eol` CRLF/LF/refused for mixed; `content_sha256` correct). `original_eol` write-back gave a minimal `git diff` (8 files, +24/−14, including 10 lines of host glue for the mixed file), and the commit passed `pytest` 4/4.
- **Atomicity.** 8-process race: 1 accepted, 7 `target_version_mismatch`, 1 ledger row, replay success.
- **Base-era history (`t00` + `t17`).** 10 keyed requests written by the base server recovered with `deduplicated: true` and the same `pdcp_log_id`. Stored `failure_detail` and `retryable` were kept. Replay succeeded, and `original_eol` returned `source_line_endings_unknown`.
- **Persisted data.** No response-only data (`near_misses`, `current_context`) was persisted (SQL).

No regression was found.

## 4. New findings

Severity counts: **blocking 0, high 0, medium 0, low 2.**

### Low

#### RD-1: Guide §1 still frames every warning as "probably not what you meant".

- **Location:** `docs/HOST_INTEGRATION_GUIDE.md:25`: "Read `warnings` on every acceptance: they flag accepted edits that are well formed but probably not what you meant."
- **Problem:** §3 (amended) says `occurrence_index_basis_shift` "cannot know which basis you meant", and MCP_TOOLS says a deliberate modifier edit also triggers `grapheme_boundary_split`. The §1 sentence keeps the old framing that NF-1/NF-7 asked to drop. It was added in this PR (`d121d55`/`0420dac`) and missed by the amendment.
- **Remedy:** for example, "they report facts about well-formed edits that are often, but not always, mistakes; check each against what you meant."

#### RD-2: Two summary documents still say tool results are "literal UTF-8" without the envelope distinction.

- **Location:** `docs/MODERNIZATION_CHANGE_DOC.md:38` ("Tool results are literal UTF-8") and `docs/CODEX_BUILD_PLAN.md:56` ("literal UTF-8 tool results").
- **Problem:** both are true of `content[0].text`, but a reader could take them to describe the wire, which is now pure ASCII. MCP_TOOLS, the guide, CHANGELOG, the skills and TEST_MATRIX state it precisely.
- **Remedy:** a precision fix only: "literal tool-result text inside an ASCII-escaped JSON-RPC line".

## 5. Not tested

- The full pytest suite, `offline_eval.py` and CI were not run; this is a friction recheck. The author's delta review reports them.
- No real external MCP host session was run, and UTF-16 offsets were simulated.
- `target_diverged` retryability and caller-owned transaction paths were not tested, as before.
- The NF-5 exactness check is empirical: 5 cases against an independent reference. The row-minimum argument is also sound by inspection, since out-of-band cells have true distance above the threshold and capped in-band values are exact up to it. It was not formally proven.

## 6. Verdict

NF-2, NF-3 and NF-6 are fixed with live and SQL evidence. NF-1 and NF-7 are fixed as guidance, with one residual sentence (RD-1). NF-4 is kept by a reasonable, now-documented decision. NF-5 is partially fixed as stated: rankings are exact and reach improved, but latency and reach on repetitive text are deferred and documented. NF-8, NF-9 and NF-10 are deferred or not addressed, as stated. All seven documentation mismatches are corrected.

The regression pass, including base-era history compatibility, found nothing broken. The two new findings are low documentation nits.

Merge-blocking findings: no
