Used MCP tool: patchdiff/patchdiff_observe_scope
Used MCP tool: patchdiff/patchdiff_submit_observed_operations
Ran count targets in database · Exited with code 1
Ran check current alembic migration in patchdiff db · Exited with code 1
Ran alembic upgrade head
Ran check how mcp_session migrates database
Ran run alembic upgrade head on patchdiff db
Ran check alembic current
Ran list tables in patchdiff db
Ran query cloud_target_files · Exited with code 1
Ran clean patchdiff db tables
Defined arm-a-native subagent
Defined arm-b-patchdiff subagent
Defined arm-c-waymark subagent
Ran copy fixtures to arm_A
Ran initialize Arm B targets · Exited with code 1
Ran initialize Arm B targets cleanly
Ran initialize Arm C targets
Used tool: invoke_subagent

I have launched the **Arm A (Native)** subagent (`conversationId: 3468a830-8787-4ccc-9419-8f7a4b7eb770`) with model setting `inherit`. The subagent is running the 21-edit multi-file task in its isolated workspace using native file reading and editing tools. 

Awaiting the subagent's completion notification via reactive wakeup.

Used tool: invoke_subagent

I have launched the **Arm B (Patch-DIFF)** subagent (`conversationId: bb23a8af-6e47-47cf-862c-cb49dbbd34a6`) with model setting `inherit`. The subagent is executing the 21 edits across the 5 fresh Patch-DIFF targets using `patchdiff_find_occurrences`, `patchdiff_read_target`, and `patchdiff_submit_edits`, followed by `patchdiff_save` and `patchdiff_replay`.

Awaiting the subagent's completion notification via reactive wakeup.

Ran export Arm B targets
Used tool: invoke_subagent

I have launched the **Arm C (Patch-DIFF + Waymark)** subagent (`conversationId: a6965390-8119-4bba-afe1-e89c2697f710`) with model setting `inherit`. The subagent is executing the 21 edits across the 5 fresh Patch-DIFF targets using Waymark structural discovery (`patchdiff_observe_scope`) and guarded scoped submission (`patchdiff_submit_observed_operations`), followed by `patchdiff_save` and `patchdiff_replay`.

Awaiting the subagent's completion notification via reactive wakeup.

Ran export Arm C targets
Ran check Arm A file hashes
Ran read reference_hashes.json
Ran run evaluator on Arm A
Ran run evaluator on Arm B
Ran run evaluator on Arm C
Analyze transcripts
Ran list agy-context-saver tools
Ran read query_transcript.json
Used MCP tool: agy-context-saver/query_transcript
Ran read read_transcript.json
Used MCP tool: agy-context-saver/read_transcript
Used MCP tool: agy-context-saver/read_transcript
Used MCP tool: agy-context-saver/read_transcript

# Patch-DIFF — Direct Three-Arm Subagent Functionality Retest Report

**Experimental Designation**: Exploratory Subagent Functionality Testing  
**Primary Study Task**: [`TASK.md`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/structural_retest/primary/prompts/TASK.md) (21 edits across 5 target files)  
**Starting Commit**: [`aa57ecfc9310c271f382431bce971bda38c11b3f`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF)  
**Orchestrator Model**: Gemini 3.8 Flash High  
**Subagent Model Parameter**: `inherit` (applied identically to all three arms)  
**Substrate / Backend**: PostgreSQL 16.3 on Docker, Stdio JSON-RPC MCP adapter, Waymark Engine `4.1.0`  

---

## 1. Executive Summary

This evaluation conducted a direct, practical subagent editing functionality retest across three independent arms on the identical 21-edit, 5-file task. All three subagents executed independently in fresh, isolated contexts without hints from other runs, without exposure to evaluator internals, and without manual human or orchestrator repair.

### Headline Results

