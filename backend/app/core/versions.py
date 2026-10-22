"""Runtime identifiers and immutable replay execution profiles."""

from __future__ import annotations

from dataclasses import dataclass

RUNTIME_VERSION = "patchdiff-mvp-0.2.2"
OPERATIONS_RUNTIME_VERSION = "patchdiff-mvp-0.3.0"
REPLACEMENT_RUNTIME_VERSION = "patchdiff-mvp-0.4.0"
PRE_SELECTOR_RUNTIME_VERSION = "patchdiff-mvp-0.2.1"
PREVIOUS_RUNTIME_VERSION = "patchdiff-mvp-0.2.0"
LEGACY_RUNTIME_VERSION = "patchdiff-mvp-0.1.0"


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    overlapping_matches: bool
    enforce_singleton_selectors: bool
    span_operations: bool = False
    replace_all_operations: bool = False


# Recorded profiles never inherit new execution semantics.
SUPPORTED_RUNTIME_PROFILES: dict[str, RuntimeProfile] = {
    LEGACY_RUNTIME_VERSION: RuntimeProfile(False, False),
    PREVIOUS_RUNTIME_VERSION: RuntimeProfile(True, False),
    PRE_SELECTOR_RUNTIME_VERSION: RuntimeProfile(True, False),
    RUNTIME_VERSION: RuntimeProfile(True, True),
    OPERATIONS_RUNTIME_VERSION: RuntimeProfile(True, True, True),
    REPLACEMENT_RUNTIME_VERSION: RuntimeProfile(True, True, True, True),
}


class UnsupportedRuntimeVersionError(ValueError):
    """Raised when a persisted log records an unknown runtime_version."""


def resolve_runtime_profile(runtime_version: str | None) -> RuntimeProfile:
    """Resolve recorded execution semantics, refusing unknown/missing versions."""
    if runtime_version not in SUPPORTED_RUNTIME_PROFILES:
        raise UnsupportedRuntimeVersionError(
            f"Unsupported logged runtime_version: {runtime_version!r}."
        )
    return SUPPORTED_RUNTIME_PROFILES[runtime_version]


def resolve_overlapping_matches(runtime_version: str | None) -> bool:
    """Retained convenience API for callers needing only match enumeration."""
    return resolve_runtime_profile(runtime_version).overlapping_matches


def uses_overlapping_matches(runtime_version: str | None) -> bool:
    """Return whether a supported runtime counts overlapping exact spans."""
    return resolve_overlapping_matches(runtime_version)
