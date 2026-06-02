#!/usr/bin/env python3
import asyncio
import inspect
import os
import re
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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "text_handler_stop_debug"
FEATURE_TITLE = "Text Handler Stop Propagation"


class _DummyMessage:
    def __init__(self, text=None):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return self


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})
        return True


class _DummyChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _DummyCallbackQuery:
    def __init__(self):
        self.message = type("_Msg", (), {"photo": None})()
        self.answers = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})
        return True

    async def edit_message_text(self, text, **kwargs):
        raise RuntimeError("edit_message_text failed")

    async def edit_message_caption(self, caption, **kwargs):
        raise RuntimeError("edit_message_caption failed")


class _DummyUpdate:
    def __init__(self, text=None, with_callback=False):
        self.message = _DummyMessage(text=text) if text is not None else None
        self.effective_message = self.message
        self.effective_chat = _DummyChat(42)
        self.callback_query = _DummyCallbackQuery() if with_callback else None


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot = _DummyBot()
        self.args = []


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

        try:
            from modules.shared.context_cleanup import EXPIRED_FLOW_TEXT, require_temp_alert
            from telegram.ext import ConversationHandler
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        # Check 1: ApplicationHandlerStop import.
        has_import = hasattr(mainbot, "ApplicationHandlerStop")
        dbg.section("import_check", {"has_import": has_import})
        if not has_import:
            dbg.problem("import_missing", {"hint": "ApplicationHandlerStop not in mainbot namespace"})

        # Check 2: global_text_handler source analysis.
        source = inspect.getsource(mainbot.global_text_handler)
        stop_count = source.count("ApplicationHandlerStop")
        min_expected = 10
        dbg.section("stop_usage_check", {
            "stop_count": stop_count,
            "min_expected": min_expected,
        })
        if stop_count < min_expected:
            dbg.problem("insufficient_stop_usage", {
                "stop_count": stop_count,
                "min_expected": min_expected,
            })

        # Check 2b: orphan text fallback guidance is present.
        has_orphan_fallback = "No text input is pending" in source
        dbg.section("orphan_fallback_source", {"has_orphan_fallback": has_orphan_fallback})
        if not has_orphan_fallback:
            dbg.problem("orphan_fallback_missing", {
                "hint": "global_text_handler should explicitly reply to orphan text after interruption",
            })

        # Check 3: handler group verification.
        mainbot_path = os.path.join(ROOT_DIR, "mainbot.py")
        with open(mainbot_path, "r", encoding="utf-8") as handle:
            full_source = handle.read()
        pattern = r"app\.add_handler\(.*global_text_handler.*group\s*=\s*(-?\d+)"
        match = re.search(pattern, full_source)
        group_num = int(match.group(1)) if match else None
        correct_group = group_num == -1
        dbg.section("handler_group_check", {
            "detected_group": group_num,
            "correct": correct_group,
        })
        if not correct_group:
            dbg.problem("wrong_handler_group", {"detected_group": group_num, "expected": -1})

        # Check 4: deferred returns for search+temp_alert conflict.
        lines = source.split("\n")
        deferred_problems = []
        in_search_conflict = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if "expecting_birthday_search" in stripped and "temp_alert" in stripped:
                in_search_conflict = True
                continue
            if "expecting_alert_search" in stripped and "temp_alert" in stripped:
                in_search_conflict = True
                continue
            if in_search_conflict:
                if "ApplicationHandlerStop" in stripped:
                    in_search_conflict = False
                    continue
                if stripped == "return":
                    deferred_problems.append(f"bare return at source line ~{idx + 1}")
                    in_search_conflict = False
                    continue
                if stripped and not stripped.startswith("#"):
                    in_search_conflict = False

        dbg.section("deferred_return_check", {
            "problems": deferred_problems,
            "ok": len(deferred_problems) == 0,
        })
        if deferred_problems:
            dbg.problem("deferred_return_raises_stop", {
                "hint": "Search+temp_alert conflict branches should raise ApplicationHandlerStop",
                "problems": deferred_problems,
            })

        # Check 5: runtime orphan text should stop propagation with guidance.
        orphan_update = _DummyUpdate(text="hello")
        orphan_context = _DummyContext()
        orphan_stopped = _run(
            mainbot.global_text_handler(orphan_update, orphan_context),
            mainbot.ApplicationHandlerStop,
        )
        orphan_reply = orphan_update.message.replies[-1]["text"] if orphan_update.message.replies else ""
        orphan_checks = {
            "stopped": orphan_stopped,
            "reply_sent": bool(orphan_update.message.replies),
            "reply_mentions_restart": "/alerts" in orphan_reply and "/cancel" in orphan_reply,
        }
        dbg.section("orphan_runtime_check", {"checks": orphan_checks, "reply": orphan_reply})
        if not all(orphan_checks.values()):
            dbg.problem("orphan_runtime_failed", {"checks": orphan_checks, "reply": orphan_reply})

        # Check 6: require_temp_alert fallback should still reply if message edit fails.
        @require_temp_alert
        async def _dummy_add_flow_handler(update, context):
            return "unexpected"

        stale_update = _DummyUpdate(with_callback=True)
        stale_context = _DummyContext()
        stale_context.user_data["expecting_edit_text"] = True
        stale_result = asyncio.run(_dummy_add_flow_handler(stale_update, stale_context))
        stale_text = stale_context.bot.sent[-1]["text"] if stale_context.bot.sent else ""
        stale_checks = {
            "conversation_ended": stale_result == ConversationHandler.END,
            "fallback_sent": bool(stale_context.bot.sent),
            "fallback_text_matches": stale_text == EXPIRED_FLOW_TEXT,
            "context_cleared": "expecting_edit_text" not in stale_context.user_data,
        }
        dbg.section("stale_callback_fallback_check", {
            "checks": stale_checks,
            "bot_sent": stale_context.bot.sent,
        })
        if not all(stale_checks.values()):
            dbg.problem("stale_callback_fallback_failed", {"checks": stale_checks})
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    import_ok = not dbg.has_problem("import_missing")
    group_ok = not dbg.has_problem("wrong_handler_group")
    stop_ok = not dbg.has_problem("insufficient_stop_usage")
    deferred_ok = not dbg.has_problem("deferred_return_raises_stop")
    orphan_ok = not dbg.has_problem("orphan_fallback_missing", "orphan_runtime_failed")
    stale_ok = not dbg.has_problem("stale_callback_fallback_failed")
    dbg.finish(summary_lines=[
        f"import: {'OK' if import_ok else 'FAIL'}",
        f"group: {'OK' if group_ok else 'FAIL'}",
        f"stop_count: {'OK' if stop_ok else 'FAIL'}",
        f"deferred: {'OK' if deferred_ok else 'FAIL'}",
        f"orphan_fallback: {'OK' if orphan_ok else 'FAIL'}",
        f"stale_callback: {'OK' if stale_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
