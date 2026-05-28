# PatchDIFF: Transaction-Enveloped Diffs for Auditable, Low-Decoding-Cost LLM Text Editing

## Abstract

Large language models are increasingly used to edit long-lived textual artifacts such as source files, Markdown specifications, configuration files, structured documents, and knowledge bases (Chen et al., 2021; Yao et al., 2023; Schick et al., 2023; Jimenez et al., 2024). The dominant interaction pattern remains full-document regeneration: the model decodes a new version of the artifact even when the requested change is local. This pattern is costly and operationally fragile. Small edits can require large outputs, unchanged regions may drift, and stale model context can overwrite newer target state without explicit detection.

PatchDIFF addresses this problem by treating LLM-generated edits as transaction-enveloped textual state transitions over a cached authoritative document. Instead of asking the model to regenerate the target, PatchDIFF asks the model to emit a declarative PatchDIFF Change Protocol file containing semantic manifests and exact target-native `MATCH/REPLACE` transitions. A trusted deterministic runtime, `changeOperator.py`, validates the protocol, verifies exact textual preconditions against the current canonical cloud target, applies accepted edits sequentially in memory, commits atomically, and records accepted and rejected transactions in append-only logs.

The central claim is not that textual diffs are new. Textual differencing and patch systems have a long history (Hunt and Szymanski, 1977; Myers, 1986), and version-control systems already use localized textual change as a review and history mechanism (Chacon and Straub, 2014). PatchDIFF instead defines the runtime and lifecycle semantics that make model-generated textual deltas safe to apply repeatedly to one cached authoritative document. In this model, `MATCH` is an optimistic concurrency precondition over current target state, `REPLACE` is a target-native state transition, the manifest is semantic transaction metadata, the PDCP log is operational truth, and SAVE is checkpoint-based compaction for long editing sessions.

PatchDIFF deliberately avoids semantic parsing, AST mutation, fuzzy matching, executable model-generated protocol logic, hidden repair, and downstream full-document rewriting. It provides structural safety rather than semantic correctness: edits remain explicit, localized, auditable, replayable, and rejected under stale, ambiguous, malformed, or divergent target context. This paper presents the PatchDIFF abstraction, protocol, runtime model, failure semantics, persistence model, evaluation plan, and limitations. The design is grounded in the PatchDIFF protocol and implementation specifications for v0.2.3.

---

## 1. Introduction

Large language models are increasingly used as interactive editors for long-lived artifacts: source files, configuration files, Markdown documents, technical specifications, HTML, YAML, JSON, and prose. Code-generation and software-engineering benchmarks demonstrate that LLMs can synthesize and modify code, but also expose reliability challenges when generated changes must interact with existing artifacts (Chen et al., 2021; Jimenez et al., 2024). The dominant editing pattern remains full-state regeneration. A user supplies a target artifact, requests a change, and the model returns a rewritten artifact.

Full-state regeneration is inefficient and operationally unsafe for iterative editing. Even when the requested change is local, the model may regenerate unchanged regions, introduce hidden mutations, alter formatting, delete caveats, or overwrite newer target state based on stale context. These failure modes are not merely model-quality problems. They arise from the editing abstraction itself: the model is asked to produce a new full state rather than a validated transition over current authoritative state.

The cost problem is not limited to a single turn. In multi-turn editing, full-state regeneration repeatedly asks the model to decode large portions of a target that already exists outside the model. Retrieval-augmented generation reduces some context pressure by supplying selected evidence rather than all available text (Lewis et al., 2020), but retrieval alone does not make the retrieved view authoritative. PatchDIFF instead assumes that the target document is cached as authoritative cloud state. The LLM receives only the context needed to propose a local edit: selected target spans, surrounding anchors, target metadata, the current manifest ledger, and the user request. The full canonical target remains outside the model and is owned by the runtime.

A natural response is diff-based editing. Instead of rewriting the full target, the model emits a localized textual delta. This is a meaningful improvement. Diffs reduce output size, expose the edit surface, and align with established software review practices.

However, raw diffs are not enough for durable LLM-mediated editing. A diff represents what text changed. It does not by itself define how to validate the model’s assumed context, how to reject stale edits, how to log rejected proposals, how to preserve semantic intent for later turns, how to atomically commit a change, or how to replay the target state deterministically.

PatchDIFF addresses this missing layer.

PatchDIFF treats LLM-emitted textual deltas as transaction-enveloped diffs. The textual transition remains local and target-native, but it is wrapped in a PatchDIFF Change Protocol transaction containing semantic manifest metadata, target reference, exact `MATCH/REPLACE` blocks, optional disambiguation metadata, hash/version preconditions, append-only logging semantics, and deterministic replay rules.

The runtime, `changeOperator.py`, validates the transaction against the canonical target. The model proposes; the runtime validates; the target changes only after every precondition succeeds.

The central abstraction is:

|PDCP element|Transactional role|
|---|---|
|`MATCH`|Optimistic concurrency precondition|
|`REPLACE`|Target-native textual state transition|
|Manifest|Semantic transaction metadata|
|Target hash/version|Authoritative-state guard|
|PDCP log|Append-only operational truth|
|Manifest ledger|Compressed semantic memory|
|SAVE|Checkpoint and compaction|

PatchDIFF does not claim that textual differencing is novel. Its claim is that LLM-generated textual deltas require a transaction envelope to become reliable long-lived edit operations. This places PatchDIFF closer to transaction processing, optimistic concurrency control, and event sourcing than to a new diff notation (Kung and Robinson, 1981; Bernstein and Goodman, 1981; Fowler, 2005).

This paper makes five contributions:

1. **Cached-document LLM editing protocol.** PatchDIFF enables repeated local edits over one canonical cloud target without requiring full-document regeneration for every turn.
    
2. **Transaction-enveloped textual deltas.** PatchDIFF wraps model-emitted `MATCH/REPLACE` transitions in a transaction envelope containing target identity, semantic manifests, optional disambiguation, hash/version preconditions, failure labels, and logging semantics.
    
3. **Model-context validation through exact preconditions.** PatchDIFF interprets each `MATCH` block as the model’s assertion that exact target-native text remains present in authoritative state. Failed matches become structured evidence of stale, incomplete, ambiguous, or divergent model context.
    
4. **Deterministic runtime and append-only persistence model.** PatchDIFF specifies parser, validator, applier, hash, atomic commit, replay, and persistence semantics sufficient for independent runtimes to reproduce accepted outcomes.
    
5. **Semantic memory and checkpoint compaction.** PatchDIFF separates operational truth from model-facing semantic memory: the PDCP log is authoritative for replay and audit, while the manifest ledger supports compact multi-turn editing context and SAVE provides checkpoint-based compaction.
    

---

## 2. From Full-State Regeneration to Transaction-Enveloped Editing

Full-state regeneration asks the model to produce the next complete version of a target artifact. This gives the model unnecessary authority over regions that the user did not ask to change. It also makes stale context dangerous: if the model regenerates from an outdated target view, it can overwrite newer changes without detecting that the authoritative target has moved on.

PatchDIFF starts from a different assumption: the target already exists outside the model as cached authoritative state. The model should not be responsible for reproducing that state. It should propose a local transition against it.

