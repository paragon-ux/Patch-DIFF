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
    adapter = ExternalMCPAdapter(profile="full")
    tools = adapter.list_tools()
    schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
    assert len(TOOL_EXAMPLES) == 12 and sum(map(len, TOOL_EXAMPLES.values())) == 20
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
                             current_hash=None, current_version=None,
                             diagnostic={"code": "replacement_too_large", "limit_exceeded": "raw_code_points"},
                             correlation_id=str(uuid.uuid4()))
    payload = _submit_result_to_payload(result)
    assert payload["pdcp_log_id"] is None and payload["diagnostic"] == result.diagnostic
    assert payload["correlation_id"] == result.correlation_id and payload["status"] == "invalid_argument"


def test_capability_metadata_and_descriptions_derive_from_runtime_constants():
    import re

    from app.core.versions import OPERATIONS_RUNTIME_VERSION, REPLACEMENT_RUNTIME_VERSION
    from app.mcp.external_adapter import TOOL_DESCRIPTIONS, _input_schema_for
    from app.pdcp.replacement import MAX_REPLACEMENT_BYTES, MAX_REPLACEMENT_CHARS, REPLACEMENT_PROTOCOL_VERSION

    assert _input_schema_for("patchdiff_submit_replacement")["x-patchdiff-capabilities"] == {
        "protocol_version": REPLACEMENT_PROTOCOL_VERSION, "runtime_version": REPLACEMENT_RUNTIME_VERSION,
        "operations": ["replace_all"], "max_code_points": MAX_REPLACEMENT_CHARS, "max_utf8_bytes": MAX_REPLACEMENT_BYTES,
    }
    assert f"runtime {OPERATIONS_RUNTIME_VERSION};" in TOOL_DESCRIPTIONS["patchdiff_submit_operations"]
    assert f"runtime {REPLACEMENT_RUNTIME_VERSION}." in TOOL_DESCRIPTIONS["patchdiff_submit_replacement"]
    assert f"{MAX_REPLACEMENT_CHARS:,} code points" in TOOL_DESCRIPTIONS["patchdiff_submit_replacement"]
    assert not [text for text in TOOL_DESCRIPTIONS.values() if re.search(r"\b(runtime|immutable|profile)\d", text)]


def test_discovery_patterns_are_portable_and_do_not_mutate_runtime_schemas():
    import copy

    from app.pdcp.operations import OPERATION_JSON_SCHEMA
    from app.pdcp.typed import TYPED_EDIT_JSON_SCHEMA

    original = copy.deepcopy((TYPED_EDIT_JSON_SCHEMA, OPERATION_JSON_SCHEMA))

    def check_patterns(value):
        if isinstance(value, dict):
            if "pattern" in value:
                assert "(?" not in value["pattern"]
            for child in value.values():
                check_patterns(child)
        elif isinstance(value, list):
            for child in value:
                check_patterns(child)

    for tool in ExternalMCPAdapter(profile="full").list_tools():
        Draft202012Validator.check_schema(tool["inputSchema"])
        check_patterns(tool["inputSchema"])
    assert (TYPED_EDIT_JSON_SCHEMA, OPERATION_JSON_SCHEMA) == original


@pytest.mark.parametrize("field,valid,limit,nullable", [
    ("expected_current_hash", "a" * 64, 64, True),
    ("client_request_id", "request-1", 128, True),
    ("change_id", "change-1", 64, True),
])
def test_portable_patterns_preserve_strict_end_and_null(field, valid, limit, nullable):
    import re

    from app.mcp.external_adapter import _input_schema_for

    properties = _input_schema_for("patchdiff_submit_edits")["properties"]
    schema = (properties["edits"]["items"]["properties"][field]
              if field == "change_id" else properties[field])
    validator = Draft202012Validator(schema)
    original_pattern = schema["pattern"][:-1] + r"(?![\s\S])"
    assert validator.is_valid(valid)
    assert validator.is_valid(None) == nullable
    cases = ["", "a", "a" * limit, "a" * (limit + 1), "hello world", "é", "🌟"]
    cases += [valid + suffix for suffix in ("\n", "\r", "\r\n", "\n\n", "\u2028", "\u0085")]
    cases += ["a\nb", "\n" + valid, "A" * 64, "!" * limit]
    for value in cases:
        assert validator.is_valid(value) == bool(re.search(original_pattern, value)), repr(value)


@pytest.mark.parametrize("field", ["query", "symbol_name", "kind"])
def test_optional_observe_selectors_advertise_empty_string_rejection(field):
    for profile in ("observed", "observed_editor", "full"):
        schema = next(tool["inputSchema"] for tool in ExternalMCPAdapter(profile=profile).list_tools()
                      if tool["name"] == "patchdiff_observe_scope")
        base = {"target_file_id": "11111111-1111-4111-8111-111111111111"}
        validator = Draft202012Validator(schema)
        assert validator.is_valid(base)
        assert validator.is_valid({**base, field: None})
        assert not validator.is_valid({**base, field: ""})
        assert validator.is_valid({**base, field: "  valid_name  "})
        assert "Nonblank" in schema["properties"][field]["description"]
