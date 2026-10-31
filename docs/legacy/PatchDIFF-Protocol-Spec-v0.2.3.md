
# PatchDIFF Protocol Specification

## Cloud-Backed Transactional MATCH/REPLACE for LLM-Generated Edits

### Version 0.2.3 — Build-Locked Draft Specification

```text
PatchDIFF v0.2.3 is build-locked for single-active-writer v1. Remaining open problems are empirical or future-extension concerns, not blockers for implementation.
```

---

## 1. Purpose

PatchDIFF is a cloud-backed, append-only transactional editing protocol for LLM-generated edits.

It allows an LLM to emit a **PDCP file** containing semantic manifests and target-native textual state transitions. A deterministic operator then applies those transitions directly against a canonical cloud target through in-place `MATCH/REPLACE` operations.

PatchDIFF is designed to avoid:

* full-document rewrites
* arbitrary model-generated code execution
* AST mutation
* normalized intermediate documents
* target-format translation
* tool-call orchestration
* filesystem synchronization problems

The core idea is:

```text
LLM emits declarative PDCP
→ PatchDIFF validates protocol structure
→ PatchDIFF validates transaction applicability
→ changeOperator.py applies exact target-native edits
→ cloud target updates atomically
→ manifest ledger stores semantic memory
```

---

## 2. Core Definition

PatchDIFF is **not** a patch language.

PatchDIFF is a **transport and validation protocol for target-native textual state transitions**.

The target file remains authoritative. PDCP does not own the document structure. The operator does not understand the target language. It only verifies and applies exact textual transitions.

---

## 3. Core Architecture Statement

> PatchDIFF is a cloud-backed, append-only transactional editing protocol in which LLMs emit PDCP files containing semantic manifests and target-native textual state transitions. `changeOperator.py` applies these transitions directly against canonical cloud targets through deterministic in-place `MATCH/REPLACE` operations, without normalization, AST construction, language translation, or executable model-generated code.

---

## 4. Protocol Scope

PatchDIFF v0.2.3 assumes **one active writer per target editing cycle**.

An active writer may be:

```text
one user
one LLM session
one editing workflow
```

PatchDIFF v0.2.3 does **not** attempt to merge simultaneous edits from multiple writers.

Concurrent edits from another user, model, browser session, or external process are treated as **target divergence**.

Divergence is detected through:

```text
target_hash mismatch
MATCH failure
ambiguous MATCH
version mismatch
```

When divergence is detected, PatchDIFF rejects the PDCP transaction rather than attempting to merge it.

### 4.1 Future Multi-Writer Extension

PatchDIFF’s append-only PDCP log creates a natural substrate for future multi-writer coordination.

A future version may support multi-active-writer workflows through:

```text
global patch log
shared cloud target version
writer/session IDs
total ordering of accepted PDCP transactions
duplicate detection
conflict detection
future conflict-resolution mechanisms
```

This is not part of v0.2.3.

The current rule is:

```text
v0.2.3: detect and reject conflicts
future: resolve conflicts when safe
```

---

## 5. System Objects

### 5.1 Cloud Target File

The cloud target file is the canonical working object.

It may be:

* Markdown
* Python
* YAML
* JSON
* HTML
* plain text
* another text-like target format

The target is edited **in-place**.

PatchDIFF does not create a normalized document, AST, semantic representation, or intermediate editing format.

---

### 5.2 PDCP File

A PDCP file is the model-emitted change artifact.

It contains:

```text
C = target reference
manifest comment block(s)
ordered MATCH/REPLACE blocks
```

It contains no executable functions, imports, loops, conditionals, or runtime logic.

---

### 5.3 Manifest Ledger

The manifest ledger is an append-only semantic summary of accepted changes.

It is used as lightweight context for future LLM turns.

The ledger stores semantic summaries, not full target text and not full PDCP blocks.

---

### 5.4 PDCP Log

The PDCP log is an append-only operational record of accepted and rejected PDCP files.

It is used for:

* replay
* audit
* rollback
* debugging
* reconstruction
* failure analysis

---

### 5.5 `changeOperator.py`

`changeOperator.py` is the deterministic interpreter for PDCP files.

It:

* reads `C`
* identifies the cloud target file
* validates PDCP structure
* verifies all `MATCH` preconditions
* applies all replacements atomically
* writes the updated target file
* appends manifest summaries
* appends the PDCP file to the log

It does not understand the semantic meaning of Python, Markdown, prose, JSON, YAML, or any other target format.

---

## 6. Structural Purity Principle

