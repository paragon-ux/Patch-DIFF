# PatchDIFF Runtime Implementation Specification

## Implementation-Ready

### Version v0.2.3 — Build-Locked Runtime and Validator for PatchDIFF v0.2.3

```text
This implementation specification implements PatchDIFF v0.2.3 without architectural drift.

PatchDIFF remains:
- target-native
- language-agnostic
- append-only
- transactionally isolated
- replay-safe
- canonically serializable
- structurally pure
- deterministic
```

---

# 1. Purpose

This document converts the PatchDIFF v0.2.3 protocol into an implementation-ready runtime, validator, and persistence model.

The implementation must not introduce:

```text
ASTs
semantic parsing
fuzzy matching
model-generated executable logic
inferred repair
hidden mutation
partial commits
target-specific rewrite engines
automatic merge logic
```

PatchDIFF is a transactional textual state system.

The trusted runtime is:

```text
changeOperator.py
```

The model output is:

```text
PDCP declarative text
```

The canonical target is:

```text
cloud_target_file.current_content
```

---

# 2. Runtime Components

PatchDIFF v1 requires five runtime components.

```text
1. PDCP Parser
2. Protocol Validator
3. Transaction Validator
4. Transaction Applier
5. Append-Only Persistence Layer
```

## 2.1 PDCP Parser

Responsible for extracting:

```text
C target reference
manifest blocks
disambiguation metadata
MATCH/REPLACE blocks
change ordering
```

The parser does not interpret target semantics.

---

## 2.2 Protocol Validator

Responsible for validating PDCP structure.

It checks:

```text
C exists
C is well-formed
manifest exists for each change
required manifest fields exist
MATCH/REPLACE block syntax is valid
MATCH is non-empty
PDCP contains no executable logic outside payloads
change IDs are valid
```

---

## 2.3 Transaction Validator

Responsible for validating applicability against the current canonical target.

It checks:

```text
target exists
target hash/version preconditions pass
MATCH blocks resolve deterministically
disambiguation resolves ambiguity
sequential in-memory mutation semantics are respected
```

---

## 2.4 Transaction Applier

Responsible for applying changes in memory and committing atomically.

It performs:

```text
load canonical target
canonicalize target
simulate all replacements in memory
commit only final successful buffer
append logs
update hash/version
```

---

## 2.5 Append-Only Persistence Layer

Responsible for storing:

```text
cloud_target_file
current_pdcp_file
append_only_pdcp_log
append_only_manifest_ledger
snapshots
```

No accepted or rejected PDCP log entry may be modified after commit.

---

# 3. Canonicalization Pipeline

Canonicalization is mandatory before:

```text
MATCH evaluation
hash generation
transaction validation
transaction replay
target divergence detection
commit
```

## 3.1 Canonicalization Rules

The runtime must convert loaded target content into canonical text using these rules:

```text
encoding: UTF-8
newline form: LF
line-ending handling: normalize CRLF and CR to LF
tab handling: preserve tabs exactly
space handling: preserve spaces exactly
trailing whitespace: preserve exactly
trailing final newline: preserve exactly
Unicode normalization: none
```

```text
PatchDIFF performs no Unicode equivalence normalization.

MATCH operates on exact canonicalized Unicode codepoint sequences.

Visually equivalent Unicode representations may fail MATCH if their codepoint sequences differ.

Implementations must not silently apply NFC, NFD, NFKC, or NFKD normalization unless a future protocol version explicitly changes this rule.
```

## 3.2 Invalid UTF-8

If the uploaded target cannot be decoded as UTF-8:

```text
reject target initialization
failure_reason = target_encoding_invalid
```

Binary or richly formatted formats are unsupported unless converted into a stable UTF-8 textual representation before becoming a PatchDIFF target.

## 3.3 Canonicalization Boundary

Canonicalization applies to:

```text
target content
MATCH payload
REPLACE payload
```

