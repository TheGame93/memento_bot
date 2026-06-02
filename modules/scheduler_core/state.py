"""In-memory scheduler state shared across coordinator logic."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

sent_pre_alerts = {}
sent_pre_alerts_dirty = False
last_tick_time = None

_PERSISTENCE_KEY = "sent_pre_alerts"

# Tracks missed pre-alerts that have already been reported to the user on a previous
# restart, so they are not reported again ("once" mode).
# Key: (user_id_str, alert_id, pa_str, occurrence_iso) → datetime when first notified.
notified_missed_pre = {}
notified_missed_pre_dirty = False
_NOTIFIED_MISSED_PRE_KEY = "notified_missed_pre"


def _serialize_key(key_tuple):
    """(user_id, alert_id, pa_str) -> 'user_id|alert_id|pa_str'"""
    return "|".join(str(part) for part in key_tuple)


def _deserialize_key(key_str):
    """'user_id|alert_id|pa_str' -> (str, str, str)"""
    parts = key_str.split("|", 2)
    if len(parts) != 3:
        return None
    return tuple(parts)


def mark_dirty():
    """Mark pre-alert tracking state as needing persistence."""
    global sent_pre_alerts_dirty
    sent_pre_alerts_dirty = True


def clear_pre_alert_tracking_for_alert(alert_id):
    """
    Remove all sent_pre_alerts entries for a given alert_id.

    Returns the number of removed entries.
    """
    target_alert_id = str(alert_id)
    to_remove = [
        key_tuple
        for key_tuple in sent_pre_alerts.keys()
        if len(key_tuple) > 1 and str(key_tuple[1]) == target_alert_id
    ]
    for key_tuple in to_remove:
        sent_pre_alerts.pop(key_tuple, None)
    removed_count = len(to_remove)
    if removed_count:
        mark_dirty()
    return removed_count


def prune_user_sent_pre_alerts(user_id_str: str) -> int:
    """Remove all sent_pre_alerts entries for a specific user id."""
    target_user_id = str(user_id_str)
    to_remove = [
        key_tuple
        for key_tuple in sent_pre_alerts.keys()
        if len(key_tuple) > 0 and str(key_tuple[0]) == target_user_id
    ]
    for key_tuple in to_remove:
        sent_pre_alerts.pop(key_tuple, None)
    removed_count = len(to_remove)
    if removed_count:
        mark_dirty()
    return removed_count


def save_pre_alert_state():
    """Persist sent_pre_alerts to runtime_state.json if dirty."""
    global sent_pre_alerts_dirty
    if not sent_pre_alerts_dirty:
        return True
    from modules.systemlog import update_runtime_state_key
    data = {}
    for key_tuple, dt_value in sent_pre_alerts.items():
        data[_serialize_key(key_tuple)] = (
            dt_value.isoformat() if isinstance(dt_value, datetime) else str(dt_value)
        )
    ok = update_runtime_state_key(_PERSISTENCE_KEY, data)
    if ok:
        sent_pre_alerts_dirty = False
    return ok


def load_pre_alert_state():
    """Restore sent_pre_alerts from runtime_state.json."""
    global sent_pre_alerts, sent_pre_alerts_dirty
    from modules.systemlog import _read_runtime_state, _runtime_state_lock
    with _runtime_state_lock:
        state = _read_runtime_state()
    data = state.get(_PERSISTENCE_KEY)
    if not isinstance(data, dict):
        return
    restored = 0
    for key_str, ts_str in data.items():
        key_tuple = _deserialize_key(key_str)
        if not key_tuple:
            continue
        try:
            sent_pre_alerts[key_tuple] = datetime.fromisoformat(ts_str)
            restored += 1
        except (ValueError, TypeError):
            continue
    sent_pre_alerts_dirty = False
    if restored:
        logger.info(f"Restored {restored} pre-alert tracking entries from disk")


# =============================================================================
# notified_missed_pre — tracks which missed pre-alerts have already been
# reported to the user after a restart, so they are not reported again
# ("once" mode).  Key: (user_id_str, alert_id, pa_str, occurrence_iso).
# =============================================================================

def is_missed_pre_notified(user_id_str, alert_id, pa_str, occurrence_iso):
    """Return True if this missed pre-alert was already notified on a previous restart."""
    return (user_id_str, alert_id, pa_str, occurrence_iso) in notified_missed_pre


def mark_missed_pre_notified(user_id_str, alert_id, pa_str, occurrence_iso, when):
    """Record that this missed pre-alert occurrence has been notified."""
    global notified_missed_pre_dirty
    notified_missed_pre[(user_id_str, alert_id, pa_str, occurrence_iso)] = when
    notified_missed_pre_dirty = True


def cleanup_notified_missed_pre(alert_last_triggered_map, known_alert_ids_by_user=None):
    """
    Remove stale entries from notified_missed_pre.

    Two removal conditions:
      1. Alert fired at or after the occurrence: last_triggered >= occ_dt.
         This means the occurrence has been superseded and the entry is no longer needed.
      2. Alert no longer exists (deleted/missing): alert_id absent from
         known_alert_ids_by_user for its user.  Without this check, entries for
         deleted alerts linger forever because alert_last_triggered_map also returns
         None for them — indistinguishable from an alert that simply hasn't fired yet.
         (FRINGE CASE FIX)

    Args:
        alert_last_triggered_map: {(user_id_str, alert_id): last_triggered_dt}
            Only includes alerts that have a non-None, parseable last_triggered.
        known_alert_ids_by_user: {user_id_str: set(alert_ids)} of currently active
            alerts.  If None, condition 2 is skipped (safe degraded behaviour).
    """
    global notified_missed_pre, notified_missed_pre_dirty
    to_remove = []
    for key in notified_missed_pre:
        user_id_str, alert_id, pa_str, occurrence_iso = key

        # Condition 2: user or alert was deleted — remove regardless of last_triggered.
        if known_alert_ids_by_user is not None:
            user_known = known_alert_ids_by_user.get(user_id_str)
            if user_known is None:
                # User completely absent from system (deleted/de-whitelisted).
                to_remove.append(key)
                continue
            if alert_id not in user_known:
                to_remove.append(key)
                continue

        # Condition 1: alert has fired at or after the occurrence.
        last_triggered = alert_last_triggered_map.get((user_id_str, alert_id))
        if last_triggered is None:
            continue  # alert has not fired yet — keep entry
        try:
            occ_dt = datetime.fromisoformat(occurrence_iso)
        except (ValueError, TypeError):
            to_remove.append(key)  # malformed key — discard
            continue
        if last_triggered >= occ_dt:
            to_remove.append(key)

    for key in to_remove:
        del notified_missed_pre[key]
    if to_remove:
        notified_missed_pre_dirty = True


def save_notified_missed_pre():
    """Persist notified_missed_pre to runtime_state.json if dirty."""
    global notified_missed_pre_dirty
    if not notified_missed_pre_dirty:
        return True
    from modules.systemlog import update_runtime_state_key
    data = {}
    for key_tuple, dt_value in notified_missed_pre.items():
        key_str = "|".join(str(p) for p in key_tuple)
        data[key_str] = dt_value.isoformat() if isinstance(dt_value, datetime) else str(dt_value)
    ok = update_runtime_state_key(_NOTIFIED_MISSED_PRE_KEY, data)
    if ok:
        notified_missed_pre_dirty = False
    return ok


def load_notified_missed_pre():
    """Restore notified_missed_pre from runtime_state.json."""
    global notified_missed_pre, notified_missed_pre_dirty
    from modules.systemlog import _read_runtime_state, _runtime_state_lock
    with _runtime_state_lock:
        state = _read_runtime_state()
    data = state.get(_NOTIFIED_MISSED_PRE_KEY)
    if not isinstance(data, dict):
        return
    restored = 0
    for key_str, ts_str in data.items():
        # Key format: "user_id|alert_id|pa_str|occurrence_iso" (maxsplit=3 for safety)
        parts = key_str.split("|", 3)
        if len(parts) != 4:
            continue
        key_tuple = tuple(parts)
        try:
            notified_missed_pre[key_tuple] = datetime.fromisoformat(ts_str)
            restored += 1
        except (ValueError, TypeError):
            continue
    notified_missed_pre_dirty = False
    if restored:
        logger.info(f"Restored {restored} notified-missed-pre-alert entries from disk")


# =============================================================================
# pending_missed_notifications — persists missed-alert info for "always" mode
# so every restart re-reports until the alert fires normally via the scheduler.
# Structure: {user_id_str: {alert_id: {
#   "occurrence":        iso_str,
#   "missed_pre_strs":  [pa_str, ...],
#   "missed_pre_times": [iso_str, ...],
#   "missed_due_time":  iso_str | None,
#   "first_notified":   iso_str,
# }}}
# =============================================================================

pending_missed_notifications = {}
pending_missed_dirty = False
_PENDING_MISSED_KEY = "pending_missed_notifications"


def record_pending_missed(user_id_str, alert_id, occurrence_iso,
                          missed_pre_strs, missed_pre_times,
                          missed_due_time_iso, first_notified_iso):
    """Store or update a missed alert entry for "always" mode re-notification."""
    global pending_missed_notifications, pending_missed_dirty
    if user_id_str not in pending_missed_notifications:
        pending_missed_notifications[user_id_str] = {}
    pending_missed_notifications[user_id_str][alert_id] = {
        "occurrence": occurrence_iso,
        "missed_pre_strs": missed_pre_strs,
        "missed_pre_times": missed_pre_times,
        "missed_due_time": missed_due_time_iso,
        "first_notified": first_notified_iso,
    }
    pending_missed_dirty = True


def clear_pending_missed_alert(user_id_str, alert_id):
    """Remove the pending entry when trigger_alert() fires normally (stops re-notification)."""
    global pending_missed_notifications, pending_missed_dirty
    user_pending = pending_missed_notifications.get(user_id_str)
    if user_pending and alert_id in user_pending:
        del user_pending[alert_id]
        pending_missed_dirty = True


def get_pending_missed_for_user(user_id_str):
    """Return {alert_id: {...}} for this user, or {}."""
    return pending_missed_notifications.get(user_id_str, {})


def save_pending_missed():
    """Persist pending_missed_notifications to runtime_state.json if dirty."""
    global pending_missed_dirty
    if not pending_missed_dirty:
        return True
    from modules.systemlog import update_runtime_state_key
    ok = update_runtime_state_key(_PENDING_MISSED_KEY, pending_missed_notifications)
    if ok:
        pending_missed_dirty = False
    return ok


def load_pending_missed():
    """Restore pending_missed_notifications from runtime_state.json."""
    global pending_missed_notifications, pending_missed_dirty
    from modules.systemlog import _read_runtime_state, _runtime_state_lock
    with _runtime_state_lock:
        state = _read_runtime_state()
    data = state.get(_PENDING_MISSED_KEY)
    if isinstance(data, dict):
        pending_missed_notifications = data
    pending_missed_dirty = False


def prune_user_missed_state(user_id_str: str) -> dict:
    """Prune missed-notification state entries for a specific user id."""
    global notified_missed_pre_dirty, pending_missed_dirty
    target_user_id = str(user_id_str)

    notified_keys = [
        key_tuple
        for key_tuple in notified_missed_pre.keys()
        if len(key_tuple) > 0 and str(key_tuple[0]) == target_user_id
    ]
    for key_tuple in notified_keys:
        notified_missed_pre.pop(key_tuple, None)
    if notified_keys:
        notified_missed_pre_dirty = True

    pending_removed = 0
    if target_user_id in pending_missed_notifications:
        pending_missed_notifications.pop(target_user_id, None)
        pending_removed = 1
        pending_missed_dirty = True

    return {
        "notified_missed_pre_removed": len(notified_keys),
        "pending_missed_removed": pending_removed,
    }
