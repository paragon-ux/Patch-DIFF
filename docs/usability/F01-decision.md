# F01 pre-code decision: immutable failure evidence and fresh bounded context

Status: accepted implementation decision within user-authorized Goal F revision 2; base SHA 2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10 (approved PR #1 merge to main).

## Scope

F01 adds bounded rejection visibility to the existing locked submit path. It does not change matching, application, fingerprint identity, accepted replay records, transaction ownership, runtime profiles, or the qualified audit guarantee. F05 near-miss comparison and F06 candidate search remain separate features.

## Public representations

Persist diagnostic.failure_context only for newly recorded rejected attempts. It describes the original failure buffer and never changes on exact keyed recovery. Return a separate top-level current_context on rejected submission responses, describing the currently locked canonical target view. Reconstruct no historical failure context when an older row lacks it. Accepted response shapes remain unchanged.

Each available context contains: available=true; selection='prefix'; buffer_stage='canonical_target' or 'intermediate_buffer'; prior_changes; zero-based start and end-exclusive end; total_chars; text; truncated; observed_target_version; observed_target_hash. The observed identity names the target at transaction start, never a hash/version of uncommitted intermediate text. prior_changes counts already simulated edits; it is zero for the canonical buffer. The shared outer failed_change_id is not duplicated.

Unavailable contexts contain available=false and a bounded enum unavailable_reason (invalid_target_id, target_not_found, or unlocked_local_state); text, spans, length, stage, selection, prior_changes and observed identity are null. Distinguish an available empty target (empty text, zero spans, not truncated) from unavailable context. Pending caller-local dirty ORM state has no authoritative locked context, even if legacy fields contain local values.

## Numeric budgets and selection

Select a prefix of at most 256 Unicode code points, retaining the longest prefix within that bound that also fits the serialized byte budget below. Normal managed target hashes are 64 hexadecimal characters, so the normal case retains min(256, len(buffer)) points. No additional full-document scan or hash is performed for context selection. start=0; end equals the retained code-point length. Offsets are code points, not UTF-16 units or UTF-8 bytes. truncated means the context omits a suffix, including an additional suffix removed to satisfy the byte cap.

Each complete context is limited to 4,096 bytes of compact ASCII-escaped JSON. The combined failure_context/current_context enrichment, including their wrapper keys, is limited to 8,192 such bytes. Enforce caps using actual serialization, including wrapper-key overhead; reduce retained prefix text if needed, never identity fields. Test non-BMP/control escaping, maximum integer metadata and deliberately non-ASCII corrupted stored hashes (the database column limits length but does not enforce hexadecimal content). Do not include arbitrary proposer strings in these bounded contexts. Bound any cap adjustment to the already captured prefix; no unbounded scan or extra target hash.

For pure application failures, capture only the bounded prefix and counts from the actual buffer before the failing operation, while that buffer still exists. Do not retain an unbounded failed buffer in a result object. First-change failures use canonical_target; later simulated-change failures use intermediate_buffer. Service/precondition/protocol/lineage errors use the known locked canonical target. Prefix context does not claim to locate an absent match or a nearest candidate.

## Recovery, persistence and ownership

Add original context before durable rejection diagnostic serialization, once through the existing rejection helper. On deduplication, preserve the stored diagnostic exactly; build only response-only current_context from the refreshed locked target. Do not overwrite terminal evidence with a newer observation. Unknown targets and the pre-lock dirty-state path must explicitly return unavailable context.

Capture cheap bounded text within the existing transaction. Keep caller transactions uncommitted and their locks untouched; responses describe a locked transaction view that may remain provisional until caller commit. No expensive enrichment, background task or post-commit machinery is needed for F01.

## Contract-first edits

Before product implementation, reconcile architecture C1/C4/C6, MCP_TOOLS, core diagnostic/result wording, DATA_MODEL diagnostic JSON and host guidance. Update relevant workspace skill instructions and the as-built record without altering protected historical reviews. No migration or execution-profile bump.

## Acceptance

Test stale guards, protocol/lineage/encoding failures, missing and ambiguous matches, first and later sequential-buffer failure, empty and capped contexts, non-BMP/escape byte limits, malformed/missing targets, dirty local state and stale ORM refresh. On keyed rejection recovery after later accepted edits, assert byte-for-byte original diagnostic stability and a separately changed fresh context. Confirm target/version/ledger nonmutation, one attempt per admitted new rejection, and caller rollback/commit ownership.

Use focused pure/service tests for the full matrix plus representative actual PostgreSQL and real public stdio. Add manual outside-pytest raw-byte submissions with independent SQL evidence, run required suites/offline checks, and obtain an independent ten-category recheck on a source-pinned commit. Keep F08/F13/F14 evidence closures distinct from feature implementation.

