#!/usr/bin/env python3
import os
import shutil
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
SCRIPT_TITLE = "birthday_bulk_storage_debug"
FEATURE_TITLE = "Birthday Bulk Storage Atomicity"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _collect_failed_checks(section_payloads):
    failed = []
    for section_name, payload in section_payloads.items():
        checks = payload.get("checks")
        if not isinstance(checks, dict):
            continue
        for check_name, value in checks.items():
            if not value:
                failed.append(f"{section_name}:{check_name}")
    return failed


def _build_storage(storage_cls, tmpdir, user_id):
    return storage_cls(base_data_dir=tmpdir, admin_id=user_id)


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    tmpdir = None
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.storage import StorageManager
            from modules import constants as C
            import birthday_bulk_storage_checks as checks_mod
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        tmpdir = tempfile.mkdtemp(prefix="birthday_bulk_storage_debug_")
        sections = {
            "bulk_success": checks_mod.run_bulk_save_success_checks(
                _build_storage(StorageManager, tmpdir, 9201),
                9201,
            ),
            "bulk_limit_atomic": checks_mod.run_bulk_save_limit_atomic_checks(
                _build_storage(StorageManager, tmpdir, 9202),
                9202,
                C,
            ),
            "bulk_invalid_atomic": checks_mod.run_bulk_save_invalid_atomic_checks(
                _build_storage(StorageManager, tmpdir, 9203),
                9203,
            ),
            "bulk_invalid_tags_atomic": checks_mod.run_bulk_save_invalid_tags_atomic_checks(
                _build_storage(StorageManager, tmpdir, 9204),
                9204,
            ),
            "bulk_empty": checks_mod.run_bulk_save_empty_checks(
                _build_storage(StorageManager, tmpdir, 9205),
                9205,
            ),
        }

        for section_name, payload in sections.items():
            dbg.section(section_name, payload)

        failed_checks = _collect_failed_checks(sections)
        if failed_checks:
            dbg.problem("birthday_bulk_storage_failed", {"failed_checks": failed_checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        if tmpdir:
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass

    atomic_ok = not dbg.has_problem("birthday_bulk_storage_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"atomicity: {'OK' if atomic_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
