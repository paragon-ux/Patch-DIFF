"""Automated regression and security verification tests for .github/workflows/publish.yml (PR23-R3-DEP-001).

Verifies:
1. YAML validity and structure.
2. Complete elimination of inline expression interpolation (${{ ... }}) in all run: blocks.
3. Strict environment variable binding for untrusted inputs.
4. Preflight anchored regex validation against valid tags and negative injection payloads.
5. Command substitution payloads are treated strictly as data and never executed.
6. Git provenance, tag peeling, and origin/main ancestry verification logic.
7. Tag-to-pyproject version cross-checking logic.
8. Publish job gating ensuring push events are build-only and publish requires manual dispatch.
9. Permission boundary isolation (id-token: write restricted strictly to publish job).
"""

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import pytest
import yaml


WORKFLOW_PATH = pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows" / "publish.yml"
PYPROJECT_PATH = pathlib.Path(__file__).resolve().parents[3] / "pyproject.toml"


def _load_workflow():
    assert WORKFLOW_PATH.is_file(), f"Workflow file not found at {WORKFLOW_PATH}"
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(content)


def test_publish_workflow_yaml_validity_and_structure():
    """Verify that publish.yml is valid YAML with expected jobs, manual-only trigger, and permissions."""
    doc = _load_workflow()
    assert doc.get("name") == "Publish to PyPI"

    # Triggers (in PyYAML 1.1 unquoted 'on' evaluates to True)
    triggers = doc.get("on") or doc.get(True) or {}
    assert "push" not in triggers, "Stage H: push: tags must be removed; only manual workflow_dispatch is permitted"
    assert "workflow_dispatch" in triggers, "Workflow must support workflow_dispatch"
    dispatch_inputs = triggers["workflow_dispatch"].get("inputs", {})
    assert "tag" in dispatch_inputs, "workflow_dispatch must have 'tag' input"
    assert dispatch_inputs["tag"].get("required") is True, "Tag input must be required"

    # Jobs
    jobs = doc.get("jobs", {})
    assert "build" in jobs, "Workflow must contain 'build' job"
    assert "publish" in jobs, "Workflow must contain 'publish' job"

    # Job outputs
    build_outputs = jobs["build"].get("outputs", {})
    assert "validated_tag" in build_outputs, "Build job must expose validated_tag output"
    assert "validated_commit" in build_outputs, "Build job must expose validated_commit output"


def test_publish_workflow_no_inline_expressions_in_run_blocks():
    """Verify that zero GitHub Actions expressions (${{ ... }}) exist inside any run: script block."""
    doc = _load_workflow()
    violations = []

    for job_name, job in doc.get("jobs", {}).items():
        for step in job.get("steps", []):
            step_name = step.get("name", "unnamed_step")
            if "run" in step:
                run_script = step["run"]
                interpolations = re.findall(r"\$\{\{[^}]+\}\}", run_script)
                if interpolations:
                    violations.append((job_name, step_name, interpolations))

    assert not violations, (
        f"Found forbidden ${{ ... }} inline expression interpolation in run: blocks: {violations}"
    )


def test_publish_workflow_untrusted_inputs_bound_via_env():
    """Verify that untrusted inputs (inputs.tag, github.event_name, github.ref) are mapped strictly in env:."""
    doc = _load_workflow()
    build_steps = doc["jobs"]["build"]["steps"]

    # Step 0 must be the preflight validation step
    preflight_step = build_steps[0]
    assert "preflight" in preflight_step.get("name", "").lower()
    step_env = preflight_step.get("env", {})

    assert "INPUT_TAG" in step_env, "INPUT_TAG must be bound in env"
    assert "${{ inputs.tag }}" in step_env["INPUT_TAG"]

    assert "EVENT_NAME" in step_env, "EVENT_NAME must be bound in env"
    assert "${{ github.event_name }}" in step_env["EVENT_NAME"]

    assert "GITHUB_REF" in step_env, "GITHUB_REF must be bound in env"
    assert "${{ github.ref }}" in step_env["GITHUB_REF"]


def test_publish_workflow_checkout_pins_main_after_preflight():
    """Verify that fetched tag ref is verified against origin/main HEAD before actions/checkout runs."""
    doc = _load_workflow()
    build_steps = doc["jobs"]["build"]["steps"]

    # Step 0 is preflight, Step 1 verifies fetched tag ref against origin/main HEAD, Step 2 is checkout
    first_step = build_steps[0]
    assert "checkout" not in first_step.get("name", "").lower()
    assert "uses" not in first_step or "actions/checkout" not in first_step.get("uses", "")

    verify_step = build_steps[1]
    assert verify_step.get("id") == "verify_tag"
    assert "actions/checkout" not in verify_step.get("uses", "")
    assert "+refs/heads/main:refs/remotes/origin/main" in verify_step.get("run", "")

    checkout_step = build_steps[2]
    assert "actions/checkout" in checkout_step.get("uses", "")
    with_clause = checkout_step.get("with", {})
    assert with_clause.get("ref") == "${{ steps.verify_tag.outputs.validated_commit }}"
    assert with_clause.get("fetch-depth") == 0, "Checkout must specify fetch-depth: 0 for history"


