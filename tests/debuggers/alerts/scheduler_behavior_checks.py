import tempfile
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch


@dataclass
class SchedulerBehaviorDeps:
    constants: object
    scheduler_module: object
    get_constants_compatibility_issues: object
    get_next_occurrence: object
    format_main_alert: object
    format_pre_alert: object
    format_missed_alert: object
    format_missed_alerts_summary: object
    get_alert_keyboard: object
    get_pre_alert_keyboard: object
    send_alert: object
    send_snooze_confirmation: object
    send_done_confirmation: object
    format_detailed_card: object
    storage_manager_cls: object


def _keyboard_rows(markup):
    if not markup:
        return []
    return [[btn.text for btn in row] for row in markup.inline_keyboard]


def _keyboard_has(markup, label):
    for row in _keyboard_rows(markup):
        if label in row:
            return True
    return False


def _keyboard_has_row(markup, expected_row):
    for row in _keyboard_rows(markup):
        if row == expected_row:
            return True
    return False


def _build_alert(constants, alert_id, title, alert_type, schedule, pre_alerts=None, active=True):
    return {
        "id": alert_id,
        "title": title,
        "type": alert_type,
        "type_name": constants.ALERT_TYPES.get(alert_type, "Unknown"),
        "schedule": schedule,
        "pre_alerts": pre_alerts or [],
        "tags": [],
        "active": bool(active),
    }


def _check_constants_compatibility(dbg, deps):
    issues = deps.get_constants_compatibility_issues()
    dbg.section("constants_compatibility", {
        "weekdays": deps.constants.WEEKDAYS,
        "ordinals": deps.constants.ORDINALS,
        "pre_alert_units": sorted(deps.constants.PRE_ALERT_UNITS.keys()),
        "issues": issues,
    })
    if issues:
        dbg.problem("constants_incompatible", {"issues": issues})


def _check_fired_message_variants(dbg, deps):
    now = datetime.now().replace(second=0, microsecond=0)
    main_time = now + timedelta(hours=2)
    pre_time = main_time - timedelta(minutes=30)
    weekday = deps.constants.WEEKDAYS[main_time.weekday()]

    recurring = _build_alert(
        deps.constants,
        "msg_r",
        "Recurring Message Test",
        3,
        {"weekdays": [weekday], "interval": 1, "time": main_time.strftime("%H:%M")},
        pre_alerts=["30m"],
    )
    recurring_exhausted = _build_alert(
        deps.constants,
        "msg_rx",
        "Recurring Exhausted Message Test",
        3,
        {"weekdays": [weekday], "interval": 1, "time": main_time.strftime("%H:%M")},
        pre_alerts=["30m"],
    )
    recurring_exhausted["repetition"] = {
        "mode": deps.constants.REPETITION_MODE_COUNT,
        "count_remaining": 0,
    }
    one_time = _build_alert(
        deps.constants,
        "msg_o",
        "One Time Message Test",
        5,
        {"date": main_time.strftime("%d/%m/%Y"), "time": main_time.strftime("%H:%M")},
        pre_alerts=["30m"],
    )

    pre_rec = deps.format_pre_alert(recurring, main_time, pre_time)
    pre_rec_exhausted = deps.format_pre_alert(recurring_exhausted, main_time, pre_time)
    pre_once = deps.format_pre_alert(one_time, main_time, pre_time)
    main_rec = deps.format_main_alert(recurring, main_time)
    main_rec_exhausted = deps.format_main_alert(recurring_exhausted, main_time)
    main_once = deps.format_main_alert(one_time, main_time)

    kb_pre_rec = deps.get_pre_alert_keyboard(recurring, occurrence_time=main_time, original_time=pre_time)
    kb_pre_once = deps.get_pre_alert_keyboard(one_time, occurrence_time=main_time, original_time=pre_time)
    kb_main_rec = deps.get_alert_keyboard(recurring, occurrence_time=main_time, original_time=main_time)
    kb_main_once = deps.get_alert_keyboard(one_time, occurrence_time=main_time, original_time=main_time)

    postpone_label = "⏰ POSTPONE this notification"
    snooze_label = "🔄 SNOOZE until manual re-activation"
    activate_label = "🟢 ACTIVATE again the alarm"
    delete_label = "🗑️ DELETE forever this alert"
    info_label = "ℹ️ Detailed info"

    recurring_inactive = _build_alert(
        deps.constants,
        "msg_ri",
        "Recurring Inactive Test",
        3,
        {"weekdays": [weekday], "interval": 1, "time": main_time.strftime("%H:%M")},
        pre_alerts=["30m"],
        active=False,
    )
    kb_pre_inactive = deps.get_pre_alert_keyboard(
        recurring_inactive,
        occurrence_time=main_time,
        original_time=pre_time,
    )
    kb_main_inactive = deps.get_alert_keyboard(
        recurring_inactive,
        occurrence_time=main_time,
        original_time=main_time,
    )

    checks = {
        "pre_rec_header": "UPCOMING ALERT" in pre_rec,
        "pre_rec_next": "Next occurrence:" in pre_rec,
        "pre_once_header": "UPCOMING ALERT" in pre_once,
        "pre_once_no_next": "Next occurrence:" not in pre_once,
        "main_rec_header": "**ALERT**" in main_rec,
        "main_rec_next": "Next occurrence:" in main_rec,
        "main_rec_exhausted_limit_text": "repetition limit reached" in main_rec_exhausted.lower(),
        "main_once_header": "**ALERT**" in main_once,
        "main_once_no_next": "Next occurrence:" not in main_once,
        "pre_rec_exhausted_limit_text": "repetition limit reached" in pre_rec_exhausted.lower(),
        "kb_pre_rec_has_snooze": _keyboard_has(kb_pre_rec, snooze_label),
        "kb_pre_once_no_snooze": not _keyboard_has(kb_pre_once, snooze_label),
        "kb_pre_rec_has_delete": _keyboard_has(kb_pre_rec, delete_label),
        "kb_pre_once_has_delete": _keyboard_has(kb_pre_once, delete_label),
        "kb_pre_rec_has_info": _keyboard_has(kb_pre_rec, info_label),
        "kb_pre_once_has_info": _keyboard_has(kb_pre_once, info_label),
        "kb_main_rec_has_delete": _keyboard_has(kb_main_rec, delete_label),
        "kb_main_rec_has_snooze": _keyboard_has(kb_main_rec, snooze_label),
        "kb_main_rec_has_info": _keyboard_has(kb_main_rec, info_label),
        "kb_main_once_has_delete": _keyboard_has(kb_main_once, delete_label),
        "kb_main_once_no_snooze": not _keyboard_has(kb_main_once, snooze_label),
        "kb_main_once_has_info": _keyboard_has(kb_main_once, info_label),
        "kb_pre_rec_postpone_own_row": _keyboard_has_row(kb_pre_rec, [postpone_label]),
        "kb_pre_rec_snooze_own_row": _keyboard_has_row(kb_pre_rec, [snooze_label]),
        "kb_pre_rec_delete_own_row": _keyboard_has_row(kb_pre_rec, [delete_label]),
        "kb_pre_rec_info_own_row": _keyboard_has_row(kb_pre_rec, [info_label]),
        "kb_main_rec_postpone_own_row": _keyboard_has_row(kb_main_rec, [postpone_label]),
        "kb_main_rec_snooze_own_row": _keyboard_has_row(kb_main_rec, [snooze_label]),
        "kb_main_rec_delete_own_row": _keyboard_has_row(kb_main_rec, [delete_label]),
        "kb_main_rec_info_own_row": _keyboard_has_row(kb_main_rec, [info_label]),
        "kb_main_once_postpone_own_row": _keyboard_has_row(kb_main_once, [postpone_label]),
        "kb_main_once_delete_own_row": _keyboard_has_row(kb_main_once, [delete_label]),
        "kb_main_once_info_own_row": _keyboard_has_row(kb_main_once, [info_label]),
        "kb_pre_inactive_has_activate": _keyboard_has(kb_pre_inactive, activate_label),
        "kb_pre_inactive_no_snooze": not _keyboard_has(kb_pre_inactive, snooze_label),
        "kb_pre_inactive_activate_own_row": _keyboard_has_row(kb_pre_inactive, [activate_label]),
        "kb_main_inactive_has_activate": _keyboard_has(kb_main_inactive, activate_label),
        "kb_main_inactive_no_snooze": not _keyboard_has(kb_main_inactive, snooze_label),
        "kb_main_inactive_activate_own_row": _keyboard_has_row(kb_main_inactive, [activate_label]),
    }

    dbg.section("fired_message_checks", {
        "checks": checks,
        "main_rec_exhausted": main_rec_exhausted,
        "pre_rec_exhausted": pre_rec_exhausted,
        "pre_rec_rows": _keyboard_rows(kb_pre_rec),
        "pre_once_rows": _keyboard_rows(kb_pre_once),
        "pre_inactive_rows": _keyboard_rows(kb_pre_inactive),
        "main_rec_rows": _keyboard_rows(kb_main_rec),
        "main_once_rows": _keyboard_rows(kb_main_once),
        "main_inactive_rows": _keyboard_rows(kb_main_inactive),
    })

    if not all(checks.values()):
        dbg.problem("fired_message_checks_failed", {"checks": checks})


