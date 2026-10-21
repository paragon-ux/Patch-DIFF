# Gemini workflow reproduction — 2026-10-21

All W1–W12 workflows completed through Codex’s native PatchDIFF MCP tools, using the recovered Gemini fixture files. Their intended final contents were independently confirmed in PostgreSQL. A supplemental exact 40-line rewrite passed too. This is an informed reproduction of the reported behavior, not a blinded usability study or a fresh PR approval.

The strongest finding is a Windows input-decoding defect: without the UTF-8 environment override, a valid raw UTF-8 star was accepted and stored as mojibake. The claimed UnicodeEncodeError crash did not reproduce. G03’s unhandled-exception claim and G07’s missing-search-metadata claim were contradicted by native responses.

## Environment and evidence

- Source: b5caa40bd41848420c4323d22ab648847cdc6745; the Gemini playground checkout’s tracked tree remained unchanged.
- Host: Codex desktop on Windows; Python 3.11.9; PostgreSQL 16.3; READ COMMITTED.
- Registered command: C:\Users\USER\Desktop\Frameworks\Antigravity-playground\patch-diff\Patch-DIFF\.venv\Scripts\python.exe -m app.mcp.external_adapter.
- PYTHONPATH: C:\Users\USER\Desktop\Frameworks\Antigravity-playground\patch-diff\Patch-DIFF\backend.
- Native-workflow configuration: PYTHONIOENCODING=utf-8; dedicated database patchdiff_codex_reproduction_20261021 on 127.0.0.1:5432.
- Installation preflight discovered 16 tools; the fresh database passed upgrade → downgrade one migration → upgrade.
- Native evidence: [native-events-final.json](native-events-final.json), containing all 80 captured calls, arguments, returned envelopes, timestamps, and byte counts. Of these, 43 are W1–W12 calls, 3 are W12B calls, and 34 are setup, targeted claim probes, or final verification.
- Other evidence: [scripted steps](scripted-steps.json), [transport results with raw stdin/stdout bytes](transport-results.json), [independent SQL/YAML verification](independent-verification.json), [installation preflight](installation-preflight.json), and [machine-readable metrics](workflow-metrics.json).
- Diagnostic scripts: [transport_probe.py](transport_probe.py), [verify_results.py](verify_results.py). These do not substitute for the native W1–W12 calls.

## Method and limits

The recovered fixture files were uploaded through native initialization calls with their original CRLF characters. Their raw SHA-256 hashes and original contents are preserved in the native evidence. Canonical target content is LF-normalized. T1 has 59 lines; T2 290 lines; T3 13 lines; T4 5,204 lines and 369,270 bytes; T5 is hello plus CRLF.

Planning used the exposed tool descriptions/schemas and the Host Integration Guide. No new backend source was opened until all W1–W12 tasks and W12B were complete. This agent had already inspected claims and source in earlier turns, so cognitive friction and hesitation costs cannot be interpreted as an independent first-use trial. The guide was read before task execution; there were no additional stuck-workflow documentation lookups.

W6 interference and W7 response loss used separate real stdio subprocesses, as allowed by Gemini’s workflow. W7 discarded the response before exposing its contents to this agent; native recovery reused the original proposal and key. A subsequent SQL check found exactly one attempt row and one ledger row before W8 began. Later SQL verified W8’s parent ID and attempt number.

Transport controls were separate subprocess experiments, with and without the override. They were followed by native exports and an independent SQL check of the stored wrong text. They are not labeled native host transport tests without the override.

The 834-test baseline and the earlier 28-step harness were not rerun in this task. No Antigravity process was killed or reconfigured. No conclusion here closes a historical PR finding, supplies a fix SHA, or authorizes a merge.

## Workflow results

