# Visual Architecture & Transaction Lifecycle

This document provides visual diagrams and state transition flowcharts for PatchDIFF's deterministic document transaction service.

---

## 1. End-to-End Transaction Sequence

The sequence diagram below illustrates the complete lifecycle of a document edit proposal, from authoritative read through optimistic locking, sequential simulation, and atomic commit or bounded rejection:

```mermaid
sequenceDiagram
    participant Host as MCP Host / Agent
    participant PD as PatchDIFF MCP Server
    participant PG as PostgreSQL 16 (Authoritative State)

    Note over Host,PG: 1. Authoritative Reading & Exact Discovery
    Host->>PD: patchdiff_read_target / patchdiff_read_lines / patchdiff_find_occurrences
    PD->>PG: Read committed canonical LF slice
    PG-->>PD: content slice + version + current_hash
    PD-->>Host: Bounded slice / exact spans + version=3

    Note over Host,PG: 2. Guarded Atomic Submission
    Host->>PD: patchdiff_submit_edits (expected_target_version=3, client_request_id="req-01", edits=[...])
    PD->>PG: SELECT ... FOR UPDATE (row lock acquired)

    alt All edits match & guards hold
        Note over PD,PG: In-memory simulation succeeds
        PD->>PG: Atomic commit (target v4 + append_only_pdcp_logs + append_only_manifest_ledger)
        PD-->>Host: status="accepted", version=4, evidence.changes[], warnings[], validity
    else Stale guard, missing match, or ambiguity
        Note over PD,PG: In-memory simulation rejects (target untouched)
        PD->>PG: Log rejected attempt in append_only_pdcp_logs (zero target mutation)
        PD-->>Host: status="rejected", failure_reason, diagnostic.failure_context, exact_candidates / near_misses
        Host->>PD: 3. Inspect diagnostics & resubmit with parent_pdcp_log_id
    end
```

---

## 2. Core Validation Stages & State Transition Flowchart

PatchDIFF evaluates proposals against five distinct `ValidationStage` boundaries, ensuring that invalid transactions fail closed before any state mutation can occur:

```mermaid
flowchart TD
    SUBMIT["Incoming Transaction Proposal<br/>(patchdiff-tx/1, tx/2, tx/3)"] --> STAGE1{"Stage 1: Precondition Guard<br/>(Row Lock: SELECT ... FOR UPDATE)"}
    
    STAGE1 -- "Target missing or<br/>Version / Hash mismatch" --> REJ1["Reject: target_version_mismatch<br/>(zero target mutation; audit logged if target exists)"]
    STAGE1 -- "Guards hold" --> STAGE2{"Stage 2: Protocol Validation<br/>(Schema, Format, Lineage)"}
    
    STAGE2 -- "Malformed syntax or<br/>invalid parent lineage" --> REJ2["Reject: block_malformed / lineage_invalid<br/>(zero target mutation; audit logged)"]
    STAGE2 -- "Protocol valid" --> STAGE3{"Stage 3: Transaction Applicability<br/>(Exact MATCH & Span Preconditions)"}
    
    STAGE3 -- "Missing text" --> REJ3A["Reject: match_absent<br/>(zero target mutation; near_misses scan)"]
    STAGE3 -- "Multiple matches" --> REJ3B["Reject: match_ambiguous<br/>(zero target mutation; up to 5 exact_candidates)"]
    STAGE3 -- "Consumed by prior edit" --> REJ3C["Reject: sequential_match_invalid<br/>(zero target mutation; consumed_by_change_id)"]
    
    STAGE3 -- "All operations match" --> STAGE4{"Stage 4: Commit Guard<br/>(Sequential In-Memory Simulation)"}
    
    STAGE4 -- "Simulated buffer<br/>diverges" --> REJ4["Reject: target_diverged<br/>(zero target mutation; audit logged)"]
    STAGE4 -- "Simulation verified" --> STAGE5["Stage 5: Accepted Commit<br/>- Advance canonical target state<br/>- Append accepted attempt log<br/>- Record manifest ledger with facts"]
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
│  - Exposes immutable profiles (editor, observed_v2, full)   │
│  - Enforces strict input schema validation & request limits │
│  - Formats bounded machine-readable responses & receipts    │
└──────────────────────────────┬──────────────────────────────┘
                               │ Internal service calls
┌──────────────────────────────▼──────────────────────────────┐
│             Tier 3: Pure Deterministic Core Runtime         │
│     (backend/app/core/, backend/app/pdcp/)                  │
│  - Parsers (tx/1, tx/2, tx/3, legacy .pdcp v0.2.3)          │
│  - Overlapping match enumerator & disambiguator             │
│  - In-memory sequential applier & change_facts calculator   │
│  - Zero LLM calls, zero network I/O, zero fuzzy guessing    │
└──────────────────────────────┬──────────────────────────────┘
                               │ SELECT ... FOR UPDATE
┌──────────────────────────────▼──────────────────────────────┐
│           Tier 4: PostgreSQL Canonical Substrate            │
│     (backend/app/storage/, migrations 0001–0005)            │
│  - cloud_target_files (authoritative canonical LF text)     │
│  - append_only_pdcp_logs (all accepted & rejected attempts) │
│  - append_only_manifest_ledger (derived span/hash facts)    │
│  - client_request_id idempotency & retry lineage            │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Deterministic Profile-Dispatched Replay Flowchart

State reconstruction in PatchDIFF is deterministic and profile-dispatched, replaying every transaction under its recorded `(protocol_version, runtime_version)`:

```mermaid
flowchart LR
    A["Initial Snapshot<br/>(Cycle 0 Text)"] --> B["Replay Engine<br/>(patchdiff_replay)"]
    C["Ordered Accepted Logs<br/>(append_only_pdcp_logs)"] --> B
    
    B --> D{"Profile Dispatch<br/>(0.1.0 .. 0.5.0)"}
    
    D --> E["Reconstruct<br/>In-Memory Buffer"]
    
    E --> F{"Materialized State Checks"}
    F --> G1["content_matches"]
    F --> G2["stored_hash_matches"]
    F --> G3["recomputed_hash_matches"]
    F --> G4["version_matches"]
    
    G1 & G2 & G3 & G4 --> H["materialized_state_matches: true"]
```
