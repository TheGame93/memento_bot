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
from _lib.runtime import run_async
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "menu_markdown_guard_debug"
FEATURE_TITLE = "Menu Markdown Guard"
_ACTIVE_RUNTIME_STORAGE = None


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _StorageStub:
    def __init__(self, payload):
        global _ACTIVE_RUNTIME_STORAGE
        self._payload = payload
        self.events = []
        _ACTIVE_RUNTIME_STORAGE = self

    def get_all_alerts(self, _user_id):
        return dict(self._payload)

    def setup_user_space(self, _user_id):
        return True

    def get_user_tags(self, _user_id):
        tags = self._payload.get("tags")
        if isinstance(tags, list):
            return list(tags)
        return []

    def get_user_prefs(self, _user_id):
        return {}

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": str(user_id),
            "event": event_type,
            "payload": payload or {},
        })
        return True


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self, fail_markdown_once=False):
        self.fail_markdown_once = bool(fail_markdown_once)
        self.failed_markdown = False
        self.calls = []
        self.replies = []

    async def reply_text(self, text, **kwargs):
        parse_mode = kwargs.get("parse_mode")
        call = {
            "text": text,
            "parse_mode": parse_mode,
            "has_reply_markup": bool(kwargs.get("reply_markup")),
            "reply_markup": kwargs.get("reply_markup"),
        }
        self.calls.append(call)
        if self.fail_markdown_once and (not self.failed_markdown) and str(parse_mode) == "Markdown":
            from telegram.error import BadRequest
            self.failed_markdown = True
            raise BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 47")
        self.replies.append(call)
        return types.SimpleNamespace(message_id=100 + len(self.replies))


class _DummyUpdate:
    def __init__(self, user_id, message=None, callback_query=None):
        self.effective_user = _DummyUser(user_id)
        self.message = message
        self.callback_query = callback_query
        self.effective_message = message or getattr(callback_query, "message", None)


class _DummyCallbackMessage:
    def __init__(self):
        self.deleted = 0

    async def delete(self):
        self.deleted += 1


class _DummyCallbackQuery:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _DummyCallbackMessage()
        self.answers = []
        self.answer_count = 0

    async def answer(self, *args, **kwargs):
        self.answer_count += 1
        self.answers.append({"args": args, "kwargs": kwargs})


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.args = []
        self.bot = _DummyBot()
        self.bot_data = {}
        if _ACTIVE_RUNTIME_STORAGE is not None:
            _seed_runtime(self, _ACTIVE_RUNTIME_STORAGE)


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": kwargs.get("parse_mode"),
            "reply_markup": kwargs.get("reply_markup"),
        })
        return types.SimpleNamespace(message_id=500 + len(self.sent))


class _MainbotPatch:
    def __init__(self, storage):
        self.storage = storage
        self._had_mainbot = False
        self._original_mainbot = None

    def __enter__(self):
        self._had_mainbot = "mainbot" in sys.modules
        self._original_mainbot = sys.modules.get("mainbot")
        sys.modules["mainbot"] = types.SimpleNamespace(storage=self.storage)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._had_mainbot:
            sys.modules["mainbot"] = self._original_mainbot
        else:
            sys.modules.pop("mainbot", None)


def _has_event(storage, name):
    for item in storage.events:
        if item.get("event") == name:
            return True
    return False


def _button_labels(markup):
    rows = getattr(markup, "inline_keyboard", []) if markup else []
    return [btn.text for row in rows for btn in row]


def _button_rows(markup):
    rows = getattr(markup, "inline_keyboard", []) if markup else []
    return [[btn.text for btn in row] for row in rows]


async def _run_alerts_escape_case(dbg, alerts_handlers):
    payload = {
        "tags": ["🏷️ Name_[x]*"],
        "alerts": [],
    }
    storage = _StorageStub(payload)
    update = _DummyUpdate(1001, _DummyMessage())
    context = _DummyContext()

    with _MainbotPatch(storage):
        await alerts_handlers.alerts_start(update, context)

    first = update.message.calls[0] if update.message.calls else {}
    text = first.get("text") or ""
    checks = {
        "one_send_attempt": len(update.message.calls) == 1,
        "parse_mode_markdown": str(first.get("parse_mode")) == "Markdown",
        "tag_name_escaped": "Name\\_\\[x]\\*" in text,
        "no_fallback_event": not _has_event(storage, "alerts_menu_markdown_fallback"),
        "command_event_logged": _has_event(storage, "command_alerts"),
    }
    dbg.section("alerts_escape_case", {
        "checks": checks,
        "calls": update.message.calls,
        "events": storage.events,
    })
    if not all(checks.values()):
        dbg.problem("alerts_escape_case_failed", {"checks": checks})


async def _run_birthdays_escape_case(dbg, birthdays_handlers):
    payload = {
        "tags": ["🎂 Name_[x]*"],
        "alerts": [{"type": 6, "tags": ["🎂 Name_[x]*"]}],
    }
    storage = _StorageStub(payload)
    update = _DummyUpdate(1002, _DummyMessage())
    context = _DummyContext()

    with _MainbotPatch(storage):
        await birthdays_handlers.birthday_start(update, context)

    first = update.message.calls[0] if update.message.calls else {}
    text = first.get("text") or ""
    checks = {
        "one_send_attempt": len(update.message.calls) == 1,
        "parse_mode_markdown": str(first.get("parse_mode")) == "Markdown",
        "tag_name_escaped": "Name\\_\\[x]\\*" in text,
        "no_fallback_event": not _has_event(storage, "birthday_menu_markdown_fallback"),
        "menu_opened_event_logged": _has_event(storage, "birthday_menu_opened"),
    }
    dbg.section("birthdays_escape_case", {
        "checks": checks,
        "calls": update.message.calls,
        "events": storage.events,
    })
    if not all(checks.values()):
        dbg.problem("birthdays_escape_case_failed", {"checks": checks})


