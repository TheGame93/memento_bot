#!/usr/bin/env python3
import os
import sys
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
from _lib.runtime import run_async

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "pre_alert_menu_debug"
FEATURE_TITLE = "Pre-alert Menu Contract"


class _DummyMessage:
    def __init__(self, text=None, message_id=101):
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
        self.answers = []
        self.edited = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        self.edited.append({
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })


class _DummyUpdate:
    def __init__(self, message=None, callback_query=None):
        self.message = message
        self.callback_query = callback_query


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}


def _button_rows(markup):
    rows = []
    for row in getattr(markup, "inline_keyboard", []) or []:
        rows.append([{"text": btn.text, "data": btn.callback_data} for btn in row])
    return rows


def _problem_if_failed(dbg, key, checks, details):
    if not all(checks.values()):
        dbg.problem(key, {"checks": checks, "details": details})


def _check_expression_boundary_for_prealert(dbg, parse_user_datetime_expression):
    ref = datetime(2026, 3, 2, 9, 0, 0)
    due = datetime(2026, 3, 2, 9, 30, 0)

    status_ok, candidate_ok, meta_ok = parse_user_datetime_expression(
        "today at 09:15",
        reference_server_dt=ref,
        boundary_mode="before_boundary",
        boundary_server_dt=due,
        now_server_dt=ref,
    )
    status_late, candidate_late, meta_late = parse_user_datetime_expression(
        "today at 09:30",
        reference_server_dt=ref,
        boundary_mode="before_boundary",
        boundary_server_dt=due,
        now_server_dt=ref,
    )
    status_past, candidate_past, meta_past = parse_user_datetime_expression(
        "today at 08:30",
        reference_server_dt=ref,
        boundary_mode="before_boundary",
        boundary_server_dt=due,
        now_server_dt=ref,
    )

    checks = {
        "valid_prealert_ok": status_ok == "ok" and candidate_ok == datetime(2026, 3, 2, 9, 15, 0),
        "valid_reason_none": (meta_ok or {}).get("reason_code") is None,
        "late_rejected": status_late == "invalid" and candidate_late is None,
        "late_reason_not_before": (meta_late or {}).get("reason_code") == "candidate_not_before_boundary",
        "past_rejected": status_past == "invalid" and candidate_past is None,
        "past_reason_not_future": (meta_past or {}).get("reason_code") == "candidate_not_future",
    }
    dbg.section("expression_boundary_prealert", {
        "ok_case": {
            "status": status_ok,
            "candidate": candidate_ok.isoformat(sep=" ") if candidate_ok else None,
            "meta": meta_ok,
        },
        "late_case": {
            "status": status_late,
            "candidate": candidate_late.isoformat(sep=" ") if candidate_late else None,
            "meta": meta_late,
        },
        "past_case": {
            "status": status_past,
            "candidate": candidate_past.isoformat(sep=" ") if candidate_past else None,
            "meta": meta_past,
        },
        "checks": checks,
    })
    _problem_if_failed(dbg, "expression_boundary_prealert_mismatch", checks, {})


