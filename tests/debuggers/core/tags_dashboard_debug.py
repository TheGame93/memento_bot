#!/usr/bin/env python3
import asyncio
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
from _lib.runtime import seed_mainbot_runtime
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "tags_dashboard_debug"
FEATURE_TITLE = "Tags Dashboard"


class _FakeStorage:
    def __init__(self, payload):
        self._payload = payload
        self.events = []

    def get_all_alerts(self, user_id):
        return self._payload

    def get_user_tags(self, user_id):
        return list(self._payload.get("tags", []))

    def setup_user_space(self, user_id):
        return True

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
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


class _DummyUpdate:
    def __init__(self, user_id):
        self.effective_user = _DummyUser(user_id)
        self.message = _DummyMessage()
        self.callback_query = None
        self.effective_message = self.message


class _DummyCallbackQuery:
    def __init__(self):
        self.message = _DummyMessage()

    async def edit_message_text(self, text, **kwargs):
        self.message.replies.append({"text": text, "kwargs": kwargs})


class _DummyCallbackUpdate:
    def __init__(self, user_id):
        self.effective_user = _DummyUser(user_id)
        self.callback_query = _DummyCallbackQuery()
        self.message = None
        self.effective_message = self.callback_query.message


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


def _extract_untagged_lines(text):
    lines = []
    for line in (text or "").splitlines():
        if "Untagged:" in line:
            lines.append(line.strip())
    return lines


def _run_token_map_sort_check(dbg, tags_handlers):
    # Input in emoji-Unicode order (🔥 before 🏠 by codepoint, fire < house).
    # Expected output: values ordered by name (home < spicy alphabetically).
    token_map = tags_handlers._build_tag_token_map(["🔥 Spicy", "🏠 Home"])
    values = list(token_map.values())
    checks = {
        "both_present": "🔥 Spicy" in values and "🏠 Home" in values,
        "home_before_spicy": (
            "🏠 Home" in values and "🔥 Spicy" in values
            and values.index("🏠 Home") < values.index("🔥 Spicy")
        ),
    }
    dbg.section("token_map_sort", {"checks": checks, "values": values})
    if not all(checks.values()):
        dbg.problem("token_map_sort_failed", {"checks": checks})


def _run_orphan_sort_check(dbg, tags_handlers):
    # Master list has only "🏠 Home"; alert carries orphan "🔥 Spicy".
    # Expected display: Home listed before Spicy (alphabetical by name).
    orphan_payload = {
        "tags": ["🏠 Home"],
        "alerts": [{"type": 1, "tags": ["🔥 Spicy"]}],
    }
    orphan_storage = _FakeStorage(orphan_payload)
    original_mainbot = sys.modules.get("mainbot")
    had_mainbot = "mainbot" in sys.modules
    runtime_mainbot = types.SimpleNamespace(storage=orphan_storage, API_FAILURE_TRACKER=None)
    sys.modules["mainbot"] = runtime_mainbot
    try:
        update = _DummyUpdate(user_id=43)
        context = _DummyContext()
        seed_mainbot_runtime(runtime_mainbot, app=context, storage=orphan_storage)
        asyncio.run(tags_handlers.tags_dashboard_start(update, context))
        reply = update.message.replies[-1] if update.message.replies else {}
        text = reply.get("text") or ""
        checks = {
            "home_in_text": "Home" in text,
            "spicy_in_text": "Spicy" in text,
            "home_before_spicy": (
                "Home" in text and "Spicy" in text
                and text.index("Home") < text.index("Spicy")
            ),
        }
        dbg.section("orphan_sort", {"checks": checks, "text": text})
        if not all(checks.values()):
            dbg.problem("orphan_sort_failed", {"checks": checks})
    finally:
        if had_mainbot:
            sys.modules["mainbot"] = original_mainbot
        else:
            sys.modules.pop("mainbot", None)


def _extract_button_labels(reply_markup):
    labels = []
    if not reply_markup:
        return labels
    for row in getattr(reply_markup, "inline_keyboard", []):
        for button in row:
            labels.append(getattr(button, "text", ""))
    return labels


