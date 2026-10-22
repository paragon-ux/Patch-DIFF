# Goal F consolidated execution plan

Authority: the user's 2026-10-21 instruction to combine F02-F07 and F08-F14 into two consolidated passes. This supersedes the accepted goal's per-feature PR cadence and delivery order, while preserving its feature scope, contracts, bounds, ownership and compatibility requirements. The verbatim accepted documents and their hashes remain unchanged.

F01 foundation is implemented at 7e20ea4 with the C2 documentation qualifier at 128f59d. Its 902-test full suite, offline evaluator and six-group outside-pytest live stdio/SQL verification passed at 128f59d. Retain its independent review as baseline evidence. Include this foundation in the first consolidated feature PR rather than opening a separate F01 PR/CI/merge cycle.

| Pass | Included IDs | Deliverables |
| --- | --- | --- |
| A: F02-F07 | F03, F05, F06, F07; completed F01 foundation | Opt-in correlation metadata, bounded post-lock near misses, bounded exact ambiguity candidates, guarded versioned span operations. F02 optional guards and F04 fingerprint normalization remain explicitly deferred. |
| B: F08-F14 | F09, F10 read-only helper, F11, F12; F08/F13/F14 evidence closures | Guarded sole-operation whole-target replacement, bounded line/range reads, zero-audit advisory preview, executable bounded discovery examples. Existing selector/paging/context fixes retain their evidence closures. F10's editing adapter remains deferred. |

For each pass: record decisions and reconcile normative contracts before the corresponding production changes; implement the whole batch first; then run one complete suite/offline check, a combined manual live PostgreSQL/public-stdio exercise and one independent ten-category review. Per the user's subsequent acceleration instruction, do not run routine intermediate test loops; focused checks are for concrete uncertainties/failures. Reuse already reviewed foundation evidence and review only affected deltas where appropriate. Repeat broad checks only for a source change, failure or unresolved concern that justifies it.

Prepare one consolidated PR per pass. Capture its exact source and generated-merge CI revisions. Merge approval remains separate. Pass B can develop from the completed A head while A awaits approval, using the correct dependent base; do not merge without approval or silently broaden deferred scope. Preserve old profiles, request identity, historical reviews, qualified audit guarantees and caller-owned transactions.

Goal G independent review is closed at the user's request and is not a pending gate. Gemini report qualifications remain in GEMINI-v1-v2-REVIEW.md; they add no production feature or extra review cycle.
