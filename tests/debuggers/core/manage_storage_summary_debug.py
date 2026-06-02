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
SCRIPT_TITLE = "manage_storage_summary_debug"
FEATURE_TITLE = "Manage Storage Summary Contract"

IMPORT_ERROR = None
try:
    from telegram.error import BadRequest
    from modules.handlers import developer as developer_mod
    from modules.handlers import manage as manage_mod
    from modules.shared import storage_metrics as sm
    from modules.security import whitelist_store
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


class _DummyStorage:
    def __init__(self):
        self.events = []
        self.meta = {
            "100": {"username": "beta"},
            "200": {"username": "alpha"},
        }

    def get_user_meta(self, user_id):
        return self.meta.get(str(user_id), {})

    def get_user_role(self, _user_id):
        return "developer"

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": str(user_id),
            "event": event_type,
            "payload": payload or {},
        })
        return True

    def get_user_event_log_path(self, user_id):
        return os.path.join(sm.DATA_DIR, "userlog.d", f"{user_id}_events.log")


class _DummyQuery:
    def __init__(self, data, *, fail_mode=None):
        self.data = data
        self.message = SimpleNamespace()
        self.fail_mode = fail_mode
        self.answers = 0
        self.edits = []

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text, **kwargs):
        if self.fail_mode == "message_not_modified":
            raise BadRequest("Message is not modified")
        self.edits.append({"text": text, "kwargs": kwargs})
        return True


class _DummyUpdate:
    def __init__(self, query, user_id="987654321"):
        self.callback_query = query
        self.effective_user = SimpleNamespace(id=user_id)


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )


def _build_fixture():
    tmp = tempfile.TemporaryDirectory(prefix="manage_storage_summary_debug_")
    data_dir = os.path.join(tmp.name, "data")
    backup_dir = os.path.join(tmp.name, "backups")
    user_backup_dir = os.path.join(backup_dir, "users")
    user_log_dir = os.path.join(data_dir, "userlog.d")

    _write_bytes(os.path.join(data_dir, "100", "alerts.json"), 100)
    _write_bytes(os.path.join(data_dir, "200", "alerts.json"), 40)
    _write_bytes(os.path.join(user_log_dir, "100_events.log"), 10)
    _write_bytes(os.path.join(user_log_dir, "100_events.log.1"), 5)
    _write_bytes(os.path.join(user_log_dir, "200_events.log"), 20)
    _write_bytes(os.path.join(data_dir, "systemlog.d", "system.log"), 5)
    _write_bytes(os.path.join(user_backup_dir, "100", "local", "a.zip"), 30)
    _write_bytes(os.path.join(user_backup_dir, "200", "local", "a.zip"), 40)
    _write_bytes(os.path.join(backup_dir, "system", "global.zip"), 7)
    return tmp, data_dir, backup_dir, user_backup_dir, user_log_dir


def _check_payload_builder(storage):
    entries = [
        {"id": "100", "role": "user"},
        {"id": "200", "role": "user"},
    ]
    meta_map = developer_mod._build_meta_map(storage, entries)
    payload = developer_mod._build_storage_summary_payload(storage, entries, meta_map)
    text = payload.get("text") or ""
    idx_beta = text.find("@beta -")
    idx_alpha = text.find("@alpha -")
    checks = {
        "has_title": "Storage Summary" in text,
        "has_total_data_root_line": "Total space (data/):" in text,
        "has_total_system_log_root_line": "Total space (data/systemlog.d):" in text,
        "has_total_user_log_root_line": "Total space (data/userlog.d):" in text,
        "has_total_backup_root_line": "Total space (backups/):" in text,
        "has_header_line": "User name - Data / Logs / Backups" in text,
        "rows_format_data_logs_backups": "@beta -" in text and " / " in text,
        "rows_sorted_by_total_desc": idx_beta != -1 and idx_alpha != -1 and idx_beta < idx_alpha,
        "rows_count": payload.get("rows_count") == 2,
        "total_data_root_bytes": payload.get("total_data_root_bytes") == 180,
        "total_system_log_root_bytes": payload.get("total_system_log_root_bytes") == 5,
        "total_user_log_root_bytes": payload.get("total_user_log_root_bytes") == 35,
        "total_backup_root_bytes": payload.get("total_backup_root_bytes") == 77,
        "total_user_data_bytes": payload.get("total_user_data_bytes") == 140,
        "total_user_logs_bytes": payload.get("total_user_logs_bytes") == 35,
        "total_user_backups_bytes": payload.get("total_user_backups_bytes") == 70,
        "total_rows_bytes": payload.get("total_rows_bytes") == 245,
    }
    print_section("payload_builder", {"checks": checks, "payload": payload})
    if not all(checks.values()):
        _log_problem("manage_storage_summary_failed", {"label": "payload_builder", "checks": checks})


