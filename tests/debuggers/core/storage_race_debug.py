#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "storage_race_debug"
FEATURE_TITLE = "Storage Concurrency"

IMPORT_ERROR = None
try:
    from modules.storage import StorageManager
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc

_DBG = None


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _dbg():
    if _DBG is None:
        raise RuntimeError("debug harness not initialized")
    return _DBG


def print_section(label, payload):
    _dbg().section(label, payload)


def _log_problem(message, payload=None):
    _dbg().problem(message, payload or {})


def _test_concurrent_saves(storage, user_id, threads_count=64):
    def _save_one(index):
        payload = {
            "title": f"stress-{index}",
            "type": None,
            "type_name": "Stress",
            "schedule": {},
            "tags": [],
        }
        return storage.save_alert(user_id, payload)

    ids = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_save_one, i) for i in range(threads_count)]
        for future in as_completed(futures):
            ids.append(future.result())

    data = storage.get_all_alerts(user_id) or {}
    alerts = data.get("alerts", []) or []
    shortcodes = [a.get("shortcode") for a in alerts if isinstance(a.get("shortcode"), str)]

    checks = {
        "all_saves_returned_id": len(ids) == threads_count and all(isinstance(i, str) and i for i in ids),
        "ids_unique": len(set(ids)) == threads_count,
        "alerts_count_matches": len(alerts) == threads_count,
        "shortcodes_unique": len(shortcodes) == threads_count and len({c.lower() for c in shortcodes}) == threads_count,
    }
    print_section("concurrent_saves", {
        "checks": checks,
        "threads_count": threads_count,
        "saved_count": len(alerts),
    })
    if not all(checks.values()):
        _log_problem("concurrent_save_failed", {"checks": checks})

    if alerts:
        return alerts[0].get("id")
    return None


def _test_concurrent_toggle(storage, user_id, alert_id, toggle_count=50):
    if not alert_id:
        _log_problem("concurrent_toggle_failed", {"reason": "missing_alert_id"})
        return

    before = storage.get_alert_by_id(user_id, alert_id) or {}
    initial_status = before.get("active", True)

    statuses = []

    def _toggle_once():
        return storage.toggle_alert(user_id, alert_id)

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(_toggle_once) for _ in range(toggle_count)]
        for future in as_completed(futures):
            statuses.append(future.result())

    after = storage.get_alert_by_id(user_id, alert_id) or {}
    expected = initial_status if toggle_count % 2 == 0 else (not initial_status)
    checks = {
        "all_toggles_return_status": len(statuses) == toggle_count and all(s in {True, False} for s in statuses),
        "final_status_parity": after.get("active", initial_status) == expected,
    }
    print_section("concurrent_toggle", {
        "checks": checks,
        "toggle_count": toggle_count,
        "initial_status": initial_status,
        "final_status": after.get("active"),
    })
    if not all(checks.values()):
        _log_problem("concurrent_toggle_failed", {"checks": checks})


def _test_postpone_mutations(storage, user_id, remove_count=20):
    def _add_one(index):
        instance = {
            "id": f"pp-{index}",
            "alert_id": f"a-{index}",
            "status": "pending",
            "fire_at": datetime.now().isoformat(),
        }
        storage.add_postpone_instance(user_id, instance)

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(_add_one, i) for i in range(40)]
        for future in as_completed(futures):
            future.result()

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(storage.remove_postpone_instance, user_id, f"pp-{i}") for i in range(remove_count)]
        for future in as_completed(futures):
            future.result()

    queue = storage.get_postpone_queue(user_id)
    ids = [item.get("id") for item in queue if isinstance(item, dict)]
    expected_remaining = 40 - remove_count
    checks = {
        "remaining_count_matches": len(queue) == expected_remaining,
        "remaining_ids_unique": len(ids) == len(set(ids)),
    }
    print_section("postpone_mutations", {
        "checks": checks,
        "remaining": len(queue),
        "expected_remaining": expected_remaining,
    })
    if not all(checks.values()):
        _log_problem("postpone_mutation_failed", {"checks": checks})


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=1)
                user_id = 1
                seed_alert_id = _test_concurrent_saves(storage, user_id)
                _test_concurrent_toggle(storage, user_id, seed_alert_id)
                _test_postpone_mutations(storage, user_id)
            finally:
                os.chdir(cwd)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    saves_ok = not dbg.has_problem("concurrent_save_failed")
    toggles_ok = not dbg.has_problem("concurrent_toggle_failed")
    postpone_ok = not dbg.has_problem("postpone_mutation_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"saves: {'OK' if saves_ok else 'FAIL'}",
        f"toggles: {'OK' if toggles_ok else 'FAIL'}",
        f"postpone: {'OK' if postpone_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
