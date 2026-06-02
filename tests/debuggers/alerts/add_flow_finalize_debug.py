#!/usr/bin/env python3
import copy
import os
import sys
import types


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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "add_flow_finalize_debug"
FEATURE_TITLE = "Add Flow Finalization"


class _FakeStorage:
    def __init__(self, save_result="a100"):
        self.save_result = save_result
        self.save_calls = []
        self.download_calls = []
        self.prefs_calls = []

    async def download_image(self, _bot, user_id, image_id):
        self.download_calls.append({"user_id": user_id, "image_id": image_id})
        return "/tmp/fake_image.jpg"

    def save_alert(self, user_id, alert_data):
        self.save_calls.append({"user_id": user_id, "alert_data": copy.deepcopy(alert_data)})
        return self.save_result

    def get_user_prefs(self, user_id):
        self.prefs_calls.append(user_id)
        return {}


class _DummySentMessage:
    def __init__(self, message_id):
        self.message_id = message_id


class _DummyBot:
    def __init__(self):
        self.sent_messages = []
        self.deleted_messages = []
        self._next_message_id = 800

    async def send_message(self, chat_id, text, parse_mode=None):
        self._next_message_id += 1
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "message_id": self._next_message_id,
        })
        return _DummySentMessage(self._next_message_id)

    async def delete_message(self, chat_id, message_id):
        self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})


class _DummyMessage:
    def __init__(self, message_id=500, chat_id=42):
        self.message_id = message_id
        self.chat_id = chat_id
        self.photo = None


class _DummyCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        self.edits.append({
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyUpdate:
    def __init__(self, callback_query, user_id=42):
        self.callback_query = callback_query
        self.effective_user = _DummyUser(user_id)


class _DummyContext:
    def __init__(self, user_data, bot):
        self.user_data = user_data
        self.bot = bot
        self.bot_data = {}


def _seed_runtime(context, storage_obj):
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage_obj, api_failure_tracker=None),
    )


def _sample_temp_alert():
    return {
        "title": "Pay bills",
        "type": 1,
        "type_name": "Monthly (Specific Day)",
        "tags": ["🏠 Home"],
        "pre_alerts": [],
        "schedule": {
            "days": [1],
            "interval": 1,
            "time": "10:00",
        },
    }


def _install_fake_mainbot(storage_obj):
    original = sys.modules.get("mainbot")
    fake_module = types.ModuleType("mainbot")
    fake_module.storage = storage_obj
    sys.modules["mainbot"] = fake_module
    return original