PDCP is structurally pure.

A valid PDCP file contains only:

```text
declarative target reference
semantic manifest comments
exact target-native textual transitions
optional disambiguation comments
```

A PDCP file must not contain runtime behavior.

No execution semantics exist inside PDCP. The only executable component is the trusted `changeOperator.py`, which is external to the model output.

This principle is central to PatchDIFF’s safety model:

```text
The LLM proposes textual state transitions.
The operator validates and applies them.
The PDCP file itself never runs.
```

---

## 7. Design Invariants

PatchDIFF must preserve these invariants:

```text
1. The target format is authoritative.
2. PDCP is transport, not transformation.
3. MATCH content is exact current target-native text.
4. REPLACE content is exact desired target-native text.
5. The operator is language-agnostic.
6. The operator performs no semantic parsing of the target language.
7. PDCP application is atomic.
8. Failed PDCPs never partially mutate target state.
9. Manifest summaries are semantic memory, not operational truth.
10. PDCP logs are append-only.
11. Cloud target state is the materialized current view.
12. SAVE snapshots the current target and clears unsaved manifest context.
13. PatchDIFF v0.2.3 is single-active-writer per target editing cycle.
14. Concurrent divergence is rejected, not merged.
15. User-visible exact deltas are part of the safety model.
16. Within a PDCP transaction, later MATCH blocks must target the progressively updated in-memory state, not the original pre-transaction state.
17. PDCP files are structurally pure and contain no executable logic.
18. A PDCP file is the smallest atomic commit unit.
```

---

## 8. Context Supply Model

PatchDIFF operates on the full canonical cloud target, but the LLM does not necessarily need to receive the full target on every turn.

The LLM may receive a **context view** containing:

```text
full cached target
selected target spans
surrounding anchors
target metadata
current manifest ledger
user request
```

This context view is advisory. It helps the LLM generate a valid PDCP file.

It is not authoritative state.

The authoritative state is always the canonical cloud target referenced by `C`.

A `MATCH` block is valid only if it matches the current canonical cloud target during transaction validation, regardless of how the LLM obtained the text.

Therefore, incomplete retrieval, stale cache, or insufficient context cannot silently corrupt the target. It can only produce a PDCP transaction that fails validation and is rejected.

---

## 9. PDCP File Format

### 9.1 Minimal PDCP File

```text
C = "target_file_id:example_001"

# MANIFEST
# change_id: chg_001
# intent: Add null-safe behavior to process_data.
# input_state: process_data multiplies x directly and fails for None.
# output_state: process_data now documents behavior and returns 0 for None.
# affected_region: process_data function
# user_visible_change: Function now handles None safely.
# risk: low

<<<<<<< MATCH
def process_data(x):
    return x * 2
=======
def process_data(x):
    """Multiplies input by two safely."""
    return x * 2 if x is not None else 0
>>>>>>> REPLACE
```

---

## 10. Manifest Format

Each change must include a manifest block immediately before its corresponding `MATCH/REPLACE` block.

### 10.1 Required Manifest Fields

```text
change_id
intent
input_state
output_state
affected_region
user_visible_change
risk
```

### 10.2 Field Meanings

```text
change_id:
A stable identifier for the change object.

intent:
The purpose of the change.

input_state:
What was true before the change.

output_state:
What will be true after the change.

affected_region:
The target-local region being changed.

user_visible_change:
Plain-language explanation of what the user will observe.

risk:
Estimated risk level: low, medium, or high.
```

### 10.3 Example Manifest

```text
# MANIFEST
# change_id: chg_004
# intent: Bind replan acceptance to pending_replan_version.
# input_state: REPLAN_ACCEPTED can rely on latest S/J summaries without proving they correspond to the proposed replan version.
# output_state: REPLAN_ACCEPTED requires S/J summaries whose plan_version matches pending_replan_version.
# affected_region: REPLAN_ACCEPTED validation
# user_visible_change: Replan acceptance can no longer use stale check or score summaries.
# risk: low
```

---

## 11. MATCH/REPLACE Format

Each change block uses a target-native exact text precondition and target-native replacement.

```text
<<<<<<< MATCH
exact existing target-native text
=======
exact desired target-native text
>>>>>>> REPLACE
```

### 11.1 Semantics

The semantics are:

```text
If the current target contains the MATCH block exactly under the declared constraints,
replace that text with the REPLACE block.
Otherwise reject the entire PDCP transaction.
```

`MATCH` should be understood as an optimistic concurrency precondition, not a broad semantic search.

