# DEV-RUN-002: invalid-input evidence decision

Recorded before coding, 2026-10-21. Base: selector PR #4, source branch fix/devin-unicode.

## Selected design

Use existing rejected-attempt TEXT and JSONB fields. No new table, migration, general encoding framework, transaction operation, runtime profile, or audit exception.

For a nonpersistable Unicode input, store one deterministic ASCII-escaped JSON evidence envelope in pdcp_content. The envelope retains the original record and submitted metadata as escaped JSON text, so decoding the stored TEXT representation can recover the offending code points without inserting them into PostgreSQL text or JSONB values. A small diagnostic marker identifies this representation and offending input paths. JSONB stores only safe scalar/path/marker values or an escaped evidence STRING, never decoded surrogate values. Prefer the smallest local helper; do not construct a generic serialization framework.

Validate nested user string values and string keys before hashing and normal storage. Include match/replace, anchors, intent/rationale and legacy text, guards, request/parent IDs and submission/retry metadata where exposed. Do not repair text or use replacement encoding. PostgreSQL text constraints must be respected by every value written. Unknown/malformed target identity still cannot create a target-linked log; return a safe structured response without echoing nonpersistable text.

A known target follows the existing locked _submit rejection path, with failure reason target_encoding_invalid and stage PROTOCOL_VALIDATION. The proposal must not be applied. Valid input continues using its exact existing canonical_record_json/canonical_sha256 representation and fingerprint.

## Invalid-input identity and recovery

For an otherwise valid client request key, fingerprint the complete deterministic safe evidence plus original guards/parent identity, with an explicit invalid-evidence marker/domain so a normal valid-input record cannot alias it. Add that marker only for invalid input; existing valid fingerprints remain byte-for-byte unchanged. Look up a safe persisted key under the same target lock and recover its recorded terminal outcome before stale-guard checks. Invalid/unencodable request keys use NULL on the rejection row and preserve the submitted value only in safe evidence. Do not query PostgreSQL with a surrogate-bearing key.

The complete original invalid submission is reversible from safe evidence; diagnostic previews may be bounded. Rejected records do not enter accepted-history replay. Legacy accepted hashes/logs are untouched. Metadata written to ordinary TEXT/JSONB columns must be safe, with any encoded value explicitly described as evidence rather than corrected input.

## Read/search boundary

Validate read/search string inputs, particularly find_occurrences.text and target identity, at the service boundary. Return invalid_argument with safely serialized error evidence and no edit-attempt row. This is not an assertion that reads currently perform the same failing hash. Preserve exact search and existing paging/context semantics; context_chars fixing stays in DEV-MCP-001.

## Verification and stop conditions

Pure/service matrices cover each text/metadata/nested field, isolated high/low surrogates, escaped JSON, valid non-ASCII and supplementary text. Actual PostgreSQL verifies rejected persistence, keyed retry, caller-owned commit/rollback and unchanged target/version/ledger. Actual stdio must return a domain rejection and readable safe stored evidence.

If this representation proves unsuitable or requires an audit exception, new operation, migration or encoding framework, stop and report before expanding scope. Catch anticipated encoding/input failures only; infrastructure exceptions stay with the transaction owner.

Implementation may refine exact marker/envelope names within this decision, with the final names documented and tested. No invalid-input encoding choice may change valid proposal identity.

## Exact representation selected

The rejected TEXT envelope is {"evidence_format":"patchdiff-invalid-input/1","inputs":{...}}, serialized with sorted keys, compact separators, ensure_ascii=True and existing default=str handling for direct Python UUID values. inputs retains original target identity, record, guards, request/parent IDs and submission/retry metadata. Unicode scalar errors and PostgreSQL-forbidden NUL both use this representation.

The safe JSONB marker is evidence_format="patchdiff-invalid-input/1", with invalid_input_paths (at most 20 escaped paths, 256 characters each) and invalid_input_paths_truncated. Only diagnostic paths are bounded; the complete admitted input remains reversible from TEXT evidence. Invalid-only fingerprints add identity_domain="patchdiff-invalid-input/1" to the existing fingerprint envelope. Valid-input fingerprint envelopes and hashes are unchanged.

New public parse_typed_record validation checks nonpersistable strings; recorded decode_record retains historical decoding. In particular, an ignored NUL anchor could previously be stored as an escaped JSON string and accepted under the singleton behavior; its replay must remain valid. The historical regression preserves its recorded text/hash/fingerprint.

For recovery only, an existing unmarked historical row may also match its original fingerprint when the original serialized proposal is persistable (for example JSON-escaped NUL) including parent UUID text that was previously rejected without being bound to PostgreSQL. Recompute that historical lookup-only fingerprint from original guards and original parent identity. This preserves previously admitted accepted or rejected outcomes without reapplying a proposal now disallowed at the new boundary. New invalid rows retain the explicit invalid-input domain; no existing fingerprint is rewritten.
