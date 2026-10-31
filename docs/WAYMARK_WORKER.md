# Resident Waymark discovery

Set `PATCHDIFF_WAYMARK_MODE=resident` before starting the serving process to reuse one internal Node process. `oneshot` remains the compatibility default. Unknown modes fail startup. `PATCHDIFF_NODE_BINARY` still selects the trusted Node executable; `PATCHDIFF_WAYMARK_WORKERS` currently accepts only `1`.

Both modes invoke `discovery_core.mjs`, which uses the pinned public `waymark-engine@4.1.0` API. Every discovery writes a fresh isolated file and parses the supplied authoritative content. The worker reuses module/grammar initialization, and does not cache document authority, symbols, observations or edit results. Existing filters, ordering, input domain and Python result validation are shared. Explicit adapter test overrides use the one-shot runner.

The private pipe protocol uses bounded length-prefixed UTF-8 JSON frames with generation and request identities. Source is streamed to an owned request file after admission; the control frame carries its generated directory token, byte count and SHA-256. This introduces no new source-size limit. Output retains the existing 2 MiB cap, and stderr is capped at 64 KiB per generation. Invalid framing, unsolicited data, wrong identities and worker death retire the generation. A failed discovery is never automatically retried or switched to another mode.

There is one active request and at most eight waiting descriptors, in FIFO order. Ordinary admission waits at most two seconds; startup readiness at most seven seconds; active discovery retains its positive finite timeout, normally fifteen seconds. The outer discovery allowance is the active timeout plus thirteen seconds (normally twenty-eight), including bounded failure cleanup under a responsive OS. These are phase ceilings, not mandatory waits, and exclude database/complete MCP request time.

Fresh submissions holding the target lock wait at most 250 ms for an already-ready worker, in the same FIFO. They never start a child while holding that lock. Request-key recovery/conflict detection happens first and remains available without discovery capacity. Queue expiry/full, protocol loss, cancellation, RSS/restart limits and cleanup failures raise `WaymarkWorkerError` with a `WAYMARK_WORKER_*` code. Service-owned transactions roll back; caller-owned transactions remain the caller's responsibility. These failures produce no invented validation attempt. Existing evaluator failures, output-size failures and active timeout retain their existing domain result/audit path.

Node old space is capped at 768 MiB. RSS is sampled every 100 ms against 1 GiB; this is an operational sampled limit. Generations retire after 10,000 requests or sixty minutes. At most three launches are permitted in a rolling minute. Windows Job Object ownership and a separate child stdin-reader thread terminate the child after abrupt parent death; POSIX uses an owned process group and the stdin-reader guard. Normal shutdown reaps the child and removes owned files. Stale-root cleanup requires a valid ownership manifest and confirmed dead/reused process creation identity; ambiguous roots are preserved.

The stdio server owns the worker for its entire serving loop and prewarms resident mode before requests, outside target transactions. Failed prewarming does not prevent recorded-key recovery. FastAPI lifespan owns cleanup but its health-only API starts no child. Trusted direct embeddings should use:

```python
from app.services.waymark_worker import serving_worker_owner

with serving_worker_owner():
    # Invoke existing registry/services here.
    ...
```

Nested contexts in one process share ownership; separate OS processes never share a child. Embeddings without a context retain lazy singleton and atexit cleanup. Mode is process startup configuration, never an MCP argument. No tool, catalog, durable runtime profile or migration is added.

The short comparison described in [the execution direction](optimization/20261028-EXECUTION.md) is retained with internal captures in the ignored local `evaluation/` directory. Public CI uses [backend verification](../backend/tests/verification/README.md); it requires no internal controller, transcript or generated result. No population-level or model-latency claim follows from the recorded comparison.

## Deployment and single-canary configuration

Install the repository's locked Python dependencies and run `npm --prefix integrations/waymark ci` from the same checkout. Set `PYTHONPATH` to that checkout's `backend` directory, and provide `PATCHDIFF_DATABASE_URL` through the operator's private environment. Start the actual editing MCP process with:

```powershell
$env:PATCHDIFF_WAYMARK_MODE = 'resident'
$env:PATCHDIFF_MCP_PROFILE = 'observed'
$env:PATCHDIFF_STRICT_OBSERVATION_MODE = '1'
.\.venv\Scripts\python.exe -m app.mcp.external_adapter
```

Set these values in the host's MCP server configuration, rather than relying on model instructions or a separate shell's environment. Restart the MCP process after changing startup settings. `tools/list` must advertise exactly `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_observed_operations`, `patchdiff_save`, and `patchdiff_replay`. Calls to all other handlers must fail at the profile boundary.

Use a separate trusted `full`-profile process for fixture initialization, final export and audit inspection. Keep its configuration and the reference evaluator outside the editing agent's context. Disable the agent's native file/shell tools and other MCP servers. Preserve exact request/result and transcript logs in private evidence, and record the executed source SHA, requested model/provider identity, effective reasoning setting and initial target hashes. Model routing and effective High reasoning must be attested by the owner's host; backend tests do not establish them.

For one owner-initiated canary, initialize five fresh targets from the authenticated original fixture bytes, supply only the unchanged original task/tool instructions plus the target mapping, and leave all versions at zero with no attempts. Do not replay archived solution payloads into those targets. After the model finishes, the operator exports the five targets, inspects SAVE/replay and audit results, and runs the independent full-byte and behavioral evaluator. Gate 2 remains closed; this configuration does not authorize a comparative run or merge.

## Optional timing evidence

`PATCHDIFF_PERF_EVENTS` selects an absolute private JSONL path for bounded timing
events. With recording enabled, `PATCHDIFF_PERF_MEMORY=1` (default) also samples
diagnostic RSS; `0` keeps timing events and recorder status without RSS samples
or a memory file. The status receipt records `memory_sampling_enabled`. Other
values invalidate telemetry (`invalid_memory_configuration`) without changing
transactions. This setting never disables the worker's independent RSS limits.
`ipc_read` covers one complete response wait: normal empty polling is included
in the successful duration; timeout, cancellation and pipe/protocol failures
produce a failed outcome. Nested durations are not additive CPU measurements.
