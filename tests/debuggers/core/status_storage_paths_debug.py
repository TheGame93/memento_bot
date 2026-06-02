#!/usr/bin/env python3
import asyncio
import os
import sys
import tempfile
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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "status_storage_paths_debug"
FEATURE_TITLE = "Status Storage Paths Aggregation"

IMPORT_ERROR = None
try:
    from modules.handlers import base as base_mod
    from modules.shared import user_status as user_status_mod
    from modules.shared import storage_metrics as sm
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


def _write_bytes(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * int(size))


class _DummyTracker:
    def snapshot(self, _user_id):
        return {}


class _DummyMessage:
    def __init__(self):
        self.calls = []

    async def reply_text(self, text, **kwargs):
        self.calls.append({"text": text, "kwargs": kwargs})
        return True


class _DummyUpdate:
    def __init__(self, message):
        self.effective_message = message
        self.message = message
        self.effective_user = SimpleNamespace(id=42)


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.bot = SimpleNamespace(send_message=self._send_message)
        self.bot_calls = []

    async def _send_message(self, **kwargs):
        self.bot_calls.append(kwargs)
        return True


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=_DummyTracker()),
    )


class _DummyStorage:
    def __init__(self, base_data):
        self.base_data = base_data
        self.events = []
        self.get_all_alerts_calls = 0
        self._alerts = {
            "alerts": [
                {"id": "a1", "type": 1, "active": True},
                {"id": "b1", "type": 6, "active": True},
            ],
            "tags": ["x", "y"],
        }

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": str(user_id),
            "event": event_type,
            "payload": payload or {},
        })
        return True

    def get_user_prefs(self, _user_id):
        return {}

    def get_user_role(self, _user_id):
        return "user"

    def get_backup_prefs(self, _user_id):
        return {"email_enabled": False, "email_address": None, "last_email_sent": None}

    def get_user_meta(self, _user_id):
        return {}

    def get_all_alerts(self, _user_id):
        self.get_all_alerts_calls += 1
        return dict(self._alerts)

    def get_all_users(self):
        return ["42"]

    def get_user_event_log_path(self, user_id):
        return os.path.join(self.base_data, "userlog.d", f"{user_id}_events.log")


