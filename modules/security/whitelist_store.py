import json
import os
import threading
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.security.authz import (
    DEFAULT_WHITELIST_PATH,
    get_role_map,
    invalidate_role_map_cache,
)
from modules.security.roles import ROLE_DEVELOPER, ROLE_USER, normalize_role, pick_stronger_role
from modules.shared.paths import (
    SYSTEM_DATA_DIR,
    WHITELIST_PATH,
    WHITELIST_REQUESTS_PATH,
    WHITELIST_INVITES_PATH,
    WHITELIST_REQUEST_STATE_PATH,
)

_LOCK = threading.Lock()


def _safe_user_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("@"):
        text = text[1:]
    if not text.lstrip("-").isdigit():
        return None
    return text


def _normalize_username(username: Any) -> Optional[str]:
    if username is None:
        return None
    text = str(username).strip()
    if not text:
        return None
    if text.startswith("@"):
        text = text[1:]
    return text or None


def _normalize_username_key(username: Any) -> Optional[str]:
    normalized = _normalize_username(username)
    if not normalized:
        return None
    return normalized.lower()


def _normalize_invite_identity(user_id: Any = None, username: Any = None):
    uid = _safe_user_id(user_id)
    uname = _normalize_username(username)
    uname_key = uname.lower() if uname else None
    return uid, uname, uname_key


def _is_valid_username(username: Any) -> bool:
    normalized = _normalize_username(username)
    if not normalized:
        return False
    if not (5 <= len(normalized) <= 32):
        return False
    for ch in normalized:
        if not (ch.isalnum() or ch == "_"):
            return False
    return True


def _ensure_system_dir() -> None:
    os.makedirs(SYSTEM_DATA_DIR, exist_ok=True)


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> bool:
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        return True
    except Exception:
        return False


