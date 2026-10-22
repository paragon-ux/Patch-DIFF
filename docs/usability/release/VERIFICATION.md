# Release verification evidence

Recorded 2026-10-22. This is unpublished verification evidence for [PR #12](https://github.com/paragon-ux/Patch-DIFF/pull/12), stacked on [PR #11](https://github.com/paragon-ux/Patch-DIFF/pull/11). The owner authorized merging the dependent PR into PR #11 after checks, with PR #11 held for an additional review before any main-branch merge. No tag, release or package upload is authorized by these results.

The [integration review](../../reviews/integration-973ba79-review.md) and [release-readiness review](../../reviews/release-readiness-973ba79-review.md) independently rechecked their findings and the evidence below. Their original source inventories remain pinned; subsequent fixes and execution revisions are explicitly recorded in their addenda.

## Source suite and dependency checks

The full source suite executed commit `57dd7c44b7fbd2e421abaa087591526f0de7037c` with Python 3.11.9 on Windows in an isolated environment containing the corrected 40 pinned dependencies. `PYTHONPATH=.;backend` selected checkout source, even though the separate installed-wheel smoke test used that environment too. A new PostgreSQL database, `patchdiff_release_suite_20261022`, was migrated to head before execution.

`python -m pytest --junitxml=<capture-path>` passed **1,144 cases: 755 unit and 389 integration, zero failures, errors or skips**, in 131.020 seconds. The XML and console output are retained separately. Ten deprecation warnings remain: nine Alembic path-splitting warnings and one supported Starlette/httpx TestClient warning. The offline evaluator passed historical format equivalence with its named legacy delimiter exception and all five replacement content/hash oracles. `pip check` reported no broken requirements; the manifest records the actual installed versions.

The initial dependency advisory query identified ten distinct advisories affecting five lock pins. Their corrected versions and advisory records are retained; the subsequent exact 40-pin OSV query returned no matches. This is a dated Python-package advisory check, not a complete security or container assessment. Worktree and Git-blob lock hashes are recorded separately because their newline bytes differ.

## Installed artifact and live workflow

A clean `git archive` of commit `9473e8bdfc64ae2c2630146af53e2c3428f1ca55` produced the corrected wheel, SHA-256 `5b132265d6243a77faec627727b26a71ca20bb90394fcf4040f84ac3ac12fcca` (83,108 bytes). Subsequent changes through the suite revision affect documentation only. The wheel contains the MIT license, README metadata and both migration assets, and excludes the accidentally discovered test packages. The initial defective wheel and corrected archive/wheel remain local unpublished artifacts with hashes in the manifest; binaries and virtual environments are not committed.

The retained helper ran outside the checkout, removed `PYTHONPATH` and locale overrides, verified all 48 installed application Python files against the wheel, and applied packaged migrations to a separate fresh database, `patchdiff_release_package_20261022`. It executed 13 actual raw JSON-RPC exchanges over stdio: initialization, discovery, Unicode upload, advisory preview, whole-target replacement, span edit, typed match, legacy PDCP, exact-key recovery after later edits, line read, SAVE, replay and export. Discovery exposed 20 tools with 13 examples; this smoke test does not claim to execute every example. The earlier feature verification separately executed all advertised pairs.

Independent read-only SQL confirmed target `ca1cefbd-9fd6-41ff-9b24-2f2093370973` ended at version 4 with text `!ready 中\n` (a trailing LF), exactly four accepted attempts across the four format/profile pairs, and four ledger facts. Preview and recovered submissions added no attempts. All replay component checks passed. Both health routes returned HTTP 200 from a real Uvicorn process loading the installed package. Reviewers independently decoded the captured bytes, recomputed hashes and queried PostgreSQL.

The first manual setup attempt timed out because the existing PostgreSQL container was paused; its separate log is preserved. No product assertions or pytest cases ran in that attempt. The container was unpaused, without recreating it or its volumes, before successful verification. The source Compose configuration now binds development PostgreSQL to loopback; the existing container retains its previous mapping until its owner recreates it.

## Identity and limits

[MANIFEST.json](MANIFEST.json) identifies the exact capture bytes, source revisions, environment and unpublished build artifacts. Git attributes preserve capture bytes without newline conversion. Historical failed executions remain in their original feature verification records and are not relabeled as this successful run.

Final published-head and generated-merge CI must be checked at their actual checkout revisions after the evidence commit. Those logs stay with the PR/task artifacts to avoid a documentation-only CI loop. The implementation owner performs the final evidence-only delta recheck; the two independent review agents have completed their work and were stopped at the owner's request.

Private security reporting was disabled when checked and must be established before publication. Intended-container/deployment assessment, representative performance evidence, broader platform testing, full-history secret scanning, final merged artifact identity, and explicit version/tag/publication approval remain outside this verification. See [release preparation](../../RELEASE_READINESS.md) and [security guidance](../../../SECURITY.md).