def _check_manage_callback(storage):
    query = _DummyQuery("mgmt_storage")
    update = _DummyUpdate(query)
    context = _DummyContext()
    _seed_runtime(context, storage)
    log_events = []

    originals = {
        "mainbot": sys.modules.get("mainbot"),
        "list_whitelist_users": whitelist_store.list_whitelist_users,
        "manage_log_system": manage_mod.log_system,
    }
    sys.modules["mainbot"] = SimpleNamespace(storage=storage)
    whitelist_store.list_whitelist_users = lambda: [
        {"id": "100", "role": "user"},
        {"id": "200", "role": "user"},
    ]
    manage_mod.log_system = lambda category, event, payload=None, level="INFO": log_events.append(
        {"category": category, "event": event, "payload": payload or {}, "level": level}
    )

    try:
        asyncio.run(manage_mod.handle_manage_callback(update, context))
    finally:
        if originals["mainbot"] is None:
            sys.modules.pop("mainbot", None)
        else:
            sys.modules["mainbot"] = originals["mainbot"]
        whitelist_store.list_whitelist_users = originals["list_whitelist_users"]
        manage_mod.log_system = originals["manage_log_system"]

    viewed_user_events = [e for e in storage.events if e.get("event") == "manage_storage_summary_viewed"]
    failed_user_events = [e for e in storage.events if e.get("event") == "manage_storage_summary_failed"]
    viewed_audit_events = [e for e in log_events if e.get("event") == "manage_storage_summary_viewed"]
    failed_audit_events = [e for e in log_events if e.get("event") == "manage_storage_summary_failed"]
    checks = {
        "query_answered_once": query.answers == 1,
        "message_edited_once": len(query.edits) == 1,
        "edited_text_has_totals": query.edits and "Total space (data/systemlog.d):" in query.edits[0]["text"],
        "user_viewed_event_logged": len(viewed_user_events) == 1,
        "user_failed_event_not_logged": len(failed_user_events) == 0,
        "audit_viewed_event_logged": len(viewed_audit_events) == 1,
        "audit_failed_event_not_logged": len(failed_audit_events) == 0,
        "payload_totals_present": viewed_user_events
        and viewed_user_events[0]["payload"].get("total_data_root_bytes") == 180
        and viewed_user_events[0]["payload"].get("total_system_log_root_bytes") == 5
        and viewed_user_events[0]["payload"].get("total_user_log_root_bytes") == 35
        and viewed_user_events[0]["payload"].get("total_backup_root_bytes") == 77
        and viewed_user_events[0]["payload"].get("rows_count") == 2
        and viewed_user_events[0]["payload"].get("delivery") == "edited",
    }
    print_section("manage_callback", {"checks": checks, "log_events": log_events, "user_events": storage.events})
    if not all(checks.values()):
        _log_problem("manage_storage_summary_failed", {"label": "manage_callback", "checks": checks})


def _check_manage_callback_message_not_modified(storage):
    query = _DummyQuery("mgmt_storage", fail_mode="message_not_modified")
    update = _DummyUpdate(query)
    context = _DummyContext()
    _seed_runtime(context, storage)
    log_events = []

    originals = {
        "mainbot": sys.modules.get("mainbot"),
        "list_whitelist_users": whitelist_store.list_whitelist_users,
        "manage_log_system": manage_mod.log_system,
    }
    sys.modules["mainbot"] = SimpleNamespace(storage=storage)
    whitelist_store.list_whitelist_users = lambda: [
        {"id": "100", "role": "user"},
        {"id": "200", "role": "user"},
    ]
    manage_mod.log_system = lambda category, event, payload=None, level="INFO": log_events.append(
        {"category": category, "event": event, "payload": payload or {}, "level": level}
    )

    try:
        asyncio.run(manage_mod.handle_manage_callback(update, context))
    finally:
        if originals["mainbot"] is None:
            sys.modules.pop("mainbot", None)
        else:
            sys.modules["mainbot"] = originals["mainbot"]
        whitelist_store.list_whitelist_users = originals["list_whitelist_users"]
        manage_mod.log_system = originals["manage_log_system"]

    viewed_user_events = [e for e in storage.events if e.get("event") == "manage_storage_summary_viewed"]
    failed_user_events = [e for e in storage.events if e.get("event") == "manage_storage_summary_failed"]
    viewed_audit_events = [e for e in log_events if e.get("event") == "manage_storage_summary_viewed"]
    failed_audit_events = [e for e in log_events if e.get("event") == "manage_storage_summary_failed"]
    checks = {
        "query_answered_once": query.answers == 1,
        "message_not_edited": len(query.edits) == 0,
        "user_viewed_event_logged": len(viewed_user_events) == 1,
        "user_failed_event_not_logged": len(failed_user_events) == 0,
        "audit_viewed_event_logged": len(viewed_audit_events) == 1,
        "audit_failed_event_not_logged": len(failed_audit_events) == 0,
        "delivery_message_not_modified": viewed_user_events
        and viewed_user_events[0]["payload"].get("delivery") == "message_not_modified",
    }
    print_section(
        "manage_callback_message_not_modified",
        {"checks": checks, "log_events": log_events, "user_events": storage.events},
    )
    if not all(checks.values()):
        _log_problem(
            "manage_storage_summary_failed",
            {"label": "manage_callback_message_not_modified", "checks": checks},
        )


