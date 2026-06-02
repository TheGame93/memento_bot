#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import sys
import time
import fnmatch
import re
from datetime import datetime
from datetime import timedelta

ARGS = sys.argv[1:]
VERBOSE = "--verbose" in ARGS
QUIET = "--quiet" in ARGS and not VERBOSE
STRICT_WARNINGS = "--allow-warn" not in ARGS
OFFLINE_ENV = os.getenv("MASTER_DEBUGGER_OFFLINE", "").strip().lower()
OFFLINE_MODE = "--offline" in ARGS or OFFLINE_ENV in {"1", "true", "yes", "on"}
SMOKE_DURATION_SECONDS = 5

LOG_FILE = None
LOG_PATH = None
PROBLEMS = []
SCRIPT_TITLE = "master_debugger"
FEATURE_TITLE = "Debug Suite"
SUMMARY_ITEMS = []
SCRIPT_TIMEOUT_SECONDS = 20
STALE_LOG_CLOCK_SKEW_SECONDS = 2.0
STDERR_ALLOWLIST_FILE = os.path.join("debuggers", "stderr_allowlist.json")
LOG_SUBDIR = "log"


def _write_log(line):
    if LOG_FILE:
        LOG_FILE.write(line + "\n")
        LOG_FILE.flush()


def _log_problem(message, payload=None):
    PROBLEMS.append(message)
    record = {"section": "problem", "message": message, "payload": payload or {}}
    _write_log(json.dumps(record, indent=2, default=str))


def _add_summary(sub_feature, status):
    SUMMARY_ITEMS.append((sub_feature, status))


def _print_compact_summary():
    if QUIET:
        return
    print(f"[{SCRIPT_TITLE}] {FEATURE_TITLE}")
    for sub_feature, status in SUMMARY_ITEMS:
        print(f"- {sub_feature}: {status}")


def print_section(label, payload):
    record = {"section": label, **payload}
    rendered = json.dumps(record, indent=2, default=str)
    _write_log(rendered)
    if VERBOSE:
        print(rendered)


def _find_scripts(tests_dir):
    scripts = []
    debuggers_root = os.path.join(tests_dir, "debuggers")
    if os.path.isdir(debuggers_root):
        for root, dirs, files in os.walk(debuggers_root):
            dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
            for name in files:
                if not name.endswith("_debug.py"):
                    continue
                if name.startswith("_"):
                    continue
                scripts.append(os.path.join(root, name))
        return sorted(scripts, key=lambda p: os.path.relpath(p, tests_dir))

    # Legacy fallback: old flat tests folder layout.
    for name in os.listdir(tests_dir):
        if not name.endswith("_debug.py"):
            continue
        if name == os.path.basename(__file__):
            continue
        scripts.append(os.path.join(tests_dir, name))
    return sorted(scripts)


def _load_stderr_allowlist(tests_dir):
    path = os.path.join(tests_dir, STDERR_ALLOWLIST_FILE)
    result = {
        "path": path,
        "rules": [],
        "errors": [],
    }

    if not os.path.exists(path):
        result["errors"].append("allowlist_file_missing")
        return result

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        result["errors"].append(f"allowlist_load_failed: {exc}")
        return result

    if not isinstance(payload, dict):
        result["errors"].append("allowlist_root_must_be_object")
        return result

    entries = payload.get("entries")
    if not isinstance(entries, list):
        result["errors"].append("allowlist_entries_must_be_list")
        return result

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            result["errors"].append(f"entry_{idx}_must_be_object")
            continue

        script_glob = entry.get("script_glob")
        pattern = entry.get("pattern")
        note = entry.get("note")

        if not isinstance(script_glob, str) or not script_glob.strip():
            result["errors"].append(f"entry_{idx}_invalid_script_glob")
            continue
        if not isinstance(pattern, str) or not pattern.strip():
            result["errors"].append(f"entry_{idx}_invalid_pattern")
            continue

        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            result["errors"].append(f"entry_{idx}_invalid_regex: {exc}")
            continue

        result["rules"].append({
            "id": idx,
            "script_glob": script_glob,
            "pattern": pattern,
            "note": note if isinstance(note, str) else "",
            "regex": compiled,
        })

    return result