It means:

```text
The LLM believes this exact text is still present.
PatchDIFF verifies that belief before allowing mutation.
```

A failed `MATCH` is therefore not merely a search failure. It is evidence that the model’s proposed edit may be stale, ambiguous, or based on an invalid target view.

### 11.2 Deterministic MATCH Evaluation

`MATCH` evaluation operates on the current canonicalized in-memory target buffer.

For each `MATCH` block, the operator must:

1. Treat `MATCH` as a Unicode codepoint sequence after canonical target serialization.
2. Search the full current in-memory target buffer.
3. Identify all exact full-span occurrences of the `MATCH` sequence.
4. If zero occurrences exist, reject with failure_reason = match_absent.
5. If more than one occurrence exists and no disambiguation resolves it to exactly one span, reject with failure_reason = match_ambiguous.
6. If exactly one occurrence exists, select that span for replacement.

`MATCH` evaluation is:

- exact
- case-sensitive
- whitespace-sensitive after canonicalization
- multiline
- left-to-right over the full current in-memory buffer

The operator must not perform fuzzy matching, semantic matching, token-level matching, or language-aware matching.

### Empty REPLACE and Deletion Semantics

- `MATCH` must be non-empty.
- `REPLACE` may be empty.
-  A non-empty `MATCH` block with an empty `REPLACE` block represents deletion of the matched span.
- Whitespace-only `REPLACE` content is valid and means the matched span is replaced by that exact whitespace.
- Zero-length `MATCH` is invalid in v0.2.3.

### Insertion Semantics


- PatchDIFF does not support zero-length cursor insertion in v0.2.3.
- Pure insertion must be represented as anchored replacement of an existing non-empty span.
- The REPLACE block should include the original anchor text plus the inserted content.

Example:
```text
<<<<<<< MATCH
## Section Title
=======
## Section Title

New inserted paragraph.
>>>>>>> REPLACE
```

This preserves the invariant that every edit is grounded in exact target-native text.

---

## 12. Context Drift Detection

PatchDIFF explicitly detects context drift.

Context drift occurs when the LLM generates a PDCP file from a target view that no longer matches the canonical cloud target.

This may happen because:

```text
the target changed after the model saw it
the model received incomplete context
prior unsaved edits changed the relevant region
the model relied on stale cached text
the target was modified outside the current editing cycle
```

In PatchDIFF, every `MATCH` block functions as a context-validity assertion.

The LLM asserts:

```text
This exact target-native text is still present.
```

The operator verifies:

```text
The canonical cloud target currently contains this exact text under the declared constraints.
```

If the assertion fails, the PDCP transaction is rejected.

Context drift is therefore handled as an optimistic concurrency failure, not as a semantic search problem.

---

## 13. Target-Native Rule

The content inside `MATCH` and `REPLACE` must be written in the target’s own textual format.

For a Markdown target:

```text
<<<<<<< MATCH
## Replan Lifecycle

A replan replaces failed components.
=======
## Replan Lifecycle

A replan replaces failed components without silently modifying completed components.
>>>>>>> REPLACE
```

For a Python target:

```text
<<<<<<< MATCH
def process_data(x):
    return x * 2
=======
def process_data(x):
    """Multiplies input by two safely."""
    return x * 2 if x is not None else 0
>>>>>>> REPLACE
```

For a YAML target:

```text
<<<<<<< MATCH
retry:
  enabled: false
=======
retry:
  enabled: true
  max_attempts: 3
>>>>>>> REPLACE
```

PatchDIFF does not translate between these formats. It applies exact textual transitions.

---

## 14. Canonical Target Serialization

PatchDIFF operates against canonicalized UTF-8 target text loaded from the cloud target referenced by `C`.

Implementations must define serialization rules before validation, hashing, and replacement.

The v0.2.3 default canonicalization rules are:

```text
encoding: UTF-8
newline form: LF
line-ending handling: normalize CRLF and CR to LF before MATCH validation and hashing
tab handling: preserve tabs exactly
space handling: preserve spaces exactly
trailing whitespace: preserve exactly
trailing final newline: preserve exactly
Unicode normalization: no Unicode normalization unless explicitly configured
```

The operator must apply the same canonicalization rules consistently during:

```text
MATCH verification
target hashing
divergence detection
in-memory transaction simulation
final target commit
```

Formatting outside replaced spans must remain unchanged.

The preservation rule is:

```text
Unmatched content is invariant.
Only matched MATCH spans may change.
```

---

## 15. Hash Semantics

