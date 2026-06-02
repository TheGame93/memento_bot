"""Per-alert scheduling-state and repetition storage mutations."""

from datetime import datetime
from typing import TYPE_CHECKING

from modules.repetition_utils import decrement_count_if_needed, normalize_repetition_payload
from modules.storage_core._alloc import _UNSET

if TYPE_CHECKING:
    from modules.storage import StorageManager


class SchedulerStateService:
    """Own per-alert schedule-state, snooze, done-marking, and repetition mutations."""

    def __init__(self, store: "StorageManager"):
        self._store = store

    def update_alert_fields(self, user_id, alert_id, updates):
        """
        Atomically update arbitrary alert fields for a single alert.

        Media-path updates are normalized to canonical per-user storage paths;
        passing `local_image_path` with an empty/unresolvable value clears it.
        Returns True only when the target alert is found and persisted.
        """
        if not isinstance(updates, dict):
            return False

        updates_without_media = dict(updates)
        local_media_key_present = "local_image_path" in updates_without_media
        raw_local_media = updates_without_media.pop("local_image_path", None) if local_media_key_present else None
        normalized_local_media = None
        if local_media_key_present:
            if isinstance(raw_local_media, str) and raw_local_media.strip():
                normalized_local_media = self._store._to_canonical_storage_local_image_path(
                    user_id, raw_local_media, require_exists=False
                )
                if not normalized_local_media:
                    normalized_local_media = self._store._rebind_local_image_by_basename(
                        user_id, raw_local_media
                    )

        def _mutator(data):
            for alert in data.get("alerts", []):
                if alert.get("id") == alert_id:
                    alert.update(updates_without_media)
                    if local_media_key_present:
                        if normalized_local_media:
                            alert["local_image_path"] = normalized_local_media
                        else:
                            alert.pop("local_image_path", None)
                    self._store._normalize_alert_repetition_inplace(alert)
                    return True, True
            return False, False

        ok, updated = self._store._mutate_user_data(user_id, _mutator)
        if not ok or not updated:
            return False

        self._store.log_user_event(user_id, "alert_fields_updated", {
            "alert_id": alert_id,
            "fields": list(updates.keys()),
        })
        return True

    def update_alert_schedule_state(
        self,
        user_id,
        alert_id,
        last_triggered=None,
        next_scheduled=None,
        snoozed_until=None,
        fuzzy_history=_UNSET,
    ):
        """
        Update scheduling metadata for an alert in one atomic storage mutation.

        Args:
            user_id: User ID
            alert_id: Alert ID
            last_triggered: datetime or ISO string of last trigger time
            next_scheduled: datetime or ISO string of next scheduled time
            snoozed_until: datetime or ISO string if alert is snoozed.
                Passing None does not modify snooze state; callers must use
                clear_alert_snooze(...) to clear an existing snooze.
            fuzzy_history: Optional list payload to persist at alert top level.
                Pass None to clear stored history; omit to leave unchanged.

        Returns:
            True if update successful, False otherwise
        """

        def _to_iso(value):
            if isinstance(value, datetime):
                return value.isoformat()
            return value

        def _mutator(data):
            for alert in data.get("alerts", []):
                if alert.get("id") != alert_id:
                    continue

                if last_triggered is not None:
                    alert["last_triggered"] = _to_iso(last_triggered)
                if next_scheduled is not None:
                    alert["next_scheduled"] = _to_iso(next_scheduled)

                if snoozed_until is not None:
                    alert["snoozed_until"] = _to_iso(snoozed_until)
                if fuzzy_history is not _UNSET:
                    if fuzzy_history is None:
                        alert.pop("fuzzy_history", None)
                    else:
                        alert["fuzzy_history"] = fuzzy_history
                return True, True
            return False, False

        ok, updated = self._store._mutate_user_data(user_id, _mutator)
        if not ok:
            return False
        return bool(updated)

    def clear_alert_snooze(self, user_id, alert_id):
        """Clears the snoozed_until field for an alert."""

        def _mutator(data):
            for alert in data.get("alerts", []):
                if alert.get("id") != alert_id:
                    continue
                had_snooze = "snoozed_until" in alert
                if had_snooze:
                    del alert["snoozed_until"]
                return had_snooze, {
                    "type": alert.get("type"),
                    "type_name": alert.get("type_name"),
                }
            return False, None

        ok, payload = self._store._mutate_user_data(user_id, _mutator)
        if not ok or payload is None:
            return False

        self._store.log_user_event(user_id, "alert_snooze_cleared", {
            "alert_id": alert_id,
            "type": payload.get("type"),
            "type_name": payload.get("type_name"),
        })
        return True

    def mark_alert_done(self, user_id, alert_id):
        """
        Marks an alert as 'done' for this occurrence.
        For one-time alerts: sets active=False
        For recurring alerts: updates last_triggered and clears snooze

        Returns: (success: bool, was_one_time: bool)
        """
        now_iso = datetime.now().isoformat()

        def _mutator(data):
            for alert in data.get("alerts", []):
                if alert.get("id") != alert_id:
                    continue
                is_one_time = alert.get("type") == 5
                if is_one_time:
                    alert["active"] = False
                    alert["last_triggered"] = now_iso
                else:
                    alert["last_triggered"] = now_iso
                    if "snoozed_until" in alert:
                        del alert["snoozed_until"]

                return True, {
                    "was_one_time": is_one_time,
                    "type": alert.get("type"),
                    "type_name": alert.get("type_name"),
                }
            return False, None

        ok, payload = self._store._mutate_user_data(user_id, _mutator)
        if not ok or payload is None:
            return False, False

        self._store.log_user_event(user_id, "alert_marked_done", {
            "alert_id": alert_id,
            "was_one_time": payload.get("was_one_time"),
            "type": payload.get("type"),
            "type_name": payload.get("type_name"),
        })
        return True, bool(payload.get("was_one_time"))

    def consume_repetition_occurrence(self, user_id, alert_id, *, should_count=True):
        """
        Atomically normalizes/decrements repetition for one alert occurrence.

        Returns a structured dict:
        {
            "ok": bool,
            "found": bool,
            "changed": bool,
            "alert_type": Any,
            "repetition": dict|None,
            "before": int|None,
            "after": int|None,
            "exhausted": bool,
            "should_count": bool,
        }
        """
        should_count_flag = bool(should_count)

        def _mutator(data):
            alerts = data.get("alerts")
            if not isinstance(alerts, list):
                return False, {
                    "found": False,
                    "changed": False,
                    "alert_type": None,
                    "repetition": None,
                    "before": None,
                    "after": None,
                    "exhausted": False,
                }

            for alert in alerts:
                if not isinstance(alert, dict):
                    continue
                if alert.get("id") != alert_id:
                    continue

                alert_type = alert.get("type")
                normalized = normalize_repetition_payload(alert_type, alert.get("repetition"))
                had_repetition = "repetition" in alert
                changed = False

                if normalized is None:
                    if had_repetition:
                        alert.pop("repetition", None)
                        changed = True
                    return changed, {
                        "found": True,
                        "changed": changed,
                        "alert_type": alert_type,
                        "repetition": None,
                        "before": None,
                        "after": None,
                        "exhausted": False,
                    }

                decremented, before, after, exhausted = decrement_count_if_needed(
                    normalized,
                    should_count=should_count_flag,
                )
                if (not had_repetition) or alert.get("repetition") != decremented:
                    alert["repetition"] = decremented
                    changed = True

                return changed, {
                    "found": True,
                    "changed": changed,
                    "alert_type": alert_type,
                    "repetition": decremented,
                    "before": before,
                    "after": after,
                    "exhausted": exhausted,
                }

            return False, {
                "found": False,
                "changed": False,
                "alert_type": None,
                "repetition": None,
                "before": None,
                "after": None,
                "exhausted": False,
            }

        ok, outcome = self._store._mutate_user_data(user_id, _mutator)
        result = {
            "ok": bool(ok),
            "found": False,
            "changed": False,
            "alert_type": None,
            "repetition": None,
            "before": None,
            "after": None,
            "exhausted": False,
            "should_count": should_count_flag,
        }
        if isinstance(outcome, dict):
            result.update(outcome)
        if not ok:
            result["changed"] = False
        return result
