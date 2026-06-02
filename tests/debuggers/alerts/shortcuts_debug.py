#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta


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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "shortcuts_debug"
FEATURE_TITLE = "Shortcuts+Pagination"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _dummy_alert(title, a_type=6, schedule=None):
    return {
        "id": title.lower().replace(" ", "_"),
        "title": title,
        "type": a_type,
        "type_name": "Birthday" if a_type == 6 else "One Time",
        "schedule": schedule or {"date": "10/10", "time": "10:00"},
        "created_at": datetime.now().isoformat(),
        "active": True,
        "pre_alerts": [],
        "tags": [],
    }


def _check_migration(dbg, storage, alerts_path, user_id):
    seed = {
        "tags": [],
        "alerts": [
            _dummy_alert("Mario Rossi", 6, {"date": "10/10", "time": "10:00"}),
            {**_dummy_alert("Martina Verdi", 6, {"date": "11/10", "time": "10:00"}), "shortcode": "bad"},
            {**_dummy_alert("Luca Bianchi", 5, {"date": "20/10/2030", "time": "10:00"}), "shortcode": "a00"},
            {**_dummy_alert("Anna Neri", 5, {"date": "21/10/2030", "time": "10:00"}), "shortcode": "a00"},
        ],
        "postpone_queue": [],
    }
    with open(alerts_path, "w", encoding="utf-8") as handle:
        json.dump(seed, handle, indent=2)

    migrated = storage.get_all_alerts(user_id)
    shortcodes = [alert.get("shortcode") for alert in migrated.get("alerts", [])]
    dbg.section("migration_shortcodes", {"shortcodes": shortcodes})

    if any(not shortcode for shortcode in shortcodes):
        dbg.problem("migration_missing_shortcode", {"shortcodes": shortcodes})
    if len(shortcodes) != len(set(shortcodes)):
        dbg.problem("migration_duplicate_shortcode", {"shortcodes": shortcodes})


def _check_allocator(dbg, storage, user_id):
    new_alert = {
        "title": "New Item",
        "type": 5,
        "type_name": "One Time",
        "schedule": {"date": "30/10/2030", "time": "10:00"},
        "pre_alerts": [],
        "tags": [],
    }
    new_id = storage.save_alert(user_id, new_alert)
    saved = storage.get_alert_by_id(user_id, new_id) if new_id else None
    dbg.section("save_shortcode", {
        "alert_id": new_id,
        "shortcode": saved.get("shortcode") if saved else None,
    })
    if not saved or not saved.get("shortcode"):
        dbg.problem("save_missing_shortcode", {"alert_id": new_id})

    data = storage.get_all_alerts(user_id)
    data.setdefault("shortcut_meta", {})
    data["shortcut_meta"]["next_seq"] = (52 * (62 ** 2)) - 1
    storage._write_user_data(user_id, data)  # noqa: SLF001 - intentional debug setup

    id_1 = storage.save_alert(user_id, {
        "title": "Edge One",
        "type": 5,
        "type_name": "One Time",
        "schedule": {"date": "01/11/2030", "time": "10:00"},
        "pre_alerts": [],
        "tags": [],
    })
    id_2 = storage.save_alert(user_id, {
        "title": "Edge Two",
        "type": 5,
        "type_name": "One Time",
        "schedule": {"date": "02/11/2030", "time": "10:00"},
        "pre_alerts": [],
        "tags": [],
    })
    a1 = storage.get_alert_by_id(user_id, id_1)
    a2 = storage.get_alert_by_id(user_id, id_2)
    dbg.section("allocator_boundary", {
        "first_shortcode": a1.get("shortcode") if a1 else None,
        "second_shortcode": a2.get("shortcode") if a2 else None,
        "first_len": len(a1.get("shortcode")) if a1 and a1.get("shortcode") else None,
        "second_len": len(a2.get("shortcode")) if a2 and a2.get("shortcode") else None,
    })
    if not a1 or not a2 or len(a2.get("shortcode", "")) < 4:
        dbg.problem("allocator_growth_failed", {
            "first": a1.get("shortcode") if a1 else None,
            "second": a2.get("shortcode") if a2 else None,
        })


def _check_list_alias_shape(dbg, build_compact_lines):
    now = datetime.now()
    page_items = []
    for idx in range(1, 21):
        page_items.append({
            "id": f"id{idx}",
            "title": f"Item {idx}",
            "type": 5,
            "type_name": "One Time",
            "active": True,
            "next_scheduled": (now + timedelta(days=idx)).isoformat(),
            "pre_alerts": ["1d"] if idx % 2 == 0 else [],
        })
    lines, alias_map = build_compact_lines(page_items, show_due_time=False)
    dbg.section("local_alias_format", {
        "first_line": lines[0] if lines else None,
        "last_line": lines[-1] if lines else None,
        "alias_keys_head": list(alias_map.keys())[:3],
        "alias_keys_tail": list(alias_map.keys())[-3:],
    })
    if "01" not in alias_map or "20" not in alias_map:
        dbg.problem("local_alias_shape_failed", {"alias_keys": list(alias_map.keys())})
    if lines and not lines[0].startswith("[/01] "):
        dbg.problem("local_alias_shape_failed", {"first_line": lines[0]})


