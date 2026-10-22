# Gemini v1/v2 report assessment before Goal F

Reviewed 2026-10-21 by Codex. Scope: both supplied LIVE_FEATURE_SET_TEST_REPORT.md and REAL_WORKFLOW_FRICTION_TEST_REPORT.md files in the original checkout's docs/reviews/gemini/v1 and v2 directories. This is an assessment of external evidence, not a new PR approval or a replacement for the accepted Devin plan. Supplied reports remain unchanged. Their exact SHA-256 values and the observations below are recorded in GEMINI-v2-evidence-check.json; GEMINI-v2-evidence-check.py reproduces the read-only check.

## Decision

Keep the v2 G01-G08 reconciliation with the qualifications below. Continue accepted Devin Goal F revision 2 from main 2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10, beginning with F01. No newly demonstrated production defect or required scope change emerged from these reports. Do not adopt their blanket certification or performance conclusions.

## Evidence actually examined

- Read all four supplied reports, the archived Codex reproduction metrics/oracle, current model/applier hash fields, the playground harness setup and concurrency assertions, and the separate G02 helper and captured results.
- The playground checkout is currently at main 2ee7ce4. Its tracked product code is unchanged; G02-live-results.json is modified and live_test_harness.py/live_test_results.json are untracked. Its PYTHONPATH therefore resolves to the intended code now. Current HEAD alone does not prove which code an older unpinned run executed.
- Playground live_test_results.json contains 28 PASS records. The harness uses real subprocess pipes for MCP cases and separate database connections with pg_blocking_pids assertions for concurrency. Those direct-service concurrency cases are not simultaneous native Antigravity tool calls. The harness explicitly sets PYTHONIOENCODING=utf-8 and serializes requests with ensure_ascii=True; it cannot establish the no-override/raw-byte claim itself.
- The separate G02 result records executed_head=2ee7ce4, Python 3.11.9, source-file digests matching the current adapter/helper, four absent/cp1252 by raw/escaped profiles, replay checks and malformed-wire nonmutation. Its actual database is patchdiff_goal_g_manual_20261021. Read-only live SQL independently matched all four captured target content/version/log/ledger summaries.
- On both localhost:5432 and 127.0.0.1:5432, the reported patchdiff_subagent_v2_eval database does not currently exist. This prevents independently rechecking its W1-W12 target oracle, 13 attempt rows, 28 ledger rows and specific retry parent. It does not prove that an earlier disposable run never occurred. No database was created to conceal this gap. No raw v2 W1-W12 event/SQL artifact was located in the reviewed repository paths. The Antigravity private directory was inaccessible.
- The independently completed Goal F baseline at the same main SHA provides separate evidence: 842 tests passed (617 unit + 225 integration), migration upgrade/downgrade/upgrade passed, offline shared-applier equivalence OK, and four outside-pytest public-stdio/SQL G02 profiles passed. These results do not authenticate Gemini's particular durations or W1-W12 run.

## Required qualifications to the reports

| ID | Disposition | Evidence and correction |
| --- | --- | --- |
| GR-01 | Revise measurement provenance and totals | The v1 friction table's individual rows reproduce archived Codex workflow-metrics.json. Attribute that baseline to the Codex reproduction rather than describing all numbers as an independent Gemini v1 measurement. Both supplied tables undercount total argument bytes by 600: v1 rows sum to 9,102, not 8,502; v2 rows sum to 8,651, not 8,051. The 43 calls, 113,556 v1 result bytes and 278,391 ms aggregate correctly. W7's two-call recovery segment excludes its deliberately discarded first response; do not relabel 43 as every setup/interference/discarded-response call. |
| GR-02 | Reject comparative performance conclusion | v2 friction section 3 explicitly compares interactive call-span time with scripted client execution time. Keep those as separately labeled observations; 278,391 versus 3,889 ms is not a product speedup or measured reduction in agent hesitation. Both tables still report 43 calls and two deliberate rejections. Payload bytes also depend on changed keys/prose/options, not solely on the transport fix. |
| GR-03 | Revise test/migration attribution | v2 feature sections 2.2/4 wrongly attribute the four new integration cases to test_stdio_adapter_subprocess.py (an existing unit file). They are in backend/tests/integration/test_external_mcp_utf8.py; the four unit tests are in test_stdio_utf8.py. v1 feature section 2.2 already reports upgrade/downgrade/upgrade, so v2's 'v1 Upgrade head only' comparison is inconsistent with its own baseline. v2 friction's final T2 oracle refers to 290 lines, the original fixture count; the archived intended final 19,958-character document has 282 lines. |
| GR-04 | Revise ledger field names | v2 friction section 5.2 and v1 W9 name before_hash/after_hash as per-change span hashes. Per-change derived_json actually contains matched_sha256/replacement_sha256 plus span_start/span_end and character counts. before_hash/after_hash belong to the enclosing transaction/log. Keep these distinct; no ledger schema change follows. |
| GR-05 | Revise evaluator claim | v2 feature section 2.4 says verdict parity across all payloads, then correctly reports legacy delimiter rejection versus typed acceptance. Retain the named delimiter exception. The approximate 82% wire saving is one measured multi-edit/minimal-prose scenario, not a universal serialization-only or model-success result. |
| GR-06 | Reject universal certification | 'Fully certified', identical Windows/Linux/macOS reliability, and absence of all corruption/collisions exceed the tested scope. Say which Windows profiles, PostgreSQL cases and CI environments passed. W6 ordered interference is not by itself simultaneous writer contention; W7 deliberate response discard is not an induced network failure. Separate those from the harness's real lock-wait cases. |

