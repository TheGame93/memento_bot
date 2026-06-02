#!/usr/bin/env python3
import json
import os
import sys
import tempfile


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
SCRIPT_TITLE = "user_meta_debug"
FEATURE_TITLE = "User Metadata"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _assert_has_meta_keys(meta):
    expected = {"username", "first_start", "last_seen", "added_at", "added_by", "added_via"}
    return isinstance(meta, dict) and expected.issubset(set(meta.keys()))


def _test_user_meta_flow(dbg, StorageManager):
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=None)
        user_id = 12345
        storage.setup_user_space(user_id)

        alerts_path = os.path.join(tmpdir, "data", str(user_id), "alerts.json")
        with open(alerts_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        meta = data.get("user_meta")
        checks = {"meta_present_on_setup": _assert_has_meta_keys(meta)}
        dbg.section("meta_defaults", {"checks": checks, "meta": meta})
        if not all(checks.values()):
            dbg.problem("user_meta_failed", {"step": "defaults", "checks": checks})
            return

        update_payload = {
            "username": "Alice",
            "first_start": "2026-02-09T12:00:00",
            "last_seen": "2026-02-09T12:05:00",
            "custom_name": "Custom Alice",
            "label_order": ["custom_name", "username", "display_name", "user_id"],
        }
        updated = storage.update_user_meta(user_id, update_payload)
        meta_after = storage.get_user_meta(user_id)
        checks = {
            "update_returns_meta": isinstance(updated, dict),
            "meta_updated": meta_after.get("username") == "Alice" and meta_after.get("first_start") == update_payload["first_start"],
            "custom_name_saved": meta_after.get("custom_name") == "Custom Alice",
            "label_order_saved": meta_after.get("label_order") == ["custom_name", "username", "display_name", "user_id"],
        }
        dbg.section("meta_update", {"checks": checks, "meta": meta_after})
        if not all(checks.values()):
            dbg.problem("user_meta_failed", {"step": "update", "checks": checks, "meta": meta_after})
            return

        legacy_path = os.path.join(tmpdir, "data", "999", "alerts.json")
        os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
        with open(legacy_path, "w", encoding="utf-8") as handle:
            json.dump({"tags": [], "alerts": [], "postpone_queue": []}, handle)

        legacy_data = storage.get_all_alerts(999)
        checks = {"legacy_meta_added": _assert_has_meta_keys(legacy_data.get("user_meta"))}
        dbg.section("meta_migration", {"checks": checks, "meta": legacy_data.get("user_meta")})
        if not all(checks.values()):
            dbg.problem("user_meta_failed", {"step": "migration", "checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.storage import StorageManager
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_user_meta_flow(dbg, StorageManager)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    meta_ok = not dbg.has_problem("user_meta_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"meta: {'OK' if meta_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
