#!/usr/bin/env python3
import asyncio
import ast
import inspect
import os
import sys
from collections import defaultdict


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
SCRIPT_TITLE = "api_timeout_coverage_debug"
FEATURE_TITLE = "API Timeout Coverage"

TARGET_METHODS = {
    "send_document",
    "edit_message_caption",
    "edit_message_reply_markup",
}


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
    def __init__(self):
        self.events = []

    def log_user_event(self, user_id, event, payload):
        self.events.append({
            "user_id": str(user_id),
            "event": event,
            "payload": payload or {},
        })
        return True

    def get_all_users(self):
        return []

    def get_active_alerts(self, user_id):
        return []


def _extract_required_methods(mainbot):
    source = inspect.getsource(mainbot._install_bot_api_wrappers)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "required_methods":
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        values = []
        for item in node.value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.append(item.value)
        return set(values)
    return set()


def _post_init_uses_retry_for_commands(mainbot):
    source = inspect.getsource(mainbot.post_init)
    tree = ast.parse(source)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        if not isinstance(call.func, ast.Name) or call.func.id != "_run_api_with_retry":
            continue
        if not call.args:
            continue
        first = call.args[0]
        if isinstance(first, ast.Constant) and first.value == "set_my_commands":
            found = True
            break
    return found


def _build_retry_bot(mainbot, retryable_failures=2):
    class _RetryBot:
        def __init__(self):
            self.calls = defaultdict(int)

        async def set_my_commands(self, commands, scope=None, **kwargs):
            self.calls["set_my_commands"] += 1
            return True

        async def send_message(self, chat_id, text, **kwargs):
            self.calls["send_message"] += 1
            return _DummyMessage(10)

        async def send_photo(self, chat_id, photo, caption=None, **kwargs):
            self.calls["send_photo"] += 1
            return _DummyMessage(11)

        async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
            self.calls["edit_message_text"] += 1
            return _DummyMessage(12)

        async def send_document(self, chat_id, document, caption=None, **kwargs):
            self.calls["send_document"] += 1
            if self.calls["send_document"] <= retryable_failures:
                raise mainbot.TimedOut("simulated document timeout")
            return _DummyMessage(13)

        async def edit_message_caption(self, chat_id=None, message_id=None, inline_message_id=None, caption=None, **kwargs):
            self.calls["edit_message_caption"] += 1
            if self.calls["edit_message_caption"] <= retryable_failures:
                raise mainbot.TimedOut("simulated caption timeout")
            return _DummyMessage(14)

        async def edit_message_reply_markup(self, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
            self.calls["edit_message_reply_markup"] += 1
            if self.calls["edit_message_reply_markup"] <= retryable_failures:
                raise mainbot.TimedOut("simulated markup timeout")
            return _DummyMessage(15)

    return _RetryBot


def _build_fatal_bot():
    class _FatalBot:
        def __init__(self):
            self.calls = defaultdict(int)

        async def set_my_commands(self, commands, scope=None, **kwargs):
            self.calls["set_my_commands"] += 1
            return True

        async def send_message(self, chat_id, text, **kwargs):
            self.calls["send_message"] += 1
            return _DummyMessage(20)

        async def send_photo(self, chat_id, photo, caption=None, **kwargs):
            self.calls["send_photo"] += 1
            return _DummyMessage(21)

        async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
            self.calls["edit_message_text"] += 1
            return _DummyMessage(22)

        async def send_document(self, chat_id, document, caption=None, **kwargs):
            self.calls["send_document"] += 1
            raise ValueError("simulated fatal send_document")

        async def edit_message_caption(self, chat_id=None, message_id=None, inline_message_id=None, caption=None, **kwargs):
            self.calls["edit_message_caption"] += 1
            return _DummyMessage(24)

        async def edit_message_reply_markup(self, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
            self.calls["edit_message_reply_markup"] += 1
            return _DummyMessage(25)

    return _FatalBot


def _build_not_modified_bot(mainbot):
    from modules.telegram_resilience import BadRequest as ResilienceBadRequest

    class _NotModifiedBot:
        def __init__(self):
            self.calls = defaultdict(int)

        async def set_my_commands(self, commands, scope=None, **kwargs):
            self.calls["set_my_commands"] += 1
            return True

        async def send_message(self, chat_id, text, **kwargs):
            self.calls["send_message"] += 1
            return _DummyMessage(40)

        async def send_photo(self, chat_id, photo, caption=None, **kwargs):
            self.calls["send_photo"] += 1
            return _DummyMessage(41)

        async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
            self.calls["edit_message_text"] += 1
            raise ResilienceBadRequest("Message is not modified: specified new message content")

        async def send_document(self, chat_id, document, caption=None, **kwargs):
            self.calls["send_document"] += 1
            return _DummyMessage(43)

        async def edit_message_caption(self, chat_id=None, message_id=None, inline_message_id=None, caption=None, **kwargs):
            self.calls["edit_message_caption"] += 1
            return _DummyMessage(44)

        async def edit_message_reply_markup(self, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
            self.calls["edit_message_reply_markup"] += 1
            return _DummyMessage(45)

    return _NotModifiedBot


def _build_startup_bot(mainbot, mode):
    class _StartupBot:
        def __init__(self):
            self.calls = defaultdict(int)

        async def set_my_commands(self, commands, scope=None, **kwargs):
            self.calls["set_my_commands"] += 1
            if mode == "retryable":
                raise mainbot.TimedOut("simulated startup timeout")
            if mode == "fatal":
                raise ValueError("simulated startup fatal")
            return True

        async def send_message(self, chat_id, text, **kwargs):
            self.calls["send_message"] += 1
            return _DummyMessage(30)

        async def send_photo(self, chat_id, photo, caption=None, **kwargs):
            self.calls["send_photo"] += 1
            return _DummyMessage(31)

        async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
            self.calls["edit_message_text"] += 1
            return _DummyMessage(32)

        async def send_document(self, chat_id, document, caption=None, **kwargs):
            self.calls["send_document"] += 1
            return _DummyMessage(33)

        async def edit_message_caption(self, chat_id=None, message_id=None, inline_message_id=None, caption=None, **kwargs):
            self.calls["edit_message_caption"] += 1
            return _DummyMessage(34)

        async def edit_message_reply_markup(self, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
            self.calls["edit_message_reply_markup"] += 1
            return _DummyMessage(35)

    return _StartupBot


def _event_filter(events, event_name):
    return [item for item in events if item.get("event") == event_name]


def _test_static_coverage(dbg, mainbot):
    required_methods = _extract_required_methods(mainbot)
    checks = {
        "target_methods_present": TARGET_METHODS.issubset(required_methods),
        "post_init_retry_path": _post_init_uses_retry_for_commands(mainbot),
    }
    dbg.section("static_coverage", {
        "checks": checks,
        "required_methods": sorted(required_methods),
    })
    if not all(checks.values()):
        dbg.problem("api_timeout_static_coverage_failed", {
            "checks": checks,
            "required_methods": sorted(required_methods),
        })


def _test_runtime_retry_paths(dbg, mainbot):
    events = []
    original_log_system = mainbot.log_system
    runtime_snapshot = snapshot_mainbot_runtime(mainbot)
    original_retry_attempts = mainbot.C.TELEGRAM_RETRY_ATTEMPTS
    original_retry_window = mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS
    original_retry_base = mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS
    original_retry_max = mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS
    original_api_slow_threshold = getattr(mainbot.C, "API_SLOW_CALL_THRESHOLD_MS", 2000)
    def _fake_log(category, event, payload=None, level="INFO"):
        events.append({
            "category": category,
            "event": event,
            "payload": payload or {},
            "level": level,
        })

    async def _runner(bot):
        await bot.send_document(111, object(), caption="doc cap")
        await bot.edit_message_caption(chat_id=111, message_id=99, caption="caption")
        await bot.edit_message_reply_markup(chat_id=111, message_id=99, reply_markup=None)

    try:
        mainbot.log_system = _fake_log
        runtime_storage = _DummyStorage()
        runtime_tracker = mainbot.ApiFailureTracker(
            window_seconds=120,
            user_threshold=2,
            global_threshold=3,
        )
        mainbot.C.TELEGRAM_RETRY_ATTEMPTS = 3
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = 2
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = 0.01
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = 0.02
        mainbot.C.API_SLOW_CALL_THRESHOLD_MS = 1

        BotCls = _build_retry_bot(mainbot, retryable_failures=2)
        app = type("_RetryApp", (), {"bot": BotCls(), "bot_data": {}})()
        seed_mainbot_runtime(
            mainbot,
            app=app,
            storage=runtime_storage,
            api_failure_tracker=runtime_tracker,
        )
        mainbot._install_bot_api_wrappers(app)
        asyncio.run(_runner(app.bot))

        wrapper_checks = {}
        for method in TARGET_METHODS:
            wrapped = getattr(type(app.bot), method)
            wrapper_checks[f"{method}_wrapped"] = bool(getattr(wrapped, "_resilience_wrapper", False))

        attempts_checks = {
            "send_document_attempts": app.bot.calls["send_document"] == 3,
            "edit_message_caption_attempts": app.bot.calls["edit_message_caption"] == 3,
            "edit_message_reply_markup_attempts": app.bot.calls["edit_message_reply_markup"] == 3,
        }

        retry_failures = _event_filter(events, "telegram_call_attempt_failed")
        retry_scheduled = _event_filter(events, "telegram_retry_scheduled")
        failures_by_op = {
            op: sum(
                1
                for item in retry_failures
                if item.get("payload", {}).get("operation") == op
            )
            for op in TARGET_METHODS
        }
        scheduled_by_op = {
            op: sum(
                1
                for item in retry_scheduled
                if item.get("payload", {}).get("operation") == op
            )
            for op in TARGET_METHODS
        }
        retryable_classification_ok = all(
            item.get("payload", {}).get("operation") in TARGET_METHODS
            and item.get("payload", {}).get("retryable") is True
            and item.get("payload", {}).get("counts_toward_degraded") is True
            and item.get("level") == "WARNING"
            for item in retry_failures
        )
        event_checks = {
            "attempt_failed_count": all(v == 2 for v in failures_by_op.values()),
            "retry_scheduled_count": all(v == 2 for v in scheduled_by_op.values()),
            "retryable_classification": retryable_classification_ok,
            "success_events": all(
                len(_event_filter(events, op)) >= 1
                and _event_filter(events, op)[-1].get("payload", {}).get("ok") is True
                for op in TARGET_METHODS
            ),
            "no_target_failed_events": (
                len(_event_filter(events, "send_document_failed")) == 0
                and len(_event_filter(events, "edit_message_caption_failed")) == 0
                and len(_event_filter(events, "edit_message_reply_markup_failed")) == 0
            ),
            "slow_event_emitted_for_targets": all(
                any(
                    item.get("payload", {}).get("operation") == op
                    and item.get("level") == "WARNING"
                    for item in _event_filter(events, "api_call_slow")
                )
                for op in TARGET_METHODS
            ),
        }

        checks = {}
        checks.update(wrapper_checks)
        checks.update(attempts_checks)
        checks.update(event_checks)

        dbg.section("runtime_retry_paths", {
            "checks": checks,
            "attempts": dict(app.bot.calls),
            "failures_by_op": failures_by_op,
            "scheduled_by_op": scheduled_by_op,
        })
        if not all(checks.values()):
            dbg.problem("api_timeout_runtime_retry_failed", {
                "checks": checks,
                "attempts": dict(app.bot.calls),
                "failures_by_op": failures_by_op,
                "scheduled_by_op": scheduled_by_op,
            })
    finally:
        mainbot.log_system = original_log_system
        restore_mainbot_runtime(mainbot, runtime_snapshot)
        mainbot.C.TELEGRAM_RETRY_ATTEMPTS = original_retry_attempts
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = original_retry_window
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = original_retry_base
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = original_retry_max
        mainbot.C.API_SLOW_CALL_THRESHOLD_MS = original_api_slow_threshold


def _test_runtime_non_retryable_classification(dbg, mainbot):
    events = []
    original_log_system = mainbot.log_system
    runtime_snapshot = snapshot_mainbot_runtime(mainbot)
    original_retry_attempts = mainbot.C.TELEGRAM_RETRY_ATTEMPTS
    original_retry_window = mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS
    original_retry_base = mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS
    original_retry_max = mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS

    def _fake_log(category, event, payload=None, level="INFO"):
        events.append({
            "category": category,
            "event": event,
            "payload": payload or {},
            "level": level,
        })

    async def _runner(bot):
        await bot.send_document(222, object(), caption="fatal")

    raised = None
    try:
        mainbot.log_system = _fake_log
        runtime_storage = _DummyStorage()
        runtime_tracker = mainbot.ApiFailureTracker(
            window_seconds=120,
            user_threshold=2,
            global_threshold=3,
        )
        mainbot.C.TELEGRAM_RETRY_ATTEMPTS = 3
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = 2
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = 0.01
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = 0.02

        BotCls = _build_fatal_bot()
        app = type("_FatalApp", (), {"bot": BotCls(), "bot_data": {}})()
        seed_mainbot_runtime(
            mainbot,
            app=app,
            storage=runtime_storage,
            api_failure_tracker=runtime_tracker,
        )
        mainbot._install_bot_api_wrappers(app)
        try:
            asyncio.run(_runner(app.bot))
        except Exception as exc:
            raised = exc

        attempt_failed = _event_filter(events, "telegram_call_attempt_failed")
        degraded_on_events = _event_filter(events, "api_degraded_mode_on")
        degraded_off_events = _event_filter(events, "api_degraded_mode_off")
        checks = {
            "raised_value_error": isinstance(raised, ValueError),
            "single_attempt": app.bot.calls["send_document"] == 1,
            "single_attempt_failed_event": len(attempt_failed) == 1,
            "non_retryable_flag": (
                len(attempt_failed) == 1
                and attempt_failed[0].get("payload", {}).get("retryable") is False
            ),
            "non_retryable_not_counted": (
                len(attempt_failed) == 1
                and attempt_failed[0].get("payload", {}).get("counts_toward_degraded") is False
            ),
            "non_retryable_level_error": (
                len(attempt_failed) == 1
                and attempt_failed[0].get("level") == "ERROR"
            ),
            "degraded_counters_unchanged": (
                len(attempt_failed) == 1
                and attempt_failed[0].get("payload", {}).get("degraded", {}).get("user_failures") == 0
                and attempt_failed[0].get("payload", {}).get("degraded", {}).get("global_failures") == 0
            ),
            "no_degraded_transition_events": len(degraded_on_events) == 0 and len(degraded_off_events) == 0,
            "no_retry_scheduled": len(_event_filter(events, "telegram_retry_scheduled")) == 0,
            "method_failed_event_present": len(_event_filter(events, "send_document_failed")) == 1,
        }

        dbg.section("runtime_non_retryable", {
            "checks": checks,
            "attempts": dict(app.bot.calls),
            "raised": str(raised) if raised else None,
        })
        if not all(checks.values()):
            dbg.problem("api_timeout_non_retryable_failed", {
                "checks": checks,
                "attempts": dict(app.bot.calls),
                "raised": str(raised) if raised else None,
            })
    finally:
        mainbot.log_system = original_log_system
        restore_mainbot_runtime(mainbot, runtime_snapshot)
        mainbot.C.TELEGRAM_RETRY_ATTEMPTS = original_retry_attempts
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = original_retry_window
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = original_retry_base
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = original_retry_max


def _test_edit_message_text_noop(dbg, mainbot):
    events = []
    original_log_system = mainbot.log_system
    runtime_snapshot = snapshot_mainbot_runtime(mainbot)
    original_retry_attempts = mainbot.C.TELEGRAM_RETRY_ATTEMPTS
    original_retry_window = mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS
    original_retry_base = mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS
    original_retry_max = mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS

    def _fake_log(category, event, payload=None, level="INFO"):
        events.append({
            "category": category,
            "event": event,
            "payload": payload or {},
            "level": level,
        })

    async def _runner(bot):
        return await bot.edit_message_text("same text", chat_id=555, message_id=77)

    raised = None
    result = None
    runtime_storage = None
    try:
        mainbot.log_system = _fake_log
        runtime_storage = _DummyStorage()
        runtime_tracker = mainbot.ApiFailureTracker(
            window_seconds=120,
            user_threshold=2,
            global_threshold=3,
        )
        mainbot.C.TELEGRAM_RETRY_ATTEMPTS = 3
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = 2
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = 0.01
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = 0.02

        BotCls = _build_not_modified_bot(mainbot)
        app = type("_NotModifiedApp", (), {"bot": BotCls(), "bot_data": {}})()
        seed_mainbot_runtime(
            mainbot,
            app=app,
            storage=runtime_storage,
            api_failure_tracker=runtime_tracker,
        )
        mainbot._install_bot_api_wrappers(app)
        try:
            result = asyncio.run(_runner(app.bot))
        except Exception as exc:
            raised = exc

        attempt_noop = [
            item for item in _event_filter(events, "telegram_call_attempt_noop")
            if item.get("payload", {}).get("operation") == "edit_message_text"
        ]
        attempt_failed = [
            item for item in _event_filter(events, "telegram_call_attempt_failed")
            if item.get("payload", {}).get("operation") == "edit_message_text"
        ]
        retry_scheduled = [
            item for item in _event_filter(events, "telegram_retry_scheduled")
            if item.get("payload", {}).get("operation") == "edit_message_text"
        ]
        wrapper_noop = _event_filter(events, "edit_message_text_noop")
        wrapper_failed = _event_filter(events, "edit_message_text_failed")
        final_event = _event_filter(events, "edit_message_text")
        user_noop_events = [
            item for item in (runtime_storage.events if hasattr(runtime_storage, "events") else [])
            if item.get("event") == "bot_message_edit_noop"
        ]
        user_edited_events = [
            item for item in (runtime_storage.events if hasattr(runtime_storage, "events") else [])
            if item.get("event") == "bot_message_edited"
        ]

        checks = {
            "no_exception_raised": raised is None,
            "single_attempt_only": app.bot.calls["edit_message_text"] == 1,
            "attempt_noop_once": len(attempt_noop) == 1,
            "attempt_noop_info_level": len(attempt_noop) == 1 and attempt_noop[0].get("level") == "INFO",
            "attempt_noop_reason": len(attempt_noop) == 1 and attempt_noop[0].get("payload", {}).get("reason_code") == "message_not_modified",
            "attempt_noop_not_counted": len(attempt_noop) == 1 and attempt_noop[0].get("payload", {}).get("counts_toward_degraded") is False,
            "no_attempt_failed": len(attempt_failed) == 0,
            "no_retry_scheduled": len(retry_scheduled) == 0,
            "wrapper_noop_once": len(wrapper_noop) == 1,
            "wrapper_no_failure_event": len(wrapper_failed) == 0,
            "final_ok_true": len(final_event) >= 1 and final_event[-1].get("payload", {}).get("ok") is True,
            "final_reason_code": len(final_event) >= 1 and final_event[-1].get("payload", {}).get("reason_code") == "message_not_modified",
            "returned_message_id": getattr(result, "message_id", None) == 77,
            "user_noop_event_logged": len(user_noop_events) == 1,
            "user_edited_event_skipped": len(user_edited_events) == 0,
        }

        dbg.section("edit_message_text_noop", {
            "checks": checks,
            "attempts": dict(app.bot.calls),
            "raised": str(raised) if raised else None,
            "result_message_id": getattr(result, "message_id", None),
        })
        if not all(checks.values()):
            dbg.problem("api_timeout_edit_message_text_noop_failed", {
                "checks": checks,
                "attempts": dict(app.bot.calls),
                "raised": str(raised) if raised else None,
                "result_message_id": getattr(result, "message_id", None),
            })
    finally:
        mainbot.log_system = original_log_system
        restore_mainbot_runtime(mainbot, runtime_snapshot)
        mainbot.C.TELEGRAM_RETRY_ATTEMPTS = original_retry_attempts
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = original_retry_window
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = original_retry_base
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = original_retry_max


def _run_post_init_case(mainbot, mode):
    events = []
    calls = {"scheduler_start": 0}
    raised = None

    original_log_system = mainbot.log_system
    original_log_downtime = mainbot.log_downtime_summary
    original_start_scheduler = mainbot.scheduler.start_scheduler
    runtime_snapshot = snapshot_mainbot_runtime(mainbot)
    original_retry_attempts = mainbot.C.TELEGRAM_RETRY_ATTEMPTS
    original_retry_window = mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS
    original_retry_base = mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS
    original_retry_max = mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS
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
        mainbot.C.TELEGRAM_RETRY_ATTEMPTS = 3
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = 1
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = 0.01
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = 0.02
        if callable(original_target_resolver):
            mainbot._get_scoped_command_targets = lambda: ([], [])

        BotCls = _build_startup_bot(mainbot, mode)
        app = type("_StartupApp", (), {"bot": BotCls(), "bot_data": {}})()
        seed_mainbot_runtime(
            mainbot,
            app=app,
            storage=runtime_storage,
            api_failure_tracker=runtime_tracker,
        )

        try:
            asyncio.run(mainbot.post_init(app))
        except Exception as exc:
            raised = exc

        return {
            "events": events,
            "calls": calls,
            "raised": raised,
            "set_calls": app.bot.calls["set_my_commands"],
        }
    finally:
        mainbot.log_system = original_log_system
        mainbot.log_downtime_summary = original_log_downtime
        mainbot.scheduler.start_scheduler = original_start_scheduler
        restore_mainbot_runtime(mainbot, runtime_snapshot)
        mainbot.C.TELEGRAM_RETRY_ATTEMPTS = original_retry_attempts
        mainbot.C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS = original_retry_window
        mainbot.C.TELEGRAM_RETRY_BASE_DELAY_SECONDS = original_retry_base
        mainbot.C.TELEGRAM_RETRY_MAX_DELAY_SECONDS = original_retry_max
        if callable(original_target_resolver):
            mainbot._get_scoped_command_targets = original_target_resolver


def _test_startup_failsoft(dbg, mainbot):
    retryable_case = _run_post_init_case(mainbot, "retryable")
    fatal_case = _run_post_init_case(mainbot, "fatal")

    retryable_events = _event_filter(retryable_case["events"], "set_my_commands_failed")
    fatal_events = _event_filter(fatal_case["events"], "set_my_commands_failed")

    checks = {
        "retryable_no_exception": retryable_case["raised"] is None,
        "retryable_scheduler_started": retryable_case["calls"]["scheduler_start"] == 1,
        "retryable_exhausted_attempts": retryable_case["set_calls"] == 3,
        "retryable_failure_warning": (
            len(retryable_events) >= 1
            and retryable_events[-1].get("level") == "WARNING"
            and retryable_events[-1].get("payload", {}).get("retryable") is True
        ),
        "fatal_exception_raised": isinstance(fatal_case["raised"], ValueError),
        "fatal_scheduler_not_started": fatal_case["calls"]["scheduler_start"] == 0,
        "fatal_single_attempt": fatal_case["set_calls"] == 1,
        "fatal_failure_error": (
            len(fatal_events) >= 1
            and fatal_events[-1].get("level") == "ERROR"
            and fatal_events[-1].get("payload", {}).get("retryable") is False
        ),
    }

    dbg.section("startup_failsoft", {
        "checks": checks,
        "retryable_set_calls": retryable_case["set_calls"],
        "fatal_set_calls": fatal_case["set_calls"],
        "retryable_raised": str(retryable_case["raised"]) if retryable_case["raised"] else None,
        "fatal_raised": str(fatal_case["raised"]) if fatal_case["raised"] else None,
    })
    if not all(checks.values()):
        dbg.problem("api_timeout_startup_failsoft_failed", {
            "checks": checks,
            "retryable_set_calls": retryable_case["set_calls"],
            "fatal_set_calls": fatal_case["set_calls"],
            "retryable_raised": str(retryable_case["raised"]) if retryable_case["raised"] else None,
            "fatal_raised": str(fatal_case["raised"]) if fatal_case["raised"] else None,
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

        _test_static_coverage(dbg, mainbot)
        _test_runtime_retry_paths(dbg, mainbot)
        _test_runtime_non_retryable_classification(dbg, mainbot)
        _test_edit_message_text_noop(dbg, mainbot)
        _test_startup_failsoft(dbg, mainbot)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    static_ok = not dbg.has_problem("api_timeout_static_coverage_failed")
    retry_ok = not dbg.has_problem("api_timeout_runtime_retry_failed")
    non_retry_ok = not dbg.has_problem("api_timeout_non_retryable_failed")
    noop_ok = not dbg.has_problem("api_timeout_edit_message_text_noop_failed")
    startup_ok = not dbg.has_problem("api_timeout_startup_failsoft_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"static: {'OK' if static_ok else 'FAIL'}",
        f"retryable_runtime: {'OK' if retry_ok else 'FAIL'}",
        f"non_retryable_runtime: {'OK' if non_retry_ok else 'FAIL'}",
        f"edit_text_noop: {'OK' if noop_ok else 'FAIL'}",
        f"startup_failsoft: {'OK' if startup_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