This changes the editing problem from full-state generation to transaction validation. The model emits a declarative PDCP transaction containing the exact target-native text it believes is present and the exact replacement it proposes. The runtime then validates that assumption against the current canonical target before committing any mutation.

In this model, a local textual transition is not applied merely because the model produced it. It is applied only if its preconditions still hold. A `MATCH` block asserts that a specific span remains present in authoritative state. A `REPLACE` block describes the desired textual transition. The transaction envelope records the target reference, semantic intent, validation metadata, failure behavior, logging semantics, and replay requirements.

The resulting control pattern is:

> The model proposes a local edit.  
> The runtime validates the model’s assumed target state.  
> The target changes only if every precondition succeeds.

PatchDIFF therefore preserves the main benefit of localized editing—small, explicit changes—while adding the lifecycle semantics needed for repeated LLM editing over long-lived artifacts. The key shift is not simply from “full document” to “diff.” It is from model-generated replacement state to runtime-validated state transition.

---

## 3. Cached Target Editing Model

PatchDIFF is designed for editing workflows in which the target artifact persists outside the model as canonical cloud state. The model does not own the document. It proposes localized textual transitions against a target reference, and the runtime decides whether those transitions are valid against the current authoritative target.

A PatchDIFF editing cycle has four distinct state views:

|State view|Role|
|---|---|
|Canonical cloud target|Authoritative current document|
|Context view|Advisory text shown to the LLM|
|PDCP transaction|Model-emitted edit proposal|
|In-memory transaction buffer|Runtime simulation state before commit|

The context view may contain the full target, selected spans, surrounding anchors, target metadata, the manifest ledger, and the user request. It is useful for generation but not trusted for application. The runtime always validates against the canonical cloud target.

This distinction is essential. If the model sees stale or incomplete context, PatchDIFF does not let that context overwrite the target. The stale context can only produce a PDCP transaction whose `MATCH` precondition fails. The result is rejection, not hidden mutation.

PatchDIFF therefore changes the editing abstraction from:

> model decodes next full document

to:

> model proposes local transaction; runtime validates against cached authoritative document.

This gives PatchDIFF its decoding-cost advantage. For local edits, model output scales with the changed span plus manifest overhead rather than with the full target size. SAVE prevents manifest-ledger growth from eventually erasing that advantage.

The model-facing context may still be retrieved, summarized, or partially cached, as in retrieval-augmented generation systems (Lewis et al., 2020). PatchDIFF’s difference is that retrieved context is advisory rather than authoritative: every proposed mutation must still validate against the canonical target.

---

## 4. Why Unified Diff Alone Is Insufficient

Unified diff is the closest textual baseline for PatchDIFF. PatchDIFF intentionally preserves the central advantage of diff-based editing: localized textual changes are preferable to regenerating an entire file when the requested edit is local. A unified diff exposes the edit surface, reduces output size, and aligns with established software review practices.

However, unified diff is a representation of textual difference, not a complete execution protocol for LLM-mediated editing. After a model emits a diff, the surrounding system must still decide how to validate it against the authoritative target, whether fuzzy application is allowed, how to detect stale model context, how to handle ambiguous matches, how to record rejected proposals, how to preserve semantic intent for later turns, and how to reconstruct target state deterministically.

These questions become central in LLM editing because the model may generate an edit from stale, partial, retrieved, summarized, or hallucinated context. A raw textual delta describes what should change, but it does not define what target state the model assumed or what should happen if that assumption is false.

PatchDIFF targets this missing layer. It treats model-generated textual deltas as transaction-enveloped edits over a cached authoritative document. The model emits localized `MATCH/REPLACE` transitions, but the runtime validates exact preconditions against the current canonical target before any mutation occurs. Accepted edits are applied atomically, rejected edits are logged with structured failure reasons, accepted manifests are stored as compact semantic memory, and accepted transactions remain replayable through append-only logs and hashes.

The distinction is therefore not “diff versus no diff.” PatchDIFF uses diff-like locality, but adds lifecycle semantics for repeated LLM editing over one authoritative target.

|Layer|Role|Limitation|
|---|---|---|
|Textual delta|Describes what target-native text changes|Does not define validation, memory, rejection, replay, or commit semantics|
|Patch application tool|Attempts to apply a textual change|Uses tool-specific behavior and does not model LLM context validity|
|PDCP transaction envelope|Describes the edit, assumed target state, validation rules, failure behavior, logging, replay, and semantic memory|Provides structural safety, not semantic correctness|

This transaction envelope gives PatchDIFF capabilities that unified diff alone does not specify:

|Capability|Why it matters for LLM editing|
|---|---|
|Semantic manifest|Records why the edit was proposed and what user-visible change it claims to make|
|Exact target-state precondition|Validates the model’s assumed context against authoritative state|
|Accepted/rejected transaction log|Preserves both successful edits and failed proposals as operational evidence|
|Failure taxonomy|Distinguishes stale context, ambiguity, malformed protocol, divergence, and internal failure|
|Manifest ledger|Provides compact semantic memory for future model turns|
|Structural-purity boundary|Prevents model output from defining executable protocol behavior|
|Replay contract|Reconstructs state using canonicalization rules, ordered accepted transactions, and hashes|
|SAVE compaction|Controls long-session context growth through checkpointing|

Thus, PatchDIFF’s novelty is not that textual deltas exist. Its novelty is the transaction lifecycle around LLM-generated textual deltas:

> diff-like local edits + semantic manifests + exact target-state validation + accepted/rejected logs + deterministic replay + compact model memory.

Unified diff primarily records textual difference. PatchDIFF records a transaction. In doing so, it turns LLM-generated diffs from review artifacts into deterministic cached-document edit transactions.

---

## 5. Why Not Line-Number Editing?

Many LLM editing systems rely on line ranges or coordinate-based edits. Line-number editing identifies where a model wants to edit. PatchDIFF identifies what text the model believes is present.

This difference matters because line coordinates can become stale when earlier edits insert or delete lines. A line range may still exist but refer to different content. By contrast, a PatchDIFF `MATCH` block must validate exact target-native text before mutation.

|Line-number editing|PatchDIFF|
|---|---|
|Coordinates may shift|Exact content must match|
|Stale line numbers may target wrong text|Stale text rejects|
|Requires trust in retrieved line map|Validates against canonical target|
|Usually lacks semantic manifest|Requires manifest metadata|
|Often edits by tool command|Edits by declarative transaction|

PatchDIFF therefore treats target text itself as the precondition. The model does not merely say “edit lines 40–45.” It says “replace this exact span, if and only if it still exists under the declared constraints.”

This choice is intentionally conservative. It sacrifices the convenience of coordinates for stronger validation of the model’s assumed context.

---

## 6. System Model

PatchDIFF v0.2.3 consists of five primary system objects:

|Object|Role|
|---|---|
|Cloud target file|Authoritative current target text|
|PDCP file|Declarative model-emitted edit artifact|
|`changeOperator.py`|Trusted deterministic runtime|
|PDCP log|Append-only operational history|
|Manifest ledger|Append-only semantic memory for future LLM turns|

