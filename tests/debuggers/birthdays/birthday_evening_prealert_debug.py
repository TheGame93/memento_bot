#!/usr/bin/env python3
import os
import sys
from datetime import datetime


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
SCRIPT_TITLE = "birthday_evening_prealert_debug"
FEATURE_TITLE = "Birthday Evening-Before Pre-Alert"


class _DummyMessage:
    def __init__(self, message_id=101):
        self.message_id = message_id
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append({
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        })
        return self


class _DummyCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = []
        self.edited = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        self.edited.append({
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })


class _DummyUpdate:
    def __init__(self, callback_query=None):
        self.callback_query = callback_query


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}


def _button_rows(markup):
    rows = []
    for row in getattr(markup, "inline_keyboard", []) or []:
        rows.append([{"text": btn.text, "data": btn.callback_data} for btn in row])
    return rows


def _check_token_selection_path(dbg, C, type_flow):
    async def _return_to_settings(_update, context):
        context.user_data["returned_to_settings"] = True
        return C.MULTI_SETTINGS

    ctx = _DummyContext({
        "settings_return": "birthday",
        "temp_alert": {"type": 6, "pre_alerts": []},
    })
    query_show = _DummyCallbackQuery("pre_dummy", _DummyMessage(message_id=201))
    state_show = run_async(type_flow.show_pre_alert_menu(_DummyUpdate(callback_query=query_show), ctx))
    rows = _button_rows(query_show.edited[-1].get("reply_markup") if query_show.edited else None)

    query_pick = _DummyCallbackQuery("pre_bdayeve", _DummyMessage(message_id=202))
    state_pick = run_async(type_flow.get_pre_alert_callback(
        _DummyUpdate(callback_query=query_pick),
        ctx,
        _return_to_settings,
    ))

    checks = {
        "menu_state": state_show == C.GET_PRE_ALERT,
        "menu_has_evening_option": any(
            btn.get("data") == "pre_bdayeve" for row in rows for btn in row
        ),
        "selection_returns": state_pick == C.MULTI_SETTINGS,
        "selection_writes_token": ctx.user_data.get("temp_alert", {}).get("pre_alerts") == [
            C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN,
        ],
    }
    dbg.section("token_selection_path", {"checks": checks, "rows": rows})
    if not all(checks.values()):
        dbg.problem("token_selection_path_failed", {"checks": checks, "rows": rows})


def _check_midnight_resolution(dbg, C, resolve_pre_alert_fire_time):
    token = C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN
    alert = {
        "id": "b-midnight",
        "type": 6,
        "type_name": C.ALERT_TYPES.get(6, "Birthday"),
        "schedule": {"date": "10/01", "time": "00:10"},
        "pre_alerts": [token],
        "tags": [],
    }

    # Server-mode baseline.
    main_server = datetime(2026, 1, 10, 0, 10, 0)
    pre_server, kind_server = resolve_pre_alert_fire_time(
        alert,
        token,
        main_server,
        user_prefs={"birthday_evening_before_time": "20:00"},
    )

    # User-timezone mode should resolve using local day boundaries.
    from modules.timezone_utils import (
        get_server_tz,
        resolve_user_timezone,
        to_server_naive_from_user,
        to_user_naive_from_server,
    )

    user_prefs = {
        "timezone_mode": C.TIMEZONE_MODE_USER,
        "timezone": {"name": "America/New_York"},
        "birthday_evening_before_time": "19:45",
    }
    server_tz = get_server_tz()
    user_tz = resolve_user_timezone(user_prefs)
    local_main = datetime(2026, 1, 10, 0, 10, 0)
    main_server_user_mode, _shifted = to_server_naive_from_user(local_main, user_tz, server_tz)
    pre_server_user, kind_user = resolve_pre_alert_fire_time(
        alert,
        token,
        main_server_user_mode,
        user_prefs=user_prefs,
    )
    pre_local_user = to_user_naive_from_server(pre_server_user, user_tz, server_tz) if pre_server_user else None

    checks = {
        "server_mode_kind": kind_server == "birthday_evening_before",
        "server_mode_time": pre_server == datetime(2026, 1, 9, 20, 0, 0),
        "user_mode_kind": kind_user == "birthday_evening_before",
        "user_mode_local_day_before": bool(pre_local_user and pre_local_user.date().isoformat() == "2026-01-09"),
        "user_mode_local_time": bool(pre_local_user and pre_local_user.strftime("%H:%M") == "19:45"),
    }
    dbg.section("midnight_resolution", {
        "checks": checks,
        "main_server": main_server.isoformat(),
        "pre_server": pre_server.isoformat() if pre_server else None,
        "main_server_user_mode": main_server_user_mode.isoformat(),
        "pre_server_user": pre_server_user.isoformat() if pre_server_user else None,
        "pre_local_user": pre_local_user.isoformat() if pre_local_user else None,
    })
    if not all(checks.values()):
        dbg.problem("midnight_resolution_failed", {"checks": checks})


