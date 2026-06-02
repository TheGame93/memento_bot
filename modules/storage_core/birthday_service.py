"""Bulk birthday import storage mutations."""

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

from modules import constants as C
from modules.storage_core._alloc import _allocate_next_shortcode, _allocate_unique_alert_id
from modules.systemlog import log_system
from modules.tags_logic import contains_emoji, parse_tag
from modules.timezone_utils import compute_next_occurrence, now_server_naive

if TYPE_CHECKING:
    from modules.storage import StorageManager

logger = logging.getLogger(__name__)


class BirthdayService:
    """Own bulk birthday import with tag resolution and atomic multi-insert."""

    def __init__(self, store: "StorageManager"):
        self._store = store

    def _normalize_hhmm_time(self, value):
        text = "" if value is None else str(value).strip()
        match = re.match(r"^(\d{1,2}):(\d{2})$", text)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"

    def _collapse_internal_spaces(self, value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _normalize_bulk_resolved_tags(self, raw_entry):
        """
        Normalizes import-session tags for one bulk birthday entry.

        Accepted schema:
        - preferred: resolved_tags -> list[str]
        - legacy fallback: resolved_tag -> str
        """
        if not isinstance(raw_entry, dict):
            return None, "invalid_entry_not_dict"

        if "resolved_tags" in raw_entry:
            raw_values = raw_entry.get("resolved_tags")
            if raw_values is None:
                raw_values = []
            if not isinstance(raw_values, list):
                return None, "invalid_entry_resolved_tags_not_list"
        else:
            legacy_value = raw_entry.get("resolved_tag")
            if legacy_value is None:
                raw_values = []
            elif isinstance(legacy_value, str) and not legacy_value.strip():
                raw_values = []
            else:
                raw_values = [legacy_value]

        normalized_tags = []
        seen_plain = set()

        for raw_tag in raw_values:
            if not isinstance(raw_tag, str):
                return None, "invalid_entry_resolved_tag_not_string"
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_tag):
                return None, "invalid_entry_resolved_tag_control_chars"
            tag_text = self._collapse_internal_spaces(raw_tag)
            if not tag_text:
                return None, "invalid_entry_resolved_tag_empty"
            if len(tag_text) > 80:
                return None, "invalid_entry_resolved_tag_too_long"

            first_token = tag_text.split(" ", 1)[0]
            if contains_emoji(first_token):
                _emoji, plain = parse_tag(tag_text)
                plain_text = self._collapse_internal_spaces(plain)
            else:
                plain_text = tag_text
            dedupe_key = (plain_text or tag_text).casefold()
            if not dedupe_key:
                return None, "invalid_entry_resolved_tag_plain_empty"
            if dedupe_key in seen_plain:
                continue

            seen_plain.add(dedupe_key)
            normalized_tags.append(tag_text)

        return normalized_tags, None

    def _normalize_bulk_birthday_entry(self, raw_entry):
        if not isinstance(raw_entry, dict):
            return None, "invalid_entry_not_dict"

        raw_name = str(raw_entry.get("name") or "").strip()
        name = re.sub(r"\s+", " ", raw_name).strip()
        if not name:
            return None, "name_empty"
        if len(name) > 80:
            return None, "name_too_long"
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
            return None, "name_control_chars"

        raw_date = str(raw_entry.get("date_ddmm") or "").strip()
        if not re.match(r"^\d{2}/\d{2}$", raw_date):
            return None, "date_ddmm_invalid"
        try:
            day, month = [int(token) for token in raw_date.split("/")]
        except Exception:
            return None, "date_ddmm_invalid"

        raw_birth_year = raw_entry.get("birth_year")
        birth_year = None
        if raw_birth_year not in {None, ""}:
            try:
                birth_year = int(raw_birth_year)
            except Exception:
                return None, "birth_year_invalid"
            if birth_year < 1900 or birth_year > 2100:
                return None, "birth_year_out_of_range"

        try:
            if birth_year is None:
                # Recurring birthday should allow 29/02.
                datetime(2000, month, day)
            else:
                datetime(birth_year, month, day)
        except ValueError:
            return None, "invalid_calendar_date"

        tags, tags_reason = self._normalize_bulk_resolved_tags(raw_entry)
        if tags is None:
            return None, tags_reason or "invalid_entry_tags"

        return {
            "name": name,
            "date_ddmm": f"{day:02d}/{month:02d}",
            "birth_year": birth_year,
            "tags": tags,
        }, None

    def save_birthdays_bulk(self, user_id, entries, *, source="settings_bulk_import"):
        """
        Atomically saves multiple birthday alerts in one storage transaction.

        Returns:
            {
              "ok": bool,
              "saved_count": int,
              "ids": list[str],
              "failure_reason": str|None
            }
        """
        from modules.storage import StorageLimitError
        try:
            normalized_entries = []
            for raw_entry in entries or []:
                normalized, reason = self._normalize_bulk_birthday_entry(raw_entry)
                if normalized is None:
                    return {
                        "ok": False,
                        "saved_count": 0,
                        "ids": [],
                        "failure_reason": reason or "invalid_entry",
                    }
                normalized_entries.append(normalized)

            if not normalized_entries:
                return {
                    "ok": False,
                    "saved_count": 0,
                    "ids": [],
                    "failure_reason": "entries_empty",
                }

            prefs = self._store.get_user_prefs(user_id) or {}
            birthday_default_time = self._normalize_hhmm_time(
                prefs.get("birthday_default_time")
            ) or self._normalize_hhmm_time(C.BIRTHDAY_DEFAULT_TIME) or "08:00"
            now_dt = now_server_naive()

            prepared_entries = []
            for item in normalized_entries:
                schedule = {
                    "date": item["date_ddmm"],
                    "time": birthday_default_time,
                }
                prepared = {
                    "title": item["name"],
                    "type": 6,
                    "type_name": C.ALERT_TYPES.get(6, "Birthday"),
                    "schedule": schedule,
                    "pre_alerts": [],
                    "additional_info": "",
                    "tags": list(item.get("tags") or []),
                    "active": True,
                    "created_at": now_dt.isoformat(),
                }
                if item.get("birth_year") is not None:
                    prepared["birth_year"] = int(item["birth_year"])

                next_occ, _shifted = compute_next_occurrence(prepared, now_dt, prefs)
                if next_occ:
                    prepared["next_scheduled"] = next_occ.isoformat()

                prepared_entries.append(prepared)

            def _mutator(data):
                if not isinstance(data.get("tags"), list):
                    data["tags"] = []
                if not isinstance(data.get("alerts"), list):
                    data["alerts"] = []
                if not isinstance(data.get("postpone_queue"), list):
                    data["postpone_queue"] = []
                self._store._ensure_shortcodes_in_data(data)

                alerts = data["alerts"]
                max_alerts = getattr(C, "USER_MAX_ALERTS", 0)
                incoming_count = len(prepared_entries)
                if max_alerts > 0 and (len(alerts) + incoming_count) > max_alerts:
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
                    item.get("shortcode")
                    for item in alerts
                    if isinstance(item.get("shortcode"), str)
                }
                used_ids = {
                    item.get("id")
                    for item in alerts
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }

                created_ids = []
                for prepared in prepared_entries:
                    alert_row = dict(prepared)
                    alert_id = _allocate_unique_alert_id(used_ids)
                    used_ids.add(alert_id)
                    alert_row["id"] = alert_id

                    shortcode, next_seq = _allocate_next_shortcode(next_seq, used_codes)
                    used_codes.add(shortcode.lower())
                    alert_row["shortcode"] = shortcode

                    alerts.append(alert_row)
                    created_ids.append(alert_id)

                meta["next_seq"] = next_seq
                return True, {"ids": created_ids}

            ok, result = self._store._mutate_user_data(
                user_id,
                _mutator,
                ensure_space=True,
                backup_reason="birthday_bulk_import",
            )
            if not ok:
                return {
                    "ok": False,
                    "saved_count": 0,
                    "ids": [],
                    "failure_reason": "storage_write_failed",
                }

            ids = list((result or {}).get("ids") or [])
            self._store.log_user_event(user_id, "birthday_bulk_saved_storage", {
                "source": source,
                "saved_count": len(ids),
                "ids_count": len(ids),
            })
            return {
                "ok": True,
                "saved_count": len(ids),
                "ids": ids,
                "failure_reason": None,
            }
        except StorageLimitError:
            return {
                "ok": False,
                "saved_count": 0,
                "ids": [],
                "failure_reason": "limit_reached",
            }
        except Exception as e:
            logger.error(f"❌ Storage Error in save_birthdays_bulk: {e}")
            log_system("storage", "save_birthdays_bulk_failed", {
                "user_id": str(user_id),
                "entries_count": len(entries or []),
                "source": source,
                "error": str(e),
            }, level="ERROR")
            return {
                "ok": False,
                "saved_count": 0,
                "ids": [],
                "failure_reason": "exception",
            }
