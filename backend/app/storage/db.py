from pathlib import Path
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.services.performance_events import install_sqlalchemy


engine: Engine = create_engine(settings.database_url, pool_pre_ping=True)
install_sqlalchemy(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def check_database() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False



def database_schema_is_current() -> bool:
    """Check the database against the migrations shipped with this installation."""
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    migrations = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "migrations"))
    with engine.connect() as connection:
        installed_heads = MigrationContext.configure(connection).get_current_heads()
    return set(installed_heads) == set(migrations.get_heads())
