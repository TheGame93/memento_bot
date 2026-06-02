import os

from modules.shared.paths import BACKUP_DIR, USER_BACKUP_DIR

BACKUP_FOLDERS = ("local", "exports", "monthly", "pre_import")


def get_backup_root():
    """Return the configured global backup root directory."""
    return BACKUP_DIR


def get_user_backup_root(user_id):
    """Return the backup root directory path for a specific user."""
    return os.path.join(USER_BACKUP_DIR, str(user_id))


def ensure_user_backup_root(user_id):
    """Ensure and return the backup root directory for a specific user."""
    path = get_user_backup_root(user_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_user_backup_folder(user_id, folder):
    """Return and ensure a canonical per-user backup subfolder path."""
    if folder not in BACKUP_FOLDERS:
        raise ValueError(f"unsupported backup folder: {folder}")
    root = ensure_user_backup_root(user_id)
    path = os.path.join(root, folder)
    os.makedirs(path, exist_ok=True)
    return path


def get_system_backup_dir():
    """Return and ensure the system backup root directory."""
    path = os.path.join(BACKUP_DIR, "system")
    os.makedirs(path, exist_ok=True)
    return path