async def _run_alerts_fallback_case(dbg, alerts_handlers):
    payload = {
        "tags": ["🏷️ Name_[x]*"],
        "alerts": [],
    }
    storage = _StorageStub(payload)
    update = _DummyUpdate(2001, _DummyMessage(fail_markdown_once=True))
    context = _DummyContext()

    with _MainbotPatch(storage):
        await alerts_handlers.alerts_start(update, context)

    calls = update.message.calls
    second = calls[1] if len(calls) > 1 else {}
    checks = {
        "retry_happened": len(calls) == 2,
        "first_markdown": len(calls) >= 1 and str(calls[0].get("parse_mode")) == "Markdown",
        "second_plain_text": len(calls) >= 2 and second.get("parse_mode") is None,
        "fallback_event_logged": _has_event(storage, "alerts_menu_markdown_fallback"),
        "fallback_sent_event_logged": _has_event(storage, "alerts_menu_markdown_fallback_sent"),
        "fallback_text_still_escaped": "Name\\_\\[x]\\*" in (second.get("text") or ""),
    }
    dbg.section("alerts_fallback_case", {
        "checks": checks,
        "calls": calls,
        "events": storage.events,
    })
    if not all(checks.values()):
        dbg.problem("alerts_fallback_case_failed", {"checks": checks})


async def _run_birthdays_fallback_case(dbg, birthdays_handlers):
    payload = {
        "tags": ["🎂 Name_[x]*"],
        "alerts": [{"type": 6, "tags": ["🎂 Name_[x]*"]}],
    }
    storage = _StorageStub(payload)
    update = _DummyUpdate(2002, _DummyMessage(fail_markdown_once=True))
    context = _DummyContext()

    with _MainbotPatch(storage):
        await birthdays_handlers.birthday_start(update, context)

    calls = update.message.calls
    second = calls[1] if len(calls) > 1 else {}
    checks = {
        "retry_happened": len(calls) == 2,
        "first_markdown": len(calls) >= 1 and str(calls[0].get("parse_mode")) == "Markdown",
        "second_plain_text": len(calls) >= 2 and second.get("parse_mode") is None,
        "fallback_event_logged": _has_event(storage, "birthday_menu_markdown_fallback"),
        "fallback_sent_event_logged": _has_event(storage, "birthday_menu_markdown_fallback_sent"),
        "fallback_text_still_escaped": "Name\\_\\[x]\\*" in (second.get("text") or ""),
    }
    dbg.section("birthdays_fallback_case", {
        "checks": checks,
        "calls": calls,
        "events": storage.events,
    })
    if not all(checks.values()):
        dbg.problem("birthdays_fallback_case_failed", {"checks": checks})


async def _run_list_orphan_warning_case(dbg, list_alerts_handlers):
    payload = {
        "tags": ["🎯 Work"],
        "alerts": [
            {"type": 1, "tags": ["🎯 Work", "legacy_tag_[x]*"]},
            {"type": 1, "tags": ["legacy_tag_[x]*"]},
        ],
    }
    storage = _StorageStub(payload)
    update = _DummyUpdate(3001, _DummyMessage())
    context = _DummyContext()

    with _MainbotPatch(storage):
        await list_alerts_handlers.list_alerts_start(update, context)

    menu_call = update.message.calls[0] if update.message.calls else {}
    menu_markup = menu_call.get("reply_markup")
    menu_rows = getattr(menu_markup, "inline_keyboard", []) if menu_markup else []
    menu_button_labels = [btn.text for row in menu_rows for btn in row]
    warning_call = context.bot.sent[0] if context.bot.sent else {}
    warning_text = warning_call.get("text") or ""

    checks = {
        "menu_sent_once": len(update.message.calls) == 1,
        "menu_sent_markdown": str(menu_call.get("parse_mode")) == "Markdown",
        "menu_has_orphan_button": "🧩 Orphan tag" in menu_button_labels,
        "warning_sent_once": len(context.bot.sent) == 1,
        "warning_sent_markdown": str(warning_call.get("parse_mode")) == "Markdown",
        "warning_mentions_orphan_tags": "Orphan tags in use" in warning_text,
        "warning_escapes_tag_markdown": "legacy\\_tag\\_\\[x]\\*" in warning_text,
        "alerts_list_view_event_logged": _has_event(storage, "alerts_list_view"),
    }
    dbg.section("list_orphan_warning_case", {
        "checks": checks,
        "menu_button_labels": menu_button_labels,
        "warning_text": warning_text,
        "events": storage.events,
    })
    if not all(checks.values()):
        dbg.problem("list_orphan_warning_case_failed", {"checks": checks})