PatchDIFF uses hashes to detect divergence and support replay.

### 15.1 `current_hash`

`current_hash` is computed from the full canonicalized target content.

```text
current_hash = hash(canonicalized_full_target_content)
```

The hash algorithm must be fixed per implementation.

Recommended default:

```text
SHA-256 over UTF-8 encoded canonicalized target text
```

### 15.2 `before_hash` and `after_hash`

Each PDCP log entry should record:

```text
before_hash = current_hash before transaction application
after_hash = current_hash after successful transaction application
```

For rejected PDCP files:

```text
before_hash = current_hash at validation time
after_hash = null
```

### 15.3 `target_hash` Disambiguation

When provided in a PDCP manifest or disambiguation metadata, `target_hash` acts as an explicit version precondition.

If the current canonical target hash does not equal the provided `target_hash`, the PDCP transaction fails with:

```text
failure_reason = target_hash_mismatch
```

---

## 16. Transaction Semantics

A PDCP file is one transaction.

A PDCP file is the smallest atomic commit unit in PatchDIFF.

Partial acceptance of individual change blocks is forbidden.

All changes inside the PDCP file must succeed, or none are committed.

```text
Validate protocol structure
→ validate transaction applicability
→ apply changes sequentially in memory
→ commit final target state
```

If any operation fails, the cloud target remains unchanged.

### 16.1 Implementation Note

After each successful `REPLACE` operation, the in-memory target buffer is immediately mutated before evaluating the next `MATCH` block.

PatchDIFF does not use staged replacement semantics where all `MATCH` blocks are first resolved against the original target and then applied later.

The evaluation loop is:

```text

1. Evaluate MATCH against current in-memory buffer.
2. Apply REPLACE immediately to that buffer.
3. Continue to the next change using the mutated buffer.
4. Commit only after all changes succeed.
```

This prevents a common implementation mistake.

---

## 17. Protocol Validity and Transaction Validity

PatchDIFF separates **protocol validity** from **transaction validity**.

### 17.1 Protocol Validation

Protocol validation checks whether the PDCP file is structurally valid.

Protocol validation includes:

```text
C exists and is well-formed
manifest blocks exist
manifest fields are present
MATCH/REPLACE blocks are well-formed
change_id values are present
no executable logic exists
PDCP grammar is satisfied
```

If protocol validation fails, the PDCP is **protocol-invalid**.

Protocol-invalid PDCP files are rejected before target-state applicability is checked.

### 17.2 Transaction Validation

Transaction validation checks whether a protocol-valid PDCP can be applied to the current canonical target.

Transaction validation includes:

```text
cloud target exists
target hash/version preconditions pass
MATCH blocks validate against current in-memory transaction state
MATCH blocks are unambiguous or properly disambiguated
later MATCH blocks account for earlier changes in the same transaction
```

If transaction validation fails, the PDCP is **transaction-invalid**.

Transaction-invalid PDCP files are rejected without mutating the target.

---

## 18. Ordering Semantics

PDCP changes execute sequentially against progressively updated target state within a single atomic transaction.

That means:

```text
Change 1 MATCH is written against the original target.
Change 2 MATCH is written against the target after Change 1.
Change N MATCH is written against the target after Changes 1 through N-1.
```

If the constraint is violated, the entire PDCP transaction fails atomically.

This allows dependent edits while preserving transaction safety.

---

## 19. Overlapping Edit Semantics

Overlapping edits are permitted only if they are sequentially valid.

This means a later change may modify text affected by an earlier change, but only if its `MATCH` block is written against the progressively updated in-memory target state.

Example:

```text
Change 1 modifies lines 1–5.
Change 2 modifies lines 4–8.
```

This is allowed only if Change 2’s `MATCH` block matches the target after Change 1 has already been applied in memory.

PatchDIFF does not perform semantic merging of overlapping edits.

The rule is:

```text
overlap is allowed
only if exact MATCH succeeds
against the current in-memory transaction state
```

---

## 20. Failure Semantics

A PDCP transaction fails if:

```text
- C is missing or invalid.
- The cloud target file does not exist.
- A manifest block is missing required fields.
- A MATCH/REPLACE block is malformed.
- A MATCH block does not match the current target exactly.
- A MATCH block matches multiple locations without disambiguation.
- A later operation becomes invalid after an earlier operation.
- The target version or hash precondition fails.
- The PDCP contains executable logic.
- The target has diverged since the PDCP was generated.
- A later MATCH block assumes the original target state instead of the progressively updated in-memory state.
```

