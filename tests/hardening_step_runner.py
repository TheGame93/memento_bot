#!/usr/bin/env python3
import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime

SCRIPT_TITLE = "hardening_step_runner"
FEATURE_TITLE = "Hardening Validation Discipline"
KNOWN_SMOKE_WARNING = "startbot_smoke_network_issue"
LOG_DIR_NAME = "log"
MASTER_LOG_NAME = "master_debugger.log"

STEP_TARGET_DEBUGGERS = {
    "step1": [
        "tests/debuggers/core/api_wrapper_install_debug.py",
    ],
    "step2": [
        "tests/debuggers/core/api_wrapper_install_debug.py",
        "tests/debuggers/core/resilience_debug.py",
    ],
    "step3": [
        "tests/debuggers/core/startup_menu_failsoft_debug.py",
        "tests/debuggers/core/api_wrapper_install_debug.py",
        "tests/debuggers/core/commands_registry_debug.py",
    ],
    "step4": [
        "tests/debuggers/core/api_timeout_coverage_debug.py",
        "tests/debuggers/core/startup_menu_failsoft_debug.py",
        "tests/debuggers/core/api_wrapper_install_debug.py",
        "tests/debuggers/core/resilience_debug.py",
    ],
    "step5": [
        "tests/debuggers/core/api_timeout_coverage_debug.py",
        "tests/debuggers/core/startup_menu_failsoft_debug.py",
        "tests/debuggers/core/api_wrapper_install_debug.py",
        "tests/debuggers/core/resilience_debug.py",
    ],
}


def _find_root_dir(start_path):
    current = os.path.abspath(os.path.dirname(start_path))
    while True:
        if os.path.exists(os.path.join(current, "mainbot.py")) and os.path.isdir(os.path.join(current, "tests")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.path.join(os.path.dirname(start_path), ".."))
        current = parent


ROOT_DIR = _find_root_dir(__file__)
TESTS_DIR = os.path.join(ROOT_DIR, "tests")
LOG_DIR = os.path.join(TESTS_DIR, LOG_DIR_NAME)


def _pick_python(root_dir):
    venv_python = os.path.join(root_dir, "venv", "bin", "python3")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _json_log_write(handle, section, payload):
    record = {"section": section, **payload}
    handle.write(json.dumps(record, indent=2, default=str) + "\n")
    handle.flush()


def _run_command(cmd, cwd, timeout_seconds):
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout_len": len(result.stdout or ""),
        "stderr_len": len(result.stderr or ""),
        "stdout_tail": (result.stdout or "").splitlines()[-8:],
        "stderr_tail": (result.stderr or "").splitlines()[-8:],
    }


def _decode_json_objects(text):
    decoder = json.JSONDecoder()
    idx = 0
    size = len(text)
    items = []
    while idx < size:
        char = text[idx]
        if char not in "{[":
            idx += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        items.append(obj)
        idx = end
    return items


def _extract_master_problem_codes(master_log_path):
    if not os.path.exists(master_log_path):
        return []
    try:
        with open(master_log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []

    problems = []
    for item in _decode_json_objects(content):
        if isinstance(item, dict) and item.get("section") == "problem":
            message = item.get("message")
            if isinstance(message, str) and message:
                problems.append(message)
    return problems


def _write_step_report(step, payload):
    report_path = os.path.join(LOG_DIR, f"hardening_{step}_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
        f.write("\n")
    return report_path


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="Run hardening validation discipline checks.")
    parser.add_argument(
        "--step",
        default="step5",
        choices=sorted(STEP_TARGET_DEBUGGERS.keys()),
        help="Step identifier from docs/plan_hardening.md",
    )
    parser.add_argument("--quiet", action="store_true", help="Print only on problems.")
    parser.add_argument("--verbose", action="store_true", help="Print run details.")
    return parser.parse_args(argv)


def main():
    args = _parse_args(sys.argv[1:])
    if args.verbose:
        args.quiet = False

    _ensure_log_dir()
    log_path = os.path.join(LOG_DIR, f"{SCRIPT_TITLE}.log")
    python_bin = _pick_python(ROOT_DIR)
    problems = []

    with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
        _json_log_write(log_file, "run_meta", {
            "run_time": datetime.now().isoformat(),
            "script": SCRIPT_TITLE,
            "feature": FEATURE_TITLE,
            "step": args.step,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "python_bin": python_bin,
            "project_root": ROOT_DIR,
            "log_file": log_path,
        })

        targeted_results = []
        for script in STEP_TARGET_DEBUGGERS[args.step]:
            result = _run_command([python_bin, script, "--quiet"], cwd=ROOT_DIR, timeout_seconds=120)
            result["script"] = script
            targeted_results.append(result)
            _json_log_write(log_file, "targeted_debugger_run", result)
            if result["returncode"] != 0:
                problems.append(f"targeted_debugger_failed:{script}")

        strict_result = _run_command(
            [python_bin, "tests/master_debugger.py", "--quiet"],
            cwd=ROOT_DIR,
            timeout_seconds=300,
        )
        _json_log_write(log_file, "master_strict_run", strict_result)

        master_log_path = os.path.join(LOG_DIR, MASTER_LOG_NAME)
        strict_problem_codes = _extract_master_problem_codes(master_log_path)
        _json_log_write(log_file, "master_strict_problems", {
            "problem_codes": strict_problem_codes,
        })

        fallback_result = None
        fallback_needed = False
        strict_only_known_warning = (
            strict_result["returncode"] != 0
            and sorted(set(strict_problem_codes)) == [KNOWN_SMOKE_WARNING]
        )

        if strict_result["returncode"] == 0:
            pass
        elif strict_only_known_warning:
            fallback_needed = True
            fallback_result = _run_command(
                [python_bin, "tests/master_debugger.py", "--quiet", "--allow-warn"],
                cwd=ROOT_DIR,
                timeout_seconds=300,
            )
            _json_log_write(log_file, "master_fallback_run", fallback_result)
            if fallback_result["returncode"] != 0:
                problems.append("master_fallback_failed")
        else:
            problems.append("master_strict_unexpected_failure")

        report_payload = {
            "run_time": datetime.now().isoformat(),
            "step": args.step,
            "targeted_debuggers": [r["script"] for r in targeted_results],
            "targeted_results": targeted_results,
            "master_strict": strict_result,
            "master_strict_problem_codes": strict_problem_codes,
            "master_fallback_needed": fallback_needed,
            "master_fallback": fallback_result,
            "strict_only_known_warning": strict_only_known_warning,
            "known_smoke_warning": KNOWN_SMOKE_WARNING,
            "ok": len(problems) == 0,
            "problems": problems,
        }
        report_path = _write_step_report(args.step, report_payload)
        _json_log_write(log_file, "report_written", {"path": report_path})

        for code in problems:
            _json_log_write(log_file, "problem", {"message": code})

    if problems:
        print(f"[{SCRIPT_TITLE}] {FEATURE_TITLE}")
        print(f"- step: {args.step}")
        print(f"- status: FAIL")
        print(f"- problems: {', '.join(problems)}")
        print(f"- logfile: {log_path}")
        return 1

    if args.verbose and not args.quiet:
        print(f"[{SCRIPT_TITLE}] {FEATURE_TITLE}")
        print(f"- step: {args.step}")
        print("- status: OK")
        print(f"- logfile: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