def _check_pre_alert_render_preview(dbg, format_pre_alerts):
    payload = {
        "type": 5,
        "schedule": {"date": "10/03/2026", "time": "10:00"},
        "pre_alerts": ["1h", "30m"],
    }
    preview = format_pre_alerts(
        payload,
        user_prefs={},
        reference_time=datetime(2026, 3, 10, 8, 0, 0),
    )

    fallback_payload = {
        "type": 99,
        "schedule": {},
        "pre_alerts": ["1h"],
    }
    fallback = format_pre_alerts(fallback_payload, user_prefs={}, reference_time=datetime(2026, 3, 10, 8, 0, 0))

    checks = {
        "preview_has_day_month": "10/03" in preview,
        "preview_has_time_component": "09:00" in preview or "09:30" in preview,
        "fallback_has_human_label": "hour" in fallback,
    }
    dbg.section("pre_alert_render_preview", {"preview": preview, "fallback": fallback, "checks": checks})
    _problem_if_failed(dbg, "pre_alert_render_preview_mismatch", checks, {})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules import constants as C
            from modules.handlers.add_flow import type_flow
            from modules.handlers.add_flow.summary_flow import format_pre_alerts
            from modules.timezone_utils import parse_user_datetime_expression
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _check_expression_boundary_for_prealert(dbg, parse_user_datetime_expression)
        _check_pre_alert_render_preview(dbg, format_pre_alerts)

        async def _return_to_settings(_update, context):
            context.user_data["returned_to_settings"] = True
            return C.MULTI_SETTINGS

        # Case 1: menu layout with empty pre-alerts uses selected-state icon for "No pre-alert".
        ctx_empty = _DummyContext({"temp_alert": {"pre_alerts": []}})
        q_empty = _DummyCallbackQuery("pre_dummy", _DummyMessage(message_id=301))
        state_empty = run_async(type_flow.show_pre_alert_menu(_DummyUpdate(callback_query=q_empty), ctx_empty))
        edited_empty = q_empty.edited[-1] if q_empty.edited else {}
        rows_empty = _button_rows(edited_empty.get("reply_markup"))
        empty_checks = {
            "state_get_pre_alert": state_empty == C.GET_PRE_ALERT,
            "row_count_3": len(rows_empty) == 3,
            "row1_len_3": len(rows_empty[0]) == 3 if len(rows_empty) > 0 else False,
            "row2_len_2": len(rows_empty[1]) == 2 if len(rows_empty) > 1 else False,
            "row3_len_1": len(rows_empty[2]) == 1 if len(rows_empty) > 2 else False,
            "has_1d": rows_empty and rows_empty[0][0]["data"] == "pre_1d",
            "has_1w": rows_empty and len(rows_empty[0]) > 1 and rows_empty[0][1]["data"] == "pre_1w",
            "has_1mo": rows_empty and len(rows_empty[0]) > 2 and rows_empty[0][2]["data"] == "pre_1mo",
            "has_custom": len(rows_empty) > 1 and rows_empty[1][0]["data"] == "pre_custom",
            "has_none": len(rows_empty) > 1 and rows_empty[1][1]["data"] == "pre_none",
            "has_cancel": len(rows_empty) > 2 and rows_empty[2][0]["data"] == "pre_cancel",
            "none_selected_icon": len(rows_empty) > 1 and rows_empty[1][1]["text"].startswith("✅"),
        }
        dbg.section("menu_empty", {"rows": rows_empty, "checks": empty_checks})
        _problem_if_failed(dbg, "menu_empty_mismatch", empty_checks, {"rows": rows_empty})

        # Case 2: menu layout with non-empty pre-alerts uses non-selected icon for "No pre-alert".
        ctx_nonempty = _DummyContext({"temp_alert": {"pre_alerts": ["1d"]}})
        q_nonempty = _DummyCallbackQuery("pre_dummy", _DummyMessage(message_id=302))
        run_async(type_flow.show_pre_alert_menu(_DummyUpdate(callback_query=q_nonempty), ctx_nonempty))
        edited_nonempty = q_nonempty.edited[-1] if q_nonempty.edited else {}
        rows_nonempty = _button_rows(edited_nonempty.get("reply_markup"))
        nonempty_checks = {
            "none_non_selected_icon": len(rows_nonempty) > 1 and rows_nonempty[1][1]["text"].startswith("🚫"),
        }
        dbg.section("menu_nonempty", {"rows": rows_nonempty, "checks": nonempty_checks})
        _problem_if_failed(dbg, "menu_nonempty_mismatch", nonempty_checks, {"rows": rows_nonempty})

        # Case 2b: birthday context shows dedicated evening-before option.
        ctx_bday = _DummyContext({
            "settings_return": "birthday",
            "temp_alert": {"type": 6, "pre_alerts": []},
        })
        q_bday = _DummyCallbackQuery("pre_dummy", _DummyMessage(message_id=3021))
        run_async(type_flow.show_pre_alert_menu(_DummyUpdate(callback_query=q_bday), ctx_bday))
        edited_bday = q_bday.edited[-1] if q_bday.edited else {}
        rows_bday = _button_rows(edited_bday.get("reply_markup"))
        bday_checks = {
            "has_evening_option_row": any(
                btn.get("data") == "pre_bdayeve"
                for row in rows_bday
                for btn in row
            ),
        }
        dbg.section("menu_birthday", {"rows": rows_bday, "checks": bday_checks})
        _problem_if_failed(dbg, "menu_birthday_mismatch", bday_checks, {"rows": rows_bday})

        # Case 2c: birthday evening-before selection stores dedicated token.
        ctx_bday_pick = _DummyContext({
            "settings_return": "birthday",
            "temp_alert": {"type": 6, "pre_alerts": ["1d"]},
        })
        q_bday_pick = _DummyCallbackQuery("pre_bdayeve", _DummyMessage(message_id=3022))
        state_bday_pick = run_async(type_flow.get_pre_alert_callback(
            _DummyUpdate(callback_query=q_bday_pick),
            ctx_bday_pick,
            _return_to_settings,
        ))
        bday_pick_checks = {
            "returns_to_settings": state_bday_pick == C.MULTI_SETTINGS,
            "token_merged": ctx_bday_pick.user_data.get("temp_alert", {}).get("pre_alerts") == [
                "1d",
                C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN,
            ],
        }
        dbg.section("birthday_evening_token_select", {"checks": bday_pick_checks})
        _problem_if_failed(dbg, "birthday_evening_token_select_mismatch", bday_pick_checks, {})

        # Case 2d: edit context (settings_return=edit) must still expose and accept evening-before.
        ctx_edit_bday = _DummyContext({
            "settings_return": "edit",
            "temp_alert": {"type": 6, "pre_alerts": []},
        })
        q_edit_bday = _DummyCallbackQuery("pre_dummy", _DummyMessage(message_id=3023))
        state_edit_menu = run_async(type_flow.show_pre_alert_menu(_DummyUpdate(callback_query=q_edit_bday), ctx_edit_bday))
        edited_edit_bday = q_edit_bday.edited[-1] if q_edit_bday.edited else {}
        rows_edit_bday = _button_rows(edited_edit_bday.get("reply_markup"))
        has_evening_edit = any(
            btn.get("data") == "pre_bdayeve"
            for row in rows_edit_bday
            for btn in row
        )

        q_edit_pick = _DummyCallbackQuery("pre_bdayeve", _DummyMessage(message_id=3024))
        state_edit_pick = run_async(type_flow.get_pre_alert_callback(
            _DummyUpdate(callback_query=q_edit_pick),
            ctx_edit_bday,
            _return_to_settings,
        ))
        edit_bday_checks = {
            "menu_state_get_pre_alert": state_edit_menu == C.GET_PRE_ALERT,
            "menu_has_evening_option": has_evening_edit,
            "selection_returns_to_settings": state_edit_pick == C.MULTI_SETTINGS,
            "selection_writes_token": ctx_edit_bday.user_data.get("temp_alert", {}).get("pre_alerts") == [
                C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN,
            ],
        }
        dbg.section("menu_birthday_edit_context", {"rows": rows_edit_bday, "checks": edit_bday_checks})
        _problem_if_failed(dbg, "menu_birthday_edit_context_mismatch", edit_bday_checks, {"rows": rows_edit_bday})

        # Case 3: unknown payload is rejected and does not mutate state.
        ctx_unknown = _DummyContext({"temp_alert": {"pre_alerts": ["1d"]}, "pending_pre_alerts": ["2w"]})
        q_unknown = _DummyCallbackQuery("pre_bogus", _DummyMessage(message_id=303))
        state_unknown = run_async(type_flow.get_pre_alert_callback(
            _DummyUpdate(callback_query=q_unknown),
            ctx_unknown,
            _return_to_settings,
        ))
        unknown_checks = {
            "stays_get_pre_alert": state_unknown == C.GET_PRE_ALERT,
            "state_not_mutated": ctx_unknown.user_data.get("temp_alert", {}).get("pre_alerts") == ["1d"],
            "did_not_return_to_settings": not ctx_unknown.user_data.get("returned_to_settings", False),
            "shows_alert": bool(q_unknown.answers and q_unknown.answers[-1].get("show_alert") is True),
        }
        dbg.section("unknown_payload", {"answers": q_unknown.answers, "checks": unknown_checks})
        _problem_if_failed(dbg, "unknown_payload_mismatch", unknown_checks, {"answers": q_unknown.answers})

        # Case 4: cancel returns to settings and clears stale pending custom values.
        ctx_cancel = _DummyContext({"temp_alert": {"pre_alerts": ["1w"]}, "pending_pre_alerts": ["2d"]})
        q_cancel = _DummyCallbackQuery("pre_cancel", _DummyMessage(message_id=304))
        state_cancel = run_async(type_flow.get_pre_alert_callback(
            _DummyUpdate(callback_query=q_cancel),
            ctx_cancel,
            _return_to_settings,
        ))
        cancel_checks = {
            "returns_to_settings": state_cancel == C.MULTI_SETTINGS,
            "did_return": ctx_cancel.user_data.get("returned_to_settings") is True,
            "pre_alerts_unchanged": ctx_cancel.user_data.get("temp_alert", {}).get("pre_alerts") == ["1w"],
            "pending_cleared": ctx_cancel.user_data.get("pending_pre_alerts") == [],
        }
        dbg.section("cancel_path", {"checks": cancel_checks})
        _problem_if_failed(dbg, "cancel_path_mismatch", cancel_checks, {})

        # Case 5: month preset is accepted, merged, and clears stale pending custom values.
        ctx_month = _DummyContext({"temp_alert": {"pre_alerts": ["1d"]}, "pending_pre_alerts": ["2d"]})
        q_month = _DummyCallbackQuery("pre_1mo", _DummyMessage(message_id=305))
        state_month = run_async(type_flow.get_pre_alert_callback(
            _DummyUpdate(callback_query=q_month),
            ctx_month,
            _return_to_settings,
        ))
        month_checks = {
            "returns_to_settings": state_month == C.MULTI_SETTINGS,
            "merged_month": ctx_month.user_data.get("temp_alert", {}).get("pre_alerts") == ["1d", "1mo"],
            "pending_cleared": ctx_month.user_data.get("pending_pre_alerts") == [],
        }
        dbg.section("month_preset", {"checks": month_checks})
        _problem_if_failed(dbg, "month_preset_mismatch", month_checks, {})

        # Case 5b: custom instructions cover both format families and defaults.
        ctx_custom_prompt = _DummyContext({"temp_alert": {"type": 5, "pre_alerts": []}})
        q_custom_prompt = _DummyCallbackQuery("pre_custom", _DummyMessage(message_id=3051))
        state_custom_prompt = run_async(type_flow.get_pre_alert_callback(
            _DummyUpdate(callback_query=q_custom_prompt),
            ctx_custom_prompt,
            _return_to_settings,
        ))
        custom_prompt_text = (q_custom_prompt.edited[-1] or {}).get("text", "") if q_custom_prompt.edited else ""
        custom_prompt_checks = {
            "state_get_custom_pre_alert": state_custom_prompt == C.GET_CUSTOM_PRE_ALERT,
            "mentions_supported_families": "Supported input families" in custom_prompt_text,
            "mentions_default_time": "Missing time uses the event time" in custom_prompt_text,
            "mentions_default_year": "Missing year uses the next future occurrence" in custom_prompt_text,
        }
        dbg.section("custom_prompt_instructions", {"text": custom_prompt_text, "checks": custom_prompt_checks})
        _problem_if_failed(dbg, "custom_prompt_instructions_mismatch", custom_prompt_checks, {})

        # Case 6: unknown custom-confirm callback is rejected and does not mutate state.
        ctx_custom_unknown = _DummyContext({
            "temp_alert": {"pre_alerts": ["1w"]},
            "pending_pre_alerts": ["1d"],
        })
        q_custom_unknown = _DummyCallbackQuery("precustom_maybe", _DummyMessage(message_id=306))
        state_custom_unknown = run_async(type_flow.confirm_custom_pre_alert(
            _DummyUpdate(callback_query=q_custom_unknown),
            ctx_custom_unknown,
            _return_to_settings,
        ))
        custom_unknown_checks = {
            "stays_confirm_custom": state_custom_unknown == C.CONFIRM_CUSTOM_PRE_ALERT,
            "did_not_return_to_settings": not ctx_custom_unknown.user_data.get("returned_to_settings", False),
            "pending_not_flushed": ctx_custom_unknown.user_data.get("pending_pre_alerts") == ["1d"],
            "pre_alerts_not_mutated": ctx_custom_unknown.user_data.get("temp_alert", {}).get("pre_alerts") == ["1w"],
            "shows_alert": bool(q_custom_unknown.answers and q_custom_unknown.answers[-1].get("show_alert") is True),
        }
        dbg.section("custom_unknown_confirm", {"answers": q_custom_unknown.answers, "checks": custom_unknown_checks})
        _problem_if_failed(dbg, "custom_unknown_confirm_mismatch", custom_unknown_checks, {"answers": q_custom_unknown.answers})

        # Case 7: canonical token helper maps exact deltas to schema-safe tokens.
        due_dt = datetime(2026, 3, 10, 10, 0, 0)
        token_cases = {
            "30m": type_flow._build_pre_alert_token_from_resolved(datetime(2026, 3, 10, 9, 30, 0), due_dt),
            "1h": type_flow._build_pre_alert_token_from_resolved(datetime(2026, 3, 10, 9, 0, 0), due_dt),
            "1w": type_flow._build_pre_alert_token_from_resolved(datetime(2026, 3, 3, 10, 0, 0), due_dt),
            "1mo": type_flow._build_pre_alert_token_from_resolved(datetime(2026, 2, 10, 10, 0, 0), due_dt),
            "invalid_order": type_flow._build_pre_alert_token_from_resolved(datetime(2026, 3, 10, 10, 0, 0), due_dt),
        }
        token_checks = {
            "token_30m": token_cases["30m"] == ("30m", None),
            "token_1h": token_cases["1h"] == ("1h", None),
            "token_1w": token_cases["1w"] == ("1w", None),
            "token_1mo": token_cases["1mo"] == ("1mo", None),
            "invalid_not_before_due": token_cases["invalid_order"] == (None, "candidate_not_before_due"),
        }
        dbg.section("custom_token_canonicalization", {"cases": token_cases, "checks": token_checks})
        _problem_if_failed(dbg, "custom_token_canonicalization_mismatch", token_checks, {"cases": token_cases})

        # Case 8: mixed token/expression input produces canonical pending tokens.
        original_now = type_flow.now_server_naive
        type_flow.now_server_naive = lambda: datetime(2026, 3, 10, 8, 0, 0)
        try:
            mixed_ctx = _DummyContext({
                "temp_alert": {
                    "type": 5,
                    "schedule": {"date": "10/03/2026", "time": "10:00"},
                    "pre_alerts": [],
                },
                "pending_pre_alerts": [],
            })
            mixed_msg = _DummyMessage(text="1h, today at 09:30", message_id=307)
            mixed_state = run_async(type_flow.get_custom_pre_alert_input(
                _DummyUpdate(message=mixed_msg),
                mixed_ctx,
            ))
            mixed_reply = mixed_msg.replies[-1] if mixed_msg.replies else {}
            mixed_checks = {
                "state_confirm_custom": mixed_state == C.CONFIRM_CUSTOM_PRE_ALERT,
                "pending_tokens_canonical": mixed_ctx.user_data.get("pending_pre_alerts") == ["1h", "30m"],
                "confirmation_message_sent": "Confirm?" in (mixed_reply.get("text") or ""),
                "confirmation_has_interpreted_block": "Interpreted entries:" in (mixed_reply.get("text") or ""),
                "confirmation_has_raw_expression": "today at 09:30" in (mixed_reply.get("text") or ""),
                "confirmation_has_canonical_token": "`30m`" in (mixed_reply.get("text") or ""),
            }
            dbg.section("custom_mixed_input", {
                "state": mixed_state,
                "reply": mixed_reply,
                "pending": mixed_ctx.user_data.get("pending_pre_alerts"),
                "checks": mixed_checks,
            })
            _problem_if_failed(dbg, "custom_mixed_input_mismatch", mixed_checks, {})

            # Case 9: invalid boundary candidates stay in input state and show feedback.
            invalid_ctx = _DummyContext({
                "temp_alert": {
                    "type": 5,
                    "schedule": {"date": "10/03/2026", "time": "10:00"},
                    "pre_alerts": [],
                },
            })
            invalid_msg = _DummyMessage(text="today at 10:30, 5h", message_id=308)
            invalid_state = run_async(type_flow.get_custom_pre_alert_input(
                _DummyUpdate(message=invalid_msg),
                invalid_ctx,
            ))
            invalid_reply = invalid_msg.replies[-1] if invalid_msg.replies else {}
            invalid_checks = {
                "state_get_custom": invalid_state == C.GET_CUSTOM_PRE_ALERT,
                "no_pending_tokens": not invalid_ctx.user_data.get("pending_pre_alerts"),
                "invalid_feedback_has_not_before_due_reason": "not before the due event" in (invalid_reply.get("text") or ""),
                "invalid_feedback_has_not_future_reason": "in the past or right now" in (invalid_reply.get("text") or ""),
            }
            dbg.section("custom_invalid_boundary", {
                "state": invalid_state,
                "reply": invalid_reply,
                "pending": invalid_ctx.user_data.get("pending_pre_alerts"),
                "checks": invalid_checks,
            })
            _problem_if_failed(dbg, "custom_invalid_boundary_mismatch", invalid_checks, {})

            # Case 10: unresolved due occurrence rejects custom parsing deterministically.
            unresolved_ctx = _DummyContext({
                "temp_alert": {
                    "type": 5,
                    "schedule": {"date": "10/03/2026", "time": "10:00"},
                    "pre_alerts": [],
                },
            })
            unresolved_msg = _DummyMessage(text="1h", message_id=309)
            type_flow.now_server_naive = lambda: datetime(2026, 3, 10, 11, 0, 0)
            unresolved_state = run_async(type_flow.get_custom_pre_alert_input(
                _DummyUpdate(message=unresolved_msg),
                unresolved_ctx,
            ))
            unresolved_reply = unresolved_msg.replies[-1] if unresolved_msg.replies else {}
            unresolved_checks = {
                "state_get_custom": unresolved_state == C.GET_CUSTOM_PRE_ALERT,
                "due_guard_message": "Cannot evaluate pre-alerts right now" in (unresolved_reply.get("text") or ""),
            }
            dbg.section("custom_due_unresolved", {
                "state": unresolved_state,
                "reply": unresolved_reply,
                "checks": unresolved_checks,
            })
            _problem_if_failed(dbg, "custom_due_unresolved_mismatch", unresolved_checks, {})
        finally:
            type_flow.now_server_naive = original_now
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    menu_ok = not dbg.has_problem(
        "menu_empty_mismatch",
        "menu_nonempty_mismatch",
        "menu_birthday_mismatch",
        "menu_birthday_edit_context_mismatch",
    )
    birthday_token_ok = not dbg.has_problem("birthday_evening_token_select_mismatch")
    unknown_ok = not dbg.has_problem("unknown_payload_mismatch")
    cancel_ok = not dbg.has_problem("cancel_path_mismatch")
    month_ok = not dbg.has_problem("month_preset_mismatch")
    custom_confirm_ok = not dbg.has_problem("custom_unknown_confirm_mismatch")
    custom_prompt_ok = not dbg.has_problem("custom_prompt_instructions_mismatch")
    boundary_ok = not dbg.has_problem("expression_boundary_prealert_mismatch")
    custom_token_ok = not dbg.has_problem("custom_token_canonicalization_mismatch")
    custom_mixed_ok = not dbg.has_problem("custom_mixed_input_mismatch")
    custom_boundary_guard_ok = not dbg.has_problem("custom_invalid_boundary_mismatch")
    custom_due_guard_ok = not dbg.has_problem("custom_due_unresolved_mismatch")
    render_preview_ok = not dbg.has_problem("pre_alert_render_preview_mismatch")
    dbg.finish(summary_lines=[
        f"menu_layout: {'OK' if menu_ok else 'FAIL'}",
        f"birthday_evening_option: {'OK' if birthday_token_ok else 'FAIL'}",
        f"unknown_payload_guard: {'OK' if unknown_ok else 'FAIL'}",
        f"cancel_path: {'OK' if cancel_ok else 'FAIL'}",
        f"month_preset: {'OK' if month_ok else 'FAIL'}",
        f"custom_prompt_instructions: {'OK' if custom_prompt_ok else 'FAIL'}",
        f"custom_confirm_guard: {'OK' if custom_confirm_ok else 'FAIL'}",
        f"boundary_policy: {'OK' if boundary_ok else 'FAIL'}",
        f"custom_token_canonicalization: {'OK' if custom_token_ok else 'FAIL'}",
        f"custom_mixed_input: {'OK' if custom_mixed_ok else 'FAIL'}",
        f"custom_boundary_guard: {'OK' if custom_boundary_guard_ok else 'FAIL'}",
        f"custom_due_guard: {'OK' if custom_due_guard_ok else 'FAIL'}",
        f"render_preview: {'OK' if render_preview_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