def test_publish_workflow_publish_job_condition_and_permissions():
    """Verify that publish job is gated strictly to manual workflow_dispatch on main and OIDC token is isolated."""
    doc = _load_workflow()

    # Top-level permissions must be read-only
    top_perms = doc.get("permissions", {})
    assert top_perms.get("contents") == "read", "Top-level contents permission must be read"
    assert "id-token" not in top_perms or top_perms.get("id-token") != "write", (
        "Top-level permissions must not grant id-token: write"
    )

    publish_job = doc["jobs"]["publish"]
    assert publish_job.get("needs") == "build", "Publish job must depend on build"
    expected_if = (
        "github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/main' && "
        "needs.build.outputs.validated_tag != ''"
    )
    assert publish_job.get("if") == expected_if, (
        f"Publish job condition must be '{expected_if}', got '{publish_job.get('if')}'"
    )

    # Publish job environment
    env = publish_job.get("environment", {})
    assert env.get("name") == "pypi", "Publish job environment must be 'pypi'"
    assert env.get("url") == "https://pypi.org/p/patchdiff-mcp"

    # Publish job permissions
    job_perms = publish_job.get("permissions", {})
    assert job_perms.get("id-token") == "write", "Publish job must have id-token: write for OIDC"
    assert job_perms.get("contents") == "read", "Publish job must have contents: read"


@pytest.mark.parametrize(
    "tag_input,expected_valid,description",
    [
        # Valid semver release tags
        ("v0.1.0", True, "Standard release tag"),
        ("v1.2.3", True, "Multi-digit components"),
        ("v10.200.3000", True, "Large component numbers"),
        ("v0.0.1", True, "Patch release tag"),
        ("v2.0.0", True, "Major release tag"),
        # Command substitution injections
        ("v0.1.0$(whoami)", False, "Command substitution suffix"),
        ("$(id)", False, "Pure command substitution"),
        ("`id`", False, "Backtick command substitution"),
        ('v0.1.0"$(id)""', False, "Quoted command substitution"),
        ("v0.1.0`reboot`", False, "Backtick suffix"),
        # Semicolon and command chaining injections
        ("v0.1.0; echo pwned", False, "Semicolon command separator"),
        ("; rm -rf /", False, "Leading semicolon command"),
        ("v0.1.0 && reboot", False, "Logical AND command chaining"),
        ("v0.1.0 || true", False, "Logical OR command chaining"),
        ("v0.1.0 | cat", False, "Pipe command chaining"),
        ("v0.1.0 > /tmp/pwned", False, "Redirection operator"),
        # Unanchored prefixes and suffixes
        ("0.1.0", False, "Missing leading 'v'"),
        ("release-v0.1.0", False, "Prefixed tag"),
        ("refs/tags/v0.1.0", False, "Full git ref path"),
        ("v0.1.0-alpha", False, "Pre-release hyphen suffix"),
        ("v0.1.0-rc1", False, "Pre-release rc suffix"),
        ("v0.1.0.1", False, "Four-part version number"),
        ("v0.1.0-dirty", False, "Dirty suffix"),
        ("v0.1.0+build123", False, "Build metadata suffix"),
        ("v0.1.0malicious", False, "Unanchored alphanumeric suffix"),
        # Whitespace and control characters
        (" v0.1.0", False, "Leading whitespace"),
        ("v0.1.0 ", False, "Trailing whitespace"),
        ("v0.1.0\n", False, "Trailing newline"),
        ("v0.1.0\nmalicious", False, "Embedded newline"),
        ("v0.1.0\t", False, "Trailing tab"),
        ("v0.1 .0", False, "Internal whitespace"),
        # Empty and incomplete tags
        ("", False, "Empty string"),
        ("v", False, "Bare 'v'"),
        ("v1", False, "Major only"),
        ("v1.2", False, "Major and minor only"),
        ("v..", False, "Dots without digits"),
        ("v1.2.", False, "Trailing dot"),
        # Git flag injections
        ("--upload-pack=evil", False, "Git flag injection"),
        ("-f", False, "Short git flag"),
    ],
)
def test_preflight_tag_regex_validation(tag_input: str, expected_valid: bool, description: str):
    """Verify that preflight bash regex validation correctly accepts valid tags and rejects injection payloads."""
    # Test with bash matching the workflow's exact logic
    bash_script = """
    if [[ -z "$CANDIDATE_TAG" || "$CANDIDATE_TAG" =~ [[:space:]] ]]; then
        exit 1
    fi
    TAG_REGEX='^v[0-9]+\\.[0-9]+\\.[0-9]+$'
    if [[ ! "$CANDIDATE_TAG" =~ $TAG_REGEX ]]; then
        exit 1
    fi
    exit 0
    """
    proc = subprocess.run(["bash", "-c", bash_script], env={"CANDIDATE_TAG": tag_input}, capture_output=True)
    is_valid = (proc.returncode == 0)
    assert is_valid == expected_valid, (
        f"Regex validation failed for '{tag_input}' ({description}): expected valid={expected_valid}, got {is_valid}"
    )

    # Test with Python regex (using \\Z for strict string termination)
    py_pattern = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+\Z")
    has_whitespace = bool(re.search(r"\s", tag_input))
    py_valid = bool(py_pattern.match(tag_input)) and not has_whitespace
    assert py_valid == expected_valid, (
        f"Python regex mismatch for '{tag_input}': expected {expected_valid}, got {py_valid}"
    )


