#!/usr/bin/env python3
import asyncio
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
SCRIPT_TITLE = "backup_email_input_debug"
FEATURE_TITLE = "Backup Email Input"


class _FakeStorage:
    def __init__(self):
        self.events = []
        self._prefs = {}

    def get_backup_prefs(self, user_id):
        return self._prefs.get(str(user_id), {
            "email_enabled": False,
            "email_address": None,
            "email_frequency": "monthly",
            "last_email_sent": None,
            "email_reminder_disabled": False,
            "last_email_reminder_sent": None,
        })

    def update_backup_prefs(self, user_id, updates, ensure_space=True):
        merged = dict(self.get_backup_prefs(user_id))
        merged.update(updates or {})
        self._prefs[str(user_id)] = merged
        return merged

    def log_user_event(self, user_id, event_type, payload):
        self.events.append({
            "user_id": str(user_id),
            "event_type": event_type,
            "payload": payload or {},
        })


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return self


class _DummyUpdate:
    def __init__(self, user_id, text):
        self.effective_user = _DummyUser(user_id)
        self.message = _DummyMessage(text)
        self.effective_message = self.message
        self.callback_query = None


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = dict(user_data or {})
        self.bot_data = {}


def _run(coro, stop_cls):
    try:
        asyncio.run(coro)
    except stop_cls:
        return True
    return False


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            import mainbot
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        fake_storage = _FakeStorage()
        runtime_snapshot = snapshot_mainbot_runtime(mainbot)

        try:
            update = _DummyUpdate(user_id=1001, text="test😀@example.com")
            context = _DummyContext(user_data={"expecting_backup_email": True})
            seed_mainbot_runtime(mainbot, app=context, storage=fake_storage)
            stopped = _run(mainbot.global_text_handler(update, context), mainbot.ApplicationHandlerStop)

            reply_text = update.message.replies[-1]["text"] if update.message.replies else ""
            event = fake_storage.events[-1] if fake_storage.events else {}
            payload = event.get("payload") or {}
            email_meta = payload.get("email_meta") or {}
            checks = {
                "stopped": stopped is True,
                "reply_invalid": "Invalid email" in reply_text,
                "event_logged": event.get("event_type") == "backup_email_invalid_input",
                "email_meta_len": email_meta.get("len") == len("test😀@example.com"),
                "email_meta_hash": bool(email_meta.get("hash")),
                "flow_flag_kept": context.user_data.get("expecting_backup_email") is True,
            }
            dbg.section("invalid_email_input", {
                "reply_text": reply_text,
                "event": event,
                "checks": checks,
            })
            if not all(checks.values()):
                dbg.problem("invalid_email_input_failed", {"checks": checks, "event": event})
        finally:
            restore_mainbot_runtime(mainbot, runtime_snapshot)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    ok = not dbg.has_problem("invalid_email_input_failed", "unhandled_exception")
    dbg.finish(summary_lines=[f"input: {'OK' if ok else 'FAIL'}"], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
