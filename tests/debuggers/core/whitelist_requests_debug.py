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
from core.whitelist_requests_checks import WhitelistRequestsApi, run_checks

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "whitelist_requests_debug"
FEATURE_TITLE = "Whitelist Requests Store"

IMPORT_ERROR = None
try:
    from modules.security.whitelist_store import (
        load_whitelist_requests,
        upsert_whitelist_request,
        remove_whitelist_request,
        update_whitelist_request,
        ensure_whitelist_request,
        update_whitelist_request_message,
        resolve_whitelist_request,
        get_whitelist_request_state,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


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

        api = WhitelistRequestsApi(
            load_whitelist_requests=load_whitelist_requests,
            upsert_whitelist_request=upsert_whitelist_request,
            remove_whitelist_request=remove_whitelist_request,
            update_whitelist_request=update_whitelist_request,
            ensure_whitelist_request=ensure_whitelist_request,
            update_whitelist_request_message=update_whitelist_request_message,
            resolve_whitelist_request=resolve_whitelist_request,
            get_whitelist_request_state=get_whitelist_request_state,
        )
        run_checks(dbg, api)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    request_ok = not dbg.has_problem("request_flow_failed")
    message_update_ok = not dbg.has_problem("message_update_edge_cases_failed")
    history_ok = not dbg.has_problem("reject_rerequest_history_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"request-flow: {'OK' if request_ok else 'FAIL'}",
        f"message-update-edge-cases: {'OK' if message_update_ok else 'FAIL'}",
        f"reject-rerequest-history: {'OK' if history_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