async def _run_birthday_list_orphan_warning_case(dbg, birthday_list_handlers):
    payload = {
        "tags": ["🎂 Family"],
        "alerts": [
            {"type": 6, "tags": ["🎂 Family", "legacy_bday_[x]*"]},
            {"type": 6, "tags": ["legacy_bday_[x]*"]},
        ],
    }
    storage = _StorageStub(payload)
    update = _DummyUpdate(3002, _DummyMessage())
    context = _DummyContext()

    with _MainbotPatch(storage):
        await birthday_list_handlers.birthday_list_start(update, context)

    menu_call = context.bot.sent[0] if len(context.bot.sent) > 0 else {}
    warning_call = context.bot.sent[1] if len(context.bot.sent) > 1 else {}
    menu_markup = menu_call.get("reply_markup")
    menu_rows = getattr(menu_markup, "inline_keyboard", []) if menu_markup else []
    menu_button_labels = [btn.text for row in menu_rows for btn in row]
    warning_text = warning_call.get("text") or ""

    checks = {
        "menu_sent_once": len(context.bot.sent) >= 1,
        "menu_sent_markdown": str(menu_call.get("parse_mode")) == "Markdown",
        "menu_has_orphan_button": "🧩 Orphan tag" in menu_button_labels,
        "warning_sent_once": len(context.bot.sent) >= 2,
        "warning_sent_markdown": str(warning_call.get("parse_mode")) == "Markdown",
        "warning_mentions_orphan_tags": "Orphan tags in use" in warning_text,
        "warning_escapes_tag_markdown": "legacy\\_bday\\_\\[x]\\*" in warning_text,
    }
    dbg.section("birthday_list_orphan_warning_case", {
        "checks": checks,
        "menu_button_labels": menu_button_labels,
        "warning_text": warning_text,
        "events": storage.events,
    })
    if not all(checks.values()):
        dbg.problem("birthday_list_orphan_warning_case_failed", {"checks": checks})


async def _run_filter_button_order_and_presence_cases(dbg, list_alerts_handlers, birthday_list_handlers):
    alerts_payload_with_orphan = {
        "tags": ["🟦 Second", "🟩 First"],
        "alerts": [
            {"type": 1, "tags": ["🟦 Second"]},
            {"type": 1, "tags": ["🟩 First", "legacy_alert_orphan"]},
            {"type": 1, "title": "NoTags"},
        ],
    }
    alerts_payload_no_orphan = {
        "tags": ["🟦 Second", "🟩 First"],
        "alerts": [
            {"type": 1, "tags": ["🟦 Second"]},
            {"type": 1, "tags": ["🟩 First"]},
        ],
    }
    birthdays_payload_with_orphan = {
        "tags": ["🎂 Second", "🎉 First"],
        "alerts": [
            {"type": 6, "tags": ["🎂 Second"]},
            {"type": 6, "tags": ["🎉 First", "legacy_bday_orphan"]},
            {"type": 6, "title": "NoTagsBirthday", "schedule": {"date": "01/02", "time": "08:00"}},
        ],
    }
    birthdays_payload_no_orphan = {
        "tags": ["🎂 Second", "🎉 First"],
        "alerts": [
            {"type": 6, "tags": ["🎂 Second"]},
            {"type": 6, "tags": ["🎉 First"]},
        ],
    }

    alerts_with_orphan_storage = _StorageStub(alerts_payload_with_orphan)
    alerts_with_orphan_update = _DummyUpdate(3101, _DummyMessage())
    alerts_with_orphan_ctx = _DummyContext()
    with _MainbotPatch(alerts_with_orphan_storage):
        await list_alerts_handlers.list_alerts_start(alerts_with_orphan_update, alerts_with_orphan_ctx)
    alerts_with_markup = alerts_with_orphan_update.message.calls[0].get("reply_markup")
    alerts_with_labels = _button_labels(alerts_with_markup)
    alerts_with_rows = _button_rows(alerts_with_markup)

    alerts_no_orphan_storage = _StorageStub(alerts_payload_no_orphan)
    alerts_no_orphan_update = _DummyUpdate(3102, _DummyMessage())
    alerts_no_orphan_ctx = _DummyContext()
    with _MainbotPatch(alerts_no_orphan_storage):
        await list_alerts_handlers.list_alerts_start(alerts_no_orphan_update, alerts_no_orphan_ctx)
    alerts_no_markup = alerts_no_orphan_update.message.calls[0].get("reply_markup")
    alerts_no_labels = _button_labels(alerts_no_markup)

    birthdays_with_orphan_storage = _StorageStub(birthdays_payload_with_orphan)
    birthdays_with_orphan_update = _DummyUpdate(3103, _DummyMessage())
    birthdays_with_orphan_ctx = _DummyContext()
    with _MainbotPatch(birthdays_with_orphan_storage):
        await birthday_list_handlers.birthday_list_start(
            birthdays_with_orphan_update, birthdays_with_orphan_ctx
        )
    birthdays_with_markup = birthdays_with_orphan_ctx.bot.sent[0].get("reply_markup") if birthdays_with_orphan_ctx.bot.sent else None
    birthdays_with_labels = _button_labels(birthdays_with_markup)
    birthdays_with_rows = _button_rows(birthdays_with_markup)

    birthdays_no_orphan_storage = _StorageStub(birthdays_payload_no_orphan)
    birthdays_no_orphan_update = _DummyUpdate(3104, _DummyMessage())
    birthdays_no_orphan_ctx = _DummyContext()
    with _MainbotPatch(birthdays_no_orphan_storage):
        await birthday_list_handlers.birthday_list_start(
            birthdays_no_orphan_update, birthdays_no_orphan_ctx
        )
    birthdays_no_labels = _button_labels(
        birthdays_no_orphan_ctx.bot.sent[0].get("reply_markup") if birthdays_no_orphan_ctx.bot.sent else None
    )

    checks = {
        "alerts_all_first_row": bool(alerts_with_labels) and alerts_with_labels[0] == "📋 ALL TAGS",
        "alerts_known_order_master": (
            "🟦 Second" in alerts_with_labels
            and "🟩 First" in alerts_with_labels
            and alerts_with_labels.index("🟦 Second") < alerts_with_labels.index("🟩 First")
        ),
        "alerts_orphan_button_present": "🧩 Orphan tag" in alerts_with_labels,
        "alerts_orphan_button_absent": "🧩 Orphan tag" not in alerts_no_labels,
        "alerts_untagged_button_present": list_alerts_handlers.UNTAGGED_FILTER_BUTTON_LABEL in alerts_with_labels,
        "alerts_untagged_button_absent": list_alerts_handlers.UNTAGGED_FILTER_BUTTON_LABEL not in alerts_no_labels,
        "alerts_untagged_last_single_row": bool(alerts_with_rows) and alerts_with_rows[-1] == [list_alerts_handlers.UNTAGGED_FILTER_BUTTON_LABEL],
        "birthdays_all_first_row": bool(birthdays_with_labels) and birthdays_with_labels[0] == "📋 ALL TAGS",
        "birthdays_known_order_master": (
            "🎂 Second" in birthdays_with_labels
            and "🎉 First" in birthdays_with_labels
            and birthdays_with_labels.index("🎂 Second") < birthdays_with_labels.index("🎉 First")
        ),
        "birthdays_orphan_button_present": "🧩 Orphan tag" in birthdays_with_labels,
        "birthdays_orphan_button_absent": "🧩 Orphan tag" not in birthdays_no_labels,
        "birthdays_untagged_button_present": birthday_list_handlers.BDAY_UNTAGGED_FILTER_BUTTON_LABEL in birthdays_with_labels,
        "birthdays_untagged_button_absent": birthday_list_handlers.BDAY_UNTAGGED_FILTER_BUTTON_LABEL not in birthdays_no_labels,
        "birthdays_untagged_last_single_row": bool(birthdays_with_rows) and birthdays_with_rows[-1] == [birthday_list_handlers.BDAY_UNTAGGED_FILTER_BUTTON_LABEL],
    }
    dbg.section("filter_button_order_and_presence", {
        "checks": checks,
        "alerts_with_labels": alerts_with_labels,
        "alerts_with_rows": alerts_with_rows,
        "alerts_no_labels": alerts_no_labels,
        "birthdays_with_labels": birthdays_with_labels,
        "birthdays_with_rows": birthdays_with_rows,
        "birthdays_no_labels": birthdays_no_labels,
    })
    if not all(checks.values()):
        dbg.problem("filter_button_order_and_presence_failed", {"checks": checks})


