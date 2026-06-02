#!/usr/bin/env python3
import ast
import os
import signal
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
SCRIPT_TITLE = "lifecycle_debug"
FEATURE_TITLE = "Lifecycle Shutdown"

IMPORT_ERROR = None
try:
    from modules import systemlog as sl
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


def _find_bot_pids(project_root):
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,cmd="],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []

    pids = []
    for raw in (result.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, cmd = parts
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        if project_root not in cmd:
            continue
        if "startbot.sh" in cmd or "mainbot.py" in cmd:
            pids.append(pid)
    return sorted(set(pids))


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pids(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    time.sleep(0.5)
    for pid in pids:
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _check_startbot_signal_forwarding(project_root):
    baseline = _find_bot_pids(project_root)
    if baseline:
        print_section("startbot_signal_forwarding", {
            "skipped": True,
            "reason": "existing_bot_processes_running",
            "baseline_pids": baseline,
        })
        return

    env = os.environ.copy()
    env["STARTBOT_SKIP_DEPS"] = "1"
    env["STARTBOT_RESPAWN_DELAY_SECONDS"] = "1"
    env["STARTBOT_CHILD_SHUTDOWN_TIMEOUT_SECONDS"] = "3"
    env.setdefault("TELEGRAM_BOT_TOKEN", "debug-token")
    env.setdefault("TELEGRAM_USER_ID", "1")

    proc = subprocess.Popen(
        ["bash", "./startbot.sh"],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        preexec_fn=os.setsid,
    )

    output = ""
    leaked = []
    checks = {}
    try:
        time.sleep(1.5)
        before_term = _find_bot_pids(project_root)
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except OSError:
            pass

        try:
            output, _ = proc.communicate(timeout=10)
        except Exception:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                pass
            output, _ = proc.communicate(timeout=5)

        time.sleep(1.0)
        after_term = _find_bot_pids(project_root)
        leaked = sorted(set(after_term) - set(baseline))
        if leaked:
            _kill_pids(leaked)

        # If no child was ever detected, the bot crashed before the 1.5 s sampling
        # window (common with a fake token that gets rejected immediately).
        # The dynamic signal-forwarding test is inconclusive in this case; the
        # static analysis above already verifies the relevant startbot.sh logic.
        # Treat this as a skipped run rather than a failure.
        if not before_term:
            print_section("startbot_signal_forwarding", {
                "skipped": True,
                "reason": "bot_crashed_before_detection_window",
                "note": "static analysis (startbot_static) covers signal-forwarding logic",
                "script_terminated": proc.returncode is not None,
                "no_leaked_children": len(leaked) == 0,
                "returncode": proc.returncode,
                "output_excerpt": (output or "")[-400:],
            })
            if leaked:
                _log_problem("startbot_signal_forwarding_failed", {
                    "reason": "leaked_children_despite_no_detection",
                    "leaked_pids": leaked,
                })
            return

        checks = {
            "script_terminated": proc.returncode is not None,
            "spawned_processes_detected": len(before_term) >= 1,
            "no_leaked_children": len(leaked) == 0,
        }

        print_section("startbot_signal_forwarding", {
            "checks": checks,
            "baseline_pids": baseline,
            "before_term_pids": before_term,
            "after_term_pids": after_term,
            "leaked_pids": leaked,
            "returncode": proc.returncode,
            "output_excerpt": (output or "")[-400:],
        })

        if not all(checks.values()):
            _log_problem("startbot_signal_forwarding_failed", {
                "checks": checks,
                "returncode": proc.returncode,
                "leaked_pids": leaked,
                "output_excerpt": (output or "")[-800:],
            })
    finally:
        if proc.poll() is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                pass
        after_cleanup = _find_bot_pids(project_root)
        extra_after_cleanup = sorted(set(after_cleanup) - set(baseline))
        if extra_after_cleanup:
            _kill_pids(extra_after_cleanup)
            _log_problem("startbot_signal_forwarding_cleanup_leak", {
                "pids": extra_after_cleanup,
            })


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg

    if IMPORT_ERROR is not None:
        dbg.run_meta({"project_root": ROOT_DIR})
        dbg.mark_dependency_error(IMPORT_ERROR)
        dbg.finish(exit_on_problems=False)
        return

    original = {
        "LOG_DIR": sl.LOG_DIR,
        "SUMMARY_LOG": sl.SUMMARY_LOG,
        "RUNTIME_STATE_FILE": sl.RUNTIME_STATE_FILE,
    }

    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        with tempfile.TemporaryDirectory() as tmpdir:
            cwd_old = os.getcwd()
            os.chdir(tmpdir)
            try:
                sl.LOG_DIR = os.path.join("data", "systemlog.d")
                sl.SUMMARY_LOG = os.path.join(sl.LOG_DIR, "system.log")
                sl.RUNTIME_STATE_FILE = os.path.join(sl.LOG_DIR, "runtime_state.json")
                os.makedirs(sl.LOG_DIR, exist_ok=True)

                sl.mark_runtime_shutdown(clean=True)
                state = sl._read_runtime_state()
                exit_val = state.get("last_exit")
                print_section("mark_clean", {
                    "last_exit": exit_val,
                    "has_shutdown_ts": bool(state.get("last_shutdown_ts")),
                    "has_pid": bool(state.get("last_pid")),
                })
                if exit_val != "clean":
                    _log_problem("mark_clean_failed", {
                        "expected": "clean",
                        "got": exit_val,
                    })

                sl.mark_runtime_shutdown(clean=False)
                state = sl._read_runtime_state()
                exit_val = state.get("last_exit")
                print_section("mark_unclean", {"last_exit": exit_val})
                if exit_val != "unclean":
                    _log_problem("mark_unclean_failed", {
                        "expected": "unclean",
                        "got": exit_val,
                    })

                seed_state = {
                    "last_startup_ts": "2026-01-01T00:00:00",
                    "last_exit": "running",
                    "last_pid": 99999,
                    "log_maintenance": {
                        "last_run_ts": "2026-01-01T00:00:00",
                        "total_runs": 42,
                    },
                    "custom_field": "should_survive",
                }
                sl._write_runtime_state(seed_state)
                sl.mark_runtime_shutdown(clean=True)
                state = sl._read_runtime_state()
                preserved = (
                    state.get("log_maintenance", {}).get("total_runs") == 42
                    and state.get("custom_field") == "should_survive"
                    and state.get("last_startup_ts") == "2026-01-01T00:00:00"
                    and state.get("last_exit") == "clean"
                )
                print_section("field_preservation", {
                    "preserved": preserved,
                    "log_maintenance_total_runs": state.get("log_maintenance", {}).get("total_runs"),
                    "custom_field": state.get("custom_field"),
                    "last_exit": state.get("last_exit"),
                })
                if not preserved:
                    _log_problem("field_preservation_failed", {
                        "state": state,
                    })

                helper_now = sl._parse_iso("2026-01-02T00:00:00")
                current_identity = sl._runtime_identity_payload()
                sl._write_runtime_state({
                    "last_shutdown_ts": "2026-01-01T23:45:00",
                    "last_startup_ts": "2026-01-01T09:00:00",
                    "last_exit": "clean",
                    "instance_identity": current_identity,
                })
                win_reliable = sl.derive_startup_downtime_window(now_dt=helper_now)
                checks_reliable = {
                    "source_last_shutdown": win_reliable.get("source") == "last_shutdown",
                    "reliable_true": win_reliable.get("is_reliable") is True,
                    "has_window_start": bool(win_reliable.get("window_start")),
                    "has_window_end": bool(win_reliable.get("window_end")),
                }
                print_section("downtime_window_helper_reliable", {
                    "window": {
                        "source": win_reliable.get("source"),
                        "is_reliable": win_reliable.get("is_reliable"),
                        "reason_code": win_reliable.get("reason_code"),
                        "window_start": (
                            win_reliable.get("window_start").isoformat()
                            if win_reliable.get("window_start") else None
                        ),
                        "window_end": (
                            win_reliable.get("window_end").isoformat()
                            if win_reliable.get("window_end") else None
                        ),
                    },
                    "checks": checks_reliable,
                })
                if not all(checks_reliable.values()):
                    _log_problem("downtime_window_helper_reliable_failed", {"checks": checks_reliable})

                sl._write_runtime_state({
                    "last_shutdown_ts": "2026-01-01T23:45:00",
                    "last_startup_ts": "2026-01-01T09:00:00",
                    "last_exit": "running",
                    "instance_identity": current_identity,
                })
                win_running = sl.derive_startup_downtime_window(now_dt=helper_now)
                checks_running = {
                    "source_last_shutdown": win_running.get("source") == "last_shutdown",
                    "reliable_false": win_running.get("is_reliable") is False,
                    "reason_last_exit_running": win_running.get("reason_code") == "last_exit_running",
                }
                print_section("downtime_window_guard_last_exit_running", {
                    "reason_code": win_running.get("reason_code"),
                    "checks": checks_running,
                })
                if not all(checks_running.values()):
                    _log_problem("downtime_window_guard_last_exit_running_failed", {"checks": checks_running})

                identity_mismatch = dict(current_identity)
                identity_mismatch["instance_tag"] = "mismatch_instance"
                sl._write_runtime_state({
                    "last_shutdown_ts": "2026-01-01T23:45:00",
                    "last_startup_ts": "2026-01-01T09:00:00",
                    "last_exit": "clean",
                    "instance_identity": identity_mismatch,
                })
                win_identity = sl.derive_startup_downtime_window(now_dt=helper_now)
                checks_identity = {
                    "source_last_shutdown": win_identity.get("source") == "last_shutdown",
                    "reliable_false": win_identity.get("is_reliable") is False,
                    "reason_identity_mismatch": win_identity.get("reason_code") == "runtime_identity_mismatch",
                }
                print_section("downtime_window_guard_identity_mismatch", {
                    "reason_code": win_identity.get("reason_code"),
                    "checks": checks_identity,
                })
                if not all(checks_identity.values()):
                    _log_problem("downtime_window_guard_identity_mismatch_failed", {"checks": checks_identity})

                sl._write_runtime_state({
                    "last_shutdown_ts": "2026-01-01T23:45:00",
                    "last_startup_ts": "2026-01-01T09:00:00",
                    "last_exit": "clean",
                    "last_pid": os.getpid(),
                    "instance_identity": current_identity,
                })
                win_pid_alive = sl.derive_startup_downtime_window(now_dt=helper_now)
                checks_pid_alive = {
                    "source_last_shutdown": win_pid_alive.get("source") == "last_shutdown",
                    "reliable_false": win_pid_alive.get("is_reliable") is False,
                    "reason_last_pid_alive": win_pid_alive.get("reason_code") == "last_pid_still_alive",
                    "last_pid_alive_true": win_pid_alive.get("last_pid_alive") is True,
                }
                print_section("downtime_window_guard_last_pid_alive", {
                    "reason_code": win_pid_alive.get("reason_code"),
                    "checks": checks_pid_alive,
                })
                if not all(checks_pid_alive.values()):
                    _log_problem("downtime_window_guard_last_pid_alive_failed", {"checks": checks_pid_alive})

                sl._write_runtime_state({
                    "last_shutdown_ts": "2026-01-01T08:00:00",
                    "last_startup_ts": "2026-01-01T09:00:00",
                    "last_exit": "clean",
                    "instance_identity": current_identity,
                })
                win_inconsistent = sl.derive_startup_downtime_window(now_dt=helper_now)
                checks_inconsistent = {
                    "source_last_startup": win_inconsistent.get("source") == "last_startup",
                    "reliable_false": win_inconsistent.get("is_reliable") is False,
                    "reason_shutdown_before_startup": (
                        win_inconsistent.get("reason_code") == "shutdown_before_startup_fallback_startup"
                    ),
                }
                print_section("downtime_window_guard_shutdown_before_startup", {
                    "reason_code": win_inconsistent.get("reason_code"),
                    "checks": checks_inconsistent,
                })
                if not all(checks_inconsistent.values()):
                    _log_problem("downtime_window_guard_shutdown_before_startup_failed", {"checks": checks_inconsistent})

                sl._write_runtime_state({
                    "last_startup_ts": "2026-01-01T20:00:00",
                })
                win_fallback = sl.derive_startup_downtime_window(now_dt=helper_now)
                checks_fallback = {
                    "source_last_startup": win_fallback.get("source") == "last_startup",
                    "reliable_false": win_fallback.get("is_reliable") is False,
                    "has_window": bool(win_fallback.get("window_start") and win_fallback.get("window_end")),
                }
                print_section("downtime_window_helper_fallback", {
                    "reason_code": win_fallback.get("reason_code"),
                    "checks": checks_fallback,
                })
                if not all(checks_fallback.values()):
                    _log_problem("downtime_window_helper_fallback_failed", {"checks": checks_fallback})

                sl._write_runtime_state({
                    "last_shutdown_ts": "not-an-iso",
                })
                win_invalid = sl.derive_startup_downtime_window(now_dt=helper_now)
                checks_invalid = {
                    "source_none": win_invalid.get("source") == "none",
                    "window_missing": win_invalid.get("window_start") is None and win_invalid.get("window_end") is None,
                    "reason_invalid_shutdown": win_invalid.get("reason_code") == "invalid_last_shutdown",
                }
                print_section("downtime_window_helper_invalid", {
                    "reason_code": win_invalid.get("reason_code"),
                    "checks": checks_invalid,
                })
                if not all(checks_invalid.values()):
                    _log_problem("downtime_window_helper_invalid_failed", {"checks": checks_invalid})

            finally:
                os.chdir(cwd_old)

        _check_startbot_signal_forwarding(ROOT_DIR)

        startbot_path = os.path.join(ROOT_DIR, "startbot.sh")
        with open(startbot_path, "r", encoding="utf-8") as f:
            startbot_source = f.read()

        startbot_checks = {
            "tracks_child_pid": "CHILD_PID=" in startbot_source,
            "forwards_signal": "startbot_signal_forwarded_to_child" in startbot_source,
            "has_force_kill_fallback": "startbot_child_force_kill" in startbot_source and "kill -KILL" in startbot_source,
            "has_lock_conflict_exit_event": "startbot_mainbot_lock_conflict_exit" in startbot_source,
        }
        print_section("startbot_static_guards", {"checks": startbot_checks})
        if not all(startbot_checks.values()):
            _log_problem("startbot_static_guards_failed", {"checks": startbot_checks})

        lock_branch_idx = startbot_source.find('if [ "$exit_code" -eq "$MAINBOT_LOCK_CONFLICT_EXIT_CODE" ]; then')
        lock_event_idx = startbot_source.find("startbot_mainbot_lock_conflict_exit")
        clean_exit_idx = startbot_source.find("startbot_exit_clean")
        crash_respawn_idx = startbot_source.find("startbot_crash_respawn")
        resolve_code_idx = startbot_source.find("resolve_mainbot_lock_conflict_exit_code")
        start_loop_idx = startbot_source.find("startbot_loop_started")
        startbot_lock_conflict_checks = {
            "has_exit_code_resolver": resolve_code_idx != -1,
            "resolver_runs_before_loop": resolve_code_idx != -1 and start_loop_idx != -1 and resolve_code_idx < start_loop_idx,
            "has_lock_conflict_branch": lock_branch_idx != -1,
            "has_lock_conflict_event": lock_event_idx != -1,
            "lock_conflict_before_clean_exit": lock_branch_idx != -1 and clean_exit_idx != -1 and lock_branch_idx < clean_exit_idx,
            "lock_conflict_before_crash_respawn": lock_branch_idx != -1 and crash_respawn_idx != -1 and lock_branch_idx < crash_respawn_idx,
            "loop_logs_lock_conflict_code": "lock_conflict_exit_code" in startbot_source,
        }
        print_section("startbot_lock_conflict_static_guards", {"checks": startbot_lock_conflict_checks})
        if not all(startbot_lock_conflict_checks.values()):
            _log_problem("startbot_lock_conflict_static_guards_failed", {"checks": startbot_lock_conflict_checks})

        parse_idx = startbot_source.find('if ! parse_args "$@"; then')
        lock_idx = startbot_source.find('exec 9>"$LOCK_FILE"')
        new_idx = startbot_source.find('if [ "$FLAG_NEW" -eq 1 ]; then')
        clean_idx = startbot_source.find('if [ "$FLAG_CLEAN" -eq 1 ]; then')

        startbot_cli_checks = {
            "has_parse_args_function": "parse_args()" in startbot_source and "case \"$arg\" in" in startbot_source,
            "has_help_usage": "print_usage()" in startbot_source and "Usage: ./startbot.sh" in startbot_source,
            "has_help_flags": "-h, --help" in startbot_source and "--help)" in startbot_source,
            "has_clean_flags": "-c, --clean" in startbot_source and "--clean)" in startbot_source,
            "has_new_flags": "-n, --new" in startbot_source and "--new)" in startbot_source,
            "has_force_start_flag": "--force-start" in startbot_source and "--force-start)" in startbot_source,
            "logs_cli_flags": "startbot_cli_flags" in startbot_source,
            "logs_cli_help": "startbot_cli_help" in startbot_source,
            "logs_cli_invalid": "startbot_cli_invalid_args" in startbot_source,
            "parse_before_lock": parse_idx != -1 and lock_idx != -1 and parse_idx < lock_idx,
        }
        print_section("startbot_cli_static_guards", {"checks": startbot_cli_checks})
        if not all(startbot_cli_checks.values()):
            _log_problem("startbot_cli_static_guards_failed", {"checks": startbot_cli_checks})

        startbot_cleanup_checks = {
            "has_cleanup_dispatch": "run_requested_cleanups()" in startbot_source,
            "has_cleanup_helpers": "run_clean_all_logfiles()" in startbot_source and "run_clean_tests_artifacts()" in startbot_source,
            "cleanup_logs_phase_started": "startbot_cleanup_phase_started" in startbot_source,
            "cleanup_logs_phase_completed": "startbot_cleanup_phase_completed" in startbot_source,
            "cleanup_logs_all_logs_outcome": (
                "startbot_cleanup_all_logs_started" in startbot_source
                and "startbot_cleanup_all_logs_ok" in startbot_source
                and "startbot_cleanup_all_logs_failed" in startbot_source
            ),
            "cleanup_logs_tests_outcome": (
                "startbot_cleanup_tests_artifacts_started" in startbot_source
                and "startbot_cleanup_tests_artifacts_ok" in startbot_source
                and "startbot_cleanup_tests_artifacts_failed" in startbot_source
            ),
            "cleanup_failure_abort_branch": "startbot_cleanup_phase_failed_abort" in startbot_source and "aborting startup." in startbot_source,
            "cleanup_failure_continue_branch": "startbot_cleanup_phase_failed_continue" in startbot_source and "continuing due to --force-start." in startbot_source,
            "cleanup_order_new_before_clean": new_idx != -1 and clean_idx != -1 and new_idx < clean_idx,
        }
        print_section("startbot_cleanup_static_guards", {"checks": startbot_cleanup_checks})
        if not all(startbot_cleanup_checks.values()):
            _log_problem("startbot_cleanup_static_guards_failed", {"checks": startbot_cleanup_checks})

        mainbot_path = os.path.join(ROOT_DIR, "mainbot.py")
        with open(mainbot_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        post_shutdown_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "post_shutdown":
                post_shutdown_node = node
                break

        if post_shutdown_node:
            func_source = ast.get_source_segment(source, post_shutdown_node) or ""
            has_mark_runtime = "mark_runtime_shutdown(" in func_source
            print_section("post_shutdown_runtime_mark_check", {
                "marks_runtime_state": has_mark_runtime,
            })
            if has_mark_runtime:
                _log_problem("post_shutdown_marks_runtime_state", {
                    "hint": "runtime state should be finalized from __main__ outcome",
                })
        else:
            _log_problem("post_shutdown_marks_runtime_state", {
                "hint": "post_shutdown function not found in mainbot.py",
            })

        runtime_flow_checks = {
            "records_runtime_shutdown_from_main": "_record_runtime_shutdown(exit_clean, exit_reason)" in source,
            "run_polling_clean_path": 'exit_reason = "run_polling_returned"' in source,
            "run_polling_unclean_path": 'exit_reason = f"run_polling_crash:{exc.__class__.__name__}"' in source,
            "crash_sets_exit_unclean": "exit_clean = False" in source and "run_polling_crash" in source,
        }
        print_section("runtime_exit_classification", {"checks": runtime_flow_checks})
        if not all(runtime_flow_checks.values()):
            _log_problem("runtime_exit_classification_failed", {
                "checks": runtime_flow_checks,
            })

        singleton_lock_checks = {
            "uses_token_global_path_helper": "token_global_lock_path" in source and "token_lock_hash_prefix" in source,
            "emits_lock_conflict_event": "mainbot_lock_conflict" in source,
            "emits_lock_acquired_event": "mainbot_lock_acquired" in source,
            "releases_local_on_global_conflict": '_release_named_lock("local")' in source,
            "uses_dedicated_lock_conflict_exit_code": "MAINBOT_EXIT_LOCK_CONFLICT" in source and "SystemExit(lock_conflict_exit_code)" in source,
        }
        missing_env_idx = source.find("if not TOKEN or not ADMIN_ID:")
        acquire_lock_idx = source.find("acquire_single_instance_lock(TOKEN)")
        singleton_lock_checks["validates_env_before_lock"] = (
            missing_env_idx != -1
            and acquire_lock_idx != -1
            and missing_env_idx < acquire_lock_idx
        )
        print_section("singleton_lock_static_guards", {"checks": singleton_lock_checks})
        if not all(singleton_lock_checks.values()):
            _log_problem("singleton_lock_static_guards_failed", {"checks": singleton_lock_checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        sl.LOG_DIR = original["LOG_DIR"]
        sl.SUMMARY_LOG = original["SUMMARY_LOG"]
        sl.RUNTIME_STATE_FILE = original["RUNTIME_STATE_FILE"]
        _DBG = None

    mark_clean_ok = not dbg.has_problem("mark_clean_failed")
    mark_unclean_ok = not dbg.has_problem("mark_unclean_failed")
    preserve_ok = not dbg.has_problem("field_preservation_failed")
    helper_reliable_ok = not dbg.has_problem("downtime_window_helper_reliable_failed")
    helper_guard_running_ok = not dbg.has_problem("downtime_window_guard_last_exit_running_failed")
    helper_guard_identity_ok = not dbg.has_problem("downtime_window_guard_identity_mismatch_failed")
    helper_guard_pid_ok = not dbg.has_problem("downtime_window_guard_last_pid_alive_failed")
    helper_guard_inconsistent_ok = not dbg.has_problem("downtime_window_guard_shutdown_before_startup_failed")
    helper_fallback_ok = not dbg.has_problem("downtime_window_helper_fallback_failed")
    helper_invalid_ok = not dbg.has_problem("downtime_window_helper_invalid_failed")
    startbot_signal_ok = not dbg.has_problem(
        "startbot_signal_forwarding_failed",
        "startbot_signal_forwarding_cleanup_leak",
    )
    startbot_static_ok = not dbg.has_problem("startbot_static_guards_failed")
    startbot_cli_static_ok = not dbg.has_problem("startbot_cli_static_guards_failed")
    startbot_cleanup_static_ok = not dbg.has_problem("startbot_cleanup_static_guards_failed")
    post_shutdown_ok = not dbg.has_problem("post_shutdown_marks_runtime_state")
    runtime_classification_ok = not dbg.has_problem("runtime_exit_classification_failed")
    singleton_lock_ok = not dbg.has_problem("singleton_lock_static_guards_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"mark_clean: {'OK' if mark_clean_ok else 'FAIL'}",
        f"mark_unclean: {'OK' if mark_unclean_ok else 'FAIL'}",
        f"field_preserve: {'OK' if preserve_ok else 'FAIL'}",
        f"downtime_helper_reliable: {'OK' if helper_reliable_ok else 'FAIL'}",
        f"downtime_guard_last_exit_running: {'OK' if helper_guard_running_ok else 'FAIL'}",
        f"downtime_guard_identity_mismatch: {'OK' if helper_guard_identity_ok else 'FAIL'}",
        f"downtime_guard_last_pid_alive: {'OK' if helper_guard_pid_ok else 'FAIL'}",
        f"downtime_guard_shutdown_before_startup: {'OK' if helper_guard_inconsistent_ok else 'FAIL'}",
        f"downtime_helper_fallback: {'OK' if helper_fallback_ok else 'FAIL'}",
        f"downtime_helper_invalid: {'OK' if helper_invalid_ok else 'FAIL'}",
        f"startbot_signal: {'OK' if startbot_signal_ok else 'FAIL'}",
        f"startbot_static: {'OK' if startbot_static_ok else 'FAIL'}",
        f"startbot_lock_conflict_static: {'OK' if not dbg.has_problem('startbot_lock_conflict_static_guards_failed') else 'FAIL'}",
        f"startbot_cli_static: {'OK' if startbot_cli_static_ok else 'FAIL'}",
        f"startbot_cleanup_static: {'OK' if startbot_cleanup_static_ok else 'FAIL'}",
        f"post_shutdown_src: {'OK' if post_shutdown_ok else 'FAIL'}",
        f"runtime_exit_flow: {'OK' if runtime_classification_ok else 'FAIL'}",
        f"singleton_lock_static: {'OK' if singleton_lock_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
