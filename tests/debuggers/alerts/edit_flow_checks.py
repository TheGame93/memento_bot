import asyncio
import copy
import sys
import tempfile
import types
from datetime import datetime, timedelta

from modules import constants as C
from modules.storage import StorageManager
from modules.timezone_utils import now_server_naive
from telegram.ext import ConversationHandler


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self, text=None, message_id=100, photo=None, caption=None):
        self.text = text
        self.caption = caption
        self.message_id = message_id
        self.replies = []
        self.edits = []
        self.reply_markup = None
        self.photo = photo

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        payload = {
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.replies.append(payload)
        self.reply_markup = reply_markup
        return self

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        payload = {
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.edits.append(payload)
        self.reply_markup = reply_markup
        return self


class _DummyCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = []
        self.edits = []
        self.caption_edits = []
        self.reply_markup_edits = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({
            "text": text,
            "show_alert": show_alert,
        })

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        payload = {
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.edits.append(payload)
        self.message.reply_markup = reply_markup
        self.message.edits.append(payload)
        return self.message

    async def edit_message_caption(self, caption, reply_markup=None, parse_mode=None):
        payload = {
            "caption": caption,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.caption_edits.append(payload)
        self.message.caption = caption
        self.message.reply_markup = reply_markup
        self.message.edits.append(payload)
        return self.message

    async def edit_message_reply_markup(self, reply_markup=None):
        self.reply_markup_edits.append(reply_markup)
        self.message.reply_markup = reply_markup
        return self.message


class _DummyUpdate:
    def __init__(self, *, user_id=1001, message=None, callback_query=None):
        self.effective_user = _DummyUser(user_id)
        self.message = message
        self.callback_query = callback_query
        self.effective_message = message or getattr(callback_query, "message", None)
        self.effective_chat = types.SimpleNamespace(id=user_id)


class _DummyBot:
    def __init__(self):
        self.sent_messages = []
        self.edit_text_calls = []
        self.edit_caption_calls = []
        self.delete_calls = []
        self.fail_edit_text_ids = set()
        self.fail_edit_caption_ids = set()
        self.fail_delete_ids = set()
        self.operations = []

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        message_id = 9000 + len(self.sent_messages) + 1
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.sent_messages.append(payload)
        self.operations.append({"op": "send_message", "text": text})
        return _DummyMessage(text=text, message_id=message_id)

    async def edit_message_text(self, *, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.edit_text_calls.append(payload)
        self.operations.append({"op": "edit_message_text", "text": text})
        if message_id in self.fail_edit_text_ids:
            raise RuntimeError("message to edit not found")
        return _DummyMessage(text=text, message_id=message_id)

    async def edit_message_caption(self, *, chat_id, message_id, caption, reply_markup=None, parse_mode=None):
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.edit_caption_calls.append(payload)
        self.operations.append({"op": "edit_message_caption", "caption": caption})
        if message_id in self.fail_edit_caption_ids:
            raise RuntimeError("message caption edit failed")
        return _DummyMessage(caption=caption, message_id=message_id, photo=[object()])

    async def delete_message(self, *, chat_id, message_id):
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        self.delete_calls.append(payload)
        self.operations.append({"op": "delete_message", "message_id": message_id})
        if message_id in self.fail_delete_ids:
            raise RuntimeError("message to delete not found")
        return True


class _DummyContext:
    def __init__(self, user_data=None, bot=None):
        self.user_data = dict(user_data or {})
        self.bot = bot or _DummyBot()
        self.bot_data = {}
        storage = getattr(sys.modules.get("mainbot"), "storage", None)
        if storage is not None:
            try:
                from modules.shared.runtime_context import BotRuntime, set_bot_runtime

                set_bot_runtime(
                    self.bot_data,
                    BotRuntime(storage=storage, api_failure_tracker=None),
                )
            except Exception:
                pass


class _FakeStorage:
    def __init__(self, alerts_by_id=None, user_tags=None):
        self._alerts_by_id = copy.deepcopy(alerts_by_id or {})
        self._user_tags = list(user_tags or [])
        self.events = []

    def get_alert_by_id(self, user_id, alert_id):
        alert = self._alerts_by_id.get(alert_id)
        return copy.deepcopy(alert) if isinstance(alert, dict) else None

    def get_user_tags(self, user_id):
        return list(self._user_tags)

    def get_user_prefs(self, user_id):
        return {}

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": str(user_id),
            "event_type": str(event_type),
            "payload": dict(payload or {}),
        })


def _extract_callback_rows(reply_markup):
    rows = []
    if not reply_markup:
        return rows
    for row in getattr(reply_markup, "inline_keyboard", []) or []:
        rows.append([getattr(button, "callback_data", None) for button in row])
    return rows


def _extract_button_labels(reply_markup):
    labels = []
    if not reply_markup:
        return labels
    for row in getattr(reply_markup, "inline_keyboard", []) or []:
        for button in row:
            labels.append(getattr(button, "text", ""))
    return labels


def _parse_iso_datetime(raw_text):
    try:
        return datetime.fromisoformat(raw_text) if raw_text else None
    except Exception:
        return None


def _build_reply_markup(callback_rows):
    keyboard = []
    for row in callback_rows:
        buttons = []
        for callback_data in row:
            buttons.append(
                types.SimpleNamespace(
                    callback_data=callback_data,
                    text="btn",
                )
            )
        keyboard.append(buttons)
    return types.SimpleNamespace(inline_keyboard=keyboard)


def run_dashboard_keyboard_checks(dashboard_mod):
    weekly = dashboard_mod.build_edit_dashboard_keyboard(3)
    one_time = dashboard_mod.build_edit_dashboard_keyboard(5)
    birthday = dashboard_mod.build_edit_dashboard_keyboard(6)

    weekly_callbacks = {cb for row in _extract_callback_rows(weekly) for cb in row if isinstance(cb, str)}
    one_time_callbacks = {cb for row in _extract_callback_rows(one_time) for cb in row if isinstance(cb, str)}
    birthday_callbacks = {cb for row in _extract_callback_rows(birthday) for cb in row if isinstance(cb, str)}

    birthday_text_with_year = dashboard_mod.format_edit_dashboard_text({
        "type": 6,
        "type_name": C.ALERT_TYPES.get(6, "Birthday"),
        "title": "Alice",
        "schedule": {"date": "25/12", "time": "09:30"},
        "birth_year": 1990,
        "tags": [],
        "pre_alerts": [],
        "additional_info": "",
    })
    birthday_text_without_year = dashboard_mod.format_edit_dashboard_text({
        "type": 6,
        "type_name": C.ALERT_TYPES.get(6, "Birthday"),
        "title": "Bob",
        "schedule": {"date": "01/01"},
        "tags": [],
        "pre_alerts": [],
        "additional_info": "",
    })
    one_time_text_with_prealert = dashboard_mod.format_edit_dashboard_text({
        "type": 5,
        "type_name": C.ALERT_TYPES.get(5, "Once"),
        "title": "Tax deadline",
        "schedule": {"date": "10/03/2099", "time": "10:00"},
        "tags": [],
        "pre_alerts": ["1h"],
        "additional_info": "",
    })

    checks = {
        "weekly_has_schedule_edit": "ed_schedule" in weekly_callbacks,
        "weekly_has_change_type": "ed_change_type" in weekly_callbacks,
        "weekly_has_interval": "ed_interval" in weekly_callbacks,
        "weekly_has_time": "ed_time" in weekly_callbacks,
        "weekly_has_repetition": "ed_repetition" in weekly_callbacks,
        "one_time_has_schedule_edit": "ed_schedule" in one_time_callbacks,
        "one_time_no_interval": "ed_interval" not in one_time_callbacks,
        "one_time_no_repetition": "ed_repetition" not in one_time_callbacks,
        "birthday_has_date_edit": "ed_bday_date" in birthday_callbacks,
        "birthday_no_schedule_edit": "ed_schedule" not in birthday_callbacks,
        "birthday_no_change_type": "ed_change_type" not in birthday_callbacks,
        "birthday_no_interval": "ed_interval" not in birthday_callbacks,
        "birthday_no_time": "ed_time" not in birthday_callbacks,
        "birthday_no_repetition": "ed_repetition" not in birthday_callbacks,
        "birthday_has_done": "ed_done" in birthday_callbacks,
        "birthday_text_has_date_line": "• Birthday date: 25/12" in birthday_text_with_year,
        "birthday_text_has_birth_year_line": "• Birth year: 1990" in birthday_text_with_year,
        "birthday_text_has_birth_year_not_set_signal": "• Birth year: not set" in birthday_text_without_year,
        "one_time_prealert_rendered_as_datetime": "• Pre-alerts: 10/03/2099 09:00" in one_time_text_with_prealert,
    }
    return {
        "weekly_callbacks": sorted(weekly_callbacks),
        "one_time_callbacks": sorted(one_time_callbacks),
        "birthday_callbacks": sorted(birthday_callbacks),
        "birthday_text_with_year": birthday_text_with_year,
        "birthday_text_without_year": birthday_text_without_year,
        "one_time_text_with_prealert": one_time_text_with_prealert,
        "checks": checks,
    }


def run_commit_plan_checks(flow_mod):
    now_ref = now_server_naive()
    future_date = (now_ref + timedelta(days=3)).strftime("%d/%m/%Y")
    past_date = (now_ref - timedelta(days=3)).strftime("%d/%m/%Y")

    original = {
        "title": "Pay bills",
        "type": 3,
        "type_name": C.ALERT_TYPES.get(3),
        "tags": [],
        "pre_alerts": [],
        "additional_info": "",
        "image_id": None,
        "local_image_path": None,
        "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
        "active": True,
    }
    changed_time = copy.deepcopy(original)
    changed_time["schedule"]["time"] = "11:30"
    title_only = copy.deepcopy(original)
    title_only["title"] = "Pay utility bills"
    repetition_only = copy.deepcopy(original)
    repetition_only["repetition"] = {"mode": C.REPETITION_MODE_COUNT, "count_remaining": 3}
    original["repetition"] = {"mode": C.REPETITION_MODE_FOREVER, "until_date": None, "count_remaining": None}
    changed_time["repetition"] = copy.deepcopy(original["repetition"])
    title_only["repetition"] = copy.deepcopy(original["repetition"])

    plan_schedule = flow_mod._build_commit_plan(changed_time, original, now_ref, user_prefs={})
    plan_title = flow_mod._build_commit_plan(title_only, original, now_ref, user_prefs={})
    plan_repetition = flow_mod._build_commit_plan(repetition_only, original, now_ref, user_prefs={})

    one_time_original = {
        "title": "Expired one-time",
        "type": 5,
        "type_name": C.ALERT_TYPES.get(5),
        "tags": [],
        "pre_alerts": [],
        "additional_info": "",
        "image_id": None,
        "local_image_path": None,
        "schedule": {"date": past_date, "time": "10:00"},
        "active": False,
    }
    one_time_future = copy.deepcopy(one_time_original)
    one_time_future["schedule"]["date"] = future_date
    plan_reactivate = flow_mod._build_commit_plan(one_time_future, one_time_original, now_ref, user_prefs={})

    one_time_past = copy.deepcopy(one_time_original)
    one_time_past["schedule"]["date"] = past_date
    plan_keep_inactive = flow_mod._build_commit_plan(one_time_past, one_time_original, now_ref, user_prefs={})

    birthday_original = {
        "title": "Alice",
        "type": 6,
        "type_name": C.ALERT_TYPES.get(6),
        "tags": [],
        "pre_alerts": [],
        "additional_info": "",
        "image_id": None,
        "local_image_path": None,
        "schedule": {"date": "01/01", "time": "08:00"},
        "birth_year": 1990,
        "active": True,
    }
    birthday_changed_year = copy.deepcopy(birthday_original)
    birthday_changed_year["birth_year"] = 1991
    birthday_cleared_year = copy.deepcopy(birthday_original)
    birthday_cleared_year.pop("birth_year", None)

    plan_bday_year_changed = flow_mod._build_commit_plan(
        birthday_changed_year,
        birthday_original,
        now_ref,
        user_prefs={},
    )
    plan_bday_year_cleared = flow_mod._build_commit_plan(
        birthday_cleared_year,
        birthday_original,
        now_ref,
        user_prefs={},
    )

    snapshot = flow_mod._prepare_edit_snapshot({
        "title": "Legacy",
        "type": 6,
        "type_name": C.ALERT_TYPES.get(6),
        "schedule": {"date": "03/03", "time": "08:00"},
        "birth_year": 1980,
        "birthday_metadata": {"legacy": True},
    })

    checks = {
        "schedule_change_detected": bool(plan_schedule.get("schedule_changed")),
        "title_only_not_schedule_change": not bool(plan_title.get("schedule_changed")),
        "title_only_changed_field_detected": "title" in (plan_title.get("changed_fields") or []),
        "repetition_changed_field_detected": "repetition" in (plan_repetition.get("changed_fields") or []),
        "repetition_only_not_schedule_change": not bool(plan_repetition.get("schedule_changed")),
        "repetition_updates_present": isinstance((plan_repetition.get("updates") or {}).get("repetition"), dict),
        "future_one_time_reactivates": bool(plan_reactivate.get("reactivate_one_time")),
        "future_one_time_updates_active": bool((plan_reactivate.get("updates") or {}).get("active")),
        "past_one_time_not_reactivated": not bool(plan_keep_inactive.get("reactivate_one_time")),
        "birthday_year_changed_field_detected": "birth_year" in (plan_bday_year_changed.get("changed_fields") or []),
        "birthday_year_change_not_schedule_change": not bool(plan_bday_year_changed.get("schedule_changed")),
        "birthday_year_update_present": (plan_bday_year_changed.get("updates") or {}).get("birth_year") == 1991,
        "birthday_year_clear_detected": "birth_year" in (plan_bday_year_cleared.get("changed_fields") or []),
        "birthday_year_cleared_to_none": (plan_bday_year_cleared.get("updates") or {}).get("birth_year") is None,
        "vestigial_birthday_metadata_not_emitted": (
            "birthday_metadata" not in (plan_bday_year_changed.get("updates") or {})
            and "birthday_metadata" not in (plan_bday_year_changed.get("changed_fields") or [])
            and "birthday_metadata" not in (plan_bday_year_cleared.get("updates") or {})
            and "birthday_metadata" not in (plan_bday_year_cleared.get("changed_fields") or [])
        ),
        "snapshot_tracks_birth_year": snapshot.get("birth_year") == 1980,
        "snapshot_drops_legacy_birthday_metadata": "birthday_metadata" not in snapshot,
    }
    return {
        "plan_schedule": plan_schedule,
        "plan_title": plan_title,
        "plan_repetition": plan_repetition,
        "plan_reactivate": plan_reactivate,
        "plan_keep_inactive": plan_keep_inactive,
        "plan_bday_year_changed": plan_bday_year_changed,
        "plan_bday_year_cleared": plan_bday_year_cleared,
        "snapshot": snapshot,
        "checks": checks,
    }


def run_one_time_edit_source_checks(mainbot_stub):
    from modules.handlers.add_flow import type_flow as type_flow_mod

    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    update = _DummyUpdate(user_id=456, message=_DummyMessage(text="17/05", message_id=911))
    context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "Passport renewal",
            "type": 5,
            "type_name": C.ALERT_TYPES.get(5),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"time": "10:00"},
            "active": True,
        },
    })

    async def _return_fn(_update, _context):
        return C.EDIT_DASHBOARD

    original_now = type_flow_mod.now_server_naive
    type_flow_mod.now_server_naive = lambda: datetime(2027, 5, 16, 11, 30, 0)
    try:
        state = asyncio.run(type_flow_mod.type_5_date(update, context, _return_fn))
    finally:
        type_flow_mod.now_server_naive = original_now

    assumed_events = [
        event for event in storage.events
        if event.get("event_type") == "one_time_year_assumed"
    ]
    payload = assumed_events[0].get("payload", {}) if assumed_events else {}
    checks = {
        "state_returns_edit_dashboard": state == C.EDIT_DASHBOARD,
        "assumed_event_logged_once": len(assumed_events) == 1,
        "assumed_event_source_edit_flow": payload.get("source") == "edit_flow",
        "date_normalized_with_assumed_year": (
            context.user_data.get("temp_alert", {}).get("schedule", {}).get("date") == "17/05/2027"
        ),
    }
    return {
        "state": state,
        "events": storage.events,
        "temp_alert": context.user_data.get("temp_alert"),
        "checks": checks,
    }


