# Release preparation

This checklist distinguishes reviewed code from a published release. Neither merging a PR nor a green historical CI run creates a tag, publishes a package, or verifies a production deployment.

## Version and tag plan

| Identifier | Current value | Meaning |
| --- | --- | --- |
| Python distribution | `patchdiff-mvp` `0.1.0` | Package metadata; candidate first tag `v0.1.0` |
| MCP server advertisement | `patchdiff-mvp` `0.2.2` | Stdio server information |
| MCP wire protocol | `2024-11-05`, `2025-06-18`, `2025-11-25` | Supported negotiated revisions (`2024-11-05` legacy default; `2025-11-25` latest). See negotiation fallback rules below. |
| Legacy transaction | `0.2.3` | Frozen declarative `.pdcp` format |
| Typed matches | `patchdiff-tx/1` / runtime `patchdiff-mvp-0.2.2` | Existing guarded match submissions |
| Match/span operations | `patchdiff-tx/2` / runtime `patchdiff-mvp-0.3.0` | Sequential span and match operations |
| Span context | `patchdiff-tx/2` / runtime `patchdiff-mvp-0.5.0` | Span operations with `expected_before`/`expected_after` |
| Sole replacement | `patchdiff-tx/3` / runtime `patchdiff-mvp-0.4.0` | Explicit whole-target replacement |

These are independent version domains. Do not rename durable runtime profiles to match a marketing version. Existing historical runtime profiles `0.1.0`, `0.2.0` and `0.2.1` remain supported under their recorded identifiers.

### Wire Protocol Fallback Semantics (`PR22-DEP-003`)

In `backend/app/mcp/external_adapter.py:262-265` (tested in `backend/tests/unit/test_editor_v2_adapter.py`), MCP initialization protocol negotiation follows these explicit rules:
- **Omitted `protocolVersion`**: When `protocolVersion` is omitted from `initialize` client params, the server falls back to `2024-11-05` (`PROTOCOL_VERSION`).
- **Unsupported revision**: When a client provides an unsupported `protocolVersion` string, the server negotiates `2025-11-25` (`LATEST_PROTOCOL_VERSION`).
- **Supported revisions**: The runtime strictly negotiates `2024-11-05`, `2025-06-18`, or `2025-11-25`.

No remote tags or GitHub releases existed when checked on 2026-10-22. `v0.1.0` is a proposal derived from the current distribution version, not an existing or authorized tag. Confirm the final release version and merged revision before creating an annotated tag. If the package version changes, update metadata and release notes together. Tagging, GitHub release publication and package upload require separate explicit authorization.

## Merge review

- Review [release notes](https://github.com/paragon-ux/Patch-DIFF/blob/main/CHANGELOG.md), [README](https://github.com/paragon-ux/Patch-DIFF/blob/main/README.md), [tool contracts](../spec/MCP_TOOLS.md) and [host guidance](../guides/HOST_INTEGRATION_GUIDE.md) against actual discovery and behavior.
- Complete integration and release-readiness reviews. Recheck every confirmed finding at a fix revision; preserve historical results and evidence.
- Check the exact current PR head and generated-merge CI checkout SHAs, test counts, migrations and offline results. A prior check on another revision is insufficient.
- Verify a real stdio/PostgreSQL workflow outside existing tests, including guard/recovery, bounded preview, ledger, SAVE/replay/export and independent SQL assertions. Retain source and helper hashes.
- Merge the dependency PR first, retarget its dependent PR to main, and verify its newly generated merge before any second merge. Keep review approval separate from owner merge authorization.

## Publication checks

- MIT license and package license/readme metadata must be present in source and built artifacts. Third-party dependency licenses are separate from the project license.
- Resolve/install the exact reviewed dependency lock in an isolated environment; run dependency consistency, current advisory checks and the complete suite after implementation is finished. Include the Python/platform and exact lock hash in evidence.
- Build and inspect a wheel without publishing. Smoke-test the installed artifact's MCP initialization/discovery and health endpoints from outside the source checkout. The documented deployment still uses a source checkout and its migration configuration; no standalone PyPI deployment is certified by an editable install.
- Verify a private security-reporting channel. It was disabled at review time; see [SECURITY.md](https://github.com/paragon-ux/Patch-DIFF/blob/main/SECURITY.md). This is a publication prerequisite, not an invitation to post sensitive reports publicly.
- Reassess the pinned PostgreSQL container image and deployment configuration for the intended environment. A PyPI advisory check does not cover operating-system/container vulnerabilities. Bind development services to loopback; do not recreate existing data volumes as part of verification.
- Use the final merged source revision for release artifacts and checksums, then attach those exact artifacts to any approved release. Do not copy source-tree test results to a different wheel or tag without checking identity.
- **MCP Registry Listing & Glama Verification (`PR22-MCP-002`)**: Static schema compliance for `glama.json` (per `https://glama.ai/mcp/schemas/server.json`, defining `maintainers: ["paragon-ux"]` and omitting duplicate tool schemas) is verified during PR review. Live claiming, indexing, and directory refresh on Glama can only occur post-merge against the default `main` branch (tracked under gate `POST_MERGE_REGISTRY_VERIFICATION`). Once merged to `main`, the repository maintainer (`paragon-ux`) confirms the live listing and directory refresh via Glama (see [Glama claim guide](https://glama.ai/blog/2025-07-08-what-is-glamajson)). Live external registry ingestion is not a pre-merge code defect and must not be claimed as verified on pre-merge PR branches.

## Evidence limits

The suite covers Python 3.11, live PostgreSQL and actual stdio workflows on the environments recorded with the checks. Broader Python/host/platform support requires its own evidence. The offline evaluator measures deterministic bytes and outcomes, not model success or tokens. Representative production datasets, performance thresholds, full-history secret scanning and container vulnerability assessment are not established by the existing local checks. Keep these limits visible in any release announcement.
