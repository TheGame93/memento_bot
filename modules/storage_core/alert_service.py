"""Alert creation/deletion/toggle storage mutations."""

import logging
import os
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from modules import constants as C
from modules.shared.logging_utils import hash_text, text_meta
from modules.storage_core._alloc import _allocate_next_shortcode
from modules.systemlog import log_system
from modules.timezone_utils import (
    compute_next_occurrence,
    get_server_tz,
    now_server_naive,
    normalize_one_time_date,
    resolve_user_timezone,
    to_server_naive_from_user,
)

if TYPE_CHECKING:
    from modules.storage import StorageManager


logger = logging.getLogger(__name__)


class AlertService:
    """Handle alert save/delete/toggle mutations through the storage manager."""

    def __init__(self, store: "StorageManager"):
        self._store = store

    def save_alert(self, user_id, alert_data):
        """Persist a new alert, compute next_scheduled, and return the allocated alert ID.

        Returns the new alert ID string on success, None on write failure, or raises
        StorageLimitError when the per-user alert cap is reached.
        """
        from modules import storage as storage_module
        from modules.storage import StorageLimitError

        try:
            now_dt = now_server_naive()
            immediate_one_time = False
            prepared = dict(alert_data or {})
            # Never persist add/edit draft-only helper keys.
            prepared.pop("_fuzzy_first_next", None)
            if isinstance(alert_data, dict):
                alert_data.pop("_fuzzy_first_next", None)
            user_prefs = None
            prepared["id"] = str(uuid.uuid4())[:8]
            prepared["created_at"] = now_dt.isoformat()
            prepared["active"] = True
            if "local_image_path" in prepared:
                normalized_local_path = self._store._to_canonical_storage_local_image_path(
                    user_id, prepared.get("local_image_path"), require_exists=False
                )
                if not normalized_local_path:
                    normalized_local_path = self._store._rebind_local_image_by_basename(
                        user_id, prepared.get("local_image_path")
                    )
                if normalized_local_path:
                    prepared["local_image_path"] = normalized_local_path
                else:
                    prepared.pop("local_image_path", None)
            self._store._normalize_alert_repetition_inplace(prepared)
            if prepared.get("type") is not None:
                try:
                    user_prefs = self._store.get_user_prefs(user_id)
                    if prepared.get("type") == 5:
                        schedule = prepared.get("schedule") or {}
                        date_str = schedule.get("date")
                        partial_input = isinstance(date_str, str) and date_str.count("/") == 1
                        status, normalized, assumed, _reason = normalize_one_time_date(
                            date_str,
                            reference_server_dt=now_dt,
                            user_prefs=user_prefs,
                            require_year_if_today=False,
                            time_str=schedule.get("time"),
                        )
                        if status == "ok" and normalized:
                            schedule["date"] = normalized
                            prepared["schedule"] = schedule
                            if assumed and partial_input:
                                assumed_year = None
                                try:
                                    assumed_year = int(normalized.split("/")[-1])
                                except Exception:
                                    assumed_year = None
                                self._store.log_user_event(user_id, "one_time_year_assumed", {
                                    "source": "storage",
                                    "date_meta": text_meta(date_str),
                                    "assumed_year": assumed_year,
                                })
                    next_occ = None
                    shifted = False
                    schedule = prepared.get("schedule") if isinstance(prepared.get("schedule"), dict) else {}
                    is_fuzzy_daily = (
                        prepared.get("type") == 7
                        and schedule.get("interval_mode") == "fuzzy"
                    )
                    if is_fuzzy_daily:
                        parsed_next = None
                        raw_next = prepared.get("next_scheduled")
                        if isinstance(raw_next, str) and raw_next.strip():
                            try:
                                parsed_next = datetime.fromisoformat(raw_next)
                                if parsed_next.tzinfo is not None:
                                    parsed_next = parsed_next.astimezone(get_server_tz()).replace(tzinfo=None)
                            except Exception:
                                parsed_next = None
                        if parsed_next is not None:
                            next_occ = parsed_next
                        else:
                            _sampled_days, next_occ, shifted = storage_module.resolve_fuzzy_next_scheduled(
                                prepared,
                                now_dt,
                                user_prefs,
                                record_history=False,
                                history_source=None,
                            )
                    else:
                        next_occ, shifted = compute_next_occurrence(prepared, now_dt, user_prefs)
                    if next_occ:
                        prepared["next_scheduled"] = next_occ.isoformat()
                        if isinstance(alert_data, dict):
                            alert_data["next_scheduled"] = prepared["next_scheduled"]
                    if shifted and next_occ:
                        tz_name = None
                        tz_block = user_prefs.get("timezone") if isinstance(user_prefs, dict) else None
                        if isinstance(tz_block, dict):
                            tz_name = tz_block.get("name")
                        log_system("scheduler", "timezone_shift_forward", {
                            "user_id": str(user_id),
                            "alert_id": prepared.get("id"),
                            "next_scheduled": next_occ.isoformat(),
                            "tz_name": tz_name,
                        })
                        self._store.log_user_event(user_id, "timezone_shift_forward", {
                            "alert_id": prepared.get("id"),
                            "next_scheduled": next_occ.isoformat(),
                            "tz_name": tz_name,
                        })
                except Exception as e:
                    logger.error(f"❌ Failed to compute next_scheduled on save: {e}")
                    log_system("storage", "next_scheduled_compute_failed", {
                        "user_id": str(user_id),
                        "alert_id": prepared.get("id"),
                        "type": prepared.get("type"),
                        "error": str(e),
                    }, level="ERROR")

            # Policy: one-time alerts in the past are allowed and should fire once immediately.
            if prepared.get("type") == 5 and not prepared.get("next_scheduled"):
                schedule = prepared.get("schedule", {}) or {}
                date_str = schedule.get("date")
                time_str = schedule.get("time") or "10:00"
                try:
                    date_part = datetime.strptime(date_str, "%d/%m/%Y")
                    time_part = datetime.strptime(time_str, "%H:%M").time()
                    candidate = date_part.replace(
                        hour=time_part.hour,
                        minute=time_part.minute,
                        second=0,
                        microsecond=0,
                    )
                    compare_dt = candidate
                    try:
                        mode = None
                        if isinstance(user_prefs, dict):
                            mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
                        if mode == C.TIMEZONE_MODE_USER:
                            user_tz = resolve_user_timezone(user_prefs)
                            compare_dt, _ = to_server_naive_from_user(candidate, user_tz)
                    except Exception:
                        compare_dt = candidate
                    if compare_dt <= now_dt:
                        prepared["next_scheduled"] = now_dt.isoformat()
                        immediate_one_time = True
                except Exception:
                    pass

            def _mutator(data):
                # Keep schema stable for future features and migrations.
                if not isinstance(data.get("tags"), list):
                    data["tags"] = []
                if not isinstance(data.get("alerts"), list):
                    data["alerts"] = []
                if not isinstance(data.get("postpone_queue"), list):
                    data["postpone_queue"] = []
                self._store._ensure_shortcodes_in_data(data)

                # Enforce max alerts limit
                max_alerts = getattr(C, "USER_MAX_ALERTS", 0)
                if max_alerts > 0 and len(data["alerts"]) >= max_alerts:
                    raise StorageLimitError(
                        f"You have reached the maximum of {max_alerts} alerts. "
                        "Delete some alerts first."
                    )

                meta = data.setdefault("shortcut_meta", {"next_seq": 0})
                try:
                    next_seq = int(meta.get("next_seq", 0))
                except Exception:
                    next_seq = 0
                used_codes = {
                    a.get("shortcode")
                    for a in data.get("alerts", [])
                    if isinstance(a.get("shortcode"), str)
                }
                shortcode, next_seq = _allocate_next_shortcode(next_seq, used_codes)
                meta["next_seq"] = next_seq

                prepared["shortcode"] = shortcode
                data["alerts"].append(prepared)
                return True, prepared

            ok, stored_alert = self._store._mutate_user_data(
                user_id,
                _mutator,
                ensure_space=True,
            )
            if not ok:
                return None

            logger.info(f"✅ Alert {stored_alert['id']} saved for user {user_id}")
            schedule_keys = sorted((stored_alert.get("schedule") or {}).keys())
            repetition = stored_alert.get("repetition") if isinstance(stored_alert.get("repetition"), dict) else None
            repetition_mode = repetition.get("mode") if repetition else None
            repetition_count_remaining = None
            if repetition_mode == C.REPETITION_MODE_COUNT:
                try:
                    repetition_count_remaining = int(repetition.get("count_remaining"))
                except Exception:
                    repetition_count_remaining = None
            self._store.log_user_event(user_id, "alert_saved", {
                "alert_id": stored_alert.get("id"),
                "type": stored_alert.get("type"),
                "type_name": stored_alert.get("type_name"),
                "shortcode": stored_alert.get("shortcode"),
                "schedule_keys": schedule_keys,
                "pre_alerts_count": len(stored_alert.get("pre_alerts") or []),
                "tags_count": len(stored_alert.get("tags") or []),
                "has_image": bool(stored_alert.get("image_id")),
                "one_time_immediate": immediate_one_time,
                "repetition_mode": repetition_mode,
                "repetition_has_until_date": bool(repetition.get("until_date")) if repetition else False,
                "repetition_count_remaining": repetition_count_remaining,
            })
            return stored_alert["id"]
        except StorageLimitError:
            raise
        except Exception as e:
            logger.error(f"❌ Storage Error in save_alert: {e}")
            log_system("storage", "save_alert_failed", {
                "user_id": str(user_id),
                "type": alert_data.get("type") if alert_data else None,
                "error": str(e),
            }, level="ERROR")
            return None

    def delete_alert(self, user_id, alert_id):
        """Delete an alert and clean related postpone entries and local media files."""

        def _mutator(data):
            alerts = data.get("alerts")
            if not isinstance(alerts, list):
                return False, None

            alert_to_del = next((a for a in alerts if a.get("id") == alert_id), None)
            if not isinstance(alert_to_del, dict):
                return False, None

            data["alerts"] = [a for a in alerts if a.get("id") != alert_id]
            if isinstance(data.get("postpone_queue"), list):
                data["postpone_queue"] = [
                    p for p in data.get("postpone_queue", [])
                    if p.get("alert_id") != alert_id
                ]
            return True, alert_to_del

        ok, alert_to_del = self._store._mutate_user_data(user_id, _mutator)
        if not ok or not alert_to_del:
            return False

        image_path = alert_to_del.get("local_image_path")
        if isinstance(image_path, str) and image_path.strip():
            try:
                resolved_path = self._store.resolve_local_image_path(
                    user_id, image_path, require_exists=False
                )
                if resolved_path and os.path.isfile(resolved_path):
                    os.remove(resolved_path)
                else:
                    reason_code = "local_path_invalid"
                    if resolved_path and not os.path.isfile(resolved_path):
                        reason_code = "local_file_missing"
                    log_system("storage", "local_image_delete_skipped", {
                        "user_id": str(user_id),
                        "alert_id": alert_id,
                        "reason_code": reason_code,
                        "path_len": len(image_path),
                        "path_hash": hash_text(image_path),
                    }, level="WARNING")
            except Exception as e:
                log_system("storage", "local_image_delete_failed", {
                    "user_id": str(user_id),
                    "alert_id": alert_id,
                    "reason_code": "local_delete_exception",
                    "path_len": len(image_path),
                    "path_hash": hash_text(image_path),
                    "error_type": e.__class__.__name__,
                }, level="ERROR")

        self._store.log_user_event(user_id, "alert_deleted", {
            "alert_id": alert_to_del.get("id"),
            "type": alert_to_del.get("type"),
            "type_name": alert_to_del.get("type_name"),
        })
        return True

    def toggle_alert(self, user_id, alert_id):
        """Toggle an alert active flag, clearing stale snooze state when re-enabling it."""

        def _mutator(data):
            alerts = data.get("alerts")
            if not isinstance(alerts, list):
                return False, None
            for alert in alerts:
                if alert.get("id") == alert_id:
                    new_status = not alert.get("active", True)
                    alert["active"] = new_status
                    snooze_cleared = False
                    if new_status and "snoozed_until" in alert:
                        alert.pop("snoozed_until", None)
                        snooze_cleared = True
                    return True, {
                        "active": new_status,
                        "snooze_cleared": snooze_cleared,
                        "type": alert.get("type"),
                        "type_name": alert.get("type_name"),
                    }
            return False, None

        ok, payload = self._store._mutate_user_data(user_id, _mutator)
        if not ok or payload is None:
            return None

        new_status = bool(payload.get("active"))
        self._store.log_user_event(user_id, "alert_toggled", {
            "alert_id": alert_id,
            "active": new_status
        })
        if payload.get("snooze_cleared"):
            self._store.log_user_event(user_id, "alert_snooze_cleared", {
                "alert_id": alert_id,
                "type": payload.get("type"),
                "type_name": payload.get("type_name"),
            })
        return new_status
