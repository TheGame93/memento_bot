#!/usr/bin/env python3
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
from _lib.runtime import run_async, seed_mainbot_runtime

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "help_navigation_debug"
FEATURE_TITLE = "Help Navigation"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _FakeStorage:
    def __init__(self):
        self.roles = {}
        self.events = []

    def set_role(self, user_id, role):
        self.roles[str(user_id)] = role

    def get_user_role(self, user_id):
        return self.roles.get(str(user_id), "user")

    def log_user_event(self, user_id, event_type, payload):
        self.events.append({
            "user_id": str(user_id),
            "event_type": event_type,
            "payload": dict(payload or {}),
        })


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self):
        self.replies = []
        self.edits = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({
            "text": text,
            "kwargs": kwargs,
        })

    async def edit_text(self, text, **kwargs):
        self.edits.append({
            "text": text,
            "kwargs": kwargs,
        })


class _StrictCallbackQuery:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message
        self.answer_attempts = 0
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answer_attempts += 1
        if self.answer_attempts > 1:
            raise RuntimeError("callback_answer_called_twice")
        self.answers.append({
            "text": text,
            "show_alert": bool(show_alert),
        })


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


def _extract_inline_labels(reply_markup):
    if not reply_markup:
        return []
    labels = []
    for row in getattr(reply_markup, "inline_keyboard", []):
        for button in row:
            labels.append(getattr(button, "text", ""))
    return labels


def _first_callback_data(reply_markup):
    if not reply_markup:
        return None
    rows = getattr(reply_markup, "inline_keyboard", []) or []
    if not rows:
        return None
    first_row = rows[0] or []
    if not first_row:
        return None
    return getattr(first_row[0], "callback_data", None)


async def _run_help_command(base_handlers, storage, *, user_id, role):
    storage.set_role(user_id, role)
    storage.events.clear()
    update = types.SimpleNamespace(
        effective_user=_DummyUser(user_id),
        message=_DummyMessage(),
        effective_message=None,
        callback_query=None,
    )
    update.effective_message = update.message
    context = _DummyContext()
    err = None
    fake_mainbot = types.SimpleNamespace(storage=storage, API_FAILURE_TRACKER=None)
    seed_mainbot_runtime(fake_mainbot, app=context, storage=storage)
    try:
        await base_handlers.help_command(update, context)
    except Exception as exc:
        err = str(exc)
    return {
        "update": update,
        "context": context,
        "error": err,
        "events": list(storage.events),
    }


async def _run_help_callback(
    base_handlers,
    storage,
    *,
    user_id,
    role,
    callback_data,
    with_query_message=True,
    with_effective_message=True,
):
    storage.set_role(user_id, role)
    storage.events.clear()
    query_message = _DummyMessage() if with_query_message else None
    query = _StrictCallbackQuery(callback_data, message=query_message)
    update = types.SimpleNamespace(
        effective_user=_DummyUser(user_id),
        callback_query=query,
        message=None,
        effective_message=query_message if with_effective_message else None,
    )
    context = _DummyContext()
    err = None
    fake_mainbot = types.SimpleNamespace(storage=storage, API_FAILURE_TRACKER=None)
    seed_mainbot_runtime(fake_mainbot, app=context, storage=storage)
    try:
        await base_handlers.handle_help_callback(update, context)
    except Exception as exc:
        err = str(exc)
    return {
        "update": update,
        "context": context,
        "query": query,
        "query_message": query_message,
        "error": err,
        "events": list(storage.events),
    }


def _latest_event(events, event_type):
    for event in reversed(events):
        if event.get("event_type") == event_type:
            return event
    return None


