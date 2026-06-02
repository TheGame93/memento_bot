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
SCRIPT_TITLE = "backup_user_service_debug"
FEATURE_TITLE = "User Backup Service"

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


def _seed_alerts(storage, user_id):
    payload = storage._default_user_payload()  # noqa: SLF001
    payload["alerts"] = [
        {
            "id": "a1",
            "title": "Pay rent",
            "type": 5,
            "type_name": "One Time",
            "schedule": {"date": "10/10/2030", "time": "10:00"},
            "active": True,
            "tags": ["🏠 Home"],
        },
        {
            "id": "b1",
            "title": "Alice",
            "type": 6,
            "type_name": "Birthday",
            "schedule": {"date": "10/10", "time": "10:00"},
            "active": True,
            "tags": ["👨‍👩‍👧 Family"],
        },
    ]
    payload["backup_prefs"] = {
        "email_enabled": True,
        "email_frequency": "monthly",
        "email_address": "debug@example.com",
    }
    payload["user_prefs"] = {"timezone_mode": "server"}
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
            from modules import constants as C
            from modules.backup_core.user_backup import (
                BackupQuotaError,
                build_user_backup,
                list_user_backups,
                enforce_folder_retention,
                check_quota_before_create,
                get_user_quota_usage_bytes,
                inspect_archive,
                diff_archive_vs_current,
            )
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
                _seed_alerts(storage, user_id)

                img_path = os.path.join(data_dir, user_id, "images", "photo.jpg")
                with open(img_path, "wb") as handle:
                    handle.write(b"fakeimage")

                now = datetime(2026, 4, 29, 8, 0, 0)
                built = build_user_backup(storage, user_id, "local", now=now, source="local")
                built_path = built.get("path")

                with zipfile.ZipFile(built_path, "r") as zf:
                    names = set(zf.namelist())
                    manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))

                build_checks = {
                    "zip_created": bool(built_path and os.path.isfile(built_path)),
                    "has_manifest": "manifest.json" in names,
                    "has_alerts": "alerts.json" in names,
                    "has_images": "images/photo.jpg" in names,
                    "no_logs": not any(name.startswith("logs/") for name in names),
                    "counts_ok": built.get("alert_count") == 1 and built.get("birthday_count") == 1,
                    "source_set": manifest_data.get("includes", {}).get("source") == "local",
                }
                print_section("build_checks", {"checks": build_checks})
                if not all(build_checks.values()):
                    _log_problem("build_checks_failed", {"checks": build_checks})

                listed = list_user_backups(user_id, "local")
                list_checks = {
                    "list_non_empty": len(listed) >= 1,
                    "list_has_sizes": all(isinstance(item.get("size_bytes"), int) for item in listed),
                }
                print_section("list_checks", {"checks": list_checks})
                if not all(list_checks.values()):
                    _log_problem("list_checks_failed", {"checks": list_checks})

                old1 = os.path.join(os.path.dirname(built_path), "backup_20260420_010101.zip")
                old2 = os.path.join(os.path.dirname(built_path), "backup_20260421_010101.zip")
                with open(old1, "wb") as h:
                    h.write(b"x")
                with open(old2, "wb") as h:
                    h.write(b"x")
                retention_result = enforce_folder_retention(user_id, "pre_import", now=now)
                retention_checks = {
                    "retention_has_stats": isinstance(retention_result.get("stats"), dict),
                }
                print_section("retention_checks", {"checks": retention_checks})
                if not all(retention_checks.values()):
                    _log_problem("retention_checks_failed", {"checks": retention_checks})

                usage = get_user_quota_usage_bytes(user_id)
                quota_check = check_quota_before_create(user_id, exact_new_bytes=1)
                quota_checks = {
                    "usage_non_negative": usage >= 0,
                    "quota_dict": "fits" in quota_check and "usage_bytes" in quota_check,
                }
                print_section("quota_checks", {"checks": quota_checks})
                if not all(quota_checks.values()):
                    _log_problem("quota_checks_failed", {"checks": quota_checks})

                tmp_upload_dir = os.path.join(data_dir, user_id, ".tmp_uploads")
                os.makedirs(tmp_upload_dir, exist_ok=True)
                temp_before = set(os.listdir(tmp_upload_dir))
                old_quota = C.USER_BACKUP_QUOTA_BYTES
                try:
                    C.USER_BACKUP_QUOTA_BYTES = 1
                    quota_raised = False
                    try:
                        build_user_backup(storage, user_id, "exports", now=now, source="export", enforce_quota=True)
                    except BackupQuotaError:
                        quota_raised = True
                    if not quota_raised:
                        _log_problem("quota_failure_not_raised", {})
                finally:
                    C.USER_BACKUP_QUOTA_BYTES = old_quota
                temp_after = set(os.listdir(tmp_upload_dir))
                if temp_after != temp_before:
                    _log_problem("temp_cleanup_failed_on_quota", {"before": list(temp_before), "after": list(temp_after)})

                inspected = inspect_archive(built_path, user_id)
                inspect_checks = {
                    "inspect_ok": inspected.get("ok") is True,
                    "inspect_counts": inspected.get("alert_count") == 1 and inspected.get("birthday_count") == 1,
                    "inspect_images": inspected.get("image_count") >= 1,
                }
                print_section("inspect_checks", {"checks": inspect_checks})
                if not all(inspect_checks.values()):
                    _log_problem("inspect_checks_failed", {"checks": inspect_checks, "inspected": inspected})

                with tempfile.TemporaryDirectory() as bad_tmp:
                    bad_zip = os.path.join(bad_tmp, "backup_20260429_090000.zip")
                    with zipfile.ZipFile(bad_zip, "w", compression=zipfile.ZIP_DEFLATED) as handle:
                        handle.writestr("manifest.json", "{}")
                    _ = inspect_archive(bad_zip, user_id)
                    bad_tmp_exists_after = os.path.exists(bad_tmp)
                    parse_error_cleanup_checks = {
                        "temp_dir_lifecycle_ok": bad_tmp_exists_after,
                    }
                    print_section("inspect_parse_error_cleanup_checks", {"checks": parse_error_cleanup_checks})

                diffed = diff_archive_vs_current(storage, user_id, built_path)
                diff_checks = {
                    "diff_ok": diffed.get("ok") is True,
                    "diff_has_preview": isinstance(diffed.get("backup_prefs_preview"), dict),
                    "diff_count_fields": "archive_alert_count" in diffed and "current_alert_count" in diffed,
                }
                print_section("diff_checks", {"checks": diff_checks})
                if not all(diff_checks.values()):
                    _log_problem("diff_checks_failed", {"checks": diff_checks, "diff": diffed})
            finally:
                if previous_backup_dir is None:
                    os.environ.pop("BOT_BACKUP_DIR", None)
                else:
                    os.environ["BOT_BACKUP_DIR"] = previous_backup_dir
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    checks_ok = not dbg.has_problem(
        "build_checks_failed",
        "list_checks_failed",
        "retention_checks_failed",
        "quota_checks_failed",
        "quota_failure_not_raised",
        "temp_cleanup_failed_on_quota",
        "inspect_checks_failed",
        "diff_checks_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"checks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
