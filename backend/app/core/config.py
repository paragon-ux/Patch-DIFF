from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

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


def _resolve_default_database_url() -> str:
    explicit = os.getenv("PATCHDIFF_DATABASE_URL")
    if explicit:
        return explicit

    cred_file_env = os.getenv("PATCHDIFF_DB_CREDENTIALS_FILE")
    cred_path = (
        Path(cred_file_env).expanduser()
        if cred_file_env
        else (Path.home() / ".local" / "share" / "patchdiff-runtime" / "db_credentials.json")
    )
    if cred_path.is_file():
        try:
            raw = json.loads(cred_path.read_text(encoding="utf-8"))
            profile_env = os.getenv("PATCHDIFF_MCP_PROFILE")
            role_env = os.getenv("PATCHDIFF_DB_ROLE", "").strip().lower()
            if role_env == "agent" or (profile_env is not None and profile_env.strip().lower() != "full"):
                user = str(raw["agent_user"])
                pw = str(raw["agent_password"])
            else:
                user = str(raw["admin_user"])
                pw = str(raw["admin_password"])
            dbname = str(raw.get("dbname", "patchdiff"))
            route = os.getenv("PATCHDIFF_ACTIVE_ROUTE", "native").strip().lower()
            port = (
                int(os.getenv("PATCHDIFF_POSTGRES_PORT", "5433"))
                if route == "docker"
                else int(os.getenv("PATCHDIFF_NATIVE_POSTGRES_PORT", "5434"))
            )
            return f"postgresql+psycopg://{quote(user, safe='')}:{quote(pw, safe='')}@127.0.0.1:{port}/{dbname}"
        except Exception:
            pass

    return "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff"


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("PATCHDIFF_APP_NAME", "PatchDIFF MVP")
    environment: str = os.getenv("PATCHDIFF_ENV", "local")
    database_url: str = _resolve_default_database_url()

    @property
    def strict_observation_mode(self) -> bool:
        return is_strict_observation_mode_enabled()


settings = Settings()
