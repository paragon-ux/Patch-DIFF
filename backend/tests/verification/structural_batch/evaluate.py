"""External behavioral evaluation using only the original oracle's pure check functions."""
import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def check(study: str, workspace: Path) -> dict:
    source = ROOT / study / "evaluator" / "verify_hard_suite.py"
    tree = ast.parse(source.read_bytes().decode("utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"load_module_from_path", "check_workspace"}]
    if {node.name for node in functions} != {"load_module_from_path", "check_workspace"}:
        raise ValueError("Original external oracle functions are missing")
    namespace = {"Path": Path, "Any": Any, "importlib": importlib, "json": json, "sys": sys}
    # Preserve original checks without importing backend services or running historical entry points.
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return namespace["check_workspace"](workspace, study)
    finally:
        sys.dont_write_bytecode = previous


def complete_primary(workspace: Path) -> dict:
    from backend.tests.verification.structural_batch.primary.evaluator.full_byte_oracle import compare
    full_byte = compare(workspace)
    # The historical verifier imports/executes Python targets. Only execute them
    # after exact equality with the authenticated reference has been established.
    behavioral = check("primary", workspace) if full_byte["passed"] else {"skipped": "full-byte failure prevents executing untrusted output"}
    return {"full_byte": full_byte, "behavioral": behavioral,
            "complete_correct": full_byte["passed"] and behavioral.get("total", 0) > 0 and behavioral["passed"] == behavioral["total"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", default="primary", choices=["primary"])
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT.parents[3]))
    result = complete_primary(args.workspace)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["complete_correct"] else 1)
