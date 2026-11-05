# Visual Architecture & Transaction Lifecycle

Follow an edit from the host's initial read through validation, commit, publication, and replay. See the [profile catalog](spec/profiles/index.md) to choose which tools the host can call.

---

## 1. End-to-End Transaction Sequence

The workspace file supplies the starting bytes and receives an explicit publication. PostgreSQL holds the canonical LF working copy, version, and audit history. The host owns edit intent, context selection, and retries.

The sequence below illustrates the 5-tool `workspace` text-editing workflow:

`initialize_target` → `read_target` / `find_occurrences` → `submit_edits` → `save`

In the primary 7-tool `observed_workspace` profile, the agent also discovers structural candidates with `patchdiff_list_scopes`, observes snapshots with `patchdiff_observe_scopes`, and commits multi-scope bundles with `patchdiff_commit_bundle` between import and SAVE publication.

```mermaid
sequenceDiagram
    autonumber
    participant H as MCP host
    participant S as PatchDIFF service
    participant F as Workspace file
    participant D as PostgreSQL working copy

    H->>S: Initialize target with from_workspace=true
    S->>F: Read source bytes and record source digest
    S->>D: Store canonical LF text and workspace binding
    S-->>H: Return target ID, version, and canonical hash

    H->>S: Read/search text or observe scopes
    S->>D: Read canonical working copy
    S-->>H: Return bounded text, matches, or scope snapshots

    H->>S: Submit edits or commit bundle with version/hash guard
    S->>D: Lock target and validate guards
    alt Proposal accepted
        S->>D: Commit working version, attempt log, and manifest entries
        S-->>H: Return accepted version and hash
    else Proposal rejected
        S->>D: Record rejected attempt
        S-->>H: Return bounded diagnostics for host review
    end

    H->>S: SAVE accepted version with sync_workspace=true
    S->>D: Verify working version and state guards
    S->>F: Verify workspace binding and expected disk digest
    alt External disk drift detected
        S-->>H: Reject publication; do not checkpoint
    else Disk is in the expected state
        S->>F: Install rendered file bytes
        alt Publication and checkpoint confirmed
            S->>D: Record checkpoint and rotate editing cycle
            S-->>H: Return saved status, snapshot ID, and publication receipt
        else Disk install succeeded but checkpoint failed
            S-->>H: Return partial status and publication receipt; no confirmed checkpoint ID
        end
    end
```

With `sync_workspace: false`, SAVE checkpoints the database without publishing a file. When SAVE returns `partial`, inspect the file and checkpoint separately. See the [workspace contract](spec/profiles/workspace-profile.md).

---

## 2. Core Validation Stages & State Transition Flowchart

PatchDIFF evaluates each proposal through five validation stages. The target is not mutated unless the transaction passes the guards, protocol validation, sequential simulation, and commit checks.

```mermaid
flowchart TD
    A["Incoming transaction proposal<br/>tx/1, tx/2, tx/3, or observed bundle"] --> B{"Target exists?"}

    B -- No --> R0["Reject: target_not_found<br/>No row lock; no attempt row"]
    B -- Yes --> C["Acquire target row lock<br/>SELECT ... FOR UPDATE"]

    C --> D{"Stage 1: Precondition guard<br/>Version/hash and request-key checks"}
    D -- "Version or hash mismatch" --> R1["Reject: target_version_mismatch<br/>or target_hash_mismatch<br/>No target mutation; attempt logged"]
    D -- "Guards hold" --> E{"Stage 2: Protocol validation<br/>Schema, format, and lineage"}

    E -- "Malformed schema or syntax" --> R2A["Reject: invalid_argument<br/>or block_malformed<br/>No target mutation; attempt logged"]
    E -- "Invalid retry lineage" --> R2B["Reject: context_invalid<br/>lineage_invalid<br/>No target mutation; attempt logged"]
    E -- "Protocol valid" --> F{"Stage 3: Transaction applicability<br/>Sequential in-memory simulation<br/>Exact-match and span preconditions"}

    F -- "Match absent" --> R3A["Reject: match_absent<br/>Near-miss diagnostics may be returned"]
    F -- "Multiple matches" --> R3B["Reject: match_ambiguous<br/>Up to 5 exact candidates"]
    F -- "Consumed by prior edit" --> R3C["Reject: sequential_match_invalid<br/>Consumed-by change ID may be returned"]
    F -- "Span text mismatch" --> R3D["Reject: span_expected_text_mismatch<br/>Actual-text context may be returned"]
    F -- "All operations succeed" --> G{"Stage 4: Commit guard<br/>Recheck target state before commit"}

    G -- "Target state diverged" --> R4["Reject: target_diverged<br/>No target mutation; attempt logged"]
    G -- "Commit guard passes" --> H["Stage 5: Accepted commit<br/>Advance canonical target state<br/>Append accepted attempt log<br/>Append manifest ledger with derived facts"]
```

