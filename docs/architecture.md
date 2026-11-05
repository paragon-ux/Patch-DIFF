# Visual Architecture & Transaction Lifecycle

Follow an edit from the host's initial read through validation, commit
and replay. See the [profile catalog](spec/profiles/index.md) to choose
which tools the host can call.

---

## 1. End-to-End Transaction Sequence

The workspace file supplies the starting bytes and receives an explicit
publication. PostgreSQL holds the canonical LF working copy, version and
audit history. The host owns edit intent, context selection and retries.

The sequence below illustrates the 5-tool `workspace` text editing workflow (`initialize_target` $\rightarrow$ `read_target` / `find_occurrences` $\rightarrow$ `submit_edits` $\rightarrow$ `save`). In the primary 7-tool `observed_workspace` profile, the agent discovers structural candidates (`patchdiff_list_scopes`), observes snapshots (`patchdiff_observe_scopes`), and commits multi-scope bundles (`patchdiff_commit_bundle`) between import and SAVE publication.

```mermaid
sequenceDiagram
    participant H as MCP host
    participant S as PatchDIFF workspace profile
    participant F as Workspace file
    participant D as PostgreSQL working copy

    H->>S: Initialize filename with from_workspace=true
    S->>F: Read source bytes and record their digest
    S->>D: Store canonical LF text and workspace binding
    S-->>H: Target ID, version and canonical hash
    H->>S: Read or find occurrences (or observe scopes)
    S->>D: Read the canonical working copy
    S-->>H: Bounded text, matches, or scope snapshots
    H->>S: Submit edits / commit bundle with version or hash guard
    S->>D: Lock target and validate guards
    alt Proposal accepted
        S->>D: Commit new working version, attempt and ledger
        S-->>H: Accepted version and hash
    else Proposal rejected
        S->>D: Record rejected attempt
        S-->>H: Return diagnostics for host review
    end

    H->>S: SAVE accepted version with sync_workspace=true
    S->>D: Verify the working version
    S->>F: Check binding and expected disk digest
    alt External disk drift
        S-->>H: Reject publication and checkpoint
    else Publication succeeds
        S->>F: Install the rendered file bytes
        alt Checkpoint and publication durability confirmed
            S->>D: Checkpoint and rotate editing cycle
            S-->>H: Saved, with snapshot ID and publication receipt
        else Post-install failure
            S-->>H: Partial, with publication receipt and no confirmed checkpoint ID
        end
    end
```

With `sync_workspace: false`, SAVE checkpoints the database without
publishing a file. When SAVE returns `partial`, inspect the file and
checkpoint separately. See the [workspace contract](spec/profiles/workspace-profile.md).

## 2. Core Validation Stages & State Transition Flowchart

PatchDIFF evaluates proposals against five distinct `ValidationStage` boundaries, ensuring that invalid transactions fail closed before any state mutation can occur:

```mermaid
flowchart TD
    SUBMIT["Incoming Transaction Proposal<br/>(patchdiff-tx/1, tx/2, tx/3, or observed bundle)"] --> ADMIT{"Pre-Admission Check"}
    
    ADMIT -- "Target missing" --> REJ0["Reject: target_not_found<br/>(fails closed; no row lock, no attempt row)"]
    ADMIT -- "Target exists" --> STAGE1{"Stage 1: Precondition Guard<br/>(Row Lock: SELECT ... FOR UPDATE)"}
    
    STAGE1 -- "Version / Hash mismatch" --> REJ1["Reject: target_version_mismatch / target_hash_mismatch<br/>(zero target mutation; attempt logged append-only)"]
    STAGE1 -- "Guards hold" --> STAGE2{"Stage 2: Protocol Validation<br/>(Schema, Format, Lineage)"}
    
    STAGE2 -- "Malformed schema syntax" --> REJ2A["Reject: invalid_argument / block_malformed<br/>(zero target mutation; attempt logged)"]
    STAGE2 -- "Invalid parent retry lineage" --> REJ2B["Reject: context_invalid / lineage_invalid<br/>(zero target mutation; attempt logged)"]
    STAGE2 -- "Protocol valid" --> STAGE3{"Stage 3: Transaction Applicability<br/>(Exact MATCH & Span Preconditions)"}
    
    STAGE3 -- "Missing text" --> REJ3A["Reject: match_absent<br/>(zero target mutation; near_misses scan)"]
    STAGE3 -- "Multiple matches" --> REJ3B["Reject: match_ambiguous<br/>(zero target mutation; up to 5 exact_candidates)"]
    STAGE3 -- "Consumed by prior edit" --> REJ3C["Reject: sequential_match_invalid<br/>(zero target mutation; consumed_by_change_id)"]
    STAGE3 -- "Span text mismatch" --> REJ3D["Reject: span_expected_text_mismatch<br/>(zero target mutation; actual_text context)"]
    
    STAGE3 -- "All operations match" --> STAGE4{"Stage 4: Commit Guard<br/>(Sequential In-Memory Simulation)"}
    
    STAGE4 -- "Simulated buffer diverges" --> REJ4["Reject: target_diverged<br/>(zero target mutation; attempt logged)"]
    STAGE4 -- "Simulation verified" --> STAGE5["Stage 5: Accepted Commit<br/>- Advance canonical target state<br/>- Append accepted attempt log<br/>- Record manifest ledger with derived facts"]
```

