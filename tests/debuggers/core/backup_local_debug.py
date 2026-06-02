#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import zipfile
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
SCRIPT_TITLE = "backup_local_debug"
FEATURE_TITLE = "Local Backups"

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


def _read_manifest_from_zip(zip_path):
    with zipfile.ZipFile(zip_path, "r") as handle:
        with handle.open("manifest.json") as mf:
            return json.loads(mf.read().decode("utf-8"))


def _seed_alerts(storage, user_id, titles):
    payload = storage._default_user_payload()  # noqa: SLF001
    alerts = []
    for idx, title in enumerate(titles, start=1):
        alerts.append({
            "id": f"dbg{idx}",
            "title": title,
            "type": 5,
            "type_name": "One Time",
            "schedule": {"date": "10/10/2030", "time": "10:00"},
            "active": True,
        })
    payload["alerts"] = alerts
    ok = storage._write_user_data(user_id, payload)  # noqa: SLF001
    if not ok:
        raise RuntimeError("failed_to_seed_alerts")


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.storage import StorageManager
            from modules.backup_core.local_backup import backup_user_local, list_local_backups
            from modules.backup_core.manifest import validate_manifest
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            previous_backup_dir = os.environ.get("BOT_BACKUP_DIR")
            os.environ["BOT_BACKUP_DIR"] = os.path.join(tmpdir, "backups")
            try:
                data_dir = os.path.join(tmpdir, "data")

                storage = StorageManager(base_data_dir=data_dir)
                user_id = "1001"
                storage.setup_user_space(user_id)
                legacy_log_dir = os.path.join(data_dir, user_id, "logs")

                _seed_alerts(storage, user_id, ["Backup Test"])

                img_path = os.path.join(data_dir, user_id, "images", "photo.jpg")
                with open(img_path, "wb") as handle:
                    handle.write(b"fakeimage")

                user_log_path = storage.get_user_event_log_path(user_id)
                os.makedirs(os.path.dirname(user_log_path), exist_ok=True)
                with open(user_log_path, "w", encoding="utf-8") as handle:
                    handle.write('{"event": "test"}\n')

                now = datetime.now().replace(microsecond=0)
                result = backup_user_local(storage, user_id, now=now)
                created = result.get("created", {})
                zip_path = created.get("path")

                backups = list_local_backups(user_id)

                checks = {
                    "zip_created": bool(zip_path and os.path.isfile(zip_path)),
                    "backup_listed": len(backups) >= 1,
                    "legacy_log_dir_absent": not os.path.isdir(legacy_log_dir),
                }

                if checks["zip_created"]:
                    with zipfile.ZipFile(zip_path, "r") as handle:
                        names = set(handle.namelist())
                    checks["has_alerts_json"] = "alerts.json" in names
                    checks["has_manifest"] = "manifest.json" in names
                    checks["has_image"] = "images/photo.jpg" in names
                    checks["logs_excluded"] = "logs/events.log" not in names

                    manifest_data = _read_manifest_from_zip(zip_path)
                    valid, errors = validate_manifest(manifest_data)
                    print_section("manifest_validation", {"valid": valid, "errors": errors})
                    if not valid:
                        _log_problem("manifest_invalid", {"errors": errors})
                else:
                    checks.update({
                        "has_alerts_json": False,
                        "has_manifest": False,
                        "has_image": False,
                        "logs_excluded": False,
                    })

                print_section("backup_checks", {"checks": checks})

                if not all(checks.values()):
                    _log_problem("backup_missing_files", {"checks": checks})
            finally:
                if previous_backup_dir is None:
                    os.environ.pop("BOT_BACKUP_DIR", None)
                else:
                    os.environ["BOT_BACKUP_DIR"] = previous_backup_dir
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    backup_ok = not dbg.has_problem("backup_missing_files", "manifest_invalid")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"backup: {'OK' if backup_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