def _restore_mainbot(original):
    if original is None:
        sys.modules.pop("mainbot", None)
    else:
        sys.modules["mainbot"] = original


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules import constants as C
            from modules.handlers import add_alert
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        # Case 1: tag DONE finalizes immediately without review step.
        storage_ok = _FakeStorage(save_result="a101")
        original_mainbot = _install_fake_mainbot(storage_ok)
        original_toggle_impl = add_alert._tags_toggle_impl
        try:
            async def _fake_tags_toggle_impl(update, context, next_func):
                context.user_data["temp_alert"]["tags"] = ["🏠 Home"]
                context.user_data["temp_selection"] = []
                return await next_func(update, context)

            add_alert._tags_toggle_impl = _fake_tags_toggle_impl
            bot = _DummyBot()
            user_data = {
                "temp_alert": _sample_temp_alert(),
                "temp_selection": ["🏠 Home"],
                "add_flow_message_ids": [300, 301, 302],
                "add_flow_start_message_id": 300,
            }
            context = _DummyContext(user_data=user_data, bot=bot)
            _seed_runtime(context, storage_ok)
            query = _DummyCallbackQuery("tag_DONE", _DummyMessage(message_id=450, chat_id=42))
            update = _DummyUpdate(query, user_id=42)
            state = run_async(add_alert.tags_toggle(update, context))
            checks = {
                "state_end": state == C.CONVERSATION_END if hasattr(C, "CONVERSATION_END") else state == -1,
                "saved_once": len(storage_ok.save_calls) == 1,
                "success_message_sent": any("Alert Saved Successfully!" in m["text"] for m in bot.sent_messages),
                "review_not_shown": not any("Review Alert" in m["text"] for m in bot.sent_messages),
                "temp_alert_cleared": "temp_alert" not in context.user_data,
            }
            dbg.section("immediate_finalize_after_tags", {
                "state": state,
                "sent_messages": bot.sent_messages,
                "checks": checks,
            })
            if not all(checks.values()):
                dbg.problem("immediate_finalize_after_tags_failed", {"checks": checks})
        finally:
            add_alert._tags_toggle_impl = original_toggle_impl
            _restore_mainbot(original_mainbot)

        # Case 2: save failure remains recoverable in direct post-tag save path.
        storage_fail = _FakeStorage(save_result=None)
        original_mainbot = _install_fake_mainbot(storage_fail)
        try:
            bot = _DummyBot()
            user_data = {
                "temp_alert": _sample_temp_alert(),
                "temp_selection": [],
            }
            context = _DummyContext(user_data=user_data, bot=bot)
            _seed_runtime(context, storage_fail)
            query = _DummyCallbackQuery("tag_DONE", _DummyMessage(message_id=451, chat_id=42))
            update = _DummyUpdate(query, user_id=42)
            state = run_async(add_alert.save_after_tags(update, context))
            checks = {
                "state_recoverable_get_tags": state == C.GET_TAGS,
                "temp_alert_still_present": "temp_alert" in context.user_data,
                "tags_rehydrated_for_retry": context.user_data.get("temp_selection") == ["🏠 Home"],
                "save_attempted_once": len(storage_fail.save_calls) == 1,
                "error_retry_message_sent": any("Press `DONE` again to retry" in m["text"] for m in bot.sent_messages),
            }
            dbg.section("save_failure_recoverable", {
                "state": state,
                "sent_messages": bot.sent_messages,
                "checks": checks,
            })
            if not all(checks.values()):
                dbg.problem("save_failure_recoverable_failed", {"checks": checks})
        finally:
            _restore_mainbot(original_mainbot)

        # Case 3: duplicate-save guard blocks re-entry when already in progress.
        storage_guard = _FakeStorage(save_result="a202")
        original_mainbot = _install_fake_mainbot(storage_guard)
        try:
            bot = _DummyBot()
            user_data = {
                "temp_alert": _sample_temp_alert(),
                "add_flow_save_in_progress": True,
            }
            context = _DummyContext(user_data=user_data, bot=bot)
            _seed_runtime(context, storage_guard)
            query = _DummyCallbackQuery("tag_DONE", _DummyMessage(message_id=452, chat_id=42))
            update = _DummyUpdate(query, user_id=42)
            state = run_async(add_alert.save_after_tags(update, context))
            checks = {
                "state_get_tags": state == C.GET_TAGS,
                "save_not_called": len(storage_guard.save_calls) == 0,
                "temp_alert_preserved": "temp_alert" in context.user_data,
            }
            dbg.section("duplicate_save_guard", {"state": state, "checks": checks})
            if not all(checks.values()):
                dbg.problem("duplicate_save_guard_failed", {"checks": checks})
        finally:
            _restore_mainbot(original_mainbot)

        # Case 4: legacy confirmation state is no longer wired in the active conversation.
        states = getattr(add_alert.add_alert_handler, "states", {}) or {}
        checks = {
            "confirmation_state_removed": C.CONFIRMATION not in states,
        }
        dbg.section("legacy_confirmation_state_removed", {"checks": checks})
        if not all(checks.values()):
            dbg.problem("legacy_confirmation_state_removed_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    immediate_ok = not dbg.has_problem("immediate_finalize_after_tags_failed")
    recoverable_ok = not dbg.has_problem("save_failure_recoverable_failed")
    guard_ok = not dbg.has_problem("duplicate_save_guard_failed")
    legacy_removed_ok = not dbg.has_problem("legacy_confirmation_state_removed_failed")
    dbg.finish(summary_lines=[
        f"immediate_finalize: {'OK' if immediate_ok else 'FAIL'}",
        f"save_failure_recoverable: {'OK' if recoverable_ok else 'FAIL'}",
        f"duplicate_save_guard: {'OK' if guard_ok else 'FAIL'}",
        f"legacy_confirmation_state_removed: {'OK' if legacy_removed_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