def _parse_iso_optional(value):
    if not value:
        return None, None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed, None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed, None
    except (TypeError, ValueError) as exc:
        return None, str(exc)


async def _run_missed_behavior_check(dbg, deps):
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = deps.constants.WEEKDAYS[now.weekday()]

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = deps.storage_manager_cls(base_data_dir=tmpdir)
        user_id = "1001"
        storage.setup_user_space(user_id)

        recurring_id = storage.save_alert(user_id, {
            "title": "Recurring Missed",
            "type": 3,
            "type_name": deps.constants.ALERT_TYPES[3],
            "schedule": {"weekdays": [weekday], "interval": 1, "time": "10:00"},
            "pre_alerts": ["1h"],
            "tags": [],
        })
        one_time_id = storage.save_alert(user_id, {
            "title": "OneTime Missed",
            "type": 5,
            "type_name": deps.constants.ALERT_TYPES[5],
            "schedule": {"date": (now + timedelta(days=1)).strftime("%d/%m/%Y"), "time": "10:00"},
            "pre_alerts": [],
            "tags": [],
        })

        past_due = now - timedelta(hours=2)
        storage.update_alert_schedule_state(user_id, recurring_id, next_scheduled=past_due)
        storage.update_alert_schedule_state(user_id, one_time_id, next_scheduled=past_due)

        previous_storage = deps.scheduler_module._storage
        previous_app = deps.scheduler_module._app
        previous_send_missed = deps.scheduler_module.send_missed_alerts_batch

        class _DummyApp:
            bot = object()

        async def _fake_send_missed_alerts_batch(_bot, _user_id, _missed_alerts):
            return {"ok": True}

        try:
            deps.scheduler_module._storage = storage
            deps.scheduler_module._app = _DummyApp()
            deps.scheduler_module.send_missed_alerts_batch = _fake_send_missed_alerts_batch
            await deps.scheduler_module.handle_missed_alerts()
        finally:
            deps.scheduler_module._storage = previous_storage
            deps.scheduler_module._app = previous_app
            deps.scheduler_module.send_missed_alerts_batch = previous_send_missed

        recurring_after = storage.get_alert_by_id(user_id, recurring_id) or {}
        one_time_after = storage.get_alert_by_id(user_id, one_time_id) or {}
        recurring_next_raw = recurring_after.get("next_scheduled")
        recurring_next, recurring_next_iso_error = _parse_iso_optional(recurring_next_raw)

        checks = {
            "recurring_still_active": recurring_after.get("active", True) is True,
            "recurring_next_iso_valid": recurring_next_iso_error is None,
            "recurring_next_updated_future": recurring_next is not None and recurring_next > now,
            "one_time_deactivated": one_time_after.get("active") is False,
        }

        dbg.section("missed_toggle_behavior", {
            "checks": checks,
            "recurring_active": recurring_after.get("active"),
            "recurring_next_scheduled": recurring_next_raw,
            "recurring_next_iso_error": recurring_next_iso_error,
            "one_time_active": one_time_after.get("active"),
        })

        if not all(checks.values()):
            dbg.problem("missed_toggle_behavior_failed", {
                "checks": checks,
                "recurring": recurring_after,
                "one_time": one_time_after,
            })


