"""Category B integration tests for patchdiff_observe_scope and server-issued scope observations."""

from __future__ import annotations

import json
import uuid

from app.core.hashing import canonical_sha256
from app.mcp import tools  # noqa: F401
from app.mcp.server import registry
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    TargetScopeObservations,
)


def test_observe_scope_candidate_discovery_and_exact_selection_python_json_markdown() -> None:
    py_content = (
        'FRAME_SYNC_STREAM = "stream-v1"\n'
        'VALID_SCOPES = ("alpha", "beta")\n'
        "\n"
        "def compute_budget(limit: int) -> int:\n"
        "    return limit * 2\n"
    )
    py_init = registry.call(
        "patchdiff_initialize_target",
        filename="config.py",
        content=py_content,
        content_type="text/x-python",
    )
    py_id = py_init["target_file_id"]

    # Mode 1: Candidate discovery (no symbol_name)
    cand_res = registry.call(
        "patchdiff_observe_scope",
        target_file_id=py_id,
        query="FRAME",
    )
    assert cand_res["status"] == "candidates"
    assert cand_res["observation_id"] is None
    assert cand_res["waymark_engine_version"] == "4.1.0"
    assert [c["name"] for c in cand_res["candidates"]] == ["FRAME_SYNC_STREAM"]

    # Mode 2: Exact unique symbol selection
    obs_res = registry.call(
        "patchdiff_observe_scope",
        target_file_id=py_id,
        symbol_name="FRAME_SYNC_STREAM",
        kind="variable",
    )
    assert obs_res["status"] == "observed"
    assert obs_res["observation_id"] is not None
    assert obs_res["target_version"] == 0
    assert obs_res["target_current_hash"] == py_init["current_hash"]
    assert obs_res["text"] == 'FRAME_SYNC_STREAM = "stream-v1"'
    assert obs_res["observed_scope_hash"] == canonical_sha256('FRAME_SYNC_STREAM = "stream-v1"')
    assert py_content[obs_res["scope_start"] : obs_res["scope_end"]] == 'FRAME_SYNC_STREAM = "stream-v1"'

    with SessionLocal() as session:
        obs_row = session.get(TargetScopeObservations, uuid.UUID(obs_res["observation_id"]))
        assert obs_row is not None
        assert str(obs_row.target_file_id) == py_id
        assert obs_row.target_version == 0
        assert obs_row.target_current_hash == py_init["current_hash"]
        assert obs_row.waymark_engine_version == "4.1.0"
        assert obs_row.symbol_name == "FRAME_SYNC_STREAM"
        assert obs_row.symbol_kind == "variable"
        assert obs_row.accepted_pdcp_log_id is None

        # Observing must never mutate target content, version, hash, logs, or ledger
        target = session.get(CloudTargetFiles, uuid.UUID(py_id))
        assert target.version == 0
        assert target.current_content == py_content
        assert session.query(AppendOnlyPdcpLogs).filter_by(target_file_id=target.target_file_id).count() == 0
        assert session.query(AppendOnlyManifestLedger).filter_by(target_file_id=target.target_file_id).count() == 0

    # JSON array-object selection
    json_content = json.dumps(
        {
            "tenants": [
                {"id": "ten_006", "quota": 100},
                {"id": "ten_013", "quota": 250},
                {"id": "ten_018", "quota": 500},
            ]
        },
        indent=2,
    ) + "\n"
    json_init = registry.call(
        "patchdiff_initialize_target",
        filename="tenants.json",
        content=json_content,
        content_type="application/json",
    )
    json_obs = registry.call(
        "patchdiff_observe_scope",
        target_file_id=json_init["target_file_id"],
        symbol_name="tenants[ten_013]",
        kind="object",
    )
    assert json_obs["status"] == "observed"
    assert '"id": "ten_013"' in json_obs["text"]
    assert '"quota": 250' in json_obs["text"]
    assert '"ten_006"' not in json_obs["text"]

    # Markdown table row & fenced code block selection
    md_content = (
        "# Deployment Checklist\n"
        "\n"
        "| Check ID | Owner | State |\n"
        "| --- | --- | --- |\n"
        "| CHK-14-C | SecOps | OPEN |\n"
        "\n"
        "```bash\n"
        "echo deploy\n"
        "```\n"
    )
    md_init = registry.call(
        "patchdiff_initialize_target",
        filename="checklist.md",
        content=md_content,
        content_type="text/markdown",
    )
    row_obs = registry.call(
        "patchdiff_observe_scope",
        target_file_id=md_init["target_file_id"],
        symbol_name="row:CHK-14-C",
        kind="table_row",
    )
    assert row_obs["status"] == "observed"
    assert row_obs["text"] == "| CHK-14-C | SecOps | OPEN |"

    fence_obs = registry.call(
        "patchdiff_observe_scope",
        target_file_id=md_init["target_file_id"],
        symbol_name="fence:L7",
        kind="code_block",
    )
    assert fence_obs["status"] == "observed"
    assert "echo deploy" in fence_obs["text"]