def _run_checks():
    with tempfile.TemporaryDirectory(prefix="status_storage_paths_debug_") as tmp:
        data_dir = os.path.join(tmp, "data")
        backup_dir = os.path.join(tmp, "backups")
        user_backup_dir = os.path.join(backup_dir, "users")
        uid = "42"

        # User data root (must count for total space)
        _write_bytes(os.path.join(data_dir, uid, "alerts.json"), 10)
        _write_bytes(os.path.join(data_dir, uid, "prefs.json"), 6)
        _write_bytes(os.path.join(data_dir, uid, "alerts.json.bak"), 9)
        _write_bytes(os.path.join(data_dir, uid, "images", "img1.jpg"), 13)

        # Legacy user-local logs/backups (must NOT count for dedicated logs/backups fields)
        _write_bytes(os.path.join(data_dir, uid, "logs", "events.log"), 101)
        _write_bytes(os.path.join(data_dir, uid, "backups", "legacy.zip"), 103)

        # Canonical user logs (must count)
        _write_bytes(os.path.join(data_dir, "userlog.d", f"{uid}_events.log"), 29)
        _write_bytes(os.path.join(data_dir, "userlog.d", f"{uid}_events.log.1"), 31)
        _write_bytes(os.path.join(data_dir, "userlog.d", "420_events.log"), 37)  # collision guard

        # Canonical backups root (must count)
        _write_bytes(os.path.join(user_backup_dir, uid, "local", "backup_1.zip"), 41)

        storage = _DummyStorage(data_dir)
        message = _DummyMessage()
        update = _DummyUpdate(message)
        context = _DummyContext()
        _seed_runtime(context, storage)

        expected = {
            "total_space": base_mod.get_size_format(242),
            "data_json": base_mod.get_size_format(16),
            "data_json_bak": base_mod.get_size_format(9),
            "images": base_mod.get_size_format(13),
            "logs": base_mod.get_size_format(60),
            "backups": base_mod.get_size_format(41),
        }

        originals = {
            "base_DATA_DIR": base_mod.DATA_DIR,
            "base_build_status_message": base_mod.build_status_message,
            "base_get_actor_user_id": base_mod.get_actor_user_id,
            "base_get_target_user_id": base_mod.get_target_user_id,
            "base_build_acting_as_payload": base_mod.build_acting_as_payload,
            "base_build_acting_as_banner": base_mod.build_acting_as_banner,
            "us_DATA_DIR": user_status_mod.DATA_DIR,
            "us_build_status_message": user_status_mod.build_status_message,
            "sm_DATA_DIR": sm.DATA_DIR,
            "sm_BACKUP_DIR": sm.BACKUP_DIR,
            "sm_USER_BACKUP_DIR": sm.USER_BACKUP_DIR,
            "sm_USER_LOG_DIR": sm.USER_LOG_DIR,
            "mainbot": sys.modules.get("mainbot"),
        }

        base_capture = {}
        user_status_capture = {}

        def _capture_base_status(**kwargs):
            base_capture.clear()
            base_capture.update(kwargs)
            return "STATUS_OK"

        def _capture_user_status(**kwargs):
            user_status_capture.clear()
            user_status_capture.update(kwargs)
            return "USER_STATUS_OK"

        base_mod.DATA_DIR = data_dir
        user_status_mod.DATA_DIR = data_dir
        sm.DATA_DIR = data_dir
        sm.BACKUP_DIR = backup_dir
        sm.USER_BACKUP_DIR = user_backup_dir
        sm.USER_LOG_DIR = os.path.join(data_dir, "userlog.d")
        base_mod.build_status_message = _capture_base_status
        user_status_mod.build_status_message = _capture_user_status
        base_mod.get_actor_user_id = lambda _update: 42
        base_mod.get_target_user_id = lambda _update, _context: 42
        base_mod.build_acting_as_payload = lambda _update, _context: {}
        base_mod.build_acting_as_banner = lambda _update, _context, parse_mode=None: ""
        sys.modules["mainbot"] = SimpleNamespace(storage=storage, API_FAILURE_TRACKER=_DummyTracker())

        try:
            asyncio.run(base_mod.status(update, context))
            user_status_mod.build_user_status_message(storage, uid, viewer_role="user")

            rendered_events = [e for e in storage.events if e.get("event") == "status_rendered"]
            failed_events = [e for e in storage.events if e.get("event") == "status_render_failed"]
            command_events = [e for e in storage.events if e.get("event") == "command_status"]

            base_stats = base_capture.get("user_stats") or {}
            shared_stats = user_status_capture.get("user_stats") or {}
            checks = {
                "base_total_space_canonical_data_dir": base_stats.get("total_space") == expected["total_space"],
                "base_data_json_uses_all_top_level_json": base_stats.get("data_json") == expected["data_json"],
                "base_data_json_bak_uses_top_level_backups": base_stats.get("data_json_bak") == expected["data_json_bak"],
                "base_images_unchanged": base_stats.get("images") == expected["images"],
                "base_logs_use_userlog_root": base_stats.get("logs") == expected["logs"],
                "base_backups_use_backup_users_root": base_stats.get("backups") == expected["backups"],
                "base_counts_from_storage_payload": base_stats.get("alerts_count") == 1
                and base_stats.get("alerts_active") == 1
                and base_stats.get("birthdays_count") == 1
                and base_stats.get("tags_count") == 2,
                "shared_total_space_canonical_data_dir": shared_stats.get("total_space") == expected["total_space"],
                "shared_data_json_uses_all_top_level_json": shared_stats.get("data_json") == expected["data_json"],
                "shared_data_json_bak_uses_top_level_backups": shared_stats.get("data_json_bak") == expected["data_json_bak"],
                "shared_logs_use_userlog_root": shared_stats.get("logs") == expected["logs"],
                "shared_backups_use_backup_users_root": shared_stats.get("backups") == expected["backups"],
                "shared_counts_from_storage_payload": shared_stats.get("alerts_count") == 1
                and shared_stats.get("alerts_active") == 1
                and shared_stats.get("birthdays_count") == 1
                and shared_stats.get("tags_count") == 2,
                "storage_get_all_alerts_used_by_both_paths": storage.get_all_alerts_calls >= 2,
                "collision_userlog_file_not_counted": base_stats.get("logs") != base_mod.get_size_format(97),
                "status_sent_once": len(message.calls) == 1,
                "command_status_logged": len(command_events) == 1,
                "status_rendered_logged": len(rendered_events) == 1,
                "status_render_failed_not_logged": len(failed_events) == 0,
                "status_rendered_payload_sizes": rendered_events
                and rendered_events[0].get("payload", {}).get("size_data_bytes") == 16
                and rendered_events[0].get("payload", {}).get("size_logs_bytes") == 60
                and rendered_events[0].get("payload", {}).get("size_backups_bytes") == 41,
            }

            print_section("status_storage_paths", {
                "checks": checks,
                "expected": expected,
                "base_stats": base_stats,
                "shared_stats": shared_stats,
                "events": [e.get("event") for e in storage.events],
            })
            if not all(checks.values()):
                _log_problem("status_storage_paths_failed", {"checks": checks})
        finally:
            base_mod.DATA_DIR = originals["base_DATA_DIR"]
            base_mod.build_status_message = originals["base_build_status_message"]
            base_mod.get_actor_user_id = originals["base_get_actor_user_id"]
            base_mod.get_target_user_id = originals["base_get_target_user_id"]
            base_mod.build_acting_as_payload = originals["base_build_acting_as_payload"]
            base_mod.build_acting_as_banner = originals["base_build_acting_as_banner"]
            user_status_mod.DATA_DIR = originals["us_DATA_DIR"]
            user_status_mod.build_status_message = originals["us_build_status_message"]
            sm.DATA_DIR = originals["sm_DATA_DIR"]
            sm.BACKUP_DIR = originals["sm_BACKUP_DIR"]
            sm.USER_BACKUP_DIR = originals["sm_USER_BACKUP_DIR"]
            sm.USER_LOG_DIR = originals["sm_USER_LOG_DIR"]
            if originals["mainbot"] is None:
                sys.modules.pop("mainbot", None)
            else:
                sys.modules["mainbot"] = originals["mainbot"]


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

        _run_checks()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    checks_ok = not dbg.has_problem("status_storage_paths_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"checks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
