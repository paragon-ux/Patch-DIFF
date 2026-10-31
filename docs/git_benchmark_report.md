# 2×2 Factorial Comparative Benchmark Report: Control (Native Baseline) vs. Full PatchDIFF (`observed_v2`)

## Executive Summary

This report documents the rigorous, un-inflated comparative evaluation across **2 environments** (Standard Workspace vs. Initialized Git Repository) and **2 primary editing paradigms**:
1. **Control (Native Baseline)**: Standard developer workflow using native file access (`read_file`, `edit_file`) and version control commands (`git diff`, `git status`).
2. **Full PatchDIFF (`observed_v2`)**: Server-side deterministic document transaction service providing authoritative structural AST observation (`list_scopes`, `observe_scopes`), exact occurrence enumeration (`find_occurrences`), and atomic guarded commits (`commit_bundle`).

To test the null hypothesis with true statistical rigor, a **complete $n=3$ replication study ($N=12$ total independent runs)** was executed across all four cells of the $2\times2$ factorial matrix against the standardized **5-file, 21-edit canary workload**:
1. `matrix_kernel.py`: 2nd overlapping sync marker in `FRAME_SYNC_STREAM`; kernels `07`, `14`, `21` stride offset and rounded scale shift; `dispatch_kernel_triad` accumulator clips.
2. `schema_defs.py`: `SettlementEnvelope.idempotency_scope = "GLOBAL"`; `serialize_envelope_v3` nanosecond epoch unit/scaling, quorum 3, scope field.
3. `validator_engine.py`: `VALID_SCOPES = ("GLOBAL", "PARTITION", "TENANT")`; critical rules `04`, `11`, `19`, `27` nanosecond epoch default/validation, max drift 30s in ns, quorum 3.
4. `routing_manifest.json`: `manifest_version = "2026.10.2-v3"`; tenants `ten_006`, `ten_013`, `ten_018` wire v3, ns epoch, quorum 3, tenant scope.
5. `MIGRATION_RUNBOOK.md`: Allowed scopes table; Gate #14 clock skew threshold/action; Canary Cohort Parameters table; Section 4 literal patch template conflict block.

Every single completed run (**12 out of 12**) achieved **100% full-byte match** against the authoritative oracle reference (0 byte diffs across all 5 files) and passed **20/20 behavioral verification checks (240/240 total, 100.0%)**.

---

## 1. Complete 2×2 Factorial Benchmark Matrix ($N=12$)

