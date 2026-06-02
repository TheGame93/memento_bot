import json
import os
import threading
from typing import Any, Dict, Optional

from modules.security.roles import (
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    ROLE_USER,
    pick_stronger_role,
    normalize_role,
)
from modules.shared.paths import WHITELIST_PATH

DEFAULT_WHITELIST_PATH = WHITELIST_PATH

_cache_lock = threading.Lock()
_cache = {
    "path": None,
    "mtime": None,
    "roles": {},
}


def _safe_user_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("@"):
        # Username-based auth is not supported yet.
        return None
    if not text.lstrip("-").isdigit():
        return None
    return text


def _assign_role(role_map: Dict[str, str], user_id: Any, role: str) -> None:
    uid = _safe_user_id(user_id)
    if not uid:
        return
    normalized = normalize_role(role)
    current = role_map.get(uid)
    if current is None:
        role_map[uid] = normalized
        return
    role_map[uid] = pick_stronger_role(current, normalized)


def _assign_many(role_map: Dict[str, str], values: Any, role: str) -> None:
    if values is None:
        return
    if isinstance(values, (list, tuple, set)):
        for value in values:
            _assign_role(role_map, value, role)
        return
    _assign_role(role_map, values, role)


def _parse_user_records(role_map: Dict[str, str], records: Any, fallback_role: str = ROLE_USER) -> None:
    if not isinstance(records, list):
        return
    for item in records:
        if isinstance(item, dict):
            _assign_role(role_map, item.get("id"), item.get("role", fallback_role))
        else:
            _assign_role(role_map, item, fallback_role)


def _parse_whitelist_payload(payload: Any) -> Dict[str, str]:
    role_map: Dict[str, str] = {}

    if isinstance(payload, list):
        _parse_user_records(role_map, payload, ROLE_USER)
        return role_map

    if not isinstance(payload, dict):
        return role_map

    # Compact role lists: {"developer": ..., "admins": [...], "users": [...]}
    _assign_many(role_map, payload.get("developer"), ROLE_DEVELOPER)
    _assign_many(role_map, payload.get("developers"), ROLE_DEVELOPER)
    # Legacy alias support (owner -> developer)
    _assign_many(role_map, payload.get("owner"), ROLE_DEVELOPER)
    _assign_many(role_map, payload.get("owners"), ROLE_DEVELOPER)
    _assign_many(role_map, payload.get("admin"), ROLE_ADMIN)
    _assign_many(role_map, payload.get("admins"), ROLE_ADMIN)
    _assign_many(role_map, payload.get("user"), ROLE_USER)
    _assign_many(role_map, payload.get("users"), ROLE_USER)

    # Nested role buckets: {"roles": {"developer": [...], "admin": [...], "user": [...]}}
    roles_bucket = payload.get("roles")
    if isinstance(roles_bucket, dict):
        _assign_many(role_map, roles_bucket.get("developer"), ROLE_DEVELOPER)
        _assign_many(role_map, roles_bucket.get("developers"), ROLE_DEVELOPER)
        _assign_many(role_map, roles_bucket.get("owner"), ROLE_DEVELOPER)
        _assign_many(role_map, roles_bucket.get("owners"), ROLE_DEVELOPER)
        _assign_many(role_map, roles_bucket.get("admin"), ROLE_ADMIN)
        _assign_many(role_map, roles_bucket.get("admins"), ROLE_ADMIN)
        _assign_many(role_map, roles_bucket.get("user"), ROLE_USER)
        _assign_many(role_map, roles_bucket.get("users"), ROLE_USER)

    # Explicit record list: {"users": [{"id": ..., "role": "..."}]}
    users_records = payload.get("users")
    if isinstance(users_records, list):
        _parse_user_records(role_map, users_records, ROLE_USER)

    return role_map


def _load_whitelist(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return _parse_whitelist_payload(payload)


def _get_mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def get_role_map(path: str = DEFAULT_WHITELIST_PATH, admin_id: Any = None) -> Dict[str, str]:
    """Load and cache the normalized user-role map from whitelist storage."""
    # Use absolute path so cache key stays stable even if cwd changes.
    target_path = os.path.abspath(path or DEFAULT_WHITELIST_PATH)
    mtime = _get_mtime(target_path)

    with _cache_lock:
        cached_path = _cache.get("path")
        cached_mtime = _cache.get("mtime")
        if cached_path == target_path and cached_mtime == mtime:
            role_map = dict(_cache.get("roles", {}))
        else:
            role_map = _load_whitelist(target_path)
            _cache["path"] = target_path
            _cache["mtime"] = mtime
            _cache["roles"] = dict(role_map)

    # Ensure ADMIN_ID from env remains a developer fallback.
    if admin_id:
        _assign_role(role_map, admin_id, ROLE_DEVELOPER)
    return role_map


def invalidate_role_map_cache(path: str = None) -> None:
    """Invalidate cached role-map data globally or for a specific path."""
    target_path = os.path.abspath(path) if path else None
    with _cache_lock:
        cached_path = _cache.get("path")
        if target_path is not None and cached_path not in {None, target_path}:
            return
        _cache["path"] = None
        _cache["mtime"] = None
        _cache["roles"] = {}


def get_user_role(user_id: Any, path: str = DEFAULT_WHITELIST_PATH, admin_id: Any = None) -> Optional[str]:
    """Return normalized role for a user id, or None when unauthorized."""
    uid = _safe_user_id(user_id)
    if not uid:
        return None
    role_map = get_role_map(path=path, admin_id=admin_id)
    return role_map.get(uid)


def is_authorized(user_id: Any, path: str = DEFAULT_WHITELIST_PATH, admin_id: Any = None) -> bool:
    """Return whether the user id is present in the effective role map."""
    return get_user_role(user_id, path=path, admin_id=admin_id) is not None


def is_admin_or_developer(user_id: Any, path: str = DEFAULT_WHITELIST_PATH, admin_id: Any = None) -> bool:
    """Return whether the user has admin-or-developer effective access."""
    role = get_user_role(user_id, path=path, admin_id=admin_id)
    return role in {ROLE_DEVELOPER, ROLE_ADMIN}