def _check_developer_callback_message_not_modified(storage):
    query = _DummyQuery("developer_storage_summary", fail_mode="message_not_modified")
    update = _DummyUpdate(query)
    context = _DummyContext()
    _seed_runtime(context, storage)
    log_events = []

    originals = {
        "mainbot": sys.modules.get("mainbot"),
        "developer_list_whitelist_users": developer_mod.list_whitelist_users,
        "developer_log_system": developer_mod.log_system,
    }
    sys.modules["mainbot"] = SimpleNamespace(storage=storage)
    developer_mod.list_whitelist_users = lambda: [
        {"id": "100", "role": "user"},
        {"id": "200", "role": "user"},
    ]
    developer_mod.log_system = lambda category, event, payload=None, level="INFO": log_events.append(
        {"category": category, "event": event, "payload": payload or {}, "level": level}
    )

    try:
        asyncio.run(developer_mod.handle_developer_callback(update, context))
    finally:
        if originals["mainbot"] is None:
            sys.modules.pop("mainbot", None)
        else:
            sys.modules["mainbot"] = originals["mainbot"]
        developer_mod.list_whitelist_users = originals["developer_list_whitelist_users"]
        developer_mod.log_system = originals["developer_log_system"]

    viewed_user_events = [e for e in storage.events if e.get("event") == "manage_storage_summary_viewed"]
    failed_user_events = [e for e in storage.events if e.get("event") == "manage_storage_summary_failed"]
    viewed_audit_events = [e for e in log_events if e.get("event") == "manage_storage_summary_viewed"]
    failed_audit_events = [e for e in log_events if e.get("event") == "manage_storage_summary_failed"]
    checks = {
        "query_answered_once": query.answers == 1,
        "message_not_edited": len(query.edits) == 0,
        "user_viewed_event_logged": len(viewed_user_events) == 1,
        "user_failed_event_not_logged": len(failed_user_events) == 0,
        "audit_viewed_event_logged": len(viewed_audit_events) == 1,
        "audit_failed_event_not_logged": len(failed_audit_events) == 0,
        "payload_source_is_developer": viewed_user_events
        and viewed_user_events[0]["payload"].get("source") == "developer_storage_summary",
        "delivery_message_not_modified": viewed_user_events
        and viewed_user_events[0]["payload"].get("delivery") == "message_not_modified",
    }
    print_section(
        "developer_callback_message_not_modified",
        {"checks": checks, "log_events": log_events, "user_events": storage.events},
    )
    if not all(checks.values()):
        _log_problem(
            "manage_storage_summary_failed",
            {"label": "developer_callback_message_not_modified", "checks": checks},
        )


def _run_checks():
    fixture = _build_fixture()
    tmp, data_dir, backup_dir, user_backup_dir, user_log_dir = fixture
    storage = _DummyStorage()

    originals = {
        "sm_DATA_DIR": sm.DATA_DIR,
        "sm_BACKUP_DIR": sm.BACKUP_DIR,
        "sm_SYSTEM_LOG_DIR": sm.SYSTEM_LOG_DIR,
        "sm_USER_BACKUP_DIR": sm.USER_BACKUP_DIR,
        "sm_USER_LOG_DIR": sm.USER_LOG_DIR,
    }
    sm.DATA_DIR = data_dir
    sm.BACKUP_DIR = backup_dir
    sm.SYSTEM_LOG_DIR = os.path.join(data_dir, "systemlog.d")
    sm.USER_BACKUP_DIR = user_backup_dir
    sm.USER_LOG_DIR = user_log_dir

    try:
        _check_payload_builder(storage)
        _check_manage_callback(storage)
        storage.events = []
        _check_manage_callback_message_not_modified(storage)
        storage.events = []
        _check_developer_callback_message_not_modified(storage)
    finally:
        sm.DATA_DIR = originals["sm_DATA_DIR"]
        sm.BACKUP_DIR = originals["sm_BACKUP_DIR"]
        sm.SYSTEM_LOG_DIR = originals["sm_SYSTEM_LOG_DIR"]
        sm.USER_BACKUP_DIR = originals["sm_USER_BACKUP_DIR"]
        sm.USER_LOG_DIR = originals["sm_USER_LOG_DIR"]
        tmp.cleanup()


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

    checks_ok = not dbg.has_problem("manage_storage_summary_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"checks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