The cloud target is canonical target-native text. It may be Markdown, Python, YAML, JSON, HTML, plain text, or another stable UTF-8 textual representation. PatchDIFF does not transform the target into an AST, semantic graph, normalized document, or intermediate representation.

The model emits a PDCP file. The runtime validates the PDCP. The target changes only if validation succeeds.

The runtime does not understand the semantic meaning of Python, Markdown, prose, YAML, or JSON. It only compares and replaces exact canonicalized text.

The execution pattern is:

|Step|Description|
|--:|---|
|1|Model emits declarative PDCP|
|2|Runtime validates protocol structure|
|3|Runtime loads canonical target|
|4|Runtime checks hash/version preconditions|
|5|Runtime evaluates exact `MATCH` blocks|
|6|Runtime applies `REPLACE` blocks sequentially in memory|
|7|Runtime commits atomically or rejects|
|8|Runtime appends accepted/rejected PDCP log|
|9|Runtime appends accepted manifest entries only on success|

PatchDIFF v0.2.3 assumes one active writer per target editing cycle. Concurrent divergence is detected and rejected rather than merged. This distinguishes PatchDIFF from collaborative editing systems that attempt convergence under simultaneous writers, such as operational transformation and CRDT approaches (Ellis and Gibbs, 1989; Sun et al., 1998; Shapiro et al., 2011).

---

## 7. Runtime Architecture

PatchDIFF v0.2.3 is implemented by five runtime components:

|Component|Responsibility|
|---|---|
|PDCP parser|Extracts target reference, manifests, disambiguation metadata, ordered `MATCH/REPLACE` blocks|
|Protocol validator|Checks structural validity, required fields, block syntax, non-empty `MATCH`, unique change IDs, and structural purity|
|Transaction validator|Checks target existence, hash/version preconditions, exact match resolution, disambiguation, and sequential mutation validity|
|Transaction applier|Simulates all replacements in memory and commits only the final successful buffer|
|Append-only persistence layer|Stores target state, current PDCP, PDCP log, manifest ledger, and snapshots|

The runtime is trusted; the model output is not. `changeOperator.py` is the only executable component. PDCP files are declarative protocol artifacts and are never executed. This separation is aligned with tool-use and agentic LLM work, where models interact with external tools but should not be treated as trusted execution environments (Yao et al., 2023; Schick et al., 2023).

This architecture enforces a simple control boundary:

|Component|Trusted?|Role|
|---|--:|---|
|LLM|No|Proposes declarative edits|
|PDCP file|No|Carries model proposal|
|`changeOperator.py`|Yes|Parses, validates, applies, commits|
|Cloud target|Yes|Stores authoritative target state|
|PDCP log|Yes|Stores operational history|
|Manifest ledger|Partially|Stores advisory semantic memory|

The model can propose text. It cannot directly mutate the target, execute protocol logic, or decide whether its own edit is valid.

---

## 8. PatchDIFF Change Protocol

A PDCP file contains:

1. A target reference.
    
2. One or more manifest blocks.
    
3. Ordered `MATCH/REPLACE` blocks.
    
4. Optional disambiguation metadata.
    

A minimal PDCP transaction has this form:

|Line|Content|
|--:|---|
|1|`C = "target_file_id:example_001"`|
|2|`# MANIFEST`|
|3|`# change_id: chg_001`|
|4|`# intent: Add null-safe behavior to process_data.`|
|5|`# input_state: process_data multiplies x directly and fails for None.`|
|6|`# output_state: process_data now documents behavior and returns 0 for None.`|
|7|`# affected_region: process_data function`|
|8|`# user_visible_change: Function now handles None safely.`|
|9|`# risk: low`|
|10|`<<<<<<< MATCH`|
|11|`def process_data(x):`|
|12|`return x * 2`|
|13|`=======`|
|14|`def process_data(x):`|
|15|`"""Multiplies input by two safely."""`|
|16|`return x * 2 if x is not None else 0`|
|17|`>>>>>>> REPLACE`|

Each change must include a manifest with the following fields:

|Field|Meaning|
|---|---|
|`change_id`|Stable identifier for the change|
|`intent`|Purpose of the change|
|`input_state`|What was true before the change|
|`output_state`|What should be true after the change|
|`affected_region`|Target-local region being changed|
|`user_visible_change`|Plain-language observable change|
|`risk`|Low, medium, or high|

The manifest is semantic metadata, not operational truth. The authoritative operational record is the PDCP log. Rejected PDCP manifests are not appended to the accepted manifest ledger.

This protocol design is intentionally less expressive than semantic patching systems that operate over program structure (Padioleau et al., 2008). PatchDIFF trades semantic expressiveness for target-format neutrality and deterministic replay.

---

## 9. Validity Levels

PatchDIFF separates four levels of correctness:

|Level|Meaning|Guaranteed by PatchDIFF?|
|---|---|--:|
|Protocol-valid|The PDCP file is structurally well formed|Yes|
|Transaction-valid|The edit applies cleanly to the current canonical target|Yes|
|Task-correct|The edit satisfies the user’s intent|No|
|Semantically safe|The replacement introduces no bugs, factual errors, or policy problems|No|

This distinction prevents overclaiming. PatchDIFF does not guarantee that an accepted edit is good. It guarantees that the edit was explicit, localized, precondition-checked, atomically applied, logged, and replayable.

A structurally valid transaction can still introduce a bug, weaken a configuration, or misstate a fact. Such failures require semantic validators, tests, linters, human review, or policy checks above the PatchDIFF layer.

---

## 10. Formal Transaction Model

Let `T₀` be the canonical target state at transaction start. Let a PDCP transaction contain ordered changes:

`c₁, c₂, ..., cₙ`

Each change `cᵢ` contains:

|Symbol|Meaning|
|---|---|
|`mᵢ`|Exact `MATCH` payload|
|`rᵢ`|Exact `REPLACE` payload|
|`dᵢ`|Optional disambiguation metadata|
|`sᵢ`|Manifest metadata|

PatchDIFF evaluates the transaction sequentially.

For each change `cᵢ`, the runtime searches the current in-memory target state `Tᵢ₋₁` for exact occurrences of `mᵢ`.

The transition is valid only if:

1. `mᵢ` is non-empty.
    
2. `mᵢ` occurs exactly once in `Tᵢ₋₁`, or disambiguation resolves multiple exact occurrences to exactly one span.
    
3. Any supplied target hash or version precondition matches current authoritative target state.
    
4. The PDCP file is structurally valid.
    
5. No previous change in the transaction has made the later `MATCH` invalid.
    

If valid, the runtime produces `Tᵢ` by replacing the selected span in `Tᵢ₋₁` with `rᵢ`.

The transaction commits only if all changes succeed. Otherwise, the target remains `T₀`.

This gives PatchDIFF all-or-nothing transaction semantics. The design is analogous to optimistic concurrency control: execution proceeds speculatively against an assumed state, but commit requires validation that the assumed state remains compatible with the authoritative state (Kung and Robinson, 1981; Bernstein and Goodman, 1981).

### Invariant 1: Unmatched-content preservation

For any successful PatchDIFF transaction, target content outside selected `MATCH` spans remains unchanged after canonicalization.

