# Release notes

## Unreleased — guarded editing, bounded reads and advisory preview

This update extends the local MCP document transaction service. It has not been tagged or published as a release.

### Added

- Guarded sequential span edits through `patchdiff_submit_operations`. Each span uses Unicode code-point coordinates and exact expected text; match/span transactions commit atomically.
- Explicit whole-target replacement through `patchdiff_submit_replacement`. It requires a version or hash guard and is the sole operation in its transaction. Fresh raw and canonical replacement limits are 1,000,000 code points and 1,048,576 UTF-8 bytes, inclusive.
- Bounded LF line-range reads through `patchdiff_read_lines`, with coherent version/hash observations and range-relative continuation.
- Keyless advisory `patchdiff_preview`, sharing submission validation without creating audit rows or changing the target. Preview evidence is bounded to 32,768 compact ASCII-escaped JSON bytes; omitted facts and diagnostics are explicit. A subsequent submission rechecks its guards.
- Separate immutable original failure evidence and fresh rejection context, bounded exact ambiguity candidates, optional invocation correlation IDs, and bounded near-miss suggestions computed after service-owned commit/lock release. Suggestions never apply edits automatically.
- Thirteen executable discovery examples across nine of the twenty advertised tools.

### Compatibility and operations

- Existing typed match/legacy identities, hashes and replay profiles are preserved. `patchdiff-tx/2` uses runtime `patchdiff-mvp-0.3.0`; sole replacement uses separate `patchdiff-tx/3` / `patchdiff-mvp-0.4.0`.
- No database migration is added by these features. Existing migrations `20260510_0001` and `20261020_0002` remain required. Caller-owned transactions retain commit/rollback and lock ownership.
- Exact keyed recovery creates no new attempt. Read/preview and documented pre-admission errors create no attempt. Use a caller-known request key to recover a lost response; correlation IDs cannot replace it.
- Preview returns a bounded subset of facts when necessary; ordinary accepted submission/recovery retains its full facts. A version guard detects intervening no-op/ABA edits that a content hash alone cannot detect.
- Optional typed guards, normalized request identity and a line-based editing adapter are not included.

### Security, licensing and verification

- MIT license added, including package license metadata.
- Development PostgreSQL publishing is restricted to `127.0.0.1`; the supplied password remains a local development example.
- Advisory-matched dependency pins updated: AnyIO 4.14.2, certifi 2026.10.19, Mako 1.4.2, pytest 9.0.3 and Starlette 1.3.1. The test extra now requires patched pytest 9.x. See the [security policy](SECURITY.md) for scope and reporting limitations.
- Verification includes live PostgreSQL, actual stdio subprocesses, separate manual public-tool workflows, migration regression, historical replay and deterministic byte accounting. Previous failed verification runs and their corrections remain traceable in PR evidence; a historical green check does not certify a later revision.

No model success-rate, token reduction, representative production performance or universal host/platform certification is claimed. See the [release checklist](docs/RELEASE_READINESS.md) before tagging or publishing.
