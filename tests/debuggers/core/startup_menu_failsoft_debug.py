#!/usr/bin/env python3
import asyncio
import inspect
import os
import sys


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
from _lib.runtime import restore_mainbot_runtime, seed_mainbot_runtime, snapshot_mainbot_runtime
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "startup_menu_failsoft_debug"
FEATURE_TITLE = "Startup Menu Fail-Soft"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _DummyMessage:
    def __init__(self, message_id=1):
        self.message_id = message_id


class _DummyStorage:
    def get_all_users(self):
        return []

    def get_active_alerts(self, user_id):
        return []

    def log_user_event(self, user_id, event, payload):
        return True


def _build_bot_class(mainbot, mode):
    class _DummyBot:
        def __init__(self):
            self.set_calls = 0
            self.command_calls = []

        async def set_my_commands(self, commands, scope=None, **kwargs):
            self.set_calls += 1
            names = [getattr(c, "command", None) for c in (commands or [])]
            self.command_calls.append({
                "commands": names,
                "scope_chat_id": getattr(scope, "chat_id", None),
            })
            if mode == "retryable":
                raise mainbot.TimedOut("simulated timeout")
            if mode == "fatal":
                raise ValueError("simulated fatal")
            return True

        async def send_message(self, chat_id, text, **kwargs):
            return _DummyMessage(10)

        async def send_photo(self, chat_id, photo, caption=None, **kwargs):
            return _DummyMessage(11)

        async def send_document(self, chat_id, document, caption=None, **kwargs):
            return _DummyMessage(12)

        async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
            return _DummyMessage(13)

        async def edit_message_caption(self, chat_id=None, message_id=None, inline_message_id=None, caption=None, **kwargs):
            return _DummyMessage(14)

        async def edit_message_reply_markup(self, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
            return _DummyMessage(15)

    return _DummyBot


def _run_post_init_case(mainbot, mode, scoped_targets=([], [])):
    events = []
    calls = {"scheduler_start": 0}

    original_log_system = mainbot.log_system
    original_log_downtime = mainbot.log_downtime_summary
    original_start_scheduler = mainbot.scheduler.start_scheduler
    runtime_snapshot = snapshot_mainbot_runtime(mainbot)
    original_retry_max_window = mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS
    original_retry_base_delay = mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS
    original_retry_max_delay = mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS
    original_target_resolver = getattr(mainbot, "_get_scoped_command_targets", None)

    def _fake_log(category, event, payload=None, level="INFO"):
        events.append({
            "category": category,
            "event": event,
            "payload": payload or {},
            "level": level,
        })

    async def _fake_start_scheduler():
        calls["scheduler_start"] += 1

    try:
        mainbot.log_system = _fake_log
        mainbot.log_downtime_summary = lambda: None
        mainbot.scheduler.start_scheduler = _fake_start_scheduler
        runtime_storage = _DummyStorage()
        runtime_tracker = mainbot.ApiFailureTracker(
            window_seconds=60,
            user_threshold=2,
            global_threshold=3,
        )
        # Keep retries fast and deterministic in debugger.
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = 1
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = 0.01
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = 0.02
        if callable(original_target_resolver):
            mainbot._get_scoped_command_targets = lambda: scoped_targets

        BotCls = _build_bot_class(mainbot, mode)
        app = type("_DummyApp", (), {"bot": BotCls(), "bot_data": {}})()
        seed_mainbot_runtime(
            mainbot,
            app=app,
            storage=runtime_storage,
            api_failure_tracker=runtime_tracker,
        )
        raised = None
        try:
            asyncio.run(mainbot.post_init(app))
        except Exception as exc:
            raised = exc

        return {
            "events": events,
            "calls": calls,
            "raised": raised,
            "set_calls": app.bot.set_calls,
            "command_calls": app.bot.command_calls,
        }
    finally:
        mainbot.log_system = original_log_system
        mainbot.log_downtime_summary = original_log_downtime
        mainbot.scheduler.start_scheduler = original_start_scheduler
        restore_mainbot_runtime(mainbot, runtime_snapshot)
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = original_retry_max_window
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = original_retry_base_delay
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = original_retry_max_delay
        if callable(original_target_resolver):
            mainbot._get_scoped_command_targets = original_target_resolver


def _has_event(case, event_name):
    return any(item.get("event") == event_name for item in case.get("events", []))


def _event_level(case, event_name):
    for item in case.get("events", []):
        if item.get("event") == event_name:
            return item.get("level")
    return None


def _test_retryable_failsoft(dbg, mainbot):
    case = _run_post_init_case(mainbot, "retryable")
    checks = {
        "no_exception": case["raised"] is None,
        "scheduler_started": case["calls"].get("scheduler_start") == 1,
        "set_called_retries": case["set_calls"] == int(mainbot.C.TELEGRAM_RETRY_ATTEMPTS),
        "failure_event_logged": _has_event(case, "set_my_commands_failed"),
        "failure_level_warning": _event_level(case, "set_my_commands_failed") == "WARNING",
        "success_event_not_logged": not _has_event(case, "set_my_commands"),
    }
    dbg.section("retryable_failsoft", {
        "checks": checks,
        "set_calls": case["set_calls"],
        "raised": str(case["raised"]) if case["raised"] else None,
    })
    if not all(checks.values()):
        dbg.problem("startup_menu_retryable_failsoft_failed", {
            "checks": checks,
            "set_calls": case["set_calls"],
            "raised": str(case["raised"]) if case["raised"] else None,
        })


def _test_fatal_propagates(dbg, mainbot):
    case = _run_post_init_case(mainbot, "fatal")
    checks = {
        "exception_raised": isinstance(case["raised"], ValueError),
        "scheduler_not_started": case["calls"].get("scheduler_start") == 0,
        "failure_event_logged": _has_event(case, "set_my_commands_failed"),
        "failure_level_error": _event_level(case, "set_my_commands_failed") == "ERROR",
    }
    dbg.section("fatal_propagates", {
        "checks": checks,
        "set_calls": case["set_calls"],
        "raised": str(case["raised"]) if case["raised"] else None,
    })
    if not all(checks.values()):
        dbg.problem("startup_menu_fatal_propagation_failed", {
            "checks": checks,
            "set_calls": case["set_calls"],
            "raised": str(case["raised"]) if case["raised"] else None,
        })


def _test_post_init_order(dbg, mainbot):
    source = inspect.getsource(mainbot.post_init)
    idx_install = source.find("_install_bot_api_wrappers(application)")
    idx_retry = source.find('_run_api_with_retry(')
    idx_raw_set = source.find("application.bot.set_my_commands(commands)")
    checks = {
        "installer_present": idx_install >= 0,
        "retry_path_present": idx_retry >= 0 and idx_raw_set >= 0,
        "installer_before_retry": idx_install >= 0 and idx_retry >= 0 and idx_install < idx_retry,
    }
    dbg.section("post_init_order", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("startup_menu_post_init_order_failed", {"checks": checks})


def _find_scoped_event(case):
    for item in case.get("events", []):
        if item.get("event") == "set_my_commands_scoped":
            return item
    return None


def _has_manage(call):
    return "manage" in (call.get("commands") or [])


def _test_scoped_command_visibility(dbg, mainbot):
    case = _run_post_init_case(mainbot, "ok", scoped_targets=([111], [222]))
    command_calls = case.get("command_calls") or []
    global_calls = [c for c in command_calls if c.get("scope_chat_id") is None]
    scoped_priv = [c for c in command_calls if c.get("scope_chat_id") == 111]
    scoped_std = [c for c in command_calls if c.get("scope_chat_id") == 222]
    scoped_event = _find_scoped_event(case)
    checks = {
        "no_exception": case["raised"] is None,
        "scheduler_started": case["calls"].get("scheduler_start") == 1,
        "set_calls_global_plus_scoped": case["set_calls"] == 3,
        "global_no_manage": len(global_calls) == 1 and not _has_manage(global_calls[0]),
        "privileged_has_manage": len(scoped_priv) == 1 and _has_manage(scoped_priv[0]),
        "standard_no_manage": len(scoped_std) == 1 and not _has_manage(scoped_std[0]),
        "scoped_event_logged": scoped_event is not None,
        "scoped_counts_logged": (
            scoped_event is not None
            and scoped_event.get("payload", {}).get("targets") == 2
            and scoped_event.get("payload", {}).get("privileged_targets") == 1
            and scoped_event.get("payload", {}).get("standard_targets") == 1
            and scoped_event.get("payload", {}).get("failed") == 0
        ),
    }
    dbg.section("scoped_command_visibility", {
        "checks": checks,
        "set_calls": case["set_calls"],
        "command_calls": command_calls,
        "scoped_event": scoped_event,
    })
    if not all(checks.values()):
        dbg.problem("startup_menu_scoped_visibility_failed", {
            "checks": checks,
            "set_calls": case["set_calls"],
            "command_calls": command_calls,
            "scoped_event": scoped_event,
        })


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
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_retryable_failsoft(dbg, mainbot)
        _test_fatal_propagates(dbg, mainbot)
        _test_post_init_order(dbg, mainbot)
        _test_scoped_command_visibility(dbg, mainbot)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    retryable_ok = not dbg.has_problem("startup_menu_retryable_failsoft_failed")
    fatal_ok = not dbg.has_problem("startup_menu_fatal_propagation_failed")
    order_ok = not dbg.has_problem("startup_menu_post_init_order_failed")
    scoped_ok = not dbg.has_problem("startup_menu_scoped_visibility_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"retryable_failsoft: {'OK' if retryable_ok else 'FAIL'}",
        f"fatal_propagation: {'OK' if fatal_ok else 'FAIL'}",
        f"order: {'OK' if order_ok else 'FAIL'}",
        f"scoped_visibility: {'OK' if scoped_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
