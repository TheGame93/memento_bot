"""User preference and metadata storage mutations."""

from datetime import datetime
from typing import TYPE_CHECKING

from modules import constants as C
from modules.timezone_utils import compute_next_occurrence, now_server_naive

if TYPE_CHECKING:
    from modules.storage import StorageManager


class UserPrefsService:
    """Handle user preference and metadata mutations through the storage layer."""

    def __init__(self, store: "StorageManager"):
        self._store = store

    def update_user_meta(self, user_id, updates, ensure_space=True):
        """Persist user metadata updates and return the merged metadata snapshot."""
        def _mutator(data):
            meta = data.get("user_meta") or self._store._default_user_meta()
            if not isinstance(meta, dict):
                meta = self._store._default_user_meta()
            meta.update(updates or {})
            data["user_meta"] = meta
            return True, meta

        ok, meta = self._store._mutate_user_data(
            user_id,
            _mutator,
            ensure_space=ensure_space,
            backup_reason="user_meta_update",
        )
        if not ok:
            return None
        return meta

    def touch_user_activity(self, user_id):
        """
        Update last_seen for a user, throttled to avoid excessive disk I/O.
        Skips the write if last_seen is already within ACTIVITY_WRITE_THROTTLE_SECONDS.
        """
        throttle = getattr(C, "ACTIVITY_WRITE_THROTTLE_SECONDS", 300)
        now = datetime.now()
        meta = self._store.get_user_meta(user_id) or {}
        last_seen_raw = meta.get("last_seen")
        if last_seen_raw:
            try:
                last_seen_dt = datetime.fromisoformat(str(last_seen_raw))
                if (now - last_seen_dt).total_seconds() < throttle:
                    return
            except Exception:
                pass
        self._store.update_user_meta(user_id, {"last_seen": now.isoformat()})

    def update_user_prefs(self, user_id, updates, ensure_space=True):
        """Persist user preference updates and return the merged preferences."""
        def _mutator(data):
            prefs = self._store._merge_user_prefs(data.get("user_prefs"))
            prefs.update(updates or {})
            data["user_prefs"] = prefs
            return True, prefs

        ok, prefs = self._store._mutate_user_data(
            user_id,
            _mutator,
            ensure_space=ensure_space,
            backup_reason="user_prefs_update",
        )
        if not ok:
            return None
        return prefs

    def update_birthday_schedule_time(self, user_id, time_str, user_prefs=None):
        """Update birthday alert times and recompute their next scheduled occurrences.

        Return a status payload with `ok`, `updated`, and `total` counters so
        callers can report partial or empty updates without re-reading alerts.
        """
        if not time_str:
            return {"ok": False, "updated": 0, "total": 0}
        prefs = user_prefs or self._store.get_user_prefs(user_id)
        now_ref = now_server_naive()

        def _mutator(data):
            alerts = data.get("alerts", []) or []
            updated = 0
            total = 0
            changed = False
            for alert in alerts:
                if alert.get("type") != 6:
                    continue
                total += 1
                schedule = alert.get("schedule") or {}
                current_time = schedule.get("time")
                if current_time != time_str:
                    schedule["time"] = time_str
                    alert["schedule"] = schedule
                    updated += 1
                    changed = True
                next_occ, _ = compute_next_occurrence(alert, now_ref, prefs)
                if next_occ:
                    alert["next_scheduled"] = next_occ.isoformat()
                    changed = True
            return changed, {"updated": updated, "total": total}

        ok, result = self._store._mutate_user_data(
            user_id,
            _mutator,
            ensure_space=True,
            backup_reason="birthday_time_update",
        )
        if not ok:
            return {"ok": False, "updated": 0, "total": 0}
        return {
            "ok": True,
            "updated": result.get("updated", 0),
            "total": result.get("total", 0),
        }

    def update_backup_prefs(self, user_id, updates, ensure_space=True):
        """Persist backup preference updates and return the merged preferences."""
        def _mutator(data):
            prefs = self._store._merge_backup_prefs(data.get("backup_prefs"))
            prefs.update(updates or {})
            data["backup_prefs"] = prefs
            return True, prefs

        ok, prefs = self._store._mutate_user_data(
            user_id,
            _mutator,
            ensure_space=ensure_space,
            backup_reason="backup_prefs_update",
        )
        if not ok:
            return None
        return prefs
