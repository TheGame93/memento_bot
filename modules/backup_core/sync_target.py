import os
import shutil
from datetime import datetime

from modules.systemlog import log_system


def get_sync_dir():
    """Return external backup sync root configured by environment variable."""
    return os.getenv("BOT_EXTERNAL_BACKUP_DIR")


def sync_backup_file(src_path, user_id, now=None):
    """Copy a backup file to external sync target and report structured outcome."""
    if now is None:
        now = datetime.now()
    dest_root = get_sync_dir()
    if not dest_root:
        return {"ok": False, "skipped": True, "reason": "not_configured"}

    if not os.path.isfile(src_path):
        return {"ok": False, "error": "source_missing"}

    dest_dir = os.path.join(dest_root, "users", str(user_id))
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, os.path.basename(src_path))

    try:
        shutil.copy2(src_path, dest_path)
        log_system("backup", "sync_target_copied", {
            "user_id": str(user_id),
            "source": src_path,
            "dest": dest_path,
        })
        return {"ok": True, "dest": dest_path}
    except Exception as exc:
        log_system("backup", "sync_target_failed", {
            "user_id": str(user_id),
            "source": src_path,
            "error": str(exc),
        }, level="ERROR")
        return {"ok": False, "error": str(exc)}