On failure:

```text
- no target mutation occurs
- the PDCP is marked rejected
- the failure reason is logged
- no manifest summary is committed as accepted
- regeneration may be requested from the model
```

Failed PDCP operations never partially modify target state.

Application is atomic at the PDCP transaction level.

### 20.1 Failure Reason Labels

Each rejected PDCP transaction must record one primary `failure_reason`.

Allowed `failure_reason` values:

```text
context_missing
context_invalid
target_not_found
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

### 20.2 Mapping from Failure Condition to Label

```text
C is missing.
→ failure_reason = context_missing

C is malformed or references an invalid target format.
→ failure_reason = context_invalid

The cloud target file does not exist.
→ failure_reason = target_not_found

A manifest block is missing.
→ failure_reason = manifest_missing

A manifest block is present but missing required fields or malformed.
→ failure_reason = manifest_invalid

A MATCH/REPLACE block is malformed.
→ failure_reason = block_malformed

A MATCH block does not match the current target exactly.
→ failure_reason = match_absent

A MATCH block matches multiple locations without disambiguation.
→ failure_reason = match_ambiguous

Disambiguation metadata is present but does not resolve to exactly one match.
→ failure_reason = disambiguation_invalid

The target hash precondition fails.
→ failure_reason = target_hash_mismatch

The target version precondition fails.
→ failure_reason = target_version_mismatch

The target has diverged since the PDCP was generated.
→ failure_reason = target_diverged

The PDCP contains executable logic.
→ failure_reason = executable_logic_detected

A later MATCH block assumes the original target state instead of the progressively updated in-memory state.
→ failure_reason = sequential_match_invalid

The operator encounters an unexpected internal error during validation or application.
→ failure_reason = transaction_internal_error
```

### 20.3 `match_absent` vs. `target_diverged`

```text
match_absent:
The exact MATCH text is not present, but no explicit target_hash/version precondition proves divergence.

target_diverged:
A target_hash or version precondition proves the target changed since the PDCP was generated.
```

`target_diverged` is stronger evidence, while `match_absent` is the local textual failure.

---

## 21. Disambiguation

By default, each `MATCH` block must match exactly once.

If the same text appears multiple times, the PDCP must include disambiguation metadata.

### 21.1 Optional Disambiguation Fields

```text
# anchor_before:
# anchor_after:
# occurrence_index:
# region_hint:
# target_hash:
```

### 21.2 Example

```text
# MANIFEST
# change_id: chg_007
# intent: Update the retry setting in the production config.
# input_state: Production retry is disabled.
# output_state: Production retry is enabled with three attempts.
# affected_region: production retry config
# user_visible_change: Production retries are enabled.
# risk: medium
# anchor_before: environment: production
# anchor_after: logging:
# occurrence_index: 1

<<<<<<< MATCH
retry:
  enabled: false
=======
retry:
  enabled: true
  max_attempts: 3