It must not alter manifest text except for parsing line boundaries.

## 3.4 Normative Rule

```text
All runtimes must perform identical canonicalization before MATCH, hash, replay, and commit.
```

---

# 4. Hash Semantics

PatchDIFF uses SHA-256 over canonicalized UTF-8 target text.

```text
current_hash = SHA256(bytes(canonicalized_target_text, "utf-8"))
```

## 4.1 Hash Fields

```text
current_hash:
hash of current canonical target content

before_hash:
hash before transaction validation/application

after_hash:
hash after successful transaction application

target_hash:
optional PDCP precondition hash
```

## 4.2 Rejected Transactions

For rejected PDCPs:

```text
before_hash = hash at validation time
after_hash = null
```

## 4.3 Hash Mismatch

If `target_hash` is supplied and does not equal `current_hash`:

```text
reject transaction
failure_reason = target_hash_mismatch
```

No MATCH evaluation should proceed after a hard hash mismatch.

---

# 5. PDCP Parsing Rules

A PDCP file must have:

```text
C = "target_file_id:<id>"
one or more change blocks
```

Each change block must have:

```text
MANIFEST
optional disambiguation comments
MATCH/REPLACE block
```

## 5.1 Required Manifest Fields

```text
change_id
intent
input_state
output_state
affected_region
user_visible_change
risk
```

## 5.2 Valid Risk Values

```text
low
medium
high
```

Any other value:

```text
failure_reason = manifest_invalid
```

## 5.3 Change ID Rules

`change_id` must be unique within a PDCP transaction.

Duplicate `change_id` values:

```text
failure_reason = manifest_invalid
```

Recommended format:

```text
chg_<integer>
```

The implementation may allow other stable strings, but must reject empty IDs.

---

# 6. Structural Purity Enforcement

Executable-logic detection applies only outside MATCH/REPLACE payloads.

## 6.1 Structural Regions

The following are PDCP structural regions:

```text
C assignment
manifest comments
disambiguation comments
text outside MATCH/REPLACE blocks
```

The following are payload regions:

```text
MATCH content
REPLACE content
```

## 6.2 Prohibited Structural Content

Outside MATCH/REPLACE payloads, reject obvious executable constructs:

```text
imports
functions
loops
conditionals
network calls
filesystem calls
shell commands
dynamic evaluation
external package references
```

If detected:

```text
failure_reason = executable_logic_detected
```

## 6.3 Payload Rule

MATCH/REPLACE payloads are opaque target-native text.

They may contain code, imports, functions, shell snippets, or other executable-looking text if that content belongs to the target file.

The operator must never execute payload text.

---

# 7. Deterministic MATCH Evaluation

MATCH evaluation operates on the current canonicalized in-memory target buffer.

For each change, the operator must:

```text
1. Take the current in-memory buffer.
2. Treat MATCH as a Unicode codepoint sequence after canonicalization.
3. Search the entire current in-memory buffer.
4. Identify all exact full-span occurrences.
5. Apply disambiguation if needed.
6. Select exactly one span or reject.
```

## 7.1 Matching Properties

MATCH evaluation is:

```text
exact
case-sensitive
whitespace-sensitive after canonicalization
multiline
left-to-right over the full current in-memory buffer
```

The operator must not perform:

```text
fuzzy matching
semantic matching
token-level matching
language-aware matching
format-aware matching
repair
fallback matching
```

## 7.2 Zero Matches

If no exact occurrence exists:

```text
failure_reason = match_absent
failed_change_id = current change_id
```

## 7.3 Multiple Matches

If more than one occurrence exists:

```text
attempt disambiguation if metadata exists
```

If disambiguation is absent or insufficient:

```text
failure_reason = match_ambiguous
failed_change_id = current change_id
```

## 7.4 Deterministic Scan Rule

The implementation must scan left-to-right over Unicode codepoint positions.

Ambiguity detection must count all full-span exact occurrences before selecting a span.

