#!/usr/bin/env python3
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
from _lib.runtime import run_async
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "daily_interval_debug"
FEATURE_TITLE = "Daily Interval Behavior"
ACTIVE_RUNTIME_STORAGE = None


class _StorageStub:
    def __init__(self):
        self.events = []
        self.user_prefs = {}

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": user_id,
            "event_type": event_type,
            "payload": dict(payload or {}),
        })
        return True

    def get_user_prefs(self, _user_id):
        return dict(self.user_prefs)


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
        self.effective_user = types.SimpleNamespace(id=42)


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}
        self.bot_data = {}
        if ACTIVE_RUNTIME_STORAGE is not None:
            _seed_runtime(self, ACTIVE_RUNTIME_STORAGE)


def _seed_runtime(context, storage_obj):
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage_obj, api_failure_tracker=None),
    )


def _extract_rows(markup):
    rows = []
    for row in getattr(markup, "inline_keyboard", []) or []:
        rows.append([getattr(btn, "callback_data", None) for btn in row])
    return rows


def _event_count(storage, event_type):
    return len([e for e in storage.events if e.get("event_type") == event_type])


def _last_event(storage, event_type):
    matches = [e for e in storage.events if e.get("event_type") == event_type]
    return matches[-1] if matches else {}


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

        storage_stub = _StorageStub()
        global ACTIVE_RUNTIME_STORAGE
        ACTIVE_RUNTIME_STORAGE = storage_stub
        original_mainbot = sys.modules.get("mainbot")
        fake_mainbot = types.ModuleType("mainbot")
        sys.modules["mainbot"] = fake_mainbot

        async def _return_multi(_update, _context):
            return C.MULTI_SETTINGS

        try:
            # Check 1: daily interval prompt starts from mode choice.
            prompt_ctx = _DummyContext({
                "temp_alert": {"type": 7, "schedule": {}},
                "settings_return": "alert",
            })
            prompt_query = _DummyCallbackQuery("ms_interval", _DummyMessage())
            prompt_state = run_async(type_flow.get_interval_prompt(
                _DummyUpdate(callback_query=prompt_query),
                prompt_ctx,
                _return_multi,
            ))
            prompt_edit = prompt_query.edits[-1] if prompt_query.edits else {}
            prompt_rows = _extract_rows(prompt_edit.get("reply_markup"))
            checks_prompt = {
                "state_mode_choice": prompt_state == C.FUZZY_INTERVAL_MODE_CHOICE,
                "has_fixed_mode_button": any(C.CB_INTERVAL_FIXED in row for row in prompt_rows),
                "has_fuzzy_mode_button": any(C.CB_INTERVAL_FUZZY in row for row in prompt_rows),
                "log_prompt_shown": _event_count(storage_stub, "daily_interval_prompt_shown") >= 1,
            }
            dbg.section("daily_prompt", {
                "checks": checks_prompt,
                "prompt_text": prompt_edit.get("text"),
                "prompt_rows": prompt_rows,
                "events": storage_stub.events,
            })
            if not all(checks_prompt.values()):
                dbg.problem("daily_prompt_failed", {"checks": checks_prompt})

            # Check 2: fixed mode selection clears fuzzy draft fields and asks for numeric interval.
            fixed_mode_ctx = _DummyContext({
                "temp_alert": {
                    "type": 7,
                    "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "interval": 2},
                    "next_scheduled": "2026-04-30T10:00:00",
                },
                "settings_return": "alert",
            })
            fixed_mode_query = _DummyCallbackQuery(C.CB_INTERVAL_FIXED, _DummyMessage())
            fixed_mode_state = run_async(type_flow.interval_mode_choice_callback(
                _DummyUpdate(callback_query=fixed_mode_query),
                fixed_mode_ctx,
            ))
            fixed_mode_edit = fixed_mode_query.edits[-1] if fixed_mode_query.edits else {}
            fixed_mode_schedule = fixed_mode_ctx.user_data.get("temp_alert", {}).get("schedule", {})
            checks_mode_fixed = {
                "state_get_interval": fixed_mode_state == C.GET_INTERVAL,
                "single_answer": len(fixed_mode_query.answers) == 1,
                "mode_fixed": fixed_mode_schedule.get("interval_mode") == "fixed",
                "fuzzy_mean_cleared": "fuzzy_mean" not in fixed_mode_schedule,
                "fuzzy_std_cleared": "fuzzy_std" not in fixed_mode_schedule,
                "draft_next_cleared": "next_scheduled" not in fixed_mode_ctx.user_data.get("temp_alert", {}),
                "prompt_mentions_days": "How many days between occurrences?" in (fixed_mode_edit.get("text") or ""),
            }
            dbg.section("daily_mode_fixed", {
                "checks": checks_mode_fixed,
                "schedule": fixed_mode_schedule,
                "prompt_text": fixed_mode_edit.get("text"),
            })
            if not all(checks_mode_fixed.values()):
                dbg.problem("daily_mode_fixed_failed", {"checks": checks_mode_fixed})

            # Check 3: fixed-mode daily text input "1" enters confirmation state.
            input_ctx = _DummyContext({
                "temp_alert": {"type": 7, "schedule": {"interval_mode": "fixed", "interval": 3, "start_marker": "10/10/2026"}},
                "settings_return": "alert",
            })
            input_msg = _DummyMessage(text="1")
            input_state = run_async(type_flow.get_interval_input(
                _DummyUpdate(message=input_msg),
                input_ctx,
                _return_multi,
            ))
            confirm_reply = input_msg.replies[-1] if input_msg.replies else {}
            confirm_rows = _extract_rows(confirm_reply.get("reply_markup"))
            checks_confirm_prompt = {
                "state_confirm": input_state == C.DAILY_INTERVAL_CONFIRM,
                "has_yes": any("dint1_yes" in row for row in confirm_rows),
                "has_change": any("dint1_change" in row for row in confirm_rows),
                "show_event_logged": _event_count(storage_stub, "daily_interval_one_confirm_shown") >= 1,
            }
            dbg.section("daily_confirm_prompt", {
                "checks": checks_confirm_prompt,
                "confirm_text": confirm_reply.get("text"),
                "confirm_rows": confirm_rows,
                "events_count": len(storage_stub.events),
            })
            if not all(checks_confirm_prompt.values()):
                dbg.problem("daily_confirm_prompt_failed", {"checks": checks_confirm_prompt})

            # Check 4: "change interval" returns to GET_INTERVAL and re-shows fixed prompt.
            change_ctx = _DummyContext({
                "temp_alert": {"type": 7, "schedule": {}},
                "settings_return": "alert",
                "daily_interval_confirm_source": "interval_text_input",
            })
            change_query = _DummyCallbackQuery("dint1_change", _DummyMessage())
            change_state = run_async(type_flow.daily_interval_confirm_callback(
                _DummyUpdate(callback_query=change_query),
                change_ctx,
                _return_multi,
                _return_multi,
            ))
            change_edit = change_query.edits[-1] if change_query.edits else {}
            change_rows = _extract_rows(change_edit.get("reply_markup"))
            checks_change = {
                "state_back_to_mode_choice": change_state == C.FUZZY_INTERVAL_MODE_CHOICE,
                "single_answer": len(change_query.answers) == 1,
                "still_no_int_1": not any("int_1" in row for row in change_rows),
                "prompt_mentions_mode": "Daily interval mode" in (change_edit.get("text") or ""),
                "change_event_logged": _event_count(storage_stub, "daily_interval_one_change_requested") >= 1,
            }
            dbg.section("daily_confirm_change", {
                "checks": checks_change,
                "answers": change_query.answers,
                "prompt_text": change_edit.get("text"),
                "prompt_rows": change_rows,
            })
            if not all(checks_change.values()):
                dbg.problem("daily_confirm_change_failed", {"checks": checks_change})

            # Check 5: "I'm sure" stores interval=1 and clears marker.
            yes_ctx = _DummyContext({
                "temp_alert": {"type": 7, "schedule": {"interval_mode": "fixed", "interval": 4, "start_marker": "05/11/2026"}},
                "settings_return": "alert",
                "daily_interval_confirm_source": "interval_text_input",
            })
            yes_query = _DummyCallbackQuery("dint1_yes", _DummyMessage())
            yes_state = run_async(type_flow.daily_interval_confirm_callback(
                _DummyUpdate(callback_query=yes_query),
                yes_ctx,
                _return_multi,
                _return_multi,
            ))
            yes_schedule = yes_ctx.user_data.get("temp_alert", {}).get("schedule", {})
            checks_yes = {
                "state_return_settings": yes_state == C.MULTI_SETTINGS,
                "single_answer": len(yes_query.answers) == 1,
                "interval_is_one": yes_schedule.get("interval") == 1,
                "marker_cleared": "start_marker" not in yes_schedule,
                "confirmed_event_logged": _event_count(storage_stub, "daily_interval_one_confirmed") >= 1,
                "set_event_logged": _event_count(storage_stub, "daily_interval_set") >= 1,
            }
            dbg.section("daily_confirm_yes", {
                "checks": checks_yes,
                "answers": yes_query.answers,
                "schedule": yes_schedule,
            })
            if not all(checks_yes.values()):
                dbg.problem("daily_confirm_yes_failed", {"checks": checks_yes})

            # Check 6: fuzzy mode selection routes to mean/std input state.
            fuzzy_mode_ctx = _DummyContext({
                "temp_alert": {"type": 7, "schedule": {}},
                "settings_return": "alert",
            })
            fuzzy_mode_query = _DummyCallbackQuery(C.CB_INTERVAL_FUZZY, _DummyMessage())
            fuzzy_mode_state = run_async(type_flow.interval_mode_choice_callback(
                _DummyUpdate(callback_query=fuzzy_mode_query),
                fuzzy_mode_ctx,
            ))
            fuzzy_mode_schedule = fuzzy_mode_ctx.user_data.get("temp_alert", {}).get("schedule", {})
            checks_mode_fuzzy = {
                "state_fuzzy_mean_std": fuzzy_mode_state == C.FUZZY_MEAN_STD_INPUT,
                "single_answer": len(fuzzy_mode_query.answers) == 1,
                "mode_fuzzy": fuzzy_mode_schedule.get("interval_mode") == "fuzzy",
            }
            dbg.section("daily_mode_fuzzy", {
                "checks": checks_mode_fuzzy,
                "schedule": fuzzy_mode_schedule,
            })
            if not all(checks_mode_fuzzy.values()):
                dbg.problem("daily_mode_fuzzy_failed", {"checks": checks_mode_fuzzy})

            # Check 7: fuzzy mean/std input stores params and sampled draft next_scheduled.
            original_resolver = type_flow.resolve_fuzzy_next_scheduled
            try:
                sampled_next = datetime(2026, 4, 30, 9, 15, 0)
                type_flow.resolve_fuzzy_next_scheduled = (
                    lambda *_args, **_kwargs: (21, sampled_next, False)
                )
                fuzzy_input_ctx = _DummyContext({
                    "temp_alert": {"type": 7, "schedule": {"interval_mode": "fuzzy", "time": "09:15"}},
                    "settings_return": "alert",
                })
                fuzzy_input_msg = _DummyMessage(text="20/3")
                fuzzy_input_state = run_async(type_flow.fuzzy_mean_std_input(
                    _DummyUpdate(message=fuzzy_input_msg),
                    fuzzy_input_ctx,
                    _return_multi,
                ))
            finally:
                type_flow.resolve_fuzzy_next_scheduled = original_resolver
            fuzzy_input_schedule = fuzzy_input_ctx.user_data.get("temp_alert", {}).get("schedule", {})
            fuzzy_set_event = _last_event(storage_stub, "daily_interval_fuzzy_set")
            checks_fuzzy_input = {
                "state_return_settings": fuzzy_input_state == C.MULTI_SETTINGS,
                "mean_set": fuzzy_input_schedule.get("fuzzy_mean") == 20.0,
                "std_set": fuzzy_input_schedule.get("fuzzy_std") == 3.0,
                "next_scheduled_set": fuzzy_input_ctx.user_data.get("temp_alert", {}).get("next_scheduled") == sampled_next.isoformat(),
                "set_event_logged": _event_count(storage_stub, "daily_interval_fuzzy_set") >= 1,
                "set_event_has_sampled_days": fuzzy_set_event.get("payload", {}).get("sampled_days") == 21,
                "set_event_has_next_scheduled": fuzzy_set_event.get("payload", {}).get("next_scheduled") == sampled_next.isoformat(),
                "set_event_uses_policy_keys": "sampled_interval_days" not in (fuzzy_set_event.get("payload") or {}),
            }
            dbg.section("daily_fuzzy_input", {
                "checks": checks_fuzzy_input,
                "schedule": fuzzy_input_schedule,
                "next_scheduled": fuzzy_input_ctx.user_data.get("temp_alert", {}).get("next_scheduled"),
                "set_event_payload": fuzzy_set_event.get("payload", {}),
            })
            if not all(checks_fuzzy_input.values()):
                dbg.problem("daily_fuzzy_input_failed", {"checks": checks_fuzzy_input})

            # Check 8: fuzzy rejection logs policy payload keys (mean/std included).
            original_resolver = type_flow.resolve_fuzzy_next_scheduled
            try:
                type_flow.resolve_fuzzy_next_scheduled = (
                    lambda *_args, **_kwargs: (None, None, False)
                )
                fuzzy_reject_ctx = _DummyContext({
                    "temp_alert": {"type": 7, "schedule": {"interval_mode": "fuzzy", "time": "09:15"}},
                    "settings_return": "alert",
                })
                fuzzy_reject_msg = _DummyMessage(text="20 3")
                fuzzy_reject_state = run_async(type_flow.fuzzy_mean_std_input(
                    _DummyUpdate(message=fuzzy_reject_msg),
                    fuzzy_reject_ctx,
                    _return_multi,
                ))
            finally:
                type_flow.resolve_fuzzy_next_scheduled = original_resolver
            fuzzy_reject_event = _last_event(storage_stub, "daily_interval_fuzzy_rejected")
            checks_fuzzy_reject = {
                "state_stays_on_fuzzy_input": fuzzy_reject_state == C.FUZZY_MEAN_STD_INPUT,
                "reject_event_logged": _event_count(storage_stub, "daily_interval_fuzzy_rejected") >= 1,
                "reject_event_has_mean": fuzzy_reject_event.get("payload", {}).get("mean") == 20.0,
                "reject_event_has_std": fuzzy_reject_event.get("payload", {}).get("std") == 3.0,
                "reject_event_reason": fuzzy_reject_event.get("payload", {}).get("reason_code") == "repetition_rejected",
            }
            dbg.section("daily_fuzzy_rejected_payload", {
                "checks": checks_fuzzy_reject,
                "reject_payload": fuzzy_reject_event.get("payload", {}),
            })
            if not all(checks_fuzzy_reject.values()):
                dbg.problem("daily_fuzzy_rejected_payload_failed", {"checks": checks_fuzzy_reject})

            # Check 9: fuzzy time-only changes adjust draft next_scheduled without re-sampling.
            original_now = type_flow.now_server_naive
            try:
                type_flow.now_server_naive = lambda: datetime(2026, 3, 10, 9, 0, 0)
                time_adjust_ctx = _DummyContext({
                    "temp_alert": {
                        "type": 7,
                        "schedule": {
                            "interval_mode": "fuzzy",
                            "fuzzy_mean": 20.0,
                            "fuzzy_std": 3.0,
                            "time": "10:00",
                        },
                        "next_scheduled": "2026-03-10T10:00:00",
                    },
                    "settings_return": "alert",
                })
                time_adjust_msg = _DummyMessage(text="08:30")
                time_adjust_state = run_async(type_flow.get_time_input(
                    _DummyUpdate(message=time_adjust_msg),
                    time_adjust_ctx,
                    _return_multi,
                ))
            finally:
                type_flow.now_server_naive = original_now
            adjusted_next = time_adjust_ctx.user_data.get("temp_alert", {}).get("next_scheduled")
            time_adjust_event = _last_event(storage_stub, "daily_interval_fuzzy_time_adjusted")
            checks_time_adjust = {
                "state_return_settings": time_adjust_state == C.MULTI_SETTINGS,
                "time_updated": time_adjust_ctx.user_data.get("temp_alert", {}).get("schedule", {}).get("time") == "08:30",
                "next_shifted_one_day": adjusted_next == "2026-03-11T08:30:00",
                "time_adjust_event_has_next_scheduled": time_adjust_event.get("payload", {}).get("next_scheduled") == "2026-03-11T08:30:00",
                "time_adjust_event_adjusted": time_adjust_event.get("payload", {}).get("adjusted") is True,
            }
            dbg.section("daily_fuzzy_time_adjust", {
                "checks": checks_time_adjust,
                "next_scheduled": adjusted_next,
                "time_adjust_payload": time_adjust_event.get("payload", {}),
            })
            if not all(checks_time_adjust.values()):
                dbg.problem("daily_fuzzy_time_adjust_failed", {"checks": checks_time_adjust})

            # Check 10: fuzzy time quick-button path logs next_scheduled metadata.
            original_now = type_flow.now_server_naive
            try:
                type_flow.now_server_naive = lambda: datetime(2026, 3, 10, 9, 0, 0)
                callback_ctx = _DummyContext({
                    "temp_alert": {
                        "type": 7,
                        "schedule": {
                            "interval_mode": "fuzzy",
                            "fuzzy_mean": 20.0,
                            "fuzzy_std": 3.0,
                            "time": "12:00",
                        },
                        "next_scheduled": "2026-03-10T12:00:00",
                    },
                    "settings_return": "alert",
                })
                callback_query = _DummyCallbackQuery("time_default", _DummyMessage())
                callback_state = run_async(type_flow.get_time_callback(
                    _DummyUpdate(callback_query=callback_query),
                    callback_ctx,
                    _return_multi,
                ))
            finally:
                type_flow.now_server_naive = original_now
            callback_event = _last_event(storage_stub, "daily_interval_fuzzy_time_adjusted")
            checks_time_callback = {
                "state_return_settings": callback_state == C.MULTI_SETTINGS,
                "event_source_callback": callback_event.get("payload", {}).get("source") == "time_default_callback",
                "event_has_next_scheduled": callback_event.get("payload", {}).get("next_scheduled") == "2026-03-10T10:00:00",
            }
            dbg.section("daily_fuzzy_time_adjust_callback", {
                "checks": checks_time_callback,
                "event_payload": callback_event.get("payload", {}),
            })
            if not all(checks_time_callback.values()):
                dbg.problem("daily_fuzzy_time_adjust_callback_failed", {"checks": checks_time_callback})

            # Check 11: stale int_1 callback for daily goes to confirmation instead of immediate set.
            stale_ctx = _DummyContext({
                "temp_alert": {"type": 7, "schedule": {"interval": 2}},
                "settings_return": "alert",
            })
            stale_query = _DummyCallbackQuery("int_1", _DummyMessage())
            stale_state = run_async(type_flow.get_interval_callback(
                _DummyUpdate(callback_query=stale_query),
                stale_ctx,
                _return_multi,
            ))
            stale_edit = stale_query.edits[-1] if stale_query.edits else {}
            stale_rows = _extract_rows(stale_edit.get("reply_markup"))
            stale_schedule = stale_ctx.user_data.get("temp_alert", {}).get("schedule", {})
            checks_stale = {
                "state_confirm": stale_state == C.DAILY_INTERVAL_CONFIRM,
                "single_answer": len(stale_query.answers) == 1,
                "did_not_set_interval_immediately": stale_schedule.get("interval") == 2,
                "has_yes": any("dint1_yes" in row for row in stale_rows),
            }
            dbg.section("daily_stale_int1_callback", {
                "checks": checks_stale,
                "answers": stale_query.answers,
                "schedule": stale_schedule,
                "confirm_rows": stale_rows,
            })
            if not all(checks_stale.values()):
                dbg.problem("daily_stale_int1_callback_failed", {"checks": checks_stale})

            # Check 12: daily is treated as recurring in Alert Settings and summary formatting.
            daily_data = {
                "type": 7,
                "type_name": "Daily",
                "schedule": {"time": "10:00"},
                "pre_alerts": [],
                "additional_info": "",
            }
            summary_flow.ensure_default_settings(daily_data)
            interval_default = summary_flow.format_interval(daily_data)
            daily_data["schedule"]["interval"] = 3
            interval_plural = summary_flow.format_interval(daily_data)

            menu_ctx = _DummyContext({"temp_alert": daily_data})
            menu_query = _DummyCallbackQuery("ms_open", _DummyMessage())
            menu_state = run_async(settings_flow.show_multi_setting_menu(
                _DummyUpdate(callback_query=menu_query),
                menu_ctx,
            ))
            menu_edit = menu_query.edits[-1] if menu_query.edits else {}
            menu_rows = _extract_rows(menu_edit.get("reply_markup"))
            checks_settings_summary = {
                "menu_state_multi_settings": menu_state == C.MULTI_SETTINGS,
                "menu_has_interval_button": any("ms_interval" in row for row in menu_rows),
                "interval_default_daily": interval_default == "Every 1 day",
                "interval_plural_daily": interval_plural == "Every 3 days",
            }
            dbg.section("daily_settings_and_summary", {
                "checks": checks_settings_summary,
                "menu_rows": menu_rows,
                "interval_default": interval_default,
                "interval_plural": interval_plural,
                "settings_text": menu_edit.get("text"),
            })
            if not all(checks_settings_summary.values()):
                dbg.problem("daily_settings_and_summary_failed", {"checks": checks_settings_summary})

            # Check 7: scheduler recurrence for daily is strict-future and anchor-stable.
            daily_simple = {
                "id": "daily_simple",
                "type": 7,
                "schedule": {"interval": 1, "time": "10:00"},
            }
            simple_ref = datetime(2026, 3, 10, 10, 5, 0)
            simple_next = get_next_occurrence(daily_simple, simple_ref)

            daily_anchor = {
                "id": "daily_anchor",
                "type": 7,
                "schedule": {"interval": 3, "time": "10:00", "start_marker": "01/03/2026"},
            }
            anchor_ref = datetime(2026, 3, 5, 12, 0, 0)
            anchor_next = get_next_occurrence(daily_anchor, anchor_ref)
            strict_ref = datetime(2026, 3, 7, 10, 0, 0)
            strict_next = get_next_occurrence(daily_anchor, strict_ref)

            daily_created_fallback = {
                "id": "daily_created",
                "type": 7,
                "created_at": "2026-03-01T15:45:00",
                "schedule": {"interval": 2, "time": "09:00"},
            }
            created_ref = datetime(2026, 3, 4, 10, 0, 0)
            created_next = get_next_occurrence(daily_created_fallback, created_ref)

            checks_scheduler = {
                "interval_one_next_day_at_time": simple_next == datetime(2026, 3, 11, 10, 0, 0),
                "interval_anchor_cycle_respected": anchor_next == datetime(2026, 3, 7, 10, 0, 0),
                "strict_future_not_equal_reference": strict_next == datetime(2026, 3, 10, 10, 0, 0),
                "created_at_fallback_uses_anchor_cycle": created_next == datetime(2026, 3, 5, 9, 0, 0),
            }
            dbg.section("daily_scheduler_recurrence", {
                "checks": checks_scheduler,
                "simple_ref": simple_ref.isoformat(),
                "simple_next": simple_next.isoformat() if simple_next else None,
                "anchor_ref": anchor_ref.isoformat(),
                "anchor_next": anchor_next.isoformat() if anchor_next else None,
                "strict_ref": strict_ref.isoformat(),
                "strict_next": strict_next.isoformat() if strict_next else None,
                "created_ref": created_ref.isoformat(),
                "created_next": created_next.isoformat() if created_next else None,
            })
            if not all(checks_scheduler.values()):
                dbg.problem("daily_scheduler_recurrence_failed", {
                    "checks": checks_scheduler,
                    "simple_next": simple_next.isoformat() if simple_next else None,
                    "anchor_next": anchor_next.isoformat() if anchor_next else None,
                    "strict_next": strict_next.isoformat() if strict_next else None,
                    "created_next": created_next.isoformat() if created_next else None,
                })

            # Check 8: detailed card renders daily recurrence and day-based interval labels.
            detail_alert_plural = {
                "id": "daily_detail_plural",
                "type": 7,
                "type_name": "Daily",
                "title": "Water Plants",
                "active": True,
                "schedule": {"time": "10:00", "interval": "3"},
                "pre_alerts": [],
                "tags": [],
                "additional_info": "",
            }
            detail_alert_singular = {
                "id": "daily_detail_singular",
                "type": 7,
                "type_name": "Daily",
                "title": "Take Medicine",
                "active": True,
                "schedule": {"time": "10:00", "interval": "bad"},
                "pre_alerts": [],
                "tags": [],
                "additional_info": "",
            }
            detail_plural_text = format_detailed_card(detail_alert_plural)
            detail_singular_text = format_detailed_card(detail_alert_singular)
            checks_detail = {
                "has_interval_line": "🔁 Interval:" in detail_plural_text,
                "plural_interval_label": "🔁 Interval: Every 3 Days" in detail_plural_text,
                "invalid_interval_falls_back_singular": "🔁 Interval: Every Day" in detail_singular_text,
            }
            dbg.section("daily_detail_card", {
                "checks": checks_detail,
                "detail_plural_text": detail_plural_text,
                "detail_singular_text": detail_singular_text,
            })
            if not all(checks_detail.values()):
                dbg.problem("daily_detail_card_failed", {
                    "checks": checks_detail,
                    "detail_plural_text": detail_plural_text,
                    "detail_singular_text": detail_singular_text,
                })
        finally:
            ACTIVE_RUNTIME_STORAGE = None
            if original_mainbot is None:
                sys.modules.pop("mainbot", None)
            else:
                sys.modules["mainbot"] = original_mainbot
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    prompt_ok = not dbg.has_problem("daily_prompt_failed")
    mode_fixed_ok = not dbg.has_problem("daily_mode_fixed_failed")
    confirm_prompt_ok = not dbg.has_problem("daily_confirm_prompt_failed")
    change_ok = not dbg.has_problem("daily_confirm_change_failed")
    yes_ok = not dbg.has_problem("daily_confirm_yes_failed")
    mode_fuzzy_ok = not dbg.has_problem("daily_mode_fuzzy_failed")
    fuzzy_input_ok = not dbg.has_problem("daily_fuzzy_input_failed")
    fuzzy_reject_ok = not dbg.has_problem("daily_fuzzy_rejected_payload_failed")
    fuzzy_time_adjust_ok = not dbg.has_problem("daily_fuzzy_time_adjust_failed")
    fuzzy_time_callback_ok = not dbg.has_problem("daily_fuzzy_time_adjust_callback_failed")
    stale_ok = not dbg.has_problem("daily_stale_int1_callback_failed")
    settings_summary_ok = not dbg.has_problem("daily_settings_and_summary_failed")
    scheduler_ok = not dbg.has_problem("daily_scheduler_recurrence_failed")
    detail_card_ok = not dbg.has_problem("daily_detail_card_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"prompt: {'OK' if prompt_ok else 'FAIL'}",
        f"mode_fixed: {'OK' if mode_fixed_ok else 'FAIL'}",
        f"confirm_prompt: {'OK' if confirm_prompt_ok else 'FAIL'}",
        f"confirm_change: {'OK' if change_ok else 'FAIL'}",
        f"confirm_yes: {'OK' if yes_ok else 'FAIL'}",
        f"mode_fuzzy: {'OK' if mode_fuzzy_ok else 'FAIL'}",
        f"fuzzy_input: {'OK' if fuzzy_input_ok else 'FAIL'}",
        f"fuzzy_rejected_payload: {'OK' if fuzzy_reject_ok else 'FAIL'}",
        f"fuzzy_time_adjust: {'OK' if fuzzy_time_adjust_ok else 'FAIL'}",
        f"fuzzy_time_callback: {'OK' if fuzzy_time_callback_ok else 'FAIL'}",
        f"stale_int1: {'OK' if stale_ok else 'FAIL'}",
        f"settings_summary: {'OK' if settings_summary_ok else 'FAIL'}",
        f"scheduler_recurrence: {'OK' if scheduler_ok else 'FAIL'}",
        f"detail_card: {'OK' if detail_card_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
