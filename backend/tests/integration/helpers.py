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
