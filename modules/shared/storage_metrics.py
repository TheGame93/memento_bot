import glob
import os
import re

from modules.shared.paths import BACKUP_DIR, DATA_DIR, SYSTEM_LOG_DIR, USER_BACKUP_DIR, USER_LOG_DIR


def get_dir_size_bytes(path):
    """Return recursive directory size in bytes, ignoring inaccessible paths."""
    total = 0
    if not path:
        return 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_dir_size_bytes(entry.path)
    except (FileNotFoundError, OSError):
        return 0
    return total


def get_logs_size_bytes(path):
    """Return recursive size of `.log` and rotated log files in bytes."""
    total = 0
    if not path:
        return 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                name = entry.name
                if name.endswith(".log") or ".log." in name:
                    total += entry.stat().st_size
            elif entry.is_dir():
                total += get_logs_size_bytes(entry.path)
    except (FileNotFoundError, OSError):
        return 0
    return total


def get_files_size_bytes(paths):
    """Return total size in bytes for existing files in the provided list."""
    total = 0
    for path in paths or []:
        if not path:
            continue
        try:
            total += os.path.getsize(path)
        except (FileNotFoundError, OSError):
            continue
    return total


def get_user_data_dir_bytes(user_id):
    """Return total bytes used by a user's data directory."""
    path = os.path.join(DATA_DIR, str(user_id))
    return get_dir_size_bytes(path)


def get_user_json_files_bytes(user_id):
    """Return total bytes of top-level JSON files in a user's data directory."""
    pattern = os.path.join(DATA_DIR, str(user_id), "*.json")
    files = [path for path in glob.glob(pattern) if os.path.isfile(path)]
    return get_files_size_bytes(files)


def get_user_json_backup_files_bytes(user_id):
    """Return total bytes of top-level JSON backup files in a user's data directory."""
    pattern = os.path.join(DATA_DIR, str(user_id), "*.json.bak")
    files = []
    for path in glob.glob(pattern):
        if not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        if ".corrupt." in name:
            continue
        files.append(path)
    return get_files_size_bytes(files)


def _sanitize_user_log_id(user_id):
    raw = str(user_id or "").strip()
    if not raw:
        return "unknown"
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("._-")
    if not normalized:
        return "unknown"
    return normalized[:128]


def _default_user_event_log_path(user_id):
    safe_id = _sanitize_user_log_id(user_id)
    return os.path.join(USER_LOG_DIR, f"{safe_id}_events.log")


def _resolve_user_event_log_path(storage, user_id):
    if storage is not None:
        getter = getattr(storage, "get_user_event_log_path", None)
        if callable(getter):
            try:
                path = getter(user_id)
                if isinstance(path, str) and path.strip():
                    return path
            except Exception:
                pass
    return _default_user_event_log_path(user_id)


def get_user_event_log_paths(storage, user_id):
    """Return event-log file paths (including rotations) for the target user."""
    base_path = _resolve_user_event_log_path(storage, user_id)
    candidates = sorted(glob.glob(base_path + "*"))
    return [path for path in candidates if os.path.isfile(path)]


def get_user_event_logs_bytes(storage, user_id):
    """Return total bytes consumed by a user's event log files."""
    return get_files_size_bytes(get_user_event_log_paths(storage, user_id))


def get_user_backup_dir_bytes(user_id):
    """Return total bytes used by a user's backup directory."""
    path = os.path.join(USER_BACKUP_DIR, str(user_id))
    return get_dir_size_bytes(path)


def get_data_root_bytes():
    """Return total bytes used under the global data root."""
    return get_dir_size_bytes(DATA_DIR)


def get_backup_root_bytes():
    """Return total bytes used under the global backup root."""
    return get_dir_size_bytes(BACKUP_DIR)


def get_system_log_root_bytes():
    """Return total bytes used under the system log root."""
    return get_dir_size_bytes(SYSTEM_LOG_DIR)


def get_user_log_root_bytes():
    """Return total bytes used under the user log root."""
    return get_dir_size_bytes(USER_LOG_DIR)
