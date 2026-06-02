#!/usr/bin/env python3
import os
import sys
from datetime import datetime
from types import SimpleNamespace


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
SCRIPT_TITLE = "placebo_buttons_debug"
FEATURE_TITLE = "Placebo DONE/NOTED Buttons"

IMPORT_ERROR = None
try:
    from modules import constants as C
    from modules.scheduler_messagelogic import (
        ACTION_LABEL_ACTIVATE,
        ACTION_LABEL_DELETE,
        ACTION_LABEL_POSTPONE,
        ACTION_LABEL_SNOOZE,
        get_alert_keyboard,
        get_pre_alert_keyboard,
        get_missed_alert_keyboard,
        build_alert_detail_keyboard,
        build_pre_alert_detail_keyboard,
        _build_placebo_done_callback,
        _build_placebo_noted_callback,
        _build_bday_noted_callback,
    )
    from modules.handlers.scheduler_handlers import (
        _build_toggle_keyboard_for_message,
        handle_placebo_done,
        handle_placebo_noted,
    )
    from modules.handlers.birthday_flow.message_suggestions.callbacks import (
        build_bday_msg_callback,
    )
    from modules.ui.keyboards.notification_kb import (
        ACTION_LABEL_NOTED as NEW_ACTION_LABEL_NOTED,
        ACTION_LABEL_INFO as NEW_ACTION_LABEL_INFO,
        build_alert_notification_keyboard,
        build_birthday_notification_keyboard,
        build_prealert_notification_keyboard,
        build_missed_alert_keyboard as build_missed_alert_keyboard_new,
    )
    from modules.ui.keyboards.detail_kb import build_detail_keyboard
except ModuleNotFoundError as exc:  # pragma: no cover
    IMPORT_ERROR = exc


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _kb_labels(keyboard_markup):
    if not keyboard_markup:
        return []
    return [btn.text for row in keyboard_markup.inline_keyboard for btn in row]


def _kb_rows(keyboard_markup):
    if not keyboard_markup:
        return []
    return [[btn.text for btn in row] for row in keyboard_markup.inline_keyboard]


def _kb_callbacks(keyboard_markup):
    if not keyboard_markup:
        return []
    return [btn.callback_data for row in keyboard_markup.inline_keyboard for btn in row]


POSTPONE_LABEL = ACTION_LABEL_POSTPONE
SNOOZE_LABEL = ACTION_LABEL_SNOOZE
ACTIVATE_LABEL = ACTION_LABEL_ACTIVATE
DELETE_LABEL = ACTION_LABEL_DELETE
DETAIL_INFO_LABEL = "ℹ️ Detailed info"


class _DummyQuery:
    def __init__(self, data, answer_exception=None):
        self.data = data
        self.answers = []
        self.answer_attempts = 0
        self.answer_exception = answer_exception

    async def answer(self, text=None, show_alert=False):
        self.answer_attempts += 1
        if self.answer_exception is not None:
            raise self.answer_exception
        self.answers.append({
            "text": text,
            "show_alert": bool(show_alert),
        })


class _FakeStorage:
    def __init__(self, alerts_by_id):
        self._alerts_by_id = dict(alerts_by_id or {})
        self.logged_events = []

    def get_alert_by_id(self, user_id, alert_id):
        alert = self._alerts_by_id.get(alert_id)
        return dict(alert) if isinstance(alert, dict) else None

    def log_user_event(self, user_id, event_type, payload=None):
        self.logged_events.append({
            "user_id": str(user_id),
            "event_type": event_type,
            "payload": dict(payload or {}),
        })


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    bot_data = getattr(context, "bot_data", None)
    if bot_data is None:
        bot_data = {}
        setattr(context, "bot_data", bot_data)
    set_bot_runtime(
        bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )


async def _invoke_handler(handler, callback_data, storage, user_id=777, answer_exception=None):
    query = _DummyQuery(callback_data, answer_exception=answer_exception)
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id),
    )
    context = SimpleNamespace(bot_data={})
    _seed_runtime(context, storage)
    error = None
    try:
        await handler(update, context)
    except Exception as exc:  # pragma: no cover - debug failure path
        error = str(exc)
    return query, storage.logged_events, error


