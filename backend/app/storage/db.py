from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import (
    DB_BOOTSTRAP_USER,
    get_active_mcp_profile,
    get_required_db_role_for_profile,
    redact_sensitive_text,
    resolve_database_url,
)
from app.services.performance_events import install_sqlalchemy

_ENGINES_BY_KEY: dict[tuple[str, str | None, bool], Engine] = {}
_SESSIONMAKERS_BY_KEY: dict[tuple[str, str | None, bool], sessionmaker[Session]] = {}


def _build_verified_engine(url: str, *, required_role: str | None, disallow_bootstrap: bool) -> Engine:
    eng: Engine = create_engine(url, pool_pre_ping=True)
    install_sqlalchemy(eng)

    @event.listens_for(eng, "connect")
    def _verify_connected_role(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SELECT current_user")
            row = cursor.fetchone()
            actual_user = str(row[0]) if row else ""
        finally:
            cursor.close()
        try:
            dbapi_connection.rollback()
        except Exception:
            pass

        if disallow_bootstrap and actual_user == DB_BOOTSTRAP_USER:
            try:
                dbapi_connection.close()
            except Exception:
                pass
            raise PermissionError(
                f"PostgreSQL connection authenticated as {actual_user!r}; {DB_BOOTSTRAP_USER!r} is never permitted for MCP connections."
            )

        if required_role is not None and actual_user != required_role:
            try:
                dbapi_connection.close()
            except Exception:
                pass
            raise PermissionError(
                f"PostgreSQL connection authenticated as {actual_user!r}, expected required role {required_role!r}."
            )

    return eng


def create_bootstrap_engine() -> Engine:
    """Create a disposable SQLAlchemy Engine authenticated as patchdiff_bootstrap for administrative/test operations."""
    url = resolve_database_url(profile=None, role=DB_BOOTSTRAP_USER)
    return _build_verified_engine(url, required_role=DB_BOOTSTRAP_USER, disallow_bootstrap=False)


def get_engine(*, profile: str | None = None, role: str | None = None) -> Engine:
    effective_profile = profile or get_active_mcp_profile()
    required_role = role or get_required_db_role_for_profile(effective_profile)
    disallow_bootstrap = effective_profile is not None
    try:
        url = resolve_database_url(profile=effective_profile, role=required_role)
    except Exception as exc:
        raise type(exc)(redact_sensitive_text(str(exc))) from None

    key = (url, required_role, disallow_bootstrap)
    eng = _ENGINES_BY_KEY.get(key)
    if eng is None:
        eng = _build_verified_engine(url, required_role=required_role, disallow_bootstrap=disallow_bootstrap)
        _ENGINES_BY_KEY[key] = eng
        _SESSIONMAKERS_BY_KEY[key] = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    return eng


class _RoleScopedLazySession(Session):
    """SQLAlchemy Session that resolves its role-scoped Engine lazily when a DB operation requests a bind."""

    def get_bind(self, mapper: Any = None, clause: Any = None, **kw: Any) -> Engine:
        if self.bind is not None:
            return self.bind  # type: ignore[return-value]
        return get_engine()


_LAZY_SESSIONMAKER = sessionmaker(
    class_=_RoleScopedLazySession,
    autoflush=False,
    expire_on_commit=False,
)


def _get_sessionmaker(*, profile: str | None = None, role: str | None = None) -> sessionmaker[Session]:
    effective_profile = profile or get_active_mcp_profile()
    required_role = role or get_required_db_role_for_profile(effective_profile)
    disallow_bootstrap = effective_profile is not None
    eng = get_engine(profile=effective_profile, role=required_role)
    key = (eng.url.render_as_string(hide_password=False), required_role, disallow_bootstrap)
    sm = _SESSIONMAKERS_BY_KEY.get(key)
    if sm is None:
        sm = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
        _SESSIONMAKERS_BY_KEY[key] = sm
    return sm


class _LazySessionFactory:
    """Session factory that resolves the role-scoped SQLAlchemy Engine on demand when a DB bind is requested."""

    def __call__(self, **kw: Any) -> Session:
        if "bind" in kw and kw["bind"] is not None:
            return _LAZY_SESSIONMAKER(**kw)
        return _LAZY_SESSIONMAKER(**kw)

    def begin(self) -> Any:
        return _get_sessionmaker().begin()

    def configure(self, **kw: Any) -> None:
        _LAZY_SESSIONMAKER.configure(**kw)


SessionLocal = _LazySessionFactory()


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def check_database() -> bool:
    try:
        eng = get_engine()
        with eng.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except (SQLAlchemyError, RuntimeError, PermissionError, ValueError, OSError):
        return False


def __getattr__(name: str) -> Any:
    if name == "engine":
        return get_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