| Workflow | Verified result |
| --- | --- |
| W1 | Only database timeout 30→60; server/cache remain 30. Search→submit→read. |
| W2 | Fifteen DataPulse occurrences outside fences renamed to TelemetryFlow; two code-fence occurrences preserved. Descending occurrence indexes worked in one transaction. |
| W3 | Overview heading renamed, a paragraph inserted under the new heading, and TOC updated in one three-edit transaction. |
| W4 | Emoji status and CJK text edited; accented text and other multilingual text preserved exactly. Override enabled. |
| W5 | Threshold near line 4000 changed 99.95→99.99 from search results alone; search supplied the hash guard. No whole-file native read. |
| W6 | Stale version rejected; fresh read and linked retry accepted. Concurrent version 1.0.4→1.0.5 survived; workers became 8. |
| W7 | Lost-response recovery returned deduplicated:true at version 1; one attempt and one ledger row confirmed independently. |
| W8 | Deliberate trailing-space mismatch rejected as match_absent; corrected linked retry accepted at version 2. |
| W9 | History tools identified two accepted T2 transactions, 18 accepted change entries, and zero failed T2 attempts at that point. Textual changes came from include_content:true. |
| W10 | SAVE rotated the cycle; replay and all four materialized checks passed; export equaled the intended complete document. |
| W11 | Legacy seven-field manifest submission changed database timeout 60→90; exact complete T1 content verified. |
| W12 | Complete original Benchmarks section replaced; exact complete T2 export verified. The recovered section has 22 lines/843 characters, not 40 lines. |
| W12B | A separate exactly 40-line section (2,684 characters) was replaced, preserving surrounding text. |

Final independent SQL equality checks passed for all five original targets: T1 version 4, T2 version 3, T3 version 1, T4 version 1, T5 version 2. Final native replay passed all four materialized checks for each target.

### Measured costs

Bytes are exact UTF-8 lengths of compact JSON arguments and the returned connector result envelopes at the exposed tool boundary. They are not a packet capture of Codex’s serialized MCP wire frames. Time columns are elapsed first-call-start to final-call-end / sum of tool-call durations, in seconds. Elapsed time includes agent deliberation and intervening work; it is not a transport latency benchmark.

| Workflow | Native calls by tool | Reads/searches before first submit | Rejections | Recovery calls through acceptance | Argument/result JSON bytes | Elapsed/call time s |
| --- | --- | --- | --- | --- | --- | --- |
| W1 | 3 (find_occurrences×1, submit_edits×1, read_target×1) | 1 | 0 | 0 | 434 / 3896 | 19.90 / 7.43 |
| W2 | 5 (find_occurrences×3, read_target×1, submit_edits×1) | 2 | 0 | 0 | 1642 / 19369 | 24.59 / 10.59 |
| W3 | 3 (read_target×2, submit_edits×1) | 1 | 0 | 0 | 711 / 4373 | 34.18 / 14.50 |
| W4 | 3 (read_target×2, submit_edits×1) | 1 | 0 | 0 | 657 / 4006 | 15.09 / 7.07 |
| W5 | 3 (find_occurrences×2, submit_edits×1) | 1 | 0 | 0 | 682 / 2438 | 27.78 / 8.41 |
| W6 | 5 (read_target×3, submit_edits×2) | 1 | 1 | 2 | 825 / 6605 | 49.56 / 12.02 |
| W7 | 2 (submit_edits×1, read_target×1) | 0 | 0 | 1 | 301 / 1370 | 4.68 / 4.66 |
| W8 | 3 (submit_edits×2, read_target×1) | 0 | 1 | 1 | 610 / 2302 | 7.65 / 7.62 |
| W9 | 5 (get_manifest_ledger×4, get_pdcp_log×1) | — | 0 | 0 | 420 / 17210 | 24.99 / 12.31 |
| W10 | 3 (save×1, replay×1, export_target×1) | — | 0 | 0 | 262 / 22618 | 9.12 / 9.09 |
| W11 | 3 (find_occurrences×1, submit_pdcp×1, read_target×1) | 1 | 0 | 0 | 770 / 3155 | 10.04 / 10.01 |
| W12 | 5 (find_occurrences×1, read_target×2, submit_edits×1, export_target×1) | 3 | 0 | 0 | 1788 / 26214 | 50.82 / 14.17 |
| W12B | 3 (read_target×1, submit_edits×1, export_target×1) | 1 | 0 | 0 | 3451 / 5062 | 7.72 / 7.68 |

W6 additionally has one scripted submission; W7 additionally has one scripted submission with its response discarded. They are recorded separately, rather than hidden in native-call counts. Recovery counts exclude the initial rejection and include the accepting retry. W7 counts its native cached-response recovery as one recovery call. A deliberate G03 extra-argument probe is separate from W3’s ordinary calls.

W12 incurred one extra read because this agent initially entered offset 2440 after search returned 2431. The read began nine characters into the heading; a corrective read at 2431 supplied the complete section. This was a host offset-entry mistake, not a server read failure.

