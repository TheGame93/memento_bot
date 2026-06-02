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
SCRIPT_TITLE = "acting_as_debug"
FEATURE_TITLE = "Developer Act-As"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyUpdate:
    def __init__(self, user_id=None):
        self.effective_user = _DummyUser(user_id) if user_id is not None else None


class _DummyContext:
    def __init__(self):
        self.user_data = {}


def _test_acting_as_payload(dbg, acting_as_api):
    update = _DummyUpdate(user_id=10)
    context = _DummyContext()
    checks = {
        "default_target_is_actor": acting_as_api.get_target_user_id(update, context) == 10,
        "default_payload_empty": acting_as_api.build_acting_as_payload(update, context) == {},
    }

    acting_as_api.set_acting_as(context, 20)
    payload = acting_as_api.build_acting_as_payload(update, context)
    checks.update({
        "target_override": acting_as_api.get_target_user_id(update, context) == 20,
        "payload_has_actor": payload.get("acting_as", {}).get("actor_id") == "10",
        "payload_has_target": payload.get("acting_as", {}).get("target_id") == "20",
    })

    acting_as_api.set_acting_as(context, "10")
    payload_same = acting_as_api.build_acting_as_payload(update, context)
    checks.update({
        "same_target_payload_empty": payload_same == {},
        "same_target_not_acting": not acting_as_api.is_acting_as(update, context),
    })

    acting_as_api.clear_acting_as(context)
    checks.update({"cleared_target_actor": acting_as_api.get_target_user_id(update, context) == 10})

    dbg.section("acting_as_checks", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("acting_as_failed", {"checks": checks})


def _test_payload_for_helper(dbg, acting_as_api):
    payload = acting_as_api.build_acting_as_payload_for(5, 9)
    payload_same = acting_as_api.build_acting_as_payload_for(5, 5)
    banner_md = acting_as_api.build_acting_as_banner_for(5, 9, parse_mode="Markdown")
    banner_html = acting_as_api.build_acting_as_banner_for(5, 9, parse_mode="HTML")
    checks = {
        "payload_for_actor": payload.get("acting_as", {}).get("actor_id") == "5",
        "payload_for_target": payload.get("acting_as", {}).get("target_id") == "9",
        "payload_same_empty": payload_same == {},
        "banner_md": "`9`" in banner_md,
        "banner_html": "<code>9</code>" in banner_html,
    }
    dbg.section("payload_for", {
        "payload": payload,
        "payload_same": payload_same,
        "banner_md": banner_md,
        "banner_html": banner_html,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("acting_as_failed", {"step": "payload_for", "checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.shared import acting_as as acting_as_api
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_acting_as_payload(dbg, acting_as_api)
        _test_payload_for_helper(dbg, acting_as_api)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    core_ok = not dbg.has_problem("acting_as_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"core: {'OK' if core_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
