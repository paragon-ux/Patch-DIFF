# P0 instrumentation and progressive measurement

The current measurement scope follows [the user's execution direction](../../docs/optimization/20261028-EXECUTION.md). The original final plan and its SHA-256 freeze remain unchanged. `benchmark.py` measures **instrumentation overhead**. Its extended qualification protocol below is optional and is no longer a prerequisite for implementing an optimization.

The proportionate worker comparison is `python evaluation/structural_batch/compare_worker.py`: five paired real MCP/Postgres workflows, alternating order, one warmup per mode, instrumentation disabled, exact golden exports and behavioral/audit/replay checks. It writes a new exclusive result directory and reports descriptive medians. See [resident worker operations](../../docs/WAYMARK_WORKER.md). No bulk tool is implemented by either harness.

```powershell
.\.venv\Scripts\python.exe evaluation/structural_batch/benchmark.py --until diagnostic
.\.venv\Scripts\python.exe evaluation/structural_batch/benchmark.py --until qualification
```

Each command creates an exclusive UTC/source-head/run-UUID directory under `evaluation/structural_batch/performance/`. It authenticates the original fixture/task/transcript data, creates a separate randomly named PostgreSQL benchmark database, upgrades it with real Alembic, and uses real MCP stdio processes. It never drops the configured canonical database. Successful runs remove only their own temporary database; failed runs preserve its exact name in `retained-database.json` for inspection.

Every workload initializes five fresh targets, observes/submits the archived declarative operations, checkpoints, replays, exports and inspects audit/ledger rows: **20 editing plus 20 trusted lifecycle calls**. All five exports must match authenticated golden bytes. Behavioral checks run after exact-byte verification; subsequent matching outputs have the same authenticated bytes. Neither archived input nor `verify.py` is edited or executed as a model workflow.

The task clock starts before the first initialization and stops after the last audit/ledger check. Warm timings exclude process initialization/catalog/shutdown. Cold timings include those process phases. Required verification and export-hash work is equal on both sides. Server `rpc` events measure registry handler execution; client samples separately measure complete JSON-RPC round trips and serialized request/result bytes.

## Optional extended instrumentation protocol

`preregister.json` is written before sampling. Diagnostic (20 pairs) and screening (60 additional pairs) can reject a prototype, never qualify release. Screening rejects clearly excessive instrumentation overhead at median ratio >1.10 or p95 ratio >1.20. Qualification uses **200 new held-out pairs**, 20 blocks of ten, with ten discarded full-workflow warmups per side before each qualification block. AB/BA alternates; block bootstrap uses seed `20261027` and 10,000 paired-block resamples. No outliers are removed and exploratory samples are never pooled into qualification.

P0 qualification retains the locked upper-95%-bound gates: median task ratio ≤1.03 and p95 ratio ≤1.05. A passing warm comparison is followed by 40 paired fresh-process samples for the cold baseline. An inconclusive interval fails. Runtime/source hashes must stay unchanged; changed-source runs are invalid, not partially reusable confirmations. Failed prototypes need no resident-worker soak. There is no automatic repeated confirmation until significance.

The manifest records exact worktree source hashes in addition to Git HEAD, dependency lock hashes, runtime/OS/CPU/RAM/power information and PostgreSQL settings. An uncommitted execution is identified by its worktree hashes; HEAD alone is not represented as its executed source. Raw samples, receipts, catalog sizes, correctness checks, event/status files and memory observations are preserved. The final manifest hashes output files. A diagnostic result's confidence interval is descriptive; only the held-out qualification and completed cold/correctness checks can set `qualified: true`. A fatal error records `failure.json` with a failed outcome, elapsed time and exception class without exception text; partial samples remain preserved. Requesting qualification returns a failing exit code when its gate is not met.

## Opt-in telemetry boundary

`PATCHDIFF_PERF_EVENTS` is a trusted startup absolute file path. Omission disables telemetry. It is not an MCP argument, request identity or transaction option. Writer failures/queue overflow invalidate measurement evidence and do not change transaction outcomes. The queue holds at most 4,096 events; each event is at most 2,048 ASCII JSON bytes. A dedicated writer appends complete locked lines, so separately serving MCP processes can share a run path. Unique per-recorder status files avoid losing evidence when OS PIDs are reused.

Events contain only timing/opaque IDs/counts/byte sizes/allowlisted outcomes. No target text, operations, selectors, filenames, request keys, SQL text/binds, exception text or credentials are written to telemetry. Temporary bridge telemetry stays separate from protocol stdout/stderr and is bounded to 64 KiB before ingestion. Child timestamps retain the child PID; different process clocks are not subtracted. Phase durations overlap and must not be summed as independent wall-time components.

- `bridge_import` times the actual dynamic public Waymark import. It does not include Node creation or builtin imports.
- `bridge_discover` times the supported fresh discovery call, including first-language initialization when applicable. It does not isolate grammar initialization from parsing.
- `coordinate_conversion` and `observation_validation` cover their named service helpers; `applier` covers the service's pure application call.
- SQL timing includes the driver/server round trip. `lock_wait` is the entire marked target-lock query, not a claim of isolated database wait time. `lock_hold` ends after the actual root transaction commits/rolls back, including caller-owned lifetime.
- `replay_reconstruct` covers the existing replay service, including its database reads; nested SQL events are reported separately. It must not be labeled isolated CPU reconstruction.
- Memory is sampled every 50 ms when instrumentation is enabled. `rss_bytes` is sampled current RSS; `os_peak_rss_bytes` is the OS peak observed at that sample while the process was alive. These are not hard real-time memory ceilings or a guaranteed final peak after a child exits.

The one-shot discovery mode, exact locked authority, public schemas/catalogs, runtime profiles, audit/idempotency and replay semantics remain unchanged. Performance runs invoke no model and do not change Gate 2 or authorize merging.
