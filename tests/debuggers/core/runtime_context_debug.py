#!/usr/bin/env python3
import os
import sys
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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "runtime_context_debug"
FEATURE_TITLE = "Runtime Context Wiring"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _DummyStorage:
    pass


class _DummyTracker:
    pass


_FORBIDDEN_MAINBOT_IMPORTS = {"storage", "API_FAILURE_TRACKER"}


def _test_runtime_roundtrip(dbg, runtime_context):
    storage = _DummyStorage()
    tracker = _DummyTracker()
    bot_data = {}
    runtime = runtime_context.BotRuntime(
        storage=storage,
        api_failure_tracker=tracker,
    )
    returned = runtime_context.set_bot_runtime(bot_data, runtime)
    context = SimpleNamespace(bot_data=bot_data)

    checks = {
        "set_returns_runtime": returned is runtime,
        "get_roundtrip_context": runtime_context.get_bot_runtime(context) is runtime,
        "get_roundtrip_mapping": runtime_context.get_bot_runtime(bot_data) is runtime,
        "storage_accessor": runtime_context.get_runtime_storage(context) is storage,
        "tracker_accessor": runtime_context.get_runtime_api_failure_tracker(context) is tracker,
    }
    dbg.section("runtime_roundtrip", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("runtime_context_roundtrip_failed", {"checks": checks})


def _test_missing_runtime_failure(dbg, runtime_context):
    missing_context_error = None
    missing_bot_data_error = None

    try:
        runtime_context.get_bot_runtime(SimpleNamespace(bot_data={}))
    except Exception as exc:
        missing_context_error = exc

    try:
        runtime_context.get_bot_runtime(object())
    except Exception as exc:
        missing_bot_data_error = exc

    checks = {
        "missing_runtime_raises": isinstance(missing_context_error, RuntimeError),
        "missing_bot_data_raises": isinstance(missing_bot_data_error, RuntimeError),
    }
    dbg.section("missing_runtime_failure", {
        "checks": checks,
        "missing_runtime_error": str(missing_context_error) if missing_context_error else None,
        "missing_bot_data_error": str(missing_bot_data_error) if missing_bot_data_error else None,
    })
    if not all(checks.values()):
        dbg.problem("runtime_context_missing_failure_failed", {
            "checks": checks,
            "missing_runtime_error": str(missing_context_error) if missing_context_error else None,
            "missing_bot_data_error": str(missing_bot_data_error) if missing_bot_data_error else None,
        })


def _test_invalid_runtime_rejected(dbg, runtime_context):
    invalid_error = None
    try:
        runtime_context.set_bot_runtime({}, object())
    except Exception as exc:
        invalid_error = exc

    checks = {
        "invalid_runtime_raises": isinstance(invalid_error, TypeError),
    }
    dbg.section("invalid_runtime_rejected", {
        "checks": checks,
        "invalid_error": str(invalid_error) if invalid_error else None,
    })
    if not all(checks.values()):
        dbg.problem("runtime_context_invalid_runtime_failed", {
            "checks": checks,
            "invalid_error": str(invalid_error) if invalid_error else None,
        })


def _test_feature_module_bootstrap_import_scan(dbg):
    """Fail when feature modules still import bootstrap runtime globals from mainbot."""

    modules_root = os.path.join(ROOT_DIR, "modules")
    scanned_files = 0
    violations = []

    for root, _dirs, files in os.walk(modules_root):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(root, filename)
            rel_path = os.path.relpath(path, ROOT_DIR)
            scanned_files += 1
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    for lineno, line in enumerate(handle, start=1):
                        stripped = line.strip()
                        if not stripped.startswith("from mainbot import "):
                            continue
                        imported = stripped.replace("from mainbot import ", "", 1)
                        names = [name.strip() for name in imported.split(",")]
                        forbidden = sorted(_FORBIDDEN_MAINBOT_IMPORTS.intersection(names))
                        if forbidden:
                            violations.append({
                                "path": rel_path,
                                "line": lineno,
                                "forbidden": forbidden,
                                "source": stripped,
                            })
            except Exception as exc:
                violations.append({
                    "path": rel_path,
                    "line": 0,
                    "forbidden": ["scan_error"],
                    "source": str(exc),
                })

    checks = {
        "modules_scanned": scanned_files > 0,
        "forbidden_imports_absent": len(violations) == 0,
    }
    dbg.section("feature_modules_bootstrap_import_scan", {
        "checks": checks,
        "scanned_files": scanned_files,
        "violations": violations,
    })
    if not all(checks.values()):
        dbg.problem("feature_modules_bootstrap_import_scan_failed", {
            "checks": checks,
            "scanned_files": scanned_files,
            "violations": violations,
        })


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.shared import runtime_context
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_runtime_roundtrip(dbg, runtime_context)
        _test_missing_runtime_failure(dbg, runtime_context)
        _test_invalid_runtime_rejected(dbg, runtime_context)
        _test_feature_module_bootstrap_import_scan(dbg)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    roundtrip_ok = not dbg.has_problem("runtime_context_roundtrip_failed")
    missing_ok = not dbg.has_problem("runtime_context_missing_failure_failed")
    invalid_ok = not dbg.has_problem("runtime_context_invalid_runtime_failed")
    imports_ok = not dbg.has_problem("feature_modules_bootstrap_import_scan_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"roundtrip: {'OK' if roundtrip_ok else 'FAIL'}",
        f"missing_runtime_failure: {'OK' if missing_ok else 'FAIL'}",
        f"invalid_runtime_rejected: {'OK' if invalid_ok else 'FAIL'}",
        f"feature_import_scan: {'OK' if imports_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