async def _run_type2_last_cache_repair_check(dbg, deps):
    fixed_now = datetime(2026, 3, 27, 22, 58, 25)
    expected_next = datetime(2026, 3, 27, 23, 0, 0)
    scenarios = [
        {"name": "naive_iso", "invalid_cached": "2026-05-01T23:00:00"},
        {"name": "aware_iso_utc", "invalid_cached": "2026-05-01T23:00:00+00:00"},
    ]
    scenario_results = []
    all_ok = True

    from modules.scheduler_core import coordinator as coordinator_module

    for scenario in scenarios:
        invalid_cached = scenario["invalid_cached"]
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = deps.storage_manager_cls(base_data_dir=tmpdir)
            user_id = "1201"
            storage.setup_user_space(user_id)
            alert_id = storage.save_alert(user_id, {
                "title": "Type2 Last Cached Repair",
                "type": 2,
                "type_name": deps.constants.ALERT_TYPES[2],
                "schedule": {
                    "ordinals": ["Last"],
                    "weekdays": ["Fri"],
                    "interval": 1,
                    "time": "23:00",
                },
                "pre_alerts": [],
                "tags": [],
            })
            storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=invalid_cached)

            previous_storage = coordinator_module._storage
            previous_app = coordinator_module._app
            previous_now_fn = coordinator_module.now_server_naive
            load_error = None
            try:
                coordinator_module._storage = storage
                coordinator_module._app = None
                coordinator_module.now_server_naive = lambda: fixed_now
                await coordinator_module.load_all_alerts()
            except Exception as exc:
                load_error = str(exc)
            finally:
                coordinator_module._storage = previous_storage
                coordinator_module._app = previous_app
                coordinator_module.now_server_naive = previous_now_fn

            alert_after = storage.get_alert_by_id(user_id, alert_id) or {}
            corrected_raw = alert_after.get("next_scheduled")
            corrected_dt, corrected_iso_error = _parse_iso_optional(corrected_raw)

            checks = {
                "load_ok": load_error is None,
                "corrected_iso_valid": corrected_iso_error is None,
                "corrected_expected": corrected_dt == expected_next,
                "changed_from_invalid": corrected_raw != invalid_cached,
            }
            if not all(checks.values()):
                all_ok = False

            scenario_results.append({
                "name": scenario["name"],
                "invalid_cached": invalid_cached,
                "checks": checks,
                "corrected_next_scheduled": corrected_raw,
                "iso_error": corrected_iso_error,
                "load_error": load_error,
            })

    dbg.section("type2_last_cached_repair", {
        "fixed_now": fixed_now.isoformat(),
        "expected_next": expected_next.isoformat(),
        "scenarios": scenario_results,
    })

    if not all_ok:
        dbg.problem("type2_last_cached_repair_failed", {
            "fixed_now": fixed_now.isoformat(),
            "expected_next": expected_next.isoformat(),
            "scenarios": scenario_results,
        })


class _FakePhoto:
    def __init__(self, file_id):
        self.file_id = file_id


class _FakeMessage:
    def __init__(self, file_id=None):
        self.photo = []
        if file_id:
            self.photo = [_FakePhoto(file_id)]


class _FakeBot:
    def __init__(self, bad_file_ids=None, local_file_id="scheduler_healed_file_id"):
        self.bad_file_ids = set(bad_file_ids or set())
        self.local_file_id = local_file_id
        self.photo_calls = []
        self.message_calls = []

    async def send_photo(self, chat_id, photo, caption, reply_markup=None, parse_mode=None):
        from telegram.error import BadRequest

        call = {
            "chat_id": chat_id,
            "photo_is_str": isinstance(photo, str),
            "photo_value": photo if isinstance(photo, str) else getattr(photo, "name", "<stream>"),
            "caption_len": len(caption or ""),
            "has_reply_markup": bool(reply_markup),
            "parse_mode": parse_mode,
        }
        self.photo_calls.append(call)
        if isinstance(photo, str) and photo in self.bad_file_ids:
            raise BadRequest("Wrong file identifier/HTTP URL specified")
        if isinstance(photo, str):
            return _FakeMessage(file_id=photo)
        return _FakeMessage(file_id=self.local_file_id)

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.message_calls.append({
            "chat_id": chat_id,
            "text": text,
            "text_len": len(text or ""),
            "has_reply_markup": bool(reply_markup),
            "parse_mode": parse_mode,
        })
        return _FakeMessage()