| Arm | Workflow | Task Correctness (Behavioral) | Full-Byte Correctness (Oracle) | Editing Failures | Recovery Attempts | Final Status |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **Arm A** | Native File Tools (`rtk read`, `edit_file`) | **20 / 20 (100%)** | **PASSED (0 diffs)** | 0 | 0 | **COMPLETED** |
| **Arm B** | Patch-DIFF Unobserved (`patchdiff_submit_edits`) | **20 / 20 (100%)** | **PASSED (0 diffs)** | 0 | 0 | **COMPLETED** |
| **Arm C** | Patch-DIFF + Waymark (`observe_scope` + `submit_observed_operations`) | **20 / 20 (100%)** | **PASSED (0 diffs)** | 0 | 0 | **COMPLETED** |

> [!NOTE]
> These results represent **exploratory subagent functionality testing** under real agent pairing conditions, not publication-grade statistically controlled benchmark evidence. They establish that Native editing, Patch-DIFF alone, and Patch-DIFF with Waymark structural observation all operate reliably and deterministically to achieve complete behavioral and exact-byte correctness on the 21-edit task.

---

## 2. Model Configuration and Host Parity

| Parameter | Arm A (Native) | Arm B (Patch-DIFF) | Arm C (Patch-DIFF + Waymark) | Parity Status |
|---|---|---|---|---|
| **Subagent Type** | `arm-a-native` | `arm-b-patchdiff` | `arm-c-waymark` | Distinct tool permissions |
| **Requested Model** | `inherit` | `inherit` | `inherit` | **Identical** |
| **Effective Model Tier** | Gemini 3.8 Flash High | Gemini 3.8 Flash High | Gemini 3.8 Flash High | **Identical** |
| **Tool Permissions** | `run_command`, `edit_file`, native tools (`EnableMCPTools: false`) | Patch-DIFF MCP tools (`EnableWriteTools: false`) | Patch-DIFF + Waymark MCP tools (`EnableWriteTools: false`) | Bounded per arm specification |
| **Initial Content** | Authenticated original fixtures | Authenticated original fixtures | Authenticated original fixtures | **Byte-identical** |
| **Target Isolation** | [`evaluation/subagent_runs/arm_A/`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/subagent_runs/arm_A) | Fresh Patch-DIFF target IDs (`b_*`) | Fresh Patch-DIFF target IDs (`c_*`) | Completely isolated |
| **Automatic Retries** | 0 | 0 | 0 | **Zero transport retries** |

---

## 3. Arm-by-Arm Execution Analysis

### 3.1 Arm A — Native Editing

