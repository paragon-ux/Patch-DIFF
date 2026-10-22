import uuid

from sqlalchemy import event, select, text

from app.services.pdcp_service import submit_edits
from app.services.read_service import read_lines
from app.storage.db import SessionLocal
from app.storage.models import CloudTargetFiles
from backend.tests.integration.helpers import create_target


def test_line_read_ignores_stale_or_dirty_orm_without_flush_or_lock():
    target_id = create_target("a\nb\n")
    with SessionLocal() as stale:
        target = stale.get(CloudTargetFiles, target_id)
        with SessionLocal() as writer:
            assert submit_edits(writer, target_file_id=target_id, intent="update", expected_target_version=0,
                                edits=[{"match": "b", "replace": "中🌟"}]).status == "accepted"
        target.current_content = "UNFLUSHED"
        statements = []
        connection = stale.connection()
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(connection, "before_cursor_execute", capture)
        try:
            result = read_lines(stale, target_file_id=target_id, start_line=2, end_line=3)
        finally:
            event.remove(connection, "before_cursor_execute", capture)
        assert result["status"] == "ok" and result["version"] == 1 and result["text"] == "中🌟\n"
        assert len(statements) == 1 and statements[0].lstrip().upper().startswith("SELECT")
        assert "FOR UPDATE" not in statements[0].upper()
        assert target.current_content == "UNFLUSHED" and target.version == 0 and target in stale.dirty
        with SessionLocal() as other:
            other.execute(text("SET LOCAL lock_timeout='500ms'"))
            assert other.scalar(select(CloudTargetFiles.target_file_id).where(
                CloudTargetFiles.target_file_id == target_id).with_for_update(nowait=True)) == target_id
        stale.rollback()


def test_line_read_target_and_argument_errors():
    target_id = create_target("")
    with SessionLocal() as session:
        assert read_lines(session, target_file_id="bad")["status"] == "invalid_argument"
        assert read_lines(session, target_file_id=uuid.uuid4())["status"] == "not_found"
        assert read_lines(session, target_file_id=target_id, start_line=True)["status"] == "invalid_argument"
        result = read_lines(session, target_file_id=target_id)
        assert result["total_lines"] == 1 and result["text"] == "" and result["version"] == 0