async def _run_orphan_filter_result_and_stale_cases(dbg, list_alerts_handlers, birthday_list_handlers):
    alerts_result_payload = {
        "tags": ["🏷️ Known"],
        "alerts": [
            {
                "id": "a1",
                "type": 1,
                "title": "AlphaKnown",
                "tags": ["🏷️ Known"],
                "next_scheduled": "2030-01-01T10:00:00",
            },
            {
                "id": "a2",
                "type": 1,
                "title": "BetaOrphan",
                "tags": ["legacy_orphan_alert"],
                "next_scheduled": "2030-01-02T10:00:00",
            },
            {
                "id": "a3",
                "type": 1,
                "title": "GammaMixed",
                "tags": ["🏷️ Known", "legacy_mixed_alert"],
                "next_scheduled": "2030-01-03T10:00:00",
            },
        ],
    }
    alerts_result_storage = _StorageStub(alerts_result_payload)
    alerts_result_update = _DummyUpdate(3201, _DummyMessage())
    alerts_result_ctx = _DummyContext()
    with _MainbotPatch(alerts_result_storage):
        await list_alerts_handlers.show_alerts_list(
            alerts_result_update,
            alerts_result_ctx,
            manual_tag=list_alerts_handlers.ORPHAN_FILTER_VALUE,
            manual_page=1,
        )
    alerts_result_text = alerts_result_ctx.bot.sent[-1]["text"] if alerts_result_ctx.bot.sent else ""

    alerts_stale_payload = {
        "tags": ["🏷️ Known"],
        "alerts": [{"id": "a4", "type": 1, "title": "OnlyKnown", "tags": ["🏷️ Known"]}],
    }
    alerts_stale_storage = _StorageStub(alerts_stale_payload)
    alerts_stale_query = _DummyCallbackQuery(list_alerts_handlers.ORPHAN_FILTER_CALLBACK_DATA)
    alerts_stale_update = _DummyUpdate(3202, callback_query=alerts_stale_query)
    alerts_stale_ctx = _DummyContext()
    with _MainbotPatch(alerts_stale_storage):
        await list_alerts_handlers.show_alerts_list(alerts_stale_update, alerts_stale_ctx)
    alerts_stale_text = alerts_stale_ctx.bot.sent[-1]["text"] if alerts_stale_ctx.bot.sent else ""

    birthdays_result_payload = {
        "tags": ["🎂 Known"],
        "alerts": [
            {
                "id": "b1",
                "type": 6,
                "title": "BdayKnown",
                "tags": ["🎂 Known"],
                "schedule": {"date": "01/02", "time": "08:00"},
            },
            {
                "id": "b2",
                "type": 6,
                "title": "BdayOrphan",
                "tags": ["legacy_orphan_bday"],
                "schedule": {"date": "02/02", "time": "08:00"},
            },
            {
                "id": "b3",
                "type": 6,
                "title": "BdayMixed",
                "tags": ["🎂 Known", "legacy_mixed_bday"],
                "schedule": {"date": "03/02", "time": "08:00"},
            },
        ],
    }
    birthdays_result_storage = _StorageStub(birthdays_result_payload)
    birthdays_result_update = _DummyUpdate(3203, _DummyMessage())
    birthdays_result_ctx = _DummyContext()
    with _MainbotPatch(birthdays_result_storage):
        await birthday_list_handlers.show_birthdays_list(
            birthdays_result_update,
            birthdays_result_ctx,
            manual_tag=birthday_list_handlers.ORPHAN_FILTER_VALUE,
            manual_page=1,
        )
    birthdays_result_text = birthdays_result_ctx.bot.sent[-1]["text"] if birthdays_result_ctx.bot.sent else ""

    birthdays_stale_payload = {
        "tags": ["🎂 Known"],
        "alerts": [
            {"id": "b4", "type": 6, "title": "OnlyKnownBirthday", "tags": ["🎂 Known"], "schedule": {"date": "04/02", "time": "08:00"}}
        ],
    }
    birthdays_stale_storage = _StorageStub(birthdays_stale_payload)
    birthdays_stale_query = _DummyCallbackQuery(
        birthday_list_handlers.BDAY_ORPHAN_FILTER_CALLBACK_DATA
    )
    birthdays_stale_update = _DummyUpdate(3204, callback_query=birthdays_stale_query)
    birthdays_stale_ctx = _DummyContext()
    with _MainbotPatch(birthdays_stale_storage):
        await birthday_list_handlers.show_birthdays_list(
            birthdays_stale_update,
            birthdays_stale_ctx,
        )
    birthdays_stale_text = birthdays_stale_ctx.bot.sent[-1]["text"] if birthdays_stale_ctx.bot.sent else ""

    alerts_real_tag_payload = {
        "tags": ["__ORPHAN__"],
        "alerts": [
            {
                "id": "a5",
                "type": 1,
                "title": "RealOrphanTag",
                "tags": ["__ORPHAN__"],
                "next_scheduled": "2030-01-04T10:00:00",
            },
        ],
    }
    alerts_real_tag_storage = _StorageStub(alerts_real_tag_payload)
    alerts_real_tag_update = _DummyUpdate(3205, _DummyMessage())
    alerts_real_tag_ctx = _DummyContext()
    with _MainbotPatch(alerts_real_tag_storage):
        await list_alerts_handlers.show_alerts_list(
            alerts_real_tag_update,
            alerts_real_tag_ctx,
            manual_tag="__ORPHAN__",
            manual_page=1,
        )
    alerts_real_tag_text = alerts_real_tag_ctx.bot.sent[-1]["text"] if alerts_real_tag_ctx.bot.sent else ""

    birthdays_real_tag_payload = {
        "tags": ["__ORPHAN__"],
        "alerts": [
            {
                "id": "b5",
                "type": 6,
                "title": "RealOrphanBirthdayTag",
                "tags": ["__ORPHAN__"],
                "schedule": {"date": "05/02", "time": "08:00"},
            },
        ],
    }
    birthdays_real_tag_storage = _StorageStub(birthdays_real_tag_payload)
    birthdays_real_tag_update = _DummyUpdate(3206, _DummyMessage())
    birthdays_real_tag_ctx = _DummyContext()
    with _MainbotPatch(birthdays_real_tag_storage):
        await birthday_list_handlers.show_birthdays_list(
            birthdays_real_tag_update,
            birthdays_real_tag_ctx,
            manual_tag="__ORPHAN__",
            manual_page=1,
        )
    birthdays_real_tag_text = birthdays_real_tag_ctx.bot.sent[-1]["text"] if birthdays_real_tag_ctx.bot.sent else ""

    checks = {
        "alerts_orphan_result_includes_orphan_only": "BETAORPHAN" in alerts_result_text,
        "alerts_orphan_result_includes_mixed": "GAMMAMIXED" in alerts_result_text,
        "alerts_orphan_result_excludes_known_only": "ALPHAKNOWN" not in alerts_result_text,
        "alerts_stale_orphan_failsoft": "Orphan filter is no longer available" in alerts_stale_text,
        "alerts_stale_answered_once": len(alerts_stale_query.answers) == 1,
        "alerts_real_orphan_name_filter_includes_item": "REALORPHANTAG" in alerts_real_tag_text,
        "alerts_real_orphan_name_filter_not_stale": "no longer available" not in alerts_real_tag_text.lower(),
        "birthdays_orphan_result_includes_orphan_only": "BDAYORPHAN" in birthdays_result_text,
        "birthdays_orphan_result_includes_mixed": "BDAYMIXED" in birthdays_result_text,
        "birthdays_orphan_result_excludes_known_only": "BDAYKNOWN" not in birthdays_result_text,
        "birthdays_stale_orphan_failsoft": "orphan filter is no longer available" in birthdays_stale_text.lower(),
        "birthdays_stale_answered_once": len(birthdays_stale_query.answers) == 1,
        "birthdays_real_orphan_name_filter_includes_item": "REALORPHANBIRTHDAYTAG" in birthdays_real_tag_text,
        "birthdays_real_orphan_name_filter_not_stale": "no longer available" not in birthdays_real_tag_text.lower(),
    }
    dbg.section("orphan_filter_result_and_stale", {
        "checks": checks,
        "alerts_result_text": alerts_result_text,
        "alerts_stale_text": alerts_stale_text,
        "alerts_real_tag_text": alerts_real_tag_text,
        "birthdays_result_text": birthdays_result_text,
        "birthdays_stale_text": birthdays_stale_text,
        "birthdays_real_tag_text": birthdays_real_tag_text,
    })
    if not all(checks.values()):
        dbg.problem("orphan_filter_result_and_stale_failed", {"checks": checks})


