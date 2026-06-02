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
SCRIPT_TITLE = "notif_context_debug"
FEATURE_TITLE = "Notification Context Parsing"

from modules.shared.callback_codec import MAX_CALLBACK_BYTES


def _check_parse_alert_tail_shapes(dbg, parse_alert_callback_tail):
    ts_orig = "1717236000"
    ts_occ = "1717232400"

    no_count = parse_alert_callback_tail(f"foo_bar_{ts_orig}_{ts_occ}")
    with_count = parse_alert_callback_tail(f"foo_bar_{ts_orig}_{ts_occ}_4")

    checks = {
        "no_count_alert_id": no_count is not None and no_count.get("alert_id") == "foo_bar",
        "no_count_postpone_0": no_count is not None and no_count.get("postpone_count") == 0,
        "no_count_times_parsed": (
            no_count is not None
            and no_count.get("original_time") is not None
            and no_count.get("occurrence_time") is not None
        ),
        "with_count_alert_id": with_count is not None and with_count.get("alert_id") == "foo_bar",
        "with_count_postpone_4": with_count is not None and with_count.get("postpone_count") == 4,
        "with_count_times_parsed": (
            with_count is not None
            and with_count.get("original_time") is not None
            and with_count.get("occurrence_time") is not None
        ),
    }
    dbg.section("parse_alert_callback_tail", {"checks": checks, "no_count": no_count, "with_count": with_count})
    if not all(checks.values()):
        dbg.problem("parse_alert_callback_tail_failed", {"checks": checks})


def _check_postpone_and_notif_back_parsers(dbg, parse_postpone_data, parse_notif_back_data):
    ts_orig = "1717236000"
    ts_occ = "1717232400"
    alert_id = "a1b2c3d4"
    menu_payload = f"pp_menu_due_{alert_id}_{ts_orig}_{ts_occ}"
    set_payload = f"pp_set_1h_pre_{alert_id}_{ts_orig}_{ts_occ}_2"
    neg_payload = f"pp_custom_due_{alert_id}_{ts_orig}_{ts_occ}_-3"
    nback_payload = f"nback_pre_{alert_id}_{ts_orig}_{ts_occ}"

    menu = parse_postpone_data(menu_payload)
    set_data = parse_postpone_data(set_payload)
    neg_data = parse_postpone_data(neg_payload)
    nback = parse_notif_back_data(nback_payload)

    checks = {
        "menu_action": menu is not None and menu.get("action") == "menu",
        "menu_kind_due": menu is not None and menu.get("kind") == "due",
        "set_duration_1h": set_data is not None and set_data.get("duration") == "1h",
        "set_postpone_count_2": set_data is not None and set_data.get("postpone_count") == 2,
        "negative_postpone_count_clamped": neg_data is not None and neg_data.get("postpone_count") == 0,
        "notif_back_kind_pre": nback is not None and nback.get("kind") == "pre",
    }
    dbg.section(
        "postpone_and_notif_back_parsers",
        {"checks": checks, "menu": menu, "set_data": set_data, "neg_data": neg_data, "nback": nback},
    )
    if not all(checks.values()):
        dbg.problem("postpone_and_notif_back_parsers_failed", {"checks": checks})


def _check_notification_context_defaults(dbg, NotificationContext):
    null_ctx = NotificationContext.from_message(None, "test_id")
    empty_ctx = NotificationContext()
    checks = {
        "from_message_null_no_raise": isinstance(null_ctx, NotificationContext),
        "default_kind_due": empty_ctx.kind == "due",
        "default_detail_from_notification_false": empty_ctx.detail_from_notification is False,
        "default_detail_from_list_false": empty_ctx.detail_from_list is False,
        "default_include_back_false": empty_ctx.include_back is False,
        "default_original_time_none": empty_ctx.original_time is None,
        "default_occurrence_time_none": empty_ctx.occurrence_time is None,
        "default_postpone_count_0": empty_ctx.postpone_count == 0,
    }
    dbg.section(
        "notification_context_defaults",
        {"checks": checks, "null_ctx": vars(null_ctx), "empty_ctx": vars(empty_ctx)},
    )
    if not all(checks.values()):
        dbg.problem("notification_context_defaults_failed", {"checks": checks})


def _check_notification_callback_payload_sizes(
    dbg,
    build_postpone_callback,
    build_prealert_info_callback,
    build_alert_info_callback,
    build_notif_back_callback,
):
    alert_id = "a1b2c3d4"
    orig = datetime(2025, 6, 1, 10, 0, 0)
    occ = datetime(2025, 6, 1, 9, 0, 0)
    payloads = {
        "postpone_menu": build_postpone_callback("menu", "due", alert_id, orig, occ, postpone_count=3),
        "prealert_info": build_prealert_info_callback(alert_id, orig, occ, postpone_count=3),
        "alert_info": build_alert_info_callback(alert_id, orig, occ, postpone_count=3),
        "notif_back": build_notif_back_callback("due", alert_id, orig, occ, postpone_count=3),
    }
    checks = {name: len(payload.encode("utf-8")) <= MAX_CALLBACK_BYTES for name, payload in payloads.items()}
    dbg.section("notification_callback_payload_sizes", {"checks": checks, "payloads": payloads, "max": MAX_CALLBACK_BYTES})
    if not all(checks.values()):
        dbg.problem("notification_callback_payload_sizes_failed", {"checks": checks, "payloads": payloads})


def _check_import_surface_regression_guard(dbg, derive_detail_origin_context):
    derived = derive_detail_origin_context(None, "test_id")
    checks = {
        "returns_dict": isinstance(derived, dict),
        "has_kind": "kind" in derived,
        "has_notification_flag": "detail_from_notification" in derived,
        "has_list_flag": "detail_from_list" in derived,
        "has_include_back": "include_back" in derived,
        "has_original_time": "original_time" in derived,
        "has_occurrence_time": "occurrence_time" in derived,
        "has_postpone_count": "postpone_count" in derived,
    }
    dbg.section("import_surface_guard", {"checks": checks, "derived": derived})
    if not all(checks.values()):
        dbg.problem("import_surface_guard_failed", {"checks": checks, "derived": derived})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        try:
            from modules.handlers.notification_context import (
                NotificationContext,
                _derive_detail_origin_context,
                _parse_alert_callback_tail,
                _parse_notif_back_data,
                _parse_postpone_data,
            )
            from modules.ui.keyboards.callbacks import (
                build_alert_info_callback,
                build_notif_back_callback,
                build_postpone_callback,
                build_prealert_info_callback,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _check_parse_alert_tail_shapes(dbg, _parse_alert_callback_tail)
        _check_postpone_and_notif_back_parsers(dbg, _parse_postpone_data, _parse_notif_back_data)
        _check_notification_context_defaults(dbg, NotificationContext)
        _check_notification_callback_payload_sizes(
            dbg,
            build_postpone_callback,
            build_prealert_info_callback,
            build_alert_info_callback,
            build_notif_back_callback,
        )
        _check_import_surface_regression_guard(dbg, _derive_detail_origin_context)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    parse_ok = not dbg.has_problem("parse_alert_callback_tail_failed", "postpone_and_notif_back_parsers_failed")
    context_ok = not dbg.has_problem("notification_context_defaults_failed")
    payload_ok = not dbg.has_problem("notification_callback_payload_sizes_failed")
    import_surface_ok = not dbg.has_problem("import_surface_guard_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"parse: {'OK' if parse_ok else 'FAIL'}",
        f"context: {'OK' if context_ok else 'FAIL'}",
        f"payload: {'OK' if payload_ok else 'FAIL'}",
        f"import-surface: {'OK' if import_surface_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
