#!/usr/bin/env python3
import importlib.util
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
SCRIPT_TITLE = "master_debugger_network_policy_debug"
FEATURE_TITLE = "Master Debugger Network Policy"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _load_master_debugger_module():
    tests_root = os.path.join(ROOT_DIR, "tests")
    path = os.path.join(tests_root, "master_debugger.py")
    spec = importlib.util.spec_from_file_location("master_debugger_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load tests/master_debugger.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify_network_policy(dbg, module):
    """Verify master-debugger network bootstrap classification across offline/strict warning modes."""
    classify = module._classify_network_bootstrap_outcome

    cases = [
        (
            "offline_network_noise",
            dict(
                has_crash_output=True,
                has_network_markers=True,
                startup_log_ok=True,
                offline_mode=True,
                strict_warnings=True,
            ),
            {"action": "note_network", "summary_status": "OK"},
        ),
        (
            "allow_warn_network_noise",
            dict(
                has_crash_output=True,
                has_network_markers=True,
                startup_log_ok=True,
                offline_mode=False,
                strict_warnings=False,
            ),
            {"action": "warn_network", "summary_status": "WARN"},
        ),
        (
            "strict_network_noise",
            dict(
                has_crash_output=True,
                has_network_markers=True,
                startup_log_ok=True,
                offline_mode=False,
                strict_warnings=True,
            ),
            {"action": "fail_network", "summary_status": "FAIL"},
        ),
        (
            "non_network_crash",
            dict(
                has_crash_output=True,
                has_network_markers=False,
                startup_log_ok=True,
                offline_mode=True,
                strict_warnings=True,
            ),
            {"action": "fail_output_issue", "summary_status": "FAIL"},
        ),
        (
            "clean_output",
            dict(
                has_crash_output=False,
                has_network_markers=False,
                startup_log_ok=False,
                offline_mode=False,
                strict_warnings=True,
            ),
            {"action": "ok", "summary_status": "OK"},
        ),
    ]

    rows = []
    all_ok = True
    for name, kwargs, expected in cases:
        got = classify(**kwargs)
        ok = got.get("action") == expected["action"] and got.get("summary_status") == expected["summary_status"]
        rows.append({"case": name, "ok": ok, "expected": expected, "got": got})
        if not ok:
            all_ok = False

    dbg.section("network_policy_cases", {"rows": rows})
    if not all_ok:
        dbg.problem("network_policy_cases_failed", {"rows": rows})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})
        dbg.run_meta({"project_root": ROOT_DIR})

        module = _load_master_debugger_module()
        _verify_network_policy(dbg, module)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    policy_ok = not dbg.has_problem("network_policy_cases_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"network_policy: {'OK' if policy_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