def _touch_file(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"img")


async def _run_media_fallback_check(dbg, deps):
    now = datetime.now().replace(second=0, microsecond=0)
    tomorrow = now + timedelta(days=1)
    tomorrow_date = tomorrow.strftime("%d/%m/%Y")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = deps.storage_manager_cls(base_data_dir=tmpdir)
        user_id = "1101"
        user_dir = storage.setup_user_space(user_id)
        images_dir = os.path.join(user_dir, "images")
        captured_events = []
        original_log_user_event = storage.log_user_event

        def _capture_log_user_event(log_user_id, event_type, payload=None):
            captured_events.append({
                "user_id": str(log_user_id),
                "event": event_type,
                "payload": dict(payload or {}),
            })
            return original_log_user_event(log_user_id, event_type, payload)

        storage.log_user_event = _capture_log_user_event
        local_rel = "images/scheduler_media_ok.jpg"
        local_abs = os.path.join(images_dir, "scheduler_media_ok.jpg")
        _touch_file(local_abs)

        alert_local_id = storage.save_alert(user_id, {
            "title": "Scheduler Local Fallback",
            "type": 5,
            "type_name": deps.constants.ALERT_TYPES[5],
            "schedule": {"date": tomorrow_date, "time": now.strftime("%H:%M")},
            "pre_alerts": [],
            "tags": [],
            "image_id": "broken_image_id_local",
            "local_image_path": local_rel,
        })
        alert_missing_id = storage.save_alert(user_id, {
            "title": "Scheduler Text Fallback",
            "type": 5,
            "type_name": deps.constants.ALERT_TYPES[5],
            "schedule": {"date": tomorrow_date, "time": now.strftime("%H:%M")},
            "pre_alerts": [],
            "tags": [],
            "image_id": "broken_image_id_missing",
            "local_image_path": "images/does_not_exist.jpg",
        })
        birthday_id = storage.save_alert(user_id, {
            "title": "Scheduler Birthday",
            "type": 6,
            "type_name": deps.constants.ALERT_TYPES[6],
            "schedule": {"date": tomorrow.strftime("%d/%m"), "time": "10:00"},
            "pre_alerts": [],
            "tags": [],
            "birth_year": 2000,
            "image_id": "broken_birthday_image",
            "local_image_path": local_rel,
        })

        alert_local = storage.get_alert_by_id(user_id, alert_local_id)
        alert_missing = storage.get_alert_by_id(user_id, alert_missing_id)
        birthday_alert = storage.get_alert_by_id(user_id, birthday_id)

        bot_local = _FakeBot(bad_file_ids={"broken_image_id_local"}, local_file_id="scheduler_healed_file_id")
        msg_local = await deps.send_alert(
            bot_local,
            user_id,
            alert_local,
            storage=storage,
            alert_type=deps.constants.ALERT_MSG_TYPE_MAIN,
            scheduled_time=now,
            occurrence_time=now,
        )
        alert_local_after = storage.get_alert_by_id(user_id, alert_local_id) or {}

        bot_missing = _FakeBot(bad_file_ids={"broken_image_id_missing"})
        msg_missing = await deps.send_alert(
            bot_missing,
            user_id,
            alert_missing,
            storage=storage,
            alert_type=deps.constants.ALERT_MSG_TYPE_MAIN,
            scheduled_time=now,
            occurrence_time=now,
        )
        alert_missing_after = storage.get_alert_by_id(user_id, alert_missing_id) or {}

        bot_birthday = _FakeBot(bad_file_ids={"broken_birthday_image"})
        msg_birthday = await deps.send_alert(
            bot_birthday,
            user_id,
            birthday_alert,
            storage=storage,
            alert_type=deps.constants.ALERT_MSG_TYPE_MAIN,
            scheduled_time=now,
            occurrence_time=now,
        )

        def _last_media_result(alert_id):
            matches = [
                event for event in captured_events
                if event.get("event") == "scheduler_alert_media_result"
                and event.get("payload", {}).get("alert_id") == alert_id
            ]
            return matches[-1] if matches else None

        local_result = _last_media_result(alert_local_id)
        missing_result = _last_media_result(alert_missing_id)
        birthday_result = _last_media_result(birthday_id)

        checks = {
            "local_fallback_sent": msg_local is not None,
            "local_fallback_photo_attempts": len(bot_local.photo_calls) == 2,
            "local_first_uses_file_id": len(bot_local.photo_calls) >= 1 and bot_local.photo_calls[0]["photo_is_str"] is True,
            "local_second_uses_file_stream": len(bot_local.photo_calls) >= 2 and bot_local.photo_calls[1]["photo_is_str"] is False,
            "local_no_text_fallback": len(bot_local.message_calls) == 0,
            "local_image_autohealed": alert_local_after.get("image_id") == "scheduler_healed_file_id",
            "local_reason_autoheal": isinstance(local_result, dict) and local_result.get("payload", {}).get("reason_code") == "autoheal_image_id",
            "missing_fallback_sent": msg_missing is not None,
            "missing_photo_attempts_once": len(bot_missing.photo_calls) == 1,
            "missing_text_fallback_used": len(bot_missing.message_calls) == 1,
            "missing_not_autohealed": alert_missing_after.get("image_id") == "broken_image_id_missing",
            "missing_reason_fallback_to_text": isinstance(missing_result, dict) and missing_result.get("payload", {}).get("reason_code") == "fallback_to_text",
            "missing_reasons_include_invalid_image_id": isinstance(missing_result, dict) and "invalid_image_id" in (missing_result.get("payload", {}).get("fallback_reasons") or []),
            "missing_reasons_include_local_file_missing": isinstance(missing_result, dict) and "local_file_missing" in (missing_result.get("payload", {}).get("fallback_reasons") or []),
            "birthday_sent_without_media": msg_birthday is not None and len(bot_birthday.photo_calls) == 0 and len(bot_birthday.message_calls) == 1,
            "birthday_reason_fallback_to_text": isinstance(birthday_result, dict) and birthday_result.get("payload", {}).get("reason_code") == "fallback_to_text",
        }

        dbg.section("scheduler_media_fallback_checks", {
            "checks": checks,
            "local_photo_calls": bot_local.photo_calls,
            "local_message_calls": bot_local.message_calls,
            "missing_photo_calls": bot_missing.photo_calls,
            "missing_message_calls": bot_missing.message_calls,
            "birthday_photo_calls": bot_birthday.photo_calls,
            "birthday_message_calls": bot_birthday.message_calls,
            "local_alert_after_image_id": alert_local_after.get("image_id"),
            "missing_alert_after_image_id": alert_missing_after.get("image_id"),
            "local_result_event": local_result,
            "missing_result_event": missing_result,
            "birthday_result_event": birthday_result,
        })

        if not all(checks.values()):
            dbg.problem("scheduler_media_fallback_checks_failed", {
                "checks": checks,
                "local_photo_calls": bot_local.photo_calls,
                "local_message_calls": bot_local.message_calls,
                "missing_photo_calls": bot_missing.photo_calls,
                "missing_message_calls": bot_missing.message_calls,
                "birthday_photo_calls": bot_birthday.photo_calls,
                "birthday_message_calls": bot_birthday.message_calls,
                "local_alert_after_image_id": alert_local_after.get("image_id"),
                "missing_alert_after_image_id": alert_missing_after.get("image_id"),
                "local_result_event": local_result,
                "missing_result_event": missing_result,
                "birthday_result_event": birthday_result,
            })

    with tempfile.TemporaryDirectory() as storage_root, tempfile.TemporaryDirectory() as legacy_root:
        storage = deps.storage_manager_cls(base_data_dir=storage_root)
        user_id = "1102"
        storage.setup_user_space(user_id)

        legacy_images = os.path.join(legacy_root, str(user_id), "images")
        os.makedirs(legacy_images, exist_ok=True)
        legacy_abs = os.path.join(legacy_images, "legacy_escape.jpg")
        _touch_file(legacy_abs)

        alert = {
            "id": "legacy_guard",
            "title": "Legacy Guard",
            "type": 5,
            "type_name": deps.constants.ALERT_TYPES[5],
            "schedule": {"date": (now + timedelta(days=1)).strftime("%d/%m/%Y"), "time": now.strftime("%H:%M")},
            "pre_alerts": [],
            "tags": [],
            "image_id": "broken_legacy_file_id",
            "local_image_path": legacy_abs,
            "active": True,
        }

        bot = _FakeBot(bad_file_ids={"broken_legacy_file_id"})

        # Guard against regressions: even if DATA_DIR points to a path containing the file,
        # storage-backed resolution must win and reject out-of-scope media.
        send_alert_globals = deps.send_alert.__globals__
        original_data_dir = send_alert_globals.get("DATA_DIR")
        send_alert_globals["DATA_DIR"] = legacy_root
        try:
            msg = await deps.send_alert(
                bot,
                user_id,
                alert,
                storage=storage,
                alert_type=deps.constants.ALERT_MSG_TYPE_MAIN,
                scheduled_time=now,
                occurrence_time=now,
            )
        finally:
            send_alert_globals["DATA_DIR"] = original_data_dir

        checks = {
            "send_succeeds_text_mode": msg is not None,
            "no_local_legacy_fallback": len(bot.photo_calls) == 1,
            "text_fallback_used": len(bot.message_calls) == 1,
        }
        dbg.section("scheduler_storage_scope_guard", {
            "checks": checks,
            "photo_calls": bot.photo_calls,
            "message_calls": bot.message_calls,
            "legacy_abs": legacy_abs,
            "storage_root": storage_root,
            "legacy_root": legacy_root,
        })
        if not all(checks.values()):
            dbg.problem("scheduler_storage_scope_guard_failed", {
                "checks": checks,
                "photo_calls": bot.photo_calls,
                "message_calls": bot.message_calls,
                "legacy_abs": legacy_abs,
                "storage_root": storage_root,
                "legacy_root": legacy_root,
            })