### Invariant 2: Atomicity

If any protocol or transaction validation step fails, the committed target state remains unchanged.

### Invariant 3: Replay determinism

Given the initial canonical target, protocol version, canonicalization rules, and ordered accepted PDCP log entries, replay either reconstructs the logged final hash or fails explicitly with a replay error.

---

## 11. Canonicalization and Hashing

PatchDIFF operates on canonical UTF-8 text.

Canonicalization is mandatory before `MATCH` evaluation, hash generation, transaction validation, replay, divergence detection, and commit. PatchDIFF v0.2.3 canonicalizes all target text to UTF-8 with LF newlines, preserving tabs, spaces, trailing whitespace, and final newline exactly. It performs no Unicode normalization. Therefore visually equivalent Unicode strings may fail to match if their codepoint sequences differ.

The v0.2.3 canonicalization rules are:

|Feature|Rule|
|---|---|
|Encoding|UTF-8|
|Newlines|Normalize CRLF and CR to LF|
|Tabs|Preserve exactly|
|Spaces|Preserve exactly|
|Trailing whitespace|Preserve exactly|
|Final newline|Preserve exactly|
|Unicode normalization|None|

All runtimes must use identical canonicalization rules for `MATCH`, `REPLACE`, hashing, replay, and commit. Otherwise deterministic replay is not guaranteed.

Hashes are computed over canonicalized UTF-8 target text. PatchDIFF v0.2.3 uses SHA-256 by default:

`current_hash = SHA256(canonicalized_full_target_content)`

Accepted log entries record:

|Field|Meaning|
|---|---|
|`before_hash`|Hash before transaction|
|`after_hash`|Hash after successful transaction|

Rejected log entries record:

|Field|Meaning|
|---|---|
|`before_hash`|Hash at validation time|
|`after_hash`|Null|

If a PDCP supplies a `target_hash` precondition and the current target hash differs, the runtime rejects the transaction before `MATCH` evaluation.

---

## 12. Deterministic Matching

PatchDIFF matching is exact, case-sensitive, whitespace-sensitive, multiline, and performed over canonicalized Unicode codepoint sequences.

For each `MATCH` block, the runtime:

1. Searches the entire current in-memory buffer.
    
2. Counts all exact full-span occurrences.
    
3. Rejects if zero occurrences exist.
    
4. Rejects if multiple occurrences exist and disambiguation does not resolve exactly one.
    
5. Selects the single valid span.
    
6. Applies the replacement immediately in memory.
    

The runtime must not perform fuzzy matching, semantic matching, token-coordinate matching, language-aware matching, fallback matching, or automatic repair.

This strictness is intentional. PatchDIFF treats a failed `MATCH` as evidence that the model’s context may be stale, incomplete, ambiguous, or invalid. The protocol therefore converts uncertain model context into explicit transaction failure rather than hidden repair.

---

## 13. Sequential Mutation Semantics

PatchDIFF applies changes sequentially within a transaction.

|Change|Evaluated against|
|---|---|
|Change 1|Original target state|
|Change 2|Target state after Change 1|
|Change 3|Target state after Changes 1 and 2|
|Change N|Progressively updated in-memory state|

PatchDIFF does not first resolve all matches against the original target and then apply replacements later.

This rule allows dependent edits while preserving determinism. A later change may modify text introduced or changed by an earlier change, but only if its `MATCH` block is written against the updated in-memory state.

Overlapping edits are therefore permitted only when sequentially valid. No semantic merge occurs.

---

## 14. Deletion, Insertion, and Ambiguity

PatchDIFF v0.2.3 requires non-empty `MATCH` blocks.

An empty `REPLACE` block is valid and represents deletion.

A whitespace-only `REPLACE` block is valid and means the matched span is replaced with exactly that whitespace.

Zero-length cursor insertion is not supported in v0.2.3. Pure insertion must be represented as anchored replacement of existing non-empty text. The replacement should include the anchor plus inserted content.

If a `MATCH` block appears multiple times, the PDCP may include disambiguation metadata.

Supported disambiguation fields include:

|Field|Role|
|---|---|
|`anchor_before`|Exact text that must appear before the selected occurrence|
|`anchor_after`|Exact text that must appear after the selected occurrence|
|`occurrence_index`|One-based index over exact occurrences|
|`region_hint`|Advisory diagnostic or UI hint|
|`target_hash`|Explicit version precondition|

Disambiguation is not fuzzy search. It can only select among already-detected exact matches. `region_hint` alone must not select a span.

---

## 15. Protocol Validity and Transaction Validity

PatchDIFF separates protocol validity from transaction validity.

Protocol validation asks whether the PDCP file is structurally well formed.

|Check|Failure label|
|---|---|
|Missing target declaration|`context_missing`|
|Invalid target declaration|`context_invalid`|
|Missing manifest|`manifest_missing`|
|Malformed manifest|`manifest_invalid`|
|Malformed `MATCH/REPLACE` block|`block_malformed`|
|Executable logic outside payloads|`executable_logic_detected`|
|Invalid UTF-8 target|`target_encoding_invalid`|

Transaction validation asks whether a protocol-valid PDCP can be applied to the current target.

|Check|Failure label|
|---|---|
|Target does not exist|`target_not_found`|
|Zero exact matches|`match_absent`|
|Multiple unresolved matches|`match_ambiguous`|
|Invalid disambiguation|`disambiguation_invalid`|
|Hash mismatch|`target_hash_mismatch`|
|Version mismatch|`target_version_mismatch`|
|Concurrent divergence|`target_diverged`|
|Later match assumes original state|`sequential_match_invalid`|

Unexpected runtime failures are recorded as `transaction_internal_error`.

This explicit failure taxonomy is useful both for debugging and for instructing the LLM to regenerate a corrected PDCP. It also creates measurable outcomes for empirical evaluation: protocol-invalid rate, transaction-invalid rate, divergence rate, ambiguity rate, and regeneration success rate.

---

## 16. Rejection and Regeneration Loop

In PatchDIFF, rejection is not an exceptional crash state. It is a first-class transaction outcome. A rejected PDCP converts model-context uncertainty into structured diagnostic feedback.

A typical recovery loop is:

|Step|Action|
|--:|---|
|1|LLM emits PDCP from available context|
|2|Runtime rejects with `failure_reason`, `failed_change_id`, and `before_hash`|
|3|System retrieves fresh local context around the failed region|
|4|LLM regenerates only the failed PDCP transaction|
|5|Runtime validates against the canonical target again|

This loop does not require full-document rewriting. The target remains unchanged after rejection, and the next attempt can be generated from refreshed local context.

Rejected transactions are useful because they distinguish different causes of failure:

|Failure label|Interpretation|
|---|---|
|`match_absent`|The model’s exact assumed text is not present|
|`match_ambiguous`|The model selected text that appears multiple times|
|`target_hash_mismatch`|The target changed relative to an explicit hash precondition|
|`target_diverged`|A commit guard detected concurrent divergence|
|`sequential_match_invalid`|A later change assumed the original target rather than the updated in-memory state|
|`manifest_invalid`|The model emitted malformed semantic metadata|
|`executable_logic_detected`|The PDCP attempted to include runtime behavior outside payloads|