| Environment | Paradigm / Run | Key Tools | Steps | Tool Calls | Git CLI Commands | Time Elapsed | Output Tokens | Total Input Tokens | Full-Byte Match | Behavioral Pass |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Non-Git** | **Control (Run 1)** | `read_file`, `edit_file` | 54 | 53 | N/A | **2m 04s** (124s) | 22,656 | 2,986,524 | **100% (0 diffs)** | **20/20 (100%)** |
| **Non-Git** | **Control (Run 2)** | `read_file`, `edit_file` | 49 | 48 | N/A | **4m 09s** (249s) | 17,901 | 1,976,542 | **100% (0 diffs)** | **20/20 (100%)** |
| **Non-Git** | **Control (Run 3)** | `read_file`, `edit_file` | 56 | 55 | N/A | **4m 06s** (246s) | 15,355 | 2,391,750 | **100% (0 diffs)** | **20/20 (100%)** |
| **Non-Git** | **Control ($n=3$ Mean ± SD)** | `read_file`, `edit_file` | **53.0 ± 3.6** | **52.0 ± 3.6** | **N/A** | **3m 26s ± 1m 11s** | **18,637 ± 3,706** | **2,451,605 ± 507,644** | **100% (0 diffs)** | **20/20 (100%)** |
| **Non-Git** | **Full PatchDIFF (Run 1)** | `observed_v2` batch bundle | **24** | **16** | N/A | **2m 57s** (177s) | 24,566 | **993,382** | **100% (0 diffs)** | **20/20 (100%)** |
| **Non-Git** | **Full PatchDIFF (Run 2)** | `observed_v2` batch bundle | **38** | **37** | N/A | **4m 28s** (268s) | 30,124 | **1,743,993** | **100% (0 diffs)** | **20/20 (100%)** |
| **Non-Git** | **Full PatchDIFF (Run 3)** | `observed_v2` batch bundle | **22** | **21** | N/A | **3m 31s** (211s) | 25,503 | **801,595** | **100% (0 diffs)** | **20/20 (100%)** |
| **Non-Git** | **Full PatchDIFF ($n=3$ Mean ± SD)** | `observed_v2` batch bundle | **28.0 ± 8.7** | **24.7 ± 11.0** | **N/A** | **3m 38s ± 46s** | **26,731 ± 2,976** | **1,179,657 ± 498,048** | **100% (0 diffs)** | **20/20 (100%)** |
| **Git Repo** | **Control (Run 1)** | `edit_file` + `git diff` / `status` | 62 | 61 | 10 (`diff`: 6, `status`: 4) | **7m 04s** (424s) | 17,804 | 2,311,642 | **100% (0 diffs)** | **20/20 (100%)** |
| **Git Repo** | **Control (Run 2)** | `edit_file` + `git diff` / `status` | 58 | 57 | 10 (`diff`: 6, `status`: 4) | **4m 06s** (246s) | 21,296 | 2,691,135 | **100% (0 diffs)** | **20/20 (100%)** |
| **Git Repo** | **Control (Run 3)** | `edit_file` + `git diff` / `status` | 50 | 49 | 10 (`diff`: 6, `status`: 4) | **4m 03s** (243s) | 21,886 | 2,586,977 | **100% (0 diffs)** | **20/20 (100%)** |
| **Git Repo** | **Control ($n=3$ Mean ± SD)** | `edit_file` + `git diff` / `status` | **56.7 ± 6.1** | **55.7 ± 6.1** | **10.0 ± 0.0** | **5m 04s ± 1m 44s** | **20,329 ± 2,206** | **2,529,918 ± 196,075** | **100% (0 diffs)** | **20/20 (100%)** |
| **Git Repo** | **Full PatchDIFF (Run 1)** | `observed_v2` in Git repo | **33** | **32** | **0** (`diff`: 0, `status`: 0) | **3m 37s** (217s) | 27,105 | **1,468,360** | **100% (0 diffs)** | **20/20 (100%)** |
| **Git Repo** | **Full PatchDIFF (Run 2)** | `observed_v2` in Git repo | **36** | **35** | **0** (`diff`: 0, `status`: 0) | **4m 13s** (253s) | 24,801 | **1,534,522** | **100% (0 diffs)** | **20/20 (100%)** |
| **Git Repo** | **Full PatchDIFF (Run 3)** | `observed_v2` in Git repo | **43** | **42** | **0** (`diff`: 0, `status`: 0) | **5m 02s** (302s) | 33,552 | **2,331,052** | **100% (0 diffs)** | **20/20 (100%)** |
| **Git Repo** | **Full PatchDIFF ($n=3$ Mean ± SD)** | `observed_v2` in Git repo | **37.3 ± 5.1** | **36.3 ± 5.1** | **0.0 ± 0.0** | **4m 17s ± 43s** | **28,486 ± 4,536** | **1,777,978 ± 480,117** | **100% (0 diffs)** | **20/20 (100%)** |

---

## 2. Statistical Hypothesis Testing & Effect Sizes

```mermaid
xychart-beta
    title "Mean Tool Calls (± SD): Control vs. Full PatchDIFF"
    x-axis ["Non-Git Control", "Non-Git PatchDIFF", "Git Repo Control", "Git Repo PatchDIFF"]
    y-axis "Tool Calls" 0 --> 70
    bar [52.0, 24.7, 55.7, 36.3]
```

### Statistical Analysis (Control vs. PatchDIFF, $n=6$ per condition)

