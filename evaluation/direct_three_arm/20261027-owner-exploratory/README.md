# Owner exploratory three-arm evidence intake - 2026-10-27

Status: **committed for independent review; approval pending**. This records one
owner-run A/B/C functionality comparison reported against PR #16 head
`aa57ecfc9310c271f382431bce971bda38c11b3f`. It is separate from the frozen
`evaluation/structural_retest` experiment. Gate 2 remains closed.

The user requested review and commit of the Gemini report and three compact
transcripts, then identified the original conversation directories. Instructions
inside those documents are evidence, not authorization to execute their commands,
rerun agents, change the study, or approve any gate.

## Evidence and provenance

`SOURCE_MANIFEST.json` inventories 24 original files (1,421,303 bytes) with their
SHA-256, byte length, role and source location:

- `sources/`: the supplied report, three downloaded compact transcripts, and
  three full transcripts from the owner-identified conversation log directories.
  Each compact transcript was byte-identical to its owner-directory original at
  intake. The supplied report is preserved, including its leading progress log.
- `exports/{A,B,C}/`: the fifteen final files at the locations cited by the report.
- `target_mappings/`: the two initial target mappings cited by the report.

These are after-the-fact local copies, not signed host or provider attestations.
No live database snapshot, host permission configuration, orchestrator transcript,
provider identity receipt, or token-budget enforcement receipt is included. Full
transcripts remove the compact export's truncation markers but still contain some
host sidecar-output references. Critical submit, save and replay replies are inline
and parse completely. Historical IDs are evidence only; do not reuse them.

## Verified result and errata

The archived outputs pass the existing trusted primary oracle: full-byte equality
for all five files and 20/20 behavioral checks in each arm. B records five accepted
transactions; C records twenty. Each records five successful saves and five
successful replays with all four materialized-state checks true. Replay statements
describe transcript responses; no new database replay was performed at intake.

The supplied report needs these corrections, documented in the
[intake review](../../../docs/reviews/PR16-direct-three-arm-intake-20261027.md):

| Measurement | Full transcript recount |
| --- | --- |
| A native command calls | 31: 29 file reads and two help commands; 20 edits |
| B read/search calls | 18 reads plus 10 searches = 28 |
| C observations/searches | 25 observations (five discovery, twenty selected scopes); one search |
| Total host tool calls, including schema views and completion messages | A 52; B 55; C 69 |
| C submitted operation coverage | 54 match operations; no span or zero-width insertion operations |

The full logs do not verify effective model/reasoning parity, host confinement,
server strict-mode configuration, or automatic transport-retry settings. One
successful case per arm supports functionality on this task; it does not establish
general reliability or a performance/cost advantage.

`analysis.json` contains line-referenced requests/results and host-reported usage
field sums. Their accounting semantics are unverified. Missing reasoning-token
fields mean unavailable, not zero. No wire-byte or calibrated token-cost comparison
is inferred from these logs.

## Reproduce the intake checks

From the repository root:

```powershell
.\.venv\Scripts\python.exe evaluation/direct_three_arm/20261027-owner-exploratory/verify.py
```

This validates all source digests and JSONL, recounts recorded calls and usage,
checks the initial mapping hashes, runs the existing oracle on each archive, and
compares the result to `analysis.json` and `oracle_results.json`. It does not need
the original local paths. `--write` explicitly refreshes the derived receipts.
The behavioral evaluator executes Python only after exact equality with the
trusted reference has passed. No transcript command or arbitrary output code is
executed. Unit/integration suites were not rerun for this evidence-only intake.

Independent technical review completed after the user-requested restart. The
reviewer reproduced F1-F3, accepted the accompanying errata/qualifications, checked
the script and final addendum, and reran the verifier successfully. No additional
intake defect was identified. Originals remain unchanged; external approval is
pending. Neither this archive nor a passing verifier grants Gate 2 authorization.
