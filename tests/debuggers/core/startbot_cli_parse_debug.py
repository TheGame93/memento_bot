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
SCRIPT_TITLE = "startbot_cli_parse_debug"
FEATURE_TITLE = "Startbot CLI Parsing"

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


def _make_executable(path):
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR)


def _prepare_startbot_sandbox(tmpdir):
    src_startbot = os.path.join(ROOT_DIR, "startbot.sh")
    dst_startbot = os.path.join(tmpdir, "startbot.sh")
    shutil.copy2(src_startbot, dst_startbot)
    _make_executable(dst_startbot)

    for cleanup_script in ("ops/remove_tests_artifacts.sh", "ops/remove_all_logfiles.sh"):
        src_cleanup = os.path.join(ROOT_DIR, cleanup_script)
        dst_cleanup = os.path.join(tmpdir, cleanup_script)
        os.makedirs(os.path.dirname(dst_cleanup), exist_ok=True)
        shutil.copy2(src_cleanup, dst_cleanup)
        _make_executable(dst_cleanup)

    _write_text(os.path.join(tmpdir, "pythonrequirements.txt"), "\n")
    _write_text(
        os.path.join(tmpdir, "mainbot.py"),
        "import sys\n"
        "sys.exit(0)\n",
    )

    _write_text(
        os.path.join(tmpdir, "venv", "bin", "activate"),
        "# fake venv activate\n",
    )
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


def _run_case(case):
    with tempfile.TemporaryDirectory() as tmpdir:
        _prepare_startbot_sandbox(tmpdir)
        result = _run_startbot(tmpdir, case["args"])
        combined = f"{result['stdout']}\n{result['stderr']}"
        has_usage = "Usage: ./startbot.sh" in combined
        has_start_banner = "Starting Alert Bot..." in combined
        lock_exists = os.path.exists(os.path.join(tmpdir, "data", "systemlog.d", "startbot.lock"))

        expected_rc = case.get("expect_returncode")
        expect_nonzero = case.get("expect_nonzero", False)
        rc_ok = (result["returncode"] == expected_rc) if expected_rc is not None else (result["returncode"] != 0 if expect_nonzero else True)
        usage_ok = has_usage == case.get("expect_usage", False)
        start_ok = has_start_banner == case.get("expect_start_banner", False)
        lock_ok = lock_exists == case.get("expect_lock_file", False)
        timeout_ok = not result["timed_out"]

        expected_substring = case.get("expect_substring")
        substring_ok = True
        if expected_substring is not None:
            substring_ok = expected_substring in combined

        checks = {
            "rc_ok": rc_ok,
            "usage_ok": usage_ok,
            "start_ok": start_ok,
            "lock_ok": lock_ok,
            "timeout_ok": timeout_ok,
            "substring_ok": substring_ok,
        }

        return {
            "name": case["name"],
            "args": case["args"],
            "checks": checks,
            "result": {
                "returncode": result["returncode"],
                "timed_out": result["timed_out"],
                "stdout_tail": result["stdout"].strip().splitlines()[-8:],
                "stderr_tail": result["stderr"].strip().splitlines()[-8:],
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

        cases = [
            {
                "name": "help_long",
                "args": ["--help"],
                "expect_returncode": 0,
                "expect_usage": True,
                "expect_start_banner": False,
                "expect_lock_file": False,
            },
            {
                "name": "help_short",
                "args": ["-h"],
                "expect_returncode": 0,
                "expect_usage": True,
                "expect_start_banner": False,
                "expect_lock_file": False,
            },
            {
                "name": "clean_short",
                "args": ["-c"],
                "expect_returncode": 0,
                "expect_usage": False,
                "expect_start_banner": True,
                "expect_lock_file": True,
            },
            {
                "name": "new_short",
                "args": ["-n"],
                "expect_returncode": 0,
                "expect_usage": False,
                "expect_start_banner": True,
                "expect_lock_file": True,
            },
            {
                "name": "cluster_nc",
                "args": ["-nc"],
                "expect_returncode": 0,
                "expect_usage": False,
                "expect_start_banner": True,
                "expect_lock_file": True,
            },
            {
                "name": "cluster_cn",
                "args": ["-cn"],
                "expect_returncode": 0,
                "expect_usage": False,
                "expect_start_banner": True,
                "expect_lock_file": True,
            },
            {
                "name": "long_pair",
                "args": ["--clean", "--new"],
                "expect_returncode": 0,
                "expect_usage": False,
                "expect_start_banner": True,
                "expect_lock_file": True,
            },
            {
                "name": "unknown_long",
                "args": ["--unknown"],
                "expect_nonzero": True,
                "expect_usage": True,
                "expect_start_banner": False,
                "expect_lock_file": False,
                "expect_substring": "Unknown option:",
            },
            {
                "name": "unknown_short",
                "args": ["-x"],
                "expect_nonzero": True,
                "expect_usage": True,
                "expect_start_banner": False,
                "expect_lock_file": False,
                "expect_substring": "Unknown option:",
            },
            {
                "name": "unexpected_positional",
                "args": ["foo"],
                "expect_nonzero": True,
                "expect_usage": True,
                "expect_start_banner": False,
                "expect_lock_file": False,
                "expect_substring": "Unexpected positional argument:",
            },
        ]

        failed_cases = []
        for case in cases:
            outcome = _run_case(case)
            print_section("cli_case", outcome)
            if not all(outcome["checks"].values()):
                failed_cases.append({
                    "name": outcome["name"],
                    "checks": outcome["checks"],
                    "result": outcome["result"],
                })

        if failed_cases:
            _log_problem("startbot_cli_parse_checks_failed", {
                "failed_cases": failed_cases,
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    parse_ok = not dbg.has_problem("startbot_cli_parse_checks_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"parse: {'OK' if parse_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