def run_start_edit_checks(flow_mod, mainbot_stub):
    alert = {
        "id": "abc12345",
        "title": "Weekly sync",
        "type": 3,
        "type_name": C.ALERT_TYPES.get(3),
        "tags": ["🚗 Car"],
        "pre_alerts": ["1d"],
        "additional_info": "Bring notes",
        "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
        "active": True,
    }
    storage = _FakeStorage(alerts_by_id={"abc12345": alert}, user_tags=["🚗 Car", "💼 Work"])
    mainbot_stub.storage = storage

    query_message = _DummyMessage(message_id=501)
    query = _DummyCallbackQuery("manage_fulledit_abc12345", query_message)
    update = _DummyUpdate(user_id=42, callback_query=query)
    context = _DummyContext(user_data={
        "temp_alert": {"title": "stale"},
        "pending_pre_alerts": ["1w"],
        "settings_return": "alert",
    })

    state = asyncio.run(flow_mod.start_edit(update, context))
    callbacks = []
    if query.edits:
        callbacks = [cb for row in _extract_callback_rows(query.edits[-1].get("reply_markup")) for cb in row]
    origin_events = [
        event for event in storage.events
        if event.get("event_type") == "edit_origin_detected"
    ]
    origin_payload = origin_events[0].get("payload", {}) if origin_events else {}

    checks = {
        "state_edit_dashboard": state == C.EDIT_DASHBOARD,
        "query_answered_once": len(query.answers) == 1,
        "edit_alert_id_set": context.user_data.get("edit_alert_id") == "abc12345",
        "original_snapshot_set": isinstance(context.user_data.get("edit_alert_original"), dict),
        "origin_context_set": isinstance(context.user_data.get("edit_origin_context"), dict),
        "temp_alert_set": isinstance(context.user_data.get("temp_alert"), dict),
        "snapshot_is_deepcopy": context.user_data.get("edit_alert_original") is not context.user_data.get("temp_alert"),
        "stale_pre_alerts_cleared": "pending_pre_alerts" not in context.user_data,
        "settings_return_edit": context.user_data.get("settings_return") == "edit",
        "dashboard_has_done": "ed_done" in callbacks,
        "origin_detected_logged_once": len(origin_events) == 1,
        "origin_detected_alert_id": origin_payload.get("alert_id") == "abc12345",
        "origin_detected_source_unknown": origin_payload.get("origin_source") == "unknown",
        "origin_detected_kind_due": origin_payload.get("kind") == "due",
        "origin_detected_has_message_ref": bool(origin_payload.get("has_message_id_ref")),
    }
    return {
        "state": state,
        "answers": query.answers,
        "context_keys": sorted(context.user_data.keys()),
        "dashboard_callbacks": callbacks,
        "events": storage.events,
        "checks": checks,
    }


def run_notification_origin_context_capture_checks(flow_mod, mainbot_stub):
    from modules.ui.keyboards.callbacks import build_notif_back_callback

    alert = {
        "id": "origctx01",
        "title": "Origin context",
        "type": 3,
        "type_name": C.ALERT_TYPES.get(3),
        "tags": ["🚗 Car"],
        "pre_alerts": ["1h"],
        "additional_info": "",
        "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
        "active": True,
    }
    storage = _FakeStorage(alerts_by_id={"origctx01": alert}, user_tags=["🚗 Car"])
    mainbot_stub.storage = storage

    orig = datetime(2026, 4, 3, 10, 0, 0)
    occ = datetime(2026, 4, 3, 9, 0, 0)
    nback_cb = build_notif_back_callback("pre", "origctx01", orig, occ, postpone_count=2)

    notif_message = _DummyMessage(message_id=540, photo=[object()])
    notif_message.reply_markup = _build_reply_markup([
        [nback_cb],
        ["manage_fulledit_origctx01"],
    ])
    notif_query = _DummyCallbackQuery("manage_fulledit_origctx01", notif_message)
    notif_update = _DummyUpdate(user_id=84, callback_query=notif_query)
    notif_context = _DummyContext(user_data={})

    notif_state = asyncio.run(flow_mod.start_edit(notif_update, notif_context))
    notif_origin = notif_context.user_data.get("edit_origin_context") or {}
    notif_orig_dt = _parse_iso_datetime(notif_origin.get("original_time"))
    notif_occ_dt = _parse_iso_datetime(notif_origin.get("occurrence_time"))

    list_alert = copy.deepcopy(alert)
    list_alert["id"] = "origctx_list"
    storage._alerts_by_id["origctx_list"] = list_alert
    list_message = _DummyMessage(message_id=541)
    list_message.reply_markup = _build_reply_markup([
        ["manage_backtolist"],
        ["manage_fulledit_origctx_list"],
    ])
    list_query = _DummyCallbackQuery("manage_fulledit_origctx_list", list_message)
    list_update = _DummyUpdate(user_id=84, callback_query=list_query)
    list_context = _DummyContext(user_data={})

    list_state = asyncio.run(flow_mod.start_edit(list_update, list_context))
    list_origin = list_context.user_data.get("edit_origin_context") or {}
    origin_events = [
        event for event in storage.events
        if event.get("event_type") == "edit_origin_detected"
    ]
    notif_origin_event = next(
        (
            event for event in origin_events
            if (event.get("payload") or {}).get("alert_id") == "origctx01"
        ),
        {},
    )
    list_origin_event = next(
        (
            event for event in origin_events
            if (event.get("payload") or {}).get("alert_id") == "origctx_list"
        ),
        {},
    )
    notif_origin_payload = notif_origin_event.get("payload", {}) if isinstance(notif_origin_event, dict) else {}
    list_origin_payload = list_origin_event.get("payload", {}) if isinstance(list_origin_event, dict) else {}

    checks = {
        "notif_state_edit_dashboard": notif_state == C.EDIT_DASHBOARD,
        "notif_source_notification": notif_origin.get("source") == "notification",
        "notif_kind_preserved": notif_origin.get("kind") == "pre",
        "notif_message_id_preserved": notif_origin.get("message_id") == 540,
        "notif_chat_id_preserved": notif_origin.get("chat_id") == 84,
        "notif_photo_flag_preserved": bool(notif_origin.get("is_photo")),
        "notif_postpone_count_preserved": notif_origin.get("postpone_count") == 2,
        "notif_original_time_preserved": bool(notif_orig_dt and int(notif_orig_dt.timestamp()) == int(orig.timestamp())),
        "notif_occurrence_time_preserved": bool(notif_occ_dt and int(notif_occ_dt.timestamp()) == int(occ.timestamp())),
        "list_state_edit_dashboard": list_state == C.EDIT_DASHBOARD,
        "list_source_detected": list_origin.get("source") == "list",
        "list_message_id_preserved": list_origin.get("message_id") == 541,
        "origin_detected_events_logged": len(origin_events) == 2,
        "notif_origin_detected_payload": (
            notif_origin_payload.get("origin_source") == "notification"
            and notif_origin_payload.get("kind") == "pre"
            and notif_origin_payload.get("postpone_count") == 2
        ),
        "list_origin_detected_payload": (
            list_origin_payload.get("origin_source") == "list"
            and list_origin_payload.get("kind") == "due"
        ),
    }
    return {
        "notif_state": notif_state,
        "notif_origin_context": notif_origin,
        "list_state": list_state,
        "list_origin_context": list_origin,
        "events": storage.events,
        "checks": checks,
    }