def _check_creation_time_boundaries(dbg, deps):
    reference = datetime(2026, 2, 2, 12, 0, 0)
    weekday = deps.constants.WEEKDAYS[reference.weekday()]
    day = reference.day
    month = reference.month

    cases = {
        "type1_monthly_day": (
            _build_alert(deps.constants, "b1a", "T1 After", 1, {"days": [day], "interval": 1, "time": "12:02"}),
            _build_alert(deps.constants, "b1b", "T1 Before", 1, {"days": [day], "interval": 1, "time": "11:58"}),
        ),
        "type2_monthly_relative": (
            _build_alert(deps.constants, "b2a", "T2 After", 2, {"ordinals": ["1st"], "weekdays": [weekday], "interval": 1, "time": "12:02"}),
            _build_alert(deps.constants, "b2b", "T2 Before", 2, {"ordinals": ["1st"], "weekdays": [weekday], "interval": 1, "time": "11:58"}),
        ),
        "type3_weekly": (
            _build_alert(deps.constants, "b3a", "T3 After", 3, {"weekdays": [weekday], "interval": 1, "time": "12:02"}),
            _build_alert(deps.constants, "b3b", "T3 Before", 3, {"weekdays": [weekday], "interval": 1, "time": "11:58"}),
        ),
        "type4_yearly": (
            _build_alert(deps.constants, "b4a", "T4 After", 4, {"dates": f"{day}/{month}", "time": "12:02"}),
            _build_alert(deps.constants, "b4b", "T4 Before", 4, {"dates": f"{day}/{month}", "time": "11:58"}),
        ),
    }

    results = {}
    all_ok = True
    for label, (after_alert, before_alert) in cases.items():
        after_occ = deps.get_next_occurrence(after_alert, reference)
        before_occ = deps.get_next_occurrence(before_alert, reference)
        checks = {
            "after_exists": bool(after_occ),
            "after_same_day": bool(after_occ and after_occ.date() == reference.date()),
            "after_future": bool(after_occ and after_occ > reference),
            "before_exists": bool(before_occ),
            "before_not_same_day": bool(before_occ and before_occ.date() != reference.date()),
            "before_future": bool(before_occ and before_occ > reference),
        }
        ok = all(checks.values())
        all_ok = all_ok and ok
        results[label] = {
            "checks": checks,
            "after_occurrence": after_occ.isoformat() if after_occ else None,
            "before_occurrence": before_occ.isoformat() if before_occ else None,
        }

    dbg.section("creation_boundary_checks", {
        "reference": reference.isoformat(),
        "results": results,
    })

    if not all_ok:
        dbg.problem("creation_boundary_checks_failed", {
            "reference": reference.isoformat(),
            "results": results,
        })