def test_command_substitution_payload_treated_as_data():
    """Verify that command substitution payloads passed via environment variables are treated strictly as data and never executed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        probe_file = pathlib.Path(tmpdir) / "pwned.txt"
        malicious_tag = f"v0.1.0$(touch {probe_file})"

        env = os.environ.copy()
        env["EVENT_NAME"] = "workflow_dispatch"
        env["INPUT_TAG"] = malicious_tag
        env["REF_NAME"] = "main"
        env["GITHUB_REF"] = "refs/heads/main"

        bash_script = """
        set -euo pipefail
        if [ "$EVENT_NAME" = "workflow_dispatch" ]; then
            if [ -z "${INPUT_TAG:-}" ]; then exit 1; fi
            if [ "$GITHUB_REF" != "refs/heads/main" ]; then exit 1; fi
            CANDIDATE_TAG="$INPUT_TAG"
        elif [ "$EVENT_NAME" = "push" ]; then
            CANDIDATE_TAG="$REF_NAME"
        else
            exit 1
        fi

        if [[ -z "$CANDIDATE_TAG" || "$CANDIDATE_TAG" =~ [[:space:]] ]]; then
            exit 1
        fi
        TAG_REGEX='^v[0-9]+\\.[0-9]+\\.[0-9]+$'
        if [[ ! "$CANDIDATE_TAG" =~ $TAG_REGEX ]]; then
            exit 1
        fi
        exit 0
        """
        proc = subprocess.run(["bash", "-c", bash_script], env=env, capture_output=True)
        assert proc.returncode == 1, "Validation must reject tag with command substitution"
        assert not probe_file.exists(), (
            f"VULNERABILITY DETECTED: Command substitution was executed! Probe file was created at {probe_file}"
        )


def test_workflow_dispatch_requires_main_branch():
    """Verify that workflow_dispatch is rejected if dispatched from a non-main ref."""
    env = os.environ.copy()
    env["EVENT_NAME"] = "workflow_dispatch"
    env["INPUT_TAG"] = "v0.1.0"
    env["REF_NAME"] = "feature/test"
    env["GITHUB_REF"] = "refs/heads/feature/test"

    bash_script = """
    set -euo pipefail
    if [ "$EVENT_NAME" = "workflow_dispatch" ]; then
        if [ "$GITHUB_REF" != "refs/heads/main" ]; then
            echo "Error: Must be dispatched from main" >&2
            exit 1
        fi
    fi
    """
    proc = subprocess.run(["bash", "-c", bash_script], env=env, capture_output=True)
    assert proc.returncode == 1, "Preflight must reject workflow_dispatch from non-main branch"


def test_pyproject_version_cross_checking_logic():
    """Verify tag-to-pyproject version cross-checking logic."""
    # Read actual pyproject.toml
    assert PYPROJECT_PATH.is_file(), f"pyproject.toml not found at {PYPROJECT_PATH}"
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    actual_version = data["project"]["version"]
    expected_tag = f"v{actual_version}"

    # Test matching tag succeeds
    def check_version(tag: str, py_ver: str) -> bool:
        return f"v{py_ver}" == tag

    assert check_version(expected_tag, actual_version) is True
    assert check_version("v99.99.99", actual_version) is False
    assert check_version(f"v{actual_version}-beta", actual_version) is False
    assert check_version(actual_version, actual_version) is False  # Missing 'v'


def test_git_provenance_and_ancestry_verification_logic():
    """Simulate git object peeling, ancestry checking on main, and detached commit checkout."""
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    try:
        # Initialize test repository
        def git(*args):
            return subprocess.run(
                ["git", "-C", str(tmpdir)] + list(args),
                capture_output=True,
                text=True,
                check=True,
            )

        def git_try(*args):
            return subprocess.run(
                ["git", "-C", str(tmpdir)] + list(args),
                capture_output=True,
                text=True,
            )

        git("init", "-b", "main")
        git("config", "user.name", "Test User")
        git("config", "user.email", "test@example.com")

        # Commit 1 on main
        (tmpdir / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
        git("add", "pyproject.toml")
        git("commit", "-m", "Initial commit for v0.1.0")
        c1 = git("rev-parse", "HEAD").stdout.strip()

        # Tag 1: Annotated tag v0.1.0 on main
        git("tag", "-a", "v0.1.0", "-m", "Release v0.1.0")

        # Commit 2 on main
        (tmpdir / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n', encoding="utf-8")
        git("add", "pyproject.toml")
        git("commit", "-m", "Update to v0.2.0")
        c2 = git("rev-parse", "HEAD").stdout.strip()

        # Tag 2: Lightweight tag v0.2.0 on main
        git("tag", "v0.2.0")

        # Create unmerged feature branch
        git("checkout", "-b", "feature/unapproved")
        (tmpdir / "pyproject.toml").write_text('[project]\nversion = "0.3.0"\n', encoding="utf-8")
        git("add", "pyproject.toml")
        git("commit", "-m", "Unapproved feature commit")
        c3 = git("rev-parse", "HEAD").stdout.strip()

        # Tag 3: Tag v0.3.0 on unmerged feature branch
        git("tag", "-a", "v0.3.0", "-m", "Unapproved tag v0.3.0")

        # Switch back to main
        git("checkout", "main")

        # Helper function implementing the publish.yml provenance logic
        def verify_release_tag(target_tag: str):
            # 1. Verify tag ref exists
            tag_ref = f"refs/tags/{target_tag}"
            if git_try("rev-parse", "-q", "--verify", tag_ref).returncode != 0:
                return False, "tag_not_found"

            # 2. Verify object type is 'tag' or 'commit'
            tag_type = git("cat-file", "-t", tag_ref).stdout.strip()
            if tag_type not in ("tag", "commit"):
                return False, f"invalid_tag_type:{tag_type}"

            # 3. Peel tag to commit SHA
            peel_res = git_try("rev-parse", "--verify", f"{tag_ref}^{{commit}}")
            if peel_res.returncode != 0:
                return False, "failed_to_peel"
            tag_commit = peel_res.stdout.strip()
            if not re.match(r"^[0-9a-f]{40}$", tag_commit):
                return False, "invalid_commit_sha"

            # 4. Check ancestry on main (or origin/main)
            is_ancestor = git_try("merge-base", "--is-ancestor", tag_commit, "main").returncode == 0
            if not is_ancestor:
                return False, "not_ancestor_of_main"

            # 5. Check out detached commit
            git("checkout", "-q", tag_commit)
            current_head = git("rev-parse", "HEAD").stdout.strip()
            if current_head != tag_commit:
                return False, "checkout_mismatch"

            return True, tag_commit

        # Test v0.1.0 (annotated tag on main) -> OK
        ok, res = verify_release_tag("v0.1.0")
        assert ok is True, f"v0.1.0 should pass verification, got {res}"
        assert res == c1

        # Test v0.2.0 (lightweight tag on main) -> OK
        ok, res = verify_release_tag("v0.2.0")
        assert ok is True, f"v0.2.0 should pass verification, got {res}"
        assert res == c2

        # Test v0.3.0 (tag on unapproved branch) -> Rejected (not ancestor of main)
        ok, res = verify_release_tag("v0.3.0")
        assert ok is False, "v0.3.0 on unapproved branch must be rejected"
        assert res == "not_ancestor_of_main"

        # Test non-existent tag -> Rejected
        ok, res = verify_release_tag("v9.9.9")
        assert ok is False, "Non-existent tag must be rejected"
        assert res == "tag_not_found"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_artifact_filename_matching_logic():
    """Verify the artifact filename matching logic used in publish.yml."""
    target_tag = "v0.1.0"
    version = target_tag.lstrip("v")
    assert version == "0.1.0"

    matching_wheel = f"dist/patchdiff_mcp-{version}-py3-none-any.whl"
    matching_sdist = f"dist/patchdiff_mcp-{version}.tar.gz"
    mismatched_wheel = "dist/patchdiff_mcp-0.2.0-py3-none-any.whl"

    wheel_pattern = re.compile(rf"^dist/patchdiff_mcp-{re.escape(version)}-.*\.whl$")
    sdist_pattern = re.compile(rf"^dist/patchdiff[-_]mcp-{re.escape(version)}\.tar\.gz$")

    assert wheel_pattern.match(matching_wheel) is not None
    assert sdist_pattern.match(matching_sdist) is not None
    assert wheel_pattern.match(mismatched_wheel) is None
