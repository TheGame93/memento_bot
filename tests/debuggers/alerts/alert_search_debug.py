#!/usr/bin/env python3
import os
import sys


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
SCRIPT_TITLE = "alert_search_debug"
FEATURE_TITLE = "Alert Search"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _coerce_int(value, fallback):
    try:
        return int(value), False
    except (TypeError, ValueError):
        return fallback, True


def _build_alert(title, constants, a_type=1):
    return {
        "id": title.lower().replace(" ", "_"),
        "title": title,
        "type": a_type,
        "type_name": "Birthday" if a_type == 6 else "Monthly (Specific Day)",
        "schedule": (
            {"days": [5], "interval": 1, "time": "10:00"}
            if a_type != 6
            else {"date": "10/10", "time": constants.BIRTHDAY_DEFAULT_TIME}
        ),
        "pre_alerts": [],
        "tags": [],
        "active": True,
    }


def _run_query(query, alerts, rank_alerts_by_name):
    q_norm, ranked = rank_alerts_by_name(query, alerts)
    best = ranked[0] if ranked else None
    return {
        "query": query,
        "normalized": q_norm,
        "best_title": best["alert"]["title"] if best else None,
        "best_score": best["score"] if best else 0,
        "top3": [
            {"title": item["alert"]["title"], "score": item["score"], "type": item["alert"].get("type")}
            for item in ranked[:3]
        ],
    }


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        suppress_ptb_user_warning()

        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        try:
            from modules import constants as C
            from modules.handlers.alerts import rank_alerts_by_name
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        min_score_raw = getattr(C, "ALERT_SEARCH_MIN_SCORE", 75)
        top_n_raw = getattr(C, "ALERT_SEARCH_TOP_N", 5)
        min_score, min_score_fallback = _coerce_int(min_score_raw, 75)
        top_n, top_n_fallback = _coerce_int(top_n_raw, 5)
        min_score = max(0, min(100, min_score))
        top_n = max(1, top_n)
        if min_score_fallback:
            dbg.problem("config_invalid_min_score", {"raw": min_score_raw, "effective": min_score})
        if top_n_fallback:
            dbg.problem("config_invalid_top_n", {"raw": top_n_raw, "effective": top_n})

        dbg.run_meta({
            "project_root": ROOT_DIR,
            "min_score_raw": min_score_raw,
            "min_score_effective": min_score,
            "top_n_raw": top_n_raw,
            "top_n_effective": top_n,
            "show_debug": getattr(C, "ALERT_SEARCH_SHOW_DEBUG", None),
        })

        alerts = [
            _build_alert("Dentist Followup", C, 1),
            _build_alert("Pay Electricity Bill", C, 5),
            _build_alert("Monthly Team Report", C, 2),
            _build_alert("Car Insurance Renewal", C, 4),
            _build_alert("Marco Rossi", C, 6),  # Must be ignored by alert search.
        ]
        queries = ["dentst", "electrcity bill", "team report", "insurence renewl"]
        query_results = [_run_query(query, alerts, rank_alerts_by_name) for query in queries]
        dbg.section("query_results", {"results": query_results})

        if any(item["type"] == 6 for result in query_results for item in result["top3"]):
            dbg.problem("birthday_filter_failed", {"results": query_results})

        expected_titles = [
            "Dentist Followup",
            "Pay Electricity Bill",
            "Monthly Team Report",
            "Car Insurance Renewal",
        ]
        threshold = max(70, min_score - 5)
        for idx, result in enumerate(query_results):
            expected = expected_titles[idx]
            if result["best_title"] != expected:
                dbg.problem("ranking_failed", {
                    "query": result["query"],
                    "best_title": result["best_title"],
                    "expected": expected,
                })
            if result["best_score"] < threshold:
                dbg.problem("tolerance_failed", {
                    "query": result["query"],
                    "best_score": result["best_score"],
                    "threshold": threshold,
                })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    filter_ok = not dbg.has_problem("birthday_filter_failed")
    ranking_ok = not dbg.has_problem("ranking_failed")
    tolerance_ok = not dbg.has_problem("tolerance_failed")
    config_ok = not dbg.has_problem("config_invalid_min_score", "config_invalid_top_n")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"filtering: {'OK' if filter_ok else 'FAIL'}",
        f"ranking: {'OK' if ranking_ok else 'FAIL'}",
        f"tolerance: {'OK' if tolerance_ok else 'FAIL'}",
        f"config: {'OK' if config_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