---

# 8. Disambiguation Semantics

Optional disambiguation fields:

```text
anchor_before
anchor_after
occurrence_index
region_hint
target_hash
```

## 8.1 Disambiguation Ordering

Disambiguation is applied only after multiple exact MATCH occurrences are found.

The runtime must not use disambiguation to perform fuzzy or semantic search.

## 8.2 `target_hash`

If present, `target_hash` is checked before MATCH evaluation.

Mismatch:

```text
failure_reason = target_hash_mismatch
```

## 8.3 `occurrence_index`

`occurrence_index` is 1-based over the ordered list of exact MATCH occurrences.

If the index is invalid:

```text
failure_reason = disambiguation_invalid
```

## 8.4 `anchor_before` and `anchor_after`

Anchors constrain the selected MATCH occurrence.

A candidate span is valid only if:

```text
anchor_before appears before the candidate span
anchor_after appears after the candidate span
```

Both anchors are exact text constraints after canonicalization.

If anchors resolve to zero or multiple candidate spans:

```text
failure_reason = disambiguation_invalid
```

## 8.5 `region_hint`

`region_hint` is advisory only.

It may be used for diagnostics or UI display.

It must not by itself select a span.

---

# 9. Replacement Semantics

## 9.1 Immediate Mutation

After a MATCH span is selected:

```text
replace selected span with REPLACE text immediately in the in-memory buffer
```

The next change is evaluated against this mutated buffer.

PatchDIFF does not stage all replacements against the original target.

## 9.2 Deletion

```text
MATCH non-empty + REPLACE empty = deletion
```

Whitespace-only REPLACE is valid.

## 9.3 Insertion

Zero-length MATCH is invalid.

Pure insertion must be represented as anchored replacement:

```text
MATCH = existing non-empty anchor text
REPLACE = same anchor text + inserted content
```

## 9.4 Overlap

Overlapping edits are allowed only if sequentially valid.

A later change may modify text affected by an earlier change only if its MATCH block matches the updated in-memory buffer.

No semantic merge occurs.

```text
Subsequent MATCH blocks may target content introduced by earlier REPLACE operations within the same PDCP transaction.

This is valid only because each change is evaluated against the progressively updated in-memory buffer.

The same rule applies to overlapping edits: the later MATCH must succeed against the current in-memory transaction state.
```

---

# 10. Transaction Semantics

A PDCP file is the smallest atomic commit unit.

Partial acceptance is forbidden.

## 10.1 Transaction Flow

```text
1. Parse PDCP.
2. Protocol-validate PDCP.
3. Load canonical cloud target.
4. Validate hash/version preconditions.
5. Initialize in-memory buffer from canonical target.
6. For each change in order:
   a. Evaluate MATCH against current in-memory buffer.
   b. Resolve ambiguity.
   c. Apply REPLACE immediately in memory.
7. Compute after_hash.
8. Commit target + logs atomically.
```

## 10.2 Atomic Commit

No cloud target mutation may occur until all changes succeed in memory.

If any step fails:

```text
target remains unchanged
PDCP log records rejection
manifest ledger is not appended as accepted
```

```text
A successful commit is defined only by atomic persistence of all of the following:

- target content update
- target hash update
- target version update
- accepted PDCP log entry
- accepted manifest ledger entries

No committed target state may exist without a corresponding accepted PDCP log entry.

No accepted manifest ledger entry may exist without a corresponding accepted PDCP log entry.
```

## 10.3 Rollback

Rollback is implemented by never committing partial state.

If an unexpected error occurs before commit:

```text
target remains unchanged
PDCP log records transaction_internal_error if possible
```

If an unexpected error occurs during commit, the storage layer must guarantee atomicity through a database transaction or equivalent atomic write mechanism.

---

# 11. Persistence Model

## 11.1 Tables / Collections

### `cloud_target_file`