async def _run_alert_untagged_filter_result_and_stale_cases(dbg, list_alerts_handlers):
    alerts_result_payload = {
        "tags": ["🏷️ Known"],
        "alerts": [
            {
                "id": "u1",
                "type": 1,
                "title": "KnownTag",
                "tags": ["🏷️ Known"],
                "next_scheduled": "2030-02-01T10:00:00",
            },
            {
                "id": "u2",
                "type": 1,
                "title": "MissingTag",
                "next_scheduled": "2030-02-02T10:00:00",
            },
            {
                "id": "u3",
                "type": 1,
                "title": "EmptyTags",
                "tags": [],
                "next_scheduled": "2030-02-03T10:00:00",
            },
            {
                "id": "u4",
                "type": 1,
                "title": "NonListTags",
                "tags": "legacy_non_list",
                "next_scheduled": "2030-02-04T10:00:00",
            },
            {
                "id": "u5",
                "type": 1,
                "title": "BlankListTags",
                "tags": [" ", ""],
                "next_scheduled": "2030-02-05T10:00:00",
            },
            {
                "id": "u6",
                "type": 1,
                "title": "MixedTag",
                "tags": ["🏷️ Known", "legacy_mixed"],
                "next_scheduled": "2030-02-06T10:00:00",
            },
        ],
    }
    alerts_result_storage = _StorageStub(alerts_result_payload)
    alerts_result_update = _DummyUpdate(3251, _DummyMessage())
    alerts_result_ctx = _DummyContext()
    with _MainbotPatch(alerts_result_storage):
        await list_alerts_handlers.show_alerts_list(
            alerts_result_update,
            alerts_result_ctx,
            manual_tag=list_alerts_handlers.UNTAGGED_FILTER_VALUE,
            manual_page=1,
        )
    alerts_result_text = alerts_result_ctx.bot.sent[-1]["text"] if alerts_result_ctx.bot.sent else ""

    alerts_stale_payload = {
        "tags": ["🏷️ Known"],
        "alerts": [
            {"id": "u7", "type": 1, "title": "OnlyTaggedOne", "tags": ["🏷️ Known"]},
            {"id": "u8", "type": 1, "title": "OnlyTaggedTwo", "tags": ["🏷️ Known", "legacy_mixed"]},
        ],
    }
    alerts_stale_storage = _StorageStub(alerts_stale_payload)
    alerts_stale_query = _DummyCallbackQuery(list_alerts_handlers.UNTAGGED_FILTER_CALLBACK_DATA)
    alerts_stale_update = _DummyUpdate(3252, callback_query=alerts_stale_query)
    alerts_stale_ctx = _DummyContext()
    with _MainbotPatch(alerts_stale_storage):
        await list_alerts_handlers.show_alerts_list(alerts_stale_update, alerts_stale_ctx)
    alerts_stale_text = alerts_stale_ctx.bot.sent[-1]["text"] if alerts_stale_ctx.bot.sent else ""

    checks = {
        "untagged_result_includes_missing": "MISSINGTAG" in alerts_result_text,
        "untagged_result_includes_empty": "EMPTYTAGS" in alerts_result_text,
        "untagged_result_includes_non_list": "NONLISTTAGS" in alerts_result_text,
        "untagged_result_includes_blank_list": "BLANKLISTTAGS" in alerts_result_text,
        "untagged_result_excludes_known": "KNOWNTAG" not in alerts_result_text,
        "untagged_result_excludes_mixed": "MIXEDTAG" not in alerts_result_text,
        "untagged_stale_failsoft": "Untagged filter is no longer available" in alerts_stale_text,
        "untagged_stale_answered_once": len(alerts_stale_query.answers) == 1,
    }
    dbg.section("alert_untagged_filter_result_and_stale", {
        "checks": checks,
        "alerts_result_text": alerts_result_text,
        "alerts_stale_text": alerts_stale_text,
    })
    if not all(checks.values()):
        dbg.problem("alert_untagged_filter_result_and_stale_failed", {"checks": checks})