This makes failed edits informative rather than destructive. In LLM-agent settings, this is particularly important because agents may repeatedly act on external artifacts over many turns (Yao et al., 2023; Schick et al., 2023).

---

## 17. Structural Safety Model

PatchDIFF provides structural safety, not semantic correctness.

A valid PDCP file must not contain executable protocol logic. Outside `MATCH/REPLACE` payloads, the runtime rejects model-emitted imports, functions, loops, conditionals, shell commands, dynamic evaluation, network calls, filesystem operations, or external package references.

Executable-logic detection applies only to PDCP structural regions: the target declaration, manifest comments, disambiguation comments, and text outside `MATCH/REPLACE` payloads.

Payloads are different. `MATCH` and `REPLACE` blocks are opaque target-native text. They may contain functions, imports, shell-like syntax, or executable-looking content when that content belongs to the target being edited. The operator never executes payload text. It only compares and replaces literal canonical text.

This distinction lets PatchDIFF edit code and configuration files without allowing the model to define executable protocol behavior.

PatchDIFF does not guarantee that replacement text is safe, correct, secure, or aligned with user intent. It guarantees that the mutation is explicit, localized, precondition-checked, atomically applied, logged, and replayable.

---

## 18. Locality Policies and Large-Span Control

PatchDIFF does not require full-document regeneration for local edits, but the protocol can technically express large replacements. A `MATCH` block could contain most of a document, and a `REPLACE` block could rewrite it. Such a transaction would still be structurally valid if it satisfied exact preconditions, but it would undermine the intended cost and reviewability benefits.

Implementations may therefore enforce locality policies:

|Policy|Purpose|
|---|---|
|Maximum replacement ratio|Reject or escalate transactions that replace too much of the target|
|Maximum changed-span size|Preserve local-edit behavior|
|High-risk escalation|Require review for large or high-risk transactions|
|Manifest-risk consistency check|Flag large edits labeled as low risk|
|Per-transaction byte/token limits|Prevent bloated PDCP files|
|SAVE recommendation after large edits|Compact context after major changes|

These policies are not part of the core deterministic matching semantics. They are deployment-level controls that preserve PatchDIFF’s intended operating regime: many explicit local edits over one cached target rather than hidden full-document rewriting.

---

## 19. Persistence and Replay

PatchDIFF persists five artifact classes:

|Artifact|Purpose|
|---|---|
|`cloud_target_file`|Current canonical materialized target|
|`current_pdcp_file`|Most recent submitted PDCP for active-session display|
|`append_only_pdcp_log`|Accepted and rejected transaction history|
|`append_only_manifest_ledger`|Accepted semantic memory for future LLM turns|
|`target_snapshots`|Replay acceleration and checkpoint artifacts|

Only the PDCP log is authoritative for operational history. `current_pdcp_file` is not authoritative and may be overwritten by later submissions. Snapshots accelerate replay but do not replace the accepted transaction log as the reconstruction source.

A successful commit atomically persists:

1. updated target content,
    
2. updated target hash,
    
3. updated target version,
    
4. accepted PDCP log entry,
    
5. accepted manifest ledger entries.
    

No committed target state may exist without a corresponding accepted PDCP log entry. No manifest ledger entry may be accepted without a corresponding accepted PDCP log entry.

Replay reconstructs target state from:

`initial canonical target + ordered accepted PDCP log entries`

Replay requires the initial canonical target, ordered accepted PDCP log entries, the protocol version for each entry, and the canonicalization rules for that protocol version. Each accepted PDCP is parsed, validated, applied deterministically, and checked against the logged `after_hash`. A mismatch indicates data corruption, log tampering, or implementation incompatibility.

This replay model follows the event-sourcing principle that materialized current state can be reconstructed from an ordered operational history (Fowler, 2005), but adapts it to LLM-generated edit proposals and deterministic textual validation.

---

## 20. Cloud-State Consistency

PatchDIFF v0.2.3 assumes one active writer per target editing cycle.

The runtime must protect commits with an optimistic write guard using either expected target version or expected current hash. Before commit, it verifies that the stored target still matches the version or hash used during validation.

If not, the runtime rejects with `target_diverged`.

This prevents two commits to the same target from interleaving.

PatchDIFF v0.2.3 does not merge concurrent edits. It detects divergence and rejects the transaction. Future versions may use the append-only PDCP log as a substrate for multi-writer coordination, but conflict resolution is intentionally out of scope for v0.2.3.

This places PatchDIFF in contrast with operational transformation and CRDT systems, which aim to preserve convergence under concurrent updates (Ellis and Gibbs, 1989; Sun et al., 1998; Shapiro et al., 2011). PatchDIFF instead treats divergence as evidence that the model’s assumed context may no longer be safe to apply.

---

## 21. Runtime Interface

A minimal PatchDIFF runtime exposes six operations:

|Operation|Role|
|---|---|
|Initialize target|Upload, canonicalize, hash, and store a target|
|Submit PDCP|Parse, validate, apply or reject a transaction|
|Get target|Return current content, hash, and version|
|Get manifest ledger|Return accepted semantic memory|
|Get PDCP log|Return accepted and rejected operational history|
|SAVE|Snapshot target, export if requested, and compact active manifest context|

This interface is intentionally small. PatchDIFF does not require target-specific rewrite engines, AST adapters, semantic parsers, or model-generated tool orchestration.

---

## 22. SAVE Checkpointing and Compaction

SAVE is PatchDIFF’s checkpoint and context-compaction operation. It is not ordinary file saving. The target is already updated after each accepted transaction. SAVE snapshots the current materialized target, preserves the accepted PDCP log, exports the target if requested, and clears active model-facing manifest context only after snapshot success.

SAVE controls the asymptotic cost of long editing sessions. PatchDIFF avoids repeated full-document regeneration by using a cached target and compact manifest ledger, but an indefinitely growing ledger can eventually approach the cost of rereading the target. Therefore implementations should recommend SAVE when:

`manifest_ledger_tokens ≥ α × target_tokens`

Suggested initial values are:

|Policy|α|
|---|--:|
|Conservative compaction|0.25|
|Standard compaction|0.33|
|Aggressive editing session|0.50|

Additional SAVE triggers may include edit count, PDCP log size, completion of a coherent task, accumulated high-risk changes, or explicit export request.

If SAVE fails, the target remains canonical, the manifest ledger remains intact, the PDCP log remains replayable, and no history is lost. A failed SAVE must not clear the manifest ledger.

---

## 23. Evaluation Plan

PatchDIFF’s empirical claims should be evaluated against full-document regeneration, conventional unified diffs, line-number editing, and informal search-and-replace baselines.

A minimal evaluation should include three artifact classes:

|Artifact type|Examples|
|---|---|
|Technical prose|Markdown documentation, specifications|
|Source code|Python, JavaScript, TypeScript|
|Structured config|YAML, JSON, TOML|

### H1: PatchDIFF reduces full-document decoding cost

Measure model output tokens across target sizes and edit sizes.

Expected result:

