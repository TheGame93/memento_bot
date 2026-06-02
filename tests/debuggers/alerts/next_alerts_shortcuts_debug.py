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
SCRIPT_TITLE = "next_alerts_shortcuts_debug"
FEATURE_TITLE = "Next Alerts Shortcuts"

IMPORT_ERROR = None


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return self


class _DummyUpdate:
    def __init__(self, user_id):
        self.effective_user = _DummyUser(user_id)
        self.message = _DummyMessage()
        self.callback_query = None


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})
        return True


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot = _DummyBot()
        self.bot_data = {}


class _FakeStorage:
    def __init__(self, alerts, postpone_queue):
        self._alerts = alerts
        self._postpone_queue = postpone_queue
        self.logged = []

    def get_all_alerts(self, _user_id):
        return {"alerts": list(self._alerts), "postpone_queue": list(self._postpone_queue)}

    def log_user_event(self, user_id, event, payload):
        self.logged.append({"user_id": user_id, "event": event, "payload": payload})


def _build_one_time(alert_id, title, date_dt, tags=None, pre_alerts=None):
    return {
        "id": alert_id,
        "title": title,
        "type": 5,
        "type_name": "One Time",
        "active": True,
        "schedule": {"date": date_dt.strftime("%d/%m/%Y"), "time": date_dt.strftime("%H:%M")},
        "pre_alerts": list(pre_alerts or []),
        "tags": list(tags or []),
    }


def _run_checks(dbg, mainbot, show_next_alerts, list_context_key):
    now = datetime.now()
    postponed_fire = now + timedelta(hours=1)
    alert_due = _build_one_time("a_due", "Due Soon", now + timedelta(days=120))
    alert_scheduled = _build_one_time(
        "a_sched",
        "Scheduled",
        now + timedelta(days=3),
        tags=["💼 Work", "🏥 Health"],
        pre_alerts=["1d", "2d"],
    )
    sched_pre_dup = now + timedelta(days=1)
    sched_pre_extra = now + timedelta(hours=12)
    fake_storage = _FakeStorage(
        alerts=[alert_due, alert_scheduled],
        postpone_queue=[{
            "status": "pending",
            "kind": "due",
            "alert_id": "a_due",
            "fire_at": postponed_fire.isoformat(),
        }, {
            "status": "pending",
            "kind": "pre",
            "alert_id": "a_sched",
            "fire_at": sched_pre_dup.isoformat(),
        }, {
            "status": "pending",
            "kind": "pre",
            "alert_id": "a_sched",
            "fire_at": sched_pre_extra.isoformat(),
        }],
    )

    runtime_snapshot = snapshot_mainbot_runtime(mainbot)
    try:
        ctx = _DummyContext()
        seed_mainbot_runtime(mainbot, app=ctx, storage=fake_storage)
        update = _DummyUpdate(user_id=1)
        run_async(show_next_alerts(update, ctx))
    finally:
        restore_mainbot_runtime(mainbot, runtime_snapshot)

    ctx_data = ctx.user_data.get(list_context_key, {})
    alias_map = ctx_data.get("alias_map", {}) if isinstance(ctx_data, dict) else {}
    message = update.message.replies[-1]["text"] if update.message.replies else ""
    view_events = [entry for entry in fake_storage.logged if entry.get("event") == "alerts_next_view"]
    view_event = view_events[-1] if view_events else None
    view_payload = view_event.get("payload", {}) if view_event else {}

    lines = message.splitlines()
    block_start = next((idx for idx, line in enumerate(lines) if line.startswith("/02 `:`")), None)
    block_lines = []
    if block_start is not None:
        for line in lines[block_start + 1:]:
            if not line.strip():
                break
            block_lines.append(line)
    block_text = "\n".join(block_lines)
    block_pre_count = block_text.count("├─ 🔔")
    block_due_last = bool(block_lines) and block_lines[-1].startswith("╰─ ")

    checks = {
        "context_saved": bool(ctx_data),
        "source_next_alerts": ctx_data.get("source") == "next_alerts",
        "alias_map_has_01": "01" in alias_map,
        "alias_map_has_02": "02" in alias_map,
        "alias_01_matches_due": alias_map.get("01") == "a_due",
        "message_has_hint": "(press the number for INFO)" in message,
        "message_has_header_rule": "━━━━━━━━━━━━━━" in message,
        "message_has_alias_01": "/01 `:`" in message,
        "message_has_inline_tags": "/02 `:` 💼🏥 `:`" in message,
        "message_has_prealert_line": "├─ 🔔" in message,
        "message_has_due_no_tags": "╰─ 🔥" in message,
        "message_has_no_tag_line": "╰─ 💼🏥" not in message,
        "block_has_single_inline_tags": block_text.count("💼🏥") == 0,
        "block_multiple_prealerts": block_pre_count == 3,
        "block_due_last": block_due_last,
        "log_event_present": bool(view_event),
        "log_count": view_payload.get("count") == 3,
        "log_items_with_tags": view_payload.get("items_with_tags") == 1,
        "log_items_with_pre_alerts": view_payload.get("items_with_pre_alerts") == 1,
        "log_items_priority": view_payload.get("items_priority") == 1,
        "log_postponed_pre_alerts_merged": view_payload.get("postponed_pre_alerts_merged") == 1,
        "icons_not_codeblocked": all(token not in message for token in ("`🔥`", "`🗓`", "`🔔`")),
    }
    dbg.section("next_alerts_shortcuts", {
        "checks": checks,
        "alias_map": alias_map,
        "view_payload": view_payload,
        "message_head": lines[:6],
        "block_lines": block_lines,
    })
    if not all(checks.values()):
        dbg.problem("next_alerts_shortcuts_failed", {"checks": checks})


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
            from modules.handlers.next_alerts import show_next_alerts
            from modules.handlers.list_alerts import LIST_CONTEXT_KEY
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _run_checks(dbg, mainbot, show_next_alerts, LIST_CONTEXT_KEY)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem("next_alerts_shortcuts_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"shortcuts: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