## G01–G08 dispositions based on execution

| ID | Result | Evidence and necessary next change |
| --- | --- | --- |
| G01 | Inconclusive for Antigravity | Codex needed its tool catalog refreshed after registration. The Antigravity cached-process/0xffffffff claim requires an Antigravity-host run. Keep host-specific restart guidance; do not change PatchDIFF runtime based on an untested host lifecycle assumption. |
| G02 / DEFECT-001 | Revise; accept input-decoding defect as the priority blocker | On default cp1252 stdin, raw UTF-8 star bytes were accepted and stored as ðŸŒŸ. All processes exited 0; stdout remained ASCII, so the reported stdout crash did not reproduce. Make stdio decoding explicitly UTF-8 and add raw-byte Windows controls. Preserve domain rejection/audit behavior for escaped invalid strings. |
| G03 | Reject the unhandled-exception/P1 claim | Native extra version argument returned isError:true with an explicit unexpected-keyword message. Subsequent submissions and reads worked; there was no native server crash or observed -32603. Whether invalid argument shape should instead use -32602 is a separate API-contract decision; do not treat it as the reproduced crash fix. |
| G04 | Revise; traversal works, proposed cursor arithmetic is wrong | W9 returned pages [15..19], [10..14], [5..9], [2..4], with 18 distinct rows. Use before_sequence=next_sequence. A probe using min−1=14 skipped eligible row 14 and returned [9..13]. Existing native tool descriptions and the guide already explain backward traversal and ascending display within each ledger page. No forward-cursor feature is justified by this run alone. |
| G05 | Accept narrower history-read friction | Ledger lacks literal match/replace text, so W9 needed attempt-log content. It does retain intent, and an explicit rationale/risk control returned intent='Host rationale retained for audit.' and risk='low'. Four other prose fields were null. Existing guide documents raw-record lookup. Any convenience excerpt should be a bounded read-side proposal; append-only history does not itself prohibit a future schema migration. |
| G06 | Accept intended semantics; revise the failure claim | W3 successfully used a newly changed heading in edit 2. A separate old-buffer proposal rejected as sequential_match_invalid with failed_change_id=chg_002 and no target mutation; a corrected progressive-buffer retry passed. Unrelated earlier length changes do not by themselves invalidate later exact strings. Keep sequential semantics; a worked example under F12 is more relevant than a runtime change. |
| G07 | Falsified | Native search returned version and current_hash. W5 used current_hash directly for a successful guarded submit. Do not add duplicate target_version/target_current_hash fields to solve this claim. |
| G08 | Accept diagnostic gap, revise labels and selector interpretation | Conflicting occurrence_index=1 and anchor_before='B:' returned disambiguation_invalid, occurrence_count=3, and a generic uniqueness message. No selector-clash explanation was present. Both constraints are conjunctive, not exclusive alternatives. Correct index 2 plus the same anchor accepted. Consider bounded constraint/candidate diagnostics under F06 while preserving semantics. |

### G02 transport control matrix

| UTF-8 override | JSON string representation | Submitted replacement | Stored replacement | Exit |
| --- | --- | --- | --- | --- |
| Off; stdin cp1252 | ASCII Unicode escapes | 🌟 | 🌟 | 0 |
| Off; stdin cp1252 | Raw UTF-8 | 🌟 | ðŸŒŸ | 0 |
| On; stdin UTF-8 | ASCII Unicode escapes | 🌟 | 🌟 | 0 |
| On; stdin UTF-8 | Raw UTF-8 | 🌟 | 🌟 | 0 |

Wrong-text target: 4b0b66aa-8c30-4efe-aa6c-e4308c2e111f. Both the later native export and SQL read returned ðŸŒŸ followed by LF. This supports a high-priority Windows transport correctness defect under the unconfigured default, not the reported UnicodeEncodeError stack trace. The current installed configuration avoids this reproduced path.

Minimal reproduction: launch the unmodified adapter with PYTHONPATH and the disposable database URL, removing PYTHONIOENCODING and PYTHONUTF8. Initialize ASCII hello. Send a UTF-8 encoded tools/call request with literal raw star in edits[0].replace and expected_target_version:0. The accepted result advances to version 1; export contains mojibake. transport_probe.py preserves exact stdin/stdout bytes in Base64 for all four controls.

