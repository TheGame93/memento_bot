#!/usr/bin/env python3
import os
import sys
from datetime import datetime


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
SCRIPT_TITLE = "prealert_info_debug"
FEATURE_TITLE = "Pre-alert Info Callback"

IMPORT_ERROR = None
try:
    from modules.scheduler_messagelogic import _build_prealert_info_callback
    from modules import constants as C
    from modules.handlers.scheduler_handlers import (
        _parse_alert_callback_with_prefix,
        _parse_notif_back_data,
        _parse_prealert_info_data,
    )
    from modules.scheduler_mathlogic import format_pre_alert_display
    from modules.ui.keyboards.callbacks import build_notif_back_callback
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _assert_ts_equal(a, b):
    if a is None or b is None:
        return False
    return int(a.timestamp()) == int(b.timestamp())


def _run_checks(dbg):
    base_alert_id = "alert123"
    orig = datetime(2026, 2, 21, 12, 0, 0)
    occ = datetime(2026, 2, 21, 13, 0, 0)

    cb_zero = _build_prealert_info_callback(base_alert_id, orig, occ, postpone_count=0)
    cb_three = _build_prealert_info_callback(base_alert_id, orig, occ, postpone_count=3)
    cb_negative = f"{cb_three.rsplit('_', 1)[0]}_-2"

    parsed_zero = _parse_prealert_info_data(cb_zero)
    parsed_three = _parse_prealert_info_data(cb_three)
    parsed_negative = _parse_prealert_info_data(cb_negative)

    checks = {
        "zero_no_suffix": not cb_zero.endswith("_0"),
        "three_has_suffix": cb_three.endswith("_3"),
        "parse_zero": isinstance(parsed_zero, dict) and parsed_zero.get("postpone_count") == 0,
        "parse_three": isinstance(parsed_three, dict) and parsed_three.get("postpone_count") == 3,
        "parse_negative_clamped": isinstance(parsed_negative, dict) and parsed_negative.get("postpone_count") == 0,
        "orig_ts_roundtrip": _assert_ts_equal(parsed_three.get("original_time"), orig) if parsed_three else False,
        "occ_ts_roundtrip": _assert_ts_equal(parsed_three.get("occurrence_time"), occ) if parsed_three else False,
    }

    dbg.section("callback_roundtrip", {
        "checks": checks,
        "cb_zero": cb_zero,
        "cb_three": cb_three,
        "cb_negative": cb_negative,
    })
    if not all(checks.values()):
        dbg.problem("prealert_info_roundtrip_failed", {"checks": checks})


def _run_notif_back_checks(dbg):
    base_alert_id = "alert123"
    orig = datetime(2026, 2, 21, 12, 0, 0)
    occ = datetime(2026, 2, 21, 13, 0, 0)

    cb_pre = build_notif_back_callback("pre", base_alert_id, orig, occ, postpone_count=0)
    cb_due = build_notif_back_callback("due", base_alert_id, orig, occ, postpone_count=4)
    cb_negative = f"{cb_due.rsplit('_', 1)[0]}_-1"

    parsed_pre = _parse_notif_back_data(cb_pre)
    parsed_due = _parse_notif_back_data(cb_due)
    parsed_negative = _parse_notif_back_data(cb_negative)

    checks = {
        "pre_prefix": cb_pre.startswith("nback_pre_"),
        "due_suffix_count": cb_due.endswith("_4"),
        "parse_pre_ok": isinstance(parsed_pre, dict) and parsed_pre.get("kind") == "pre",
        "parse_due_ok": isinstance(parsed_due, dict) and parsed_due.get("kind") == "due",
        "parse_negative_clamped": isinstance(parsed_negative, dict) and parsed_negative.get("postpone_count") == 0,
        "orig_ts_roundtrip": _assert_ts_equal(parsed_due.get("original_time"), orig) if parsed_due else False,
        "occ_ts_roundtrip": _assert_ts_equal(parsed_due.get("occurrence_time"), occ) if parsed_due else False,
    }

    dbg.section("notif_back_roundtrip", {
        "checks": checks,
        "cb_pre": cb_pre,
        "cb_due": cb_due,
        "cb_negative": cb_negative,
    })
    if not all(checks.values()):
        dbg.problem("notif_back_roundtrip_failed", {"checks": checks})


