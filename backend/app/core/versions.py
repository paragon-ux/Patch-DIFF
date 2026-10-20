"""Runtime version identifiers and explicit replay-compatibility profiles.

Single home for runtime-version compatibility so the submit service and replay
cannot disagree about how a persisted transaction must be re-applied.
"""

from __future__ import annotations

RUNTIME_VERSION = "patchdiff-mvp-0.2.1"
PREVIOUS_RUNTIME_VERSION = "patchdiff-mvp-0.2.0"

# Logs written by this runtime enumerated MATCH candidates by skipping overlapping
# spans. Accepted history written under it must replay identically.
LEGACY_RUNTIME_VERSION = "patchdiff-mvp-0.1.0"

# Explicit allowlist of runtime execution profiles -> overlapping_matches flag.
# Unknown runtime versions must fail replay explicitly rather than silently
# inheriting current matching semantics.
SUPPORTED_RUNTIME_PROFILES: dict[str, bool] = {
    LEGACY_RUNTIME_VERSION: False,
    PREVIOUS_RUNTIME_VERSION: True,
    RUNTIME_VERSION: True,
}


class UnsupportedRuntimeVersionError(ValueError):
    """Raised when a persisted log records an unknown runtime_version."""


def resolve_overlapping_matches(runtime_version: str | None) -> bool:
    """Resolve the exact MATCH enumeration profile for a persisted runtime_version.

    Raises ``UnsupportedRuntimeVersionError`` for unknown or missing versions so
    replay fails safely instead of guessing future semantics.
    """

    if runtime_version not in SUPPORTED_RUNTIME_PROFILES:
        raise UnsupportedRuntimeVersionError(
            f"Unsupported logged runtime_version: {runtime_version!r}."
        )
    return SUPPORTED_RUNTIME_PROFILES[runtime_version]


def uses_overlapping_matches(runtime_version: str | None) -> bool:
    """Return whether a supported runtime_version counts overlapping exact spans."""

    return resolve_overlapping_matches(runtime_version)