def run_start_edit_failure_cleanup_checks(flow_mod, mainbot_stub):
    from modules.handlers import shortcut_router as shortcut_router_mod
    from modules.handlers.list_alerts import LIST_CONTEXT_KEY

    alert = {
        "id": "fail1234",
        "title": "Dashboard fails",
        "type": 3,
        "type_name": C.ALERT_TYPES.get(3),
        "tags": [],
        "pre_alerts": [],
        "additional_info": "",
        "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
        "active": True,
    }
    storage = _FakeStorage(alerts_by_id={"fail1234": alert}, user_tags=[])
    mainbot_stub.storage = storage

    query_message = _DummyMessage(message_id=502)
    query = _DummyCallbackQuery("manage_fulledit_fail1234", query_message)
    update = _DummyUpdate(user_id=43, callback_query=query)
    context = _DummyContext(user_data={
        "temp_alert": {"title": "stale"},
        "settings_return": "alert",
        "add_flow_message_ids": [111],
    })

    async def _raise_dashboard(*_args, **_kwargs):
        raise RuntimeError("forced_dashboard_failure")

    original_show_edit_dashboard = flow_mod.show_edit_dashboard
    flow_mod.show_edit_dashboard = _raise_dashboard
    try:
        state = asyncio.run(flow_mod.start_edit(update, context))
    finally:
        flow_mod.show_edit_dashboard = original_show_edit_dashboard

    command_message = _DummyMessage(text="/01", message_id=503)
    command_update = _DummyUpdate(user_id=43, message=command_message)
    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "alerts",
        "alias_map": {"01": "fail1234"},
    }
    shortcut_calls = []

    async def _fake_send_alert_detail_by_id(update, context, alert_id, source_hint=None):
        shortcut_calls.append({
            "alert_id": alert_id,
            "source_hint": source_hint,
        })

    original_send_alert_detail_by_id = shortcut_router_mod.send_alert_detail_by_id
    shortcut_router_mod.send_alert_detail_by_id = _fake_send_alert_detail_by_id
    try:
        asyncio.run(shortcut_router_mod.handle_dynamic_shortcut_command(command_update, context))
    finally:
        shortcut_router_mod.send_alert_detail_by_id = original_send_alert_detail_by_id

    fail_text = "❌ Could not open edit dashboard. Please retry from the alert card."
    checks = {
        "state_conversation_end": state == ConversationHandler.END,
        "query_answered_once": len(query.answers) == 1,
        "temp_alert_cleared": "temp_alert" not in context.user_data,
        "edit_alert_id_cleared": "edit_alert_id" not in context.user_data,
        "edit_alert_original_cleared": "edit_alert_original" not in context.user_data,
        "edit_origin_context_cleared": "edit_origin_context" not in context.user_data,
        "add_flow_message_ids_cleared": "add_flow_message_ids" not in context.user_data,
        "failure_text_rendered": (
            any(edit.get("text") == fail_text for edit in query.edits)
            or any(sent.get("text") == fail_text for sent in context.bot.sent_messages)
        ),
        "shortcut_unblocked_after_cleanup": len(shortcut_calls) == 1,
        "shortcut_target_id_routed": (
            len(shortcut_calls) == 1
            and shortcut_calls[0].get("alert_id") == "fail1234"
        ),
        "shortcut_collision_warning_not_sent": not any(
            "Finish or /cancel" in str((payload or {}).get("text", ""))
            for payload in command_message.replies
        ),
    }
    return {
        "state": state,
        "answers": query.answers,
        "context_keys": sorted(context.user_data.keys()),
        "query_edits": query.edits,
        "bot_messages": context.bot.sent_messages,
        "shortcut_calls": shortcut_calls,
        "shortcut_replies": command_message.replies,
        "checks": checks,
    }


def run_ed_tags_preselected_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=["🚗 Car", "💼 Work"])
    mainbot_stub.storage = storage

    query = _DummyCallbackQuery("ed_tags", _DummyMessage(message_id=601))
    update = _DummyUpdate(user_id=55, callback_query=query)
    context = _DummyContext(user_data={
        "temp_alert": {
            "title": "Test",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": ["🚗 Car"],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"weekdays": ["Tue"], "interval": 1, "time": "10:00"},
            "active": True,
        },
    })

    state = asyncio.run(flow_mod.handle_edit_choice(update, context))
    labels = _extract_button_labels(query.edits[-1].get("reply_markup")) if query.edits else []

    checks = {
        "state_get_tags": state == C.GET_TAGS,
        "query_answered_once": len(query.answers) == 1,
        "temp_selection_preselected": context.user_data.get("temp_selection") == ["🚗 Car"],
        "selected_label_marked": any(label.strip() == "🚗 Car ✅" for label in labels),
    }
    return {
        "state": state,
        "answers": query.answers,
        "labels": labels,
        "temp_selection": context.user_data.get("temp_selection"),
        "checks": checks,
    }


def run_ed_repetition_route_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    query = _DummyCallbackQuery("ed_repetition", _DummyMessage(message_id=611))
    update = _DummyUpdate(user_id=56, callback_query=query)
    context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "Test",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": [],
            "pre_alerts": [],
            "repetition": {"mode": C.REPETITION_MODE_FOREVER},
            "additional_info": "",
            "schedule": {"weekdays": ["Tue"], "interval": 1, "time": "10:00"},
            "active": True,
        },
    })

    state = asyncio.run(flow_mod.handle_edit_choice(update, context))
    callbacks = []
    if query.edits:
        callbacks = [cb for row in _extract_callback_rows(query.edits[-1].get("reply_markup")) for cb in row]

    checks = {
        "state_get_repetition_menu": state == C.GET_REPETITION_MENU,
        "query_answered_once": len(query.answers) == 1,
        "has_rep_forever": "rep_forever" in callbacks,
        "has_rep_until": "rep_until" in callbacks,
        "has_rep_count": "rep_count" in callbacks,
        "has_rep_back": "rep_back" in callbacks,
    }

    unsupported_query = _DummyCallbackQuery("ed_repetition", _DummyMessage(message_id=612))
    unsupported_update = _DummyUpdate(user_id=56, callback_query=unsupported_query)
    unsupported_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "One-time Test",
            "type": 5,
            "type_name": C.ALERT_TYPES.get(5),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "31/12/2099", "time": "10:00"},
            "active": True,
        },
    })
    unsupported_state = asyncio.run(flow_mod.handle_edit_choice(unsupported_update, unsupported_context))
    unsupported_checks = {
        "unsupported_fallback_edit_dashboard": unsupported_state == C.EDIT_DASHBOARD,
        "unsupported_answered_once": len(unsupported_query.answers) == 1,
    }
    checks.update(unsupported_checks)
    return {
        "state": state,
        "unsupported_state": unsupported_state,
        "answers": query.answers,
        "unsupported_answers": unsupported_query.answers,
        "callbacks": callbacks,
        "checks": checks,
    }


def run_ed_schedule_route_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    one_time_query = _DummyCallbackQuery("ed_schedule", _DummyMessage(message_id=616))
    one_time_update = _DummyUpdate(user_id=156, callback_query=one_time_query)
    one_time_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "Passport renewal",
            "type": 5,
            "type_name": C.ALERT_TYPES.get(5),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "31/12/2099", "time": "09:00"},
            "active": True,
        },
    })
    one_time_state = asyncio.run(flow_mod.handle_edit_choice(one_time_update, one_time_context))
    one_time_prompt = one_time_query.edits[-1].get("text", "") if one_time_query.edits else ""

    weekly_query = _DummyCallbackQuery("ed_schedule", _DummyMessage(message_id=617))
    weekly_update = _DummyUpdate(user_id=157, callback_query=weekly_query)
    weekly_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "Weekly sync",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"weekdays": ["Tue"], "interval": 1, "time": "10:00"},
            "active": True,
        },
    })
    weekly_state = asyncio.run(flow_mod.handle_edit_choice(weekly_update, weekly_context))
    weekly_prompt = weekly_query.edits[-1].get("text", "") if weekly_query.edits else ""

    checks = {
        "one_time_state_type_5_date": one_time_state == C.TYPE_5_DATE,
        "one_time_answered_once": len(one_time_query.answers) == 1,
        "one_time_prompt_mentions_date_format": "DD/MM" in one_time_prompt,
        "weekly_state_type_3_weekdays": weekly_state == C.TYPE_3_WEEKDAYS,
        "weekly_answered_once": len(weekly_query.answers) == 1,
        "weekly_prompt_mentions_weekly": "Weekly" in weekly_prompt,
    }
    return {
        "one_time_state": one_time_state,
        "weekly_state": weekly_state,
        "one_time_prompt": one_time_prompt,
        "weekly_prompt": weekly_prompt,
        "checks": checks,
    }


def run_ed_name_prompt_context_checks(flow_mod, mainbot_stub):
    from modules.shared.markdown_utils import md_escape

    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    raw_title = "Pay _rent* [A]"
    query = _DummyCallbackQuery("ed_name", _DummyMessage(message_id=618))
    update = _DummyUpdate(user_id=158, callback_query=query)
    context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": raw_title,
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
            "active": True,
        },
    })

    state = asyncio.run(flow_mod.handle_edit_choice(update, context))
    prompt_text = query.edits[-1].get("text", "") if query.edits else ""
    escaped_title = md_escape(raw_title)
    checks = {
        "state_edit_name": state == C.EDIT_NAME,
        "answered_once": len(query.answers) == 1,
        "prompt_mentions_rename": "Rename alert" in prompt_text,
        "prompt_contains_escaped_title": escaped_title in prompt_text,
        "prompt_excludes_raw_markdown_title": raw_title not in prompt_text,
    }
    return {
        "state": state,
        "prompt_text": prompt_text,
        "escaped_title": escaped_title,
        "checks": checks,
    }


