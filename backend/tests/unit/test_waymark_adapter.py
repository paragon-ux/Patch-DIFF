"""Category A & B unit tests for the pinned Waymark Engine npm adapter and coordinate conversion."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.scope_observation_service import (
    ScopeCoordinateConversionError,
    utf16_column_to_code_point_offset,
    waymark_span_to_code_point_offsets,
)
from app.services.waymark_adapter import (
    EXPECTED_WAYMARK_ENGINE_VERSION,
    WAYMARK_DISCOVER_SCRIPT,
    WAYMARK_INTEGRATION_DIR,
    discover_symbols_from_content,
)


def test_waymark_package_manifest_and_lockfile_pin_exact_npm_release() -> None:
    package_json_path = WAYMARK_INTEGRATION_DIR / "package.json"
    lockfile_path = WAYMARK_INTEGRATION_DIR / "package-lock.json"
    assert package_json_path.is_file()
    assert lockfile_path.is_file()
    assert WAYMARK_DISCOVER_SCRIPT.is_file()

    pkg = json.loads(package_json_path.read_text(encoding="utf-8"))
    deps = pkg.get("dependencies", {})
    pinned = deps.get("waymark-engine")
    assert pinned == EXPECTED_WAYMARK_ENGINE_VERSION == "4.1.0"
    for forbidden in ("^", "~", "*", ">", "<", "latest", "file:", "github:", "git+"):
        assert forbidden not in pinned

    lock = json.loads(lockfile_path.read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    wm_entry = packages.get("node_modules/waymark-engine")
    assert wm_entry is not None
    assert wm_entry["version"] == "4.1.0"
    assert wm_entry["resolved"] == "https://registry.npmjs.org/waymark-engine/-/waymark-engine-4.1.0.tgz"
    assert wm_entry["integrity"].startswith("sha512-")


def test_python_discovery_exposes_module_assignments_classes_functions_and_methods() -> None:
    content = (
        'FRAME_SYNC_STREAM = "v1"\n'
        'VALID_SCOPES: tuple[str, ...] = ("read", "write")\n'
        "\n"
        "class StreamWorker:\n"
        "    CLASS_ATTR = 42\n"
        "    def process(self) -> str:\n"
        "        local_var = 99\n"
        "        return FRAME_SYNC_STREAM\n"
        "\n"
        "def helper() -> int:\n"
        "    inner = 1\n"
        "    return inner\n"
    )
    res = discover_symbols_from_content(filename="worker.py", content=content)
    assert res.ok is True
    assert res.language == "python"
    assert res.waymark_engine_version == "4.1.0"

    by_name = {(s.name, s.kind, s.parent): s for s in res.symbols}
    assert ("FRAME_SYNC_STREAM", "variable", None) in by_name
    assert ("VALID_SCOPES", "variable", None) in by_name
    assert ("StreamWorker", "class", None) in by_name
    assert ("process", "method", None) in by_name
    assert ("helper", "function", None) in by_name

    # Local variables and class attributes must not leak as module-level variables
    names = {s.name for s in res.symbols}
    assert "local_var" not in names
    assert "inner" not in names
    assert "CLASS_ATTR" not in names


def test_json_discovery_array_objects_escaped_paths_and_fail_closed_limits() -> None:
    doc = {
        "tenants": [
            {"id": "ten_006", "tier": "standard"},
            {"id": "ten_013", "tier": "enterprise"},
            {"id": "ten_018", "tier": "starter"},
        ],
        "a": {"b": [{"id": "x", "v": 1}]},
        "a.b": [{"id": "x", "v": 2}],
    }
    res = discover_symbols_from_content(filename="tenants.json", content=json.dumps(doc, indent=2))
    assert res.ok is True
    assert res.language == "json"
    names = {s.name for s in res.symbols}
    assert "tenants[ten_006]" in names
    assert "tenants[ten_013]" in names
    assert "tenants[ten_018]" in names
    assert "a.b[x]" in names
    assert r"a\.b[x]" in names


def test_json_duplicate_key_fails_closed_with_ambiguous_symbol_identity() -> None:
    raw_dup_json = '{"alpha": 1, "alpha": 2}\n'
    res = discover_symbols_from_content(filename="dup.json", content=raw_dup_json)
    assert res.ok is False
    assert res.error is not None
    assert res.error.code == "AMBIGUOUS_SYMBOL_IDENTITY"


def test_json_array_exceeding_500_items_fails_closed_with_outline_limit_exceeded() -> None:
    items = [{"id": f"item_{i}"} for i in range(501)]
    res = discover_symbols_from_content(filename="big.json", content=json.dumps({"items": items}))
    assert res.ok is False
    assert res.error is not None
    assert res.error.code == "OUTLINE_LIMIT_EXCEEDED"


def test_markdown_discovery_headings_table_rows_and_fenced_blocks() -> None:
    md = (
        "# Runbook\n"
        "\n"
        "| Check ID | Status |\n"
        "| --- | --- |\n"
        "| CHK-14-C | PENDING |\n"
        "\n"
        "```yaml\n"
        "timeout: 30\n"
        "```\n"
    )
    res = discover_symbols_from_content(filename="runbook.md", content=md)
    assert res.ok is True
    assert res.language == "markdown"
    by_kind = {(s.name, s.kind) for s in res.symbols}
    assert ("# Runbook", "section") in by_kind
    assert ("row:CHK-14-C", "table_row") in by_kind
    assert ("fence:L7", "code_block") in by_kind


def test_unsupported_language_and_syntax_error_preserve_waymark_error_codes() -> None:
    unsupported = discover_symbols_from_content(filename="notes.txt", content="plain text\n")
    assert unsupported.ok is False
    assert unsupported.error is not None
    assert unsupported.error.code == "UNSUPPORTED_LANGUAGE"

    bad_json = discover_symbols_from_content(filename="broken.json", content='{"unclosed": [1, 2}\n')
    assert bad_json.ok is False
    assert bad_json.error is not None
    assert bad_json.error.code == "PARSE_ERROR"


def test_temp_directory_is_cleaned_up_after_normal_and_error_runs() -> None:
    tmp_root = Path(tempfile.gettempdir())
    before = {p.name for p in tmp_root.glob("patchdiff-waymark-*")}

    ok_res = discover_symbols_from_content(filename="clean.py", content="X = 1\n")
    assert ok_res.ok is True

    err_res = discover_symbols_from_content(filename="broken.json", content="{bad")
    assert err_res.ok is False

    after = {p.name for p in tmp_root.glob("patchdiff-waymark-*")}
    assert after - before == set()


def test_adapter_handles_timeout_nonzero_exit_and_invalid_json() -> None:
    with patch(
        "app.services.waymark_adapter._run_bounded_discovery",
        side_effect=subprocess.TimeoutExpired(cmd=["node"], timeout=0.1),
    ):
        timeout_res = discover_symbols_from_content(filename="slow.py", content="X = 1\n", timeout_seconds=0.1)
        assert timeout_res.ok is False
        assert timeout_res.error is not None
        assert timeout_res.error.code == "WAYMARK_TIMEOUT"

    completed_bad_json = subprocess.CompletedProcess(args=["node"], returncode=0, stdout=b"not-json", stderr=b"")
    with patch("app.services.waymark_adapter._run_bounded_discovery", return_value=completed_bad_json):
        bad_json_res = discover_symbols_from_content(filename="bad.py", content="X = 1\n")
        assert bad_json_res.ok is False
        assert bad_json_res.error is not None
        assert bad_json_res.error.code == "WAYMARK_INVALID_OUTPUT"

    completed_nonzero = subprocess.CompletedProcess(args=["node"], returncode=2, stdout=b"", stderr=b"boom")
    with patch("app.services.waymark_adapter._run_bounded_discovery", return_value=completed_nonzero):
        nonzero_res = discover_symbols_from_content(filename="crash.py", content="X = 1\n")
        assert nonzero_res.ok is False
        assert nonzero_res.error is not None
        assert nonzero_res.error.code == "WAYMARK_PROCESS_ERROR"


def test_utf16_column_to_code_point_offset_handles_ascii_bmp_and_astral_surrogates() -> None:
    # '🚀' is 1 Unicode code point in Python str, but 2 UTF-16 code units (4 bytes in UTF-16LE).
    line = 'PREFIX = "🚀_ok"'
    assert utf16_column_to_code_point_offset(line, 0) == 0
    assert utf16_column_to_code_point_offset(line, 10) == 10  # right before 🚀
    # After 🚀 (UTF-16 column 12), Python code point offset is 11
    assert utf16_column_to_code_point_offset(line, 12) == 11
    assert utf16_column_to_code_point_offset(line, len(line.encode("utf-16-le")) // 2) == len(line)

    # Splitting a surrogate pair (UTF-16 column 11) or out-of-bounds must fail closed
    with pytest.raises(ScopeCoordinateConversionError):
        utf16_column_to_code_point_offset(line, 11)
    with pytest.raises(ScopeCoordinateConversionError):
        utf16_column_to_code_point_offset(line, 999)

    content = f"# header\n{line}\nFOOTER = 1\n"
    res = discover_symbols_from_content(filename="emoji.py", content=content)
    assert res.ok is True
    sym = next(s for s in res.symbols if s.name == "PREFIX")
    start, end = waymark_span_to_code_point_offsets(content, sym.start, sym.end)
    assert content[start:end] == line