def _check_markdown_hardening(dbg, deps, run_async):
    md_escape = deps.format_main_alert.__globals__.get("_md_escape")
    if not callable(md_escape):
        dbg.problem("scheduler_markdown_escape_helper_missing", {})
        return

    now = datetime(2026, 2, 2, 12, 0, 0)
    due_time = now + timedelta(hours=2)
    weekday = deps.constants.WEEKDAYS[due_time.weekday()]
    unsafe_title = r"Unsafe_[*`[title\end"
    tags = ["🏷️ tag_[x]", "⚙️ stage*one`["]

    recurring = _build_alert(
        deps.constants,
        "md_case",
        unsafe_title,
        3,
        {"weekdays": [weekday], "interval": 1, "time": due_time.strftime("%H:%M")},
        pre_alerts=["30m"],
    )
    recurring["tags"] = list(tags)

    main_msg = deps.format_main_alert(recurring, due_time)
    pre_msg = deps.format_pre_alert(recurring, due_time, due_time - timedelta(minutes=30))
    missed_msg = deps.format_missed_alert(recurring, due_time - timedelta(hours=1))
    summary_msg = deps.format_missed_alerts_summary([{
        "alert": {
            **recurring,
            "tags": ["[x] risky"],
        },
        "missed_pre": [due_time - timedelta(minutes=30)],
        "missed_due": [due_time],
        "upcoming_pre": [],
        "upcoming_due": [],
    }])

    escaped_title_upper = md_escape(unsafe_title.upper())
    escaped_title_plain = md_escape(unsafe_title)
    escaped_tags = md_escape(", ".join(tags))
    escaped_risky_tag_icon = md_escape("[x]")

    sync_checks = {
        "main_title_escaped": f"📌 **{escaped_title_upper}**" in main_msg,
        "main_tags_escaped": f"🏷️ Tags: `{escaped_tags}`" in main_msg,
        "main_no_raw_title": unsafe_title.upper() not in main_msg,
        "pre_title_escaped": f"📌 **{escaped_title_upper}**" in pre_msg,
        "pre_tags_escaped": f"🏷️ Tags: `{escaped_tags}`" in pre_msg,
        "pre_no_raw_title": unsafe_title.upper() not in pre_msg,
        "missed_title_escaped": f"📌 **{escaped_title_upper}**" in missed_msg,
        "missed_no_raw_title": unsafe_title.upper() not in missed_msg,
        "missed_causality_neutral": "bot was offline" not in missed_msg.lower(),
        "missed_mentions_startup_recovery": "startup recovery" in missed_msg.lower(),
        "summary_title_escaped": escaped_title_plain in (summary_msg or ""),
        "summary_risky_tag_icon_escaped": escaped_risky_tag_icon in (summary_msg or ""),
        "summary_no_raw_title": unsafe_title not in (summary_msg or ""),
        "summary_causality_neutral": "bot was offline" not in (summary_msg or "").lower(),
        "summary_mentions_startup_recovery": "startup recovery" in (summary_msg or "").lower(),
    }

    async def _run_confirmation_checks():
        bot = _FakeBot()
        snooze_msg = await deps.send_snooze_confirmation(bot, "1301", recurring, due_time)
        done_msg = await deps.send_done_confirmation(bot, "1301", recurring, was_one_time=False)
        exhausted_alert = dict(recurring)
        exhausted_alert["repetition"] = {
            "mode": deps.constants.REPETITION_MODE_COUNT,
            "count_remaining": 0,
        }
        done_exhausted_msg = await deps.send_done_confirmation(
            bot,
            "1301",
            exhausted_alert,
            was_one_time=False,
        )

        snooze_text = bot.message_calls[0]["text"] if bot.message_calls else ""
        done_text = bot.message_calls[1]["text"] if len(bot.message_calls) > 1 else ""
        done_exhausted_text = bot.message_calls[2]["text"] if len(bot.message_calls) > 2 else ""
        return {
            "snooze_sent": snooze_msg is not None,
            "done_sent": done_msg is not None,
            "done_exhausted_sent": done_exhausted_msg is not None,
            "snooze_title_escaped": f"**{escaped_title_plain}**" in snooze_text,
            "done_title_escaped": f"**{escaped_title_plain}**" in done_text,
            "done_exhausted_limit_text": "repetition limit reached" in done_exhausted_text.lower(),
            "snooze_parse_mode_markdown": bot.message_calls[0].get("parse_mode") == "Markdown" if bot.message_calls else False,
            "done_parse_mode_markdown": bot.message_calls[1].get("parse_mode") == "Markdown" if len(bot.message_calls) > 1 else False,
            "done_exhausted_parse_mode_markdown": bot.message_calls[2].get("parse_mode") == "Markdown" if len(bot.message_calls) > 2 else False,
            "snooze_no_raw_title": unsafe_title not in snooze_text,
            "done_no_raw_title": unsafe_title not in done_text,
            "done_exhausted_no_raw_title": unsafe_title not in done_exhausted_text,
            "snooze_text": snooze_text,
            "done_text": done_text,
            "done_exhausted_text": done_exhausted_text,
        }

    async_result = run_async(_run_confirmation_checks())
    async_checks = {
        k: v for k, v in async_result.items()
        if k not in {"snooze_text", "done_text", "done_exhausted_text"}
    }
    checks = {**sync_checks, **async_checks}
    dbg.section("scheduler_markdown_hardening", {
        "checks": checks,
        "unsafe_title": unsafe_title,
        "escaped_title_upper": escaped_title_upper,
        "escaped_title_plain": escaped_title_plain,
        "main_msg": main_msg,
        "pre_msg": pre_msg,
        "missed_msg": missed_msg,
        "summary_msg": summary_msg,
        "snooze_text": async_result.get("snooze_text"),
        "done_text": async_result.get("done_text"),
        "done_exhausted_text": async_result.get("done_exhausted_text"),
    })
    if not all(checks.values()):
        dbg.problem("scheduler_markdown_hardening_failed", {
            "checks": checks,
            "unsafe_title": unsafe_title,
            "escaped_title_upper": escaped_title_upper,
            "escaped_title_plain": escaped_title_plain,
            "main_msg": main_msg,
            "pre_msg": pre_msg,
            "missed_msg": missed_msg,
            "summary_msg": summary_msg,
            "snooze_text": async_result.get("snooze_text"),
            "done_text": async_result.get("done_text"),
            "done_exhausted_text": async_result.get("done_exhausted_text"),
        })