|Workflow|Output scaling|
|---|---|
|Full regeneration|Approximately proportional to target size|
|Unified diff|Proportional to diff size but lacks transaction lifecycle|
|Line edits|Proportional to edit size but coordinate-fragile|
|PatchDIFF|Proportional to changed span plus manifest overhead|

### H2: PatchDIFF reduces unintended mutation

Measure the rate of changes outside user-requested regions.

Compare:

1. Full-document regeneration.
    
2. LLM-emitted unified diff.
    
3. Line-number editing.
    
4. Plain search-and-replace.
    
5. PatchDIFF PDCP.
    

The primary metric is unintended edit rate per task. PatchDIFF should preserve unmatched content exactly after canonicalization.

### H3: PatchDIFF improves stale-context detection

Simulate target divergence between model context generation and edit application.

|Metric|Meaning|
|---|---|
|Divergence detection rate|Fraction of stale edits rejected|
|Silent overwrite rate|Fraction of stale edits that mutate target incorrectly|
|Regeneration success rate|Fraction of rejected edits corrected after refreshed context|

PatchDIFF should have near-zero silent overwrite rate under exact hash and `MATCH` validation.

### H4: PatchDIFF supports multi-edit cached-document workflows

Run long editing sessions over one cached target.

|Metric|Meaning|
|---|---|
|Total decoding cost|Sum of model output tokens|
|Context cost|Target spans plus manifest ledger tokens|
|SAVE frequency|Number of compaction checkpoints|
|Edit throughput|Accepted edits per session|
|Recovery overhead|Extra turns caused by rejected PDCPs|

### H5: PatchDIFF preserves deterministic replay

Run accepted PDCP logs across independent runtimes or repeated replay executions.

|Metric|Meaning|
|---|---|
|Replay success rate|Fraction of logs reconstructing final target|
|Hash agreement|Whether replayed `after_hash` equals logged `after_hash`|
|Parser conformance|Whether valid/invalid corpora produce stable outcomes|

### H6: PatchDIFF improves reviewability

Conduct a human review study where participants inspect edits under full-regeneration diffs, unified diffs, line edits, and PatchDIFF manifests plus exact `MATCH/REPLACE`.

|Metric|Meaning|
|---|---|
|Review time|Time to understand change|
|Hidden mutation detection|Ability to identify unintended edits|
|Confidence|Reviewer-rated confidence|
|Error rate|Missed or misclassified changes|

### H7: LLMs can generate valid PDCP transactions

Measure whether models can reliably emit protocol-valid and transaction-valid PDCP.

|Metric|Meaning|
|---|---|
|Syntax-valid PDCP rate|Fraction satisfying parser requirements|
|Protocol-valid PDCP rate|Fraction satisfying manifest and block structure|
|Transaction-valid rate|Fraction applying successfully to current target|
|Success after refresh|Fraction succeeding after regenerated context|
|Failure distribution|Counts of `match_absent`, `match_ambiguous`, `manifest_invalid`, etc.|

This experiment is important because exact matching is intentionally strict. It also connects PatchDIFF to broader questions in LLM software engineering: models can often propose plausible code edits, but real-world utility depends on whether those proposals can be applied, validated, and recovered from when they fail (Chen et al., 2021; Jimenez et al., 2024).

---

## 24. Required Runtime Test Matrix

A PatchDIFF v0.2.3 implementation is not complete until it passes conformance tests covering exact matching, sequential mutation, edge cases, transaction atomicity, security boundaries, replay, divergence, and parser validity.

Required tests include:

|Test class|Examples|
|---|---|
|MATCH tests|Single match succeeds; zero match rejects; duplicate match rejects; case and whitespace mismatches reject|
|Sequential mutation tests|Later `MATCH` sees earlier `REPLACE`; later original-state `MATCH` fails|
|Edge cases|Empty `MATCH` rejects; empty `REPLACE` deletes; anchored insertion succeeds|
|Security boundary|Functions outside payload reject; functions inside payload are allowed|
|Transaction tests|One failed change rolls back all; rejected PDCP is logged; manifests append only on success|
|Replay tests|Accepted logs reconstruct target; altered log causes replay hash mismatch|
|Divergence tests|Hash mismatch rejects; version mismatch rejects; concurrent commit rejects|
|Parser conformance|Known-valid and known-invalid PDCP corpora produce deterministic results|

This test matrix converts PatchDIFF from an informal editing convention into a reproducible runtime contract.

---

## 25. Related Work

PatchDIFF draws on textual differencing, version control, JSON Patch, optimistic concurrency control, event sourcing, collaborative editing, semantic program transformation, structured patching, edit-based generation, retrieval-augmented generation, and LLM-assisted software engineering. Its novelty does not lie in inventing textual deltas. Instead, PatchDIFF identifies a missing systems layer for LLM editing: a transaction envelope around model-emitted textual diffs.

A raw diff describes a local edit. A PatchDIFF PDCP transaction describes a local edit together with semantic intent, assumed input state, expected output state, target identity, validation rules, failure labels, append-only logging, replay semantics, and compact model-facing memory.

### 25.1 Textual differencing and patch systems

Textual differencing has a long history in software engineering. Classical sequence-comparison algorithms such as longest common subsequence and shortest edit script methods provided the foundation for practical diff tools (Hunt and Szymanski, 1977; Myers, 1986). Unified diff and patch workflows then became standard mechanisms for reviewing and applying localized changes.

PatchDIFF inherits the practical insight that localized textual changes are preferable to full-state rewrites. At the edit-surface level, a PDCP `MATCH/REPLACE` block is intentionally diff-like: it identifies existing target-native text and replacement target-native text.

However, PatchDIFF is not merely another diff format. It addresses a different problem: how an LLM-generated textual delta should be validated, logged, summarized, and replayed when the model may have stale or incomplete context.

### 25.2 Version control and commit histories

Version-control systems such as Git provide durable commit histories, content addressing, branching, and review workflows (Chacon and Straub, 2014). PatchDIFF shares the view that changes should be recorded rather than hidden.

However, version control generally records accepted repository states or commits. PatchDIFF operates one layer earlier, inside the LLM edit proposal loop. It records not only accepted changes but also rejected PDCP transactions, including failure reasons and failed change identifiers. This is important because rejected LLM edits are informative: they may indicate stale context, ambiguous target spans, malformed protocol, or target divergence.

PatchDIFF also separates operational truth from semantic memory. The PDCP log is authoritative for replay. The manifest ledger is model-facing semantic memory and is populated only from accepted transactions.

### 25.3 JSON Patch and structured document patching

Structured patch formats such as JSON Patch define operations over path-addressable JSON documents (Bryan and Nottingham, 2013). These systems are effective when the target has a stable schema and structural representation.

PatchDIFF deliberately avoids requiring a target schema, AST, or normalized document. It operates on canonical UTF-8 target-native text. This makes it less structurally expressive than JSON Patch but more broadly applicable across Markdown, source code, YAML, JSON, HTML, prose, and other text-like artifacts.

The closest conceptual overlap is the idea of preconditioned mutation. JSON Patch includes test-like behavior over structured paths; PatchDIFF applies the precondition idea to arbitrary target-native text spans generated by an LLM. A `MATCH` block is not merely a search pattern. It is the model’s assertion that exact text remains present in authoritative state.

