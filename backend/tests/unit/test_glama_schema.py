"""Stage I (PR22-MCP-002): Offline Draft7Validator test for glama.json against https://glama.ai/mcp/schemas/server.json."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator

REPO_ROOT = Path(__file__).resolve().parents[3]
GLAMA_JSON_PATH = REPO_ROOT / "glama.json"

# Captured from the official URL on 2026-11-01; validated offline.
OFFICIAL_GLAMA_SERVER_SCHEMA = json.loads(
    (REPO_ROOT / "backend/tests/fixtures/glama-server.schema.json").read_text()
)


def test_glama_json_conforms_to_official_draft7_schema_and_maintainer_contract() -> None:
    assert GLAMA_JSON_PATH.is_file(), f"Missing glama.json at {GLAMA_JSON_PATH}"
    data = json.loads(GLAMA_JSON_PATH.read_text(encoding="utf-8"))

    Draft7Validator.check_schema(OFFICIAL_GLAMA_SERVER_SCHEMA)
    validator = Draft7Validator(OFFICIAL_GLAMA_SERVER_SCHEMA)
    errors = list(validator.iter_errors(data))
    assert not errors, f"glama.json failed Draft7Validator schema validation: {errors}"

    assert data.get("$schema") == "https://glama.ai/mcp/schemas/server.json"
    maintainers = data.get("maintainers")
    assert isinstance(maintainers, list)
    assert "paragon-ux" in maintainers
    # Live tools must be discovered from tools/list, not invented in glama.json
    assert "tools" not in data
