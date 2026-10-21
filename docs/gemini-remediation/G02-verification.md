# G02 verification and Goal G delivery

Date: 2026-10-21. Repository: paragon-ux/Patch-DIFF.
Starting product head: b5caa40bd41848420c4323d22ab648847cdc6745.
Accepted plan/archive commit: 6786ab7.
Fix and exact executed head: f19c97f50f241b8af764539e818c6e9762de3c1b.
Branch: fix/gemini-stdio-utf8.

## Delivered scope

Created [GEMINI_CHANGE_PLAN.md](../reviews/gemini/GEMINI_CHANGE_PLAN.md) and [Gemini-Goal-G.md](../reviews/gemini/Gemini-Goal-G.md) in the requested directory. Archived the three superseded Gemini reports without changing their bytes, and copied the native reproduction/raw transport/SQL evidence. The archive manifest records original locations and SHA-256 values; all 12 protected historical hashes and both Devin template hashes remain unchanged.

G02 product fix is exactly two lines in external_adapter.main: reconfigure the existing stdin/stdout wrappers as UTF-8 with strict errors. This updates the wrappers already bound by serve_stdio defaults, leaving injected test streams usable. No stderr reconfiguration, new dependency, migration, tool alias, JSON response escaping change, fingerprint change, replay-profile bump or transaction change.

Active README, setup guide, host guide and modernization change record describe the corrected defect and compatibility workaround. The four pre-existing skill quote edits and untracked Devin documents remain outside these commits.

## Independent implementation triage

Default-model worker goal_g_transport independently confirmed cp1252 decoding of literal UTF-8, demonstrated the new unit subprocess regression failing before the fix with mojibake, and implemented only the adapter/two new test files. Its focused run passed 13 tests in 47.86s against isolated worker database patchdiff_goal_g_worker_20261021. The count includes four new unit checks, five existing subprocess checks, and four new live matrix cases. The initial live test assertion used an incorrect evidence-key name; it was corrected to evidence_format before the successful run, with no extra product change.

## Required local verification at the fixed SHA

| Check | Execution/result |
| --- | --- |
| Empty migration rehearsal | Fresh suite DB passed upgrade head → downgrade -1 → upgrade head; manual DB upgraded to head. Populated migration preservation/refusal tests also ran in the full integration suite. |
| Unit + live integration suite | PYTHONPATH=backend, isolated PATCHDIFF_DATABASE_URL ending patchdiff_goal_g_suite_20261021; python -m pytest backend/tests/unit backend/tests/integration -o addopts='' -q. 842 passed, 9 existing Alembic deprecation warnings, 102.13s. |
| Offline evaluator | python evaluation/offline_eval.py. Verdict equivalence on the shared applier: OK; byte accounting remains separated from task/model claims. |
| Manual live workflow | python -X utf8 docs/gemini-remediation/G02-live-verify.py; outside pytest, separate database patchdiff_goal_g_manual_20261021. Four profiles passed: ambient encoding absent or explicit cp1252:surrogateescape × raw UTF-8 or ASCII-escaped JSON. |
| Independent review | A second inherited/default-model reviewer inspected f19c97f, reran a raw-byte invalid-target probe without DB writes, verified archive/protected hashes and manual source hashes, read all four manual targets independently via SQL, and reviewed suite/offline/manual evidence. No actionable P1/P2/P3 findings. Full category report: G02-independent-review.md. |

Saved execution logs: G02-suite.txt, G02-offline.txt, G02-manual.txt. Raw-byte and SQL evidence: G02-live-results.json. Reproduction helper: G02-live-verify.py. The manual record pins executed_head and the SHA-256 values of the adapter and helper, so a later evidence-only commit does not pretend to be newly executed product code.

The manual workflow executed actual public MCP tools over OS subprocess stdin/stdout, with binary request bytes. It checked upload/CRLF canonicalization, bounded read, exact search/version/hash metadata, Unicode typed acceptance, exact keyed recovery, handled unexpected kwargs followed by a successful read, escaped NUL and lone-surrogate audited rejection, SAVE, replay, and export. Separate malformed UTF-8 requests failed decoding without target/log/ledger mutation.

Each of the four independently queried SQL targets contained exactly the intended Unicode at version 1, with one accepted log, two rejected logs and one accepted ledger entry. All replay components passed. The second reviewer independently read those rows, rather than relying only on script status.

## Disposition ledger

| ID | Result |
| --- | --- |
| G02 | Fixed at f19c97f; raw-byte + live DB/manual evidence and independent recheck supplied. Original stdout-crash mechanism was not reproduced and is not claimed fixed as that mechanism. |
| G03 | Unhandled/P1 premise not reproducible; handled isError:true and continued operation verified. No dispatch rewrite. |
| G04 | Intentional compatible traversal; use returned next_sequence exclusively. Historical min−1 guidance corrected in accepted inventory. No cursor/order change. |
| G05 | Intentional compact ledger plus existing attempt-log text retrieval; optional read enrichment deferred. Supplied intent/rationale/risk preservation verified. |
| G06 | Intentional progressive-buffer semantics; atomic rejection and corrected retry verified. Examples remain Goal F/F12. |
| G07 | Missing-metadata premise not reproducible; native search returned version/current_hash and supported direct guarded submit. No alias fields added. |
| G08 | Diagnostic enhancement outside Goal G implementation; evidence retained for Goal F/F06, without changing conjunctive selectors. |
| G01 | Affected Antigravity host lifecycle remains unverified; deferred by accepted scope. Host refresh guidance states the uncertainty. |

## Limits and integration

All results above are local, source-pinned execution; no new CI pass is inferred. The installed native MCP registration still points at the original playground checkout with PYTHONIOENCODING=utf-8 and the reproduction database. Fixed-code verification explicitly launched this repository's adapter in separate processes; it is not described as a fixed native-host deployment.

No PRs have been merged, no protected branch changed, and no original databases dropped. The existing PR #9 was independently checked as OPEN at b5caa40 on docs/devin-request-identity, providing the correct current stacking base for a follow-up review branch. Any publication/CI metadata is recorded separately when available; Goal F’s consolidated-main prerequisites remain unchanged.