def load_whitelist_invites(path: str = WHITELIST_INVITES_PATH) -> Dict[str, Any]:
    """Load whitelist invites payload with a stable default structure."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {"invites": []}
    except Exception:
        return {"invites": []}
    if not isinstance(payload, dict):
        return {"invites": []}
    invites = payload.get("invites")
    if not isinstance(invites, list):
        payload["invites"] = []
    return payload


def list_whitelist_invites(path: str = WHITELIST_INVITES_PATH) -> List[Dict[str, Any]]:
    """Return invite records filtered to dictionary entries."""
    payload = load_whitelist_invites(path)
    invites = payload.get("invites", [])
    return [r for r in invites if isinstance(r, dict)]


def upsert_whitelist_invite(
    user_id: Any = None,
    username: Any = None,
    display_name: Any = None,
    role: Optional[str] = None,
    invited_by: Any = None,
    now_iso: Optional[str] = None,
    path: str = WHITELIST_INVITES_PATH,
) -> bool:
    """Create or update a whitelist invite matched by user id or username."""
    uid, uname, uname_key = _normalize_invite_identity(user_id, username)
    if uname and not _is_valid_username(uname):
        return False
    if not uid and not uname_key:
        return False
    normalized_role = normalize_role(role) if role else ROLE_USER
    timestamp = now_iso or datetime.now().isoformat()
    invited_by = _safe_user_id(invited_by)
    display_name = (str(display_name).strip() if display_name else None) or None

    with _LOCK:
        payload = load_whitelist_invites(path)
        invites = [r for r in payload.get("invites", []) if isinstance(r, dict)]
        found = None
        if uid:
            for record in invites:
                if str(record.get("user_id")) == uid:
                    found = record
                    break
        if not found and uname_key:
            for record in invites:
                if record.get("username") == uname_key:
                    found = record
                    break
        if found:
            found["role"] = normalized_role
            found["user_id"] = uid or found.get("user_id")
            found["username"] = uname_key or found.get("username")
            if display_name:
                found["display_name"] = display_name
            found["invited_by"] = invited_by or found.get("invited_by")
            found["invited_at"] = timestamp
        else:
            invites.append({
                "user_id": uid,
                "username": uname_key,
                "display_name": display_name,
                "role": normalized_role,
                "invited_by": invited_by,
                "invited_at": timestamp,
            })
        payload["invites"] = invites
        _ensure_system_dir()
        return _atomic_write_json(path, payload)


def find_whitelist_invite(
    user_id: Any = None,
    username: Any = None,
    path: str = WHITELIST_INVITES_PATH,
) -> Optional[Dict[str, Any]]:
    """Return the first invite matching user id or normalized username."""
    uid, _uname, uname_key = _normalize_invite_identity(user_id, username)
    if not uid and not uname_key:
        return None
    invites = list_whitelist_invites(path)
    if uid:
        for record in invites:
            if str(record.get("user_id")) == uid:
                return record
    if uname_key:
        for record in invites:
            if record.get("username") == uname_key:
                return record
    return None


def remove_whitelist_invite(
    user_id: Any = None,
    username: Any = None,
    path: str = WHITELIST_INVITES_PATH,
) -> bool:
    """Remove invites matching user id or normalized username."""
    uid, _uname, uname_key = _normalize_invite_identity(user_id, username)
    if not uid and not uname_key:
        return False
    with _LOCK:
        payload = load_whitelist_invites(path)
        invites = [r for r in payload.get("invites", []) if isinstance(r, dict)]
        def _keep(record):
            if uid and str(record.get("user_id")) == uid:
                return False
            if uname_key and record.get("username") == uname_key:
                return False
            return True
        new_invites = [r for r in invites if _keep(r)]
        if len(new_invites) == len(invites):
            return False
        payload["invites"] = new_invites
        _ensure_system_dir()
        return _atomic_write_json(path, payload)


def load_whitelist_requests(path: str = WHITELIST_REQUESTS_PATH) -> Dict[str, Any]:
    """Load whitelist request payload with a stable default structure."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {"requests": []}
    except Exception:
        return {"requests": []}
    if not isinstance(payload, dict):
        return {"requests": []}
    requests = payload.get("requests")
    if not isinstance(requests, list):
        payload["requests"] = []
    return payload


def list_whitelist_requests(path: str = WHITELIST_REQUESTS_PATH) -> List[Dict[str, Any]]:
    """Return whitelist request records filtered to dictionary entries."""
    payload = load_whitelist_requests(path)
    requests = payload.get("requests", [])
    return [r for r in requests if isinstance(r, dict)]


def find_whitelist_request(user_id: Any, path: str = WHITELIST_REQUESTS_PATH) -> Optional[Dict[str, Any]]:
    """Return the pending whitelist request record for the target user id."""
    uid = _safe_user_id(user_id)
    if not uid:
        return None
    for record in list_whitelist_requests(path=path):
        if str(record.get("user_id")) == uid:
            return record
    return None