async def _run_scheduler_due_window_check(dbg, C, coordinator, scheduler_state):
    token = C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN
    alert = {
        "id": "b-due-window",
        "title": "Birthday Due Window",
        "type": 6,
        "type_name": C.ALERT_TYPES.get(6, "Birthday"),
        "active": True,
        "schedule": {"date": "12/03", "time": "08:00"},
        "pre_alerts": [token],
        "next_scheduled": datetime(2026, 3, 12, 8, 0, 0).isoformat(),
        "tags": [],
    }
    user_id = "9901"
    now = datetime(2026, 3, 11, 20, 0, 0)
    expected_pre = datetime(2026, 3, 11, 20, 0, 0)
    user_prefs = {"birthday_evening_before_time": "20:00"}

    sent_calls = []

    async def _fake_send_alert(*_args, **kwargs):
        sent_calls.append({
            "scheduled_time": kwargs.get("scheduled_time"),
            "main_trigger_time": kwargs.get("main_trigger_time"),
            "pre_alert_str": kwargs.get("pre_alert_str"),
        })
        return {"ok": True}

    original_send_alert = coordinator.send_alert
    original_storage = coordinator._storage
    original_save_state = scheduler_state.save_pre_alert_state
    original_sent = dict(scheduler_state.sent_pre_alerts)
    original_sent_dirty = scheduler_state.sent_pre_alerts_dirty

    try:
        coordinator.send_alert = _fake_send_alert
        coordinator._storage = None
        scheduler_state.save_pre_alert_state = lambda: True
        scheduler_state.sent_pre_alerts.clear()
        scheduler_state.sent_pre_alerts_dirty = False

        count_first = await coordinator.check_pre_alerts(
            bot=object(),
            user_id=user_id,
            alert=alert,
            now=now,
            user_prefs=user_prefs,
        )
        count_second = await coordinator.check_pre_alerts(
            bot=object(),
            user_id=user_id,
            alert=alert,
            now=now,
            user_prefs=user_prefs,
        )

        tracking_key = (str(user_id), alert["id"], token)
        first_call = sent_calls[0] if sent_calls else {}

        checks = {
            "first_due_sent": count_first == 1,
            "second_suppressed_by_tracking": count_second == 0,
            "single_send_call": len(sent_calls) == 1,
            "tracking_key_recorded": tracking_key in scheduler_state.sent_pre_alerts,
            "scheduled_time_matches_evening": first_call.get("scheduled_time") == expected_pre,
            "main_trigger_preserved": first_call.get("main_trigger_time") == datetime(2026, 3, 12, 8, 0, 0),
            "token_forwarded": first_call.get("pre_alert_str") == token,
        }
        dbg.section("scheduler_due_window", {
            "checks": checks,
            "sent_calls": sent_calls,
            "tracking_keys": [list(k) for k in scheduler_state.sent_pre_alerts.keys()],
        })
        if not all(checks.values()):
            dbg.problem("scheduler_due_window_failed", {"checks": checks, "sent_calls": sent_calls})
    finally:
        coordinator.send_alert = original_send_alert
        coordinator._storage = original_storage
        scheduler_state.save_pre_alert_state = original_save_state
        scheduler_state.sent_pre_alerts.clear()
        scheduler_state.sent_pre_alerts.update(original_sent)
        scheduler_state.sent_pre_alerts_dirty = original_sent_dirty


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        try:
            from modules import constants as C
            from modules.handlers.add_flow import type_flow
            from modules.scheduler_mathlogic import resolve_pre_alert_fire_time
            from modules.scheduler_core import coordinator, state as scheduler_state
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _check_token_selection_path(dbg, C, type_flow)
        _check_midnight_resolution(dbg, C, resolve_pre_alert_fire_time)
        run_async(_run_scheduler_due_window_check(dbg, C, coordinator, scheduler_state))

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    token_ok = not dbg.has_problem("token_selection_path_failed")
    midnight_ok = not dbg.has_problem("midnight_resolution_failed")
    scheduler_ok = not dbg.has_problem("scheduler_due_window_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"token-selection: {'OK' if token_ok else 'FAIL'}",
        f"midnight-resolution: {'OK' if midnight_ok else 'FAIL'}",
        f"scheduler-due-window: {'OK' if scheduler_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