def _check_detail_repetition_rendering(dbg, deps):
    reference = datetime(2026, 7, 21, 11, 30)
    weekday = deps.constants.WEEKDAYS[reference.weekday()]

    recurring = _build_alert(
        deps.constants,
        "detail_rep",
        "Detail Repetition",
        3,
        {"weekdays": [weekday], "interval": 1, "time": "11:30"},
        pre_alerts=["30m"],
    )
    recurring["repetition"] = {
        "mode": deps.constants.REPETITION_MODE_COUNT,
        "count_remaining": 2,
    }
    recurring["next_scheduled"] = (reference + timedelta(days=7)).isoformat()

    recurring_exhausted = _build_alert(
        deps.constants,
        "detail_rep_x",
        "Detail Repetition Exhausted",
        3,
        {"weekdays": [weekday], "interval": 1, "time": "11:30"},
        pre_alerts=[],
    )
    recurring_exhausted["repetition"] = {
        "mode": deps.constants.REPETITION_MODE_COUNT,
        "count_remaining": 0,
    }
    recurring_exhausted["next_scheduled"] = None

    one_time = _build_alert(
        deps.constants,
        "detail_once",
        "Detail One Time",
        5,
        {"date": "21/07/2026", "time": "11:30"},
        pre_alerts=[],
    )

    recurring_text = deps.format_detailed_card(recurring)
    recurring_exhausted_text = deps.format_detailed_card(recurring_exhausted)
    one_time_text = deps.format_detailed_card(one_time)

    checks = {
        "recurring_repetition_line_present": "Repetition:" in recurring_text,
        "recurring_repetition_human_count": "Next 2 events" in recurring_text,
        "exhausted_detail_mentions_exhausted": "repetition exhausted" in recurring_exhausted_text.lower(),
        "one_time_no_repetition_line": "Repetition:" not in one_time_text,
    }
    dbg.section("detail_repetition_rendering", {
        "checks": checks,
        "recurring_text": recurring_text,
        "recurring_exhausted_text": recurring_exhausted_text,
        "one_time_text": one_time_text,
    })
    if not all(checks.values()):
        dbg.problem("detail_repetition_rendering_failed", {
            "checks": checks,
            "recurring_text": recurring_text,
            "recurring_exhausted_text": recurring_exhausted_text,
            "one_time_text": one_time_text,
        })


