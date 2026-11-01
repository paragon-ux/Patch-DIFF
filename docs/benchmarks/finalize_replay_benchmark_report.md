# PatchDIFF Finalize & Replay Scaling Benchmark Report

**Document Reference**: `PR23-IMPL-ARCH-001`, `PR23-R3-DOC-002`  
**Date**: 2026-10-31  
**Environment**: PostgreSQL 18.6, Python 3.14 (Linux x86_64)

---

## 1. Objective

Measure empirical lock acquisition wait time, exclusive row-lock hold duration, and deterministic replay scaling during `patchdiff_finalize_target` under PostgreSQL `SELECT ... FOR UPDATE` row locking.

This report documents the decoupled timing instrumentation established in Milestone M3 (`PR23-R3-DOC-002`), reports empirical distributions across edit tiers, and evaluates the architectural necessity of executing deterministic replay validation inside the exclusive lock boundary to prevent optimistic concurrency control (OCC) time-of-check to time-of-use (TOCTOU) race conditions.

---

## 2. Benchmark Methodology & Instrumentation Decomposition (PR23-R3-DOC-002)

- **Benchmark Harness**: [`backend/tests/verification/benchmark_finalize_replay.py`](../../backend/tests/verification/benchmark_finalize_replay.py)
- **Document Baseline**: 120 lines of Python source code.
- **Sequential Edit Tiers Evaluated**:
  - `0 edits`: Freshly initialized canonical target (baseline database overhead).
  - `25 edits`: Moderate sequential edit transaction history.
  - `100 edits`: Extended sequential edit transaction history in a single active cycle.
- **Sample Size**: 5 trials per tier ($N=5$).

### Timing Metric Decomposition

In earlier iterations (baseline commit `1073338`), timing instrumentation started prior to `session.begin()` and `select_target_for_update()`, conflating connection checkout, transaction initialization, and lock acquisition wait time with the critical section duration. Under Milestone M3 (`PR23-R3-DOC-002`), timing instrumentation in `backend/app/services/finalize_service.py` cleanly separates these distinct phases:

1. **`lock_wait_ms`**: Time elapsed waiting to acquire the exclusive `SELECT ... FOR UPDATE` row lock on `cloud_target_files`. In uncontended runs, this measures transaction establishment and index lookup. Under concurrent write attempts, this measures the exact queueing delay until the prior lock holder commits or rolls back.
2. **`lock_hold_ms`**: Time elapsed between successful acquisition of the row lock and transaction completion (`tx.commit()` or `_rollback()`). This measures the exact duration the row lock is held, protecting target mutation, SAVE snapshot creation, in-memory replay verification, and finalization record persistence.
3. **`replay_ms`**: Time spent executing in-memory deterministic replay verification (`replay_target`). Evaluates all sequential transactions in the active editing cycle to verify hash, version, and materialized state consistency.
4. **`total_ms`**: End-to-end Python roundtrip duration of `finalize_target`, including argument validation, lock acquisition wait, critical section hold, and receipt materialization.

---

## 3. Empirical Results

The table below presents empirical timings across 5 trials per edit tier in an uncontended local PostgreSQL 18.6 environment:

| Edit History Tier | Mean Lock Wait Time [min .. max] | Mean Lock Hold Time [min .. max] | Mean Replay Time [min .. max] | Mean Total Finalize Time [min .. max] |
| :--- | :--- | :--- | :--- | :--- |
| **0 edits** (fresh target) | **3.06 ms** [2.02 .. 5.99 ms] | **30.99 ms** [20.37 .. 47.21 ms] | **5.37 ms** [3.95 .. 9.60 ms] | **34.42 ms** [22.71 .. 53.67 ms] |
| **25 edits** | **2.50 ms** [2.22 .. 3.05 ms] | **42.95 ms** [28.09 .. 73.26 ms] | **16.54 ms** [10.17 .. 24.93 ms] | **45.81 ms** [31.16 .. 76.66 ms] |
| **100 edits** | **3.35 ms** [1.97 .. 6.69 ms] | **58.31 ms** [35.43 .. 73.19 ms] | **31.93 ms** [20.91 .. 44.11 ms] | **61.98 ms** [37.64 .. 80.23 ms] |

*Note on empirical variance*: In extended testing across varying background workloads, 100-edit mean lock hold times ranged from ~58 ms to ~89 ms (with individual trials reaching 158 ms under disk I/O pressure). Distributions are reported as empirical observations rather than fixed upper bounds.

---

## 4. Architectural Analysis & Findings

### 1. Deterministic Replay Scaling
In-memory deterministic replay scales linearly ($O(N)$) with the number of accepted editing transactions in the active cycle ($5.37\text{ ms} \to 16.54\text{ ms} \to 31.93\text{ ms}$ across 0, 25, and 100 edits). Replay validation remains efficient because all match, replace, and change-fact derivations execute in memory against canonical UTF-8 text buffers without intermediate database queries.

### 2. Lock Hold Duration Decomposition
Exclusive row lock hold duration is composed of:
- **Baseline Database Overhead (~25–35 ms)**: Snapshot creation in `target_snapshots`, editing cycle closure and rotation in `editing_cycles`, finalization metadata insertion in `target_finalizations`, and audit log insertion.
- **Replay Overhead (~5–35 ms)**: Linear scaling proportional to cycle transaction depth.
At 100 edits, replay accounts for more than half of the total critical section hold time (~32 ms out of ~58 ms mean hold).

### 3. Isolation of Lock Acquisition Wait Time (`lock_wait_ms`)
Decoupling `lock_wait_ms` from `lock_hold_ms` is essential for diagnosing operational contention:
- In uncontended execution, `lock_wait_ms` is negligible (2–6 ms), representing query roundtrip overhead.
- In contended scenarios (verified in adversarial integration tests `test_adversarial_m3_2.py`), a competing transaction holding the row lock causes `lock_wait_ms` to reflect the full waiting period (e.g., 250+ ms), while `lock_hold_ms` remains strictly confined to the execution time of the active transaction once the lock is acquired.

### 4. OCC Race Precaution & Necessity of In-Lock Replay
Replay verification must occur inside the `SELECT ... FOR UPDATE` lock boundary. If replay validation were performed prior to acquiring the row lock or outside the transaction, a concurrent edit transaction could commit between replay verification and SAVE snapshot rotation. This would produce a critical TOCTOU race where the checkpointed snapshot does not match the replayed and verified state. Maintaining replay within the lock guarantees atomic snapshot integrity.

---

## 5. Methodological Limitations & Empirical Qualifications

1. **Absence of Wall-Clock Deterministic Latency Bounds**:
   While transaction state validity and replay outcomes are strictly deterministic, transaction wall-clock latency is influenced by external environment factors including PostgreSQL fsync settings, WAL write performance, disk I/O scheduling, and CPU concurrency. No sub-50 ms or sub-millisecond latency guarantee is claimed or implied across arbitrary production environments.
2. **Document Size and Edit Complexity**:
   The empirical data above reflects a 120-line benchmark document. Targets with larger buffers (e.g., 10,000+ lines or files approaching the 1 MiB inline export limit) will experience increased SHA-256 computation and database serialization times.
3. **Operational Recommendation (Editing Cycle Checkpoints)**:
   Because deterministic replay scales linearly with transaction count in the active cycle, applications experiencing high edit volume should invoke `patchdiff_save` periodically. Checkpointing closes the active cycle and creates a new baseline snapshot, resetting active cycle depth to 0 and preventing unbounded growth in `lock_hold_ms`.