def _run_checks(dbg):
    alert_id = "a1b2c3d4"
    orig = datetime(2026, 3, 10, 9, 0, 0)
    occ = datetime(2026, 3, 10, 10, 0, 0)

    # --- Regular recurring alert (type 3 = Weekly) ---
    regular_alert = {"id": alert_id, "type": 3, "title": "Test"}
    kb = get_alert_keyboard(regular_alert, occ, orig)
    labels = _kb_labels(kb)
    rows = _kb_rows(kb)
    callbacks = _kb_callbacks(kb)
    regular_checks = {
        "has_done_button": any("DONE" in l for l in labels),
        "done_is_first_row": kb.inline_keyboard[0][0].text == "✅ DONE !" if kb else False,
        "done_prefix_correct": any(cb.startswith(C.CB_PLACEBO_DONE) for cb in callbacks),
        "no_noted_button": not any("NOTED" in l for l in labels),
        "postpone_label_present": POSTPONE_LABEL in labels,
        "snooze_label_present": SNOOZE_LABEL in labels,
        "delete_label_present": DELETE_LABEL in labels,
        "info_label_present": DETAIL_INFO_LABEL in labels,
        "all_rows_single_button": all(len(row) == 1 for row in rows),
        "postpone_own_row": [POSTPONE_LABEL] in rows,
        "snooze_own_row": [SNOOZE_LABEL] in rows,
        "delete_own_row": [DELETE_LABEL] in rows,
        "info_own_row": [DETAIL_INFO_LABEL] in rows,
    }
    dbg.section("regular_alert_keyboard", {"rows": rows, "labels": labels, "checks": regular_checks})
    if not all(regular_checks.values()):
        dbg.problem("regular_alert_keyboard_failed", {"checks": regular_checks, "rows": rows, "labels": labels})

    regular_alert_inactive = {"id": alert_id, "type": 3, "title": "Test", "active": False}
    kb_inactive = get_alert_keyboard(regular_alert_inactive, occ, orig)
    labels_inactive = _kb_labels(kb_inactive)
    rows_inactive = _kb_rows(kb_inactive)
    inactive_checks = {
        "activate_label_present": ACTIVATE_LABEL in labels_inactive,
        "snooze_label_hidden": SNOOZE_LABEL not in labels_inactive,
        "activate_own_row": [ACTIVATE_LABEL] in rows_inactive,
    }
    dbg.section(
        "regular_alert_inactive_keyboard",
        {"rows": rows_inactive, "labels": labels_inactive, "checks": inactive_checks},
    )
    if not all(inactive_checks.values()):
        dbg.problem("regular_alert_inactive_keyboard_failed", {"checks": inactive_checks})

    # --- One-time alert (type 5) ---
    onetime_alert = {"id": alert_id, "type": 5, "title": "Once"}
    kb_once = get_alert_keyboard(onetime_alert, occ, orig)
    labels_once = _kb_labels(kb_once)
    rows_once = _kb_rows(kb_once)
    onetime_checks = {
        "has_done_button": any("DONE" in l for l in labels_once),
        "no_snooze": SNOOZE_LABEL not in labels_once,
        "postpone_label_present": POSTPONE_LABEL in labels_once,
        "delete_label_present": DELETE_LABEL in labels_once,
        "info_label_present": DETAIL_INFO_LABEL in labels_once,
        "all_rows_single_button": all(len(row) == 1 for row in rows_once),
        "postpone_own_row": [POSTPONE_LABEL] in rows_once,
        "delete_own_row": [DELETE_LABEL] in rows_once,
    }
    dbg.section("onetime_alert_keyboard", {"rows": rows_once, "labels": labels_once, "checks": onetime_checks})
    if not all(onetime_checks.values()):
        dbg.problem("onetime_alert_keyboard_failed", {"checks": onetime_checks})

    # --- Birthday alert (type 6) ---
    bday_alert = {"id": alert_id, "type": 6, "title": "Birthday"}
    kb_bday = get_alert_keyboard(bday_alert, occ, orig)
    labels_bday = _kb_labels(kb_bday)
    rows_bday = _kb_rows(kb_bday)
    callbacks_bday = _kb_callbacks(kb_bday)
    bday_checks = {
        "has_noted_button": any("NOTED" in l for l in labels_bday),
        "no_done_button": not any("DONE" in l for l in labels_bday),
        "noted_is_first_row": kb_bday.inline_keyboard[0][0].text == "👀 NOTED !" if kb_bday else False,
        "bday_noted_prefix": any(cb.startswith(C.CB_BDAY_NOTED) for cb in callbacks_bday),
        "postpone_own_row": [POSTPONE_LABEL] in rows_bday,
        "snooze_own_row": [SNOOZE_LABEL] in rows_bday,
        "delete_own_row": [DELETE_LABEL] in rows_bday,
        "info_own_row": [DETAIL_INFO_LABEL] in rows_bday,
    }
    dbg.section("birthday_alert_keyboard", {"rows": rows_bday, "labels": labels_bday, "checks": bday_checks})
    if not all(bday_checks.values()):
        dbg.problem("birthday_alert_keyboard_failed", {"checks": bday_checks, "labels": labels_bday})

    # --- Pre-alert keyboard (all types) ---
    for alert_type, label in [(3, "weekly"), (5, "onetime"), (6, "birthday")]:
        pre_alert = {"id": alert_id, "type": alert_type, "title": f"Pre {label}"}
        kb_pre = get_pre_alert_keyboard(pre_alert, occ, orig)
        labels_pre = _kb_labels(kb_pre)
        rows_pre = _kb_rows(kb_pre)
        callbacks_pre = _kb_callbacks(kb_pre)
        pre_checks = {
            "has_noted_button": any("NOTED" in l for l in labels_pre),
            "noted_is_first_row": kb_pre.inline_keyboard[0][0].text == "👀 NOTED !" if kb_pre else False,
            "pre_noted_prefix": any(cb.startswith(C.CB_PLACEBO_NOTED) for cb in callbacks_pre),
            "no_done_button": not any("DONE" in l for l in labels_pre),
            "postpone_own_row": [POSTPONE_LABEL] in rows_pre,
            "delete_own_row": [DELETE_LABEL] in rows_pre,
            "info_own_row": [DETAIL_INFO_LABEL] in rows_pre,
            "all_rows_single_button": all(len(row) == 1 for row in rows_pre),
            "recurring_snooze_own_row": ([SNOOZE_LABEL] in rows_pre) if alert_type != 5 else True,
            "one_time_no_snooze": (SNOOZE_LABEL not in labels_pre) if alert_type == 5 else True,
        }
        section_name = f"pre_alert_keyboard_{label}"
        dbg.section(section_name, {"rows": rows_pre, "labels": labels_pre, "checks": pre_checks})
        if not all(pre_checks.values()):
            dbg.problem(f"pre_alert_keyboard_{label}_failed", {"checks": pre_checks})

    pre_alert_inactive = {"id": alert_id, "type": 3, "title": "Pre inactive", "active": False}
    kb_pre_inactive = get_pre_alert_keyboard(pre_alert_inactive, occ, orig)
    labels_pre_inactive = _kb_labels(kb_pre_inactive)
    rows_pre_inactive = _kb_rows(kb_pre_inactive)
    pre_inactive_checks = {
        "activate_label_present": ACTIVATE_LABEL in labels_pre_inactive,
        "snooze_label_hidden": SNOOZE_LABEL not in labels_pre_inactive,
        "activate_own_row": [ACTIVATE_LABEL] in rows_pre_inactive,
    }
    dbg.section(
        "pre_alert_inactive_keyboard",
        {"rows": rows_pre_inactive, "labels": labels_pre_inactive, "checks": pre_inactive_checks},
    )
    if not all(pre_inactive_checks.values()):
        dbg.problem("pre_alert_inactive_keyboard_failed", {"checks": pre_inactive_checks})

    # --- Missed alert keyboard (no placebo buttons) ---
    missed_alert = {"id": alert_id, "type": 3, "title": "Missed"}
    kb_missed = get_missed_alert_keyboard(missed_alert)
    labels_missed = _kb_labels(kb_missed)
    missed_checks = {
        "no_done_button": not any("DONE" in l for l in labels_missed),
        "no_noted_button": not any("NOTED" in l for l in labels_missed),
    }
    dbg.section("missed_alert_keyboard", {"labels": labels_missed, "checks": missed_checks})
    if not all(missed_checks.values()):
        dbg.problem("missed_alert_keyboard_failed", {"checks": missed_checks})

    # --- Detail keyboards ---
    kb_detail_pre = build_pre_alert_detail_keyboard(regular_alert, occ, orig)
    labels_detail_pre = _kb_labels(kb_detail_pre)
    rows_detail_pre = _kb_rows(kb_detail_pre)
    callbacks_detail_pre = _kb_callbacks(kb_detail_pre)
    detail_pre_checks = {
        "has_noted": any("NOTED" in l for l in labels_detail_pre),
        "noted_first": kb_detail_pre.inline_keyboard[0][0].text == "👀 NOTED !" if kb_detail_pre else False,
        "postpone_own_row": [POSTPONE_LABEL] in rows_detail_pre,
        "snooze_own_row": [SNOOZE_LABEL] in rows_detail_pre,
        "delete_own_row": [DELETE_LABEL] in rows_detail_pre,
        "edit_text_own_row": ["✏️ Edit text"] in rows_detail_pre,
        "all_rows_single_button": all(len(row) == 1 for row in rows_detail_pre),
        "edittext_pre_callback_present": any(cb.startswith("manage_edittext_pre_") for cb in callbacks_detail_pre),
    }
    dbg.section(
        "detail_pre_alert_keyboard",
        {"rows": rows_detail_pre, "labels": labels_detail_pre, "callbacks": callbacks_detail_pre, "checks": detail_pre_checks},
    )
    if not all(detail_pre_checks.values()):
        dbg.problem("detail_pre_alert_keyboard_failed", {"checks": detail_pre_checks})

    kb_detail_due = build_alert_detail_keyboard(regular_alert, occ, orig)
    labels_detail_due = _kb_labels(kb_detail_due)
    rows_detail_due = _kb_rows(kb_detail_due)
    callbacks_detail_due = _kb_callbacks(kb_detail_due)
    detail_due_checks = {
        "has_done": any("DONE" in l for l in labels_detail_due),
        "done_first": kb_detail_due.inline_keyboard[0][0].text == "✅ DONE !" if kb_detail_due else False,
        "postpone_own_row": [POSTPONE_LABEL] in rows_detail_due,
        "snooze_own_row": [SNOOZE_LABEL] in rows_detail_due,
        "delete_own_row": [DELETE_LABEL] in rows_detail_due,
        "edit_text_own_row": ["✏️ Edit text"] in rows_detail_due,
        "all_rows_single_button": all(len(row) == 1 for row in rows_detail_due),
        "edittext_due_callback_present": any(cb.startswith("manage_edittext_due_") for cb in callbacks_detail_due),
    }
    dbg.section(
        "detail_due_alert_keyboard",
        {"rows": rows_detail_due, "labels": labels_detail_due, "callbacks": callbacks_detail_due, "checks": detail_due_checks},
    )
    if not all(detail_due_checks.values()):
        dbg.problem("detail_due_alert_keyboard_failed", {"checks": detail_due_checks})

    kb_detail_due_inactive = build_alert_detail_keyboard(regular_alert_inactive, occ, orig)
    labels_detail_due_inactive = _kb_labels(kb_detail_due_inactive)
    rows_detail_due_inactive = _kb_rows(kb_detail_due_inactive)
    detail_due_inactive_checks = {
        "activate_label_present": ACTIVATE_LABEL in labels_detail_due_inactive,
        "snooze_label_hidden": SNOOZE_LABEL not in labels_detail_due_inactive,
        "activate_own_row": [ACTIVATE_LABEL] in rows_detail_due_inactive,
    }
    dbg.section(
        "detail_due_inactive_keyboard",
        {"rows": rows_detail_due_inactive, "labels": labels_detail_due_inactive, "checks": detail_due_inactive_checks},
    )
    if not all(detail_due_inactive_checks.values()):
        dbg.problem("detail_due_inactive_keyboard_failed", {"checks": detail_due_inactive_checks})

    kb_detail_due_once = build_alert_detail_keyboard(onetime_alert, occ, orig)
    labels_detail_due_once = _kb_labels(kb_detail_due_once)
    rows_detail_due_once = _kb_rows(kb_detail_due_once)
    detail_due_once_checks = {
        "has_done": any("DONE" in l for l in labels_detail_due_once),
        "done_first": kb_detail_due_once.inline_keyboard[0][0].text == "✅ DONE !" if kb_detail_due_once else False,
        "no_snooze": SNOOZE_LABEL not in labels_detail_due_once,
        "postpone_own_row": [POSTPONE_LABEL] in rows_detail_due_once,
        "delete_own_row": [DELETE_LABEL] in rows_detail_due_once,
        "edit_text_own_row": ["✏️ Edit text"] in rows_detail_due_once,
        "all_rows_single_button": all(len(row) == 1 for row in rows_detail_due_once),
    }
    dbg.section(
        "detail_due_onetime_alert_keyboard",
        {"rows": rows_detail_due_once, "labels": labels_detail_due_once, "checks": detail_due_once_checks},
    )
    if not all(detail_due_once_checks.values()):
        dbg.problem("detail_due_onetime_alert_keyboard_failed", {"checks": detail_due_once_checks})

    kb_detail_bday = build_alert_detail_keyboard(bday_alert, occ, orig)
    labels_detail_bday = _kb_labels(kb_detail_bday)
    rows_detail_bday = _kb_rows(kb_detail_bday)
    callbacks_detail_bday = _kb_callbacks(kb_detail_bday)
    detail_bday_checks = {
        "has_noted": any("NOTED" in l for l in labels_detail_bday),
        "no_done": not any("DONE" in l for l in labels_detail_bday),
        "noted_first": kb_detail_bday.inline_keyboard[0][0].text == "👀 NOTED !" if kb_detail_bday else False,
        "postpone_own_row": [POSTPONE_LABEL] in rows_detail_bday,
        "snooze_own_row": [SNOOZE_LABEL] in rows_detail_bday,
        "delete_own_row": [DELETE_LABEL] in rows_detail_bday,
        "edit_text_own_row": ["✏️ Edit text"] in rows_detail_bday,
        "all_rows_single_button": all(len(row) == 1 for row in rows_detail_bday),
        "edittext_due_callback_present": any(cb.startswith("manage_edittext_due_") for cb in callbacks_detail_bday),
    }
    dbg.section(
        "detail_bday_alert_keyboard",
        {"rows": rows_detail_bday, "labels": labels_detail_bday, "callbacks": callbacks_detail_bday, "checks": detail_bday_checks},
    )
    if not all(detail_bday_checks.values()):
        dbg.problem("detail_bday_alert_keyboard_failed", {"checks": detail_bday_checks})

    # --- 64-byte callback limit ---
    cb_done = _build_placebo_done_callback(alert_id, orig, occ)
    cb_noted = _build_placebo_noted_callback(alert_id, orig, occ)
    cb_bnoted = _build_bday_noted_callback(alert_id, orig, occ)
    cb_bmsg = build_bday_msg_callback("cringe", alert_id, occ)
    limit_checks = {
        "done_fits": len(cb_done.encode("utf-8")) <= 64,
        "noted_fits": len(cb_noted.encode("utf-8")) <= 64,
        "bday_noted_fits": len(cb_bnoted.encode("utf-8")) <= 64,
        "bday_msg_fits": len(cb_bmsg.encode("utf-8")) <= 64,
    }
    dbg.section("callback_64byte_limit", {
        "callbacks": {
            "done": cb_done,
            "noted": cb_noted,
            "bday_noted": cb_bnoted,
            "bday_msg": cb_bmsg,
        },
        "lengths": {
            "done": len(cb_done.encode("utf-8")),
            "noted": len(cb_noted.encode("utf-8")),
            "bday_noted": len(cb_bnoted.encode("utf-8")),
            "bday_msg": len(cb_bmsg.encode("utf-8")),
        },
        "checks": limit_checks,
    })
    if not all(limit_checks.values()):
        dbg.problem("callback_64byte_limit_failed", {"checks": limit_checks})


