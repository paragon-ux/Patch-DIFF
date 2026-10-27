You are executing the **Native File Editing (`rtk read` + `edit_file`) Track** of a high-difficulty 5-file editing & token economics benchmark.

### STRICT BOUNDARY & GOVERNANCE RULES
1. **Never create, edit, or touch any file outside `C:\Users\USER\.gemini\antigravity\brain\b9443a60-130f-467d-8f8b-296809249560\scratch\hard_suite\native_workspace\`**.
2. **Use ONLY native file inspection and editing tools**:
   - Inspect files using `rtk read <file>` via `run_command` (remember `read_file` is blocked by the governance hook).
   - Edit files using the native `edit_file` tool (`Path`, `Target`, `Replacement`).
   - **Do NOT use any `patchdiff` MCP tools.**
   - **Do NOT use Python/PowerShell scripts to edit or rewrite the files.** Every file modification MUST be performed via the `edit_file` tool!
   - Remember `edit_file` rules:
     1. Use `edit_file` for a single contiguous block of edits. To edit multiple non-adjacent regions, make separate calls.
     2. `Target` must exactly match existing file text, including whitespace.
     3. **CRITICAL TRAP**: If `Target` appears multiple times in the file, **every occurrence is replaced** by `edit_file`! You must include enough unique surrounding context in `Target` and `Replacement` so you do not accidentally overwrite other functions/tenants/rules!

---

### TARGET FILES IN YOUR WORKSPACE
All 5 files are located in `C:\Users\USER\.gemini\antigravity\brain\b9443a60-130f-467d-8f8b-296809249560\scratch\hard_suite\native_workspace\`:
1. `matrix_kernel.py` (770 lines, 24,065 bytes)
2. `schema_defs.py` (339 lines, 13,393 bytes)
3. `validator_engine.py` (526 lines, 21,797 bytes)
4. `routing_manifest.json` (286 lines, 6,555 bytes)
5. `MIGRATION_RUNBOOK.md` (252 lines, 10,072 bytes)

---

### EXACT MULTI-FILE EDIT SPECIFICATION (21 EDITS ACROSS 5 FILES)

#### File 1: `matrix_kernel.py`
Contains `FRAME_SYNC_STREAM`, 24 nearly identical SIMD kernel functions (`execute_tile_kernel_01` .. `execute_tile_kernel_24`), and `dispatch_kernel_triad`.
1. **Overlapping Sync Marker**: In `FRAME_SYNC_STREAM = "HEADER::SYNC::SYNC::SYNC::SYNC::SYNC::TRAILER"`, replace the **2nd overlapping occurrence** of `"::SYNC::SYNC::"` with `"::SYNC::CALIB::"` so the string becomes `"HEADER::SYNC::SYNC::CALIB::SYNC::SYNC::TRAILER"`.
2. **Kernels `07`, `14`, and `21` ONLY** (out of 24 identical kernels; all other 21 kernels MUST remain untouched!):
   - Change `stride_offset = (block_id << 4) + lane_id` to `stride_offset = (block_id << 5) + (lane_id * 3)`
   - Change `scaled = cell >> scale_shift` to `scaled = (cell + (1 << (scale_shift - 1))) >> scale_shift`
3. **`dispatch_kernel_triad`**:
   - After `total_acc = k07["accumulator"] + k14["accumulator"] + k21["accumulator"]`, add:
     `total_clips = k07["saturation_clips"] + k14["saturation_clips"] + k21["saturation_clips"]`
   - In the returned dictionary, immediately after `"total_accumulator": total_acc,`, add:
     `"total_saturation_clips": total_clips,`

#### File 2: `schema_defs.py`
Contains `SettlementEnvelope` dataclass and 3 serializers (`serialize_envelope_v1`, `serialize_envelope_v2`, `serialize_envelope_v3`) that share identical inner lines.
1. **`SettlementEnvelope` dataclass**: Immediately after `schema_revision: str = "v3"`, add a new field:
   `idempotency_scope: str = "GLOBAL"`
2. **`serialize_envelope_v3` ONLY** (leave `serialize_envelope_v1` and `serialize_envelope_v2` 100% untouched!):
   - Change `"epoch_unit": "sec",` to `"epoch_unit": "ns",`
   - Change `"settlement_epoch": env.settlement_epoch_sec,` to `"settlement_epoch": env.settlement_epoch_sec * 1_000_000_000,`
   - Change `"quorum_required": 2,` to `"quorum_required": 3,` and immediately after it add `"idempotency_scope": env.idempotency_scope,`

#### File 3: `validator_engine.py`
Contains `VALID_SCOPES` and 30 identical-looking rule functions (`evaluate_settlement_rule_01` .. `evaluate_settlement_rule_30`).
1. Change `VALID_SCOPES = ("GLOBAL", "PARTITION")` to `VALID_SCOPES = ("GLOBAL", "PARTITION", "TENANT")`.
2. In **ONLY** `evaluate_settlement_rule_04`, `evaluate_settlement_rule_11`, `evaluate_settlement_rule_19`, and `evaluate_settlement_rule_27` (leave the other 26 rule functions 100% untouched!):
   - Change `unit = packet.get("epoch_unit", "sec")` to `unit = packet.get("epoch_unit", "ns")`
   - Change `max_drift = 30` to `max_drift = 30_000_000_000`
   - Change `quorum = int(packet.get("quorum_required", 2))` to `quorum = int(packet.get("quorum_required", 3))`
   - Change `if unit != "sec":` to `if unit != "ns":`
   - Change `if quorum < 2:` to `if quorum < 3:`

#### File 4: `routing_manifest.json`
Contains `"manifest_version"` and 20 tenant objects (`ten_001` .. `ten_020`).
1. Change `"manifest_version": "2026.10.1"` to `"manifest_version": "2026.10.2-v3"`.
2. For **ONLY** tenants `ten_006`, `ten_013`, and `ten_018` (leave all other 17 tenants untouched!):
   - Change `"wire_version": "v2",` to `"wire_version": "v3",`
   - Change `"epoch_unit": "sec",` to `"epoch_unit": "ns",`
   - Change `"max_drift": 30,` to `"max_drift": 30000000000,`
   - Change `"quorum_size": 2,` to `"quorum_size": 3,`
   - Change `"idempotency_scope": "GLOBAL",` to `"idempotency_scope": "TENANT",`

#### File 5: `MIGRATION_RUNBOOK.md`
1. In Section 1, change `- **Allowed Idempotency Scopes**: \`GLOBAL, PARTITION\`` to `- **Allowed Idempotency Scopes**: \`GLOBAL, PARTITION, TENANT\``.
2. In Section 2.14 (Gate #14 ONLY; leave the other 19 gates untouched!), change:
   `| \`CHK-14-C\` | Clock skew p99 | \`<= 30 sec\` | Trigger NTP resync |`
   to:
   `| \`CHK-14-C\` | Clock skew p99 | \`<= 30000000000 ns\` | Trigger PTP hardware resync |`
3. In Section 3 Canary Cohort Parameters table, change:
   `| \`canary-v3\` | \`v2\` | \`sec\` | \`30\` | \`2\` | \`GLOBAL\` |`
   to:
   `| \`canary-v3\` | \`v3\` | \`ns\` | \`30000000000\` | \`3\` | \`TENANT\` |`
4. In Section 4 Literal Patch & Conflict Template (inside the fenced block containing literal `<<<<<<< MATCH` / `=======` / `>>>>>>> REPLACE`), change the replacement portion from:
   ```text
   =======
   wire_version = "v3"
   epoch_unit = "sec"
   quorum_required = 2
   >>>>>>> REPLACE
   ```
   to:
   ```text
   =======
   wire_version = "v3"
   epoch_unit = "ns"
   quorum_required = 3
   >>>>>>> REPLACE
   ```

---

### REQUIRED DELIVERABLE FORMAT
When finished, reply with a structured Markdown report containing:
1. **Summary Table per File**: `filename`, `rtk read calls`, `edit_file calls`, `truncations or retries encountered`.
2. **Context & Boilerplate Overhead**: How much surrounding context you had to duplicate in `Target` and `Replacement` to prevent `edit_file` from globally overwriting all 24 kernels, 30 rules, or 20 tenants, and whether `rtk read` output truncation required follow-up reads.
3. **Final Verification**: Confirm all 21 edits were applied only inside `native_workspace`.