def run_photo_card_media_edit_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=["🚗 Car"])
    mainbot_stub.storage = storage

    photo_temp_alert = {
        "title": "Car insurance",
        "type": 3,
        "type_name": C.ALERT_TYPES.get(3),
        "tags": ["🚗 Car"],
        "pre_alerts": ["1d"],
        "additional_info": "",
        "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
        "active": True,
    }

    dashboard_query = _DummyCallbackQuery(
        "manage_fulledit_photo01",
        _DummyMessage(message_id=640, photo=[object()]),
    )
    dashboard_update = _DummyUpdate(user_id=59, callback_query=dashboard_query)
    dashboard_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": copy.deepcopy(photo_temp_alert),
    })
    dashboard_state = asyncio.run(flow_mod.show_edit_dashboard(dashboard_update, dashboard_context))

    name_query = _DummyCallbackQuery(
        "ed_name",
        _DummyMessage(message_id=641, photo=[object()]),
    )
    name_update = _DummyUpdate(user_id=59, callback_query=name_query)
    name_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": copy.deepcopy(photo_temp_alert),
    })
    name_state = asyncio.run(flow_mod.handle_edit_choice(name_update, name_context))

    birthday_query = _DummyCallbackQuery(
        "ed_bday_date",
        _DummyMessage(message_id=642, photo=[object()]),
    )
    birthday_update = _DummyUpdate(user_id=59, callback_query=birthday_query)
    birthday_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01", "time": "08:00"},
            "active": True,
        },
    })
    birthday_state = asyncio.run(flow_mod.prompt_birthday_date_edit(birthday_update, birthday_context))

    terminal_query = _DummyCallbackQuery(
        "ed_done",
        _DummyMessage(message_id=643, photo=[object()]),
    )
    terminal_update = _DummyUpdate(user_id=59, callback_query=terminal_query)
    terminal_context = _DummyContext(user_data={})
    asyncio.run(flow_mod._render_edit_terminal(terminal_update, terminal_context, "✅ Alert updated!"))

    dashboard_caption = dashboard_query.caption_edits[-1] if dashboard_query.caption_edits else {}
    name_caption = name_query.caption_edits[-1] if name_query.caption_edits else {}
    birthday_caption = birthday_query.caption_edits[-1] if birthday_query.caption_edits else {}
    terminal_caption = terminal_query.caption_edits[-1] if terminal_query.caption_edits else {}

    checks = {
        "dashboard_state_edit_dashboard": dashboard_state == C.EDIT_DASHBOARD,
        "dashboard_used_caption_edit": bool(dashboard_query.caption_edits),
        "dashboard_no_text_edit": not bool(dashboard_query.edits),
        "dashboard_caption_markdown": dashboard_caption.get("parse_mode") == "Markdown",
        "name_state_edit_name": name_state == C.EDIT_NAME,
        "name_used_caption_edit": bool(name_query.caption_edits),
        "name_prompt_mentions_rename": "Rename alert" in (name_caption.get("caption") or ""),
        "birthday_state_type_6_date": birthday_state == C.TYPE_6_DATE,
        "birthday_used_caption_edit": bool(birthday_query.caption_edits),
        "birthday_prompt_mentions_dd_mm": "DD/MM" in (birthday_caption.get("caption") or ""),
        "terminal_used_caption_edit": bool(terminal_query.caption_edits),
        "terminal_prompt_is_success_text": (terminal_caption.get("caption") or "") == "✅ Alert updated!",
    }
    return {
        "dashboard_state": dashboard_state,
        "name_state": name_state,
        "birthday_state": birthday_state,
        "dashboard_caption_edit": dashboard_caption,
        "name_caption_edit": name_caption,
        "birthday_caption_edit": birthday_caption,
        "terminal_caption_edit": terminal_caption,
        "checks": checks,
    }


def run_photo_origin_start_edit_checks(flow_mod, mainbot_stub):
    alert = {
        "id": "photo1234",
        "title": "Photo-origin start",
        "type": 3,
        "type_name": C.ALERT_TYPES.get(3),
        "tags": ["🚗 Car"],
        "pre_alerts": ["1d"],
        "additional_info": "",
        "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
        "active": True,
    }
    storage = _FakeStorage(alerts_by_id={"photo1234": alert}, user_tags=["🚗 Car"])
    mainbot_stub.storage = storage

    query_message = _DummyMessage(message_id=644, photo=[object()])
    query = _DummyCallbackQuery("manage_fulledit_photo1234", query_message)
    update = _DummyUpdate(user_id=60, callback_query=query)
    context = _DummyContext(user_data={})

    state = asyncio.run(flow_mod.start_edit(update, context))
    caption_edit = query.caption_edits[-1] if query.caption_edits else {}
    callbacks = []
    if caption_edit:
        callbacks = [cb for row in _extract_callback_rows(caption_edit.get("reply_markup")) for cb in row]

    checks = {
        "state_edit_dashboard": state == C.EDIT_DASHBOARD,
        "answered_once": len(query.answers) == 1,
        "used_caption_edit": bool(query.caption_edits),
        "did_not_use_text_edit": not bool(query.edits),
        "caption_contains_dashboard_text": bool(str(caption_edit.get("caption") or "").strip()),
        "dashboard_has_done": "ed_done" in callbacks,
        "temp_alert_staged": isinstance(context.user_data.get("temp_alert"), dict),
        "edit_alert_id_staged": context.user_data.get("edit_alert_id") == "photo1234",
    }
    return {
        "state": state,
        "answers": query.answers,
        "caption_edit": caption_edit,
        "dashboard_callbacks": callbacks,
        "context_keys": sorted(context.user_data.keys()),
        "checks": checks,
    }


def run_photo_origin_edit_choice_checks(flow_mod, mainbot_stub):
    direct = run_photo_card_media_edit_checks(flow_mod, mainbot_stub)
    delegated = run_delegated_photo_route_checks(flow_mod, mainbot_stub)

    checks = {
        "direct_checks_all_passed": all(bool(v) for v in (direct.get("checks") or {}).values()),
        "delegated_checks_all_passed": all(bool(v) for v in (delegated.get("checks") or {}).values()),
        "direct_used_caption_edits": bool(
            (direct.get("dashboard_caption_edit") or {})
            and (direct.get("name_caption_edit") or {})
            and (direct.get("birthday_caption_edit") or {})
        ),
        "delegated_used_caption_edits": bool(
            (delegated.get("change_type_case") or {}).get("caption")
            and (delegated.get("photo_case") or {}).get("caption")
            and (delegated.get("repetition_case") or {}).get("caption")
        ),
    }
    return {
        "direct": direct,
        "delegated": delegated,
        "checks": checks,
    }


def run_delegated_photo_route_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=["🚗 Car", "💼 Work"])
    mainbot_stub.storage = storage

    def _base_alert(alert_type=3):
        payload = {
            "title": "Delegated route test",
            "type": alert_type,
            "type_name": C.ALERT_TYPES.get(alert_type),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
            "active": True,
        }
        if alert_type == 7:
            payload["schedule"] = {"interval": 2, "time": "09:00"}
        if alert_type == 5:
            payload["schedule"] = {"date": "31/12/2099", "time": "09:00"}
        payload["repetition"] = {"mode": C.REPETITION_MODE_FOREVER}
        return payload

    def _run_choice(data, temp_alert, message_id):
        query = _DummyCallbackQuery(data, _DummyMessage(message_id=message_id, photo=[object()]))
        update = _DummyUpdate(user_id=71, callback_query=query)
        context = _DummyContext(user_data={
            "settings_return": "edit",
            "temp_alert": copy.deepcopy(temp_alert),
        })
        state = asyncio.run(flow_mod.handle_edit_choice(update, context))
        caption = query.caption_edits[-1].get("caption", "") if query.caption_edits else ""
        return {
            "state": state,
            "query": query,
            "caption": caption,
            "context": context,
        }

    change_type_case = _run_choice("ed_change_type", _base_alert(3), 650)
    info_case = _run_choice("ed_info", _base_alert(3), 651)
    time_case = _run_choice("ed_time", _base_alert(3), 652)
    interval_case = _run_choice("ed_interval", _base_alert(3), 653)
    pre_case = _run_choice("ed_pre", _base_alert(3), 654)
    photo_case = _run_choice("ed_photo", _base_alert(3), 655)
    repetition_case = _run_choice("ed_repetition", _base_alert(3), 656)
    schedule_case = _run_choice("ed_schedule", _base_alert(3), 657)
    tags_case = _run_choice("ed_tags", _base_alert(3), 658)

    pre_custom_query = _DummyCallbackQuery("pre_custom", _DummyMessage(message_id=659, photo=[object()]))
    pre_custom_update = _DummyUpdate(user_id=71, callback_query=pre_custom_query)
    pre_custom_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": copy.deepcopy(_base_alert(3)),
    })
    pre_custom_state = asyncio.run(flow_mod.get_pre_alert_callback_edit(pre_custom_update, pre_custom_context))
    pre_custom_caption = pre_custom_query.caption_edits[-1].get("caption", "") if pre_custom_query.caption_edits else ""

    rep_until_query = _DummyCallbackQuery("rep_until", _DummyMessage(message_id=660, photo=[object()]))
    rep_until_update = _DummyUpdate(user_id=71, callback_query=rep_until_query)
    rep_until_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": copy.deepcopy(_base_alert(3)),
    })
    rep_until_state = asyncio.run(flow_mod.handle_repetition_choice_edit(rep_until_update, rep_until_context))
    rep_until_caption = rep_until_query.caption_edits[-1].get("caption", "") if rep_until_query.caption_edits else ""

    daily_confirm_query = _DummyCallbackQuery("int_1", _DummyMessage(message_id=661, photo=[object()]))
    daily_confirm_update = _DummyUpdate(user_id=71, callback_query=daily_confirm_query)
    daily_confirm_context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": copy.deepcopy(_base_alert(7)),
    })
    daily_confirm_state = asyncio.run(flow_mod.get_interval_callback_edit(daily_confirm_update, daily_confirm_context))
    daily_confirm_caption = daily_confirm_query.caption_edits[-1].get("caption", "") if daily_confirm_query.caption_edits else ""

    checks = {
        "change_type_state": change_type_case["state"] == C.CHANGE_ALERT_TYPE,
        "change_type_uses_caption": bool(change_type_case["query"].caption_edits),
        "change_type_answer_once": len(change_type_case["query"].answers) == 1,
        "change_type_prompt_text": "Change alert type" in change_type_case["caption"],
        "info_state": info_case["state"] == C.GET_ADDITIONAL_INFO,
        "info_uses_caption": bool(info_case["query"].caption_edits),
        "info_answer_once": len(info_case["query"].answers) == 1,
        "time_state": time_case["state"] == C.GET_TIME,
        "time_uses_caption": bool(time_case["query"].caption_edits),
        "time_answer_once": len(time_case["query"].answers) == 1,
        "interval_state": interval_case["state"] == C.GET_INTERVAL,
        "interval_uses_caption": bool(interval_case["query"].caption_edits),
        "interval_answer_once": len(interval_case["query"].answers) == 1,
        "pre_state": pre_case["state"] == C.GET_PRE_ALERT,
        "pre_uses_caption": bool(pre_case["query"].caption_edits),
        "pre_answer_once": len(pre_case["query"].answers) == 1,
        "pre_custom_state": pre_custom_state == C.GET_CUSTOM_PRE_ALERT,
        "pre_custom_uses_caption": bool(pre_custom_query.caption_edits),
        "pre_custom_answer_once": len(pre_custom_query.answers) == 1,
        "pre_custom_prompt_text": "Custom Pre-Alert" in pre_custom_caption,
        "photo_state": photo_case["state"] == C.GET_PHOTO,
        "photo_uses_caption": bool(photo_case["query"].caption_edits),
        "photo_answer_once": len(photo_case["query"].answers) == 1,
        "repetition_state": repetition_case["state"] == C.GET_REPETITION_MENU,
        "repetition_uses_caption": bool(repetition_case["query"].caption_edits),
        "repetition_answer_once": len(repetition_case["query"].answers) == 1,
        "rep_until_state": rep_until_state == C.GET_REPETITION_UNTIL_DATE,
        "rep_until_uses_caption": bool(rep_until_query.caption_edits),
        "rep_until_answer_once": len(rep_until_query.answers) == 1,
        "rep_until_prompt_text": "Until Date" in rep_until_caption,
        "schedule_state": schedule_case["state"] == C.TYPE_3_WEEKDAYS,
        "schedule_uses_caption": bool(schedule_case["query"].caption_edits),
        "schedule_answer_once": len(schedule_case["query"].answers) == 1,
        "schedule_prompt_text": "Weekly" in schedule_case["caption"],
        "tags_state": tags_case["state"] == C.GET_TAGS,
        "tags_uses_caption": bool(tags_case["query"].caption_edits),
        "tags_answer_once": len(tags_case["query"].answers) == 1,
        "daily_confirm_state": daily_confirm_state == C.DAILY_INTERVAL_CONFIRM,
        "daily_confirm_uses_caption": bool(daily_confirm_query.caption_edits),
        "daily_confirm_answer_once": len(daily_confirm_query.answers) == 1,
        "daily_confirm_prompt_text": "Daily interval confirmation" in daily_confirm_caption,
    }
    return {
        "change_type_case": {
            "state": change_type_case["state"],
            "caption": change_type_case["caption"],
            "answers": change_type_case["query"].answers,
        },
        "info_case": {
            "state": info_case["state"],
            "caption": info_case["caption"],
            "answers": info_case["query"].answers,
        },
        "time_case": {
            "state": time_case["state"],
            "caption": time_case["caption"],
            "answers": time_case["query"].answers,
        },
        "interval_case": {
            "state": interval_case["state"],
            "caption": interval_case["caption"],
            "answers": interval_case["query"].answers,
        },
        "pre_case": {
            "state": pre_case["state"],
            "caption": pre_case["caption"],
            "answers": pre_case["query"].answers,
        },
        "pre_custom_case": {
            "state": pre_custom_state,
            "caption": pre_custom_caption,
            "answers": pre_custom_query.answers,
        },
        "photo_case": {
            "state": photo_case["state"],
            "caption": photo_case["caption"],
            "answers": photo_case["query"].answers,
        },
        "repetition_case": {
            "state": repetition_case["state"],
            "caption": repetition_case["caption"],
            "answers": repetition_case["query"].answers,
        },
        "rep_until_case": {
            "state": rep_until_state,
            "caption": rep_until_caption,
            "answers": rep_until_query.answers,
        },
        "schedule_case": {
            "state": schedule_case["state"],
            "caption": schedule_case["caption"],
            "answers": schedule_case["query"].answers,
        },
        "tags_case": {
            "state": tags_case["state"],
            "caption": tags_case["caption"],
            "answers": tags_case["query"].answers,
        },
        "daily_confirm_case": {
            "state": daily_confirm_state,
            "caption": daily_confirm_caption,
            "answers": daily_confirm_query.answers,
        },
        "checks": checks,
    }


