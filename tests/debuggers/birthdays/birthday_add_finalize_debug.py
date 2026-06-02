#!/usr/bin/env python3
import copy
import logging
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
SCRIPT_TITLE = "birthday_add_finalize_debug"
FEATURE_TITLE = "Birthday Add Finalization"


class _FakeStorage:
    def __init__(self, save_result="b101"):
        self.save_result = save_result
        self.save_calls = []

    def save_alert(self, user_id, alert_data):
        self.save_calls.append({"user_id": user_id, "alert_data": copy.deepcopy(alert_data)})
        return self.save_result


class _DummyMessage:
    def __init__(self, message_id=600, chat_id=77):
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


class _FailingCallbackQuery(_DummyCallbackQuery):
    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        raise RuntimeError("edit failed")


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyUpdate:
    def __init__(self, callback_query, user_id=77):
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


class _DummyBot:
    def __init__(self):
        self.sent_messages = []
        self._next_message_id = 900

    async def send_message(self, chat_id, text, parse_mode=None):
        self._next_message_id += 1
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "message_id": self._next_message_id,
        })
        return types.SimpleNamespace(message_id=self._next_message_id)


class _FailingBot(_DummyBot):
    async def send_message(self, chat_id, text, parse_mode=None):
        raise RuntimeError("send failed")


def _sample_birthday_alert():
    return {
        "title": "Alice Example",
        "type": 6,
        "type_name": "Birthday",
        "tags": ["👨‍👩‍👧 Family"],
        "pre_alerts": [],
        "additional_info": "",
        "schedule": {"date": "12/03", "time": "8:00"},
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
            from modules.handlers.birthday_flow import flow
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return
        logging.getLogger("modules.handlers.birthday_flow.flow").setLevel(logging.CRITICAL)

        # Case 1: tag DONE finalizes immediately (no review step).
        storage_ok = _FakeStorage(save_result="b201")
        original_mainbot = _install_fake_mainbot(storage_ok)
        try:
            bot = _DummyBot()
            user_data = {
                "temp_alert": _sample_birthday_alert(),
                "temp_selection": ["👨‍👩‍👧 Family"],
            }
            context = _DummyContext(user_data=user_data, bot=bot)
            _seed_runtime(context, storage_ok)
            query = _DummyCallbackQuery("btag_DONE", _DummyMessage(message_id=610, chat_id=77))
            update = _DummyUpdate(query, user_id=77)
            state = run_async(flow.birthday_tags_toggle(update, context))
            checks = {
                "state_end": state == -1,
                "saved_once": len(storage_ok.save_calls) == 1,
                "edited_success": bool(query.edits and "Birthday Saved Successfully!" in query.edits[-1]["text"]),
                "review_not_shown": not any("Review Birthday" in e["text"] for e in query.edits),
                "temp_alert_cleared": "temp_alert" not in context.user_data,
            }
            dbg.section("immediate_finalize_after_tags", {
                "state": state,
                "checks": checks,
                "edits": query.edits,
                "sent_messages": bot.sent_messages,
            })
            if not all(checks.values()):
                dbg.problem("immediate_finalize_after_tags_failed", {"checks": checks})
        finally:
            _restore_mainbot(original_mainbot)

        # Case 2: save failure remains recoverable in direct post-tag save path.
        storage_fail = _FakeStorage(save_result=None)
        original_mainbot = _install_fake_mainbot(storage_fail)
        try:
            bot = _DummyBot()
            user_data = {
                "temp_alert": _sample_birthday_alert(),
                "temp_selection": [],
            }
            context = _DummyContext(user_data=user_data, bot=bot)
            _seed_runtime(context, storage_fail)
            query = _DummyCallbackQuery("btag_DONE", _DummyMessage(message_id=611, chat_id=77))
            update = _DummyUpdate(query, user_id=77)
            state = run_async(flow.birthday_save_after_tags(update, context))
            checks = {
                "state_recoverable_get_tags": state == C.GET_TAGS,
                "temp_alert_still_present": "temp_alert" in context.user_data,
                "tags_rehydrated_for_retry": context.user_data.get("temp_selection") == ["👨‍👩‍👧 Family"],
                "save_attempted_once": len(storage_fail.save_calls) == 1,
                "error_retry_message_sent": any("Press `DONE` again to retry" in m["text"] for m in bot.sent_messages),
            }
            dbg.section("save_failure_recoverable", {
                "state": state,
                "checks": checks,
                "edits": query.edits,
                "sent_messages": bot.sent_messages,
            })
            if not all(checks.values()):
                dbg.problem("save_failure_recoverable_failed", {"checks": checks})
        finally:
            _restore_mainbot(original_mainbot)

        # Case 3: duplicate-save guard blocks re-entry.
        storage_guard = _FakeStorage(save_result="b301")
        original_mainbot = _install_fake_mainbot(storage_guard)
        try:
            bot = _DummyBot()
            user_data = {
                "temp_alert": _sample_birthday_alert(),
                "birthday_save_in_progress": True,
            }
            context = _DummyContext(user_data=user_data, bot=bot)
            _seed_runtime(context, storage_guard)
            query = _DummyCallbackQuery("btag_DONE", _DummyMessage(message_id=612, chat_id=77))
            update = _DummyUpdate(query, user_id=77)
            state = run_async(flow.birthday_save_after_tags(update, context))
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

        # Case 4: if persistence succeeds but delivery fails, flow still ends and clears state.
        storage_delivery_fail = _FakeStorage(save_result="b401")
        original_mainbot = _install_fake_mainbot(storage_delivery_fail)
        try:
            bot = _FailingBot()
            user_data = {
                "temp_alert": _sample_birthday_alert(),
                "temp_selection": ["👨‍👩‍👧 Family"],
            }
            context = _DummyContext(user_data=user_data, bot=bot)
            _seed_runtime(context, storage_delivery_fail)
            query = _FailingCallbackQuery("btag_DONE", _DummyMessage(message_id=613, chat_id=77))
            update = _DummyUpdate(query, user_id=77)
            state = run_async(flow.birthday_tags_toggle(update, context))
            checks = {
                "state_end": state == -1,
                "saved_once": len(storage_delivery_fail.save_calls) == 1,
                "temp_alert_cleared": "temp_alert" not in context.user_data,
            }
            dbg.section("delivery_failure_after_save", {"state": state, "checks": checks})
            if not all(checks.values()):
                dbg.problem("delivery_failure_after_save_failed", {"checks": checks})
        finally:
            _restore_mainbot(original_mainbot)

        # Case 5: legacy confirmation state is no longer wired in the active conversation.
        states = getattr(flow.birthday_add_handler, "states", {}) or {}
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
    delivery_fail_ok = not dbg.has_problem("delivery_failure_after_save_failed")
    legacy_removed_ok = not dbg.has_problem("legacy_confirmation_state_removed_failed")
    dbg.finish(summary_lines=[
        f"immediate_finalize: {'OK' if immediate_ok else 'FAIL'}",
        f"save_failure_recoverable: {'OK' if recoverable_ok else 'FAIL'}",
        f"duplicate_save_guard: {'OK' if guard_ok else 'FAIL'}",
        f"delivery_failure_after_save: {'OK' if delivery_fail_ok else 'FAIL'}",
        f"legacy_confirmation_state_removed: {'OK' if legacy_removed_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