async def _run_birthday_untagged_filter_result_and_stale_cases(dbg, birthday_list_handlers):
    birthdays_result_payload = {
        "tags": ["🎂 Known"],
        "alerts": [
            {
                "id": "bu1",
                "type": 6,
                "title": "KnownBirthday",
                "tags": ["🎂 Known"],
                "schedule": {"date": "01/03", "time": "08:00"},
            },
            {
                "id": "bu2",
                "type": 6,
                "title": "MissingBirthdayTags",
                "schedule": {"date": "02/03", "time": "08:00"},
            },
            {
                "id": "bu3",
                "type": 6,
                "title": "EmptyBirthdayTags",
                "tags": [],
                "schedule": {"date": "03/03", "time": "08:00"},
            },
            {
                "id": "bu4",
                "type": 6,
                "title": "NonListBirthdayTags",
                "tags": "legacy_non_list",
                "schedule": {"date": "04/03", "time": "08:00"},
            },
            {
                "id": "bu5",
                "type": 6,
                "title": "BlankBirthdayTags",
                "tags": [" ", ""],
                "schedule": {"date": "05/03", "time": "08:00"},
            },
            {
                "id": "bu6",
                "type": 6,
                "title": "MixedBirthdayTags",
                "tags": ["🎂 Known", "legacy_mixed"],
                "schedule": {"date": "06/03", "time": "08:00"},
            },
        ],
    }
    birthdays_result_storage = _StorageStub(birthdays_result_payload)
    birthdays_result_update = _DummyUpdate(3253, _DummyMessage())
    birthdays_result_ctx = _DummyContext()
    with _MainbotPatch(birthdays_result_storage):
        await birthday_list_handlers.show_birthdays_list(
            birthdays_result_update,
            birthdays_result_ctx,
            manual_tag=birthday_list_handlers.BDAY_UNTAGGED_FILTER_VALUE,
            manual_page=1,
        )
    birthdays_result_text = birthdays_result_ctx.bot.sent[-1]["text"] if birthdays_result_ctx.bot.sent else ""

    birthdays_stale_payload = {
        "tags": ["🎂 Known"],
        "alerts": [
            {"id": "bu7", "type": 6, "title": "OnlyTaggedBirthdayOne", "tags": ["🎂 Known"], "schedule": {"date": "07/03", "time": "08:00"}},
            {"id": "bu8", "type": 6, "title": "OnlyTaggedBirthdayTwo", "tags": ["🎂 Known", "legacy_mixed"], "schedule": {"date": "08/03", "time": "08:00"}},
        ],
    }
    birthdays_stale_storage = _StorageStub(birthdays_stale_payload)
    birthdays_stale_query = _DummyCallbackQuery(
        birthday_list_handlers.BDAY_UNTAGGED_FILTER_CALLBACK_DATA
    )
    birthdays_stale_update = _DummyUpdate(3254, callback_query=birthdays_stale_query)
    birthdays_stale_ctx = _DummyContext()
    with _MainbotPatch(birthdays_stale_storage):
        await birthday_list_handlers.show_birthdays_list(
            birthdays_stale_update,
            birthdays_stale_ctx,
        )
    birthdays_stale_text = birthdays_stale_ctx.bot.sent[-1]["text"] if birthdays_stale_ctx.bot.sent else ""

    checks = {
        "untagged_result_includes_missing": "MISSINGBIRTHDAYTAGS" in birthdays_result_text,
        "untagged_result_includes_empty": "EMPTYBIRTHDAYTAGS" in birthdays_result_text,
        "untagged_result_includes_non_list": "NONLISTBIRTHDAYTAGS" in birthdays_result_text,
        "untagged_result_includes_blank_list": "BLANKBIRTHDAYTAGS" in birthdays_result_text,
        "untagged_result_excludes_known": "KNOWNBIRTHDAY" not in birthdays_result_text,
        "untagged_result_excludes_mixed": "MIXEDBIRTHDAYTAGS" not in birthdays_result_text,
        "untagged_stale_failsoft": "Birthday untagged filter is no longer available" in birthdays_stale_text,
        "untagged_stale_answered_once": len(birthdays_stale_query.answers) == 1,
    }
    dbg.section("birthday_untagged_filter_result_and_stale", {
        "checks": checks,
        "birthdays_result_text": birthdays_result_text,
        "birthdays_stale_text": birthdays_stale_text,
    })
    if not all(checks.values()):
        dbg.problem("birthday_untagged_filter_result_and_stale_failed", {"checks": checks})


