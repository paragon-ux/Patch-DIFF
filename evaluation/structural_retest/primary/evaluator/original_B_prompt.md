You are executing the **PatchDIFF MCP (`patchdiff-tx/1`) Track** of a high-difficulty 5-file editing & token economics benchmark.

### STRICT BOUNDARY & GOVERNANCE RULES
1. **Never create, edit, or touch any file outside `C:\Users\USER\.gemini\antigravity\brain\b9443a60-130f-467d-8f8b-296809249560\scratch\hard_suite\patchdiff_workspace\`**.
2. **Use ONLY the current modernized PatchDIFF MCP tools** via `call_mcp_tool` (`ServerName: "patchdiff"`):
   - `patchdiff_find_occurrences` (parameters: `target_file_id`, `text`, `context_chars` [0..400, default 40], `start_occurrence`, `max_results`)
   - `patchdiff_read_target` (parameters: `target_file_id`, `start`, `length`)
   - `patchdiff_submit_edits` (parameters: `target_file_id`, `expected_target_version`, `expected_current_hash`, `client_request_id`, `intent`, `edits: [{match, replace, occurrence_index?, anchor_before?, anchor_after?, change_id?, rationale?, risk?}]`, `parent_pdcp_log_id`, `attempt`)
   - `patchdiff_save` (parameters: `target_file_id`, `expected_current_hash`)
   - `patchdiff_replay` (parameters: `target_file_id`)
   - **Do NOT use legacy `patchdiff_submit_pdcp`.**
   - **Do NOT use `edit_file` or `write_file` or `rtk read` to inspect or edit the target files.** All inspection and editing of the 5 targets must go through the PatchDIFF MCP tools!
3. Only AFTER all 5 targets have been edited, saved (`patchdiff_save`), and verified (`patchdiff_replay`) in PatchDIFF, run this single one-liner via `run_command` to sync the exported canonical contents from PatchDIFF Postgres to `patchdiff_workspace` for the external test harness:
   `$env:PYTHONPATH="backend"; .\.venv\Scripts\python.exe -c "import json; from pathlib import Path; from app.mcp import tools; from app.mcp.server import registry; ws=Path(r'C:\Users\USER\.gemini\antigravity\brain\b9443a60-130f-467d-8f8b-296809249560\scratch\hard_suite\patchdiff_workspace'); m=json.loads((ws.parent/'targets_manifest.json').read_text()); [ (ws/f).write_text(registry.call('patchdiff_export_target', target_file_id=info['target_file_id'])['content'], encoding='utf-8', newline='\n') for f, info in m.items() ]"`

---

### TARGETS REGISTERED IN PATCHDIFF POSTGRES
All 5 targets start at `version: 0`:
1. `matrix_kernel.py`: `target_file_id = "a02a9469-6789-47fa-8910-bd92439a87c4"` (`initial_hash = "15906b9ab796d45886133a7a2085f1671dd4c6eb0bf359ea689821ad596f3bf0"`)
2. `schema_defs.py`: `target_file_id = "2196776b-8dbe-48e5-8621-abec447ff592"` (`initial_hash = "c0c99a1618d4500d8e016d3150be0c9247c8b0154c046b387885e9c47bf8fc39"`)
3. `validator_engine.py`: `target_file_id = "f5375412-34a4-46d6-acfd-594f08d174e3"` (`initial_hash = "1f4b3e1d9052c72d840b9bcda4633744d7960e0d152924b9539419df1e7f5291"`)
4. `routing_manifest.json`: `target_file_id = "3de32588-53d3-4053-837c-f5afa5ae1038"` (`initial_hash = "dcd050b53b771e9dca92a52c25bd8012e67917fd4ca149624b92c76ba87a2e89"`)
5. `MIGRATION_RUNBOOK.md`: `target_file_id = "f7e74e57-fd8a-4a7c-921a-a87662280feb"` (`initial_hash = "fc026134e740237e3e4578e5282ebcb829e29281c6d7050964e96efdc850b0ed"`)

---

### EXACT MULTI-FILE EDIT SPECIFICATION (21 EDITS ACROSS 5 FILES)

#### File 1: `matrix_kernel.py` (`a02a9469-6789-47fa-8910-bd92439a87c4`)
Contains `FRAME_SYNC_STREAM`, 24 nearly identical SIMD kernel functions (`execute_tile_kernel_01` .. `execute_tile_kernel_24`), and `dispatch_kernel_triad`.
1. **Overlapping Sync Marker**: In `FRAME_SYNC_STREAM = "HEADER::SYNC::SYNC::SYNC::SYNC::SYNC::TRAILER"`, replace the **2nd overlapping occurrence** (`occurrence_index: 2`) of `"::SYNC::SYNC::"` with `"::SYNC::CALIB::"` so the string becomes `"HEADER::SYNC::SYNC::CALIB::SYNC::SYNC::TRAILER"`.
2. **Kernels `07`, `14`, and `21` ONLY** (out of 24 identical kernels; all other 21 kernels MUST remain untouched!):
   - Change `stride_offset = (block_id << 4) + lane_id` to `stride_offset = (block_id << 5) + (lane_id * 3)`
   - Change `scaled = cell >> scale_shift` to `scaled = (cell + (1 << (scale_shift - 1))) >> scale_shift`
3. **`dispatch_kernel_triad`**:
   - After `total_acc = k07["accumulator"] + k14["accumulator"] + k21["accumulator"]`, add:
     `total_clips = k07["saturation_clips"] + k14["saturation_clips"] + k21["saturation_clips"]`
   - In the returned dictionary, immediately after `"total_accumulator": total_acc,`, add:
     `"total_saturation_clips": total_clips,`

#### File 2: `schema_defs.py` (`2196776b-8dbe-48e5-8621-abec447ff592`)
Contains `SettlementEnvelope` dataclass and 3 serializers (`serialize_envelope_v1`, `serialize_envelope_v2`, `serialize_envelope_v3`) that share identical inner lines.
1. **`SettlementEnvelope` dataclass**: Immediately after `schema_revision: str = "v3"`, add a new field:
   `idempotency_scope: str = "GLOBAL"`
2. **`serialize_envelope_v3` ONLY** (leave `serialize_envelope_v1` and `serialize_envelope_v2` 100% untouched!):
   - Change `"epoch_unit": "sec",` to `"epoch_unit": "ns",`
   - Change `"settlement_epoch": env.settlement_epoch_sec,` to `"settlement_epoch": env.settlement_epoch_sec * 1_000_000_000,`
   - Change `"quorum_required": 2,` to `"quorum_required": 3,` and immediately after it add `"idempotency_scope": env.idempotency_scope,`

#### File 3: `validator_engine.py` (`f5375412-34a4-46d6-acfd-594f08d174e3`)
Contains `VALID_SCOPES` and 30 identical-looking rule functions (`evaluate_settlement_rule_01` .. `evaluate_settlement_rule_30`).
1. Change `VALID_SCOPES = ("GLOBAL", "PARTITION")` to `VALID_SCOPES = ("GLOBAL", "PARTITION", "TENANT")`.
2. In **ONLY** `evaluate_settlement_rule_04`, `evaluate_settlement_rule_11`, `evaluate_settlement_rule_19`, and `evaluate_settlement_rule_27` (leave the other 26 rule functions 100% untouched!):
   - Change `unit = packet.get("epoch_unit", "sec")` to `unit = packet.get("epoch_unit", "ns")`
   - Change `max_drift = 30` to `max_drift = 30_000_000_000`
   - Change `quorum = int(packet.get("quorum_required", 2))` to `quorum = int(packet.get("quorum_required", 3))`
   - Change `if unit != "sec":` to `if unit != "ns":`
   - Change `if quorum < 2:` to `if quorum < 3:`
   *(Tip: Remember that `apply_pdcp_transaction` applies edits sequentially in memory! If you use `occurrence_index` across multiple edits that mutate the matched pattern, earlier replacements reduce the total occurrence count for subsequent edits in the same transaction, OR you can match each rule's contiguous block or account for sequential occurrence indices!)*

#### File 4: `routing_manifest.json` (`3de32588-53d3-4053-837c-f5afa5ae1038`)
Contains `"manifest_version"` and 20 tenant objects (`ten_001` .. `ten_020`).
1. Change `"manifest_version": "2026.10.1"` to `"manifest_version": "2026.10.2-v3"`.
2. For **ONLY** tenants `ten_006`, `ten_013`, and `ten_018` (leave all other 17 tenants untouched!):
   - Change `"wire_version": "v2",` to `"wire_version": "v3",`
   - Change `"epoch_unit": "sec",` to `"epoch_unit": "ns",`
   - Change `"max_drift": 30,` to `"max_drift": 30000000000,`
   - Change `"quorum_size": 2,` to `"quorum_size": 3,`
   - Change `"idempotency_scope": "GLOBAL",` to `"idempotency_scope": "TENANT",`

#### File 5: `MIGRATION_RUNBOOK.md` (`f7e74e57-fd8a-4a7c-921a-a87662280feb`)
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
1. **Summary Table per File**: `filename`, `target_file_id`, `read/search calls`, `submit_edits calls`, `retries/rejections`, `final_version`, `final_hash`, `replay_status`.
2. **Rejection & Recovery Log**: Details of any rejected transactions (`failure_reason`, `pdcp_log_id`) and how you recovered using `parent_pdcp_log_id`.
3. **Ergonomics & Difficulty Observations**: How `patchdiff_find_occurrences`, `occurrence_index` / anchors, and atomic multi-edit transactions handled the 24-kernel, 30-rule, 20-tenant, and conflict-marker traps.