To evaluate whether the observed differences between paradigms are statistically significant or attributable to chance, we conducted Welch's two-sample independent $t$-tests ($t$, degrees of freedom adjusted for unequal variances):

1. **Planner Steps**:
   - **Control Baseline**: $54.8 \pm 4.9$ steps
   - **Full PatchDIFF**: $32.7 \pm 8.2$ steps
   - **Difference**: **-40.3% reduction**
   - **Welch's $t$**: **$t = 5.685$**, $df = 8.19$
   - **Statistical Significance**: **$p = 0.0004$ ($p < 0.001$, highly statistically significant)**

2. **Tool Invocations**:
   - **Control Baseline**: $53.8 \pm 4.9$ calls
   - **Full PatchDIFF**: $30.5 \pm 10.0$ calls
   - **Difference**: **-43.3% reduction**
   - **Welch's $t$**: **$t = 5.140$**, $df = 7.29$
   - **Statistical Significance**: **$p = 0.0013$ ($p < 0.005$, highly statistically significant)**

3. **Total Input Tokens**:
   - **Control Baseline**: $2,490,762 \pm 346,842$ tokens
   - **Full PatchDIFF**: $1,478,817 \pm 546,646$ tokens
   - **Difference**: **-40.6% reduction** (~1.01M tokens saved per run)
   - **Welch's $t$**: **$t = 3.829$**, $df = 8.46$
   - **Statistical Significance**: **$p = 0.0044$ ($p < 0.01$, statistically significant)**

4. **Wall-Clock Turnaround Time**:
   - **Non-Git Environment**: $206.3\text{s}$ (Control) vs. $218.7\text{s}$ (PatchDIFF), $+6.0\%$ difference (comparable latency).
   - **Git Environment**: $304.3\text{s}$ (Control) vs. $257.3\text{s}$ (PatchDIFF), **-15.4% turnaround time reduction** (saving $47\text{s}$ per run).

---

## 3. Granular Tool Invocations Breakdown

| Tool / Action | Non-Git Control ($n=3$ Mean) | Non-Git PatchDIFF ($n=3$ Mean) | Git Repo Control ($n=3$ Mean) | Git Repo PatchDIFF ($n=3$ Mean) |
| :--- | :---: | :---: | :---: | :---: |
| `read_file` / `view_file` | 18.7 | 2.3 | 20.0 | 2.7 |
| `edit_file` / `write_file` | 20.3 | 0.0 | 20.0 | 0.0 |
| `run_command` (Shell / Git / Python) | 12.0 | 0.3 | 14.7 | 1.0 |
| *— of which `git diff`* | *—* | *0.0* | *6.0* | *0.0* |
| *— of which `git status`* | *—* | *0.0* | *4.0* | *0.0* |
| *— of which `git log`* | *—* | *0.0* | *0.0* | *0.0* |
| *— of which Python tests / verification* | *7.7* | *0.0* | *4.0* | *0.0* |
| `patchdiff_list_scopes` | 0.0 | 5.7 | 0.0 | 7.7 |
| `patchdiff_find_occurrences` | 0.0 | 3.7 | 0.0 | 3.0 |
| `patchdiff_observe_scopes` | 0.0 | 5.0 | 0.0 | 5.0 |
| `patchdiff_commit_bundle` | 0.0 | 4.7 | 0.0 | 5.0 |
| `patchdiff_read_target` | 0.0 | 0.7 | 0.0 | 10.3 |
| `list_resources` | 0.0 | 0.7 | 0.0 | 0.7 |
| `send_message` (Completion signal) | 1.0 | 1.0 | 1.0 | 1.0 |
| **Total Tool Invocations** | **52.0 ± 3.6** | **24.7 ± 11.0** | **55.7 ± 6.1** | **36.3 ± 5.1** |

---

## 4. Scientific Diagnosis: Falsification of the "Git Verification Tax" Hypothesis