def run_ed_birthday_date_route_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    query = _DummyCallbackQuery("ed_bday_date", _DummyMessage(message_id=621))
    update = _DummyUpdate(user_id=57, callback_query=query)
    context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01", "time": "08:00"},
            "active": True,
        },
    })

    state = asyncio.run(flow_mod.handle_edit_choice(update, context))
    last_edit = query.edits[-1] if query.edits else {}
    text = last_edit.get("text") or ""
    prompted_events = [
        event for event in storage.events
        if event.get("event_type") == "birthday_date_edit_prompted"
    ]
    prompted_payload = prompted_events[0].get("payload", {}) if prompted_events else {}
    checks = {
        "state_type_6_date": state == C.TYPE_6_DATE,
        "query_answered_once": len(query.answers) == 1,
        "prompt_rendered": bool(query.edits),
        "prompt_mentions_today_line": "Today is `" in text,
        "prompt_mentions_dd_mm": "DD/MM" in text,
        "prompt_mentions_dd_mm_yyyy": "DD/MM/YYYY" in text,
        "prompt_event_logged_once": len(prompted_events) == 1,
        "prompt_event_source_edit_flow": prompted_payload.get("source") == "edit_flow",
    }
    return {
        "state": state,
        "answers": query.answers,
        "prompt_text": text,
        "events": storage.events,
        "checks": checks,
    }


def run_edit_additional_info_clear_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    handler = getattr(flow_mod, "edit_alert_handler", None)
    states = getattr(handler, "states", {}) or {}
    additional_info_handlers = states.get(C.GET_ADDITIONAL_INFO, [])
    additional_info_patterns = set()
    for state_handler in additional_info_handlers:
        pattern = getattr(state_handler, "pattern", None)
        if isinstance(pattern, str):
            additional_info_patterns.add(pattern)
        else:
            pattern_text = getattr(pattern, "pattern", None)
            if isinstance(pattern_text, str):
                additional_info_patterns.add(pattern_text)

    original_origin = {
        "source": "notification",
        "alert_id": "edclear01",
        "message_id": 711,
        "chat_id": 60,
        "kind": "due",
    }
    query = _DummyCallbackQuery("info_clear", _DummyMessage(message_id=711))
    update = _DummyUpdate(user_id=60, callback_query=query)
    context = _DummyContext(user_data={
        "settings_return": "edit",
        "edit_origin_context": copy.deepcopy(original_origin),
        "temp_alert": {
            "id": "edclear01",
            "title": "Edit clear check",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "should be cleared",
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
            "active": True,
        },
    })

    state = asyncio.run(flow_mod.handle_additional_info_clear_edit(update, context))
    persisted_origin = context.user_data.get("edit_origin_context")

    checks = {
        "state_returns_edit_dashboard": state == C.EDIT_DASHBOARD,
        "has_info_skip_callback": "^info_skip$" in additional_info_patterns,
        "has_info_clear_callback": "^info_clear$" in additional_info_patterns,
        "query_answered_once": len(query.answers) == 1,
        "additional_info_cleared": (
            context.user_data.get("temp_alert", {}).get("additional_info") == ""
        ),
        "edit_origin_context_preserved": persisted_origin == original_origin,
    }
    return {
        "state": state,
        "answers": query.answers,
        "patterns": sorted(additional_info_patterns),
        "temp_alert": context.user_data.get("temp_alert"),
        "edit_origin_context": persisted_origin,
        "checks": checks,
    }


def run_ed_birthday_date_input_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    def _run_case(message_text, temp_alert):
        update = _DummyUpdate(user_id=58, message=_DummyMessage(text=message_text, message_id=631))
        context = _DummyContext(user_data={
            "settings_return": "edit",
            "temp_alert": copy.deepcopy(temp_alert),
        })
        state = asyncio.run(flow_mod.type_6_date_edit(update, context))
        return {
            "state": state,
            "temp_alert": context.user_data.get("temp_alert"),
            "replies": list(update.message.replies),
        }

    case_no_year = _run_case(
        "25/12",
        {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01", "time": "09:15"},
            "birth_year": 1990,
            "active": True,
        },
    )
    case_with_year = _run_case(
        "25/12/1995",
        {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01", "time": "09:15"},
            "active": True,
        },
    )
    case_missing_time = _run_case(
        "11/11",
        {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01"},
            "active": True,
        },
    )
    case_invalid_format = _run_case(
        "invalid",
        {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01", "time": "09:15"},
            "birth_year": 1990,
            "active": True,
        },
    )
    case_future_year = _run_case(
        f"01/01/{datetime.now().year + 1}",
        {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01", "time": "09:15"},
            "birth_year": 1990,
            "active": True,
        },
    )
    case_two_digit_year = _run_case(
        "01/01/90",
        {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01", "time": "09:15"},
            "birth_year": 1990,
            "active": True,
        },
    )

    invalid_events = [
        event for event in storage.events
        if event.get("event_type") == "birthday_date_edit_invalid"
    ]
    set_events = [
        event for event in storage.events
        if event.get("event_type") == "birthday_date_edit_set"
    ]
    invalid_reason_codes = sorted({(event.get("payload") or {}).get("reason_code") for event in invalid_events})

    checks = {
        "no_year_state_dashboard": case_no_year["state"] == C.EDIT_DASHBOARD,
        "no_year_clears_birth_year": case_no_year["temp_alert"].get("birth_year") is None,
        "no_year_updates_date": case_no_year["temp_alert"].get("schedule", {}).get("date") == "25/12",
        "no_year_keeps_existing_time": case_no_year["temp_alert"].get("schedule", {}).get("time") == "09:15",
        "with_year_state_dashboard": case_with_year["state"] == C.EDIT_DASHBOARD,
        "with_year_sets_birth_year": case_with_year["temp_alert"].get("birth_year") == 1995,
        "with_year_updates_date": case_with_year["temp_alert"].get("schedule", {}).get("date") == "25/12",
        "missing_time_gets_default": bool(case_missing_time["temp_alert"].get("schedule", {}).get("time")),
        "invalid_format_stays_input_state": case_invalid_format["state"] == C.TYPE_6_DATE,
        "future_year_stays_input_state": case_future_year["state"] == C.TYPE_6_DATE,
        "two_digit_year_stays_input_state": case_two_digit_year["state"] == C.TYPE_6_DATE,
        "invalid_event_has_input_meta": all(
            isinstance((event.get("payload") or {}).get("date_input_meta"), dict)
            for event in invalid_events
        ),
        "invalid_events_metadata_only": all(
            "raw_text" not in (event.get("payload") or {})
            and "date_input" not in (event.get("payload") or {})
            for event in invalid_events
        ),
        "set_event_logged_for_successes": len(set_events) >= 3,
        "set_event_metadata_only": all(
            "date_input_meta" not in (event.get("payload") or {})
            for event in set_events
        ),
        "invalid_reason_codes_present": {
            "invalid_format",
            "year_in_future",
            "year_two_digits",
        }.issubset(set(invalid_reason_codes)),
    }
    return {
        "cases": {
            "no_year": case_no_year,
            "with_year": case_with_year,
            "missing_time": case_missing_time,
            "invalid_format": case_invalid_format,
            "future_year": case_future_year,
            "two_digit_year": case_two_digit_year,
        },
        "invalid_reason_codes": invalid_reason_codes,
        "events": storage.events,
        "checks": checks,
    }


def run_daily_prompt_callback_context_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    query = _DummyCallbackQuery("ct_7", _DummyMessage(message_id=701))
    update = _DummyUpdate(user_id=88, callback_query=query)
    context = _DummyContext(user_data={
        "temp_alert": {
            "title": "Water plants",
            "type": 7,
            "type_name": C.ALERT_TYPES.get(7),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {},
            "active": True,
        },
    })

    state = asyncio.run(flow_mod.prompt_type_specific_edit(update, context))
    last_edit = query.edits[-1] if query.edits else {}
    text = last_edit.get("text") or ""
    rows = _extract_callback_rows(last_edit.get("reply_markup"))
    checks = {
        "state_mode_choice": state == C.FUZZY_INTERVAL_MODE_CHOICE,
        "edit_rendered": bool(query.edits),
        "daily_text_present": "Daily interval mode" in text,
        "fixed_mode_button_present": any("intmode_fixed" in row for row in rows),
        "fuzzy_mode_button_present": any("intmode_fuzzy" in row for row in rows),
    }
    return {
        "state": state,
        "text": text,
        "rows": rows,
        "edit_count": len(query.edits),
        "checks": checks,
    }


def run_daily_interval_prompt_source_checks():
    from modules.handlers.add_flow import type_flow

    context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "type": 7,
            "type_name": C.ALERT_TYPES.get(7),
        },
    })
    update = _DummyUpdate(user_id=88)

    value = type_flow._daily_interval_prompt_source(update, context)
    checks = {
        "returns_string": isinstance(value, str),
        "non_empty_value": bool(str(value).strip()),
    }
    return {
        "value": value,
        "checks": checks,
    }


def run_birthday_prealert_edit_context_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=["👨‍👩‍👧 Family"])
    mainbot_stub.storage = storage

    context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "Alice",
            "type": 6,
            "type_name": C.ALERT_TYPES.get(6),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "01/01", "time": "08:00"},
            "active": True,
        },
    })

    show_query = _DummyCallbackQuery("ed_pre", _DummyMessage(message_id=801))
    show_update = _DummyUpdate(user_id=99, callback_query=show_query)
    state_show = asyncio.run(flow_mod.show_pre_alert_menu(show_update, context))
    show_callbacks = []
    if show_query.edits:
        show_callbacks = [cb for row in _extract_callback_rows(show_query.edits[-1].get("reply_markup")) for cb in row]

    pick_query = _DummyCallbackQuery("pre_bdayeve", _DummyMessage(message_id=802))
    pick_update = _DummyUpdate(user_id=99, callback_query=pick_query)
    state_pick = asyncio.run(flow_mod.get_pre_alert_callback_edit(pick_update, context))

    checks = {
        "show_state_pre_alert": state_show == C.GET_PRE_ALERT,
        "menu_has_bdayeve": "pre_bdayeve" in show_callbacks,
        "pick_returns_dashboard": state_pick == C.EDIT_DASHBOARD,
        "token_saved": C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN in (context.user_data.get("temp_alert", {}).get("pre_alerts") or []),
    }
    return {
        "show_state": state_show,
        "pick_state": state_pick,
        "show_callbacks": show_callbacks,
        "pick_answers": pick_query.answers,
        "saved_pre_alerts": list(context.user_data.get("temp_alert", {}).get("pre_alerts") or []),
        "checks": checks,
    }


