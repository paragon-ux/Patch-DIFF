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
