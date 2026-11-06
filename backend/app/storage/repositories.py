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


def select_targets_for_update_ordered(target_file_ids: list[uuid.UUID | str]) -> Select[tuple[CloudTargetFiles]]:
    """Select multiple targets locked in canonical ascending UUID order to prevent deadlocks."""
    target_uuids = sorted(
        [tid if isinstance(tid, uuid.UUID) else uuid.UUID(str(tid)) for tid in target_file_ids],
        key=str,
    )
    return (
        select(CloudTargetFiles)
        .where(CloudTargetFiles.target_file_id.in_(target_uuids))
        .order_by(CloudTargetFiles.target_file_id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )

