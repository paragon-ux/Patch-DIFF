# Public backend verification

These deterministic checks are part of CI. Internal model experiments, controllers,
transcripts, generated exports and performance captures remain in the ignored local
`evaluation/` directory and are not required by a clean checkout.

From the repository root, with the locked dependencies installed:

```powershell
$env:PYTHONPATH = '.;backend'
python backend/tests/verification/offline_eval.py
python backend/tests/verification/structural_batch/verify.py --output <new-directory>
```

The offline check verifies serialization byte accounting and deterministic verdict /
replacement equivalence without a model, database or network. The five-file check
requires live PostgreSQL, the pinned Waymark npm installation and real stdio MCP.
It verifies five atomic batches, SAVE and replay, exact full-file bytes and 20
behavioral assertions. It makes no live-model or comparative performance claim.

`structural_batch/primary/` contains only the original five regression fixtures,
task text and independent oracle dependencies. Fixture/task identities and expected
output hashes are pinned by the oracle. The fixtures and task retain their original
bytes; the oracle is checked before any resulting Python module is executed.

`structural_batch/operations.json` contains the existing 20 groups / 54 declarative
operations extracted from the authenticated original Arm C transcript at source
`703e6381a001c16e96c798d1e011589f6f294549`. The verifier pins its SHA-256
`43625f22c9c2bf46c6fddbb2757c1b940bfbcdd9b55a52b239ac61a4a853a70a`.
The extraction changes neither selectors nor operation values. CI needs this compact
input instead of the entire historical transcript, exported solutions or study
controller. Never use these prepared operations to perform a live model canary.

Test output belongs in a new external directory or the ignored `.ci-results/`.
Historical documents can reference the original local evaluation paths; current
reproduction commands use this directory.
