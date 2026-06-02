#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from telegram.error import BadRequest


def _find_debuggers_root(start_path):
    current = os.path.abspath(os.path.dirname(start_path))
    while True:
        if os.path.basename(current) == "debuggers" and os.path.isdir(os.path.join(current, "_lib")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.path.join(os.path.dirname(start_path), ".."))
        current = parent


DEBUGGERS_ROOT = _find_debuggers_root(__file__)
if DEBUGGERS_ROOT not in sys.path:
    sys.path.insert(0, DEBUGGERS_ROOT)

from _lib.harness import DebugHarness
from _lib.root import add_project_root_to_path
from _lib.runtime import run_async

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "ghost_alert_debug"
FEATURE_TITLE = "Ghost Alert Utilities"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _to_local_naive(date_str, time_str):
    return datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")


def _run_ghost_utils_unit_checks(
    dbg,
    StorageManager,
    create_ghost_alert,
    find_existing_ghost,
    get_pending_ghost_alerts,
    is_ghost_alert,
    resolve_user_timezone,
    to_server_naive_from_user,
):
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=1)
            user_id = 1
            storage.setup_user_space(user_id)

            source_alert = {
                "id": "src12345",
                "title": "Dentist",
                "type": 3,
                "type_name": "Weekly",
                "schedule": {"days": ["Mon"], "time": "10:00"},
                "pre_alerts": [],
                "tags": [],
            }
            source_id = storage.save_alert(user_id, source_alert)
            source_saved = storage.get_alert_by_id(user_id, source_id)

            fire_at = datetime(2026, 3, 2, 15, 30, 0)
            ghost_id = create_ghost_alert(
                storage,
                user_id,
                source_saved,
                fire_at,
                missed_date_str="02/03/2026 15:30",
            )
            ghost_alert = storage.get_alert_by_id(user_id, ghost_id)

            pending = get_pending_ghost_alerts(storage, user_id)
            existing = find_existing_ghost(storage, user_id, source_saved["id"])

            schedule_date = ((ghost_alert or {}).get("schedule") or {}).get("date", "")
            schedule_time = ((ghost_alert or {}).get("schedule") or {}).get("time", "")
            additional_info = (ghost_alert or {}).get("additional_info", "")

            checks = {
                "ghost_saved": bool(ghost_id and ghost_alert),
                "type_is_one_time": (ghost_alert or {}).get("type") == 5,
                "type_name_is_one_time": (ghost_alert or {}).get("type_name") == "One Time",
                "active_true": (ghost_alert or {}).get("active") is True,
                "ghost_source_id_set": (ghost_alert or {}).get("ghost_source_id") == source_saved["id"],
                "title_prefixed": ((ghost_alert or {}).get("title") or "").startswith("👻 "),
                "additional_info_has_provenance": "Ghost of:" in additional_info and "Expected:" in additional_info,
                "schedule_date_format": len(schedule_date.split("/")) == 3,
                "schedule_time_format": len(schedule_time) == 5 and ":" in schedule_time,
                "is_ghost_alert_true": is_ghost_alert(ghost_alert) is True,
                "pending_contains_ghost": any(a.get("id") == ghost_id for a in pending),
                "find_existing_returns_ghost": bool(existing) and existing.get("id") == ghost_id,
                "is_ghost_alert_false_non_ghost": is_ghost_alert(source_saved) is False,
            }

            storage.update_user_prefs(user_id, {
                "timezone_mode": "user",
                "timezone": {"name": "America/New_York"},
            })
            fire_at_user_mode = datetime(2026, 6, 15, 18, 45, 0)
            tz_ghost_id = create_ghost_alert(
                storage,
                user_id,
                source_saved,
                fire_at_user_mode,
                missed_date_str="15/06/2026 18:45",
            )
            tz_ghost = storage.get_alert_by_id(user_id, tz_ghost_id)
            tz_schedule = (tz_ghost or {}).get("schedule") or {}
            user_prefs = storage.get_user_prefs(user_id)
            user_tz = resolve_user_timezone(user_prefs)
            stored_local = _to_local_naive(tz_schedule.get("date", "01/01/1970"), tz_schedule.get("time", "00:00"))
            restored_server_dt, shifted = to_server_naive_from_user(stored_local, user_tz)
            checks["timezone_mode_preserves_server_instant"] = (
                shifted is False
                and restored_server_dt == fire_at_user_mode
            )

            dbg.section("ghost_utils_unit", {
                "checks": checks,
                "source_id": source_id,
                "ghost_id": ghost_id,
                "tz_ghost_id": tz_ghost_id,
                "stored_schedule": {"date": schedule_date, "time": schedule_time},
                "tz_stored_schedule": tz_schedule,
                "restored_server_dt": restored_server_dt.isoformat(),
            })
            if not all(checks.values()):
                dbg.problem("ghost_utils_unit_failed", {"checks": checks})
        finally:
            os.chdir(cwd)


def _mk_item(title, *, missed_due=None, missed_pre=None, upcoming_due=None, upcoming_pre=None):
    return {
        "alert": {"title": title, "tags": []},
        "missed_due": missed_due or [],
        "missed_pre": missed_pre or [],
        "upcoming_due": upcoming_due or [],
        "upcoming_pre": upcoming_pre or [],
    }


