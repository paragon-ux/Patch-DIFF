"""Waymark runtime bridge provisioning and verification.

Ensures that the pinned waymark-engine@4.1.0 dependency is cleanly installed
into a controlled host cache or target directory from packaged lockfiles.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


EXPECTED_WAYMARK_ENGINE_VERSION = "4.1.0"
MINIMUM_NODE_VERSION = (22, 0, 0)
BRIDGE_FILES = (
    "discover.mjs",
    "discovery_core.mjs",
    "worker.mjs",
    "package.json",
    "package-lock.json",
)


def get_default_bridge_cache_dir() -> Path:
    base = os.getenv("XDG_CACHE_HOME")
    cache_root = Path(base) if base else Path.home() / ".cache"
    return cache_root / "patchdiff" / f"waymark-bridge-{EXPECTED_WAYMARK_ENGINE_VERSION}"


def get_packaged_bridge_dir() -> Path:
    return Path(__file__).resolve().parent


def parse_node_version(version_str: str) -> tuple[int, int, int]:
    clean = version_str.strip().lstrip("v")
    parts = clean.split(".")
    if len(parts) < 3:
        raise ValueError(f"Invalid Node version string: {version_str!r}")
    return (int(parts[0]), int(parts[1]), int(parts[2].split("-")[0]))


def verify_node_binary(node_path: str) -> tuple[int, int, int]:
    try:
        proc = subprocess.run(
            [node_path, "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5.0,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError(f"Failed to execute Node binary at {node_path}: {exc}") from exc
    version = parse_node_version(proc.stdout)
    if version < MINIMUM_NODE_VERSION:
        raise RuntimeError(
            f"Node version {proc.stdout.strip()} at {node_path} is below minimum requirement {MINIMUM_NODE_VERSION}."
        )
    return version


def verify_installed_bridge(bridge_dir: Path) -> str:
    """Verify that bridge_dir has all required bridge files and waymark-engine@4.1.0."""
    missing = [name for name in BRIDGE_FILES if not (bridge_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"Bridge directory {bridge_dir} is missing required files: {missing}")

    pkg_json = bridge_dir / "node_modules" / "waymark-engine" / "package.json"
    if not pkg_json.is_file():
        raise RuntimeError(f"waymark-engine is not installed in {bridge_dir / 'node_modules'}")

    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read {pkg_json}: {exc}") from exc

    version = str(data.get("version", ""))
    if version != EXPECTED_WAYMARK_ENGINE_VERSION:
        raise RuntimeError(
            f"Installed waymark-engine version is {version!r}, expected {EXPECTED_WAYMARK_ENGINE_VERSION!r}"
        )
    return version


def bootstrap_bridge(
    target_dir: Path | str | None = None,
    *,
    node_binary: str | None = None,
    npm_binary: str | None = None,
) -> Path:
    dest = Path(target_dir).resolve() if target_dir else get_default_bridge_cache_dir()
    dest.mkdir(parents=True, exist_ok=True)

    from app.services.waymark_adapter import resolve_node_executable

    node_path = resolve_node_executable(node_binary)
    verify_node_binary(node_path)

    # Copy bridge files from packaged location
    pkg_dir = get_packaged_bridge_dir()
    for fname in BRIDGE_FILES:
        src = pkg_dir / fname
        if not src.is_file():
            # Fall back to repo checkout if running from unpacked dev checkout
            src = Path(__file__).resolve().parents[3] / "integrations" / "waymark" / fname
        if not src.is_file():
            raise RuntimeError(f"Source bridge file {fname} not found in package or repo.")
        shutil.copy2(src, dest / fname)

    # Check if already cleanly installed
    try:
        verify_installed_bridge(dest)
        return dest
    except RuntimeError:
        pass

    # Resolve npm
    npm_path = npm_binary or shutil.which("npm")
    if not npm_path:
        # Check adjacent to node binary
        adjacent = Path(node_path).parent / "npm"
        if adjacent.is_file() and os.access(adjacent, os.X_OK):
            npm_path = str(adjacent)
        else:
            raise RuntimeError(f"npm binary not found in PATH or adjacent to Node at {node_path}")

    # Run npm ci
    cmd = [npm_path, "ci", "--ignore-scripts"]
    try:
        subprocess.run(
            cmd,
            cwd=str(dest),
            check=True,
            capture_output=True,
            text=True,
            timeout=120.0,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"npm ci failed in {dest} with code {exc.returncode}: {exc.stderr}"
        ) from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError(f"Failed to execute npm at {npm_path}: {exc}") from exc

    verify_installed_bridge(dest)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap PatchDIFF Waymark JavaScript bridge")
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Target directory for bridge installation (default: user cache)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify existing bridge installation without running npm ci",
    )
    args = parser.parse_args()

    target = Path(args.target_dir).resolve() if args.target_dir else get_default_bridge_cache_dir()
    if args.check_only:
        try:
            version = verify_installed_bridge(target)
            print(f"Waymark bridge valid at {target} (waymark-engine@{version})")
            sys.exit(0)
        except Exception as exc:
            print(f"Waymark bridge check failed: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        res = bootstrap_bridge(target)
        print(f"Waymark bridge successfully bootstrapped at {res}")
        sys.exit(0)
    except Exception as exc:
        print(f"Waymark bootstrap failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
