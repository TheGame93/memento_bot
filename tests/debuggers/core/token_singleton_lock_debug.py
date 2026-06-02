#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import time


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
SCRIPT_TITLE = "token_singleton_lock_debug"
FEATURE_TITLE = "Token Global Singleton Lock"

_PROBE_CODE = (
    "import json, os, time\n"
    "import mainbot\n"
    "token = os.environ.get('LOCK_TOKEN', '')\n"
    "hold_seconds = float(os.environ.get('LOCK_HOLD_SECONDS', '0'))\n"
    "ok, meta = mainbot.acquire_single_instance_lock(token)\n"
    "print(json.dumps({'ok': bool(ok), 'meta': meta}, default=str), flush=True)\n"
    "if ok and hold_seconds > 0:\n"
    "    time.sleep(hold_seconds)\n"
    "mainbot.release_single_instance_lock()\n"
)


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _start_probe(*, token, data_dir, global_lock_dir, hold_seconds):
    env = os.environ.copy()
    env["BOT_DATA_DIR"] = data_dir
    env["BOT_GLOBAL_LOCK_DIR"] = global_lock_dir
    env["TELEGRAM_USER_ID"] = env.get("TELEGRAM_USER_ID", "1")
    env["LOCK_TOKEN"] = token
    env["LOCK_HOLD_SECONDS"] = str(hold_seconds)
    return subprocess.Popen(
        [sys.executable, "-c", _PROBE_CODE],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _read_probe_result(proc, timeout_seconds=8.0):
    deadline = time.monotonic() + timeout_seconds
    line = ""
    while time.monotonic() < deadline:
        line = (proc.stdout.readline() if proc.stdout else "").strip()
        if line:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)

    if not line:
        stderr = ""
        if proc.stderr:
            try:
                stderr = proc.stderr.read()
            except Exception:
                stderr = ""
        return {
            "ok": None,
            "meta": None,
            "parse_error": "missing_probe_output",
            "stderr": stderr.strip()[-500:],
            "returncode": proc.poll(),
        }

    try:
        payload = json.loads(line)
    except Exception as exc:
        return {
            "ok": None,
            "meta": None,
            "parse_error": f"invalid_json:{exc}",
            "raw_line": line[-500:],
            "returncode": proc.poll(),
        }

    return {
        "ok": payload.get("ok"),
        "meta": payload.get("meta") or {},
        "parse_error": None,
        "returncode": proc.poll(),
    }


def _terminate_probe(proc):
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=2)
        return
    except Exception:
        pass
    try:
        proc.kill()
        proc.wait(timeout=2)
    except Exception:
        pass


def _test_path_determinism(dbg):
    from modules.shared import paths

    token = "abc-token-123"
    path1 = paths.token_global_lock_path(token)
    path2 = paths.token_global_lock_path(token)
    token_hash = paths.token_lock_hash_prefix(token)
    checks = {
        "same_token_same_path": path1 == path2,
        "absolute_path": os.path.isabs(path1),
        "no_raw_token_in_path": token not in path1,
        "hash_prefix_in_basename": token_hash in os.path.basename(path1),
        "under_global_lock_dir": os.path.abspath(os.path.dirname(path1)) == os.path.abspath(paths.GLOBAL_LOCK_DIR),
    }
    dbg.section("path_determinism", {
        "path": path1,
        "token_hash_prefix": token_hash,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("token_lock_path_determinism_failed", {"checks": checks, "path": path1})


def _test_contention_behavior(dbg):
    with tempfile.TemporaryDirectory() as tmpdir:
        global_lock_dir = os.path.join(tmpdir, "global_locks")
        data_dir_a = os.path.join(tmpdir, "inst_a_data")
        data_dir_b = os.path.join(tmpdir, "inst_b_data")
        data_dir_c = os.path.join(tmpdir, "inst_c_data")
        os.makedirs(global_lock_dir, exist_ok=True)
        os.makedirs(data_dir_a, exist_ok=True)
        os.makedirs(data_dir_b, exist_ok=True)
        os.makedirs(data_dir_c, exist_ok=True)

        token_a = "token-A"
        token_b = "token-B"

        probe_a = _start_probe(
            token=token_a,
            data_dir=data_dir_a,
            global_lock_dir=global_lock_dir,
            hold_seconds=3,
        )
        probe_b = None
        probe_c = None
        probe_d = None
        try:
            result_a = _read_probe_result(probe_a)
            expected_lock = os.path.join(global_lock_dir, f"mainbot_{result_a.get('meta', {}).get('token_hash_prefix')}.lock")

            probe_b = _start_probe(
                token=token_a,
                data_dir=data_dir_b,
                global_lock_dir=global_lock_dir,
                hold_seconds=0,
            )
            result_b = _read_probe_result(probe_b)
            try:
                probe_b.wait(timeout=4)
            except Exception:
                pass

            probe_c = _start_probe(
                token=token_b,
                data_dir=data_dir_c,
                global_lock_dir=global_lock_dir,
                hold_seconds=0,
            )
            result_c = _read_probe_result(probe_c)
            try:
                probe_c.wait(timeout=4)
            except Exception:
                pass

            try:
                probe_a.wait(timeout=6)
            except Exception:
                pass

            probe_d = _start_probe(
                token=token_a,
                data_dir=data_dir_b,
                global_lock_dir=global_lock_dir,
                hold_seconds=0,
            )
            result_d = _read_probe_result(probe_d)
            try:
                probe_d.wait(timeout=4)
            except Exception:
                pass

            checks = {
                "first_instance_acquires": result_a.get("ok") is True,
                "second_same_token_blocked": result_b.get("ok") is False,
                "blocked_scope_is_token_global": (result_b.get("meta") or {}).get("scope") == "token_global",
                "blocked_lock_file_matches_expected": (result_b.get("meta") or {}).get("lock_file") == expected_lock,
                "different_token_allowed": result_c.get("ok") is True,
                "same_token_acquires_after_release": result_d.get("ok") is True,
            }
            dbg.section("contention_behavior", {
                "checks": checks,
                "result_a": result_a,
                "result_b": result_b,
                "result_c": result_c,
                "result_d": result_d,
            })
            if not all(checks.values()):
                dbg.problem("token_lock_contention_failed", {
                    "checks": checks,
                    "result_a": result_a,
                    "result_b": result_b,
                    "result_c": result_c,
                    "result_d": result_d,
                })
        finally:
            _terminate_probe(probe_a)
            _terminate_probe(probe_b)
            _terminate_probe(probe_c)
            _terminate_probe(probe_d)


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR, "python_exec": sys.executable})

        _test_path_determinism(dbg)
        _test_contention_behavior(dbg)
    except ModuleNotFoundError as exc:
        dbg.mark_dependency_error(exc)
        dbg.finish(exit_on_problems=False)
        return
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    determinism_ok = not dbg.has_problem("token_lock_path_determinism_failed")
    contention_ok = not dbg.has_problem("token_lock_contention_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"path_determinism: {'OK' if determinism_ok else 'FAIL'}",
        f"contention: {'OK' if contention_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