def _run_summary_text_checks(dbg, format_missed_alerts_summary):
    now = datetime(2026, 5, 1, 10, 0, 0)
    one_std = [_mk_item("Standard A", missed_due=[now])]
    one_ghost_missed = [{"alert": {"title": "👻 Ghost A", "ghost_source_id": "src"}}]
    one_ghost_pending = [{
        "title": "👻 Ghost P",
        "ghost_source_id": "src",
        "next_scheduled": now.isoformat(),
    }]

    text_none = format_missed_alerts_summary([], [], [])
    text_std = format_missed_alerts_summary(one_std, [], [])
    text_ghost_only = format_missed_alerts_summary([], one_ghost_missed, [])
    text_pending_only = format_missed_alerts_summary([], [], one_ghost_pending)
    text_full = format_missed_alerts_summary(one_std, one_ghost_missed, one_ghost_pending)

    many_std = [_mk_item(f"Std {i:02d}", missed_due=[now]) for i in range(21)]
    text_20 = format_missed_alerts_summary(many_std[:20], [], [])
    text_21 = format_missed_alerts_summary(many_std, [], [])

    many_ghost_missed = [{"alert": {"title": f"👻 M{i:02d}", "ghost_source_id": "src"}} for i in range(21)]
    many_ghost_pending = [{
        "title": f"👻 P{i:02d}",
        "ghost_source_id": "src",
        "next_scheduled": now.isoformat(),
    } for i in range(21)]
    text_ghost_caps = format_missed_alerts_summary(one_std, many_ghost_missed, many_ghost_pending)

    checks = {
        "empty_none": text_none is None,
        "standard_only": isinstance(text_std, str) and "MISSED ALERTS SUMMARY" in text_std and "Ghost reminders" not in text_std,
        "ghost_missed_only": isinstance(text_ghost_only, str) and "Ghost reminders" in text_ghost_only and "Missed ghost copies" in text_ghost_only,
        "pending_only_none": text_pending_only is None,
        "full_sections": isinstance(text_full, str) and "Ghost reminders" in text_full and "Pending ghost copies" in text_full,
        "cap_20_no_overflow": isinstance(text_20, str) and "_...and 1 more_" not in text_20,
        "cap_21_overflow": isinstance(text_21, str) and "_...and 1 more_" in text_21,
        "ghost_caps_overflow": isinstance(text_ghost_caps, str) and text_ghost_caps.count("_...and 1 more_") >= 2,
        "within_telegram_limit": isinstance(text_ghost_caps, str) and len(text_ghost_caps) <= 4096,
    }
    dbg.section("summary_text", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("summary_text_failed", {"checks": checks})


async def _run_summary_send_checks(
    dbg,
    send_missed_alerts_batch,
    handle_missed_alerts,
):
    class _DummyBot:
        def __init__(self):
            self.messages = []

        async def send_message(self, **kwargs):
            self.messages.append(kwargs)
            return {"ok": True, "id": len(self.messages)}

    now = datetime(2026, 5, 1, 10, 0, 0)
    bot = _DummyBot()
    standard_item = {
        "alert": {"id": "abcd1234", "title": "Standard title", "tags": []},
        "missed_due": [now],
        "missed_pre": [],
        "upcoming_due": [],
        "upcoming_pre": [],
    }
    msg = await send_missed_alerts_batch(bot, 1, [standard_item], storage=None)
    first = bot.messages[0] if bot.messages else {}
    first_markup = first.get("reply_markup")
    first_button = first_markup.inline_keyboard[0][0] if first_markup else None
    callback_data = first_button.callback_data if first_button else ""

    ghost_item = {
        "alert": {"id": "efgh5678", "title": "👻 Ghost missed", "ghost_source_id": "src"},
        "missed_due": [now],
        "missed_pre": [],
        "upcoming_due": [],
        "upcoming_pre": [],
    }
    bot_ghost = _DummyBot()
    msg_ghost = await send_missed_alerts_batch(bot_ghost, 1, [ghost_item], storage=None)
    ghost_first = bot_ghost.messages[0] if bot_ghost.messages else {}

    pending_only = [{"title": "👻 Pending", "ghost_source_id": "src", "next_scheduled": now.isoformat()}]

    class _StoragePendingOnly:
        def get_active_alerts(self, _user_id):
            return pending_only

    bot_pending = _DummyBot()
    msg_pending = await send_missed_alerts_batch(bot_pending, 1, [], storage=_StoragePendingOnly())

    many_items = []
    for i in range(25):
        many_items.append({
            "alert": {"id": f"id{i:06d}"[:8], "title": f"Std {i}", "tags": []},
            "missed_due": [now],
            "missed_pre": [],
            "upcoming_due": [],
            "upcoming_pre": [],
        })
    bot_many = _DummyBot()
    await send_missed_alerts_batch(bot_many, 1, many_items, storage=None)
    many_markup = bot_many.messages[0].get("reply_markup") if bot_many.messages else None
    button_count = len(many_markup.inline_keyboard) if many_markup else 0

    old_calls = []
    new_calls = []

    async def _old_send(_bot, _user_id, _missed_list):
        old_calls.append(True)
        return {"ok": True}

    async def _new_send(_bot, _user_id, _missed_list, *, storage=None):
        new_calls.append(storage)
        return {"ok": True}

    class _StorageCompat:
        def get_all_users(self):
            return [1]

        def get_all_alerts(self, _user_id):
            return {
                "alerts": [{
                    "id": "zxyw1234",
                    "title": "Compat Alert",
                    "type": 5,
                    "type_name": "One Time",
                    "schedule": {"date": "01/01/2020", "time": "10:00"},
                    "next_scheduled": "2020-01-01T10:00:00",
                    "active": True,
                    "pre_alerts": [],
                    "tags": [],
                }],
                "postpone_queue": [],
            }

        def get_user_prefs(self, _user_id):
            return {}

        def mark_alert_done(self, _user_id, _alert_id):
            return True, True

        def log_user_event(self, _user_id, _name, _payload):
            return None

        def cleanup_postpone_queue(self, _user_id, _now_iso):
            return None

        def update_postpone_instance(self, _user_id, _postpone_id, _updates):
            return False

    compat_storage = _StorageCompat()
    compat_bot = _DummyBot()
    await handle_missed_alerts(
        compat_bot,
        compat_storage,
        now=datetime(2026, 5, 1, 11, 0, 0),
        send_missed_func=_old_send,
    )
    await handle_missed_alerts(
        compat_bot,
        compat_storage,
        now=datetime(2026, 5, 1, 11, 5, 0),
        send_missed_func=_new_send,
    )

    checks = {
        "standard_sent": msg is not None and bool(first),
        "standard_callback_format": callback_data.startswith("missed_dtl_abcd1234_"),
        "standard_timestamp_matches": callback_data.endswith(str(int(now.timestamp()))),
        "ghost_only_sent": msg_ghost is not None and bool(ghost_first),
        "ghost_only_no_keyboard": ghost_first.get("reply_markup") is None,
        "pending_only_none": msg_pending is None and len(bot_pending.messages) == 0,
        "button_cap_20": button_count == 20,
        "old_signature_works": len(old_calls) > 0,
        "new_signature_receives_storage": len(new_calls) > 0 and all(s is compat_storage for s in new_calls),
    }
    dbg.section("summary_send", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("summary_send_failed", {"checks": checks})


async def _run_ghost_missed_filter_checks(dbg, handle_missed_alerts):
    """Verify ghost alerts are excluded from missed summary and cleaned at startup."""
    class _StorageGhostFilter:
        def __init__(self):
            self._ghost_id = "ghost1234"
            self.mark_done_calls = []
            self.postpone_updates = []
            self.events = []

        def get_all_users(self):
            return [1]

        def get_all_alerts(self, _user_id):
            return {
                "alerts": [{
                    "id": self._ghost_id,
                    "title": "👻 Ghost follow-up",
                    "type": 5,
                    "type_name": "One Time",
                    "next_scheduled": "2026-05-01T08:00:00",
                    "active": True,
                    "ghost_source_id": "src1234",
                    "schedule": {"date": "01/05/2026", "time": "08:00"},
                    "pre_alerts": [],
                    "tags": [],
                }],
                "postpone_queue": [{
                    "id": "pp_ghost_due",
                    "status": "pending",
                    "alert_id": self._ghost_id,
                    "kind": "due",
                    "fire_at": "2026-05-01T08:30:00",
                }],
            }

        def get_user_prefs(self, _user_id):
            return {}

        def mark_alert_done(self, _user_id, alert_id):
            self.mark_done_calls.append(alert_id)
            return True, True

        def log_user_event(self, _user_id, event, payload):
            self.events.append((event, dict(payload or {})))

        def update_postpone_instance(self, _user_id, postpone_id, updates):
            self.postpone_updates.append((postpone_id, dict(updates or {})))

        def cleanup_postpone_queue(self, _user_id, _now_iso):
            return None

    class _DummyBot:
        pass

    sent_missed_payloads = []

    async def _capture_send(_bot, _user_id, missed_list, *, storage=None):
        sent_missed_payloads.append({"missed_list": missed_list, "storage": storage})
        return None

    storage = _StorageGhostFilter()
    ghost_id = storage._ghost_id
    now = datetime(2026, 5, 1, 12, 0, 0)

    await handle_missed_alerts(
        _DummyBot(),
        storage,
        now=now,
        send_missed_func=_capture_send,
    )

    ghost_not_in_summary = True
    for item in sent_missed_payloads:
        for missed in item.get("missed_list") or []:
            alert_id = ((missed or {}).get("alert") or {}).get("id")
            if alert_id == ghost_id:
                ghost_not_in_summary = False
                break
        if not ghost_not_in_summary:
            break

    ghost_postpone_expired_on_startup = any(
        postpone_id == "pp_ghost_due"
        and updates.get("status") == "expired"
        and updates.get("reason") == "ghost_recovery_cleanup"
        for postpone_id, updates in storage.postpone_updates
    )

    checks = {
        "ghost_not_in_summary": ghost_not_in_summary,
        "ghost_marked_done": ghost_id in storage.mark_done_calls,
        "ghost_postpone_expired_on_startup": ghost_postpone_expired_on_startup,
    }
    dbg.section("ghost_missed_filter", {
        "checks": checks,
        "mark_done_calls": storage.mark_done_calls,
        "postpone_updates": storage.postpone_updates,
        "missed_payloads_len": len(sent_missed_payloads),
    })
    if not all(checks.values()):
        dbg.problem("ghost_missed_filter_failed", {"checks": checks})


async def _run_inactive_postpone_missed_checks(dbg, handle_missed_alerts):
    """Verify past-due postpones for inactive (not deleted, not ghost) alerts appear in the missed summary."""
    from datetime import timedelta

    now = datetime(2026, 5, 2, 10, 0, 0)
    fire_at_due = (now - timedelta(hours=1)).isoformat()
    fire_at_boundary = now.isoformat()
    fire_at_deleted = (now - timedelta(hours=1)).isoformat()

    class _StorageInactivePostpone:
        def __init__(self):
            self._inactive_id = "inact1234"
            self._deleted_id = "delet5678"
            self._pp_due_id = "pp_inact_due"
            self._pp_boundary_id = "pp_inact_bound"
            self._pp_deleted_id = "pp_deleted_due"
            self.postpone_updates = []
            self.events = []
            self.mark_done_calls = []

        def get_all_users(self):
            return [1]

        def get_all_alerts(self, _user_id):
            return {
                "alerts": [{
                    "id": self._inactive_id,
                    "title": "Weekly meeting",
                    "type": 3,
                    "type_name": "Weekly",
                    "active": False,
                    "pre_alerts": [],
                    "tags": [],
                }],
                "postpone_queue": [
                    {
                        "id": self._pp_due_id,
                        "status": "pending",
                        "alert_id": self._inactive_id,
                        "kind": "due",
                        "fire_at": fire_at_due,
                    },
                    {
                        "id": self._pp_boundary_id,
                        "status": "pending",
                        "alert_id": self._inactive_id,
                        "kind": "due",
                        "fire_at": fire_at_boundary,
                    },
                    {
                        "id": self._pp_deleted_id,
                        "status": "pending",
                        "alert_id": self._deleted_id,
                        "kind": "due",
                        "fire_at": fire_at_deleted,
                    },
                ],
            }

        def get_user_prefs(self, _user_id):
            return {}

        def update_postpone_instance(self, _user_id, postpone_id, updates):
            self.postpone_updates.append((postpone_id, dict(updates or {})))

        def log_user_event(self, _user_id, event, payload):
            self.events.append((event, dict(payload or {})))

        def mark_alert_done(self, _user_id, alert_id):
            self.mark_done_calls.append(alert_id)
            return True, True

        def cleanup_postpone_queue(self, _user_id, _now_iso):
            return None

    class _DummyBot:
        pass

    sent_missed_payloads = []

    async def _capture_send(_bot, _user_id, missed_list, *, storage=None):
        sent_missed_payloads.append({"missed_list": missed_list})
        return None

    storage = _StorageInactivePostpone()
    inactive_id = storage._inactive_id
    deleted_id = storage._deleted_id

    await handle_missed_alerts(
        _DummyBot(),
        storage,
        now=now,
        send_missed_func=_capture_send,
    )

    inactive_postpone_expired = any(
        pid == storage._pp_due_id and upd.get("status") == "expired"
        for pid, upd in storage.postpone_updates
    )
    boundary_expired = any(
        pid == storage._pp_boundary_id and upd.get("status") == "expired"
        for pid, upd in storage.postpone_updates
    )
    all_missed = [
        entry
        for payload in sent_missed_payloads
        for entry in (payload.get("missed_list") or [])
    ]
    inactive_entry = next(
        (e for e in all_missed if (e.get("alert") or {}).get("id") == inactive_id),
        None,
    )
    deleted_in_summary = any(
        (e.get("alert") or {}).get("id") == deleted_id for e in all_missed
    )

    checks = {
        "inactive_postpone_expired": inactive_postpone_expired,
        "inactive_boundary_expired": boundary_expired,
        "inactive_alert_in_summary": inactive_entry is not None,
        "inactive_alert_has_missed_due": bool(
            inactive_entry and inactive_entry.get("missed_due")
        ),
        "deleted_not_in_summary": not deleted_in_summary,
    }
    dbg.section("inactive_postpone_missed", {
        "checks": checks,
        "postpone_updates": storage.postpone_updates,
        "missed_payloads_len": len(sent_missed_payloads),
        "all_missed_ids": [(e.get("alert") or {}).get("id") for e in all_missed],
    })
    if not all(checks.values()):
        dbg.problem("inactive_postpone_missed_failed", {"checks": checks})


async def _run_ghost_picker_and_dedup_checks(
    dbg,
    handle_missed_dtl,
    handle_ghost_set,
    handle_ghost_set_custom,
    handle_ghost_custom_text,
    handle_ghost_dedup_confirm,
    handle_ghost_dedup_cancel,
    handle_ghost_noop,
    clear_transient_context,
):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    class _DummyMessage:
        def __init__(self, message_id, *, text=None, reply_markup=None):
            self.message_id = message_id
            self.text = text
            self.reply_markup = reply_markup
            self.replies = []

        async def reply_text(self, text, parse_mode=None, reply_markup=None):
            self.replies.append({
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            })
            return self

    class _DummyQuery:
        def __init__(self, data, message):
            self.data = data
            self.message = message
            self.answers = []
            self.edits = []

        async def answer(self, text=None, show_alert=False):
            self.answers.append({"text": text, "show_alert": show_alert})

        async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
            self.edits.append({
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            })
            self.message.text = text
            self.message.reply_markup = reply_markup

    class _DummyBot:
        def __init__(self):
            self.sent_messages = []
            self.edit_markup_calls = []
            self.deleted_messages = []

        async def send_message(self, **kwargs):
            self.sent_messages.append(kwargs)
            return SimpleNamespace(message_id=700 + len(self.sent_messages))

        async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
            self.edit_markup_calls.append({
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            })

        async def delete_message(self, chat_id, message_id):
            self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})

    class _FakeStorage:
        def __init__(self):
            self.alerts = {
                "abcd1234": {
                    "id": "abcd1234",
                    "title": "Pay rent",
                    "type": 3,
                    "type_name": "Weekly",
                    "schedule": {"days": ["Mon"], "time": "10:00"},
                    "active": True,
                    "tags": [],
                    "pre_alerts": [],
                }
            }
            self.events = []

        def get_alert_by_id(self, _user_id, alert_id):
            return self.alerts.get(alert_id)

        def get_user_prefs(self, _user_id):
            return {}

        def log_user_event(self, _user_id, event, payload):
            self.events.append({"event": event, "payload": payload})

    storage = _FakeStorage()
    bot = _DummyBot()
    context = SimpleNamespace(user_data={}, bot=bot, bot_data={})
    set_bot_runtime(context.bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
    user = SimpleNamespace(id=1)

    ts_val = str(int(datetime(2026, 5, 1, 9, 0, 0).timestamp()))
    summary_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔔 Pay rent", callback_data=f"missed_dtl_abcd1234_{ts_val}")
    ]])
    summary_message = _DummyMessage(101, reply_markup=summary_markup)

    def _has_summary_noop_edit():
        for call in bot.edit_markup_calls:
            if call.get("message_id") != 101:
                continue
            markup = call.get("reply_markup")
            if not markup or not getattr(markup, "inline_keyboard", None):
                continue
            for row in markup.inline_keyboard:
                for button in row:
                    if getattr(button, "callback_data", "") == "ghost_noop_abcd1234":
                        return True
        return False

    def _snapshot_has_noop(snapshot):
        if not isinstance(snapshot, list):
            return False
        for row in snapshot:
            if not isinstance(row, list):
                continue
            for item in row:
                if not isinstance(item, dict):
                    continue
                if item.get("callback_data") == "ghost_noop_abcd1234":
                    return True
        return False

    query_open = _DummyQuery(f"missed_dtl_abcd1234_{ts_val}", summary_message)
    update_open = SimpleNamespace(callback_query=query_open, effective_user=user, message=None)
    await handle_missed_dtl(update_open, context)

    picker_key = "ghost_picker_abcd1234"
    picker_state = context.user_data.get(picker_key) or {}
    picker_message = _DummyMessage(picker_state.get("picker_msg_id"), reply_markup=None)
    query_set = _DummyQuery("ghost_set_1h_abcd1234", picker_message)
    update_set = SimpleNamespace(callback_query=query_set, effective_user=user, message=None)
    with patch("modules.handlers.ghost_flow.find_existing_ghost", return_value=None), patch(
        "modules.handlers.ghost_flow.create_ghost_alert",
        return_value="ghost-new-1",
    ):
        await handle_ghost_set(update_set, context)
    summary_snapshot_used = (
        picker_state.get("summary_markup_key") == "ghost_summary_markup_101"
        and (
            _has_summary_noop_edit()
            or _snapshot_has_noop(context.user_data.get("ghost_summary_markup_101"))
            or "ghost_summary_markup_101" in context.user_data
        )
    )
    snapshot_after_creation = context.user_data.get("ghost_summary_markup_101")
    snapshot_after_creation_has_noop = _snapshot_has_noop(snapshot_after_creation)
    query_second_open = _DummyQuery(f"missed_dtl_abcd1234_{ts_val}", summary_message)
    update_second = SimpleNamespace(
        callback_query=query_second_open,
        effective_user=user,
        message=None,
    )
    await handle_missed_dtl(update_second, context)
    snapshot_after_second_press = context.user_data.get("ghost_summary_markup_101")
    snapshot_after_second_press_has_noop = _snapshot_has_noop(snapshot_after_second_press)
    snapshot_has_noop_signal = (
        snapshot_after_creation_has_noop
        or snapshot_after_second_press_has_noop
        or _has_summary_noop_edit()
    )

    query_noop = _DummyQuery("ghost_noop_abcd1234", _DummyMessage(102))
    update_noop = SimpleNamespace(callback_query=query_noop, effective_user=user, message=None)
    user_data_len_before_noop = len(context.user_data)
    await handle_ghost_noop(update_noop, context)
    ghost_noop_answers_only = bool(query_noop.answers) and len(context.user_data) == user_data_len_before_noop

    summary_message_2 = _DummyMessage(
        202,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔔 Pay rent", callback_data=f"missed_dtl_abcd1234_{ts_val}")
        ]]),
    )
    query_open2 = _DummyQuery(f"missed_dtl_abcd1234_{ts_val}", summary_message_2)
    await handle_missed_dtl(SimpleNamespace(callback_query=query_open2, effective_user=user, message=None), context)
    picker_state_2 = context.user_data.get(picker_key) or {}
    picker_message_2 = _DummyMessage(picker_state_2.get("picker_msg_id"), reply_markup=None)
    query_set2 = _DummyQuery("ghost_set_1h_abcd1234", picker_message_2)
    with patch("modules.handlers.ghost_flow.find_existing_ghost", return_value={"id": "existing-ghost"}):
        await handle_ghost_set(SimpleNamespace(callback_query=query_set2, effective_user=user, message=None), context)

    dedup_msg = bot.sent_messages[-1] if bot.sent_messages else {}
    dedup_markup = dedup_msg.get("reply_markup")
    dedup_buttons = []
    if dedup_markup and dedup_markup.inline_keyboard:
        for row in dedup_markup.inline_keyboard:
            dedup_buttons.extend(button.callback_data for button in row)

    context.user_data["ghost_dedup_abcd1234"] = datetime(2026, 5, 2, 9, 0, 0).isoformat()
    query_ok = _DummyQuery("ghost_dedup_ok_abcd1234", _DummyMessage(303))
    with patch("modules.handlers.ghost_flow.create_ghost_alert", return_value="ghost-new-2"):
        await handle_ghost_dedup_confirm(
            SimpleNamespace(callback_query=query_ok, effective_user=user, message=None),
            context,
        )

    context.user_data[picker_key] = {"source_alert": storage.alerts["abcd1234"]}
    context.user_data["ghost_dedup_abcd1234"] = datetime(2026, 5, 3, 9, 0, 0).isoformat()
    context.user_data["expecting_ghost_custom"] = {"source_alert_id": "abcd1234"}
    query_cancel = _DummyQuery("ghost_dedup_no_abcd1234", _DummyMessage(404))
    await handle_ghost_dedup_cancel(
        SimpleNamespace(callback_query=query_cancel, effective_user=user, message=None),
        context,
    )
    dedup_cancel_cleaned = (
        "ghost_picker_abcd1234" not in context.user_data
        and "ghost_dedup_abcd1234" not in context.user_data
        and "expecting_ghost_custom" not in context.user_data
    )

    context.user_data["ghost_picker_abcd1234"] = {"a": 1}
    context.user_data["ghost_dedup_abcd1234"] = "x"
    context.user_data["ghost_summary_markup_101"] = []
    context.user_data["ghost_delete_markup_zz"] = []
    context.user_data["expecting_ghost_custom"] = {"source_alert_id": "abcd1234"}
    clear_transient_context(context.user_data)
    cancel_cleared_ghost_keys = (
        "ghost_picker_abcd1234" not in context.user_data
        and "ghost_dedup_abcd1234" not in context.user_data
        and "ghost_summary_markup_101" not in context.user_data
        and "ghost_delete_markup_zz" not in context.user_data
        and "expecting_ghost_custom" not in context.user_data
    )

    context.user_data[picker_key] = {
        "source_alert": storage.alerts["abcd1234"],
        "summary_msg_id": None,
        "summary_markup_key": None,
        "picker_msg_id": 505,
    }
    query_custom = _DummyQuery(
        "ghost_set_cust_abcd1234",
        _DummyMessage(
            505,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("custom", callback_data="x")]]),
        ),
    )
    await handle_ghost_set_custom(SimpleNamespace(callback_query=query_custom, effective_user=user, message=None), context)
    bad_text_message = _DummyMessage(606, text="not a date")
    await handle_ghost_custom_text(SimpleNamespace(callback_query=None, effective_user=user, message=bad_text_message), context)

    checks = {
        "ghost_picker_opened": bool(picker_state) and picker_state.get("missed_date_str") != "recently",
        "ghost_set_created": any(e.get("event") == "ghost_created" for e in storage.events),
        "ghost_set_no_edit_in_picker_path": not query_set.edits,
        "summary_snapshot_used": summary_snapshot_used,
        "snapshot_setdefault_preserves_noop": (
            snapshot_has_noop_signal
            and snapshot_after_creation == snapshot_after_second_press
        ),
        "picker_deleted_after_create": any(item.get("message_id") == picker_state.get("picker_msg_id") for item in bot.deleted_messages),
        "dedup_buttons_emitted": "ghost_dedup_ok_abcd1234" in dedup_buttons and "ghost_dedup_no_abcd1234" in dedup_buttons,
        "dedup_confirm_creates": any(e.get("payload", {}).get("ghost_id") == "ghost-new-2" for e in storage.events),
        "dedup_confirm_edits_dialog": bool(query_ok.edits) and any(
            "✅ Ghost reminder" in (edit.get("text") or "")
            for edit in query_ok.edits
        ),
        "dedup_cancel_cleans_state": dedup_cancel_cleaned,
        "ghost_noop_answers_only": ghost_noop_answers_only,
        "cancel_clears_ghost_keys": cancel_cleared_ghost_keys,
        "custom_parse_error_keeps_state": bool(bad_text_message.replies) and "expecting_ghost_custom" in context.user_data,
    }
    dbg.section("ghost_picker", {"checks": checks})
    dbg.section("ghost_dedup", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("ghost_picker_failed", {"checks": checks})


async def _run_ghost_summary_logging_checks(dbg, handle_missed_dtl, handle_ghost_set):
    """Verify ghost summary markup diagnostics use reason codes without raw exception text."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    class _DummyMessage:
        def __init__(self, message_id, *, text=None, reply_markup=None):
            self.message_id = message_id
            self.text = text
            self.reply_markup = reply_markup
            self.replies = []

        async def reply_text(self, text, parse_mode=None, reply_markup=None):
            self.replies.append({
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            })
            return self

    class _DummyQuery:
        def __init__(self, data, message):
            self.data = data
            self.message = message
            self.answers = []
            self.edits = []

        async def answer(self, text=None, show_alert=False):
            self.answers.append({"text": text, "show_alert": show_alert})

        async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
            self.edits.append({
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            })
            self.message.text = text
            self.message.reply_markup = reply_markup

    class _DummyBot:
        def __init__(self, edit_exc=None):
            self.edit_exc = edit_exc
            self.sent_messages = []
            self.edit_markup_calls = []
            self.deleted_messages = []

        async def send_message(self, **kwargs):
            self.sent_messages.append(kwargs)
            return SimpleNamespace(message_id=700 + len(self.sent_messages))

        async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
            self.edit_markup_calls.append({
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            })
            if self.edit_exc is not None:
                raise self.edit_exc

        async def delete_message(self, chat_id, message_id):
            self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})

    class _FakeStorage:
        def __init__(self):
            self.alerts = {
                "abcd1234": {
                    "id": "abcd1234",
                    "title": "Pay rent",
                    "type": 3,
                    "type_name": "Weekly",
                    "schedule": {"days": ["Mon"], "time": "10:00"},
                    "active": True,
                    "tags": [],
                    "pre_alerts": [],
                }
            }
            self.events = []

        def get_alert_by_id(self, _user_id, alert_id):
            return self.alerts.get(alert_id)

        def get_user_prefs(self, _user_id):
            return {}

        def log_user_event(self, _user_id, event, payload):
            self.events.append({"event": event, "payload": payload})

    def _snapshot_has_noop(snapshot):
        if not isinstance(snapshot, list):
            return False
        for row in snapshot:
            if not isinstance(row, list):
                continue
            for item in row:
                if not isinstance(item, dict):
                    continue
                if item.get("callback_data") == "ghost_noop_abcd1234":
                    return True
        return False

    def _call_has_raw_text(mock_calls, needle):
        for call in mock_calls:
            for arg in call.args:
                if isinstance(arg, str) and needle in arg:
                    return True
        return False

    async def _exercise_case(exc):
        storage = _FakeStorage()
        bot = _DummyBot(edit_exc=exc)
        context = SimpleNamespace(user_data={}, bot=bot, bot_data={})
        set_bot_runtime(context.bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
        user = SimpleNamespace(id=1)
        ts_val = str(int(datetime(2026, 5, 1, 9, 0, 0).timestamp()))
        summary_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔔 Pay rent", callback_data=f"missed_dtl_abcd1234_{ts_val}")
        ]])
        summary_message = _DummyMessage(101, reply_markup=summary_markup)

        query_open = _DummyQuery(f"missed_dtl_abcd1234_{ts_val}", summary_message)
        update_open = SimpleNamespace(callback_query=query_open, effective_user=user, message=None)
        await handle_missed_dtl(update_open, context)

        picker_key = "ghost_picker_abcd1234"
        picker_state = context.user_data.get(picker_key) or {}
        picker_message = _DummyMessage(picker_state.get("picker_msg_id"), reply_markup=None)
        query_set = _DummyQuery("ghost_set_1h_abcd1234", picker_message)
        update_set = SimpleNamespace(callback_query=query_set, effective_user=user, message=None)

        with patch("modules.handlers.ghost_flow.find_existing_ghost", return_value=None), patch(
            "modules.handlers.ghost_flow.create_ghost_alert",
            return_value="ghost-new-logging",
        ), patch("modules.handlers.ghost_flow.logger.debug") as mock_debug, patch(
            "modules.handlers.ghost_flow.logger.warning"
        ) as mock_warning:
            await handle_ghost_set(update_set, context)

        return {
            "storage": storage,
            "context": context,
            "bot": bot,
            "mock_debug": mock_debug,
            "mock_warning": mock_warning,
        }

    noop_result = await _exercise_case(BadRequest("Message is not modified"))
    missing_result = await _exercise_case(BadRequest("Message to edit not found"))
    runtime_result = await _exercise_case(RuntimeError("boom"))

    noop_debug_extra = (
        noop_result["mock_debug"].call_args.kwargs.get("extra")
        if noop_result["mock_debug"].call_args
        else {}
    )
    missing_warning_extra = (
        missing_result["mock_warning"].call_args.kwargs.get("extra")
        if missing_result["mock_warning"].call_args
        else {}
    )
    runtime_warning_extra = (
        runtime_result["mock_warning"].call_args.kwargs.get("extra")
        if runtime_result["mock_warning"].call_args
        else {}
    )

    checks = {
        "noop_creation_succeeds": any(
            e.get("event") == "ghost_created"
            for e in noop_result["storage"].events
        ),
        "noop_snapshot_preserved": _snapshot_has_noop(
            noop_result["context"].user_data.get("ghost_summary_markup_101")
        ),
        "noop_no_warning": noop_result["mock_warning"].call_count == 0,
        "noop_reason_code_logged": noop_debug_extra.get("reason_code") == "message_not_modified",
        "noop_no_raw_exception_text": not _call_has_raw_text(
            noop_result["mock_debug"].call_args_list,
            "Message is not modified",
        ),
        "missing_warning_reason_code": missing_warning_extra.get("reason_code") == "message_not_found",
        "missing_no_raw_exception_text": not _call_has_raw_text(
            missing_result["mock_warning"].call_args_list,
            "Message to edit not found",
        ),
        "runtime_warning_reason_code": runtime_warning_extra.get("reason_code") == "unexpected_exception",
        "runtime_warning_error_class": runtime_warning_extra.get("error_class") == "RuntimeError",
        "runtime_no_raw_exception_text": not _call_has_raw_text(
            runtime_result["mock_warning"].call_args_list,
            "boom",
        ),
    }
    dbg.section("ghost_summary_logging", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("ghost_summary_logging_failed", {"checks": checks})


async def _run_ghost_notification_checks(
    dbg,
    format_ghost_alert,
    build_ghost_notification_keyboard,
    send_alert,
):
    class _DummyBot:
        def __init__(self):
            self.sent_text = []

        async def send_message(self, **kwargs):
            self.sent_text.append(kwargs)
            return {"ok": True}

    ghost_alert = {
        "id": "deadbeef",
        "title": "👻 Pay taxes_[soon]",
        "type": 5,
        "type_name": "One Time",
        "ghost_source_id": "src12345",
        "schedule": {"date": "01/01/2026", "time": "09:00"},
        "active": True,
        "tags": [],
        "pre_alerts": [],
    }
    dt = datetime(2026, 6, 1, 12, 30, 0)
    text = format_ghost_alert(ghost_alert, dt)
    kb = build_ghost_notification_keyboard(ghost_alert, dt, dt)
    bot = _DummyBot()
    await send_alert(
        bot,
        1,
        ghost_alert,
        alert_type="main",
        scheduled_time=dt,
        occurrence_time=dt,
    )
    sent = bot.sent_text[0] if bot.sent_text else {}
    sent_markup = sent.get("reply_markup")
    callbacks = []
    if kb and kb.inline_keyboard:
        for row in kb.inline_keyboard:
            callbacks.extend(button.callback_data for button in row)
    sent_callbacks = []
    if sent_markup and sent_markup.inline_keyboard:
        for row in sent_markup.inline_keyboard:
            sent_callbacks.extend(button.callback_data for button in row)

    checks = {
        "format_header": "👻 *Ghost Reminder*" in text,
        "format_title_strips_prefix": "👻 Pay taxes" not in text and "Pay taxes" in text,
        "format_escapes_title": "\\_" in text and "\\[" in text,
        "keyboard_has_4_buttons": len(callbacks) == 4,
        "keyboard_prefixes_ok": (
            any(cb.startswith("ghost_noted_") for cb in callbacks)
            and any(cb.startswith("pp_menu_due_") for cb in callbacks)
            and any(cb.startswith("ghost_dtl_") for cb in callbacks)
            and any(cb.startswith("ghost_del_") for cb in callbacks)
        ),
        "send_dispatch_ghost_text": isinstance(sent.get("text"), str) and "Ghost Reminder" in sent.get("text"),
        "send_dispatch_ghost_keyboard": any(cb.startswith("ghost_noted_") for cb in sent_callbacks),
    }
    dbg.section("ghost_notification", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("ghost_notification_failed", {"checks": checks})


async def _run_ghost_postpone_checks(dbg, process_postpone_queue_for_user):
    class _Storage:
        def __init__(self):
            self.updated = []
            self.events = []
            self.cleaned = []

        def update_postpone_instance(self, _user_id, postpone_id, updates):
            self.updated.append((postpone_id, dict(updates or {})))

        def log_user_event(self, _user_id, event, payload):
            self.events.append((event, dict(payload or {})))

        def cleanup_postpone_queue(self, _user_id, now_iso):
            self.cleaned.append(now_iso)

    now = datetime(2026, 5, 1, 12, 0, 0)
    fire_at = (now - timedelta(minutes=1)).isoformat()
    alerts = {
        "g1": {"id": "g1", "type": 5, "active": False},
        "o1": {"id": "o1", "type": 5, "active": False},
        "r1": {"id": "r1", "type": 3, "active": False},
    }
    items = [
        {"id": "p-ghost-due", "status": "pending", "alert_id": "g1", "kind": "due", "fire_at": fire_at},
        {"id": "p-one-due", "status": "pending", "alert_id": "o1", "kind": "due", "fire_at": fire_at},
        {"id": "p-rec-due", "status": "pending", "alert_id": "r1", "kind": "due", "fire_at": fire_at},
        {"id": "p-one-pre", "status": "pending", "alert_id": "o1", "kind": "pre", "fire_at": fire_at},
    ]
    storage = _Storage()
    trigger_calls = []

    async def _fake_trigger_alert(
        _bot,
        _user_id,
        alert,
        _alert_type,
        _storage,
        _sent_pre_alerts,
        **kwargs,
    ):
        trigger_calls.append((alert.get("id"), kwargs))
        return {"ok": True}

    async def _fake_send_alert(*args, **kwargs):
        return {"ok": True}

    with patch("modules.scheduler_core.postpone.trigger_alert", new=_fake_trigger_alert), patch(
        "modules.scheduler_core.postpone.send_alert",
        new=_fake_send_alert,
    ):
        pre_sent, due_sent = await process_postpone_queue_for_user(
            bot=None,
            user_id=1,
            alert_map=alerts,
            postpone_items=items,
            now=now,
            storage=storage,
            sent_pre_alerts=set(),
        )

    fired_ids = [pid for pid, upd in storage.updated if upd.get("status") == "fired"]
    expired_ids = [pid for pid, upd in storage.updated if upd.get("status") == "expired"]
    checks = {
        "inactive_type5_due_ghost_fires": "p-ghost-due" in fired_ids,
        "inactive_type5_due_standard_fires": "p-one-due" in fired_ids,
        "inactive_recurring_due_expires": "p-rec-due" in expired_ids,
        "inactive_type5_pre_expires": "p-one-pre" in expired_ids,
        "due_sent_count": due_sent == 2,
        "pre_sent_count": pre_sent == 0,
        "trigger_called_for_two_type5_due": sorted(aid for aid, _ in trigger_calls) == ["g1", "o1"],
    }
    dbg.section("ghost_postpone", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("ghost_postpone_failed", {"checks": checks})


async def _run_ghost_callbacks_checks(
    dbg,
    handle_ghost_noted,
    handle_ghost_dtl,
    handle_ghost_del,
    handle_ghost_del_confirm,
    handle_ghost_del_cancel,
):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    class _Storage:
        def __init__(self):
            self.alerts = {
                "gh1": {"id": "gh1", "title": "👻 Ghost 1", "ghost_source_id": "src1"},
                "src1": {"id": "src1", "title": "Source 1"},
                "gh2": {"id": "gh2", "title": "👻 Ghost 2", "ghost_source_id": "src2"},
            }
            self.deleted = []
            self.events = []

        def get_alert_by_id(self, _uid, aid):
            return self.alerts.get(aid)

        def delete_alert(self, _uid, aid):
            self.deleted.append(aid)
            self.alerts.pop(aid, None)
            return True

        def log_user_event(self, _uid, event, payload):
            self.events.append((event, dict(payload or {})))

    class _Bot:
        def __init__(self):
            self.messages = []

        async def send_message(self, **kwargs):
            self.messages.append(kwargs)
            return {"ok": True}

    class _Query:
        def __init__(self, data, message):
            self.data = data
            self.message = message
            self.answered = []
            self.edits = []
            self.markup_edits = []

        async def answer(self, text=None, show_alert=False):
            self.answered.append((text, show_alert))

        async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
            self.edits.append((text, parse_mode, reply_markup))
            self.message.reply_markup = reply_markup

        async def edit_message_reply_markup(self, reply_markup=None):
            self.markup_edits.append(reply_markup)
            self.message.reply_markup = reply_markup

    class _QueryBadRequest(_Query):
        async def edit_message_reply_markup(self, reply_markup=None):
            raise BadRequest("Message is not modified")

    storage = _Storage()
    bot = _Bot()
    context = SimpleNamespace(user_data={}, bot=bot, bot_data={})
    set_bot_runtime(context.bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
    user = SimpleNamespace(id=1)
    message = SimpleNamespace(reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Noted", callback_data="ghost_noted_gh1"),
        InlineKeyboardButton("⏰ Postpone", callback_data="pp_menu_due_gh1_1_1"),
    ]]))

    q_noted = _Query("ghost_noted_gh1", message)
    await handle_ghost_noted(SimpleNamespace(callback_query=q_noted, effective_user=user), context)

    q_dtl_alive = _Query("ghost_dtl_gh1", message)
    with patch("modules.handlers.ghost_flow.send_alert_detail_by_id") as mock_detail:
        await handle_ghost_dtl(SimpleNamespace(callback_query=q_dtl_alive, effective_user=user), context)
    # source deleted flow
    storage.alerts.pop("src2", None)
    q_dtl_deleted = _Query("ghost_dtl_gh2", message)
    await handle_ghost_dtl(SimpleNamespace(callback_query=q_dtl_deleted, effective_user=user), context)

    q_del = _Query("ghost_del_gh1", message)
    await handle_ghost_del(SimpleNamespace(callback_query=q_del, effective_user=user), context)

    q_del_cancel = _Query("ghost_del_no_gh1", message)
    await handle_ghost_del_cancel(SimpleNamespace(callback_query=q_del_cancel, effective_user=user), context)
    context.user_data["ghost_delete_markup_gh1"] = [[{"text": "✅ Noted", "callback_data": "ghost_noted_gh1"}]]
    q_del_cancel_bad_request = _QueryBadRequest("ghost_del_no_gh1", message)
    await handle_ghost_del_cancel(SimpleNamespace(callback_query=q_del_cancel_bad_request, effective_user=user), context)

    # re-open and confirm delete
    await handle_ghost_del(SimpleNamespace(callback_query=q_del, effective_user=user), context)
    q_del_ok = _Query("ghost_del_ok_gh1", message)
    await handle_ghost_del_confirm(SimpleNamespace(callback_query=q_del_ok, effective_user=user), context)

    checks = {
        "ghost_noted_answered": bool(q_noted.answered),
        "ghost_dtl_source_alive_calls_detail": mock_detail.called,
        "ghost_dtl_include_back_false": (
            mock_detail.call_args is not None
            and mock_detail.call_args.kwargs.get("include_back") is False
        ),
        "ghost_dtl_no_source_hint_alerts": (
            mock_detail.call_args is None
            or mock_detail.call_args.kwargs.get("source_hint") != "alerts"
        ),
        "ghost_dtl_source_deleted_sends_message": any("Original alert was deleted" in (m.get("text") or "") for m in bot.messages),
        "ghost_del_prompts_confirmation": bool(q_del.edits),
        "ghost_del_cancel_restores_markup": bool(q_del_cancel.markup_edits),
        "ghost_del_cancel_answers_on_bad_request": bool(q_del_cancel_bad_request.answered),
        "ghost_del_confirm_deletes": "gh1" in storage.deleted,
        "ghost_del_confirm_logs": any(evt == "ghost_deleted" for evt, _ in storage.events),
    }
    dbg.section("ghost_callbacks", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("ghost_callbacks_failed", {"checks": checks})


def _run_ghost_dtl_order_checks(dbg):
    from modules.handlers.ghost_flow import _find_deletion_ts

    with tempfile.TemporaryDirectory() as tmpdir:
        active_log = os.path.join(tmpdir, "1_events.log")
        rotation_log = os.path.join(tmpdir, "1_events.log.2026-05-04")

        with open(active_log, "w", encoding="utf-8") as handle:
            handle.write(
                '{"event":"alert_deleted","ts":"2026-05-05T10:00:00Z","payload":{"alert_id":"src1"}}\n'
            )
        os.utime(active_log, (2000.0, 2000.0))

        with open(rotation_log, "w", encoding="utf-8") as handle:
            handle.write(
                '{"event":"alert_deleted","ts":"2026-05-04T08:00:00Z","payload":{"alert_id":"src1"}}\n'
            )
        os.utime(rotation_log, (1000.0, 1000.0))

        with patch(
            "modules.handlers.ghost_flow.get_user_event_log_paths",
            return_value=sorted([active_log, rotation_log]),
        ):
            result = _find_deletion_ts(None, 1, "src1")
            result_missing = _find_deletion_ts(None, 1, "src_missing")

    checks = {
        "newest_mtime_searched_first": result == "2026-05-05T10:00:00Z",
        "missing_source_returns_none": result_missing is None,
    }
    dbg.section("ghost_dtl_order", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("ghost_dtl_order_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.ghost_utils import (
                create_ghost_alert,
                find_existing_ghost,
                get_pending_ghost_alerts,
                is_ghost_alert,
            )
            from modules.storage import StorageManager
            from modules.scheduler_core.missed import handle_missed_alerts
            from modules.scheduler_messagelogic import send_missed_alerts_batch
            from modules.handlers.ghost_flow import (
                handle_ghost_custom_text,
                handle_ghost_dedup_cancel,
                handle_ghost_dedup_confirm,
                handle_ghost_noop,
                handle_ghost_set,
                handle_ghost_set_custom,
                handle_missed_dtl,
            )
            from modules.shared.context_cleanup import clear_transient_context
            from modules.timezone_utils import resolve_user_timezone, to_server_naive_from_user
            from modules.ui.formatters.alert_text import format_missed_alerts_summary
            from modules.ui.formatters.alert_text import format_ghost_alert
            from modules.ui.keyboards.notification_kb import build_ghost_notification_keyboard
            from modules.ui.send_utils import send_alert
            from modules.scheduler_core.postpone import process_postpone_queue_for_user
            from modules.handlers.ghost_flow import (
                handle_ghost_noted,
                handle_ghost_dtl,
                handle_ghost_del,
                handle_ghost_del_confirm,
                handle_ghost_del_cancel,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _run_ghost_utils_unit_checks(
            dbg,
            StorageManager,
            create_ghost_alert,
            find_existing_ghost,
            get_pending_ghost_alerts,
            is_ghost_alert,
            resolve_user_timezone,
            to_server_naive_from_user,
        )
        _run_summary_text_checks(dbg, format_missed_alerts_summary)
        run_async(_run_ghost_missed_filter_checks(dbg, handle_missed_alerts))
        run_async(_run_inactive_postpone_missed_checks(dbg, handle_missed_alerts))
        run_async(_run_summary_send_checks(dbg, send_missed_alerts_batch, handle_missed_alerts))
        run_async(
            _run_ghost_picker_and_dedup_checks(
                dbg,
                handle_missed_dtl,
                handle_ghost_set,
                handle_ghost_set_custom,
                handle_ghost_custom_text,
                handle_ghost_dedup_confirm,
                handle_ghost_dedup_cancel,
                handle_ghost_noop,
                clear_transient_context,
            )
        )
        run_async(_run_ghost_summary_logging_checks(
            dbg,
            handle_missed_dtl,
            handle_ghost_set,
        ))
        run_async(
            _run_ghost_notification_checks(
                dbg,
                format_ghost_alert,
                build_ghost_notification_keyboard,
                send_alert,
            )
        )
        run_async(_run_ghost_postpone_checks(dbg, process_postpone_queue_for_user))
        run_async(
            _run_ghost_callbacks_checks(
                dbg,
                handle_ghost_noted,
                handle_ghost_dtl,
                handle_ghost_del,
                handle_ghost_del_confirm,
                handle_ghost_del_cancel,
            )
        )
        _run_ghost_dtl_order_checks(dbg)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem(
        "ghost_utils_unit_failed",
        "summary_text_failed",
        "summary_send_failed",
        "ghost_missed_filter_failed",
        "inactive_postpone_missed_failed",
        "ghost_picker_failed",
        "ghost_summary_logging_failed",
        "ghost_notification_failed",
        "ghost_postpone_failed",
        "ghost_callbacks_failed",
        "ghost_dtl_order_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"ghost-utils+summary-text: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
