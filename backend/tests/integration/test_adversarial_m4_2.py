"""Adversarial stress tests for Milestone M4 (Challenger M4-2).

Verifies:
1. Benchmark metric integrity (PR23-R3-DOC-002):
   - lock_wait_ms, lock_hold_ms, replay_ms are non-null, positive, and numerically distinct.
   - Under uncontended execution, lock_wait_ms is small (~2-6 ms) while lock_hold_ms is larger and scales with edits.
   - Replay verification duration scales with active cycle edit count.
   - Idempotent finalization recovery returns persisted checks and valid timing fields.
2. MCP Schema and Registry Parity:
   - registry.names() contains exactly 24 tools.
   - MCP_PROFILES["full"] contains exactly 24 tools.
   - registry.names() set equals MCP_PROFILES["full"].
   - patchdiff_read_finalized_export is in full and NOT in observed_v2 or any editing profile.
   - Attempting to call patchdiff_read_finalized_export or patchdiff_finalize_target on observed_v2 fails closed.
3. Host Finalize Guide and Contract Alignment:
   - examples/host_finalize.py signatures and error classes match HOST_INTEGRATION_GUIDE.md and MCP_TOOLS.md.
   - safe_write_back_file and finalize_single_target keyword-only arguments and defaults are exact.
   - Error classes HostWriteBackError, PreimageMismatchError, PathEscapeError match hierarchy.
4. Benchmark CLI & Distribution Structure:
   - benchmark_finalize_replay.run_benchmark returns well-formed distribution dictionaries with min/max ranges.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import statistics
import uuid

import pytest

from app.mcp.external_adapter import ExternalMCPAdapter, MCP_PROFILES, EXPECTED_TOOL_NAMES
from app.mcp.tools import registry
from app.services.finalize_service import finalize_target
from app.services.target_service import initialize_target
from app.services.pdcp_service import submit_edits
from app.storage.db import SessionLocal
import examples.host_finalize as host_finalize


def test_mcp_registry_and_profile_parity_adversarial():
    """Adversarially verify tool counts, profile containment, and unauthorized access rejection."""
    # 1. Parity checks
    names = registry.names()
    assert len(names) == 24, f"Expected exactly 24 tools in registry.names(), got {len(names)}: {names}"
    assert len(EXPECTED_TOOL_NAMES) == 24, f"Expected 24 in EXPECTED_TOOL_NAMES, got {len(EXPECTED_TOOL_NAMES)}"
    assert len(MCP_PROFILES["full"]) == 24, f"Expected 24 in MCP_PROFILES['full'], got {len(MCP_PROFILES['full'])}"
    assert set(names) == MCP_PROFILES["full"], "Registry names and full profile set must be identical"

    # 2. Finalization and export tool isolation
    restricted_profiles = [
        "observed_v2",
        "editor",
        "unobserved",
        "unobserved_editor",
        "hybrid_editor",
        "observed",
        "observed_editor",
    ]
    for profile in restricted_profiles:
        profile_tools = MCP_PROFILES[profile]
        assert "patchdiff_read_finalized_export" not in profile_tools, (
            f"Security violation: patchdiff_read_finalized_export exposed in {profile}"
        )
        assert "patchdiff_finalize_target" not in profile_tools, (
            f"Security violation: patchdiff_finalize_target exposed in {profile}"
        )

    # 3. Adversarial call attempts on observed_v2 adapter
    adapter_v2 = ExternalMCPAdapter(profile="observed_v2")
    tools_v2 = adapter_v2.list_tools()
    tool_names_v2 = [t["name"] for t in tools_v2]
    assert len(tool_names_v2) == 5, f"Expected 5 tools in observed_v2, got {len(tool_names_v2)}"
    assert "patchdiff_read_finalized_export" not in tool_names_v2
    assert "patchdiff_finalize_target" not in tool_names_v2

    # Direct call_tool rejection
    call_res = adapter_v2.call_tool("patchdiff_read_finalized_export", {
        "finalization_id": str(uuid.uuid4()),
        "target_file_id": str(uuid.uuid4()),
    })
    assert call_res.get("isError") is True
    assert "Unknown PatchDIFF MCP tool" in call_res["content"][0]["text"]

    call_fin = adapter_v2.call_tool("patchdiff_finalize_target", {
        "target_file_id": str(uuid.uuid4()),
        "client_request_id": "test-fin",
    })
    assert call_fin.get("isError") is True
    assert "Unknown PatchDIFF MCP tool" in call_fin["content"][0]["text"]

    # JSON-RPC request rejection
    rpc_req = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {
            "name": "patchdiff_read_finalized_export",
            "arguments": {
                "finalization_id": str(uuid.uuid4()),
                "target_file_id": str(uuid.uuid4()),
            },
        },
    }
    rpc_res = adapter_v2.handle_request(rpc_req)
    assert rpc_res is not None
    assert rpc_res["result"].get("isError") is True
    assert "Unknown PatchDIFF MCP tool" in rpc_res["result"]["content"][0]["text"]

    # 4. Verify full adapter advertises all 24 tools
    adapter_full = ExternalMCPAdapter(profile="full")
    tools_full = adapter_full.list_tools()
    assert len(tools_full) == 24
    tool_names_full = {t["name"] for t in tools_full}
    assert "patchdiff_read_finalized_export" in tool_names_full
    assert "patchdiff_finalize_target" in tool_names_full


def test_host_finalize_documentation_and_contract_parity():
    """Verify that examples/host_finalize.py strictly adheres to the documented contracts."""
    # 1. Error hierarchy
    assert issubclass(host_finalize.HostWriteBackError, Exception)
    assert issubclass(host_finalize.PreimageMismatchError, host_finalize.HostWriteBackError)
    assert issubclass(host_finalize.PathEscapeError, host_finalize.HostWriteBackError)

    # 2. safe_write_back_file signature
    sig_swb = inspect.signature(host_finalize.safe_write_back_file)
    swb_params = list(sig_swb.parameters.values())

    assert swb_params[0].name == "destination_path"
    assert swb_params[1].name == "data"

    kw_only = {p.name: p for p in swb_params[2:]}
    assert "expected_sha256" in kw_only
    assert kw_only["expected_sha256"].default is inspect.Parameter.empty  # mandatory kwarg
    assert "preimage_sha256" in kw_only
    assert kw_only["preimage_sha256"].default is None
    assert "authorized_root" in kw_only
    assert kw_only["authorized_root"].default is None
    assert "allow_unconditional_overwrite" in kw_only
    assert kw_only["allow_unconditional_overwrite"].default is False

    # 3. finalize_single_target signature
    sig_fst = inspect.signature(host_finalize.finalize_single_target)
    fst_params = list(sig_fst.parameters.values())

    assert fst_params[0].name == "call_tool"
    fst_kw = {p.name: p for p in fst_params[1:]}

    assert "target_file_id" in fst_kw
    assert fst_kw["target_file_id"].default is inspect.Parameter.empty
    assert "client_request_id" in fst_kw
    assert fst_kw["client_request_id"].default is inspect.Parameter.empty
    assert "expected_target_version" in fst_kw
    assert fst_kw["expected_target_version"].default is None
    assert "expected_current_hash" in fst_kw
    assert fst_kw["expected_current_hash"].default is None
    assert "format" in fst_kw
    assert fst_kw["format"].default == "original_eol"
    assert "destination_path" in fst_kw
    assert fst_kw["destination_path"].default is None
    assert "preimage_sha256" in fst_kw
    assert fst_kw["preimage_sha256"].default is None
    assert "authorized_root" in fst_kw
    assert fst_kw["authorized_root"].default is None
    assert "allow_unconditional_overwrite" in fst_kw
    assert fst_kw["allow_unconditional_overwrite"].default is False
    assert "raise_on_disk_error" in fst_kw
    assert fst_kw["raise_on_disk_error"].default is False

    # 4. Text alignment in HOST_INTEGRATION_GUIDE.md and MCP_TOOLS.md
    guide_path = Path("docs/guides/HOST_INTEGRATION_GUIDE.md")
    assert guide_path.is_file()
    guide_text = guide_path.read_text(encoding="utf-8")

    assert "safe_write_back_file" in guide_text
    assert "finalize_single_target" in guide_text
    assert "HostWriteBackError" in guide_text
    assert "PreimageMismatchError" in guide_text
    assert "PathEscapeError" in guide_text
    assert "PR23-R3-SCRIPT-001" in guide_text
    assert "PR23-R3-SCRIPT-002" in guide_text
    assert "PR23-R3-SCRIPT-003" in guide_text
    assert "PR23-R3-SCRIPT-004" in guide_text
    assert "PR23-R3-SCRIPT-005" in guide_text
    assert "patchdiff_read_finalized_export" in guide_text

    tools_spec_path = Path("docs/spec/MCP_TOOLS.md")
    assert tools_spec_path.is_file()
    tools_spec_text = tools_spec_path.read_text(encoding="utf-8")
    assert "patchdiff_read_finalized_export" in tools_spec_text
    assert "lock_wait_ms" in tools_spec_text
    assert "lock_hold_ms" in tools_spec_text
    assert "replay_ms" in tools_spec_text


def test_benchmark_metrics_live_scaling_and_decoupling():
    """Adversarially verify decoupled timing fields and positive scaling against live PostgreSQL."""
    session = SessionLocal()
    try:
        # Warmup to stabilize JIT / connection pool
        warm_target = initialize_target(
            session=session,
            filename=f"warmup_{uuid.uuid4().hex[:8]}.py",
            content="x = 1\n",
            target_type="python",
        )
        finalize_target(
            session=session,
            target_file_id=warm_target.target_file_id,
            client_request_id=f"warm-{uuid.uuid4()}",
            expected_target_version=warm_target.version,
        )

        tiers = [0, 25]
        metrics_by_tier = {}

        for edit_count in tiers:
            # Initialize target
            initial_lines = [f"item_{i:03d} = {i}" for i in range(50)]
            initial_text = "\n".join(initial_lines) + "\n"
            target = initialize_target(
                session=session,
                filename=f"bench_test_{edit_count}_{uuid.uuid4().hex[:8]}.py",
                content=initial_text,
                target_type="python",
            )
            target_id = target.target_file_id
            cur_version = target.version

            # Apply edits sequentially if requested
            for e_idx in range(edit_count):
                old_val = f"item_{e_idx:03d} = {e_idx}"
                new_val = f"item_{e_idx:03d} = {e_idx * 100}"
                sub_res = submit_edits(
                    session=session,
                    target_file_id=target_id,
                    intent=f"Edit {e_idx}",
                    edits=[{"match": old_val, "replace": new_val}],
                    expected_target_version=cur_version,
                )
                assert sub_res.status == "accepted", f"Failed edit {e_idx}: {sub_res}"
                cur_version = sub_res.after_version

            # Finalize target
            fin_client_req = f"req-{target_id}-1"
            fin_res = finalize_target(
                session=session,
                target_file_id=target_id,
                client_request_id=fin_client_req,
                expected_target_version=cur_version,
            )

            assert fin_res.status == "ok", fin_res

            # Assert metric non-null, positive, and numerically distinct
            assert fin_res.lock_wait_ms is not None, "lock_wait_ms must not be None"
            assert fin_res.lock_hold_ms is not None, "lock_hold_ms must not be None"
            assert fin_res.replay_ms is not None, "replay_ms must not be None"

            wait_ms = fin_res.lock_wait_ms
            hold_ms = fin_res.lock_hold_ms
            replay_ms = fin_res.replay_ms

            assert wait_ms > 0.0, f"lock_wait_ms must be positive, got {wait_ms}"
            assert hold_ms > 0.0, f"lock_hold_ms must be positive, got {hold_ms}"
            assert replay_ms > 0.0, f"replay_ms must be positive, got {replay_ms}"

            # Under uncontended conditions, lock_wait_ms is small
            assert wait_ms < 30.0, f"Uncontended lock_wait_ms surprisingly high: {wait_ms} ms"

            # Lock hold must encapsulate replay duration
            assert hold_ms >= replay_ms, f"Lock hold ({hold_ms}) must encapsulate replay ({replay_ms})"

            # All 3 metrics must be numerically distinct
            assert len({wait_ms, hold_ms, replay_ms}) == 3, (
                f"Metrics must be numerically distinct: wait={wait_ms}, hold={hold_ms}, replay={replay_ms}"
            )

            # Check idempotent retry retains original checks and non-null lock timing
            fin_retry = finalize_target(
                session=session,
                target_file_id=target_id,
                client_request_id=fin_client_req,
                expected_target_version=cur_version,
            )
            assert fin_retry.status == "ok"
            assert fin_retry.is_idempotent_replay is True
            assert fin_retry.lock_wait_ms is not None
            assert fin_retry.lock_hold_ms is not None
            assert fin_retry.replay_ms is None  # Replay is bypassed on idempotent receipt recovery
            assert fin_retry.materialized_state_checks == fin_res.materialized_state_checks

            metrics_by_tier[edit_count] = {
                "wait_ms": wait_ms,
                "hold_ms": hold_ms,
                "replay_ms": replay_ms,
            }

        # Compare scaling between 0 edits and 25 edits
        m0 = metrics_by_tier[0]
        m25 = metrics_by_tier[25]
        # Replay at 25 edits must take longer than at 0 edits
        assert m25["replay_ms"] > m0["replay_ms"], (
            f"Replay scaling failure: 25 edits took {m25['replay_ms']} ms, but 0 edits took {m0['replay_ms']} ms"
        )
    finally:
        session.close()


def test_benchmark_script_module_execution():
    """Verify backend/tests/verification/benchmark_finalize_replay.py execution and output structure."""
    import backend.tests.verification.benchmark_finalize_replay as bench_mod

    results = bench_mod.run_benchmark(trials_per_tier=2, edit_counts=(0, 5))
    assert 0 in results
    assert 5 in results

    for edit_count in (0, 5):
        entry = results[edit_count]
        assert entry["trials"] == 2
        assert entry["mean_lock_wait_ms"] > 0
        assert entry["mean_lock_hold_ms"] > 0
        assert entry["mean_replay_ms"] > 0
        assert entry["mean_total_ms"] > 0
        assert entry["range_lock_wait_ms"][0] <= entry["range_lock_wait_ms"][1]
        assert entry["range_lock_hold_ms"][0] <= entry["range_lock_hold_ms"][1]
        assert entry["range_replay_ms"][0] <= entry["range_replay_ms"][1]
        assert entry["range_total_ms"][0] <= entry["range_total_ms"][1]


def test_read_finalized_export_adversarial_edge_cases():
    """Adversarially test patchdiff_read_finalized_export contract validations and fail-closed security boundaries."""
    from app.services.export_service import read_finalized_export

    session = SessionLocal()
    try:
        # Create canonical target and finalize
        content = "Line 1\nLine 2\nLine 3\n"
        target = initialize_target(
            session=session,
            filename=f"export_edge_{uuid.uuid4().hex[:8]}.txt",
            content=content,
            target_type="text/plain",
        )
        target_id = target.target_file_id

        fin_res = finalize_target(
            session=session,
            target_file_id=target_id,
            client_request_id=f"fin-{uuid.uuid4()}",
            expected_target_version=target.version,
        )
        assert fin_res.status == "ok"
        finalization_id = fin_res.finalization_id

        # 1. Non-UUID finalization_id
        res_bad_fid = read_finalized_export(session, finalization_id="not-a-uuid", target_file_id=target_id)
        assert res_bad_fid["status"] == "invalid_argument"
        assert "not a valid UUID" in res_bad_fid["failure_detail"]

        # 2. Non-UUID target_file_id
        res_bad_tid = read_finalized_export(session, finalization_id=finalization_id, target_file_id="bad-uuid")
        assert res_bad_tid["status"] == "invalid_argument"
        assert "not a valid UUID" in res_bad_tid["failure_detail"]

        # 3. Boolean offset
        res_bool_off = read_finalized_export(session, finalization_id=finalization_id, target_file_id=target_id, offset=True)
        assert res_bool_off["status"] == "invalid_argument"
        assert res_bool_off["code"] == "invalid_offset"

        # 4. Negative offset
        res_neg_off = read_finalized_export(session, finalization_id=finalization_id, target_file_id=target_id, offset=-5)
        assert res_neg_off["status"] == "invalid_argument"
        assert res_neg_off["code"] == "invalid_offset"

        # 5. Non-positive or boolean limit
        res_bool_lim = read_finalized_export(session, finalization_id=finalization_id, target_file_id=target_id, limit=False)
        assert res_bool_lim["status"] == "invalid_argument"
        assert res_bool_lim["code"] == "invalid_limit"

        res_zero_lim = read_finalized_export(session, finalization_id=finalization_id, target_file_id=target_id, limit=0)
        assert res_zero_lim["status"] == "invalid_argument"
        assert res_zero_lim["code"] == "invalid_limit"

        # 6. Target mismatch (unauthorized cross-target access attempt)
        other_target = initialize_target(
            session=session,
            filename=f"other_{uuid.uuid4().hex[:8]}.txt",
            content="Other\n",
            target_type="text/plain",
        )
        res_mismatch = read_finalized_export(
            session,
            finalization_id=finalization_id,
            target_file_id=other_target.target_file_id,
        )
        assert res_mismatch["status"] == "not_found"
        assert res_mismatch["error"] == "finalization_not_found"

        # 7. Out-of-bounds offset
        res_oob = read_finalized_export(
            session,
            finalization_id=finalization_id,
            target_file_id=target_id,
            offset=999999,
        )
        assert res_oob["status"] == "invalid_argument"
        assert res_oob["code"] == "invalid_range"

        # 8. Valid retrieval
        res_valid = read_finalized_export(
            session,
            finalization_id=finalization_id,
            target_file_id=target_id,
            offset=0,
            limit=10,
        )
        assert res_valid["status"] == "ok"
        assert res_valid["bytes_read"] == 10
        assert res_valid["has_more"] is True
        assert res_valid["next_offset"] == 10
    finally:
        session.close()
