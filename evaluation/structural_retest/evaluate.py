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
    return namespace["check_workspace"](workspace, study)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, choices=["primary", "supplemental"])
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    result = check(args.study, args.workspace)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["total"] > 0 and result["passed"] == result["total"] else 1)