def _check_placebo_done_handler(dbg):
    alert_id = "deadbeef"
    now = datetime(2026, 3, 10, 9, 0, 0)
    ts = str(int(now.timestamp()))

    recurring_alert = {
        "id": alert_id,
        "type": 3,
        "title": "Recurring",
        "schedule": {"weekdays": ["Tue"], "time": "10:00", "interval": 1},
    }
    recurring_storage = _FakeStorage({alert_id: recurring_alert})
    recurring_data = f"{C.CB_PLACEBO_DONE}{alert_id}_{ts}_{ts}"
    query_rec, events_rec, err_rec = run_async(
        _invoke_handler(handle_placebo_done, recurring_data, recurring_storage)
    )
    recurring_checks = {
        "no_exception": err_rec is None,
        "single_answer": len(query_rec.answers) == 1,
        "single_attempt": query_rec.answer_attempts == 1,
        "show_alert_true": bool(query_rec.answers and query_rec.answers[0].get("show_alert")),
        "text_present": bool(query_rec.answers and query_rec.answers[0].get("text")),
        "event_logged": any(
            event.get("event_type") == "placebo_done_pressed"
            and event.get("payload", {}).get("alert_id") == alert_id
            and event.get("payload", {}).get("alert_type") == 3
            for event in events_rec
        ),
        "feedback_sent_logged": any(
            event.get("event_type") == "placebo_done_feedback_sent"
            and event.get("payload", {}).get("alert_id") == alert_id
            and event.get("payload", {}).get("alert_type") == 3
            for event in events_rec
        ),
    }
    dbg.section("placebo_done_recurring_handler", {
        "callback_data": recurring_data,
        "answers": query_rec.answers,
        "events": events_rec,
        "error": err_rec,
        "checks": recurring_checks,
    })
    if not all(recurring_checks.values()):
        dbg.problem("placebo_done_recurring_handler_failed", {"checks": recurring_checks})

    onetime_alert = {
        "id": alert_id,
        "type": 5,
        "title": "One-time",
    }
    onetime_storage = _FakeStorage({alert_id: onetime_alert})
    query_once, events_once, err_once = run_async(
        _invoke_handler(handle_placebo_done, recurring_data, onetime_storage)
    )
    onetime_checks = {
        "no_exception": err_once is None,
        "single_answer": len(query_once.answers) == 1,
        "single_attempt": query_once.answer_attempts == 1,
        "show_alert_true": bool(query_once.answers and query_once.answers[0].get("show_alert")),
        "text_matches": bool(
            query_once.answers
            and query_once.answers[0].get("text") == "👋 Completed and archived!"
        ),
        "event_logged": any(
            event.get("event_type") == "placebo_done_pressed"
            and event.get("payload", {}).get("alert_type") == 5
            for event in events_once
        ),
        "feedback_sent_logged": any(
            event.get("event_type") == "placebo_done_feedback_sent"
            and event.get("payload", {}).get("alert_type") == 5
            and event.get("payload", {}).get("result") == "one_time_archived"
            for event in events_once
        ),
    }
    dbg.section("placebo_done_onetime_handler", {
        "answers": query_once.answers,
        "events": events_once,
        "error": err_once,
        "checks": onetime_checks,
    })
    if not all(onetime_checks.values()):
        dbg.problem("placebo_done_onetime_handler_failed", {"checks": onetime_checks})

    missing_storage = _FakeStorage({})
    query_missing, events_missing, err_missing = run_async(
        _invoke_handler(handle_placebo_done, recurring_data, missing_storage)
    )
    missing_checks = {
        "no_exception": err_missing is None,
        "single_answer": len(query_missing.answers) == 1,
        "single_attempt": query_missing.answer_attempts == 1,
        "show_alert_true": bool(query_missing.answers and query_missing.answers[0].get("show_alert")),
        "not_found_text": bool(
            query_missing.answers
            and query_missing.answers[0].get("text") == "Alert not found"
        ),
        "feedback_sent_logged": any(
            event.get("event_type") == "placebo_done_feedback_sent"
            and event.get("payload", {}).get("alert_type") is None
            and event.get("payload", {}).get("result") == "alert_not_found"
            for event in events_missing
        ),
        "no_pressed_logged": not any(
            event.get("event_type") == "placebo_done_pressed"
            for event in events_missing
        ),
    }
    dbg.section("placebo_done_missing_handler", {
        "answers": query_missing.answers,
        "events": events_missing,
        "error": err_missing,
        "checks": missing_checks,
    })
    if not all(missing_checks.values()):
        dbg.problem("placebo_done_missing_handler_failed", {"checks": missing_checks})


