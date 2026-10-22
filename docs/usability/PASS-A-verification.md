# Goal F Pass A verification

Scope: completed F01 foundation plus F03 correlation metadata, F05 bounded post-lock near misses, F06 bounded exact candidates and F07 guarded span operations. F02/F04 remain deferred. Pass B contains the remaining accepted implementations/closures. EXECUTION-PLAN.md records the user's two-pass cadence and implementation-first/full-suite-afterward instruction.

Production implementation and manual helper are pinned at 46bd2938977b3992e6009187370df36649655810, based on main 2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10. Follow-ups afdd80bcf3ba3b16e0ce6538c4a04a02b3d76590 (expected enum inventory) and 154ab7a97c74775e8f7ff205f00ecc1a5e5d7eab (skill guidance) change no production code. Do not relabel an executed SHA as a later documentation head.

## Local execution

- Implementation agent: 391 distinct focused cases passed, including 103 new Pass A cases (50 unit + 53 PostgreSQL/stdio). These are narrower implementation checks, not a second full suite.
- One post-implementation full suite at 46bd293: 1,004 passed, one failed, nine warnings, 120.14 seconds. PASS-A-junit.xml contains 685 unit and 320 integration cases. The sole failure was test_failures.py's exact expected enum set, missing the two deliberately introduced span labels. Preserve PASS-A-suite.txt/PASS-A-junit.xml as the actual failed run; do not report it as green.
- Root independently checked the expected taxonomy against the pre-code decision and FailureReason/PDCP_REJECTION_REASONS, then fixed the test at afdd80b. Only test_failures.py was rerun: three passed in 0.08 seconds (PASS-A-recheck.txt and PASS-A-recheck-junit.xml). The full suite will run through required final head/generated-merge CI instead of another local broad repetition for the test/document-only corrections.
- Offline evaluator at afdd80b: shared-applier equivalence OK, including its named legacy delimiter exception and separate persisted/wire-byte accounting (PASS-A-offline.txt). No token or model-success claim.
- Combined outside-pytest manual run at 46bd293: seven groups passed in PASS-A-live-verify.py, using disposable patchdiff_goal_f_pass_a_manual_20261021. Seventeen public tool calls used one real stdio process with raw UTF-8 and no PYTHONIOENCODING/PYTHONUTF8 overrides. Independent SQL verifies final content/version, seven attempts, four ledger facts, old tx/1 runtime 0.2.2 alongside tx/2 runtime 0.3.0, and exact preserved original diagnostics.
- Manual groups cover opted-in/fresh/default-omitted UUIDs without generated request keys; exact ambiguity candidates; whitespace near misses; Unicode insertion and mixed sequential span/match edits; recovery after later edits with old immutable failure/near inputs and fresh target context; response-option exclusion from identity; atomic bounds/expected-text/later-operation rejection; invalid-option pre-admission nonmutation; history paging; SAVE/replay/export.
- A separate scoped service diagnostic-entry probe in the same manual script obtains FOR UPDATE NOWAIT from another PostgreSQL connection and sees the committed rejection before invoking the real near-miss algorithm. The caller-owned counterpart retains its lock, returns explicit omission, and leaves rollback/visibility under caller control. This is instrumentation of diagnostic entry, distinguished from the unmodified public-stdio cases.

PASS-A-live-results.json records raw wire bytes, all production Python source digests, actual executed head, SQL state, replay checks and lock observations. PASS-A-manual.txt is its console result. No mutation of the installed-host configuration is claimed.

## Independent findings and recheck

The default-model reviewer reused the completed F01 review as baseline and inspected Pass A's new/affected ten categories. TEST-A1 is the inventory correction above. SKILL-A1 is the persistence skill's stale runtime/content-format guidance; SKILL-A2 is its overbroad row-per-submission wording, qualified to the current audit contract in 154ab7a. Review source, fix/evidence pins and final dispositions are in docs/reviews/Goal-F-PASS-A-46bd293-review.md. The reviewer independently checked raw responses, unchanged F01 blobs, source hashes and fresh read-only live SQL.

This record establishes local implementation/live evidence and records the initial test failure honestly. It does not claim final CI or merge approval. Final PR head and generated-merge runs must be inspected at their actual checkout SHAs before approval; their evidence can be retained with the PR and task artifacts without creating a CI-triggering documentation loop.