```text
target_file_id
current_content
current_hash
version
created_at
updated_at
```

### `current_pdcp_file`

```text
pdcp_file_id
target_file_id
content
status
created_at
updated_at
```

### `append_only_pdcp_log`

```text
pdcp_log_id
target_file_id
pdcp_content
protocol_version
status
failure_reason
failure_detail
failed_change_id
before_hash
after_hash
created_at
```

### `append_only_manifest_ledger`

```text
manifest_entry_id
target_file_id
pdcp_log_id
change_id
intent
input_state
output_state
affected_region
user_visible_change
risk
created_at
```

### `target_snapshots`

```text
snapshot_id
target_file_id
content_hash
content
version
created_at
reason
```

```text
Snapshots are replay acceleration artifacts only.

Snapshots are not authoritative protocol state.

The authoritative reconstruction path is:

initial canonical target
+ ordered accepted PDCP log entries
= reconstructed canonical target
```
### current_pdcp_file Lifecycle


`current_pdcp_file` stores the most recent submitted PDCP content for the active editing cycle.

It is not authoritative protocol state.

The authoritative operational history is `append_only_pdcp_log`.

On PDCP submission:
```text
- current_pdcp_file is updated with the submitted PDCP content and status = pending
- after validation/application, status is updated to accepted or rejected
- the full PDCP content is appended to append_only_pdcp_log
```
`current_pdcp_file` may be overwritten by later submissions.

It is used for UI inspection and active-session display only.

Replay must never depend on `current_pdcp_file`.

---

# 12. Append-Only Guarantees

The following are append-only:

```text
append_only_pdcp_log
append_only_manifest_ledger
target_snapshots
```

No update or delete operations are allowed on committed log rows.

Corrections must be represented by new transactions.

The cloud target file may be updated only by successful atomic PDCP commits or SAVE/snapshot operations.

---

# 13. Cloud-State Consistency

PatchDIFF v1 assumes one active writer per target editing cycle.

## 13.1 Required Write Guard

Each transaction must include an optimistic write guard:

```text
expected_target_version
or
expected_current_hash
```

Before commit, the runtime must verify the stored target still matches the version/hash used during validation.

If not:

```text
failure_reason = target_diverged
```

No target mutation occurs.

## 13.2 Transaction Isolation

A runtime must hold transaction isolation across:

```text
target read
validation
in-memory application
commit
log append
manifest append
hash/version update
```

Recommended implementation:

```text
database transaction
row-level target lock
compare-and-swap on version/hash
```

Do not allow two commits to the same target to interleave.

---

# 14. Failure Handling

Every rejected PDCP must record:

```text
status = rejected
failure_reason
failure_detail
failed_change_id when applicable
before_hash
after_hash = null
```

## 14.1 Failure Reason Labels

```text
context_missing
context_invalid
target_not_found
target_encoding_invalid
manifest_missing
manifest_invalid
block_malformed
match_absent
match_ambiguous
disambiguation_invalid
target_hash_mismatch
target_version_mismatch
target_diverged
executable_logic_detected
sequential_match_invalid
transaction_internal_error
```

## 14.2 Failure Classification

Protocol-invalid failures:

```text
context_missing
context_invalid
manifest_missing
manifest_invalid
block_malformed
executable_logic_detected
target_encoding_invalid
```

Transaction-invalid failures:

```text
target_not_found
match_absent
match_ambiguous
disambiguation_invalid
target_hash_mismatch
target_version_mismatch
target_diverged
sequential_match_invalid
```

Internal runtime failures:

```text
transaction_internal_error
```

---

# 15. Replay Semantics

Replay must be deterministic across environments.

## 15.1 Replay Inputs

Replay requires:

```text
initial canonical target content
ordered accepted PDCP log entries
protocol version for each PDCP
canonicalization rules for each protocol version
```

## 15.2 Replay Algorithm

