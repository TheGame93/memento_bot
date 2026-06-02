#!/usr/bin/env python3
import os
import sys
from datetime import datetime, timedelta


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
from _lib.runtime import (
    restore_mainbot_runtime,
    run_async,
    seed_mainbot_runtime,
    snapshot_mainbot_runtime,
)
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "next_birthdays_shortcuts_debug"
FEATURE_TITLE = "Next Birthdays Shortcuts"

IMPORT_ERROR = None


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})
        return True


class _DummyUpdate:
    def __init__(self, user_id):
        self.effective_user = _DummyUser(user_id)
        self.callback_query = None


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot = _DummyBot()
        self.bot_data = {}


class _FakeStorage:
    def __init__(self, alerts):
        self._alerts = alerts
        self.logged = []

    def get_all_alerts(self, _user_id):
        return {"alerts": list(self._alerts)}

    def get_user_prefs(self, _user_id):
        return {"birthday_default_time": "08:00"}

    def log_user_event(self, user_id, event, payload):
        self.logged.append({"user_id": user_id, "event": event, "payload": payload})


def _build_birthday(alert_id, title, date_dt, birth_year=None, pre_alerts=None):
    return {
        "id": alert_id,
        "title": title,
        "type": 6,
        "type_name": "Birthday",
        "active": True,
        "schedule": {"date": f"{date_dt.day}/{date_dt.month}", "time": "08:00"},
        "pre_alerts": list(pre_alerts or []),
        "tags": [],
        "birth_year": birth_year,
    }


def _run_checks(dbg, mainbot, show_next_birthdays, list_context_key, get_back_button):
    now = datetime.now()
    past = now - timedelta(days=3)
    future = now + timedelta(days=5)
    today_age = now.year - 1990
    past_age = past.year - 1985
    future_age = future.year - 2000
    today_pre = (now - timedelta(days=1)).strftime("%a %d %b")
    future_date = future.strftime("%a %d %b")

    alerts = [
        _build_birthday("b_past", "Past", past, birth_year=1985),
        _build_birthday("b_today", "Today", now, birth_year=1990, pre_alerts=["1d"]),
        _build_birthday("b_today_unknown", "Mystery", now, birth_year=None),
        _build_birthday("b_future", "Future", future, birth_year=2000, pre_alerts=["1d"]),
    ]
    fake_storage = _FakeStorage(alerts)

    runtime_snapshot = snapshot_mainbot_runtime(mainbot)
    try:
        ctx = _DummyContext()
        seed_mainbot_runtime(mainbot, app=ctx, storage=fake_storage)
        update = _DummyUpdate(user_id=1)
        run_async(show_next_birthdays(update, ctx))
    finally:
        restore_mainbot_runtime(mainbot, runtime_snapshot)

    ctx_data = ctx.user_data.get(list_context_key, {})
    alias_map = ctx_data.get("alias_map", {}) if isinstance(ctx_data, dict) else {}
    message = ctx.bot.sent[-1]["text"] if ctx.bot.sent else ""

    context_for_back = _DummyContext()
    context_for_back.user_data["birthday_current_filter"] = "Family"
    context_for_back.user_data["current_filter"] = "Work"
    back_button = get_back_button(context_for_back, "next_birthdays")
    back_text = getattr(back_button, "text", None)

    valid_ids = {a["id"] for a in alerts}
    alias_ids_ok = all(val in valid_ids for val in alias_map.values())

    checks = {
        "context_saved": bool(ctx_data),
        "source_next_birthdays": ctx_data.get("source") == "next_birthdays",
        "alias_map_has_01": "01" in alias_map,
        "alias_map_ids_valid": alias_ids_ok,
        "message_has_hint": "(press the number for INFO)" in message,
        "message_has_new_title": "⏩ Next Birthdays" in message,
        "message_has_header_rule": "━━━━━━━━━━━━━━" in message,
        "message_has_sections_last_today_next": (
            message.find("LAST 10 DAYS") < message.find("TODAY") < message.find("NEXT 30 DAYS")
        ),
        "message_has_alias_01_colon": "/01 : " in message,
        "message_has_today_flame_prefix": "🔥 /02 : " in message,
        "message_has_today_flame_pre_alert": f"🔥 ├─ 🔔 {today_pre}" in message,
        "message_has_turns_today": f"🔥 ╰─ 🎂 turns {today_age} today!" in message,
        "message_has_unknown_age": "🔥 ╰─ 🎂 ?? (mysterious age, discover it!)" in message,
        "message_has_today_flame_spacer": "\n🔥\n🔥 /03 : " in message,
        "message_has_turned_past": f"╰─ 🎂 turned {past_age} on" in message,
        "message_has_turns_future": f"╰─ 🎂 turns {future_age} on {future_date} (in 5d)" in message,
        "back_uses_birthday_filter": back_text == "⬅️ Back (Family)",
    }
    dbg.section("next_birthdays_shortcuts", {
        "checks": checks,
        "alias_map": alias_map,
        "message_head": message.splitlines()[:6],
        "back_text": back_text,
    })
    if not all(checks.values()):
        dbg.problem("next_birthdays_shortcuts_failed", {"checks": checks})


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            import mainbot
            from modules.handlers.birthday_flow.list_view import show_next_birthdays
            from modules.handlers.list_alerts import LIST_CONTEXT_KEY, _get_back_button
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _run_checks(dbg, mainbot, show_next_birthdays, LIST_CONTEXT_KEY, _get_back_button)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem("next_birthdays_shortcuts_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"shortcuts: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
