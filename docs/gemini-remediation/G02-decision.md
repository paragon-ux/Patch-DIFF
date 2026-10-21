# G02 pre-code decision: explicit UTF-8 stdio

Date: 2026-10-21. Base: b5caa40bd41848420c4323d22ab648847cdc6745.
Authority: docs/reviews/gemini/GEMINI_CHANGE_PLAN.md and Gemini-Goal-G.md; user authorized beginning Goal G.

## Observed defect

The archived raw-byte controls prove cp1252 stdin decodes valid literal UTF-8 star bytes as mojibake which can be accepted and stored. Escaped Unicode and the UTF-8 workaround pass. The reported stdout crash did not reproduce; no general unhandled-exception fix is selected.

## Selected change

At the external process main entry point, configure sys.stdin and sys.stdout as UTF-8 with strict errors before serve_stdio runs. Reconfigure the existing text wrappers rather than replacing streams; this preserves the already-bound default stream references. Keep the injectable serve_stdio interface for tests. Do not reconfigure stderr: protocol traffic is stdin/stdout, and stderr remains diagnostics.

Malformed wire UTF-8 fails decoding and must not result in an accepted mutation. No repair/ignore policy, surrogateescape transport fallback, new JSON-RPC error contract, migration, runtime profile or dependency is introduced. A specific malformed-wire process exit is not promised; exact JSON-level validation remains separate.

Valid JSON ASCII escapes still decode into the same proposal fields. Existing known-target surrogate/NUL domain rejection, reversible evidence, fingerprints, keyed recovery and audit ownership are preserved. Configure strict errors explicitly so an ambient cp1252/surrogateescape setting cannot persist decoded invalid bytes.

## Verification and documentation

Implement a minimal main-entry configuration test with injected streams and real raw-byte subprocess coverage, including explicit cp1252 ambient configuration (portable reproduction) and absent overrides. Verify actual database text, versions, log/ledger counts, escaped invalid-domain inputs, and continuation after handled argument error. Run required unit/integration/offline checks plus a separate manual workflow and independent read-only SQL proof.

Update setup/host documentation and the current change record. Preserve native reproduction registration/config; fixed-code manual subprocesses explicitly select this checkout. Keep evidence and independent review under docs/gemini-remediation, with source pins and the limits of local versus CI evidence.

