#!/usr/bin/env python3
import asyncio
import os
import sys
import types
from datetime import datetime


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
SCRIPT_TITLE = "add_flow_debug"
FEATURE_TITLE = "Add Flow"


def _pattern_text(pattern):
    if isinstance(pattern, str):
        return pattern
    return getattr(pattern, "pattern", None)


class _DummyMessage:
    def __init__(self):
        self.replies = []
        self.text = None

    async def reply_text(self, text, **kwargs):
        payload = {"text": text, "kwargs": kwargs}
        self.replies.append(payload)
        return types.SimpleNamespace(message_id=1001)


_UNSET = object()


class _DummyCallbackQuery:
    def __init__(self, message=_UNSET):
        self.answered = False
        self.message = _DummyMessage() if message is _UNSET else message
        self.edits = []

    async def answer(self, *args, **kwargs):
        self.answered = True

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        payload = {"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode}
        self.edits.append(payload)
        return self.message

    async def edit_message_caption(self, caption, reply_markup=None, parse_mode=None):
        payload = {"caption": caption, "reply_markup": reply_markup, "parse_mode": parse_mode}
        self.edits.append(payload)
        return self.message


class _DummyUpdate:
    def __init__(self, with_callback=False):
        self.message = _DummyMessage()
        self.effective_chat = types.SimpleNamespace(id=1001)
        self.callback_query = _DummyCallbackQuery() if with_callback else None


class _DummyBot:
    def __init__(self):
        self.delete_calls = []

    async def delete_message(self, *, chat_id, message_id):
        self.delete_calls.append({"chat_id": chat_id, "message_id": message_id})


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot = _DummyBot()


def _extract_inline_rows(reply_markup):
    rows = []
    for row in getattr(reply_markup, "inline_keyboard", []) or []:
        labels = []
        callbacks = []
        for button in row:
            labels.append(getattr(button, "text", None))
            callbacks.append(getattr(button, "callback_data", None))
        rows.append({"labels": labels, "callbacks": callbacks})
    return rows


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.handlers import add_alert
            from modules import constants as C
            from modules.handlers.add_flow import summary_flow as summary_flow_mod
            from modules.handlers.add_flow import settings_flow as settings_flow_mod
            from modules.handlers.add_flow.keyboards import (
                build_change_type_keyboard,
                build_type_keyboard,
            )
            from modules.handlers.add_flow.summary_flow import (
                ensure_default_settings,
                format_alert_summary,
            )
            from modules.handlers.edit_flow.dashboard import (
                build_edit_dashboard_keyboard,
                format_edit_dashboard_text,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        handler = getattr(add_alert, "add_alert_handler", None)
        per_message = getattr(handler, "per_message", None)
        entry_points = getattr(handler, "entry_points", None)
        states = getattr(handler, "states", None)

        has_entry = False
        if entry_points:
            for entry in entry_points:
                pattern = _pattern_text(getattr(entry, "pattern", None))
                if pattern and pattern == "^alert_add$":
                    has_entry = True
                    break

        has_select_type = False
        state_handlers = (states or {}).get(C.SELECT_TYPE, [])
        for state_handler in state_handlers:
            pattern = _pattern_text(getattr(state_handler, "pattern", None))
            if pattern and pattern == f"^{C.CB_TYPE}":
                has_select_type = True
                break

        has_change_type_state = False
        change_state_handlers = (states or {}).get(C.CHANGE_ALERT_TYPE, [])
        for state_handler in change_state_handlers:
            pattern = _pattern_text(getattr(state_handler, "pattern", None))
            if pattern and pattern == "^ct_":
                has_change_type_state = True
                break
        additional_info_handlers = (states or {}).get(C.GET_ADDITIONAL_INFO, [])
        additional_info_patterns = {
            _pattern_text(getattr(state_handler, "pattern", None))
            for state_handler in additional_info_handlers
        }
        has_additional_info_skip = "^info_skip$" in additional_info_patterns
        has_additional_info_clear = "^info_clear$" in additional_info_patterns

        dbg.section("config", {
            "per_message": per_message,
            "has_alert_add_entry": has_entry,
            "has_select_type_state": has_select_type,
            "has_change_type_state": has_change_type_state,
            "has_additional_info_skip_callback": has_additional_info_skip,
            "has_additional_info_clear_callback": has_additional_info_clear,
            "additional_info_patterns": sorted(p for p in additional_info_patterns if p),
        })

        if per_message is not False:
            dbg.problem("per_message_must_be_false", {"per_message": per_message})
        if not has_entry:
            dbg.problem("missing_alert_add_entry")
        if not has_select_type:
            dbg.problem("missing_select_type_state")
        if not has_change_type_state:
            dbg.problem("missing_change_type_state")
        if not has_additional_info_skip:
            dbg.problem("missing_additional_info_skip_callback")
        if not has_additional_info_clear:
            dbg.problem("missing_additional_info_clear_callback")

        keyboard = build_type_keyboard()
        rows = getattr(keyboard, "inline_keyboard", None)
        row_callbacks = []
        row_labels = []
        if rows is not None:
            try:
                rows = list(rows)
            except TypeError:
                rows = None
        if isinstance(rows, list):
            for row in rows:
                try:
                    items = list(row)
                except TypeError:
                    items = []
                row_callbacks.append([
                    getattr(btn, "callback_data", None) for btn in items
                ])
                row_labels.append([
                    getattr(btn, "text", None) for btn in items
                ])
        expected = [
            [f"{C.CB_TYPE}7", f"{C.CB_TYPE}3"],
            [f"{C.CB_TYPE}1"],
            [f"{C.CB_TYPE}2"],
            [f"{C.CB_TYPE}4", f"{C.CB_TYPE}5"],
        ]
        expected_labels = [
            ["Daily", "Weekly"],
            ["Monthly (Specific Day)"],
            ["Monthly (Relative Day)"],
            ["Yearly", "One Time"],
        ]
        layout_checks = {
            "keyboard_rows": isinstance(rows, list) and len(rows) == 4,
            "row_0": len(row_callbacks) > 0 and row_callbacks[0] == expected[0],
            "row_1": len(row_callbacks) > 1 and row_callbacks[1] == expected[1],
            "row_2": len(row_callbacks) > 2 and row_callbacks[2] == expected[2],
            "row_3": len(row_callbacks) > 3 and row_callbacks[3] == expected[3],
            "labels_row_0": len(row_labels) > 0 and row_labels[0] == expected_labels[0],
            "labels_row_1": len(row_labels) > 1 and row_labels[1] == expected_labels[1],
            "labels_row_2": len(row_labels) > 2 and row_labels[2] == expected_labels[2],
            "labels_row_3": len(row_labels) > 3 and row_labels[3] == expected_labels[3],
        }
        dbg.section("type_keyboard_layout", {
            "rows": row_callbacks,
            "labels": row_labels,
            "expected": expected,
            "expected_labels": expected_labels,
            "checks": layout_checks,
        })
        if not all(layout_checks.values()):
            dbg.problem("type_keyboard_layout_failed", {"checks": layout_checks})

        change_keyboard = build_change_type_keyboard()
        change_rows = getattr(change_keyboard, "inline_keyboard", None)
        change_callbacks = []
        change_labels = []
        if change_rows is not None:
            try:
                change_rows = list(change_rows)
            except TypeError:
                change_rows = None
        if isinstance(change_rows, list):
            for row in change_rows:
                try:
                    items = list(row)
                except TypeError:
                    items = []
                change_callbacks.append([
                    getattr(btn, "callback_data", None) for btn in items
                ])
                change_labels.append([
                    getattr(btn, "text", None) for btn in items
                ])
        expected_change = [
            ["ct_7", "ct_3"],
            ["ct_1"],
            ["ct_2"],
            ["ct_4", "ct_5"],
            ["ct_back"],
        ]
        expected_change_labels = [
            ["Daily", "Weekly"],
            ["Monthly (Specific Day)"],
            ["Monthly (Relative Day)"],
            ["Yearly", "One Time"],
            ["⬅️ Back"],
        ]
        flat_change_callbacks = [
            callback
            for row in change_callbacks
            for callback in row
            if isinstance(callback, str)
        ]
        change_layout_checks = {
            "change_keyboard_rows": isinstance(change_rows, list) and len(change_rows) == 5,
            "change_row_0": len(change_callbacks) > 0 and change_callbacks[0] == expected_change[0],
            "change_row_1": len(change_callbacks) > 1 and change_callbacks[1] == expected_change[1],
            "change_row_2": len(change_callbacks) > 2 and change_callbacks[2] == expected_change[2],
            "change_row_3": len(change_callbacks) > 3 and change_callbacks[3] == expected_change[3],
            "change_row_4": len(change_callbacks) > 4 and change_callbacks[4] == expected_change[4],
            "change_labels_row_0": len(change_labels) > 0 and change_labels[0] == expected_change_labels[0],
            "change_labels_row_1": len(change_labels) > 1 and change_labels[1] == expected_change_labels[1],
            "change_labels_row_2": len(change_labels) > 2 and change_labels[2] == expected_change_labels[2],
            "change_labels_row_3": len(change_labels) > 3 and change_labels[3] == expected_change_labels[3],
            "change_labels_row_4": len(change_labels) > 4 and change_labels[4] == expected_change_labels[4],
            "exclude_birthday": "ct_6" not in flat_change_callbacks,
            "exclude_empty": "ct_8" not in flat_change_callbacks,
        }
        dbg.section("change_type_keyboard_layout", {
            "rows": change_callbacks,
            "labels": change_labels,
            "expected": expected_change,
            "expected_labels": expected_change_labels,
            "checks": change_layout_checks,
        })
        if not all(change_layout_checks.values()):
            dbg.problem("change_type_keyboard_layout_failed", {"checks": change_layout_checks})

        prompt_update = _DummyUpdate(with_callback=False)
        prompt_context = _DummyContext()
        prompt_state = asyncio.run(settings_flow_mod.prompt_additional_info(prompt_update, prompt_context))
        prompt_replies = getattr(prompt_update.message, "replies", []) or []
        first_prompt_reply = prompt_replies[0] if prompt_replies else {}
        prompt_markup = first_prompt_reply.get("kwargs", {}).get("reply_markup")
        prompt_rows = _extract_inline_rows(prompt_markup)
        prompt_labels = [row.get("labels", []) for row in prompt_rows]
        prompt_callbacks = [row.get("callbacks", []) for row in prompt_rows]
        additional_info_prompt_checks = {
            "state_is_get_additional_info": prompt_state == C.GET_ADDITIONAL_INFO,
            "single_row": len(prompt_rows) == 1,
            "two_buttons_in_row": len(prompt_callbacks) > 0 and len(prompt_callbacks[0]) == 2,
            "cancel_button": (
                len(prompt_labels) > 0
                and prompt_labels[0][0] == "❌ Cancel this operation"
                and prompt_callbacks[0][0] == "info_skip"
            ),
            "clear_button": (
                len(prompt_labels) > 0
                and prompt_labels[0][1] == "🗑️ Clear present text"
                and prompt_callbacks[0][1] == "info_clear"
            ),
        }
        dbg.section("additional_info_prompt", {
            "prompt_state": prompt_state,
            "reply_count": len(prompt_replies),
            "prompt_labels": prompt_labels,
            "prompt_callbacks": prompt_callbacks,
            "checks": additional_info_prompt_checks,
        })
        if not all(additional_info_prompt_checks.values()):
            dbg.problem("additional_info_prompt_failed", {"checks": additional_info_prompt_checks})

        clear_update = _DummyUpdate(with_callback=True)
        clear_context = _DummyContext()
        clear_context.user_data["temp_alert"] = {"additional_info": "Persist me"}
        clear_delegate_calls = {"count": 0}

        async def _fake_return_to_settings(update, context):
            clear_delegate_calls["count"] += 1
            return C.MULTI_SETTINGS

        clear_result = asyncio.run(
            settings_flow_mod.handle_additional_info_clear(
                clear_update,
                clear_context,
                _fake_return_to_settings,
            )
        )
        additional_info_clear_checks = {
            "callback_answered": bool(getattr(clear_update.callback_query, "answered", False)),
            "additional_info_cleared": (
                clear_context.user_data.get("temp_alert", {}).get("additional_info") == ""
            ),
            "delegate_called_once": clear_delegate_calls["count"] == 1,
            "delegate_result_passthrough": clear_result == C.MULTI_SETTINGS,
        }
        dbg.section("additional_info_clear", {
            "clear_result": clear_result,
            "delegate_calls": clear_delegate_calls["count"],
            "temp_alert": clear_context.user_data.get("temp_alert"),
            "checks": additional_info_clear_checks,
        })
        if not all(additional_info_clear_checks.values()):
            dbg.problem("additional_info_clear_failed", {"checks": additional_info_clear_checks})

        copy_lifecycle_checks = {}

        # callback-path: copy sent when text is present (stores id, preserves raw text, no parse_mode)
        cb_ctx = _DummyContext()
        cb_ctx.user_data["temp_alert"] = {"additional_info": "Existing note  "}
        cb_update = _DummyUpdate(with_callback=True)
        asyncio.run(settings_flow_mod.prompt_additional_info(cb_update, cb_ctx))
        cb_cq_replies = cb_update.callback_query.message.replies
        cb_last_reply = cb_cq_replies[-1] if cb_cq_replies else {}
        copy_lifecycle_checks["cb_copy_sent"] = len(cb_cq_replies) >= 1
        copy_lifecycle_checks["cb_copy_has_label"] = "Current text:\n" in (cb_last_reply.get("text") or "")
        copy_lifecycle_checks["cb_raw_preserved_no_strip"] = "Existing note  " in (cb_last_reply.get("text") or "")
        copy_lifecycle_checks["cb_no_parse_mode"] = (cb_last_reply.get("kwargs") or {}).get("parse_mode") is None
        copy_lifecycle_checks["cb_msg_id_stored"] = cb_ctx.user_data.get("additional_info_copy_msg_id") == 1001

        # callback-path: no copy when text is empty
        empty_cb_ctx = _DummyContext()
        empty_cb_ctx.user_data["temp_alert"] = {"additional_info": ""}
        empty_cb_update = _DummyUpdate(with_callback=True)
        asyncio.run(settings_flow_mod.prompt_additional_info(empty_cb_update, empty_cb_ctx))
        copy_lifecycle_checks["no_copy_when_empty"] = len(empty_cb_update.callback_query.message.replies) == 0
        copy_lifecycle_checks["no_msg_id_when_empty"] = "additional_info_copy_msg_id" not in empty_cb_ctx.user_data

        # callback-path: copy skipped silently when callback_query.message is None
        none_msg_cq = _DummyCallbackQuery(message=None)
        none_msg_update = _DummyUpdate(with_callback=True)
        none_msg_update.callback_query = none_msg_cq
        none_msg_ctx = _DummyContext()
        none_msg_ctx.user_data["temp_alert"] = {"additional_info": "Has text"}
        asyncio.run(settings_flow_mod.prompt_additional_info(none_msg_update, none_msg_ctx))
        copy_lifecycle_checks["no_copy_when_cq_msg_none"] = "additional_info_copy_msg_id" not in none_msg_ctx.user_data

        async def _fake_return_fn(_update, _context):
            return C.MULTI_SETTINGS

        # cleanup on skip
        skip_ctx = _DummyContext()
        skip_ctx.user_data["additional_info_copy_msg_id"] = 1001
        skip_ctx.user_data["temp_alert"] = {}
        skip_update = _DummyUpdate(with_callback=True)
        asyncio.run(settings_flow_mod.handle_additional_info_skip(skip_update, skip_ctx, _fake_return_fn))
        copy_lifecycle_checks["skip_clears_key"] = "additional_info_copy_msg_id" not in skip_ctx.user_data
        copy_lifecycle_checks["skip_delete_attempted"] = len(skip_ctx.bot.delete_calls) == 1
        copy_lifecycle_checks["skip_delete_correct_id"] = (
            (skip_ctx.bot.delete_calls[0]["message_id"] == 1001) if skip_ctx.bot.delete_calls else False
        )

        # cleanup on clear
        clear2_ctx = _DummyContext()
        clear2_ctx.user_data["additional_info_copy_msg_id"] = 1002
        clear2_ctx.user_data["temp_alert"] = {"additional_info": "Old text"}
        clear2_update = _DummyUpdate(with_callback=True)
        asyncio.run(settings_flow_mod.handle_additional_info_clear(clear2_update, clear2_ctx, _fake_return_fn))
        copy_lifecycle_checks["clear_clears_key"] = "additional_info_copy_msg_id" not in clear2_ctx.user_data
        copy_lifecycle_checks["clear_delete_attempted"] = len(clear2_ctx.bot.delete_calls) == 1
        copy_lifecycle_checks["clear_delete_correct_id"] = (
            (clear2_ctx.bot.delete_calls[0]["message_id"] == 1002) if clear2_ctx.bot.delete_calls else False
        )

        # cleanup on successful input
        input_ctx = _DummyContext()
        input_ctx.user_data["additional_info_copy_msg_id"] = 1003
        input_ctx.user_data["temp_alert"] = {}
        input_update = _DummyUpdate(with_callback=False)
        input_update.message.text = "Valid info text"
        asyncio.run(settings_flow_mod.handle_additional_info_input(input_update, input_ctx, _fake_return_fn))
        copy_lifecycle_checks["input_clears_key"] = "additional_info_copy_msg_id" not in input_ctx.user_data
        copy_lifecycle_checks["input_delete_attempted"] = len(input_ctx.bot.delete_calls) == 1
        copy_lifecycle_checks["input_delete_correct_id"] = (
            (input_ctx.bot.delete_calls[0]["message_id"] == 1003) if input_ctx.bot.delete_calls else False
        )

        # copy-message retained on too-long input (validation failure path must not delete)
        toolong_ctx = _DummyContext()
        toolong_ctx.user_data["additional_info_copy_msg_id"] = 1004
        toolong_ctx.user_data["temp_alert"] = {}
        toolong_update = _DummyUpdate(with_callback=False)
        toolong_update.message.text = "x" * (C.ADDITIONAL_INFO_MAX_LEN + 1)
        toolong_state = asyncio.run(
            settings_flow_mod.handle_additional_info_input(toolong_update, toolong_ctx, _fake_return_fn)
        )
        copy_lifecycle_checks["toolong_key_retained"] = "additional_info_copy_msg_id" in toolong_ctx.user_data
        copy_lifecycle_checks["toolong_state_stays_input"] = toolong_state == C.GET_ADDITIONAL_INFO
        copy_lifecycle_checks["toolong_no_delete_attempt"] = len(toolong_ctx.bot.delete_calls) == 0

        # add-flow /cancel cleanup
        original_end_conv_add = getattr(add_alert, "end_registered_conversations", None)
        add_alert_end_conv_calls = []

        def _mock_add_cancel_end_conv(_update):
            add_alert_end_conv_calls.append(True)

        if hasattr(add_alert, "end_registered_conversations"):
            add_alert.end_registered_conversations = _mock_add_cancel_end_conv
        try:
            cancel_ctx = _DummyContext()
            cancel_ctx.user_data["additional_info_copy_msg_id"] = 1005
            cancel_ctx.user_data["temp_alert"] = {}
            cancel_update = _DummyUpdate(with_callback=False)
            asyncio.run(add_alert.cancel(cancel_update, cancel_ctx))
        finally:
            if original_end_conv_add is not None:
                add_alert.end_registered_conversations = original_end_conv_add
        copy_lifecycle_checks["cancel_clears_key"] = "additional_info_copy_msg_id" not in cancel_ctx.user_data
        copy_lifecycle_checks["cancel_delete_attempted"] = len(cancel_ctx.bot.delete_calls) == 1
        copy_lifecycle_checks["cancel_delete_correct_id"] = (
            (cancel_ctx.bot.delete_calls[0]["message_id"] == 1005) if cancel_ctx.bot.delete_calls else False
        )
        copy_lifecycle_checks["cancel_sends_reply"] = any(
            "Cancelled" in (r.get("text") or "") for r in cancel_update.message.replies
        )

        dbg.section("additional_info_copy_lifecycle", {"checks": copy_lifecycle_checks})
        if not all(copy_lifecycle_checks.values()):
            dbg.problem("additional_info_copy_lifecycle_failed", {"checks": copy_lifecycle_checks})

        def _flatten_callbacks(markup):
            callbacks = []
            rows = getattr(markup, "inline_keyboard", []) or []
            for row in rows:
                for btn in row:
                    callbacks.append(getattr(btn, "callback_data", None))
            return callbacks

        weekly_callbacks = _flatten_callbacks(build_edit_dashboard_keyboard(3))
        one_time_callbacks = _flatten_callbacks(build_edit_dashboard_keyboard(5))
        birthday_callbacks = _flatten_callbacks(build_edit_dashboard_keyboard(6))
        edit_keyboard_checks = {
            "weekly_has_change_type": "ed_change_type" in weekly_callbacks,
            "weekly_has_interval": "ed_interval" in weekly_callbacks,
            "weekly_has_time": "ed_time" in weekly_callbacks,
            "one_time_no_interval": "ed_interval" not in one_time_callbacks,
            "one_time_has_time": "ed_time" in one_time_callbacks,
            "birthday_no_change_type": "ed_change_type" not in birthday_callbacks,
            "birthday_no_interval": "ed_interval" not in birthday_callbacks,
            "birthday_no_time": "ed_time" not in birthday_callbacks,
        }
        dbg.section("edit_dashboard_keyboard", {
            "weekly_callbacks": weekly_callbacks,
            "one_time_callbacks": one_time_callbacks,
            "birthday_callbacks": birthday_callbacks,
            "checks": edit_keyboard_checks,
        })
        if not all(edit_keyboard_checks.values()):
            dbg.problem("edit_dashboard_keyboard_failed", {"checks": edit_keyboard_checks})

        edit_text = format_edit_dashboard_text({
            "title": "Unsafe *[title",
            "type": 3,
            "type_name": "Weekly_[raw]",
            "schedule": {"interval": 2, "time": "08:30"},
            "pre_alerts": ["1d"],
            "additional_info": "Raw *[info]",
            "tags": ["🏠 Home"],
            "image_id": None,
        })
        birthday_text = format_edit_dashboard_text({
            "title": "Bday",
            "type": 6,
            "type_name": "Birthday",
            "schedule": {"time": "08:00"},
            "pre_alerts": [],
            "additional_info": "",
            "tags": [],
            "image_id": None,
        })
        edit_text_checks = {
            "escape_title": "Unsafe \\*\\[title" in edit_text,
            "escape_info": "Raw \\*\\[info" in edit_text,
            "repetition_shown_for_weekly": "• Repetition: Forever" in edit_text,
            "birthday_omits_interval": "• Interval:" not in birthday_text,
            "birthday_omits_time": "• Time:" not in birthday_text,
            "birthday_omits_repetition": "• Repetition:" not in birthday_text,
        }
        dbg.section("edit_dashboard_text", {
            "edit_text": edit_text,
            "birthday_text": birthday_text,
            "checks": edit_text_checks,
        })
        if not all(edit_text_checks.values()):
            dbg.problem("edit_dashboard_text_failed", {"checks": edit_text_checks})

        recurring_payload = {
            "title": "Recurring repetition default",
            "type": 3,
            "type_name": "Weekly",
            "schedule": {"weekdays": ["Mon"], "time": "09:00"},
            "pre_alerts": [],
            "tags": [],
            "additional_info": "",
            "image_id": None,
        }
        recurring_until_payload = {
            "title": "Recurring until date",
            "type": 3,
            "type_name": "Weekly",
            "schedule": {"weekdays": ["Mon"], "time": "09:00"},
            "pre_alerts": [],
            "tags": [],
            "additional_info": "",
            "image_id": None,
            "repetition": {"mode": C.REPETITION_MODE_UNTIL_DATE, "until_date": "31/12/2027"},
        }
        recurring_count_payload = {
            "title": "Recurring count",
            "type": 3,
            "type_name": "Weekly",
            "schedule": {"weekdays": ["Mon"], "time": "09:00"},
            "pre_alerts": [],
            "tags": [],
            "additional_info": "",
            "image_id": None,
            "repetition": {"mode": C.REPETITION_MODE_COUNT, "count_remaining": 2},
        }
        one_time_payload = {
            "title": "One-time no repetition",
            "type": 5,
            "type_name": "One Time",
            "schedule": {"date": "10/10/2027", "time": "09:00"},
            "pre_alerts": [],
            "tags": [],
            "additional_info": "",
            "image_id": None,
            "repetition": {"mode": C.REPETITION_MODE_COUNT, "count_remaining": 3},
        }
        birthday_payload = {
            "title": "Birthday no repetition",
            "type": 6,
            "type_name": "Birthday",
            "schedule": {"date": "10/10", "time": "08:00"},
            "pre_alerts": [],
            "tags": [],
            "additional_info": "",
            "image_id": None,
            "repetition": {"mode": C.REPETITION_MODE_UNTIL_DATE, "until_date": "31/12/2027"},
        }

        ensure_default_settings(recurring_payload)
        ensure_default_settings(recurring_until_payload)
        ensure_default_settings(recurring_count_payload)
        ensure_default_settings(one_time_payload)
        ensure_default_settings(birthday_payload)
        recurring_summary = format_alert_summary(recurring_payload)
        recurring_until_summary = format_alert_summary(recurring_until_payload)
        recurring_count_summary = format_alert_summary(recurring_count_payload)
        one_time_summary = format_alert_summary(one_time_payload)
        birthday_summary = format_alert_summary(birthday_payload)

        repetition_checks = {
            "recurring_default_created": isinstance(recurring_payload.get("repetition"), dict),
            "recurring_default_forever": recurring_payload.get("repetition", {}).get("mode") == C.REPETITION_MODE_FOREVER,
            "recurring_until_preserved": recurring_until_payload.get("repetition", {}).get("mode") == C.REPETITION_MODE_UNTIL_DATE,
            "recurring_count_preserved": recurring_count_payload.get("repetition", {}).get("mode") == C.REPETITION_MODE_COUNT,
            "one_time_repetition_removed": "repetition" not in one_time_payload,
            "birthday_repetition_removed": "repetition" not in birthday_payload,
            "recurring_summary_shows_repetition": "**Repetition:** `Forever`" in recurring_summary,
            "recurring_until_summary": "**Repetition:** `Until 31/12/2027 (inclusive)`" in recurring_until_summary,
            "recurring_count_summary": "**Repetition:** `Next 2 events`" in recurring_count_summary,
            "one_time_summary_hides_repetition": "**Repetition:**" not in one_time_summary,
            "birthday_summary_hides_repetition": "**Repetition:**" not in birthday_summary,
        }
        dbg.section("summary_repetition_contract", {
            "recurring_payload": recurring_payload,
            "recurring_until_payload": recurring_until_payload,
            "recurring_count_payload": recurring_count_payload,
            "one_time_payload": one_time_payload,
            "birthday_payload": birthday_payload,
            "recurring_summary": recurring_summary,
            "recurring_until_summary": recurring_until_summary,
            "recurring_count_summary": recurring_count_summary,
            "one_time_summary": one_time_summary,
            "birthday_summary": birthday_summary,
            "checks": repetition_checks,
        })
        if not all(repetition_checks.values()):
            dbg.problem("summary_repetition_contract_failed", {"checks": repetition_checks})

        original_now_server_naive = summary_flow_mod.now_server_naive
        try:
            # Deterministic boundary: server is already next day while user-local is still Monday.
            summary_flow_mod.now_server_naive = lambda: datetime(2026, 1, 6, 0, 30, 0)

            timezone_payload = {
                "title": "Timezone boundary",
                "type": 3,
                "type_name": "Weekly",
                "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "20:00"},
                "pre_alerts": ["1h"],
                "tags": [],
                "additional_info": "",
                "image_id": None,
            }
            user_prefs = {
                "timezone_mode": C.TIMEZONE_MODE_USER,
                "timezone": {"name": "America/New_York"},
            }
            reference_time = datetime(2026, 1, 5, 18, 30, 0)

            pre_default = summary_flow_mod.format_pre_alerts(timezone_payload)
            pre_context = summary_flow_mod.format_pre_alerts(
                timezone_payload,
                user_prefs=user_prefs,
                reference_time=reference_time,
            )
            timezone_summary = format_alert_summary(
                timezone_payload,
                user_prefs=user_prefs,
                reference_time=reference_time,
            )

            context_line = f"**Pre-Alerts:** `{pre_context}`"
            default_line = f"**Pre-Alerts:** `{pre_default}`"
            timezone_checks = {
                "context_differs_from_default": pre_context != pre_default,
                "summary_uses_context_render": context_line in timezone_summary,
                "summary_not_default_render": (
                    default_line not in timezone_summary if pre_context != pre_default else False
                ),
            }
            dbg.section("summary_prealert_timezone_context", {
                "pre_default": pre_default,
                "pre_context": pre_context,
                "reference_time": reference_time.isoformat(sep=" "),
                "timezone_summary": timezone_summary,
                "checks": timezone_checks,
            })
            if not all(timezone_checks.values()):
                dbg.problem("summary_prealert_timezone_context_failed", {"checks": timezone_checks})
        finally:
            summary_flow_mod.now_server_naive = original_now_server_naive
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    dbg.finish(
        summary_lines=["config: FAIL"],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
