# PDCP_FORMAT.md

## Scope

This document defines the MVP `.pdcp` file format for the MCP-first PatchDIFF server.

PDCP is declarative and non-executable.

`.pdcp` files are not Python, JavaScript, C, JSON, YAML, or any target language. The trusted runtime may be implemented in Python, but `.pdcp` content must never be executed.

## File Structure

One `.pdcp` file is one atomic PatchDIFF transaction.

The MVP file shape is:

```text
PDCP 0.2.3
target_file_id: <target id>
target_type: <target content type>
target_hash: <optional sha256>

# MANIFEST
# change_id: ...
# intent: ...
# input_state: ...
# output_state: ...
# affected_region: ...
# user_visible_change: ...
# risk: low|medium|high
# anchor_before: <optional>
# anchor_after: <optional>
# occurrence_index: <optional>
# region_hint: <optional>
# target_hash: <optional>

<<<<<<< MATCH
<exact current target-native text>
=======
<exact desired target-native text>
>>>>>>> REPLACE
```

Multiple manifest-plus-block sections may appear in one file. They execute sequentially against the progressively updated in-memory target.

## Header

The header is protocol-native and must appear at the top of the file in this order:

```text
PDCP 0.2.3
target_file_id: <value>
target_type: <value>
target_hash: <value>    # optional
```

Rules:

- line 1 must be exactly `PDCP 0.2.3`
- `target_file_id` is required
- `target_type` is required for the MVP build docs
- file-level `target_hash` is optional and acts as a whole-transaction precondition
- unknown header fields are invalid in MVP
- Python-style headers such as `C = "target_file_id:example_001"` are invalid for the MCP-first MVP

Failure mapping:

- missing or malformed header -> `context_invalid`
- missing `target_file_id` or `target_type` -> `context_missing`
- file-level `target_hash` precondition fails before validation begins -> `target_hash_mismatch`

## Manifest Block Format

Each change must include one manifest block immediately before its corresponding `MATCH/REPLACE` block.

The manifest begins with:

```text
# MANIFEST
```

Each field uses one line:

```text
# field_name: value
```

Parsing rules:

- the first colon separates field name from value
- additional colons remain part of the value
- required values must not be empty
- duplicate fields in the same manifest are invalid
- multiline manifest values are not supported in MVP
- duplicate `change_id` values within one `.pdcp` file are invalid

### Required manifest fields

```text
change_id
intent
input_state
output_state
affected_region
user_visible_change
risk
```

### Valid `risk` values

```text
low
medium
high
```

Failure mapping:

- missing manifest block -> `manifest_missing`
- missing required field, duplicate field, empty value, duplicate `change_id`, or invalid `risk` -> `manifest_invalid`

## Optional Disambiguation Fields

The following manifest fields are optional and are used only when exact `MATCH` text appears more than once or when an explicit hash guard is desired:

```text
anchor_before
anchor_after
occurrence_index
region_hint
target_hash
```

Rules:

- `occurrence_index` is 1-based over the ordered list of exact `MATCH` occurrences
- `anchor_before` and `anchor_after` are exact text constraints after canonicalization
- `region_hint` is advisory only and must not select a candidate by itself
- manifest-level `target_hash` is checked before `MATCH` evaluation for that change
- if both header-level and manifest-level `target_hash` are present and unequal, reject with `target_hash_mismatch` before `MATCH` evaluation

Failure mapping:

- multiple exact matches and no disambiguation -> `match_ambiguous`
- invalid `occurrence_index`, conflicting anchors, zero candidates, or multiple remaining candidates -> `disambiguation_invalid`
- manifest-level `target_hash` precondition fails before validation begins -> `target_hash_mismatch`

## `MATCH/REPLACE` Block Syntax

Each change uses the following exact delimiter lines:

```text
<<<<<<< MATCH
<match payload>
=======
<replace payload>
>>>>>>> REPLACE
```

Rules:

- `MATCH` payload is required and must be non-empty after canonicalization
- `REPLACE` payload may be empty
- empty `REPLACE` means deletion
- whitespace-only `REPLACE` is valid
- the payload is opaque target-native text and is never executed
- `MATCH` is exact, case-sensitive, whitespace-sensitive after canonicalization, and multiline
- changes are applied sequentially in file order

Failure mapping:

- malformed delimiters or malformed block order -> `block_malformed`
- empty `MATCH` payload -> `block_malformed`
- zero exact matches -> `match_absent`
- later change fails only because the target was already mutated by an earlier accepted change in the same transaction -> `sequential_match_invalid`

## Deletion

Deletion is represented by a non-empty `MATCH` and an empty `REPLACE`:

```text
<<<<<<< MATCH
Old sentence.
=======
>>>>>>> REPLACE
```

This deletes `Old sentence.` exactly where it matched.

## Anchored Insertion

Pure zero-length insertion is not supported in the MVP.

Insertion must be expressed as anchored replacement of existing non-empty text:

```text
<<<<<<< MATCH
## Summary
=======
## Summary

New paragraph inserted after the heading.
>>>>>>> REPLACE
```

Rules:

- `MATCH` must still be non-empty
- the replacement must include the original anchor text plus the inserted text
- cursor-style insertion with an empty `MATCH` is invalid

Failure mapping:

- zero-length insertion attempt -> `block_malformed`

## Ambiguity Behavior