def _run_action_menu_sort_checks(dbg, tags_handlers):
    payload = {
        "tags": ["🔥 Spicy", "🏠 Home", "😀 Alpha"],
        "alerts": [],
    }
    menu_storage = _FakeStorage(payload)
    original_mainbot = sys.modules.get("mainbot")
    had_mainbot = "mainbot" in sys.modules
    runtime_mainbot = types.SimpleNamespace(storage=menu_storage, API_FAILURE_TRACKER=None)
    sys.modules["mainbot"] = runtime_mainbot
    try:
        context = _DummyContext()
        seed_mainbot_runtime(runtime_mainbot, app=context, storage=menu_storage)

        delete_update = _DummyCallbackUpdate(user_id=44)
        asyncio.run(tags_handlers.show_delete_menu(delete_update, context))
        delete_reply = delete_update.callback_query.message.replies[-1] if delete_update.callback_query.message.replies else {}
        delete_labels = [
            label for label in _extract_button_labels(delete_reply.get("kwargs", {}).get("reply_markup"))
            if label.startswith("❌ ")
        ]

        edit_update = _DummyCallbackUpdate(user_id=44)
        asyncio.run(tags_handlers.show_edit_menu(edit_update, context))
        edit_reply = edit_update.callback_query.message.replies[-1] if edit_update.callback_query.message.replies else {}
        edit_labels = [
            label for label in _extract_button_labels(edit_reply.get("kwargs", {}).get("reply_markup"))
            if label.startswith("✏️ ")
        ]

        expected_delete = ["❌ 😀 Alpha", "❌ 🏠 Home", "❌ 🔥 Spicy"]
        expected_edit = ["✏️ 😀 Alpha", "✏️ 🏠 Home", "✏️ 🔥 Spicy"]
        checks = {
            "delete_order": delete_labels == expected_delete,
            "edit_order": edit_labels == expected_edit,
            "delete_token_map_preserved": list((context.user_data.get("tag_delete_token_map") or {}).values()) == payload["tags"][:0] + ["😀 Alpha", "🏠 Home", "🔥 Spicy"],
            "edit_token_map_preserved": list((context.user_data.get("tag_edit_token_map") or {}).values()) == payload["tags"][:0] + ["😀 Alpha", "🏠 Home", "🔥 Spicy"],
        }
        dbg.section("action_menu_sort", {
            "checks": checks,
            "delete_labels": delete_labels,
            "edit_labels": edit_labels,
        })
        if not all(checks.values()):
            dbg.problem("action_menu_sort_failed", {"checks": checks})
    finally:
        if had_mainbot:
            sys.modules["mainbot"] = original_mainbot
        else:
            sys.modules.pop("mainbot", None)


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.handlers import tags_dashboard as tags_handlers
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        payload = {
            "tags": ["Work"],
            "alerts": [
                {"type": 1, "tags": []},
                {"type": 6, "tags": []},
                {"type": 1, "tags": ["Work"]},
            ],
        }
        fake_storage = _FakeStorage(payload)
        original_mainbot = sys.modules.get("mainbot")
        had_mainbot = "mainbot" in sys.modules
        runtime_mainbot = types.SimpleNamespace(storage=fake_storage, API_FAILURE_TRACKER=None)
        sys.modules["mainbot"] = runtime_mainbot

        try:
            update = _DummyUpdate(user_id=42)
            context = _DummyContext()
            seed_mainbot_runtime(runtime_mainbot, app=context, storage=fake_storage)
            asyncio.run(tags_handlers.tags_dashboard_start(update, context))
            reply = update.message.replies[-1] if update.message.replies else {}
            text = reply.get("text") or ""
            untagged_lines = _extract_untagged_lines(text)
            expected_line = "Untagged: <b>1</b> alerts, <b>1</b> bdays"
            checks = {
                "has_reply": bool(reply),
                "single_untagged_line": len(untagged_lines) == 1,
                "line_matches": untagged_lines[0] == expected_line if untagged_lines else False,
                "line_ascii_only": all(ord(ch) < 128 for ch in untagged_lines[0]) if untagged_lines else False,
                "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "tags_dashboard_opened",
            }
            dbg.section("untagged_line_checks", {
                "text": text,
                "untagged_lines": untagged_lines,
                "expected_line": expected_line,
                "checks": checks,
            })
            if not all(checks.values()):
                dbg.problem("tags_dashboard_untagged_failed", {"checks": checks})
        finally:
            if had_mainbot:
                sys.modules["mainbot"] = original_mainbot
            else:
                sys.modules.pop("mainbot", None)

        _run_token_map_sort_check(dbg, tags_handlers)
        _run_orphan_sort_check(dbg, tags_handlers)
        _run_action_menu_sort_checks(dbg, tags_handlers)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    untagged_ok = not dbg.has_problem("tags_dashboard_untagged_failed")
    token_map_ok = not dbg.has_problem("token_map_sort_failed")
    orphan_ok = not dbg.has_problem("orphan_sort_failed")
    action_menu_ok = not dbg.has_problem("action_menu_sort_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"untagged: {'OK' if untagged_ok else 'FAIL'}",
        f"token_map_sort: {'OK' if token_map_ok else 'FAIL'}",
        f"orphan_sort: {'OK' if orphan_ok else 'FAIL'}",
        f"action_menu_sort: {'OK' if action_menu_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
