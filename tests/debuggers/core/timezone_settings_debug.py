#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from datetime import timedelta
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
SCRIPT_TITLE = "timezone_settings_debug"
FEATURE_TITLE = "Timezone Settings"

_DBG = None


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _dbg():
    if _DBG is None:
        raise RuntimeError("debug harness not initialized")
    return _DBG


def print_section(label, payload):
    _dbg().section(label, payload)


def _log_problem(message, payload=None):
    _dbg().problem(message, payload or {})


def _extract_inline_labels(reply_markup):
    labels = []
    if not reply_markup:
        return labels
    for row in getattr(reply_markup, "inline_keyboard", []):
        for button in row:
            labels.append(getattr(button, "text", ""))
    return labels


class _FakeStorage:
    def __init__(self):
        self.events = []

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": str(user_id),
            "event_type": event_type,
            "payload": payload or {},
        })


class _DummyMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return True


class _DummyCallbackQuery:
    def __init__(self, data):
        self.data = data
        self.message = _DummyMessage()
        self.answer_calls = []

    async def answer(self, *args, **kwargs):
        self.answer_calls.append({"args": list(args), "kwargs": dict(kwargs)})
        return True


class _DummyUpdate:
    def __init__(self, *, user_id=1, callback_data=None):
        self.effective_user = SimpleNamespace(id=user_id)
        self.message = _DummyMessage() if callback_data is None else None
        self.callback_query = _DummyCallbackQuery(callback_data) if callback_data else None
        self.effective_message = self.callback_query.message if self.callback_query else self.message


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = dict(user_data or {})
        self.bot_data = {}
        self.bot = SimpleNamespace()


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules import constants as C
            from modules.handlers import base as base_handlers
            from modules.storage import StorageManager
            from modules.scheduler_core.coordinator import reschedule_user_alerts
            from modules.timezone_catalog import suggest_timezones
            from modules.timezone_geo import resolve_timezone_from_location
            from modules.timezone_utils import now_server_naive
            from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        original_mainbot = sys.modules.get("mainbot")
        had_mainbot = "mainbot" in sys.modules
        fake_storage = _FakeStorage()
        sys.modules["mainbot"] = SimpleNamespace(storage=fake_storage)

        try:
            timezone_labels = _extract_inline_labels(base_handlers.build_timezone_keyboard({}))
            timezone_keyboard_checks = {
                "has_back_label": "⬅️ Back" in timezone_labels,
                "plain_back_absent": "Back" not in timezone_labels,
            }
            print_section("timezone_keyboard_labels", {
                "labels": timezone_labels,
                "checks": timezone_keyboard_checks,
            })
            if not all(timezone_keyboard_checks.values()):
                _log_problem("timezone_keyboard_failed", {"checks": timezone_keyboard_checks})

            settings_update = _DummyUpdate(callback_data="settings_timezone_auto")
            settings_context = _DummyContext()
            _seed_runtime(settings_context, fake_storage)
            import asyncio
            asyncio.run(base_handlers.handle_settings_callback(settings_update, settings_context))
            prompt_reply = settings_update.callback_query.message.replies[-1] if settings_update.callback_query.message.replies else {}
            prompt_markup = prompt_reply.get("kwargs", {}).get("reply_markup")
            settings_prompt_checks = {
                "query_answered_once": len(settings_update.callback_query.answer_calls) == 1,
                "expecting_location_set": settings_context.user_data.get("expecting_timezone_location") is True,
                "reply_keyboard_present": isinstance(prompt_markup, ReplyKeyboardMarkup),
                "share_location_prompt_sent": "Share your location" in (prompt_reply.get("text") or ""),
                "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "timezone_auto_prompt",
            }
            print_section("timezone_auto_prompt", {
                "reply": prompt_reply,
                "checks": settings_prompt_checks,
            })
            if not all(settings_prompt_checks.values()):
                _log_problem("timezone_auto_prompt_failed", {"checks": settings_prompt_checks})

            cancel_update = _DummyUpdate()
            cancel_context = _DummyContext({"expecting_timezone_location": True})
            _seed_runtime(cancel_context, fake_storage)
            asyncio.run(base_handlers.cancel(cancel_update, cancel_context))
            cancel_reply = cancel_update.message.replies[-1] if cancel_update.message.replies else {}
            cancel_markup = cancel_reply.get("kwargs", {}).get("reply_markup")
            cancel_checks = {
                "cancel_message_sent": "Operation cancelled" in (cancel_reply.get("text") or ""),
                "reply_keyboard_removed": isinstance(cancel_markup, ReplyKeyboardRemove),
                "expecting_location_cleared": "expecting_timezone_location" not in cancel_context.user_data,
                "cancel_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "command_cancel",
            }
            print_section("timezone_cancel_cleanup", {
                "reply": cancel_reply,
                "checks": cancel_checks,
            })
            if not all(cancel_checks.values()):
                _log_problem("timezone_cancel_cleanup_failed", {"checks": cancel_checks})

            with tempfile.TemporaryDirectory() as tmpdir:
                cwd = os.getcwd()
                os.chdir(tmpdir)
                try:
                    storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=1)
                    user_id = 1

                    tomorrow = now_server_naive() + timedelta(days=1)
                    payload = {
                        "title": "TZ Test",
                        "type": 5,
                        "type_name": "One Time",
                        "schedule": {
                            "date": tomorrow.strftime("%d/%m/%Y"),
                            "time": "10:00",
                        },
                        "pre_alerts": [],
                        "tags": [],
                    }
                    alert_id = storage.save_alert(user_id, payload)
                    initial = storage.get_alert_by_id(user_id, alert_id)
                    initial_next = (initial or {}).get("next_scheduled")

                    storage.update_user_prefs(user_id, {
                        "timezone_mode": C.TIMEZONE_MODE_USER,
                        "timezone": {
                            "name": "America/New_York",
                            "source": C.TIMEZONE_SOURCE_MANUAL,
                            "state": "New York",
                        },
                    })

                    updated_count = reschedule_user_alerts(user_id, reason="debug", storage=storage)
                    updated = storage.get_alert_by_id(user_id, alert_id)
                    updated_next = (updated or {}).get("next_scheduled")

                    checks = {
                        "initial_next_set": bool(initial_next),
                        "updated_next_set": bool(updated_next),
                        "updated_count_positive": updated_count > 0,
                        "next_changed": bool(initial_next and updated_next and initial_next != updated_next),
                    }
                    print_section("reschedule_checks", {
                        "checks": checks,
                        "initial_next": initial_next,
                        "updated_next": updated_next,
                    })
                    if not all(checks.values()):
                        _log_problem("reschedule_failed", {"checks": checks})

                    suggestions = suggest_timezones("rome", limit=5)
                    print_section("suggestions", {"rome": suggestions})
                    if not suggestions or "Europe/Rome" not in suggestions:
                        _log_problem("suggest_failed", {"rome": suggestions})

                    tz_guess = resolve_timezone_from_location(41.9028, 12.4964)
                    print_section("location_lookup", {"rome": tz_guess})
                finally:
                    os.chdir(cwd)
        finally:
            if had_mainbot:
                sys.modules["mainbot"] = original_mainbot
            else:
                sys.modules.pop("mainbot", None)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    settings_ok = not dbg.has_problem(
        "suggest_failed",
        "reschedule_failed",
        "timezone_keyboard_failed",
        "timezone_auto_prompt_failed",
        "timezone_cancel_cleanup_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"settings: {'OK' if settings_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