def _check_placebo_noted_handler(dbg):
    alert_id = "feedface"
    orig = datetime(2026, 3, 10, 9, 0, 0)
    occ = datetime(2026, 3, 11, 10, 0, 0)
    orig_ts = str(int(orig.timestamp()))
    occ_ts = str(int(occ.timestamp()))
    expected_date = occ.strftime("%d/%m/%Y")

    storage_with_occ = _FakeStorage({})
    data_with_occ = f"{C.CB_PLACEBO_NOTED}{alert_id}_{orig_ts}_{occ_ts}"
    query_occ, events_occ, err_occ = run_async(
        _invoke_handler(handle_placebo_noted, data_with_occ, storage_with_occ)
    )
    with_occ_checks = {
        "no_exception": err_occ is None,
        "single_answer": len(query_occ.answers) == 1,
        "single_attempt": query_occ.answer_attempts == 1,
        "show_alert_true": bool(query_occ.answers and query_occ.answers[0].get("show_alert")),
        "text_matches": bool(
            query_occ.answers
            and query_occ.answers[0].get("text") == f"📝 Be ready, {expected_date} is close!"
        ),
        "event_logged": any(
            event.get("event_type") == "placebo_noted_pressed"
            and event.get("payload", {}).get("alert_id") == alert_id
            and event.get("payload", {}).get("alert_type") is None
            for event in events_occ
        ),
        "feedback_sent_logged": any(
            event.get("event_type") == "placebo_noted_feedback_sent"
            and event.get("payload", {}).get("result") == "prealert_date_shown"
            for event in events_occ
        ),
    }
    dbg.section("placebo_noted_with_occurrence_handler", {
        "callback_data": data_with_occ,
        "answers": query_occ.answers,
        "events": events_occ,
        "error": err_occ,
        "checks": with_occ_checks,
    })
    if not all(with_occ_checks.values()):
        dbg.problem("placebo_noted_with_occurrence_handler_failed", {"checks": with_occ_checks})

    storage_no_occ = _FakeStorage({})
    data_no_occ = f"{C.CB_PLACEBO_NOTED}{alert_id}"
    query_no_occ, events_no_occ, err_no_occ = run_async(
        _invoke_handler(handle_placebo_noted, data_no_occ, storage_no_occ)
    )
    no_occ_checks = {
        "no_exception": err_no_occ is None,
        "single_answer": len(query_no_occ.answers) == 1,
        "single_attempt": query_no_occ.answer_attempts == 1,
        "show_alert_true": bool(query_no_occ.answers and query_no_occ.answers[0].get("show_alert")),
        "text_matches": bool(
            query_no_occ.answers and query_no_occ.answers[0].get("text") == "📝 Noted!"
        ),
        "event_logged": any(
            event.get("event_type") == "placebo_noted_pressed"
            and event.get("payload", {}).get("alert_id") == alert_id
            and event.get("payload", {}).get("alert_type") is None
            for event in events_no_occ
        ),
        "feedback_sent_logged": any(
            event.get("event_type") == "placebo_noted_feedback_sent"
            and event.get("payload", {}).get("result") == "generic_noted"
            for event in events_no_occ
        ),
    }
    dbg.section("placebo_noted_without_occurrence_handler", {
        "callback_data": data_no_occ,
        "answers": query_no_occ.answers,
        "events": events_no_occ,
        "error": err_no_occ,
        "checks": no_occ_checks,
    })
    if not all(no_occ_checks.values()):
        dbg.problem("placebo_noted_without_occurrence_handler_failed", {"checks": no_occ_checks})

    storage_bad_occ = _FakeStorage({})
    data_bad_occ = f"{C.CB_PLACEBO_NOTED}{alert_id}_{orig_ts}_not_a_timestamp"
    query_bad_occ, events_bad_occ, err_bad_occ = run_async(
        _invoke_handler(handle_placebo_noted, data_bad_occ, storage_bad_occ)
    )
    bad_occ_checks = {
        "no_exception": err_bad_occ is None,
        "single_answer": len(query_bad_occ.answers) == 1,
        "single_attempt": query_bad_occ.answer_attempts == 1,
        "show_alert_true": bool(query_bad_occ.answers and query_bad_occ.answers[0].get("show_alert")),
        "fallback_text_matches": bool(
            query_bad_occ.answers and query_bad_occ.answers[0].get("text") == "📝 Noted!"
        ),
        "event_logged": any(
            event.get("event_type") == "placebo_noted_pressed"
            and event.get("payload", {}).get("alert_id") == alert_id
            for event in events_bad_occ
        ),
        "feedback_sent_logged": any(
            event.get("event_type") == "placebo_noted_feedback_sent"
            and event.get("payload", {}).get("result") == "generic_noted"
            for event in events_bad_occ
        ),
    }
    dbg.section("placebo_noted_malformed_timestamp_handler", {
        "callback_data": data_bad_occ,
        "answers": query_bad_occ.answers,
        "events": events_bad_occ,
        "error": err_bad_occ,
        "checks": bad_occ_checks,
    })
    if not all(bad_occ_checks.values()):
        dbg.problem("placebo_noted_malformed_timestamp_handler_failed", {"checks": bad_occ_checks})