---

## 3. Four-Tier Architecture

PatchDIFF enforces a strict separation of concerns across four distinct operational tiers:

```text
┌─────────────────────────────────────────────────────────────┐
│                      Tier 1: MCP Host                       │
│     (Claude Desktop / Agentic Host / IDE Workflow)          │
│  - Reads context slices & searches exact occurrences        │
│  - Formulates declarative transaction proposals             │
│  - Owns retries, recovery lineage, and completion evaluation│
└──────────────────────────────┬──────────────────────────────┘
                               │ JSON-RPC (stdio transport)
┌──────────────────────────────▼──────────────────────────────┐
│                  Tier 2: MCP Transport Layer                │
│     (backend/app/mcp/external_adapter.py, tools.py)         │
│  - Exposes immutable workspace, editing and lifecycle profiles   │
│  - Enforces strict input schema validation & request limits │
│  - Formats bounded machine-readable responses & receipts    │
└──────────────────────────────┬──────────────────────────────┘
                               │ Internal service calls
┌──────────────────────────────▼──────────────────────────────┐
│             Tier 3: Transaction Service Layer               │
│     (backend/app/services/)                                 │
│  - Owns SQLAlchemy session, per-target row lock & retry key │
│  - Invokes Pure Core Runtime for in-memory simulation       │
│  - Atomically commits accepted mutations or logs rejections │
│  - Manages file import, SAVE publication, checkpoints and replay     │
└──────────────┬───────────────────────────────▲──────────────┘
               │                               │ Pure in-memory
               │ SELECT ... FOR UPDATE         │ evaluation (no I/O)
               │ atomic commit/audit           │
┌──────────────▼──────────────┐ ┌──────────────┴──────────────┐
│ Tier 4: PostgreSQL Substrate│ │ Pure Deterministic Core     │
│ (backend/app/storage/)      │ │ (backend/app/core/, pdcp/)  │
│ - cloud_target_files        │ │ - Exact match enumerator    │
│ - append_only_pdcp_logs     │ │ - Sequential tx applier     │
│ - append_only_manifest_ledger│ │ - Change facts & validity   │
│ - client_request_id recovery│ │ - Zero DB/network/LLM I/O   │
└─────────────────────────────┘ └─────────────────────────────┘
```

---

## 4. Deterministic Profile-Dispatched Replay Flowchart

State reconstruction in PatchDIFF is deterministic and profile-dispatched, replaying every transaction under its recorded `(protocol_version, runtime_version)`:

```mermaid
flowchart LR
    A["Initial Snapshot<br/>(Cycle 0 Text)"] --> B["Replay Engine<br/>(patchdiff_replay)"]
    C["Ordered Accepted Logs<br/>(append_only_pdcp_logs)"] --> B
    
    B --> D{"Profile Dispatch<br/>(tx/1..3: 0.1.0..0.5.0;<br/>observed-batch/1)"}
    
    D --> E["Reconstruct<br/>In-Memory Buffer"]
    
    E --> F{"4 Materialized State Checks<br/>(content, stored hash,<br/>recomputed hash, version)"}
    F -- "All checks pass" --> H["materialized_state_matches: true<br/>(Reconstruction Verified)"]
    F -- "Any check fails" --> DIV["materialized_state_matches: false<br/>(Storage Tamper / CRLF Detected)"]
```