These are corrections to evidence interpretation, not six new production bugs. Preserve the supplied reports as external historical evidence; use this assessment when quoting them. The absent W1-W12 database/raw records and ambiguous dual Python version listing remain verification gaps, not defect findings. Do not close historical review findings based on these summaries alone.

## G01-G08 reconciliation

| Item | Decision for Goal F |
| --- | --- |
| G01 | Keep deferred host lifecycle investigation. A Codex refresh does not falsify every Antigravity process-lifecycle claim. No new host controller. |
| G02 | Keep fixed and verified, with the corrected defect description: raw UTF-8 input could be decoded as cp1252 and accepted as mojibake. The captured four-profile main run and independent SQL support the transport fix; a universal stdout crash was not established. No reopening or new profile. |
| G03 | Keep handled tool-error closure: unexpected kwargs yield isError=true and the server survives. The separate non-object params case returns -32602; do not conflate these error envelopes. |
| G04 | Keep returned exclusive next_sequence traversal and documented page order. Do not subtract one or change ordering. |
| G05 | Keep compact ledger and retrieve literal submitted edits from attempt content. This does not ban every future schema change; it removes an unsupported migration request here. |
| G06 | Keep sequential buffer semantics. Existing prose examples and the successful descending-index workflow support the current invariant. They do not complete F12's bounded executable tools/list examples. |
| G07 | Keep falsified missing-metadata premise: search already returns version/current_hash. No redundant new read or metadata feature. |
| G08 | Keep diagnostic work under F06. Selectors are conjunctive constraints. Preserve the exact verdict while adding bounded labeled candidates. |

## Consequences for accepted Goal F

- F01 remains first: W6 needs visible fresh state and W8 needs bounded original failure context. Keep original terminal evidence immutable on keyed recovery and return fresh context separately. A successful retry does not close this feature.
- F12 remains an implementation: publish bounded schema-conforming examples and actually execute all of them over stdio/PostgreSQL, including exact dedup, linked retry, sequential selectors and both history page orders. No model-success claim.
- F10 remains the accepted read-only line/range helper. W12 supports its usefulness, but does not authorize the deferred editing adapter.
- F05/F06 retain the accepted bounds, stage identity and ownership constraints. Near-miss work starts only after a service-owned lock is released; caller-owned locks require explicit omission. No fuzzy application, automatic selector choice or unlimited candidate output.
- F03/F07/F09/F11 retain their pre-code decisions and compatibility gates. This report supplies no reason to add optional guards, normalize request identity, waive guarded expected text, or build submit-then-rollback preview.
- F08/F13/F14 still require merged-base evidence closures. G04/G06/G07 summaries are not substitutes for their actual fix/test pins.
- Retain bounded feature PRs, live verification outside existing tests, default-model independent review, and separate merge approval. The baseline is already green; no source change occurred during this report assessment.

## Remaining evidence request, without blocking F01

If Gemini's exact new workflow timings or SQL totals will be used for release claims, retain its raw client script, per-call request/result/timing events, executed module paths and source hashes, Python version, environment flags, fixture digests, target IDs, and read-only oracle/SQL output before disposing of its database. Rerun comparable clients under the same timing boundary for any performance comparison. Existing independent baseline evidence is sufficient to proceed with the accepted F01 work; the uncorroborated measurements must not be presented as independently verified.

## User disposition after assessment

The user closed the Goal G independent review on 2026-10-21 because it had no remaining open items and further verification can occur later. The running review agent was stopped. Goal G is not a pending review gate for Goal F. Its already-delivered arithmetic/line-count corrections above remain recorded; a separate review of the new F01 implementation remains part of accepted Goal F.
