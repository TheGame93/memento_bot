#!/usr/bin/env python3
import os
import shutil
import stat
import subprocess
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
SCRIPT_TITLE = "startbot_cleanup_scripts_debug"
FEATURE_TITLE = "Startbot Cleanup Scripts"

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


def _write_text(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _write_bytes(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)


def _install_script(src_rel_path, dest_root):
    src_path = os.path.join(ROOT_DIR, src_rel_path)
    if not os.path.exists(src_path):
        return None
    dest_path = os.path.join(dest_root, src_rel_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy2(src_path, dest_path)
    current_mode = os.stat(dest_path).st_mode
    os.chmod(dest_path, current_mode | stat.S_IXUSR)
    return dest_path


def _run_script(script_rel_path, cwd):
    return subprocess.run(
        ["bash", script_rel_path],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _check_remove_tests_artifacts():
    with tempfile.TemporaryDirectory() as tmpdir:
        installed = _install_script("ops/remove_tests_artifacts.sh", tmpdir)
        if installed is None:
            return {
                "script_present": False,
            }

        _write_text(os.path.join(tmpdir, "tests", "log", ".gitkeep"), "")
        _write_text(os.path.join(tmpdir, "tests", "log", "master_debugger.log"), "x\n")
        _write_text(os.path.join(tmpdir, "tests", "log", "master_debugger.log.1"), "x\n")
        _write_text(os.path.join(tmpdir, "tests", "log", "hardening_step5_report.json"), "{}\n")
        _write_text(os.path.join(tmpdir, "tests", "log", "keep.json"), "{}\n")
        _write_text(os.path.join(tmpdir, "data", "systemlog.d", "system.log"), "x\n")
        _write_bytes(os.path.join(tmpdir, "backups", "users", "1001", "local", "backup_1.zip"), b"zip")
        _write_bytes(os.path.join(tmpdir, "backups", "users", "1001", "user_export_1001_1.zip"), b"zip")
        _write_bytes(os.path.join(tmpdir, "backups", "users", "2002", "local", "backup_2.zip"), b"zip")

        first_run = _run_script("./ops/remove_tests_artifacts.sh", cwd=tmpdir)
        second_run = _run_script("./ops/remove_tests_artifacts.sh", cwd=tmpdir)

        checks = {
            "script_present": True,
            "first_run_ok": first_run.returncode == 0,
            "second_run_ok": second_run.returncode == 0,
            "gitkeep_preserved": os.path.exists(os.path.join(tmpdir, "tests", "log", ".gitkeep")),
            "log_removed": not os.path.exists(os.path.join(tmpdir, "tests", "log", "master_debugger.log")),
            "rotated_log_removed": not os.path.exists(os.path.join(tmpdir, "tests", "log", "master_debugger.log.1")),
            "report_removed": not os.path.exists(os.path.join(tmpdir, "tests", "log", "hardening_step5_report.json")),
            "non_target_json_kept": os.path.exists(os.path.join(tmpdir, "tests", "log", "keep.json")),
            "outside_tests_log_kept": os.path.exists(os.path.join(tmpdir, "data", "systemlog.d", "system.log")),
            "zip_1001_removed": not os.path.exists(os.path.join(tmpdir, "backups", "users", "1001", "local", "backup_1.zip")),
            "zip_1001_export_removed": not os.path.exists(os.path.join(tmpdir, "backups", "users", "1001", "user_export_1001_1.zip")),
            "other_user_zip_kept": os.path.exists(os.path.join(tmpdir, "backups", "users", "2002", "local", "backup_2.zip")),
            "second_run_noop_msg": "No test artifacts or 1001 backups found." in (second_run.stdout or ""),
        }

        return {
            "script_present": True,
            "checks": checks,
            "first_run": {
                "returncode": first_run.returncode,
                "stdout": (first_run.stdout or "").strip().splitlines()[-4:],
                "stderr": (first_run.stderr or "").strip().splitlines()[-4:],
            },
            "second_run": {
                "returncode": second_run.returncode,
                "stdout": (second_run.stdout or "").strip().splitlines()[-4:],
                "stderr": (second_run.stderr or "").strip().splitlines()[-4:],
            },
        }


def _check_remove_all_logfiles():
    with tempfile.TemporaryDirectory() as tmpdir:
        installed = _install_script("ops/remove_all_logfiles.sh", tmpdir)
        if installed is None:
            return {
                "script_present": False,
            }

        _write_text(os.path.join(tmpdir, "tests", "log", "master_debugger.log"), "x\n")
        _write_text(os.path.join(tmpdir, "data", "systemlog.d", "lifecycle.log"), "x\n")
        _write_text(os.path.join(tmpdir, "docs", "notes.txt"), "keep\n")
        _write_text(os.path.join(tmpdir, ".git", "internal.log"), "must stay\n")
        _write_text(os.path.join(tmpdir, "venv", "sandbox.log"), "must stay\n")
        _write_bytes(os.path.join(tmpdir, "backups", "users", "1001", "backup.zip"), b"zip")

        first_run = _run_script("./ops/remove_all_logfiles.sh", cwd=tmpdir)
        second_run = _run_script("./ops/remove_all_logfiles.sh", cwd=tmpdir)

        checks = {
            "script_present": True,
            "first_run_ok": first_run.returncode == 0,
            "second_run_ok": second_run.returncode == 0,
            "tests_log_removed": not os.path.exists(os.path.join(tmpdir, "tests", "log", "master_debugger.log")),
            "system_log_removed": not os.path.exists(os.path.join(tmpdir, "data", "systemlog.d", "lifecycle.log")),
            "txt_kept": os.path.exists(os.path.join(tmpdir, "docs", "notes.txt")),
            "git_log_kept": os.path.exists(os.path.join(tmpdir, ".git", "internal.log")),
            "venv_log_kept": os.path.exists(os.path.join(tmpdir, "venv", "sandbox.log")),
            "zip_kept": os.path.exists(os.path.join(tmpdir, "backups", "users", "1001", "backup.zip")),
            "second_run_noop_msg": "No log files found." in (second_run.stdout or ""),
        }

        return {
            "script_present": True,
            "checks": checks,
            "first_run": {
                "returncode": first_run.returncode,
                "stdout": (first_run.stdout or "").strip().splitlines()[-4:],
                "stderr": (first_run.stderr or "").strip().splitlines()[-4:],
            },
            "second_run": {
                "returncode": second_run.returncode,
                "stdout": (second_run.stdout or "").strip().splitlines()[-4:],
                "stderr": (second_run.stderr or "").strip().splitlines()[-4:],
            },
        }


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        tests_artifacts = _check_remove_tests_artifacts()
        print_section("remove_tests_artifacts", tests_artifacts)
        if not tests_artifacts.get("script_present"):
            _log_problem("remove_tests_artifacts_script_missing")
        elif not all(tests_artifacts.get("checks", {}).values()):
            _log_problem("remove_tests_artifacts_checks_failed", {
                "checks": tests_artifacts.get("checks", {}),
            })

        all_logs = _check_remove_all_logfiles()
        print_section("remove_all_logfiles", all_logs)
        if not all_logs.get("script_present"):
            _log_problem("remove_all_logfiles_script_missing")
        elif not all(all_logs.get("checks", {}).values()):
            _log_problem("remove_all_logfiles_checks_failed", {
                "checks": all_logs.get("checks", {}),
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    tests_artifacts_ok = not dbg.has_problem(
        "remove_tests_artifacts_script_missing",
        "remove_tests_artifacts_checks_failed",
    )
    all_logs_ok = not dbg.has_problem(
        "remove_all_logfiles_script_missing",
        "remove_all_logfiles_checks_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"tests_artifacts: {'OK' if tests_artifacts_ok else 'FAIL'}",
        f"all_logs: {'OK' if all_logs_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