def run_pre_alert_custom_edit_parity_checks(flow_mod, mainbot_stub):
    from modules.handlers.add_flow import type_flow as type_flow_mod

    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    context = _DummyContext(user_data={
        "settings_return": "edit",
        "temp_alert": {
            "title": "Doctor",
            "type": 5,
            "type_name": C.ALERT_TYPES.get(5),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"date": "10/03/2026", "time": "10:00"},
            "active": True,
        },
    })

    original_now = type_flow_mod.now_server_naive
    pending_before_confirm = []
    type_flow_mod.now_server_naive = lambda: datetime(2026, 3, 10, 8, 0, 0)
    try:
        input_update = _DummyUpdate(
            user_id=77,
            message=_DummyMessage(text="1h, today at 09:30", message_id=888),
        )
        input_state = asyncio.run(flow_mod.get_custom_pre_alert_input_edit(input_update, context))
        input_reply = input_update.message.replies[-1] if input_update.message.replies else {}
        pending_before_confirm = list(context.user_data.get("pending_pre_alerts") or [])

        confirm_query = _DummyCallbackQuery("precustom_yes", _DummyMessage(message_id=889))
        confirm_update = _DummyUpdate(user_id=77, callback_query=confirm_query)
        confirm_state = asyncio.run(flow_mod.confirm_custom_pre_alert_edit(confirm_update, context))
    finally:
        type_flow_mod.now_server_naive = original_now

    checks = {
        "input_state_confirm_custom": input_state == C.CONFIRM_CUSTOM_PRE_ALERT,
        "pending_tokens_canonical": pending_before_confirm == ["1h", "30m"],
        "pending_cleared_after_confirm": context.user_data.get("pending_pre_alerts") == [],
        "confirm_returns_dashboard": confirm_state == C.EDIT_DASHBOARD,
        "saved_tokens_canonical": context.user_data.get("temp_alert", {}).get("pre_alerts") == ["1h", "30m"],
        "input_reply_contains_confirm": "Confirm?" in (input_reply.get("text") or ""),
    }
    return {
        "input_state": input_state,
        "confirm_state": confirm_state,
        "input_reply": input_reply,
        "pending_before_confirm": pending_before_confirm,
        "saved_pre_alerts": list(context.user_data.get("temp_alert", {}).get("pre_alerts") or []),
        "checks": checks,
    }


def run_edit_origin_context_persistence_checks(flow_mod, mainbot_stub):
    storage = _FakeStorage(alerts_by_id={}, user_tags=[])
    mainbot_stub.storage = storage

    original_origin_context = {
        "source": "notification",
        "alert_id": "persist01",
        "chat_id": 55,
        "message_id": 805,
        "is_photo": False,
        "kind": "due",
        "original_time": "2026-04-03T10:00:00",
        "occurrence_time": "2026-04-03T10:00:00",
        "postpone_count": 1,
    }

    update = _DummyUpdate(
        user_id=55,
        message=_DummyMessage(text="Updated from input", message_id=806),
    )
    context = _DummyContext(user_data={
        "settings_return": "edit",
        "edit_origin_context": copy.deepcopy(original_origin_context),
        "temp_alert": {
            "title": "Persist check",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
            "active": True,
        },
    })

    state = asyncio.run(flow_mod.handle_additional_info_input_edit(update, context))
    persisted = context.user_data.get("edit_origin_context")
    checks = {
        "state_returns_dashboard": state == C.EDIT_DASHBOARD,
        "additional_info_updated": context.user_data.get("temp_alert", {}).get("additional_info") == "Updated from input",
        "origin_context_still_present": isinstance(persisted, dict),
        "origin_context_unchanged": persisted == original_origin_context,
        "dashboard_rendered_via_message_reply": len(update.message.replies) >= 1,
    }
    return {
        "state": state,
        "persisted_origin_context": persisted,
        "message_replies": update.message.replies,
        "bot_sent_messages": context.bot.sent_messages,
        "checks": checks,
    }