>>>>>>> REPLACE
```

The operator may use these fields only to disambiguate exact textual matching. It still does not parse target semantics.

---

## 22. Threat Model

PatchDIFF provides **structural safety**, not full semantic correctness.

### 22.1 Structural Safety Guarantees

PatchDIFF guarantees:

```text
- no executable model-generated code
- no hidden target mutation
- exact visible textual delta
- exact MATCH precondition before mutation
- atomic rollback on failure
- append-only operational history
```

The operator never executes model-generated functions, imports, shell commands, network calls, or runtime logic.

### 22.2 Semantic Safety Limits

PatchDIFF does not guarantee that the replacement content is semantically correct, desirable, secure, or aligned with user intent.

For example, a structurally valid PDCP could still:

```text
- introduce a bug into source code
- weaken a security configuration
- make a factual error in a document
- remove an important qualification
- implement a user request incorrectly
```

Those are semantic risks, not protocol-structure risks.

### 22.3 Reviewability Advantage

PatchDIFF improves semantic reviewability because the exact change is visible.

The user or reviewer can inspect:

```text
MATCH = exact old text
REPLACE = exact new text
MANIFEST = stated intent and semantic before/after
```

This is safer than opaque full-document regeneration because the edit surface is localized, explicit, and auditable.

---

## 23. Cloud Storage Model

PatchDIFF stores four primary artifacts:

```text
cloud_target_file
current_pdcp_file
append_only_pdcp_log
append_only_manifest_ledger
```

### 23.1 Cloud Target File

Stores the current editable target.

```text
target_file_id
current_content
current_hash
version
created_at
updated_at
```

### 23.2 Current PDCP File

Stores the current unsaved PDCP content.

```text
pdcp_file_id
target_file_id
content
status
created_at
updated_at
```

### 23.3 PDCP Log

Append-only log of validated or rejected PDCP files.

```text
pdcp_log_id
target_file_id
pdcp_content
status
failure_reason
failure_detail
failed_change_id
before_hash
after_hash
created_at
```

Where:

```text
failure_reason = machine-readable label
failure_detail = human-readable explanation
failed_change_id = change_id that caused rejection, if applicable
```

Example:

```json
{
  "status": "rejected",
  "failure_reason": "sequential_match_invalid",
  "failed_change_id": "chg_011",
  "failure_detail": "Change chg_011 MATCH block was written against the original target, but chg_010 had already modified that span in memory."
}
```

### 23.4 Manifest Ledger

Append-only lightweight context used by the LLM.

```text
manifest_entry_id
target_file_id
change_id
intent
input_state
output_state
affected_region
user_visible_change
risk
pdcp_log_id
created_at
```

---

## 24. Execution Workflow

### 24.1 File Initialization

When a file is added during a session:

```text
1. Upload file to cloud database.
2. Store it as cloud_target_file.
3. Canonicalize target content.
4. Compute current_hash.
5. Initialize empty manifest ledger.
6. Enable PDCP ingestion.
```

PDCP ingestion activates only after the target exists.

---

### 24.2 User Edit Request

The user submits a change request.

The LLM receives:

```text
target reference
context view
current manifest ledger
user request
```

The context view may include the full cached target or selected spans.

The LLM emits a PDCP file.

---

### 24.3 PDCP Ingestion

PatchDIFF receives the PDCP output and:

```text
1. Reads C.
2. Identifies the cloud target.
3. Loads canonicalized target content.
4. Validates manifest formatting.
5. Validates MATCH/REPLACE structure.
6. Rejects executable logic.
7. Checks target hash/version constraints when provided.
8. Verifies each MATCH block against the progressively updated in-memory target state.
```

---

### 24.4 Successful Application

If validation succeeds:

```text
1. Apply all changes sequentially in memory.
2. Commit final target content atomically.
3. Append manifest summaries to manifest ledger.
4. Append full PDCP file to PDCP log.
5. Update current_hash and version.
```

---

### 24.5 Failed Application

If validation fails:

```text
1. Do not modify target.
2. Mark PDCP rejected.
3. Store failure reason.
4. Request regenerated PDCP from model.
```

---

## 25. SAVE Semantics

SAVE is a compaction checkpoint.

When SAVE is called:

```text
1. Snapshot the current cloud target file.
2. Export finalized target file.
3. Mark the current editing cycle complete.
4. Clear lightweight manifest context for the next cycle.
5. Preserve PDCP log for audit/replay.
```

After SAVE:

```text
current target = new canonical base
manifest ledger context = empty
PDCP log = archived
```

SAVE does not require the LLM to rewrite the document.

---

## 26. SAVE Cost Policy

SAVE is not merely a convenience function. It is the asymptotic cost-control mechanism of PatchDIFF.

PatchDIFF reduces repeated input cost by replacing repeated full-document context with a lightweight manifest ledger. However, if the manifest ledger grows indefinitely, its context cost can eventually approach or exceed the cost of rereading the full target.

Therefore SAVE should be recommended when the unsaved manifest ledger approaches a configured fraction of target size.

Example policy:

```text
Recommend SAVE when:
manifest_ledger_tokens ≥ α × target_tokens
```

Suggested initial values:

```text
α = 0.25 for conservative compaction
α = 0.33 for standard compaction
α = 0.50 for aggressive editing sessions
```

Interpretation:

```text
If the unsaved manifest ledger reaches 25–33% of the target document size,
PatchDIFF should recommend SAVE.
```

The goal is to prevent accumulated ledger context from overtaking the cost advantage of PatchDIFF over full-document editing.

### 26.1 Additional SAVE Triggers

SAVE may also be recommended when:

```text
edit_count exceeds configured threshold
PDCP log size exceeds configured threshold
user completes a coherent editing task
high-risk changes have accumulated
target export is requested
```

### 26.2 SAVE Failure Semantics

If SAVE fails:

```text
- the prior cloud target remains canonical
- the manifest ledger remains intact
- the PDCP log remains replayable
- no editing history is lost
- SAVE may be retried
```

A failed SAVE must not clear the manifest ledger.

---

## 27. MVCC Interpretation

PatchDIFF behaves like a lightweight textual MVCC transaction system.

```text
manifest = transaction metadata
MATCH = optimistic concurrency precondition
REPLACE = committed state transition
PDCP log = transaction log
cloud target = materialized current view
SAVE = checkpoint / compaction
```

The key reframing is that PatchDIFF uses optimistic concurrency not only for multi-user conflicts, but also for **model-context synchronization**.

A `MATCH` block verifies that the model’s proposed edit is still grounded in the current target state.

If the `MATCH` fails, the model’s context may be stale, incomplete, or ambiguous.

---

## 28. Future Multi-Writer Extension

PatchDIFF v0.2.3 rejects conflicting or divergent edits.

A future version may introduce multi-active-writer support.

Such a system would require:

```text
global patch log
shared cloud target context
writer/session identifiers
total ordering of accepted PDCP transactions
duplicate detection
conflict detection
future conflict-resolution mechanisms
```

In that future model, deterministic `MATCH/REPLACE` operations and replayable PDCP logs could support more advanced coordination.

However, v0.2.3 does not transform conflicting patches.

The current rule remains:

```text
conflict → reject → regenerate
```

---

## 29. Security Model

A valid PDCP file must not contain:

```text
imports
functions
loops
conditionals
network calls
filesystem operations
shell commands
dynamic evaluation
external package references
```

Only declarative protocol content is allowed:

```text
C assignment
manifest comments
MATCH/REPLACE blocks
optional disambiguation comments
```

### Executable-Logic Detection Scope

Executable-logic detection applies only to PDCP structural regions outside `MATCH` `REPLACE` payloads.

The following regions are PDCP structural regions:

- C assignment
- manifest comments
- disambiguation comments
- text outside `MATCH`/`REPLACE`  blocks

Content inside `MATCH` and `REPLACE` blocks is opaque target-native payload text.

Therefore, `MATCH`/`REPLACE` payloads may contain code, function definitions, imports, shell commands, or other executable-looking text when such text is part of the target file being edited.

The operator must never execute payload text. It only compares and replaces it as literal text.

---

## 30. Minimal Valid PDCP Grammar

Informally:

```text
PDCP_FILE :=
  CONTEXT_DECLARATION
  CHANGE_BLOCK+

