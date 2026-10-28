# Resident-worker package — implementation and verification

The resident internal Waymark worker is implemented. Set `PATCHDIFF_WAYMARK_MODE=resident` before starting the serving process; `oneshot` remains the compatibility default. See [operations](../../../../docs/WAYMARK_WORKER.md).

## Local comparison

| Median time | One-shot | Resident |
|---|---:|---:|
| Twenty editing calls | 5.857 s | 1.770 s |
| Full forty-call workflow | 6.500 s | 2.463 s |

Editing time was about **70% lower in this five-pair local sample**. Both sides used the same code, fixtures and fresh-target workflow, alternating order, after one warmup per mode. Instrumentation was disabled. All five golden exports and twenty behavioral checks passed for each measured workflow, alongside audit/ledger, SAVE and replay checks. Full/observed catalog bytes stayed 47,999/16,953; calls stayed twenty editing plus twenty trusted lifecycle calls. This establishes a local runtime benefit, not a population-level performance claim, cold-start result or model/host latency result.

[Raw samples](samples.jsonl), [protocol and source hashes](protocol.json), [summary](summary.json).

## Verification

- Full unit suite: 973 passed.
- Full live Postgres integration suite in resident mode: 544 passed, including migrations and real stdio subprocesses.
- Final focused adapter, worker fault/lifecycle and live transaction checks: 39 passed.
- Offline verdict equivalence and replacement oracles: passed.
- Source hashes stayed unchanged during the comparison; `git diff --check` passed.

Final focused checks followed the small readiness-allocation and POSIX zombie-cleanup corrections. Windows process ownership, hard parent termination and stale-root recovery were executed; POSIX-specific process behavior remains unexecuted on this host. [Verification manifest and XML receipts](verification/VERIFICATION.json).

The worker reuses initialization while performing a fresh parse of every supplied authoritative preimage. Existing guarded application, atomicity, idempotency, audit and replay remain in the shared service/runtime path. New supervisor failures propagate as infrastructure errors; tests verify no invented attempts and the distinction between service-owned rollback and caller-owned transactions. No public tool, catalog, durable profile, migration or bulk scheduler was added.

The long instrumentation run was stopped after its sixty-pair screening stage, as requested; its earlier twenty diagnostic pairs and original raw evidence remain preserved. The queued two-hundred-pair qualification was skipped. Both planning subagents were interrupted/completed and performed no implementation work. Original/frozen plans remain byte-identical; the user's execution direction is recorded separately. This report covers the first resident-worker implementation package, not completion of the broader optimization plan, CI approval or Gate 2.
