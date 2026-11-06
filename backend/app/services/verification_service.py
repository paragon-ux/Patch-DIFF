"""Pre-commit semantic verification hooks for PatchDIFF preview outputs."""

from __future__ import annotations

import ast
import json
import re
import time
from typing import Any


def verify_python_syntax(content: str, filename: str = "<preview>") -> dict[str, Any]:
    """Verify that Python content parses into a valid AST without syntax errors."""
    start_time = time.perf_counter()
    try:
        ast.parse(content, filename=filename)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
        return {
            "hook": "python_syntax",
            "passed": True,
            "status": "passed",
            "duration_ms": duration_ms,
            "error": None,
        }
    except SyntaxError as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
        return {
            "hook": "python_syntax",
            "passed": False,
            "status": "failed",
            "duration_ms": duration_ms,
            "error": {
                "message": exc.msg,
                "line": exc.lineno,
                "offset": exc.offset,
                "text": (exc.text or "").strip(),
            },
        }


def verify_json_syntax(content: str) -> dict[str, Any]:
    """Verify that JSON content parses into valid data structures."""
    start_time = time.perf_counter()
    try:
        json.loads(content)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
        return {
            "hook": "json_syntax",
            "passed": True,
            "status": "passed",
            "duration_ms": duration_ms,
            "error": None,
        }
    except json.JSONDecodeError as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
        return {
            "hook": "json_syntax",
            "passed": False,
            "status": "failed",
            "duration_ms": duration_ms,
            "error": {
                "message": exc.msg,
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
            },
        }


def verify_markdown_fences(content: str) -> dict[str, Any]:
    """Verify that all opened Markdown code fences are closed."""
    start_time = time.perf_counter()
    lines = content.splitlines()
    in_fence: str | None = None
    fence_start_line = 0
    fence_pattern = re.compile(r"^(```+|~~~+)")

    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        match = fence_pattern.match(stripped)
        if match:
            fence_chars = match.group(1)
            char_type = fence_chars[0]
            fence_len = len(fence_chars)
            if in_fence is None:
                in_fence = fence_chars
                fence_start_line = idx
            else:
                if char_type == in_fence[0] and fence_len >= len(in_fence):
                    in_fence = None

    duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
    if in_fence is not None:
        return {
            "hook": "markdown_fences",
            "passed": False,
            "status": "failed",
            "duration_ms": duration_ms,
            "error": {
                "message": f"Unclosed code fence starting at line {fence_start_line}.",
                "line": fence_start_line,
            },
        }

    return {
        "hook": "markdown_fences",
        "passed": True,
        "status": "passed",
        "duration_ms": duration_ms,
        "error": None,
    }


HOOK_REGISTRY = {
    "python_syntax": verify_python_syntax,
    "syntax": verify_python_syntax,
    "json_syntax": verify_json_syntax,
    "markdown_fences": verify_markdown_fences,
    "fence_balance": verify_markdown_fences,
}


def run_verification_hooks(
    content: str,
    *,
    target_type: str | None = None,
    filename: str | None = None,
    verify_syntax: bool = False,
    hooks: list[str] | None = None,
) -> dict[str, Any]:
    """Run requested or inferred semantic verification hooks against buffer content."""
    requested_hooks: list[str] = list(hooks) if hooks else []

    if verify_syntax:
        t_type = (target_type or "").lower()
        f_name = (filename or "").lower()
        if "python" in t_type or f_name.endswith((".py", ".pyw")):
            if "python_syntax" not in requested_hooks and "syntax" not in requested_hooks:
                requested_hooks.append("python_syntax")
        elif "json" in t_type or f_name.endswith(".json"):
            if "json_syntax" not in requested_hooks:
                requested_hooks.append("json_syntax")
        elif "markdown" in t_type or f_name.endswith((".md", ".markdown")):
            if "markdown_fences" not in requested_hooks and "fence_balance" not in requested_hooks:
                requested_hooks.append("markdown_fences")

    if not requested_hooks:
        return {
            "status": "passed",
            "passed": True,
            "checks": [],
            "errors": [],
        }

    checks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    all_passed = True

    for hook_name in requested_hooks:
        if hook_name not in HOOK_REGISTRY:
            checks.append({
                "hook": hook_name,
                "passed": False,
                "status": "unknown_hook",
                "duration_ms": 0.0,
                "error": f"Unknown verification hook: {hook_name}.",
            })
            errors.append({"hook": hook_name, "message": f"Unknown verification hook: {hook_name}."})
            all_passed = False
            continue

        handler = HOOK_REGISTRY[hook_name]
        if hook_name in {"python_syntax", "syntax"}:
            res = handler(content, filename=filename or "<preview>")
        else:
            res = handler(content)

        checks.append(res)
        if not res["passed"]:
            all_passed = False
            if res.get("error"):
                errors.append({"hook": hook_name, **res["error"]})

    return {
        "status": "passed" if all_passed else "failed",
        "passed": all_passed,
        "checks": checks,
        "errors": errors,
    }
