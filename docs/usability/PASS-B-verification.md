# Goal F Pass B verification

Base: reviewed Pass A d27c1832a85efdb92e12d0b9fcf8acefb1c559f6. Pass B implementation f263f2e, integration merge5ac2e77 and profile guidance84ec120. Corrections c34a7e5d854db52b5b8aaa31e94737e6a0b3045a; test-fixture correction9854e1bfb9b5a78b959a68d76045429fb2ad83eb. No product/helper/evaluator change follows c34a7e5. Decisions preceded implementation in PASS-B-decision.md; EXECUTION-PLAN records the approved two-pass cadence.

## Local execution and correction chain

- One full post-implementation run at84ec120:1116 cases (733unit/383integration),1115passed/1failed,0errors/0skips,113.069seconds,ninewarnings. PASS-B-junit.xml/PASS-B-suite.txt preserve the actual failed run. Sole failure TEST-B1: manual/discovery helper expected nonexistent match_not_found rather than canonical match_absent. Do not report this run as green.
- Outside-pytest initial manual run failed at the same assertion; PASS-B-manual-initial-failure.txt preserves it. Runtime worker independently confirmed the enum/applier/MCP label; c34a7e5 corrects only the helper expectation.
- Independent source review identified MCP-B1: oversized replacement service results lost diagnostic.code and null log ID in MCP serialization. Root independently confirmed and fixed this atc34a7e5, preserving old invalid-option behavior and exposing structured admission data/fresh opted-in correlation when present. SKILL-B1/ARCH-B1 reconcile active exhaustive format/tool/profile lists. SCRIPT-B1 extends offline replacement byte accounting explicitly required by accepted Goal F.
- Affected correction run atc34a7e5:28cases,27passed/1failed. Public real-stdio discovery workflow and existing MCP cases passed. New direct serializer fixture lacked two required current-identity constructor fields (TEST-B2); PASS-B-recheck XML/text preserve the failure. Root added the null fixture fields at9854e1b and reran only that case:1passed (PASS-B-fixture-recheck XML/text). No product change for TEST-B2.
- No repeated local full suite. Final head/generated-merge CI must establish a green complete suite before approval. Serializer correction is covered by public stdio oversize assertions and the focused boundary case.
- Offline evaluator atc34a7e5 passed historical shared-applier equivalence with its named delimiter-collision exception and all5new accepted tx/3 content/hash oracles. New section measures UTF-8 bytes of the same guarded proposal's canonical persisted representation and modeled complete compact tools/call request line including LF. No captured-transport/persistence/token/timing/model-success claim follows from those byte counts.

## Separate outside-pytest live verification

PASS-B-live-verify.py ran atc34a7e5 against isolated patchdiff_goal_f_pass_b_manual_20261022 after live migrations. One real stdio process used raw UTF-8 for valid multilingual proposals with PYTHONIOENCODING/PYTHONUTF8 unset. Independent read-only SQL connections verify assertions. Integration invokes this same new workflow once; outside-pytest execution is separate, not an inflated distinct-scenario count.

Four combined assertion groups passed:

1. Bind and execute all13advertised(tool,index) pairs across9tools, validating actual bound arguments against actual schemas: selector acceptance, identical keyed recovery, intentional absent match, linked retry, span insertion, sole replacement, read/search/line read and preview. Complete discovery23492bytes/examples2096bytes stay below65536/8192 compact ASCII-escaped JSON budgets. Accepted preview hash/facts are checked and every managed table's row-content digest/count stays identical.
2. Nonvacuous complete history traversal: exclusive returned cursors, attempts descending and ledger ascending within each newest page. Unique sequence sets equal independent SQL. Before additional no-op transition:version4,5attempts,4accepted facts; retry parent and immutable original diagnostic match. Replacement log uses tx/3 and0.4.0; ledger operation=replace_all.
3. Final empty LF line and invalid boolean bounds; oversized valid replacement returns structured invalid_argument/null log/code without mutation. Failed span preview reports expected-text mismatch with no partial facts. SQL content/hash/version/log/ledger remain identical.
4. A no-op replacement advances monotonic version4→5 while retaining hash; old-version preview rejects. SAVE/replay/export succeed and all4materialized-state checks pass across tx/1,tx/2,tx/3 history. Final target a5eafcf2-994b-4bbd-89f8-d8b351c4b9bc:6attempts,5accepted facts,version5,content Final text plus LF.

PASS-B-live-results.json records27wire events (large request stores byte count/SHA rather than embedding its megabyte payload),47production source digests/helper digest, executedhead/status, real bound pairs, table-content evidence, final SQL and replay. PASS-B-manual.txt records console success. Additional live pytest cases cover raw equal/over size boundaries, invalid Unicode auditing before stale guards/size, recovery under stricter admission, replay bypass, caller rollback, actual pg_blocking_pids writer blocking/recheck, four-format preview/submit parity, dirty/stale ORM/pending unrelated state, one coherent SELECT/no FOR UPDATE and ownership. Those are pytest/live cases, not separately rerun manual probes.

## Review and release limits

Default-model ten-category independent review/rechecks: docs/reviews/Goal-F-PASS-B-84ec120-review.md. Reviewer independently parsed wire, checked47source/helper hashes and fresh read-only SQL at the manual target. Final published head/generated-merge CI and user merge approval remain separate gates at this snapshot.

F08/F13/F14 retain merged remediation/baseline closures in BASELINE-and-evidence-closures.md. F02/F04 and F10's editing adapter remain deferred; no fingerprint strategy/migration was added. V02 representative migration rehearsal and V04 representative replay/writer benchmark have no supplied sanitized dataset/meaningful production thresholds; synthetic migration/concurrency/replay evidence does not establish representative performance. No installed-host, model-success or universal platform certification is claimed.