### 25.4 Optimistic concurrency control and MVCC

PatchDIFF’s strongest conceptual lineage is optimistic concurrency control. In optimistic concurrency systems, a transaction proceeds based on an assumed state and validates that assumption before commit. If the state has changed incompatibly, the transaction aborts (Kung and Robinson, 1981; Bernstein and Goodman, 1981).

PatchDIFF adapts this principle to LLM context. The problem is not only concurrent users modifying a file; it is also that the model may generate an edit from stale, partial, summarized, or hallucinated target context. PatchDIFF therefore treats exact `MATCH` text as a context-validity assertion.

The model asserts:

> This exact text is still present in the current target.

The runtime verifies:

> The canonical authoritative target contains this exact text under the declared constraints.

If the assertion fails, the transaction is rejected.

This is the core novelty relative to ordinary diff: PatchDIFF treats LLM-generated textual changes as transactions whose preconditions validate model context.

### 25.5 Event sourcing and replay

Event-sourced systems treat current state as the materialized result of an ordered event history (Fowler, 2005). PatchDIFF applies a similar idea to LLM-generated edits. The current cloud target is the materialized current view, while the append-only PDCP log is the operational reconstruction path.

Replay starts from an initial canonical target and applies ordered accepted PDCP entries. Each replayed transaction must reproduce the logged `after_hash`; otherwise replay fails.

This replay model is another reason raw diff alone is insufficient. In long LLM editing sessions, the system needs to reconstruct not only text but also the validated sequence of accepted model proposals. PatchDIFF’s accepted/rejected logs, hashes, protocol versions, and canonicalization rules make reconstruction explicit.

### 25.6 Operational transformation and CRDTs

Operational transformation and CRDT systems address collaborative editing and convergence under concurrent modification (Ellis and Gibbs, 1989; Sun et al., 1998; Shapiro et al., 2011). PatchDIFF v0.2.3 does not attempt this. It assumes one active writer per target editing cycle and rejects divergence rather than merging.

This is a deliberate design choice. In LLM-mediated editing, automatic merge can hide model-context errors. PatchDIFF instead makes conflicts explicit. If another process changes the target, a target hash mismatch, version mismatch, absent `MATCH`, ambiguous `MATCH`, or write-guard failure rejects the transaction.

Future versions may build multi-writer coordination on the append-only PDCP log, but v0.2.3 prioritizes deterministic rejection.

### 25.7 Program transformation and semantic patching

Semantic patching systems and AST-based refactoring tools modify programs using target-language structure. These tools can provide strong semantic guarantees but require parsers, ASTs, type information, or language-specific transformation rules (Padioleau et al., 2008).

PatchDIFF intentionally avoids this layer. It does not know whether the target is Python, Markdown, YAML, JSON, or prose. It treats every supported target as canonical UTF-8 text.

This makes PatchDIFF semantically weaker but operationally broader. It does not replace semantic validators, type checkers, linters, or test suites. Instead, it provides the deterministic textual transaction substrate beneath them.

### 25.8 Edit-based generation

Edit-based generation methods reduce generation cost by predicting edits rather than producing full sequences from scratch. Prior work such as LaserTagger and the Levenshtein Transformer showed that edit operations can improve efficiency in text generation settings, often by using token-level insert/delete/keep actions and model-specific training objectives (Malmi et al., 2019; Gu et al., 2019).

PatchDIFF differs in both target and mechanism. It does not require retraining, does not operate over token-level edit actions, and does not ask the model to own the full sequence transformation. Instead, it uses an ordinary LLM to emit a declarative transaction over target-native text, while a deterministic runtime validates and applies the transaction.

### 25.9 LLM-assisted editing and agentic software engineering

LLMs are increasingly used to generate, modify, and repair code and documents. Codex-style models demonstrated strong code-generation capabilities (Chen et al., 2021), while SWE-bench evaluates whether models can resolve real-world GitHub issues in existing repositories (Jimenez et al., 2024). Tool-use and agentic reasoning systems further show that models can interact with external tools and environments (Yao et al., 2023; Schick et al., 2023).

PatchDIFF’s claim is that these edit operations need a durable transaction envelope. A model-generated diff or tool call may be useful for a single edit, but iterative editing of long-lived artifacts requires more: semantic memory, accepted/rejected operational logs, context-drift diagnosis, replay, and structural-purity guarantees.

PatchDIFF separates proposal from authority:

|Component|Role|
|---|---|
|LLM|Proposes declarative PDCP transaction|
|Runtime|Validates and commits|
|Target|Remains authoritative|
|Log|Records accepted/rejected operational history|
|Manifest ledger|Provides accepted semantic memory|

This separation is especially important for LLM agents, where the model may repeatedly act on external artifacts over many turns.

### 25.10 LLM context management and memory

Long LLM editing sessions face context pressure. Systems often use retrieval, summaries, cached target views, or memory stores to reduce context cost. Retrieval-augmented generation demonstrates the value of selectively supplying relevant evidence to a model (Lewis et al., 2020), but retrieval can introduce stale, incomplete, or mismatched context.

PatchDIFF’s manifest ledger addresses semantic memory while preserving target authority. The ledger stores summaries of accepted edits so that future model turns can understand prior changes without receiving the full PDCP history or entire target. But the ledger is advisory. Every future edit must still pass exact `MATCH` validation against the canonical target.

SAVE checkpointing controls long-session growth by snapshotting the current target and clearing active manifest context only after successful snapshot. This makes PDCP not just an edit representation but a lifecycle protocol for iterative LLM editing.

---

## 26. Limitations

PatchDIFF deliberately accepts several tradeoffs.

### Exact matching is brittle

Whitespace changes, formatting drift, repeated text, or Unicode representation differences can cause rejection. This is intentional. PatchDIFF prefers deterministic failure over hidden repair.

### Exact matching can increase regeneration turns

A strict rejection policy may require additional turns to refresh local context and regenerate a corrected PDCP. This is the cost of converting stale-context risk into explicit failure rather than silent mutation.

### Semantic correctness is not guaranteed

PatchDIFF validates structural applicability, not semantic desirability. A valid replacement may still be wrong.

### The manifest can be misleading

The manifest is model-generated. It may understate risk, misdescribe intent, or omit an important user-visible change. The manifest is advisory semantic memory, not operational truth.

### The model needs sufficient target context

The LLM must see enough exact target-native text to produce valid `MATCH` blocks. Incomplete retrieval may produce rejected PDCPs.

### PatchDIFF does not eliminate retrieval

The manifest ledger reduces repeated semantic context, but it does not replace authoritative target retrieval. Every future edit remains subject to exact `MATCH` validation.

### v0.2.3 is single-active-writer

PatchDIFF rejects concurrent divergence rather than merging simultaneous edits.

### Large replacements are technically expressible

PatchDIFF does not require full-document regeneration, but a large `MATCH/REPLACE` transaction can approximate a rewrite. Deployment policies should limit or escalate large-span edits when locality is required.

### Rich and binary formats require textual representations

PatchDIFF operates on canonical UTF-8 text. Binary formats and rich documents require stable textual serialization before use.

### SAVE thresholds require calibration