```text
1. Load initial target.
2. Canonicalize using the PDCP entry’s protocol version rules.
3. For each accepted PDCP in order:
   a. parse PDCP
   b. validate protocol
   c. apply transaction deterministically
   d. verify computed after_hash equals logged after_hash
4. Output reconstructed target.
```

If computed hash differs from logged hash:

```text
replay failure
reason = replay_hash_mismatch
```

This should be treated as data corruption or implementation incompatibility.

## 15.3 Protocol Versioning

Each PDCP log entry must include:

```text
protocol_version
```

For v1 implementation:

```text
protocol_version = "0.2.3"
```

Future protocol versions must preserve old replay behavior.

---

# 16. SAVE Implementation

SAVE is a compaction checkpoint.

## 16.1 SAVE Flow

```text
1. Load current target.
2. Verify current_hash.
3. Create target snapshot.
4. Export finalized target if requested.
5. Mark editing cycle complete.
6. Clear manifest ledger context for next cycle only after snapshot succeeds.
7. Preserve PDCP log.
```

## 16.2 SAVE Failure

If SAVE fails:

```text
target remains canonical
manifest ledger remains intact
PDCP log remains replayable
SAVE may be retried
```

Never clear manifest context before snapshot/export success.

---

# 17. Runtime API

## 17.1 Initialize Target

```text
POST /targets
```

Input:

```json
{
  "filename": "example.md",
  "content": "...",
  "content_type": "text/markdown"
}
```

Behavior:

```text
validate UTF-8
canonicalize
compute current_hash
store cloud_target_file
create initial snapshot
```


---

## 17.2 Submit PDCP

```text
POST /targets/{target_file_id}/pdcp
```

Input:

```json
{
  "pdcp_content": "...",
  "expected_target_version": 3,
  "expected_current_hash": "..."
}
```

Behavior:

```text
parse
protocol-validate
transaction-validate
apply atomically or reject
append PDCP log
append manifest ledger only on success
return result
```

---

## 17.3 Get Target

```text
GET /targets/{target_file_id}
```

Returns:

```json
{
  "target_file_id": "...",
  "current_content": "...",
  "current_hash": "...",
  "version": 4
}
```

---

## 17.4 Get Manifest Ledger

```text
GET /targets/{target_file_id}/manifest-ledger
```

Returns accepted manifest entries only.

Rejected PDCP manifests are not included in LLM context.

---

## 17.5 Get PDCP Log

```text
GET /targets/{target_file_id}/pdcp-log
```

Returns accepted and rejected PDCP log entries.

---

## 17.6 SAVE

```text
POST /targets/{target_file_id}/save
```

Behavior:

```text
snapshot target
export if requested
clear active manifest context only after success
preserve PDCP log
```

---
## 17.7 Restore Target to Version

```text
POST /targets/{target_file_id}/restore

Input:

{
  "target_version": 3
}
```

```text
Behavior:

1. Reconstruct target state by replaying accepted PDCP log entries up to target_version.
2. Verify reconstructed hash.
3. Commit restored content as a new PDCP-controlled system transaction.
4. Append a restoration entry to append_only_pdcp_log.
5. Update current_hash and version.
```

Rollback does not mutate history.

Rollback creates a new forward transaction that restores prior content.
---

# 18. Reference `changeOperator.py` Pseudocode

