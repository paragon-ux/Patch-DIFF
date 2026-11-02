import uuid

from app.services.target_service import initialize_target
from app.storage.db import SessionLocal


def pdcp_for(
    target_file_id: uuid.UUID,
    *changes: tuple[str, str],
    header_hash: str | None = None,
    change_id_prefix: str = "chg",
) -> str:
    header = f"PDCP 0.2.3\ntarget_file_id: {target_file_id}\ntarget_type: text/plain"
    if header_hash is not None:
        header += f"\ntarget_hash: {header_hash}"

    sections = [header]
    for index, (match, replace) in enumerate(changes, start=1):
        sections.append(
            f"""# MANIFEST
# change_id: {change_id_prefix}_{index:03d}
# intent: Update text.
# input_state: Old text exists.
# output_state: New text exists.
# affected_region: example
# user_visible_change: Text changes.
# risk: low

<<<<<<< MATCH
{match}
=======
{replace}
>>>>>>> REPLACE"""
        )
    return "\n\n".join(sections)


def create_target(content: str = "old", *, target_type: str = "text/plain") -> uuid.UUID:
    with SessionLocal() as session:
        initialized = initialize_target(
            session,
            filename=f"{uuid.uuid4()}.txt",
            content=content,
            target_type=target_type,
        )
        return initialized.target_file_id


from contextlib import contextmanager
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.storage.db import create_bootstrap_engine


@contextmanager
def maintenance_session(*tables, rollback=False):
    """Inject deliberate corruption in a disposable DB as bootstrap, never a service.

    Trigger disable, fault injection and re-enable share one transaction. On any
    exception the DDL and data roll back together. This is test-only maintenance.
    """
    permitted = {"append_only_pdcp_logs", "append_only_manifest_ledger", "target_snapshots",
                 "target_scope_observations", "target_finalization_export_chunks"}
    assert tables and set(tables) <= permitted
    engine = create_bootstrap_engine()
    try:
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            with session.begin() as transaction:
                for table in tables:
                    session.execute(text(f'ALTER TABLE {table} DISABLE TRIGGER trg_immutable_{table}'))
                yield session
                session.flush()
                if rollback:
                    transaction.rollback()
                else:
                    for table in tables:
                        session.execute(text(f'ALTER TABLE {table} ENABLE TRIGGER trg_immutable_{table}'))
    finally:
        engine.dispose()
