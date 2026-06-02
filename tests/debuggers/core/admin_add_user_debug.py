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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "admin_add_user_debug"
FEATURE_TITLE = "Admin Add User Forward Parse"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _User:
    def __init__(self, user_id=1, username=None, first_name=None, last_name=None, full_name=None):
        self.id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.full_name = full_name


class _ForwardOrigin:
    def __init__(self, sender_user=None, sender_user_name=None, chat=None):
        self.sender_user = sender_user
        self.sender_user_name = sender_user_name
        self.chat = chat


class _Message:
    def __init__(self, forward_from=None, forward_origin=None, forward_sender_name=None):
        self.forward_from = forward_from
        self.forward_origin = forward_origin
        self.forward_sender_name = forward_sender_name


def _test_forward_from_user(dbg, extract_forward_identity):
    msg = _Message(forward_from=_User(10, username="alpha", first_name="Alpha", last_name="User"))
    result = extract_forward_identity(msg)
    checks = {
        "user_id": result.get("user_id") == 10,
        "username": result.get("username") == "alpha",
        "display_name": result.get("display_name") == "Alpha User",
        "error": result.get("error") is None,
    }
    dbg.section("forward_from", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("forward_parse_failed", {"step": "forward_from", "checks": checks})


def _test_forward_origin_user(dbg, extract_forward_identity):
    origin = _ForwardOrigin(sender_user=_User(20, username="beta", full_name="Beta User"))
    msg = _Message(forward_origin=origin)
    result = extract_forward_identity(msg)
    checks = {
        "user_id": result.get("user_id") == 20,
        "username": result.get("username") == "beta",
        "display_name": result.get("display_name") == "Beta User",
        "error": result.get("error") is None,
    }
    dbg.section("forward_origin_user", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("forward_parse_failed", {"step": "forward_origin_user", "checks": checks})


def _test_forward_hidden_sender(dbg, extract_forward_identity):
    msg = _Message(forward_sender_name="Hidden User")
    result = extract_forward_identity(msg)
    checks = {"hidden_error": result.get("error") == "hidden_sender"}
    dbg.section("forward_hidden", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("forward_parse_failed", {"step": "forward_hidden", "checks": checks})


def _test_forward_origin_chat(dbg, extract_forward_identity):
    origin = _ForwardOrigin(chat=object())
    msg = _Message(forward_origin=origin)
    result = extract_forward_identity(msg)
    checks = {"chat_error": result.get("error") == "forwarded_chat"}
    dbg.section("forward_chat", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("forward_parse_failed", {"step": "forward_chat", "checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.shared.forward_extract import extract_forward_identity
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_forward_from_user(dbg, extract_forward_identity)
        _test_forward_origin_user(dbg, extract_forward_identity)
        _test_forward_hidden_sender(dbg, extract_forward_identity)
        _test_forward_origin_chat(dbg, extract_forward_identity)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    parse_ok = not dbg.has_problem("forward_parse_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"parse: {'OK' if parse_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