```python
def apply_pdcp(target_id, pdcp_content, expected_version=None, expected_hash=None):
    parsed = parse_pdcp(pdcp_content)

    protocol_result = validate_protocol(parsed)
    if not protocol_result.ok:
        return reject(protocol_result)

    with db.transaction():
        target = db.get_target_for_update(target_id)

        if target is None:
            return reject_reason("target_not_found")

        canonical = canonicalize(target.current_content)
        before_hash = sha256_utf8(canonical)

        if expected_version is not None and target.version != expected_version:
            return reject_reason("target_version_mismatch", before_hash=before_hash)

        if expected_hash is not None and before_hash != expected_hash:
            return reject_reason("target_hash_mismatch", before_hash=before_hash)

        buffer = canonical

        for change in parsed.changes:
            match = canonicalize_payload(change.match_text)
            replace = canonicalize_payload(change.replace_text)

            if match == "":
                return reject_reason("block_malformed", change_id=change.id)

            occurrences = find_exact_occurrences(buffer, match)

            selected = resolve_occurrence(occurrences, change.disambiguation)

            if not selected.ok:
                return reject(selected.failure)

            buffer = (
                buffer[:selected.start]
                + replace
                + buffer[selected.end:]
            )

        after_hash = sha256_utf8(buffer)

        db.update_target(
            target_id=target_id,
            content=buffer,
            current_hash=after_hash,
            version=target.version + 1
        )

        log_id = db.append_pdcp_log(
            target_id=target_id,
            pdcp_content=pdcp_content,
            protocol_version="0.2.3",
            status="accepted",
            before_hash=before_hash,
            after_hash=after_hash
        )

        db.append_manifest_entries(log_id, parsed.manifests)

        return accepted(after_hash=after_hash)
```

---

# 19. Required Test Matrix

The implementation is not complete until these tests pass.

## 19.1 MATCH Tests

```text
exact single match succeeds
zero match rejects match_absent
duplicate match rejects match_ambiguous
case mismatch rejects match_absent
whitespace mismatch rejects match_absent
multiline match succeeds
CRLF target canonicalizes to LF
```

## 19.2 Sequential Mutation Tests

```text
second MATCH sees first REPLACE mutation
second MATCH against original state fails
overlapping sequential edits succeed when valid
overlapping sequential edits fail when invalid
```

## 19.3 Edge Case Tests

```text
empty MATCH rejects
empty REPLACE deletes
whitespace-only REPLACE succeeds
anchored insertion succeeds
zero-length insertion rejects
```

## 19.4 Security Boundary Tests

```text
function outside payload rejects
import outside payload rejects
function inside MATCH payload allowed
function inside REPLACE payload allowed
shell-looking text inside payload allowed
```

## 19.5 Transaction Tests

```text
one failed change rolls back all changes
no manifest ledger entry on rejection
rejected PDCP log is appended
accepted PDCP log is appended
before_hash and after_hash correct
```

## 19.6 Replay Tests

```text
accepted log replay reconstructs target
replay after_hash matches logged after_hash
replay fails on altered log entry
replay is stable across LF/CRLF inputs after canonicalization
```

## 19.7 Divergence Tests

```text
target_hash mismatch rejects
target_version mismatch rejects
concurrent commit causes target_diverged
stale MATCH rejects without mutation
```
## 19.8 Parser-Conformance Tests
```text
known-valid PDCP corpus parses successfully
known-invalid PDCP corpus rejects deterministically
parser output is stable across runtimes
```

---

# 20. Build-Lock Criteria

PatchDIFF implementation is build-ready when:

```text
canonicalization is deterministic
MATCH evaluation is deterministic
transactions are atomic
logs are append-only
replay reconstructs target
failure labels are complete
payload security boundaries are enforced
SAVE cannot clear ledger on failure
independent runtimes can reproduce accepted outcomes
```

---

# 21. Final Runtime Lock

```text
PatchDIFF v0.2.3 runtime =
canonical UTF-8 target text
+ declarative PDCP
+ exact deterministic MATCH
+ immediate sequential REPLACE
+ atomic commit
+ append-only log
+ semantic manifest ledger
+ deterministic replay
```

---

# 22. Deferred Work

```text
Unicode normalization handling is deferred.

PatchDIFF v0.2.3 performs no Unicode equivalence normalization. A future protocol version may optionally support per-target NFC normalization, but such support would require a new protocol version because it changes MATCH and hash semantics.

```

No remaining behavior is intentionally left undefined for v1 implementation.
