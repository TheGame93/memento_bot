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
SCRIPT_TITLE = "birthday_search_debug"
FEATURE_TITLE = "Birthday Search"


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


def _build_bday(title, constants, date_str="10/10", active=True, tags=None):
    return {
        "id": title.lower().replace(" ", "_"),
        "title": title,
        "type": 6,
        "type_name": "Birthday",
        "schedule": {"date": date_str, "time": constants.BIRTHDAY_DEFAULT_TIME},
        "pre_alerts": [],
        "tags": tags or [],
        "active": active,
    }


def _run_query(query, birthdays, rank_birthdays_by_name):
    q_norm, ranked = rank_birthdays_by_name(query, birthdays)
    best = ranked[0] if ranked else None
    return {
        "query": query,
        "normalized": q_norm,
        "best_title": best["alert"]["title"] if best else None,
        "best_score": best["score"] if best else 0,
        "top3": [{"title": item["alert"]["title"], "score": item["score"]} for item in ranked[:3]],
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
            from modules.handlers.birthdays import _normalize_search_text, rank_birthdays_by_name
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        min_score_raw = getattr(C, "BIRTHDAY_SEARCH_MIN_SCORE", 75)
        top_n_raw = getattr(C, "BIRTHDAY_SEARCH_TOP_N", 5)
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
            "show_debug": getattr(C, "BIRTHDAY_SEARCH_SHOW_DEBUG", None),
        })

        birthdays = [
            _build_bday("Marco Bianchi", C, "01/03", tags=["👨‍👩‍👧 Family"]),
            _build_bday("Giuseppe D'Angelo", C, "14/07"),
            _build_bday("Anna Maria Rossi", C, "22/11"),
            _build_bday("Luca Verdi", C, "05/09", active=False),
        ]

        norm_samples = {
            "Marco": _normalize_search_text("Marco"),
            "MATT E O": _normalize_search_text("MATT E O"),
            "D'Angelo": _normalize_search_text("D'Angelo"),
            "Ànna   Maria": _normalize_search_text("Ànna   Maria"),
        }
        dbg.section("normalization_samples", {"samples": norm_samples})
        if norm_samples["D'Angelo"] != "d angelo":
            dbg.problem("normalization_failed", {
                "sample": "D'Angelo",
                "normalized": norm_samples["D'Angelo"],
            })

        queries = ["Marko", "Marcoo", "Marci", "marco bianch", "anna rosi", "dangelo"]
        query_results = [_run_query(query, birthdays, rank_birthdays_by_name) for query in queries]
        dbg.section("query_results", {"results": query_results})

        threshold = max(70, min_score - 5)
        for item in query_results[:4]:
            if item["best_title"] != "Marco Bianchi" or item["best_score"] < threshold:
                dbg.problem("tolerance_failed", {
                    "query": item["query"],
                    "best_title": item["best_title"],
                    "best_score": item["best_score"],
                    "expected_title": "Marco Bianchi",
                    "threshold": threshold,
                })

        if query_results[4]["best_title"] != "Anna Maria Rossi":
            dbg.problem("ranking_failed", {
                "query": query_results[4]["query"],
                "best_title": query_results[4]["best_title"],
                "expected": "Anna Maria Rossi",
            })

        if query_results[5]["best_title"] != "Giuseppe D'Angelo":
            dbg.problem("ranking_failed", {
                "query": query_results[5]["query"],
                "best_title": query_results[5]["best_title"],
                "expected": "Giuseppe D'Angelo",
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    normalization_ok = not dbg.has_problem("normalization_failed")
    ranking_ok = not dbg.has_problem("ranking_failed")
    tolerance_ok = not dbg.has_problem("tolerance_failed")
    config_ok = not dbg.has_problem("config_invalid_min_score", "config_invalid_top_n")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"normalize: {'OK' if normalization_ok else 'FAIL'}",
        f"ranking: {'OK' if ranking_ok else 'FAIL'}",
        f"tolerance: {'OK' if tolerance_ok else 'FAIL'}",
        f"config: {'OK' if config_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