def _classify_stderr(script, stderr_text, rules):
    lines = []
    for raw in (stderr_text or "").splitlines():
        line = raw.rstrip()
        if line.strip():
            lines.append(line)

    scoped_rules = [r for r in rules if fnmatch.fnmatch(script, r["script_glob"])]
    allowed = []
    unexpected = []

    for line in lines:
        matched_rule = None
        for rule in scoped_rules:
            if rule["regex"].search(line):
                matched_rule = rule
                break
        if matched_rule:
            allowed.append({
                "line": line,
                "rule_id": matched_rule["id"],
                "script_glob": matched_rule["script_glob"],
                "pattern": matched_rule["pattern"],
            })
        else:
            unexpected.append(line)

    return {
        "line_count": len(lines),
        "rule_count": len(scoped_rules),
        "allowed_count": len(allowed),
        "unexpected_count": len(unexpected),
        "allowed_sample": allowed[:5],
        "unexpected_sample": unexpected[:8],
    }


def _read_log_content(log_path):
    if not os.path.exists(log_path):
        return None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, UnicodeError):
        return None


def _tests_log_dir(tests_dir):
    path = os.path.join(tests_dir, LOG_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def _debugger_log_path(tests_dir, script_path):
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    return os.path.join(_tests_log_dir(tests_dir), f"{script_name}.log")


def _script_name_collisions(tests_dir, scripts):
    name_to_scripts = {}
    for script_path in scripts:
        script_name = os.path.splitext(os.path.basename(script_path))[0]
        name_to_scripts.setdefault(script_name, []).append(os.path.relpath(script_path, tests_dir))
    return {name: paths for name, paths in name_to_scripts.items() if len(paths) > 1}


def _log_has_problems(content):
    if content is None:
        return None
    return (
        '"section": "problem"' in content
        or '"section": "dependency_error"' in content
    )


def _log_has_run_meta(content):
    if content is None:
        return None
    return '"section": "run_meta"' in content


def _pick_python(root_dir):
    venv_python = os.path.join(root_dir, "venv", "bin", "python")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


def _parse_iso(ts):
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


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


def _is_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stop_bot_processes(project_root):
    pids = _find_bot_pids(project_root)
    if not pids:
        return {"found": 0, "stopped": 0, "killed": 0}

    stopped = 0
    killed = 0

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    deadline = time.time() + 3
    while time.time() < deadline:
        alive = [pid for pid in pids if _is_running(pid)]
        if not alive:
            break
        time.sleep(0.2)

    for pid in pids:
        if _is_running(pid):
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except OSError:
                pass
        else:
            stopped += 1

    return {"found": len(pids), "stopped": stopped, "killed": killed}


def _terminate_proc_tree(proc):
    if proc.poll() is not None:
        return

    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass

    try:
        proc.wait(timeout=3)
        return
    except Exception:
        pass

    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_startbot_smoke(root_dir, tests_dir, duration_seconds=SMOKE_DURATION_SECONDS):
    smoke_log_path = os.path.join(_tests_log_dir(tests_dir), "startbot_smoke.log")
    env = os.environ.copy()
    env["STARTBOT_SKIP_DEPS"] = "1"
    env["STARTBOT_DNS_WAIT_SECONDS"] = "1"
    env["STARTBOT_DNS_WAIT_INTERVAL"] = "1"
    lock_conflict_marker = "another startbot.sh instance is already running"

    def _run_once():
        start_time = datetime.now()
        proc = subprocess.Popen(
            ["bash", "./startbot.sh"],
            cwd=root_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
            env=env,
        )

        time.sleep(max(1, duration_seconds))
        _terminate_proc_tree(proc)

        try:
            output, _ = proc.communicate(timeout=5)
        except Exception:
            output = ""

        end_time = datetime.now()
        return {
            "start": start_time,
            "end": end_time,
            "duration_seconds": duration_seconds,
            "returncode": proc.returncode,
            "output_len": len(output or ""),
            "output_path": smoke_log_path,
            "saw_start_banner": "Starting Alert Bot..." in (output or ""),
            "output": output or "",
        }

    result = _run_once()
    first_output_lower = (result.get("output") or "").lower()
    retry_attempted = False
    lock_conflict_detected = False
    if lock_conflict_marker in first_output_lower:
        retry_attempted = True
        _stop_bot_processes(root_dir)
        time.sleep(0.5)
        result = _run_once()
        second_output_lower = (result.get("output") or "").lower()
        lock_conflict_detected = lock_conflict_marker in second_output_lower

    try:
        with open(smoke_log_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(result.get("output") or "")
    except OSError:
        pass

    result["retry_attempted"] = retry_attempted
    result["lock_conflict_detected"] = lock_conflict_detected

    return result


def _read_json_log(path, start, end):
    rows = []
    if not os.path.exists(path):
        return rows

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = _parse_iso(entry.get("ts"))
            if ts is None:
                continue
            if ts < start or ts > end:
                continue
            rows.append(entry)
    return rows


def _review_start_logs(root_dir, start, end, grace_seconds=2):
    window_start = start - timedelta(seconds=grace_seconds)
    window_end = end + timedelta(seconds=grace_seconds)
    log_dir = os.path.join(root_dir, "data", "systemlog.d")
    lifecycle_log = os.path.join(log_dir, "lifecycle.log")
    errors_log = os.path.join(log_dir, "errors.log")

    lifecycle_entries = _read_json_log(lifecycle_log, window_start, window_end)
    error_entries = _read_json_log(errors_log, window_start, window_end)

    startup_events = [
        e for e in lifecycle_entries
        if e.get("event") in {"scheduler_initialized", "scheduler_started", "startup"}
    ]

    print_section("bot_start_log_review", {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "grace_seconds": grace_seconds,
        "lifecycle_events": len(lifecycle_entries),
        "startup_events": len(startup_events),
        "errors": len(error_entries),
    })

    if not startup_events:
        _log_problem("startup_events_missing", {
            "lifecycle_log": lifecycle_log,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        })

    if error_entries:
        _log_problem("startup_errors_detected", {
            "count": len(error_entries),
            "sample": [
                {
                    "event": e.get("event"),
                    "error": (e.get("payload") or {}).get("error"),
                    "type": (e.get("payload") or {}).get("type"),
                }
                for e in error_entries[:3]
            ]
        })

    return {
        "lifecycle_events": len(lifecycle_entries),
        "startup_events": len(startup_events),
        "errors": len(error_entries),
    }


def _classify_network_bootstrap_outcome(
    *,
    has_crash_output,
    has_network_markers,
    startup_log_ok,
    offline_mode,
    strict_warnings,
):
    """Classify startup-smoke bootstrap output into note/warn/fail actions and summary status."""
    if not has_crash_output:
        return {"action": "ok", "summary_status": "OK"}

    if not (has_network_markers and startup_log_ok):
        return {"action": "fail_output_issue", "summary_status": "FAIL"}

    if offline_mode:
        return {"action": "note_network", "summary_status": "OK"}

    if not strict_warnings:
        return {"action": "warn_network", "summary_status": "WARN", "severity": "WARNING"}

    return {"action": "fail_network", "summary_status": "FAIL"}


def main():
    tests_dir = os.path.dirname(__file__)
    root_dir = os.path.dirname(tests_dir)
    script_name = os.path.splitext(os.path.basename(__file__))[0]
    log_path = os.path.join(_tests_log_dir(tests_dir), f"{script_name}.log")
    python_exec = _pick_python(root_dir)

    global LOG_FILE, LOG_PATH
    LOG_PATH = log_path
    LOG_FILE = open(log_path, "w", encoding="utf-8", errors="replace")

    try:
        scripts = _find_scripts(tests_dir)
        collisions = _script_name_collisions(tests_dir, scripts)
        stderr_allowlist = _load_stderr_allowlist(tests_dir)
        allowlist_rules = stderr_allowlist["rules"]
        print_section("run_meta", {
            "run_time": datetime.now().isoformat(),
            "python": sys.version.split()[0],
            "python_for_scripts": python_exec,
            "tests_dir": tests_dir,
            "project_root": root_dir,
            "scripts": [os.path.relpath(s, tests_dir) for s in scripts],
            "log_file": log_path,
            "smoke_duration_seconds": SMOKE_DURATION_SECONDS,
            "script_timeout_seconds": SCRIPT_TIMEOUT_SECONDS,
            "strict_warnings": STRICT_WARNINGS,
            "offline_mode": OFFLINE_MODE,
            "stderr_allowlist_file": stderr_allowlist["path"],
            "stderr_allowlist_rule_count": len(allowlist_rules),
            "stderr_allowlist_error_count": len(stderr_allowlist["errors"]),
            "debug_log_dir": _tests_log_dir(tests_dir),
            "script_name_collision_count": len(collisions),
        })
        print_section("flags", {
            "strict_warnings": STRICT_WARNINGS,
            "offline_mode": OFFLINE_MODE,
            "smoke_duration_seconds": SMOKE_DURATION_SECONDS,
        })
        if not scripts:
            _log_problem("no_debug_scripts_found", {"tests_dir": tests_dir})
        if collisions:
            _log_problem("script_log_name_collision", {"collisions": collisions})
        if stderr_allowlist["errors"]:
            _log_problem("stderr_allowlist_invalid", {
                "path": stderr_allowlist["path"],
                "errors": stderr_allowlist["errors"],
            })

        # 1) Run all debug scripts
        for script_path in scripts:
            script = os.path.relpath(script_path, tests_dir)
            cmd = [python_exec, script_path, "--quiet"]
            script_name_only = os.path.splitext(os.path.basename(script_path))[0]
            if script_name_only in collisions:
                _add_summary(script, "FAIL")
                continue
            child_log = _debugger_log_path(tests_dir, script_path)
            run_start_wall = time.time()
            if os.path.exists(child_log):
                try:
                    os.remove(child_log)
                except OSError:
                    pass

            timed_out = False
            stderr_eval = None
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=SCRIPT_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                result = subprocess.CompletedProcess(
                    cmd,
                    returncode=124,
                    stdout=(exc.stdout or ""),
                    stderr=(exc.stderr or ""),
                )
            print_section("script_run", {
                "script": script,
                "script_path": script_path,
                "returncode": result.returncode,
                "stdout_len": len(result.stdout or ""),
                "stderr_len": len(result.stderr or ""),
                "timed_out": timed_out,
            })

            if result.returncode != 0:
                _log_problem("script_failed", {
                    "script": script,
                    "returncode": result.returncode,
                    "stderr": (result.stderr or "").strip(),
                })
            if timed_out:
                _log_problem("script_timeout", {
                    "script": script,
                    "timeout_seconds": SCRIPT_TIMEOUT_SECONDS,
                })
            if (result.stderr or "").strip():
                stderr_eval = _classify_stderr(script, result.stderr or "", allowlist_rules)
                print_section("script_stderr", {
                    "script": script,
                    **stderr_eval,
                })
                if stderr_eval["unexpected_count"] > 0:
                    _log_problem("script_unexpected_stderr", {
                        "script": script,
                        "unexpected_sample": stderr_eval["unexpected_sample"],
                        "allowlist_path": stderr_allowlist["path"],
                    })

            log_content = _read_log_content(child_log)
            has_problems = _log_has_problems(log_content)
            script_status = "OK"
            if has_problems is None:
                _log_problem("log_missing_or_unreadable", {
                    "script": script,
                    "log_path": child_log,
                })
                script_status = "FAIL"
            else:
                try:
                    mtime = os.path.getmtime(child_log)
                except OSError:
                    mtime = 0
                # Some filesystems expose coarse mtime resolution (e.g. whole seconds),
                # so allow a small skew to avoid false stale-log failures.
                if mtime + STALE_LOG_CLOCK_SKEW_SECONDS < run_start_wall:
                    _log_problem("log_stale_timestamp", {
                        "script": script,
                        "log_path": child_log,
                        "mtime": mtime,
                        "run_start_wall": run_start_wall,
                        "skew_seconds": STALE_LOG_CLOCK_SKEW_SECONDS,
                    })
                    script_status = "FAIL"

                has_run_meta = _log_has_run_meta(log_content)
                if not has_run_meta:
                    _log_problem("log_missing_run_meta", {
                        "script": script,
                        "log_path": child_log,
                    })
                    script_status = "FAIL"
                if has_problems:
                    _log_problem("script_reported_problems", {
                        "script": script,
                        "log_path": child_log,
                    })
                    script_status = "FAIL"

            if result.returncode != 0:
                script_status = "FAIL"
            if stderr_eval and stderr_eval["unexpected_count"] > 0:
                script_status = "FAIL"
            _add_summary(script, script_status)

        # 2) Stop any running bot instance started from this project
        stop_info = _stop_bot_processes(root_dir)
        print_section("bot_stop_before_smoke", stop_info)

        # 3) Start bot for 5 seconds and stop
        smoke = _run_startbot_smoke(root_dir, tests_dir, duration_seconds=SMOKE_DURATION_SECONDS)
        print_section("bot_smoke_run", {
            "start": smoke["start"].isoformat(),
            "end": smoke["end"].isoformat(),
            "duration_seconds": smoke["duration_seconds"],
            "returncode": smoke["returncode"],
            "output_len": smoke["output_len"],
            "output_path": smoke["output_path"],
            "saw_start_banner": smoke["saw_start_banner"],
            "retry_attempted": smoke.get("retry_attempted", False),
            "lock_conflict_detected": smoke.get("lock_conflict_detected", False),
        })
        smoke_lock_conflict = bool(smoke.get("lock_conflict_detected"))
        if smoke["saw_start_banner"]:
            _add_summary("startbot_smoke", "OK")
        elif smoke_lock_conflict:
            _add_summary("startbot_smoke", "WARN")
        else:
            _add_summary("startbot_smoke", "FAIL")

        # 4) Review startup behavior from logs + smoke output
        log_review = None
        if not smoke["saw_start_banner"]:
            if smoke_lock_conflict:
                print_section("startbot_smoke_warning", {
                    "kind": "lock_conflict",
                    "severity": "WARNING",
                    "output_path": smoke["output_path"],
                    "retry_attempted": smoke.get("retry_attempted", False),
                    "lock_conflict_detected": True,
                })
                _add_summary("startup_logs", "WARN")
            else:
                _log_problem("startbot_smoke_never_started_bot", {
                    "output_path": smoke["output_path"],
                })
                _add_summary("startup_logs", "FAIL")
        else:
            log_review = _review_start_logs(root_dir, smoke["start"], smoke["end"])
            _add_summary("startup_logs", "OK" if log_review["startup_events"] > 0 and log_review["errors"] == 0 else "FAIL")

        output_lower = (smoke.get("output") or "").lower()
        has_crash_output = "traceback" in output_lower or "bot crashed with exit code" in output_lower
        has_network_markers = any(marker in output_lower for marker in (
            "temporary failure in name resolution",
            "httpx.connecterror",
            "telegram.error.networkerror",
            "failed to establish a new connection",
        ))

        startup_log_ok = bool(log_review and log_review["startup_events"] > 0 and log_review["errors"] == 0)
        network_outcome = _classify_network_bootstrap_outcome(
            has_crash_output=has_crash_output,
            has_network_markers=has_network_markers,
            startup_log_ok=startup_log_ok,
            offline_mode=OFFLINE_MODE,
            strict_warnings=STRICT_WARNINGS,
        )
        if network_outcome["action"] == "warn_network":
            print_section("startbot_smoke_warning", {
                "kind": "network",
                "severity": network_outcome["severity"],
                "strict_warnings": STRICT_WARNINGS,
                "offline_mode": OFFLINE_MODE,
                "output_path": smoke["output_path"],
            })
        elif network_outcome["action"] == "note_network":
            print_section("startbot_smoke_note", {
                "kind": "network",
                "severity": "INFO",
                "strict_warnings": STRICT_WARNINGS,
                "offline_mode": OFFLINE_MODE,
                "output_path": smoke["output_path"],
                "note": "offline_run_network_noise_ignored",
            })
        elif network_outcome["action"] == "fail_network":
            _log_problem("startbot_smoke_network_issue", {
                "output_path": smoke["output_path"],
                "reason": "network/bootstrap noise detected during smoke run",
            })
        elif network_outcome["action"] == "fail_output_issue":
            _log_problem("startbot_smoke_output_issue", {
                "output_path": smoke["output_path"],
            })
        _add_summary("network_bootstrap", network_outcome["summary_status"])

        # 5) Final cleanup: ensure no smoke process left running
        stop_after = _stop_bot_processes(root_dir)
        print_section("bot_stop_after_smoke", stop_after)

    except Exception as exc:
        _log_problem("unhandled_exception", {"error": str(exc)})
    finally:
        if LOG_FILE:
            LOG_FILE.close()

    _add_summary("problems", "OK" if not PROBLEMS else "FAIL")
    _print_compact_summary()
    if PROBLEMS and not QUIET:
        print(f"- details: {len(PROBLEMS)} issue(s)")
        print(f"- logfile: {LOG_PATH}")
    if PROBLEMS:
        sys.exit(1)


if __name__ == "__main__":
    main()
