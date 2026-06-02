#!/usr/bin/env python3
import asyncio
import os
import sys
from datetime import datetime
from types import SimpleNamespace


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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "one_time_date_prompt_debug"
FEATURE_TITLE = "One-Time Date Prompt Contract"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _DummyStorage:
    def __init__(self, prefs=None):
        self._prefs = prefs or {}
        self.events = []

    def get_user_prefs(self, user_id):
        return self._prefs.get(str(user_id), {})

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": str(user_id),
            "event": event_type,
            "payload": payload or {},
        })
        return True


class _DummyMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return True


class _DummyUpdate:
    def __init__(self, user_id, text):
        self.effective_user = SimpleNamespace(id=user_id)
        self.message = _DummyMessage(text)


class _DummyContext:
    def __init__(self):
        self.user_data = {
            "temp_alert": {"schedule": {"time": "10:00"}},
        }
        self.bot_data = {}


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )


async def _show_multi_setting_menu(_update, _context):
    return "UNEXPECTED_NEXT_STATE"


def _check_today_prompt_contract(dbg, type_flow, C):
    user_id = 7001
    update = _DummyUpdate(user_id, "16/05")
    context = _DummyContext()
    storage = _DummyStorage({
        str(user_id): {"timezone_mode": C.TIMEZONE_MODE_SERVER},
    })
    _seed_runtime(context, storage)

    reference_server_dt = datetime(2027, 5, 16, 11, 30, 0)
    original_now_server_naive = type_flow.now_server_naive
    type_flow.now_server_naive = lambda: reference_server_dt

    try:
        state = asyncio.run(type_flow.type_5_date(update, context, _show_multi_setting_menu))
    finally:
        type_flow.now_server_naive = original_now_server_naive

    replies = update.message.replies
    prompt_text = replies[0]["text"] if replies else ""
    today_prompt_events = [e for e in storage.events if e.get("event") == "one_time_today_year_required_prompt"]
    checks = {
        "returns_same_state": state == C.TYPE_5_DATE,
        "one_reply_sent": len(replies) == 1,
        "short_example_dynamic": "16/05/27" in prompt_text,
        "full_example_dynamic": "16/05/2027" in prompt_text,
        "prompt_format_hint_present": "DD/MM/YY" in prompt_text and "DD/MM/YYYY" in prompt_text,
        "date_not_set_on_needs_year": context.user_data["temp_alert"]["schedule"].get("date") is None,
        "event_logged_once": len(today_prompt_events) == 1,
        "event_has_examples": (
            len(today_prompt_events) == 1
            and today_prompt_events[0]["payload"].get("today_short_example") == "16/05/27"
            and today_prompt_events[0]["payload"].get("today_full_example") == "16/05/2027"
        ),
    }
    dbg.section("today_prompt_contract", {
        "checks": checks,
        "state": state,
        "prompt_text": prompt_text,
        "events": storage.events,
    })
    if not all(checks.values()):
        dbg.problem("one_time_date_prompt_contract_failed", {"checks": checks})


def _check_timezone_example_alignment(dbg, type_flow, C):
    reference_server_dt = datetime(2027, 5, 16, 0, 30, 0)
    server_prefs = {"timezone_mode": C.TIMEZONE_MODE_SERVER}
    user_prefs = {
        "timezone_mode": C.TIMEZONE_MODE_USER,
        "timezone": {"name": "America/Los_Angeles"},
    }

    server_short, server_full = type_flow._build_one_time_today_examples(reference_server_dt, server_prefs)
    user_short, user_full = type_flow._build_one_time_today_examples(reference_server_dt, user_prefs)

    checks = {
        "server_examples_match_server_day": server_short == "16/05/27" and server_full == "16/05/2027",
        "user_examples_match_user_day": user_short == "15/05/27" and user_full == "15/05/2027",
    }
    dbg.section("timezone_example_alignment", {
        "checks": checks,
        "server_examples": {"short": server_short, "full": server_full},
        "user_examples": {"short": user_short, "full": user_full},
    })
    if not all(checks.values()):
        dbg.problem("one_time_date_prompt_timezone_alignment_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules import constants as C
            from modules.handlers.add_flow import type_flow
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _check_today_prompt_contract(dbg, type_flow, C)
        _check_timezone_example_alignment(dbg, type_flow, C)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    contract_ok = not dbg.has_problem("one_time_date_prompt_contract_failed")
    tz_ok = not dbg.has_problem("one_time_date_prompt_timezone_alignment_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"prompt_contract: {'OK' if contract_ok else 'FAIL'}",
        f"timezone_alignment: {'OK' if tz_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
