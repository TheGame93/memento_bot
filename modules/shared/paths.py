import hashlib
import os


def _project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


PROJECT_ROOT = _project_root()
DATA_DIR = os.path.abspath(os.getenv("BOT_DATA_DIR", os.path.join(PROJECT_ROOT, "data")))
BACKUP_DIR = os.path.abspath(os.getenv("BOT_BACKUP_DIR", os.path.join(PROJECT_ROOT, "backups")))
GLOBAL_LOCK_DIR = os.path.abspath(
    os.getenv("BOT_GLOBAL_LOCK_DIR", "/tmp/recurring_alert_bot_locks")
)
SYSTEM_LOG_DIR = os.path.join(DATA_DIR, "systemlog.d")
USER_LOG_DIR = os.path.join(DATA_DIR, "userlog.d")
USER_BACKUP_DIR = os.path.join(BACKUP_DIR, "users")
SYSTEM_DATA_DIR = os.path.join(DATA_DIR, "system")
WHITELIST_PATH = os.path.join(SYSTEM_DATA_DIR, "whitelist.json")
WHITELIST_REQUESTS_PATH = os.path.join(SYSTEM_DATA_DIR, "whitelist_requests.json")
WHITELIST_INVITES_PATH = os.path.join(SYSTEM_DATA_DIR, "whitelist_invites.json")
WHITELIST_REQUEST_STATE_PATH = os.path.join(SYSTEM_DATA_DIR, "whitelist_request_state.json")

_TOKEN_LOCK_HASH_LEN = 16


def token_lock_hash_prefix(token):
    """Return the first 16 hex chars of the SHA256 hash of token for use in lock filenames."""
    raw = str(token) if token is not None else ""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:_TOKEN_LOCK_HASH_LEN]


def token_global_lock_path(token):
    """Return the full path to the token-scoped global lock file under GLOBAL_LOCK_DIR."""
    return os.path.join(GLOBAL_LOCK_DIR, f"mainbot_{token_lock_hash_prefix(token)}.lock")
