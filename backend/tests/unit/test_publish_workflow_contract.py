"""Contract tests for .github/workflows/publish.yml (PR23-PLAN-DEP-004, PR23-PLAN-PYPI-001)."""

from __future__ import annotations

import fnmatch
from pathlib import Path
import re
import subprocess
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISH_YML = REPO_ROOT / ".github" / "workflows" / "publish.yml"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"


def test_publish_workflow_tag_glob_and_oidc_gating():
    content = PUBLISH_YML.read_text(encoding="utf-8")

    # 1. Glob must match semantic version tags like v0.1.0 (not literal '+')
    assert "- 'v[0-9]*.[0-9]*.[0-9]*'" in content
    assert "'v[0-9]+.[0-9]+.[0-9]+'" not in content
    assert fnmatch.fnmatch("v0.1.0", "v[0-9]*.[0-9]*.[0-9]*")
    assert fnmatch.fnmatch("v12.34.56", "v[0-9]*.[0-9]*.[0-9]*")
    assert not fnmatch.fnmatch("feature/v0.1.0", "v[0-9]*.[0-9]*.[0-9]*")

    # 2. Top-level permissions must be read-only; id-token: write only in publish job under environment: pypi
    assert "permissions:\n  contents: read" in content
    assert "environment:\n      name: pypi" in content
    assert "id-token: write" in content
    assert "SHA256SUMS.txt" in content
    assert "sha256sum -c SHA256SUMS.txt" in content

    # 3. Verify pyproject.toml distribution name is patchdiff-mcp (never third-party 'patchdiff')
    pyproject = tomllib.loads(PYPROJECT_TOML.read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "patchdiff-mcp"
    assert pyproject["project"]["scripts"]["patchdiff-mcp"] == "app.mcp.external_adapter:main"


def test_publish_preflight_rejects_unapproved_events_and_invalid_tags():
    """Execute the preflight validation logic against valid and invalid release inputs."""
    content = PUBLISH_YML.read_text(encoding="utf-8")
    m = re.search(r"id: preflight.*?run: \|\n(.*?)\n\n      - name: Checkout", content, re.DOTALL)
    assert m is not None
    script_lines = [line[10:] if line.startswith("          ") else line for line in m.group(1).splitlines()]
    script = "\n".join(script_lines)

    # 1. Valid push tag v0.1.0 succeeds
    res_ok = subprocess.run(
        ["bash", "-c", script],
        env={"EVENT_NAME": "push", "REF_NAME": "v0.1.0", "GITHUB_REF": "refs/tags/v0.1.0"},
        capture_output=True,
        text=True,
    )
    assert res_ok.returncode == 0, res_ok.stderr

    # 2. Pull request event is rejected
    res_pr = subprocess.run(
        ["bash", "-c", script],
        env={"EVENT_NAME": "pull_request", "REF_NAME": "v0.1.0", "GITHUB_REF": "refs/pull/23/merge"},
        capture_output=True,
        text=True,
    )
    assert res_pr.returncode != 0
    assert "Unsupported event" in res_pr.stderr

    # 3. workflow_dispatch from non-main branch is rejected
    res_branch = subprocess.run(
        ["bash", "-c", script],
        env={"EVENT_NAME": "workflow_dispatch", "INPUT_TAG": "v0.1.0", "GITHUB_REF": "refs/heads/feature/branch"},
        capture_output=True,
        text=True,
    )
    assert res_branch.returncode != 0
    assert "must be executed from 'refs/heads/main'" in res_branch.stderr

    # 4. Malformed or shell-injection tags are rejected
    for bad_tag in ("0.1.0", "v0.1", "v0.1.0-rc1", "v0.1.0; echo pwned", "v0.1.0\ninjected"):
        res_bad = subprocess.run(
            ["bash", "-c", script],
            env={"EVENT_NAME": "push", "REF_NAME": bad_tag, "GITHUB_REF": f"refs/tags/{bad_tag}"},
            capture_output=True,
            text=True,
        )
        assert res_bad.returncode != 0