def run_commit_notification_origin_completion_checks(flow_mod, mainbot_stub):
    from modules.handlers import scheduler_handlers as scheduler_mod

    class _CommitStorage(_FakeStorage):
        def __init__(self, alerts_by_id=None):
            super().__init__(alerts_by_id=alerts_by_id or {}, user_tags=[])
            self.update_calls = []
            self.schedule_state_calls = []
            self.clear_snooze_calls = []
            self.expire_postpone_calls = []

        def update_alert_fields(self, user_id, alert_id, updates):
            self.update_calls.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
                "updates": copy.deepcopy(updates),
            })
            current = self._alerts_by_id.get(alert_id)
            if not isinstance(current, dict):
                return False
            current.update(copy.deepcopy(updates))
            return True

        def update_alert_schedule_state(self, user_id, alert_id, next_scheduled=None):
            self.schedule_state_calls.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
                "next_scheduled": next_scheduled,
            })
            return True

        def clear_alert_snooze(self, user_id, alert_id):
            self.clear_snooze_calls.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
            })
            return True

        def expire_pending_postpones_for_alert(self, user_id, alert_id):
            self.expire_postpone_calls.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
            })
            return 0

    def _build_alert(alert_id):
        return {
            "id": alert_id,
            "title": "Commit test",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": ["💼 Work"],
            "pre_alerts": ["1h"],
            "repetition": {"mode": C.REPETITION_MODE_FOREVER, "until_date": None, "count_remaining": None},
            "additional_info": "",
            "image_id": None,
            "local_image_path": None,
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
            "active": True,
            "next_scheduled": "2026-04-04T09:00:00",
        }

    restore_calls = []
    restore_behaviors = {}
    cleared_pre_alert_tracking = []

    async def _fake_restore(_context, **kwargs):
        restore_calls.append(dict(kwargs))
        _context.bot.operations.append({"op": "restore", "payload": dict(kwargs)})
        alert_id = str(kwargs.get("alert_id") or "")
        behavior = restore_behaviors.get(
            alert_id,
            {"success": True, "reason_code": "ok"},
        )
        if isinstance(behavior, dict):
            return dict(behavior)
        return {"success": True, "reason_code": "ok"}

    def _fake_clear(alert_id):
        cleared_pre_alert_tracking.append(str(alert_id))
        return 0

    original_restore = scheduler_mod._restore_notification_message_view
    original_clear = flow_mod.clear_pre_alert_tracking_for_alert
    scheduler_mod._restore_notification_message_view = _fake_restore
    flow_mod.clear_pre_alert_tracking_for_alert = _fake_clear

    try:
        # Case A: notification-origin, changed fields -> success + restore + artifact cleanup.
        storage_changed = _CommitStorage(alerts_by_id={"commit_notif_changed": _build_alert("commit_notif_changed")})
        mainbot_stub.storage = storage_changed
        original_changed = flow_mod._prepare_edit_snapshot(storage_changed.get_alert_by_id("501", "commit_notif_changed"))
        temp_changed = copy.deepcopy(original_changed)
        temp_changed["title"] = "Commit changed"
        update_changed = _DummyUpdate(
            user_id=501,
            callback_query=_DummyCallbackQuery("ed_done", _DummyMessage(message_id=901)),
        )
        context_changed = _DummyContext(user_data={
            "edit_alert_id": "commit_notif_changed",
            "edit_alert_original": copy.deepcopy(original_changed),
            "temp_alert": copy.deepcopy(temp_changed),
            "add_flow_message_ids": [1101, 1102, 901],
            "add_flow_start_message_id": None,
            "edit_origin_context": {
                "source": "notification",
                "alert_id": "commit_notif_changed",
                "chat_id": 501,
                "message_id": 901,
                "is_photo": False,
                "kind": "due",
                "original_time": "2026-04-03T09:00:00",
                "occurrence_time": "2026-04-03T09:00:00",
                "postpone_count": 3,
            },
        })
        state_changed = asyncio.run(flow_mod.commit_edit(update_changed, context_changed))
        changed_restore_call = restore_calls[-1] if restore_calls else {}
        changed_operations = [item.get("op") for item in context_changed.bot.operations]
        changed_delete_ids = [payload.get("message_id") for payload in context_changed.bot.delete_calls]
        changed_terminal_id = (
            context_changed.bot.sent_messages[0].get("message_id")
            if context_changed.bot.sent_messages and isinstance(context_changed.bot.sent_messages[0], dict)
            else None
        )
        changed_events = [e for e in storage_changed.events if e.get("event_type") == "alert_edited"]
        changed_attempt_events = [
            e for e in storage_changed.events
            if e.get("event_type") == "edit_notification_restore_attempted"
        ]
        changed_result_events = [
            e for e in storage_changed.events
            if e.get("event_type") == "edit_notification_restore_result"
        ]

        # Case B: notification-origin, no changes -> info terminal + restore + artifact cleanup.
        storage_no_change = _CommitStorage(alerts_by_id={"commit_notif_nochange": _build_alert("commit_notif_nochange")})
        mainbot_stub.storage = storage_no_change
        original_no_change = flow_mod._prepare_edit_snapshot(storage_no_change.get_alert_by_id("502", "commit_notif_nochange"))
        temp_no_change = copy.deepcopy(original_no_change)
        update_no_change = _DummyUpdate(
            user_id=502,
            callback_query=_DummyCallbackQuery("ed_done", _DummyMessage(message_id=902)),
        )
        context_no_change = _DummyContext(user_data={
            "edit_alert_id": "commit_notif_nochange",
            "edit_alert_original": copy.deepcopy(original_no_change),
            "temp_alert": copy.deepcopy(temp_no_change),
            "add_flow_message_ids": [1201, 1202, 902],
            "edit_origin_context": {
                "source": "notification",
                "alert_id": "commit_notif_nochange",
                "chat_id": 502,
                "message_id": 902,
                "is_photo": False,
                "kind": "pre",
                "original_time": "2026-04-03T09:00:00",
                "occurrence_time": "2026-04-03T08:00:00",
                "postpone_count": 1,
            },
        })
        previous_restore_count = len(restore_calls)
        state_no_change = asyncio.run(flow_mod.commit_edit(update_no_change, context_no_change))
        no_change_restore_call = restore_calls[-1] if len(restore_calls) > previous_restore_count else {}
        no_change_operations = [item.get("op") for item in context_no_change.bot.operations]
        no_change_delete_ids = [payload.get("message_id") for payload in context_no_change.bot.delete_calls]
        no_change_events = [e for e in storage_no_change.events if e.get("event_type") == "alert_edited"]
        no_change_attempt_events = [
            e for e in storage_no_change.events
            if e.get("event_type") == "edit_notification_restore_attempted"
        ]
        no_change_result_events = [
            e for e in storage_no_change.events
            if e.get("event_type") == "edit_notification_restore_result"
        ]

        # Case C: list-origin, changed fields -> restore detail card + cleanup.
        storage_list = _CommitStorage(alerts_by_id={"commit_list": _build_alert("commit_list")})
        mainbot_stub.storage = storage_list
        original_list = flow_mod._prepare_edit_snapshot(storage_list.get_alert_by_id("503", "commit_list"))
        temp_list = copy.deepcopy(original_list)
        temp_list["title"] = "List changed"
        list_bot = _DummyBot()
        list_bot.fail_delete_ids.add(1302)
        query_list = _DummyCallbackQuery("ed_done", _DummyMessage(message_id=903, photo=[object()]))
        update_list = _DummyUpdate(user_id=503, callback_query=query_list)
        context_list = _DummyContext(user_data={
            "edit_alert_id": "commit_list",
            "edit_alert_original": copy.deepcopy(original_list),
            "temp_alert": copy.deepcopy(temp_list),
            "manage_source": "alerts",
            "current_filter": "💼 Work",
            "add_flow_message_ids": [1301, 1302, 903],
            "edit_origin_context": {
                "source": "list",
                "alert_id": "commit_list",
                "chat_id": 503,
                "message_id": 903,
                "is_photo": True,
                "kind": "due",
                "original_time": None,
                "occurrence_time": None,
                "postpone_count": 0,
                "source_hint": "alerts",
                "include_back": True,
                "tag_filter": "💼 Work",
            },
        }, bot=list_bot)
        restore_before_list = len(restore_calls)
        state_list = asyncio.run(flow_mod.commit_edit(update_list, context_list))
        restore_after_list = len(restore_calls)
        list_operations = [item.get("op") for item in context_list.bot.operations]
        list_delete_ids = [payload.get("message_id") for payload in context_list.bot.delete_calls]
        list_events = [e for e in storage_list.events if e.get("event_type") == "alert_edited"]
        list_notif_attempt_events = [
            e for e in storage_list.events
            if e.get("event_type") == "edit_notification_restore_attempted"
        ]
        list_notif_result_events = [
            e for e in storage_list.events
            if e.get("event_type") == "edit_notification_restore_result"
        ]
        list_attempt_events = [
            e for e in storage_list.events
            if e.get("event_type") == "edit_list_restore_attempted"
        ]
        list_result_events = [
            e for e in storage_list.events
            if e.get("event_type") == "edit_list_restore_result"
        ]

        # Case D: notification-origin restore returns failure metadata -> fail-soft warning + reason code.
        restore_behaviors["commit_notif_restore_fail"] = {
            "success": False,
            "reason_code": "restore_failed",
        }
        storage_restore_fail = _CommitStorage(alerts_by_id={"commit_notif_restore_fail": _build_alert("commit_notif_restore_fail")})
        mainbot_stub.storage = storage_restore_fail
        original_restore_fail = flow_mod._prepare_edit_snapshot(
            storage_restore_fail.get_alert_by_id("504", "commit_notif_restore_fail")
        )
        temp_restore_fail = copy.deepcopy(original_restore_fail)
        temp_restore_fail["title"] = "Restore fail changed"
        update_restore_fail = _DummyUpdate(
            user_id=504,
            callback_query=_DummyCallbackQuery("ed_done", _DummyMessage(message_id=904)),
        )
        context_restore_fail = _DummyContext(user_data={
            "edit_alert_id": "commit_notif_restore_fail",
            "edit_alert_original": copy.deepcopy(original_restore_fail),
            "temp_alert": copy.deepcopy(temp_restore_fail),
            "add_flow_message_ids": [1401, 904],
            "edit_origin_context": {
                "source": "notification",
                "alert_id": "commit_notif_restore_fail",
                "chat_id": 504,
                "message_id": 904,
                "is_photo": False,
                "kind": "due",
                "original_time": "2026-04-03T09:00:00",
                "occurrence_time": "2026-04-03T09:00:00",
                "postpone_count": 4,
            },
        })
        state_restore_fail = asyncio.run(flow_mod.commit_edit(update_restore_fail, context_restore_fail))
        restore_fail_operations = [item.get("op") for item in context_restore_fail.bot.operations]
        restore_fail_texts = [payload.get("text", "") for payload in context_restore_fail.bot.sent_messages]
        restore_fail_attempt_events = [
            e for e in storage_restore_fail.events
            if e.get("event_type") == "edit_notification_restore_attempted"
        ]
        restore_fail_result_events = [
            e for e in storage_restore_fail.events
            if e.get("event_type") == "edit_notification_restore_result"
        ]

        # Case E: notification-origin restore returns no-op success metadata.
        restore_behaviors["commit_notif_noop"] = {
            "success": True,
            "reason_code": "message_not_modified",
        }
        storage_noop = _CommitStorage(alerts_by_id={"commit_notif_noop": _build_alert("commit_notif_noop")})
        mainbot_stub.storage = storage_noop
        original_noop = flow_mod._prepare_edit_snapshot(storage_noop.get_alert_by_id("505", "commit_notif_noop"))
        temp_noop = copy.deepcopy(original_noop)
        temp_noop["title"] = "Noop changed"
        update_noop = _DummyUpdate(
            user_id=505,
            callback_query=_DummyCallbackQuery("ed_done", _DummyMessage(message_id=905)),
        )
        context_noop = _DummyContext(user_data={
            "edit_alert_id": "commit_notif_noop",
            "edit_alert_original": copy.deepcopy(original_noop),
            "temp_alert": copy.deepcopy(temp_noop),
            "add_flow_message_ids": [1501, 905],
            "edit_origin_context": {
                "source": "notification",
                "alert_id": "commit_notif_noop",
                "chat_id": 505,
                "message_id": 905,
                "is_photo": False,
                "kind": "pre",
                "original_time": "2026-04-03T09:00:00",
                "occurrence_time": "2026-04-03T08:00:00",
                "postpone_count": 0,
            },
        })
        state_noop = asyncio.run(flow_mod.commit_edit(update_noop, context_noop))
        noop_operations = [item.get("op") for item in context_noop.bot.operations]
        noop_attempt_events = [
            e for e in storage_noop.events
            if e.get("event_type") == "edit_notification_restore_attempted"
        ]
        noop_result_events = [
            e for e in storage_noop.events
            if e.get("event_type") == "edit_notification_restore_result"
        ]

        # Case F: list-origin restore fail-soft path with media-aware attempts.
        storage_list_fail = _CommitStorage(alerts_by_id={"commit_list_fail": _build_alert("commit_list_fail")})
        mainbot_stub.storage = storage_list_fail
        original_list_fail = flow_mod._prepare_edit_snapshot(storage_list_fail.get_alert_by_id("506", "commit_list_fail"))
        temp_list_fail = copy.deepcopy(original_list_fail)
        temp_list_fail["title"] = "List restore fail"
        list_fail_bot = _DummyBot()
        list_fail_bot.fail_edit_caption_ids.add(906)
        list_fail_bot.fail_edit_text_ids.add(906)
        query_list_fail = _DummyCallbackQuery("ed_done", _DummyMessage(message_id=906, photo=[object()]))
        update_list_fail = _DummyUpdate(user_id=506, callback_query=query_list_fail)
        context_list_fail = _DummyContext(user_data={
            "edit_alert_id": "commit_list_fail",
            "edit_alert_original": copy.deepcopy(original_list_fail),
            "temp_alert": copy.deepcopy(temp_list_fail),
            "manage_source": "alerts",
            "current_filter": "💼 Work",
            "add_flow_message_ids": [1601, 1602, 906],
            "edit_origin_context": {
                "source": "list",
                "alert_id": "commit_list_fail",
                "chat_id": 506,
                "message_id": 906,
                "is_photo": True,
                "kind": "due",
                "original_time": None,
                "occurrence_time": None,
                "postpone_count": 0,
                "source_hint": "alerts",
                "include_back": True,
                "tag_filter": "💼 Work",
            },
        }, bot=list_fail_bot)
        state_list_fail = asyncio.run(flow_mod.commit_edit(update_list_fail, context_list_fail))
        list_fail_operations = [item.get("op") for item in context_list_fail.bot.operations]
        list_fail_texts = [payload.get("text", "") for payload in context_list_fail.bot.sent_messages]
        list_fail_result_events = [
            e for e in storage_list_fail.events
            if e.get("event_type") == "edit_list_restore_result"
        ]

        # Case G: repeated ed_done should not produce duplicate success messages.
        storage_repeat = _CommitStorage(alerts_by_id={"commit_repeat": _build_alert("commit_repeat")})
        mainbot_stub.storage = storage_repeat
        original_repeat = flow_mod._prepare_edit_snapshot(storage_repeat.get_alert_by_id("507", "commit_repeat"))
        temp_repeat = copy.deepcopy(original_repeat)
        temp_repeat["title"] = "Repeat changed"
        repeat_query = _DummyCallbackQuery("ed_done", _DummyMessage(message_id=907))
        repeat_update = _DummyUpdate(user_id=507, callback_query=repeat_query)
        context_repeat = _DummyContext(user_data={
            "edit_alert_id": "commit_repeat",
            "edit_alert_original": copy.deepcopy(original_repeat),
            "temp_alert": copy.deepcopy(temp_repeat),
            "add_flow_message_ids": [1701, 907],
            "edit_origin_context": {
                "source": "notification",
                "alert_id": "commit_repeat",
                "chat_id": 507,
                "message_id": 907,
                "is_photo": False,
                "kind": "due",
                "original_time": "2026-04-03T09:00:00",
                "occurrence_time": "2026-04-03T09:00:00",
                "postpone_count": 0,
            },
        })
        first_repeat_state = asyncio.run(flow_mod.commit_edit(repeat_update, context_repeat))
        repeat_before_second = len(context_repeat.bot.sent_messages)
        second_repeat_state = asyncio.run(flow_mod.commit_edit(repeat_update, context_repeat))
        repeat_after_second = len(context_repeat.bot.sent_messages)
        repeat_success_count = sum(
            1
            for payload in context_repeat.bot.sent_messages
            if payload.get("text") == "✅ Alert updated!"
        )

        checks = {
            "changed_state_end": state_changed == ConversationHandler.END,
            "changed_ack_sent": bool(context_changed.bot.sent_messages and context_changed.bot.sent_messages[0].get("text") == "✅ Alert updated!"),
            "changed_order_ack_then_restore": changed_operations[:2] == ["send_message", "restore"],
            "changed_restore_called_once": bool(changed_restore_call),
            "changed_restore_kind_due": changed_restore_call.get("kind") == "due",
            "changed_restore_postpone_preserved": changed_restore_call.get("postpone_count") == 3,
            "changed_query_terminal_not_used": (
                len(update_changed.callback_query.edits) == 0
                and len(update_changed.callback_query.caption_edits) == 0
            ),
            "changed_cleanup_deleted_artifacts": set(changed_delete_ids) == {1101, 1102},
            "changed_cleanup_kept_origin_message": 901 not in changed_delete_ids,
            "changed_cleanup_kept_terminal_message": changed_terminal_id not in changed_delete_ids,
            "changed_update_called": len(storage_changed.update_calls) == 1,
            "changed_event_logged": len(changed_events) == 1,
            "changed_context_cleared": "edit_origin_context" not in context_changed.user_data and "temp_alert" not in context_changed.user_data,
            "changed_restore_attempt_logged": len(changed_attempt_events) == 1,
            "changed_restore_result_ok": (
                len(changed_result_events) == 1
                and (changed_result_events[0].get("payload") or {}).get("success") is True
                and (changed_result_events[0].get("payload") or {}).get("reason_code") == "ok"
            ),
            "no_change_state_end": state_no_change == ConversationHandler.END,
            "no_change_info_sent": bool(context_no_change.bot.sent_messages and "No changes detected" in (context_no_change.bot.sent_messages[0].get("text") or "")),
            "no_change_order_ack_then_restore": no_change_operations[:2] == ["send_message", "restore"],
            "no_change_restore_called": bool(no_change_restore_call),
            "no_change_no_update_call": len(storage_no_change.update_calls) == 0,
            "no_change_no_alert_edited_event": len(no_change_events) == 0,
            "no_change_cleanup_deleted_artifacts": set(no_change_delete_ids) == {1201, 1202},
            "no_change_restore_attempt_logged": len(no_change_attempt_events) == 1,
            "no_change_restore_result_ok": (
                len(no_change_result_events) == 1
                and (no_change_result_events[0].get("payload") or {}).get("success") is True
                and (no_change_result_events[0].get("payload") or {}).get("reason_code") == "ok"
            ),
            "list_state_end": state_list == ConversationHandler.END,
            "list_notification_restore_not_used": restore_after_list == restore_before_list,
            "list_ack_sent_once": len(context_list.bot.sent_messages) == 1,
            "list_ack_success_text": bool(context_list.bot.sent_messages and context_list.bot.sent_messages[0].get("text") == "✅ Alert updated!"),
            "list_restore_used_caption_branch": "edit_message_caption" in list_operations,
            "list_cleanup_attempted_delete": set(list_delete_ids) == {1301, 1302},
            "list_cleanup_fail_soft_on_delete_error": state_list == ConversationHandler.END,
            "list_update_called": len(storage_list.update_calls) == 1,
            "list_event_logged": len(list_events) == 1,
            "list_context_cleared": "edit_origin_context" not in context_list.user_data and "temp_alert" not in context_list.user_data,
            "list_restore_telemetry_logged": (
                len(list_attempt_events) == 1
                and len(list_result_events) == 1
                and (list_result_events[0].get("payload") or {}).get("success") is True
            ),
            "list_notification_restore_telemetry_not_logged": (
                len(list_notif_attempt_events) == 0 and len(list_notif_result_events) == 0
            ),
            "restore_fail_state_end": state_restore_fail == ConversationHandler.END,
            "restore_fail_order_ack_then_restore": restore_fail_operations[:2] == ["send_message", "restore"],
            "restore_fail_warning_sent": (
                len(restore_fail_texts) >= 2
                and "couldn't restore" in str(restore_fail_texts[-1]).lower()
            ),
            "restore_fail_result_reason_code": (
                len(restore_fail_attempt_events) == 1
                and len(restore_fail_result_events) == 1
                and (restore_fail_result_events[0].get("payload") or {}).get("success") is False
                and (restore_fail_result_events[0].get("payload") or {}).get("reason_code") == "restore_failed"
            ),
            "noop_state_end": state_noop == ConversationHandler.END,
            "noop_order_ack_then_restore": noop_operations[:2] == ["send_message", "restore"],
            "noop_no_warning_sent": len(context_noop.bot.sent_messages) == 1,
            "noop_result_reason_code_message_not_modified": (
                len(noop_attempt_events) == 1
                and len(noop_result_events) == 1
                and (noop_result_events[0].get("payload") or {}).get("success") is True
                and (noop_result_events[0].get("payload") or {}).get("reason_code") == "message_not_modified"
            ),
            "list_fail_state_end": state_list_fail == ConversationHandler.END,
            "list_fail_attempted_caption_then_text": (
                list_fail_operations.count("edit_message_caption") >= 1
                and list_fail_operations.count("edit_message_text") >= 1
            ),
            "list_fail_warning_sent": any("couldn't restore" in str(text).lower() for text in list_fail_texts),
            "list_fail_reason_coded": (
                len(list_fail_result_events) == 1
                and (list_fail_result_events[0].get("payload") or {}).get("success") is False
                and (list_fail_result_events[0].get("payload") or {}).get("reason_code") in {
                    "message_not_found",
                    "restore_exception",
                }
            ),
            "repeat_first_state_end": first_repeat_state == ConversationHandler.END,
            "repeat_second_state_end": second_repeat_state == ConversationHandler.END,
            "repeat_no_duplicate_success_message": (
                repeat_after_second == repeat_before_second
                and repeat_success_count == 1
            ),
            "schedule_unchanged_prealert_tracking_not_cleared": len(cleared_pre_alert_tracking) == 0,
        }
        return {
            "restore_calls": restore_calls,
            "cleared_pre_alert_tracking": cleared_pre_alert_tracking,
            "changed_case": {
                "state": state_changed,
                "operations": changed_operations,
                "sent_messages": context_changed.bot.sent_messages,
                "update_calls": storage_changed.update_calls,
                "events": changed_events,
            },
            "no_change_case": {
                "state": state_no_change,
                "operations": no_change_operations,
                "sent_messages": context_no_change.bot.sent_messages,
                "update_calls": storage_no_change.update_calls,
                "events": no_change_events,
            },
            "list_case": {
                "state": state_list,
                "operations": list_operations,
                "delete_calls": context_list.bot.delete_calls,
                "sent_messages": context_list.bot.sent_messages,
                "update_calls": storage_list.update_calls,
                "events": list_events,
            },
            "restore_fail_case": {
                "state": state_restore_fail,
                "operations": restore_fail_operations,
                "sent_messages": context_restore_fail.bot.sent_messages,
                "events": storage_restore_fail.events,
            },
            "noop_case": {
                "state": state_noop,
                "operations": noop_operations,
                "sent_messages": context_noop.bot.sent_messages,
                "events": storage_noop.events,
            },
            "list_restore_fail_case": {
                "state": state_list_fail,
                "operations": list_fail_operations,
                "sent_messages": context_list_fail.bot.sent_messages,
                "events": storage_list_fail.events,
            },
            "repeat_case": {
                "first_state": first_repeat_state,
                "second_state": second_repeat_state,
                "sent_messages": context_repeat.bot.sent_messages,
            },
            "checks": checks,
        }
    finally:
        scheduler_mod._restore_notification_message_view = original_restore
        flow_mod.clear_pre_alert_tracking_for_alert = original_clear


