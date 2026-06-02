#!/usr/bin/env python3
import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch


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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "callback_answer_contract_debug"
FEATURE_TITLE = "Scheduler Callback Answer Contract"

IMPORT_ERROR = None
try:
    from modules import constants as C
    from modules.handlers.scheduler_handlers import (
        handle_postpone_menu,
        handle_postpone_set,
        handle_postpone_custom,
        handle_prealert_info,
        handle_alert_info,
        handle_notif_back,
        handle_alert_toggle,
        handle_bday_noted,
        handle_bday_msg_style,
        handle_alert_done,
    )
    from modules.handlers.birthday_flow.message_suggestions.callbacks import (
        build_bday_msg_callback,
        build_bday_noted_callback,
    )
except ModuleNotFoundError as exc:  # pragma: no cover
    IMPORT_ERROR = exc


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _StrictQuery:
    def __init__(self, data):
        self.data = data
        self.answer_attempts = 0
        self.answers = []
        self.message = SimpleNamespace(message_id=101, photo=None)
        self.edit_reply_markup_calls = []
        self.edit_text_calls = []
        self.edit_caption_calls = []

    async def answer(self, text=None, show_alert=False):
        self.answer_attempts += 1
        if self.answer_attempts > 1:
            raise RuntimeError("callback_answer_called_twice")
        self.answers.append({
            "text": text,
            "show_alert": bool(show_alert),
        })

    async def edit_message_reply_markup(self, reply_markup=None):
        self.edit_reply_markup_calls.append({"reply_markup": reply_markup})

    async def edit_message_text(self, text=None, **kwargs):
        payload = {"text": text}
        payload.update(kwargs)
        self.edit_text_calls.append(payload)

    async def edit_message_caption(self, caption=None, **kwargs):
        payload = {"caption": caption}
        payload.update(kwargs)
        self.edit_caption_calls.append(payload)


class _DummyBot:
    def __init__(self):
        self.sent_messages = []
        self.edits = []
        self.edit_text_calls = []
        self.edit_caption_calls = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "kwargs": dict(kwargs),
        })

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
        self.edits.append({
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup,
        })

    async def edit_message_text(self, *, chat_id, message_id, text, **kwargs):
        self.edit_text_calls.append({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "kwargs": dict(kwargs),
        })

    async def edit_message_caption(self, *, chat_id, message_id, caption, **kwargs):
        self.edit_caption_calls.append({
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
            "kwargs": dict(kwargs),
        })


class _StorageStub:
    def __init__(self):
        self.alerts = {}
        self.toggle_results = {}
        self.events = []
        self.postpone_queue = []
        self.postpone_updates = []

    def get_alert_by_id(self, user_id, alert_id):
        alert = self.alerts.get(alert_id)
        return dict(alert) if isinstance(alert, dict) else None

    def get_user_prefs(self, user_id):
        return {}

    def toggle_alert(self, user_id, alert_id):
        return self.toggle_results.get(alert_id)

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": str(user_id),
            "event_type": event_type,
            "payload": dict(payload or {}),
        })

    def get_postpone_queue(self, user_id):
        return list(self.postpone_queue)

    def update_postpone_instance(self, user_id, instance_id, updates):
        self.postpone_updates.append({
            "user_id": str(user_id),
            "instance_id": instance_id,
            "updates": dict(updates or {}),
        })

    def add_postpone_instance(self, user_id, instance):
        self.postpone_queue.append(dict(instance))