def _run_numeric_id_tail_parser_checks(dbg):
    alert_id = "legacy_123"
    orig = datetime(2026, 2, 21, 12, 0, 0)
    occ = datetime(2026, 2, 21, 13, 0, 0)

    preinfo_no_count = _build_prealert_info_callback(alert_id, orig, occ, postpone_count=0)
    preinfo_with_count = _build_prealert_info_callback(alert_id, orig, occ, postpone_count=7)
    parsed_preinfo_no_count = _parse_alert_callback_with_prefix(preinfo_no_count, C.CB_PREALERT_INFO)
    parsed_preinfo_with_count = _parse_alert_callback_with_prefix(preinfo_with_count, C.CB_PREALERT_INFO)

    nback_no_count = build_notif_back_callback("pre", alert_id, orig, occ, postpone_count=0)
    nback_with_count = build_notif_back_callback("due", alert_id, orig, occ, postpone_count=5)
    parsed_nback_no_count = _parse_notif_back_data(nback_no_count)
    parsed_nback_with_count = _parse_notif_back_data(nback_with_count)

    checks = {
        "preinfo_no_count_id_roundtrip": (
            isinstance(parsed_preinfo_no_count, dict)
            and parsed_preinfo_no_count.get("alert_id") == alert_id
            and parsed_preinfo_no_count.get("postpone_count") == 0
        ),
        "preinfo_no_count_orig_roundtrip": (
            _assert_ts_equal(parsed_preinfo_no_count.get("original_time"), orig)
            if parsed_preinfo_no_count else False
        ),
        "preinfo_no_count_occ_roundtrip": (
            _assert_ts_equal(parsed_preinfo_no_count.get("occurrence_time"), occ)
            if parsed_preinfo_no_count else False
        ),
        "preinfo_with_count_id_roundtrip": (
            isinstance(parsed_preinfo_with_count, dict)
            and parsed_preinfo_with_count.get("alert_id") == alert_id
            and parsed_preinfo_with_count.get("postpone_count") == 7
        ),
        "nback_no_count_id_roundtrip": (
            isinstance(parsed_nback_no_count, dict)
            and parsed_nback_no_count.get("alert_id") == alert_id
            and parsed_nback_no_count.get("kind") == "pre"
            and parsed_nback_no_count.get("postpone_count") == 0
        ),
        "nback_with_count_id_roundtrip": (
            isinstance(parsed_nback_with_count, dict)
            and parsed_nback_with_count.get("alert_id") == alert_id
            and parsed_nback_with_count.get("kind") == "due"
            and parsed_nback_with_count.get("postpone_count") == 5
        ),
        "nback_no_count_orig_roundtrip": (
            _assert_ts_equal(parsed_nback_no_count.get("original_time"), orig)
            if parsed_nback_no_count else False
        ),
        "nback_no_count_occ_roundtrip": (
            _assert_ts_equal(parsed_nback_no_count.get("occurrence_time"), occ)
            if parsed_nback_no_count else False
        ),
    }
    dbg.section("numeric_id_tail_parser", {
        "checks": checks,
        "preinfo_no_count": preinfo_no_count,
        "preinfo_with_count": preinfo_with_count,
        "nback_no_count": nback_no_count,
        "nback_with_count": nback_with_count,
    })
    if not all(checks.values()):
        dbg.problem("numeric_id_tail_parser_failed", {"checks": checks})


def _run_display_checks(dbg):
    due_dt = datetime(2026, 3, 10, 10, 0, 0)
    alert = {
        "id": "pre_display_01",
        "type": 5,
        "type_name": "Once",
        "schedule": {"date": "10/03/2026", "time": "10:00"},
        "pre_alerts": ["1h"],
    }
    resolved = format_pre_alert_display(alert, "1h", due_dt=due_dt, user_prefs={})

    unresolved_alert = {
        "id": "pre_display_02",
        "type": 99,
        "type_name": "Unknown",
        "schedule": {},
        "pre_alerts": ["1h"],
    }
    fallback = format_pre_alert_display(unresolved_alert, "1h", due_dt=None, user_prefs={})

    checks = {
        "resolved_contains_day_month": "10/03" in resolved,
        "resolved_contains_time": "09:00" in resolved,
        "fallback_is_human_label": fallback == "1 hour",
    }
    dbg.section("display_resolution", {
        "resolved": resolved,
        "fallback": fallback,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("prealert_info_display_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        _run_checks(dbg)
        _run_display_checks(dbg)
        _run_notif_back_checks(dbg)
        _run_numeric_id_tail_parser_checks(dbg)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    check_ok = not dbg.has_problem(
        "prealert_info_roundtrip_failed",
        "prealert_info_display_failed",
        "notif_back_roundtrip_failed",
        "numeric_id_tail_parser_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"roundtrip: {'OK' if check_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