def _check_toggle_context_dispatch(dbg, deps, run_async):
    from modules import constants as C
    from modules.handlers.scheduler_handlers import handle_alert_toggle
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime
    from modules.ui.keyboards.callbacks import build_notif_back_callback

    class _StorageStub:
        def __init__(self, alert):
            self._alert = dict(alert)
            self.events = []

        def toggle_alert(self, user_id, alert_id):
            if str(self._alert.get("id")) != str(alert_id):
                return None
            new_status = not bool(self._alert.get("active", True))
            self._alert["active"] = new_status
            return new_status

        def get_alert_by_id(self, user_id, alert_id):
            if str(self._alert.get("id")) != str(alert_id):
                return None
            return dict(self._alert)

        def get_user_prefs(self, user_id):
            return {}

        def log_user_event(self, user_id, event_type, payload=None):
            self.events.append({"event_type": event_type, "payload": dict(payload or {})})

    class _QueryStub:
        def __init__(self, data, keyboard):
            self.data = data
            self.answer_calls = []
            self.edit_calls = {
                "reply_markup": [],
                "text": [],
                "caption": [],
            }
            self.message = SimpleNamespace(
                reply_markup=SimpleNamespace(inline_keyboard=keyboard),
                photo=None,
            )

        async def answer(self, text=None, show_alert=False):
            self.answer_calls.append({"text": text, "show_alert": bool(show_alert)})

        async def edit_message_reply_markup(self, reply_markup=None):
            self.edit_calls["reply_markup"].append({"reply_markup": reply_markup})

        async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
            self.edit_calls["text"].append(
                {"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode}
            )

        async def edit_message_caption(self, caption=None, reply_markup=None, parse_mode=None):
            self.edit_calls["caption"].append(
                {"caption": caption, "reply_markup": reply_markup, "parse_mode": parse_mode}
            )

    class _BotStub:
        def __init__(self):
            self.sent_messages = []

        async def send_message(self, chat_id, text, **kwargs):
            self.sent_messages.append(
                {"chat_id": chat_id, "text": text, "kwargs": dict(kwargs)}
            )

    def _button(callback_data, text="x"):
        return SimpleNamespace(callback_data=callback_data, text=text)

    async def _run_scenario(name, keyboard):
        now = datetime(2026, 3, 10, 10, 0, 0)
        alert_id = "toggle_ctx_alert"
        alert = _build_alert(
            deps.constants,
            alert_id,
            "Toggle Context Alert",
            3,
            {"weekdays": [deps.constants.WEEKDAYS[now.weekday()]], "interval": 1, "time": "10:00"},
            pre_alerts=[],
            active=True,
        )
        alert["next_scheduled"] = now.isoformat()

        storage = _StorageStub(alert)
        query = _QueryStub(C.CB_ALERT_TOGGLE + alert_id, keyboard)
        context = SimpleNamespace(bot=_BotStub(), bot_data={}, user_data={})
        set_bot_runtime(
            context.bot_data,
            BotRuntime(storage=storage, api_failure_tracker=None),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=1001),
        )
        error = None
        try:
            await handle_alert_toggle(update, context)
        except Exception as exc:  # pragma: no cover
            error = str(exc)

        return {
            "name": name,
            "error": error,
            "answer_calls": list(query.answer_calls),
            "edit_calls": dict(query.edit_calls),
            "fallback_messages": list(context.bot.sent_messages),
        }

    alert_id = "toggle_ctx_alert"
    now = datetime(2026, 3, 10, 10, 0, 0)
    nback_callback = build_notif_back_callback("due", alert_id, now, now)

    notification_result = run_async(
        _run_scenario("notification", [[_button("cb_non_detail")]])
    )
    detail_notif_result = run_async(
        _run_scenario("detail_from_notification", [[_button(nback_callback)]])
    )
    detail_list_result = run_async(
        _run_scenario(
            "detail_from_list",
            [[_button(f"manage_fulledit_{alert_id}")]],
        )
    )

    checks = {
        "notification_no_exception": notification_result["error"] is None,
        "notification_answer_once": len(notification_result["answer_calls"]) == 1,
        "notification_reply_markup_only": (
            len(notification_result["edit_calls"]["reply_markup"]) == 1
            and len(notification_result["edit_calls"]["text"]) == 0
            and len(notification_result["edit_calls"]["caption"]) == 0
        ),
        "notification_no_fallback_msg": len(notification_result["fallback_messages"]) == 0,
        "detail_notif_no_exception": detail_notif_result["error"] is None,
        "detail_notif_answer_once": len(detail_notif_result["answer_calls"]) == 1,
        "detail_notif_text_edit_only": (
            len(detail_notif_result["edit_calls"]["reply_markup"]) == 0
            and len(detail_notif_result["edit_calls"]["text"]) == 1
            and len(detail_notif_result["edit_calls"]["caption"]) == 0
        ),
        "detail_notif_no_fallback_msg": len(detail_notif_result["fallback_messages"]) == 0,
        "detail_list_no_exception": detail_list_result["error"] is None,
        "detail_list_answer_once": len(detail_list_result["answer_calls"]) == 1,
        "detail_list_text_edit_only": (
            len(detail_list_result["edit_calls"]["reply_markup"]) == 0
            and len(detail_list_result["edit_calls"]["text"]) == 1
            and len(detail_list_result["edit_calls"]["caption"]) == 0
        ),
        "detail_list_no_fallback_msg": len(detail_list_result["fallback_messages"]) == 0,
    }
    dbg.section(
        "toggle_context_dispatch",
        {
            "checks": checks,
            "notification": notification_result,
            "detail_from_notification": detail_notif_result,
            "detail_from_list": detail_list_result,
        },
    )
    if not all(checks.values()):
        dbg.problem("toggle_context_dispatch_failed", {"checks": checks})


def run_checks(dbg, deps, run_async):
    _check_constants_compatibility(dbg, deps)
    _check_fired_message_variants(dbg, deps)
    run_async(_run_missed_behavior_check(dbg, deps))
    run_async(_run_type2_last_cache_repair_check(dbg, deps))
    run_async(_run_media_fallback_check(dbg, deps))
    _check_creation_time_boundaries(dbg, deps)
    _check_markdown_hardening(dbg, deps, run_async)
    _check_detail_repetition_rendering(dbg, deps)
    _check_toggle_context_dispatch(dbg, deps, run_async)