The stages serve different purposes: Stage 3 simulates the proposed edits against the evolving in-memory buffer; Stage 4 verifies the commit guard before persistence. Rejections leave the target document unchanged. Pre-admission failures such as a missing target do not create an attempt row.

---

## 3. Four-Tier Architecture

PatchDIFF separates the external agent, MCP transport, transaction orchestration, and persistent state. The deterministic core is shown as a component called by the transaction service, rather than as a separate operational tier, because it performs pure in-memory evaluation without database or network I/O.

```mermaid
flowchart TB
    subgraph T1["Tier 1: MCP host"]
        HOST["Claude Desktop / agentic host / IDE workflow<br/>Selects context and formulates proposals<br/>Owns retries, recovery lineage, and completion evaluation"]
    end

    subgraph T2["Tier 2: MCP transport layer"]
        MCP["external_adapter.py and tools.py<br/>Exposes active tool profiles and JSON schemas<br/>Validates arguments and request limits<br/>Formats bounded responses and receipts"]
    end

    subgraph T3["Tier 3: Transaction service layer"]
        SERVICE["backend/app/services/<br/>Owns SQLAlchemy session and per-target row lock<br/>Checks request-key idempotency and state guards<br/>Coordinates import, SAVE, checkpoints, and replay"]
        CORE["Pure deterministic core<br/>Exact-match enumeration and sequential application<br/>Change facts and validity derivation<br/>No database, network, or LLM I/O"]
        SERVICE <-->|"Target text, transaction, profile / result and derived facts"| CORE
    end

    subgraph T4["Tier 4: PostgreSQL substrate"]
        DB["backend/app/storage/<br/>cloud_target_files<br/>append_only_pdcp_logs<br/>append_only_manifest_ledger<br/>target_snapshots and editing_cycles<br/>client_request_id recovery and lineage"]
    end

    FILE["Workspace file<br/>Source bytes on import<br/>Rendered bytes on SAVE publication"]

    HOST <-->|"JSON-RPC (stdio transport)"| MCP
    MCP <-->|"Internal service calls"| SERVICE
    SERVICE <-->|"SELECT ... FOR UPDATE (atomic commit/audit)"| DB
    SERVICE <-->|"Import bytes / guarded SAVE publication"| FILE
```

**Execution boundary:** The transaction service coordinates persistence and workspace I/O. The pure deterministic core receives the target text, transaction payload, and execution profile; it returns a simulated result and derived facts without calling an LLM, database, or network service.

---

## 4. Deterministic Profile-Dispatched Replay Flowchart

Replay reconstructs the target by starting from the initial upload snapshot and applying accepted log entries in `log_sequence` order. Each entry is executed using its recorded `(protocol_version, runtime_version)` profile.

```mermaid
flowchart TD
    SNAP["Initial upload snapshot<br/>Canonical text, initial version, and hash"] --> REPLAY["Replay engine<br/>patchdiff_replay"]
    LOGS["Accepted append-only logs<br/>Ordered by log_sequence"] --> REPLAY

    REPLAY --> DISPATCH["For each accepted log entry<br/>Read protocol_version and runtime_version"]
    DISPATCH --> PROFILE{"Dispatch to recorded profile"}

    PROFILE --> TX1["patchdiff-tx/1<br/>Exact-match operations"]
    PROFILE --> TX2["patchdiff-tx/2<br/>Match and guarded-span operations"]
    PROFILE --> TX3["patchdiff-tx/3<br/>Whole-target replacement"]
    PROFILE --> BATCH["patchdiff-observed-batch/1<br/>Structural scope bundle"]

    TX1 --> APPLY["Apply transaction deterministically<br/>to the in-memory buffer"]
    TX2 --> APPLY
    TX3 --> APPLY
    BATCH --> APPLY

    APPLY --> VERIFY["Verify 4 Materialized State Checks<br/>content_matches<br/>stored_hash_matches<br/>recomputed_hash_matches<br/>version_matches"]
    VERIFY --> RES{"All 4 checks pass?"}
    RES -- Yes --> PASS["materialized_state_matches: true<br/>Reconstruction verified"]
    RES -- No --> FAIL["materialized_state_matches: false<br/>Content or line-ending divergence"]
```

The four materialized-state checks are independent: `content_matches`, `stored_hash_matches`, `recomputed_hash_matches`, and `version_matches`. The content comparison also detects raw line-ending divergence, such as out-of-band CRLF or bare-CR changes, even when canonical LF hashes agree.