CONTEXT_DECLARATION :=
  C = "target_file_id:<id>"

CHANGE_BLOCK :=
  MANIFEST_BLOCK
  MATCH_REPLACE_BLOCK

MANIFEST_BLOCK :=
  "# MANIFEST"
  "# change_id: ..."
  "# intent: ..."
  "# input_state: ..."
  "# output_state: ..."
  "# affected_region: ..."
  "# user_visible_change: ..."
  "# risk: ..."

MATCH_REPLACE_BLOCK :=
  "<<<<<<< MATCH"
  MATCH_TEXT
  "======="
  REPLACE_TEXT
  ">>>>>>> REPLACE"
```

A formal grammar is deferred until parser implementation stabilizes.

---

## 31. Benefits and Tradeoffs

### 31.1 Benefits

PatchDIFF provides:

```text
lower output cost than full-document regeneration
reduced repeated input cost through manifest-ledger context
exact user-visible deltas
deterministic in-place application
no executable model-generated code
no AST or parser dependency
append-only audit and replay history
explicit context-drift detection through MATCH validation
atomic failure behavior
target-format neutrality
```

### 31.2 Tradeoffs

PatchDIFF also has limitations:

```text
exact MATCH can fail due to whitespace, formatting, or target divergence
the LLM must see enough exact target text to generate valid MATCH blocks
semantic correctness is not guaranteed by the protocol
multi-writer editing is not supported in v0.2.3
long editing sessions require SAVE to prevent manifest-ledger context growth
binary or richly formatted formats require a stable textual representation before PatchDIFF can operate
```

These tradeoffs are intentional.

PatchDIFF prioritizes:

```text
determinism
auditability
target-format neutrality
reviewability
structural safety
```

over:

```text
semantic parsing
fuzzy matching
automatic merging
model-generated execution
hidden document rewriting
```

---

## 32. End-to-End Example

### User request

```text
Make process_data safe for None inputs.
```

### LLM output

```text
C = "target_file_id:data_utils_py"

# MANIFEST
# change_id: chg_001
# intent: Add null-safe behavior to process_data.
# input_state: process_data multiplies x directly and fails for None.
# output_state: process_data now documents behavior and returns 0 for None.
# affected_region: process_data function
# user_visible_change: Function now handles None safely.
# risk: low

