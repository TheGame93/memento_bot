#!/usr/bin/env python3
import json
import os
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
SCRIPT_TITLE = "startup_whitelist_prelock_debug"
FEATURE_TITLE = "Startup Whitelist Prelock"

_PROBE_CODE = r"""
import json
import os

import mainbot
from modules.security.whitelist_store import list_whitelist_users

admin_id = os.environ.get("TELEGRAM_USER_ID")
result = mainbot._prepare_startup_whitelist(
    admin_id,
    whitelist_path=mainbot.WHITELIST_PATH,
)

users = []
if os.path.exists(mainbot.WHITELIST_PATH):
    users = list_whitelist_users(path=mainbot.WHITELIST_PATH)

print(json.dumps({
    "result": result,
    "whitelist_path": mainbot.WHITELIST_PATH,
    "users": users,
}, default=str), flush=True)
"""


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _run_probe(*, data_dir, admin_id):
    env = os.environ.copy()
    env["BOT_DATA_DIR"] = data_dir
    env["TELEGRAM_USER_ID"] = str(admin_id)
    env.setdefault("TELEGRAM_BOT_TOKEN", "debug-token")
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE_CODE],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = None
    parse_error = None
    stdout = (proc.stdout or "").strip()
    if stdout:
        last_line = stdout.splitlines()[-1]
        try:
            payload = json.loads(last_line)
        except Exception as exc:
            parse_error = f"invalid_json:{exc}"
    else:
        parse_error = "missing_stdout"
    return {
        "returncode": proc.returncode,
        "stderr": (proc.stderr or "").strip()[-1000:],
        "stdout_tail": stdout[-1000:],
        "payload": payload,
        "parse_error": parse_error,
    }


def _assert_case(dbg, label, probe_result, checks):
    dbg.section(label, {
        "probe": probe_result,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("startup_whitelist_prelock_failed", {
            "case": label,
            "checks": checks,
            "probe": probe_result,
        })


def _test_prepare_startup_whitelist(dbg):
    with tempfile.TemporaryDirectory() as tmpdir:
        def data_dir(name):
            return os.path.join(tmpdir, name, "data")

        case_seed = _run_probe(
            data_dir=data_dir("seeded"),
            admin_id=12345,
        )
        seed_payload = case_seed.get("payload") or {}
        seed_result = seed_payload.get("result") or {}
        seed_users = seed_payload.get("users") or []
        _assert_case(dbg, "seeded_missing_everything", case_seed, {
            "returncode_ok": case_seed.get("returncode") == 0,
            "parse_ok": case_seed.get("parse_error") is None,
            "status_seeded": seed_result.get("status") == "seeded",
            "canonical_available": seed_result.get("canonical_available") is True,
            "admin_present": seed_result.get("admin_present_in_canonical") is True,
            "user_seeded": len(seed_users) == 1 and str(seed_users[0].get("id")) == "12345",
        })

        corrupt_canonical = os.path.join(data_dir("corrupt_canonical"), "system", "whitelist.json")
        os.makedirs(os.path.dirname(corrupt_canonical), exist_ok=True)
        with open(corrupt_canonical, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        case_corrupt = _run_probe(
            data_dir=data_dir("corrupt_canonical"),
            admin_id=12345,
        )
        corrupt_payload = case_corrupt.get("payload") or {}
        corrupt_result = corrupt_payload.get("result") or {}
        _assert_case(dbg, "corrupt_canonical", case_corrupt, {
            "returncode_ok": case_corrupt.get("returncode") == 0,
            "parse_ok": case_corrupt.get("parse_error") is None,
            "status_corrupt": corrupt_result.get("status") == "corrupt",
            "canonical_available_false": corrupt_result.get("canonical_available") is False,
            "admin_absent": corrupt_result.get("admin_present_in_canonical") is False,
            "event_name": corrupt_result.get("event_name") == "whitelist_seed_skipped_corrupt",
        })

        case_invalid = _run_probe(
            data_dir=data_dir("invalid_admin_missing_canonical"),
            admin_id="   ",
        )
        invalid_payload = case_invalid.get("payload") or {}
        invalid_result = invalid_payload.get("result") or {}
        invalid_whitelist_path = invalid_payload.get("whitelist_path")
        _assert_case(dbg, "invalid_admin_missing_canonical", case_invalid, {
            "returncode_ok": case_invalid.get("returncode") == 0,
            "parse_ok": case_invalid.get("parse_error") is None,
            "status_skipped": invalid_result.get("status") == "skipped",
            "reason_invalid_admin": (invalid_result.get("result") or {}).get("reason") == "invalid_admin_id",
            "canonical_available_false": invalid_result.get("canonical_available") is False,
            "admin_absent": invalid_result.get("admin_present_in_canonical") is False,
            "event_name": invalid_result.get("event_name") == "whitelist_seed_skipped_invalid_admin",
            "file_not_created": bool(invalid_whitelist_path) and not os.path.exists(invalid_whitelist_path),
        })

        fallback_dir = os.path.join(tmpdir, "fallback_active")
        fallback_canonical = os.path.join(fallback_dir, "data", "system", "whitelist.json")
        _write_json(fallback_canonical, {"users": [{"id": 555, "role": "admin"}]})
        case_fallback = _run_probe(
            data_dir=os.path.join(fallback_dir, "data"),
            admin_id=12345,
        )
        fallback_payload = case_fallback.get("payload") or {}
        fallback_result = fallback_payload.get("result") or {}
        _assert_case(dbg, "env_fallback_metadata", case_fallback, {
            "returncode_ok": case_fallback.get("returncode") == 0,
            "parse_ok": case_fallback.get("parse_error") is None,
            "status_exists": fallback_result.get("status") == "exists",
            "canonical_available": fallback_result.get("canonical_available") is True,
            "admin_absent": fallback_result.get("admin_present_in_canonical") is False,
        })


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        _test_prepare_startup_whitelist(dbg)
    except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
        dbg.mark_dependency_error(exc)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    feature_ok = not dbg.has_problem("startup_whitelist_prelock_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"prelock_startup: {'OK' if feature_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