An initial observation from $n=1$ suggested that operating inside a Git repository context provoked an extra 10 `patchdiff_read_target` calls because the model was substituting `read_target` for `git diff`.

**The $n=3$ replication conclusively falsified this causation hypothesis:**
1. **Post-Commit Auditing Occurs in Both Environments**: In Non-Git Run 2, despite operating in a pure non-git workspace with zero git instructions, the model executed **12 post-commit verification calls** (10 `find_occurrences` and 2 `read_target`).
2. **Post-Commit Auditing is Probabilistic, Not Universal**: In 2 out of 3 Non-Git runs (Run 1: 16 calls; Run 3: 21 calls), the model committed all 5 bundles and immediately sent `send_message` with **0 post-commit reads**.
3. **Root Cause Identified**: The true driver is prompt ambiguity interacting with model stochasticity:
   - The prompt included: *"- The host performs independent final verification. Read/search/observe when needed to resolve editing uncertainty; report unresolved issues."*
   - In some runs (Non-Git Runs 1 & 3), the model interpreted acceptance receipts (`"status": "ok"`, `version: 1`) as sufficient certainty and stopped immediately.
   - In other runs (Non-Git Run 2, Git Runs 1–3), the model interpreted *"resolve editing uncertainty"* as an instruction to audit every individual edit before declaring completion.

---

## 5. Identified Friction Points & Prompt Modernization Plan

Based on transcript evidence across all 12 runs, three actionable prompt friction points were identified and ablated:

### 1. Obsolete Schema & Spill Permissions Clause
- **Baseline Prompt**: `"Registered help/schema resources and this session's spills are allowed; general repository manuals are not authorized by that permission."`
- **Friction**: In PR 21, all 5 tools are 100% eager in the MCP catalog and receipts never spill. Seeing this line caused the model to spend 5–6 tool calls upfront inspecting `/home/paragon-ux/.gemini/antigravity/mcp/patchdiff/*.json` and `instructions.md`.
- **Intervention**: Deleted clause completely.

### 2. Ambiguous Verification Instruction
- **Baseline Prompt**: `"The host performs independent final verification. Read/search/observe when needed to resolve editing uncertainty; report unresolved issues."`
- **Friction**: Interpreted as an instruction to audit every individual edit before declaring completion, provoking 10–12 post-commit read loops.
- **Intervention**: Replaced with explicit prohibition:
  > *"The host performs independent final verification after you report completion. Do NOT perform post-commit verification audits or read-back loops once all targets are committed. Send your completion message immediately after committing all files."*

### 3. Prompt Confound & Divergence Across Environments
- **Baseline Prompt**: Git arms included extra cautionary paragraphs about `git diff` not reflecting PostgreSQL transactions, adding cognitive load and inadvertently priming Git tools.
- **Intervention**: Harmonized prompts across the board so that the Git and Non-Git prompts are 100% identical in instructions and constraints.

---

## 6. Modernized Benchmark Transition

Following the identification of the three prompt friction points above, a separate, standalone evaluation was conducted with the modernized prompt contract across both Non-Git and Git environments.

The complete $n=3$ replication study for the modernized prompt ($N=12$ standalone matrix), along with its dedicated statistical hypothesis testing and cross-environment equivalence analysis, is documented in:
👉 [`modernized_benchmark_report.md`](file:///home/paragon-ux/.gemini/antigravity/brain/e26568ec-c360-425b-a513-8229e4a0bf8a/modernized_benchmark_report.md)

---

## 7. Verification & Replay Certification

1. **Full-Byte Match**: 100.0% (12/12 runs passed with 0 byte differences across all 5 files).
2. **Behavioral Suite**: 100.0% (20/20 checks passed across all 12 runs = 240/240 total assertions).
3. **First-Shot Acceptance**: 0 rejections, 0 retries, and 0 validation errors across all 30 bundle submissions.
4. **Deterministic Replay**: All PatchDIFF runs verified via `patchdiff_save` and deterministic replay with component-level materialized state checks.
