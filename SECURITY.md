# Security policy

PatchDIFF currently targets a trusted local MCP host and PostgreSQL deployment. The stdio adapter inherits the launching user's local privileges and database access. It is not a public multi-tenant editing service and provides no separate application authentication or tenant-isolation boundary.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/paragon-ux/Patch-DIFF/security/advisories/new) when it is enabled. The repository setting was disabled when checked on 2026-10-22; enabling and verifying a private reporting channel is required before a tagged public release. No private email address or response-time commitment is currently published.

Until a private channel is available, ask the maintainer for one without posting exploit details, credentials or document contents in a public issue. Do not submit sensitive evidence through ordinary public issues.

## Local deployment

- The Compose database binds to `127.0.0.1:5432`. Existing containers keep their old mapping until deliberately recreated; editing Compose does not change a running container.
- The `patchdiff:patchdiff` credentials are development examples. Use distinct credentials, database permissions and a protected connection for real data. Keep `.env` and connection strings out of commits and public reports.
- Keep the health server on loopback unless a separately configured authenticated deployment is provided. The supported MCP path is local stdio, not an exposed HTTP MCP endpoint.
- Attempt evidence intentionally retains submitted text, including rejected proposals. Treat the database, exports, backups and diagnostic artifacts as sensitive. Invalid Unicode is escaped for safe evidence storage; escaping is not redaction or encryption.
- Use an isolated disposable database for verification. Do not downgrade or recreate an existing data volume to run tests.

## Dependencies and support

Install the reviewed lock with `python -m pip install -r requirements.lock`, then install the source package with `python -m pip install --no-deps -e .`. Recheck advisories when preparing a release; a lockfile is a reproducibility record, not a permanent security guarantee.

The 2026-10-22 advisory review matched ten distinct GitHub advisories across five previous pins. Fixed boundaries were verified against advisory records and package metadata: AnyIO 4.14.2, certifi 2026.10.19, Mako 1.4.2, pytest 9.0.3 and Starlette 1.3.1. This was a package-version match, not a demonstration that all advisory paths were reachable in PatchDIFF. The HTTP app currently mounts health endpoints; it does not mount forms, static files or templates.

Primary advisory records: [AnyIO TLS](https://github.com/agronholm/anyio/security/advisories/GHSA-82r6-8w77-94w6), [AnyIO workers](https://github.com/agronholm/anyio/security/advisories/GHSA-5p39-cfhj-2xmp), [certifi](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2), [Mako](https://github.com/sqlalchemy/mako/security/advisories/GHSA-5639-2j2p-m4mx), [pytest](https://github.com/advisories/GHSA-6w46-j5rx-g56g), [Starlette forms](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq). Other matched Starlette records are retained in the release review.

No supported published-version matrix or security response SLA is established yet. Report the exact revision and dependency set. Container-image vulnerabilities, full Git history and representative production threat testing are separate checks; a dependency scan or local secret-signature scan does not certify their absence.