def run_pre_alert_tracking_clear_checks():
    from modules.scheduler_core import state as scheduler_state

    original_entries = copy.deepcopy(scheduler_state.sent_pre_alerts)
    original_dirty = bool(scheduler_state.sent_pre_alerts_dirty)
    try:
        scheduler_state.sent_pre_alerts.clear()
        scheduler_state.sent_pre_alerts.update({
            ("1", "A1", "1d"): datetime.now(),
            ("2", "A1", "1w"): datetime.now(),
            ("1", "B2", "1d"): datetime.now(),
        })
        scheduler_state.sent_pre_alerts_dirty = False

        removed = scheduler_state.clear_pre_alert_tracking_for_alert("A1")
        remaining_keys = sorted(scheduler_state.sent_pre_alerts.keys())

        checks = {
            "removed_two_entries": removed == 2,
            "remaining_only_other_alert": remaining_keys == [("1", "B2", "1d")],
            "dirty_marked": bool(scheduler_state.sent_pre_alerts_dirty),
        }
        return {
            "removed": removed,
            "remaining_keys": remaining_keys,
            "dirty": scheduler_state.sent_pre_alerts_dirty,
            "checks": checks,
        }
    finally:
        scheduler_state.sent_pre_alerts.clear()
        scheduler_state.sent_pre_alerts.update(original_entries)
        scheduler_state.sent_pre_alerts_dirty = original_dirty


def run_cancel_cleanup_checks(flow_mod, mainbot_stub):
    original_end_conv = getattr(flow_mod, "end_registered_conversations", None)
    end_conv_calls = []

    def _mock_end_conv(_update):
        end_conv_calls.append(True)

    flow_mod.end_registered_conversations = _mock_end_conv
    try:
        query_msg = _DummyMessage(message_id=800)
        query = _DummyCallbackQuery("cancel_edit", query_msg)
        update = _DummyUpdate(user_id=99, callback_query=query)
        context = _DummyContext(user_data={
            "additional_info_copy_msg_id": 800,
            "temp_alert": {"title": "Test"},
            "settings_return": "edit",
        })

        state = asyncio.run(flow_mod.cancel_edit(update, context))
        delete_calls = list(context.bot.delete_calls)

        checks = {
            "copy_key_removed": "additional_info_copy_msg_id" not in context.user_data,
            "delete_attempted_once": len(delete_calls) == 1,
            "delete_correct_message_id": (delete_calls[0]["message_id"] == 800) if delete_calls else False,
            "terminal_state_returned": state == ConversationHandler.END,
        }
    finally:
        if original_end_conv is not None:
            flow_mod.end_registered_conversations = original_end_conv

    return {
        "delete_calls": delete_calls,
        "state": state,
        "context_keys": sorted(context.user_data.keys()),
        "checks": checks,
    }


def run_change_type_same_type_checks(settings_flow_mod):
    prompt_fn_calls = []
    return_fn_calls = []

    async def _prompt_fn(_update, _context):
        prompt_fn_calls.append(True)
        return C.CHANGE_ALERT_TYPE

    async def _return_fn(_update, _context):
        return_fn_calls.append(True)
        return C.EDIT_DASHBOARD

    stale_schedule = {"weekdays": ["Mon"], "interval": 1, "time": "09:00"}

    # Same-type branch: current_type == next_type == 3
    query_same = _DummyCallbackQuery("ct_3", _DummyMessage(message_id=750))
    update_same = _DummyUpdate(user_id=88, callback_query=query_same)
    context_same = _DummyContext(user_data={
        "temp_selection": ["Mon", "Tue"],
        "temp_alert": {
            "title": "Same type test",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": copy.deepcopy(stale_schedule),
            "active": True,
        },
    })
    asyncio.run(settings_flow_mod._change_type_callback_impl(
        update_same, context_same, _return_fn, _prompt_fn,
    ))
    same_temp_alert = context_same.user_data.get("temp_alert", {})

    # Different-type branch: current_type = 3, next_type = 1
    prompt_fn_calls.clear()
    return_fn_calls.clear()
    query_diff = _DummyCallbackQuery("ct_1", _DummyMessage(message_id=751))
    update_diff = _DummyUpdate(user_id=88, callback_query=query_diff)
    context_diff = _DummyContext(user_data={
        "temp_selection": ["Mon"],
        "temp_alert": {
            "title": "Diff type test",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "tags": [],
            "pre_alerts": [],
            "additional_info": "",
            "schedule": copy.deepcopy(stale_schedule),
            "active": True,
        },
    })
    asyncio.run(settings_flow_mod._change_type_callback_impl(
        update_diff, context_diff, _return_fn, _prompt_fn,
    ))
    diff_temp_alert = context_diff.user_data.get("temp_alert", {})
    diff_schedule = diff_temp_alert.get("schedule", {})

    checks = {
        "prompt_fn_called_once": len(prompt_fn_calls) == 1,
        "return_fn_not_called": len(return_fn_calls) == 0,
        "temp_selection_reset": context_same.user_data.get("temp_selection") == [],
        "type_unchanged": same_temp_alert.get("type") == 3,
        "schedule_preserved": same_temp_alert.get("schedule", {}).get("weekdays") == ["Mon"],
        "diff_prompt_fn_called_once": len(prompt_fn_calls) == 1,
        "schedule_cleared": "weekdays" not in diff_schedule,
        "type_updated": diff_temp_alert.get("type") == 1,
    }
    return {
        "same_type_temp_alert": same_temp_alert,
        "same_type_selection": context_same.user_data.get("temp_selection"),
        "diff_type_temp_alert": diff_temp_alert,
        "checks": checks,
    }


def run_postpone_expire_checks():
    with tempfile.TemporaryDirectory(prefix="edit_flow_debug_") as tmp_dir:
        storage = StorageManager(base_data_dir=tmp_dir, admin_id="1")
        user_id = "777001"
        storage.setup_user_space(user_id)

        def _seed(data):
            data["alerts"] = []
            data["postpone_queue"] = [
                {"id": "p1", "alert_id": "A1", "status": "pending"},
                {"id": "p2", "alert_id": "A1", "status": "sent"},
                {"id": "p3", "alert_id": "B2", "status": "pending"},
            ]
            return True, True

        storage._mutate_user_data(user_id, _seed, ensure_space=True)

        expired_count = storage.expire_pending_postpones_for_alert(user_id, "A1")
        queue = storage.get_postpone_queue(user_id)
        by_id = {item.get("id"): item for item in queue}

        checks = {
            "expired_only_pending_for_target": expired_count == 1,
            "target_pending_marked_expired": by_id.get("p1", {}).get("status") == "expired",
            "target_pending_reason_set": by_id.get("p1", {}).get("reason") == "alert_edited",
            "target_nonpending_untouched": by_id.get("p2", {}).get("status") == "sent",
            "other_alert_untouched": by_id.get("p3", {}).get("status") == "pending",
        }
        return {
            "expired_count": expired_count,
            "queue": queue,
            "checks": checks,
        }
