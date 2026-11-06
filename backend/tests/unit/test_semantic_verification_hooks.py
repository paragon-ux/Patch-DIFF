"""Unit tests for pre-commit semantic verification hooks and preview integration."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.hashing import canonical_sha256
from app.core.validity import NOT_EVALUATED, ValidationStage, validity_levels
from app.services.pdcp_service import preview
from app.services.verification_service import (
    run_verification_hooks,
    verify_json_syntax,
    verify_markdown_fences,
    verify_python_syntax,
)


def test_verify_python_syntax_valid():
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    res = verify_python_syntax(code)
    assert res["passed"] is True
    assert res["status"] == "passed"
    assert res["error"] is None
    assert isinstance(res["duration_ms"], float)


def test_verify_python_syntax_invalid():
    code = "def broken(\n    return 42\n"
    res = verify_python_syntax(code)
    assert res["passed"] is False
    assert res["status"] == "failed"
    assert res["error"] is not None
    assert "line" in res["error"]
    assert res["error"]["line"] in (1, 2)


def test_verify_json_syntax_valid():
    data = '{"name": "patchdiff", "features": ["preview", "verification"], "count": 42}'
    res = verify_json_syntax(data)
    assert res["passed"] is True
    assert res["status"] == "passed"
    assert res["error"] is None


def test_verify_json_syntax_invalid():
    data = '{"name": "patchdiff", "invalid": }'
    res = verify_json_syntax(data)
    assert res["passed"] is False
    assert res["status"] == "failed"
    assert res["error"] is not None
    assert res["error"]["line"] == 1


def test_verify_markdown_fences_balanced():
    doc = (
        "# Title\n\n"
        "Here is a code block:\n"
        "```python\n"
        "print('hello')\n"
        "```\n\n"
        "And tildes:\n"
        "~~~json\n"
        '{"a": 1}\n'
        "~~~\n"
    )
    res = verify_markdown_fences(doc)
    assert res["passed"] is True
    assert res["status"] == "passed"
    assert res["error"] is None


def test_verify_markdown_fences_unclosed():
    doc = (
        "# Header\n\n"
        "```python\n"
        "x = 1\n"
    )
    res = verify_markdown_fences(doc)
    assert res["passed"] is False
    assert res["status"] == "failed"
    assert res["error"] is not None
    assert res["error"]["line"] == 3


def test_run_verification_hooks_inferred_python():
    code = "x = 1 + 2\n"
    res = run_verification_hooks(code, target_type="text/x-python", verify_syntax=True)
    assert res["passed"] is True
    assert len(res["checks"]) == 1
    assert res["checks"][0]["hook"] == "python_syntax"


def test_run_verification_hooks_unknown_hook():
    res = run_verification_hooks("print(1)", hooks=["nonexistent_linter"])
    assert res["passed"] is False
    assert res["status"] == "failed"
    assert len(res["errors"]) == 1
    assert "Unknown verification hook" in res["errors"][0]["message"]


def test_validity_levels_with_semantic_flag():
    val_true = validity_levels("accepted", stage=ValidationStage.ACCEPTED, semantic=True)
    assert val_true["protocol_valid"] is True
    assert val_true["transaction_valid"] is True
    assert val_true["task_correct"] == NOT_EVALUATED
    assert val_true["semantic"] is True

    val_false = validity_levels("accepted", stage=ValidationStage.ACCEPTED, semantic=False)
    assert val_false["semantic"] is False

    val_default = validity_levels("accepted", stage=ValidationStage.ACCEPTED)
    assert val_default["semantic"] == NOT_EVALUATED


def _mock_session_and_target(target_type="text/x-python", content="def foo():\n    return 1\n", filename="main.py"):
    target_id = "11111111-1111-1111-1111-111111111111"
    target_uuid = uuid.UUID(target_id)
    observation = SimpleNamespace(
        target_file_id=target_uuid,
        target_type=target_type,
        current_content=content,
        current_version=0,
        current_hash=canonical_sha256(content),
        filename=filename,
    )
    session = MagicMock()
    session.identity_map.get.return_value = None
    session.identity_key.return_value = ("CloudTargetFiles", target_uuid)
    session.dirty = set()
    session.deleted = set()
    session.new = set()
    return session, observation, target_id


@patch("app.services.read_service.observe_target")
def test_preview_verify_syntax_python_pass(mock_observe):
    session, obs, target_id = _mock_session_and_target(
        target_type="text/x-python",
        content="def calculate(x: int) -> int:\n    return x * 2\n",
        filename="calc.py",
    )
    mock_observe.return_value = obs

    proposal = {
        "format": "patchdiff-tx/3",
        "intent": "update function body",
        "expected_target_version": 0,
        "replacement": "def calculate(x: int) -> int:\n    return x * 3\n",
        "verify_syntax": True,
    }

    result = preview(session, target_file_id=target_id, **proposal)
    assert result["status"] == "accepted"
    assert result["validity"]["protocol_valid"] is True
    assert result["validity"]["transaction_valid"] is True
    assert result["validity"]["semantic"] is True
    assert "verification" in result
    assert result["verification"]["status"] == "passed"
    assert result["verification"]["passed"] is True
    assert len(result["verification"]["checks"]) == 1
    assert result["verification"]["checks"][0]["hook"] == "python_syntax"


@patch("app.services.read_service.observe_target")
def test_preview_verify_syntax_python_fail(mock_observe):
    session, obs, target_id = _mock_session_and_target(
        target_type="text/x-python",
        content="def calculate(x: int) -> int:\n    return x * 2\n",
        filename="calc.py",
    )
    mock_observe.return_value = obs

    proposal = {
        "format": "patchdiff-tx/3",
        "intent": "introduce syntax error",
        "expected_target_version": 0,
        "replacement": "def calculate(x: int) -> int:\n    return (x *\n",
        "verify_syntax": True,
    }

    result = preview(session, target_file_id=target_id, **proposal)
    # The transaction itself is accepted as a valid document transformation
    assert result["status"] == "accepted"
    assert result["validity"]["protocol_valid"] is True
    assert result["validity"]["transaction_valid"] is True
    # But semantic validity is False due to syntax error
    assert result["validity"]["semantic"] is False
    assert "verification" in result
    assert result["verification"]["status"] == "failed"
    assert result["verification"]["passed"] is False
    assert len(result["verification"]["errors"]) >= 1


@patch("app.services.read_service.observe_target")
def test_preview_verify_syntax_default_not_evaluated(mock_observe):
    session, obs, target_id = _mock_session_and_target()
    mock_observe.return_value = obs

    proposal = {
        "format": "patchdiff-tx/3",
        "intent": "plain replacement without verification",
        "expected_target_version": 0,
        "replacement": "def foo():\n    return 2\n",
    }

    result = preview(session, target_file_id=target_id, **proposal)
    assert result["status"] == "accepted"
    assert result["validity"]["semantic"] == "not_evaluated"
    assert "verification" not in result


@patch("app.services.read_service.observe_target")
def test_preview_invalid_parameter_types(mock_observe):
    session, obs, target_id = _mock_session_and_target()
    mock_observe.return_value = obs

    # verify_syntax not a boolean
    result = preview(
        session,
        target_file_id=target_id,
        format="patchdiff-tx/3",
        intent="test",
        expected_target_version=0,
        replacement="content",
        verify_syntax="yes",
    )
    assert result["status"] == "invalid_argument"
    assert result["code"] == "invalid_parameter"

    # verification_hooks not a list of strings
    result2 = preview(
        session,
        target_file_id=target_id,
        format="patchdiff-tx/3",
        intent="test",
        expected_target_version=0,
        replacement="content",
        verification_hooks="python_syntax",
    )
    assert result2["status"] == "invalid_argument"
    assert result2["code"] == "invalid_parameter"


@patch("app.services.read_service.observe_target")
def test_preview_verify_syntax_json_pass_and_fail(mock_observe):
    session, obs, target_id = _mock_session_and_target(
        target_type="application/json",
        content='{"key": 1}\n',
        filename="config.json",
    )
    mock_observe.return_value = obs

    # Valid JSON
    res_pass = preview(
        session,
        target_file_id=target_id,
        format="patchdiff-tx/3",
        intent="valid json",
        expected_target_version=0,
        replacement='{"key": 2}\n',
        verify_syntax=True,
    )
    assert res_pass["status"] == "accepted"
    assert res_pass["validity"]["semantic"] is True
    assert res_pass["verification"]["passed"] is True
    assert res_pass["verification"]["checks"][0]["hook"] == "json_syntax"

    # Invalid JSON
    res_fail = preview(
        session,
        target_file_id=target_id,
        format="patchdiff-tx/3",
        intent="invalid json",
        expected_target_version=0,
        replacement='{"key": }\n',
        verify_syntax=True,
    )
    assert res_fail["status"] == "accepted"
    assert res_fail["validity"]["semantic"] is False
    assert res_fail["verification"]["passed"] is False


@patch("app.services.read_service.observe_target")
def test_preview_explicit_verification_hooks(mock_observe):
    session, obs, target_id = _mock_session_and_target(
        target_type="text/markdown",
        content="# Intro\n",
        filename="README.md",
    )
    mock_observe.return_value = obs

    # Unclosed code fence with explicit markdown_fences hook
    res = preview(
        session,
        target_file_id=target_id,
        format="patchdiff-tx/3",
        intent="unclosed fence",
        expected_target_version=0,
        replacement="# Intro\n\n```python\nx = 1\n",
        verification_hooks=["markdown_fences"],
    )
    assert res["status"] == "accepted"
    assert res["validity"]["semantic"] is False
    assert res["verification"]["passed"] is False
    assert res["verification"]["checks"][0]["hook"] == "markdown_fences"


@patch("app.services.read_service.observe_target")
@patch("app.mcp.tools.SessionLocal")
def test_patchdiff_preview_mcp_tool_delegation(mock_session_local, mock_observe):
    from app.mcp.tools import patchdiff_preview

    session, obs, target_id = _mock_session_and_target(
        target_type="text/x-python",
        content="val = 10\n",
        filename="settings.py",
    )
    mock_session_local.return_value.__enter__.return_value = session
    mock_observe.return_value = obs

    res = patchdiff_preview(
        target_file_id=target_id,
        format="patchdiff-tx/3",
        intent="mcp tool test",
        expected_target_version=0,
        replacement="val = 20\n",
        verify_syntax=True,
    )
    assert res["status"] == "accepted"
    assert res["validity"]["semantic"] is True
    assert res["verification"]["passed"] is True