async def _run_handler(handler, callback_data, storage, user_id=777, patch_mark_done=None):
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    query = _StrictQuery(callback_data)
    bot_data = {}
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id),
    )
    context = SimpleNamespace(
        bot=_DummyBot(),
        bot_data=bot_data,
        user_data={},
    )
    set_bot_runtime(bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
    err = None
    if patch_mark_done is None:
        try:
            await handler(update, context)
        except Exception as exc:  # pragma: no cover
            err = str(exc)
    else:
        with patch("modules.handlers.scheduler_handlers.mark_alert_done", patch_mark_done):
            try:
                await handler(update, context)
            except Exception as exc:  # pragma: no cover
                err = str(exc)
    return {
        "query": query,
        "context": context,
        "storage": storage,
        "error": err,
    }


def _check_case(dbg, code, label, result, expect_show_alert, expect_text=None, extra_checks=None):
    query = result["query"]
    checks = {
        "no_exception": result["error"] is None,
        "single_answer_attempt": query.answer_attempts == 1,
        "one_answer_recorded": len(query.answers) == 1,
        "show_alert_expected": bool(query.answers and query.answers[0]["show_alert"] == expect_show_alert),
    }
    if expect_text is not None:
        checks["text_expected"] = bool(query.answers and query.answers[0]["text"] == expect_text)
    if isinstance(extra_checks, dict):
        checks.update(extra_checks)

    dbg.section(label, {
        "checks": checks,
        "answers": query.answers,
        "answer_attempts": query.answer_attempts,
        "error": result["error"],
        "events": result["storage"].events,
        "bot_sent_count": len(result["context"].bot.sent_messages),
        "bot_edit_text_calls": len(result["context"].bot.edit_text_calls),
        "bot_edit_caption_calls": len(result["context"].bot.edit_caption_calls),
        "query_edit_reply_markup_calls": len(query.edit_reply_markup_calls),
        "query_edit_text_calls": len(query.edit_text_calls),
        "query_edit_caption_calls": len(query.edit_caption_calls),
    })
    if not all(checks.values()):
        dbg.problem(code, {"checks": checks})


def _run_contract_checks(dbg):
    ts = str(int(datetime(2026, 3, 10, 10, 0, 0).timestamp()))

    # postpone_menu invalid payload
    storage = _StorageStub()
    res = run_async(_run_handler(handle_postpone_menu, "pp_menu_bad", storage))
    _check_case(
        dbg,
        "postpone_menu_invalid_contract_failed",
        "postpone_menu_invalid",
        res,
        expect_show_alert=True,
        expect_text="❌ Invalid postpone data",
    )

    # postpone_set invalid payload
    storage = _StorageStub()
    res = run_async(_run_handler(handle_postpone_set, "pp_set_bad", storage))
    _check_case(
        dbg,
        "postpone_set_invalid_contract_failed",
        "postpone_set_invalid",
        res,
        expect_show_alert=True,
        expect_text="❌ Invalid postpone data",
    )

    # postpone_set missing alert
    storage = _StorageStub()
    callback = f"pp_set_1h_due_missing_{ts}_{ts}"
    res = run_async(_run_handler(handle_postpone_set, callback, storage))
    _check_case(
        dbg,
        "postpone_set_missing_alert_contract_failed",
        "postpone_set_missing_alert",
        res,
        expect_show_alert=True,
        expect_text="❌ Alert not found",
    )

    # postpone_custom invalid payload
    storage = _StorageStub()
    res = run_async(_run_handler(handle_postpone_custom, "pp_custom_bad", storage))
    _check_case(
        dbg,
        "postpone_custom_invalid_contract_failed",
        "postpone_custom_invalid",
        res,
        expect_show_alert=True,
        expect_text="❌ Invalid postpone data",
    )

    # prealert_info invalid payload
    storage = _StorageStub()
    res = run_async(_run_handler(handle_prealert_info, "preinfo_bad", storage))
    _check_case(
        dbg,
        "prealert_info_invalid_contract_failed",
        "prealert_info_invalid",
        res,
        expect_show_alert=True,
        expect_text="❌ Invalid data",
    )

    # prealert_info missing alert
    storage = _StorageStub()
    callback = f"preinfo_missing_{ts}_{ts}"
    res = run_async(_run_handler(handle_prealert_info, callback, storage))
    _check_case(
        dbg,
        "prealert_info_missing_alert_contract_failed",
        "prealert_info_missing_alert",
        res,
        expect_show_alert=True,
        expect_text="❌ Item not found",
        extra_checks={
            "reply_markup_cleared": len(res["query"].edit_reply_markup_calls) == 1,
        },
    )

    # alert_info invalid payload
    storage = _StorageStub()
    res = run_async(_run_handler(handle_alert_info, "ainfo_bad", storage))
    _check_case(
        dbg,
        "alert_info_invalid_contract_failed",
        "alert_info_invalid",
        res,
        expect_show_alert=True,
        expect_text="❌ Invalid data",
    )

    # alert_info missing alert
    storage = _StorageStub()
    callback = f"ainfo_missing_{ts}_{ts}"
    res = run_async(_run_handler(handle_alert_info, callback, storage))
    _check_case(
        dbg,
        "alert_info_missing_alert_contract_failed",
        "alert_info_missing_alert",
        res,
        expect_show_alert=True,
        expect_text="❌ Item not found",
        extra_checks={
            "reply_markup_cleared": len(res["query"].edit_reply_markup_calls) == 1,
        },
    )

    # notif_back invalid payload
    storage = _StorageStub()
    res = run_async(_run_handler(handle_notif_back, "nback_bad", storage))
    _check_case(
        dbg,
        "notif_back_invalid_contract_failed",
        "notif_back_invalid",
        res,
        expect_show_alert=True,
        expect_text="❌ Invalid data",
    )

    # notif_back missing alert
    storage = _StorageStub()
    callback = f"{C.CB_NOTIF_BACK}due_missing_{ts}_{ts}"
    res = run_async(_run_handler(handle_notif_back, callback, storage))
    _check_case(
        dbg,
        "notif_back_missing_alert_contract_failed",
        "notif_back_missing_alert",
        res,
        expect_show_alert=True,
        expect_text="❌ Alert not found",
    )

    # notif_back success path
    storage = _StorageStub()
    alert_id = "notif_back_01"
    storage.alerts[alert_id] = {
        "id": alert_id,
        "title": "Test alert",
        "type": 3,
        "schedule": {"time": "10:00"},
        "next_scheduled": datetime(2026, 3, 10, 10, 0, 0).isoformat(),
    }
    callback = f"{C.CB_NOTIF_BACK}due_{alert_id}_{ts}_{ts}"
    res = run_async(_run_handler(handle_notif_back, callback, storage))
    _check_case(
        dbg,
        "notif_back_success_contract_failed",
        "notif_back_success",
        res,
        expect_show_alert=False,
        extra_checks={
            "bot_restore_single_edit": (
                len(res["context"].bot.edit_text_calls) + len(res["context"].bot.edit_caption_calls)
            ) == 1,
            "query_message_not_edited": (
                len(res["query"].edit_text_calls) == 0 and len(res["query"].edit_caption_calls) == 0
            ),
        },
    )

    # alert_toggle missing alert
    storage = _StorageStub()
    callback = f"{C.CB_ALERT_TOGGLE}missing"
    res = run_async(_run_handler(handle_alert_toggle, callback, storage))
    _check_case(
        dbg,
        "alert_toggle_missing_contract_failed",
        "alert_toggle_missing",
        res,
        expect_show_alert=True,
        expect_text="❌ Alert not found",
    )

    # birthday noted missing alert
    storage = _StorageStub()
    callback = build_bday_noted_callback("missing", datetime(2026, 3, 10, 10, 0, 0), datetime(2026, 3, 10, 10, 0, 0))
    res = run_async(_run_handler(handle_bday_noted, callback, storage))
    _check_case(
        dbg,
        "bday_noted_missing_contract_failed",
        "bday_noted_missing",
        res,
        expect_show_alert=True,
        expect_text="Alert not found",
    )

    # birthday noted success path
    storage = _StorageStub()
    alert_id = "bday1"
    storage.alerts[alert_id] = {
        "id": alert_id,
        "title": "Birthday",
        "type": 6,
    }
    callback = build_bday_noted_callback(alert_id, datetime(2026, 3, 10, 10, 0, 0), datetime(2026, 3, 10, 10, 0, 0))
    res = run_async(_run_handler(handle_bday_noted, callback, storage))
    _check_case(
        dbg,
        "bday_noted_success_contract_failed",
        "bday_noted_success",
        res,
        expect_show_alert=False,
        extra_checks={
            "prompt_message_sent": len(res["context"].bot.sent_messages) == 1,
        },
    )

    # bday_msg_style malformed payload
    storage = _StorageStub()
    callback = f"{C.CB_BDAY_MSG}zz"
    res = run_async(_run_handler(handle_bday_msg_style, callback, storage))
    _check_case(
        dbg,
        "bday_msg_style_malformed_contract_failed",
        "bday_msg_style_malformed",
        res,
        expect_show_alert=True,
        expect_text="⚠️ This birthday action is no longer valid.",
    )

    # bday_msg_style invalid style
    storage = _StorageStub()
    alert_id = "bday_invalid_style"
    storage.alerts[alert_id] = {"id": alert_id, "title": "Birthday", "type": 6}
    callback = build_bday_msg_callback("alien", alert_id, datetime(2026, 3, 10, 10, 0, 0))
    res = run_async(_run_handler(handle_bday_msg_style, callback, storage))
    _check_case(
        dbg,
        "bday_msg_style_invalid_style_contract_failed",
        "bday_msg_style_invalid_style",
        res,
        expect_show_alert=True,
        expect_text="⚠️ Unsupported style.",
    )

    # bday_msg_style wrong type
    storage = _StorageStub()
    alert_id = "bday_wrong_type"
    storage.alerts[alert_id] = {"id": alert_id, "title": "Not birthday", "type": 3}
    callback = build_bday_msg_callback("polite", alert_id, datetime(2026, 3, 10, 10, 0, 0))
    res = run_async(_run_handler(handle_bday_msg_style, callback, storage))
    _check_case(
        dbg,
        "bday_msg_style_wrong_type_contract_failed",
        "bday_msg_style_wrong_type",
        res,
        expect_show_alert=True,
        expect_text="⚠️ This callback is only valid for birthdays.",
    )

    # bday_msg_style success (user decline)
    storage = _StorageStub()
    alert_id = "bday_no_style"
    storage.alerts[alert_id] = {"id": alert_id, "title": "Birthday", "type": 6}
    callback = build_bday_msg_callback("no", alert_id, datetime(2026, 3, 10, 10, 0, 0))
    res = run_async(_run_handler(handle_bday_msg_style, callback, storage))
    _check_case(
        dbg,
        "bday_msg_style_no_contract_failed",
        "bday_msg_style_no",
        res,
        expect_show_alert=False,
        extra_checks={
            "sent_confirmation_once": len(res["context"].bot.sent_messages) == 1,
        },
    )

    # legacy alert_done not-found path
    storage = _StorageStub()
    callback = f"{C.CB_ALERT_DONE}missing"
    res = run_async(_run_handler(handle_alert_done, callback, storage))
    _check_case(
        dbg,
        "alert_done_not_found_contract_failed",
        "alert_done_not_found",
        res,
        expect_show_alert=False,
        extra_checks={
            "edited_text_once": len(res["query"].edit_text_calls) == 1,
        },
    )

    # legacy alert_done failure path
    storage = _StorageStub()
    alert_id = "done1"
    storage.alerts[alert_id] = {
        "id": alert_id,
        "title": "Test",
        "type": 3,
    }
    callback = f"{C.CB_ALERT_DONE}{alert_id}"

    async def _mark_done_fail(user_id, callback_alert_id, storage=None):
        return False, False, None

    res = run_async(_run_handler(handle_alert_done, callback, storage, patch_mark_done=_mark_done_fail))
    _check_case(
        dbg,
        "alert_done_failure_contract_failed",
        "alert_done_failure",
        res,
        expect_show_alert=True,
        expect_text="❌ Error marking alert as done",
    )

    # legacy alert_done success path (regular ack)
    storage = _StorageStub()
    alert_id = "done2"
    storage.alerts[alert_id] = {
        "id": alert_id,
        "title": "Test",
        "type": 3,
    }
    callback = f"{C.CB_ALERT_DONE}{alert_id}"

    async def _mark_done_success(user_id, callback_alert_id, storage=None):
        return True, False, datetime(2026, 4, 1, 10, 0, 0)

    res = run_async(_run_handler(handle_alert_done, callback, storage, patch_mark_done=_mark_done_success))
    _check_case(
        dbg,
        "alert_done_success_contract_failed",
        "alert_done_success",
        res,
        expect_show_alert=False,
        extra_checks={
            "edited_text_once": len(res["query"].edit_text_calls) == 1,
        },
    )


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        _run_contract_checks(dbg)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem(
        "postpone_menu_invalid_contract_failed",
        "postpone_set_invalid_contract_failed",
        "postpone_set_missing_alert_contract_failed",
        "postpone_custom_invalid_contract_failed",
        "prealert_info_invalid_contract_failed",
        "prealert_info_missing_alert_contract_failed",
        "alert_info_invalid_contract_failed",
        "alert_info_missing_alert_contract_failed",
        "notif_back_invalid_contract_failed",
        "notif_back_missing_alert_contract_failed",
        "notif_back_success_contract_failed",
        "alert_toggle_missing_contract_failed",
        "bday_noted_missing_contract_failed",
        "bday_noted_success_contract_failed",
        "bday_msg_style_malformed_contract_failed",
        "bday_msg_style_invalid_style_contract_failed",
        "bday_msg_style_wrong_type_contract_failed",
        "bday_msg_style_no_contract_failed",
        "alert_done_not_found_contract_failed",
        "alert_done_failure_contract_failed",
        "alert_done_success_contract_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"callback-answer-contract: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