def _check_placebo_feedback_failure_telemetry(dbg):
    alert_id = "fadedcab"
    now = datetime(2026, 3, 10, 9, 0, 0)
    ts = str(int(now.timestamp()))
    failure_exc = RuntimeError("Query is too old and response timeout expired or query id is invalid")

    done_alert = {
        "id": alert_id,
        "type": 3,
        "title": "Recurring",
        "schedule": {"weekdays": ["Tue"], "time": "10:00", "interval": 1},
    }
    done_storage = _FakeStorage({alert_id: done_alert})
    done_data = f"{C.CB_PLACEBO_DONE}{alert_id}_{ts}_{ts}"
    done_query, done_events, done_err = run_async(
        _invoke_handler(
            handle_placebo_done,
            done_data,
            done_storage,
            answer_exception=failure_exc,
        )
    )
    done_checks = {
        "no_exception": done_err is None,
        "single_attempt": done_query.answer_attempts == 1,
        "no_success_answer": len(done_query.answers) == 0,
        "pressed_logged": any(
            event.get("event_type") == "placebo_done_pressed"
            for event in done_events
        ),
        "feedback_failed_logged": any(
            event.get("event_type") == "placebo_done_feedback_failed"
            and event.get("payload", {}).get("reason_code") == "query_too_old_or_invalid"
            for event in done_events
        ),
        "no_raw_error_leak": not any(
            "error" in event.get("payload", {})
            for event in done_events
        ),
    }
    dbg.section("placebo_done_feedback_failure_handler", {
        "answers": done_query.answers,
        "attempts": done_query.answer_attempts,
        "events": done_events,
        "error": done_err,
        "checks": done_checks,
    })
    if not all(done_checks.values()):
        dbg.problem("placebo_done_feedback_failure_handler_failed", {"checks": done_checks})

    noted_storage = _FakeStorage({})
    noted_data = f"{C.CB_PLACEBO_NOTED}{alert_id}_{ts}_{ts}"
    noted_query, noted_events, noted_err = run_async(
        _invoke_handler(
            handle_placebo_noted,
            noted_data,
            noted_storage,
            answer_exception=failure_exc,
        )
    )
    noted_checks = {
        "no_exception": noted_err is None,
        "single_attempt": noted_query.answer_attempts == 1,
        "no_success_answer": len(noted_query.answers) == 0,
        "pressed_logged": any(
            event.get("event_type") == "placebo_noted_pressed"
            for event in noted_events
        ),
        "feedback_failed_logged": any(
            event.get("event_type") == "placebo_noted_feedback_failed"
            and event.get("payload", {}).get("reason_code") == "query_too_old_or_invalid"
            for event in noted_events
        ),
        "no_raw_error_leak": not any(
            "error" in event.get("payload", {})
            for event in noted_events
        ),
    }
    dbg.section("placebo_noted_feedback_failure_handler", {
        "answers": noted_query.answers,
        "attempts": noted_query.answer_attempts,
        "events": noted_events,
        "error": noted_err,
        "checks": noted_checks,
    })
    if not all(noted_checks.values()):
        dbg.problem("placebo_noted_feedback_failure_handler_failed", {"checks": noted_checks})


