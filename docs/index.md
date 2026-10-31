# PatchDIFF Documentation

Welcome to the PatchDIFF documentation. PatchDIFF is a server-side, deterministic document transaction service designed for MCP-connected agents and automated workflows.

PatchDIFF transforms untrusted, model-generated text edits into **explicitly preconditioned, atomic, auditable, and deterministically replayable PostgreSQL transactions** over the Model Context Protocol (MCP).

---

## Documentation Structure

```text
docs/
├── spec/          Normative specifications and protocol contracts
├── guides/        Host integration, client setup, and workflow recipes
├── benchmarks/    Empirical evaluation reports and test matrix
├── papers/        Conceptual whitepapers and architecture records
├── standards/     Engineering standards, PR review rubric, and release checklist
└── legacy/        Frozen legacy formats, deprecated wrappers, and historical profiles
```

---

## 1. Specifications (`docs/spec/`)

Authoritative technical specifications and tool schemas:

- [**PATCHDIFF_CORE_SPEC.md**](spec/PATCHDIFF_CORE_SPEC.md): Pure deterministic core runtime, validation stages (`ValidationStage`), overlapping-match enumeration, sequential simulation, and replay engine.
- [**MCP_TOOLS.md**](spec/MCP_TOOLS.md): Complete Model Context Protocol tool contracts, schemas, byte budgets, and request/response representations.
- [**DATA_MODEL.md**](spec/DATA_MODEL.md): PostgreSQL relational substrate, row-locking concurrency model (`SELECT ... FOR UPDATE`), and Alembic migrations `20260510_0001` through `20261027_0005`.
- [**PDCP_FORMAT.md**](spec/PDCP_FORMAT.md): Declarative transaction input formats: typed edits (`patchdiff-tx/1`), guarded match/span operations (`patchdiff-tx/2`), and guarded sole replacement (`patchdiff-tx/3`).
- [**MCP_EDITOR_V2.md**](spec/MCP_EDITOR_V2.md): Streamlined 5-tool `observed_v2` editor profile with explicit reusable snapshots and bounded receipts (`<= 2 KB`).
- [**STRUCTURAL_BATCH_EDITING.md**](spec/STRUCTURAL_BATCH_EDITING.md): Multi-scope AST observation and atomic batch execution contracts.
- [**WAYMARK_WORKER.md**](spec/WAYMARK_WORKER.md): Resident worker process architecture and IPC lifecycle for external AST engines.

---

## 2. Host & Client Guides (`docs/guides/`)

Practical guides for integrating PatchDIFF with agents and desktop tools:

- [**HOST_INTEGRATION_GUIDE.md**](guides/HOST_INTEGRATION_GUIDE.md): Host-owned loop, prompt hygiene rules, reading slices, guarded submissions, handling rejections, and retry orchestration.
- [**CLAUDE_DESKTOP_SETUP.md**](guides/CLAUDE_DESKTOP_SETUP.md): Step-by-step configuration for connecting Anthropic Claude Desktop to PatchDIFF via stdio MCP.
- [**OBSERVED_EDITOR_WORKFLOW.md**](guides/OBSERVED_EDITOR_WORKFLOW.md): End-to-end walkthrough for agents using structural observation and atomic batch submission.

---

## 3. Benchmarks & Verification (`docs/benchmarks/`)

Empirical validation and testing methodology:

- [**modernized_benchmark_report.md**](benchmarks/modernized_benchmark_report.md): Standalone Modernized 2×2 Factorial Benchmark ($N=12$) demonstrating a -55.8% step reduction, -57.8% tool invocation reduction, -64.8% token reduction, and zero Git verification tax.
- [**git_benchmark_report.md**](benchmarks/git_benchmark_report.md): Complete baseline 2×2 factorial evaluation ($N=12$) comparing Native Control against Full PatchDIFF across Git and Non-Git environments.
- [**TEST_MATRIX.md**](benchmarks/TEST_MATRIX.md): Comprehensive test coverage matrix across unit, live PostgreSQL, migration roundtrip, and stdio subprocess tests.

---

## 4. Concept Papers & Architecture Records (`docs/papers/`)

Conceptual foundations, design rationale, and modernization history:

- [**PatchDIFF-Concept-Paper-6.md**](papers/PatchDIFF-Concept-Paper-6.md): Modernized conceptual whitepaper: theoretical model, comparison with other editing paradigms, operational efficiency bounds, and empirical research hypotheses.
- [**MODERNIZATION_ARCHITECTURE.md**](papers/MODERNIZATION_ARCHITECTURE.md): Architectural decisions A1–A8, contracts C1–C6, and evidence evaluation E1–E8.
- [**MODERNIZATION_CHANGE_DOC.md**](papers/MODERNIZATION_CHANGE_DOC.md): Product change record, format compatibility, and verification scope.

---

## 5. Engineering Standards (`docs/standards/`)

Engineering governance and release requirements:

- [**PR_REVIEW_STANDARD.md**](standards/PR_REVIEW_STANDARD.md): PR Review Standard v1.1.0: file-to-category mapping, per-category coverage statements, P1/P2/P3 finding lists, and review archiving.
- [**RELEASE_READINESS.md**](standards/RELEASE_READINESS.md): Production release checklist, verification requirements, and dependency audit limits.

---

## 6. Legacy Reference (`docs/legacy/`)

Frozen legacy formats and historical records:

- [**LEGACY_COMPATIBILITY.md**](legacy/LEGACY_COMPATIBILITY.md): Frozen `.pdcp` v0.2.3 wire syntax, legacy submission tool (`patchdiff_submit_pdcp`), deprecated regeneration wrappers, and historical replay profiles.
- [**PatchDIFF-Concept-Paper-5.md**](legacy/PatchDIFF-Concept-Paper-5.md): Historical v0.2.3 conceptual whitepaper.
- [**PatchDIFF-Protocol-Spec-v0.2.3.md**](legacy/PatchDIFF-Protocol-Spec-v0.2.3.md): Historical v0.2.3 protocol specification.
- [**PatchDIFF-Implementation-Spec-v0.2.3.md**](legacy/PatchDIFF-Implementation-Spec-v0.2.3.md): Historical v0.2.3 implementation specification.
- [**PatchDIFF-Snapshot.md**](legacy/PatchDIFF-Snapshot.md): Historical v0.2.3 state snapshot.
