from __future__ import annotations

import json
from pathlib import Path

from app.mcp import tools  # noqa: F401
from app.mcp.server import registry

SUITE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = SUITE_DIR / "source"
NATIVE_WS = SUITE_DIR / "native_workspace"
PATCHDIFF_WS = SUITE_DIR / "patchdiff_workspace"


def gen_matrix_kernel_py() -> str:
    """~580 lines, ~23 KB. 24 nearly identical SIMD kernel functions + overlapping state marker."""
    lines = [
        '"""High-Throughput Quantized Matrix Kernel & Frame Sync Module."""',
        "from __future__ import annotations",
        "",
        "from typing import Sequence",
        "",
        '# Overlapping frame sync marker stream (contains overlapping "::SYNC::SYNC::" occurrences)',
        'FRAME_SYNC_STREAM = "HEADER::SYNC::SYNC::SYNC::SYNC::SYNC::TRAILER"',
        "",
    ]

    for k in range(1, 25):
        lines.extend(
            [
                f"def execute_tile_kernel_{k:02d}(",
                "    tile: Sequence[Sequence[int]],",
                "    weights: Sequence[Sequence[int]],",
                "    lane_id: int = 0,",
                "    scale_shift: int = 4,",
                ") -> dict[str, int]:",
                f'    """Execute quantized 4x4 tile kernel #{k:02d} with deterministic saturation."""',
                f"    block_id = {k}",
                "    stride_offset = (block_id << 4) + lane_id",
                "    accumulator = 0",
                "    saturation_clips = 0",
                "    for i in range(4):",
                "        for j in range(4):",
                "            cell = 0",
                "            for d in range(4):",
                "                cell += tile[i][d] * weights[d][j]",
                "            scaled = cell >> scale_shift",
                "            if scaled > 32767:",
                "                scaled = 32767",
                "                saturation_clips += 1",
                "            elif scaled < -32768:",
                "                scaled = -32768",
                "                saturation_clips += 1",
                "            accumulator += scaled",
                "    return {",
                '        "kernel_id": block_id,',
                '        "stride_offset": stride_offset,',
                '        "accumulator": accumulator,',
                '        "saturation_clips": saturation_clips,',
                "    }",
                "",
            ]
        )

    lines.extend(
        [
            "def dispatch_kernel_triad(",
            "    tile: Sequence[Sequence[int]],",
            "    weights: Sequence[Sequence[int]],",
            ") -> dict[str, object]:",
            '    """Run primary calibration triad (kernels 07, 14, 21) and return combined telemetry."""',
            "    k07 = execute_tile_kernel_07(tile, weights, lane_id=1)",
            "    k14 = execute_tile_kernel_14(tile, weights, lane_id=2)",
            "    k21 = execute_tile_kernel_21(tile, weights, lane_id=3)",
            '    total_acc = k07["accumulator"] + k14["accumulator"] + k21["accumulator"]',
            "    return {",
            '        "sync_stream": FRAME_SYNC_STREAM,',
            '        "triad_kernels": (7, 14, 21),',
            '        "total_accumulator": total_acc,',
            '        "k07": k07,',
            '        "k14": k14,',
            '        "k21": k21,',
            "    }",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def gen_schema_defs_py() -> str:
    """~480 lines, ~19 KB. Contains v1, v2, v3 envelope serializers with identical inner lines."""
    lines = [
        '"""Canonical Settlement Envelope Schemas (v1, v2, v3)."""',
        "from __future__ import annotations",
        "",
        "import dataclasses",
        "import hashlib",
        "from typing import Any",
        "",
        "",
        "@dataclasses.dataclass(frozen=True)",
        "class SettlementEnvelope:",
        "    envelope_id: str",
        "    tenant_id: str",
        "    amount_minor: int",
        "    currency: str",
        "    settlement_epoch_sec: int",
        '    schema_revision: str = "v3"',
        "",
    ]

    # Add 22 field normalizer helpers so the serializers sit in the middle/lower half of the file
    for idx in range(1, 23):
        lines.extend(
            [
                f"def normalize_ledger_attribute_{idx:02d}(raw_val: Any, default_tag: str = 'TAG_{idx:02d}') -> dict[str, Any]:",
                f'    """Normalize ledger attribute slot #{idx:02d} for canonical hashing."""',
                "    text = str(raw_val).strip() if raw_val is not None else default_tag",
                '    digest = hashlib.sha256(f"{default_tag}:{text}".encode("utf-8")).hexdigest()[:12]',
                "    return {",
                f'        "slot": {idx},',
                '        "tag": default_tag,',
                '        "value": text,',
                '        "checksum": digest,',
                "    }",
                "",
            ]
        )

    # Three serializers (v1, v2, v3) that share identical dictionary construction lines
    for ver in ("v1", "v2", "v3"):
        lines.extend(
            [
                f"def serialize_envelope_{ver}(env: SettlementEnvelope) -> dict[str, Any]:",
                f'    """Serialize SettlementEnvelope using protocol wire format {ver}."""',
                "    if env.amount_minor < 0:",
                '        raise ValueError("amount_minor must be non-negative")',
                "    payload = {",
                f'        "wire_version": "{ver}",',
                '        "envelope_id": env.envelope_id,',
                '        "tenant_id": env.tenant_id,',
                '        "amount_minor": env.amount_minor,',
                '        "currency": env.currency.upper(),',
                '        "epoch_unit": "sec",',
                '        "settlement_epoch": env.settlement_epoch_sec,',
                '        "quorum_required": 2,',
                "    }",
                "    return payload",
                "",
            ]
        )

    # Add trailing codec helpers
    for idx in range(1, 9):
        lines.extend(
            [
                f"def verify_codec_footer_{idx:02d}(packet: dict[str, Any]) -> bool:",
                f'    """Verify structural footer invariant #{idx:02d}."""',
                '    return bool(packet.get("envelope_id")) and int(packet.get("amount_minor", -1)) >= 0',
                "",
            ]
        )

    return "\n".join(lines) + "\n"


def gen_validator_engine_py() -> str:
    """~540 lines, ~21 KB. 30 rule functions (rule_01 .. rule_30) with identical bodies."""
    lines = [
        '"""Deterministic Settlement Rule Validation Engine."""',
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        'VALID_SCOPES = ("GLOBAL", "PARTITION")',
        "",
    ]

    for r in range(1, 31):
        lines.extend(
            [
                f"def evaluate_settlement_rule_{r:02d}(packet: dict[str, Any]) -> tuple[bool, str]:",
                f'    """Evaluate compliance rule #{r:02d} against serialized settlement packet."""',
                '    unit = packet.get("epoch_unit", "sec")',
                '    max_drift = 30',
                '    quorum = int(packet.get("quorum_required", 2))',
                '    scope = str(packet.get("idempotency_scope", "GLOBAL"))',
                "    if scope not in VALID_SCOPES:",
                f'        return False, "rule_{r:02d}: invalid_scope"',
                '    if unit != "sec":',
                f'        return False, "rule_{r:02d}: invalid_epoch_unit"',
                "    if quorum < 2:",
                f'        return False, "rule_{r:02d}: insufficient_quorum"',
                '    drift = abs(int(packet.get("clock_drift", 0)))',
                "    if drift > max_drift:",
                f'        return False, "rule_{r:02d}: drift_exceeded"',
                f'    return True, "rule_{r:02d}: ok"',
                "",
            ]
        )

    lines.extend(
        [
            "def run_v3_critical_rules(packet: dict[str, Any]) -> list[tuple[bool, str]]:",
            '    """Run the 4 v3-upgraded critical rules (04, 11, 19, 27)."""',
            "    return [",
            "        evaluate_settlement_rule_04(packet),",
            "        evaluate_settlement_rule_11(packet),",
            "        evaluate_settlement_rule_19(packet),",
            "        evaluate_settlement_rule_27(packet),",
            "    ]",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def gen_routing_manifest_json() -> str:
    """~440 lines, ~13 KB. 20 tenant route objects with identical field lines."""
    tenants = []
    for idx in range(1, 21):
        tenants.append(
            {
                "tenant_id": f"ten_{idx:03d}",
                "cluster_shard": f"shard-{(idx - 1) // 5 + 1:02d}",
                "wire_version": "v2",
                "epoch_unit": "sec",
                "max_drift": 30,
                "quorum_size": 2,
                "idempotency_scope": "GLOBAL",
                "failover": {
                    "enabled": True,
                    "backoff_ms": 250,
                    "max_attempts": 3,
                },
            }
        )
    doc = {
        "manifest_version": "2026.10.1",
        "environment": "prod-multi-region",
        "tenants": tenants,
    }
    return json.dumps(doc, indent=2) + "\n"


def gen_migration_runbook_md() -> str:
    """~460 lines, ~18 KB. Contains 24 runbook sections, tables, and literal conflict markers."""
    sections = [
        "# Settlement Protocol v3 Nanosecond & Quorum Migration Runbook",
        "",
        "## 1. Executive Summary",
        "",
        "- **Active Wire Default**: `v2` (`epoch_unit = sec`)",
        "- **Allowed Idempotency Scopes**: `GLOBAL, PARTITION`",
        "- **Critical Rule Cohort**: `rule_04, rule_11, rule_19, rule_27`",
        "- **Canary Tenant Cohort**: `ten_006, ten_013, ten_018`",
        "",
    ]

    for step in range(1, 21):
        sections.extend(
            [
                f"## 2.{step} Pre-Flight Verification Gate #{step:02d}",
                "",
                f"Verify partition telemetry and replication watermark for gate `{step:02d}` before",
                "promoting canary tenants to the next epoch precision tier.",
                "",
                "| Check ID | Metric | Threshold | Action on Breach |",
                "| --- | --- | --- | --- |",
                f"| `CHK-{step:02d}-A` | Replication lag | `< 50 ms` | Halt canary promotion |",
                f"| `CHK-{step:02d}-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |",
                f"| `CHK-{step:02d}-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |",
                "",
            ]
        )

    sections.extend(
        [
            "## 3. Canary Cohort Parameters",
            "",
            "| Cohort | Wire Version | Epoch Unit | Max Drift | Quorum Size | Scope |",
            "| --- | --- | --- | --- | --- | --- |",
            "| `legacy-default` | `v2` | `sec` | `30` | `2` | `GLOBAL` |",
            "| `canary-v3` | `v2` | `sec` | `30` | `2` | `GLOBAL` |",
            "",
            "## 4. Literal Patch & Conflict Template",
            "",
            "Operators auditing raw diffs must verify the literal marker block below:",
            "",
            "```text",
            "<<<<<<< MATCH",
            'wire_version = "v2"',
            'epoch_unit = "sec"',
            "quorum_required = 2",
            "=======",
            'wire_version = "v3"',
            'epoch_unit = "sec"',
            "quorum_required = 2",
            ">>>>>>> REPLACE",
            "```",
            "",
        ]
    )
    return "\n".join(sections) + "\n"


def main() -> None:
    for d in (SOURCE_DIR, NATIVE_WS, PATCHDIFF_WS):
        d.mkdir(parents=True, exist_ok=True)

    files = {
        "matrix_kernel.py": (gen_matrix_kernel_py(), "text/x-python"),
        "schema_defs.py": (gen_schema_defs_py(), "text/x-python"),
        "validator_engine.py": (gen_validator_engine_py(), "text/x-python"),
        "routing_manifest.json": (gen_routing_manifest_json(), "application/json"),
        "MIGRATION_RUNBOOK.md": (gen_migration_runbook_md(), "text/markdown"),
    }

    manifest = {}
    for fname, (content, ctype) in files.items():
        (SOURCE_DIR / fname).write_text(content, encoding="utf-8", newline="\n")
        (NATIVE_WS / fname).write_text(content, encoding="utf-8", newline="\n")
        (PATCHDIFF_WS / fname).write_text(content, encoding="utf-8", newline="\n")
        res = registry.call(
            "patchdiff_initialize_target",
            filename=fname,
            content=content,
            content_type=ctype,
        )
        manifest[fname] = {
            "target_file_id": res["target_file_id"],
            "initial_version": res["version"],
            "initial_hash": res["current_hash"],
            "bytes": len(content.encode("utf-8")),
            "lines": content.count("\n"),
        }

    (SUITE_DIR / "targets_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
