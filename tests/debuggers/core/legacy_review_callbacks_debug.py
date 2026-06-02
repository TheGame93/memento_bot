#!/usr/bin/env python3
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
from _lib.runtime import run_async
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "legacy_review_callbacks_debug"
FEATURE_TITLE = "Legacy Review Callback Fallback"


class _DummyMessage:
    def __init__(self, message_id=100, has_photo=False):
        self.message_id = message_id
        self.photo = [object()] if has_photo else None


class _DummyUser:
    def __init__(self, user_id=123):
        self.id = user_id


class _DummyCallbackQuery:
    def __init__(self, data, message, fail_edits=False):
        self.data = data
        self.message = message
        self.fail_edits = fail_edits
        self.answers = []
        self.edits_text = []
        self.edits_caption = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        if self.fail_edits:
            raise RuntimeError("edit text failed")
        self.edits_text.append({
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })

    async def edit_message_caption(self, caption, parse_mode=None, reply_markup=None):
        if self.fail_edits:
            raise RuntimeError("edit caption failed")
        self.edits_caption.append({
            "caption": caption,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })


class _DummyUpdate:
    def __init__(self, callback_query, user_id=123):
        self.callback_query = callback_query
        self.effective_user = _DummyUser(user_id)


class _DummyBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        })


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot = _DummyBot()


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        suppress_ptb_user_warning()
        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.handlers.add_alert import (
                LEGACY_REVIEW_CALLBACK_PATTERN,
                handle_legacy_review_callback,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        # Check 1: text-message legacy save callback is answered and edited in place.
        ctx1 = _DummyContext()
        q1 = _DummyCallbackQuery("save", _DummyMessage(has_photo=False))
        run_async(handle_legacy_review_callback(_DummyUpdate(q1, user_id=501), ctx1))
        checks1 = {
            "answered": bool(q1.answers),
            "answer_alert": bool(q1.answers and q1.answers[-1].get("show_alert") is True),
            "edited_text": bool(q1.edits_text),
            "no_fallback_send": len(ctx1.bot.sent_messages) == 0,
        }
        dbg.section("text_callback_path", {"checks": checks1, "answers": q1.answers, "edits_text": q1.edits_text})
        if not all(checks1.values()):
            dbg.problem("text_callback_path_failed", {"checks": checks1})

        # Check 2: photo-message legacy callback uses caption edit path.
        ctx2 = _DummyContext()
        q2 = _DummyCallbackQuery("bday_discard", _DummyMessage(has_photo=True))
        run_async(handle_legacy_review_callback(_DummyUpdate(q2, user_id=502), ctx2))
        checks2 = {
            "answered": bool(q2.answers),
            "edited_caption": bool(q2.edits_caption),
            "no_fallback_send": len(ctx2.bot.sent_messages) == 0,
        }
        dbg.section("photo_callback_path", {"checks": checks2, "answers": q2.answers, "edits_caption": q2.edits_caption})
        if not all(checks2.values()):
            dbg.problem("photo_callback_path_failed", {"checks": checks2})

        # Check 3: when message edit fails, fallback send is used.
        ctx3 = _DummyContext()
        q3 = _DummyCallbackQuery("discard", _DummyMessage(has_photo=False), fail_edits=True)
        run_async(handle_legacy_review_callback(_DummyUpdate(q3, user_id=503), ctx3))
        checks3 = {
            "answered": bool(q3.answers),
            "fallback_sent": len(ctx3.bot.sent_messages) == 1,
            "fallback_to_actor": bool(ctx3.bot.sent_messages and ctx3.bot.sent_messages[0]["chat_id"] == 503),
        }
        dbg.section("fallback_send_path", {"checks": checks3, "answers": q3.answers, "sent_messages": ctx3.bot.sent_messages})
        if not all(checks3.values()):
            dbg.problem("fallback_send_path_failed", {"checks": checks3})

        # Check 4: callback pattern remains strict and complete.
        expected_pattern = r"^(save|discard|bday_save|bday_discard)$"
        checks4 = {"pattern_expected": LEGACY_REVIEW_CALLBACK_PATTERN == expected_pattern}
        dbg.section("pattern_contract", {"checks": checks4, "pattern": LEGACY_REVIEW_CALLBACK_PATTERN})
        if not all(checks4.values()):
            dbg.problem("pattern_contract_failed", {"checks": checks4, "pattern": LEGACY_REVIEW_CALLBACK_PATTERN})
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    text_ok = not dbg.has_problem("text_callback_path_failed")
    photo_ok = not dbg.has_problem("photo_callback_path_failed")
    fallback_ok = not dbg.has_problem("fallback_send_path_failed")
    pattern_ok = not dbg.has_problem("pattern_contract_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"text_path: {'OK' if text_ok else 'FAIL'}",
        f"photo_path: {'OK' if photo_ok else 'FAIL'}",
        f"fallback_path: {'OK' if fallback_ok else 'FAIL'}",
        f"pattern_contract: {'OK' if pattern_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