async def _run_mixed_type_known_tag_filter_cases(dbg, list_alerts_handlers, birthday_list_handlers):
    alerts_payload = {
        "tags": [123, "🏷️ Other"],
        "alerts": [
            {
                "id": "m1",
                "type": 1,
                "title": "IntTagAlert",
                "tags": [123],
                "next_scheduled": "2030-01-05T10:00:00",
            },
            {
                "id": "m2",
                "type": 1,
                "title": "StrTagAlert",
                "tags": ["123"],
                "next_scheduled": "2030-01-06T10:00:00",
            },
            {
                "id": "m3",
                "type": 1,
                "title": "OtherTagAlert",
                "tags": ["🏷️ Other"],
                "next_scheduled": "2030-01-07T10:00:00",
            },
        ],
    }
    alerts_storage = _StorageStub(alerts_payload)
    alerts_update = _DummyUpdate(3301, _DummyMessage())
    alerts_ctx = _DummyContext()
    with _MainbotPatch(alerts_storage):
        await list_alerts_handlers.show_alerts_list(
            alerts_update,
            alerts_ctx,
            manual_tag="123",
            manual_page=1,
        )
    alerts_text = alerts_ctx.bot.sent[-1]["text"] if alerts_ctx.bot.sent else ""

    birthdays_payload = {
        "tags": [456, "🎂 Other"],
        "alerts": [
            {
                "id": "bm1",
                "type": 6,
                "title": "IntTagBirthday",
                "tags": [456],
                "schedule": {"date": "06/02", "time": "08:00"},
            },
            {
                "id": "bm2",
                "type": 6,
                "title": "StrTagBirthday",
                "tags": ["456"],
                "schedule": {"date": "07/02", "time": "08:00"},
            },
            {
                "id": "bm3",
                "type": 6,
                "title": "OtherTagBirthday",
                "tags": ["🎂 Other"],
                "schedule": {"date": "08/02", "time": "08:00"},
            },
        ],
    }
    birthdays_storage = _StorageStub(birthdays_payload)
    birthdays_update = _DummyUpdate(3302, _DummyMessage())
    birthdays_ctx = _DummyContext()
    with _MainbotPatch(birthdays_storage):
        await birthday_list_handlers.show_birthdays_list(
            birthdays_update,
            birthdays_ctx,
            manual_tag="456",
            manual_page=1,
        )
    birthdays_text = birthdays_ctx.bot.sent[-1]["text"] if birthdays_ctx.bot.sent else ""

    checks = {
        "alerts_known_filter_includes_int_tag": "INTTAGALERT" in alerts_text,
        "alerts_known_filter_includes_str_tag": "STRTAGALERT" in alerts_text,
        "alerts_known_filter_excludes_other_tag": "OTHERTAGALERT" not in alerts_text,
        "birthdays_known_filter_includes_int_tag": "INTTAGBIRTHDAY" in birthdays_text,
        "birthdays_known_filter_includes_str_tag": "STRTAGBIRTHDAY" in birthdays_text,
        "birthdays_known_filter_excludes_other_tag": "OTHERTAGBIRTHDAY" not in birthdays_text,
    }
    dbg.section("mixed_type_known_tag_filter", {
        "checks": checks,
        "alerts_text": alerts_text,
        "birthdays_text": birthdays_text,
    })
    if not all(checks.values()):
        dbg.problem("mixed_type_known_tag_filter_failed", {"checks": checks})


