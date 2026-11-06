from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_STRICT_OBSERVATION_MODE_OVERRIDE: ContextVar[bool | None] = ContextVar(
    "patchdiff_strict_observation_mode_override",
    default=None,
)
_WORKSPACE_ROOT_OVERRIDE: ContextVar[str | None] = ContextVar(
    "patchdiff_workspace_root_override",
    default=None,
)
_WORKSPACE_SYNC_ON_SAVE_OVERRIDE: ContextVar[bool | None] = ContextVar(
    "patchdiff_workspace_sync_on_save_override",
    default=None,
)


def _parse_bool_env(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_strict_observation_mode_enabled() -> bool:
    """Return True when every target-mutating submission route must carry a valid observation."""
    override = _STRICT_OBSERVATION_MODE_OVERRIDE.get()
    if override is not None:
        return override
    return _parse_bool_env(os.getenv("PATCHDIFF_STRICT_OBSERVATION_MODE"))


@contextmanager
def strict_observation_mode(enabled: bool = True):
    """Context-manager / test-fixture hook to toggle strict observation mode deterministically."""
    token = _STRICT_OBSERVATION_MODE_OVERRIDE.set(bool(enabled))
    try:
        yield
    finally:
        _STRICT_OBSERVATION_MODE_OVERRIDE.reset(token)


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("PATCHDIFF_APP_NAME", "PatchDIFF MVP")
    environment: str = os.getenv("PATCHDIFF_ENV", "local")
    database_url: str = os.getenv(
        "PATCHDIFF_DATABASE_URL",
        "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff",
    )

    @property
    def strict_observation_mode(self) -> bool:
        return is_strict_observation_mode_enabled()

    @property
    def workspace_root(self) -> str | None:
        return get_workspace_root()

    @property
    def workspace_sync_on_save(self) -> bool:
        return is_workspace_sync_on_save_enabled()


def get_workspace_root() -> str | None:
    """Return configured PATCHDIFF_WORKSPACE_ROOT when set and nonblank."""
    override = _WORKSPACE_ROOT_OVERRIDE.get()
    raw = override if override is not None else os.getenv("PATCHDIFF_WORKSPACE_ROOT")
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def is_workspace_sync_on_save_enabled() -> bool:
    """Return True when SAVE should request managed write-back to PATCHDIFF_WORKSPACE_ROOT by default."""
    override = _WORKSPACE_SYNC_ON_SAVE_OVERRIDE.get()
    if override is not None:
        return override
    return _parse_bool_env(os.getenv("PATCHDIFF_WORKSPACE_SYNC_ON_SAVE"))


@contextmanager
def workspace_root_context(
    workspace_root: str | os.PathLike[str] | None,
    *,
    sync_on_save: bool | None = None,
):
    """Context-manager / test-fixture hook to configure workspace sync deterministically."""
    root_val = os.fspath(workspace_root) if workspace_root is not None else ""
    root_tok = _WORKSPACE_ROOT_OVERRIDE.set(root_val)
    sync_tok = (
        _WORKSPACE_SYNC_ON_SAVE_OVERRIDE.set(bool(sync_on_save))
        if sync_on_save is not None
        else None
    )
    try:
        yield
    finally:
        if sync_tok is not None:
            _WORKSPACE_SYNC_ON_SAVE_OVERRIDE.reset(sync_tok)
        _WORKSPACE_ROOT_OVERRIDE.reset(root_tok)


settings = Settings()