def test_observe_scope_fails_closed_on_missing_and_ambiguous_symbols() -> None:
    # Two classes each defining a method named `execute` -> ambiguous when selecting `execute`
    content = (
        "class AlphaWorker:\n"
        "    def execute(self) -> int:\n"
        "        return 1\n"
        "\n"
        "class BetaWorker:\n"
        "    def execute(self) -> int:\n"
        "        return 222222\n"
    )
    init = registry.call(
        "patchdiff_initialize_target",
        filename="workers.py",
        content=content,
        content_type="text/x-python",
    )
    target_id = init["target_file_id"]

    missing = registry.call(
        "patchdiff_observe_scope",
        target_file_id=target_id,
        symbol_name="nonexistent_symbol",
    )
    assert missing["status"] == "not_found"
    assert missing["code"] == "SCOPE_NOT_FOUND"
    assert missing["observation_id"] is None

    ambiguous = registry.call(
        "patchdiff_observe_scope",
        target_file_id=target_id,
        symbol_name="execute",
    )
    assert ambiguous["status"] == "ambiguous"
    assert ambiguous["code"] == "AMBIGUOUS_SCOPE_SELECTION"
    assert ambiguous["observation_id"] is None
    assert len(ambiguous["candidates"]) == 2


def test_observe_scope_pagination_and_continuation_via_observation_id() -> None:
    body_lines = [f"    step_{i} = {i}" for i in range(60)]
    content = "def long_workflow():\n" + "\n".join(body_lines) + "\n    return 0\n"
    init = registry.call(
        "patchdiff_initialize_target",
        filename="workflow.py",
        content=content,
        content_type="text/x-python",
    )
    target_id = init["target_file_id"]

    page1 = registry.call(
        "patchdiff_observe_scope",
        target_file_id=target_id,
        symbol_name="long_workflow",
        kind="function",
        offset=0,
        max_chars=120,
        include_line_starts=True,
    )
    assert page1["status"] == "observed"
    assert page1["truncated"] is True
    assert page1["next_offset"] == 120
    assert isinstance(page1["line_starts"], list) and len(page1["line_starts"]) >= 1
    obs_id = page1["observation_id"]

    # Reconstruct full scope across continuation pages using observation_id
    chunks = [page1["text"]]
    next_off = page1["next_offset"]
    while next_off is not None:
        page = registry.call(
            "patchdiff_observe_scope",
            target_file_id=target_id,
            observation_id=obs_id,
            offset=next_off,
            max_chars=200,
        )
        assert page["status"] == "observed"
        assert page["mode"] == "scope_page"
        assert page["observation_id"] == obs_id
        chunks.append(page["text"])
        next_off = page["next_offset"]

    reconstructed = "".join(chunks)
    assert reconstructed == content[page1["scope_start"] : page1["scope_end"]]
    assert canonical_sha256(reconstructed) == page1["observed_scope_hash"]


def test_blank_optional_selectors_are_read_only_admission_failures():
    from sqlalchemy import func, select

    target = registry.call("patchdiff_initialize_target", filename="selector-contract.py",
                           content="def example():\n    return 1\n", content_type="text/x-python")
    target_id = uuid.UUID(target["target_file_id"])
    def counts():
        with SessionLocal() as session:
            current = session.get(CloudTargetFiles, target_id)
            return (current.version, current.current_hash,
                    *[session.scalar(select(func.count()).select_from(model).where(model.target_file_id == target_id))
                      for model in (AppendOnlyPdcpLogs, AppendOnlyManifestLedger, TargetScopeObservations)])
    before = counts()
    for field in ("query", "symbol_name", "kind"):
        for value in ("", " ", "\t\n", "\u00a0", "\u3000"):
            result = registry.call("patchdiff_observe_scope", target_file_id=str(target_id), **{field: value})
            assert result["status"] == "invalid_argument"
            assert result["failure_detail"] == f"{field} must be a non-empty string when provided."
    assert counts() == before
    discovered = registry.call("patchdiff_observe_scope", target_file_id=str(target_id), query=None, kind=None, symbol_name=None)
    assert discovered["status"] == "candidates"
    observed = registry.call("patchdiff_observe_scope", target_file_id=str(target_id), symbol_name="example")
    assert observed["status"] == "observed"
