# PatchDIFF

[![CI](https://github.com/paragon-ux/Patch-DIFF/actions/workflows/ci.yml/badge.svg)](https://github.com/paragon-ux/Patch-DIFF/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-Zensical-purple.svg)](https://paragon-ux.github.io/Patch-DIFF/)
[![tests](https://img.shields.io/badge/tests-1581%20passed-success)](https://github.com/paragon-ux/Patch-DIFF/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/)
[![postgres](https://img.shields.io/badge/postgres-16.3--alpine-336791.svg?logo=postgresql&logoColor=white)](https://hub.docker.com/_/postgres)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05-8A2BE2.svg)](https://modelcontextprotocol.io/)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Transactional document-editing service for MCP-connected agents.**

PatchDIFF turns model-generated document edits into **explicitly preconditioned, atomic, auditable, and deterministically replayable PostgreSQL transactions** over the Model Context Protocol (MCP).

| ⚡ Completion Speed (Git) | ⏱️ Turnaround Predictability | 📉 Context Window Burn | 🎯 Byte Fidelity |
| :---: | :---: | :---: | :---: |
| **1.66× Faster** | **4.7× Tighter** | **-64.8%** | **100.0%** |
| *(3m 03s vs. 5m 04s in Git)* | *(±20s vs. ±96s variance)* | *(1.61M tokens saved/task)* | *(0 diffs across 60 files)* |

```mermaid
xychart-beta
    title "Mean Task Completion Duration in Seconds (N=24)"
    x-axis ["Non-Git Control", "Non-Git PatchDIFF", "Git Repo Control", "Git Repo PatchDIFF"]
    y-axis "Duration (Seconds)" 0 --> 350
    bar [206, 207, 304, 183]
```

> **Evaluation Disclaimer**: Measured in the Google Antigravity agent runtime across $N=24$ independent runs (Gemini 3.8 Flash High) comparing Modernized PatchDIFF (`observed_v2`) against the native Antigravity file-editing control baseline on a standardized 5-file, 21-edit canary task. Transcripts, seeds, and evaluation methodology are published in the [Modernized Benchmark Report](docs/benchmarks/modernized_benchmark_report.md) and [Git Benchmark Report](docs/benchmarks/git_benchmark_report.md).

### How Compounded Efficiency Drives Faster Speed

When agent throughput is constrained, every redundant turn, token, and verification step compounds into severe wall-clock delays. PatchDIFF completes tasks in **3 minutes flat (1.66× faster in Git environments)** by eliminating latency drivers across the entire execution loop:

- **-55.8% Interaction Steps** (24.2 vs. 54.8 turns): Eliminates round-trip model dispatch latency ($p < 0.00001$).
- **-64.8% Total Context Tokens** (876K vs. 2.49M): Cuts prompt prefill and attention processing by 1.61M tokens/task ($p < 0.00001$).
- **-57.8% Tool Invocations** (22.7 vs. 53.8 calls): Compresses sequential file operations into atomic bundle commits.
- **Zero Git Verification Tax** (0.0 vs. 10.0 shell commands): Replaces exploratory `git diff`/`status` loops with mathematical certainty under PostgreSQL row locks.
- **High Predictability**: Standard deviation collapses from $\pm 96.0\text{s}$ down to **$\pm 20.3\text{s}$** (and $\pm 14\text{s}$ in Git), eliminating long-tail recovery spirals.
- **100.0% Full-Byte Accuracy**: 60/60 target files matched oracle reference with 240/240 verification assertions passing.

| Operating Environment | Paradigm ($n=3$ per cell) | Mean Duration | Mean Steps | Mean Tool Calls | Git Commands | Mean Context Tokens | Full-Byte Match |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Non-Git Workspace** | Control Baseline | 3m 26s ± 1m 11s | 53.0 ± 3.6 | 52.0 ± 3.6 | N/A | 2,451,605 ± 507,644 | 100% (0 diffs) |
| **Non-Git Workspace** | Modernized PatchDIFF | **3m 27s ± 21s** | **26.7 ± 2.5** | **24.7 ± 4.2** | N/A | **1,001,039 ± 143,395** | **100% (0 diffs)** |
| **Git Repository** | Control Baseline | 5m 04s ± 1m 44s | 56.7 ± 6.1 | 55.7 ± 6.1 | 10.0 ± 0.0 | 2,529,918 ± 196,075 | 100% (0 diffs) |
| **Git Repository** | Modernized PatchDIFF | **3m 03s ± 14s** | **21.7 ± 1.2** | **20.7 ± 1.2** | **0.0 ± 0.0** | **750,230 ± 30,670** | **100% (0 diffs)** |

---

## System Architecture

```text
PatchDIFF server = deterministic transaction runtime + authoritative read/commit service
MCP              = transport/interface (stdio JSON-RPC / internal registry)
Host / Model     = planning, context selection, proposal generator, retry owner
PostgreSQL 16+   = canonical working substrate (SELECT ... FOR UPDATE)
```

> For interactive visual flowcharts of the host transaction lifecycle and 5-stage validation pipeline, see the **[Visual Architecture & Flow](https://paragon-ux.github.io/Patch-DIFF/architecture/)** guide.

---

## Why PatchDIFF?

| Editing Problem | Conventional Approach | What PatchDIFF Provides Directly |
| --- | --- | --- |
| **Small edit in large file** | Full regeneration emits complete replacement document | `patchdiff-tx/1` and `tx/2` emit only matched/replaced spans |
| **Repeated identical text** | `str_replace` requires expanding `old_str` with surrounding lines | Explicit `occurrence_index`, `anchor_before` / `anchor_after`, or code-point spans |
| **Line-diff grammars (`diff -u`)** | Requires line-prefixed diff syntax or numeric hunk headers | Structured JSON fields (`edits[]` / `operations[]`); no delimiter collisions |
| **Coordinate & state drift** | Line-based edits assume positions remain unchanged | Required `expected_target_version` / `expected_current_hash` under `SELECT ... FOR UPDATE` |
| **Multiple changes in one file** | Single-replacement requires $N$ calls with partial failure risks | Single submission simulated sequentially in memory and committed atomically |
| **Missing or ambiguous match** | Basic interfaces return uninformative error strings | Bounded diagnostics: `failure_context`, `exact_candidates`, and Levenshtein `near_misses` |
| **Lost submission response** | Host must re-read to guess if a timed-out write succeeded | Resubmitting with the same `client_request_id` returns recorded outcome (`deduplicated: true`) |
| **Audit & session history** | Host must maintain custom logging and verification | Append-only attempt log, manifest ledger with runtime-derived facts, `save` & `replay` |

---

## Transaction Formats

PatchDIFF supports three declarative, non-executable transaction input formats:

- **`patchdiff-tx/1` (`patchdiff_submit_edits`)**: Ordered exact `MATCH/REPLACE` edits with optional `occurrence_index`, `anchor_before`, or `anchor_after` disambiguation.
- **`patchdiff-tx/2` (`patchdiff_submit_operations`)**: Ordered exact match and `[start, end)` code-point span operations with `expected_text` and optional adjacency guards.
- **`patchdiff-tx/3` (`patchdiff_submit_replacement`)**: Sole explicit whole-document replacement (`<= 1,000,000` code points and `<= 1,048,576` UTF-8 bytes).

All formats require `expected_target_version` and/or `expected_current_hash` and lower into the same deterministic core applier. See [PDCP Format](docs/spec/PDCP_FORMAT.md) and [Host Integration Guide](docs/guides/HOST_INTEGRATION_GUIDE.md) for full request schemas and examples.

---

## Quickstart

### 1. Start PostgreSQL & Apply Migrations

```bash
docker compose up -d postgres
python -m alembic -c backend/app/migrations/alembic.ini upgrade head
```

### 2. Connect via MCP Stdio Adapter

PatchDIFF exposes a stdio JSON-RPC MCP adapter. For Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "patchdiff": {
      "command": "python",
      "args": ["-m", "app.mcp.external_adapter"],
      "env": {
        "PYTHONPATH": "/path/to/Patch-DIFF/backend",
        "PATCHDIFF_DATABASE_URL": "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff",
        "PATCHDIFF_MCP_PROFILE": "editor"
      }
    }
  }
}
```

See [Claude Desktop Setup](docs/guides/CLAUDE_DESKTOP_SETUP.md) for full host integration details.

---

## MCP Profiles & Tool Surface

External MCP defaults to the **7-tool `editor` profile**: `patchdiff_read_target`, `patchdiff_find_occurrences`, `patchdiff_observe_scope`, `patchdiff_submit_edits`, `patchdiff_submit_observed_operations`, `patchdiff_save`, and `patchdiff_replay`.

Configure the profile via `PATCHDIFF_MCP_PROFILE`:
- **`editor`** (default, 7 tools): Recommended for interactive agent workflows.
- **`observed_v2`** (5 tools): Streamlined editing with explicit AST snapshots and compact receipts (`<= 2 KB`). See [MCP Editor v2](docs/spec/MCP_EDITOR_V2.md).
- **`observed_editor`** (4 tools): Pure editing and reading tools for delegated subagents.
- **`unobserved`** (5 tools): Direct text reads and submissions without structural AST observation.
- **`full`** (22 tools): Complete tool suite including administrative document lifecycle and legacy wrappers.

---

## Documentation

Full documentation is available on the **[Zensical Documentation Site](https://paragon-ux.github.io/Patch-DIFF/)**:

- **Visual Architecture**: [Visual Architecture & Transaction Lifecycle](docs/architecture.md)
- **Specifications**: [Core Runtime](docs/spec/PATCHDIFF_CORE_SPEC.md) | [MCP Tools](docs/spec/MCP_TOOLS.md) | [Data Model](docs/spec/DATA_MODEL.md) | [PDCP Formats](docs/spec/PDCP_FORMAT.md) | [Editor v2](docs/spec/MCP_EDITOR_V2.md) | [Batch Editing](docs/spec/STRUCTURAL_BATCH_EDITING.md)
- **Guides**: [Host Integration Guide](docs/guides/HOST_INTEGRATION_GUIDE.md) | [Claude Desktop Setup](docs/guides/CLAUDE_DESKTOP_SETUP.md) | [Observed Workflow](docs/guides/OBSERVED_EDITOR_WORKFLOW.md)
- **Whitepapers**: [Concept Paper v6](docs/papers/PatchDIFF-Concept-Paper-6.md) | [Modernization Architecture](docs/papers/MODERNIZATION_ARCHITECTURE.md)
- **Benchmarks**: [Modernized Benchmark](docs/benchmarks/modernized_benchmark_report.md) | [Git Comparative Benchmark](docs/benchmarks/git_benchmark_report.md) | [Test Matrix](docs/benchmarks/TEST_MATRIX.md)
- **Standards & Legacy**: [PR Review Standard](docs/standards/PR_REVIEW_STANDARD.md) | [Release Readiness](docs/standards/RELEASE_READINESS.md) | [Legacy Compatibility](docs/legacy/LEGACY_COMPATIBILITY.md)

---

## License

[MIT](LICENSE)
