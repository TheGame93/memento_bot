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
SCRIPT_TITLE = "startbot_cli_cleanup_flow_debug"
FEATURE_TITLE = "Startbot CLI Cleanup Flow"

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


def _make_executable(path):
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR)


def _prepare_sandbox(tmpdir):
    for script_name in ("startbot.sh", "ops/remove_tests_artifacts.sh", "ops/remove_all_logfiles.sh"):
        src = os.path.join(ROOT_DIR, script_name)
        dst = os.path.join(tmpdir, script_name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        _make_executable(dst)

    _write_text(os.path.join(tmpdir, "pythonrequirements.txt"), "\n")
    _write_text(
        os.path.join(tmpdir, "mainbot.py"),
        "import sys\n"
        "sys.exit(0)\n",
    )
    _write_text(os.path.join(tmpdir, "venv", "bin", "activate"), "# fake\n")
    _write_text(
        os.path.join(tmpdir, "venv", "bin", "pip"),
        "#!/bin/bash\n"
        "exit 0\n",
    )
    _make_executable(os.path.join(tmpdir, "venv", "bin", "pip"))
    _write_text(
        os.path.join(tmpdir, "venv", "bin", "python3"),
        "#!/bin/bash\n"
        "exec python3 \"$@\"\n",
    )
    _make_executable(os.path.join(tmpdir, "venv", "bin", "python3"))


def _seed_artifacts(tmpdir):
    _write_text(os.path.join(tmpdir, "tests", "log", ".gitkeep"), "")
    _write_text(os.path.join(tmpdir, "tests", "log", "master_debugger.log"), "x\n")
    _write_text(os.path.join(tmpdir, "tests", "log", "hardening_step5_report.json"), "{}\n")
    _write_text(os.path.join(tmpdir, "tests", "log", "keep.json"), "{}\n")
    _write_text(os.path.join(tmpdir, "data", "systemlog.d", "lifecycle.log"), "x\n")
    _write_text(os.path.join(tmpdir, "data", "systemlog.d", "system.log"), "x\n")
    _write_bytes(os.path.join(tmpdir, "backups", "users", "1001", "local", "backup.zip"), b"zip")
    _write_bytes(os.path.join(tmpdir, "backups", "users", "2002", "local", "backup.zip"), b"zip")


def _run_startbot(tmpdir, args):
    env = os.environ.copy()
    env["STARTBOT_SKIP_DEPS"] = "1"
    env["STARTBOT_DNS_HOST"] = "localhost"
    env["STARTBOT_DNS_WAIT_SECONDS"] = "1"
    env["STARTBOT_DNS_WAIT_INTERVAL"] = "1"
    cmd = ["bash", "./startbot.sh"] + list(args)
    try:
        result = subprocess.run(
            cmd,
            cwd=tmpdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
        }


def _collect_state(tmpdir):
    return {
        "tests_log_exists": os.path.exists(os.path.join(tmpdir, "tests", "log", "master_debugger.log")),
        "tests_report_exists": os.path.exists(os.path.join(tmpdir, "tests", "log", "hardening_step5_report.json")),
        "tests_keep_json_exists": os.path.exists(os.path.join(tmpdir, "tests", "log", "keep.json")),
        "tests_gitkeep_exists": os.path.exists(os.path.join(tmpdir, "tests", "log", ".gitkeep")),
        "system_log_exists": os.path.exists(os.path.join(tmpdir, "data", "systemlog.d", "system.log")),
        "lifecycle_log_exists": os.path.exists(os.path.join(tmpdir, "data", "systemlog.d", "lifecycle.log")),
        "backup_1001_exists": os.path.exists(os.path.join(tmpdir, "backups", "users", "1001", "local", "backup.zip")),
        "backup_2002_exists": os.path.exists(os.path.join(tmpdir, "backups", "users", "2002", "local", "backup.zip")),
    }


def _run_flow_case(case):
    with tempfile.TemporaryDirectory() as tmpdir:
        _prepare_sandbox(tmpdir)
        _seed_artifacts(tmpdir)

        if case.get("fail_clean_script"):
            failing_script = case["fail_clean_script"]
            _write_text(
                os.path.join(tmpdir, failing_script),
                "#!/bin/bash\n"
                "echo forced_failure\n"
                "exit 7\n",
            )
            _make_executable(os.path.join(tmpdir, failing_script))

        result = _run_startbot(tmpdir, case["args"])
        state = _collect_state(tmpdir)
        combined = f"{result['stdout']}\n{result['stderr']}"

        checks = {
            "returncode_ok": (
                result["returncode"] == case["expect_returncode"]
                if "expect_returncode" in case
                else (result["returncode"] != 0 if case.get("expect_nonzero", False) else True)
            ),
            "timed_out_ok": not result["timed_out"],
            "start_banner_ok": ("Starting Alert Bot..." in combined) == case.get("expect_start_banner", True),
            "tests_log_ok": state["tests_log_exists"] == case["expect_tests_log_exists"],
            "tests_report_ok": state["tests_report_exists"] == case["expect_tests_report_exists"],
            "tests_keep_ok": state["tests_keep_json_exists"] == case["expect_tests_keep_json_exists"],
            "gitkeep_ok": state["tests_gitkeep_exists"] == case["expect_gitkeep_exists"],
            "system_log_ok": state["system_log_exists"] == case["expect_system_log_exists"],
            "backup_1001_ok": state["backup_1001_exists"] == case["expect_backup_1001_exists"],
            "backup_2002_ok": state["backup_2002_exists"] == case["expect_backup_2002_exists"],
        }

        expect_substring = case.get("expect_substring")
        if expect_substring is not None:
            checks["substring_ok"] = expect_substring in combined

        return {
            "name": case["name"],
            "args": case["args"],
            "checks": checks,
            "result": {
                "returncode": result["returncode"],
                "timed_out": result["timed_out"],
                "stdout_tail": result["stdout"].strip().splitlines()[-10:],
                "stderr_tail": result["stderr"].strip().splitlines()[-10:],
            },
            "state": state,
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

        cases = [
            {
                "name": "clean_only",
                "args": ["-c"],
                "expect_returncode": 0,
                "expect_start_banner": True,
                "expect_tests_log_exists": False,
                "expect_tests_report_exists": False,
                "expect_tests_keep_json_exists": True,
                "expect_gitkeep_exists": True,
                "expect_system_log_exists": True,
                "expect_backup_1001_exists": False,
                "expect_backup_2002_exists": True,
            },
            {
                "name": "new_only",
                "args": ["-n"],
                "expect_returncode": 0,
                "expect_start_banner": True,
                "expect_tests_log_exists": False,
                "expect_tests_report_exists": True,
                "expect_tests_keep_json_exists": True,
                "expect_gitkeep_exists": True,
                "expect_system_log_exists": False,
                "expect_backup_1001_exists": True,
                "expect_backup_2002_exists": True,
            },
            {
                "name": "combined_nc",
                "args": ["-nc"],
                "expect_returncode": 0,
                "expect_start_banner": True,
                "expect_tests_log_exists": False,
                "expect_tests_report_exists": False,
                "expect_tests_keep_json_exists": True,
                "expect_gitkeep_exists": True,
                "expect_system_log_exists": False,
                "expect_backup_1001_exists": False,
                "expect_backup_2002_exists": True,
            },
            {
                "name": "clean_fail_abort",
                "args": ["-c"],
                "fail_clean_script": "ops/remove_tests_artifacts.sh",
                "expect_nonzero": True,
                "expect_start_banner": False,
                "expect_tests_log_exists": True,
                "expect_tests_report_exists": True,
                "expect_tests_keep_json_exists": True,
                "expect_gitkeep_exists": True,
                "expect_system_log_exists": True,
                "expect_backup_1001_exists": True,
                "expect_backup_2002_exists": True,
                "expect_substring": "aborting startup.",
            },
            {
                "name": "clean_fail_force_continue",
                "args": ["-c", "--force-start"],
                "fail_clean_script": "ops/remove_tests_artifacts.sh",
                "expect_returncode": 0,
                "expect_start_banner": True,
                "expect_tests_log_exists": True,
                "expect_tests_report_exists": True,
                "expect_tests_keep_json_exists": True,
                "expect_gitkeep_exists": True,
                "expect_system_log_exists": True,
                "expect_backup_1001_exists": True,
                "expect_backup_2002_exists": True,
                "expect_substring": "continuing due to --force-start.",
            },
        ]

        failed_cases = []
        for case in cases:
            outcome = _run_flow_case(case)
            print_section("cleanup_flow_case", outcome)
            if not all(outcome["checks"].values()):
                failed_cases.append({
                    "name": outcome["name"],
                    "checks": outcome["checks"],
                    "result": outcome["result"],
                    "state": outcome["state"],
                })

        if failed_cases:
            _log_problem("startbot_cli_cleanup_flow_checks_failed", {
                "failed_cases": failed_cases,
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    flow_ok = not dbg.has_problem("startbot_cli_cleanup_flow_checks_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"flow: {'OK' if flow_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
