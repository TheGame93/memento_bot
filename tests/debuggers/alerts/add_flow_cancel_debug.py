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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "add_flow_cancel_debug"
FEATURE_TITLE = "Add Alert Cancel Command"

IMPORT_ERROR = None


class _DummyEntity:
    def __init__(self, ent_type, offset, length):
        self.type = ent_type
        self.offset = offset
        self.length = length


class _DummyMessage:
    def __init__(self, text):
        self.text = text
        self.entities = []
        if text and text.startswith("/"):
            cmd = text.split()[0]
            self.entities = [_DummyEntity("bot_command", 0, len(cmd))]


class _DummyUpdate:
    def __init__(self, text):
        message = _DummyMessage(text)
        self.message = message
        self.edited_message = None
        self.effective_message = message
        self.channel_post = None
        self.edited_channel_post = None


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _handler_accepts(handler, update):
    try:
        return bool(handler.check_update(update)), None
    except Exception as exc:
        return None, str(exc)


def _check_state_filters(dbg, MessageHandler, C, add_alert_handler):
    targets = {
        C.TYPE_1_DAYS: "TYPE_1_DAYS",
        C.TYPE_4_DATES: "TYPE_4_DATES",
        C.TYPE_5_DATE: "TYPE_5_DATE",
        C.TYPE_6_DATE: "TYPE_6_DATE",
        C.GET_TIME: "GET_TIME",
    }
    cancel_update = _DummyUpdate("/cancel")
    checks = {}
    errors = []

    for state, label in targets.items():
        handlers = add_alert_handler.states.get(state, [])
        msg_handlers = [h for h in handlers if isinstance(h, MessageHandler)]
        state_checks = {
            "message_handler_count": len(msg_handlers),
            "cancel_matches": [],
            "errors": [],
        }
        if not msg_handlers:
            state_checks["errors"].append("missing_message_handler")
        for handler in msg_handlers:
            cancel_match, cancel_err = _handler_accepts(handler, cancel_update)
            state_checks["cancel_matches"].append(cancel_match)
            if cancel_err:
                state_checks["errors"].append(f"cancel_error:{cancel_err}")
        checks[label] = state_checks

        if state_checks["errors"]:
            errors.append({"state": label, "errors": state_checks["errors"]})
            continue
        if any(state_checks["cancel_matches"]):
            errors.append({"state": label, "errors": ["cancel_should_not_match"]})

    dbg.section("cancel_filter_checks", {"checks": checks, "errors": errors})
    if errors:
        dbg.problem("cancel_filters_failed", {"errors": errors})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from telegram.ext import MessageHandler
            from modules import constants as C
            from modules.handlers.add_alert import add_alert_handler
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _check_state_filters(dbg, MessageHandler, C, add_alert_handler)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    check_ok = not dbg.has_problem("cancel_filters_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"filters: {'OK' if check_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
