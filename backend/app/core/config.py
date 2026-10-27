from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_STRICT_OBSERVATION_MODE_OVERRIDE: ContextVar[bool | None] = ContextVar(
    "patchdiff_strict_observation_mode_override",
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


settings = Settings()
