# PatchDIFF MCP-First MVP Final Checklist

Use this after the implementation phases are complete.

## Architecture Boundary

- [ ] Repo follows MCP-first architecture.
- [ ] No frontend or chat UI is part of the MVP implementation.
- [ ] MCP orchestration is separate from deterministic core runtime.
- [ ] Service layer coordinates workflows without duplicating core logic.
- [ ] Deterministic core runtime has no MCP/model/prompt dependencies.
- [ ] MCP tools cannot mutate targets directly.
- [ ] MCP tools cannot bypass `patchdiff_submit_pdcp` validation path.

## PDCP Format

- [ ] `.pdcp` extension is used for transaction files.
- [ ] PDCP header is protocol-native, not Python-style `C = ...`.
- [ ] `PDCP 0.2.3` header is required.
- [ ] `target_file_id` and `target_type` are required.
- [ ] Optional `target_hash` behavior is implemented.
- [ ] Manifest required fields are enforced.
- [ ] Optional disambiguation fields are parsed.
- [ ] MATCH/REPLACE delimiters are implemented.
- [ ] Delimiter collision rejects deterministically.
- [ ] Empty MATCH rejects.
- [ ] Empty REPLACE deletes.
- [ ] Anchored insertion works.
- [ ] PDCP remains declarative and non-executable.

## Deterministic Core

- [ ] Canonicalization normalizes CRLF/CR to LF.
- [ ] Tabs, spaces, trailing whitespace, and final newline are preserved.
- [ ] No Unicode normalization is applied.
- [ ] Hashing uses SHA-256 over canonical UTF-8 bytes.
- [ ] Exact MATCH is case-sensitive, whitespace-sensitive, and multiline.
- [ ] Disambiguation resolves only exact candidates.
- [ ] No fuzzy matching exists.
- [ ] No semantic matching exists.
- [ ] No AST matching exists.
- [ ] No generated code execution exists.
- [ ] Sequential mutation applies changes against progressively updated buffer.
- [ ] `sequential_match_invalid` is distinguishable from ordinary `match_absent`.
- [ ] Multi-change failure rejects the whole transaction.
- [ ] No partial commits are possible.

## Failure Labels And Diagnostics

- [ ] Canonical ordinary rejection labels are implemented.
- [ ] Replay-only labels are separate.
- [ ] No unapproved labels are introduced.
- [ ] Accepted responses include before_hash, after_hash, version, log ID.
- [ ] Rejected responses include failure_reason, failure_detail, failed_change_id when applicable.
- [ ] Rejected responses include after_hash = null.
- [ ] Diagnostic JSON is advisory only.
- [ ] Diagnostics do not affect transaction semantics.

## Postgres Persistence

- [ ] Docker Compose runs pinned Postgres.
- [ ] Alembic migrations create the schema.
- [ ] SQLite is not used for MVP persistence.
- [ ] `cloud_target_files` is authoritative current target state.
- [ ] `current_pdcp_files` is mutable/non-authoritative display state.
- [ ] `append_only_pdcp_logs` stores accepted and rejected attempts.
- [ ] `append_only_manifest_ledger` stores accepted manifests only.
- [ ] `target_snapshots` stores initial and SAVE snapshots.
- [ ] `editing_cycles` supports one active cycle per target.
- [ ] `diagnostic_json JSONB NULLABLE` exists on PDCP logs if selected.
- [ ] Regeneration lineage fields exist where specified.
- [ ] Append-only behavior is enforced in repository/application code.
- [ ] MVP+ database triggers/roles are documented but not required.

## Transactions And Locking

- [ ] Accepted PDCP commit is one Postgres transaction.
- [ ] Target row is locked with `FOR UPDATE`.
- [ ] Expected version/hash guards are checked.
- [ ] Accepted transaction updates target and inserts log/ledger atomically.
- [ ] Rejected transaction logs rejection without target mutation.
- [ ] Same-target writes cannot interleave.
- [ ] Different targets can commit independently.
- [ ] `target_version_mismatch`, `target_hash_mismatch`, and `target_diverged` are distinct as documented.

## SAVE And Replay

- [ ] SAVE creates snapshot.
- [ ] SAVE closes current editing cycle.
- [ ] SAVE opens one new active editing cycle.
- [ ] SAVE does not mutate target content.
- [ ] SAVE preserves logs and ledger history.
- [ ] SAVE failure leaves old active cycle intact.
- [ ] Replay reconstructs from initial canonical target plus accepted PDCP logs.
- [ ] Replay ignores current_pdcp_files.
- [ ] Replay ignores manifest ledger and snapshots as authoritative history.
- [ ] Replay verifies after_hash after each accepted log.
- [ ] Replay failure labels are correct.

## MCP Orchestration

- [ ] Upload event initializes target.
- [ ] Prompt context includes target metadata, version/hash, manifest summary, user request, target spans, and PDCP rules.
- [ ] Model PDCP response is stored as pending current PDCP.
- [ ] Submission goes through deterministic core.
- [ ] Accepted status returns to MCP caller.
- [ ] Rejected diagnostics return to MCP caller.
- [ ] Regeneration context/prompt can be built after rejection.
- [ ] Regenerated PDCP submits as a new attempt.
- [ ] Parent rejected attempt remains logged.
- [ ] Export returns current canonical target.
- [ ] SAVE and replay can be triggered through MCP.

## Tests

- [ ] Core parser/protocol unit tests pass.
- [ ] Canonicalization and hashing tests pass.
- [ ] Exact matching and disambiguation tests pass.
- [ ] Transaction applier tests pass.
- [ ] Postgres migration/integration tests pass.
- [ ] Atomic commit tests pass.
- [ ] Row-level locking/divergence tests pass.
- [ ] SAVE tests pass.
- [ ] Replay tests pass.
- [ ] MCP upload/context/submit/export tests pass.
- [ ] MCP regeneration orchestration tests pass.
- [ ] End-to-end smoke test passes.
- [ ] No tests rely on SQLite for persistence correctness.

## Deferred Work Confirmed

- [ ] Frontend/debug console deferred.
- [ ] Stream-intercepted partial PDCP handling deferred.
- [ ] Restore-to-version deferred.
- [ ] Rich/binary document targets deferred.
- [ ] Semantic validation deferred.
- [ ] AST parsing deferred.
- [ ] Fuzzy repair deferred.
- [ ] Production auth/billing deferred.

## MVP Exit

MVP is complete when:

- [ ] Upload initializes canonical target.
- [ ] Prompt context can be built.
- [ ] Valid `.pdcp` applies atomically.
- [ ] Invalid `.pdcp` rejects without mutation.
- [ ] Accepted and rejected attempts are append-only logged.
- [ ] Manifest ledger appends only on accepted transactions.
- [ ] Regeneration flow creates separate attempts validated from scratch.
- [ ] SAVE advances editing cycle without altering target content.
- [ ] Replay reconstructs target deterministically.
- [ ] Export returns canonical current target.
- [ ] MCP orchestration cannot bypass deterministic core validation.