Default behavior:

- if exact `MATCH` text resolves to exactly one span, PatchDIFF selects it
- if exact `MATCH` text resolves to zero spans, reject
- if exact `MATCH` text resolves to multiple spans, reject unless disambiguation reduces it to exactly one span

The runtime must not use:

- fuzzy matching
- semantic matching
- AST matching
- language-aware repair
- automatic merge

## Canonicalization

Canonicalization applies to:

- target content
- `MATCH` payloads
- `REPLACE` payloads

Rules:

```text
encoding: UTF-8
newline form: LF
normalize CRLF to LF
normalize CR to LF
preserve tabs
preserve spaces
preserve trailing whitespace
preserve final newline
no Unicode normalization
```

Consequences:

- `\r\n` and `\r` are normalized to `\n`
- tabs remain tabs
- ordinary spaces remain ordinary spaces
- trailing whitespace remains significant
- a final newline is preserved if it exists in the submitted or stored canonical text
- visually similar but codepoint-different Unicode strings do not silently normalize into equality

## Structural Purity

Outside payload regions, a `.pdcp` file may contain only:

- the protocol header
- blank lines
- `# MANIFEST`
- manifest field lines beginning with `# `

Outside payload regions, the runtime must reject obvious executable logic such as:

- imports
- functions
- classes
- loops
- conditionals
- tool calls
- shell commands
- network calls
- filesystem calls

Failure mapping:

- executable logic outside payloads -> `executable_logic_detected`

Code-like text inside `MATCH` or `REPLACE` payloads is allowed because the target itself may be source code.

## Delimiter Collision Behavior

The MVP uses raw textual delimiters and does not support delimiter escaping or length-prefixed payloads.

MVP rule:

- if any payload line is exactly one of the delimiter lines
  - `<<<<<<< MATCH`
  - `=======`
  - `>>>>>>> REPLACE`
- the runtime rejects the file deterministically

Recommended failure mapping:

- treat delimiter collision as `block_malformed`

Future versions may add escaping or length-prefixed payloads, but not in the MCP-first MVP.

## Valid Examples

### Valid replacement

```text
PDCP 0.2.3
target_file_id: target_123
target_type: text/markdown
target_hash: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

# MANIFEST
# change_id: chg_001
# intent: Clarify the SAVE definition.
# input_state: The section is brief.
# output_state: The section explicitly states that SAVE preserves history.
# affected_region: SAVE section
# user_visible_change: SAVE now explains that logs and ledger history are preserved.
# risk: low

<<<<<<< MATCH
SAVE is checkpointing and active manifest context compaction.
=======
SAVE is checkpointing and active manifest context compaction. It preserves append-only PDCP log and manifest ledger history.
>>>>>>> REPLACE
```

### Valid anchored insertion with disambiguation

```text
PDCP 0.2.3
target_file_id: target_456
target_type: text/markdown

# MANIFEST
# change_id: chg_002
# intent: Insert a warning after the Summary heading.
# input_state: The Summary heading has no warning text.
# output_state: The Summary heading is followed by a warning sentence.
# affected_region: Summary heading
# user_visible_change: A warning sentence is inserted under Summary.
# risk: low
# anchor_before: ## Summary
# occurrence_index: 1

<<<<<<< MATCH
## Summary
=======
## Summary

Warning: replay depends only on accepted PDCP log entries.
>>>>>>> REPLACE
```

## Invalid Examples

### Invalid Python-style header

```text
C = "target_file_id:target_123"

# MANIFEST
# change_id: chg_bad
# intent: Invalid header example.
# input_state: Old text exists.
# output_state: New text exists.
# affected_region: example
# user_visible_change: Example changes.
# risk: low

<<<<<<< MATCH
old
=======
new
>>>>>>> REPLACE
```

Why invalid:

- uses archival `C = ...` format instead of protocol-native MCP-first header

### Invalid executable logic outside payload

```text
PDCP 0.2.3
target_file_id: target_123
target_type: text/plain

def applyPDCP():
    pass

# MANIFEST
# change_id: chg_bad
# intent: Invalid executable logic example.
# input_state: Old text exists.
# output_state: New text exists.
# affected_region: example
# user_visible_change: Example changes.
# risk: low

<<<<<<< MATCH
old
=======
new
>>>>>>> REPLACE
```

Why invalid:

- executable logic appears outside payloads

### Invalid zero-length insertion

```text
PDCP 0.2.3
target_file_id: target_123
target_type: text/plain

# MANIFEST
# change_id: chg_bad_insert
# intent: Attempt unsupported cursor insertion.
# input_state: No inserted text exists.
# output_state: Inserted text would appear at a cursor location.
# affected_region: example
# user_visible_change: Example insertion.
# risk: low

<<<<<<< MATCH
=======
inserted text
>>>>>>> REPLACE
```

Why invalid:

- `MATCH` is empty
- MVP does not support zero-length cursor insertion

## Non-Negotiable Constraints

- `.pdcp` files are declarative and non-executable.
- `.pdcp` files must never contain generated `applyPDCP` functions.
- `.pdcp` files must never contain loops, conditionals, imports, tool calls, shell commands, or runtime logic outside payloads.
- `.pdcp` files must never perform mutation outside selected exact `MATCH` spans.
- regenerated `.pdcp` content must still pass the same format and validation rules from scratch.