async def _run_callback_answer_contract_cases(dbg, birthdays_handlers, list_alerts_handlers):
    birthday_payload = {
        "tags": ["🎂 Family"],
        "alerts": [
            {
                "id": "c1",
                "type": 6,
                "title": "BirthdayOne",
                "tags": ["🎂 Family"],
                "schedule": {"date": "09/02", "time": "08:00"},
            },
        ],
    }
    alerts_payload = {
        "tags": ["🏷️ Work"],
        "alerts": [
            {
                "id": "c2",
                "type": 1,
                "title": "AlertOne",
                "tags": ["🏷️ Work"],
                "next_scheduled": "2030-01-10T10:00:00",
            },
        ],
    }

    bday_list_query = _DummyCallbackQuery("bday_list")
    bday_list_update = _DummyUpdate(3401, callback_query=bday_list_query)
    bday_list_ctx = _DummyContext()
    with _MainbotPatch(_StorageStub(birthday_payload)):
        await birthdays_handlers.handle_birthday_menu(bday_list_update, bday_list_ctx)

    bday_next_query = _DummyCallbackQuery("bday_next")
    bday_next_update = _DummyUpdate(3402, callback_query=bday_next_query)
    bday_next_ctx = _DummyContext()
    with _MainbotPatch(_StorageStub(birthday_payload)):
        await birthdays_handlers.handle_birthday_menu(bday_next_update, bday_next_ctx)

    manage_alerts_query = _DummyCallbackQuery("manage_backtolist")
    manage_alerts_update = _DummyUpdate(3403, callback_query=manage_alerts_query)
    manage_alerts_ctx = _DummyContext()
    manage_alerts_ctx.user_data["manage_source"] = "alerts"
    manage_alerts_ctx.user_data["current_filter"] = "ALL"
    with _MainbotPatch(_StorageStub(alerts_payload)):
        await list_alerts_handlers.handle_management(manage_alerts_update, manage_alerts_ctx)

    manage_birthdays_query = _DummyCallbackQuery("manage_backtolist")
    manage_birthdays_update = _DummyUpdate(3404, callback_query=manage_birthdays_query)
    manage_birthdays_ctx = _DummyContext()
    manage_birthdays_ctx.user_data["manage_source"] = "birthdays"
    manage_birthdays_ctx.user_data["birthday_current_filter"] = "ALL"
    with _MainbotPatch(_StorageStub(birthday_payload)):
        await list_alerts_handlers.handle_management(
            manage_birthdays_update, manage_birthdays_ctx
        )

    checks = {
        "bday_list_answered_once": bday_list_query.answer_count == 1,
        "bday_next_answered_once": bday_next_query.answer_count == 1,
        "manage_backtolist_alerts_answered_once": manage_alerts_query.answer_count == 1,
        "manage_backtolist_birthdays_answered_once": manage_birthdays_query.answer_count == 1,
    }
    dbg.section("callback_answer_contract", {
        "checks": checks,
        "counts": {
            "bday_list": bday_list_query.answer_count,
            "bday_next": bday_next_query.answer_count,
            "manage_backtolist_alerts": manage_alerts_query.answer_count,
            "manage_backtolist_birthdays": manage_birthdays_query.answer_count,
        },
    })
    if not all(checks.values()):
        dbg.problem("callback_answer_contract_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown = _parse_cli_args(dbg.args)
        if unknown:
            dbg.problem("cli_args_unknown", {"unknown": unknown, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.handlers import alerts as alerts_handlers
            from modules.handlers import birthdays as birthdays_handlers
            from modules.handlers import list_alerts as list_alerts_handlers
            from modules.handlers.birthday_flow import list_view as birthday_list_handlers
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        run_async(_run_alerts_escape_case(dbg, alerts_handlers))
        run_async(_run_birthdays_escape_case(dbg, birthdays_handlers))
        run_async(_run_alerts_fallback_case(dbg, alerts_handlers))
        run_async(_run_birthdays_fallback_case(dbg, birthdays_handlers))
        run_async(_run_list_orphan_warning_case(dbg, list_alerts_handlers))
        run_async(_run_birthday_list_orphan_warning_case(dbg, birthday_list_handlers))
        run_async(_run_filter_button_order_and_presence_cases(
            dbg,
            list_alerts_handlers,
            birthday_list_handlers,
        ))
        run_async(_run_orphan_filter_result_and_stale_cases(
            dbg,
            list_alerts_handlers,
            birthday_list_handlers,
        ))
        run_async(_run_alert_untagged_filter_result_and_stale_cases(
            dbg,
            list_alerts_handlers,
        ))
        run_async(_run_birthday_untagged_filter_result_and_stale_cases(
            dbg,
            birthday_list_handlers,
        ))
        run_async(_run_mixed_type_known_tag_filter_cases(
            dbg,
            list_alerts_handlers,
            birthday_list_handlers,
        ))
        run_async(_run_callback_answer_contract_cases(
            dbg,
            birthdays_handlers,
            list_alerts_handlers,
        ))
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    escape_ok = not dbg.has_problem("alerts_escape_case_failed", "birthdays_escape_case_failed")
    fallback_ok = not dbg.has_problem("alerts_fallback_case_failed", "birthdays_fallback_case_failed")
    list_orphan_ok = not dbg.has_problem(
        "list_orphan_warning_case_failed",
        "birthday_list_orphan_warning_case_failed",
        "filter_button_order_and_presence_failed",
        "orphan_filter_result_and_stale_failed",
        "alert_untagged_filter_result_and_stale_failed",
        "birthday_untagged_filter_result_and_stale_failed",
        "mixed_type_known_tag_filter_failed",
        "callback_answer_contract_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"escape: {'OK' if escape_ok else 'FAIL'}",
        f"fallback: {'OK' if fallback_ok else 'FAIL'}",
        f"list_orphan: {'OK' if list_orphan_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
