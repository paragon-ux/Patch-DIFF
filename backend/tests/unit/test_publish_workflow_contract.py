"""Contract tests for .github/workflows/publish.yml (PR23-PLAN-DEP-004, PR23-PLAN-PYPI-001)."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISH_YML = REPO_ROOT / ".github" / "workflows" / "publish.yml"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"


def test_publish_workflow_manual_dispatch_only_and_oidc_gating():
    content = PUBLISH_YML.read_text(encoding="utf-8")

    # 1. Stage H: remove push: tags; only manual workflow_dispatch is permitted
    assert "workflow_dispatch:" in content
    assert "\n  push:" not in content
    assert "tags:" not in content

    # 2. Verify fetched tag ref against origin/main HEAD before checkout, with no direct ${{ inputs.tag }} interpolation in run: blocks
    assert "${{ inputs.tag }}" not in re.sub(r"INPUT_TAG:\s*\$\{\{\s*inputs\.tag\s*\}\}", "", content)
    assert "+refs/heads/main:refs/remotes/origin/main" in content
    assert "refs/tags/$TARGET_TAG^{commit}" in content

    # 3. Top-level permissions must be read-only; id-token: write only in publish job under environment: pypi
    assert "permissions:\n  contents: read" in content
    assert "environment:\n      name: pypi" in content
    assert content.count("id-token: write") == 1
    assert "SHA256SUMS.txt" in content
    assert "sha256sum -c SHA256SUMS.txt" in content

    # 4. Verify pyproject.toml distribution name is patchdiff-mcp==0.1.0 (never third-party 'patchdiff')
    pyproject = tomllib.loads(PYPROJECT_TOML.read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "patchdiff-mcp"
    assert pyproject["project"]["version"] == "0.1.0"
    assert pyproject["project"]["scripts"]["patchdiff"] == "app.mcp.external_adapter:main"
    assert pyproject["project"]["scripts"]["patchdiff-mcp"] == "app.mcp.external_adapter:main"
    assert pyproject["project"]["scripts"]["patchdiff-mcp-setup"] == "app.mcp.runtime_cli:setup_entrypoint"
    assert pyproject["project"]["scripts"]["patchdiff-mcp-daemon"] == "app.mcp.runtime_cli:daemon_entrypoint"


def test_publish_preflight_rejects_unapproved_events_and_invalid_tags():
    """Execute the preflight validation logic against valid and invalid release inputs."""
    content = PUBLISH_YML.read_text(encoding="utf-8")
    m = re.search(
        r"id: preflight.*?run: \|\n(.*?)\n\n      - name: Verify fetched tag ref",
        content,
        re.DOTALL,
    )
    assert m is not None
    script_lines = [line[10:] if line.startswith("          ") else line for line in m.group(1).splitlines()]
    script = "\n".join(script_lines)

    # 1. Valid workflow_dispatch on refs/heads/main with tag v0.1.0 succeeds
    res_ok = subprocess.run(
        ["bash", "-c", script],
        env={"EVENT_NAME": "workflow_dispatch", "INPUT_TAG": "v0.1.0", "GITHUB_REF": "refs/heads/main"},
        capture_output=True,
        text=True,
    )
    assert res_ok.returncode == 0, res_ok.stderr

    # 2. Push and pull_request events are rejected
    for bad_event in ("push", "pull_request"):
        res_ev = subprocess.run(
            ["bash", "-c", script],
            env={"EVENT_NAME": bad_event, "INPUT_TAG": "v0.1.0", "GITHUB_REF": "refs/heads/main"},
            capture_output=True,
            text=True,
        )
        assert res_ev.returncode != 0
        assert "only run via manual workflow_dispatch" in res_ev.stderr

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
    for bad_tag in ("", "0.1.0", "v0.1", "v0.1.0-rc1", "v0.1.0; echo pwned", "v0.1.0\ninjected"):
        res_bad = subprocess.run(
            ["bash", "-c", script],
            env={"EVENT_NAME": "workflow_dispatch", "INPUT_TAG": bad_tag, "GITHUB_REF": "refs/heads/main"},
            capture_output=True,
            text=True,
        )
        assert res_bad.returncode != 0
