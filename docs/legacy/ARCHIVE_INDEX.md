# Historical Archive & Pre-Pruning Evidence Index

**Status**: Non-normative historical reference  
**Pre-Pruning Commit Baseline**: [`2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a`](https://github.com/paragon-ux/Patch-DIFF/tree/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a)  
**Pruning PR**: PR #22 (Phase 1 Archival Pruning)

---

## 1. Purpose & Audit Reproducibility

During Phase 1 of PR #22, 61 historical scratch files, intermediate debug scripts, and legacy phase prompts totaling −7,716 lines were removed from the active Git working tree, alongside 3 consolidated root plans in Phase 2 (64 file removals total across PR #22), to eliminate clutter and prevent AI coding agents from following superseded procedures.

In accordance with [PR Review Standard v1.1.0](../standards/PR_REVIEW_STANDARD.md), all historical artifacts remain immutably preserved in Git history. This document provides direct, commit-pinned links to the exact pre-pruning trees for historical inspection, forensic audit, and empirical reproducibility.

> [!NOTE]
> Artifacts linked in this archive index are preserved as frozen historical evidence. They are **not** part of the active, normative PatchDIFF runtime or tool surface, and their scripts are not maintained for current execution. For active contracts and specifications, consult `docs/spec/` and `docs/guides/`.

---

## 2. Directory Family Archive Links

All links below resolve directly to the pre-pruning tree at commit [`2afcda6`](https://github.com/paragon-ux/Patch-DIFF/tree/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a):

| Historical Directory Family | Removed Count | Description & Historical Scope | Commit-Pinned Tree Link |
| :--- | :---: | :--- | :--- |
| **`docs/Archive/`** | **16** | 16 historical concept drafts, early design memos, and initial protocol iterations (v0.1.x–v0.2.x). | [`docs/Archive/` @ `2afcda6`](https://github.com/paragon-ux/Patch-DIFF/tree/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a/docs/Archive) |
| **`docs/optimization/`** | **1** | 1 performance optimization note (`O01-optimizations.md`) from early MVP iterations. | [`docs/optimization/` @ `2afcda6`](https://github.com/paragon-ux/Patch-DIFF/tree/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a/docs/optimization) |
| **`docs/gemini-remediation/`** | **8** | 8 canary run verification artifacts, transcripts, and the historical verification script `G02-live-verify.py`. | [`docs/gemini-remediation/` @ `2afcda6`](https://github.com/paragon-ux/Patch-DIFF/tree/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a/docs/gemini-remediation) |
| **`docs/remediation/`** | **30** | 30 early protocol remediation notes, verification logs, and prompt debugging transcripts. | [`docs/remediation/` @ `2afcda6`](https://github.com/paragon-ux/Patch-DIFF/tree/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a/docs/remediation) |
| **`docs/phase_prompts/`** | **6** | 6 staged prompt iterations used during early exploratory canary runs. | [`docs/phase_prompts/` @ `2afcda6`](https://github.com/paragon-ux/Patch-DIFF/tree/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a/docs/phase_prompts) |
| **Subtotal (Phase 1)** | **61** | Directory families removed in Phase 1 pruning | |

---

## 3. Consolidated Root Plans

Three early build plans (3 files) from the root of `docs/` were consolidated into the active modernization specifications in Phase 2, bringing total removals to 64 files:

1. **`docs/CODEX_BUILD_PLAN.md`**: Early MVP work plan; consolidated into [`docs/papers/MODERNIZATION_ARCHITECTURE.md`](../papers/MODERNIZATION_ARCHITECTURE.md). Preserved at [`docs/CODEX_BUILD_PLAN.md` @ `2afcda6`](https://github.com/paragon-ux/Patch-DIFF/blob/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a/docs/CODEX_BUILD_PLAN.md).
2. **`docs/MCP_FIRST_MVP.md`**: Initial MCP architecture note; consolidated into [`docs/spec/MCP_TOOLS.md`](../spec/MCP_TOOLS.md). Preserved at [`docs/MCP_FIRST_MVP.md` @ `2afcda6`](https://github.com/paragon-ux/Patch-DIFF/blob/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a/docs/MCP_FIRST_MVP.md).
3. **`docs/WAYMARK_STRUCTURAL_OBSERVATION_RETEST_PLAN.md`**: Structural observation retest plan; consolidated into [`docs/spec/STRUCTURAL_BATCH_EDITING.md`](../spec/STRUCTURAL_BATCH_EDITING.md). Preserved at [`docs/WAYMARK_STRUCTURAL_OBSERVATION_RETEST_PLAN.md` @ `2afcda6`](https://github.com/paragon-ux/Patch-DIFF/blob/2afcda61cf9bd4d2d2ec7b84c6d9235b437c852a/docs/WAYMARK_STRUCTURAL_OBSERVATION_RETEST_PLAN.md).