## Original FRIC-01–FRIC-09 claims

| Claim | Disposition from this run |
| --- | --- |
| FRIC-01 lifecycle | Antigravity-specific failure remains unverified; Codex registration refresh was observed. See G01. |
| FRIC-02 encoding | Real default-input decoding problem reproduced; stdout crash not reproduced. See G02. |
| FRIC-03 extra read argument | Handled tool error reproduced; unhandled/crash interpretation rejected. See G03. |
| FRIC-04 repeated occurrence drift | Ascending indexes [1,2,3] over 'old old old' rejected at edit 3 and left version 0 unchanged. Descending [3,2,1] accepted and produced 'new new new'. W2 used this strategy successfully; the claim that indexes must be abandoned is too strong. |
| FRIC-05 near-miss diagnostics | Confirmed sparse response: 'MATCH text was not found.', failed ID, stage, and guards, with no near-miss snippet/candidates. W8 recovery used already observed tiny text, not new evidence supplied by the rejection. F05 remains supported. |
| FRIC-06 stale recovery | Confirmed guard response includes current version/hash but no changed-text excerpt; W6 used one fresh read before the retry. F01 may improve visibility without replacing safe rereading. |
| FRIC-07 ledger pagination | Correct traversal passed. min−1 guidance actively skips a row; use returned next_sequence. See G04. |
| FRIC-08 legacy prose/delimiters | Legacy required seven prose fields. A literal separator inside a MATCH block caused block_malformed at protocol_validation; typed submission of the same literal text accepted. Keep typed primary and legacy frozen. Actual W1 submit arguments were 255 bytes versus W11 592 bytes; differing prose/intents/keys mean this is a sample comparison, not a controlled universal ratio. |
| FRIC-09 rewrite payload | Literal old and new sections are both sent. Original fixture section was 22 lines; supplemental exact 40-line control passed. Size friction is real; F07 still carries required expected_text, F09 is whole-target replacement rather than literal replace-all, and F10 is a read helper, so none automatically removes old-text transmission in this workflow. |

## First conversation: skill frontmatter

Parsing the original checkout’s core-runtime skill header with PyYAML reproduced 'mapping values are not allowed here' at the unquoted internal 'runtime: typed' text. Quoting the description in memory made it parse. The other three original skill headers already parsed. The four existing local quote-only edits were not modified or reverted. Parser verification supports the reported YAML root cause; it does not claim a new Antigravity skill-loader run.

## Implications for Goal F and delivery

1. First remediate the proven Windows stdio input-decoding problem, with raw UTF-8 byte tests plus escaped-JSON controls and read/search/edit roundtrips. The existing UTF-8 environment setting remains the interim workaround. This report does not implement that fix.
2. Remove the proposed G07 search-metadata enrichment and the P1 unhandled-TypeError premise from the change list. Preserve G03 response-shape discussion as a separate, bounded contract review if desired.
3. Correct Gemini’s pagination guidance to before_sequence=next_sequence. Existing shipped docs already state this; preserve historical Gemini review records and record the correction separately.
4. Keep F01, F05, F06, and F12 supported by the live evidence, with bounded diagnostics and examples. Preserve conjunctive selectors and progressive atomic application.
5. Keep G05 as a read-side audit convenience question; raw attempt records already provide text. Do not infer a permanent schema ban from append-only history.
6. Evaluate F07/F09/F10 on their actual contracts and measured payload benefits. This run does not justify a replace-all feature, an unconditional runtime-profile change, or the removal of expected-text safety.
7. Resolve G01 only in the affected Antigravity host if that behavior remains important. Do not import its process-management diagnosis into the PatchDIFF runtime.

No code fixes, PR updates, merges, or Goal F edits were made. The installed MCP registration and dedicated database remain available for follow-up; the default database URL and UTF-8 setting were not changed during the probes. All additional targets and intentional wrong-text controls are confined to the dedicated reproduction database.

## Post-hoc source notes

Only after task completion, external_adapter.py was opened to explain the observations: its TypeError catch returns a tool-error envelope, and json.dumps uses default ASCII escaping, consistent with handled G03 and ASCII stdout in G02. The adapter does not establish UTF-8 stdin decoding itself. These explanations supplement the captured execution; the dispositions above are grounded in the actual responses and persisted content.

