#!/usr/bin/env python3
import importlib
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
SCRIPT_TITLE = "auth_access_debug"
FEATURE_TITLE = "Authorization Access"

IMPORT_ERROR = None
get_role_map = None
get_user_role = None
is_authorized = None
StorageManager = None


def _load_runtime_modules():
    """Load auth and storage modules after BOT_DATA_DIR is set."""
    global get_role_map, get_user_role, is_authorized, StorageManager

    paths_module = importlib.import_module("modules.shared.paths")
    importlib.reload(paths_module)
    authz_module = importlib.import_module("modules.security.authz")
    importlib.reload(authz_module)
    storage_module = importlib.import_module("modules.storage")
    importlib.reload(storage_module)

    get_role_map = authz_module.get_role_map
    get_user_role = authz_module.get_user_role
    is_authorized = authz_module.is_authorized
    StorageManager = storage_module.StorageManager

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


def _test_whitelist_parser():
    with tempfile.TemporaryDirectory() as tmpdir:
        old_style = os.path.join(tmpdir, "old_style.json")
        with open(old_style, "w", encoding="utf-8") as f:
            json.dump([111, 222], f)

        roles = get_role_map(path=old_style, admin_id=999)
        checks = {
            "old_style_user_role": roles.get("111") == "user",
            "old_style_second_user_role": roles.get("222") == "user",
            "admin_fallback_developer": roles.get("999") == "developer",
        }
        print_section("whitelist_old_style", {"roles": roles, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_parser_failed", {"style": "old", "checks": checks, "roles": roles})

        canonical = os.path.join(tmpdir, "canonical.json")
        with open(canonical, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "users": [
                        {"id": 1000, "role": "developer"},
                        {"id": 2000, "role": "admin"},
                        {"id": 3000, "role": "user"},
                        4000,
                    ]
                },
                f,
            )

        roles_canonical = get_role_map(path=canonical, admin_id=None)
        checks_canonical = {
            "developer_role": roles_canonical.get("1000") == "developer",
            "admin_role": roles_canonical.get("2000") == "admin",
            "user_role": roles_canonical.get("3000") == "user",
            "list_user_role": roles_canonical.get("4000") == "user",
        }
        print_section("whitelist_canonical", {"roles": roles_canonical, "checks": checks_canonical})
        if not all(checks_canonical.values()):
            _log_problem("whitelist_parser_failed", {"style": "canonical", "checks": checks_canonical, "roles": roles_canonical})

        new_style = os.path.join(tmpdir, "new_style.json")
        with open(new_style, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "developer": 1000,
                    "admins": [2000],
                    "users": [
                        {"id": 3000, "role": "user"},
                        {"id": 4000, "role": "admin"},
                    ],
                },
                f,
            )

        roles_new = get_role_map(path=new_style, admin_id=None)
        checks_new = {
            "developer_role": roles_new.get("1000") == "developer",
            "admin_role": roles_new.get("2000") == "admin",
            "record_user_role": roles_new.get("3000") == "user",
            "record_admin_role": roles_new.get("4000") == "admin",
        }
        print_section("whitelist_new_style", {"roles": roles_new, "checks": checks_new})
        if not all(checks_new.values()):
            _log_problem("whitelist_parser_failed", {"style": "new", "checks": checks_new, "roles": roles_new})


def _test_role_resolution():
    with tempfile.TemporaryDirectory() as tmpdir:
        whitelist_path = os.path.join(tmpdir, "roles.json")
        with open(whitelist_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "roles": {
                        "developer": [10],
                        "admin": [20, 30],
                        "user": [40, 50],
                    }
                },
                f,
            )

        checks = {
            "developer_is_authorized": is_authorized(10, path=whitelist_path),
            "admin_is_authorized": is_authorized(20, path=whitelist_path),
            "user_is_authorized": is_authorized(40, path=whitelist_path),
            "unknown_not_authorized": not is_authorized(60, path=whitelist_path),
            "role_developer": get_user_role(10, path=whitelist_path) == "developer",
            "role_admin": get_user_role(30, path=whitelist_path) == "admin",
            "role_user": get_user_role(50, path=whitelist_path) == "user",
            "role_unknown": get_user_role(70, path=whitelist_path) is None,
        }
        print_section("role_resolution", {"checks": checks})
        if not all(checks.values()):
            _log_problem("role_resolution_failed", {"checks": checks})


def _test_storage_bridge(data_root):
    system_dir = os.path.join(data_root, "system")
    whitelist_path = os.path.join(system_dir, "whitelist.json")
    os.makedirs(system_dir, exist_ok=True)
    with open(whitelist_path, "w", encoding="utf-8") as f:
        json.dump([12345], f)

    storage = StorageManager(base_data_dir=data_root, admin_id=99999)
    unauthorized_log_ok = storage.log_user_event(54321, "unauth_attempt", {"note": "debug_check"})
    unauthorized_folder_exists = os.path.exists(os.path.join(data_root, "54321"))

    storage.setup_user_space(12345)
    storage.setup_user_space(99999)
    rogue_path = os.path.join(data_root, "54321")
    os.makedirs(rogue_path, exist_ok=True)
    with open(os.path.join(rogue_path, "alerts.json"), "w", encoding="utf-8") as f:
        json.dump({"tags": [], "alerts": [], "postpone_queue": []}, f)
    scheduler_users = set(storage.get_all_users())

    checks = {
        "listed_user_allowed": storage.is_user_whitelisted(12345),
        "admin_fallback_allowed": storage.is_user_whitelisted(99999),
        "unknown_denied": not storage.is_user_whitelisted(54321),
        "listed_role_user": storage.get_user_role(12345) == "user",
        "admin_role_developer": storage.get_user_role(99999) == "developer",
        "unauthorized_log_rejected": unauthorized_log_ok is False,
        "unauthorized_folder_not_created": unauthorized_folder_exists is False,
        "scheduler_users_authorized_only": "54321" not in scheduler_users and {"12345", "99999"}.issubset(scheduler_users),
    }
    print_section("storage_bridge", {"checks": checks})
    if not all(checks.values()):
        _log_problem("storage_whitelist_bridge_failed", {"checks": checks})


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        with tempfile.TemporaryDirectory() as runtime_tmpdir:
            previous_data_dir = os.environ.get("BOT_DATA_DIR")
            data_root = os.path.join(runtime_tmpdir, "data")
            os.environ["BOT_DATA_DIR"] = data_root
            try:
                try:
                    _load_runtime_modules()
                except ModuleNotFoundError as exc:
                    dbg.mark_dependency_error(exc)
                    dbg.finish(exit_on_problems=False)
                    return

                _test_whitelist_parser()
                _test_role_resolution()
                _test_storage_bridge(data_root)
            finally:
                if previous_data_dir is None:
                    os.environ.pop("BOT_DATA_DIR", None)
                else:
                    os.environ["BOT_DATA_DIR"] = previous_data_dir
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    parser_ok = not dbg.has_problem("whitelist_parser_failed")
    roles_ok = not dbg.has_problem("role_resolution_failed")
    storage_ok = not dbg.has_problem("storage_whitelist_bridge_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"parser: {'OK' if parser_ok else 'FAIL'}",
        f"roles: {'OK' if roles_ok else 'FAIL'}",
        f"storage-bridge: {'OK' if storage_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
