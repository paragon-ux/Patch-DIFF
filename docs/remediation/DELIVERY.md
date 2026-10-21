# PR #1 remediation delivery

Starting PR #1 head:b33faaf332e269019747772602afff34f9829e5c. No PR or branch has been merged. The changes are an ordered stack of independently reviewed workstreams, each with active contracts, implementation, tests and source-pinned execution evidence.

| Scope | Fix / disposition | PR | Independent closure |
| --- | --- | --- | --- |
| DEV-RUN-001 | ecd0dfa +3d4daec; one new immutable0.2.2 profile, historical selector behavior preserved | #4,head2df23ed | DEV-RUN-001-review.md |
| DEV-RUN-002 | 893301e; safe reversible audited Unicode evidence, historical recovery and wrapper ownership | #5,headd8c71fe | DEV-RUN-002-review.md |
| DEV-SVC-001 | 3a7ddb0; separate NULL-key conflict rows, submitted fingerprints and immutable recovery | #6,headfda5adb | DEV-SVC-001-review.md |
| DEV-DB-001 | cd1b91f after contract-first9de0a64; raw content health, unchanged canonical hashes and no repair | #7,headdd5877d | DEV-DB-001-review.md |
| DEV-MCP-001/002 | production3b122df,finaltests69f6a64; context types, filtered paging, preserved display orders | #8,head226ab22 | DEV-MCP-001-002-review.md |
| DEV-SVC-002 /D01 | Retain existing parent identity by decision; document full existing canonical-record identity | Final docs PR pending | DEV-SVC-002-D01-review.md pending |
| V01/V06/V07/V09 | Verified actual READ COMMITTED blocking, caller ownership/lock lifetime and complete terminal recovery | #5/#6 | Unicode/conflict reports |

## Verification and source limits

Final integrated product run at69f6a64:834passed (613unit/221actual PostgreSQL integration),9existing Alembic warnings,37.52s. Real subprocess workflows and isolated populated migration tests are included; offline verdict equivalenceOK. Each runtime/service workstream also has separate outside-pytest PostgreSQL/stdio evidence and an independent reviewer readback or recheck. Exact commands, source pins and limits are in the per-stream tests/live/review files; passing counts alone do not establish closure.

Inspected generated-merge CI runs:PR#4 39542822860/3ee9105,PR#5 39567916478/4207996,PR#6 39569958566/d404924,PR#7 39570822144/20c66c5,PR#8 39572642874/b0444e2. All passed; actual checkout and test lines were inspected, not inferred from head status. The final docs PR will receive its own CI/publication record.

Final source audit: exactly one new runtime profile (0.2.2), no migrations/dependencies/new protocol operations/general rate limiter. Shared locked submit/reject helpers remain the persistence path; caller transactions are not committed by service helpers. Valid canonical_sha256 is unchanged, historical profiles/fingerprints remain recoverable, and no historical record is rewritten. All12 protected review-file SHA256 values match; no path under docs/reviews is changed. Original untracked Devin files are preserved.

Stronger isolation modes are not newly guaranteed; their transaction retry belongs to the caller. Parent identity for rejected/ineligible lineage retains supplied spelling, so an exact retry must preserve it. Optional F01-F14 features and the normalized-identity alternative are outside this release. Merge requires separate user approval.
