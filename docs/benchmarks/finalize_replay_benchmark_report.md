# PatchDIFF Finalize & Replay Scaling Benchmark Report

**Document Reference**: `PR23-IMPL-ARCH-001`
**Date**: 2026-10-31
**Environment**: PostgreSQL 18, Python 3.14 (Linux x86_64)

## 1. Objective

Measure empirical lock hold duration and deterministic replay scaling during `patchdiff_finalize_target` under PostgreSQL `SELECT ... FOR UPDATE` row locking.

## 2. Benchmark Methodology

- Script: [`benchmark_finalize_replay.py`](../../backend/tests/verification/benchmark_finalize_replay.py)
- Sequential edit histories evaluated: 0 edits (fresh target), 25 edits, 100 edits.
- Document baseline: 120 lines Python source code.
- Metrics recorded per trial (3 trials per edit tier):
  - `lock_hold_ms`: Time elapsed between acquiring the exclusive target row lock (`SELECT ... FOR UPDATE`) and committing the transaction.
  - `replay_ms`: Time spent executing in-memory deterministic replay (`replay_target`).
  - `total_ms`: End-to-end roundtrip execution time of `finalize_target`.

## 3. Empirical Results

| Edit History Tier | Mean Lock Hold Time | Mean Replay Time | Mean Total Finalize Time |
| :--- | :--- | :--- | :--- |
| **0 edits** (initial upload) | **33.60 ms** | 6.82 ms | 33.88 ms |
| **25 edits** | **31.57 ms** | 10.71 ms | 31.79 ms |
| **100 edits** | **40.74 ms** | 19.41 ms | 40.97 ms |

## 4. Architectural Analysis & Findings

1. **Replay Scaling**:
   Deterministic replay scales linearly with the number of accepted editing transactions in the active cycle ($6.82\text{ ms} \to 10.71\text{ ms} \to 19.41\text{ ms}$ across 0 to 100 edits). Replay overhead remains modest even on long chains because all change facts and in-memory text buffers are evaluated deterministically in memory.
2. **Lock Hold Duration**:
   Total lock hold duration under `SELECT ... FOR UPDATE` consistently remains between 30 ms and 42 ms across all tested tiers. The database operations (snapshot insertion, active cycle rotation, finalization record insertion, and audit flushing) dominate the 0-edit baseline (~26 ms DB overhead), while replay adds approximately 13 ms for 100 edits.
3. **OCC Race Precaution**:
   Replay occurs inside the exclusive lock boundary to prevent race conditions where a concurrent transaction commits between replay validation and SAVE snapshot creation. Given the observed sub-50 ms lock durations, moving replay outside the lock boundary is unnecessary and would introduce stale-read concurrency vulnerabilities.