The proposed manifest-ledger compaction thresholds are heuristics. Their optimal values depend on target size, edit frequency, model context costs, and user workflow.

### Delimiter collision requires future hardening

The v0.2.3 format uses textual delimiters for `MATCH/REPLACE` blocks. Future versions may adopt delimiter escaping or length-prefixed payloads to prevent delimiter collision in arbitrary targets.

### Empirical claims remain to be validated

PatchDIFF’s theoretical advantages in decoding cost, drift reduction, stale-context detection, and reviewability require empirical validation. The evaluation plan in Section 23 specifies the hypotheses and metrics needed to test these claims.

---

## 27. Discussion

PatchDIFF’s central design choice is to move trust away from model-generated full states and into deterministic validation against authoritative state.

This does not make LLM edits semantically correct. Instead, it changes the failure mode. A stale or ambiguous edit becomes a rejected transaction rather than a silent overwrite. A proposed mutation becomes an explicit textual delta rather than an opaque regenerated artifact. Reviewers inspect the exact old text, exact new text, and stated semantic intent.

This is especially important for long-lived artifacts. In a multi-turn editing session, the model may not have a perfect view of the current target. PatchDIFF makes that uncertainty operationally visible. The runtime asks: does the exact text the model claims to edit still exist in the target? If not, the model must regenerate its proposal from fresh context.

PatchDIFF is intentionally less ambitious than semantic editing. It does not know whether a Python edit type-checks, whether a YAML change preserves security, or whether a document revision remains factually accurate. Those checks can be layered above or after PatchDIFF. The base protocol ensures that the textual mutation itself is explicit, deterministic, logged, and replayable.

The key conceptual shift is from “smaller output” to “transactional validity.” Token savings and reduced latency may result from localized output, but they are not the main invention. The main invention is the transaction envelope required to make localized LLM-generated edits safe to apply, remember, reject, audit, and replay.

PatchDIFF turns LLM-generated diffs from review artifacts into deterministic cached-document edit transactions.

---

## 28. Future Work

Future work includes both empirical evaluation and protocol extensions.

Evaluation work should measure:

|Area|Question|
|---|---|
|MATCH failure rates|How often exact matching rejects useful edits?|
|Drift reduction|How much hidden mutation does PatchDIFF prevent?|
|Token and latency savings|How does cost scale with target size and edit size?|
|Human review|Do reviewers detect errors faster with PatchDIFF?|
|SAVE calibration|What compaction threshold minimizes total context cost?|
|PDCP generation reliability|How often do LLMs generate valid PDCP on the first attempt?|

Protocol extensions may include:

|Extension|Purpose|
|---|---|
|Formal EBNF grammar|Stronger parser conformance|
|Delimiter escaping or length-prefixing|Avoid delimiter collision|
|Multi-writer coordination|Support concurrent editing cycles|
|Semantic validation layers|Optional type-checking, linting, policy checks|
|Editor integrations|IDE and document-editor workflows|
|Rich diagnostics|Better model feedback after rejection|
|Version negotiation|Stable replay across protocol evolution|

The core constraint for future versions is that deterministic replay and explicit textual validation should remain preserved.

---

## 29. Conclusion

PatchDIFF reframes LLM editing as deterministic transaction control over cached authoritative text.

The contribution is not that local textual deltas exist. The contribution is that LLM-generated deltas need an execution protocol: exact preconditions, runtime validation, atomic commit, rejected-edit diagnostics, append-only logs, deterministic replay, semantic memory, and checkpoint compaction.

In PatchDIFF, the model does not rewrite the document. It proposes a declarative transaction. The runtime validates the model’s assumed context against the current canonical target. Accepted edits mutate only matched spans. Rejected edits leave the target unchanged and become structured feedback for regeneration.

This design enables low-decoding-cost multi-turn editing over one cached document while preserving auditability, replayability, structural safety, and explicit user-visible deltas.

PatchDIFF provides structural safety rather than semantic correctness. It does not decide whether an edit is good. It ensures that the edit is grounded in current target state, applied only under exact preconditions, committed atomically, and preserved in an append-only audit trail.

In doing so, PatchDIFF transforms LLM editing from opaque full-state regeneration into validated textual state transition over authoritative state.

---

## References

Bernstein, P. A., and Goodman, N. (1981). Concurrency control in distributed database systems. _ACM Computing Surveys_, 13(2), 185–221.

Bryan, P., and Nottingham, M. (2013). _RFC 6902: JavaScript Object Notation (JSON) Patch_. Internet Engineering Task Force.

Chacon, S., and Straub, B. (2014). _Pro Git_. Apress.

Chen, M., Tworek, J., Jun, H., Yuan, Q., Pinto, H. P. O., Kaplan, J., Edwards, H., Burda, Y., Joseph, N., Brockman, G., et al. (2021). Evaluating large language models trained on code. _arXiv:2107.03374_.

Ellis, C. A., and Gibbs, S. J. (1989). Concurrency control in groupware systems. _Proceedings of the ACM SIGMOD International Conference on Management of Data_, 399–407.

Fowler, M. (2005). Event Sourcing. martinfowler.com.

Gu, J., Wang, C., and Zhao, J. (2019). Levenshtein Transformer. _Advances in Neural Information Processing Systems_, 32.

Hunt, J. W., and Szymanski, T. G. (1977). A fast algorithm for computing longest common subsequences. _Communications of the ACM_, 20(5), 350–353.

Jimenez, C. E., Yang, J., Wettig, A., Yao, S., Pei, K., Press, O., and Narasimhan, K. (2024). SWE-bench: Can language models resolve real-world GitHub issues? _International Conference on Learning Representations_.

Kung, H. T., and Robinson, J. T. (1981). On optimistic methods for concurrency control. _ACM Transactions on Database Systems_, 6(2), 213–226.

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W., Rocktäschel, T., Riedel, S., and Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. _Advances in Neural Information Processing Systems_, 33.

Malmi, E., Krause, S., Rothe, S., Mirylenka, D., and Severyn, A. (2019). Encode, Tag, Realize: High-Precision Text Editing. _Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing_.

Myers, E. W. (1986). An O(ND) difference algorithm and its variations. _Algorithmica_, 1, 251–266.

Padioleau, Y., Lawall, J. L., Muller, G., and Hansen, R. R. (2008). Documenting and automating collateral evolutions in Linux device drivers. _Proceedings of the European Conference on Computer Systems_, 247–260.

Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Hambro, E., Zettlemoyer, L., Cancedda, N., and Scialom, T. (2023). Toolformer: Language models can teach themselves to use tools. _Advances in Neural Information Processing Systems_.

Shapiro, M., Preguiça, N., Baquero, C., and Zawirski, M. (2011). Conflict-free replicated data types. _International Symposium on Stabilization, Safety, and Security of Distributed Systems_, 386–400.

Sun, C., Jia, X., Zhang, Y., Yang, Y., and Chen, D. (1998). Achieving convergence, causality preservation, and intention preservation in real-time cooperative editing systems. _ACM Transactions on Computer-Human Interaction_, 5(1), 63–108.

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., and Cao, Y. (2023). ReAct: Synergizing reasoning and acting in language models. _International Conference on Learning Representations_.