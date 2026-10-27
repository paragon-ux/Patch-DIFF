"""Standalone final-workspace verifier for the 5-file / 20-check hard suite.

Remediates BM-7 by packaging the verifier directly inside the benchmark directory
with zero external `app.*` imports or hardcoded machine paths.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SUITE_DIR = Path(__file__).resolve().parent


def load_module_from_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def check_workspace(ws_dir: Path, label: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    # 1. Verify matrix_kernel.py
    mk_path = ws_dir / "matrix_kernel.py"
    try:
        mk = load_module_from_path(f"mk_{label}", mk_path)
        record(
            "matrix_kernel.sync_stream_2nd_overlap",
            mk.FRAME_SYNC_STREAM == "HEADER::SYNC::SYNC::CALIB::SYNC::SYNC::TRAILER",
            f"got {mk.FRAME_SYNC_STREAM!r}",
        )
        tile = [[10, 20, 30, 40]] * 4
        weights = [[1, 2, 3, 4]] * 4
        for k in range(1, 25):
            fn = getattr(mk, f"execute_tile_kernel_{k:02d}")
            res = fn(tile, weights, lane_id=2, scale_shift=4)
            if k in (7, 14, 21):
                exp_stride = (k << 5) + 6
                exp_acc = 252
                record(
                    f"matrix_kernel.k{k:02d}_updated",
                    res["stride_offset"] == exp_stride and res["accumulator"] == exp_acc,
                    f"got {res}",
                )
            else:
                exp_stride = (k << 4) + 2
                exp_acc = 244
                if res["stride_offset"] != exp_stride or res["accumulator"] != exp_acc:
                    record(
                        f"matrix_kernel.k{k:02d}_untouched",
                        False,
                        f"corrupted non-target kernel {k:02d}: {res}",
                    )
        untouched_ok = all(
            getattr(mk, f"execute_tile_kernel_{k:02d}")(tile, weights, lane_id=2, scale_shift=4)["accumulator"] == 244
            and getattr(mk, f"execute_tile_kernel_{k:02d}")(tile, weights, lane_id=2, scale_shift=4)["stride_offset"] == (k << 4) + 2
            for k in range(1, 25)
            if k not in (7, 14, 21)
        )
        record("matrix_kernel.other_21_kernels_untouched", untouched_ok)

        triad = mk.dispatch_kernel_triad(tile, weights)
        record(
            "matrix_kernel.dispatch_triad_total_saturation_clips",
            "total_saturation_clips" in triad and triad["total_saturation_clips"] == 0 and triad["total_accumulator"] == 756,
            f"got keys={list(triad.keys())}, total_acc={triad.get('total_accumulator')}",
        )
    except Exception as exc:
        record("matrix_kernel.import_and_exec", False, repr(exc))

    # 2. Verify schema_defs.py
    sd_path = ws_dir / "schema_defs.py"
    try:
        sd = load_module_from_path(f"sd_{label}", sd_path)
        env = sd.SettlementEnvelope(
            envelope_id="env_1",
            tenant_id="ten_006",
            amount_minor=5000,
            currency="usd",
            settlement_epoch_sec=1700000000,
        )
        record(
            "schema_defs.dataclass_default_scope",
            getattr(env, "idempotency_scope", None) == "GLOBAL",
            f"got {getattr(env, 'idempotency_scope', None)!r}",
        )
        env_custom = sd.SettlementEnvelope(
            envelope_id="env_2",
            tenant_id="ten_006",
            amount_minor=5000,
            currency="usd",
            settlement_epoch_sec=1700000000,
            idempotency_scope="TENANT",
        )
        s1 = sd.serialize_envelope_v1(env_custom)
        s2 = sd.serialize_envelope_v2(env_custom)
        s3 = sd.serialize_envelope_v3(env_custom)
        record(
            "schema_defs.v1_v2_untouched",
            s1["epoch_unit"] == "sec"
            and s1["settlement_epoch"] == 1700000000
            and s1["quorum_required"] == 2
            and "idempotency_scope" not in s1
            and s2["epoch_unit"] == "sec"
            and s2["settlement_epoch"] == 1700000000
            and s2["quorum_required"] == 2
            and "idempotency_scope" not in s2,
            f"s1={s1}, s2={s2}",
        )
        record(
            "schema_defs.v3_updated",
            s3.get("epoch_unit") == "ns"
            and s3.get("settlement_epoch") == 1700000000 * 1_000_000_000
            and s3.get("quorum_required") == 3
            and s3.get("idempotency_scope") == "TENANT",
            f"s3={s3}",
        )
    except Exception as exc:
        record("schema_defs.import_and_exec", False, repr(exc))

    # 3. Verify validator_engine.py
    ve_path = ws_dir / "validator_engine.py"
    try:
        ve = load_module_from_path(f"ve_{label}", ve_path)
        record(
            "validator_engine.valid_scopes",
            tuple(ve.VALID_SCOPES) == ("GLOBAL", "PARTITION", "TENANT"),
            f"got {ve.VALID_SCOPES!r}",
        )
        v3_pkt = {
            "epoch_unit": "ns",
            "quorum_required": 3,
            "idempotency_scope": "TENANT",
            "clock_drift": 15_000_000_000,
        }
        v2_pkt = {
            "epoch_unit": "sec",
            "quorum_required": 2,
            "idempotency_scope": "TENANT",
            "clock_drift": 20,
        }
        crit_results = ve.run_v3_critical_rules(v3_pkt)
        record(
            "validator_engine.v3_critical_rules_04_11_19_27_accept_ns",
            all(ok for ok, _ in crit_results)
            and not any(
                getattr(ve, f"evaluate_settlement_rule_{r:02d}")({"epoch_unit": "ns", "quorum_required": 2, "idempotency_scope": "TENANT", "clock_drift": 0})[0]
                for r in (4, 11, 19, 27)
            ),
            f"got {crit_results}",
        )
        other_26_ok = all(
            getattr(ve, f"evaluate_settlement_rule_{r:02d}")(v2_pkt) == (True, f"rule_{r:02d}: ok")
            and getattr(ve, f"evaluate_settlement_rule_{r:02d}")(v3_pkt)[0] is False
            for r in range(1, 31)
            if r not in (4, 11, 19, 27)
        )
        record("validator_engine.other_26_rules_untouched", other_26_ok)
    except Exception as exc:
        record("validator_engine.import_and_exec", False, repr(exc))

    # 4. Verify routing_manifest.json
    rm_path = ws_dir / "routing_manifest.json"
    try:
        rm = json.loads(rm_path.read_text(encoding="utf-8"))
        record(
            "routing_manifest.version_updated",
            rm.get("manifest_version") == "2026.10.2-v3",
            f"got {rm.get('manifest_version')!r}",
        )
        tenants = {t["tenant_id"]: t for t in rm["tenants"]}
        canary_ids = {"ten_006", "ten_013", "ten_018"}
        canary_ok = all(
            tenants[tid]["wire_version"] == "v3"
            and tenants[tid]["epoch_unit"] == "ns"
            and tenants[tid]["max_drift"] == 30000000000
            and tenants[tid]["quorum_size"] == 3
            and tenants[tid]["idempotency_scope"] == "TENANT"
            for tid in canary_ids
        )
        record("routing_manifest.canary_tenants_006_013_018_updated", canary_ok)
        others_ok = all(
            t["wire_version"] == "v2"
            and t["epoch_unit"] == "sec"
            and t["max_drift"] == 30
            and t["quorum_size"] == 2
            and t["idempotency_scope"] == "GLOBAL"
            for tid, t in tenants.items()
            if tid not in canary_ids
        )
        record("routing_manifest.other_17_tenants_untouched", others_ok)
    except Exception as exc:
        record("routing_manifest.parse_and_check", False, repr(exc))

    # 5. Verify MIGRATION_RUNBOOK.md
    rb_path = ws_dir / "MIGRATION_RUNBOOK.md"
    try:
        rb = rb_path.read_text(encoding="utf-8")
        record(
            "runbook.allowed_scopes",
            "- **Allowed Idempotency Scopes**: `GLOBAL, PARTITION, TENANT`" in rb,
        )
        record(
            "runbook.gate_14_updated",
            "| `CHK-14-C` | Clock skew p99 | `<= 30000000000 ns` | Trigger PTP hardware resync |" in rb,
        )
        other_gates_ok = all(
            f"| `CHK-{s:02d}-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |" in rb
            for s in range(1, 21)
            if s != 14
        )
        record("runbook.other_19_gates_untouched", other_gates_ok)
        record(
            "runbook.canary_table_updated",
            "| `canary-v3` | `v3` | `ns` | `30000000000` | `3` | `TENANT` |" in rb
            and "| `legacy-default` | `v2` | `sec` | `30` | `2` | `GLOBAL` |" in rb,
        )
        expected_conflict_block = (
            "<<<<<<< MATCH\n"
            'wire_version = "v2"\n'
            'epoch_unit = "sec"\n'
            "quorum_required = 2\n"
            "=======\n"
            'wire_version = "v3"\n'
            'epoch_unit = "ns"\n'
            "quorum_required = 3\n"
            ">>>>>>> REPLACE"
        )
        record("runbook.conflict_marker_template_updated", expected_conflict_block in rb)
    except Exception as exc:
        record("runbook.read_and_check", False, repr(exc))

    passed_count = sum(1 for c in checks if c["passed"])
    return {
        "workspace": label,
        "passed": passed_count,
        "total": len(checks),
        "accuracy_pct": round(100.0 * passed_count / max(1, len(checks)), 2),
        "checks": checks,
    }


if __name__ == "__main__":
    wm_res = check_workspace(SUITE_DIR / "ws_waymark_extended", "ws_waymark_extended")
    sg_res = check_workspace(SUITE_DIR / "ws_ast_grep_rule", "ws_ast_grep_rule")
    print(json.dumps({"ws_waymark_extended": wm_res, "ws_ast_grep_rule": sg_res}, indent=2))