<<<<<<< MATCH
def process_data(x):
    return x * 2
=======
def process_data(x):
    """Multiplies input by two safely."""
    return x * 2 if x is not None else 0
>>>>>>> REPLACE
```

### Operator behavior

```text
1. Load target_file_id:data_utils_py.
2. Canonicalize target content.
3. Verify the MATCH block appears exactly once.
4. Replace the matched span with the REPLACE span.
5. Commit the updated target.
6. Append manifest to manifest ledger.
7. Append full PDCP to PDCP log.
```

### Manifest ledger entry

```json
{
  "change_id": "chg_001",
  "intent": "Add null-safe behavior to process_data.",
  "input_state": "process_data multiplies x directly and fails for None.",
  "output_state": "process_data now documents behavior and returns 0 for None.",
  "affected_region": "process_data function",
  "user_visible_change": "Function now handles None safely.",
  "risk": "low"
}
```

---

## 33. End-to-End Example with Divergence

### Initial target

```text
retry:
  enabled: false
```

### LLM output

```text
C = "target_file_id:config_yaml"

# MANIFEST
# change_id: chg_002
# intent: Enable retry behavior.
# input_state: Retry is disabled.
# output_state: Retry is enabled with three attempts.
# affected_region: retry config
# user_visible_change: Retry is now enabled.
# risk: medium

<<<<<<< MATCH
retry:
  enabled: false
=======
retry:
  enabled: true
  max_attempts: 3
>>>>>>> REPLACE
```

### Diverged target at application time

```text
retry:
  enabled: true
  max_attempts: 1
```

### Operator behavior

```text
1. Load target.
2. Canonicalize target content.
3. Search for exact MATCH.
4. MATCH is absent.
5. Reject transaction.
6. Do not mutate target.
7. Log failure reason.
8. Request regenerated PDCP.
```

The failure means the model’s proposed edit was based on stale target context.

---

## 34. End-to-End Example with Sequential MATCH Failure

### Initial target

```text
status: draft
review_required: false
```

### Invalid PDCP

```text
C = "target_file_id:workflow_yaml"

# MANIFEST
# change_id: chg_010
# intent: Mark the workflow as reviewed.
# input_state: The workflow is in draft state and review is not required.
# output_state: The workflow is reviewed and review is required.
# affected_region: workflow status block
# user_visible_change: Workflow status and review requirement are updated.
# risk: low

<<<<<<< MATCH
status: draft
=======
status: reviewed
>>>>>>> REPLACE

# MANIFEST
# change_id: chg_011
# intent: Require review after status update.
# input_state: The workflow is in draft state and review is not required.
# output_state: Review is required.
# affected_region: workflow status block
# user_visible_change: Review is now required.
# risk: low

<<<<<<< MATCH
status: draft
review_required: false
=======
status: reviewed
review_required: true
>>>>>>> REPLACE
```

### Why this fails

Change 1 updates:

```text
status: draft
```

to:

```text
status: reviewed
```

Therefore Change 2 cannot match the original text:

```text
status: draft
review_required: false
```

because the in-memory target has already changed.

### Correct PDCP structure

The second `MATCH` must be written against the post-Change-1 state:

```text
<<<<<<< MATCH
status: reviewed
review_required: false
=======
status: reviewed
review_required: true
>>>>>>> REPLACE
```

### Operator behavior

```text
1. Apply Change 1 in memory.
2. Attempt Change 2 against the updated in-memory target.
3. MATCH fails.
4. Reject the entire PDCP transaction.
5. Do not commit any target mutation.
6. Log sequential MATCH failure.
```

---

## 35. Deferred Work

The following are not required before v1 build:

```text
formal EBNF grammar
semantic verifier
static analysis integration
multi-writer conflict-resolution protocol
empirical α calibration
MATCH failure-rate model
fuzzy matching
AST-aware target adapters
```

These are v0.3 or evaluation-track items.

---

## 36. Summary

PatchDIFF’s locked model is:

```text
Target-native text in
target-native text out
validated by exact MATCH
applied by deterministic REPLACE
explained by semantic MANIFEST
recorded by append-only logs
compacted by SAVE
```

PatchDIFF v0.2.3 is:

```text
single-active-writer
cloud-backed
append-only
transactional
target-native
language-agnostic
reviewable
deterministic
structurally pure
context-drift-aware
```

The system is powerful because it avoids hidden abstraction layers. It does not need to understand the target. It only needs to preserve transactional textual truth.
