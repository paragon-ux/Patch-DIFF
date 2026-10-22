import json

import pytest
from jsonschema import Draft202012Validator

from app.mcp.external_adapter import ExternalMCPAdapter, TOOL_EXAMPLES
from app.services.read_service import line_slice
from app.mcp.tools import _submit_result_to_payload
from app.services.pdcp_service import SubmitPDCPResult
import uuid


@pytest.mark.parametrize("content,start,end,text,lines,begin,stop", [
    ("", 1, None, "", 1, 0, 0),
    ("a\n", 2, 2, "", 2, 2, 2),
    ("a\nb\nc", 2, 2, "b\n", 3, 2, 4),
    ("🌟\n中\n", 1, 2, "🌟\n中\n", 3, 0, 4),
    ("a\rb\u2028c\u0085d", 1, 1, "a\rb\u2028c\u0085d", 1, 0, 7),
])
def test_lf_ranges_and_exact_codepoint_coordinates(content, start, end, text, lines, begin, stop):
    result = line_slice(content, start_line=start, end_line=end)
    assert result["text"] == text
    assert (result["total_lines"], result["range_start"], result["range_end"]) == (lines, begin, stop)
    assert result["start"] == begin and result["end"] == stop
    assert result["truncated"] is False and result["next_offset"] is None


@pytest.mark.parametrize("field,value", [("start_line", True), ("end_line", False), ("offset", True),
    ("max_chars", True), ("start_line", 0), ("end_line", 0), ("offset", -1), ("max_chars", 0),
    ("offset", 1.0), ("max_chars", "4"), ("start_line", None), ("end_line", 3), ("offset", 4)])
def test_line_input_domains(field, value):
    with pytest.raises(ValueError):
        line_slice("a\n", **{field: value})


def test_range_continuation_long_line_and_eof_offset():
    content = "x\n" + "🌟" * 9001 + "\nz"
    first = line_slice(content, start_line=2, end_line=2)
    second = line_slice(content, start_line=2, end_line=2, offset=first["next_offset"], max_chars=99999)
    assert len(first["text"]) == 4000 and first["next_offset"] == 4000
    assert first["text"] + second["text"] == "🌟" * 9001 + "\n"
    assert second["start"] == 4002 and second["end"] == 9004 and not second["truncated"]
    assert len(line_slice("x" * 9000, max_chars=99999)["text"]) == 8000
    assert line_slice("a\n", start_line=1, end_line=1, offset=2)["text"] == ""
    with pytest.raises(ValueError):
        line_slice("a\nb", start_line=2, end_line=1)


def test_discovery_examples_are_valid_bounded_and_isolated():
    adapter = ExternalMCPAdapter()
    tools = adapter.list_tools()
    schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
    assert len(TOOL_EXAMPLES) == 9 and sum(map(len, TOOL_EXAMPLES.values())) == 13
    assert len(json.dumps({"tools": tools}, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 65536
    assert len(json.dumps(TOOL_EXAMPLES, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 8192
    for name, examples in TOOL_EXAMPLES.items():
        Draft202012Validator.check_schema(schemas[name])
        for example in examples:
            Draft202012Validator(schemas[name]).validate(example)
    schemas["patchdiff_submit_edits"]["examples"][0]["edits"][0]["replace"] = "mutated"
    assert adapter.list_tools() != tools
    assert TOOL_EXAMPLES["patchdiff_submit_edits"][0]["edits"][0]["replace"] == "beta"


def test_structured_admission_survives_mcp_serialization():
    result = SubmitPDCPResult(status="invalid_argument", target_file_id=uuid.uuid4(), pdcp_log_id=None,
                             before_hash=None, after_hash=None, before_version=None, after_version=None,
                             diagnostic={"code": "replacement_too_large", "limit_exceeded": "raw_code_points"},
                             correlation_id=str(uuid.uuid4()))
    payload = _submit_result_to_payload(result)
    assert payload["pdcp_log_id"] is None and payload["diagnostic"] == result.diagnostic
    assert payload["correlation_id"] == result.correlation_id and payload["status"] == "invalid_argument"
