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
SCRIPT_TITLE = "add_flow_integration_debug"
FEATURE_TITLE = "Add Flow Integration"


class _DummyMessage:
    def __init__(self, text=None, message_id=100):
        self.text = text
        self.message_id = message_id
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append({
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        })
        return self


class _DummyCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answered = False
        self.edited = []

    async def answer(self, text=None, show_alert=None):
        self.answered = True

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        self.edited.append({
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })


class _DummyUpdate:
    def __init__(self, message=None, callback_query=None, effective_user=None):
        self.message = message
        self.callback_query = callback_query
        self.effective_user = effective_user


class _DummyBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        message = _DummyMessage(text=text, message_id=900 + len(self.sent_messages))
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
            "message": message,
        })
        return message


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot = _DummyBot()


def _extract_callback_rows(reply_markup):
    rows = []
    for row in getattr(reply_markup, "inline_keyboard", []) or []:
        rows.append([getattr(btn, "callback_data", None) for btn in row])
    return rows


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.handlers.add_flow import flow_start
            from modules.handlers import add_alert
            from modules import constants as C
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        context = _DummyContext()
        context.user_data["settings_return"] = "alert"
        context.user_data["daily_interval_confirm_source"] = "interval_text_input"
        start_update = _DummyUpdate(
            message=_DummyMessage(text="/add", message_id=101),
            effective_user=type("User", (), {"id": 42})(),
        )
        start_state = run_async(flow_start.start_add(start_update, context))

        start_checks = {
            "state_get_title": start_state == C.GET_TITLE,
            "temp_alert_initialized": isinstance(context.user_data.get("temp_alert"), dict),
            "settings_return_cleared": "settings_return" not in context.user_data,
            "daily_confirm_source_cleared": "daily_interval_confirm_source" not in context.user_data,
        }
        dbg.section("start_add", {
            "state": start_state,
            "checks": start_checks,
            "temp_alert": context.user_data.get("temp_alert"),
            "add_flow_message_ids": context.user_data.get("add_flow_message_ids"),
            "start_message_id": context.user_data.get("add_flow_start_message_id"),
        })

        if not all(start_checks.values()):
            dbg.problem("start_add_reset_failed", {
                "checks": start_checks,
                "state": start_state,
                "keys_after_start": sorted(context.user_data.keys()),
            })

        title_update = _DummyUpdate(
            message=_DummyMessage(text="Pay rent", message_id=150),
            effective_user=type("User", (), {"id": 42})(),
        )
        title_state = run_async(flow_start.get_title(title_update, context, flow_start.prompt_type_specific))
        title_replies = title_update.message.replies
        title_last = title_replies[-1] if title_replies else {}
        title_rows = _extract_callback_rows(title_last.get("reply_markup"))
        title_checks = {
            "state_select_type": title_state == C.SELECT_TYPE,
            "title_saved": context.user_data.get("temp_alert", {}).get("title") == "Pay rent",
            "type_keyboard_sent": bool(title_replies),
            "type_keyboard_has_type7": any("type_7" in row for row in title_rows),
        }
        dbg.section("get_title", {
            "state": title_state,
            "checks": title_checks,
            "title_rows": title_rows,
        })
        if not all(title_checks.values()):
            dbg.problem("get_title_flow_failed", {
                "state": title_state,
                "checks": title_checks,
                "title_rows": title_rows,
            })

        cb_message = _DummyMessage(message_id=202)
        callback = _DummyCallbackQuery(data=f"{C.CB_TYPE}5", message=cb_message)
        cb_update = _DummyUpdate(callback_query=callback, effective_user=type("User", (), {"id": 42})())
        next_state = run_async(flow_start.select_type(cb_update, context))

        dbg.section("select_type", {
            "state": next_state,
            "type": context.user_data.get("temp_alert", {}).get("type"),
            "type_name": context.user_data.get("temp_alert", {}).get("type_name"),
            "answered": callback.answered,
            "edited_count": len(callback.edited),
        })

        if next_state != C.TYPE_5_DATE:
            dbg.problem("select_type_state_mismatch", {"state": next_state})
        if context.user_data.get("temp_alert", {}).get("type") != 5:
            dbg.problem("type_not_set")
        if context.user_data.get("temp_alert", {}).get("type_name") != C.ALERT_TYPES.get(5):
            dbg.problem("type_name_not_set")
        if not callback.answered:
            dbg.problem("callback_not_answered")
        if not callback.edited:
            dbg.problem("callback_not_edited")

        callback_ctx = _DummyContext()
        callback_ctx.user_data["temp_alert"] = {
            "type": 1,
            "type_name": C.ALERT_TYPES.get(1),
            "schedule": {},
            "pre_alerts": [],
            "tags": [],
        }
        cb_msg = _DummyMessage(message_id=260)
        cb_query = _DummyCallbackQuery(data=f"{C.CB_TYPE}1", message=cb_msg)
        cb_prompt_update = _DummyUpdate(
            callback_query=cb_query,
            effective_user=type("User", (), {"id": 77})(),
        )
        cb_prompt_state = run_async(add_alert.prompt_type_specific(cb_prompt_update, callback_ctx))
        cb_prompt_checks = {
            "callback_prompt_state": cb_prompt_state == C.TYPE_1_DAYS,
            "callback_prompt_edited": len(cb_query.edited) == 1,
        }
        dbg.section("prompt_type_specific_callback_context", {
            "state": cb_prompt_state,
            "edited_count": len(cb_query.edited),
            "checks": cb_prompt_checks,
        })
        if not all(cb_prompt_checks.values()):
            dbg.problem("prompt_type_specific_callback_context_failed", {
                "state": cb_prompt_state,
                "edited_count": len(cb_query.edited),
                "checks": cb_prompt_checks,
            })

        settings_ctx = _DummyContext()
        settings_ctx.user_data["temp_alert"] = {
            "title": "Weekly task",
            "type": 3,
            "type_name": C.ALERT_TYPES.get(3),
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
            "pre_alerts": [],
            "tags": [],
        }
        settings_msg = _DummyMessage(message_id=380)
        settings_query = _DummyCallbackQuery(data="ms_open", message=settings_msg)
        settings_update = _DummyUpdate(
            callback_query=settings_query,
            effective_user=type("User", (), {"id": 100})(),
        )
        settings_state = run_async(add_alert.show_multi_setting_menu(settings_update, settings_ctx))
        settings_payload = settings_query.edited[-1] if settings_query.edited else {}
        settings_markup = settings_payload.get("reply_markup")
        settings_rows = _extract_callback_rows(settings_markup)
        settings_text = settings_payload.get("text") or ""
        settings_checks = {
            "settings_state": settings_state == C.MULTI_SETTINGS,
            "change_type_button_present": len(settings_rows) > 0 and settings_rows[0] == ["ms_change_type"],
            "supported_row_2_interval_time": len(settings_rows) > 1 and settings_rows[1] == ["ms_interval", "ms_time"],
            "supported_row_3_pre_repetition": len(settings_rows) > 2 and settings_rows[2] == ["ms_pre", "ms_repetition"],
            "supported_row_4_photo_info": len(settings_rows) > 3 and settings_rows[3] == ["ms_photo", "ms_info"],
            "supported_row_5_done": len(settings_rows) > 4 and settings_rows[4] == ["ms_done"],
            "supported_text_has_repetition_line": "• Repetition:" in settings_text,
        }
        dbg.section("settings_menu_change_type_button", {
            "state": settings_state,
            "rows": settings_rows,
            "text": settings_text,
            "checks": settings_checks,
        })
        if not all(settings_checks.values()):
            dbg.problem("settings_menu_change_type_button_failed", {
                "state": settings_state,
                "rows": settings_rows,
                "text": settings_text,
                "checks": settings_checks,
            })

        settings_unsupported_ctx = _DummyContext()
        settings_unsupported_ctx.user_data["temp_alert"] = {
            "title": "One-time task",
            "type": 5,
            "type_name": C.ALERT_TYPES.get(5),
            "schedule": {"date": "10/10/2027", "time": "10:00"},
            "pre_alerts": [],
            "tags": [],
        }
        settings_unsupported_msg = _DummyMessage(message_id=381)
        settings_unsupported_query = _DummyCallbackQuery(data="ms_open", message=settings_unsupported_msg)
        settings_unsupported_update = _DummyUpdate(
            callback_query=settings_unsupported_query,
            effective_user=type("User", (), {"id": 100})(),
        )
        settings_unsupported_state = run_async(
            add_alert.show_multi_setting_menu(settings_unsupported_update, settings_unsupported_ctx)
        )
        settings_unsupported_payload = settings_unsupported_query.edited[-1] if settings_unsupported_query.edited else {}
        settings_unsupported_rows = _extract_callback_rows(settings_unsupported_payload.get("reply_markup"))
        settings_unsupported_text = settings_unsupported_payload.get("text") or ""
        unsupported_flat_callbacks = [cb for row in settings_unsupported_rows for cb in row if isinstance(cb, str)]
        settings_unsupported_checks = {
            "unsupported_state": settings_unsupported_state == C.MULTI_SETTINGS,
            "unsupported_row_1_change_type": len(settings_unsupported_rows) > 0 and settings_unsupported_rows[0] == ["ms_change_type"],
            "unsupported_row_2_time_only": len(settings_unsupported_rows) > 1 and settings_unsupported_rows[1] == ["ms_time"],
            "unsupported_row_3_pre_only": len(settings_unsupported_rows) > 2 and settings_unsupported_rows[2] == ["ms_pre"],
            "unsupported_row_4_photo_info": len(settings_unsupported_rows) > 3 and settings_unsupported_rows[3] == ["ms_photo", "ms_info"],
            "unsupported_row_5_done": len(settings_unsupported_rows) > 4 and settings_unsupported_rows[4] == ["ms_done"],
            "unsupported_no_repetition_button": "ms_repetition" not in unsupported_flat_callbacks,
            "unsupported_text_no_repetition_line": "• Repetition:" not in settings_unsupported_text,
        }
        dbg.section("settings_menu_repetition_visibility", {
            "state": settings_unsupported_state,
            "rows": settings_unsupported_rows,
            "text": settings_unsupported_text,
            "checks": settings_unsupported_checks,
        })
        if not all(settings_unsupported_checks.values()):
            dbg.problem("settings_menu_repetition_visibility_failed", {
                "state": settings_unsupported_state,
                "rows": settings_unsupported_rows,
                "text": settings_unsupported_text,
                "checks": settings_unsupported_checks,
            })

        settings_prealert_ctx = _DummyContext()
        settings_prealert_ctx.user_data["temp_alert"] = {
            "title": "Deterministic one-time",
            "type": 5,
            "type_name": C.ALERT_TYPES.get(5),
            "schedule": {"date": "10/03/2099", "time": "10:00"},
            "pre_alerts": ["1h", "30m"],
            "tags": [],
        }
        settings_prealert_msg = _DummyMessage(message_id=382)
        settings_prealert_query = _DummyCallbackQuery(data="ms_open", message=settings_prealert_msg)
        settings_prealert_update = _DummyUpdate(
            callback_query=settings_prealert_query,
            effective_user=type("User", (), {"id": 100})(),
        )
        settings_prealert_state = run_async(
            add_alert.show_multi_setting_menu(settings_prealert_update, settings_prealert_ctx)
        )
        settings_prealert_payload = settings_prealert_query.edited[-1] if settings_prealert_query.edited else {}
        settings_prealert_text = settings_prealert_payload.get("text") or ""
        settings_prealert_checks = {
            "state_multi_settings": settings_prealert_state == C.MULTI_SETTINGS,
            "prealert_has_first_resolved_time": "10/03/2099 09:00" in settings_prealert_text,
            "prealert_has_second_resolved_time": "10/03/2099 09:30" in settings_prealert_text,
        }
        dbg.section("settings_prealert_resolved_render", {
            "state": settings_prealert_state,
            "text": settings_prealert_text,
            "checks": settings_prealert_checks,
        })
        if not all(settings_prealert_checks.values()):
            dbg.problem("settings_prealert_resolved_render_failed", {
                "state": settings_prealert_state,
                "text": settings_prealert_text,
                "checks": settings_prealert_checks,
            })

        settings_unsupported_query.data = "ms_repetition"
        unsupported_repetition_state = run_async(
            add_alert.handle_multi_setting_choice(settings_unsupported_update, settings_unsupported_ctx)
        )
        unsupported_repetition_checks = {
            "unsupported_repetition_state_multi_settings": unsupported_repetition_state == C.MULTI_SETTINGS,
            "unsupported_repetition_answered": settings_unsupported_query.answered is True,
        }
        dbg.section("settings_repetition_unsupported_fallback", {
            "state": unsupported_repetition_state,
            "answered": settings_unsupported_query.answered,
            "checks": unsupported_repetition_checks,
        })
        if not all(unsupported_repetition_checks.values()):
            dbg.problem("settings_repetition_unsupported_fallback_failed", {
                "state": unsupported_repetition_state,
                "answered": settings_unsupported_query.answered,
                "checks": unsupported_repetition_checks,
            })

        settings_query.data = "ms_repetition"
        repetition_menu_state = run_async(add_alert.handle_multi_setting_choice(settings_update, settings_ctx))
        repetition_markup = settings_query.edited[-1]["reply_markup"] if settings_query.edited else None
        repetition_rows = _extract_callback_rows(repetition_markup)
        repetition_flat_callbacks = [
            cb for row in repetition_rows for cb in row if isinstance(cb, str)
        ]
        repetition_menu_checks = {
            "repetition_menu_state": repetition_menu_state == C.GET_REPETITION_MENU,
            "repetition_menu_has_forever": "rep_forever" in repetition_flat_callbacks,
            "repetition_menu_has_until": "rep_until" in repetition_flat_callbacks,
            "repetition_menu_has_count": "rep_count" in repetition_flat_callbacks,
            "repetition_menu_has_back": "rep_back" in repetition_flat_callbacks,
        }
        dbg.section("settings_repetition_menu_route", {
            "state": repetition_menu_state,
            "rows": repetition_rows,
            "checks": repetition_menu_checks,
        })
        if not all(repetition_menu_checks.values()):
            dbg.problem("settings_repetition_menu_route_failed", {
                "state": repetition_menu_state,
                "rows": repetition_rows,
                "checks": repetition_menu_checks,
            })

        settings_query.data = "ms_change_type"
        change_menu_state = run_async(add_alert.handle_multi_setting_choice(settings_update, settings_ctx))
        change_markup = settings_query.edited[-1]["reply_markup"] if settings_query.edited else None
        change_rows = _extract_callback_rows(change_markup)
        flat_change_callbacks = [cb for row in change_rows for cb in row if isinstance(cb, str)]
        change_menu_checks = {
            "change_menu_state": change_menu_state == C.CHANGE_ALERT_TYPE,
            "ct_back_present": "ct_back" in flat_change_callbacks,
            "ct_birthday_excluded": "ct_6" not in flat_change_callbacks,
        }
        dbg.section("settings_change_type_menu", {
            "state": change_menu_state,
            "rows": change_rows,
            "checks": change_menu_checks,
        })
        if not all(change_menu_checks.values()):
            dbg.problem("settings_change_type_menu_failed", {
                "state": change_menu_state,
                "rows": change_rows,
                "checks": change_menu_checks,
            })

        from modules.handlers.add_flow import type_flow as type_flow_mod

        original_now = type_flow_mod.now_server_naive
        type_flow_mod.now_server_naive = lambda: type_flow_mod.datetime(2026, 3, 10, 8, 0, 0)
        try:
            custom_ctx = _DummyContext()
            custom_ctx.user_data["temp_alert"] = {
                "title": "One-time meeting",
                "type": 5,
                "type_name": C.ALERT_TYPES.get(5),
                "schedule": {"date": "10/03/2026", "time": "10:00"},
                "pre_alerts": [],
                "tags": [],
            }
            custom_update = _DummyUpdate(
                message=_DummyMessage(text="1h, today at 09:30", message_id=387),
                effective_user=type("User", (), {"id": 100})(),
            )
            custom_state = run_async(add_alert.get_custom_pre_alert_input(custom_update, custom_ctx))
            custom_reply = custom_update.message.replies[-1] if custom_update.message.replies else {}
            custom_checks = {
                "custom_state_confirm": custom_state == C.CONFIRM_CUSTOM_PRE_ALERT,
                "pending_tokens_canonical": custom_ctx.user_data.get("pending_pre_alerts") == ["1h", "30m"],
                "custom_reply_sent": "Confirm?" in (custom_reply.get("text") or ""),
            }
            dbg.section("custom_prealert_mixed_input", {
                "state": custom_state,
                "pending_pre_alerts": custom_ctx.user_data.get("pending_pre_alerts"),
                "reply": custom_reply,
                "checks": custom_checks,
            })
            if not all(custom_checks.values()):
                dbg.problem("custom_prealert_mixed_input_failed", {
                    "state": custom_state,
                    "pending_pre_alerts": custom_ctx.user_data.get("pending_pre_alerts"),
                    "reply": custom_reply,
                    "checks": custom_checks,
                })
        finally:
            type_flow_mod.now_server_naive = original_now

        daily_ctx = _DummyContext()
        daily_ctx.user_data["temp_alert"] = {
            "type": 7,
            "type_name": C.ALERT_TYPES.get(7),
            "schedule": {},
            "pre_alerts": [],
            "tags": [],
        }
        daily_update = _DummyUpdate(
            message=_DummyMessage(text="Water plants", message_id=301),
            effective_user=type("User", (), {"id": 99})(),
        )
        daily_state = run_async(add_alert.prompt_type_specific(daily_update, daily_ctx))
        daily_replies = daily_update.message.replies
        daily_last = daily_replies[-1] if daily_replies else {}
        daily_rows = _extract_callback_rows(daily_last.get("reply_markup"))
        daily_checks = {
            "daily_goes_to_mode_choice_state": daily_state == C.FUZZY_INTERVAL_MODE_CHOICE,
            "daily_prompt_sent": bool(daily_replies),
            "daily_prompt_mentions_mode": "Daily interval mode" in (daily_last.get("text") or ""),
            "daily_prompt_has_fixed_mode_button": any("intmode_fixed" in row for row in daily_rows),
            "daily_prompt_has_fuzzy_mode_button": any("intmode_fuzzy" in row for row in daily_rows),
            "daily_prompt_has_no_legacy_int1": not any("int_1" in row for row in daily_rows),
        }
        dbg.section("daily_title_to_interval", {
            "state": daily_state,
            "checks": daily_checks,
            "prompt_text": daily_last.get("text"),
            "prompt_rows": daily_rows,
        })
        if not all(daily_checks.values()):
            dbg.problem("daily_title_to_interval_failed", {
                "state": daily_state,
                "checks": daily_checks,
                "prompt_text": daily_last.get("text"),
                "prompt_rows": daily_rows,
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    dbg.finish(
        summary_lines=[f"FAIL: {code}" for code in dbg.problems],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
