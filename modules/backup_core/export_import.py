from datetime import datetime

from modules.backup_core.user_backup import build_user_backup
from modules.backup_core.user_restore import apply_user_restore
from modules.systemlog import log_system


def export_user_archive(storage, user_id, now=None, include_images=True):
    """Export one user dataset by creating a canonical quota-guarded backup archive."""
    if now is None:
        now = datetime.now()
    if include_images is False:
        raise ValueError("include_images=False not supported by canonical export")

    created = build_user_backup(
        storage,
        user_id,
        "exports",
        now=now,
        source="export",
        enforce_quota=True,
    )

    log_system("backup", "export_created", {
        "user_id": str(user_id),
        "path": created.get("path"),
        "alert_count": int(created.get("alert_count") or 0),
        "image_count": int(created.get("image_count") or 0),
    })
    storage.log_user_event(str(user_id), "backup_created", {
        "source": "export",
        "archive_id": (created.get("path") or "").split("/")[-1].rsplit(".", 1)[0],
        "size_bytes": int(created.get("size_bytes") or 0),
        "alert_count": int(created.get("alert_count") or 0),
        "image_count": int(created.get("image_count") or 0),
    })

    return {
        "path": created.get("path"),
        "manifest": created.get("manifest"),
        "files": (created.get("manifest") or {}).get("files", []),
    }


def import_user_archive(storage, user_id, archive_path, allow_overwrite=True):
    """Import one user archive by delegating to the restore service flow."""
    import modules.scheduler_core.state as scheduler_state_module

    _ = allow_overwrite  # kept for backward-compatible signature
    return apply_user_restore(
        storage,
        user_id,
        archive_path,
        actor_id="0",
        scheduler_state_module=scheduler_state_module,
        source="import",
        get_role_fn=lambda _uid: "developer",
    )
