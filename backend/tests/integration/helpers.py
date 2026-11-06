import uuid

from app.services.target_service import initialize_target
from app.storage.db import SessionLocal


def edit_pairs(*changes: tuple[str, str], change_id_prefix: str = "chg") -> list[dict]:
    return [
        {"match": match, "replace": replacement, "change_id": f"{change_id_prefix}_{index:03d}", "risk": "low"}
        for index, (match, replacement) in enumerate(changes, start=1)
    ]


def create_target(content: str = "old", *, target_type: str = "text/plain") -> uuid.UUID:
    with SessionLocal() as session:
        initialized = initialize_target(
            session,
            filename=f"{uuid.uuid4()}.txt",
            content=content,
            target_type=target_type,
        )
        return initialized.target_file_id
