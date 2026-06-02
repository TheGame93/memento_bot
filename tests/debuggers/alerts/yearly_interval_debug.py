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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "yearly_interval_debug"
FEATURE_TITLE = "Yearly Interval Behavior"


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
        self.edits = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        self.edits.append({
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


def _extract_callback_data(markup):
    rows = []
    for row in getattr(markup, "inline_keyboard", []) or []:
        rows.append([getattr(btn, "callback_data", None) for btn in row])
    return rows


def _next_iso(dt):
    return dt.isoformat() if dt else None


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        suppress_ptb_user_warning()
        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules import constants as C
            from modules.handlers.add_flow import settings_flow, summary_flow, type_flow
            from modules.handlers.list_alerts import format_detailed_card
            from modules.scheduler_mathlogic import get_next_occurrence
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        # Check 1: yearly appears in settings interval controls and summary formatting.
        data_yearly = {
            "type": 4,
            "schedule": {"dates": "10/03, 25/12", "time": "10:00"},
            "pre_alerts": [],
            "additional_info": "",
        }
        summary_flow.ensure_default_settings(data_yearly)
        interval_default = summary_flow.format_interval(data_yearly)
        data_yearly["schedule"]["interval"] = 2
        interval_plural = summary_flow.format_interval(data_yearly)

        menu_ctx = _DummyContext({"temp_alert": data_yearly})
        menu_query = _DummyCallbackQuery("ms_open", _DummyMessage())
        menu_state = run_async(settings_flow.show_multi_setting_menu(_DummyUpdate(callback_query=menu_query), menu_ctx))
        menu_rows = _extract_callback_data(menu_query.edits[-1]["reply_markup"]) if menu_query.edits else []
        has_interval_button = any("ms_interval" in row for row in menu_rows)

        checks_ui = {
            "default_interval_yearly": interval_default == "Every 1 year",
            "plural_interval_yearly": interval_plural == "Every 2 years",
            "menu_state_multi_settings": menu_state == C.MULTI_SETTINGS,
            "menu_has_interval_button": has_interval_button,
        }
        dbg.section("yearly_settings_ui", {
            "checks": checks_ui,
            "interval_default": interval_default,
            "interval_plural": interval_plural,
            "menu_rows": menu_rows,
        })
        if not all(checks_ui.values()):
            dbg.problem("yearly_settings_ui_failed", {"checks": checks_ui, "menu_rows": menu_rows})

        # Check 2: interval prompt supports yearly wording and callback path.
        prompt_ctx = _DummyContext({"temp_alert": {"type": 4, "schedule": {"dates": "10/03, 25/12"}}})
        prompt_query = _DummyCallbackQuery("ms_interval", _DummyMessage())

        async def _return_multi(_update, _context):
            return C.MULTI_SETTINGS

        prompt_state = run_async(type_flow.get_interval_prompt(
            _DummyUpdate(callback_query=prompt_query),
            prompt_ctx,
            _return_multi,
        ))
        prompt_edit = prompt_query.edits[-1] if prompt_query.edits else {}
        prompt_rows = _extract_callback_data(prompt_edit.get("reply_markup"))
        checks_prompt = {
            "state_get_interval": prompt_state == C.GET_INTERVAL,
            "prompt_mentions_years": "years between occurrences" in (prompt_edit.get("text") or ""),
            "prompt_has_int1": any("int_1" in row for row in prompt_rows),
        }
        dbg.section("yearly_interval_prompt", {
            "checks": checks_prompt,
            "prompt_text": prompt_edit.get("text"),
            "prompt_rows": prompt_rows,
        })
        if not all(checks_prompt.values()):
            dbg.problem("yearly_interval_prompt_failed", {"checks": checks_prompt})

        # Check 3: resetting interval to 1 clears stale start_marker (callback + text input paths).
        reset_ctx_cb = _DummyContext({"temp_alert": {"type": 4, "schedule": {"interval": 3, "start_marker": "05/03/2026"}}})
        reset_query = _DummyCallbackQuery("int_1", _DummyMessage())
        reset_state_cb = run_async(type_flow.get_interval_callback(
            _DummyUpdate(callback_query=reset_query),
            reset_ctx_cb,
            _return_multi,
        ))
        cb_schedule = reset_ctx_cb.user_data["temp_alert"]["schedule"]

        reset_ctx_in = _DummyContext({"temp_alert": {"type": 4, "schedule": {"interval": 5, "start_marker": "10/05/2027"}}})
        reset_msg = _DummyMessage(text="1")
        reset_state_in = run_async(type_flow.get_interval_input(
            _DummyUpdate(message=reset_msg),
            reset_ctx_in,
            _return_multi,
        ))
        in_schedule = reset_ctx_in.user_data["temp_alert"]["schedule"]

        checks_reset = {
            "callback_returns_settings": reset_state_cb == C.MULTI_SETTINGS,
            "callback_interval_one": cb_schedule.get("interval") == 1,
            "callback_marker_cleared": "start_marker" not in cb_schedule,
            "input_returns_settings": reset_state_in == C.MULTI_SETTINGS,
            "input_interval_one": in_schedule.get("interval") == 1,
            "input_marker_cleared": "start_marker" not in in_schedule,
        }
        dbg.section("interval_reset_cleanup", {
            "checks": checks_reset,
            "callback_schedule": cb_schedule,
            "input_schedule": in_schedule,
        })
        if not all(checks_reset.values()):
            dbg.problem("interval_reset_cleanup_failed", {"checks": checks_reset})

        # Check 4: yearly suggested start uses next configured yearly date.
        before = datetime.now()
        suggested = type_flow.calculate_suggested_start({
            "type": 4,
            "schedule": {"dates": "10/03, 25/12"},
        })
        allowed_md = {(10, 3), (25, 12)}
        checks_suggestion = {
            "suggested_after_now": suggested > before,
            "suggested_matches_configured_date": (suggested.day, suggested.month) in allowed_md,
        }
        dbg.section("yearly_suggested_start", {
            "checks": checks_suggestion,
            "suggested": suggested.isoformat(),
            "allowed_md": sorted(list(allowed_md)),
        })
        if not all(checks_suggestion.values()):
            dbg.problem("yearly_suggested_start_failed", {"checks": checks_suggestion, "suggested": suggested.isoformat()})

        # Check 5: scheduler yearly interval honors anchor and interval cycles.
        yearly_interval_alert = {
            "id": "yi1",
            "type": 4,
            "schedule": {
                "dates": "10/03,25/12",
                "time": "10:00",
                "interval": 2,
                "start_marker": "15/04/2026",
            },
        }
        occ_a = get_next_occurrence(yearly_interval_alert, datetime(2026, 1, 1, 9, 0, 0))
        occ_b = get_next_occurrence(yearly_interval_alert, datetime(2026, 12, 26, 9, 0, 0))
        occ_c = get_next_occurrence(yearly_interval_alert, datetime(2028, 1, 1, 9, 0, 0))

        yearly_interval_one = {
            "id": "yi2",
            "type": 4,
            "schedule": {
                "dates": "10/03,25/12",
                "time": "10:00",
                "interval": 1,
                "start_marker": "15/04/2026",
            },
        }
        occ_d = get_next_occurrence(yearly_interval_one, datetime(2027, 1, 1, 9, 0, 0))

        checks_scheduler = {
            "interval2_anchor_year_first": bool(occ_a and occ_a == datetime(2026, 12, 25, 10, 0, 0)),
            "interval2_skips_off_years": bool(occ_b and occ_b == datetime(2028, 3, 10, 10, 0, 0)),
            "interval2_keeps_cycle": bool(occ_c and occ_c == datetime(2028, 3, 10, 10, 0, 0)),
            "interval1_backcompat": bool(occ_d and occ_d == datetime(2027, 3, 10, 10, 0, 0)),
        }
        dbg.section("yearly_scheduler_interval", {
            "checks": checks_scheduler,
            "occ_a": _next_iso(occ_a),
            "occ_b": _next_iso(occ_b),
            "occ_c": _next_iso(occ_c),
            "occ_d": _next_iso(occ_d),
        })
        if not all(checks_scheduler.values()):
            dbg.problem("yearly_scheduler_interval_failed", {
                "checks": checks_scheduler,
                "occ_a": _next_iso(occ_a),
                "occ_b": _next_iso(occ_b),
                "occ_c": _next_iso(occ_c),
                "occ_d": _next_iso(occ_d),
            })

        # Check 6: yearly interval is visible in detailed list cards.
        detail_card_text = format_detailed_card({
            "id": "yi-card",
            "type": 4,
            "type_name": "Yearly",
            "title": "Yearly check",
            "active": True,
            "pre_alerts": [],
            "tags": ["✨ Other"],
            "schedule": {
                "dates": "10/03,25/12",
                "time": "10:00",
                "interval": 3,
            },
        })
        checks_details = {
            "interval_visible": "🔁 Interval: Every 3 Years" in detail_card_text,
        }
        dbg.section("yearly_detail_card_interval", {
            "checks": checks_details,
            "card_excerpt": detail_card_text[:400],
        })
        if not all(checks_details.values()):
            dbg.problem("yearly_detail_card_interval_failed", {
                "checks": checks_details,
                "card_excerpt": detail_card_text[:400],
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    ui_ok = not dbg.has_problem("yearly_settings_ui_failed")
    prompt_ok = not dbg.has_problem("yearly_interval_prompt_failed")
    reset_ok = not dbg.has_problem("interval_reset_cleanup_failed")
    suggestion_ok = not dbg.has_problem("yearly_suggested_start_failed")
    scheduler_ok = not dbg.has_problem("yearly_scheduler_interval_failed")
    detail_ok = not dbg.has_problem("yearly_detail_card_interval_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"settings_ui: {'OK' if ui_ok else 'FAIL'}",
        f"interval_prompt: {'OK' if prompt_ok else 'FAIL'}",
        f"interval_reset_cleanup: {'OK' if reset_ok else 'FAIL'}",
        f"yearly_suggestion: {'OK' if suggestion_ok else 'FAIL'}",
        f"scheduler_interval: {'OK' if scheduler_ok else 'FAIL'}",
        f"detail_card_interval: {'OK' if detail_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
