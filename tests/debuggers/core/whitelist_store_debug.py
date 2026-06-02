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
SCRIPT_TITLE = "whitelist_store_debug"
FEATURE_TITLE = "Whitelist Store"

IMPORT_ERROR = None
try:
    import modules.security.authz as authz
    import modules.security.whitelist_store as whitelist_store_module
    from modules.security.whitelist_store import (
        add_whitelist_user,
        ensure_whitelist_seeded,
        find_whitelist_invite,
        list_whitelist_users,
        list_whitelist_invites,
        reconcile_startup_whitelist,
        remove_whitelist_user,
        remove_whitelist_invite,
        upsert_whitelist_invite,
    )
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


def _write_whitelist_payload(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _test_store_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        whitelist_path = os.path.join(tmpdir, "whitelist.json")

        ok_add = add_whitelist_user(100, role="admin", path=whitelist_path)
        users = list_whitelist_users(path=whitelist_path)
        checks = {
            "add_ok": ok_add is True,
            "user_count": len(users) == 1,
            "role_admin": users[0].get("role") == "admin",
        }
        print_section("whitelist_add", {"users": users, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "add", "checks": checks})
            return

        ok_add_update = add_whitelist_user(100, role="developer", path=whitelist_path)
        users = list_whitelist_users(path=whitelist_path)
        checks = {
            "add_update_ok": ok_add_update is True,
            "role_updated": users[0].get("role") == "developer",
        }
        print_section("whitelist_update", {"users": users, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "update", "checks": checks})
            return

        ok_no_downgrade = add_whitelist_user(100, role="user", path=whitelist_path)
        users = list_whitelist_users(path=whitelist_path)
        checks = {
            "no_downgrade_ok": ok_no_downgrade is True,
            "role_still_developer": users[0].get("role") == "developer",
        }
        print_section("whitelist_no_downgrade", {"users": users, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "no_downgrade", "checks": checks})
            return

        ok_force_down = add_whitelist_user(100, role="user", path=whitelist_path, force=True)
        users = list_whitelist_users(path=whitelist_path)
        checks = {
            "force_down_ok": ok_force_down is True,
            "role_now_user": users[0].get("role") == "user",
        }
        print_section("whitelist_force_downgrade", {"users": users, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "force_downgrade", "checks": checks})
            return

        ok_force_same = add_whitelist_user(100, role="user", path=whitelist_path, force=True)
        users = list_whitelist_users(path=whitelist_path)
        checks = {
            "force_same_ok": ok_force_same is True,
            "role_still_user": users[0].get("role") == "user",
        }
        print_section("whitelist_force_same_noop", {"users": users, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "force_same_noop", "checks": checks})
            return

        add_whitelist_user(100, role="developer", path=whitelist_path, force=True)

        removed = remove_whitelist_user(100, path=whitelist_path)
        users_after = list_whitelist_users(path=whitelist_path)
        checks = {
            "removed_ok": removed is True,
            "users_empty": users_after == [],
        }
        print_section("whitelist_remove", {"users": users_after, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "remove", "checks": checks})
            return

        removed_missing = remove_whitelist_user(200, path=whitelist_path)
        checks = {
            "remove_missing_false": removed_missing is False,
        }
        print_section("whitelist_remove_missing", {"checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "remove_missing", "checks": checks})

        cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            ok_relative = add_whitelist_user(300, role="user", path="whitelist.json")
            users_relative = list_whitelist_users(path="whitelist.json")
            checks = {
                "relative_add_ok": ok_relative is True,
                "relative_user_added": len(users_relative) == 1 and str(users_relative[0].get("id")) == "300",
            }
            print_section("whitelist_relative_path", {"users": users_relative, "checks": checks})
            if not all(checks.values()):
                _log_problem("whitelist_store_failed", {"step": "relative_path", "checks": checks})
        finally:
            os.chdir(cwd)


def _test_cache_invalidation_with_coarse_mtime():
    with tempfile.TemporaryDirectory() as tmpdir:
        whitelist_path = os.path.join(tmpdir, "whitelist.json")
        original_get_mtime = authz._get_mtime
        try:
            authz._get_mtime = lambda _path: 123.0
            ok1 = add_whitelist_user(1001, role="user", path=whitelist_path)
            ok2 = add_whitelist_user(1002, role="admin", path=whitelist_path)
            users = list_whitelist_users(path=whitelist_path)
            ids = {str(item.get("id")) for item in users}
            checks = {
                "first_add_ok": ok1 is True,
                "second_add_ok": ok2 is True,
                "contains_1001": "1001" in ids,
                "contains_1002": "1002" in ids,
                "count_two": len(users) == 2,
            }
            print_section("whitelist_cache_invalidation", {"users": users, "checks": checks})
            if not all(checks.values()):
                _log_problem("whitelist_store_failed", {"step": "cache_invalidation", "checks": checks, "users": users})
        finally:
            authz._get_mtime = original_get_mtime


def _test_ensure_whitelist_seeded():
    with tempfile.TemporaryDirectory() as tmpdir:
        whitelist_path = os.path.join(tmpdir, "system", "whitelist.json")

        result_missing = ensure_whitelist_seeded(12345, path=whitelist_path)
        users_missing = list_whitelist_users(path=whitelist_path)
        checks_missing = {
            "missing_seeded": result_missing.get("status") == "seeded",
            "missing_path": result_missing.get("path") == os.path.abspath(whitelist_path),
            "missing_user_count": len(users_missing) == 1,
            "missing_user_id": str(users_missing[0].get("id")) == "12345",
            "missing_user_role": users_missing[0].get("role") == "developer",
        }
        print_section("whitelist_seed_missing", {"result": result_missing, "users": users_missing, "checks": checks_missing})
        if not all(checks_missing.values()):
            _log_problem("whitelist_store_failed", {"step": "seed_missing", "checks": checks_missing, "result": result_missing})
            return

        corrupt_path = os.path.join(tmpdir, "corrupt", "whitelist.json")
        os.makedirs(os.path.dirname(corrupt_path), exist_ok=True)
        with open(corrupt_path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with open(corrupt_path, "r", encoding="utf-8") as handle:
            before_corrupt = handle.read()
        result_corrupt = ensure_whitelist_seeded(12345, path=corrupt_path)
        with open(corrupt_path, "r", encoding="utf-8") as handle:
            after_corrupt = handle.read()
        checks_corrupt = {
            "corrupt_status": result_corrupt.get("status") == "corrupt",
            "corrupt_unchanged": before_corrupt == after_corrupt,
        }
        print_section("whitelist_seed_corrupt", {"result": result_corrupt, "checks": checks_corrupt})
        if not all(checks_corrupt.values()):
            _log_problem("whitelist_store_failed", {"step": "seed_corrupt", "checks": checks_corrupt, "result": result_corrupt})
            return

        exists_path = os.path.join(tmpdir, "exists", "whitelist.json")
        os.makedirs(os.path.dirname(exists_path), exist_ok=True)
        with open(exists_path, "w", encoding="utf-8") as handle:
            json.dump({"users": [{"id": 777, "role": "admin"}]}, handle)
        with open(exists_path, "r", encoding="utf-8") as handle:
            before_exists = handle.read()
        result_exists = ensure_whitelist_seeded(12345, path=exists_path)
        with open(exists_path, "r", encoding="utf-8") as handle:
            after_exists = handle.read()
        users_exists = list_whitelist_users(path=exists_path)
        checks_exists = {
            "exists_status": result_exists.get("status") == "exists",
            "exists_unchanged": before_exists == after_exists,
            "exists_seed_absent": all(str(user.get("id")) != "12345" for user in users_exists),
        }
        print_section("whitelist_seed_exists", {"result": result_exists, "users": users_exists, "checks": checks_exists})
        if not all(checks_exists.values()):
            _log_problem("whitelist_store_failed", {"step": "seed_exists", "checks": checks_exists, "result": result_exists})
            return

        missing_invalid_path = os.path.join(tmpdir, "invalid", "whitelist.json")
        result_invalid = ensure_whitelist_seeded("   ", path=missing_invalid_path)
        checks_invalid = {
            "invalid_skipped": result_invalid.get("status") == "skipped",
            "invalid_reason": result_invalid.get("reason") == "invalid_admin_id",
            "invalid_absent": not os.path.exists(missing_invalid_path),
        }
        print_section("whitelist_seed_invalid", {"result": result_invalid, "checks": checks_invalid})
        if not all(checks_invalid.values()):
            _log_problem("whitelist_store_failed", {"step": "seed_invalid", "checks": checks_invalid, "result": result_invalid})


def _test_reconcile_startup_whitelist():
    with tempfile.TemporaryDirectory() as tmpdir:
        def canonical_path(case_name):
            return os.path.join(tmpdir, case_name, "system", "whitelist.json")

        seed_path = canonical_path("seed")
        result_seed = reconcile_startup_whitelist(12345, path=seed_path)
        users_seed = list_whitelist_users(path=seed_path)
        checks_seed = {
            "status_seeded": result_seed.get("status") == "seeded",
            "seed_user_count": len(users_seed) == 1,
            "seed_user_id": len(users_seed) == 1 and str(users_seed[0].get("id")) == "12345",
            "seed_user_role": len(users_seed) == 1 and users_seed[0].get("role") == "developer",
        }
        print_section("startup_reconcile_seeded", {"result": result_seed, "users": users_seed, "checks": checks_seed})
        if not all(checks_seed.values()):
            _log_problem("whitelist_store_failed", {"step": "reconcile_seeded", "checks": checks_seed, "result": result_seed})
            return

        corrupt_path = canonical_path("corrupt")
        os.makedirs(os.path.dirname(corrupt_path), exist_ok=True)
        with open(corrupt_path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        authz.invalidate_role_map_cache(path=corrupt_path)
        result_corrupt = reconcile_startup_whitelist(12345, path=corrupt_path)
        checks_corrupt = {
            "status_corrupt": result_corrupt.get("status") == "corrupt",
        }
        print_section("startup_reconcile_corrupt", {"result": result_corrupt, "checks": checks_corrupt})
        if not all(checks_corrupt.values()):
            _log_problem("whitelist_store_failed", {"step": "reconcile_corrupt", "checks": checks_corrupt, "result": result_corrupt})
            return

        invalid_path = canonical_path("invalid_admin_missing")
        result_invalid = reconcile_startup_whitelist("   ", path=invalid_path)
        checks_invalid = {
            "status_skipped": result_invalid.get("status") == "skipped",
            "invalid_reason": result_invalid.get("reason") == "invalid_admin_id",
            "invalid_absent": not os.path.exists(invalid_path),
        }
        print_section("startup_reconcile_invalid_admin", {"result": result_invalid, "checks": checks_invalid})
        if not all(checks_invalid.values()):
            _log_problem("whitelist_store_failed", {"step": "reconcile_invalid_admin", "checks": checks_invalid, "result": result_invalid})
            return

        exists_path = canonical_path("exists")
        _write_whitelist_payload(exists_path, {"users": [{"id": 555, "role": "admin"}]})
        before_exists = _read_text(exists_path)
        authz.invalidate_role_map_cache(path=exists_path)
        result_exists = reconcile_startup_whitelist(12345, path=exists_path)
        after_exists = _read_text(exists_path)
        users_exists = list_whitelist_users(path=exists_path)
        checks_exists = {
            "status_exists": result_exists.get("status") == "exists",
            "exists_unchanged": before_exists == after_exists,
            "exists_seed_absent": all(str(user.get("id")) != "12345" for user in users_exists),
        }
        print_section("startup_reconcile_exists", {"result": result_exists, "users": users_exists, "checks": checks_exists})
        if not all(checks_exists.values()):
            _log_problem("whitelist_store_failed", {"step": "reconcile_exists", "checks": checks_exists, "result": result_exists})
            return

def _test_seed_race_handling():
    def run_case(case_name, competing_writer):
        with tempfile.TemporaryDirectory() as tmpdir:
            whitelist_path = os.path.join(tmpdir, case_name, "system", "whitelist.json")
            original_link = whitelist_store_module.os.link
            try:
                def fake_link(src, dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    competing_writer(dst)
                    raise FileExistsError("simulated seed race")

                whitelist_store_module.os.link = fake_link
                result = ensure_whitelist_seeded(12345, path=whitelist_path)
            finally:
                whitelist_store_module.os.link = original_link

            temp_dir = os.path.dirname(whitelist_path)
            leftovers = []
            if os.path.isdir(temp_dir):
                leftovers = [
                    name for name in os.listdir(temp_dir)
                    if name.startswith(".whitelist.") and name.endswith(".tmp")
                ]
            authz.invalidate_role_map_cache(path=whitelist_path)
            users = list_whitelist_users(path=whitelist_path) if os.path.exists(whitelist_path) else []
            file_text = _read_text(whitelist_path) if os.path.exists(whitelist_path) else None
            return result, leftovers, users, file_text

    def write_valid(dst):
        _write_whitelist_payload(dst, {"users": [{"id": 777, "role": "admin"}]})

    result_exists, leftovers_exists, users_exists, _exists_text = run_case("race_exists", write_valid)
    checks_exists = {
        "race_exists_status": result_exists.get("status") == "exists",
        "race_exists_preserved_competing_user": len(users_exists) == 1 and str(users_exists[0].get("id")) == "777",
        "race_exists_no_leftovers": leftovers_exists == [],
    }
    print_section("whitelist_seed_race_exists", {"result": result_exists, "users": users_exists, "leftovers": leftovers_exists, "checks": checks_exists})
    if not all(checks_exists.values()):
        _log_problem("whitelist_store_failed", {"step": "seed_race_exists", "checks": checks_exists, "result": result_exists, "leftovers": leftovers_exists})
        return

    def write_corrupt(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as handle:
            handle.write("{broken")

    result_corrupt, leftovers_corrupt, _corrupt_users, corrupt_text = run_case("race_corrupt", write_corrupt)
    checks_corrupt = {
        "race_corrupt_status": result_corrupt.get("status") == "corrupt",
        "race_corrupt_no_leftovers": leftovers_corrupt == [],
        "race_corrupt_file_preserved": corrupt_text == "{broken",
    }
    print_section("whitelist_seed_race_corrupt", {"result": result_corrupt, "leftovers": leftovers_corrupt, "checks": checks_corrupt})
    if not all(checks_corrupt.values()):
        _log_problem("whitelist_store_failed", {"step": "seed_race_corrupt", "checks": checks_corrupt, "result": result_corrupt, "leftovers": leftovers_corrupt})


def _test_invite_store_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        invites_path = os.path.join(tmpdir, "whitelist_invites.json")

        ok_add = upsert_whitelist_invite(username="@Alpha", role="admin", invited_by=99, path=invites_path)
        invites = list_whitelist_invites(path=invites_path)
        record = find_whitelist_invite(username="alpha", path=invites_path)
        checks = {
            "invite_add_ok": ok_add is True,
            "invite_count": len(invites) == 1,
            "invite_username_lower": invites[0].get("username") == "alpha",
            "invite_role": invites[0].get("role") == "admin",
            "invite_find": record is not None and record.get("username") == "alpha",
        }
        print_section("invite_add", {"invites": invites, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "invite_add", "checks": checks})
            return

        ok_update = upsert_whitelist_invite(username="ALPHA", role="developer", invited_by=100, path=invites_path)
        invites = list_whitelist_invites(path=invites_path)
        checks = {
            "invite_update_ok": ok_update is True,
            "invite_role_updated": invites[0].get("role") == "developer",
        }
        print_section("invite_update", {"invites": invites, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "invite_update", "checks": checks})
            return

        removed = remove_whitelist_invite(username="alpha", path=invites_path)
        invites_after = list_whitelist_invites(path=invites_path)
        checks = {
            "invite_removed_ok": removed is True,
            "invite_empty": invites_after == [],
        }
        print_section("invite_remove", {"invites": invites_after, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "invite_remove", "checks": checks})

        ok_add_by_id = upsert_whitelist_invite(user_id=555, display_name="Beta User", invited_by=99, path=invites_path)
        record_by_id = find_whitelist_invite(user_id="555", path=invites_path)
        checks = {
            "invite_add_by_id_ok": ok_add_by_id is True,
            "invite_find_by_id": record_by_id is not None and record_by_id.get("user_id") == "555",
            "invite_name_stored": record_by_id is not None and record_by_id.get("display_name") == "Beta User",
        }
        print_section("invite_add_by_id", {"record": record_by_id, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "invite_add_by_id", "checks": checks})

        removed_by_id = remove_whitelist_invite(user_id="555", path=invites_path)
        invites_after_id = list_whitelist_invites(path=invites_path)
        checks = {
            "invite_removed_by_id_ok": removed_by_id is True,
            "invite_empty_after_id": invites_after_id == [],
        }
        print_section("invite_remove_by_id", {"invites": invites_after_id, "checks": checks})
        if not all(checks.values()):
            _log_problem("whitelist_store_failed", {"step": "invite_remove_by_id", "checks": checks})


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

        _test_store_flow()
        _test_cache_invalidation_with_coarse_mtime()
        _test_ensure_whitelist_seeded()
        _test_reconcile_startup_whitelist()
        _test_seed_race_handling()
        _test_invite_store_flow()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    store_ok = not dbg.has_problem("whitelist_store_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"store: {'OK' if store_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