def _check_compact_prealert_dates(dbg, build_compact_lines):
    due_dt = datetime.now() + timedelta(days=10, hours=9)
    page_items = [{
        "id": "precheck1",
        "title": "PreDateCheck",
        "type": 5,
        "type_name": "One Time",
        "active": True,
        "next_scheduled": due_dt.isoformat(),
        "pre_alerts": ["1h", "1d"],
        "tags": [],
    }]
    lines, _alias_map = build_compact_lines(page_items, show_due_time=False)
    detail_line = lines[1] if len(lines) > 1 else ""
    expected_first = (due_dt - timedelta(days=1)).strftime("%d %b").lower()
    expected_second = (due_dt - timedelta(hours=1)).strftime("%d %b").lower()
    if expected_first == expected_second:
        detail_dates_sorted = detail_line.count(expected_first) == 1
    else:
        detail_dates_sorted = (
            expected_first in detail_line
            and expected_second in detail_line
            and detail_line.index(expected_first) < detail_line.index(expected_second)
        )

    checks = {
        "detail_has_pre_marker": "🔔" in detail_line,
        "detail_has_first_date": expected_first in detail_line,
        "detail_has_second_date": expected_second in detail_line,
        "detail_dates_sorted": detail_dates_sorted,
    }
    dbg.section("compact_prealert_dates", {
        "detail_line": detail_line,
        "expected_first": expected_first,
        "expected_second": expected_second,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("compact_prealert_dates_failed", {"checks": checks, "detail_line": detail_line})


def _check_card_render(dbg, format_standard_card, format_detailed_card):
    now = datetime.now()
    detail_alert = {
        "id": "render1",
        "title": "Render Check",
        "type": 5,
        "type_name": "One Time",
        "active": True,
        "shortcode": "a0a",
        "tags": ["alpha", "beta"],
        "schedule": {"date": "12/12/2030", "time": "10:00"},
        "next_scheduled": (now + timedelta(days=2)).isoformat(),
        "created_at": now.isoformat(),
        "pre_alerts": ["1d"],
    }
    try:
        compact_card = format_standard_card(detail_alert)
        detailed_card = format_detailed_card(detail_alert)
        card_checks = {
            "compact_is_text": isinstance(compact_card, str) and len(compact_card) > 0,
            "detailed_is_text": isinstance(detailed_card, str) and len(detailed_card) > 0,
            "compact_has_tags": "🏷️" in compact_card,
            "detailed_has_tags": "🏷️" in detailed_card,
        }
        dbg.section("card_render_checks", {"checks": card_checks})
        if not all(card_checks.values()):
            dbg.problem("card_render_failed", {"checks": card_checks})
    except Exception as exc:
        dbg.problem("card_render_failed", {"error": str(exc)})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        suppress_ptb_user_warning()

        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.handlers.list_alerts import (
                _build_compact_lines,
                _format_detailed_card,
                _format_standard_card,
            )
            from modules.storage import StorageManager
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory(prefix="shortcuts_debug_") as tmp_root:
            storage = StorageManager(base_data_dir=tmp_root, admin_id="1")
            user_id = 1
            storage.setup_user_space(user_id)
            alerts_path = os.path.join(tmp_root, str(user_id), "alerts.json")

            _check_migration(dbg, storage, alerts_path, user_id)
            _check_allocator(dbg, storage, user_id)
            _check_list_alias_shape(dbg, _build_compact_lines)
            _check_compact_prealert_dates(dbg, _build_compact_lines)
            _check_card_render(dbg, _format_standard_card, _format_detailed_card)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    migration_ok = not dbg.has_problem("migration_missing_shortcode", "migration_duplicate_shortcode")
    allocator_ok = not dbg.has_problem("save_missing_shortcode", "allocator_growth_failed")
    alias_ok = not dbg.has_problem("local_alias_shape_failed", "compact_prealert_dates_failed")
    render_ok = not dbg.has_problem("card_render_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"migration: {'OK' if migration_ok else 'FAIL'}",
        f"allocator: {'OK' if allocator_ok else 'FAIL'}",
        f"local-alias: {'OK' if alias_ok else 'FAIL'}",
        f"card-render: {'OK' if render_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