- **Conversation ID**: [`3468a830-8787-4ccc-9419-8f7a4b7eb770`](conversation://3468a830-8787-4ccc-9419-8f7a4b7eb770)
- **Raw Transcript**: [`transcript.jsonl`](file:///C:/Users/USER/.gemini/antigravity/brain/3468a830-8787-4ccc-9419-8f7a4b7eb770/.system_generated/logs/transcript.jsonl) (106 total log steps)
- **Execution Interval**: `2026-10-27T09:21:18Z` to `2026-10-27T09:30:40Z` (~9 min 22 sec)
- **Tool Calls**:
  - `run_command` (`rtk read <file>`): 28 calls (used for slicing inspection and post-edit verification)
  - `edit_file`: 20 calls (exact string matching with local disambiguation context)
- **Editing Failures & Recovery**: 0 rejections, 0 retries.
- **Workflow Pattern**: The native subagent systematically inspected each file's surrounding lines via `rtk read`, constructed exact-context replacement blocks for `edit_file`, and re-read the edited regions to confirm no unintended whitespace or neighboring-rule mutations were introduced.

---

### 3.2 Arm B — Patch-DIFF (Unobserved Mode)

- **Conversation ID**: [`bb23a8af-6e47-47cf-862c-cb49dbbd34a6`](conversation://bb23a8af-6e47-47cf-862c-cb49dbbd34a6)
- **Raw Transcript**: [`transcript.jsonl`](file:///C:/Users/USER/.gemini/antigravity/brain/bb23a8af-6e47-47cf-862c-cb49dbbd34a6/.system_generated/logs/transcript.jsonl) (112 total log steps)
- **Execution Interval**: `2026-10-27T09:31:10Z` to `2026-10-27T09:37:54Z` (~6 min 44 sec)
- **Tool Calls**:
  - `patchdiff_read_target` & `patchdiff_find_occurrences`: 18 calls
  - `patchdiff_submit_edits`: 5 transactions (one atomic guarded transaction per target file)
  - `patchdiff_save`: 5 calls
  - `patchdiff_replay`: 5 calls
- **Editing Failures & Recovery**: 0 rejections, 0 retries. Every proposal passed expected target version and expected current SHA-256 hash guards on first attempt.
- **Target Lineage & Transactions**:
  1. `matrix_kernel.py` (`08532fe3-e2c2-4b91-97ad-196103159348`): Log ID `3ce323a8-aed7-475d-ba7c-c613c8770213` (v1); Snapshot `63074f37-2a2a-4cc9-9da6-eaea9500fed9`; Replay `success` (`materialized_state_matches: true`).
  2. `schema_defs.py` (`def7a04f-05ff-4779-a8d5-6217b39943e5`): Log ID `74dbfb88-228e-4282-a167-8b12459d6649` (v1); Snapshot `79ecaa8f-9664-492c-8bf6-eae3507c47d9`; Replay `success` (`materialized_state_matches: true`).
  3. `validator_engine.py` (`3e7e1ffc-d007-403d-83d8-83d4cda54816`): Log ID `11a2ecbe-4258-43cc-bd19-38ded347193e` (v1); Snapshot `1b539ff5-fbaf-4a92-b2a2-21b611bc6b77`; Replay `success` (`materialized_state_matches: true`).
  4. `routing_manifest.json` (`d6020c11-468a-4eeb-938f-62bb030a4e21`): Log ID `8c281182-bc96-41f7-9d0a-0808ff227629` (v1); Snapshot `0636d7d4-56f6-4016-a82b-fe3f4146a5e5`; Replay `success` (`materialized_state_matches: true`).
  5. `MIGRATION_RUNBOOK.md` (`9c0a42ea-7f85-4c8c-ac55-9c02e0638f13`): Log ID `29eddf01-e3b3-4517-9028-6bf782136968` (v1); Snapshot `a8dbc077-6b0c-4ff1-82d9-3563b2ecfc5d`; Replay `success` (`materialized_state_matches: true`).

---

### 3.3 Arm C — Patch-DIFF + Waymark Structural Observation

- **Conversation ID**: [`a6965390-8119-4bba-afe1-e89c2697f710`](conversation://a6965390-8119-4bba-afe1-e89c2697f710)
- **Raw Transcript**: [`transcript.jsonl`](file:///C:/Users/USER/.gemini/antigravity/brain/a6965390-8119-4bba-afe1-e89c2697f710/.system_generated/logs/transcript.jsonl) (140 total log steps)
- **Execution Interval**: `2026-10-27T09:38:52Z` to `2026-10-27T09:46:38Z` (~7 min 46 sec)
- **Tool Calls**:
  - `patchdiff_observe_scope`: 20 calls (used to discover and lock structural symbol boundaries via Waymark)
  - `patchdiff_submit_observed_operations`: 20 transactions (every edit strictly bound to an active `observation_id`)
  - `patchdiff_find_occurrences`: 5 calls
  - `patchdiff_save`: 5 calls
  - `patchdiff_replay`: 5 calls
- **Editing Failures & Recovery**: 0 rejections, 0 retries. All zero-width insertions and scope operations respected strict interior boundary guards.
- **Target Lineage & Transactions**:
  1. `matrix_kernel.py` (`e2731d31-589f-4730-b631-1c65d03616b3`): Advanced to `v5` across 5 observed scopes (`FRAME_SYNC_STREAM`, `execute_tile_kernel_07`, `14`, `21`, and `dispatch_kernel_triad`); Snapshot `68123056-84f1-4889-8af7-12e0277f219d`; Replay `success` (`materialized_state_matches: true`).
  2. `schema_defs.py` (`b3795cb3-a75d-4460-80bb-6cbcd5d3be7e`): Advanced to `v2` across 2 observed scopes (`SettlementEnvelope` dataclass and `serialize_envelope_v3`); Snapshot `6bc09817-10d9-4855-a579-a0721a9ca837`; Replay `success` (`materialized_state_matches: true`).
  3. `validator_engine.py` (`1ed44b1b-bb16-4d25-b03e-6cdc9ef66087`): Advanced to `v5` across 5 observed scopes (`VALID_SCOPES`, `evaluate_settlement_rule_04`, `11`, `19`, and `27`); Snapshot `a9813a63-8144-4f25-997c-8952a0f14000`; Replay `success` (`materialized_state_matches: true`).
  4. `routing_manifest.json` (`58680d04-9b72-4711-b2df-ab81906909b4`): Advanced to `v4` across 4 observed scopes (`manifest_version`, `ten_006`, `ten_013`, and `ten_018`); Snapshot `49b50831-ce99-4424-acd6-15cb5c88c25f`; Replay `success` (`materialized_state_matches: true`).
  5. `MIGRATION_RUNBOOK.md` (`5452943b-6d67-40d5-bed0-82f6eaf48dd3`): Advanced to `v4` across 4 observed scopes (Section 1, Section 2.14, Section 3, Section 4); Snapshot `c537f763-80dc-41c3-9139-6664588230ea`; Replay `success` (`materialized_state_matches: true`).

---

## 4. Complete File Hashes & Byte Fidelity

The resulting workspaces were independently verified using the official evaluators:
1. Behavioral Verifier ([`verify_hard_suite.py`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/structural_retest/primary/evaluator/verify_hard_suite.py))
2. Full-Byte Oracle ([`full_byte_oracle.py`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/structural_retest/primary/evaluator/full_byte_oracle.py))

```text
==================================================================================================================================
File Name                Starting Hash (v0)                                                Final Produced Hash (All 3 Arms)
==================================================================================================================================
matrix_kernel.py         15906b9ab796d45886133a7a2085f1671dd4c6eb0bf359ea689821ad596f3bf0 36dba6340c0d47abcf6bbdc5e34788b8f800bbf0417254c7f791c40a926ab8f7
schema_defs.py           c0c99a1618d4500d8e016d3150be0c9247c8b0154c046b387885e9c47bf8fc39 da3e5504f40a5cb0d4da5638fb986e4c4c23af5185aa481d9737838fce3b9c4d
validator_engine.py      1f4b3e1d9052c72d840b9bcda4633744d7960e0d152924b9539419df1e7f5291 90871b4658e10e960585abf05c27031179f7aab16b77d9e97a9a69ed604b1484
routing_manifest.json    dcd050b53b771e9dca92a52c25bd8012e67917fd4ca149624b92c76ba87a2e89 84ce22315b1665e9308ccad447267c64ba04c4c660ee66a2be2f4ce14612306e
MIGRATION_RUNBOOK.md     fc026134e740237e3e4578e5282ebcb829e29281c6d7050964e96efdc850b0ed 95b08e130e92c0aeeada6d92518e48509f5dd131d4ff96cd6b51d5d0de3f5fbb
==================================================================================================================================
```

### Full-Byte Oracle & Behavioral Breakdown

| Check Group | Verification Target | Arm A | Arm B | Arm C |
|---|---|:---:|:---:|:---:|
| **Full-Byte Equality** | Exact whole-file byte match against gold reference | **Passed** (0 diffs) | **Passed** (0 diffs) | **Passed** (0 diffs) |
| `matrix_kernel.py` | Overlapping sync marker (`HEADER::SYNC::SYNC::CALIB...`) | Passed | Passed | Passed |
| `matrix_kernel.py` | Kernels 07, 14, 21 updated; remaining 21 kernels untouched | Passed | Passed | Passed |
| `matrix_kernel.py` | `dispatch_kernel_triad` telemetry & saturation clips | Passed | Passed | Passed |
| `schema_defs.py` | `SettlementEnvelope.idempotency_scope` dataclass field | Passed | Passed | Passed |
| `schema_defs.py` | `serialize_envelope_v3` updated; v1 & v2 untouched | Passed | Passed | Passed |
| `validator_engine.py` | `VALID_SCOPES` extended to `("GLOBAL", "PARTITION", "TENANT")` | Passed | Passed | Passed |
| `validator_engine.py` | Rules 04, 11, 19, 27 accept `ns`; other 26 rules untouched | Passed | Passed | Passed |
| `routing_manifest.json` | Manifest version `2026.10.2-v3` | Passed | Passed | Passed |
| `routing_manifest.json` | Tenants `ten_006`, `013`, `018` updated; 17 tenants untouched | Passed | Passed | Passed |
| `MIGRATION_RUNBOOK.md` | Allowed scopes, Gate 14, Canary table, Literal conflict template | Passed | Passed | Passed |
| **Total Behavioral** | **20 Automated Behavioral Checks** | **20 / 20 (100%)** | **20 / 20 (100%)** | **20 / 20 (100%)** |

---

## 5. Concrete Observations & Workflow Differences

1. **Transaction Granularity**:
   - **Arm A** applied edits incrementally via 20 individual `edit_file` calls, verifying each with `rtk read`.
   - **Arm B** leveraged Patch-DIFF's atomic transaction grouping, packaging all edits for an entire file into a single guarded `patchdiff_submit_edits` transaction per file (5 total transactions).
   - **Arm C** operated structurally, scoping each edit target to its Waymark symbol (`patchdiff_observe_scope`) and submitting an observed operation specifically bound to that symbol's sequential coordinates (20 total transactions).
2. **Deterministic Replay Integrity**:
   - In both Arm B and Arm C, all targets were checkpointed via `patchdiff_save` and replayed via `patchdiff_replay`.
   - Replay confirmed that re-executing transactions from the append-only log reproduced the materialized state with 100% hash, version, and content fidelity (`materialized_state_checks.all: true`).
3. **Absence of Regressions**:
   - None of the three arms introduced unintended collateral edits to neighboring kernels, rules, tenants, or serializers.
   - All 13 known failure modes detected by the full-byte oracle (trailing whitespace, comment shift, reordered JSON keys, unneeded line breaks) were completely avoided across all three workflows.

---

## 6. Artifact & Evidence Archive

All raw logs, transcripts, and final file outputs have been preserved in the workspace for independent review:

- **Arm A Workspace**: [`evaluation/subagent_runs/arm_A/`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/subagent_runs/arm_A)
- **Arm B Exports**: [`evaluation/subagent_runs/arm_B/exports/`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/subagent_runs/arm_B/exports)
- **Arm C Exports**: [`evaluation/subagent_runs/arm_C/exports/`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/subagent_runs/arm_C/exports)
- **Target Mappings**: [`arm_b_targets.json`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/subagent_runs/arm_b_targets.json), [`arm_c_targets.json`](file:///C:/Users/USER/Desktop/Frameworks/Patch-DIFF/evaluation/subagent_runs/arm_c_targets.json)
- **Full Transcripts**:
  - Arm A: [`3468a830-8787-4ccc-9419-8f7a4b7eb770`](conversation://3468a830-8787-4ccc-9419-8f7a4b7eb770)
  - Arm B: [`bb23a8af-6e47-47cf-862c-cb49dbbd34a6`](conversation://bb23a8af-6e47-47cf-862c-cb49dbbd34a6)
  - Arm C: [`a6965390-8119-4bba-afe1-e89c2697f710`](conversation://a6965390-8119-4bba-afe1-e89c2697f710)