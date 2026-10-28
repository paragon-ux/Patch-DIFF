import uuid

from sqlalchemy import Select, select

from app.storage.models import CloudTargetFiles


def select_target_for_update(target_file_id: uuid.UUID | str) -> Select[tuple[CloudTargetFiles]]:
    target_uuid = target_file_id if isinstance(target_file_id, uuid.UUID) else uuid.UUID(str(target_file_id))
    return (
        select(CloudTargetFiles)
        .where(CloudTargetFiles.target_file_id == target_uuid)
        .with_for_update()
        .execution_options(populate_existing=True, patchdiff_perf_target_lock=str(target_uuid))
    )