def load_whitelist_request_state(path: str = WHITELIST_REQUEST_STATE_PATH) -> Dict[str, Any]:
    """Load whitelist request-state payload with stable requests/meta buckets."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {"requests": {}, "meta": {}}
    except Exception:
        return {"requests": {}, "meta": {}}
    if not isinstance(payload, dict):
        return {"requests": {}, "meta": {}}
    requests = payload.get("requests")
    if not isinstance(requests, dict):
        payload["requests"] = {}
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        payload["meta"] = {}
    return payload


def _write_whitelist_request_state(payload: Dict[str, Any], path: str = WHITELIST_REQUEST_STATE_PATH) -> bool:
    _ensure_system_dir()
    return _atomic_write_json(path, payload)


def get_whitelist_request_state(user_id: Any, path: str = WHITELIST_REQUEST_STATE_PATH) -> Optional[Dict[str, Any]]:
    """Return request-state metadata for a user id, if present."""
    uid = _safe_user_id(user_id)
    if not uid:
        return None
    payload = load_whitelist_request_state(path=path)
    requests = payload.get("requests", {})
    if isinstance(requests, dict):
        return requests.get(uid)
    return None


def update_whitelist_request_state_meta(
    updates: Dict[str, Any],
    path: str = WHITELIST_REQUEST_STATE_PATH,
) -> bool:
    """Merge global request-state metadata updates atomically."""
    if not isinstance(updates, dict):
        return False
    with _LOCK:
        payload = load_whitelist_request_state(path=path)
        meta = payload.get("meta") or {}
        meta.update(updates)
        payload["meta"] = meta
        return _write_whitelist_request_state(payload, path=path)


def get_whitelist_request_state_meta(path: str = WHITELIST_REQUEST_STATE_PATH) -> Dict[str, Any]:
    """Return global request-state metadata with dict fallback guarantees."""
    payload = load_whitelist_request_state(path=path)
    meta = payload.get("meta") or {}
    return meta if isinstance(meta, dict) else {}


def upsert_whitelist_request(
    user_id: Any,
    username: Any = None,
    display_name: Any = None,
    custom_name: Any = None,
    request_message: Any = None,
    label_order: Any = None,
    now_iso: Optional[str] = None,
    path: str = WHITELIST_REQUESTS_PATH,
) -> bool:
    """Create or refresh a pending whitelist request record for a user."""
    uid = _safe_user_id(user_id)
    if not uid:
        return False
    normalized_username = _normalize_username(username)
    display_name = (str(display_name).strip() if display_name else None) or None
    custom_name = (str(custom_name).strip() if custom_name else None) or None
    request_message = (str(request_message).strip() if request_message is not None else None)
    timestamp = now_iso or datetime.now().isoformat()

    with _LOCK:
        payload = load_whitelist_requests(path)
        requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
        found = None
        for record in requests:
            if str(record.get("user_id")) == uid:
                found = record
                break

        if found:
            found["last_requested_at"] = timestamp
            found["request_count"] = int(found.get("request_count", 0)) + 1
            if normalized_username:
                found["username"] = normalized_username
            if display_name:
                found["display_name"] = display_name
            if custom_name is not None:
                found["custom_name"] = custom_name
            if request_message is not None:
                found["request_message"] = request_message or None
            if label_order is not None:
                found["label_order"] = label_order
        else:
            requests.append({
                "user_id": uid,
                "username": normalized_username,
                "display_name": display_name,
                "custom_name": custom_name,
                "request_message": request_message or None,
                "label_order": label_order,
                "first_requested_at": timestamp,
                "last_requested_at": timestamp,
                "request_count": 1,
            })

        payload["requests"] = requests
        _ensure_system_dir()
        return _atomic_write_json(path, payload)


def update_whitelist_request(
    user_id: Any,
    *,
    custom_name: Any = None,
    label_order: Any = None,
    path: str = WHITELIST_REQUESTS_PATH,
    state_path: str = WHITELIST_REQUEST_STATE_PATH,
) -> bool:
    """Update editable request fields and sync mirrored request-state snapshot."""
    uid = _safe_user_id(user_id)
    if not uid:
        return False
    custom_name = (str(custom_name).strip() if custom_name is not None else None)
    with _LOCK:
        payload = load_whitelist_requests(path)
        requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
        found = None
        for record in requests:
            if str(record.get("user_id")) == uid:
                found = record
                break
        if not found:
            return False
        if custom_name is not None:
            found["custom_name"] = custom_name or None
        if label_order is not None:
            found["label_order"] = label_order
        payload["requests"] = requests
        _ensure_system_dir()
        ok = _atomic_write_json(path, payload)
        if not ok:
            return False

        # Keep request-state snapshot aligned with pending edits.
        state_payload = load_whitelist_request_state(path=state_path)
        state_requests = state_payload.get("requests") or {}
        state_record = state_requests.get(uid)
        if isinstance(state_record, dict):
            timestamp = datetime.now().isoformat()
            if custom_name is not None:
                state_record["custom_name"] = custom_name or None
            if label_order is not None:
                state_record["label_order"] = label_order
            state_record["updated_at"] = timestamp
            state_requests[uid] = state_record
            state_payload["requests"] = state_requests
            _write_whitelist_request_state(state_payload, path=state_path)

        return True


def update_whitelist_request_message(
    user_id: Any,
    request_message: Any,
    *,
    now_iso: Optional[str] = None,
    requests_path: str = WHITELIST_REQUESTS_PATH,
    state_path: str = WHITELIST_REQUEST_STATE_PATH,
) -> Dict[str, Any]:
    """Update pending request message text and synchronize request-state mirrors.

    Returns a status payload with `status`, `request_ok`, and `state_ok` flags.
    `status` can be `invalid`, `not_found`, `not_pending`, `write_failed`,
    `updated`, or `updated_partial`.
    """
    uid = _safe_user_id(user_id)
    if not uid:
        return {
            "status": "invalid",
            "request_ok": False,
            "state_ok": False,
            "record": None,
            "state": None,
        }

    normalized_message = (str(request_message).strip() if request_message is not None else None)
    timestamp = now_iso or datetime.now().isoformat()

    with _LOCK:
        payload = load_whitelist_requests(path=requests_path)
        requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
        found = None
        for record in requests:
            if str(record.get("user_id")) == uid:
                found = record
                break
        if not isinstance(found, dict):
            return {
                "status": "not_found",
                "request_ok": False,
                "state_ok": False,
                "record": None,
                "state": get_whitelist_request_state(uid, path=state_path),
            }

        state_payload = load_whitelist_request_state(path=state_path)
        state_requests = state_payload.get("requests") or {}
        state_record = state_requests.get(uid) if isinstance(state_requests, dict) else None
        if isinstance(state_record, dict):
            state_status = str(state_record.get("status") or "pending").strip().lower()
            if state_status in {"approved", "rejected"}:
                return {
                    "status": "not_pending",
                    "request_ok": False,
                    "state_ok": False,
                    "record": dict(found),
                    "state": state_record,
                }

        found["request_message"] = normalized_message or None
        record = dict(found)
        payload["requests"] = requests
        req_ok = _atomic_write_json(requests_path, payload)
        if not req_ok:
            return {
                "status": "write_failed",
                "request_ok": False,
                "state_ok": False,
                "record": record,
                "state": state_record if isinstance(state_record, dict) else None,
            }

        if not isinstance(state_record, dict):
            state_record = {"status": "pending", "created_at": record.get("first_requested_at") or timestamp}

        state_record.update({
            "status": "pending",
            "updated_at": timestamp,
            "request_count": record.get("request_count"),
            "first_requested_at": record.get("first_requested_at"),
            "last_requested_at": record.get("last_requested_at"),
            "username": record.get("username"),
            "display_name": record.get("display_name"),
            "custom_name": record.get("custom_name"),
            "request_message": record.get("request_message"),
            "label_order": record.get("label_order"),
        })
        state_requests[uid] = state_record
        state_payload["requests"] = state_requests
        state_ok = _write_whitelist_request_state(state_payload, path=state_path)

    return {
        "status": "updated" if state_ok else "updated_partial",
        "request_ok": True,
        "state_ok": bool(state_ok),
        "record": record,
        "state": state_record,
    }


def ensure_whitelist_request(
    user_id: Any,
    username: Any = None,
    display_name: Any = None,
    custom_name: Any = None,
    request_message: Any = None,
    label_order: Any = None,
    now_iso: Optional[str] = None,
    requests_path: str = WHITELIST_REQUESTS_PATH,
    state_path: str = WHITELIST_REQUEST_STATE_PATH,
) -> Dict[str, Any]:
    """Ensure a pending whitelist request exists and reset resolved-cycle state safely.

    Returns `{ok, created, record, state, state_ok}` where `created` signals a
    new pending cycle and `state_ok` indicates whether mirrored state persistence
    succeeded after request persistence.
    """
    uid = _safe_user_id(user_id)
    if not uid:
        return {"ok": False, "created": False, "record": None, "state": None, "state_ok": False}
    normalized_username = _normalize_username(username)
    display_name = (str(display_name).strip() if display_name else None) or None
    custom_name = (str(custom_name).strip() if custom_name else None) or None
    request_message = (str(request_message).strip() if request_message is not None else None)
    timestamp = now_iso or datetime.now().isoformat()

    with _LOCK:
        payload = load_whitelist_requests(path=requests_path)
        requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
        found = None
        for record in requests:
            if str(record.get("user_id")) == uid:
                found = record
                break

        created = False
        if found:
            found["last_requested_at"] = timestamp
            found["request_count"] = int(found.get("request_count", 0)) + 1
            if normalized_username:
                found["username"] = normalized_username
            if display_name:
                found["display_name"] = display_name
            if custom_name is not None:
                found["custom_name"] = custom_name
            if request_message is not None:
                found["request_message"] = request_message or None
            if label_order is not None:
                found["label_order"] = label_order
            record = dict(found)
        else:
            record = {
                "user_id": uid,
                "username": normalized_username,
                "display_name": display_name,
                "custom_name": custom_name,
                "request_message": request_message or None,
                "label_order": label_order,
                "first_requested_at": timestamp,
                "last_requested_at": timestamp,
                "request_count": 1,
            }
            requests.append(record)
            created = True

        # Load state BEFORE persisting request, so we can recover history from
        # prior resolution snapshots and correct the record before writing.
        state_payload = load_whitelist_request_state(path=state_path)
        state_requests = state_payload.get("requests") or {}
        state_record = state_requests.get(uid) if isinstance(state_requests, dict) else None
        if not isinstance(state_record, dict):
            state_record = {"status": "pending", "created_at": timestamp}
        else:
            # Reset any prior resolution/notification metadata when a new request cycle starts.
            if state_record.get("status") in {"approved", "rejected"}:
                # Extract history from resolution snapshot BEFORE deleting it.
                prior_snapshot = state_record.get("request") or {}
                prior_first = (
                    prior_snapshot.get("first_requested_at")
                    or state_record.get("first_requested_at")
                )
                prior_count = (
                    prior_snapshot.get("request_count")
                    or state_record.get("request_count")
                    or 0
                )
                for key in (
                    "resolved_at",
                    "resolved_by",
                    "resolved_by_label",
                    "resolved_role",
                    "request",
                ):
                    state_record.pop(key, None)
                state_record.pop("first_notified_at", None)
                state_record.pop("last_notified_at", None)
                state_record.pop("message_refs", None)
                # Carry forward history into the NEW request record.
                if created and prior_first:
                    record["first_requested_at"] = prior_first
                if created:
                    record["request_count"] = int(prior_count) + 1

        # Persist request with corrected history values.
        payload["requests"] = requests
        req_ok = _atomic_write_json(requests_path, payload)

        state_record.update({
            "status": "pending",
            "updated_at": timestamp,
            "request_count": record.get("request_count"),
            "first_requested_at": record.get("first_requested_at"),
            "last_requested_at": record.get("last_requested_at"),
            "username": record.get("username"),
            "display_name": record.get("display_name"),
            "custom_name": record.get("custom_name"),
            "request_message": record.get("request_message"),
            "label_order": record.get("label_order"),
        })
        state_requests[uid] = state_record
        state_payload["requests"] = state_requests
        state_ok = _write_whitelist_request_state(state_payload, path=state_path)

    return {
        "ok": bool(req_ok),
        "created": created,
        "record": record,
        "state": state_record,
        "state_ok": bool(state_ok),
    }


def register_whitelist_request_message(
    user_id: Any,
    chat_id: Any,
    message_id: Any,
    now_iso: Optional[str] = None,
    path: str = WHITELIST_REQUEST_STATE_PATH,
) -> bool:
    """Register one admin notification message reference for a request."""
    uid = _safe_user_id(user_id)
    if not uid:
        return False
    timestamp = now_iso or datetime.now().isoformat()
    with _LOCK:
        payload = load_whitelist_request_state(path=path)
        requests = payload.get("requests") or {}
        record = requests.get(uid)
        if not isinstance(record, dict):
            record = {"status": "pending", "created_at": timestamp}
        refs = record.get("message_refs")
        if not isinstance(refs, list):
            refs = []
        ref = {"chat_id": str(chat_id), "message_id": int(message_id), "sent_at": timestamp}
        if not any(r.get("chat_id") == ref["chat_id"] and r.get("message_id") == ref["message_id"] for r in refs):
            refs.append(ref)
        record["message_refs"] = refs
        requests[uid] = record
        payload["requests"] = requests
        return _write_whitelist_request_state(payload, path=path)


def set_whitelist_request_notified(
    user_id: Any,
    now_iso: Optional[str] = None,
    path: str = WHITELIST_REQUEST_STATE_PATH,
) -> bool:
    """Mark request notification timestamps for first/last notify tracking."""
    uid = _safe_user_id(user_id)
    if not uid:
        return False
    timestamp = now_iso or datetime.now().isoformat()
    with _LOCK:
        payload = load_whitelist_request_state(path=path)
        requests = payload.get("requests") or {}
        record = requests.get(uid)
        if not isinstance(record, dict):
            record = {"status": "pending", "created_at": timestamp}
        if not record.get("first_notified_at"):
            record["first_notified_at"] = timestamp
        record["last_notified_at"] = timestamp
        requests[uid] = record
        payload["requests"] = requests
        return _write_whitelist_request_state(payload, path=path)


def prune_whitelist_request_message_refs(
    user_id: Any,
    message_refs: List[Dict[str, Any]],
    path: str = WHITELIST_REQUEST_STATE_PATH,
) -> bool:
    """Replace stored request message references with the surviving subset."""
    uid = _safe_user_id(user_id)
    if not uid:
        return False
    with _LOCK:
        payload = load_whitelist_request_state(path=path)
        requests = payload.get("requests") or {}
        record = requests.get(uid)
        if not isinstance(record, dict):
            return False
        record["message_refs"] = message_refs
        requests[uid] = record
        payload["requests"] = requests
        return _write_whitelist_request_state(payload, path=path)


def resolve_whitelist_request(
    user_id: Any,
    action: str,
    actor_id: Any = None,
    actor_role: Any = None,
    actor_label: Optional[str] = None,
    now_iso: Optional[str] = None,
    requests_path: str = WHITELIST_REQUESTS_PATH,
    state_path: str = WHITELIST_REQUEST_STATE_PATH,
) -> Dict[str, Any]:
    """Resolve a pending whitelist request and persist a resolution snapshot.

    Returns a status payload where `status` can be `invalid`, `not_found`,
    `already_resolved`, `resolved`, or `resolved_partial`, plus `record/state`
    snapshots for downstream notification rendering.
    """
    uid = _safe_user_id(user_id)
    if not uid:
        return {"status": "invalid", "record": None, "state": None}
    action = str(action).strip().lower()
    if action not in {"approved", "rejected"}:
        return {"status": "invalid", "record": None, "state": None}
    timestamp = now_iso or datetime.now().isoformat()

    with _LOCK:
        payload = load_whitelist_requests(path=requests_path)
        requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
        found = None
        for record in requests:
            if str(record.get("user_id")) == uid:
                found = record
                break

        state_payload = load_whitelist_request_state(path=state_path)
        state_requests = state_payload.get("requests") or {}
        state_record = state_requests.get(uid)
        if not isinstance(state_record, dict):
            state_record = {}

        # If already resolved, return existing resolution info.
        if state_record.get("status") in {"approved", "rejected"}:
            if found:
                payload["requests"] = [r for r in requests if str(r.get("user_id")) != uid]
                _atomic_write_json(requests_path, payload)
            return {"status": "already_resolved", "record": found, "state": state_record}

        if not found:
            return {"status": "not_found", "record": None, "state": state_record}

        # Resolve: remove from pending list.
        payload["requests"] = [r for r in requests if str(r.get("user_id")) != uid]
        req_ok = _atomic_write_json(requests_path, payload)

        # Store resolution snapshot.
        snapshot = {
            "user_id": uid,
            "username": found.get("username"),
            "display_name": found.get("display_name"),
            "custom_name": found.get("custom_name"),
            "request_message": found.get("request_message"),
            "label_order": found.get("label_order"),
            "request_count": found.get("request_count"),
            "first_requested_at": found.get("first_requested_at"),
            "last_requested_at": found.get("last_requested_at"),
        }

        state_record.update({
            "status": action,
            "updated_at": timestamp,
            "resolved_at": timestamp,
            "resolved_by": _safe_user_id(actor_id),
            "resolved_by_label": actor_label,
            "resolved_role": str(actor_role) if actor_role is not None else None,
            "request": snapshot,
        })
        state_requests[uid] = state_record
        state_payload["requests"] = state_requests
        state_ok = _write_whitelist_request_state(state_payload, path=state_path)

    return {
        "status": "resolved" if req_ok and state_ok else "resolved_partial",
        "record": found,
        "state": state_record,
    }


def remove_whitelist_request(user_id: Any, path: str = WHITELIST_REQUESTS_PATH) -> bool:
    """Remove one pending whitelist request by user id."""
    uid = _safe_user_id(user_id)
    if not uid:
        return False
    with _LOCK:
        payload = load_whitelist_requests(path)
        requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
        new_requests = [r for r in requests if str(r.get("user_id")) != uid]
        if len(new_requests) == len(requests):
            return False
        payload["requests"] = new_requests
        _ensure_system_dir()
        return _atomic_write_json(path, payload)


def _coerce_id_for_write(value: str) -> Any:
    if value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _load_json_status(path: str) -> Dict[str, Any]:
    target_path = os.path.abspath(path)
    try:
        with open(target_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {"status": "missing", "path": target_path}
    except json.JSONDecodeError:
        return {"status": "corrupt", "path": target_path}
    except Exception as exc:
        return {
            "status": "error",
            "reason": "read_failed",
            "path": target_path,
            "error_type": type(exc).__name__,
        }
    return {"status": "valid", "path": target_path, "payload": payload}


def _publish_new_whitelist_payload(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    target_path = os.path.abspath(path or WHITELIST_PATH)
    dir_path = os.path.dirname(target_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_path or None, prefix=".whitelist.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())

        try:
            os.link(tmp_path, target_path)
        except FileExistsError:
            existing_status = _load_json_status(target_path)
            if existing_status["status"] == "valid":
                return {"status": "exists", "path": target_path}
            if existing_status["status"] == "corrupt":
                return {"status": "corrupt", "path": target_path}
            return {
                "status": "error",
                "reason": "read_failed",
                "path": target_path,
                "error_type": existing_status.get("error_type", "OSError"),
            }
        except Exception as exc:
            return {
                "status": "error",
                "reason": "write_failed",
                "path": target_path,
                "error_type": type(exc).__name__,
            }

        return {"status": "created", "path": target_path}
    except Exception as exc:
        return {
            "status": "error",
            "reason": "write_failed",
            "path": target_path,
            "error_type": type(exc).__name__,
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def list_whitelist_users(path: str = DEFAULT_WHITELIST_PATH) -> List[Dict[str, Any]]:
    """List whitelist users as sorted `{id, role}` entries."""
    role_map = get_role_map(path=path, admin_id=None)
    entries = []
    for uid, role in role_map.items():
        entries.append({
            "id": uid,
            "role": role,
        })
    return sorted(entries, key=lambda item: int(item["id"]) if str(item["id"]).isdigit() else str(item["id"]))


def _build_whitelist_payload(role_map: Dict[str, str]) -> Dict[str, Any]:
    users = []
    for uid, role in role_map.items():
        users.append({
            "id": _coerce_id_for_write(str(uid)),
            "role": normalize_role(role),
        })
    users_sorted = sorted(users, key=lambda item: int(item["id"]) if str(item["id"]).isdigit() else str(item["id"]))
    return {"users": users_sorted}


def ensure_whitelist_seeded(admin_id: Any, path: str = WHITELIST_PATH) -> dict:
    """Seed whitelist storage with the env developer when first-start auth has no persisted file.

    Returns a structured status payload describing whether the file already exists,
    was created, was corrupt, was skipped because the admin id is invalid, or failed.
    """
    uid = _safe_user_id(admin_id)
    target_path = os.path.abspath(path or WHITELIST_PATH)
    if not uid:
        return {"status": "skipped", "reason": "invalid_admin_id", "path": target_path}

    payload = {
        "users": [{
            "id": _coerce_id_for_write(uid),
            "role": ROLE_DEVELOPER,
        }],
    }
    publish_status = _publish_new_whitelist_payload(target_path, payload)
    if publish_status["status"] == "created":
        invalidate_role_map_cache(path=target_path)
        return {"status": "seeded", "path": target_path}
    return publish_status


def reconcile_startup_whitelist(admin_id: Any, path: str = WHITELIST_PATH) -> dict:
    """Ensure canonical whitelist storage is initialized for startup, seeding it with admin_id on first run."""
    uid = _safe_user_id(admin_id)
    target_path = os.path.abspath(path or WHITELIST_PATH)
    canonical_status = _load_json_status(target_path)

    if canonical_status["status"] == "corrupt":
        return {"status": "corrupt", "path": target_path}
    if canonical_status["status"] == "error":
        return dict(canonical_status)
    if canonical_status["status"] == "missing":
        if not uid:
            return {"status": "skipped", "reason": "invalid_admin_id", "path": target_path}
        return ensure_whitelist_seeded(uid, path=target_path)

    return {"status": "exists", "path": target_path}


def add_whitelist_user(
    user_id: Any,
    role: Optional[str] = None,
    path: str = DEFAULT_WHITELIST_PATH,
    force: bool = False,
) -> bool:
    """Add or upgrade a whitelist user role with optional force override."""
    uid = _safe_user_id(user_id)
    if not uid:
        return False
    normalized_role = normalize_role(role) if role else ROLE_USER
    with _LOCK:
        role_map = get_role_map(path=path, admin_id=None)
        current = role_map.get(uid)
        if current:
            if force:
                if normalize_role(current) == normalized_role:
                    return True
                role_map[uid] = normalized_role
            else:
                stronger = pick_stronger_role(current, normalized_role)
                if stronger == current:
                    return True
                role_map[uid] = stronger
        else:
            role_map[uid] = normalized_role
        payload = _build_whitelist_payload(role_map)
        ok = _atomic_write_json(path, payload)
        if ok:
            invalidate_role_map_cache(path=path)
        return ok


def remove_whitelist_user(user_id: Any, path: str = DEFAULT_WHITELIST_PATH) -> bool:
    """Remove a whitelist user and invalidate cached role mappings."""
    uid = _safe_user_id(user_id)
    if not uid:
        return False
    with _LOCK:
        role_map = get_role_map(path=path, admin_id=None)
        if uid not in role_map:
            return False
        role_map.pop(uid, None)
        payload = _build_whitelist_payload(role_map)
        ok = _atomic_write_json(path, payload)
        if ok:
            invalidate_role_map_cache(path=path)
        return ok