def _record_case(dbg, label, checks, details, problem_code):
    dbg.section(label, {"checks": checks, **details})
    if not all(checks.values()):
        dbg.problem(problem_code, {"checks": checks, **details})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.handlers import base as base_handlers
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        storage = _FakeStorage()
        user_id = 7070

        cmd_user = run_async(_run_help_command(base_handlers, storage, user_id=user_id, role="user"))
        cmd_user_replies = cmd_user["update"].message.replies
        first_reply = cmd_user_replies[0] if cmd_user_replies else {}
        first_markup = first_reply.get("kwargs", {}).get("reply_markup")
        first_labels = _extract_inline_labels(first_markup)
        first_cb = _first_callback_data(first_markup)
        first_step = _latest_event(cmd_user["events"], "help_step_sent")
        checks = {
            "no_exception": cmd_user["error"] is None,
            "single_message": len(cmd_user_replies) == 1,
            "next_button_present": any("Next" in label for label in first_labels),
            "next_button_callback": first_cb == "help_next_2",
            "logs_command_help": _latest_event(cmd_user["events"], "command_help") is not None,
            "logs_help_step_sent": first_step is not None and first_step["payload"].get("step_index") == 1,
        }
        _record_case(
            dbg,
            "help_command_user_entry",
            checks,
            {
                "reply_count": len(cmd_user_replies),
                "first_reply_labels": first_labels,
                "first_callback": first_cb,
                "events": cmd_user["events"],
            },
            "help_command_user_entry_failed",
        )

        cb_next2 = run_async(_run_help_callback(
            base_handlers,
            storage,
            user_id=user_id,
            role="user",
            callback_data="help_next_2",
        ))
        next2_replies = cb_next2["query_message"].replies if cb_next2["query_message"] else []
        next2_first = next2_replies[0] if next2_replies else {}
        next2_markup = next2_first.get("kwargs", {}).get("reply_markup")
        next2_cb = _first_callback_data(next2_markup)
        next2_labels = _extract_inline_labels(next2_markup)
        next_press_event = _latest_event(cb_next2["events"], "help_next_pressed")
        next_step_event = _latest_event(cb_next2["events"], "help_step_sent")
        checks = {
            "no_exception": cb_next2["error"] is None,
            "single_answer": cb_next2["query"].answer_attempts == 1,
            "answer_non_alert": bool(cb_next2["query"].answers and not cb_next2["query"].answers[0]["show_alert"]),
            "new_message_sent": len(next2_replies) == 1,
            "sends_expected_text": next2_first.get("text") == getattr(base_handlers, "HELP_INTRO_USEIT_TEXT", ""),
            "next_callback_progresses": next2_cb == "help_next_3",
            "no_edit_usage": len(cb_next2["query_message"].edits) == 0 if cb_next2["query_message"] else False,
            "logs_next_pressed": bool(next_press_event and next_press_event["payload"].get("next_step_index") == 2),
            "logs_step_sent": bool(next_step_event and next_step_event["payload"].get("step_index") == 2),
        }
        _record_case(
            dbg,
            "help_callback_next2_user",
            checks,
            {
                "answers": cb_next2["query"].answers,
                "reply_labels": next2_labels,
                "reply_callback": next2_cb,
                "events": cb_next2["events"],
            },
            "help_callback_next2_user_failed",
        )

        cb_done = run_async(_run_help_callback(
            base_handlers,
            storage,
            user_id=user_id,
            role="user",
            callback_data="help_done",
        ))
        done_event = _latest_event(cb_done["events"], "help_flow_completed_popup")
        done_replies = cb_done["query_message"].replies if cb_done["query_message"] else []
        checks = {
            "no_exception": cb_done["error"] is None,
            "single_answer": cb_done["query"].answer_attempts == 1,
            "alert_popup": bool(cb_done["query"].answers and cb_done["query"].answers[0]["show_alert"]),
            "popup_text_exact": bool(cb_done["query"].answers and cb_done["query"].answers[0]["text"] == getattr(base_handlers, "HELP_DONE_POPUP_TEXT", "")),
            "no_followup_message": len(done_replies) == 0,
            "logs_completion": done_event is not None,
        }
        _record_case(
            dbg,
            "help_callback_done_popup",
            checks,
            {
                "answers": cb_done["query"].answers,
                "events": cb_done["events"],
            },
            "help_callback_done_popup_failed",
        )

        cb_out_scope = run_async(_run_help_callback(
            base_handlers,
            storage,
            user_id=user_id,
            role="user",
            callback_data="help_next_6",
        ))
        invalid_event = _latest_event(cb_out_scope["events"], "help_callback_invalid")
        out_scope_replies = cb_out_scope["query_message"].replies if cb_out_scope["query_message"] else []
        checks = {
            "no_exception": cb_out_scope["error"] is None,
            "single_answer": cb_out_scope["query"].answer_attempts == 1,
            "alert_popup": bool(cb_out_scope["query"].answers and cb_out_scope["query"].answers[0]["show_alert"]),
            "no_followup_message": len(out_scope_replies) == 0,
            "reason_step_out_of_scope": bool(invalid_event and invalid_event["payload"].get("reason_code") == "step_out_of_scope"),
        }
        _record_case(
            dbg,
            "help_callback_out_of_scope_user",
            checks,
            {
                "answers": cb_out_scope["query"].answers,
                "events": cb_out_scope["events"],
            },
            "help_callback_out_of_scope_user_failed",
        )

        cb_invalid = run_async(_run_help_callback(
            base_handlers,
            storage,
            user_id=user_id,
            role="user",
            callback_data="help_next_X",
        ))
        invalid_event = _latest_event(cb_invalid["events"], "help_callback_invalid")
        checks = {
            "no_exception": cb_invalid["error"] is None,
            "single_answer": cb_invalid["query"].answer_attempts == 1,
            "alert_popup": bool(cb_invalid["query"].answers and cb_invalid["query"].answers[0]["show_alert"]),
            "reason_invalid_payload": bool(invalid_event and invalid_event["payload"].get("reason_code") == "invalid_payload"),
        }
        _record_case(
            dbg,
            "help_callback_invalid_payload",
            checks,
            {
                "answers": cb_invalid["query"].answers,
                "events": cb_invalid["events"],
            },
            "help_callback_invalid_payload_failed",
        )

        cb_stale = run_async(_run_help_callback(
            base_handlers,
            storage,
            user_id=user_id,
            role="user",
            callback_data="help_next_2",
            with_query_message=False,
            with_effective_message=False,
        ))
        stale_event = _latest_event(cb_stale["events"], "help_callback_invalid")
        checks = {
            "no_exception": cb_stale["error"] is None,
            "single_answer": cb_stale["query"].answer_attempts == 1,
            "alert_popup": bool(cb_stale["query"].answers and cb_stale["query"].answers[0]["show_alert"]),
            "reason_stale": bool(stale_event and stale_event["payload"].get("reason_code") == "stale_or_unavailable"),
        }
        _record_case(
            dbg,
            "help_callback_stale_message",
            checks,
            {
                "answers": cb_stale["query"].answers,
                "events": cb_stale["events"],
            },
            "help_callback_stale_message_failed",
        )

        cb_admin_step6 = run_async(_run_help_callback(
            base_handlers,
            storage,
            user_id=user_id,
            role="admin",
            callback_data="help_next_6",
        ))
        admin_replies = cb_admin_step6["query_message"].replies if cb_admin_step6["query_message"] else []
        admin_first = admin_replies[0] if admin_replies else {}
        checks = {
            "no_exception": cb_admin_step6["error"] is None,
            "single_answer": cb_admin_step6["query"].answer_attempts == 1,
            "non_alert_answer": bool(cb_admin_step6["query"].answers and not cb_admin_step6["query"].answers[0]["show_alert"]),
            "admin_message_sent": len(admin_replies) == 1,
            "admin_text_expected": admin_first.get("text") == getattr(base_handlers, "HELP_ADMIN_TEXT", ""),
        }
        _record_case(
            dbg,
            "help_callback_admin_step6",
            checks,
            {
                "answers": cb_admin_step6["query"].answers,
                "events": cb_admin_step6["events"],
            },
            "help_callback_admin_step6_failed",
        )

        cb_role_change = run_async(_run_help_callback(
            base_handlers,
            storage,
            user_id=user_id,
            role="admin",
            callback_data="help_next_7",
        ))
        role_change_invalid = _latest_event(cb_role_change["events"], "help_callback_invalid")
        checks = {
            "no_exception": cb_role_change["error"] is None,
            "single_answer": cb_role_change["query"].answer_attempts == 1,
            "alert_popup": bool(cb_role_change["query"].answers and cb_role_change["query"].answers[0]["show_alert"]),
            "blocked_when_role_downgraded": bool(role_change_invalid and role_change_invalid["payload"].get("reason_code") == "step_out_of_scope"),
        }
        _record_case(
            dbg,
            "help_callback_role_change_guard",
            checks,
            {
                "answers": cb_role_change["query"].answers,
                "events": cb_role_change["events"],
            },
            "help_callback_role_change_guard_failed",
        )

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    navigation_ok = not dbg.has_problem(
        "help_command_user_entry_failed",
        "help_callback_next2_user_failed",
        "help_callback_done_popup_failed",
        "help_callback_out_of_scope_user_failed",
        "help_callback_invalid_payload_failed",
        "help_callback_stale_message_failed",
        "help_callback_admin_step6_failed",
        "help_callback_role_change_guard_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"navigation: {'OK' if navigation_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