def _run_checks_new_keyboards(dbg):
    """Verify new notification_kb and detail_kb keyboard builders."""
    alert_id = "new_kb_test01"
    orig = datetime(2026, 3, 10, 9, 0, 0)
    occ = datetime(2026, 3, 10, 10, 0, 0)

    # --- build_alert_notification_keyboard (AA, regular recurring) ---
    regular = {"id": alert_id, "type": 3, "title": "AA Test", "active": True}
    kb_aa = build_alert_notification_keyboard(regular, occ, orig)
    labels_aa = _kb_labels(kb_aa)
    callbacks_aa = _kb_callbacks(kb_aa)
    rows_aa = _kb_rows(kb_aa)
    aa_checks = {
        "noted_label": labels_aa[0] == NEW_ACTION_LABEL_NOTED if labels_aa else False,
        "pdone_prefix": callbacks_aa[0].startswith(C.CB_PLACEBO_DONE) if callbacks_aa else False,
        "postpone_present": POSTPONE_LABEL in labels_aa,
        "snooze_present": SNOOZE_LABEL in labels_aa,
        "delete_present": DELETE_LABEL in labels_aa,
        "info_present": NEW_ACTION_LABEL_INFO in labels_aa,
        "all_single_row": all(len(r) == 1 for r in rows_aa),
        "five_rows": len(rows_aa) == 5,
    }
    dbg.section("new_aa_keyboard", {"labels": labels_aa, "checks": aa_checks})
    if not all(aa_checks.values()):
        dbg.problem("new_aa_keyboard_failed", {"checks": aa_checks, "labels": labels_aa})

    # AA type 5 — no SNOOZE
    onetime = {"id": alert_id, "type": 5, "title": "Once", "active": True}
    kb_aa5 = build_alert_notification_keyboard(onetime, occ, orig)
    labels_aa5 = _kb_labels(kb_aa5)
    aa5_checks = {
        "no_snooze": SNOOZE_LABEL not in labels_aa5,
        "four_rows": len(_kb_rows(kb_aa5)) == 4,
    }
    dbg.section("new_aa_keyboard_type5", {"labels": labels_aa5, "checks": aa5_checks})
    if not all(aa5_checks.values()):
        dbg.problem("new_aa_keyboard_type5_failed", {"checks": aa5_checks})

    # --- build_birthday_notification_keyboard (BB) ---
    bday = {"id": alert_id, "type": 6, "title": "BB Test", "active": True}
    kb_bb = build_birthday_notification_keyboard(bday, occ, orig)
    labels_bb = _kb_labels(kb_bb)
    callbacks_bb = _kb_callbacks(kb_bb)
    bb_checks = {
        "noted_label": labels_bb[0] == NEW_ACTION_LABEL_NOTED if labels_bb else False,
        "bnote_prefix": callbacks_bb[0].startswith(C.CB_BDAY_NOTED) if callbacks_bb else False,
        "postpone_present": POSTPONE_LABEL in labels_bb,
        "snooze_present": SNOOZE_LABEL in labels_bb,
        "delete_present": DELETE_LABEL in labels_bb,
        "five_rows": len(_kb_rows(kb_bb)) == 5,
    }
    dbg.section("new_bb_keyboard", {"labels": labels_bb, "checks": bb_checks})
    if not all(bb_checks.values()):
        dbg.problem("new_bb_keyboard_failed", {"checks": bb_checks, "labels": labels_bb})

    # --- build_prealert_notification_keyboard (PA/PB) ---
    kb_pa = build_prealert_notification_keyboard(regular, occ, orig)
    labels_pa = _kb_labels(kb_pa)
    callbacks_pa = _kb_callbacks(kb_pa)
    pa_checks = {
        "noted_label": labels_pa[0] == NEW_ACTION_LABEL_NOTED if labels_pa else False,
        "pnote_prefix": callbacks_pa[0].startswith(C.CB_PLACEBO_NOTED) if callbacks_pa else False,
        "postpone_prefix": any(cb.startswith(C.CB_POSTPONE) for cb in callbacks_pa),
        "snooze_present": SNOOZE_LABEL in labels_pa,
        "delete_present": DELETE_LABEL in labels_pa,
        "info_present": NEW_ACTION_LABEL_INFO in labels_pa,
        "five_rows": len(_kb_rows(kb_pa)) == 5,
    }
    dbg.section("new_pa_keyboard", {"labels": labels_pa, "checks": pa_checks})
    if not all(pa_checks.values()):
        dbg.problem("new_pa_keyboard_failed", {"checks": pa_checks, "labels": labels_pa})

    # --- build_missed_alert_keyboard_new ---
    kb_missed_new = build_missed_alert_keyboard_new(regular)
    labels_missed_new = _kb_labels(kb_missed_new)
    missed_new_checks = {
        "delete_only": len(labels_missed_new) == 1,
        "delete_present": DELETE_LABEL in labels_missed_new,
    }
    dbg.section("new_missed_keyboard", {"labels": labels_missed_new, "checks": missed_new_checks})
    if not all(missed_new_checks.values()):
        dbg.problem("new_missed_keyboard_failed", {"checks": missed_new_checks})

    # --- build_detail_keyboard: Variant A (from notification, pre kind) ---
    kb_detail_a_pre = build_detail_keyboard(
        regular, from_notification=True, kind="pre",
        occurrence_time=occ, original_time=orig, postpone_count=0,
    )
    labels_a_pre = _kb_labels(kb_detail_a_pre)
    callbacks_a_pre = _kb_callbacks(kb_detail_a_pre)
    detail_a_pre_checks = {
        "noted_first": labels_a_pre[0] == NEW_ACTION_LABEL_NOTED if labels_a_pre else False,
        "pnote_prefix": callbacks_a_pre[0].startswith(C.CB_PLACEBO_NOTED) if callbacks_a_pre else False,
        "postpone_present": POSTPONE_LABEL in labels_a_pre,
        "snooze_present": SNOOZE_LABEL in labels_a_pre,
        "delete_uses_alertdel": any(cb.startswith(C.CB_ALERT_DELETE) for cb in callbacks_a_pre),
        "edit_present": "✏️ Edit fields" in labels_a_pre,
        "back_present": "⬅️ Back" in labels_a_pre,
        "back_uses_nback": any(cb.startswith(C.CB_NOTIF_BACK) for cb in callbacks_a_pre),
        "six_rows": len(_kb_rows(kb_detail_a_pre)) == 6,
    }
    dbg.section("detail_kb_variant_a_pre", {"labels": labels_a_pre, "checks": detail_a_pre_checks})
    if not all(detail_a_pre_checks.values()):
        dbg.problem("detail_kb_variant_a_pre_failed", {"checks": detail_a_pre_checks})

    # --- Variant A, due, birthday ---
    kb_detail_a_bday = build_detail_keyboard(
        bday, from_notification=True, kind="due",
        occurrence_time=occ, original_time=orig,
    )
    callbacks_a_bday = _kb_callbacks(kb_detail_a_bday)
    detail_a_bday_checks = {
        "bnote_prefix": callbacks_a_bday[0].startswith(C.CB_BDAY_NOTED) if callbacks_a_bday else False,
    }
    dbg.section("detail_kb_variant_a_bday", {"checks": detail_a_bday_checks})
    if not all(detail_a_bday_checks.values()):
        dbg.problem("detail_kb_variant_a_bday_failed", {"checks": detail_a_bday_checks})

    # --- Variant B (from list) ---
    kb_detail_b = build_detail_keyboard(regular, from_notification=False, tag_filter="ALL")
    labels_b = _kb_labels(kb_detail_b)
    callbacks_b = _kb_callbacks(kb_detail_b)
    detail_b_checks = {
        "no_noted_button": NEW_ACTION_LABEL_NOTED not in labels_b,
        "no_postpone_button": POSTPONE_LABEL not in labels_b,
        "snooze_present": SNOOZE_LABEL in labels_b,
        "delete_uses_manage_del": any(cb.startswith("manage_del_") for cb in callbacks_b),
        "snooze_uses_manage_toggle": any(cb.startswith("manage_toggle_") for cb in callbacks_b),
        "edit_present": "✏️ Edit fields" in labels_b,
        "back_uses_manage_backtolist": "manage_backtolist" in callbacks_b,
        "back_label_all": "⬅️ Back" in labels_b,
        "four_rows": len(_kb_rows(kb_detail_b)) == 4,
    }
    dbg.section("detail_kb_variant_b", {"labels": labels_b, "checks": detail_b_checks})
    if not all(detail_b_checks.values()):
        dbg.problem("detail_kb_variant_b_failed", {"checks": detail_b_checks, "labels": labels_b})

    # Variant B with tag filter — back label includes tag name
    kb_detail_b_tag = build_detail_keyboard(
        regular, from_notification=False, tag_filter="💰 Finance"
    )
    labels_b_tag = _kb_labels(kb_detail_b_tag)
    detail_b_tag_checks = {
        "back_label_has_tag": any("Finance" in l for l in labels_b_tag),
    }
    dbg.section("detail_kb_variant_b_tag", {"labels": labels_b_tag, "checks": detail_b_tag_checks})
    if not all(detail_b_tag_checks.values()):
        dbg.problem("detail_kb_variant_b_tag_failed", {"checks": detail_b_tag_checks})

    # Type 5: no SNOOZE in both variants
    kb_detail_once_a = build_detail_keyboard(
        onetime, from_notification=True, kind="due", occurrence_time=occ, original_time=orig
    )
    kb_detail_once_b = build_detail_keyboard(onetime, from_notification=False)
    type5_checks = {
        "variant_a_no_snooze": SNOOZE_LABEL not in _kb_labels(kb_detail_once_a),
        "variant_b_no_snooze": SNOOZE_LABEL not in _kb_labels(kb_detail_once_b),
    }
    dbg.section("detail_kb_type5_no_snooze", {"checks": type5_checks})
    if not all(type5_checks.values()):
        dbg.problem("detail_kb_type5_no_snooze_failed", {"checks": type5_checks})

    # --- Toggle keyboard context rebuild ---
    rebuilt_detail_notif = _build_toggle_keyboard_for_message(
        regular,
        SimpleNamespace(reply_markup=kb_detail_a_pre),
        alert_id,
    )
    rebuilt_detail_list = _build_toggle_keyboard_for_message(
        regular,
        SimpleNamespace(reply_markup=kb_detail_b_tag),
        alert_id,
    )
    rebuilt_raw_notif = _build_toggle_keyboard_for_message(
        regular,
        SimpleNamespace(reply_markup=kb_pa),
        alert_id,
    )
    legacy_numeric_id = "legacy_123"
    regular_legacy = {"id": legacy_numeric_id, "type": 3, "title": "Legacy", "active": True}
    kb_detail_a_pre_legacy = build_detail_keyboard(
        regular_legacy,
        from_notification=True,
        kind="pre",
        occurrence_time=occ,
        original_time=orig,
        postpone_count=0,
    )
    rebuilt_detail_notif_legacy = _build_toggle_keyboard_for_message(
        regular_legacy,
        SimpleNamespace(reply_markup=kb_detail_a_pre_legacy),
        legacy_numeric_id,
    )

    cb_detail_notif = _kb_callbacks(rebuilt_detail_notif)
    cb_detail_list = _kb_callbacks(rebuilt_detail_list)
    cb_raw_notif = _kb_callbacks(rebuilt_raw_notif)
    cb_detail_notif_legacy = _kb_callbacks(rebuilt_detail_notif_legacy)
    toggle_rebuild_checks = {
        "detail_notif_keeps_nback": any(cb.startswith(C.CB_NOTIF_BACK) for cb in cb_detail_notif),
        "detail_notif_uses_alerttoggle": any(cb.startswith(C.CB_ALERT_TOGGLE) for cb in cb_detail_notif),
        "detail_notif_no_manage_toggle": not any(cb.startswith("manage_toggle_") for cb in cb_detail_notif),
        "detail_list_uses_manage_toggle": any(cb.startswith("manage_toggle_") for cb in cb_detail_list),
        "detail_list_no_nback": not any(cb.startswith(C.CB_NOTIF_BACK) for cb in cb_detail_list),
        "detail_list_keeps_backtolist": "manage_backtolist" in cb_detail_list,
        "raw_notif_keeps_preinfo": any(cb.startswith(C.CB_PREALERT_INFO) for cb in cb_raw_notif),
        "raw_notif_no_nback": not any(cb.startswith(C.CB_NOTIF_BACK) for cb in cb_raw_notif),
        "legacy_numeric_detail_keeps_nback": any(cb.startswith(C.CB_NOTIF_BACK) for cb in cb_detail_notif_legacy),
        "legacy_numeric_detail_keeps_pnote": any(cb.startswith(C.CB_PLACEBO_NOTED) for cb in cb_detail_notif_legacy),
    }
    dbg.section(
        "toggle_keyboard_context_rebuild",
        {
            "checks": toggle_rebuild_checks,
            "detail_notif_callbacks": cb_detail_notif,
            "detail_list_callbacks": cb_detail_list,
            "raw_notif_callbacks": cb_raw_notif,
            "legacy_numeric_detail_notif_callbacks": cb_detail_notif_legacy,
        },
    )
    if not all(toggle_rebuild_checks.values()):
        dbg.problem("toggle_keyboard_context_rebuild_failed", {"checks": toggle_rebuild_checks})


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

        _run_checks(dbg)
        _run_checks_new_keyboards(dbg)
        _check_placebo_done_handler(dbg)
        _check_placebo_noted_handler(dbg)
        _check_placebo_feedback_failure_telemetry(dbg)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    check_ok = not dbg.has_problem(
        "regular_alert_keyboard_failed",
        "onetime_alert_keyboard_failed",
        "birthday_alert_keyboard_failed",
        "pre_alert_keyboard_weekly_failed",
        "pre_alert_keyboard_onetime_failed",
        "pre_alert_keyboard_birthday_failed",
        "missed_alert_keyboard_failed",
        "detail_pre_alert_keyboard_failed",
        "detail_due_alert_keyboard_failed",
        "detail_due_onetime_alert_keyboard_failed",
        "detail_bday_alert_keyboard_failed",
        "callback_64byte_limit_failed",
        "new_aa_keyboard_failed",
        "new_aa_keyboard_type5_failed",
        "new_bb_keyboard_failed",
        "new_pa_keyboard_failed",
        "new_missed_keyboard_failed",
        "detail_kb_variant_a_pre_failed",
        "detail_kb_variant_a_bday_failed",
        "detail_kb_variant_b_failed",
        "detail_kb_variant_b_tag_failed",
        "detail_kb_type5_no_snooze_failed",
        "toggle_keyboard_context_rebuild_failed",
        "placebo_done_recurring_handler_failed",
        "placebo_done_onetime_handler_failed",
        "placebo_done_missing_handler_failed",
        "placebo_noted_with_occurrence_handler_failed",
        "placebo_noted_without_occurrence_handler_failed",
        "placebo_noted_malformed_timestamp_handler_failed",
        "placebo_done_feedback_failure_handler_failed",
        "placebo_noted_feedback_failure_handler_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"keyboards: {'OK' if check_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
